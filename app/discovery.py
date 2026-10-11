"""Descoberta de jogos sem caminhos particulares do desenvolvedor.

Fontes: manifestos Steam/Epic, biblioteca GOG, Riot, atalhos do Windows
e pastas comuns de jogos em todas as unidades locais disponiveis.
Nenhum drive ou nome de usuario e assumido.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import quote

from .library import compact_name, game_id, sync_found

SKIP_DIRS = {
    "$recycle.bin", "system volume information", "windows", "windows.old",
    "program files", "program files (x86)", "programdata", "users",
    "recovery", "downloads", "tools", "backup", "backups", "drivers",
    "nvidia", "intel", "amd", "temp", "one drive", "onedrive", "steam",
    "steamapps", "steamlibrary", "epic games", "riot games", "xboxgames",
    "games", "jogos", "arquivos de programas", "appdata", "python",
    "windowsapps", "wpsystem", "riot client", "mcbe-contentupgrade",
}
SKIP_EXE = re.compile(
    r"(?i)(^unins|^setup|installer|installshield|redist|crashreport|crashhandler|"
    r"unrealcef|vcredist|dxsetup|uninstall|unins000|dotnet|eosoverlay|"
    r"benchmark|editor|configtool|anticheat|easyanticheat|"
    r"reporter|update|support|prereq|launcherpatcher|steamservice)"
)
SAFE_MOUNT_FOLDER = ("Games", "Jogos", "Installed Games", "SteamLibrary", "Epic Games",
                     "GOG Games", "Ubisoft", "Ubisoft Games", "Riot Games", "XboxGames")


def drives() -> list[Path]:
    if os.name != "nt":
        return [Path.home()]
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    result = []
    for num in range(26):
        if not mask & (1 << num):
            continue
        root = Path(chr(65 + num) + ":\\")
        try:
            # DRIVE_FIXED(3); exclui unidades CD e pen drives por padrao
            if ctypes.windll.kernel32.GetDriveTypeW(str(root)) == 3:
                result.append(root)
        except OSError:
            continue
    return result


def parse_kv(text: str) -> dict[str, str]:
    # Manifestos Valve/Steam sao KeyValues, nao JSON.
    return {
        key.casefold(): val.replace("\\\\", "\\")
        for key, val in re.findall(r'"([^"]+)"\s*"([^"]*)"', text)
    }


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""


def tidy_name(name: str) -> str:
    text = re.sub(r"\s*\[(?:fitgirl|repack|xatab|elamigos|dodi)[^\]]*\]", "", name, flags=re.I)
    return re.sub(r"\s{2,}", " ", text).strip(" -_.") or name


def find_game_exe(folder: Path, title: str = "", max_files: int = 1100) -> Path | None:
    """Procura executavel sem varrer um disco inteiro. Usado so em diretorios candidatos."""
    if not folder.is_dir():
        return None
    pending = [(folder, 0)]
    choices: list[tuple[float, Path]] = []
    checked = 0
    title_key = compact_name(title)
    while pending and checked < max_files:
        here, depth = pending.pop(0)
        try:
            entries = list(here.iterdir())
        except (OSError, PermissionError):
            continue
        for path in entries:
            checked += 1
            if checked > max_files:
                break
            lower = path.name.casefold()
            if path.is_dir() and depth < 2 and not any(
                t in lower for t in ("redist", "support", "installer", "update", "crash",
                                    "setup", "directx", "manual", "language")
            ):
                pending.append((path, depth + 1))
                continue
            if not path.is_file() or path.suffix.lower() != ".exe" or SKIP_EXE.search(lower):
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size < 150_000:
                continue
            stem = compact_name(path.stem)
            score = 2 if depth == 0 else 0
            if title_key and (stem == title_key or title_key in stem or stem in title_key and len(stem) > 4):
                score += 18
            elif title_key and len(set(re.findall(r"[a-z]+|\d+", path.stem.casefold())) &
                                     set(re.findall(r"[a-z]+|\d+", title.casefold()))) >= 1:
                score += 4
            if "binaries" in str(path.parent).casefold() or "win64" in str(path.parent).casefold():
                score += 2
            if "launcher" in lower:
                score -= 4
            # Executavel grande pode ser o jogo, mas nao confie apenas no tamanho.
            score += min(size / (40 * 1024 * 1024), 4)
            choices.append((score, path))
    return max(choices, key=lambda item: item[0])[1] if choices else None


def game_record(name: str, source: str, kind: str, target: str,
                install_dir: str = "", exe: str = "", identifier: str = "",
                args: list[str] | None = None, steam_id: str = "", icon_source: str = "") -> dict:
    key = identifier or target
    return {
        "id": game_id(source, key), "name": tidy_name(name), "source": source,
        "kind": kind, "target": target, "args": args or [],
        "install_dir": install_dir, "exe": exe, "steam_id": steam_id,
        "icon_source": icon_source or exe or target,
        "available": True, "favorite": False, "hidden": False,
    }


def steam_roots() -> set[Path]:
    roots: set[Path] = set()
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                for entry in ("SteamPath", "InstallPath"):
                    try:
                        roots.add(Path(winreg.QueryValueEx(key, entry)[0]))
                    except OSError:
                        pass
        except OSError:
            pass
    pf86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    roots.add(pf86 / "Steam")
    for disk in drives():
        roots.add(disk / "Steam")
        roots.add(disk / "SteamLibrary")
        roots.add(disk / "Program Files (x86)" / "Steam")
    libraries: set[Path] = set()
    for root in roots:
        if (root / "steamapps").is_dir():
            libraries.add(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        content = read_text(vdf)
        for raw in re.findall(r'"path"\s*"([^"]+)"', content, flags=re.I):
            try:
                lib = Path(raw.replace("\\\\", "\\"))
                if (lib / "steamapps").is_dir():
                    libraries.add(lib)
            except OSError:
                continue
    return libraries


def scan_steam(progress=None) -> list[dict]:
    found = []
    for library in steam_roots():
        try:
            manifests = sorted((library / "steamapps").glob("appmanifest_*.acf"))
        except OSError:
            continue
        for manifest in manifests:
            pairs = parse_kv(read_text(manifest))
            appid = pairs.get("appid") or manifest.stem.removeprefix("appmanifest_")
            if not appid.isdigit():
                continue
            name = pairs.get("name") or "Steam " + appid
            if "redistributable" in name.casefold() or not pairs.get("installdir"):
                continue
            install = library / "steamapps" / "common" / pairs["installdir"]
            if not install.is_dir():
                continue
            exe = find_game_exe(install, name)
            found.append(game_record(name, "Steam", "uri", "steam://rungameid/" + appid,
                                     str(install), str(exe or ""), appid, steam_id=appid,
                                     icon_source=str(exe or "")))
    if progress:
        progress("Steam verificada")
    return found


def scan_epic(progress=None) -> list[dict]:
    found = []
    locations = [
        Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) /
        "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    ]
    for manifest_dir in locations:
        if not manifest_dir.is_dir():
            continue
        for item in manifest_dir.glob("*.item"):
            try:
                data = json.loads(item.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                continue
            name = data.get("DisplayName")
            install = Path(data.get("InstallLocation", ""))
            app = str(data.get("AppName") or "")
            if not name or not app or not install.is_dir():
                continue
            relative_exe = str(data.get("LaunchExecutable") or "").replace("/", "\\").lstrip("\\")
            preferred_exe = install / relative_exe if relative_exe else None
            exe = preferred_exe if preferred_exe and preferred_exe.is_file() else find_game_exe(install, name)
            uri = "com.epicgames.launcher://apps/" + quote(app, safe="") + "?action=launch&silent=true"
            found.append(game_record(name, "Epic Games", "uri", uri,
                                     str(install), str(exe or ""), app, icon_source=str(exe or "")))
    if progress:
        progress("Epic Games verificada")
    return found


def scan_gog(progress=None) -> list[dict]:
    found = []
    if os.name != "nt":
        return found
    try:
        import winreg
        hives = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
        for hive in hives:
            for view in (0, winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
                try:
                    root = winreg.OpenKey(hive, r"SOFTWARE\GOG.com\Games", 0, winreg.KEY_READ | view)
                except OSError:
                    continue
                with root:
                    try:
                        count = winreg.QueryInfoKey(root)[0]
                    except OSError:
                        count = 0
                    for i in range(min(count, 200)):
                        try:
                            key_name = winreg.EnumKey(root, i)
                            with winreg.OpenKey(root, key_name) as key:
                                def value(label):
                                    try:
                                        return str(winreg.QueryValueEx(key, label)[0])
                                    except OSError:
                                        return ""
                                title = value("gameName") or value("name")
                                install = Path(value("path"))
                                launch = value("exe")
                                exe = Path(launch) if launch and Path(launch).is_file() else find_game_exe(install, title)
                                if title and exe and exe.is_file():
                                    found.append(game_record(title, "GOG", "exe", str(exe),
                                                             str(install), str(exe), key_name))
                        except (OSError, ValueError):
                            continue
    except OSError:
        pass
    if progress:
        progress("GOG verificada")
    return found


def scan_riot(progress=None) -> list[dict]:
    found = []
    for disk in drives():
        riot_dir = disk / "Riot Games"
        client = riot_dir / "Riot Client" / "RiotClientServices.exe"
        if not client.is_file():
            continue
        for folder, display, product in (
            ("League of Legends", "League of Legends", "league_of_legends"),
            ("VALORANT", "VALORANT", "valorant"),
        ):
            install = riot_dir / folder
            if not install.is_dir():
                continue
            icon = find_game_exe(install, display)
            found.append(game_record(display, "Riot Games", "exe", str(client),
                                     str(install), str(icon or client), product,
                                     args=["--launch-product=" + product, "--launch-patchline=live"],
                                     icon_source=str(icon or client)))
    if progress:
        progress("Riot Games verificada")
    return found


def scan_shortcuts(progress=None) -> list[dict]:
    if os.name != "nt":
        return []
    # WScript.Shell extrai caminhos .lnk corretamente, inclusive argumentos Steam/Riot.
    script = r"""
