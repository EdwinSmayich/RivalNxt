"""The programs the work starts end with the app.

On Windows a child process outlives its parent: an app closed in the middle of
a translation would leave llama-server running, holding gigabytes of the
graphics card's memory until the next restart. Every program started here is
put in a job object that Windows ends when the app's last handle to it closes,
which happens however the app exits -- closed, crashed or killed.
"""
from __future__ import annotations

import subprocess
import sys
import threading
from typing import List, Optional

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

_lock = threading.Lock()
_job: Optional[int] = None
_kernel32 = None
_tried = False


def _kill_on_exit_job() -> Optional[int]:
    """A job object whose processes end when this process does; None where there is none."""
    global _job, _kernel32, _tried
    with _lock:
        if _tried:
            return _job
        _tried = True
        if sys.platform != "win32":
            return None
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class Io(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = Extended()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info),
                                                ctypes.sizeof(info)):
            kernel32.CloseHandle(job)
            return None
        _job, _kernel32 = job, kernel32  # never closed: closing it is what ends the children
        return _job


def start(args: List[str], **kwargs) -> subprocess.Popen:
    """subprocess.Popen without a console window, ended with the app."""
    proc = subprocess.Popen(args, creationflags=NO_WINDOW, **kwargs)
    job = _kill_on_exit_job()
    if job and _kernel32 is not None:
        _kernel32.AssignProcessToJobObject(job, int(proc._handle))  # type: ignore[attr-defined]
    return proc
