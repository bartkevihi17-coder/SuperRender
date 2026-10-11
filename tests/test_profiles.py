"""Testes de seguranca e reversao dos perfis, sem executar jogos."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import optimization as opt


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.exe=self.root/"NBA2K20.exe"
        self.exe.write_bytes(b"TEST-EXE")
        self.cfg=self.root/"VideoSettings.cfg"
        self.original={"WIDTH":1280,"HEIGHT":720,"CROWDLOD":2,
                       "SHADOW_DETAIL":1,"OVERALL_QUALITY":4,
                       "CPU_CORES":4,"VSYNC":1,"PLAYERLOD":1}
        self.original_bytes=json.dumps(self.original,indent=2).encode()
        self.cfg.write_bytes(self.original_bytes)
        self.game={"id":"game:test:nba2k20","name":"NBA 2K20","source":"Manual",
                   "exe":str(self.exe),"target":str(self.exe)}
        patches=[
            patch.object(opt,"nba_config_path",return_value=self.cfg),
            patch.object(opt,"_SESSIONS",self.root/"sessions"),
            patch.object(opt,"_BACKUPS",self.root/"backups"),
            patch.object(opt,"is_running",return_value=False),
        ]
        for p in patches:p.start();self.addCleanup(p.stop)

    def test_normal_does_not_change_game(self):
        self.assertIsNone(opt.prepare_game(self.game,"normal"))
        self.assertEqual(self.cfg.read_bytes(),self.original_bytes)

    def test_optimized_changes_and_restores_exact_original(self):
        info=opt.prepare_game(self.game,"optimized")
        self.assertIsNotNone(info)
        data=json.loads(self.cfg.read_text())
        self.assertEqual((data["WIDTH"],data["HEIGHT"]),(960,540))
        self.assertEqual(data["SHADOW_DETAIL"],4)
        self.assertEqual(data["CPU_CORES"],4)
        self.assertEqual(data["CROWDLOD"],3)
        self.assertEqual(opt.restore_game(self.game),"Configuracoes originais restauradas.")
        self.assertEqual(self.cfg.read_bytes(),self.original_bytes)
        self.assertIsNone(opt.read_session(self.game))

    def test_potato_resolution(self):
        opt.prepare_game(self.game,"potato")
        data=json.loads(self.cfg.read_text())
        self.assertEqual((data["WIDTH"],data["HEIGHT"]),(640,480))
        self.assertTrue(data["ALLOW_BLURRY_UI"])
        self.assertEqual(data["OVERALL_QUALITY"],4)

    def test_never_overwrite_external_game_changes(self):
        opt.prepare_game(self.game,"potato")
        latest=json.loads(self.cfg.read_text())
        latest["VSYNC"]=1
        self.cfg.write_text(json.dumps(latest),encoding="utf-8")
        msg=opt.restore_game(self.game)
        self.assertIn("modificada",msg)
        self.assertTrue(self.cfg.is_file())
        self.assertIsNotNone(opt.read_session(self.game))

    def test_custom_game_not_modified(self):
        other=dict(self.game)
        other.update({"name":"Skater XL","exe":str(self.root/"skater.exe"),
                      "target":str(self.root/"skater.exe")})
        self.assertIsNone(opt.prepare_game(other,"potato"))
        self.assertEqual(self.cfg.read_bytes(),self.original_bytes)


if __name__=="__main__":unittest.main()
