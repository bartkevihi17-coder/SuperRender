"""Entrada Windows do SuperRender: janela nativa, sem console."""
import os
import traceback
from pathlib import Path

if __name__ == "__main__":
    try:
        from app.gui import main
        main()
    except Exception:
        folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SuperRender"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "startup-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("SuperRender", "Falha ao iniciar. Veja startup-error.log em %LOCALAPPDATA%\\SuperRender.")
            root.destroy()
        except Exception:
            pass
