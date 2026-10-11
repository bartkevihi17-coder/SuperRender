"""Persistencia local e reconciliacao de jogos detectados.

Nenhum caminho particular entra no GitHub: dados ficam em %LOCALAPPDATA%.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

APP_DATA = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / ".local" / "share")) / "SuperRender"
DB_FILE = APP_DATA / "library.json"
_write_lock = threading.RLock()


def game_id(source: str, identifier: str) -> str:
    digest = hashlib.sha256((source.lower() + "|" + str(identifier).casefold()).encode("utf-8")).hexdigest()[:16]
    return source.lower().replace(" ", "_") + ":" + digest


def compact_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def load() -> dict:
    try:
        data = json.loads(DB_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("games"), list):
            return data
    except (OSError, ValueError, TypeError):
        pass
    return {"version": 2, "games": [], "settings": {}}


def save(data: dict) -> None:
    with _write_lock:
        APP_DATA.mkdir(parents=True, exist_ok=True)
        tmp = DB_FILE.with_suffix(".new")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(DB_FILE)


def sync_found(existing: list[dict], discovered: list[dict]) -> list[dict]:
    """Preserva favoritos, caminhos manuais e historico; evita duplicacoes."""
    old = {g["id"]: g for g in existing if g.get("id")}
    dedup: list[dict] = []
    by_exe: set[str] = set()
    by_name: set[str] = set()
    by_location: set[tuple[str, str]] = set()
    seen_ids: set[str] = set()
    for found in discovered:
        ident = found.get("id")
        if not ident or ident in seen_ids:
            continue
        seen_ids.add(ident)
        exe = str(found.get("exe") or "").casefold()
        loc = str(found.get("install_dir") or "").casefold().rstrip("\\/")
        normalized = compact_name(found.get("name") or "")
        if normalized and normalized in by_name:
            continue
        if exe and exe in by_exe:
            continue
        if loc and normalized and (loc, normalized) in by_location:
            continue
        if exe:
            by_exe.add(exe)
        if normalized:
            by_name.add(normalized)
        if loc and normalized:
            by_location.add((loc, normalized))
        entry = dict(found)
        before = old.get(ident, {})
        entry.update({k: before[k] for k in ("favorite", "hidden", "last_played") if k in before})
        entry["available"] = True
        dedup.append(entry)

    # Jogos cadastrados manualmente nao desaparecem ao atualizar a biblioteca.
    for ident, old_entry in old.items():
        if ident in seen_ids:
            continue
        if old_entry.get("source") == "Manual":
            stored = dict(old_entry)
            target = stored.get("target", "")
            stored["available"] = bool(target and Path(target).exists())
            if not any(compact_name(g.get("name", "")) == compact_name(stored.get("name", ""))
                       and g.get("exe") == stored.get("exe") for g in dedup):
                dedup.append(stored)
    return sorted(dedup, key=lambda g: (not g.get("favorite", False), g.get("name", "").casefold()))


def update_game(game: dict, **fields) -> dict:
    with _write_lock:
        data = load()
        games = data["games"]
        for index, item in enumerate(games):
            if item.get("id") == game["id"]:
                games[index] = {**item, **fields}
                save(data)
                return games[index]
        raise KeyError(game["id"])


def add_manual(path: Path, name: str = "") -> dict:
    path = path.resolve()
    if not path.is_file() or path.suffix.lower() not in (".exe", ".lnk", ".bat", ".cmd"):
        raise ValueError("Selecione um executavel ou atalho valido (.exe/.lnk/.bat/.cmd).")
    kind = "shortcut" if path.suffix.lower() == ".lnk" else "exe"
    game = {
        "id": game_id("manual", str(path)), "name": name.strip() or path.stem,
        "source": "Manual", "kind": kind, "target": str(path), "args": [],
        "exe": str(path) if path.suffix.lower() == ".exe" else "",
        "install_dir": str(path.parent), "icon_source": str(path),
        "available": True, "favorite": False, "hidden": False,
    }
    with _write_lock:
        data = load()
        data["games"] = [g for g in data["games"] if g.get("id") != game["id"]] + [game]
        save(data)
    return game


def remove_game(ident: str) -> None:
    with _write_lock:
        data = load()
        data["games"] = [g for g in data["games"] if g.get("id") != ident]
        save(data)


def played(ident: str) -> None:
    with _write_lock:
        data = load()
        for game in data["games"]:
            if game.get("id") == ident:
                game["last_played"] = datetime.now().isoformat(timespec="seconds")
                break
        save(data)
