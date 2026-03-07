#!/usr/bin/env python3
"""
PREDATOR CONTROL — Acer Predator PH16-72
Requires: PyQt6  →  pip install PyQt6 --break-system-packages
Run with: sudo -E python predator-gui.py
"""

import sys, os, subprocess, fcntl, ctypes, time
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QGroupBox, QSpinBox, QScrollArea,
    QSlider, QComboBox, QGridLayout, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QColor, QFont, QLinearGradient, QPalette

# ── Paths ─────────────────────────────────────────────────────────────────────
PROFILE    = "/sys/devices/platform/acer-wmi/platform-profile/platform-profile-0/profile"
PROF_CHOI  = "/sys/devices/platform/acer-wmi/platform-profile/platform-profile-0/choices"
CORETEMP   = "/sys/class/hwmon"

def _find_acer_hwmon():
    """Dynamically find the acer-wmi hwmon path (number can vary)."""
    base = "/sys/devices/platform/acer-wmi/hwmon"
    try:
        for entry in os.listdir(base):
            p = os.path.join(base, entry)
            if os.path.exists(os.path.join(p, "fan1_input")):
                return p
    except: pass
    return "/sys/devices/platform/acer-wmi/hwmon/hwmon4"  # fallback

HWMON_BASE      = _find_acer_hwmon()
FAN1_PWM        = f"{HWMON_BASE}/pwm1"
FAN2_PWM        = f"{HWMON_BASE}/pwm2"
FAN1_PWM_ENABLE = f"{HWMON_BASE}/pwm1_enable"
FAN2_PWM_ENABLE = f"{HWMON_BASE}/pwm2_enable"
FAN1_RPM        = f"{HWMON_BASE}/fan1_input"
FAN2_RPM        = f"{HWMON_BASE}/fan2_input"

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
    "purple":  "#aa44ff",
    "pink":    "#ff44aa",
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
QSlider::groove:horizontal {{
    background: {C['bg3']};
    border: 1px solid {C['border']};
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {C['green']};
    border: 1px solid {C['green']};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::sub-page:horizontal {{
    background: {C['green3']};
    border-radius: 2px;
}}
QComboBox {{
    background: {C['bg3']};
    border: 1px solid {C['border']};
    border-radius: 2px;
    color: {C['green']};
    font-family: 'Courier New';
    font-size: 10px;
    font-weight: bold;
    padding: 4px 8px;
    min-height: 28px;
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox::down-arrow {{
    width: 8px; height: 8px;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid {C['green']};
}}
QComboBox QAbstractItemView {{
    background: {C['bg3']};
    border: 1px solid {C['border']};
    color: {C['green']};
    selection-background-color: {C['green3']};
    font-family: 'Courier New';
    font-size: 10px;
}}
QScrollBar:vertical {{
    background: {C['bg2']};
    width: 4px;
    border-radius: 2px;
}}
QScrollBar::handle:vertical {{ background: {C['green3']}; border-radius: 2px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""

# ══════════════════════════════════════════════════════════════════════════════
# RGB PROTOCOL (from predator_rgb.py — fully integrated)
# ══════════════════════════════════════════════════════════════════════════════
USB_VID, USB_PID  = 0x05AF, 0x666A
IFACE_MAIN        = 3
IFACE_ZONES       = 0
USBDEVFS_CONTROL  = 0xc0185500
USBHID_IFACES     = ["1-7:1.0", "1-7:1.3"]

RGB_MODES = {
    "off":          (0x00, False, "All LEDs off"),
    "static":       (0x01, True,  "Solid colour"),
    "breathing":    (0x02, True,  "Fade in/out"),
    "wave":         (0x03, False, "Colour wave"),
    "neon":         (0x05, True,  "Neon snake"),
    "ripple":       (0x06, True,  "Ripple outward"),
    "twinkling":    (0x07, False, "Random twinkling"),
    "strobe":       (0x08, False, "Strobe flash"),
    "rain":         (0x0a, True,  "Rain drops"),
    "lightning":    (0x12, True,  "Lightning strike"),
    "fireball":     (0x27, True,  "Fireball sweep"),
    "snow":         (0x28, True,  "Snowfall"),
    "heartbeat":    (0x29, True,  "Heartbeat pulse"),
    "fireworks":    (0x2a, True,  "Fireworks burst"),
    "sparkle":      (0x2b, True,  "Sparkle/glitter"),
    "spot":         (0x25, True,  "Spotlight"),
    "stars":        (0x26, False, "Starfield"),
}

WAVE_DIRS = {
    "left":          0x01,
    "right":         0x02,
    "left2":         0x03,
    "up":            0x04,
    "circular_right":0x05,
    "circular_left": 0x06,
    "inout":         0x07,
}

class usbdevfs_ctrltransfer(ctypes.Structure):
    _fields_ = [
        ("bRequestType", ctypes.c_uint8),
        ("bRequest",     ctypes.c_uint8),
        ("wValue",       ctypes.c_uint16),
        ("wIndex",       ctypes.c_uint16),
        ("wLength",      ctypes.c_uint16),
        ("timeout",      ctypes.c_uint32),
        ("data",         ctypes.c_void_p),
    ]

def _csum(d): return (~sum(d[:7])) & 0xFF

def _cmd(*b):
    b = list(b); b.append(_csum(b))
    return (ctypes.c_uint8 * 8)(*b)

def _set_report(fd, iface, payload8):
    ctrl = usbdevfs_ctrltransfer()
    ctrl.bRequestType = 0x21
    ctrl.bRequest     = 0x09
    ctrl.wValue       = 0x0300
    ctrl.wIndex       = iface
    ctrl.wLength      = 8
    ctrl.timeout      = 2000
    ctrl.data         = ctypes.cast(payload8, ctypes.c_void_p)
    return fcntl.ioctl(fd, USBDEVFS_CONTROL, ctrl)

def find_usb_device():
    try:
        out = subprocess.check_output(["lsusb"], stderr=subprocess.DEVNULL).decode()
        for line in out.splitlines():
            if f"{USB_VID:04x}:{USB_PID:04x}".lower() in line.lower():
                parts = line.split()
                bus, dev = int(parts[1]), int(parts[3].rstrip(":"))
                path = f"/dev/bus/usb/{bus:03d}/{dev:03d}"
                if os.path.exists(path): return path
    except Exception: pass
    return None

def unbind_ifaces():
    for iface in USBHID_IFACES:
        try: open("/sys/bus/usb/drivers/usbhid/unbind","w").write(iface)
        except: pass

def rebind_ifaces():
    for iface in USBHID_IFACES:
        try: open("/sys/bus/usb/drivers/usbhid/bind","w").write(iface)
        except: pass

class PredatorRGB:
    def __init__(self, usb_path):
        self.fd = os.open(usb_path, os.O_RDWR)

    def close(self):
        try: os.close(self.fd)
        except: pass

    def _s(self, iface, *args):
        _set_report(self.fd, iface, _cmd(*args))
        time.sleep(0.05)

    def _std(self, mode_code, r, g, b, speed=5, brightness=50,
             direction=0, per_zone_flag=0x05, zone_mask=0x01):
        hint = 0x01 if zone_mask == 0x0f else zone_mask
        self._s(IFACE_MAIN,  0x88,0,0,0,0,0,0)
        self._s(IFACE_ZONES, 0x14,hint,0x00,r,g,b,0x00)
        self._s(IFACE_MAIN,  0xb1,0,0,0,0,0,0)
        self._s(IFACE_MAIN,  0x08,0x02,0x00,0x00,0x00,0x00,0x00)
        self._s(IFACE_MAIN,  0x08,0x02,mode_code,speed,brightness,direction,per_zone_flag)
        self._s(IFACE_ZONES, 0x08,0x00,zone_mask,speed,0x64,zone_mask,per_zone_flag)
        self._s(IFACE_MAIN,  0x14,0x00,0x00,r,g,b,0x00)

    def set_static(self, r, g, b, brightness=50, speed=10):
        self._s(IFACE_MAIN,  0x88,0,0,0,0,0,0)
        self._s(IFACE_ZONES, 0x14,0x01,0x00,r,g,b,0x00)
        self._s(IFACE_MAIN,  0xb1,0,0,0,0,0,0)
        self._s(IFACE_MAIN,  0x08,0x02,0x00,0x00,0x00,0x00,0x00)
        self._s(IFACE_MAIN,  0x08,0x02,0x01,speed,brightness,0x00,0x00)
        self._s(IFACE_ZONES, 0x08,0x00,0x01,speed,0x64,0x00,0x01)
        self._s(IFACE_MAIN,  0x14,0x00,0x00,r,g,b,0x00)

    def set_wave(self, speed=5, brightness=50, direction="left"):
        pz = WAVE_DIRS.get(direction, 0x01)
        self._s(IFACE_MAIN,  0x88,0,0,0,0,0,0)
        self._s(IFACE_ZONES, 0x14,0x08,0x00,0x00,0x00,0x00,0x00)
        self._s(IFACE_MAIN,  0xb1,0,0,0,0,0,0)
        self._s(IFACE_MAIN,  0x08,0x02,0x00,0x00,0x00,0x00,0x00)
        self._s(IFACE_MAIN,  0x08,0x02,0x03,speed,brightness,0x00,pz)
        self._s(IFACE_ZONES, 0x08,0x00,0x08,speed,0x64,0x08,pz)
        self._s(IFACE_MAIN,  0x14,0x00,0x00,0x00,0x00,0x00,0x00)

    def set_breathing(self, r, g, b, brightness=50, speed=5):
        self._std(0x02, r, g, b, speed, brightness, direction=0,
                  per_zone_flag=0x00, zone_mask=0x02)

    def turn_off(self):
        self._s(IFACE_MAIN,  0x88,0,0,0,0,0,0)
        self._s(IFACE_MAIN,  0xb1,0,0,0,0,0,0)
        self._s(IFACE_MAIN,  0x08,0x02,0x00,0x00,0x00,0x00,0x00)
        self._s(IFACE_ZONES, 0x08,0x00,0x0f,0x00,0x00,0x0f,0x01)
        self._s(IFACE_MAIN,  0x14,0x00,0x00,0x00,0x00,0x00,0x00)

    def set_mode(self, mode_code, r, g, b, brightness=50, speed=5):
        self._std(mode_code, r, g, b, speed, brightness)


# ── RGB worker thread (keeps UI responsive during USB transfers) ──────────────
class RGBWorker(QThread):
    done    = pyqtSignal(bool, str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn; self._a = args; self._k = kwargs

    def run(self):
        usb = find_usb_device()
        if not usb:
            self.done.emit(False, "keyboard not found — check USB"); return
        try:
            unbind_ifaces(); time.sleep(0.05)
            rgb = PredatorRGB(usb)
            self._fn(rgb, *self._a, **self._k)
            rgb.close()
            self.done.emit(True, "OK")
        except Exception as e:
            self.done.emit(False, str(e))
        finally:
            rebind_ifaces()


# ══════════════════════════════════════════════════════════════════════════════
# GUI HELPERS (unchanged from original)
# ══════════════════════════════════════════════════════════════════════════════
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
    f1 = read(FAN1_RPM)
    f2 = read(FAN2_RPM)
    return (int(f1) if f1 else 0), (int(f2) if f2 else 0)

def pct_to_pwm(pct): return int(pct * 255 / 100)
def pwm_to_pct(pwm): return int(int(pwm) * 100 / 255)

def get_fan_pcts():
    p1 = read(FAN1_PWM)
    p2 = read(FAN2_PWM)
    e1 = read(FAN1_PWM_ENABLE)
    e2 = read(FAN2_PWM_ENABLE)
    cpu = 0 if e1 == "2" else (pwm_to_pct(p1) if p1 else 0)
    gpu = 0 if e2 == "2" else (pwm_to_pct(p2) if p2 else 0)
    return cpu, gpu

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

    def setActive(self, v): self.setChecked(v); self._style(v)

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
    def info(self, msg):
        self.setStyleSheet(self._b+f"color:{C['cyan']};"); self.setText(f"◌  {msg}")
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


# ══════════════════════════════════════════════════════════════════════════════
# COLOR PICKER WIDGET
# ══════════════════════════════════════════════════════════════════════════════
class ColorSwatch(QWidget):
    """Clickable colour preset swatch."""
    clicked = pyqtSignal(str)  # emits hex colour

    PRESETS = [
        "#ff2244", "#ff7700", "#ffdd00", "#00ff88",
        "#00eeff", "#0088ff", "#aa44ff", "#ff44aa",
        "#ffffff", "#b0ffe0", "#003322", "#000000",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QGridLayout(self)
        lay.setContentsMargins(0,0,0,0); lay.setSpacing(4)
        for i, col in enumerate(self.PRESETS):
            btn = QPushButton()
            btn.setFixedSize(26, 26)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {col};
                    border: 1px solid {C['border']};
                    border-radius: 2px;
                }}
                QPushButton:hover {{
                    border: 2px solid {C['green']};
                }}
            """)
            btn.clicked.connect(lambda _, c=col: self.clicked.emit(c))
            lay.addWidget(btn, i // 6, i % 6)


class RGBSliders(QWidget):
    """R/G/B sliders with live hex preview."""
    colorChanged = pyqtSignal(int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0,0,0,0); lay.setSpacing(6)

        self._sliders = {}
        for ch, col in [("R", C['red']), ("G", C['green']), ("B", C['cyan'])]:
            row = QHBoxLayout(); row.setSpacing(8)
            lbl = QLabel(ch)
            lbl.setFixedWidth(12)
            lbl.setStyleSheet(f"color:{col};font-weight:bold;font-size:11px;")
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(0, 255); sl.setValue(0)
            sl.setStyleSheet(sl.styleSheet() + f"""
                QSlider::handle:horizontal {{ background: {col}; border-color: {col}; }}
                QSlider::sub-page:horizontal {{ background: {col}30; }}
            """)
            val = QLabel("000")
            val.setFixedWidth(32)
            val.setStyleSheet(f"color:{col};font-size:10px;font-family:'Courier New';")
            sl.valueChanged.connect(lambda v, l=val: l.setText(f"{v:03d}"))
            sl.valueChanged.connect(self._emit)
            row.addWidget(lbl); row.addWidget(sl, 1); row.addWidget(val)
            lay.addLayout(row)
            self._sliders[ch] = sl

        # hex preview box
        self.hex_box = QLabel("#000000")
        self.hex_box.setFixedHeight(32)
        self.hex_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hex_box.setStyleSheet(f"""
            background: #000000;
            border: 1px solid {C['border']};
            border-radius: 2px;
            color: {C['text']};
            font-family: 'Courier New';
            font-size: 12px;
            font-weight: bold;
        """)
        lay.addWidget(self.hex_box)

    def _emit(self, _=None):
        r = self._sliders["R"].value()
        g = self._sliders["G"].value()
        b = self._sliders["B"].value()
        hex_col = f"#{r:02x}{g:02x}{b:02x}"
        self.hex_box.setStyleSheet(self.hex_box.styleSheet().split("background:")[0] +
            f"background: {hex_col}; border: 1px solid {C['border']}; "
            f"border-radius: 2px; color: {'#000' if (r+g+b)>384 else C['text']}; "
            f"font-family: 'Courier New'; font-size: 12px; font-weight: bold;")
        self.hex_box.setText(hex_col.upper())
        self.colorChanged.emit(r, g, b)

    def set_color_hex(self, hex_col):
        hex_col = hex_col.lstrip("#")
        r = int(hex_col[0:2], 16)
        g = int(hex_col[2:4], 16)
        b = int(hex_col[4:6], 16)
        for ch, v in [("R",r),("G",g),("B",b)]:
            self._sliders[ch].blockSignals(True)
            self._sliders[ch].setValue(v)
            self._sliders[ch].blockSignals(False)
        self._emit()

    def rgb(self):
        return (self._sliders["R"].value(),
                self._sliders["G"].value(),
                self._sliders["B"].value())


# ══════════════════════════════════════════════════════════════════════════════
# RGB SECTION WIDGET
# ══════════════════════════════════════════════════════════════════════════════
class RGBSection(QGroupBox):
    status_msg = pyqtSignal(bool, str)   # success, message

    def __init__(self, parent=None):
        super().__init__("RGB KEYBOARD", parent)
        self._worker = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setSpacing(12)

        # ── Row 1: Mode selector + direction ──
        row1 = QHBoxLayout(); row1.setSpacing(12)

        mode_col = QVBoxLayout(); mode_col.setSpacing(4)
        mode_lbl = QLabel("MODE")
        mode_lbl.setStyleSheet(f"color:{C['textdim']};font-size:10px;letter-spacing:2px;")
        self.mode_combo = QComboBox()
        for name, (_, _, desc) in RGB_MODES.items():
            self.mode_combo.addItem(f"{name.upper():<14}  {desc}", name)
        self.mode_combo.setCurrentIndex(1)  # static
        self.mode_combo.currentIndexChanged.connect(self._on_mode_change)
        mode_col.addWidget(mode_lbl)
        mode_col.addWidget(self.mode_combo)
        row1.addLayout(mode_col, 2)

        dir_col = QVBoxLayout(); dir_col.setSpacing(4)
        dir_lbl = QLabel("WAVE DIRECTION")
        dir_lbl.setStyleSheet(f"color:{C['textdim']};font-size:10px;letter-spacing:2px;")
        self.dir_combo = QComboBox()
        for d in WAVE_DIRS:
            self.dir_combo.addItem(d.upper().replace("_", " "), d)
        dir_col.addWidget(dir_lbl)
        dir_col.addWidget(self.dir_combo)
        self.dir_widget = QWidget()
        self.dir_widget.setLayout(dir_col)
        self.dir_widget.setVisible(False)
        row1.addWidget(self.dir_widget, 1)

        root.addLayout(row1)

        # ── Row 2: Colour pickers ──
        row2 = QHBoxLayout(); row2.setSpacing(16)

        # sliders
        slider_col = QVBoxLayout(); slider_col.setSpacing(4)
        slider_lbl = QLabel("COLOUR")
        slider_lbl.setStyleSheet(f"color:{C['textdim']};font-size:10px;letter-spacing:2px;")
        self.sliders = RGBSliders()
        slider_col.addWidget(slider_lbl)
        slider_col.addWidget(self.sliders)
        self.color_widget = QWidget()
        self.color_widget.setLayout(slider_col)
        row2.addWidget(self.color_widget, 2)

        # presets
        preset_col = QVBoxLayout(); preset_col.setSpacing(4)
        preset_lbl = QLabel("PRESETS")
        preset_lbl.setStyleSheet(f"color:{C['textdim']};font-size:10px;letter-spacing:2px;")
        self.swatches = ColorSwatch()
        self.swatches.clicked.connect(self.sliders.set_color_hex)
        preset_col.addWidget(preset_lbl)
        preset_col.addWidget(self.swatches)
        preset_col.addStretch()
        self.preset_widget = QWidget()
        self.preset_widget.setLayout(preset_col)
        row2.addWidget(self.preset_widget, 1)

        root.addLayout(row2)

        # ── Row 3: Speed + Brightness sliders ──
        sb_row = QHBoxLayout(); sb_row.setSpacing(24)

        for attr, label, default in [("speed_sl","SPEED",5), ("bright_sl","BRIGHTNESS",50)]:
            col = QVBoxLayout(); col.setSpacing(4)
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color:{C['textdim']};font-size:10px;letter-spacing:2px;")
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(1 if attr=="speed_sl" else 0, 10 if attr=="speed_sl" else 100)
            sl.setValue(default)
            val_lbl = QLabel(str(default))
            val_lbl.setFixedWidth(36)
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            val_lbl.setStyleSheet(f"color:{C['green']};font-size:11px;font-weight:bold;font-family:'Courier New';")
            sl.valueChanged.connect(lambda v, l=val_lbl: l.setText(str(v)))
            row = QHBoxLayout(); row.setSpacing(8)
            row.addWidget(sl, 1); row.addWidget(val_lbl)
            col.addWidget(lbl); col.addLayout(row)
            sb_row.addLayout(col, 1)
            setattr(self, attr, sl)

        root.addLayout(sb_row)

        # ── Row 4: Apply buttons ──
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        self.btn_apply = mkbtn("APPLY", C['green'])
        self.btn_off   = mkbtn("OFF",   C['red'])
        self.btn_apply.clicked.connect(self._apply)
        self.btn_off.clicked.connect(self._turn_off)
        btn_row.addWidget(self.btn_apply)
        btn_row.addWidget(self.btn_off)
        btn_row.addStretch()

        # USB status indicator
        self.usb_lbl = QLabel("USB: SCANNING...")
        self.usb_lbl.setStyleSheet(f"color:{C['textdim']};font-size:10px;")
        btn_row.addWidget(self.usb_lbl)
        root.addLayout(btn_row)

        # check USB on startup
        QTimer.singleShot(500, self._check_usb)
        self._on_mode_change()

    def _check_usb(self):
        usb = find_usb_device()
        if usb:
            self.usb_lbl.setText(f"USB: {usb}")
            self.usb_lbl.setStyleSheet(f"color:{C['dim']};font-size:10px;")
        else:
            self.usb_lbl.setText("USB: NOT FOUND")
            self.usb_lbl.setStyleSheet(f"color:{C['red']};font-size:10px;")

    def _on_mode_change(self):
        mode_name = self.mode_combo.currentData() or "static"
        needs_color = RGB_MODES.get(mode_name, (0, True, ""))[1]
        is_wave = (mode_name == "wave")
        self.color_widget.setVisible(needs_color)
        self.preset_widget.setVisible(needs_color)
        self.dir_widget.setVisible(is_wave)

    def _busy(self, busy):
        self.btn_apply.setEnabled(not busy)
        self.btn_off.setEnabled(not busy)
        self.btn_apply.setText("APPLYING..." if busy else "APPLY")

    def _apply(self):
        mode_name = self.mode_combo.currentData()
        r, g, b   = self.sliders.rgb()
        speed     = self.speed_sl.value()
        bright    = self.bright_sl.value()
        direction = self.dir_combo.currentData()

        def do(rgb_dev):
            if mode_name == "off":
                rgb_dev.turn_off()
            elif mode_name == "static":
                rgb_dev.set_static(r, g, b, bright, speed)
            elif mode_name == "wave":
                rgb_dev.set_wave(speed, bright, direction)
            elif mode_name == "breathing":
                rgb_dev.set_breathing(r, g, b, bright, speed)
            else:
                code = RGB_MODES[mode_name][0]
                rgb_dev.set_mode(code, r, g, b, bright, speed)

        self._busy(True)
        self._worker = RGBWorker(do)
        self._worker.done.connect(self._on_done)
        self._worker.start()
        self.status_msg.emit(True, f"RGB → {mode_name.upper()} applying...")

    def _turn_off(self):
        def do(rgb_dev): rgb_dev.turn_off()
        self._busy(True)
        self._worker = RGBWorker(do)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_done(self, ok, msg):
        self._busy(False)
        self._check_usb()
        if ok:
            mode_name = self.mode_combo.currentData()
            self.status_msg.emit(True, f"RGB → {mode_name.upper()}")
        else:
            self.status_msg.emit(False, f"RGB error: {msg}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN WINDOW
# ══════════════════════════════════════════════════════════════════════════════
class PredatorGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PREDATOR CONTROL")
        self.setMinimumSize(720, 680)
        self.resize(820, 780)
        self.setStyleSheet(SS)
        self._build_ui()
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

        # ── RGB Keyboard ── (NEW)
        self.rgb_section = RGBSection()
        self.rgb_section.status_msg.connect(
            lambda ok, msg: self.status_bar.ok(msg) if ok else self.status_bar.err(msg)
        )
        lay.addWidget(self.rgb_section)

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

    def _load_initial_state(self):
        cpu_v, gpu_v = get_fan_pcts()
        self.fan_cpu.setValue(cpu_v)
        self.fan_gpu.setValue(gpu_v)
        self.tog_boot.blockSignals(True)
        self.tog_boot.setChecked(False)
        self.tog_boot.blockSignals(False)

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

    def _apply_fan(self):
        cpu, gpu = self.fan_cpu.value(), self.fan_gpu.value()
        ok1 = write(FAN1_PWM_ENABLE, "1") and write(FAN1_PWM, str(pct_to_pwm(cpu)))
        ok2 = write(FAN2_PWM_ENABLE, "1") and write(FAN2_PWM, str(pct_to_pwm(gpu)))
        if ok1 and ok2:
            self.status_bar.ok(f"Fan → CPU:{cpu}%  GPU:{gpu}%")
        else:
            self.status_bar.err("Write failed — run as root")

    def _fan_auto(self):
        self.fan_cpu.setValue(0); self.fan_gpu.setValue(0)
        ok1 = write(FAN1_PWM_ENABLE, "2")
        ok2 = write(FAN2_PWM_ENABLE, "2")
        if ok1 and ok2:
            self.status_bar.ok("Fans → AUTO")
        else:
            self.status_bar.err("Write failed — run as root")

    def _fan_max(self):
        self.fan_cpu.setValue(100); self.fan_gpu.setValue(100)
        ok1 = write(FAN1_PWM_ENABLE, "1") and write(FAN1_PWM, "255")
        ok2 = write(FAN2_PWM_ENABLE, "1") and write(FAN2_PWM, "255")
        if ok1 and ok2:
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
        self.status_bar.err("Boot animation not supported in this linuwu-sense version")


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
