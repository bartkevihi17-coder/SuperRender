"""Interface desktop nativa do SuperRender (Tkinter, sem servidor/HTML)."""
from __future__ import annotations

import os
import sys
import queue
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox

from .artwork import ensure_art, photo_file
from .discovery import discover
from .launcher import launch
from .library import add_manual, load, remove_game, save, sync_found, update_game

BG = "#0b1020"
SIDEBAR = "#10192b"
SURFACE = "#151f32"
SURFACE_2 = "#1b2840"
LINE = "#2c3a52"
TEXT = "#f0f5ff"
MUTED = "#91a2bd"
CYAN = "#6be4ed"
CYAN_DARK = "#164b5b"
PURPLE = "#9383f7"
DANGER = "#e98e96"
TILE_WIDTH = 272
FONT = "Segoe UI"


def button(parent, text, command, accent=False, small=False, width=None):
    bg = CYAN if accent else SURFACE_2
    fg = "#0b1520" if accent else TEXT
    active_bg = "#a2f2f6" if accent else "#2b3d58"
    widget = tk.Button(
        parent, text=text, command=command, font=(FONT, 9 if small else 10, "bold"),
        bg=bg, fg=fg, activebackground=active_bg, activeforeground=fg,
        borderwidth=0, relief="flat", highlightthickness=0,
        padx=12 if small else 16, pady=9 if small else 11,
        cursor="hand2", width=width,
    )
    widget.bind("<Enter>", lambda _e: widget.configure(bg=active_bg))
    widget.bind("<Leave>", lambda _e: widget.configure(bg=bg))
    return widget


def label(parent, value, size=10, color=TEXT, bold=False, **kwargs):
    return tk.Label(parent, text=value, fg=color, bg=parent.cget("bg"),
                    font=(FONT, size, "bold" if bold else "normal"), **kwargs)


def ellipsis(value: str, length: int = 42) -> str:
    return value if len(value) <= length else value[: length - 1] + "…"


