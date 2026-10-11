"""Capas e icones locais para a UI nativa.

Prioridade: imagem do cache da Steam > capa oficial da Steam > icone do
executavel/atalho. Conversao local via System.Drawing do Windows.
Nunca requer chave de API de terceiros nem altera os jogos.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from .library import APP_DATA

ART = APP_DATA / "art"
WIDTH, HEIGHT = 264, 146


def photo_file(game: dict) -> Path:
    digest = hashlib.sha256(str(game.get("id", "")).encode("utf-8")).hexdigest()[:24]
    return ART / (digest + ".png")


def steam_art_candidates(game: dict):
    steam_id = str(game.get("steam_id") or "")
    if not steam_id.isdigit():
        return
    installation = Path(game.get("install_dir") or ".")
    # %Steam%\steamapps\common\<game> -> biblioteca raiz
    library = installation.parent.parent.parent if installation.is_dir() else Path(".")
    roots = [
        library / "appcache" / "librarycache",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) /
        "Steam" / "appcache" / "librarycache",
    ]
    for cache in roots:
        for file in (
            cache / steam_id / "header.jpg",
            cache / steam_id / "library_hero.jpg",
            cache / steam_id / "library_600x900.jpg",
            cache / (steam_id + "_header.jpg"),
            cache / (steam_id + "_library_hero.jpg"),
            cache / (steam_id + "_library_600x900.jpg"),
        ):
            if file.is_file():
                yield file


def remote_steam_art(steam_id: str) -> Path | None:
    if not steam_id.isdigit():
        return None
    # Endereco oficial de imagens publicas do catalogo Steam.
    url = "https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/" + steam_id + "/header.jpg"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SuperRender/0.2"})
        with urllib.request.urlopen(req, timeout=4.0) as response:
            content_type = response.headers.get("Content-Type", "")
            if "image/" not in content_type:
                return None
            raw = response.read(2_500_001)
        if len(raw) > 2_500_000 or len(raw) < 100:
            return None
        ART.mkdir(parents=True, exist_ok=True)
        image = ART / ("steam-" + steam_id + ".jpg")
        image.write_bytes(raw)
        return image
    except (OSError, ValueError, TimeoutError):
        return None


def convert_with_windows(source: Path, destination: Path, icon: bool) -> bool:
    """Converte JPEG/ICO/EXE/atalho em PNG dimensionado sem Pillow/PyQt."""
    if os.name != "nt" or not source.is_file():
        return False
    script = r"""
Add-Type -AssemblyName System.Drawing
$ErrorActionPreference='Stop'
$source=$env:SR_IMG_SOURCE
$dest=$env:SR_IMG_DEST
$mode=$env:SR_IMG_MODE
$image=$null
$icon=$null
$canvas=$null
$gfx=$null
try {
 if($mode -eq 'icon') {
    $icon=[System.Drawing.Icon]::ExtractAssociatedIcon($source)
    if($null -eq $icon) {exit 2}
    $image=$icon.ToBitmap()
 } else {
    $image=[System.Drawing.Image]::FromFile($source)
 }
 $width=264; $height=146
 $canvas=New-Object System.Drawing.Bitmap($width, $height)
 $gfx=[System.Drawing.Graphics]::FromImage($canvas)
 $gfx.SmoothingMode=[System.Drawing.Drawing2D.SmoothingMode]::HighQuality
 $gfx.InterpolationMode=[System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
 $gfx.Clear([System.Drawing.Color]::FromArgb(25,34,53))
 if($mode -eq 'icon') {
    $scale=[Math]::Min(0.87*[Math]::Min($width,$height)/$image.Width, 0.87*[Math]::Min($width,$height)/$image.Height)
 } else {
    $scale=[Math]::Max($width/$image.Width,$height/$image.Height)
 }
 $w=[int][Math]::Round($image.Width*$scale)
 $h=[int][Math]::Round($image.Height*$scale)
 $destRect=New-Object System.Drawing.Rectangle([int](($width-$w)/2),[int](($height-$h)/2),$w,$h)
 $gfx.DrawImage($image,$destRect)
 $canvas.Save($dest,[System.Drawing.Imaging.ImageFormat]::Png)
} finally {
 if($null -ne $gfx){$gfx.Dispose()}
 if($null -ne $canvas){$canvas.Dispose()}
 if($null -ne $image){$image.Dispose()}
 if($null -ne $icon){$icon.Dispose()}
}
"""
    env = os.environ.copy()
    env["SR_IMG_SOURCE"] = str(source)
    env["SR_IMG_DEST"] = str(destination)
    env["SR_IMG_MODE"] = "icon" if icon else "cover"
    try:
        process = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, env=env, timeout=13,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return process.returncode == 0 and destination.is_file() and destination.stat().st_size > 500
    except (OSError, subprocess.TimeoutExpired):
        return False


def ensure_art(game: dict) -> Path | None:
    output = photo_file(game)
    if output.is_file():
        return output
    missed = output.with_suffix(".missing")
    if missed.is_file():
        return None
    ART.mkdir(parents=True, exist_ok=True)
    source = None
    steam_id = str(game.get("steam_id") or "")
    if steam_id.isdigit():
        source = next(iter(steam_art_candidates(game)), None)
        if source is None:
            source = remote_steam_art(steam_id)
    if source and convert_with_windows(source, output, icon=False):
        return output
    raw_icon = str(game.get("icon_source") or game.get("exe") or "")
    if raw_icon:
        exe_or_shortcut = Path(raw_icon.split(",")[0])
        if exe_or_shortcut.is_file():
            is_icon = exe_or_shortcut.suffix.lower() in (".exe", ".lnk", ".ico")
            if convert_with_windows(exe_or_shortcut, output, icon=is_icon):
                return output
    try:
        missed.touch()
    except OSError:
        pass
    return None
