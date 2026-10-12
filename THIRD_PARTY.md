# Third-party components

## PresentMon

PresentMon is redistributed under its upstream license. See
`third_party/PresentMon-LICENSE.txt`.

## External Frame Generation helper

`SuperRenderFrameGen.exe` is **not a third-party binary**. It is compiled
from this repository's source in `native/framegen/` by GitHub Actions and is
covered by the SuperRender GPL-3.0 license.

An earlier research branch evaluated an injected LFG-based backend. That
binary is no longer bundled or loaded. The current Render Beta architecture
uses Windows Graphics Capture and a separate D3D11 process, so it does not
load a DLL into the game's process.
