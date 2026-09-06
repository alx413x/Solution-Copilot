"""Run local app processes. Infrastructure is managed separately by Compose."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from dotenv import dotenv_values

os.chdir(Path(__file__).resolve().parents[1])
env = {**os.environ, **{k: v for k, v in dotenv_values(".env").items() if v is not None}}
commands = [
    [sys.executable, "-m", "uvicorn", "apps.api.main:app", "--host", "127.0.0.1", "--port", "8000"],
    [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "apps.worker.main:app",
        "worker",
        "--pool=solo",
        "--loglevel=INFO",
        "--hostname=solution-local@%h",
    ],
    ["pnpm", "dev"],
]
processes = []


def stop(*_):
    raise KeyboardInterrupt


signal.signal(signal.SIGTERM, stop)
try:
    for command in commands:
        processes.append(subprocess.Popen(command, env=env, start_new_session=True))
    while all(p.poll() is None for p in processes):
        time.sleep(0.5)
    raise SystemExit("An application process exited; stopping the remaining processes.")
except KeyboardInterrupt:
    pass
finally:
    for process in processes:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
    for process in processes:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
