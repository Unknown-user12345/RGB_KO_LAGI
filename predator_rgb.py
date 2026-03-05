#!/usr/bin/env python3
"""
Acer Predator PH16-72 4-Zone Keyboard RGB Controller
=====================================================
Reverse-engineered from USB pcap of Windows Predator Sense app.

Protocol: USB HID SET_REPORT control transfers to VID=05AF PID=666A
  Interface 3 (iface=3): init, setup, mode, all-zone colour (zone=0x00)
  Interface 0 (iface=0): per-zone colour + zone config

Usage:
  sudo python3 predator_rgb.py static ff2828
  sudo python3 predator_rgb.py static ff0000 00ff00 0000ff ffff00
  sudo python3 predator_rgb.py breathing ff8800 --speed 3
  sudo python3 predator_rgb.py wave --speed 5
  sudo python3 predator_rgb.py off
"""

import sys, os, fcntl, ctypes, struct, time, argparse, subprocess

USB_VID, USB_PID = 0x05AF, 0x666A
USB_IFACE_MAIN  = 3
USB_IFACE_ZONES = 0
USBDEVFS_CONTROL = 0xc0185500
USBHID_IFACES = ["1-7:1.0", "1-7:1.3"]

MODES = {"off":0x00,"static":0x01,"breathing":0x02,"wave":0x03,"neon":0x05,"meteor":0x06,"twinkling":0x07}
NO_COLOR_MODES = {"wave","neon","meteor","twinkling"}

class usbdevfs_ctrltransfer(ctypes.Structure):
    _fields_ = [
        ("bRequestType", ctypes.c_uint8), ("bRequest", ctypes.c_uint8),
        ("wValue", ctypes.c_uint16), ("wIndex", ctypes.c_uint16),
        ("wLength", ctypes.c_uint16), ("timeout", ctypes.c_uint32),
        ("data", ctypes.c_void_p),
    ]

def csum(d): return (~sum(d[:7])) & 0xFF
def cmd(*b):
    b = list(b); b.append(csum(b))
    return (ctypes.c_uint8 * 8)(*b)

def set_report(fd, iface, payload8):
    ctrl = usbdevfs_ctrltransfer()
    ctrl.bRequestType = 0x21; ctrl.bRequest = 0x09
    ctrl.wValue = 0x0300; ctrl.wIndex = iface
    ctrl.wLength = 8; ctrl.timeout = 2000
    ctrl.data = ctypes.cast(payload8, ctypes.c_void_p)
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

def unbind_ifaces(verbose=True):
    for iface in USBHID_IFACES:
        try:
            open("/sys/bus/usb/drivers/usbhid/unbind","w").write(iface)
            if verbose: print(f"  Unbound {iface}")
        except Exception as e:
            if verbose: print(f"  Unbind {iface}: already unbound or {e}")

def rebind_ifaces(verbose=True):
    for iface in USBHID_IFACES:
        try:
            open("/sys/bus/usb/drivers/usbhid/bind","w").write(iface)
            if verbose: print(f"  Rebound {iface}")
        except Exception as e:
            if verbose: print(f"  Rebind {iface}: {e}")


