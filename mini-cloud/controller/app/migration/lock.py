# app/migration/lock.py
import time
from typing import Optional
import redis

class RedisLock:
    """
    Simple redis-based advisory lock with blocking wait.
    Usage:
        with RedisLock("key", ttl=300, wait=10, sleep=0.1):
            # critical section
    """

    def __init__(self, key: str, ttl: int = 300, wait: int = 10, sleep: float = 0.1, redis_url: str = None):
        self.key = f"lock:{key}"
        self.ttl = ttl
        self.wait = wait
        self.sleep = sleep
        self._redis = None
        self._locked = False
        # lazy import of redis config from env if not provided
        self.redis_url = redis_url

    def _get_redis(self):
        if self._redis is None:
            import os
            url = self.redis_url or os.environ.get("REDIS_URL") or os.environ.get("REDIS", "redis://127.0.0.1:6379/0")
            self._redis = redis.from_url(url)
        return self._redis

    def acquire(self) -> bool:
        r = self._get_redis()
        deadline = time.time() + self.wait
        while time.time() < deadline:
            # setnx with expiry
            ok = r.set(self.key, "1", nx=True, ex=self.ttl)
            if ok:
                self._locked = True
                return True
            time.sleep(self.sleep)
        raise TimeoutError(f"failed to acquire lock {self.key} within {self.wait}s")

    def release(self):
        if self._locked:
            try:
                r = self._get_redis()
                r.delete(self.key)
            finally:
                self._locked = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False
