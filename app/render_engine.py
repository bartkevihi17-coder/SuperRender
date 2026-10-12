"""Render (Beta): adaptive planning layer for the SuperRender hybrid engine.

Quality-first rule:
- Render never applies the Potato/Optimized graphics reductions.
- A pending SuperRender graphics session is restored before Render starts.
- Real frame generation is preferred through a separate Windows Graphics
  Capture/D3D11 helper; no DLL is injected into the game.
- Protected/competitive titles stay on the non-invasive path by default.

The native backend is intentionally experimental and offline-oriented. It
captures a game window externally and does not attempt any anticheat bypass.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from .library import APP_DATA
from .render_backend import framegen_available_for_game


_RENDER_SESSIONS = APP_DATA / "render_sessions"
PROTECTED_HINTS = (
    "valorant", "fortnite", "league of legends", "counter-strike",
    "counter strike", "apex legends", "call of duty", "warzone",
    "rainbow six", "overwatch",
)


@dataclass(frozen=True)
class RenderCapabilities:
    windows: bool
    executable_known: bool
    gpu_name: str
    integrated_adapter: bool
    protected_hint: bool
    framegen_available: bool = False


@dataclass(frozen=True)
class RenderPlan:
    backend: str
    reconstruction: str
    frame_generation: str
    target_multiplier: int
    requires_offline: bool
    reason: str
    gpu_name: str

    @property
    def label(self) -> str:
        names = {
            "integrated": "Integrado",
            "external-framegen": "FrameGen Externo",
            "external": "Externo",
            "light": "Leve",
        }
        return names.get(self.backend, self.backend.title())


def _gpu_name() -> str:
    """Best-effort Windows GPU discovery without adding dependencies."""
    if os.name != "nt":
        return platform.machine() or "desconhecida"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    commands = (
        [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            "(Get-CimInstance Win32_VideoController | "
            "Where-Object {$_.Name} | Select-Object -ExpandProperty Name) -join ' | '",
        ],
        ["wmic.exe", "path", "win32_VideoController", "get", "name", "/value"],
    )
    for cmd in commands:
        try:
            output = subprocess.check_output(
                cmd, stderr=subprocess.DEVNULL, timeout=3,
                creationflags=flags, text=True, encoding="utf-8",
                errors="replace",
            ).strip()
        except (OSError, subprocess.SubprocessError):
            continue
        if not output:
            continue
        if "Name=" in output:
            names = [line.split("=", 1)[1].strip() for line in output.splitlines()
                     if line.startswith("Name=") and line.split("=", 1)[1].strip()]
            if names:
                return " | ".join(names)
        return " ".join(output.split())
    return "GPU nao identificada"


def _protected_hint(game: dict) -> bool:
    text = " ".join(str(game.get(k) or "") for k in ("name", "exe", "target")).casefold()
    return any(hint in text for hint in PROTECTED_HINTS)


def inspect_capabilities(game: dict) -> RenderCapabilities:
    exe = Path(str(game.get("exe") or ""))
    integrated = bool(game.get("render_integration"))
    protected = _protected_hint(game)
    return RenderCapabilities(
        windows=os.name == "nt",
        executable_known=exe.is_file(),
        gpu_name=_gpu_name(),
        integrated_adapter=integrated,
        protected_hint=protected,
        framegen_available=(not protected and framegen_available_for_game(game)),
    )


def choose_plan(game: dict, caps: RenderCapabilities | None = None) -> RenderPlan:
    """Select the best currently available quality-first path."""
    caps = caps or inspect_capabilities(game)
    if not caps.windows:
        return RenderPlan(
            "light", "none", "off", 1, False,
            "Render Beta requer Windows; usando caminho leve.", caps.gpu_name,
        )

    if caps.protected_hint:
        return RenderPlan(
            "light", "preserve-native", "off", 1, False,
            "Jogo com indicio de protecao/online: Render experimental desativado por politica de seguranca.",
            caps.gpu_name,
        )

    if caps.integrated_adapter:
        return RenderPlan(
            "integrated", "temporal", "adaptive", 4, True,
            "Adaptador temporal verificado disponivel; preservando qualidade nativa.",
            caps.gpu_name,
        )

    if caps.framegen_available:
        return RenderPlan(
            "external-framegen", "motion-block-adaptive", "adaptive-to-target", 4, True,
            "Backend externo WGC/D3D11 disponivel; captura a janela sem injetar DLL e cria frames intermediarios.",
            caps.gpu_name,
        )

    if caps.executable_known:
        return RenderPlan(
            "external", "preserve-native", "off", 1, False,
            "Executavel reconhecido, mas esta compilacao ainda nao inclui um backend compativel.",
            caps.gpu_name,
        )

    return RenderPlan(
        "light", "preserve-native", "off", 1, False,
        "Executavel real nao identificado; preservando configuracao do jogo sem prometer Frame Generation.",
        caps.gpu_name,
    )


def _session_path(game: dict) -> Path:
    """Return a Windows-safe, stable session filename for any game identifier.

    Library IDs can contain ':' (for example Windows shortcut IDs). On NTFS a
    colon is interpreted as an alternate data stream, which made os.replace()
    fail with WinError 87. Hashing the logical ID also avoids every other
    reserved filename character and excessively long paths.
    """
    logical_id = str(game.get("id") or game.get("exe") or game.get("name") or "game")
    digest = hashlib.sha256(logical_id.encode("utf-8", errors="replace")).hexdigest()[:24]
    return _RENDER_SESSIONS / f"game-{digest}-latest.json"


def record_plan(game: dict, plan: RenderPlan) -> Path:
    _RENDER_SESSIONS.mkdir(parents=True, exist_ok=True)
    path = _session_path(game)
    data = {
        "version": 2,
        "session_id": uuid.uuid4().hex,
        "created_unix": time.time(),
        "game_id": game.get("id"),
        "game_name": game.get("name"),
        "exe": game.get("exe"),
        "quality_policy": "high-adapter-or-preserve",
        "plan": asdict(plan),
        "metrics": {
            "base_fps": None,
            "presented_fps": None,
            "capture_fps": None,
            "generated_fps": None,
            "generated_between": None,
            "engine_cost_ms": None,
            "latency_ms": None,
        },
    }
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)
    return path


def update_session_metrics(game: dict, **metrics) -> None:
    path = _session_path(game)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        stored = data.setdefault("metrics", {})
        for key, value in metrics.items():
            if key in stored:
                stored[key] = value
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, path)
    except (OSError, ValueError, TypeError):
        pass


def prepare_render(game: dict) -> RenderPlan:
    plan = choose_plan(game)
    record_plan(game, plan)
    return plan


def plan_summary(plan: RenderPlan) -> str:
    parts = [
        f"Render Beta: {plan.label}",
        "qualidade alta quando ha adaptador; senao preservada",
        f"geracao {plan.frame_generation}",
    ]
    if plan.gpu_name:
        parts.append(plan.gpu_name)
    return " | ".join(parts)
