"""RTSS in-game HUD for exclusive fullscreen games.

Third-party RTSS is NOT redistributed: we use its public shared-memory SDK
when installed. With user consent SuperRender can install the official WinGet
package on machines without it. Qt overlay stays as a noninvasive fallback.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog, QWidget

RTSS_MAPPING = "RTSSSharedMemoryV2"
RTSS_OWNER = b"SuperRenderFPS"
FILE_MAP_READ = 0x0004
FILE_MAP_WRITE = 0x0002
RTSS_SIGNATURE = 0x52545353
INSTALL_PACKAGE = "Guru3D.RTSS"
OFFICIAL_URL = "https://www.guru3d.com/download/rtss-rivatuner-statistics-server-download/"


def installed_rtss() -> Path | None:
    if os.name != "nt":
        return None
    roots = (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(os.environ.get("LOCALAPPDATA", str(Path.home()))),
    )
    names = ("RivaTuner Statistics Server", "RTSS")
    for root in roots:
        for name in names:
            exe = root / name / "RTSS.exe"
            if exe.is_file():
                return exe
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for view in (0, winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
                keypath = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
                try:
                    rootkey=winreg.OpenKey(hive,keypath,0,winreg.KEY_READ|view)
                except OSError:
                    continue
                with rootkey:
                    for index in range(min(winreg.QueryInfoKey(rootkey)[0],900)):
                        try:
                            subname=winreg.EnumKey(rootkey,index)
                            with winreg.OpenKey(rootkey,subname) as sub:
                                label=str(winreg.QueryValueEx(sub,"DisplayName")[0])
                                if "rivatuner statistics server" not in label.casefold():
                                    continue
                                loc=str(winreg.QueryValueEx(sub,"InstallLocation")[0])
                                candidate=Path(loc)/"RTSS.exe"
                                if candidate.is_file():
                                    return candidate
                        except OSError:
                            continue
    except OSError:
        pass
    return None


def winrt_api():
    kernel = ctypes.windll.kernel32
    kernel.OpenFileMappingW.argtypes=(wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.OpenFileMappingW.restype=wintypes.HANDLE
    kernel.MapViewOfFile.argtypes=(wintypes.HANDLE, wintypes.DWORD,
                                    wintypes.DWORD,wintypes.DWORD,ctypes.c_size_t)
    kernel.MapViewOfFile.restype=ctypes.c_void_p
    kernel.UnmapViewOfFile.argtypes=(ctypes.c_void_p,)
    kernel.UnmapViewOfFile.restype=wintypes.BOOL
    kernel.CloseHandle.argtypes=(wintypes.HANDLE,)
    return kernel


def mapping_available()->bool:
    if os.name!="nt":
        return False
    kernel=winrt_api()
    handle=kernel.OpenFileMappingW(FILE_MAP_READ,False,RTSS_MAPPING)
    if handle:
        kernel.CloseHandle(handle)
    return bool(handle)


class RTSSOSD:
    """Writes ONLY the application's own slot; never edits RTSS global settings."""
    def __init__(self):
        self.available=False
        self.last_error=""
        self._is_displayed=False

    def _apply(self, text:str|None)->bool:
        if os.name!="nt":
            return False
        kernel=winrt_api()
        handle=kernel.OpenFileMappingW(FILE_MAP_READ|FILE_MAP_WRITE,False,RTSS_MAPPING)
        if not handle:
            self.available=False
            self.last_error="RTSS nao esta em execucao ou acesso ao overlay negado."
            return False
        ptr=None
        try:
            ptr=kernel.MapViewOfFile(handle,FILE_MAP_READ|FILE_MAP_WRITE,0,0,0)
            if not ptr:
                self.last_error="Nao foi possivel acessar a memoria compartilhada do RTSS."
                return False
            head=(ctypes.c_uint32*10).from_address(ptr)
            sig, ver = int(head[0]), int(head[1])
            slot_size, offset, slots = int(head[5]), int(head[6]), int(head[7])
            if not (sig==RTSS_SIGNATURE and ver>>16==2 and
                    512<=slot_size<=400000 and 48<=offset<=1_000_000 and
                    2<=slots<=256 and offset+slot_size*slots<=80_000_000):
                self.last_error="Versao ou estrutura de RTSS nao reconhecida."
                return False
            self.available=True
            own=None
            free=None
            for index in range(1,slots):
                entry=ptr+offset+index*slot_size
                owner=ctypes.string_at(entry+256,256).split(b"\x00",1)[0]
                if owner==RTSS_OWNER:
                    own=entry
                    break
                if not owner and free is None:
                    free=entry
            if text is None:
                if own is not None:
                    self._commit(head,own,None,ver,slot_size)
                self._is_displayed=False
                return True
            entry=own if own is not None else free
            if entry is None:
                self.last_error="Nao ha espaco livre no OSD do RTSS."
                return False
            self._commit(head,entry,text,ver,slot_size)
            self._is_displayed=True
            return True
        except (OSError,ValueError,OverflowError) as exc:
            self.last_error=str(exc)
            return False
        finally:
            if ptr:
                kernel.UnmapViewOfFile(ptr)
            kernel.CloseHandle(handle)

    @staticmethod
    def _commit(head, entry:int,text:str|None,version:int,size:int):
        # RTSS SDK: szOSD 256 bytes, szOSDOwner 256, szOSDEx 4096.
        # Keep the critical section tiny, always release dwBusy.
        if version>=0x0002000E:
            busy=ctypes.c_uint32.from_address(ctypes.addressof(head)+36)
            if busy.value&1:
                raise OSError("RTSS OSD esta ocupado. Tente novamente.")
            busy.value|=1
        else:
            busy=None
        try:
            if text is None:
                ctypes.memset(entry,0,512)
                if size>=4608:
                    ctypes.memset(entry+512,0,4096)
            else:
                encoded=text.encode("ascii","replace")[:245]
                # Old and new RTSS renderers: write a single OSD text source.
                ctypes.memset(entry,0,256)
                if size>=4608 and version>=0x00020007:
                    ctypes.memset(entry+512,0,4096)
                    ctypes.memmove(entry+512,encoded+b"\x00",len(encoded)+1)
                else:
                    ctypes.memmove(entry,encoded+b"\x00",len(encoded)+1)
                ctypes.memset(entry+256,0,256)
                ctypes.memmove(entry+256,RTSS_OWNER+b"\x00",len(RTSS_OWNER)+1)
            head[8]=(int(head[8])+1)&0xffffffff
        finally:
            if busy is not None:
                busy.value&=~1

    def show(self)->bool:
        if self._is_displayed and self.available:
            return True
        # RTSS token <FR> is the server's own measured in-game frame rate.
        return self._apply("FPS: <FR>")

    def hide(self)->bool:
        if not self._is_displayed:
            return True
        return self._apply(None)

    def close(self):
        try:
            self._apply(None)
        except (OSError,ValueError):
            pass
        self._is_displayed=False


