"""Perfis reversiveis do SuperRender.

Apenas adaptadores conhecidos modificam configuracoes de jogos.
O adaptador NBA 2K20 utiliza VideoSettings.cfg documentado pelo proprio jogo.
Nunca toca nos arquivos de instalacao e nunca altera configuracoes de jogos sem adaptador.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from .library import APP_DATA

PROFILE_ORDER = ("normal", "light", "optimized", "potato")
PROFILE_INFO = {
    "normal": {
        "title": "Normal", "sub": "Do jeito que voce configurou", "accent": "#c8ceda",
        "details": "Nenhuma alteracao. O jogo usa exatamente suas configuracoes atuais."
    },
    "light": {
        "title": "Levemente otimizado", "sub": "Qualidade preservada", "accent": "#91d4cc",
        "details": "Prioridade de processo e ajustes conservadores. No NBA 2K20 mantem a resolucao atual."
    },
    "optimized": {
        "title": "Otimizado", "sub": "Prioridade para FPS", "accent": "#b49aff",
        "details": "Para NBA 2K20: 960x540 (16:9), sem efeitos caros. Pode ficar menos nitido."
    },
    "potato": {
        "title": "Potato", "sub": "Desempenho acima dos graficos", "accent": "#ffad74",
        "details": "Para NBA 2K20: 640x480 (4:3), qualidade minima. Imagem pode ficar bem borrada."
    }
}

_SESSIONS = APP_DATA / "sessions"
_BACKUPS = APP_DATA / "backups"
_LOCK = threading.RLock()

# Apenas propriedades documentadas em VideoSettingsHelp.txt.
NBA_CORE_LOW = {
    "OVERALL_QUALITY": 4, "WINDOWMODE": 0, "VSYNC": 0, "DYNAMIC_VSYNC": False,
    "BUFFERCOUNT": 1, "MSAA": 0, "MSAAQUALITY": 0, "SSAA": 0,
    "MAXANISOTROPY": 1, "ENHANCEDAA": False,
    "SHADER_DETAIL": 2, "SHADOW_DETAIL": 4,
    "CACHE_SPOT_SHADOWS": True, "CACHE_SUN_SHADOWS": True,
    "TEMPORALAA": False, "AMBIENT_OCCLUSION": False,
    "VOLUMETRIC_LIGHTING": False, "DEPTH_OF_FIELD": False,
    "MOTION_BLUR": False, "BLOOM": False, "FLOOR_REFLECTIONS": False,
    "MIRROR_REFLECTIONS": False, "PLAYERLOD": 2, "MEDIAPEOPLELOD": 3,
    "CROWDLOD": 3, "HAIRLOD": 2, "TEXTURELOD": 2,
    "D3D_INTERNAL_THREADING_OPTIMIZATIONS": True,
    "FAST_TEXTURE_FORMAT_CONVERSION": False, "JIT_SHADER_CREATE": False
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_nba2k20(game: dict) -> bool:
    target = Path(str(game.get("exe") or game.get("target") or "")).name.lower()
    name = str(game.get("name") or "").casefold().replace(" ", "")
    return target == "nba2k20.exe" or (
        name in ("nba2k20", "nba2k20game") and
        (game.get("source") == "Manual" or str(game.get("install_dir") or ""))
    )


def nba_config_path() -> Path:
    roaming = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    return roaming / "2K Sports" / "NBA 2K20" / "VideoSettings.cfg"


def get_adapter(game: dict) -> str | None:
    if is_nba2k20(game) and nba_config_path().is_file():
        return "nba2k20"
    return None


def supports_graphic_profile(game: dict) -> bool:
    return get_adapter(game) is not None


def profile_changes(game: dict, profile: str, current: dict) -> dict:
    if profile not in PROFILE_INFO:
        raise ValueError("Perfil de otimizacao invalido.")
    if profile == "normal" or not supports_graphic_profile(game):
        return {}
    if profile == "light":
        # Conservador: evita modificar resolucao, torcida e detalhes que
        # o proprio usuario deseja preservar.
        return {
            "D3D_INTERNAL_THREADING_OPTIMIZATIONS": True,
            "CACHE_SPOT_SHADOWS": True,
            "CACHE_SUN_SHADOWS": True, "ABOVE_NORMAL_PRIORITY": 1,
        }
    result = {**NBA_CORE_LOW, "ABOVE_NORMAL_PRIORITY": 1, "USE_COMPUTE_SHADERS": False}
    if profile == "optimized":
        result.update({"WIDTH": 960, "HEIGHT": 540, "ALLOW_BLURRY_UI": False})
    else:
        result.update({"WIDTH": 640, "HEIGHT": 480, "UI_ASPECT": True,
                       "ALLOW_BLURRY_UI": True, "ABOVE_NORMAL_PRIORITY": 2})
    return result


def session_file(game: dict) -> Path:
    ident = hashlib.sha256(str(game.get("id") or game.get("exe") or "").encode("utf-8")).hexdigest()[:20]
    return _SESSIONS / (ident + ".json")


def is_running(game: dict) -> bool:
    """Reutiliza a verificacao Win32 do launcher; nao mexe no processo."""
    exe = Path(str(game.get("exe") or ""))
    if not exe.is_file():
        return False
    try:
        from .launcher import _matching_process
        handle = _matching_process(exe)
        if handle:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(handle)
        return bool(handle)
    except (OSError, AttributeError, ImportError, ValueError):
        return False


def read_session(game: dict) -> dict | None:
    try:
        file = session_file(game)
        if file.is_file():
            return json.loads(file.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        pass
    return None


def _write_json_atomic(destination: Path, data: dict) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(destination.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, destination)


def _write_bytes_atomic(destination: Path, data: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_name(destination.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, destination)


def restore_game(game: dict, force: bool = False) -> str:
    """Restaura o CFG quando possivel.

    force=True so deve ser invocado apos confirmacao explicita, pois
    sobrepoe alteracoes recentes. Antes, guarda uma copia dessas alteracoes.
    """
    with _LOCK:
        state = read_session(game)
        if not state:
            return ""
        if is_running(game):
            return "Nao restaurado: o jogo ainda esta aberto."
        original = Path(state.get("backup", ""))
        config = Path(state.get("config", ""))
        if not original.is_file():
            return "Backup nao encontrado; restauracao manual necessaria."
        if not config.is_file():
            return "Arquivo de configuracao foi removido; backup preservado."
        current_bytes = config.read_bytes()
        if _sha(current_bytes) != state.get("applied_sha256"):
            if not force:
                # Jogo ou usuario alterou o CFG: nunca apagar mudancas sem autorizacao.
                return "Configuracao modificada fora do SuperRender. Backup preservado para revisao."
            _BACKUPS.mkdir(parents=True, exist_ok=True)
            current_backup = _BACKUPS / (
                "before-manual-restore-" + uuid.uuid4().hex[:12] + ".cfg")
            current_backup.write_bytes(current_bytes)
        data = original.read_bytes()
        _write_bytes_atomic(config, data)
        if _sha(config.read_bytes()) != state.get("original_sha256"):
            raise OSError("Falha ao validar a restauracao do backup.")
        session_file(game).unlink(missing_ok=True)
        return "Configuracoes originais restauradas."


def prepare_game(game: dict, profile: str) -> dict | None:
    """Cria backup antes de modificar, e registra sessao persistente para recuperacao."""
    with _LOCK:
        if profile == "normal":
            return None
        if not supports_graphic_profile(game):
            return None
        if is_running(game):
            raise RuntimeError("Feche o jogo antes de aplicar um novo perfil grafico.")
        old_state = read_session(game)
        if old_state:
            result = restore_game(game)
            if read_session(game):
                raise RuntimeError(
                    "Ha um backup pendente para este jogo. " + result +
                    " Abra a area de backup e restaure antes de aplicar outro perfil."
                )
        file = nba_config_path()
        data = file.read_bytes()
        if len(data) > 150_000:
            raise RuntimeError("Configuracao inesperadamente grande. Nenhuma alteracao aplicada.")
        try:
            config = json.loads(data.decode("utf-8-sig"))
        except (ValueError, UnicodeError) as exc:
            raise RuntimeError("VideoSettings.cfg nao esta em formato JSON valido.") from exc
        if not isinstance(config, dict) or "WIDTH" not in config or "HEIGHT" not in config:
            raise RuntimeError("Formato de configuracao NBA 2K20 nao reconhecido.")
        modified = {**config, **profile_changes(game, profile, config)}
        new_bytes = (json.dumps(modified, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        if data == new_bytes:
            return None
        _BACKUPS.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = _BACKUPS / (f"NBA2K20-{stamp}-{uuid.uuid4().hex[:8]}.cfg")
        backup_path.write_bytes(data)
        state = {
            "version": 1, "game_id": game["id"], "exe": str(game.get("exe") or ""),
            "config": str(file), "backup": str(backup_path), "profile": profile,
            "original_sha256": _sha(data), "applied_sha256": _sha(new_bytes),
            "started_at": datetime.now().isoformat(timespec="seconds"),
        }
        _write_json_atomic(session_file(game), state)
        try:
            _write_bytes_atomic(file, new_bytes)
        except BaseException:
            session_file(game).unlink(missing_ok=True)
            _write_bytes_atomic(file, data)
            raise
        return state


def monitor_and_restore(game: dict, notice=None, grace_seconds: int = 150) -> None:
    """Aguarda o executavel real abrir e encerrar; restauracao segura."""
    if not read_session(game):
        return
    launched = False
    for _ in range(grace_seconds):
        if is_running(game):
            launched = True
            break
        time.sleep(1)
    if not launched:
        result = restore_game(game)
        if notice:
            notice("Jogo nao detectado. " + result)
        return
    while is_running(game):
        time.sleep(2)
    time.sleep(1)
    result = restore_game(game)
    if notice and result:
        notice(result)


def restore_stale_sessions(games: list[dict]) -> list[str]:
    notes = []
    for game in games:
        if read_session(game) and not is_running(game):
            result = restore_game(game)
            if result:
                notes.append(game.get("name", "Jogo") + ": " + result)
    return notes
