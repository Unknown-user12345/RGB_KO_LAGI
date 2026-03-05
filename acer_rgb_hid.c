/*
 * Acer Predator PH16-72 USB HID RGB keyboard driver
 * Add this as a new file: src/acer_rgb_hid.c
 * and add `obj-m += acer_rgb_hid.o` to your Makefile
 *
 * Protocol reverse-engineered from pcap of Windows Predator Sense app.
 *
 * Architecture:
 *   The PH16-72 keyboard has two USB HID interfaces:
 *     "dev_a" (bInterfaceNumber=0, report 0x0303) — main/left half
 *     "dev_b" (bInterfaceNumber=1, report 0x0000) — secondary/right half (per-zone colours)
 *
 *   Both bind to the same VID:PID 05AF:666A.
 *   We use hid_hw_output_report() to send HID Output reports directly.
 *
 * Sysfs interface exposed under /sys/bus/hid/devices/<dev>/rgb/ :
 *   four_zone_rgb   RW  "mode,speed,brightness,direction,RRGGBB"  (whole-keyboard)
 *   per_zone_rgb    RW  "RRGGBB,RRGGBB,RRGGBB,RRGGBB,brightness"
 *
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include <linux/hid.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/mutex.h>

#define ACER_KBD_VID  0x05AF
#define ACER_KBD_PID  0x666A

/* HID report ID for all RGB commands */
#define ACER_RGB_REPORT_ID   0x03
#define ACER_RGB_REPORT_LEN  8      /* 8 data bytes (not counting report-id byte) */

/* bInterfaceNumber that each hid_device corresponds to */
#define ACER_RGB_IFACE_MAIN  0   /* "dev_a": init, mode, all-zone colour  */
#define ACER_RGB_IFACE_ZONE  1   /* "dev_b": per-zone colour + zone config */

/* Command opcodes */
#define ACER_RGB_CMD_INIT    0x88
#define ACER_RGB_CMD_SETUP   0xb1
#define ACER_RGB_CMD_MODE    0x08
#define ACER_RGB_CMD_COLOR   0x14

/* Mode sub-commands (byte[1] of CMD_MODE) */
#define ACER_RGB_SUB_ANIM    0x02
#define ACER_RGB_SUB_ZONE    0x00

/* Animation mode codes */
enum acer_rgb_mode {
    ACER_RGB_MODE_OFF       = 0x00,
    ACER_RGB_MODE_STATIC    = 0x01,
    ACER_RGB_MODE_BREATHING = 0x02,
    ACER_RGB_MODE_WAVE      = 0x03,
    ACER_RGB_MODE_NEON      = 0x05,
    ACER_RGB_MODE_METEOR    = 0x06,
    ACER_RGB_MODE_TWINKLING = 0x07,
};

/* Per-device driver data */
struct acer_rgb_data {
    struct hid_device *hdev_main;  /* interface 0 */
    struct hid_device *hdev_zone;  /* interface 1 */
    struct mutex lock;

    /* current state */
    u8  mode;
    u8  speed;
    u8  brightness;
    u8  direction;
    u8  per_zone;
    u8  zone_r[4], zone_g[4], zone_b[4];
};

/* One global pointer per physical keyboard (two hid_device handles share it). */
static struct acer_rgb_data *g_rgb_data;

/* ── Checksum ─────────────────────────────────────────────────────────────── */

static u8 acer_rgb_checksum(const u8 *d)
{
    u8 sum = 0;
    int i;
    for (i = 0; i < 7; i++)
        sum += d[i];
    return ~sum;
}

/* ── Raw HID output ───────────────────────────────────────────────────────── */

static int acer_rgb_send(struct hid_device *hdev, const u8 *payload8)
{
    u8 *buf;
    int ret;

    /* hidraw output: prepend report ID */
    buf = kmalloc(1 + ACER_RGB_REPORT_LEN, GFP_KERNEL);
    if (!buf)
        return -ENOMEM;

    buf[0] = ACER_RGB_REPORT_ID;
    memcpy(buf + 1, payload8, ACER_RGB_REPORT_LEN);

    ret = hid_hw_output_report(hdev, buf, 1 + ACER_RGB_REPORT_LEN);
    kfree(buf);
    return ret < 0 ? ret : 0;
}

/* ── Command builders ─────────────────────────────────────────────────────── */

static void build_cmd(u8 *out, u8 b0, u8 b1, u8 b2, u8 b3, u8 b4, u8 b5, u8 b6)
{
    out[0] = b0; out[1] = b1; out[2] = b2; out[3] = b3;
    out[4] = b4; out[5] = b5; out[6] = b6;
    out[7] = acer_rgb_checksum(out);
}

static int send_init(struct acer_rgb_data *d)
{
    u8 cmd[8];
    build_cmd(cmd, ACER_RGB_CMD_INIT, 0, 0, 0, 0, 0, 0);
    return acer_rgb_send(d->hdev_main, cmd);
}

