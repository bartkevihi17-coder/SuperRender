"""FPS real no SuperRender: PresentMon (incluido no EXE) + OSD nativo Qt.

A captura vem de ETW/PresentMon ou da memoria compartilhada do RTSS (quando
ele ja estiver em execucao). Nunca calcula FPS usando um timer da GUI.

O HUD e click-through, so aparece quando a janela ativa pertence ao jogo,
e Ctrl+7 global alterna sua visibilidade. Fullscreen exclusivo pode bloquear
janelas desktop: o programa nao promete burlar o modo exclusivo.
"""
from __future__ import annotations

import csv
import ctypes
from ctypes import wintypes
from collections import deque
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
import uuid

from PySide6.QtCore import Qt, QObject, QTimer, Signal, QAbstractNativeEventFilter, QPoint
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget
from .rtss_backend import RTSSOSD, RTSSProvisioner, mapping_available

HOTKEY_ID = 0x7A71
WM_HOTKEY = 0x0312
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
VK_7 = 0x37
# Win32 PROCESS_QUERY_LIMITED_INFORMATION; FILE_MAP_READ
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
FILE_MAP_READ = 0x0004
RTSS_NAME = "RTSSSharedMemoryV2"


def _win_functions():
    if os.name != "nt":
        return None
    kernel = ctypes.windll.kernel32
    user = ctypes.windll.user32
    psapi = ctypes.windll.psapi
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.GetProcessId.argtypes = (wintypes.HANDLE,)
    kernel.GetProcessId.restype = wintypes.DWORD
    kernel.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
    kernel.OpenFileMappingW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.OpenFileMappingW.restype = wintypes.HANDLE
    kernel.MapViewOfFile.argtypes = (wintypes.HANDLE, wintypes.DWORD,
                                      wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t)
    kernel.MapViewOfFile.restype = ctypes.c_void_p
    kernel.UnmapViewOfFile.argtypes = (ctypes.c_void_p,)
    user.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int,
                                    wintypes.UINT, wintypes.UINT)
    user.RegisterHotKey.restype = wintypes.BOOL
    user.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
    user.UnregisterHotKey.restype = wintypes.BOOL
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    return kernel, user, psapi


def find_pid_for_executable(exe: str) -> int | None:
    """Identificacao por caminho completo: evita capturar outro jogo por engano."""
    if os.name != "nt" or not exe or not Path(exe).is_file():
        return None
    kernel, _user, psapi = _win_functions()
    pids = (wintypes.DWORD * 8192)()
    returned = wintypes.DWORD()
    if not psapi.EnumProcesses(ctypes.byref(pids), ctypes.sizeof(pids),
                               ctypes.byref(returned)):
        return None
    expected = os.path.normcase(os.path.normpath(exe))
    for pid in pids[:returned.value // ctypes.sizeof(wintypes.DWORD)]:
        if not pid:
            continue
        handle = kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            continue
        try:
            path = ctypes.create_unicode_buffer(32768)
            count = wintypes.DWORD(len(path))
            if kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(count)):
                if os.path.normcase(os.path.normpath(path.value)) == expected:
                    return int(pid)
        finally:
            kernel.CloseHandle(handle)
    return None


def pid_foreground() -> int | None:
    if os.name != "nt":
        return None
    _kernel, user, _psapi = _win_functions()
    hwnd = user.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value) or None


def bundled_presentmon() -> Path | None:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    exe = root / "third_party" / "PresentMon-1.10.0-x64.exe"
    return exe if exe.is_file() else None


