"""Render (Beta): adaptive planning layer for the SuperRender hybrid engine.

This module does not pretend to generate frames before a renderer exists.
It creates a stable contract between the launcher/UI and future native render
backends (external capture, integrated temporal reconstruction and lightweight
fallback), records the selected plan and keeps protected/online games on the
non-invasive path by default.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from .library import APP_DATA


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
    # Future adapters can set this only when they can expose motion/depth data
    # or another supported temporal-integration contract.
    integrated = bool(game.get("render_integration"))
    return RenderCapabilities(
        windows=os.name == "nt",
        executable_known=exe.is_file(),
        gpu_name=_gpu_name(),
        integrated_adapter=integrated,
        protected_hint=_protected_hint(game),
    )


def choose_plan(game: dict, caps: RenderCapabilities | None = None) -> RenderPlan:
    """Select the safest useful render path.

    Order:
      1. Integrated temporal path when a verified adapter exists.
      2. External capture/reconstruction path for normal desktop games.
      3. Lightweight path when capture cannot be prepared safely.

    Protected/online hints never select the future invasive integrated path
    automatically. This is policy, not an anticheat bypass mechanism.
    """
    caps = caps or inspect_capabilities(game)
    if not caps.windows:
        return RenderPlan(
            "light", "none", "off", 1, False,
            "Render Beta requer Windows; usando caminho leve.", caps.gpu_name,
        )

    if caps.integrated_adapter and not caps.protected_hint:
        return RenderPlan(
            "integrated", "temporal", "2x", 2, True,
            "Adaptador temporal verificado disponivel; priorizando dados internos da cena.",
            caps.gpu_name,
        )

    if caps.executable_known and not caps.protected_hint:
        return RenderPlan(
            "external", "spatial-adaptive", "2x-experimental", 2, False,
            "Sem adaptador temporal; selecionado pipeline externo com reconstrucao leve.",
            caps.gpu_name,
        )

    if caps.protected_hint:
        return RenderPlan(
            "light", "spatial-when-available", "off", 1, False,
            "Jogo com indicio de protecao/online: caminho nao invasivo selecionado automaticamente.",
            caps.gpu_name,
        )

    return RenderPlan(
        "light", "spatial-when-available", "off", 1, False,
        "Executavel real nao identificado; usando caminho leve ate haver captura verificavel.",
        caps.gpu_name,
    )


def _session_path(game: dict) -> Path:
    ident = str(game.get("id") or "game").replace("/", "_").replace("\\", "_")
    return _RENDER_SESSIONS / (ident + "-latest.json")


def record_plan(game: dict, plan: RenderPlan) -> Path:
    """Persist the selected plan for debugging and future benchmark decisions."""
    _RENDER_SESSIONS.mkdir(parents=True, exist_ok=True)
    path = _session_path(game)
    data = {
        "version": 1,
        "session_id": uuid.uuid4().hex,
        "created_unix": time.time(),
        "game_id": game.get("id"),
        "game_name": game.get("name"),
        "exe": game.get("exe"),
        "plan": asdict(plan),
        "metrics": {
            "base_fps": None,
            "presented_fps": None,
            "engine_cost_ms": None,
            "latency_ms": None,
        },
    }
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)
    return path


def prepare_render(game: dict) -> RenderPlan:
    plan = choose_plan(game)
    record_plan(game, plan)
    return plan


def plan_summary(plan: RenderPlan) -> str:
    parts = [
        f"Render Beta: {plan.label}",
        f"reconstrucao {plan.reconstruction}",
        f"geracao {plan.frame_generation}",
    ]
    if plan.gpu_name:
        parts.append(plan.gpu_name)
    return " | ".join(parts)
