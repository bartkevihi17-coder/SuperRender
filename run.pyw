"""Entrada desktop Windows: uma janela Qt nativa, sem console."""
import os
import traceback
from pathlib import Path

if __name__=="__main__":
    try:
        from app.qt_gui import main
        main()
    except BaseException:
        dest=Path(os.environ.get("LOCALAPPDATA") or Path.home())/"SuperRender"
        dest.mkdir(parents=True,exist_ok=True)
        (dest/"startup-error.log").write_text(traceback.format_exc(),encoding="utf-8")
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None,"Falha ao abrir SuperRender. Consulte startup-error.log em %LOCALAPPDATA%\\SuperRender.",
                "SuperRender",0x10)
        except Exception:
            pass
