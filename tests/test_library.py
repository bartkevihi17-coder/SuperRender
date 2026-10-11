"""Testes do nucleo da biblioteca, sem abrir jogos reais."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import library
from app.launcher import eligible_for_priority


class LibraryTests(unittest.TestCase):
    def test_prefers_store_and_avoids_duplicate_shortcut(self):
        game_name = "Demo Racing 2026"
        entry_store = {
            "id": library.game_id("steam", "99292"), "name": game_name,
            "source": "Steam", "target": "steam://rungameid/99292",
            "exe": "", "install_dir": r"D:\SteamLibrary\steamapps\common\Demo Racing",
        }
        entry_link = {
            "id": library.game_id("shortcut", "demo"), "name": game_name,
            "source": "Atalho Windows", "target": r"C:\Users\Public\Desktop\Demo.lnk",
            "exe": "", "install_dir": r"D:\SteamLibrary\steamapps\common\Demo Racing",
        }
        found = library.sync_found([], [entry_store, entry_link])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["source"], "Steam")

    def test_stable_id(self):
        self.assertEqual(library.game_id("steam", "1234"), library.game_id("Steam", "1234"))
        self.assertNotEqual(library.game_id("steam", "1234"), library.game_id("epic", "1234"))

    def test_manual_add_and_remove_is_local(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            exe = root / "ExampleGame.exe"
            exe.write_bytes(b"example")
            with patch.object(library, "APP_DATA", root), patch.object(
                library, "DB_FILE", root / "library.json"
            ):
                item = library.add_manual(exe, "Example Game")
                saved = library.load()
                self.assertEqual(saved["games"][0]["name"], "Example Game")
                library.remove_game(item["id"])
                self.assertEqual(library.load()["games"], [])

    def test_competitive_games_are_not_optimized(self):
        for name in ("VALORANT", "Fortnite", "League of Legends"):
            with self.subTest(name=name):
                self.assertFalse(eligible_for_priority({"name": name}))
        self.assertTrue(eligible_for_priority({"name": "NBA 2K20"}))


if __name__ == "__main__":
    unittest.main()
