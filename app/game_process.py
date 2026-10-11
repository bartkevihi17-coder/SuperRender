"""Steam-like per-game stop: close the *game* window, never a shared launcher.

Only an explicit click can request a stop. First sends WM_CLOSE (same as
pressing the window's X). If the game does not exit, the UI MUST ask before a
verified process termination, which can lose unsaved game progress.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000
WM_CLOSE = 0x0010
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258


def _win_api():
    kernel = ctypes.windll.kernel32
    user = ctypes.windll.user32
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    )
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel.TerminateProcess.restype = wintypes.BOOL
    user.EnumWindows.argtypes = (ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
                                  wintypes.LPARAM)
    user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user.IsWindowVisible.argtypes = (wintypes.HWND,)
    user.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user.PostMessageW.restype = wintypes.BOOL
    return kernel, user


def _normal_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _verified_handle(pid: int, exe_path: str, access: int):
    """Opens only the requested PID after comparing its actual executable path."""
    if os.name != "nt" or pid <= 0 or not Path(exe_path).is_file():
        return None
    kernel, _user = _win_api()
    handle = kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | access, False, int(pid))
    if not handle:
        return None
    found = ctypes.create_unicode_buffer(32768)
    chars = wintypes.DWORD(len(found))
    if not kernel.QueryFullProcessImageNameW(handle, 0, found, ctypes.byref(chars)):
        kernel.CloseHandle(handle)
        return None
    if _normal_path(found.value) != _normal_path(exe_path):
        kernel.CloseHandle(handle)
        return None
    return handle


def is_exact_process_alive(pid: int, exe_path: str) -> bool:
    handle = _verified_handle(pid, exe_path, SYNCHRONIZE)
    if not handle:
        return False
    kernel, _user = _win_api()
    try:
        return kernel.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
    finally:
        kernel.CloseHandle(handle)


def stop_gracefully(pid: int, exe_path: str, timeout_seconds: float = 8.0) -> str:
    """Attempt normal window close; return 'needs_force' if still running."""
    handle = _verified_handle(pid, exe_path, SYNCHRONIZE)
    if not handle:
        return "not_found"
    kernel, user = _win_api()
    try:
        if kernel.WaitForSingleObject(handle, 0) == WAIT_OBJECT_0:
            return "closed"
        posted = [0]
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def on_window(hwnd, _lparam):
            owner_pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
            if int(owner_pid.value) != int(pid):
                return True
            if not user.IsWindowVisible(hwnd):
                return True
            if user.PostMessageW(hwnd, WM_CLOSE, 0, 0):
                posted[0] += 1
            return True

        callback = callback_type(on_window)
        user.EnumWindows(callback, 0)
        if posted[0] == 0:
            return "needs_force"
        wait_ms = max(0, min(15000, int(timeout_seconds * 1000)))
        status = kernel.WaitForSingleObject(handle, wait_ms)
        return "closed" if status == WAIT_OBJECT_0 else "needs_force"
    finally:
        kernel.CloseHandle(handle)


def force_terminate_verified(pid: int, exe_path: str) -> str:
    """Call only after explicit user confirmation about unsaved game progress."""
    handle = _verified_handle(pid, exe_path, PROCESS_TERMINATE | SYNCHRONIZE)
    if not handle:
        return "not_found"
    kernel, _user = _win_api()
    try:
        if kernel.WaitForSingleObject(handle, 0) == WAIT_OBJECT_0:
            return "closed"
        if not kernel.TerminateProcess(handle, 1):
            return "denied"
        return "closed" if kernel.WaitForSingleObject(handle, 3000) == WAIT_OBJECT_0 else "denied"
    finally:
        kernel.CloseHandle(handle)