class RTSSFPS:
    """Consulta read-only conforme RTSSSharedMemory.h (SDK do RTSS).

    Estruturas v2.x: cabecalho DWORD[5], entradas com PID, timestamps,
    contagem e intervalo de frames. Nenhum byte e gravado no RTSS.
    """
    def read(self, pid: int) -> float | None:
        if os.name != "nt" or not pid:
            return None
        kernel, _user, _psapi = _win_functions()
        mapping = kernel.OpenFileMappingW(FILE_MAP_READ, False, RTSS_NAME)
        if not mapping:
            return None
        view = None
        try:
            view = kernel.MapViewOfFile(mapping, FILE_MAP_READ, 0, 0, 0)
            if not view:
                return None
            head = (ctypes.c_uint32 * 5).from_address(view)
            signature, version, size, offset, count = [int(x) for x in head]
            # 'RTSS' em compiladores C pode usar ordenacao de multichar.
            if signature not in (0x52545353, 0x53535452):
                return None
            if (version >> 16) != 2 or not (284 <= size <= 200000):
                return None
            if not (32 <= offset <= 1000000) or not (0 < count <= 4096):
                return None
            for i in range(count):
                ptr = view + offset + i * size
                data = (ctypes.c_uint32 * 5).from_address(ptr + 264)
                # DWORD dwFlags=264, dwTime0=268, dwTime1=272,
                # dwFrames=276, dwFrameTime=280
                proc, = (ctypes.c_uint32 * 1).from_address(ptr)
                if int(proc) != pid:
                    continue
                _flags, time0, time1, frames, frame_time = (int(v) for v in data)
                elapsed = (time1 - time0) & 0xFFFFFFFF
                age = (kernel.GetTickCount() - time1) & 0xFFFFFFFF
                if time0 and time1 and 0 < elapsed < 10000 and age < 2500 and frames:
                    fps = 1000.0 * frames / elapsed
                    if 0.5 <= fps <= 1000.0:
                        return fps
                if frame_time and 500 <= frame_time <= 1000000 and age < 2500:
                    fps = 1000000.0 / frame_time
                    if 0.5 <= fps <= 1000.0:
                        return fps
            return None
        except (OSError, ValueError, OverflowError, TypeError):
            return None
        finally:
            if view:
                kernel.UnmapViewOfFile(view)
            kernel.CloseHandle(mapping)


def metric_from_row(header: list[str], row: list[str]) -> float | None:
    """Extrai tempo entre presents, sem inventar dados."""
    keys = [re.sub(r"[^a-z0-9]", "", x.casefold()) for x in header]
    for candidate in ("msbetweenpresents", "msbetweensimulationstart"):
        if candidate in keys:
            index = keys.index(candidate)
            if index >= len(row):
                continue
            try:
                ms = float(row[index])
            except (ValueError, TypeError):
                return None
            if 0.6 <= ms <= 500.0:
                return ms
    return None


