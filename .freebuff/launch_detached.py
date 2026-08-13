#!/usr/bin/env python3
"""Detached launcher for preview servers.

Forks a child that calls setsid() (new session / process group) and execs the
given command, so the server survives the tooling shell that started it being
killed. Prints the child PID to stdout before exec — redirect stdout/stderr of
THIS script to the server's log file to capture both.

Usage:
    python3 launch_detached.py <command...>  > server.log 2>&1
"""
import os
import sys

if len(sys.argv) < 2:
    sys.exit("usage: launch_detached.py <command...>")

cmd = sys.argv[1:]

pid = os.fork()
if pid > 0:
    # Parent: report the child (server) PID and exit so the invoking shell
    # completes; the child is now reparented to init and in its own session.
    print(pid, flush=True)
    os._exit(0)

os.setsid()
os.execvp(cmd[0], cmd)
