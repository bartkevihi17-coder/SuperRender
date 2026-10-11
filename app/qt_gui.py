"""SuperRender 0.3 - interface nativa Qt Widgets, sem HTML nem navegador."""
from __future__ import annotations

import os
import queue
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import (Qt, QTimer, QEasingCurve, QPropertyAnimation, QRect,
                            QEvent, QSize, Signal, Property)
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QIcon, QPixmap)
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QFileDialog, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget, QGraphicsOpacityEffect,
)

from .artwork import ensure_art, photo_file
from .discovery import discover
from .launcher import launch
from .fps_overlay import FPSController
from .library import add_manual, load, save, sync_found, update_game
from .optimization import (PROFILE_INFO, PROFILE_ORDER, get_adapter, is_running,
                           monitor_and_restore, prepare_game, read_session,
                           restore_game, restore_stale_sessions)
from .ui_dialogs import ProfileDialog
from .ui_widgets import (
    P, FeaturedAccordion, Grainient, SidebarItem, SplashOverlay, SwipeToast,
    color, label, make_button,
)


def shortened(text: str, length=44) -> str:
    return text if len(text)<=length else text[:length-1]+"…"


def style_app(app:QApplication):
    app.setStyle("Fusion")
    app.setStyleSheet(f"""
        QWidget{{font-family:"Segoe UI";font-size:10pt;color:{P["ink"]};}}
        QMainWindow{{background:{P["bg"]};}}
        QFrame#mainBackground{{background:{P["bg"]};}}
        QFrame#sidebar{{background:{P["base"]};border-right:1px solid {P["stroke"]};}}
        QFrame#gameCard{{background:{P["panel"]};border:1px solid {P["stroke"]};
            border-radius:14px;}}
        QFrame#gameCard:hover{{border:1px solid #8f77bf;background:#201d33;}}
        QLabel{{background:transparent;}}
        QLineEdit{{background:{P["panel"]};color:{P["ink"]};border:1px solid
            {P["stroke"]};border-radius:11px;padding:11px 15px;selection-background-color:{P["accent"]};}}
        QLineEdit:focus{{border-color:{P["accent"]};}}
        QScrollArea{{border:0;background:transparent;}}
        QScrollBar:vertical{{background:{P["base"]};width:8px;border:0;margin:2px;}}
        QScrollBar::handle:vertical{{background:#615774;min-height:30px;border-radius:4px;}}
        QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}
        QPushButton#primary{{background:{P["accent"]};color:{P["dark"]};
            border:0;border-radius:9px;padding:7px 13px;font-weight:700;}}
        QPushButton#primary:hover{{background:#d5baff;}}
        QPushButton#primary:pressed{{background:#b091f1;}}
        QPushButton#button{{background:#302944;color:{P["ink"]};border:1px solid #4b3d63;
            border-radius:9px;padding:7px 12px;font-weight:600;}}
        QPushButton#button:hover{{background:#3f3457;border-color:{P["accent"]};}}
        QPushButton#subtle{{background:{P["panel2"]};color:{P["muted"]};
            border:1px solid {P["stroke"]};border-radius:9px;padding:7px 12px;}}
        QPushButton#subtle:hover{{background:#303049;color:{P["ink"]};}}
        QToolTip{{background:{P["panel2"]};color:{P["ink"]};border:1px solid {P["stroke"]};}}
    """)


