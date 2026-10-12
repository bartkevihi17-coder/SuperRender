"""Patch the pinned upstream LFG source for SuperRender's quality-first mode.

We deliberately keep the patch small and auditable. The upstream repository is
GPL-3.0 and is cloned at an exact commit by GitHub Actions.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Upstream LFG changed; patch target missing: {label}")
    return text.replace(old, new, 1)


def patch(root: Path) -> None:
    header = root / "LFG" / "Pipeline" / "Generation" / "FrameGeneration.h"
    present = root / "LFG" / "Hook" / "Present" / "Present.cpp"

    h = header.read_text(encoding="utf-8-sig")
    h = replace_once(
        h,
        "float RenderScale = 0.67f; // 0.5 - 1.0 - Balanced: 0.67f",
        "float RenderScale = 1.0f; // SuperRender: never lower the game's visible resolution by default",
        "quality-first RenderScale",
    )
    header.write_text(h, encoding="utf-8", newline="\n")

    p = present.read_text(encoding="utf-8-sig")
    p = replace_once(
        p,
        "#include <chrono>",
        "#include <chrono>\n#include <algorithm>\n#include <string>",
        "extra includes",
    )
    p = replace_once(
        p,
        "static bool showMenu = true;",
        "static bool showMenu = false;",
        "menu starts closed",
    )

    needle = "\t\t\tFrameGeneration::Instance().Initialize(Present::Device);"
    config = r'''
			FrameGeneration::Instance().Initialize(Present::Device);

			// SuperRender per-process settings. The host writes this only after
			// measuring the real game FPS, so 30 FPS can use 2x while ~22 FPS
			// can use 3x. Game graphics remain untouched: RenderScale defaults
			// to 100%, and only the intermediate-frame algorithm changes.
			wchar_t localAppData[32768] = {};
			if (GetEnvironmentVariableW(L"LOCALAPPDATA", localAppData, 32768) > 0)
			{
				std::wstring cfg = std::wstring(localAppData) +
					L"\\SuperRender\\framegen-" +
					std::to_wstring(GetCurrentProcessId()) + L".ini";
				if (GetFileAttributesW(cfg.c_str()) != INVALID_FILE_ATTRIBUTES)
				{
					auto& sr = FrameGeneration::Instance().GetSettings();
					auto readInt = [&](const wchar_t* key, int fallback) -> int {
						return (int)GetPrivateProfileIntW(L"framegen", key, fallback, cfg.c_str());
					};
					sr.MultiFrameCount = std::clamp(readInt(L"MultiFrameCount", 1), 0, 3);
					sr.EnableDynamicRatio = readInt(L"EnableDynamicRatio", 0) != 0;
					sr.DynamicTargetFPS = std::clamp(readInt(L"DynamicTargetFPS", 60), 30, 360);
					sr.RenderScale = std::clamp(readInt(L"RenderScalePercent", 100) / 100.0f, 0.5f, 1.0f);
					sr.OpticalFlowAlgorithm = std::clamp(readInt(L"OpticalFlowAlgorithm", 0), 0, 2);
					sr.BlockSize = std::clamp(readInt(L"BlockSize", 16), 4, 64);
					sr.SearchRadius = std::clamp(readInt(L"SearchRadius", 8), 2, 64);
					sr.MaxPyramidLevel = std::clamp(readInt(L"MaxPyramidLevel", 1), 0, 4);
					sr.MinPyramidLevel = std::clamp(readInt(L"MinPyramidLevel", 0), 0, 4);
					sr.EnableBiDirFlow = readInt(L"EnableBiDirFlow", 0) != 0;
					sr.EnableAdaptiveBlock = readInt(L"EnableAdaptiveBlock", 0) != 0;
					sr.EnableSubPixel = readInt(L"EnableSubPixel", 1) != 0;
					sr.EnableMotionSmoothing = readInt(L"EnableMotionSmoothing", 0) != 0;
					sr.LowLatencyMode = readInt(L"LowLatencyMode", 1) != 0;
					sr.DisableVSync = readInt(L"DisableVSync", 1) != 0;
					sr.EnableEdgeProtection = readInt(L"EdgeProtection", 1) != 0;
					sr.GhostingReduction = std::clamp(readInt(L"GhostingReductionPercent", 35) / 100.0f, 0.0f, 1.0f);
					sr.RcasStrength = std::clamp(readInt(L"RcasStrengthPercent", 10) / 100.0f, 0.0f, 1.0f);
					sr.ShowDebugOverlay = readInt(L"ShowDebugOverlay", 1) != 0;
				}
			}
'''
    if needle not in p:
        raise RuntimeError("Upstream LFG changed; initialization target missing")
    p = p.replace(needle, config.strip("\n"), 1)
    present.write_text(p, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    patch(Path(args.source).resolve())
    print("LFG patched for SuperRender quality-first adaptive mode.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
