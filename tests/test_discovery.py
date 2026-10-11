"""Testes sem tocar em jogos reais, sem abrir aplicativos externos."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import discovery
from app.library import game_id, sync_found


class DiscoveryTests(unittest.TestCase):
    def test_steam_appmanifest_from_arbitrary_library(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            apps = root / "steamapps"
            installed = apps / "common" / "Game Anywhere"
            installed.mkdir(parents=True)
            (installed / "GameAnywhere.exe").write_bytes(b"X" * 200_000)
            (apps / "appmanifest_123456.acf").write_text(
                '"AppState"\n{\n"appid" "123456"\n"name" "Game Anywhere"\n'
                '"installdir" "Game Anywhere"\n}', encoding="utf-8"
            )
            with patch.object(discovery, "steam_roots", return_value={root}):
                result = discovery.scan_steam()
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["source"], "Steam")
            self.assertEqual(result[0]["target"], "steam://rungameid/123456")
            self.assertTrue(result[0]["exe"].endswith("GameAnywhere.exe"))

    def test_epic_manifest_on_custom_drive(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            game = base / "custom-install" / "Epic Game"
            game.mkdir(parents=True)
            (game / "Game.exe").write_bytes(b"Y" * 300_000)
            manifests = base / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
            manifests.mkdir(parents=True)
            (manifests / "mygame.item").write_text(json.dumps({
                "DisplayName": "Epic Game", "AppName": "EpicApplication99",
                "InstallLocation": str(game), "LaunchExecutable": "Game.exe"
            }), encoding="utf-8")
            with patch.dict("os.environ", {"PROGRAMDATA": str(base)}):
                result = discovery.scan_epic()
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["source"], "Epic Games")
            self.assertEqual(result[0]["exe"], str(game / "Game.exe"))

    def test_reject_setup_and_find_game_binary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "setup.exe").write_bytes(b"0" * 8_000_000)
            (root / "NBA2K20.exe").write_bytes(b"1" * 220_000)
            result = discovery.find_game_exe(root, "NBA 2K20")
            self.assertIsNotNone(result)
            self.assertEqual(result.name, "NBA2K20.exe")

    def test_keep_manual_and_favorites(self):
        same_id = game_id("steam", "1")
        current = [{"id": same_id, "name": "My Game", "favorite": True,
                    "source": "Steam", "target": "steam://rungameid/1"},
                   {"id": "manual:1", "name": "Personal", "source": "Manual",
                    "target": "", "favorite": False}]
        scanned = [{"id": same_id, "name": "My Game", "source": "Steam",
                    "target": "steam://rungameid/1", "available": True}]
        merged = sync_found(current, scanned)
        self.assertTrue(next(g for g in merged if g["id"] == same_id)["favorite"])
        self.assertTrue(any(g.get("source") == "Manual" for g in merged))

    def test_kv_parsing(self):
        pairs = discovery.parse_kv('"path" "D:\\\\SteamLibrary"\n"name" "Game X"')
        self.assertEqual(pairs["path"], r"D:\SteamLibrary")


if __name__ == "__main__":
    unittest.main()