class RTSSProvisioner:
    """RTSS is freeware from its publisher; never embed/rehost its installer."""
    def __init__(self):
        self.prompted=False
        self.declined=False
        self.last_error=""

    def ensure_running(self)->bool:
        if mapping_available():
            return True
        exe=installed_rtss()
        if exe is None:
            return False
        try:
            flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
            subprocess.Popen([str(exe),"/f"],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,creationflags=flags,
                cwd=str(exe.parent))
        except OSError as exc:
            self.last_error=str(exc)
            return False
        for _ in range(12):
            if mapping_available():
                return True
            time.sleep(.25)
        self.last_error="RTSS instalado, mas seu servico OSD nao iniciou."
        return False

    def provision(self,parent:QWidget|None=None)->bool:
        if os.name!="nt":
            return False
        if self.ensure_running():
            return True
        if installed_rtss() is not None:
            return False
        if self.declined:
            return False
        if self.prompted:
            return self.ensure_running()
        self.prompted=True
        reply=QMessageBox.question(
            parent,"SuperRender - FPS em tela cheia",
            "Para que o FPS apareca sobre jogos em tela cheia exclusiva, "
            "o SuperRender utiliza o RTSS (RivaTuner Statistics Server).\n\n"
            "O RTSS e um aplicativo gratuito de terceiros, distribuido pelo "
            "proprio desenvolvedor, e NAO faz parte do SuperRender.\n\n"
            "Deseja que o SuperRender baixe e instale o RTSS automaticamente "
            "pelo Gerenciador de Pacotes do Windows? Pode precisar de internet "
            "e confirmacao de administrador. Nenhuma instalacao sera feita "
            "se voce selecionar Nao.\n\n"
            "Fornecedor oficial: Guru3D / Unwinder",
            QMessageBox.Yes|QMessageBox.No,QMessageBox.Yes)
        if reply!=QMessageBox.Yes:
            self.declined=True
            return False
        manager=shutil.which("winget")
        if not manager:
            local=Path(os.environ.get("LOCALAPPDATA",""))/"Microsoft"/"WindowsApps"/"winget.exe"
            if local.is_file():
                manager=str(local)
        if not manager:
            self.last_error="winget nao esta disponivel; nenhum download executado."
            QMessageBox.warning(parent,"SuperRender - instalacao",self.last_error)
            return False

        progress=QProgressDialog(
            "Preparando o suporte a tela cheia pelo WinGet.\n"
            "Aguarde a confirmacao do Windows, se solicitada.",
            "",0,0,parent)
        progress.setWindowTitle("SuperRender - configurando OSD")
        progress.setCancelButton(None)
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setMinimumWidth(440)
        outcome={"code":None,"error":""}
        done=threading.Event()

        def worker():
            try:
                proc=subprocess.run(
                    [manager,"install","--id",INSTALL_PACKAGE,"--exact",
                     "--source","winget","--silent",
                     "--accept-package-agreements","--accept-source-agreements"],
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,timeout=230,
                    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
                outcome["code"]=proc.returncode
            except (OSError,subprocess.TimeoutExpired) as exc:
                outcome["error"]=str(exc)
            finally:
                done.set()
        threading.Thread(target=worker,daemon=True,name="sr-rtss-install").start()
        progress.show()
        while not done.wait(.07):
            QApplication.processEvents()
        progress.close()
        if outcome["code"]!=0:
            self.last_error=outcome["error"] or (
                "WinGet nao concluiu a instalacao. Nenhum ajuste no jogo foi feito.")
            QMessageBox.warning(parent,"SuperRender - suporte tela cheia",self.last_error)
            return False
        if not self.ensure_running():
            QMessageBox.warning(parent,"SuperRender - RTSS",self.last_error or
                                "RTSS foi instalado, mas precisa ser iniciado.")
            return False
        return True