$ErrorActionPreference='SilentlyContinue'
$w=New-Object -ComObject WScript.Shell
$folders=@([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('CommonDesktopDirectory'),
[Environment]::GetFolderPath('StartMenu'),[Environment]::GetFolderPath('CommonStartMenu'))
$list=@()
foreach($d in $folders) {
 if(!(Test-Path -LiteralPath $d)){continue}
 foreach($l in (Get-ChildItem -LiteralPath $d -Filter '*.lnk' -File -Recurse -ErrorAction SilentlyContinue |
 Select-Object -First 750)) {
  try {
   $s=$w.CreateShortcut($l.FullName)
   $list+=@{name=$l.BaseName; shortcut=$l.FullName; target=$s.TargetPath; arguments=$s.Arguments; icon=$s.IconLocation}
  } catch {}
 }
}
ConvertTo-Json -InputObject @($list) -Compress -Depth 3
"""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=25, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        raw = json.loads(result.stdout) if result.stdout.strip() else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    found = []
    if isinstance(raw, dict):
        raw = [raw]
    gaming_path = re.compile(r"(?i)[\\/](games|jogos|steamapps[\\/]common|epic games|"
                             r"riot games|xboxgames|gog games|ubisoft games)[\\/]")
    rejects = re.compile(r"(?i)(uninstall|configura|readme|crash|setup|launcher|steam|epic games|"
                         r"origin|ea app|gog galaxy|discord|chrome|brave|edge|"
                         r"game bar|visual studio|control panel|nvidia|directx|7-zip|winrar|"
                         r"riot client|cliente riot|game launch|steamworks)")
    for item in raw:
        title, path = str(item.get("name") or ""), str(item.get("target") or "")
        if not title or rejects.search(title):
            continue
        if not path or not Path(item.get("shortcut") or "").is_file():
            continue
        args = item.get("arguments") or ""
        good = gaming_path.search(path) or gaming_path.search(args)
        if not good and re.search(r"(?i)--launch-product=|--applaunch\s+\d+", args):
            good = True
        if not good:
            # Atalhos de jogos fora da pasta padrao em unidades secundarias.
            root = Path(path).anchor.upper()
            if root and root != Path(os.environ.get("SystemDrive", "C:") + "\\").anchor.upper():
                good = Path(path).suffix.lower() == ".exe"
        if not good:
            continue
        if title.casefold().startswith("play "):
            title = title[5:]
        link = str(item["shortcut"])
        found.append(game_record(title, "Atalho Windows", "shortcut", link,
                                 str(Path(path).parent), path if path.lower().endswith(".exe") else "",
                                 link, icon_source=path if Path(path).is_file() else link))
    if progress:
        progress("Atalhos verificados")
    return found


def scan_folders(progress=None) -> list[dict]:
    """Encontra instalacoes fora dos launchers em C:, D: etc (sem caminhos fixos)."""
    found = []
    disks = drives()
    visited: set[str] = set()
    for disk in disks:
        candidate_dirs = []
        for folder in SAFE_MOUNT_FOLDER:
            cand = disk / folder
            if cand.is_dir():
                try:
                    candidate_dirs.extend([x for x in cand.iterdir() if x.is_dir()])
                except OSError:
                    pass
        # Pastas de jogos instalados diretamente na raiz de unidades secundarias.
        is_system = str(disk).casefold().startswith(str(Path(os.environ.get("SystemDrive", "C:") + "\\")).casefold())
        if not is_system:
            try:
                candidate_dirs.extend(
                    x for x in disk.iterdir()
                    if x.is_dir() and x.name.casefold() not in SKIP_DIRS and
                    not x.name.startswith(("$", "."))
                )
            except OSError:
                pass
        for folder in candidate_dirs[:350]:
            location = str(folder).casefold()
            if location in visited or folder.name.casefold() in SKIP_DIRS:
                continue
            visited.add(location)
            # Repack/setup sem jogo instalado nao sera aceito: exige EXE real.
            exe = find_game_exe(folder, tidy_name(folder.name), max_files=900)
            if not exe:
                continue
            if re.search(r"(?i)(repack|fitgirl|setup)", folder.name) and not (
                compact_name(folder.name) in compact_name(exe.stem) or
                compact_name(exe.stem) in compact_name(folder.name) and len(exe.stem) > 5
            ):
                continue
            found.append(game_record(folder.name, "Pasta local", "exe", str(exe),
                                     str(folder), str(exe), str(folder), icon_source=str(exe)))
    if progress:
        progress("Pastas de jogos verificadas")
    return found


def discover(progress=None) -> list[dict]:
    def notify(message: str):
        if progress:
            progress(message)
    candidates = []
    for name, scanner in (
        ("Steam", scan_steam), ("Epic Games", scan_epic), ("GOG", scan_gog),
        ("Riot Games", scan_riot), ("Atalhos do Windows", scan_shortcuts),
        ("Discos locais", scan_folders),
    ):
        notify("Procurando jogos: " + name + "...")
        try:
            candidates.extend(scanner(notify))
        except Exception as error:
            notify(name + ": verificacao parcial (" + type(error).__name__ + ")")
    # a ordem favorece fontes da loja com titulo/id oficial.
    return sync_found([], candidates)
