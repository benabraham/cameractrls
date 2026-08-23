#!/usr/bin/env python3
"""
Insta360 Link UVC Extension Unit Control Script

Standalone script to control Insta360 Link camera via UVC Extension Units.
Based on reverse engineering documented in docs/insta360.md

Confirmed working controls:
- Exposure Mode (0x1e): auto/manual mode selection
- Shutter Speed (0x19): 1/30s to 1/10000s (manual mode only)

Note: 0x1b is NOT gain, it is the function status bitmask (see insta360.md).
Writing raw values there is what disconnected the camera, so it is gone from here.

Usage:
  ./insta360-ctrl.py                    # Show current values
  ./insta360-ctrl.py mode manual        # Set manual exposure mode
  ./insta360-ctrl.py mode auto          # Set auto exposure mode
  ./insta360-ctrl.py shutter 1/60       # Set shutter to 1/60s
  ./insta360-ctrl.py shutter 8000       # Set shutter to 8000µs

Author: srb
License: MIT
"""

import ctypes
import os
import sys
import argparse
from fcntl import ioctl

# UVC Extension Unit GUID for Insta360 Link (Unit 9)
# Original: faf1672d-b71b-4793-8c91-7b1c9b7f95f8
# Bytes reversed for little-endian matching in USB descriptors
INSTA360_LINK_GUID = b'\x2d\x67\xf1\xfa\x1b\xb7\x93\x47\x8c\x91\x7b\x1c\x9b\x7f\x95\xf8'
INSTA360_LINK_USB_ID = '2e1a:4c01'

# Selectors (control registers)
SEL_EXP_MODE = 0x1e   # 1 byte: exposure mode
SEL_EXP_TIME = 0x19   # 2 bytes LE: exposure time in microseconds
SEL_FUNC_STATUS = 0x1b  # 2 bytes LE: function status bitmask, 0x10 = gestures enabled
SEL_GESTURE = 0x05    # 1 byte: gesture bitmask, palm 0x02, L 0x04, V 0x08
SEL_EXP_BIAS = 0x09   # 2 bytes LE: exposure bias, signed, -4..+4 on this firmware
SEL_TRACK_SPEED = 0x12  # 1 byte: 1 slow, 2 medium, 3 fast

# UVC Query commands
UVC_SET_CUR = 0x01
UVC_GET_CUR = 0x81

# ioctl definitions
_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14
_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS
_IOC_WRITE = 1
_IOC_READ = 2

def _IOC(dir_, type_, nr, size):
    return (
        ctypes.c_int32(dir_ << _IOC_DIRSHIFT).value |
        ctypes.c_int32(ord(type_) << _IOC_TYPESHIFT).value |
        ctypes.c_int32(nr << _IOC_NRSHIFT).value |
        ctypes.c_int32(size << _IOC_SIZESHIFT).value
    )

def _IOWR(type_, nr, size):
    return _IOC(_IOC_READ | _IOC_WRITE, type_, nr, ctypes.sizeof(size))

class uvc_xu_control_query(ctypes.Structure):
    _fields_ = [
        ('unit', ctypes.c_uint8),
        ('selector', ctypes.c_uint8),
        ('query', ctypes.c_uint8),
        ('size', ctypes.c_uint16),
        ('data', ctypes.c_void_p),
    ]

UVCIOC_CTRL_QUERY = _IOWR('u', 0x21, uvc_xu_control_query)


def find_device():
    """Find Insta360 Link by USB ID"""
    stable_path = '/dev/v4l/by-id/usb-Insta360_Insta360_Link-video-index0'
    if os.path.exists(stable_path):
        return stable_path

    # Fallback: search /dev/video*
    for i in range(10):
        dev = f'/dev/video{i}'
        if os.path.exists(dev):
            usb_ids = get_usb_ids(dev)
            if usb_ids == INSTA360_LINK_USB_ID:
                return dev
    return None


