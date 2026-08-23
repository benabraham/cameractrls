#!/usr/bin/env python3
"""
Insta360 Link gen 1 (2e1a:4c01) — probes that need real light in the room.

Run it when the room is lit. It streams the camera itself, measures frame statistics
around each write, restores every selector it touched, and writes a report next to
itself. Nothing here needs a person in frame.

  ./daylight-probe.py [--out report.txt]

Selector names come from the vendor app's protobuf ControlSelector enum, see
src/insta360.md.
"""

import argparse
import ctypes
import os
import statistics
import struct
import subprocess
import sys
import threading
import time
from fcntl import ioctl

DEV = '/dev/v4l/by-id/usb-Insta360_Insta360_Link-video-index0'
UNIT = 9

SEL_VIDEO_MODE = 0x02
SEL_EXPOSURE_VALUE = 0x09
SEL_DEVICE_STATUS = 0x0b
SEL_FUNC_ENABLE = 0x1b
SEL_BIAS = 0x18
SEL_ISO = 0x19
SEL_PANTILT_ABS = 0x1a
SEL_EXPOSURE_TIME = 0x1d
SEL_AE_MODE = 0x1e

GET_CUR, SET_CUR = 0x81, 0x01
FUNC_BIT_GESTURES = 0x10


class _query(ctypes.Structure):
    _fields_ = [('unit', ctypes.c_uint8), ('selector', ctypes.c_uint8), ('query', ctypes.c_uint8),
                ('size', ctypes.c_uint16), ('data', ctypes.c_void_p)]


UVCIOC_CTRL_QUERY = (ctypes.c_int32(3 << 30).value | ctypes.c_int32(ord('u') << 8).value |
                     ctypes.c_int32(0x21).value | ctypes.c_int32(ctypes.sizeof(_query) << 16).value)


class Camera:
    def __init__(self, device=DEV):
        self.fd = os.open(device, os.O_RDWR)
        self.device = device

    def xu(self, selector, query, data):
        buf = ctypes.create_string_buffer(data, len(data))
        q = _query()
        q.unit, q.selector, q.query, q.size = UNIT, selector, query, len(data)
        q.data = ctypes.cast(ctypes.pointer(buf), ctypes.c_void_p)
        ioctl(self.fd, UVCIOC_CTRL_QUERY, q)
        return buf.raw[:len(data)]

    def read(self, selector, length):
        return self.xu(selector, GET_CUR, bytes(length))

    def read_int(self, selector, length, signed=False):
        return int.from_bytes(self.read(selector, length), 'little', signed=signed)

    def write(self, selector, data):
        self.xu(selector, SET_CUR, data)

    def write_int(self, selector, value, length, signed=False):
        self.write(selector, value.to_bytes(length, 'little', signed=signed))

    def pantilt(self):
        return struct.unpack('<ii', self.read(SEL_PANTILT_ABS, 8))

    def close(self):
        os.close(self.fd)