class SuperRender(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SuperRender  |  Sua biblioteca de jogos")
        try:
            base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
            icon = base / "assets" / "SuperRender.ico"
            if icon.is_file():
                self.iconbitmap(str(icon))
        except (tk.TclError, OSError):
            pass
        self.configure(bg=BG)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = min(1280, max(960, int(sw * 0.90)))
        h = min(840, max(600, int(sh * 0.87)))
        self.geometry(f"{w}x{h}+{max(0,(sw-w)//2)}+{max(0,(sh-h)//2)}")
        self.minsize(930, 560)
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self.games = load().get("games", [])
        self.view = "Todos os jogos"
        self.show_count = 48
        self.search_var = tk.StringVar()
        self.messages = queue.Queue()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sr-artwork")
        self.awaiting_art = set()
        self.card_photos = []
        self.art_canvases = {}
        self.scan_busy = False
        self._render_task = None
        self._layout_cols = 0
        self._last_content_width = 0
        self._build()
        self.search_var.trace_add("write", lambda *_: self.schedule_render())
        self.bind("<F5>", lambda _e: self.scan_games())
        self.bind("<Control-f>", lambda _e: self.focus_search())
        self.after(100, self.drain_messages)
        self.after(400, self.scan_games)

    def close_app(self):
        try:
            self.executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            self.executor.shutdown(wait=False)
        self.destroy()

    def _build(self):
        self.sidebar = tk.Frame(self, width=218, bg=SIDEBAR, highlightbackground=LINE,
                                highlightthickness=1)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        brand = tk.Frame(self.sidebar, bg=SIDEBAR)
        brand.pack(fill="x", padx=23, pady=(27, 37))
        logo = tk.Canvas(brand, width=38, height=38, bg=SIDEBAR, highlightthickness=0)
        logo.pack(side="left")
        logo.create_rectangle(3, 3, 35, 35, fill=CYAN_DARK, outline=CYAN, width=1)
        logo.create_polygon(8, 27, 19, 10, 29, 10, 19, 25, 29, 25, 29, 28, 9, 28,
                            fill=CYAN, outline="")
        btxt = tk.Frame(brand, bg=SIDEBAR)
        btxt.pack(side="left", padx=9)
        label(btxt, "SUPER", 14, TEXT, bold=True, anchor="w").pack(fill="x")
        label(btxt, "RENDER", 10, CYAN, bold=True, anchor="w").pack(fill="x")

        label(self.sidebar, "BIBLIOTECA", 8, MUTED, bold=True,
              anchor="w").pack(fill="x", padx=24, pady=(4, 10))
        self.nav_frame = tk.Frame(self.sidebar, bg=SIDEBAR)
        self.nav_frame.pack(fill="x", padx=10)
        self.build_nav()

        tk.Frame(self.sidebar, bg=LINE, height=1).pack(fill="x", padx=18, pady=(26, 15))
        label(self.sidebar, "DESCOBERTA", 8, MUTED, bold=True, anchor="w").pack(
            fill="x", padx=24, pady=(2, 8))
        self.scan_btn = button(self.sidebar, "↻  Buscar jogos", self.scan_games)
        self.scan_btn.pack(fill="x", padx=17, pady=5)
        button(self.sidebar, "＋  Adicionar jogo", self.manual_game).pack(
            fill="x", padx=17, pady=5)
        self.scan_note = label(self.sidebar, "Windows • Biblioteca local", 8, MUTED,
                               wraplength=170, justify="left", anchor="w")
        self.scan_note.pack(side="bottom", fill="x", padx=22, pady=26)
        self.main_area = tk.Frame(self, bg=BG)
        self.main_area.pack(side="left", fill="both", expand=True)

        top = tk.Frame(self.main_area, bg=BG)
        top.pack(fill="x", padx=34, pady=(26, 16))
        headings = tk.Frame(top, bg=BG)
        headings.pack(side="left", fill="x", expand=True)
        label(headings, "BIBLIOTECA DE JOGOS", 9, CYAN, bold=True,
              anchor="w").pack(anchor="w")
        label(headings, "Pronto para jogar?", 27, TEXT, bold=True,
              anchor="w").pack(anchor="w", pady=(2, 1))
        label(headings, "Seus jogos em um só lugar. Sem instalações duplicadas.",
              10, MUTED, anchor="w").pack(anchor="w")

        search_holder = tk.Frame(top, bg=SURFACE, highlightbackground=LINE,
                                 highlightthickness=1, padx=10, pady=9)
        search_holder.pack(side="right", padx=(10, 0))
        label(search_holder, "⌕", 15, CYAN).pack(side="left", padx=(0, 7))
        entry = tk.Entry(search_holder, textvariable=self.search_var, font=(FONT, 10),
                         bg=SURFACE, fg=TEXT, insertbackground=CYAN, width=23,
                         relief="flat", highlightthickness=0, borderwidth=0)
        entry.pack(side="left", padx=3)
        self.search_entry = entry

        self.hero = tk.Frame(self.main_area, bg=SURFACE, highlightbackground=LINE,
                             highlightthickness=1)
        self.hero.pack(fill="x", padx=34, pady=(3, 17))
        hero_content = tk.Frame(self.hero, bg=SURFACE)
        hero_content.pack(side="left", fill="both", expand=True, padx=22, pady=17)
        label(hero_content, "SUPERRENDER  /  DESKTOP", 9, PURPLE, bold=True,
              anchor="w").pack(anchor="w")
        label(hero_content, "Sua coleção, do seu jeito.", 18, TEXT, bold=True,
              anchor="w").pack(anchor="w", pady=(7, 4))
        label(hero_content,
              "Inicie normalmente ou teste o perfil experimental de desempenho.",
              10, MUTED, anchor="w").pack(anchor="w")
        right = tk.Frame(self.hero, bg=SURFACE, padx=25, pady=24)
        right.pack(side="right")
        self.counter = label(right, "00", 30, CYAN, bold=True)
        self.counter.pack()
        label(right, "JOGOS ENCONTRADOS", 8, MUTED, bold=True).pack()

        tools = tk.Frame(self.main_area, bg=BG)
        tools.pack(fill="x", padx=34, pady=(2, 9))
        self.heading = label(tools, "Todos os jogos", 14, TEXT, bold=True, anchor="w")
        self.heading.pack(side="left")
        self.count_info = label(tools, "", 9, MUTED)
        self.count_info.pack(side="left", padx=10, pady=4)
        self.status = label(tools, "Pronto", 9, CYAN, anchor="e")
        self.status.pack(side="right")

        holder = tk.Frame(self.main_area, bg=BG)
        holder.pack(fill="both", expand=True, padx=(34, 22), pady=(2, 4))
        self.canvas = tk.Canvas(holder, bg=BG, borderwidth=0, highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar = tk.Scrollbar(holder, orient="vertical", command=self.canvas.yview,
                                 bg=SIDEBAR, troughcolor=BG, activebackground=CYAN)
        scrollbar.pack(side="right", fill="y")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.tile_area = tk.Frame(self.canvas, bg=BG)
        self.tile_window = self.canvas.create_window((0, 0), window=self.tile_area,
                                                     anchor="nw")
        self.tile_area.bind("<Configure>", self.configure_scroll)
        self.canvas.bind("<Configure>", self.resize_canvas)
        self.canvas.bind("<MouseWheel>", self.mouse_wheel)
        self.tile_area.bind("<MouseWheel>", self.mouse_wheel)

        footer = tk.Frame(self.main_area, bg=BG)
        footer.pack(fill="x", padx=34, pady=(5, 15))
        label(footer, "v0.2  •  Aplicativo nativo Python  •  Dados salvos somente neste PC",
              8, MUTED).pack(side="left")
        button(footer, "Sobre o modo otimizado", self.show_help, small=True).pack(
            side="right")
        self.render_cards()

    def build_nav(self):
        for widget in self.nav_frame.winfo_children():
            widget.destroy()
        entries = [("◫", "Todos os jogos"), ("☆", "Favoritos")]
        sources = sorted({g.get("source", "") for g in self.games if g.get("source")})
        entries += [("◈", s) for s in sources]
        for icon, name in entries:
            selected = self.view == name
            bg = "#20394c" if selected else SIDEBAR
            fg = CYAN if selected else MUTED
            item = tk.Frame(self.nav_frame, bg=bg)
            item.pack(fill="x", pady=2)
            tag = tk.Frame(item, width=3, bg=CYAN if selected else bg)
            tag.pack(side="left", fill="y")
            icon_label = tk.Label(item, text=icon, bg=bg, fg=fg, font=(FONT, 14),
                                  padx=11, pady=10)
            icon_label.pack(side="left")
            name_label = tk.Label(item, text=name, bg=bg, fg=TEXT if selected else MUTED,
                                  font=(FONT, 10, "bold" if selected else "normal"),
                                  anchor="w")
            name_label.pack(side="left", fill="x", expand=True)
            for widget in (item, icon_label, name_label):
                widget.bind("<Button-1>", lambda _e, v=name: self.switch_view(v))
                widget.configure(cursor="hand2")

    def switch_view(self, name):
        self.view = name
        self.show_count = 48
        self.build_nav()
        self.schedule_render()

    def focus_search(self):
        self.search_entry.focus_set()
        self.search_entry.select_range(0, tk.END)

    def configure_scroll(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def resize_canvas(self, event=None):
        if not event:
            return
        self.canvas.itemconfigure(self.tile_window, width=event.width)
        if abs(self._last_content_width - event.width) > 55:
            self._last_content_width = event.width
            self.schedule_render()

    def mouse_wheel(self, event):
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def schedule_render(self):
        if self._render_task:
            self.after_cancel(self._render_task)
        self._render_task = self.after(90, self.render_cards)

    def filtered(self):
        text = self.search_var.get().strip().casefold()
        games = [g for g in self.games if not g.get("hidden")]
        if self.view == "Favoritos":
            games = [g for g in games if g.get("favorite")]
        elif self.view != "Todos os jogos":
            games = [g for g in games if g.get("source") == self.view]
        if text:
            games = [g for g in games if text in g.get("name", "").casefold()
                     or text in g.get("source", "").casefold()]
        return sorted(games, key=lambda g: (
            not g.get("favorite", False), g.get("name", "").casefold()))

    def render_cards(self):
        self._render_task = None
        previous_scroll = self.canvas.yview()[0]
        for item in self.tile_area.winfo_children():
            item.destroy()
        self.card_photos.clear()
        self.art_canvases.clear()
        visible = self.filtered()
        self.heading.configure(text=self.view)
        self.counter.configure(text=f"{sum(bool(g.get('available', True)) for g in self.games):02d}")
        self.count_info.configure(text=f"({len(visible)})")
        columns = max(1, min(4, self.canvas.winfo_width() // (TILE_WIDTH + 12)))
        for col in range(columns):
            self.tile_area.grid_columnconfigure(col, weight=1, uniform="cards")
        self._layout_cols = columns
        limited = visible[:self.show_count]
        if not limited:
            blank = tk.Frame(self.tile_area, bg=SURFACE, padx=28, pady=32)
            blank.grid(row=0, column=0, sticky="nsew", padx=6, pady=10)
            label(blank, "Nenhum jogo por aqui ainda.", 15, TEXT, bold=True).pack(anchor="w")
            label(blank, "Use 'Buscar jogos' para encontrar instalacoes automaticamente.",
                  10, MUTED).pack(anchor="w", pady=(7, 15))
            button(blank, "Buscar jogos agora", self.scan_games, accent=True).pack(anchor="w")
            return
        for i, game in enumerate(limited):
            card = tk.Frame(self.tile_area, bg=SURFACE, highlightbackground=LINE,
                            highlightthickness=1)
            card.grid(row=i // columns, column=i % columns, sticky="nsew",
                      padx=(0, 12), pady=(0, 13))
            art = tk.Canvas(card, height=146, bg="#1b283d", highlightthickness=0,
                            width=TILE_WIDTH-12)
            art.pack(fill="x")
            self.art_canvases[game["id"]] = art
            local_photo = photo_file(game)
            if local_photo.is_file():
                try:
                    pic = tk.PhotoImage(file=str(local_photo))
                    self.card_photos.append(pic)
                    art.create_image(0, 0, anchor="nw", image=pic)
                except tk.TclError:
                    self.placeholder(art, game)
            else:
                self.placeholder(art, game)
                self.load_art_async(game)
            info = tk.Frame(card, bg=SURFACE)
            info.pack(fill="x", padx=14, pady=(13, 14))
            row = tk.Frame(info, bg=SURFACE)
            row.pack(fill="x")
            label(row, ellipsis(game.get("source", "Local"), 18).upper(),
                  8, CYAN, bold=True).pack(side="left")
            star = "★" if game.get("favorite") else "☆"
            fav_btn = tk.Label(row, text=star, bg=SURFACE,
                               fg=CYAN if game.get("favorite") else MUTED,
                               font=(FONT, 15), cursor="hand2")
            fav_btn.pack(side="right")
            fav_btn.bind("<Button-1>", lambda _e, g=game: self.favorite(g))
            name = label(info, ellipsis(game.get("name") or "Jogo", 42),
                         12, TEXT, bold=True, anchor="w", justify="left",
                         wraplength=234)
            name.pack(fill="x", pady=(9, 2))
            label(info, "Detectado automaticamente" if game.get("source") != "Manual"
                  else "Adicionado manualmente", 9, MUTED,
                  anchor="w").pack(fill="x", pady=(1, 13))
            actions = tk.Frame(info, bg=SURFACE)
            actions.pack(fill="x")
            button(actions, "Normal", lambda g=game: self.launch_game(g, "normal"),
                   small=True).pack(side="left", fill="x", expand=True, padx=(0, 4))
            button(actions, "⚡ Otimizado",
                   lambda g=game: self.launch_game(g, "optimized"),
                   accent=True, small=True).pack(side="left", fill="x", expand=True)
            details = tk.Label(info, text="Detalhes e caminho  ↗", bg=SURFACE,
                               fg=MUTED, cursor="hand2", font=(FONT, 9))
            details.pack(anchor="w", pady=(11, 0))
            details.bind("<Button-1>", lambda _e, g=game: self.details(g))
            art.bind("<Button-1>", lambda _e, g=game: self.details(g))
            art.configure(cursor="hand2")
        if len(visible) > len(limited):
            bottom = tk.Frame(self.tile_area, bg=BG)
            bottom.grid(row=(len(limited) + columns - 1) // columns,
                        column=0, columnspan=columns, pady=20)
            button(bottom, f"Ver mais jogos ({len(visible) - len(limited)})",
                   self.more_games).pack()
        self.update_idletasks()
        self.configure_scroll()
        self.canvas.yview_moveto(previous_scroll)

    def more_games(self):
        self.show_count += 48
        self.render_cards()

    def placeholder(self, canvas: tk.Canvas, game: dict):
        # Imagem de fallback sintetizada pela GUI, sem arte falsa de franquias.
        source = game.get("source", "")
        palette = {"Steam": "#233b62", "Epic Games": "#3b3458",
                   "Riot Games": "#573b4b", "GOG": "#40466c",
                   "Pasta local": "#1b4a52"}
        base = palette.get(source, "#24334d")
        canvas.create_rectangle(0, 0, 420, 160, fill=base, outline="")
        for x in range(-100, 420, 34):
            canvas.create_line(x, 0, x+90, 146, fill="#31415f", width=1)
        initial = "".join(piece[0] for piece in game.get("name", "?").split()[:2]).upper()
        canvas.create_text(132, 64, text=initial or "SR",
                           font=(FONT, 37, "bold"), fill="#d8e8fa")
        canvas.create_text(132, 120, text=source.upper(), font=(FONT, 9, "bold"),
                           fill="#a7bdd4")

    def load_art_async(self, game: dict):
        key = game.get("id")
        if (not key or key in self.awaiting_art or
                photo_file(game).with_suffix(".missing").is_file()):
            return
        self.awaiting_art.add(key)
        def work():
            try:
                ensure_art(game)
            except Exception:
                pass
            self.messages.put(("art", key))
        self.executor.submit(work)

    def favorite(self, game):
        new_value = not game.get("favorite", False)
        try:
            update_game(game, favorite=new_value)
        except KeyError:
            pass
        game["favorite"] = new_value
        self.render_cards()

    def launch_game(self, game, mode):
        self.set_status("Abrindo " + game.get("name", "jogo") + "...")
        try:
            answer = launch(game, mode, notify=lambda message: self.messages.put(("message", message)))
        except Exception as e:
            messagebox.showerror("Nao foi possivel iniciar", str(e), parent=self)
            self.set_status("Erro ao iniciar.")
            return
        self.set_status(answer)
        for g in self.games:
            if g.get("id") == game.get("id"):
                g["last_played"] = "Agora"
        messagebox.showinfo("SuperRender", answer, parent=self)

    def set_status(self, value):
        self.status.configure(text=ellipsis(value, 64))

    def scan_games(self):
        if self.scan_busy:
            return
        self.scan_busy = True
        self.scan_btn.configure(state="disabled")
        self.set_status("Procurando jogos...")
        self.scan_note.configure(text="Analisando bibliotecas e unidades locais...")
        def worker():
            try:
                games = discover(progress=lambda message: self.messages.put(("progress", message)))
                self.messages.put(("done", games))
            except Exception as exc:
                self.messages.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True, name="sr-discovery").start()

    def drain_messages(self):
        try:
            while True:
                msg = self.messages.get_nowait()
                if msg[0] == "progress":
                    self.set_status(msg[1])
                elif msg[0] == "done":
                    data = load()
                    data["games"] = sync_found(data.get("games", []), msg[1])
                    save(data)
                    self.games = data["games"]
                    self.scan_busy = False
                    self.scan_btn.configure(state="normal")
                    self.scan_note.configure(text=f"{len(self.games)} jogos • Dados locais")
                    self.set_status(f"Busca concluida: {len(self.games)} jogos.")
                    self.build_nav()
                    self.schedule_render()
                elif msg[0] == "art":
                    self.awaiting_art.discard(msg[1])
                    game_canvas = self.art_canvases.get(msg[1])
                    found_photo = next((g for g in self.games if g.get("id") == msg[1]), None)
                    if game_canvas and found_photo and photo_file(found_photo).is_file():
                        try:
                            pic = tk.PhotoImage(file=str(photo_file(found_photo)))
                            self.card_photos.append(pic)
                            game_canvas.delete("all")
                            game_canvas.create_image(0, 0, anchor="nw", image=pic)
                        except tk.TclError:
                            pass
                elif msg[0] == "error":
                    self.scan_busy = False
                    self.scan_btn.configure(state="normal")
                    self.set_status("Erro ao procurar jogos.")
                    messagebox.showerror("SuperRender", msg[1], parent=self)
                elif msg[0] == "message":
                    self.set_status(msg[1])
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(150, self.drain_messages)

    def manual_game(self):
        path = filedialog.askopenfilename(
            parent=self, title="Selecione o executavel do jogo",
            filetypes=[("Jogos e atalhos", "*.exe *.lnk *.bat *.cmd"),
                       ("Executaveis", "*.exe"), ("Todos os arquivos", "*.*")])
        if not path:
            return
        try:
            game = add_manual(Path(path))
        except (OSError, ValueError) as exc:
            messagebox.showerror("Erro ao adicionar", str(exc), parent=self)
            return
        self.games = sync_found(load().get("games", []), self.games)
        self.view = "Todos os jogos"
        self.build_nav()
        self.render_cards()
        self.set_status("Jogo adicionado: " + game["name"])

    def details(self, game):
        dialog = tk.Toplevel(self)
        dialog.title("SuperRender - " + game.get("name", "Jogo"))
        dialog.geometry("630x390")
        dialog.minsize(520, 330)
        dialog.configure(bg=BG)
        dialog.transient(self)
        frame = tk.Frame(dialog, bg=BG, padx=25, pady=21)
        frame.pack(fill="both", expand=True)
        label(frame, game.get("name") or "Jogo", 19, TEXT, bold=True,
              anchor="w").pack(fill="x")
        label(frame, game.get("source") or "Local", 11, CYAN, anchor="w").pack(
            fill="x", pady=(3, 18))
        for title, value in (
            ("COMANDO DE INICIO", game.get("target", "")),
            ("PASTA DE INSTALACAO", game.get("install_dir", "")),
            ("TIPO", game.get("kind", "")),
        ):
            label(frame, title, 9, MUTED, bold=True, anchor="w").pack(fill="x", pady=(6, 2))
            field = tk.Entry(frame, bg=SURFACE, fg=TEXT, font=(FONT, 9), relief="flat",
                             highlightthickness=0, readonlybackground=SURFACE)
            field.insert(0, str(value))
            field.configure(state="readonly")
            field.pack(fill="x", ipady=6)
        buttons = tk.Frame(frame, bg=BG)
        buttons.pack(fill="x", pady=(18, 0))
        button(buttons, "Iniciar normal", lambda: self.launch_game(game, "normal"),
               small=True).pack(side="left", padx=(0, 8))
        button(buttons, "⚡ Iniciar otimizado",
               lambda: self.launch_game(game, "optimized"),
               accent=True, small=True).pack(side="left", padx=(0, 8))
        button(buttons, "Remover", lambda: self.remove_from_library(game, dialog),
               small=True).pack(side="right")

    def remove_from_library(self, game, dialog):
        if not messagebox.askyesno("Remover da biblioteca",
                                   "Remover este item da biblioteca? O jogo nao sera desinstalado.",
                                   parent=dialog):
            return
        remove_game(game["id"])
        self.games = load()["games"]
        dialog.destroy()
        self.build_nav()
        self.render_cards()

    def show_help(self):
        messagebox.showinfo(
            "SuperRender - Modo otimizado",
            "Esta versao experimental utiliza somente ajustes reversiveis de prioridade "
            "de processo no Windows quando o executavel e identificado.\n\n"
            "Nao reduz resolucao, remove sombras, injeta DLL, modifica o jogo ou "
            "contorna DirectX/anticheat. Jogos com protecao online nao sao "
            "alterados automaticamente.\n\n"
            "O aumento de FPS nao e garantido. Benchmarks e melhorias na "
            "renderizacao serao fases posteriores.",
            parent=self,
        )


def main():
    app = SuperRender()
    app.mainloop()
