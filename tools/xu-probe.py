#!/usr/bin/env python3
"""
Raw UVC extension unit probe: read or write any selector on any unit.

The other tools here know the selectors they care about. This one knows nothing and
asks the device instead — GET_LEN and GET_INFO first, then the value — which is what
you want when mapping a register nobody has decoded yet.

    ./xu-probe.py --scan                    every selector of unit 9, 10 and 11
    ./xu-probe.py --unit 9 --sel 0x04       one selector, all query types
    ./xu-probe.py --unit 9 --sel 0x04 --set a5d00300f132
    ./xu-probe.py --unit 10 --sel 0x03 --watch 20

Remember that writes only stick while the camera is streaming — keep an ffmpeg
capture running, see daylight-probe.py.
"""

import argparse
import ctypes
import os
import sys
import time
from fcntl import ioctl

UNIT_GUIDS = {
    9:  b'\x2d\x67\xf1\xfa\x1b\xb7\x93\x47\x8c\x91\x7b\x1c\x9b\x7f\x95\xf8',
    10: b'\x49\xe6\x07\xe3\x18\x46\xff\xa3\x82\xfc\x2d\x8b\x5f\x21\x67\x73',
    11: b'\xf2\x5d\xbd\xa8\x98\x1a\x4e\x47\x8d\xd0\xd9\x26\x72\xd1\x94\xfa',
}

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

SET_CUR, GET_CUR, GET_MIN, GET_MAX, GET_RES, GET_LEN, GET_INFO, GET_DEF = (
    0x01, 0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87)
QUERY_NAMES = {GET_CUR: 'CUR', GET_MIN: 'MIN', GET_MAX: 'MAX', GET_RES: 'RES', GET_DEF: 'DEF'}

_IOC_READ, _IOC_WRITE = 2, 1


def _IOWR(type_, nr, size):
    d = (_IOC_READ | _IOC_WRITE) << 30
    return ctypes.c_int32(d | (ord(type_) << 8) | nr | (ctypes.sizeof(size) << 16)).value


class uvc_xu_control_query(ctypes.Structure):
    _fields_ = [('unit', ctypes.c_uint8), ('selector', ctypes.c_uint8),
                ('query', ctypes.c_uint8), ('size', ctypes.c_uint16),
                ('data', ctypes.c_void_p)]


UVCIOC_CTRL_QUERY = _IOWR('u', 0x21, uvc_xu_control_query)


def descriptors(device):
    node = os.path.basename(os.path.realpath(device))
    with open(f'/sys/class/video4linux/{node}/../../../descriptors', 'rb') as f:
        return f.read()


def unit_ids(device):
    """Map our unit numbers to the ids this camera actually advertises."""
    data = descriptors(device)
    found = {}
    for unit, guid in UNIT_GUIDS.items():
        pos = data.find(guid)
        if pos > 0:
            found[unit] = data[pos - 1]
    return found


def query(fd, unit, selector, q, size, payload=None):
    buf = ctypes.create_string_buffer(bytes(payload) if payload else size)
    xq = uvc_xu_control_query()
    xq.unit, xq.selector, xq.query = unit, selector, q
    xq.size = size
    xq.data = ctypes.cast(ctypes.pointer(buf), ctypes.c_void_p)
    ioctl(fd, UVCIOC_CTRL_QUERY, xq)
    return buf.raw[:size]


def try_query(fd, unit, selector, q, size, payload=None):
    try:
        return query(fd, unit, selector, q, size, payload), None
    except OSError as e:
        return None, e.strerror


def get_len(fd, unit, selector):
    raw, err = try_query(fd, unit, selector, GET_LEN, 2)
    return int.from_bytes(raw, 'little') if raw else 0


def info_flags(fd, unit, selector):
    raw, err = try_query(fd, unit, selector, GET_INFO, 1)
    if not raw:
        return '-'
    bits = raw[0]
    names = [n for b, n in ((1, 'get'), (2, 'set'), (4, 'disabled'),
                            (8, 'autoupdate'), (16, 'async')) if bits & b]
    return f'{bits:#04x} ' + '|'.join(names)


def hexdump(data, indent='    '):
    out = []
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hexs = ' '.join(f'{b:02x}' for b in chunk)
        text = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
        out.append(f'{indent}{i:04x}  {hexs:<47}  {text}')
    return '\n'.join(out)


def show(fd, unit, selector, queries, brief=False):
    length = get_len(fd, unit, selector)
    name = SELECTORS.get(selector, '') if unit == 9 else ''
    head = f'unit {unit} sel {selector:#04x} {name:<24} len {length:>4}  info {info_flags(fd, unit, selector)}'
    if not length:
        print(head + '   (no length, skipping)')
        return
    print(head)
    for q in queries:
        raw, err = try_query(fd, unit, selector, q, length)
        if raw is None:
            print(f'  {QUERY_NAMES[q]}: {err}')
            continue
        if brief and q == GET_CUR and length <= 8:
            print(f'  {QUERY_NAMES[q]}: {raw.hex()}')
        else:
            print(f'  {QUERY_NAMES[q]}:')
            print(hexdump(raw))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('-d', '--device',
                    default='/dev/v4l/by-id/usb-Insta360_Insta360_Link-video-index0')
    ap.add_argument('--unit', type=int, help='unit number, 9 10 or 11')
    ap.add_argument('--sel', type=lambda s: int(s, 0), help='selector, e.g. 0x04')
    ap.add_argument('--set', dest='payload', help='hex bytes to SET_CUR')
    ap.add_argument('--all-queries', action='store_true', help='also MIN MAX RES DEF')
    ap.add_argument('--scan', action='store_true', help='walk every selector of every unit')
    ap.add_argument('--watch', type=float, metavar='SECONDS',
                    help='re-read once a second and print only when the value changes')
    args = ap.parse_args()

    ids = unit_ids(args.device)
    if not ids:
        print('no known extension unit in this device descriptor', file=sys.stderr)
        return 1

    fd = os.open(args.device, os.O_RDWR)
    queries = [GET_CUR] + ([GET_MIN, GET_MAX, GET_RES, GET_DEF] if args.all_queries else [])

    if args.scan:
        for unit, uid in sorted(ids.items()):
            print(f'\n=== unit {unit} (id {uid}) ===')
            for sel in range(1, 0x20):
                show(fd, uid, sel, [GET_CUR], brief=True)
        return 0

    if args.unit is None or args.sel is None:
        ap.error('need --unit and --sel, or --scan')
    uid = ids.get(args.unit, args.unit)

    if args.payload:
        data = bytes.fromhex(args.payload.replace(' ', ''))
        length = get_len(fd, uid, args.sel)
        if length and len(data) < length:
            data = data + bytes(length - len(data))
        raw, err = try_query(fd, uid, args.sel, SET_CUR, len(data), data)
        print(f'SET_CUR {len(data)}B: ' + ('ok' if err is None else err))

    if args.watch:
        length = get_len(fd, uid, args.sel)
        last, deadline = None, time.time() + args.watch
        while time.time() < deadline:
            raw, err = try_query(fd, uid, args.sel, GET_CUR, length)
            if raw != last:
                print(f'{time.time() % 1000:8.2f}s')
                print(hexdump(raw) if raw else f'    {err}')
                last = raw
            time.sleep(0.2)
        return 0

    show(fd, uid, args.sel, queries)
    return 0


if __name__ == '__main__':
    sys.exit(main())
