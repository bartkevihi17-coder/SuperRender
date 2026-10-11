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
run([
    "--clean","--noconfirm","--onefile","--windowed",
    "--icon","assets/SuperRender.ico",
    "--add-data","assets/SuperRender.ico;assets",
    "--add-data","assets/SuperRender.png;assets",
    "--add-data","third_party/PresentMon-1.10.0-x64.exe;third_party",
    "--add-data","third_party/PresentMon-LICENSE.txt;third_party",
    "--name","SuperRender",
    "--distpath","dist",
    "run.pyw",
])
