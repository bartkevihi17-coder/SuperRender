# Third-party components

## Lufzy's Frame Generation (LFG)

The experimental DirectX 11 Frame Generation backend is built from
`furkan-1337/LFG` at commit
`cd1a2fa2b4fb26c1b18f13e79ea65bae67bc6531`.

- Upstream: https://github.com/furkan-1337/LFG
- License: GNU GPL v3
- Local license copy: `third_party/LFG-LICENSE.txt`
- SuperRender patch: `scripts/patch_lfg.py`

The build applies a small, auditable SuperRender patch: native visual quality
is preserved by default, the in-game menu starts closed, and settings are read
from a per-process INI written by SuperRender after measuring the base FPS.

SuperRender does not attempt to bypass anticheat. The native injection backend
is only selected automatically for non-protected games and is intended for
offline experimentation.

## PresentMon

PresentMon is redistributed under its upstream license. See
`third_party/PresentMon-LICENSE.txt`.
