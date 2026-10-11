"""Inicializacao segura: normal ou prioridade de processo acima do normal.

Esta versao nao intercepta DirectX nem injeta DLLs. Em clientes como Steam
usa o protocolo oficial da loja, sem tentar contornar DRM/anticheat.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import threading
import time
from pathlib import Path
from ctypes import wintypes

from .library import played

ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
HIGH_PRIORITY_CLASS = 0x00000080
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_SET_INFORMATION = 0x0200
BLOCKED_PROTECTED_GAMES = ("valorant", "fortnite", "league of legends")


def eligible_for_priority(game: dict) -> bool:
    text = str(game.get("name") or "").casefold()
    return not any(game_name in text for game_name in BLOCKED_PROTECTED_GAMES)


def _change_priority(handle, value: int) -> bool:
    try:
        kernel = ctypes.windll.kernel32
        kernel.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.SetPriorityClass.restype = wintypes.BOOL
        return bool(kernel.SetPriorityClass(handle, value))
    except (AttributeError, OSError):
        return False


def _priority_direct(process: subprocess.Popen, priority=ABOVE_NORMAL_PRIORITY_CLASS) -> bool:
    if os.name != "nt":
        return False
    try:
        return _change_priority(int(process._handle), priority)
    except (AttributeError, OSError, ValueError):
        return False


def _matching_process(exe: Path, require_set=False):
    """Localiza processo pelo caminho completo, evitando afetar outros jogos."""
    if os.name != "nt" or not exe.is_file():
        return None
    kernel = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    pids = (wintypes.DWORD * 4096)()
    returned = wintypes.DWORD()
    if not psapi.EnumProcesses(ctypes.byref(pids), ctypes.sizeof(pids), ctypes.byref(returned)):
        return None
    for pid in pids[:returned.value // ctypes.sizeof(wintypes.DWORD)]:
        if not pid:
            continue
        handle = kernel.OpenProcess(
            (PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SET_INFORMATION)
            if require_set else PROCESS_QUERY_LIMITED_INFORMATION,
            False, int(pid),
        )
        if not handle:
            continue
        name = ctypes.create_unicode_buffer(32768)
        chars = wintypes.DWORD(len(name))
        found = bool(kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(chars)))
        if found and os.path.normcase(name.value) == os.path.normcase(str(exe)):
            return handle
        kernel.CloseHandle(handle)
    return None


def _watch_priority(exe: Path, notify=None, priority=ABOVE_NORMAL_PRIORITY_CLASS):
    """Aguarda ate o jogo aparecer (launchers retornam imediatamente)."""
    if not exe.is_file():
        return
    handle = None
    for _ in range(75):
        handle = _matching_process(exe, require_set=True)
        if handle:
            break
        time.sleep(1)
    if not handle:
        if notify:
            notify("O launcher abriu, mas nao foi possivel identificar o processo do jogo.")
        return
    kernel = ctypes.windll.kernel32
    old_priority = kernel.GetPriorityClass(handle)
    changed = _change_priority(handle, priority)
    if notify:
        notify("Prioridade do jogo elevada temporariamente." if changed
               else "Jogo iniciado; Windows recusou mudar a prioridade.")
    try:
        while True:
            # WAIT_OBJECT_0 = 0, timeout de 1 segundo
            if kernel.WaitForSingleObject(handle, 1000) == 0:
                break
    finally:
        if changed and old_priority:
            _change_priority(handle, old_priority)
        kernel.CloseHandle(handle)


def launch(game: dict, mode: str, notify=None) -> str:
    if mode not in ("normal", "light", "optimized", "potato", "render"):
        raise ValueError("Modo de inicializacao desconhecido.")
    if os.name != "nt":
        raise RuntimeError("Inicializacao de jogos Windows requer Windows.")
    kind = game.get("kind")
    target = str(game.get("target") or "")
    args = game.get("args") or []
    if not target or not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise ValueError("Cadastro do jogo esta incompleto.")

    exe_to_monitor = Path(str(game.get("exe") or ""))
    eligible = eligible_for_priority(game)
    priority = HIGH_PRIORITY_CLASS if mode == "potato" else ABOVE_NORMAL_PRIORITY_CLASS

    if kind == "uri":
        if not (target.startswith("steam://rungameid/") and target[18:].isdigit()
                or target.startswith("com.epicgames.launcher://apps/") and "?action=launch" in target):
            raise ValueError("Protocolo de loja nao reconhecido.")
        os.startfile(target)
        result = "Comando enviado ao launcher da loja."
    elif kind == "shortcut":
        shortcut = Path(target)
        if not shortcut.is_file() or shortcut.suffix.lower() != ".lnk":
            raise FileNotFoundError("Atalho nao localizado: " + target)
        os.startfile(str(shortcut))
        result = "Atalho executado."
    elif kind == "exe":
        executable = Path(target)
        if not executable.is_file() or executable.suffix.lower() not in (".exe", ".bat", ".cmd"):
            raise FileNotFoundError("Executavel nao localizado: " + target)
        cmd = [str(executable), *args]
        if executable.suffix.lower() in (".bat", ".cmd"):
            cmd = ["cmd.exe", "/d", "/c", str(executable), *args]
        process = subprocess.Popen(
            cmd, cwd=str(executable.parent),
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        # Nao mexe na prioridade do Riot Client, apenas do executavel do jogo.
        if mode != "normal" and eligible and exe_to_monitor.is_file() and (
            os.path.normcase(str(executable)) == os.path.normcase(str(exe_to_monitor))
        ):
            if _priority_direct(process, priority):
                result = "Jogo iniciado com prioridade acima do normal."
            else:
                result = "Jogo iniciado; Windows nao permitiu elevar prioridade."
        else:
            result = "Processo iniciado."
    else:
        raise ValueError("Tipo de jogo nao reconhecido.")

    played(game["id"])
    if mode != "normal":
        if not eligible:
            result += " Otimizacoes de processo desativadas para jogos com anticheat."
        elif exe_to_monitor.is_file() and (kind in ("uri", "shortcut") or
                                           os.path.normcase(target) != os.path.normcase(str(exe_to_monitor))):
            threading.Thread(
                target=_watch_priority, args=(exe_to_monitor, notify, priority),
                daemon=True, name="sr-priority-watch",
            ).start()
            result += " Aguardando executavel do jogo para aplicar prioridade."
        elif kind == "uri" or kind == "shortcut":
            result += " Sem executavel detectado para aplicar prioridade."
    return result