def get_usb_ids(device):
    """Get USB vendor:product from sysfs"""
    if os.path.islink(device):
        device = os.readlink(device)
    device = os.path.basename(device)

    vendor_file = f'/sys/class/video4linux/{device}/../../../idVendor'
    product_file = f'/sys/class/video4linux/{device}/../../../idProduct'

    try:
        with open(vendor_file) as f:
            vendor = f.read().strip()
        with open(product_file) as f:
            product = f.read().strip()
        return f'{vendor}:{product}'
    except:
        return ''


def find_unit_id(device):
    """Find XU unit ID by GUID in USB descriptors"""
    if os.path.islink(device):
        device = os.path.realpath(device)
    device = os.path.basename(device)

    desc_file = f'/sys/class/video4linux/{device}/../../../descriptors'
    try:
        with open(desc_file, 'rb') as f:
            data = f.read()
            pos = data.find(INSTA360_LINK_GUID)
            if pos > 0:
                return data[pos - 1]
    except Exception as e:
        print(f'Error reading descriptors: {e}', file=sys.stderr)
    return 0


def to_buf(b):
    """Create ctypes buffer from bytes"""
    return ctypes.create_string_buffer(b)


def query_xu(fd, unit_id, selector, query, data):
    """Query UVC Extension Unit control"""
    xu_query = uvc_xu_control_query()
    xu_query.unit = unit_id
    xu_query.selector = selector
    xu_query.query = query
    xu_query.size = len(data) - 1  # create_string_buffer adds +1
    xu_query.data = ctypes.cast(ctypes.pointer(data), ctypes.c_void_p)

    try:
        ioctl(fd, UVCIOC_CTRL_QUERY, xu_query)
        return True
    except Exception as e:
        print(f'XU query failed: {e}', file=sys.stderr)
        return False


def get_value(fd, unit_id, selector, length):
    """Get current value from control"""
    buf = to_buf(bytes(length))
    if query_xu(fd, unit_id, selector, UVC_GET_CUR, buf):
        return int.from_bytes(buf.raw[:length], 'little')
    return None


def set_value(fd, unit_id, selector, value, length):
    """Set control value"""
    data = value.to_bytes(length, 'little')
    buf = to_buf(data)
    return query_xu(fd, unit_id, selector, UVC_SET_CUR, buf)


# Exposure mode mapping
EXP_MODES = {
    0: 'auto-0',
    1: 'manual',
    2: 'auto',
    3: 'auto-fast',
    4: 'auto-slow',
    5: 'auto-5',
}
EXP_MODES_REV = {v: k for k, v in EXP_MODES.items()}

TRACK_SPEEDS = {
    1: 'slow',
    2: 'medium',
    3: 'fast',
}

GESTURE_BITS = {
    0x02: 'palm',
    0x04: 'L',
    0x08: 'V',
}

# Shutter speed presets (name -> microseconds)
SHUTTER_PRESETS = {
    '1/30': 33333,
    '1/60': 16667,
    '1/125': 8000,
    '1/250': 4000,
    '1/500': 2000,
    '1/1000': 1000,
    '1/2000': 500,
    '1/4000': 250,
    '1/8000': 125,
    '1/10000': 100,
}


def format_shutter(us):
    """Format microseconds as shutter speed"""
    if us >= 1000000:
        return f'{us/1000000:.1f}s'
    for name, val in SHUTTER_PRESETS.items():
        if abs(val - us) < 100:
            return f'{name} ({us}µs)'
    return f'1/{1000000//us} ({us}µs)'