class GameCard(QFrame):
    playClicked=Signal(dict)
    gearClicked=Signal(dict)
    def __init__(self,game,parent=None):
        super().__init__(parent)
        self.game=game
        self.setObjectName("gameCard")
        self.setAttribute(Qt.WA_StyledBackground,True)
        self.setMinimumWidth(230)
        self.setMaximumWidth(370)
        self._pix=None
        main=QVBoxLayout(self)
        main.setContentsMargins(0,0,0,0)
        main.setSpacing(0)
        self.cover=QLabel()
        self.cover.setMinimumHeight(130)
        self.cover.setMaximumHeight(160)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet(
            f"border:0;border-top-left-radius:13px;border-top-right-radius:13px;"
            f"color:{P['accent']};background:#2b2540;font-size:28px;font-weight:800;"
        )
        main.addWidget(self.cover)
        info=QVBoxLayout()
        info.setSpacing(7)
        info.setContentsMargins(14,14,14,15)
        source=label(game.get("source","ARQUIVO LOCAL").upper(),8,"accent",True)
        info.addWidget(source)
        title=label(shortened(game.get("name","Jogo"),32),12,"ink",True)
        title.setMinimumHeight(37)
        title.setWordWrap(True)
        info.addWidget(title)
        if game.get("default_profile") and game.get("profile_is_default"):
            profile=PROFILE_INFO.get(game["default_profile"],PROFILE_INFO["normal"])
            subtitle=profile["title"]
        else: subtitle="Escolher modo ao iniciar"
        sub=label(shortened(subtitle,35),9,"muted")
        info.addWidget(sub)
        row=QHBoxLayout()
        row.setSpacing(8)
        play=make_button("▶   PLAY",filled=True)
        play.setMinimumHeight(41)
        play.clicked.connect(lambda:self.playClicked.emit(self.game))
        row.addWidget(play,1)
        gear=make_button("⚙",secondary=True)
        gear.setFixedSize(43,41)
        gear.setToolTip("Configurar modo de inicializacao")
        gear.clicked.connect(lambda:self.gearClicked.emit(self.game))
        row.addWidget(gear)
        info.addSpacing(2)
        info.addLayout(row)
        main.addLayout(info)
        self.update_cover()

    def update_cover(self):
        file=photo_file(self.game)
        if file.is_file():
            pix=QPixmap(str(file))
            if not pix.isNull():
                self._pix=pix
                self.cover.setPixmap(pix.scaled(330,157,Qt.KeepAspectRatioByExpanding,Qt.SmoothTransformation))
                return
        self.cover.setPixmap(QPixmap())
        self.cover.setText("✦  "+("".join(w[0] for w in self.game.get("name","SR").split()[:2]).upper() or "SR"))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SuperRender — Sua biblioteca")
        screen=QGuiApplication.primaryScreen().availableGeometry()
        width=min(1300,max(1000,int(screen.width()*.91)))
        height=min(860,max(590,int(screen.height()*.94)))
        self.resize(width,height)
        self.move(screen.center().x()-width//2,screen.center().y()-height//2)
        self.setMinimumSize(905,570)
        self.messages=queue.Queue()
        self.executor=ThreadPoolExecutor(max_workers=4,thread_name_prefix="superrender")
        self.games=load().get("games",[])
        self.nav_items={}
        self.active_view="Todos os jogos"
        self.sidebar_collapsed=False
        self.search_query=""
        self.scan_busy=False
        self.cards={}
        self.art_loading=set()
        self.toast=None
        self._render_later=QTimer(self);self._render_later.setSingleShot(True)
        self._render_later.setInterval(150);self._render_later.timeout.connect(self.render_cards)
        self._build()
        self.fps_hud = FPSController(self)
        self.fps_hud.notify.connect(lambda msg: self.messages.put(("session", msg)))
        self.poll=QTimer(self);self.poll.setInterval(150);self.poll.timeout.connect(self.process_messages)
        self.poll.start()
        QTimer.singleShot(320,self.scan)
        QTimer.singleShot(200,self.show_splash)

    def _build(self):
        self.wrapper=QWidget(self)
        self.setCentralWidget(self.wrapper)
        self.wrapper.setObjectName("appWrapper")
        self.wrapper.setStyleSheet(f"QWidget#appWrapper{{background:{P['bg']};}}")
        shell=QFrame(self.wrapper)
        shell.setObjectName("mainBackground")
        self.shell=shell
        shell.setGeometry(self.wrapper.rect())
        horizontal=QHBoxLayout(shell)
        horizontal.setContentsMargins(0,0,0,0)
        horizontal.setSpacing(0)

        sidebar=QFrame(shell)
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(228)
        self.sidebar=sidebar
        horizontal.addWidget(sidebar)

        side_layout=QVBoxLayout(sidebar)
        side_layout.setContentsMargins(14,19,14,18)
        side_layout.setSpacing(13)

        top=QHBoxLayout()
        self.logo=QLabel()
        logo_path=self.asset("SuperRender.png")
        if logo_path.is_file():
            self.logo.setPixmap(QPixmap(str(logo_path)).scaled(35,35,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        else:
            self.logo.setText("✦")
        self.logo.setFixedSize(38,38)
        top.addWidget(self.logo)
        self.brand=label("SUPER\nRENDER",12,"ink",True)
        self.brand.setMinimumWidth(93)
        top.addWidget(self.brand,1)
        self.collapse_btn=make_button("≡",secondary=True)
        self.collapse_btn.setFixedSize(34,34)
        self.collapse_btn.clicked.connect(self.toggle_sidebar)
        top.addWidget(self.collapse_btn)
        side_layout.addLayout(top)
        side_layout.addSpacing(24)
        self.nav_layout=QVBoxLayout()
        self.nav_layout.setSpacing(3)
        side_layout.addLayout(self.nav_layout)
        side_layout.addStretch(1)
        self.scan_button=make_button("↻  Buscar jogos",secondary=True)
        self.scan_button.clicked.connect(self.scan)
        side_layout.addWidget(self.scan_button)
        self.add_button=make_button("+  Adicionar jogo",secondary=True)
        self.add_button.clicked.connect(self.add_manual_game)
        side_layout.addWidget(self.add_button)
        self.side_footer=label("APLICATIVO LOCAL · v0.3.2",8,"muted")
        side_layout.addWidget(self.side_footer)
        self.populate_sidebar()

        main=QFrame(shell)
        main.setObjectName("mainBackground")
        horizontal.addWidget(main,1)
        self.main_content=main
        layout=QVBoxLayout(main)
        layout.setContentsMargins(28,19,28,19)
        layout.setSpacing(13)

        header=QHBoxLayout()
        titles=QVBoxLayout()
        titles.setSpacing(1)
        titles.addWidget(label("SUA BIBLIOTECA, SEU DESEMPENHO",9,"accent",True))
        titles.addWidget(label("O que vamos jogar hoje?",23,"ink",True))
        header.addLayout(titles,1)
        self.search=QLineEdit()
        self.search.setPlaceholderText("⌕  Buscar jogos...")
        self.search.setMinimumWidth(190)
        self.search.setMaximumWidth(290)
        self.search.textChanged.connect(self.search_changed)
        header.addWidget(self.search)
        layout.addLayout(header)

        self.feature_wrap=QFrame()
        self.feature_wrap.setObjectName("hero")
        self.feature_wrap.setMinimumHeight(215)
        self.feature_wrap.setMaximumHeight(232)
        self.feature_wrap.setStyleSheet("QFrame#hero{background:transparent;border:0;}")
        self.gradient=Grainient(self.feature_wrap)
        self.gradient.setGeometry(self.feature_wrap.rect())
        feature_layout=QVBoxLayout(self.feature_wrap)
        feature_layout.setContentsMargins(14,12,14,12)
        feature_layout.setSpacing(9)
        feature_header=QHBoxLayout()
        feature_header.addWidget(label("EM DESTAQUE",9,"ink",True))
        feature_header.addStretch(1)
        feature_header.addWidget(label("Passe o mouse para explorar",8,"muted"))
        feature_layout.addLayout(feature_header)
        self.feature=FeaturedAccordion()
        self.feature.setFixedHeight(165)
        self.feature.chosen.connect(self.on_play)
        feature_layout.addWidget(self.feature)
        layout.addWidget(self.feature_wrap)

        topline=QHBoxLayout()
        self.section_name=label("Todos os jogos",16,"ink",True)
        topline.addWidget(self.section_name)
        self.count=label("",10,"muted")
        topline.addWidget(self.count)
        topline.addStretch(1)
        self.status=label("Carregando biblioteca...",9,"muted")
        topline.addWidget(self.status)
        layout.addLayout(topline)

        self.scroller=QScrollArea()
        self.scroller.setWidgetResizable(True)
        self.scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tile_root=QWidget()
        self.tile_root.setObjectName("gameGrid")
        self.tile_root.setStyleSheet(f"QWidget#gameGrid{{background:{P['bg']};}}")
        self.tiles=QGridLayout(self.tile_root)
        self.tiles.setSpacing(13)
        self.tiles.setContentsMargins(1,2,11,18)
        self.scroller.setWidget(self.tile_root)
        self.scroller.viewport().setObjectName("superrenderViewport")
        self.scroller.viewport().setStyleSheet(
            f"QWidget#superrenderViewport{{background:{P['bg']};}}")
        layout.addWidget(self.scroller,1)

        footer=QHBoxLayout()
        footer.addWidget(label("Feito para computadores diferentes · Otimizacao reversivel",8,"muted"))
        footer.addStretch(1)
        footer.addWidget(label("SUPERRENDER  /  WINDOWS",8,"accent",True))
        layout.addLayout(footer)
        self.update_games_view()

    def asset(self,name)->Path:
        root=Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parents[1]))
        return root/"assets"/name

    def show_splash(self):
        logo=QPixmap(str(self.asset("SuperRender.png")))
        self.splash=SplashOverlay(self.wrapper,self.shell,logo)
        self.splash.setGeometry(self.wrapper.rect())
        self.splash.raise_()

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,"shell"):
            self.shell.setGeometry(self.wrapper.rect())
        if hasattr(self,"splash") and self.splash and self.splash.isVisible():
            self.splash.setGeometry(self.wrapper.rect())
        if hasattr(self,"gradient"):
            self.gradient.setGeometry(self.feature_wrap.rect())
            self.gradient.lower()
        if self.toast and self.toast.isVisible():
            self.toast.set_position()
        if hasattr(self,"_render_later"):
            self._render_later.start()

    def changeEvent(self,event):
        if event.type()==QEvent.WindowStateChange and hasattr(self,"gradient"):
            if self.isMinimized():self.gradient.timing.stop()
            elif not self.gradient.timing.isActive():self.gradient.timing.start()
        super().changeEvent(event)

    def toggle_sidebar(self):
        self.sidebar_collapsed=not self.sidebar_collapsed
        end=83 if self.sidebar_collapsed else 228
        self._side_animation=QPropertyAnimation(self.sidebar,b"maximumWidth",self)
        self._side_animation.setDuration(245)
        self._side_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._side_animation.setStartValue(self.sidebar.width())
        self._side_animation.setEndValue(end)
        self.sidebar.setMinimumWidth(0)
        self._side_animation.start()
        self.brand.setVisible(not self.sidebar_collapsed)
        self.side_footer.setVisible(not self.sidebar_collapsed)
        self.scan_button.setText("↻" if self.sidebar_collapsed else "↻  Buscar jogos")
        self.add_button.setText("+" if self.sidebar_collapsed else "+  Adicionar jogo")
        self.scan_button.setToolTip("Buscar jogos")
        self.add_button.setToolTip("Adicionar jogo")
        self.collapse_btn.setText("›" if self.sidebar_collapsed else "≡")
        for item in self.nav_items.values():item.set_collapsed(self.sidebar_collapsed)

    def populate_sidebar(self):
        while self.nav_layout.count():
            item=self.nav_layout.takeAt(0)
            if item.widget():item.widget().deleteLater()
        self.nav_items={}
        names=[("Todos os jogos","▦"),("Favoritos","☆")]
        sources=sorted({g.get("source") for g in self.games if g.get("source")})
        for source in sources:
            glyph={"Steam":"◈","Epic Games":"◆","Riot Games":"◇","GOG":"✧",
                   "Pasta local":"⌂","Atalho Windows":"▧","Manual":"+"}.get(source,"◯")
            names.append((source,glyph))
        for name,glyph in names:
            nav=SidebarItem(name,glyph)
            nav.set_collapsed(self.sidebar_collapsed)
            nav.set_selected(self.active_view==name)
            nav.clicked_name.connect(self.set_view)
            self.nav_layout.addWidget(nav)
            self.nav_items[name]=nav

    def set_view(self,name):
        self.active_view=name
        for key,item in self.nav_items.items():item.set_selected(key==name)
        self.update_games_view()

    def search_changed(self,new):
        self.search_query=new.casefold().strip()
        self._render_later.start()

    def filtered(self):
        games=[g for g in self.games if not g.get("hidden")]
        if self.active_view=="Favoritos":
            games=[g for g in games if g.get("favorite")]
        elif self.active_view!="Todos os jogos":
            games=[g for g in games if g.get("source")==self.active_view]
        if self.search_query:
            games=[g for g in games if self.search_query in
                   (g.get("name","")+" "+g.get("source","")).casefold()]
        return sorted(games,key=lambda g:(not g.get("favorite",False),
                                          g.get("name","").casefold()))

    def update_games_view(self):
        self.section_name.setText(self.active_view)
        self.render_cards()
        featured=sorted(self.games,key=lambda g:(not bool(g.get("favorite")),
                                                 g.get("name","").casefold()))
        good=featured[:5]
        for item in good:
            path=photo_file(item)
            item["_cover"]=str(path) if path.is_file() else ""
        self.feature.set_games(good)

    def render_cards(self):
        while self.tiles.count():
            it=self.tiles.takeAt(0)
            if it.widget():it.widget().deleteLater()
        self.cards={}
        games=self.filtered()
        self.section_name.setText(self.active_view)
        self.count.setText(" · "+str(len(games))+" jogos")
        width=max(self.scroller.viewport().width(),300)
        cols=max(1,min(4,(width-10)//255))
        for i,game in enumerate(games[:120]):
            card=GameCard(game)
            card.playClicked.connect(self.on_play)
            card.gearClicked.connect(self.on_gear)
            self.tiles.addWidget(card,i//cols,i%cols)
            self.cards[game["id"]]=card
            self.request_art(game)
        for col in range(cols):
            self.tiles.setColumnStretch(col,1)
        self.tiles.setRowStretch((min(len(games),120)+cols-1)//cols,1)
        if not games:
            msg=label("Ainda nao encontramos jogos neste filtro. Use Buscar jogos.",12,"muted")
            msg.setWordWrap(True)
            self.tiles.addWidget(msg,0,0,1,cols)
        if len(games)>120:
            self.status.setText("Mostrando 120 jogos. Use a busca para localizar outros.")

    def request_art(self,game):
        ident=game.get("id")
        file=photo_file(game)
        if file.is_file() or file.with_suffix(".missing").exists() or ident in self.art_loading:
            return
        self.art_loading.add(ident)
        self.executor.submit(self._art_job,dict(game))

    def _art_job(self,game):
        try:ensure_art(game)
        except Exception as error:self.messages.put(("log",str(error)))
        self.messages.put(("art",game["id"]))

    def scan(self):
        if self.scan_busy:return
        self.scan_busy=True
        self.scan_button.setEnabled(False)
        self.status.setText("Localizando instalacoes...")
        self.executor.submit(self._scan_job)

    def _scan_job(self):
        try:
            games=discover(lambda message:self.messages.put(("progress",message)))
            self.messages.put(("found",games))
        except Exception as error:
            self.messages.put(("scan_error",str(error)))

    def process_messages(self):
        for _ in range(25):
            try:typ,data=self.messages.get_nowait()
            except queue.Empty:break
            if typ=="progress":self.status.setText(shortened(data,44))
            elif typ=="found":
                db=load()
                db["games"]=sync_found(db.get("games",[]),data)
                save(db)
                self.games=db["games"]
                self.scan_busy=False
                self.scan_button.setEnabled(True)
                self.status.setText("Busca concluida")
                self.populate_sidebar()
                self.update_games_view()
                self.executor.submit(self._recovery_job,list(self.games))
                self.show_toast("Biblioteca atualizada",str(len(self.games))+" jogos detectados automaticamente.")
            elif typ=="art":
                self.art_loading.discard(data)
                card=self.cards.get(data)
                if card:card.update_cover()
                for game in self.games:
                    if game.get("id")==data:
                        pic=photo_file(game)
                        game["_cover"]=str(pic) if pic.is_file() else ""
                if any(g.get("id")==data for g in self.feature.games):
                    self.feature.set_games(self.feature.games)
            elif typ=="log":
                self.status.setText(shortened(data,56))
            elif typ=="restore":
                if data:self.show_toast("Backup seguro",shortened(data[0],100))
            elif typ=="scan_error":
                self.scan_busy=False;self.scan_button.setEnabled(True)
                self.show_toast("Falha ao buscar jogos",str(data))
            elif typ=="session":
                self.show_toast("SuperRender",data)
        if self.toast and self.toast.isVisible():
            self.toast.set_position()

    def _recovery_job(self,games):
        notes=restore_stale_sessions(games)
        if notes:self.messages.put(("restore",notes))

    def show_toast(self,title,description=""):
        if self.toast:
            try:self.toast.hide();self.toast.deleteLater()
            except RuntimeError:pass
        self.toast=SwipeToast(self.wrapper,title,description)
        self.toast.set_position()

    def add_manual_game(self):
        file,_=QFileDialog.getOpenFileName(
            self,"Localizar executavel/atalho de jogo",str(Path.home()),
            "Jogos e atalhos (*.exe *.lnk *.bat *.cmd);;Todos os arquivos (*.*)")
        if not file:return
        try:
            new=add_manual(Path(file))
        except Exception as error:
            self.show_toast("Jogo nao adicionado",str(error))
            return
        self.games=load().get("games",[])
        self.active_view="Todos os jogos"
        self.populate_sidebar()
        self.update_games_view()
        self.show_toast("Jogo adicionado",new["name"])

    def on_play(self,game):
        if game.get("skip_profile_dialog") and game.get("profile_is_default"):
            mode=game.get("default_profile","normal")
            if mode in PROFILE_ORDER:
                self.start_game(game,mode)
                return
        self.show_profile_dialog(game,launch_after=True)

    def on_gear(self,game):
        if read_session(game):
            choice=QMessageBox.question(
                self,"SuperRender — backup pendente",
                "Existe uma configuracao temporaria deste jogo.\n\n"
                "Deseja restaurar o backup original agora? O estado atual sera "
                "preservado em outro backup por seguranca.\n\n"
                "Escolha Nao para continuar apenas editando as preferencias.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if choice==QMessageBox.Yes:
                try:
                    result=restore_game(game,force=True)
                    self.show_toast("Backup",result)
                except Exception as exc:
                    QMessageBox.warning(self,"Restauracao",str(exc))
        self.show_profile_dialog(game,launch_after=False)

    def show_profile_dialog(self,game,launch_after):
        dialog=ProfileDialog(game,self)
        if not launch_after:
            dialog.setWindowTitle("SuperRender | Configurar preferencia")
            for button in dialog.findChildren(QWidget):
                if hasattr(button,"text") and callable(button.text):
                    if button.text()=="Iniciar jogo  ↗":button.setText("Salvar preferencias")
        if dialog.exec()!=ProfileDialog.Accepted:return
        settings=dialog.settings()
        game["default_profile"]=settings["default_profile"]
        game["profile_is_default"]=settings["profile_is_default"]
        game["skip_profile_dialog"]=settings["skip_profile_dialog"]
        try:
            update_game(game,default_profile=settings["default_profile"],
                        profile_is_default=settings["profile_is_default"],
                        skip_profile_dialog=settings["skip_profile_dialog"])
        except Exception as error:
            self.show_toast("Preferencias nao salvas",str(error))
        if launch_after:
            self.start_game(game,settings["selected"])
        else:
            self.show_toast("Preferencias atualizadas",
                           "Use o botao Play para iniciar com as novas opcoes.")
            self.render_cards()

    def start_game(self,game,mode):
        if mode not in PROFILE_ORDER:mode="normal"
        if is_running(game):
            self.show_toast("Jogo ja esta aberto",game.get("name","Jogo"))
            return
        # Prepara RTSS ANTES de abrir o jogo: hook fullscreen precisa estar
        # ativo no inicio. Outros PCs podem aceitar instalacao automatica.
        self.fps_hud.prepare_backend(self)
        # Nunca testar diretamente processos do jogo: ajustes de arquivo
        # so acontecem quando o usuario solicita iniciar.
        try:
            pending=read_session(game)
            if pending:
                result=restore_game(game)
                if read_session(game):
                    raise RuntimeError("Backup pendente: "+result)
            modified=prepare_game(game,mode)
        except Exception as error:
            QMessageBox.warning(self,"SuperRender — perfil",str(error))
            return
        try:
            answer=launch(game,mode,notify=lambda text:self.messages.put(("session",text)))
        except Exception as error:
            if modified:
                restore_game(game)
            QMessageBox.critical(self,"Nao foi possivel iniciar",str(error))
            return
        # O FPS e monitorado sem modificar arquivos do jogo.
        self.fps_hud.start_game(game)
        if modified:
            threading.Thread(target=monitor_and_restore,
                             args=(dict(game),lambda text:self.messages.put(("session",text))),
                             daemon=True,name="sr-restore-monitor").start()
        self.show_toast(PROFILE_INFO[mode]["title"],shortened(answer,100))
        if mode not in ("normal","light") and not get_adapter(game):
            self.show_toast("Sem adaptador grafico",
                            "Este jogo ainda nao possui ajustes graficos especificos. "
                            "Apenas prioridade de processo foi aplicada.")
        # Menos processamento de interface enquanto o jogo estiver ativo.
        self.gradient.timing.stop()
        QTimer.singleShot(650,self.showMinimized)

    def closeEvent(self,event):
        self.gradient.timing.stop()
        self.fps_hud.close()
        self.executor.shutdown(wait=False,cancel_futures=True)
        # Monitoramento de jogo continua so enquanto o programa estiver aberto.
        # Uma sessao pendente sera restaurada no proximo inicio.
        super().closeEvent(event)


def main():
    os.environ.setdefault("QT_QUICK_BACKEND","software")
    app=QApplication.instance() or QApplication(sys.argv)
    style_app(app)
    window=MainWindow()
    icon=window.asset("SuperRender.ico")
    if icon.is_file():
        window.setWindowIcon(QIcon(str(icon)))
        app.setWindowIcon(QIcon(str(icon)))
    window.show()
    return app.exec()


if __name__=="__main__":
    raise SystemExit(main())