class PredatorRGB:
    def __init__(self, usb_path):
        self.fd = os.open(usb_path, os.O_RDWR)

    def close(self): os.close(self.fd)

    def _s(self, iface, *args):
        set_report(self.fd, iface, cmd(*args)); time.sleep(0.05)

    def set_static_all(self, r, g, b, brightness=50, speed=10):
        """All zones same colour - exact pcap sequence."""
        self._s(USB_IFACE_MAIN,  0x88,0,0,0,0,0,0)
        self._s(USB_IFACE_ZONES, 0x14,0x01,0x00,r,g,b,0x00)  # early color hint
        self._s(USB_IFACE_MAIN,  0xb1,0,0,0,0,0,0)
        self._s(USB_IFACE_MAIN,  0x08,0x02,0x00,0x00,0x00,0x00,0x00)  # mode off
        self._s(USB_IFACE_MAIN,  0x08,0x02,0x01,speed,brightness,0x00,0x00)  # static
        self._s(USB_IFACE_ZONES, 0x08,0x00,0x01,speed,0x64,0x00,0x01)  # zone cfg
        self._s(USB_IFACE_MAIN,  0x14,0x00,0x00,r,g,b,0x00)  # final color

    def set_animation(self, mode_code, speed=10, brightness=50, direction=0, r=0xff, g=0x28, b=0x28):
        self._s(USB_IFACE_MAIN,  0x88,0,0,0,0,0,0)
        self._s(USB_IFACE_ZONES, 0x14,0x01,0x00,r,g,b,0x00)
        self._s(USB_IFACE_MAIN,  0xb1,0,0,0,0,0,0)
        self._s(USB_IFACE_MAIN,  0x08,0x02,0x00,0x00,0x00,0x00,0x00)
        self._s(USB_IFACE_MAIN,  0x08,0x02,mode_code,speed,brightness,direction,0x00)
        self._s(USB_IFACE_ZONES, 0x08,0x00,0x0f,speed,0x64,0x0f,0x01)
        self._s(USB_IFACE_MAIN,  0x14,0x00,0x00,r,g,b,0x00)

    def turn_off(self):
        self._s(USB_IFACE_MAIN,  0x88,0,0,0,0,0,0)
        self._s(USB_IFACE_MAIN,  0xb1,0,0,0,0,0,0)
        self._s(USB_IFACE_MAIN,  0x08,0x02,0x00,0x00,0x00,0x00,0x00)
        self._s(USB_IFACE_ZONES, 0x08,0x00,0x0f,0x00,0x00,0x0f,0x01)
        self._s(USB_IFACE_MAIN,  0x14,0x00,0x00,0x00,0x00,0x00,0x00)


def parse_color(s):
    s = s.lstrip("#")
    if len(s) != 6: raise argparse.ArgumentTypeError(f"Need 6 hex digits, got: {s}")
    return int(s[0:2],16), int(s[2:4],16), int(s[4:6],16)


def main():
    parser = argparse.ArgumentParser(description="Acer Predator PH16-72 RGB keyboard controller",
        epilog="Examples:\n  sudo %(prog)s static 3cf03c\n  sudo %(prog)s breathing ff8800\n  sudo %(prog)s wave\n  sudo %(prog)s off")
    parser.add_argument("command", choices=list(MODES.keys()))
    parser.add_argument("colors", nargs="*", metavar="RRGGBB")
    parser.add_argument("--speed",  type=int, default=10)
    parser.add_argument("--bright", type=int, default=50)
    parser.add_argument("--dir", choices=["left","right"], default="left")
    parser.add_argument("--usb", metavar="PATH", help="e.g. /dev/bus/usb/001/004")
    parser.add_argument("--no-rebind", action="store_true")
    args = parser.parse_args()

    colors = [parse_color(c) for c in args.colors]
    direction = 1 if args.dir == "right" else 0

    usb_path = args.usb or find_usb_device()
    if not usb_path:
        print("Error: keyboard not found. Try --usb /dev/bus/usb/001/XXX", file=sys.stderr)
        sys.exit(1)
    print(f"USB: {usb_path}")

    print("Unbinding usbhid...")
    unbind_ifaces()
    time.sleep(0.05)

    try:
        rgb = PredatorRGB(usb_path)

        if args.command == "off":
            print("Off..."); rgb.turn_off()

        elif args.command == "static":
            if not colors: colors = [(0x3c,0xf0,0x3c)]
            if len(colors) == 1:
                r,g,b = colors[0]
                print(f"Static: #{r:02x}{g:02x}{b:02x}")
                rgb.set_static_all(r, g, b, args.bright, args.speed)
            else:
                parser.error("static: provide 1 colour (all zones). Per-zone coming soon.")

        elif args.command == "breathing":
            if not colors: colors = [(0xff,0x28,0x28)]
            r,g,b = colors[0]
            print(f"Breathing: #{r:02x}{g:02x}{b:02x}")
            rgb.set_animation(MODES["breathing"], args.speed, args.bright, direction, r, g, b)

        elif args.command in NO_COLOR_MODES:
            r,g,b = colors[0] if colors else (0xff,0x28,0x28)
            print(f"{args.command}: speed={args.speed}")
            rgb.set_animation(MODES[args.command], args.speed, args.bright, direction, r, g, b)

        print("Done.")
        rgb.close()

    finally:
        if not args.no_rebind:
            print("Rebinding usbhid...")
            rebind_ifaces()


if __name__ == "__main__":
    main()
