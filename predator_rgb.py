#!/usr/bin/env python3
"""
Acer Predator PH16-72 RGB Keyboard Controller
==============================================
Fully reverse-engineered from USB pcap of Windows Predator Sense.

Usage:
  sudo python3 predator_rgb.py static ff2828
  sudo python3 predator_rgb.py static ff0000 00ff00 0000ff ffff00   # 4 zones
  sudo python3 predator_rgb.py breathing ff8800 --speed 3 --bright 80
  sudo python3 predator_rgb.py wave --speed 5 --dir right
  sudo python3 predator_rgb.py neon ff2828 --speed 3
  sudo python3 predator_rgb.py meteor ffa000 --speed 7
  sudo python3 predator_rgb.py ripple 00aec7 --speed 5
  sudo python3 predator_rgb.py off
  sudo python3 predator_rgb.py modes          # list all modes
"""

import sys, os, fcntl, ctypes, struct, time, argparse, subprocess

# ── USB constants ─────────────────────────────────────────────────────────────
USB_VID, USB_PID     = 0x05AF, 0x666A
IFACE_MAIN           = 3    # init / setup / mode / all-zone colour
IFACE_ZONES          = 0    # per-zone colour + zone config
USBDEVFS_CONTROL     = 0xc0185500
USBHID_IFACES        = ["1-7:1.0", "1-7:1.3"]

# ── Mode table ────────────────────────────────────────────────────────────────
# (mode_code, needs_color, has_direction, description)
MODES = {
    "off":          (0x00, False, False, "All LEDs off"),
    "static":       (0x01, True,  False, "Solid colour"),
    "breathing":    (0x02, True,  False, "Fade in/out"),
    "wave":         (0x03, False, True,  "Rainbow wave across keyboard"),
    "snake_neon":    (0x05, True,  False, "Neon colour cycle"),
    "meteor":       (0x06, True,  True,  "Meteor shower effect"),
    "twinkling":    (0x07, False, False, "Random twinkling"),
    "ripple":       (0x0a, True,  False, "Ripple effect"),
    "marquee":      (0x12, True,  False, "Marquee/running lights"),
    "rainbow":      (0x27, True,  False, "Rainbow static"),
    "raindrop":     (0x28, True,  False, "Raindrop effect"),
    "aurora":       (0x29, True,  False, "Aurora/northern lights"),
    "fireworks":    (0x2a, True,  False, "Fireworks burst"),
    "sparkle":      (0x2b, True,  False, "Sparkle/glitter"),
}

# ── USB control transfer ──────────────────────────────────────────────────────
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

def csum(d): return (~sum(d[:7])) & 0xFF

def cmd(*b):
    b = list(b); b.append(csum(b))
    return (ctypes.c_uint8 * 8)(*b)

def set_report(fd, iface, payload8):
    ctrl = usbdevfs_ctrltransfer()
    ctrl.bRequestType = 0x21
    ctrl.bRequest     = 0x09
    ctrl.wValue       = 0x0300
    ctrl.wIndex       = iface
    ctrl.wLength      = 8
    ctrl.timeout      = 2000
    ctrl.data         = ctypes.cast(payload8, ctypes.c_void_p)
    return fcntl.ioctl(fd, USBDEVFS_CONTROL, ctrl)

# ── Device helpers ────────────────────────────────────────────────────────────
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
            open("/sys/bus/usb/drivers/usbhid/unbind", "w").write(iface)
            if verbose: print(f"  Unbound {iface}")
        except Exception:
            if verbose: print(f"  {iface} already unbound")

def rebind_ifaces(verbose=True):
    for iface in USBHID_IFACES:
        try:
            open("/sys/bus/usb/drivers/usbhid/bind", "w").write(iface)
            if verbose: print(f"  Rebound {iface}")
        except Exception as e:
            if verbose: print(f"  Rebind {iface}: {e}")

