"""Testes de integridade do slot RTSS (sem executar RTSS ou qualquer jogo)."""
import ctypes
import unittest
from app.rtss_backend import RTSSOSD,RTSS_OWNER


class RTSSBackendTests(unittest.TestCase):
    def setUp(self):
        self.data=(ctypes.c_ubyte*20000)()
        self.mem=ctypes.addressof(self.data)
        self.head=(ctypes.c_uint32*10).from_address(self.mem)
        self.entry=self.mem+1024
        self.head[8]=15

    def test_extended_osd_writes_only_owned_slot(self):
        prev=(ctypes.c_ubyte*512).from_address(self.entry+5000)
        prev[0]=77
        RTSSOSD._commit(self.head,self.entry,"FPS: <FR>",0x00020015,4608)
        owner=ctypes.string_at(self.entry+256,256).split(b"\0",1)[0]
        text=ctypes.string_at(self.entry+512,100).split(b"\0",1)[0]
        self.assertEqual(owner,RTSS_OWNER)
        self.assertEqual(text,b"FPS: <FR>")
        self.assertEqual(self.head[8],16)
        self.assertEqual(self.head[9]&1,0)
        self.assertEqual(prev[0],77)

    def test_release_does_not_clear_neighbouring_slots(self):
        other=ctypes.c_uint8.from_address(self.entry+4900)
        other.value=42
        RTSSOSD._commit(self.head,self.entry,"FPS: <FR>",0x00020015,4608)
        RTSSOSD._commit(self.head,self.entry,None,0x00020015,4608)
        self.assertEqual(ctypes.string_at(self.entry,1),b"\0")
        self.assertEqual(ctypes.string_at(self.entry+256,1),b"\0")
        self.assertEqual(ctypes.string_at(self.entry+512,1),b"\0")
        self.assertEqual(self.head[8],17)
        self.assertEqual(other.value,42)
        self.assertEqual(self.head[9]&1,0)

    def test_legacy_text_slot(self):
        RTSSOSD._commit(self.head,self.entry,"FPS: <FR>",0x00020005,512)
        self.assertEqual(ctypes.string_at(self.entry,len(b"FPS: <FR>")),b"FPS: <FR>")
        self.assertEqual(ctypes.string_at(self.entry+256,len(RTSS_OWNER)),RTSS_OWNER)


if __name__=="__main__":
    unittest.main()
