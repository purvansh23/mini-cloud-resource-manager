# app/migration_service/utils.py
import shlex, subprocess

def ssh_run(host, user, cmd, timeout=60):
    """
    Run `cmd` on remote `host` via ssh. Returns (rc, stdout, stderr).
    Expects passwordless ssh (key-based) or ssh agent available.
    """
    ssh_cmd = ["ssh", "-o", "BatchMode=yes", f"{user}@{host}", cmd]
    try:
        proc = subprocess.run(ssh_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, text=True)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired as e:
        return 124, "", f"timeout: {str(e)}"