class Preview:
    """Keeps the camera streaming — XU writes only stick while it is — and samples frames."""

    W, H = 32, 18
    FRAME = W * H

    def __init__(self, device=DEV):
        self.proc = subprocess.Popen(
            ['ffmpeg', '-nostdin', '-loglevel', 'error', '-f', 'v4l2', '-input_format', 'mjpeg',
             '-video_size', '1280x720', '-framerate', '30', '-i', device,
             '-vf', f'fps=4,scale={self.W}:{self.H},format=gray', '-f', 'rawvideo', 'pipe:1'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.frames = []
        self.t0 = time.monotonic()
        threading.Thread(target=self._read, daemon=True).start()
        deadline = time.monotonic() + 15
        while not self.frames and time.monotonic() < deadline:
            time.sleep(0.2)
        if not self.frames:
            raise RuntimeError('no frames from the camera, is something else using it?')

    def _read(self):
        while True:
            b = self.proc.stdout.read(self.FRAME)
            if not b or len(b) < self.FRAME:
                return
            self.frames.append((time.monotonic(), b))

    def stats(self, seconds=4, settle=1.5):
        mark = time.monotonic()
        time.sleep(seconds)
        px = [p for t, f in self.frames if mark + settle <= t <= mark + seconds for p in f]
        if not px:
            return None
        px_sorted = sorted(px)
        return {'mean': round(statistics.mean(px), 1), 'sd': round(statistics.pstdev(px), 1),
                'p5': px_sorted[len(px_sorted) // 20], 'p95': px_sorted[len(px_sorted) * 19 // 20]}

    def close(self):
        self.proc.terminate()


def fmt(st):
    return f'mean {st["mean"]:>5} sd {st["sd"]:>5} p5 {st["p5"]:>3} p95 {st["p95"]:>3}' if st else 'no frames'


def section_a(cam, preview, saved, say):
    say('\n=== A. exposure compensation 0x09, needs headroom to show the positive half ===')
    for value in (-300, -150, 0, 150, 300):
        cam.write_int(SEL_EXPOSURE_VALUE, value, 2, signed=True)
        say(f'  {value:+5d} ({value / 100:+.2f} EV): {fmt(preview.stats(6))}')
    cam.write(SEL_EXPOSURE_VALUE, saved[SEL_EXPOSURE_VALUE])
    time.sleep(2)


def section_b(cam, preview, saved, say):
    say('\n=== B. ISO ladder 0x19 at 1/60s, expect a straight line ===')
    cam.write_int(SEL_AE_MODE, 1, 1)
    cam.write_int(SEL_EXPOSURE_TIME, 60, 2)
    time.sleep(2)
    for iso in (100, 200, 400, 800, 1600, 3200):
        cam.write_int(SEL_ISO, iso, 2)
        say(f'  ISO {iso:>5}: {fmt(preview.stats(5))}')


def section_c(cam, preview, saved, say):
    say('\n=== C. shutter ladder 0x1d at ISO 400, expect halving per stop ===')
    cam.write_int(SEL_AE_MODE, 1, 1)
    cam.write_int(SEL_ISO, 400, 2)
    time.sleep(2)
    for denominator in (30, 60, 125, 250, 500, 1000, 2000, 4000, 8000):
        cam.write_int(SEL_EXPOSURE_TIME, denominator, 2)
        say(f'  1/{denominator:<5}s: readback 1/{cam.read_int(SEL_EXPOSURE_TIME, 2):<5} '
            f'{fmt(preview.stats(5))}')


def section_d(cam, preview, reference, say):
    """Low bits of the function bitmask only. See the danger note below."""
    say('\n=== D. 0x1b function bitmask, low bits only ===')
    say('  DANGER, measured 2026-08-21: setting bit 0x20 dropped the camera off the USB bus,')
    say('  left 0x1b reading 0x0030 and made every write to it fail with EPROTO until the')
    say('  device re-enumerated. Bits 0x20 and above are never written here.')
    base_mask = cam.read_int(SEL_FUNC_ENABLE, 2)
    say(f'  mask 0x{base_mask:04x} reference: {fmt(reference)}')
    for flag in (0x01, 0x02, 0x04, 0x08):
        if flag == FUNC_BIT_GESTURES or base_mask & flag:
            continue
        try:
            cam.write_int(SEL_FUNC_ENABLE, base_mask | flag, 2)
            got = cam.read_int(SEL_FUNC_ENABLE, 2)
            stats = preview.stats(5)
        except OSError as err:
            say(f'  bit 0x{flag:04x}: camera errored ({err.strerror}), stopping the sweep')
            return
        took = 'stuck' if got & flag else 'rejected'
        note = ''
        if stats and reference and took == 'stuck':
            spread = (stats['p95'] - stats['p5']) - (reference['p95'] - reference['p5'])
            note = f'  dynamic-range change {spread:+d}'
        say(f'  bit 0x{flag:04x}: {took:<8} {fmt(stats)}{note}')
        cam.write_int(SEL_FUNC_ENABLE, base_mask, 2)
        time.sleep(1.5)


def section_f(cam, preview, reference, say):
    say('\n=== F. HDR hunt in the AE mode itself, 0x1e ===')
    say('  The app says "After enabling HDR, manual exposure is temporarily not supported",')
    say('  so HDR is an auto-exposure variant rather than an independent toggle. 1 is manual,')
    say('  2 is auto, and 0, 3, 4, 5 are all accepted. HDR lifts shadows, so watch p5.')
    for mode in (2, 0, 3, 4, 5):
        cam.write_int(SEL_AE_MODE, mode, 1)
        time.sleep(1)
        got = cam.read_int(SEL_AE_MODE, 1)
        stats = preview.stats(7)
        note = ''
        if stats and reference:
            note = (f'  p5 {stats["p5"] - reference["p5"]:+d}, '
                    f'range {(stats["p95"] - stats["p5"]) - (reference["p95"] - reference["p5"]):+d}')
        say(f'  0x1e={mode} -> readback {got}  {fmt(stats)}{note}')
    cam.write_int(SEL_AE_MODE, 2, 1)
    time.sleep(2)


def section_e(cam, preview, saved, say):
    say('\n=== E. XU_BIAS 0x18, suspected horizontal fine-tuning ===')
    say(f'  before: 0x18={saved[SEL_BIAS].hex(" ")} pan/tilt={cam.pantilt()}')
    for low_byte in (0, 96):
        payload = bytearray(saved[SEL_BIAS])
        payload[0] = low_byte
        cam.write(SEL_BIAS, bytes(payload))
        time.sleep(3)
        say(f'  low byte {low_byte:>3}: readback {cam.read(SEL_BIAS, 4).hex(" ")} '
            f'pan/tilt={cam.pantilt()} {fmt(preview.stats(4))}')
    cam.write(SEL_BIAS, saved[SEL_BIAS])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                  'daylight-report.txt'))
    ap.add_argument('--sections', default='ABCDFE',
                    help='which sections to run, e.g. --sections FE')
    args = ap.parse_args()
    sections = args.sections.upper()

    cam = Camera()
    preview = Preview()
    lines = []

    def say(msg):
        print(msg, flush=True)
        lines.append(msg)

    saved = {sel: cam.read(sel, n) for sel, n in (
        (SEL_EXPOSURE_VALUE, 2), (SEL_FUNC_ENABLE, 2), (SEL_BIAS, 4),
        (SEL_ISO, 2), (SEL_EXPOSURE_TIME, 2), (SEL_AE_MODE, 1))}
    say(f'device {cam.device}, status {cam.read(SEL_DEVICE_STATUS, 5).hex(" ")}, sections {sections}')
    say('saved: ' + ', '.join(f'0x{s:02x}={v.hex()}' for s, v in saved.items()))
    reference = preview.stats(5)
    say(f'baseline (auto exposure): {fmt(reference)}')

    try:
        if 'A' in sections:
            section_a(cam, preview, saved, say)
        if 'B' in sections:
            section_b(cam, preview, saved, say)
        if 'C' in sections:
            section_c(cam, preview, saved, say)
        if 'D' in sections or 'F' in sections:
            cam.write_int(SEL_AE_MODE, 2, 1)
            time.sleep(3)
            reference = preview.stats(6) or reference
        if 'D' in sections:
            section_d(cam, preview, reference, say)
        if 'F' in sections:
            section_f(cam, preview, reference, say)
        if 'E' in sections:
            section_e(cam, preview, saved, say)
    finally:
        for sel, value in saved.items():
            try:
                cam.write(sel, value)
            except OSError as err:
                say(f'restore of 0x{sel:02x} failed: {err.strerror}')
        time.sleep(1)
        say('(0x19 and 0x1d drift by design once auto exposure takes over again)')
        preview.close()
        cam.close()
        with open(args.out, 'w') as fh:
            fh.write('\n'.join(lines) + '\n')
        print(f'\nreport written to {args.out}')


if __name__ == '__main__':
    sys.exit(main())