static int send_setup(struct acer_rgb_data *d)
{
    u8 cmd[8];
    build_cmd(cmd, ACER_RGB_CMD_SETUP, 0, 0, 0, 0, 0, 0);
    return acer_rgb_send(d->hdev_main, cmd);
}

static int send_mode(struct acer_rgb_data *d)
{
    u8 cmd[8];
    build_cmd(cmd, ACER_RGB_CMD_MODE, ACER_RGB_SUB_ANIM,
              d->mode, d->speed, d->brightness, d->direction, d->per_zone);
    return acer_rgb_send(d->hdev_main, cmd);
}

static int send_zone_config(struct acer_rgb_data *d, u8 zone_mask)
{
    u8 cmd[8];
    build_cmd(cmd, ACER_RGB_CMD_MODE, ACER_RGB_SUB_ZONE,
              zone_mask, d->speed, d->brightness, zone_mask, 0x01);
    return acer_rgb_send(d->hdev_zone, cmd);
}

static int send_color_zone(struct acer_rgb_data *d, u8 zone_id, u8 r, u8 g, u8 b)
{
    u8 cmd[8];
    build_cmd(cmd, ACER_RGB_CMD_COLOR, zone_id, 0x00, r, g, b, 0x00);
    return acer_rgb_send(d->hdev_zone, cmd);
}

/* Apply the full current state to hardware */
static int acer_rgb_apply(struct acer_rgb_data *d)
{
    int ret;
    static const u8 zone_ids[4] = {0x01, 0x02, 0x04, 0x08};
    int i;

    ret = send_init(d);   if (ret) return ret;
    ret = send_setup(d);  if (ret) return ret;
    ret = send_mode(d);   if (ret) return ret;
    ret = send_zone_config(d, 0x0f); if (ret) return ret;

    if (d->per_zone) {
        for (i = 0; i < 4; i++) {
            ret = send_color_zone(d, zone_ids[i],
                                  d->zone_r[i], d->zone_g[i], d->zone_b[i]);
            if (ret) return ret;
        }
    } else {
        /* All zones same colour (zone_r[0] etc.) */
        for (i = 0; i < 4; i++) {
            ret = send_color_zone(d, zone_ids[i],
                                  d->zone_r[0], d->zone_g[0], d->zone_b[0]);
            if (ret) return ret;
        }
    }
    return 0;
}

/* ── Sysfs: four_zone_rgb ─────────────────────────────────────────────────── */

static ssize_t four_zone_rgb_show(struct device *dev,
                                   struct device_attribute *attr, char *buf)
{
    struct acer_rgb_data *d = g_rgb_data;
    if (!d) return -ENODEV;
    return sysfs_emit(buf, "%d,%d,%d,%d,%d,%d,%d\n",
                      d->mode, d->speed, d->brightness, d->direction,
                      d->zone_r[0], d->zone_g[0], d->zone_b[0]);
}

static ssize_t four_zone_rgb_store(struct device *dev,
                                    struct device_attribute *attr,
                                    const char *buf, size_t count)
{
    struct acer_rgb_data *d = g_rgb_data;
    int mode, speed, brightness, direction, r, g, b;
    int ret;

    if (!d) return -ENODEV;

    if (sscanf(buf, "%d,%d,%d,%d,%d,%d,%d",
               &mode, &speed, &brightness, &direction, &r, &g, &b) != 7)
        return -EINVAL;

    if (mode < 0 || mode > 7)   return -EINVAL;
    if (speed < 0 || speed > 10) return -EINVAL;
    if (brightness < 0 || brightness > 100) return -EINVAL;
    if (direction < 0 || direction > 1)     return -EINVAL;
    if (r < 0 || r > 255 || g < 0 || g > 255 || b < 0 || b > 255) return -EINVAL;

    mutex_lock(&d->lock);
    d->mode = mode; d->speed = speed; d->brightness = brightness;
    d->direction = direction; d->per_zone = 0;
    d->zone_r[0] = r; d->zone_g[0] = g; d->zone_b[0] = b;
    ret = acer_rgb_apply(d);
    mutex_unlock(&d->lock);

    return ret ? ret : count;
}

static DEVICE_ATTR_RW(four_zone_rgb);

/* ── Sysfs: per_zone_rgb ──────────────────────────────────────────────────── */

static ssize_t per_zone_rgb_show(struct device *dev,
                                  struct device_attribute *attr, char *buf)
{
    struct acer_rgb_data *d = g_rgb_data;
    if (!d) return -ENODEV;
    return sysfs_emit(buf, "%02x%02x%02x,%02x%02x%02x,%02x%02x%02x,%02x%02x%02x,%d\n",
                      d->zone_r[0], d->zone_g[0], d->zone_b[0],
                      d->zone_r[1], d->zone_g[1], d->zone_b[1],
                      d->zone_r[2], d->zone_g[2], d->zone_b[2],
                      d->zone_r[3], d->zone_g[3], d->zone_b[3],
                      d->brightness);
}

