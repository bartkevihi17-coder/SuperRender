"""Security and UI tests for Steam-like Stop without ending real games."""
import os
import sys
import unittest
from pathlib import Path

from app import game_process


class GameProcessTests(unittest.TestCase):
    def test_does_not_accept_invalid_pid(self):
        self.assertIsNone(game_process._verified_handle(-1,sys.executable,0))
        self.assertFalse(game_process.is_exact_process_alive(-1,sys.executable))

    @unittest.skipUnless(os.name == "nt", "Requer Windows")
    def test_checks_full_executable_path(self):
        self.assertTrue(game_process.is_exact_process_alive(os.getpid(),sys.executable))
        fake_executable=Path(sys.executable).with_name("not-the-same-python.exe")
        self.assertFalse(game_process.is_exact_process_alive(os.getpid(),str(fake_executable)))

    @unittest.skipUnless(os.name == "nt", "Requer Windows")
    def test_never_terminates_different_application(self):
        # Because exe differs, the API MUST return without termination.
        mismatch=str(Path(sys.executable).with_name("unknown_game.exe"))
        self.assertEqual(
            game_process.force_terminate_verified(os.getpid(),mismatch),
            "not_found",
        )
        self.assertTrue(game_process.is_exact_process_alive(os.getpid(),sys.executable))


class CardStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_play_becomes_stop_then_returns(self):
        from app.qt_gui import GameCard
        game={"id":"fake:test","name":"NBA 2K20","source":"Manual"}
        card=GameCard(game)
        played=[]
        stopped=[]
        card.playClicked.connect(lambda data: played.append(data["id"]))
        card.stopClicked.connect(lambda data: stopped.append(data["id"]))
        card.play.click()
        self.assertEqual(played,["fake:test"])
        self.assertEqual(stopped,[])
        card.set_launch_state("running")
        self.assertIn("INTERROMPER",card.play.text())
        card.play.click()
        self.assertEqual(stopped,["fake:test"])
        card.set_launch_state("stopping")
        self.assertFalse(card.play.isEnabled())
        card.set_launch_state("idle")
        self.assertTrue(card.play.isEnabled())
        self.assertIn("PLAY",card.play.text())
        card.close()


if __name__=="__main__":
    unittest.main()
