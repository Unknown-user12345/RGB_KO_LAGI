#!/usr/bin/env python3
"""
PREDATOR CONTROL — Acer Predator PH16-72
Requires: PyQt6  →  pip install PyQt6 --break-system-packages
Run with: sudo -E python predator-gui.py
"""

import sys, os, subprocess
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QGroupBox, QSpinBox, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QLinearGradient, QPalette

# ── Paths ─────────────────────────────────────────────────────────────────────
PREDATOR  = "/sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi/predator_sense"
PROFILE   = "/sys/firmware/acpi/platform_profile"
PROF_CHOI = "/sys/firmware/acpi/platform_profile_choices"
HWMON     = "/sys/devices/platform/acer-wmi/hwmon"
CORETEMP  = "/sys/class/hwmon"

# ── Colors ────────────────────────────────────────────────────────────────────
C = {
    "bg":      "#020c0c",
    "bg2":     "#050f0f",
    "bg3":     "#091818",
    "border":  "#0e2e2e",
    "green":   "#00ff88",
    "green3":  "#003322",
    "cyan":    "#00eeff",
    "red":     "#ff2244",
    "orange":  "#ff7700",
    "dim":     "#2a5544",
    "text":    "#b0ffe0",
    "textdim": "#2a5040",
}

SS = f"""
QMainWindow, QWidget {{
    background-color: {C['bg']};
    color: {C['text']};
    font-family: 'Courier New', monospace;
}}
QGroupBox {{
    border: 1px solid {C['border']};
    border-radius: 2px;
    margin-top: 14px;
    padding-top: 10px;
    font-size: 10px;
    font-weight: bold;
    color: {C['green']};
    letter-spacing: 3px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 8px;
    background-color: {C['bg']};
    color: {C['green']};
}}
QSpinBox {{
    background: {C['bg3']};
    border: 1px solid {C['border']};
    border-radius: 2px;
    color: {C['green']};
    font-family: 'Courier New';
    font-size: 18px;
    font-weight: bold;
    padding: 4px 8px;
    min-width: 68px;
    min-height: 36px;
}}
QSpinBox::up-button, QSpinBox::down-button {{ width:0; height:0; border:none; }}
QScrollBar:vertical {{
    background: {C['bg2']};
    width: 4px;
    border-radius: 2px;
}}
QScrollBar::handle:vertical {{ background: {C['green3']}; border-radius: 2px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""

# ── Helpers ───────────────────────────────────────────────────────────────────
def read(path):
    try:
        with open(path) as f: return f.read().strip()
    except: return None

def write(path, val):
    try:
        with open(path, 'w') as f: f.write(str(val)); return True
    except:
        try:
            subprocess.run(['sudo','tee',path], input=str(val).encode(),
                           capture_output=True, check=True); return True
        except: return False

def get_fan_rpms():
    try:
        for e in os.listdir(HWMON):
            p = os.path.join(HWMON, e)
            f1 = read(os.path.join(p, "fan1_input"))
            f2 = read(os.path.join(p, "fan2_input"))
            if f1 and f2: return int(f1), int(f2)
    except: pass
    return 0, 0

def get_cpu_temp():
    try:
        for d in os.listdir(CORETEMP):
            if read(os.path.join(CORETEMP, d, "name")) == "coretemp":
                t = read(os.path.join(CORETEMP, d, "temp1_input"))
                if t: return int(t) // 1000
    except: pass
    t = read("/sys/class/thermal/thermal_zone0/temp")
    return int(t) // 1000 if t else 0

# ── Arc Gauge ─────────────────────────────────────────────────────────────────
class ArcGauge(QWidget):
    def __init__(self, label, max_val, unit, color=None, parent=None):
        super().__init__(parent)
        self.label = label; self.max_val = max_val
        self.unit = unit; self.color = QColor(color or C['green'])
        self._value = 0; self.setFixedSize(148, 148)

    def setValue(self, v):
        self._value = max(0, min(v, self.max_val)); self.update()

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        cx, cy = w//2, h//2; r = min(w,h)//2 - 18
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        pen = QPen(QColor(C['bg3']), 7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(cx-r, cy-r, r*2, r*2, 225*16, -270*16)

        frac = self._value / self.max_val if self.max_val else 0
        span = int(-270 * 16 * frac)
        if span:
            col = (QColor(C['red']) if frac > 0.85
                   else QColor(C['orange']) if frac > 0.65
                   else self.color)
            gpen = QPen(QColor(col.red(), col.green(), col.blue(), 35), 14)
            gpen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(gpen)
            p.drawArc(cx-r, cy-r, r*2, r*2, 225*16, span)
            apen = QPen(col, 7)
            apen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(apen)
            p.drawArc(cx-r, cy-r, r*2, r*2, 225*16, span)

        p.setPen(QPen(self.color))
        p.setFont(QFont("Courier New", 16, QFont.Weight.Bold))
        p.drawText(0, cy-15, w, 24, Qt.AlignmentFlag.AlignCenter, str(self._value))
        p.setPen(QPen(QColor(C['dim'])))
        p.setFont(QFont("Courier New", 8))
        p.drawText(0, cy+9, w, 16, Qt.AlignmentFlag.AlignCenter, self.unit)
        p.setPen(QPen(QColor(C['textdim'])))
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.drawText(0, h-18, w, 14, Qt.AlignmentFlag.AlignCenter, f"─ {self.label} ─")

# ── Fan Spinbox ───────────────────────────────────────────────────────────────
class FanControl(QWidget):
    def __init__(self, label, color, parent=None):
        super().__init__(parent)
        self.color = color
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0,0,0,0); lay.setSpacing(6)

        lbl = QLabel(label)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(f"color:{C['textdim']};font-size:10px;letter-spacing:2px;")
        lay.addWidget(lbl)

        row = QHBoxLayout(); row.setSpacing(4)
        self.btn_minus = self._mkbtn("−")
        self.spin = QSpinBox()
        self.spin.setRange(0, 100); self.spin.setValue(0)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_plus = self._mkbtn("+")
        self.btn_minus.clicked.connect(lambda: self.spin.setValue(max(0, self.spin.value()-5)))
        self.btn_plus.clicked.connect(lambda: self.spin.setValue(min(100, self.spin.value()+5)))
        row.addWidget(self.btn_minus); row.addWidget(self.spin, 1); row.addWidget(self.btn_plus)
        lay.addLayout(row)

        self.pct = QLabel("AUTO")
        self.pct.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pct.setStyleSheet(f"color:{color};font-size:11px;font-weight:bold;")
        lay.addWidget(self.pct)
        self.spin.valueChanged.connect(lambda v: self.pct.setText("AUTO" if v==0 else f"{v}%"))

    def _mkbtn(self, t):
        b = QPushButton(t); b.setFixedSize(34,34)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(f"""
            QPushButton {{
                background:{C['bg3']};border:1px solid {C['border']};
                border-radius:2px;color:{self.color};font-size:18px;font-weight:bold;
            }}
            QPushButton:hover {{ background:{C['green3']};border-color:{self.color}; }}
        """)
        return b

    def value(self): return self.spin.value()
    def setValue(self, v):
        self.spin.blockSignals(True); self.spin.setValue(v)
        self.pct.setText("AUTO" if v==0 else f"{v}%")
        self.spin.blockSignals(False)

# ── Mode Button ───────────────────────────────────────────────────────────────
class ModeBtn(QPushButton):
    COLS = {
        "low-power":"#00eeff","quiet":"#00ff88","balanced":"#00ff88",
        "balanced-performance":"#ff7700","performance":"#ff2244",
    }
    def __init__(self, mode, parent=None):
        super().__init__(mode.upper().replace("-","\n"), parent)
        self.mode = mode; self.col = self.COLS.get(mode, C['green'])
        self.setCheckable(True); self.setMinimumSize(82,52)
        self.setCursor(Qt.CursorShape.PointingHandCursor); self._style(False)

    def setActive(self, v):
        self.setChecked(v); self._style(v)

    def _style(self, on):
        if on:
            self.setStyleSheet(f"""QPushButton {{
                background:rgba(0,255,136,0.07);border:1px solid {self.col};
                border-radius:2px;color:{self.col};
                font-size:8px;font-weight:bold;letter-spacing:1px;padding:4px 2px;
            }}""")
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background:{C['bg3']};border:1px solid {C['border']};
                    border-radius:2px;color:{C['textdim']};
                    font-size:8px;font-weight:bold;letter-spacing:1px;padding:4px 2px;
                }}
                QPushButton:hover {{ border-color:{self.col};color:{self.col}; }}
            """)

