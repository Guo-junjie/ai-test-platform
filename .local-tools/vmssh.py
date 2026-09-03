#!/usr/bin/env python3
"""VM SSH 助手：python vmssh.py "command"  — 在虚拟机上执行命令并打印输出。"""
import sys
import paramiko

HOST, USER, PASSWORD = "192.168.125.128", "gjj", "123456"


def run(cmd: str, timeout: int = 120) -> int:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=15)
    try:
        _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
        if out:
            print(out, end="" if out.endswith("\n") else "\n")
        if err:
            print("[stderr]", err, file=sys.stderr)
        return code
    finally:
        client.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "echo no command"
    tmo = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    sys.exit(run(cmd, tmo))