class PresentMonStream:
    """Le CSV em tempo real sem criar arquivos gigantes; sessoes sao unicas."""
    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.thread: threading.Thread | None = None
        self.session = ""
        self.pid = 0
        self.lock = threading.Lock()
        self.samples = deque(maxlen=180)
        self.last_update = 0.0
        self.error = ""
        self._stop = threading.Event()

    def start(self, pid: int):
        self.stop()
        binary = bundled_presentmon()
        if binary is None:
            self.error = "PresentMon nao incluido nesta compilacao."
            return
        self.pid = int(pid)
        self.session = "SR_FPS_" + uuid.uuid4().hex[:16]
        self.samples.clear()
        self.last_update = 0.0
        self.error = ""
        self._stop = threading.Event()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        args = [
            str(binary), "-process_id", str(pid),
            "-session_name", self.session,
            "-output_stdout", "-no_top", "-terminate_on_proc_exit",
        ]
        try:
            self.process = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, creationflags=flags,
                cwd=str(binary.parent),
            )
        except OSError as error:
            self.error = "Nao foi possivel iniciar captura de FPS: " + str(error)
            self.process = None
            return
        self.thread = threading.Thread(target=self._parse, args=(self.process,self._stop),
                                       daemon=True,name="sr-presentmon-read")
        self.thread.start()

    def _parse(self, process, stop_event):
        try:
            if process.stdout is None:
                return
            header = None
            for raw in process.stdout:
                if stop_event.is_set():
                    break
                try:
                    text = raw.decode("utf-8-sig",errors="replace").strip()
                    if not text:
                        continue
                    cols = next(csv.reader([text]))
                except (UnicodeError, csv.Error):
                    continue
                if header is None:
                    if any("betweenpresents" in v.casefold() for v in cols):
                        header = cols
                    continue
                ms = metric_from_row(header, cols)
                if ms is None:
                    continue
                now = time.monotonic()
                with self.lock:
                    self.samples.append((now, ms))
                    self.last_update = now
        except (OSError, ValueError) as error:
            self.error = str(error)

    def get_fps(self) -> float | None:
        with self.lock:
            now = time.monotonic()
            if now - self.last_update > 2.3:
                return None
            entries = [ms for at,ms in self.samples if now - at <= 1.5]
            if len(entries) < 6:
                return None
            # FPS medio por presents recentes, evitando um unico pico.
            fps = 1000.0 * len(entries) / sum(entries)
            return fps if 0.5 <= fps <= 1000.0 else None

    def stop(self):
        self._stop.set()
        p = self.process
        session = self.session
        self.process = None
        self.session = ""
        self.pid = 0
        if p:
            try: p.terminate()
            except OSError: pass
        self.samples.clear()
        self.last_update = 0.0
        if session and p is not None:
            # Finalizacao ETW em thread: nao bloqueia a interface ao sair do jogo.
            threading.Thread(
                target=self._end_capture, args=(p,session),
                daemon=True,name="sr-presentmon-cleanup",
            ).start()

    @staticmethod
    def _end_capture(process, session):
        try:
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:process.kill()
            except OSError:pass
        binary=bundled_presentmon()
        if binary is None:
            return
        try:
            subprocess.run(
                [str(binary), "-session_name", session, "-terminate_existing"],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,timeout=4,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


def _game_screen(pid:int):
    """Escolhe o monitor que contem a janela do jogo, sem foco nem clique."""
    if os.name!="nt":
        return None
    user=ctypes.windll.user32
    best=[None,0]
    callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    user.EnumWindows.argtypes=(callback,wintypes.LPARAM)
    user.IsWindowVisible.argtypes=(wintypes.HWND,)
    user.GetWindowRect.argtypes=(wintypes.HWND,ctypes.POINTER(wintypes.RECT))
    def visit(hwnd,_extra):
        if not user.IsWindowVisible(hwnd):
            return True
        process=wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd,ctypes.byref(process))
        if int(process.value)!=pid:
            return True
        rect=wintypes.RECT()
        if not user.GetWindowRect(hwnd,ctypes.byref(rect)):
            return True
        width=rect.right-rect.left
        height=rect.bottom-rect.top
        area=width*height
        if width<300 or height<200 or area<=best[1]:
            return True
        best[0]=QPoint((rect.left+rect.right)//2,(rect.top+rect.bottom)//2)
        best[1]=area
        return True
    cb=callback(visit)
    user.EnumWindows(cb,0)
    return QApplication.screenAt(best[0]) if best[0] is not None else None


class GameFPSOverlay(QWidget):
    """HUD proprio; nunca recebe clique e nao rouba o foco do jogo."""
    def __init__(self):
        flags = (Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                 Qt.Tool | Qt.WindowTransparentForInput |
                 Qt.WindowDoesNotAcceptFocus)
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground,True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents,True)
        self.setAttribute(Qt.WA_ShowWithoutActivating,True)
        self.setFixedSize(145,43)
        self.fps = None
        self.message = "FPS  --"

    def set_fps(self, fps: float | None):
        self.fps = fps
        text = f"FPS  {fps:.0f}" if fps is not None else "FPS  --"
        if text != self.message:
            self.message = text
            self.update()

    def paintEvent(self,_event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(9,10,20,212))
        painter.drawRoundedRect(0,0,145,43,11,11)
        painter.setBrush(QColor("#c3a1ff"))
        painter.drawRoundedRect(8,10,4,22,2,2)
        painter.setPen(QColor("#f5eeff"))
        painter.setFont(QFont("Segoe UI",15,QFont.DemiBold))
        painter.drawText(20,2,117,39,Qt.AlignVCenter|Qt.AlignLeft,self.message)
        painter.end()

    def position_corner(self,pid:int|None=None):
        screen = None
        if os.name=="nt" and pid:
            screen=_game_screen(pid)
        if screen is None:
            screen=QApplication.primaryScreen()
        if screen:
            box=screen.geometry()
            self.move(box.left()+16,box.top()+16)


class Ctrl7Hotkey(QObject,QAbstractNativeEventFilter):
    activated=Signal()
    def __init__(self,window):
        QObject.__init__(self,window)
        QAbstractNativeEventFilter.__init__(self)
        self.hwnd = int(window.winId())
        self.registered = False
        QApplication.instance().installNativeEventFilter(self)

    def enable(self):
        if os.name != "nt" or self.registered:
            return self.registered
        _kernel, user, _psapi = _win_functions()
        self.registered=bool(user.RegisterHotKey(self.hwnd,HOTKEY_ID,
                                  MOD_CONTROL|MOD_NOREPEAT,VK_7))
        return self.registered

    def disable(self):
        if self.registered and os.name=="nt":
            _kernel,user,_psapi=_win_functions()
            user.UnregisterHotKey(self.hwnd,HOTKEY_ID)
        self.registered=False

    def nativeEventFilter(self,eventType,message):
        if eventType in (b"windows_generic_MSG",b"windows_dispatcher_MSG"):
            msg=wintypes.MSG.from_address(int(message))
            if msg.message==WM_HOTKEY and int(msg.wParam)==HOTKEY_ID:
                self.activated.emit()
                return True,0
        return False,0

    def close(self):
        self.disable()
        QApplication.instance().removeNativeEventFilter(self)


