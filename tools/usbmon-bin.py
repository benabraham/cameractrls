#!/usr/bin/env python3
"""
Capture UVC extension-unit traffic with FULL payloads.

The usbmon text interface truncates data at 32 bytes, which hides the interesting half of
anything bigger — the 255 byte exposure curve, the 52 byte video mode struct, the 32+ byte
PTZ commands. The binary interface has no such limit, so this reads /dev/usbmonN directly.

Needs root for the device node:

    sudo ./usbmon-bin.py 3 --seconds 180 --out /home/srb/vm/xu.txt

Then read it back as a normal user — the file is chowned to the invoking user.

The read() ABI delivers a 48 byte header, not the 64 byte one from the mmap ABI — the
trailing interval/start_frame/xfer_flags/ndesc fields exist only in mon_bin_mfetch:
    u64 id, u8 type, u8 xfer_type, u8 epnum, u8 devnum, u16 busnum,
    s8 flag_setup, s8 flag_data, s64 ts_sec, s32 ts_usec, s32 status,
    u32 len_urb, u32 len_cap, u8 setup[8]
"""

import argparse
import os
import pwd
import struct
import sys
import time

HDR = struct.Struct('<Q4BHbbqiiII8s')
assert HDR.size == 48, HDR.size   # the read() ABI header

XFER_CONTROL = 2
SELECTORS = {
    0x01: 'EXEC_SCRIPT', 0x02: 'VIDEO_MODE', 0x03: 'DEVICE_INFO', 0x04: 'PTZ_CMD',
    0x05: 'GESTURE_STATUS', 0x06: 'GESTURE_BIND', 0x07: 'NOISE_CANCEL',
    0x08: 'FIRMWARE_UPGRADE', 0x09: 'EXPOSURE_VALUE', 0x0a: 'TAKE_PICTURE',
    0x0b: 'DEVICE_STATUS', 0x0c: 'DEVICE_SN', 0x0d: 'DEVICE_LICENSEN', 0x0e: 'DEVICE_PARAM',
    0x0f: 'AF_MODE', 0x10: 'EXPOSURE_CURVE', 0x11: 'USB_MODE_SWITCH', 0x12: 'TRACK_SPEED',
    0x13: 'LAYOUT_STYLE', 0x14: 'HEAD_LIST', 0x15: 'TRACK_TARGET', 0x16: 'PANTILT_RELATIVE',
    0x17: 'MOBVOI_PUBKEY', 0x18: 'BIAS', 0x19: 'ISO', 0x1a: 'PANTILT_ABSOLUTE',
    0x1b: 'FUNC_ENABLE', 0x1c: 'VIDEO_RES', 0x1d: 'EXPOSURE_TIME_ABSOLUTE', 0x1e: 'AE_MODE',
}
REQUESTS = {0x01: 'SET_CUR', 0x81: 'GET_CUR', 0x82: 'GET_MIN', 0x83: 'GET_MAX',
            0x84: 'GET_RES', 0x85: 'GET_LEN', 0x86: 'GET_INFO', 0x87: 'GET_DEF'}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('bus', type=int, help='USB bus number, 3 for this camera')
    ap.add_argument('--seconds', type=float, default=180)
    ap.add_argument('--out', default='xu-capture.txt')
    ap.add_argument('--all', action='store_true', help='keep reads too, not just writes')
    args = ap.parse_args()

    node = f'/dev/usbmon{args.bus}'
    if not os.path.exists(node):
        print(f'{node} missing — run: sudo modprobe usbmon', file=sys.stderr)
        return 1

    pending = {}
    events = control_events = count = 0
    base = None
    deadline = time.time() + args.seconds
    out = open(args.out, 'w')
    owner = os.environ.get('SUDO_USER')
    if owner:                                  # hand the file back before writing anything
        try:
            info = pwd.getpwnam(owner)
            os.chown(args.out, info.pw_uid, info.pw_gid)
        except (KeyError, OSError):
            pass
    fd = os.open(node, os.O_RDONLY)
    print(f'capturing {node} for {args.seconds:.0f}s, full payloads -> {args.out}',
          file=sys.stderr, flush=True)

    def emit(stamp, unit, selector, breq, payload):
        nonlocal count, base
        if base is None:
            base = stamp
        count += 1
        name = SELECTORS.get(selector, '?')
        request = REQUESTS.get(breq, f'0x{breq:02x}')
        out.write(f'{stamp - base:8.3f}s unit {unit:>2} 0x{selector:02x} {name:<24} '
                  f'{request:<8} {len(payload) // 2:>3}B {payload}\n')
        out.flush()

    try:
        while time.time() < deadline:
            try:
                buf = os.read(fd, 65536)
            except OSError:
                continue
            if len(buf) < HDR.size:
                continue
            (_id, ev_type, xfer_type, _ep, _dev, _bus, flag_setup, _flag_data,
             ts_sec, ts_usec, _status, _len_urb, len_cap, setup) = HDR.unpack_from(buf)
            events += 1
            data = buf[HDR.size:HDR.size + len_cap]
            stamp = ts_sec + ts_usec / 1e6

            if xfer_type != XFER_CONTROL:
                continue
            control_events += 1
            if flag_setup == 0:                       # 'S' submit carries the setup packet
                bmreq, breq, wvalue, windex, wlength = struct.unpack('<BBHHH', setup)
                if bmreq not in (0x21, 0xa1):
                    continue
                selector, unit = wvalue >> 8, windex >> 8
                if breq == 0x01:
                    emit(stamp, unit, selector, breq, data.hex())
                else:
                    pending[_id] = (stamp, unit, selector, breq)
            elif _id in pending and args.all:
                stamp, unit, selector, breq = pending.pop(_id)
                emit(stamp, unit, selector, breq, data.hex())
    finally:
        os.close(fd)
        out.close()

    print(f'{events} URB events, {control_events} control transfers, '
          f'{count} extension-unit transfers -> {args.out}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
