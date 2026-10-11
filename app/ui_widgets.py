"""Widgets visuais nativos inspirados nas referencias do usuario.

Adaptacoes Qt Widgets (Python puro, sem React, HTML, WebGL ou navegador):
Grainient => gradiente leve pintado em CPU;
LineSidebar => marcadores de proximidade/animacao sem indices;
AccordionGallery => paines de jogos com expansao;
SquishSwitch => interruptor fisico animado;
SwipeToast => avisos com dismiss;
StickerPeel => vinheta de abertura com logo e efeito de dobra.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PySide6.QtCore import (Qt, QEvent, QEasingCurve, Property, QPropertyAnimation, QAbstractAnimation,
                             QRectF, QPoint, QPointF, QTimer, Signal)
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QRadialGradient)
from PySide6.QtWidgets import (QAbstractButton, QFrame, QGraphicsBlurEffect,
                                QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                                QPushButton, QSizePolicy, QVBoxLayout, QWidget)

P = {
    "bg": "#090b16", "base": "#101324", "panel": "#17192c",
    "panel2": "#21243a", "stroke": "#32354b", "ink": "#f6f0ff",
    "muted": "#a39fb8", "accent": "#c3a1ff", "pink": "#ff9ffc",
    "mint": "#98efe2", "warm": "#ffc88c", "dark": "#10101c",
}

def color(name: str, alpha: int | None = None) -> QColor:
    col = QColor(P.get(name, name))
    if alpha is not None:
        col.setAlpha(alpha)
    return col

def label(text: str, size: int=11, role: str="", weight: bool=False) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(False)
    lab.setStyleSheet(f"color:{P.get(role, role) if role else P['ink']};background:transparent;")
    font = QFont("Segoe UI", size)
    font.setBold(weight)
    lab.setFont(font)
    return lab

def make_button(text: str, filled: bool=False, secondary: bool=False) -> QPushButton:
    widget = QPushButton(text)
    widget.setCursor(Qt.PointingHandCursor)
    widget.setMinimumHeight(38)
    widget.setObjectName("primary" if filled else ("subtle" if secondary else "button"))
    return widget


class SquishSwitch(QAbstractButton):
    """Interruptor de preferencia com thumb elastico e transicao suave."""
    def __init__(self, parent=None, value=False):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(value)
        self.setFixedSize(64, 34)
        self.setCursor(Qt.PointingHandCursor)
        self._position = 1.0 if value else 0.0
        self._anim = QPropertyAnimation(self, b"position", self)
        self._anim.setDuration(225)
        self._anim.setEasingCurve(QEasingCurve.OutBack)
        self.toggled.connect(self._animate)

    def _get_position(self):
        return self._position

    def _set_position(self, v):
        self._position = float(v)
        self.update()

    position = Property(float, _get_position, _set_position)

    def _animate(self, checked):
        self._anim.stop()
        self._anim.setStartValue(self._position)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, 62, 32)
        from_color = color("#3a3952")
        to_color = color("accent")
        x = max(0.0, min(1.0, self._position))
        mix = QColor(*(round(from_color.getRgb()[i]*(1-x)+to_color.getRgb()[i]*x) for i in range(3)))
        p.setPen(Qt.NoPen)
        p.setBrush(mix)
        p.drawRoundedRect(r, 16, 16)
        # durante deslocamento rapido, o thumb alonga ligeiramente
        stretch = max(0, 1 - abs(x - .5)*2)*3
        thumb_x = 5 + 30*x - stretch/2
        p.setBrush(color("#0e1020" if self.isChecked() else "#e0dce9"))
        p.drawRoundedRect(QRectF(thumb_x, 5, 25+stretch, 25), 12.5, 12.5)
        p.end()


class SidebarItem(QAbstractButton):
    clicked_name = Signal(str)
    def __init__(self, name: str, glyph: str, parent=None):
        super().__init__(parent)
        self.name = name
        self.glyph = glyph
        self.collapsed = False
        self.selected = False
        self._influence = 0.0
        self._anim = QPropertyAnimation(self, b"influence", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(47)
        self.clicked.connect(lambda: self.clicked_name.emit(self.name))
        self.setToolTip(name)

    def _get_influence(self):
        return self._influence

    def _set_influence(self, v):
        self._influence=float(v); self.update()
    influence=Property(float,_get_influence,_set_influence)

    def set_influence(self,value):
        if abs(self._influence-value)<0.05:return
        self._anim.stop(); self._anim.setStartValue(self._influence)
        self._anim.setEndValue(value);self._anim.start()

    def set_selected(self,value: bool):
        self.selected=value;self.update()

    def set_collapsed(self,value: bool):
        self.collapsed=value;self.update()

    def paintEvent(self,_event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        intensity=max(self._influence, 1.0 if self.selected else 0.0)
        if self.selected:
            p.setPen(Qt.NoPen)
            p.setBrush(color("accent", 24))
            p.drawRoundedRect(QRectF(7,3,self.width()-14,40),11,11)
        marker_len=6+21*intensity
        p.setPen(QPen(color("accent" if intensity>.4 else "muted",190),1.7))
        p.drawLine(9,24,9+marker_len,24)
        fg=color("accent") if self.selected else color("muted")
        if intensity>.15 and not self.selected:
            fg=color("ink")
        p.setPen(fg)
        glyph_f=QFont("Segoe UI Symbol",15,QFont.Medium)
        p.setFont(glyph_f)
        x=28 if self.collapsed else 39
        p.drawText(QRectF(x,5,27,37),Qt.AlignCenter,self.glyph)
        if not self.collapsed:
            font=QFont("Segoe UI",10,QFont.DemiBold if self.selected else QFont.Medium)
            p.setFont(font)
            p.drawText(QRectF(70+9*intensity,5,self.width()-85,37),Qt.AlignVCenter|Qt.AlignLeft,
                       self.name)
        p.end()


class Grainient(QWidget):
    """Pintura de gradientes e grao estatico CPU; animacao lenta desliga ao minimizar."""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.phase=0.0
        rnd=random.Random(29)
        self._grain=[(rnd.random(),rnd.random(),rnd.randrange(1,3)) for _ in range(100)]
        self.timing=QTimer(self);self.timing.setInterval(110)
        self.timing.timeout.connect(self.advance)
        self.timing.start()
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def advance(self):
        if self.isVisible():
            self.phase+=0.02
            self.update()

    def paintEvent(self,_event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        rect=QRectF(self.rect())
        p.fillRect(rect,color("#221d39"))
        w,h=self.width(),self.height()
        x=w*(.27+.07*math.sin(self.phase))
        y=h*(.3+.06*math.cos(self.phase*1.3))
        grad=QRadialGradient(QPointF(x,y),w*.78)
        grad.setColorAt(0,color("#693c8c",190));grad.setColorAt(.55,color("#533c8b",100))
        grad.setColorAt(1,color("#18152e",0))
        p.fillRect(rect,grad)
        grad2=QRadialGradient(QPointF(w*(.8+.04*math.cos(self.phase*.6)),h*.4),w*.62)
        grad2.setColorAt(0,color("#f09bbf",135));grad2.setColorAt(.6,color("#8462cc",45))
        grad2.setColorAt(1,color("#171224",0))
        p.fillRect(rect,grad2)
        grad3=QLinearGradient(0,0,w,h)
        grad3.setColorAt(0,color("#171829",25))
        grad3.setColorAt(1,color("#080b17",185))
        p.fillRect(rect,grad3)
        p.setPen(Qt.NoPen);p.setBrush(QColor(255,245,255,13))
        for rx,ry,s in self._grain:
            p.drawRect(int(rx*w),int(ry*h),s,s)
        p.end()


class FeaturedAccordion(QWidget):
    """Galeria com expansao por hover (sem site web nem animacao GPU)."""
    chosen=Signal(dict)
    def __init__(self,parent=None):
        super().__init__(parent)
        self.games=[]
        self.active=0
        self._ratios=[]
        self._target=[]
        self._timer=QTimer(self);self._timer.setInterval(18)
        self._timer.timeout.connect(self.animate)
        self.setMouseTracking(True)
        self.setFixedHeight(214)
        self.setCursor(Qt.PointingHandCursor)
        self._cover_pix={}

    def set_games(self,games):
        self.games=list(games[:5])
        n=len(self.games)
        self.active=min(self.active,max(n-1,0))
        self._ratios=[1.0]*n
        self._target=[1.0]*n
        self.set_active(self.active)
        self.update()

    def set_active(self,index):
        if index<0 or index>=len(self.games):return
        self.active=index
        self._target=[3.4 if i==index else 1.0 for i in range(len(self.games))]
        if len(self._ratios)!=len(self._target):
            self._ratios=[1.0]*len(self._target)
        self._timer.start()
        self.update()

    def animate(self):
        pending=False
        for i,target in enumerate(self._target):
            self._ratios[i]+=(target-self._ratios[i])*.24
            if abs(self._ratios[i]-target)>.02:pending=True
        self.update()
        if not pending:self._timer.stop()

    def rectangles(self):
        n=len(self.games)
        if not n:return []
        gap=9
        usable=max(0,self.width() - gap*(n-1))
        weights=self._ratios if len(self._ratios)==n else [1.0]*n
        total=sum(weights)
        pos=0
        result=[]
        for v in weights:
            width=usable*v/total
            result.append(QRectF(pos,0,width,self.height()))
            pos+=width+gap
        return result

    def mouseMoveEvent(self,event):
        x=event.position().x()
        for i,rect in enumerate(self.rectangles()):
            if rect.contains(QPointF(x,event.position().y())):
                if i!=self.active:self.set_active(i)
                break
        super().mouseMoveEvent(event)

    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton:
            for i,r in enumerate(self.rectangles()):
                if r.contains(event.position()) and i<len(self.games):
                    self.chosen.emit(self.games[i])
                    break

    def paintEvent(self,_event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        for i,(game,r) in enumerate(zip(self.games,self.rectangles())):
            if r.width()<2:continue
            path=QPainterPath()
            path.addRoundedRect(r,13,13)
            p.save();p.setClipPath(path)
            p.fillRect(r,color("#2a2543"))
            picpath=game.get("_cover","")
            if picpath:
                pix=self._cover_pix.get(picpath)
                if pix is None:
                    pix=QPixmap(picpath)
                    self._cover_pix[picpath]=pix
                if not pix.isNull():
                    scaled=pix.scaled(int(max(r.width(),1)),int(r.height()),Qt.KeepAspectRatioByExpanding,Qt.SmoothTransformation)
                    crop_x=(scaled.width()-r.width())/2
                    crop_y=(scaled.height()-r.height())/2
                    p.drawPixmap(QPointF(r.x()-crop_x,r.y()-crop_y),scaled)
            shading=QLinearGradient(r.left(),r.top(),r.left(),r.bottom())
            shading.setColorAt(0,QColor(7,9,22,20))
            shading.setColorAt(.52,QColor(7,9,22,86))
            shading.setColorAt(1,QColor(7,9,22,235))
            p.fillRect(r,shading)
            if i==self.active:
                p.setPen(QPen(color("accent"),2))
                p.drawRoundedRect(r.adjusted(1,1,-1,-1),12,12)
            p.setPen(color("ink"));f=QFont("Segoe UI",11,QFont.Bold);p.setFont(f)
            bound=r.adjusted(12,10,-12,-21)
            p.drawText(bound,Qt.AlignBottom|Qt.AlignLeft|Qt.TextWordWrap,game.get("name","Jogo")[:45])
            p.setPen(color("accent" if i==self.active else "muted"))
            f.setPointSize(8);p.setFont(f)
            p.drawText(r.adjusted(13,0,-6,-6),Qt.AlignBottom|Qt.AlignLeft,
                       "DESTAQUE" if i==self.active else "BIBLIOTECA")
            p.restore()
        p.end()


class SwipeToast(QFrame):
    closed=Signal()
    def __init__(self,parent,title,description="",ms=3300):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setFixedWidth(345)
        self.setStyleSheet(
            f"QFrame#toast{{background:{P['panel2']};border:1px solid {P['stroke']};"
            f"border-radius:14px;}} QLabel{{color:{P['ink']};background:transparent;}}")
        lay=QVBoxLayout(self)
        lay.setContentsMargins(18,12,20,10)
        lay.setSpacing(5)
        upper=QHBoxLayout()
        upper.addWidget(label(title,11,"ink",True),1)
        x=make_button("Ã—",secondary=True)
        x.setFixedSize(26,26)
        x.clicked.connect(self.dismiss)
        upper.addWidget(x)
        lay.addLayout(upper)
        desc=label(description,9,"muted")
        desc.setWordWrap(True); lay.addWidget(desc)
        self.bar=QFrame();self.bar.setFixedHeight(2)
        self.bar.setStyleSheet(f"background:{P['accent']};border:0px;")
        lay.addWidget(self.bar)
        self.adjustSize()
        self.opacity=QGraphicsOpacityEffect(self);self.setGraphicsEffect(self.opacity)
        self._alpha=QPropertyAnimation(self.opacity,b"opacity",self)
        self._alpha.setDuration(220);self._alpha.setStartValue(0.0);self._alpha.setEndValue(1.0)
        self._born=QTimer(self);self._born.setSingleShot(True)
        self._born.timeout.connect(self.dismiss)
        self._duration=ms
        self._hold=False
        self._progress=1.0
        self._fuse=QTimer(self);self._fuse.setInterval(45)
        self._fuse.timeout.connect(self.tick)
        self._gesture=QPoint()
        self.show()
        self._alpha.start()
        self._born.start(ms)
        self._fuse.start()

    def set_position(self):
        parent=self.parentWidget()
        if parent:
            self.move(max(8,parent.width()-self.width()-26),max(8,parent.height()-self.height()-24))
            self.raise_()

    def tick(self):
        if self._hold:return
        self._progress=max(0,self._progress-45/max(self._duration,1))
        self.bar.setFixedWidth(max(2,int((self.width()-38)*self._progress)))

    def enterEvent(self,e):
        self._hold=True;self._born.stop();super().enterEvent(e)
    def leaveEvent(self,e):
        self._hold=False
        self._born.start(max(400,int(self._duration*self._progress)))
        super().leaveEvent(e)

    def mousePressEvent(self,e):
        self._gesture=e.globalPosition().toPoint()
        super().mousePressEvent(e)
    def mouseReleaseEvent(self,e):
        if (e.globalPosition().toPoint()-self._gesture).manhattanLength()>70:
            self.dismiss()
        else:
            super().mouseReleaseEvent(e)

    def dismiss(self):
        if not self.isVisible():return
        self._born.stop();self._fuse.stop()
        self._alpha.stop()
        self._alpha.setStartValue(self.opacity.opacity());self._alpha.setEndValue(0)
        try:self._alpha.finished.disconnect()
        except (RuntimeError,TypeError):pass
        self._alpha.finished.connect(self.finish)
        self._alpha.start()
    def finish(self):
        self.closed.emit();self.deleteLater()


class StickerBadge(QWidget):
    """Marca estetica nao interativa, com canto dobrado e sombra."""
    def __init__(self,pixmap:QPixmap,parent=None):
        super().__init__(parent)
        self.original=pixmap
        self._angle=-11.0
        self.setFixedSize(236,236)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def _get_angle(self):return self._angle
    def _set_angle(self,v):self._angle=float(v);self.update()
    angle=Property(float,_get_angle,_set_angle)

    def paintEvent(self,_event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        p.translate(self.width()/2,self.height()/2)
        p.rotate(self._angle)
        # A arte ocupa o centro visual do splash, nao um icone pequeno.
        p.scale(1.46,1.46)
        shadow=QRectF(-61,-61,122,122)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0,0,0,84));p.drawRoundedRect(shadow.translated(8,11),18,18)
        p.setBrush(color("#f6edff"));p.drawRoundedRect(shadow,18,18)
        pix=self.original
        if not pix.isNull():
            target=QRectF(-52,-52,104,104)
            p.drawPixmap(target,pix,QRectF(pix.rect()))
        # dobra do adesivo: pequena aba com diagonal
        fold=QPainterPath()
        fold.moveTo(43,-56);fold.lineTo(66,-56);fold.lineTo(66,-34);fold.closeSubpath()
        p.fillPath(fold,color("#cdb8eb"))
        p.setPen(QPen(color("#a993bc",140),1))
        p.drawLine(43,-56,66,-34)
        p.end()


class SplashOverlay(QWidget):
    """Vinheta temporaria: adesivo EXATAMENTE centralizado, blur ao fundo."""
    finished=Signal()

    def __init__(self,parent,behind:QWidget,logo:QPixmap):
        super().__init__(parent)
        self.setObjectName("splash")
        self.setAttribute(Qt.WA_StyledBackground,True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents,True)
        self.setStyleSheet("QWidget#splash{background:rgba(8,8,20,215);}")
        self.behind=behind
        self.blur=QGraphicsBlurEffect(behind)
        self.blur.setBlurRadius(15)
        behind.setGraphicsEffect(self.blur)
        self.badge=StickerBadge(logo,self)
        self.loading=label("PREPARANDO SUA BIBLIOTECA",11,"ink",True)
        self.loading.setParent(self)
        self.loading.setAlignment(Qt.AlignCenter)
        self.loading.setStyleSheet(
            f"color:{P['muted']};background:transparent;letter-spacing:2px;")
        self.brand=label("SUPERRENDER",25,"ink",True)
        self.brand.setParent(self)
        self.brand.setAlignment(Qt.AlignCenter)
        self.brand.setStyleSheet(
            f"color:{P['ink']};background:transparent;letter-spacing:3px;")
        self._exiting=False
        # Geometria do splash configurada ANTES de calcular o destino.
        self.setGeometry(parent.rect())
        center=self.badge_target()
        self.layout_caption()
        self._anim_badge=QPropertyAnimation(self.badge,b"angle",self)
        self._anim_badge.setDuration(735)
        self._anim_badge.setEasingCurve(QEasingCurve.OutBack)
        self._anim_badge.setStartValue(-24.0)
        self._anim_badge.setEndValue(4.0)
        self.opacity=QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity)
        self._fade=QPropertyAnimation(self.opacity,b"opacity",self)
        self._fade.setDuration(410)
        self._fade.setEasingCurve(QEasingCurve.InOutCubic)
        self._fade.finished.connect(self.end)
        self._timer=QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)
        start=QPoint(center.x(),-self.badge.height()-26)
        self.badge.move(start)
        self._travel=QPropertyAnimation(self.badge,b"pos",self)
        self._travel.setStartValue(start)
        self._travel.setEndValue(center)
        self._travel.setDuration(780)
        self._travel.setEasingCurve(QEasingCurve.OutBack)
        self.show()
        self.raise_()
        self._travel.start()
        self._anim_badge.start()
        self._timer.start(1700)

    def badge_target(self)->QPoint:
        """Centraliza o adesivo pelo centro geometrico da janela inteira."""
        return QPoint(
            (self.width()-self.badge.width())//2,
            (self.height()-self.badge.height())//2,
        )

    def layout_caption(self):
        w=self.width()
        target=self.badge_target()
        bottom=target.y()+self.badge.height()
        self.brand.setGeometry(0,bottom+2,w,46)
        self.loading.setGeometry(0,bottom+50,w,28)

    def resizeEvent(self,event):
        target=self.badge_target()
        self.layout_caption()
        travel=getattr(self,"_travel",None)
        if travel is None or travel.state()==QAbstractAnimation.Stopped:
            if not self._exiting:
                self.badge.move(target)
        elif not self._exiting:
            travel.setEndValue(target)
        super().resizeEvent(event)

    def dismiss(self):
        if not self.isVisible() or self._exiting:
            return
        self._exiting=True
        self._travel.stop()
        self._travel.setStartValue(self.badge.pos())
        self._travel.setEndValue(QPoint(self.width()+self.badge.width(),
                                        self.badge.y()-95))
        self._travel.setDuration(440)
        self._travel.setEasingCurve(QEasingCurve.InCubic)
        self._travel.start()
        self._anim_badge.stop()
        self._anim_badge.setStartValue(self.badge.angle)
        self._anim_badge.setEndValue(38.0)
        self._anim_badge.setDuration(410)
        self._anim_badge.start()
        self._fade.setStartValue(self.opacity.opacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def end(self):
        self.hide()
        self._timer.stop()
        self.behind.setGraphicsEffect(None)
        self.finished.emit()
        self.deleteLater()
