#!/usr/bin/env python3
"""
Talk to the Insta360 Link Controller's own remote-control WebSocket.

The Windows app serves a phone remote (the QR code in its sidebar). That remote speaks
protobuf over a WebSocket, and its message set covers every feature the app has — including
the ones with no known UVC extension-unit selector, HDR among them.

Useful two ways:
  * drive a feature that Linux cannot reach natively yet
  * drive it while usbmon captures the bus, which reveals the XU selector behind it:
        sudo modprobe usbmon
        sudo sh -c 'timeout 120 cat /sys/kernel/debug/usb/usbmon/3u > cap.txt'
        ./insta360-ws.py --url '<qr url>' --set 26=1 --set 26=0
        ./usbmon-xu.py cap.txt --writes-only

The URL is the one behind the QR code, e.g.
  http://IP:62017/v3/link/?ip=IP&port=62016&token=TOKEN&language=English&version=2.2.4.14

Protocol recovered from the app's own web client bundle (umi chunk 226):

  Request                 ValueChangeNotification      UVCExtendRequest
   1 hasUvcRequest         1 curDeviceSerialNum (req)    1 curDeviceSerialNum (req)
   2 hasUvcExtendRequest   2 paramType (req)             2 paramType (req)
   3 hasSwitchDeviceReq    3 newValue (string)           3 selector (req)  <- the XU selector
   4 hasControlRequest     4 ptzParam                    4 repeated data
   5 hasHeartbeatRequest                                 5 presetPosIndex
   6 hasPresetUpdateReq   ControlRequest
   7 hasValueChangeNotify  1 token (req)
  10 uvcRequest           13 controlRequest
  11 uvcExtendRequest     14 heartbeatRequest
  12 switchDeviceRequest  15 presetUpdateRequest
                          16 valueChangeNotify
"""

import argparse
import base64
import os
import re
import socket
import struct
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

# ParamType, from the app's protobuf descriptor. See src/insta360.md.
PARAMS = {
    'mirror_ver': 1, 'mirror_hor': 2, 'reset_ptz': 3, 'zoom': 4, 'video_mode': 5,
    'ptz_mid': 6, 'ptz_op': 7, 'ptz_host': 8, 'track_speed': 9, 'composition_style': 10,
    'composition_style_switch': 11, 'auto_track': 12, 'single_tap_tracking': 13,
    'iso': 14, 'shutter': 15, 'exposure_compensation': 16, 'auto_exposure': 17,
    'auto_focus': 18, 'manual_focus_value': 19, 'auto_whitebalance': 20,
    'white_balance_temp': 21, 'brightness': 22, 'contrast': 23, 'saturation': 24,
    'sharpness': 25, 'hdr': 26, 'anti_flick': 27, 'blur_switch': 28, 'replace_switch': 29,
    'blur_radius': 30, 'blur_mode': 31, 'replace_index': 32, 'audio_capture_mode': 33,
    'smart_adjust': 34, 'privacy_mode': 35, 'roll_adjust': 36, 'lower_res': 37,
    'vertical_screen': 38, 'gesture_total_switch': 39, 'gesture_palm_switch': 40,
    'gesture_v_switch': 41, 'gesture_l_switch': 42, 'gesture_rock_switch': 43,
    'gesture_ok_switch': 44, 'host_ptz_info': 45, 'image_filter': 46, 'image_template': 47,
    'close_blur_replace': 48, 'video_privacy_mode': 49, 'fine_tuning': 50,
    'track_forbidden_area': 51, 'ver_screen_lock': 52,
    'roll': 100, 'pan_tilt_absolute': 101, 'pan_tilt_relative': 102, 'preset_position': 103,
    'bias': 104, 'change_device_name': 105, 'resolution': 106, 'imageparam_reset': 107,
    'save_imageparam_preset': 108,
}
PARAM_NAMES = {v: k for k, v in PARAMS.items()}


# --- protobuf ---------------------------------------------------------------

def varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7f
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def field(number, wire, payload):
    return varint((number << 3) | wire) + payload


def pb_bool(number, value):
    return field(number, 0, varint(1 if value else 0))


def pb_int(number, value):
    return field(number, 0, varint(value))


def pb_str(number, value):
    raw = value.encode()
    return field(number, 2, varint(len(raw)) + raw)


def pb_msg(number, payload):
    return field(number, 2, varint(len(payload)) + payload)


def read_varint(buf, i):
    value = shift = 0
    while True:
        byte = buf[i]
        value |= (byte & 0x7f) << shift
        i += 1
        shift += 7
        if not byte & 0x80:
            return value, i


def walk(buf):
    """Yield (field_number, wire_type, value) for one protobuf message."""
    i = 0
    while i < len(buf):
        try:
            tag, i = read_varint(buf, i)
            number, wire = tag >> 3, tag & 7
            if wire == 0:
                value, i = read_varint(buf, i)
            elif wire == 2:
                length, i = read_varint(buf, i)
                value, i = buf[i:i + length], i + length
            elif wire == 5:
                value, i = buf[i:i + 4], i + 4
            elif wire == 1:
                value, i = buf[i:i + 8], i + 8
            else:
                return
            yield number, wire, value
        except (IndexError, ValueError):
            return