static ssize_t per_zone_rgb_store(struct device *dev,
                                   struct device_attribute *attr,
                                   const char *buf, size_t count)
{
    struct acer_rgb_data *d = g_rgb_data;
    unsigned long z[4];
    int brightness, i, ret;
    char tmp[34];
    char *p = tmp, *tok;

    if (!d) return -ENODEV;

    strncpy(tmp, buf, sizeof(tmp) - 1);
    tmp[sizeof(tmp)-1] = '\0';
    /* strip newline */
    if (tmp[strlen(tmp)-1] == '\n') tmp[strlen(tmp)-1] = '\0';

    for (i = 0; i < 4; i++) {
        tok = strsep(&p, ",");
        if (!tok || strlen(tok) != 6) return -EINVAL;
        if (kstrtoul(tok, 16, &z[i])) return -EINVAL;
    }
    tok = strsep(&p, ",");
    if (!tok || kstrtoint(tok, 10, &brightness)) return -EINVAL;
    if (brightness < 0 || brightness > 100) return -EINVAL;

    mutex_lock(&d->lock);
    d->mode = ACER_RGB_MODE_STATIC;
    d->brightness = brightness;
    d->per_zone = 1;
    for (i = 0; i < 4; i++) {
        d->zone_r[i] = (z[i] >> 16) & 0xff;
        d->zone_g[i] = (z[i] >>  8) & 0xff;
        d->zone_b[i] = (z[i]      ) & 0xff;
    }
    ret = acer_rgb_apply(d);
    mutex_unlock(&d->lock);

    return ret ? ret : count;
}

static DEVICE_ATTR_RW(per_zone_rgb);

static struct attribute *acer_rgb_attrs[] = {
    &dev_attr_four_zone_rgb.attr,
    &dev_attr_per_zone_rgb.attr,
    NULL,
};
static struct attribute_group acer_rgb_group = {
    .name  = "rgb",
    .attrs = acer_rgb_attrs,
};

/* ── HID driver callbacks ─────────────────────────────────────────────────── */

static int acer_rgb_probe(struct hid_device *hdev,
                           const struct hid_device_id *id)
{
    int ret;
    int iface = hdev->intf_num; /* interface number within the USB device */

    ret = hid_parse(hdev);
    if (ret) return ret;

    ret = hid_hw_start(hdev, HID_CONNECT_HIDRAW);
    if (ret) return ret;

    ret = hid_hw_open(hdev);
    if (ret) {
        hid_hw_stop(hdev);
        return ret;
    }

    if (!g_rgb_data) {
        g_rgb_data = kzalloc(sizeof(*g_rgb_data), GFP_KERNEL);
        if (!g_rgb_data) {
            hid_hw_close(hdev);
            hid_hw_stop(hdev);
            return -ENOMEM;
        }
        mutex_init(&g_rgb_data->lock);
        /* sane defaults */
        g_rgb_data->mode       = ACER_RGB_MODE_STATIC;
        g_rgb_data->speed      = 5;
        g_rgb_data->brightness = 100;
        g_rgb_data->zone_r[0]  = 0x00;
        g_rgb_data->zone_g[0]  = 0x00;
        g_rgb_data->zone_b[0]  = 0xFF;  /* Predator blue */
    }

    if (iface == ACER_RGB_IFACE_MAIN)
        g_rgb_data->hdev_main = hdev;
    else
        g_rgb_data->hdev_zone = hdev;

    /* Register sysfs only once (from iface 0) */
    if (iface == ACER_RGB_IFACE_MAIN) {
        ret = sysfs_create_group(&hdev->dev.kobj, &acer_rgb_group);
        if (ret) {
            hid_warn(hdev, "Failed to create sysfs group: %d\n", ret);
            /* non-fatal */
        }
    }

    hid_info(hdev, "Acer Predator RGB keyboard (iface %d) registered\n", iface);
    return 0;
}

static void acer_rgb_remove(struct hid_device *hdev)
{
    if (hdev->intf_num == ACER_RGB_IFACE_MAIN) {
        sysfs_remove_group(&hdev->dev.kobj, &acer_rgb_group);
        if (g_rgb_data) {
            kfree(g_rgb_data);
            g_rgb_data = NULL;
        }
    }
    hid_hw_close(hdev);
    hid_hw_stop(hdev);
}

static const struct hid_device_id acer_rgb_table[] = {
    { HID_USB_DEVICE(ACER_KBD_VID, ACER_KBD_PID) },
    {}
};
MODULE_DEVICE_TABLE(hid, acer_rgb_table);

static struct hid_driver acer_rgb_driver = {
    .name    = "acer-predator-rgb",
    .id_table = acer_rgb_table,
    .probe   = acer_rgb_probe,
    .remove  = acer_rgb_remove,
};
module_hid_driver(acer_rgb_driver);

MODULE_AUTHOR("You");
MODULE_DESCRIPTION("Acer Predator PH16-72 RGB keyboard USB HID driver");
MODULE_LICENSE("GPL");
