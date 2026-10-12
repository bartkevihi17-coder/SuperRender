"""Native Render Beta backend.

The experimental backend is intentionally narrow:
- only the bundled, hash-verified LFG.dll can be loaded;
- only into the exact executable started and tracked by SuperRender;
- protected/competitive titles are rejected by the planner before this module;
- there is no anticheat bypass, stealth loading or arbitrary DLL/process mode.

LFG is an independent GPL-3.0 project pinned by the build workflow. SuperRender
writes a per-process INI so the backend can keep the game's native visual
settings and only synthesize intermediate frames.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import math
import os
from pathlib import Path
import sys

from .library import APP_DATA


PROCESS_CREATE_THREAD = 0x0002
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
IMAGE_FILE_MACHINE_AMD64 = 0x8664


def runtime_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def bundled_framegen() -> Path | None:
    dll = runtime_root() / "third_party" / "LFG.dll"
    return dll if dll.is_file() else None


def _sha_file() -> Path:
    return runtime_root() / "third_party" / "LFG-SHA256.txt"


def verify_bundled_framegen() -> tuple[Path | None, str]:
    """Verify the exact backend produced by our pinned build."""
    dll = bundled_framegen()
    if dll is None:
        return None, "Backend nativo de Frame Generation ainda nao esta incluido nesta compilacao."
    checksum = _sha_file()
    if not checksum.is_file():
        return None, "Manifesto SHA-256 do backend nao encontrado; carregamento bloqueado."
    try:
        expected = checksum.read_text(encoding="utf-8").strip().split()[0].lower()
        actual = hashlib.sha256(dll.read_bytes()).hexdigest().lower()
    except (OSError, IndexError):
        return None, "Nao foi possivel validar a integridade do backend."
    if len(expected) != 64 or actual != expected:
        return None, "LFG.dll falhou na verificacao SHA-256; carregamento bloqueado."
    return dll, ""


def pe_machine(path: Path) -> int | None:
    """Read PE machine without executing or loading the game binary."""
    try:
        with path.open("rb") as handle:
            if handle.read(2) != b"MZ":
                return None
            handle.seek(0x3C)
            raw = handle.read(4)
            if len(raw) != 4:
                return None
            pe_offset = int.from_bytes(raw, "little")
            if pe_offset < 64 or pe_offset > 32 * 1024 * 1024:
                return None
            handle.seek(pe_offset)
            if handle.read(4) != b"PE\x00\x00":
                return None
            machine = handle.read(2)
            return int.from_bytes(machine, "little") if len(machine) == 2 else None
    except OSError:
        return None


def is_x64_game(game: dict) -> bool:
    exe = Path(str(game.get("exe") or ""))
    return exe.is_file() and pe_machine(exe) == IMAGE_FILE_MACHINE_AMD64


def framegen_available_for_game(game: dict) -> bool:
    dll, _error = verify_bundled_framegen()
    return dll is not None and is_x64_game(game)


def generated_frame_count(base_fps: float | None, target_fps: int = 60) -> int:
    """Number of synthetic frames inserted between real frames.

    The cap is deliberate: beyond 4x displayed cadence quality/latency becomes
    too poor for the default automatic mode. Users can still improve real FPS
    independently through game-specific profiles.
    """
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


def write_backend_config(pid: int, base_fps: float | None, gpu_name: str,
                         target_fps: int = 60) -> Path:
    """Write settings consumed once by the injected backend for this PID."""
    count = generated_frame_count(base_fps, target_fps)
    legacy = _legacy_gpu(gpu_name)
    if legacy:
        # Keep the game itself at native quality. Only motion estimation uses
        # the cheapest algorithm; RenderScale remains 100%.
        algorithm, block, radius, max_pyr, min_pyr = 0, 32, 4, 2, 2
        adaptive, subpixel, smooth = 0, 0, 0
        ghost, rcas = 45, 8
    else:
        algorithm, block, radius, max_pyr, min_pyr = 1, 16, 12, 1, 0
        adaptive, subpixel, smooth = 1, 1, 0
        ghost, rcas = 35, 12

    APP_DATA.mkdir(parents=True, exist_ok=True)
    path = APP_DATA / f"framegen-{int(pid)}.ini"
    text = (
        "[framegen]\n"
        f"MultiFrameCount={count}\n"
        "EnableDynamicRatio=0\n"
        f"DynamicTargetFPS={int(target_fps)}\n"
        "RenderScalePercent=100\n"
        f"OpticalFlowAlgorithm={algorithm}\n"
        f"BlockSize={block}\n"
        f"SearchRadius={radius}\n"
        f"MaxPyramidLevel={max_pyr}\n"
        f"MinPyramidLevel={min_pyr}\n"
        "EnableBiDirFlow=0\n"
        f"EnableAdaptiveBlock={adaptive}\n"
        f"EnableSubPixel={subpixel}\n"
        f"EnableMotionSmoothing={smooth}\n"
        "LowLatencyMode=1\n"
        "DisableVSync=1\n"
        "EdgeProtection=1\n"
        f"GhostingReductionPercent={ghost}\n"
        f"RcasStrengthPercent={rcas}\n"
        "ShowDebugOverlay=1\n"
    )
    temp = path.with_suffix(".tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)
    return path


def _normal(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _open_verified_process(pid: int, exe_path: str):
    """Open with injection rights only after comparing the exact image path."""
    if os.name != "nt" or pid <= 0 or not Path(exe_path).is_file():
        return None
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    )
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    access = (
        PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION |
        PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_OPERATION |
        PROCESS_VM_WRITE | PROCESS_VM_READ
    )
    handle = kernel.OpenProcess(access, False, int(pid))
    if not handle:
        return None
    actual = ctypes.create_unicode_buffer(32768)
    size = wintypes.DWORD(len(actual))
    if (not kernel.QueryFullProcessImageNameW(handle, 0, actual, ctypes.byref(size))
            or _normal(actual.value) != _normal(exe_path)):
        kernel.CloseHandle(handle)
        return None
    return handle


def _load_verified_backend(pid: int, exe_path: str, dll: Path) -> str:
    """Load our single bundled backend into the verified game process."""
    kernel = ctypes.windll.kernel32
    handle = _open_verified_process(pid, exe_path)
    if not handle:
        raise RuntimeError("Processo do jogo mudou ou o Windows negou acesso ao backend.")

    kernel.VirtualAllocEx.argtypes = (
        wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD
    )
    kernel.VirtualAllocEx.restype = ctypes.c_void_p
    kernel.VirtualFreeEx.argtypes = (
        wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD
    )
    kernel.WriteProcessMemory.argtypes = (
        wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)
    )
    kernel.WriteProcessMemory.restype = wintypes.BOOL
    kernel.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
    kernel.GetModuleHandleW.restype = wintypes.HMODULE
    kernel.GetProcAddress.argtypes = (wintypes.HMODULE, ctypes.c_char_p)
    kernel.GetProcAddress.restype = ctypes.c_void_p
    kernel.CreateRemoteThread.argtypes = (
        wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)
    )
    kernel.CreateRemoteThread.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.GetExitCodeThread.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.GetExitCodeThread.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)

    remote = None
    thread = None
    try:
        encoded = (str(dll.resolve()) + "\x00").encode("utf-16-le")
        remote = kernel.VirtualAllocEx(
            handle, None, len(encoded), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
        )
        if not remote:
            raise RuntimeError("Falha ao reservar memoria para iniciar o backend.")
        buffer = ctypes.create_string_buffer(encoded)
        written = ctypes.c_size_t()
        if not kernel.WriteProcessMemory(
            handle, remote, buffer, len(encoded), ctypes.byref(written)
        ) or written.value != len(encoded):
            raise RuntimeError("Falha ao enviar o caminho do backend para o jogo.")

        module = kernel.GetModuleHandleW("kernel32.dll")
        load_library = kernel.GetProcAddress(module, b"LoadLibraryW") if module else None
        if not load_library:
            raise RuntimeError("LoadLibraryW nao disponivel no Windows.")

        tid = wintypes.DWORD()
        thread = kernel.CreateRemoteThread(
            handle, None, 0, load_library, remote, 0, ctypes.byref(tid)
        )
        if not thread:
            raise RuntimeError(
                "Windows recusou iniciar o backend no jogo. Tente executar os dois no mesmo nivel de permissao."
            )
        status = kernel.WaitForSingleObject(thread, 12000)
        if status == WAIT_TIMEOUT:
            raise RuntimeError("Backend demorou demais para carregar.")
        if status != WAIT_OBJECT_0:
            raise RuntimeError("Falha ao aguardar inicializacao do backend.")
        code = wintypes.DWORD()
        if not kernel.GetExitCodeThread(thread, ctypes.byref(code)) or code.value == 0:
            raise RuntimeError("O jogo recusou carregar o backend de Frame Generation.")
        return "Backend DX11 de Frame Generation carregado."
    finally:
        if thread:
            kernel.CloseHandle(thread)
        if remote:
            kernel.VirtualFreeEx(handle, remote, 0, MEM_RELEASE)
        kernel.CloseHandle(handle)


def start_frame_generation(game: dict, pid: int, base_fps: float | None,
                           gpu_name: str, target_fps: int = 60) -> dict:
    """Prepare per-game settings and start real intermediate-frame generation."""
    dll, error = verify_bundled_framegen()
    if dll is None:
        raise RuntimeError(error)
    exe = Path(str(game.get("exe") or ""))
    if not exe.is_file():
        raise RuntimeError("Executavel real do jogo nao foi identificado.")
    if pe_machine(exe) != IMAGE_FILE_MACHINE_AMD64:
        raise RuntimeError("Backend experimental atual requer jogo Windows x64.")
    config = write_backend_config(pid, base_fps, gpu_name, target_fps)
    message = _load_verified_backend(pid, str(exe), dll)
    return {
        "message": message,
        "config": str(config),
        "base_fps": base_fps,
        "generated_between": generated_frame_count(base_fps, target_fps),
        "target_fps": target_fps,
    }