# --- websocket (RFC 6455, only what this needs) ------------------------------

class WebSocket:
    def __init__(self, host, port, path):
        self.sock = socket.create_connection((host, port), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (f'GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n'
                   f'Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n'
                   f'Sec-WebSocket-Version: 13\r\n\r\n')
        self.sock.sendall(request.encode())
        header = b''
        while b'\r\n\r\n' not in header:
            chunk = self.sock.recv(1)
            if not chunk:
                raise ConnectionError('server closed during handshake')
            header += chunk
        if b'101' not in header.split(b'\r\n')[0]:
            raise ConnectionError('handshake refused: ' + header.split(b'\r\n')[0].decode())
        self.buf = b''

    def send(self, payload, opcode=0x2):
        header = bytearray([0x80 | opcode])
        mask = os.urandom(4)
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 1 << 16:
            header.append(0x80 | 126)
            header += struct.pack('>H', length)
        else:
            header.append(0x80 | 127)
            header += struct.pack('>Q', length)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def _recv_exact(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError('closed')
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self):
        first, second = self._recv_exact(2)
        opcode = first & 0x0f
        length = second & 0x7f
        if length == 126:
            length = struct.unpack('>H', self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack('>Q', self._recv_exact(8))[0]
        mask = self._recv_exact(4) if second & 0x80 else None
        payload = self._recv_exact(length)
        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return opcode, payload

    def close(self):
        try:
            self.send(b'', opcode=0x8)
        except OSError:
            pass
        self.sock.close()


# --- the client -------------------------------------------------------------

def request_control(token):
    return pb_bool(4, True) + pb_msg(13, pb_str(1, token))


def request_heartbeat():
    return pb_bool(5, True) + pb_msg(14, b'')


def request_value_change(serial, param, new_value):
    body = pb_str(1, serial) + pb_int(2, param) + pb_str(3, str(new_value))
    return pb_bool(7, True) + pb_msg(16, body)


def request_uvc_extend(serial, param, selector, data):
    body = pb_str(1, serial) + pb_int(2, param) + pb_int(3, selector)
    for byte in data:
        body += pb_int(4, byte)
    return pb_bool(2, True) + pb_msg(11, body)


# DeviceSettingInfo, from the app's own protobuf. Field number -> (name, kind).
SETTING_FIELDS = {
    1: ('composition_style', 'int'), 2: ('track_speed', 'int'), 4: ('auto_track', 'bool'),
    5: ('single_tap_tracking', 'bool'), 6: ('composition_style_enabled', 'bool'),
    9: ('hdr', 'bool'), 12: ('brightness', 'int'), 13: ('contrast', 'int'),
    14: ('saturation', 'int'), 15: ('sharpening', 'int'), 16: ('image_param_reset', 'bool'),
    17: ('auto_exposure', 'bool'), 18: ('iso', 'int'), 19: ('shutter', 'int'),
    20: ('exposure_compensation', 'int'), 21: ('auto_white_balance', 'bool'),
    22: ('white_balance', 'int'), 25: ('cur_image_param', 'int'), 26: ('cur_image_filter', 'int'),
    27: ('support_virtual_camera', 'bool'), 28: ('background_blur', 'bool'),
    29: ('background_replace', 'bool'), 31: ('support_blur_mode_list', 'int'),
    32: ('replace_index', 'int'), 34: ('anti_flicker', 'int'), 35: ('audio_capture_mode', 'int'),
    36: ('cur_blur_mode', 'int'), 37: ('smart_adjust', 'bool'), 38: ('privacy_mode', 'bool'),
    39: ('roll_adjust', 'bool'), 40: ('lower_res', 'bool'), 41: ('blur_radius', 'int'),
    42: ('gesture_enabled', 'bool'), 43: ('gesture_palm', 'bool'), 44: ('gesture_v', 'bool'),
    45: ('gesture_l', 'bool'), 46: ('gesture_rock', 'bool'), 47: ('gesture_ok', 'bool'),
    48: ('auto_focus', 'bool'), 49: ('manual_focus', 'int'), 50: ('vertical_screen', 'bool'),
    51: ('video_privacy_mode', 'bool'), 52: ('resolution', 'str'),
    53: ('fine_tuning', 'float'), 54: ('ver_screen_lock', 'bool'),
    55: ('track_forbidden_area', 'bool'),
}

# DeviceBasicInfo
BASIC_FIELDS = {1: ('device_name', 'str'), 2: ('serial', 'str'), 3: ('camera_type', 'int'),
                4: ('video_mode_type', 'int'), 7: ('cur_preset_pos', 'int'),
                8: ('vertically_mirror', 'bool'), 9: ('horizontally_mirror', 'bool')}


def render(number, wire, value, table):
    name, kind = table.get(number, (f'field_{number}', 'raw'))
    if wire == 0:
        return name, (bool(value) if kind == 'bool' else value)
    if kind == 'str':
        return name, value.decode(errors='replace')
    if kind == 'float' and len(value) == 4:
        return name, round(struct.unpack('<f', value)[0], 3)
    return name, value.hex()


def dump_device_info(payload, seen):
    """DeviceInfoNotification -> repeated DeviceBasicInfo(1) -> DeviceSettingInfo(10)."""
    for number, wire, value in walk(payload):
        if number != 1 or wire != 2:
            continue
        for bnum, bwire, bval in walk(value):
            if bnum == 10 and bwire == 2:
                for snum, swire, sval in walk(bval):
                    name, shown = render(snum, swire, sval, SETTING_FIELDS)
                    seen[name] = shown
            elif bnum == 5 and bwire == 2:
                zoom = {n: v for n, w, v in walk(bval) if w == 0}
                seen['zoom'] = f"{zoom.get(1)} of {zoom.get(2)}-{zoom.get(3)}"
            else:
                name, shown = render(bnum, bwire, bval, BASIC_FIELDS)
                seen[name] = shown


def dump_value_change(payload):
    param = new_value = None
    for number, wire, value in walk(payload):
        if number == 2 and wire == 0:
            param = value
        elif number == 3 and wire == 2:
            new_value = value.decode(errors='replace')
    if param is not None:
        return PARAM_NAMES.get(param, f'param_{param}'), new_value
    return None, None


def describe(payload):
    """Cheap human summary of a notification frame."""
    parts = []
    for number, wire, value in walk(payload):
        if wire == 2 and value:
            strings = re.findall(rb'[\x20-\x7e]{4,}', value)
            inner = ' '.join(s.decode() for s in strings[:6])
            parts.append(f'f{number}={inner}' if inner else f'f{number}=<{len(value)}B>')
        elif wire == 0:
            parts.append(f'f{number}={value}')
    return ', '.join(parts)[:300]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', required=True, help='the URL behind the QR code')
    ap.add_argument('--serial', default='', help='camera serial, read from the app if omitted')
    ap.add_argument('--set', action='append', default=[], metavar='PARAM=VALUE',
                    help='set a ParamType, by name or number, e.g. --set hdr=1 --set 26=0')
    ap.add_argument('--gap', type=float, default=4.0, help='seconds between --set actions')
    ap.add_argument('--listen', type=float, default=6.0, help='seconds to listen before acting')
    ap.add_argument('--list-params', action='store_true')
    ap.add_argument('--dump-state', action='store_true',
                    help='decode the app\'s notifications instead of printing raw frames')
    args = ap.parse_args()

    if args.list_params:
        for name, number in sorted(PARAMS.items(), key=lambda kv: kv[1]):
            print(f'  {number:>3}  {name}')
        return 0

    query = parse_qs(urlparse(args.url).query)
    host = query.get('ip', [urlparse(args.url).hostname])[0]
    port = int(query['port'][0])
    token = query['token'][0]

    ws = WebSocket(host, port, f'/?token={token}')
    print(f'connected to ws://{host}:{port}')
    state, changes = {}, {}

    serial = args.serial
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                opcode, payload = ws.recv()
            except (ConnectionError, OSError):
                return
            if opcode == 0x8:
                print('<< server closed')
                return
            nonlocal serial
            if args.dump_state:
                fields = {n: v for n, w, v in walk(payload) if w == 2}
                if 10 in fields:                       # deviceInfoNotify
                    dump_device_info(fields[10], state)
                    if not serial:
                        serial = state.get('serial', '')
                if 11 in fields:                       # valueChangeNotify
                    name, value = dump_value_change(fields[11])
                    if name and value is not None:
                        changes[name] = value
                continue
            if not serial:
                for match in re.findall(rb'[A-Z0-9]{12,20}', payload):
                    text = match.decode()
                    if text.startswith('IB') or text.isalnum() and len(text) >= 14:
                        serial = text
                        print(f'<< learned serial {serial}')
                        break
            print(f'<< {describe(payload)}')

    threading.Thread(target=reader, daemon=True).start()

    ws.send(request_control(token))
    print('>> control(token)')
    deadline = time.time() + args.listen
    while time.time() < deadline and not serial:
        time.sleep(0.2)
    time.sleep(max(0, deadline - time.time()))

    if not serial:
        print('no serial seen, pass --serial explicitly', file=sys.stderr)

    for action in args.set:
        name, _, value = action.partition('=')
        param = PARAMS.get(name.strip()) if not name.strip().isdigit() else int(name)
        if param is None:
            print(f'unknown param {name!r}, try --list-params', file=sys.stderr)
            continue
        ws.send(request_value_change(serial, param, value.strip()))
        print(f'>> valueChange {PARAM_NAMES.get(param, param)} ({param}) = {value.strip()}')
        end = time.time() + args.gap
        while time.time() < end:
            ws.send(request_heartbeat())
            time.sleep(min(2.0, max(0.1, end - time.time())))

    time.sleep(1.5)
    stop.set()
    ws.close()

    if args.dump_state:
        print(f'\n=== device state, {len(state)} fields the app tracks ===')
        for name in sorted(state):
            print(f'  {name:<28} {state[name]}')
        if changes:
            print(f'\n=== valueChange notifications, {len(changes)} parameters ===')
            for name in sorted(changes):
                print(f'  {name:<28} {changes[name]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
