"""Dialogo nativo de escolha de perfil para cada jogo."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel,
                                QPushButton, QScrollArea, QSizePolicy,
                                QVBoxLayout, QWidget)

from .optimization import PROFILE_INFO, PROFILE_ORDER, supports_graphic_profile
from .ui_widgets import P, SquishSwitch, label, make_button


class ProfileRow(QFrame):
    activated = Signal(str)
    def __init__(self, ident: str, parent=None):
        super().__init__(parent)
        self.ident = ident
        self.selected = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(72)
        self.setObjectName("profileChoice")
        self.setAttribute(Qt.WA_StyledBackground, True)
        info = PROFILE_INFO[ident]
        row = QHBoxLayout(self)
        row.setSpacing(11); row.setContentsMargins(15,7,14,7)
        self.glyph = QLabel("◯")
        font = QFont("Segoe UI", 17)
        self.glyph.setFont(font)
        self.glyph.setFixedWidth(26)
        self.glyph.setStyleSheet(f"color:{info['accent']};background:transparent;")
        row.addWidget(self.glyph)
        col=QVBoxLayout();col.setSpacing(3)
        title=label(info["title"], 11, "ink",True)
        desc=label(info["sub"],9,"muted")
        col.addWidget(title);col.addWidget(desc)
        row.addLayout(col,1)
        self.badge=label("",9,"accent",True)
        row.addWidget(self.badge)
        self._paint_selection()

    def _paint_selection(self):
        if self.selected:
            self.setStyleSheet(
                f"QFrame#profileChoice{{background:#302743;border:1.5px solid "
                f"{P['accent']};border-radius:13px;}}")
        else:
            self.setStyleSheet(
                f"QFrame#profileChoice{{background:#1b1b31;border:1px solid "
                f"{P['stroke']};border-radius:13px;}}"
                f"QFrame#profileChoice:hover{{background:#27233b;}}")
        self.glyph.setText("◉" if self.selected else "○")
        self.badge.setText("SELECIONADO" if self.selected else "")

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.LeftButton:
            self.activated.emit(self.ident)
        return super().mouseReleaseEvent(event)


class ProfileDialog(QDialog):
    """Leitor e editor das duas preferencias: padrao e abrir sem perguntar."""
    def __init__(self,game:dict,parent=None):
        super().__init__(parent)
        self.game=game
        self.setWindowTitle("SuperRender | Escolher inicializacao")
        self.setMinimumWidth(540)
        self.setModal(True)
        self.setStyleSheet(f"""
            QDialog{{background:{P["bg"]};color:{P["ink"]};}}
            QLabel{{background:transparent;}}
            QPushButton#primary{{background:{P["accent"]};color:{P["dark"]};
                border:0;border-radius:10px;padding:10px 19px;font-weight:700;}}
            QPushButton#primary:hover{{background:#d7c3ff;}}
            QPushButton#subtle{{background:{P["panel2"]};color:{P["muted"]};
                border:1px solid {P["stroke"]};border-radius:10px;padding:9px 18px;}}
            QPushButton#subtle:hover{{background:#34334b;color:{P["ink"]};}}
        """)
        self.selected=game.get("default_profile","normal")
        if self.selected not in PROFILE_ORDER:self.selected="normal"
        root=QVBoxLayout(self)
        root.setContentsMargins(27,17,27,17);root.setSpacing(9)

        header=label("COMO DESEJA JOGAR?",11,"accent",True)
        root.addWidget(header)
        title=label(game.get("name","Seu jogo"),22,"ink",True)
        title.setWordWrap(True);root.addWidget(title)
        desc=label("Escolha o equilibrio entre qualidade de imagem e desempenho.",10,"muted")
        desc.setWordWrap(True);root.addWidget(desc)
        root.addSpacing(5)

        self.list_panel=QScrollArea(self)
        self.list_panel.setFrameShape(QFrame.NoFrame)
        self.list_panel.setWidgetResizable(True)
        self.list_panel.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_panel.setStyleSheet(
            "QScrollArea{border:0;background:transparent;}"
            "QScrollArea QWidget{background:transparent;}"
            "QScrollBar:vertical{background:#17192c;width:7px;}"
            "QScrollBar::handle:vertical{background:#615774;border-radius:3px;}"
        )
        list_body=QWidget()
        list_layout=QVBoxLayout(list_body)
        list_layout.setSpacing(8)
        list_layout.setContentsMargins(2,2,10,2)
        self.rows={}
        for ident in PROFILE_ORDER:
            card=ProfileRow(ident)
            card.activated.connect(self.select)
            self.rows[ident]=card
            list_layout.addWidget(card)
        self.list_panel.setWidget(list_body)
        self.list_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Reserve enough room for the fixed footer, even at 1366x768.
        screen = QGuiApplication.primaryScreen()
        usable = screen.availableGeometry().height() if screen else 800
        natural_rows = len(PROFILE_ORDER)*72 + max(0,len(PROFILE_ORDER)-1)*8 + 6
        self.list_panel.setFixedHeight(min(natural_rows,max(190,usable-375)))
        root.addWidget(self.list_panel,1)

        self.explainer=label("",10,"muted")
        self.explainer.setWordWrap(True)
        self.explainer.setMinimumHeight(47)
        self.explainer.setStyleSheet(
            f"background:{P['base']};color:{P['muted']};"
            f"border:1px solid {P['stroke']};border-radius:9px;padding:11px;"
        )
        root.addWidget(self.explainer)
        root.addSpacing(6)
        self.primary_switch=self.option(
            root,"Usar este perfil como principal",
            "Deixa este perfil preselecionado nas proximas vezes.",
            bool(game.get("default_profile") and game.get("profile_is_default",False))
        )
        self.autoplay_switch=self.option(
            root,"Abrir direto, sem perguntar novamente",
            "No proximo Play, inicia automaticamente com o perfil salvo.",
            bool(game.get("skip_profile_dialog",False))
        )
        self.autoplay_switch.toggled.connect(self._auto_requires_default)
        footer=QHBoxLayout(); footer.setSpacing(12); footer.addStretch(1)
        cancel=make_button("Cancelar",secondary=True)
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        go=make_button("Iniciar jogo  ↗",filled=True)
        go.clicked.connect(self.accept)
        footer.addWidget(go)
        root.addSpacing(10);root.addLayout(footer)
        self.select(self.selected)

    def option(self,layout,title:str,sub:str,value:bool)->SquishSwitch:
        row=QHBoxLayout()
        col=QVBoxLayout();col.setSpacing(2)
        title_label=label(title,10,"ink",True)
        subtitle=label(sub,9,"muted")
        col.addWidget(title_label);col.addWidget(subtitle)
        row.addLayout(col,1)
        toggle=SquishSwitch(value=value)
        row.addWidget(toggle)
        layout.addLayout(row)
        return toggle

    def _auto_requires_default(self,state):
        if state:self.primary_switch.setChecked(True)

    def select(self,profile):
        if profile not in PROFILE_ORDER:return
        self.selected=profile
        for ident,row in self.rows.items():
            row.selected=ident==profile
            row._paint_selection()
        explanation=PROFILE_INFO[profile]["details"]
        if profile not in ("normal","light","render") and not supports_graphic_profile(self.game):
            explanation=(
                "Este jogo ainda nao possui adaptador grafico no SuperRender. "
                "O perfil aplica apenas prioridade de processo; nao altera a resolucao "
                "nem os graficos. Novos adaptadores serao adicionados por jogo."
            )
        self.explainer.setText(explanation)

    def settings(self)->dict:
        default=self.primary_switch.isChecked() or self.autoplay_switch.isChecked()
        return {
            "selected":self.selected,
            "default_profile":self.selected if default else self.game.get("default_profile","normal"),
            "profile_is_default":default,
            "skip_profile_dialog":self.autoplay_switch.isChecked(),
        }