def show_status(fd, unit_id):
    """Display current camera settings"""
    mode = get_value(fd, unit_id, SEL_EXP_MODE, 1)
    shutter = get_value(fd, unit_id, SEL_EXP_TIME, 2)
    bias = get_value(fd, unit_id, SEL_EXP_BIAS, 2)
    track_speed = get_value(fd, unit_id, SEL_TRACK_SPEED, 1)
    gestures = get_value(fd, unit_id, SEL_GESTURE, 1)
    func_status = get_value(fd, unit_id, SEL_FUNC_STATUS, 2)

    print('📷 Insta360 Link Status')
    print('─' * 30)

    if mode is not None:
        mode_name = EXP_MODES.get(mode, f'unknown({mode})')
        print(f'  Exposure Mode: {mode_name}')

    if shutter is not None:
        print(f'  Shutter Speed: {format_shutter(shutter)}')

    if bias is not None:
        print(f'  Exposure Bias: {bias - 256 if bias > 127 else bias}')

    if track_speed is not None:
        print(f'  Track Speed:   {TRACK_SPEEDS.get(track_speed, f"unknown({track_speed})")}')

    if gestures is not None:
        on = [name for bit, name in GESTURE_BITS.items() if gestures & bit]
        print(f'  Gestures:      {", ".join(on) if on else "none"} (0x{gestures:02x})')

    if func_status is not None:
        print(f'  Func Status:   0x{func_status:04x}')

    print()
    if mode != 1:
        print('ℹ️  Set mode to "manual" to control the shutter speed')


def main():
    parser = argparse.ArgumentParser(
        description='Control Insta360 Link camera via UVC Extension Units',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s                    Show current values
  %(prog)s mode manual        Enable manual exposure
  %(prog)s mode auto          Enable auto exposure
  %(prog)s shutter 1/60       Set shutter to 1/60s
  %(prog)s shutter 8000       Set shutter to 8000µs

Shutter presets: 1/30, 1/60, 1/125, 1/250, 1/500, 1/1000, 1/2000, 1/4000, 1/8000
''')

    parser.add_argument('control', nargs='?',
                        choices=['mode', 'shutter'],
                        help='Control to set')
    parser.add_argument('value', nargs='?',
                        help='Value to set')
    parser.add_argument('-d', '--device',
                        help='Video device path (auto-detected if not specified)')

    args = parser.parse_args()

    # Find device
    device = args.device or find_device()
    if not device:
        print('❌ Insta360 Link not found', file=sys.stderr)
        sys.exit(1)

    # Verify USB ID
    usb_ids = get_usb_ids(device)
    if usb_ids != INSTA360_LINK_USB_ID:
        print(f'⚠️  Device {device} is not Insta360 Link (USB ID: {usb_ids})', file=sys.stderr)

    # Find unit ID
    unit_id = find_unit_id(device)
    if unit_id == 0:
        print('❌ Could not find UVC Extension Unit', file=sys.stderr)
        sys.exit(1)

    # Open device
    try:
        fd = os.open(device, os.O_RDWR)
    except Exception as e:
        print(f'❌ Cannot open {device}: {e}', file=sys.stderr)
        sys.exit(1)

    try:
        # No args = show status
        if not args.control:
            show_status(fd, unit_id)
            return

        # Set control
        if args.control == 'mode':
            if args.value not in EXP_MODES_REV:
                print(f'❌ Invalid mode. Use: {list(EXP_MODES_REV.keys())}', file=sys.stderr)
                sys.exit(1)
            val = EXP_MODES_REV[args.value]
            if set_value(fd, unit_id, SEL_EXP_MODE, val, 1):
                print(f'✅ Exposure mode set to: {args.value}')
            else:
                print('❌ Failed to set exposure mode', file=sys.stderr)
                sys.exit(1)

        elif args.control == 'shutter':
            # Parse shutter value
            if args.value in SHUTTER_PRESETS:
                us = SHUTTER_PRESETS[args.value]
            else:
                try:
                    us = int(args.value)
                except ValueError:
                    print(f'❌ Invalid shutter. Use preset (1/60) or µs (16667)', file=sys.stderr)
                    sys.exit(1)

            if us < 100 or us > 33333:
                print(f'⚠️  Shutter {us}µs may be out of range (100-33333)', file=sys.stderr)

            # Check if in manual mode
            mode = get_value(fd, unit_id, SEL_EXP_MODE, 1)
            if mode != 1:
                print('⚠️  Camera not in manual mode, shutter may not take effect')

            if set_value(fd, unit_id, SEL_EXP_TIME, us, 2):
                print(f'✅ Shutter set to: {format_shutter(us)}')
            else:
                print('❌ Failed to set shutter', file=sys.stderr)
                sys.exit(1)

    finally:
        os.close(fd)


if __name__ == '__main__':
    main()