# ── RGB controller ────────────────────────────────────────────────────────────
class PredatorRGB:
    def __init__(self, usb_path):
        self.fd = os.open(usb_path, os.O_RDWR)

    def close(self):
        os.close(self.fd)

    def _s(self, iface, *args):
        set_report(self.fd, iface, cmd(*args))
        time.sleep(0.05)

    def _standard_sequence(self, mode_code, r, g, b,
                            speed=10, brightness=50,
                            direction=0, per_zone_flag=None,
                            zone_mask=0x01):
        """
        Standard 7-step sequence used by all non-per-key modes.
        direction: 0=forward, 0xe0=reverse
        per_zone_flag: None=auto (use same as direction indicator)
        """
        if per_zone_flag is None:
            per_zone_flag = 0x05  # default seen in most sequences

        hint_zone = 0x01 if zone_mask == 0x0f else zone_mask

        self._s(IFACE_MAIN,  0x88,0,0,0,0,0,0)                               # INIT
        self._s(IFACE_ZONES, 0x14,hint_zone,0x00,r,g,b,0x00)                 # early color hint
        self._s(IFACE_MAIN,  0xb1,0,0,0,0,0,0)                               # SETUP
        self._s(IFACE_MAIN,  0x08,0x02,0x00,0x00,0x00,0x00,0x00)             # MODE OFF
        self._s(IFACE_MAIN,  0x08,0x02,mode_code,speed,brightness,
                direction,per_zone_flag)                                        # MODE target
        self._s(IFACE_ZONES, 0x08,0x00,zone_mask,speed,0x64,zone_mask,
                per_zone_flag)                                                  # ZONE CFG
        self._s(IFACE_MAIN,  0x14,0x00,0x00,r,g,b,0x00)                      # final COLOR

    def set_static_all(self, r, g, b, brightness=50, speed=10):
        """All 4 zones same colour."""
        self._s(IFACE_MAIN,  0x88,0,0,0,0,0,0)
        self._s(IFACE_ZONES, 0x14,0x01,0x00,r,g,b,0x00)
        self._s(IFACE_MAIN,  0xb1,0,0,0,0,0,0)
        self._s(IFACE_MAIN,  0x08,0x02,0x00,0x00,0x00,0x00,0x00)
        self._s(IFACE_MAIN,  0x08,0x02,0x01,speed,brightness,0x00,0x00)
        self._s(IFACE_ZONES, 0x08,0x00,0x01,speed,0x64,0x00,0x01)
        self._s(IFACE_MAIN,  0x14,0x00,0x00,r,g,b,0x00)

    def set_static_per_zone(self, colors, brightness=50, speed=10):
        """4 zones with independent colours. colors=[(r,g,b)*4]"""
        assert len(colors) == 4
        zone_ids = [0x01, 0x02, 0x04, 0x08]
        r0, g0, b0 = colors[0]

        self._s(IFACE_MAIN,  0x88,0,0,0,0,0,0)
        self._s(IFACE_ZONES, 0x14,0x01,0x00,r0,g0,b0,0x00)
        self._s(IFACE_MAIN,  0xb1,0,0,0,0,0,0)
        self._s(IFACE_MAIN,  0x08,0x02,0x00,0x00,0x00,0x00,0x00)
        self._s(IFACE_MAIN,  0x08,0x02,0x01,speed,brightness,0x00,0x01)

        for zid, (r, g, b) in zip(zone_ids, colors):
            self._s(IFACE_ZONES, 0x08,0x00,zid,speed,0x64,zid,0x02)
            self._s(IFACE_MAIN,  0x08,0x02,0x01,speed,brightness,0x00,0x01)

        rl, gl, bl = colors[-1]
        self._s(IFACE_MAIN,  0x14,0x00,0x00,rl,gl,bl,0x00)

    def set_breathing(self, r, g, b, brightness=50, speed=5):
        self._standard_sequence(0x02, r, g, b, speed, brightness,
                                 direction=0, per_zone_flag=0x00,
                                 zone_mask=0x02)

    # Wave direction codes (encoded in per_zone byte, dir byte is always 0x00)
    # Confirmed by hardware testing:
    WAVE_DIRS = {
        "left":           0x01,  # confirmed
        "right":          0x02,  # confirmed
        "left2":          0x03,  # confirmed (variant of left)
        "up":             0x04,  # confirmed
        "circular_right": 0x05,  # confirmed
        "circular_left":  0x06,  # confirmed
        "inout":          0x07,  # confirmed (both directions simultaneously)
    }

    def set_wave(self, speed=5, brightness=50, direction="left"):
        per_zone = self.WAVE_DIRS.get(direction, 0x01)
        self._s(IFACE_MAIN,  0x88,0,0,0,0,0,0)
        self._s(IFACE_ZONES, 0x14,0x08,0x00,0x00,0x00,0x00,0x00)
        self._s(IFACE_MAIN,  0xb1,0,0,0,0,0,0)
        self._s(IFACE_MAIN,  0x08,0x02,0x00,0x00,0x00,0x00,0x00)
        self._s(IFACE_MAIN,  0x08,0x02,0x03,speed,brightness,0x00,per_zone)
        self._s(IFACE_ZONES, 0x08,0x00,0x08,speed,0x64,0x08,per_zone)
        self._s(IFACE_MAIN,  0x14,0x00,0x00,0x00,0x00,0x00,0x00)

    def set_neon(self, r, g, b, brightness=50, speed=5):
        self._standard_sequence(0x05, r, g, b, speed, brightness,
                                 per_zone_flag=0x05, zone_mask=0x01)

    def set_meteor(self, r, g, b, brightness=50, speed=5, reverse=False):
        direction = 0xe0 if reverse else 0x00
        self._standard_sequence(0x06, r, g, b, speed, brightness,
                                 direction=direction, per_zone_flag=0x05,
                                 zone_mask=0x01)

    def set_twinkling(self, brightness=50, speed=5):
        self._standard_sequence(0x07, 0x00, 0x00, 0x00, speed, brightness,
                                 per_zone_flag=0x05, zone_mask=0x08)

    def set_mode(self, mode_code, r, g, b, brightness=50, speed=5,
                 reverse=False):
        """Generic setter for any mode by code."""
        direction = 0xe0 if reverse else 0x00
        self._standard_sequence(mode_code, r, g, b, speed, brightness,
                                 direction=direction)

    def turn_off(self):
        self._s(IFACE_MAIN,  0x88,0,0,0,0,0,0)
        self._s(IFACE_MAIN,  0xb1,0,0,0,0,0,0)
        self._s(IFACE_MAIN,  0x08,0x02,0x00,0x00,0x00,0x00,0x00)
        self._s(IFACE_ZONES, 0x08,0x00,0x0f,0x00,0x00,0x0f,0x01)
        self._s(IFACE_MAIN,  0x14,0x00,0x00,0x00,0x00,0x00,0x00)

# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_color(s):
    s = s.lstrip("#")
    if len(s) != 6:
        raise argparse.ArgumentTypeError(f"Need 6 hex digits, got: {s!r}")
    return int(s[0:2],16), int(s[2:4],16), int(s[4:6],16)

def main():
    parser = argparse.ArgumentParser(
        description="Acer Predator PH16-72 RGB keyboard controller",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  static     Solid colour (1 colour=all zones, 4 colours=per-zone)
  breathing  Fade in/out
  wave       Rainbow wave (use --dir right to reverse)
  neon       Neon colour cycle
  meteor     Meteor shower (use --dir right to reverse)
  twinkling  Random twinkling stars
  ripple     Ripple effect
  marquee    Running lights
  rainbow    Rainbow static
  raindrop   Raindrop effect
  aurora     Aurora borealis
  fireworks  Fireworks burst
  sparkle    Glitter/sparkle
  off        Turn off

Examples:
  sudo %(prog)s static 3cf03c
  sudo %(prog)s static ff0000 00ff00 0000ff ffff00
  sudo %(prog)s breathing ff8800 --speed 3 --bright 70
  sudo %(prog)s wave --speed 7 --dir right
  sudo %(prog)s neon ff2828 --speed 5
  sudo %(prog)s meteor ffa000 --speed 6 --dir right
  sudo %(prog)s aurora 00aec7
  sudo %(prog)s off
        """)
    parser.add_argument("command", choices=list(MODES.keys()) + ["off","modes"])
    parser.add_argument("colors", nargs="*", metavar="RRGGBB",
                        help="Hex colour(s): 1=all zones, 4=per-zone (static only)")
    parser.add_argument("--speed",  type=int, default=5,  metavar="1-10",
                        help="Speed 1-10 (default: 5)")
    parser.add_argument("--bright", type=int, default=50, metavar="0-100",
                        help="Brightness 0-100 (default: 50)")
    parser.add_argument("--dir", choices=["left","right","left2","up","circular_right","circular_left","inout"], default="left",
                        help="Wave direction: left, right, left2, up, circular_right, circular_left, inout (default: left)")
    parser.add_argument("--usb", metavar="PATH",
                        help="Override USB device (e.g. /dev/bus/usb/001/004)")
    parser.add_argument("--no-rebind", action="store_true",
                        help="Don't rebind usbhid after (for scripting)")
    args = parser.parse_args()

    if args.command == "modes":
        print("Available modes:")
        for name, (code, needs_color, has_dir, desc) in MODES.items():
            color_hint = " <RRGGBB>" if needs_color else ""
            dir_hint   = " [--dir left|right]" if has_dir else ""
            print(f"  {name:<12}{color_hint:<10}{dir_hint:<22}  {desc}")
        return

    if not 1 <= args.speed  <= 10:  parser.error("--speed must be 1-10")
    if not 0 <= args.bright <= 100: parser.error("--bright must be 0-100")

    reverse = (args.dir == "right")
    colors  = []
    for c in args.colors:
        try:    colors.append(parse_color(c))
        except  argparse.ArgumentTypeError as e: parser.error(str(e))

    usb_path = args.usb or find_usb_device()
    if not usb_path:
        print("Error: keyboard (05AF:666A) not found.", file=sys.stderr)
        print("Try: lsusb | grep 05af  then pass --usb /dev/bus/usb/BBB/DDD",
              file=sys.stderr)
        sys.exit(1)
    print(f"USB: {usb_path}")

    print("Unbinding usbhid from RGB interfaces...")
    unbind_ifaces()
    time.sleep(0.05)

    try:
        rgb = PredatorRGB(usb_path)

        cmd_name = args.command
        r, g, b  = colors[0] if colors else (0x00, 0xae, 0xc7)  # default cyan

        if cmd_name == "off":
            print("Off...")
            rgb.turn_off()

        elif cmd_name == "static":
            if not colors: colors = [(0x3c, 0xf0, 0x3c)]
            if len(colors) == 1:
                r, g, b = colors[0]
                print(f"Static all zones: #{r:02x}{g:02x}{b:02x}  "
                      f"bright={args.bright}%")
                rgb.set_static_all(r, g, b, args.bright, args.speed)
            elif len(colors) == 4:
                labels = " | ".join(f"Z{i+1}=#{r:02x}{g:02x}{b:02x}"
                                    for i,(r,g,b) in enumerate(colors))
                print(f"Static per-zone: {labels}")
                rgb.set_static_per_zone(colors, args.bright, args.speed)
            else:
                parser.error("static needs 1 colour (all zones) or 4 colours (per-zone)")

        elif cmd_name == "breathing":
            print(f"Breathing: #{r:02x}{g:02x}{b:02x}  speed={args.speed}  "
                  f"bright={args.bright}%")
            rgb.set_breathing(r, g, b, args.bright, args.speed)

        elif cmd_name == "wave":
            print(f"Wave: speed={args.speed}  bright={args.bright}%  dir={args.dir}")
            rgb.set_wave(args.speed, args.bright, args.dir)

        elif cmd_name == "neon":
            print(f"Neon: #{r:02x}{g:02x}{b:02x}  speed={args.speed}")
            rgb.set_neon(r, g, b, args.bright, args.speed)

        elif cmd_name == "meteor":
            print(f"Meteor: #{r:02x}{g:02x}{b:02x}  speed={args.speed}  "
                  f"dir={args.dir}")
            rgb.set_meteor(r, g, b, args.bright, args.speed, reverse)

        elif cmd_name == "twinkling":
            print(f"Twinkling: speed={args.speed}  bright={args.bright}%")
            rgb.set_twinkling(args.bright, args.speed)

        else:
            # All other modes via generic setter
            mode_code = MODES[cmd_name][0]
            print(f"{cmd_name} (0x{mode_code:02x}): #{r:02x}{g:02x}{b:02x}  "
                  f"speed={args.speed}  bright={args.bright}%  dir={args.dir}")
            rgb.set_mode(mode_code, r, g, b, args.bright, args.speed, reverse)

        print("Done.")
        rgb.close()

    finally:
        if not args.no_rebind:
            print("Rebinding usbhid...")
            rebind_ifaces()

if __name__ == "__main__":
    main()
