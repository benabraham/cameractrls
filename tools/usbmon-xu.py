#!/usr/bin/env python3
"""
Decode UVC extension-unit traffic out of a usbmon text capture.

Point it at a capture taken while the Windows app drives the camera (in a VM, with the
camera passed through) and it prints every XU read and write with the vendor's own selector
names, so a UI action can be matched to the bytes it sends.

  sudo modprobe usbmon
  sudo sh -c 'timeout 180 cat /sys/kernel/debug/usb/usbmon/3u > /home/srb/vm/cap.txt'
  ./usbmon-xu.py /home/srb/vm/cap.txt --writes-only

usbmon prints a control setup packet as:
  <urb> <ts> S Co:3:004:0 s 21 01 1900 0900 0002 2 = 9001
                            ^bmRequestType ^bRequest ^wValue ^wIndex ^wLength
For a UVC XU request wValue is the selector in the high byte and wIndex the unit id in the
high byte, so the example is SET_CUR on unit 9 selector 0x19 (ISO) with payload 0x0190 = 400.
"""

import argparse
import re
import sys

# recovered from the vendor app's protobuf ControlSelector enum, see src/insta360.md
SELECTORS = {
    0x01: 'EXEC_SCRIPT', 0x02: 'VIDEO_MODE', 0x03: 'DEVICE_INFO', 0x04: 'PTZ_CMD',
    0x05: 'GESTURE_STATUS', 0x06: 'GESTURE_BIND', 0x07: 'NOISE_CANCEL',
    0x08: 'FIRMWARE_UPGRADE/BLEND_DRAW', 0x09: 'EXPOSURE_VALUE', 0x0a: 'TAKE_PICTURE',
    0x0b: 'DEVICE_STATUS', 0x0c: 'DEVICE_SN', 0x0d: 'DEVICE_LICENSEN', 0x0e: 'DEVICE_PARAM',
    0x0f: 'DOWNLOAD_FILE/AF_MODE', 0x10: 'UPLOAD_FILE/EXPOSURE_CURVE', 0x11: 'USB_MODE_SWITCH',
    0x12: 'TRACK_SPEED', 0x13: 'LAYOUT_STYLE', 0x14: 'HEAD_LIST', 0x15: 'TRACK_TARGET',
    0x16: 'PANTILT_RELATIVE', 0x17: 'MOBVOI_PUBKEY', 0x18: 'BIAS', 0x19: 'ISO',
    0x1a: 'PANTILT_ABSOLUTE', 0x1b: 'FUNC_ENABLE', 0x1c: 'VIDEO_RES',
    0x1d: 'EXPOSURE_TIME_ABSOLUTE', 0x1e: 'AE_MODE',
}

REQUESTS = {0x01: 'SET_CUR', 0x81: 'GET_CUR', 0x82: 'GET_MIN', 0x83: 'GET_MAX',
            0x84: 'GET_RES', 0x85: 'GET_LEN', 0x86: 'GET_INFO', 0x87: 'GET_DEF'}

COMPLETION = re.compile(
    r'^(?P<urb>\S+)\s+(?P<ts>\d+)\s+C\s+Co:\d+:\d+:\d+\s+(?P<status>-?\d+)\s+'
    r'(?P<len>\d+)(?P<rest>.*)$')

SETUP = re.compile(
    r'^(?P<urb>\S+)\s+(?P<ts>\d+)\s+(?P<event>[SC])\s+Co:(?P<bus>\d+):(?P<dev>\d+):\d+\s+s\s+'
    r'(?P<bmreq>[0-9a-f]{2})\s+(?P<breq>[0-9a-f]{2})\s+(?P<wvalue>[0-9a-f]{4})\s+'
    r'(?P<windex>[0-9a-f]{4})\s+(?P<wlength>[0-9a-f]{4})(?P<rest>.*)$')


def payload(rest):
    if '=' not in rest:
        return ''
    return rest.split('=', 1)[1].strip().replace(' ', '')


def decode(data, selector):
    """Best-effort human reading of a short payload."""
    if not data or len(data) > 8:
        return ''
    raw = bytes.fromhex(data)
    value = int.from_bytes(raw, 'little')
    signed = int.from_bytes(raw, 'little', signed=True)
    hints = {
        0x09: lambda: f'{signed} raw = {signed / 100:+.2f} EV',
        0x19: lambda: f'ISO {value}',
        0x1d: lambda: f'1/{value}s',
        0x1e: lambda: {1: 'manual', 2: 'auto'}.get(value, f'mode {value}'),
        0x12: lambda: {1: 'slow', 2: 'medium', 3: 'fast'}.get(value, f'speed {value}'),
        0x13: lambda: {1: 'head', 2: 'half body', 3: 'whole body'}.get(value, f'style {value}'),
        0x05: lambda: 'gestures ' + (', '.join(
            n for bit, n in ((0x02, 'palm'), (0x04, 'L'), (0x08, 'V')) if value & bit) or 'none'),
        0x1b: lambda: f'func mask 0x{value:04x}',
    }
    if selector in hints:
        return hints[selector]()
    return f'{value} (0x{value:x})' if len(raw) <= 4 else ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('capture', help='usbmon text capture, or - for stdin')
    ap.add_argument('--writes-only', action='store_true', help='only SET_CUR, the interesting half')
    ap.add_argument('--unit', type=int, default=None, help='only this extension unit id')
    ap.add_argument('--selector', type=lambda v: int(v, 0), default=None, help='only this selector')
    args = ap.parse_args()

    stream = sys.stdin if args.capture == '-' else open(args.capture, errors='replace')
    seen = 0
    pending = {}   # a GET carries its payload on the completion line, not the setup line

    def emit(ts, unit, selector, breq, data):
        nonlocal seen
        seen += 1
        name = SELECTORS.get(selector, '?')
        request = REQUESTS.get(breq, f'req 0x{breq:02x}')
        print(f'{ts / 1e6:12.3f}s  unit {unit:>2}  0x{selector:02x} {name:<28} '
              f'{request:<8} {data:<20} {decode(data, selector)}')

    for line in stream:
        line = line.strip()
        done = COMPLETION.match(line)
        if done and done.group('urb') in pending:
            ts, unit, selector, breq = pending.pop(done.group('urb'))
            emit(ts, unit, selector, breq, payload(done.group('rest')))
            continue
        m = SETUP.match(line)
        if not m:
            continue
        bmreq = int(m.group('bmreq'), 16)
        if bmreq not in (0x21, 0xa1):            # class request to an interface
            continue
        breq = int(m.group('breq'), 16)
        selector = int(m.group('wvalue'), 16) >> 8
        unit = int(m.group('windex'), 16) >> 8
        if args.unit is not None and unit != args.unit:
            continue
        if args.selector is not None and selector != args.selector:
            continue
        if args.writes_only and breq != 0x01:
            continue
        if m.group('event') != 'S':
            continue
        if breq == 0x01:                      # a write carries its payload on the submit line
            emit(int(m.group('ts')), unit, selector, breq, payload(m.group('rest')))
        else:                                 # a read gets its payload on the completion line
            pending[m.group('urb')] = (int(m.group('ts')), unit, selector, breq)
    print(f'\n{seen} extension-unit transfers', file=sys.stderr)
    if not seen:
        print('Nothing matched. Check the bus number in the capture and that the app was '
              'actually driving the camera.', file=sys.stderr)


if __name__ == '__main__':
    sys.exit(main())
