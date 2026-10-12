"""Quality adapters used by Render (Beta).

Frame generation is game-agnostic where the graphics API is compatible.
Changing an individual game's quality settings is not: every game stores them
differently. This registry keeps those concerns separate.

Adapters return *temporary* changes. optimization.py already backs up the
original config and restores it after the game closes, so Render can request a
quality-first preset without permanently taking over the user's settings.
"""
from __future__ import annotations

from collections.abc import Callable


QualityAdapter = Callable[[dict], dict]


def _nba2k20_high(current: dict) -> dict:
    """High, not Ultra: preserve resolution and avoid brute-force AA.

    NBA's documented values use zero for the highest LOD on most detail
    controls. Shadows=1 is High (0 is Ultra). MSAA/SSAA stay disabled because
    they multiply pixel cost rather than scene quality, which is exactly the
    work the Frame Generation experiment should avoid duplicating.
    """
    return {
        "OVERALL_QUALITY": 4,  # Custom: individual values below are honored.
        "WINDOWMODE": 2,        # Borderless: required by the external presenter.
        "VSYNC": 0,
        "BUFFERCOUNT": 1,
        "MAXANISOTROPY": 16,
        "ALLOW_BLURRY_UI": False,
        "TEXTURELOD": 0,
        "SHADER_DETAIL": 0,
        "SHADOW_DETAIL": 1,
        "CACHE_SPOT_SHADOWS": True,
        "CACHE_SUN_SHADOWS": True,
        "TEMPORALAA": True,
        "AMBIENT_OCCLUSION": True,
        "VOLUMETRIC_LIGHTING": True,
        "DEPTH_OF_FIELD": True,
        "MOTION_BLUR": False,
        "BLOOM": True,
        "FLOOR_REFLECTIONS": True,
        "MIRROR_REFLECTIONS": True,
        "PLAYERLOD": 0,
        "MEDIAPEOPLELOD": 0,
        "CROWDLOD": 0,
        "HAIRLOD": 0,
        "MSAA": 0,
        "MSAAQUALITY": 0,
        "SSAA": 0,
        "ENHANCEDAA": False,
        "D3D_INTERNAL_THREADING_OPTIMIZATIONS": True,
        "CACHE_SPOT_SHADOWS": True,
        "CACHE_SUN_SHADOWS": True,
    }


QUALITY_ADAPTERS: dict[str, QualityAdapter] = {
    "nba2k20": _nba2k20_high,
}


def has_quality_adapter(adapter: str | None) -> bool:
    return bool(adapter and adapter in QUALITY_ADAPTERS)


def render_quality_changes(adapter: str | None, current: dict) -> dict:
    fn = QUALITY_ADAPTERS.get(adapter or "")
    if fn is None:
        return {}
    changes = fn(dict(current))
    # Resolution and monitor are never changed. A known adapter may switch the
    # presentation mode (for example exclusive fullscreen -> borderless) when
    # the external compositor needs DWM visibility; the original is restored.
    for forbidden in ("WIDTH", "HEIGHT", "WINDOW_X", "WINDOW_Y", "MONITOR"):
        changes.pop(forbidden, None)
    return changes
