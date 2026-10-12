"""Compilacao do aplicativo Qt em prioridade reduzida no Windows."""
import ctypes
import os
from pathlib import Path

if os.name=="nt":
    BELOW_NORMAL_PRIORITY_CLASS=0x00004000
    kernel=ctypes.windll.kernel32
    kernel.SetPriorityClass(kernel.GetCurrentProcess(),BELOW_NORMAL_PRIORITY_CLASS)

from PyInstaller.__main__ import run

ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT)

args=[
    "--clean","--noconfirm","--onefile","--windowed",
    "--icon","assets/SuperRender.ico",
    "--add-data","assets/SuperRender.ico;assets",
    "--add-data","assets/SuperRender.png;assets",
    "--add-data","third_party/PresentMon-1.10.0-x64.exe;third_party",
    "--add-data","third_party/PresentMon-LICENSE.txt;third_party",
    "--name","SuperRender",
    "--distpath",os.environ.get("SUPERRENDER_DIST_DIR","dist"),
]

# Built from this repository's native/framegen source. Development/source
# runs remain usable without it; Render Beta reports FG as unavailable until
# the helper exists rather than downloading or injecting anything.
for extra in (
    "third_party/SuperRenderFrameGen.exe",
    "third_party/SuperRenderFrameGen-SHA256.txt",
):
    if (ROOT/extra).is_file():
        args.extend(["--add-data",extra+";third_party"])

args.append("run.pyw")
run(args)
