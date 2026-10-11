"""Testes do contador independente de jogos reais e sem captura ETW."""
import io
import os
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.fps_overlay import (
    PresentMonStream, RTSSFPS, bundled_presentmon, find_pid_for_executable,
    metric_from_row,
)


class FPSParserTests(unittest.TestCase):
    def test_measures_frametime_from_actual_presents(self):
        header=["Application","ProcessID","Runtime","msBetweenPresents"]
        self.assertAlmostEqual(metric_from_row(header,["Game","42","DXGI","16.666"]),16.666)

    def test_does_not_invent_zero_or_invalid_fps(self):
        head=["Application","msBetweenPresents"]
        for row in (["Game",""],["Game","N/A"],["Game","0"],
                    ["Game","-8"],["Game","999999"]):
            self.assertIsNone(metric_from_row(head,row))

    def test_stream_aggregates_real_rows(self):
        src = ("Application,ProcessID,msBetweenPresents\n" +
               "".join("MyGame.exe,512,33.333\n" for _ in range(60))).encode("utf-8")
        stream=PresentMonStream()
        stream._parse(SimpleNamespace(stdout=io.BytesIO(src)),threading.Event())
        fps=stream.get_fps()
        self.assertIsNotNone(fps)
        self.assertAlmostEqual(fps,30.0,places=1)

    def test_stream_does_not_reuse_stale_fps(self):
        stream=PresentMonStream()
        with stream.lock:
            stream.samples.extend([(0.0,16.67)]*30)
            stream.last_update=0.0
        self.assertIsNone(stream.get_fps())

    def test_bundled_capture_tool(self):
        path=bundled_presentmon()
        self.assertIsNotNone(path)
        self.assertTrue(path.is_file())
        self.assertGreater(path.stat().st_size,20_000)

    @unittest.skipUnless(os.name=="nt","Requer Windows")
    def test_finds_current_process_without_install_path_fixed(self):
        import sys
        found=find_pid_for_executable(sys.executable)
        self.assertIsInstance(found,int)
        self.assertGreater(found,0)

    @unittest.skipUnless(os.name=="nt","Requer Windows")
    def test_rtss_read_only_when_unavailable(self):
        self.assertIsNone(RTSSFPS().read(-1))


if __name__=="__main__":unittest.main()
