"""End the calculation process when its owning service process disappears."""
import os
from threading import Thread
from time import sleep


def watch_parent():
    parent = os.environ.get("CITY_RUN_PARENT_PID")
    if parent is None:
        return
    identity = int(parent)
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, identity)  # SYNCHRONIZE
        if not handle:
            os._exit(74)

        def wait():
            kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
            kernel.CloseHandle(handle)
            os._exit(74)
    else:
        def wait():
            while os.getppid() == identity:
                sleep(0.1)
            os._exit(74)
    Thread(target=wait, name="run-parent-lifetime", daemon=True).start()