# ── Glow Toggle ───────────────────────────────────────────────────────────────
class GlowToggle(QPushButton):
    def __init__(self, label, parent=None):
        super().__init__(label, parent)
        self.setCheckable(True); self.setMinimumHeight(40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggled.connect(self._style); self._style(False)

    def _style(self, on):
        if on:
            self.setStyleSheet(f"""QPushButton {{
                background:{C['green3']};border:1px solid {C['green']};
                border-radius:2px;color:{C['green']};
                font-size:11px;font-weight:bold;letter-spacing:2px;padding:4px 10px;
            }}
            QPushButton:hover {{ background:#004d28; }}""")
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background:{C['bg3']};border:1px solid {C['border']};
                    border-radius:2px;color:{C['textdim']};
                    font-size:11px;font-weight:bold;letter-spacing:2px;padding:4px 10px;
                }}
                QPushButton:hover {{ border-color:{C['dim']};color:{C['text']}; }}
            """)

# ── Action Button ─────────────────────────────────────────────────────────────
def mkbtn(text, color):
    b = QPushButton(text); b.setMinimumHeight(34)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(f"""
        QPushButton {{
            background:{C['bg3']};border:1px solid {color};border-radius:2px;
            color:{color};font-size:10px;font-weight:bold;
            letter-spacing:2px;padding:4px 16px;
        }}
        QPushButton:hover {{ background:rgba(0,255,136,0.07); }}
        QPushButton:pressed {{ background:rgba(0,255,136,0.14); }}
    """)
    return b

# ── Status Bar ────────────────────────────────────────────────────────────────
class StatusBar(QLabel):
    _b = f"background:{C['bg2']};border-top:1px solid {C['border']};" \
         f"font-size:10px;padding:0 14px;letter-spacing:1px;"
    def __init__(self, parent=None):
        super().__init__("●  SYSTEM ONLINE", parent)
        self.setFixedHeight(26); self.setStyleSheet(self._b+f"color:{C['dim']};")
    def ok(self, msg):
        self.setStyleSheet(self._b+f"color:{C['green']};"); self.setText(f"✓  {msg}")
        QTimer.singleShot(3000, self._reset)
    def err(self, msg):
        self.setStyleSheet(self._b+f"color:{C['red']};"); self.setText(f"✗  {msg}")
        QTimer.singleShot(3000, self._reset)
    def _reset(self):
        self.setStyleSheet(self._b+f"color:{C['dim']};"); self.setText("●  SYSTEM ONLINE")

# ── Header ────────────────────────────────────────────────────────────────────
class Header(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent); self.setFixedHeight(60)

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(C['bg2']))
        g = QLinearGradient(0,0,w,0)
        g.setColorAt(0, QColor(0,0,0,0)); g.setColorAt(0.2, QColor(0,255,136,160))
        g.setColorAt(0.6, QColor(0,238,255,160)); g.setColorAt(1, QColor(0,0,0,0))
        p.fillRect(0, h-2, w, 2, g)
        p.setPen(QPen(QColor(C['green'])))
        p.setFont(QFont("Courier New", 22, QFont.Weight.Bold))
        p.drawText(18, 0, w, h-4, Qt.AlignmentFlag.AlignVCenter, "PREDATOR")
        p.setPen(QPen(QColor(C['cyan'])))
        p.setFont(QFont("Courier New", 22))
        p.drawText(150, 0, w, h-4, Qt.AlignmentFlag.AlignVCenter, " CONTROL")
        p.setPen(QPen(QColor(C['textdim'])))
        p.setFont(QFont("Courier New", 8))
        p.drawText(20, 38, 400, 16, Qt.AlignmentFlag.AlignVCenter,
                   "PH16-72  //  ARCH LINUX  //  SYSTEM INTERFACE")
        p.drawText(0, 0, w-16, h,
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   "LINUWU-SENSE //")

# ── Main Window ───────────────────────────────────────────────────────────────
class PredatorGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PREDATOR CONTROL")
        self.setMinimumSize(720, 580)
        self.resize(800, 620)
        self.setStyleSheet(SS)
        self._build_ui()
        # Load initial state AFTER window is fully built
        QTimer.singleShot(100, self._load_initial_state)
        self.timer = QTimer()
        self.timer.timeout.connect(self._refresh)
        self.timer.start(2000)
        self._refresh()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        root.addWidget(Header())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(scroll, 1)

        body = QWidget(); scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(16,14,16,14); lay.setSpacing(12)

        # ── Telemetry ──
        tele = QGroupBox("LIVE TELEMETRY")
        tr = QHBoxLayout(tele); tr.setSpacing(12)
        self.g_cpu_fan  = ArcGauge("CPU FAN",  6000, "RPM", C['green'])
        self.g_gpu_fan  = ArcGauge("GPU FAN",  6000, "RPM", C['cyan'])
        self.g_cpu_temp = ArcGauge("CPU TEMP", 100,  "°C",  C['orange'])
        for g in [self.g_cpu_fan, self.g_gpu_fan, self.g_cpu_temp]:
            tr.addWidget(g, alignment=Qt.AlignmentFlag.AlignCenter)
        sc = QVBoxLayout(); sc.setSpacing(6)
        self.s_mode = self._stat("MODE",    "--")
        self.s_temp = self._stat("PACKAGE", "-- °C")
        self.s_nvme = self._stat("NVME",    "-- °C")
        self.s_bat  = self._stat("BATTERY", "-- V")
        for s in [self.s_mode, self.s_temp, self.s_nvme, self.s_bat]:
            sc.addWidget(s)
        sc.addStretch(); tr.addLayout(sc)
        lay.addWidget(tele)

        # ── Fan Control ──
        fan_grp = QGroupBox("FAN CONTROL")
        fl = QVBoxLayout(fan_grp); fl.setSpacing(10)
        fans_row = QHBoxLayout(); fans_row.setSpacing(32)
        self.fan_cpu = FanControl("CPU FAN", C['green'])
        self.fan_gpu = FanControl("GPU FAN", C['cyan'])
        fans_row.addWidget(self.fan_cpu)
        fans_row.addWidget(self.fan_gpu)
        fans_row.addStretch()
        fl.addLayout(fans_row)
        fbr = QHBoxLayout(); fbr.setSpacing(8)
        self.btn_apply = mkbtn("APPLY", C['green'])
        self.btn_auto  = mkbtn("AUTO",  C['dim'])
        self.btn_max   = mkbtn("MAX",   C['red'])
        self.btn_apply.clicked.connect(self._apply_fan)
        self.btn_auto.clicked.connect(self._fan_auto)
        self.btn_max.clicked.connect(self._fan_max)
        fbr.addWidget(self.btn_apply); fbr.addWidget(self.btn_auto)
        fbr.addWidget(self.btn_max); fbr.addStretch()
        fl.addLayout(fbr)
        lay.addWidget(fan_grp)

        # ── Thermal Profiles ──
        mode_grp = QGroupBox("THERMAL PROFILES")
        ml = QHBoxLayout(mode_grp); ml.setSpacing(8)
        self.mode_btns = {}
        choices = (read(PROF_CHOI) or
                   "low-power quiet balanced balanced-performance performance").split()
        for m in choices:
            b = ModeBtn(m)
            b.clicked.connect(lambda _, mode=m: self._set_mode(mode))
            self.mode_btns[m] = b; ml.addWidget(b)
        ml.addStretch()
        lay.addWidget(mode_grp)

        # ── Boot Animation ──
        boot_grp = QGroupBox("BOOT ANIMATION")
        bl = QHBoxLayout(boot_grp); bl.setSpacing(12)
        self.tog_boot = GlowToggle("BOOT ANIMATION  &  SOUND")
        desc = QLabel("Predator logo animation and sound on startup")
        desc.setStyleSheet(f"color:{C['textdim']};font-size:10px;")
        bl.addWidget(self.tog_boot)
        bl.addWidget(desc)
        bl.addStretch()
        self.tog_boot.toggled.connect(self._set_boot)
        lay.addWidget(boot_grp)

        lay.addStretch()
        self.status_bar = StatusBar()
        root.addWidget(self.status_bar)

    def _stat(self, key, val):
        w = QLabel(f"{key}  {val}")
        w.setStyleSheet(f"""
            color:{C['textdim']};font-size:10px;
            background:{C['bg3']};border:1px solid {C['border']};
            border-radius:2px;padding:5px 10px;min-width:148px;
        """)
        return w

    def _upd(self, lbl, key, val, col=None):
        c = col or C['text']
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setText(f"{key}  <span style='color:{c};font-weight:bold'>{val}</span>")

    # ── Load initial state (delayed 100ms so sysfs is ready) ─────────────────
    def _load_initial_state(self):
        # Fan
        fan_val = read(f"{PREDATOR}/fan_speed")
        if fan_val:
            parts = fan_val.split(',')
            cpu_v = int(parts[0]) if parts[0].isdigit() else 0
            gpu_v = int(parts[1]) if len(parts)>1 and parts[1].isdigit() else 0
            self.fan_cpu.setValue(cpu_v)
            self.fan_gpu.setValue(gpu_v)

        # Boot animation toggle — read actual state from system
        boot = read(f"{PREDATOR}/boot_animation_sound")
        self.tog_boot.blockSignals(True)
        self.tog_boot.setChecked(boot == "1")
        self.tog_boot.blockSignals(False)

    # ── Timer refresh — only updates telemetry, never fan spinboxes ──────────
    def _refresh(self):
        f1, f2 = get_fan_rpms()
        self.g_cpu_fan.setValue(f1)
        self.g_gpu_fan.setValue(f2)

        temp = get_cpu_temp()
        self.g_cpu_temp.setValue(temp)
        col = C['green'] if temp < 70 else C['orange'] if temp < 85 else C['red']
        self._upd(self.s_temp, "PACKAGE", f"{temp} °C", col)

        nvme = read("/sys/class/nvme/nvme0/hwmon2/temp1_input")
        if nvme:
            nt = int(nvme) // 1000
            self._upd(self.s_nvme, "NVME", f"{nt} °C",
                      C['green'] if nt < 55 else C['orange'])

        bat_v = read("/sys/class/power_supply/BAT1/voltage_now")
        if bat_v:
            self._upd(self.s_bat, "BATTERY", f"{int(bat_v)/1_000_000:.1f} V", C['cyan'])

        profile = read(PROFILE) or "--"
        self._upd(self.s_mode, "MODE", profile.upper(), C['green'])
        for m, btn in self.mode_btns.items():
            btn.setActive(m == profile)

    # ── Actions ───────────────────────────────────────────────────────────────
    def _apply_fan(self):
        cpu, gpu = self.fan_cpu.value(), self.fan_gpu.value()
        if write(f"{PREDATOR}/fan_speed", f"{cpu},{gpu}"):
            self.status_bar.ok(f"Fan → CPU:{cpu}%  GPU:{gpu}%")
        else:
            self.status_bar.err("Write failed — run as root")

    def _fan_auto(self):
        self.fan_cpu.setValue(0); self.fan_gpu.setValue(0)
        if write(f"{PREDATOR}/fan_speed", "0,0"):
            self.status_bar.ok("Fans → AUTO")
        else:
            self.status_bar.err("Write failed — run as root")

    def _fan_max(self):
        self.fan_cpu.setValue(100); self.fan_gpu.setValue(100)
        if write(f"{PREDATOR}/fan_speed", "100,100"):
            self.status_bar.ok("Fans → MAX")
        else:
            self.status_bar.err("Write failed — run as root")

    def _set_mode(self, mode):
        if write(PROFILE, mode):
            self.status_bar.ok(f"Mode → {mode.upper()}")
            self._refresh()
        else:
            self.status_bar.err("Write failed — run as root")

    def _set_boot(self, val):
        if write(f"{PREDATOR}/boot_animation_sound", "1" if val else "0"):
            self.status_bar.ok(f"Boot animation → {'ON' if val else 'OFF'}")
        else:
            self.status_bar.err("Write failed — run as root")


# ── Entry ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("PREDATOR CONTROL")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,          QColor(C['bg']))
    pal.setColor(QPalette.ColorRole.WindowText,      QColor(C['text']))
    pal.setColor(QPalette.ColorRole.Base,            QColor(C['bg2']))
    pal.setColor(QPalette.ColorRole.Text,            QColor(C['text']))
    pal.setColor(QPalette.ColorRole.Button,          QColor(C['bg3']))
    pal.setColor(QPalette.ColorRole.ButtonText,      QColor(C['text']))
    pal.setColor(QPalette.ColorRole.Highlight,       QColor(C['green']))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(C['bg']))
    app.setPalette(pal)
    win = PredatorGUI()
    win.show()
    sys.exit(app.exec())