class FPSController(QObject):
    """Lifecycle gerenciado pelo aplicativo e nao pelo processo do jogo."""
    notify=Signal(str)
    def __init__(self,host):
        super().__init__(host)
        self.overlay=GameFPSOverlay()
        self.hotkey=Ctrl7Hotkey(host)
        self.hotkey.activated.connect(self.toggle)
        self.visible_requested=True
        self.game:dict|None=None
        self.pid:int|None=None
        self.started_at=0.0
        self.last_pid_check=0.0
        self.last_fps=None
        self.rtss=RTSSFPS()
        self.rtss_osd=RTSSOSD()
        self.rtss_provisioner=RTSSProvisioner()
        self.prefer_native_rtss=False
        self.presentmon=PresentMonStream()
        self.timer=QTimer(self)
        self.timer.setInterval(390)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self._capture_delayed=False
        self._warned=False

    def prepare_backend(self, parent: QWidget):
        """Start an installed RTSS or offer a consent-based automatic install."""
        self.prefer_native_rtss=self.rtss_provisioner.provision(parent)
        if self.prefer_native_rtss:
            self.notify.emit("OSD dentro do jogo ativado para tela cheia.")
        elif self.rtss_provisioner.last_error:
            self.notify.emit("OSD RTSS indisponivel: "+self.rtss_provisioner.last_error)

    def start_game(self,game):
        self.stop()
        self.game=dict(game)
        self.visible_requested=True
        self.started_at=time.monotonic()
        self._capture_delayed=False
        self._warned=False
        self.overlay.set_fps(None)
        if self.hotkey.enable():
            self.notify.emit("FPS ligado · Ctrl+7 esconde/mostra")
        else:
            self.notify.emit("Ctrl+7 ja esta em uso por outro programa.")

    def toggle(self):
        if self.game is None:
            return
        self.visible_requested=not self.visible_requested
        if not self.visible_requested:
            self.overlay.hide()
            self.rtss_osd.hide()
        self.notify.emit("Contador de FPS "+("ativado" if self.visible_requested else "oculto"))

    def tick(self):
        if self.game is None:
            return
        now=time.monotonic()
        exe=str(self.game.get("exe") or "")
        if now-self.last_pid_check>1.2:
            self.last_pid_check=now
            found=find_pid_for_executable(exe)
            if found!=self.pid:
                if found:
                    self.pid=found
                    self._capture_delayed=False
                elif self.pid is not None:
                    self.stop()
                    return
        if self.pid is None:
            if now-self.started_at>100:
                self.notify.emit("Nao foi possivel detectar o processo para medir FPS.")
                self.stop()
            return
        foreground = pid_foreground()==self.pid
        if self.prefer_native_rtss:
            # O RTSS desenha dentro do pipeline 3D do jogo, inclusive fullscreen.
            # O proprio token <FR> e interpretado pelo RTSS como FPS REAL.
            if foreground and self.visible_requested:
                if self.rtss_osd.show():
                    self.overlay.hide()
                    return
            else:
                self.rtss_osd.hide()
                self.overlay.hide()
                return
        # Fallback nativo, seguro para janela/borderless. Nao garante
        # sobreposicao sobre modo fullscreen exclusivo.
        value=self.rtss.read(self.pid)
        if value is None:
            if not self._capture_delayed and now-self.started_at>1.5:
                self.presentmon.start(self.pid)
                self._capture_delayed=True
            value=self.presentmon.get_fps()
        self.last_fps=value
        if value is None and now-self.started_at>14 and not self._warned:
            self._warned=True
            self.notify.emit(
                "FPS indisponivel. Capture ETW bloqueada ou overlay nao suportado.")
        self.overlay.set_fps(value)
        if self.visible_requested and foreground:
            self.overlay.position_corner(self.pid)
            if not self.overlay.isVisible():
                self.overlay.show()
                self.overlay.raise_()
        elif self.overlay.isVisible():
            self.overlay.hide()

    def stop(self):
        self.overlay.hide()
        self.rtss_osd.close()
        self.presentmon.stop()
        self.hotkey.disable()
        self.game=None
        self.pid=None
        self.last_fps=None
        self.last_pid_check=0.0

    def close(self):
        self.stop()
        self.timer.stop()
        self.hotkey.close()
        self.overlay.close()
