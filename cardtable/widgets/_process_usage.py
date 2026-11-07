"""Sample application CPU time and resident memory using only the stdlib."""

from __future__ import annotations

import ctypes
import os
import struct
import sys
from pathlib import Path
from time import monotonic


def _read_process(pid: int) -> tuple[float, int]:
    """Return cumulative CPU seconds and current resident bytes."""
    if sys.platform == "darwin":
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        libproc.proc_pidinfo.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint64,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        info = ctypes.create_string_buffer(96)  # struct proc_taskinfo
        size = libproc.proc_pidinfo(pid, 4, 0, info, len(info))
        if size != len(info):
            raise OSError(ctypes.get_errno(), "proc_pidinfo failed")
        _, resident, user, system = struct.unpack_from("=QQQQ", info.raw)
        return (user + system) / 1e9, resident

    if sys.platform.startswith("linux"):
        # comm is parenthesized and may itself contain spaces or parentheses.
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        cpu = (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
        return cpu, int(fields[21]) * os.sysconf("SC_PAGE_SIZE")

    if sys.platform == "win32":
        from ctypes import wintypes

        class MemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                *[
                    (name, ctypes.c_size_t)
                    for name in (
                        "PeakWorkingSetSize",
                        "WorkingSetSize",
                        "QuotaPeakPagedPoolUsage",
                        "QuotaPagedPoolUsage",
                        "QuotaPeakNonPagedPoolUsage",
                        "QuotaNonPagedPoolUsage",
                        "PagefileUsage",
                        "PeakPagefileUsage",
                    )
                ],
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            *([ctypes.POINTER(ctypes.c_uint64)] * 4),
        ]
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(MemoryCounters),
            wintypes.DWORD,
        ]
        handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            times = [ctypes.c_uint64() for _ in range(4)]
            memory = MemoryCounters()
            memory.cb = ctypes.sizeof(memory)
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
                raise ctypes.WinError(ctypes.get_last_error())
            return (times[2].value + times[3].value) / 1e7, memory.WorkingSetSize
        finally:
            kernel.CloseHandle(handle)

    raise OSError(f"Unsupported platform: {sys.platform}")


class ProcessUsage:
    """Track the main application and UI process; one busy core means 100%."""

    def __init__(self) -> None:
        self._pids = {os.getpid(), os.getppid()}
        self._previous: dict[int, tuple[float, float]] = {}

    def sample(self) -> str:
        now = monotonic()
        cpu = 0.0
        resident = 0
        try:
            readings = {pid: _read_process(pid) for pid in self._pids}
        except (OSError, ValueError, IndexError):
            self._previous.clear()
            return "CPU:--%, Mem.:--GB"
        for pid, (seconds, memory) in readings.items():
            previous = self._previous.get(pid)
            if previous is not None and now > previous[0]:
                cpu += max(0.0, seconds - previous[1]) / (now - previous[0]) * 100
            self._previous[pid] = now, seconds
            resident += memory
        return f"CPU:{cpu:.0f}%, Mem.:{resident / 1_000_000_000:.2f}GB"
