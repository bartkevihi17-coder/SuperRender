"""External Render Beta frame-generation backend.

The production path is deliberately non-injecting. SuperRender starts a small
native helper which captures only the selected game window with Windows
Graphics Capture, runs motion estimation/interpolation on our own D3D11 device,
and presents the synthesized cadence in a click-through overlay.

No DLL is loaded into the game and no anticheat/DRM bypass is attempted.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from .library import APP_DATA


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001


def runtime_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def bundled_framegen() -> Path | None:
    exe = runtime_root() / "third_party" / "SuperRenderFrameGen.exe"
    return exe if exe.is_file() else None


def _sha_file() -> Path:
    return runtime_root() / "third_party" / "SuperRenderFrameGen-SHA256.txt"


def verify_bundled_framegen() -> tuple[Path | None, str]:
    helper = bundled_framegen()
    if helper is None:
        return None, "Backend externo de Frame Generation nao esta incluido nesta compilacao."
    manifest = _sha_file()
    if not manifest.is_file():
        return None, "Manifesto SHA-256 do backend externo nao foi encontrado."
    try:
        expected = manifest.read_text(encoding="utf-8").strip().split()[0].lower()
        actual = hashlib.sha256(helper.read_bytes()).hexdigest().lower()
    except (OSError, IndexError):
        return None, "Nao foi possivel validar a integridade do backend externo."
    if len(expected) != 64 or actual != expected:
        return None, "Backend externo falhou na verificacao SHA-256."
    return helper, ""


def framegen_available_for_game(game: dict) -> bool:
    helper, _error = verify_bundled_framegen()
    exe = Path(str(game.get("exe") or ""))
    return os.name == "nt" and helper is not None and exe.is_file()


def generated_frame_count(base_fps: float | None, target_fps: int = 60) -> int:
    """Estimate how many presented ticks will be synthetic between real frames."""
    if base_fps is None or not math.isfinite(base_fps) or base_fps <= 1:
        return 1
    if base_fps >= target_fps * 0.95:
        return 0
    total = max(2, int(math.ceil(target_fps / base_fps)))
    return max(1, min(3, total - 1))


def _legacy_gpu(name: str) -> bool:
    text = (name or "").casefold()
    markers = (
        "geforce gt 4", "geforce gt 5", "geforce gt 6", "geforce gt 7",
        "radeon hd", "intel(r) hd graphics", "intel hd graphics",
        "uhd graphics 6", "vega 3",
    )
    return any(marker in text for marker in markers)


def telemetry_path(game: dict, pid: int) -> Path:
    ident = hashlib.sha256(
        str(game.get("id") or game.get("exe") or pid).encode("utf-8")
    ).hexdigest()[:16]
    return APP_DATA / "framegen" / f"{ident}-{int(pid)}.json"


def read_framegen_telemetry(path: str | Path) -> dict | None:
    try:
        p = Path(path)
        if not p.is_file():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def start_frame_generation(game: dict, pid: int, base_fps: float | None,
                           gpu_name: str, target_fps: int = 60) -> dict:
    """Start the external WGC/D3D11 helper for the exact tracked game PID."""
    helper, error = verify_bundled_framegen()
    if helper is None:
        raise RuntimeError(error)
    exe = Path(str(game.get("exe") or ""))
    if not exe.is_file():
        raise RuntimeError("Executavel real do jogo nao foi identificado.")

    legacy = _legacy_gpu(gpu_name)
    block_size = 32 if legacy else 16
    search_radius = 4 if legacy else 8
    target_fps = max(30, min(240, int(target_fps)))
    telemetry = telemetry_path(game, pid)
    telemetry.parent.mkdir(parents=True, exist_ok=True)
    telemetry.unlink(missing_ok=True)

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    args = [
        str(helper),
        "--pid", str(int(pid)),
        "--owner-pid", str(os.getpid()),
        "--target-fps", str(target_fps),
        "--block-size", str(block_size),
        "--search-radius", str(search_radius),
        "--telemetry", str(telemetry),
    ]
    try:
        process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            cwd=str(helper.parent),
        )
    except OSError as exc:
        raise RuntimeError("Nao foi possivel iniciar o backend externo: " + str(exc)) from exc

    # Fail fast on initialization errors, but do not add a long startup delay.
    deadline = time.monotonic() + 3.0
    status = None
    while time.monotonic() < deadline:
        code = process.poll()
        status = read_framegen_telemetry(telemetry)
        if status and status.get("status") in ("starting", "active"):
            break
        if status and status.get("status") == "error":
            raise RuntimeError(str(status.get("message") or "Backend externo recusou a captura."))
        if code is not None:
            raise RuntimeError(f"Backend externo encerrou durante a inicializacao (codigo {code}).")
        time.sleep(0.08)

    return {
        "message": "Frame Generation externo iniciado sem injecao no jogo.",
        "helper_pid": int(process.pid),
        "telemetry": str(telemetry),
        "base_fps": base_fps,
        "generated_between": generated_frame_count(base_fps, target_fps),
        "target_fps": target_fps,
        "block_size": block_size,
        "search_radius": search_radius,
    }


def _process_path(handle) -> str:
    kernel = ctypes.windll.kernel32
    buffer = ctypes.create_unicode_buffer(32768)
    size = wintypes.DWORD(len(buffer))
    kernel.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    )
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
        return buffer.value
    return ""


def stop_frame_generation(helper_pid: int) -> bool:
    """Terminate only our verified external helper process."""
    if os.name != "nt" or not helper_pid:
        return False
    helper = bundled_framegen()
    if helper is None:
        return False
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    access = PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE
    handle = kernel.OpenProcess(access, False, int(helper_pid))
    if not handle:
        return False
    try:
        actual = _process_path(handle)
        expected = os.path.normcase(os.path.normpath(str(helper.resolve())))
        if os.path.normcase(os.path.normpath(actual)) != expected:
            return False
        return bool(kernel.TerminateProcess(handle, 0))
    finally:
        kernel.CloseHandle(handle)
