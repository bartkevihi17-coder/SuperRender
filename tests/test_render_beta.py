"""Render Beta is a placeholder UI profile, not a graphics accelerator."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.optimization import PROFILE_ORDER, PROFILE_INFO, prepare_game, profile_changes
from app import optimization, launcher


class RenderBetaTests(unittest.TestCase):
    def test_profile_registered_as_fifth_choice(self):
        self.assertEqual(PROFILE_ORDER[-1], "render")
        self.assertEqual(PROFILE_INFO["render"]["title"],"Render (Beta)")
        self.assertIn("normalmente",PROFILE_INFO["render"]["details"])

    def test_no_graphics_mutations_even_on_nba(self):
        with tempfile.TemporaryDirectory() as root:
            cfg=Path(root)/"VideoSettings.cfg"
            original=json.dumps({"WIDTH":1280,"HEIGHT":720}).encode("utf-8")
            cfg.write_bytes(original)
            game={"id":"test:nba","name":"NBA 2K20","source":"Manual",
                  "exe":str(Path(root)/"NBA2K20.exe")}
            with patch.object(optimization,"nba_config_path",return_value=cfg):
                self.assertEqual(profile_changes(game,"render",{"WIDTH":1280}),{})
                self.assertIsNone(prepare_game(game,"render"))
                self.assertEqual(cfg.read_bytes(),original)

    def test_launcher_render_uses_normal_execution_no_priority_change(self):
        if os.name!="nt":
            self.skipTest("Windows-specific game launcher")
        with tempfile.TemporaryDirectory() as root:
            exe=Path(root)/"MockGame.exe"
            exe.write_bytes(b"stub-not-executable")
            game={"id":"mock:1","name":"Mock Game","kind":"exe",
                  "target":str(exe),"exe":str(exe),"args":[]}
            with (patch.object(launcher.subprocess,"Popen") as popen,
                  patch.object(launcher,"played") as played,
                  patch.object(launcher,"_priority_direct") as priority):
                message=launcher.launch(game,"render")
                popen.assert_called_once()
                played.assert_called_once_with("mock:1")
                priority.assert_not_called()
                self.assertIn("iniciado",message.casefold())

    def test_dialog_selects_and_persists_beta_without_needing_game(self):
        from PySide6.QtWidgets import QApplication
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        app=QApplication.instance() or QApplication([])
        dialog=None
        try:
            from app.ui_dialogs import ProfileDialog
            dialog=ProfileDialog({"name":"NBA 2K20"})
            dialog.select("render")
            self.assertIn("render",dialog.rows)
            self.assertEqual(dialog.selected,"render")
            self.assertIn("normalmente",dialog.explainer.text())
            dialog.autoplay_switch.setChecked(True)
            settings=dialog.settings()
            self.assertEqual(settings["default_profile"],"render")
            self.assertTrue(settings["skip_profile_dialog"])
            dialog.adjustSize()
            screen=app.primaryScreen().availableGeometry()
            self.assertLessEqual(dialog.height(),screen.height())
        finally:
            if dialog is not None:
                dialog.close()


if __name__=="__main__":
    unittest.main()
