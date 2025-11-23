# tests/ssh_xe_test.py
import paramiko, sys, os

HOST = "10.20.24.40"           # <=== change to one XCP-ng host IP reachable from controller
USER = "root"
PASSWORD = os.environ.get("DOM0_PW")  # safer: set DOM0_PW env var before running

if not PASSWORD:
    print("Set DOM0_PW environment variable to the Dom0 root password and re-run.")
    sys.exit(1)

def run_cmd(cmd):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(HOST, username=USER, password=PASSWORD, timeout=10)
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=20)
        out = stdout.read().decode(errors="ignore")
        err = stderr.read().decode(errors="ignore")
        rc = stdout.channel.recv_exit_status()
        return rc, out, err
    finally:
        ssh.close()

if __name__ == "__main__":
    rc, out, err = run_cmd("xe vm-list params=uuid,name-label,power-state --minimal")
    print("rc:", rc)
    print("stdout preview:\n", out[:2000])
    print("stderr preview:\n", err[:2000])
