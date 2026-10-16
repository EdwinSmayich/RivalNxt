"""The programs the work starts end with the app, however it ends."""
from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from pathlib import Path

import psutil
import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(sys.platform != "win32", reason="job objects are a Windows matter")
def test_a_program_started_for_the_work_ends_when_the_app_is_killed(tmp_path):
    parent = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(ROOT)!r})
        from core.voice_subtitles import processes
        child = processes.start([sys.executable, "-c", "import time; time.sleep(120)"])
        print("child", child.pid, flush=True)
        time.sleep(120)
    """)
    app = subprocess.Popen([sys.executable, "-c", parent], stdout=subprocess.PIPE, text=True)
    try:
        line = ""
        while not line.startswith("child "):  # importing core prints its settings first
            line = app.stdout.readline()
            assert line, "the stand-in app ended early"
        child_pid = int(line.split()[1])
        assert psutil.pid_exists(child_pid)
        app.kill()  # what Tauri does to the backend: no clean-up runs
        app.wait(timeout=10)
        end = time.time() + 10
        while psutil.pid_exists(child_pid) and time.time() < end:
            time.sleep(0.1)
        assert not psutil.pid_exists(child_pid)
    finally:
        if app.poll() is None:
            app.kill()
