# Insta360 Link UVC Extension Unit Research

## Device Info
- **USB ID**: `2e1a:4c01`
- **Model**: IBJLA23066B543
- **Firmware**: v1.4.5.8_build1
- **Serial**: 13B586099180472

## 🎛️ 2026-09-19 — WHAT HANDS-ON TESTING CHANGED

- **0x1b bit 0x0400 is portrait/landscape**, not single tap tracking. See the correction
  above; it is the one finding that timestamp correlation got wrong.
- **The gimbal does not move without a live stream.** The 0x16 write is accepted and reads
  back, the camera stays still.
- **Hue is accepted and ignored** by this firmware. Full ±15 moves mean RGB by about 1.
- **The gimbal coasts about 6° after a stop**, measured as pan 60480 → 81720 arc-seconds in
  the 1.5s after the stop write, then holding.
- **V4L2 pan_speed and tilt_speed are dead on this camera**: advertised, zero range, EIO on
  write. cameractrls now drops them when the Insta360 controls load.

## 🔌 THE CAMERA VANISHES WHEN THE MONITOR IS OFF

On this machine the camera hangs off a USB hub inside the monitor, so **switching the
monitor off unpowers the hub and the camera leaves the bus entirely**. Every hub in the
chain disappears with it:

    2109:2817 VIA hub, 05e3:0610 Genesys, 2109:8883 billboard, 2109:0817, 05e3:0625

It looks exactly like a camera fault, and it was misdiagnosed twice in one day. Tell them
apart before blaming firmware:

- `lsusb -d 2e1a:4c01` empty **and** the hubs above also missing → the monitor is off.
  Nothing to fix, power it back on.
- Camera missing but the hubs still present → a real device problem, usually a
  re-enumeration after writing 0x1b bit 0x20, which resolves itself.
- Camera present but `/dev/video0` missing, interfaces bound to `usbfs` → a VM passthrough
  detach that did not restore the driver. Replug, or
  `echo 3-1.4 | sudo tee /sys/bus/usb/drivers/usb/unbind` then the same to `bind`.

## ⚠️ XU writes only stick while the camera is streaming

Reported in [cameractrls issue #55](https://github.com/soyersoyer/cameractrls/issues/55)
for this exact camera: written at idle, an XU control is accepted, `GET_CUR` echoes the
new value, and about a second later the firmware silently reverts it. No error at any point.

**Every "read-only" / "doesn't accept changes" verdict in this file that was taken without
a capture running is suspect** and needs re-testing with e.g. `ffmpeg -f v4l2 -i <dev>`
in the background. The exposure results below were taken with a preview open, so those hold.

## Extension Units Found

| Unit | GUID | Controls |
|------|------|----------|
| 9 | `faf1672d-b71b-4793-8c91-7b1c9b7f95f8` | 22 controls (main) |
| 10 | `e307e649-4618-a3ff-82fc-2d8b5f216773` | 6 controls |
| 11 | `a8bd5df2-1a98-474e-8dd0-d92672d194fa` | 5 controls |

---

## ✅ CONFIRMED WORKING

### 0x1e - Exposure Mode (1 byte)
- **0** = Auto mode variant (observed exp ~1000µs)
- **1** = Manual exposure (0x19 controls shutter)
- **2** = Auto exposure (default)
- **3** = Auto with faster shutter bias? (observed exp ~200µs)
- **4** = Auto with slower shutter bias? (observed exp ~4700µs)
- **5** = Similar to mode 3 (observed exp ~200µs)
- **All modes accept and stick** ✅
- **Status**: ✅ Fully working, mode differences need visual confirmation

### 0x19 - Exposure Time (2 bytes, little-endian)
- **Unit**: Microseconds (µs)
- **Range**: ~100 - 33333 µs
- **Only works when 0x1e = 1 (manual mode)**
- **Common values**:
  - 33333 µs = 1/30s (brightest, 30fps limit)
  - 16667 µs = 1/60s
  - 8000 µs = 1/125s
  - 4000 µs = 1/250s
  - 2000 µs = 1/500s
  - 1000 µs = 1/1000s
  - 500 µs = 1/2000s
  - 100 µs = 1/10000s (darkest)
- **Status**: ✅ Fully working

### 0x1b - Function Status Bitmask (2 bytes, little-endian) — **NOT gain**
- **Corrected 2026-08-20**: this is `XU_FUNC_STATUS_CONTROL`, a feature bitmask, not gain/ISO.
- Confirmed by cameractrls [PR #101](https://github.com/soyersoyer/cameractrls/pull/101)
  (Link 2 family) and by reading it here: current value **16 = 0x10**, the
  "gestures enabled" bit, consistent with 0x05 reading 0x0E (all three gestures on).
- **This explains the crashes**: writing 200 didn't set an out-of-range gain, it set
  a pile of unrelated feature bits at once, and the firmware fell over.
- **Do not write raw values to 0x1b.** Flip single bits only.
- **Status**: ✅ Identified, handled by `Insta360Ctrls` (gesture-all bit only)

### 0x07 - Unknown Toggle (1 byte)
- **Values**: 0 or 1
- **Default**: 1
- **Can toggle**: ✅ Yes, both values stick
- **Visual effect**: Unknown - no obvious change
- **Might be**: HDR? Some processing toggle?
- **Status**: ✅ Settable, effect unknown

---

## 🔍 NEEDS MORE TESTING

### 0x1d - Unknown (2 bytes)
- Observed values: 29, 33
- **Tested**: Setting different values, readback always same
- **Status**: ❌ Read-only (doesn't accept changes)

### 0x05 - Gesture Bitmask (1 byte) — identified
- **Corrected 2026-08-20**: `XU_GESTURE_STATUS_CONTROL`, per PR #101:
  `0x02` = palm (tracking on/off), `0x04` = L (zoom), `0x08` = V (whiteboard).
- Reads **14 = 0b1110** here, i.e. all three gestures enabled.
- The earlier "readback stays 0" verdict was almost certainly taken **at idle** —
  see the streaming caveat below.
- **Status**: ✅ Identified, exposed as three booleans

### 0x11 - Possibly Gesture Control (1 byte)
- Default: 0
- Setting to 1 caused protocol error
- **Status**: ❌ Not settable

### 0x12 - Tracking Speed (1 byte) — identified
- **Corrected 2026-08-20**: `XU_TRACK_SPEED_CONTROL`, per PR #101: 1 = slow, 2 = medium, 3 = fast.
- Reads **1** here (slow), not 0 as noted earlier.
- **Status**: ✅ Identified, write effect not yet verified

### 0x13 - Unknown Toggle (1 byte)
- Default: 1
- **Tested**: Setting to 0, readback stays 1
- **Status**: ❌ Read-only

### 0x09 - Exposure Bias (2 bytes) — identified
- **Corrected 2026-08-20**: `XU_EXPOSURE_VALUE_CONTROL`, per PR #101.
- **The reported -4..+4 range is wrong.** The real unit is **0.01 EV** and the usable
  range is **±300 = ±3.00 EV**, confirmed by luminance sweep — see the test log below.
- Matches the "Exposure Compensation ±3 EV" row in the Windows feature table below.
- **Status**: ✅ Confirmed working on gen 1

### 0x15 - Unknown (8 bytes)
- Value: all zeros
- Might be preset position storage
- **Status**: Not tested

### 0x1a - Pan/Tilt Related? (8 bytes)
- Contains 2x 32-bit signed values
- Observed: -290880, -16200
- **Arc-seconds conversion**: -290880/3600 = -80.8°, -16200/3600 = -4.5°
- V4L2 pan/tilt use same arc-seconds unit but different values observed
- Might be internal gimbal position vs commanded position?
- **Status**: Not tested

---

## ❌ READ-ONLY / INFO SELECTORS

### 0x03 - Device Info (170 bytes)
- Contains: Serial, firmware version, etc.

### 0x0b - Unknown (5 bytes)
- Read-only

### 0x0c - Model ID (32 bytes)
- Contains: "IBJLA23066B543"

---

## Extension Unit 10 (6 controls)

| Selector | Size | RW | Value | Notes |
|----------|------|-----|-------|-------|
| 0x01 | 8B | RO | `01 00 00 00 00 00 00 00` | Status? |
| 0x03 | 10B | RW | all zeros | Preset slot 1? |
| 0x04 | 10B | RW | all zeros | Preset slot 2? |
| 0x05 | 10B | RW | all zeros | Preset slot 3? |
| 0x06 | 1B | RW | 255 (0xff) | Doesn't accept changes |

---

## Extension Unit 11 (5 controls)

| Selector | Size | RW | Value | Notes |
|----------|------|-----|-------|-------|
| 0x01 | 1B | RO | 1 | Status? |
| 0x02 | 1B | RW | 0 | Toggle, accepts 0/1, effect unknown |
| 0x03 | 1B | RO | 6 | Status/mode indicator? |
| 0x04 | 1B | RW | N/A | Can't read |
| 0x05 | 1B | RW | N/A | Can't read |

---

## 🐛 ISSUES ENCOUNTERED

1. **Camera crashes/disconnects** when setting certain 0x1b (gain) values
2. **Timeout errors** on some write operations
3. **Device path changes** after crash (/dev/video0 → video2, etc.)
4. Use stable path: `/dev/v4l/by-id/usb-Insta360_Insta360_Link-video-index0`

---

## 🧪 TEST LOG 2026-08-20 — writes with a stream running

Method: `ffmpeg` capturing 1280x720 MJPEG throughout, frames downscaled to 32x18 gray
at 4 fps, mean/stddev/percentiles per phase. Every selector restored afterwards.

### Confirmed working

| Selector | Test | Result |
|---|---|---|
| 0x12 tracking speed | wrote 3, then 2 | **sticks** at +0.2s / +1s / +3s, no revert |
| 0x1e exposure mode | wrote 1 (manual) | **sticks** |
| 0x19 exposure time | 33333 µs (1/30s) | luminance 98.6 → **111.6** ✅ |
| 0x19 exposure time | 250 µs (1/4000s) | luminance → **3.2** ✅ |

The revert-at-idle behaviour described in issue #55 **did not occur once** while streaming.

### Negative results

### 0x09 exposure bias — WORKS, the first test just used the wrong scale

An initial sweep of -4..+4 moved nothing, because **the unit is 0.01 EV**: ±4 raw is
±0.04 EV, far inside the noise. GET_MIN/GET_MAX report -4/+4, which is neither the range
nor the unit — ignore them on this firmware. Swept properly against frame luminance:

| 0x09 | -300 | -200 | -100 | -50 | 0 | +50 | +100 | +200 | +300 |
|---|---|---|---|---|---|---|---|---|---|
| luminance | 50.4 | 43.4 | 77.4 | 91.0 | 98.7 | 105.0 | 105.3 | 105.2 | 105.0 |

Monotonic downwards, and flat above +50 only because the test scene was dim and the
sensor had no headroom left — a scene limit, not a protocol one. **±300 = ±3.00 EV**,
matching the Windows slider exactly. The app moves in 0.3 EV steps, i.e. 30 raw units.

**0x07 — not HDR, or not measurably so.** Wrote 0 and 1, six seconds each: mean 100.1 /
100.1, stddev 55.6 / 55.4, p5 19 / 19, p95 224 / 224. Identical. A fair caveat: HDR may
need a high-dynamic-range scene (bright window plus dark room) to show up at all, and the
test scene was evenly lit.

### 0x10 — the exposure curve LUT, read-only in practice

Structure decoded: **1 header byte + 127 × u16 little-endian at offset 1**, values
`0, 0, 4, 8, 12, … 496, 500` — a constant step of 4, i.e. a **linear identity ramp**,
which is exactly the straight diagonal the "Exposure curve" widget shows in the screenshots.

Writes do not take. A scaled curve (×0.4) and a gamma curve with endpoints preserved were
both **silently reverted** — GET_CUR returns the identity ramp again within half a second,
and luminance never moved. Only a byte-identical rewrite of the identity ramp "echoes".

Note the Windows app keeps its curve **host-side** as normalised control points in
`Documents/Insta360/Webcam-desktop/<serial>/<serial>_curve.json`
(`curve_info: [{x:0,y:1},{x:1,y:0}]`), which fits: the curve is applied in the app's
virtual-camera pipeline, not pushed into the firmware.

### Other selectors decoded

| Sel | Decoding | Value seen |
|---|---|---|
| 0x1a | 2 × int32 LE, arc-seconds | -291240, -11880 = **-80.9°, -3.3°** — gimbal pan/tilt position ✅ |
| 0x14 | volatile | 17 nonzero bytes on one read, 240 zeros on the next — telemetry, not a setting |
| 0x0f | 6 × u16 LE | 0, 1108, 724, 3276, 705, 3041 |
| 0x18 | 2 × u16 LE | 48, 2643 |
| 0x16 | 2 × u16 LE | 768, 768 |

### Still needs a human

Tracking speed semantics (Quick/Ordinary/Slow is a rate, invisible in a frame) and the
gesture bits (someone has to perform a palm / L / V in front of the lens).

## 📜 THE WINDOWS APP LOG IS A PROTOCOL ORACLE

`/mnt/winos/Users/DanielSrb/AppData/Local/Insta360/Insta360 Link Controller/log/2025_12_10/19_25_39.log`
is the session in which the screenshots were taken, and it names what the app reads and
writes over the extension unit. Grep it with `grep -a` — it contains NUL bytes, so plain
grep silently treats it as binary and finds nothing.

What it establishes:

- `camera_image_param.cc: get Exposure Compensation from uvc_extend: 0` — **exposure
  compensation is a camera XU value on gen 1**, not a host-side effect.
- `set compensation: -0.3 / -0.6 / -0.9 / -1.2 / -1.5` — the app works in **EV floats,
  0.3 EV per slider step**, which pins the raw unit at 0.01 EV given the ±300 range.
- `get iso from uvc_extend: 770 / 814 / 818 / 938 / 100` and `set iso to 800 / 1000 /
  3200` — **an ISO selector exists on gen 1 and is still unfound.** The odd read values
  look like the AE's actual ISO, the set values are the slider positions.
- `set shutter to 30 / 50 / 80 / 240 / 1250 / 8000` — the app's shutter unit is the
  **denominator** (1/30s … 1/8000s), while selector 0x19 takes **microseconds**.
- `spline_manager.cc: reset exposure curve clicked!`, `begin add point, x: 203.582,
  y: 23.138`, `axis w: 238, h: 160` — the curve is edited in **widget pixel coordinates**
  and stored host-side, consistent with 0x10 rejecting writes.
- `set auto exposure: 0/1`, `set white balance to`, `set brightness/contrast/saturation`,
  `set sharpening_level`, `set AF`, `set Manual Focus` — the rest of the Effects tab.

Anything still unmapped should be looked for here first: turn the knob in the app on
Windows, then read the log line it produced.

## 📡 2026-08-23 — DRIVING THE VENDOR APP FROM LINUX, AND WHAT IT REVEALED

The Windows app has a phone remote behind a QR code. It is protobuf over a WebSocket, and
reimplementing it turned the whole problem around: instead of guessing selectors, ask the
app to perform a feature and read the selector off the bus.

### Setup

Windows 11 in libvirt with the camera passed through (`virsh attach-device`), the app
running inside, and `usbmon` capturing bus 3 on the **host** — QEMU passes USB through
usbfs, so every control transfer still crosses the host kernel and is visible.

  sudo modprobe usbmon
  sudo sh -c 'setsid timeout 240 cat /sys/kernel/debug/usb/usbmon/3u > cap.txt &'
  ./insta360-ws.py --url '<qr url>' --set hdr=1 --set video_mode=2 ...
  ./usbmon-xu.py cap.txt --writes-only --unit 9

### The protocol, from the app's own web bundle

The client is served at `http://IP:62017/v3/link/` and its chunk 226 carries the generated
protobuf. The socket is `ws://IP:62016?token=<token>`, first message
`Request{hasControlRequest, controlRequest{token}}`, heartbeat every 10s.

| Request | | ValueChangeNotification | | UVCExtendRequest | |
|---|---|---|---|---|---|
| 4 | hasControlRequest | 1 | curDeviceSerialNum | 1 | curDeviceSerialNum |
| 7 | hasValueChangeNotify | 2 | paramType | 2 | paramType |
| 13 | controlRequest | 3 | newValue (string) | 3 | **selector** |
| 16 | valueChangeNotify | 4 | ptzParam | 4 | repeated data |

`insta360-ws.py` implements this in the standard library, WebSocket framing included, and
can set any of the 61 ParamTypes by name. Confirmation that the enum extraction was right:
the client sends `paramType:103` for preset save/switch, exactly PARAM_PRESET_POSITION.

### 🎯 HDR found, plus two more, all in the 0x1b word

26 features were driven three seconds apart. Lining the sends up against the capture:

| Sent over the WebSocket | On the wire |
|---|---|
| `hdr=0` | `0x1b` ← `0x0010` |
| `hdr=1` | `0x1b` ← `0x0014` |
| `video_mode=2` | `0x02` ← `02` + 31 zero bytes |
| `video_mode=3` | `0x02` ← `03` + 31 zero bytes |
| `auto_track=1` | `0x1b` ← `0x0114` |
| `composition_style_switch=1` | `0x1b` ← `0x0115` |
| `composition_style_switch=0` | `0x1b` ← `0x0114` |
| `anti_flick=0/1` | unit **5** selector 0x05 — the standard UVC power line frequency |

So the function bitmask at 0x1b holds:

| Bit | Meaning |
|---|---|
| **0x0001** | **Smart Composition** |
| **0x0004** | **HDR** |
| 0x0010 | gestures master switch |
| **0x0100** | **AI Tracking** |
| 0x0020 | **do not touch, drops the camera off the bus** |

HDR was under our nose the whole time: the daylight bit sweep found 0x04 "sticks, no
dynamic-range change" — because a flat, evenly lit room has no dynamic range for HDR to
compress. Luminance testing could never have identified it. The vendor protocol could.

`video_mode` writes its value as the first byte of a 32-byte payload at 0x02, so the four
bottom-bar modes are one small struct away, not a mystery any more.

Toggles that produced **no** unit 9 traffic at all: mirror horizontal and vertical,
smart adjustment, fine tuning, `gesture_rock_switch`, `gesture_ok_switch`, `lower_res`.
Either the app handles them host-side, or the gen 1 Link does not implement them — the two
extra gestures are most likely Link 2 features.

## 🕹️ GIMBAL SPEED, VIDEO MODES AND THE CURVE (2026-08-23)

Captured with `usbmon-bin.py` while the user drove the vendor app's own controls, so these
are full payloads rather than the 32 byte truncations the text interface gives.

### Correction 2026-09-19: 0x1b bit 0x0400 is portrait, not single tap tracking

Hands-on testing showed bit 0x0400 **switches the image between portrait and landscape**.
It was originally labelled Single Tap Tracking, from lining up send timestamps against the
capture — the arithmetic put the write next to a `single_tap_tracking` send, and nothing in
the bus trace contradicted it.

The lesson for the rest of this file: **timestamp correlation names a bit, it does not prove
what the bit does.** Bits confirmed only that way are worth re-checking by hand. The ones
verified by watching the image or the gimbal — HDR, privacy, high frame rate, AI tracking,
gestures — are not affected.

Note the camera therefore has two separate portrait concepts: bit 0x0020 makes portrait
*resolutions* available and re-enumerates, while bit 0x0400 switches the current image
orientation.

### 0x16 XU_PANTILT_RELATIVE — continuous gimbal movement ✅

Four bytes, `[pan sign, pan magnitude, tilt sign, tilt magnitude]`:

| Captured | Meaning |
|---|---|
| `ff 08 00 01` | pan left, magnitude 8 |
| `01 04 00 01` | pan right, magnitude 4 |
| `00 01 ff 08` | tilt down, magnitude 8 |
| `00 01 01 08` | tilt up, magnitude 8 |
| `00 01 00 01` | **stop** — the app's idle encoding, magnitude 1 with sign 0 |

Sign `0x01` is right/up, `0xff` is left/down. Magnitudes up to 30 were seen. Verified on the
device: a 2 second burst at magnitude 8 swung the gimbal about 40°, and driving the opposite
sign brought it back.

**This is the gap the old notes flagged since day one.** The V4L2 `pan_speed` and `tilt_speed`
controls exist on this camera but return EIO, so continuous movement was impossible from
Linux. Exposed as `insta360_pan_speed` / `insta360_tilt_speed`, flagged `zeroer` so letting go
stops the gimbal.

Note the field order in 0x1a: the **second** int32 is pan, the first is tilt, confirmed by
matching against V4L2 `pan_absolute`.

### 0x02 XU_VIDEO_MODE — the four bottom-bar modes ✅

The mode id rides in byte 0 of the 52 byte struct. Clicking through the app's buttons twice:

| Id | Mode |
|---|---|
| 0 | normal, also written when leaving any mode |
| 4 | Whiteboard |
| 5 | Overhead |
| 6 | DeskView |

Id 1 appeared once, unidentified. This matches an earlier native probe where 5 was the only
id to visibly transform the image — Overhead points the camera at the desk. Whiteboard and
DeskView refuse unless the scene suits, which the app's own error strings confirm.

### 0x10 XU_EXPOSURE_CURVE — chunked, and it does work ✅

Every single-shot write was rejected because the curve arrives in **three chunks**:

    byte 0      start index: 0, then 126, then 252
    u16[0]      2 while more chunks follow, 1 on the last
    u16[1..126] up to 126 curve points, 10 bit, little endian

256 points spanning 0-1023. `GET_CUR` only ever returns the chunk written last, so the curve
**cannot be read back** — the control is flagged `unrestorable` and always reports linear.

Measured with a gamma 2.2 curve versus gamma 0.5, same scene:

| Curve | mean | p5 | p95 |
|---|---|---|---|
| baseline | 131.5 | 43 | 197 |
| gamma 2.2 | 128.5 | **31** | 198 |
| gamma 0.5 | 139.8 | **47** | 197 |

Shadows move, highlights hold — exactly what a tone curve should do. Offered as five
presets rather than a 256 point editor. The vendor's own default is a linear ramp, and the
three writes that produce it are in `xu3.txt` if it ever needs restoring byte for byte.

## 🎬 60 FPS AND PORTRAIT, UNLOCKED (2026-08-23)

The app's Compatibility Settings checkbox writes **bit 0x0020 of 0x1b**, captured while the
user ticked it. Doing the same from Linux changes what the camera advertises:

| | bit clear | bit set |
|---|---|---|
| MJPG / H264 1920x1080, 1920x1440, 1280x720, 1280x960 | 30, 25, 24 | **60, 50**, 30, 25, 24 |
| MJPG / H264 3840x2160 | 30, 25, 24 | 30, 25, 24 (unchanged) |
| **1080x1920, 1088x1920, 736x1280** portrait | absent | **60, 50, 30, 25, 24** |

Ten format combinations become sixteen, and every non-4K mode gains 50 and 60 fps. 4K stays
at 30, which matches the app's own HDR note about 4K and 50/60fps being exclusive.

Exposed as `insta360_high_framerate`, flagged `reopener` because the device re-enumerates —
anything already capturing loses the handle. Clearing the bit restores the original list.

### What else the checkbox capture showed

- **0x10 XU_EXPOSURE_CURVE is writable after all.** The app sent three curve writes, the
  first starting `00 02 00 00 00 04 00 08 00 0c ...`. Our own writes were rejected, so the
  payload needs a header or a framing we got wrong — not a read-only register.
- **0x04 XU_PTZ_CMD_CONTROL** takes a 32-byte command, seen as
  `a5 d0 03 00 f1 32 00 ...` — the gimbal command channel, still unmapped.
- Ticking the checkbox also drove unit 5 selector 0x05 (power line frequency) and three
  short writes to 0x02, so the app reconfigures more than the one bit.

## 🗂️ THE COMPLETE FEATURE LIST, READ OUT OF THE APP

`insta360-ws.py --dump-state` decodes the app's `DeviceInfoNotification`, which carries a
`DeviceSettingInfo` — the app's own state model for the attached camera. This is the
authoritative answer to "what can this camera do", straight from the vendor:

    anti_flicker 1          auto_exposure True      auto_focus True     auto_track True
    auto_white_balance True brightness 50           composition_style 1 contrast 50
    exposure_compensation 0 fine_tuning 0.0         gesture_enabled True
    gesture_palm True       gesture_l True          gesture_v True
    gesture_ok False        gesture_rock False      hdr True
    horizontally_mirror F   vertically_mirror F     iso 2               shutter 0
    lower_res False         manual_focus 0          privacy_mode False
    resolution horizontal   saturation 50           sharpening 50
    single_tap_tracking F   smart_adjust False      support_virtual_camera False
    track_forbidden_area F  track_speed 1           ver_screen_lock False
    vertical_screen False   video_privacy_mode F    white_balance 6300
    zoom 100 of 100-400     device_name Link-66B543 cur_preset_pos -1

Two things worth noting. `gesture_ok` and `gesture_rock` **exist as fields** for this camera
but driving them produced no extension-unit traffic, so the app tracks them while the gen 1
firmware ignores them. And `iso: 2` / `shutter: 0` are **slider indices**, not the raw values
the XU takes — the app converts.

The device message also carries ten fields (56-65) that the app's own web client does not
decode. Field 59 holds ascii-ish data including a colour, field 57 and 58 look like repeated
int32 lists padded with -1, plausibly preset slots. Unexplored.

### The selector map, confirmed by a second independent build

The VM runs app 2.2.4.14, the installed one is 2.0.6.2. **Every selector we rely on matches
across both builds** — in fact the whole enum does, see the correction dated 2026-09-19 at
the end of this file; the "no aliases in the newer build" claim here was an artifact of
reading the enum out of the web bundle instead of the exe. The selectors: GESTURE_STATUS 5, NOISE_CANCEL 7, EXPOSURE_VALUE 9, DEVICE_SN
12, TRACK_SPEED 18 (0x12), LAYOUT_STYLE 19 (0x13), BIAS 24 (0x18), ISO 25 (0x19),
PANTILT_ABSOLUTE 26 (0x1a), FUNC_ENABLE 27 (0x1b), VIDEO_RES 28 (0x1c),
EXPOSURE_TIME_ABSOLUTE 29 (0x1d), AE_MODE 30 (0x1e).

The newer build dropped BLEND_DRAW, AF_MODE and EXPOSURE_CURVE, which were the aliases at 8,
15 and 16 — consistent with the exposure curve living at 0x10 alongside UPLOAD_FILE.

## 🙋 TEST LOG 2026-08-21, WITH A HUMAN IN FRAME

The three things no measurement could settle, done with the user in front of the lens and a
live ffplay preview keeping the stream up.

### Gestures 0x05 — confirmed by A/B ✅

| Step | Mask | Palm gesture |
|---|---|---|
| baseline | 0x0e | **fires**, AI tracking switched on |
| palm bit cleared | 0x0c | **ignored** |
| palm bit restored | 0x0e | **fires** again |

So bit 0x02 of 0x05 really is the palm gesture, and it is independently addressable — the
mask is not a global on/off. The L gesture was confirmed working with all bits restored, but
**not** during the palm-off window, so L=0x04 and V=0x08 stay inferred from PR #101 rather
than verified here.

### Tracking speed 0x12 — confirmed by blind A/B ✅

Values presented without telling the user which was which:

| Setting | Value | User's read |
|---|---|---|
| A | 3 | "tracking speed fast seems" |
| B | 1 | "this is slower then before" |

PR #101's mapping is right: **1 slow, 2 medium, 3 fast**, which the vendor labels Slow,
Ordinary and Quick.

### Composition 0x13 — direction confirmed, effect is weak ⚠️

Blind again: 3 first, then 1.

| Value | User's read |
|---|---|
| 3 | "willing to show more of my body" |
| 1 | "probably yes [tighter], but still doesn't zoom as much when I am more far away" |

So 1 = Head, 2 = Half Body, 3 = Whole Body, matching the vendor labels, and the direction is
real. **The effect is subtle and does not tighten much at distance** — and the user reports
the same weakness in the Windows app, so this is firmware behaviour, not something missing
on the Linux side. Worth saying plainly to anyone who tries this control and expects a hard
crop.

## ☀️ TEST LOG 2026-08-21, DAYLIGHT

Same method as the night run, `daylight-probe.py`, camera streaming 720p30 throughout.

### Exposure compensation 0x09 — the positive half works, it was scene-limited

| 0x09 | +150 (+1.50 EV) | +300 (+3.00 EV) |
|---|---|---|
| mean | 182.2 | 222.4 |
| p5 | 63 | 124 |

Against a ~133 baseline. At night the positive half looked dead because the sensor had no
headroom left, exactly as suspected — not a firmware limit. ✅

### ISO ladder 0x19 at 1/60s

| ISO | 100 | 200 | 400 | 800 | 1600 | 3200 |
|---|---|---|---|---|---|---|
| mean | 51.1 | 74.5 | 109.1 | 152.6 | 193.9 | 219.5 |

Monotonic, compressing at the top as the frame clips. ✅

### Shutter ladder 0x1d at ISO 400 — textbook halving

| shutter | 1/30 | 1/60 | 1/125 | 1/250 | 1/500 | 1/1000 | 1/2000 | 1/4000 | 1/8000 |
|---|---|---|---|---|---|---|---|---|---|
| mean | 148.4 | 108.3 | 70.2 | 43.9 | 28.5 | 15.5 | 8.9 | 4.6 | 2.5 |

Roughly halves per stop across nine stops. Readback quantises only at the slow end,
30 → 29 and 60 → 59, the rest are exact. ✅

### 0x1b bit 0x20 — read as a crash, actually a feature (corrected 2026-08-23)

**This section's original conclusion was wrong and is kept for the reasoning.** Bit 0x20 is
the vendor app's "Portrait Resolution and High Frame rate" toggle. Setting it makes the
camera **re-enumerate on the USB bus**, which is exactly what a device advertising a new
descriptor set must do — the probe saw the disconnect and called it a crash. Writes issued
while the device is re-enumerating fail with EPROTO, which looked like a bricked register.
It round-trips cleanly from Linux in both directions. See the daylight section below.

Sweeping the function bitmask one bit at a time:

| bit | result |
|---|---|
| 0x01 | sticks, no dynamic-range change |
| 0x02 | **rejected**, readback never shows it |
| 0x04 | sticks, no dynamic-range change |
| 0x08 | sticks, dynamic range -5, within noise |
| **0x20** | **camera dropped off the USB bus** |

After that write the ioctl returned ENODEV, the stream died, and once the device came back
0x1b read **0x0030** with every write to it failing **EPROTO** — including writes that would
have cleared the bit. It cleared itself on the next re-enumeration. The device recovered on
its own both times, but this is a hard hazard: **never write bits ≥ 0x20 to 0x1b.**
`daylight-probe.py` now refuses to.

### HDR is still not found, and three places have been ruled out

The string table said HDR is an auto-exposure variant, so the spare 0x1e AE modes were the
prime suspects. They are not it:

| 0x1e | mean | p5 | reading |
|---|---|---|---|
| 2 (auto) | 140.1 | 32 | reference |
| 0 | 141.4 | 32 | same as auto |
| 3 | 63.9 | 6 | about a stop darker, range compressed by 70 |
| 4 | 135.0 | 30 | same as auto |
| 5 | 61.0 | 5 | same as mode 3 |

Modes 3 and 5 pull everything down, highlights included — that is underexposure, not HDR,
which would lift p5 while holding p95. Modes 0 and 4 are indistinguishable from auto.

So HDR is not an AE mode, not one of the low function bits, and not a selector of its own.
What is left: a field inside 0x02 XU_VIDEO_MODE_CONTROL (52 bytes, mostly unexplored), the
function bits at 0x20 and above (which cannot be probed safely), or the command channel.

### XU_BIAS 0x18 — writes take, effect not visible

Low byte accepted at 0, 96, 128 and 255, echoed back every time, **pan/tilt never moved and
the frame stayed within scene noise** (spatial delta ~5.4-6.0 against a 5.4 noise floor).
Changing the high half moved the spatial delta to 11-15, which is suggestive but not
conclusive against a live scene. If this is the Horizontal fine-tuning slider, its effect is
too small for a 32x18 downsample to resolve. Needs a static scene and a full-resolution
before/after.

## 🔤 WHAT THE APP'S OWN STRING TABLE GIVES AWAY

`%LOCALAPPDATA%/Insta360/Insta360 Link Controller/translations/en-US.json`, 909 strings.
Some of them answer questions the pixels could not.

**The HDR lead.** Two strings pin down what HDR is:

- `hdr_on_m_exposure`: *"After enabling HDR, manual exposure is temporarily not supported."*
- `right_img_hdr_des`: *"Currently not supported for use at 4K and 50/60fps"*

So HDR is **an auto-exposure variant, not an independent toggle** — it is mutually exclusive
with manual exposure and constrained by sensor mode. That makes 0x1e XU_AE_MODE_CONTROL the
place to look, not a bit in the 0x1b bitmask: 1 is manual, 2 is auto, and earlier probing
found 0, 3, 4 and 5 are all accepted. One of those spare values is the likely HDR mode.
`daylight-probe.py` tests them and watches **p5**, since HDR lifts shadows rather than
shifting the mean.

**Naming, straight from the vendor:**

| Key | Label |
|---|---|
| `right_ptz_fast` / `right_ptz_normal` / `right_ptz_slow` | Quick / Ordinary / Slow |
| `right_compose_head` / `_half` / `_whole` | Head / Half Body / Whole Body — matches 0x13 taking 1, 2, 3 |
| `right_other_finetuning` | Horizontal fine-tuning — the manual slider, the XU_BIAS 0x18 candidate |
| `horizontal_correction_tips` | a *separate* automatic horizontal correction, so don't conflate the two |
| `right_img_exposure_com` | Exposure Compensation — our 0x09 |
| `moreset_key_board` / `_Aerial` / `_smartAerial` | Whiteboard / Overhead / DeskView |

Note the app's internal keys order tracking speed **fast, normal, slow** while the labels
read Quick, Ordinary, Slow. PR #101 assumes 1=slow, 2=medium, 3=fast. This camera reads 1,
and which integer means which is still unconfirmed — it needs a human to watch the gimbal.

**Privacy mode has two hardware flavours**, and this camera is the gimbal one:
`video_privacy_g_des` says *"lift the gimbal manually to exit Privacy Mode"* while
`video_privacy_h_des` talks about a lens cover. Tilting the gimbal 90° down arms it, and
`right_other_untilPrivacy` ("Mute in Privacy Mode") is the `setUltiPrivacyModeChecked` method.

**Audio capture modes** behind PARAM_AUDIO_CAPTURE_MODE: standard, wide, focus, music, plus
far / near / live-broadcast variants, the last of which "turns off AI noise-cancelation" —
the same feature as XU_NOISE_CANCEL at 0x07.

## 🧬 THE CAMERA API SURFACE, STRAIGHT FROM THE BINARY

`Webcam::CameraInsta::*` symbols survive in the exe, so the vendor's own camera class is
readable. 98 methods; these are the ones with no Linux equivalent yet:

| Method | What it implies |
|---|---|
| `setHdrChecked` | **HDR is a camera-side setting**, and no XU selector is named for it — so it rides inside another selector, most likely a bit of 0x1b |
| `setAntiFlash` | anti-flicker |
| `setAudioDenoise`, `setAudioCaptureMode` | the mic, matching XU_NOISE_CANCEL at 0x07 |
| `setPrivacyModeChecked`, `setUltiPrivacyModeChecked` | two privacy levels, the second logged as "ExtremePrivacy" |
| `setHorizontalCorrectionChecked` | the Horizontal fine-tuning slider, fits XU_BIAS at 0x18 |
| `setCompositionType` | Head / Half Body / Whole Body, fits XU_LAYOUT_STYLE at 0x13 |
| `setSmartAdjustmentChecked`, `setAiZoomChecked` | More tab toggles |
| `setMirrorChecked`, `setVerticallyMirrorChecked` | H and V flip, neither exposed over V4L2 here |
| `setForcedVertical`, `setVerticalModeEnabled`, `setLowResolution` | the Compatibility settings |
| `setRoll`, `setPitch`, `setHostPTZ`, `addPanTilt`, `savePTZ`, `resetPTZ` | gimbal, including preset save |
| `setUseGestureRock`, `setUseGestureOK` | **two gestures beyond palm/L/V**, not shown in this camera's UI |
| `ResetLink1Camera` | an explicit gen 1 code path, separate from `ResetPUC2CameraLower` |

Model-gated features are listed as `support*` flags: AiDenoise, AllowHostAdjustVolume,
AreaTrack, AudioCaptureMode, AutoFraming, AutoTrack, AutoTrackingTriggeredByCamera, Beauty,
BlurModeList, ForcedVerticalAndRollAdjustment, Highlighting, HorizontalCorrection,
ImageTemplate, Mirrorvertically, PTZDrag, PrivacyMode, RollAdjustment,
SetStartupParamsToCamera, SmartAdjustment, SoundWall, SpeakTracking, SuperBokeh, TrackSpeed,
VirtualCamera, Vulkan. **HDR is not among them**, so it is not model-gated — the gen 1 Link
has it, which matches the HDR toggle in its Effects tab.

### Two protocols, don't confuse them

- **`ControlSelector` (XU_*)** — app to camera, over the UVC extension unit. That is the
  table above and the only thing cameractrls can speak.
- **`ParamType` (PARAM_*)** — the WebSocket protocol the app serves for its own remote
  control, carrying protobuf `ControlRequest` / `ValueChangeNotification` messages. Those
  ids are not selectors. A feature appearing only as a PARAM_ still has to reach the camera
  through some XU selector.

Worth noting: 0x0e XU_DEVICE_PARAM_CONTROL reports **write-only** in GET_INFO, and 0x08 is
502 bytes and constantly changing. A command-in / notification-out channel pair is the
obvious reading, and would explain why features like HDR have no selector of their own.

### How to redo this on an app update

```bash
grep -a -o 'Webcam::CameraInsta::[A-Za-z0-9_]*' 'Insta360 Link Controller.exe' | sort -u
grep -a -o 'support[A-Z][A-Za-z0-9]*' 'Insta360 Link Controller.exe' | sort -u
```

## 🪟 OFFICIAL WINDOWS UI — EVERY OPTION, AND WHETHER IT IS MAPPED

Source: the 8 screenshots of Insta360 Link Controller taken 2025-12-10 on this camera
(`../Screenshot 2025-12-10 2005*.png`, originals in `/mnt/winos/Users/DanielSrb/Downloads/`).

✅ usable from Linux today · ⚠️ partly mapped or unverified · ❌ not mapped

### View tab

| UI control | Mapped | How |
|---|---|---|
| Pan / tilt d-pad | ✅ | V4L2 `pan_absolute` / `tilt_absolute`, XU 0x1a |
| **Pan / tilt continuous** | ✅ | **XU 0x16, `insta360_pan_speed` / `insta360_tilt_speed`** |
| Zoom | ✅ | V4L2 `zoom_absolute`, the app uses the same UVC control |
| Presets | ❌ | unit 10 selectors 0x03-0x05 suspected, all read zero |
| Smart Composition | ✅ | XU 0x1b bit 0x0001 |
| Composition Head / Half / Whole | ✅ | XU 0x13 |
| Tracking Speed | ✅ | XU 0x12 |
| Enable Auto Tracking | ✅ | XU 0x1b bit 0x0100 |
| Portrait / landscape | ✅ | XU 0x1b bit 0x0400 |

### Effects tab

| UI control | Mapped | How |
|---|---|---|
| Exposure Auto / M | ✅ | XU 0x1e |
| Exposure Compensation | ✅ | XU 0x09, 0.01 EV per unit |
| ISO | ✅ | XU 0x19 |
| Shutter | ✅ | XU 0x1d, denominator |
| Exposure curve | ✅ | XU 0x10, five presets. Not readable back |
| Auto Focus, Temperature, Brightness, Contrast, Saturation, Sharpness | ✅ | V4L2 |
| **HDR** | ✅ | **XU 0x1b bit 0x0004** |
| Anti-Flicker | ✅ | V4L2 `power_line_frequency`, same control the app drives |
| Set as startup | ❌ | camera-side per the capability flags, selector unknown |
| Color section reset | ❌ | the app's own `resetImageSettings` |

### More tab

| UI control | Mapped | How |
|---|---|---|
| Gesture master switch | ✅ | XU 0x1b bit 0x0010 |
| Gesture palm / L / V | ✅ | XU 0x05 bits 0x02 / 0x04 / 0x08 |
| Horizontal fine-tuning | ❌ | no bus traffic when driven, likely host-side |
| Horizontal Correction | ✅ | XU 0x1b bit 0x0080 |
| Smart Adjustment | ❌ | no bus traffic |
| Privacy Mode | ✅ | XU 0x1b bit 0x0800 |
| **Portrait Resolution and High Frame rate** | ✅ | **XU 0x1b bit 0x0020**, unlocks 50/60 fps and portrait |

### Bottom bar

| UI control | Mapped | How |
|---|---|---|
| **AI Tracking / Whiteboard / Overhead / DeskView** | ✅ | **XU 0x02 byte 0: 0, 4, 5, 6** |
| Resolution / format | ✅ | V4L2 |
| Snapshot / Record | ✅ | host-side, any capture tool |

### Score

**29 of 33 controls usable from Linux.** What is left, and why:

- **Presets** — the app's save/recall slots. Unit 10 selectors 0x03-0x05 read as zeros and
  were never driven; cameractrls has its own host-side preset system, which covers the need
  differently.
- **Horizontal fine-tuning** and **Smart Adjustment** — driving both over the vendor's own
  remote produced **zero** bus traffic, so the app applies them host-side. Not reachable
  through the camera at all.
- **Set as startup** and the **Color reset button** — app-level conveniences.

Linux also gained one thing the Windows app cannot do: `insta360-ws.py` can drive any of the
61 parameters programmatically, and `usbmon-bin.py` shows exactly what each one sends.

## 📋 WINDOWS FEATURES TO MAP## 📋 WINDOWS FEATURES TO MAP

From Windows Link Controller software:

| Feature | XU Selector | Status |
|---------|-------------|--------|
| Auto/Manual Exposure | 0x1e | ✅ Found |
| Shutter Speed (1/30-1/8000) | 0x19 | ✅ Found |
| ISO (100-3200) | ? | 🔍 Unknown (0x1b was a wrong guess, see above) |
| Exposure Compensation (±3 EV) | 0x09 | ✅ Found (-4..+4) |
| HDR | ? | 🔍 Unknown |
| Tracking Mode / Speed | 0x12 | ✅ Found (slow/medium/fast) |
| DeskView/Overhead/Whiteboard | ? | 🔍 Unknown (V gesture toggles whiteboard) |
| Gesture Control | 0x05 + 0x1b | ✅ Found (per-gesture bits + global enable) |
| Presets (save/recall) | 0x15? | 🔍 Unknown |
| Privacy Mode | ? | 🔍 Unknown |

---

## 🧪 TEST LOG

### 2024-12-05

**Exposure Mode + Time**: ✅ SUCCESS
- Set 0x1e=1 (manual), then 0x19 to various values
- Brightness visibly changed from dark (100µs) to bright (8000µs)
- Readback matches set value

**Gain/ISO (0x1b)**: ⚠️ PARTIAL
- Values 48-100 work
- Value 200 causes timeout and camera disconnect
- Need to find valid range

---

## 🔧 CAMERACTRLS EXTENSION IMPLEMENTATION

### Required Structure
Based on KiyoProCtrls pattern from cameractrls.py:

```python
# GUID for Unit 9 (main controls) - bytes reversed for little-endian
INSTA360_LINK_GUID = b'\x2d\x67\xf1\xfa\x1b\xb7\x93\x47\x8c\x91\x7b\x1c\x9b\x7f\x95\xf8'
INSTA360_LINK_USB_ID = '2e1a:4c01'

# Selectors
INSTA360_EXP_MODE_SEL = 0x1e  # 1 byte
INSTA360_EXP_TIME_SEL = 0x19  # 2 bytes LE, microseconds
INSTA360_GAIN_SEL = 0x1b      # 2 bytes LE, 0-100 safe range
INSTA360_TOGGLE_07_SEL = 0x07 # 1 byte, 0/1

class Insta360LinkCtrls:
    def __init__(self, device, fd):
        self.device = device
        self.fd = fd
        self.unit_id = find_unit_id_in_sysfs(device, INSTA360_LINK_GUID)
        self.usb_ids = find_usb_ids_in_sysfs(device)
        self.get_device_controls()

    def supported(self):
        return self.unit_id != 0 and self.usb_ids == INSTA360_LINK_USB_ID
```

### Controls to Implement

1. **Exposure Mode** (menu):
   - auto (value 2) - default
   - manual (value 1)
   - auto_fast (value 3)
   - auto_slow (value 4)

2. **Shutter Speed** (menu, only in manual mode):
   - 1/30 (33333)
   - 1/60 (16667)
   - 1/125 (8000)
   - 1/250 (4000)
   - 1/500 (2000)
   - 1/1000 (1000)
   - 1/2000 (500)
   - 1/4000 (250)

3. **Gain** (integer 0-100, use with caution)

4. **Toggle 0x07** (menu: on/off) - effect TBD

### Key Functions from cameractrls.py

```python
def query_xu_control(fd, unit_id, selector, query, data):
    # Uses UVCIOC_CTRL_QUERY ioctl
    # data should be from to_buf(bytes)

def to_buf(b):
    return ctypes.create_string_buffer(b)

def find_unit_id_in_sysfs(device, guid):
    # Reads /sys/class/video4linux/{dev}/../../../descriptors
    # Returns byte before GUID position
```

### UVC Constants
```python
UVC_GET_CUR = 0x81
UVC_SET_CUR = 0x01
UVCIOC_CTRL_QUERY = 0xc0107521
```

---

## 📋 UNIT 9 SELECTORS — AUTHORITATIVE MAP

The names below are **not guesses**. The Windows app embeds its own protobuf
`ControlSelector` enum, and the descriptor carries the numbers. See "How the names were
recovered" below to redo it. ✅ = verified on this camera, gen 1, firmware v1.4.5.8_build1.

| Sel | Official name | Len | RW | Meaning / value seen |
|---|---|---|---|---|
| 0x01 | XU_EXEC_SCRIPT_CONTROL | 4 | rw | zeros |
| 0x02 | XU_VIDEO_MODE_CONTROL | 52 | rw | ✅ mode id in **byte 0**: 0 normal, 4 whiteboard, 5 overhead, 6 deskview |
| 0x03 | XU_DEVICE_INFO_CONTROL | 170 | rw | ✅ serial, a UUID, and **firmware `v1.4.5.8_build1`** as strings |
| 0x04 | XU_PTZ_CMD_CONTROL | 262 | rw | zeros |
| 0x05 | XU_GESTURE_STATUS_CONTROL | 1 | rw | ✅ gesture bitmask: palm 0x02, L 0x04, V 0x08 |
| 0x06 | XU_GESTURE_BIND_CONTROL | 5 | rw | zeros — which action each gesture triggers |
| 0x07 | XU_NOISE_CANCEL_CONTROL | 1 | rw | ✅ **microphone noise cancelling**, default 1. This is why toggling it never changed the image — it was never HDR |
| 0x08 | XU_FIRMWARE_UPGRADE / XU_BLEND_DRAW | 502 | rw | volatile, aliased pair in the enum |
| 0x09 | XU_EXPOSURE_VALUE_CONTROL | 2 | rw | ✅ **exposure compensation**, signed, 0.01 EV per unit, ±300 = ±3.00 EV |
| 0x0a | XU_TAKE_PICTURE_CONTROL | 129 | rw | zeros |
| 0x0b | XU_DEVICE_STATUS_CONTROL | 5 | ro | ✅ **byte 0 and 1 are temperatures in °C**, byte 3 is a **streaming flag**. Idle 44/37 flag 0, after a minute of 720p30 46/41 flag 1 |
| 0x0c | XU_DEVICE_SN_CONTROL | 32 | rw | ✅ serial number string |
| 0x0d | XU_DEVICE_LICENSEN_CONTROL | 129 | rw | per-device blob, don't paste |
| 0x0e | XU_DEVICE_PARAM_CONTROL | 1 | **wo** | write-only, GET_INFO says no read |
| 0x0f | XU_DOWNLOAD_FILE / XU_AF_MODE | 12 | rw | aliased pair. Volatile |
| 0x10 | XU_UPLOAD_FILE / XU_EXPOSURE_CURVE | 255 | rw | ✅ **exposure curve**, 256 points sent in 3 chunks. Reads return only the last chunk |
| 0x11 | XU_USB_MODE_SWITCH_CONTROL | 1 | rw | 0. **Do not write** — it can change how the device enumerates |
| 0x12 | XU_TRACK_SPEED_CONTROL | 1 | rw | ✅ tracking speed, **1 slow, 2 medium, 3 fast**, confirmed by blind A/B. Vendor labels them Slow, Ordinary, Quick |
| 0x13 | XU_LAYOUT_STYLE_CONTROL | 1 | rw | ✅ composition, **1 Head, 2 Half Body, 3 Whole Body**, 0 rejected. Direction confirmed with a person in frame, but the effect is weak at distance on this firmware |
| 0x14 | XU_HEAD_LIST_CONTROL | 240 | ro | ✅ **detected head boxes as floats**. All-zero with nobody in frame, populated otherwise |
| 0x15 | XU_TRACK_TARGET_CONTROL | 8 | rw | zeros |
| 0x16 | XU_PANTILT_RELATIVE_CONTROL | 4 | rw | ✅ **gimbal speed**, [pan sign, pan mag, tilt sign, tilt mag], stop is `00 01 00 01` |
| 0x17 | XU_MOBVOI_PUBKEY_CONTROL | 129 | rw | per-device blob, don't paste |
| 0x18 | XU_BIAS_CONTROL | 4 | rw | 48, 2643. Distinct from 0x09 — the ParamType enum groups PARAM_BIAS with the PTZ family, so this is likely the horizontal fine-tuning |
| 0x19 | XU_ISO_CONTROL | 2 | rw | ✅ **ISO**. 100 → luminance 3.8, 400 → 10.2, 1600 → 26.4, 3200 → 40.5 |
| 0x1a | XU_PANTILT_ABSOLUTE_CONTROL | 8 | rw | ✅ 2 × int32 LE arc-seconds, **tilt first, then pan** |
| 0x1b | XU_FUNC_ENABLE_CONTROL | 2 | rw | ✅ function bitmask: **0x01** smart composition, **0x04** HDR, **0x10** gestures, **0x20** portrait/high frame rate (re-enumerates), **0x80** horizontal correction, **0x100** AI tracking, **0x400** portrait/landscape switch, **0x800** privacy mode |
| 0x1c | XU_VIDEO_RES_CONTROL | 10 | rw | mirrors the active stream format, zeros while idle |
| 0x1d | XU_EXPOSURE_TIME_ABSOLUTE_CONTROL | 2 | rw | ✅ **shutter as denominator**, 60 = 1/60s. 1/30 → 85.0, 1/120 → 38.4, 1/1000 → 14.9, 1/8000 → 8.2. Firmware quantises: 30 reads back 29 |
| 0x1e | XU_AE_MODE_CONTROL | 1 | rw | ✅ exposure mode, 1 = manual, 2 = auto. 0 and 4 behave like auto, 3 and 5 are ~1 stop darker. None of them is HDR |

Unit 9 exposes 30 selectors, one per enum entry that this firmware implements.

### The two corrections this table forced

1. **0x19 is ISO, not exposure time.** The old shutter control wrote microseconds into
   the ISO register — 33333 clamped to maximum ISO and 250 was ISO 250, so the image
   dimmed and brightened for entirely the wrong reason. Shutter belongs at 0x1d.
2. **0x07 is microphone noise cancelling**, not an HDR candidate. No amount of luminance
   testing would ever have shown an effect.

## 🔍 HOW THE NAMES WERE RECOVERED

`Insta360 Link Controller.exe` (115 MB, Qt + protobuf) embeds the serialized descriptor
for its own `ControlSelector` enum. No debugger or disassembler needed:

1. Find the name pool: `grep -a` the exe for `XU_` — the strings sit around file offset
   `0x1668c40`, right after the literal `ControlSelector`.
2. Each entry is a serialized `EnumValueDescriptorProto`: `0a <len> <NAME> 10 <number>`.
   The `10` is protobuf field 2 as a varint, and that varint **is the selector number**.
   Three numbers are aliased pairs (0x08, 0x0f, 0x10).
3. The same blob holds the `ParamType` enum used by the app's WebSocket protocol —
   PARAM_ISO_VALUE, PARAM_HDR, PARAM_PRIVACY_MODE, PARAM_GESTURE_*_SWITCH and so on.

`ParamType` names features the XU list does not, so it is the better map of what the
camera can do: PARAM_HDR, PARAM_AUTI_FLICK, PARAM_SMART_ADJUST, PARAM_PRIVACY_MODE,
PARAM_ROLL_ADJUST, PARAM_LOWER_RES, PARAM_VERTICAL_SCREEN, PARAM_FINE_TUNING,
PARAM_GESTURE_ROCK_SWITCH and PARAM_GESTURE_OK_SWITCH (two gestures the Linux side has
never seen), PARAM_AUDIO_CAPTURE_MODE, PARAM_TRACK_FIRBOIDDEN_AREA, PARAM_HOST_PTZ_INFO.
Those are app-level parameter ids, not selectors — they travel inside XU payloads.

## 📝 TODO

1. [x] Write cameractrls extension class — now `Insta360Ctrls`, shared with the Link 2 family
2. [x] Find the real ISO selector — 0x19, verified
3. [x] Identify 0x07 — microphone noise cancelling, not HDR
4. [x] Find the HDR toggle — 0x1b bit 0x04, captured from the vendor protocol
5. [x] Confirm 0x13 layout style visually — direction confirmed, effect weak at distance
6. [x] Confirm the palm gesture bit and tracking speed — both confirmed by blind A/B
7. [ ] Confirm the L and V gesture bits individually, still inferred from PR #101
8. [ ] Test presets (unit 10 slots)
9. [ ] Feed the gen 1 findings back into cameractrls PR #101 / issue #55

---

## 🎮 PAN/TILT/ZOOM CONTROL

Standard UVC pan/tilt **speed** controls fail with error -5. Kernel disables them because Insta360 uses proprietary protocol.

### What Works Now (V4L2)

| Control | Min | Max | Step | Unit |
|---------|-----|-----|------|------|
| `pan_absolute` | -522000 | 522000 | 3600 | arc-seconds |
| `tilt_absolute` | -324000 | 360000 | 3600 | arc-seconds |
| `zoom_absolute` | 100 | 400 | 1 | percentage (100=1x, 400=4x) |

**Conversion**: `degrees = arc_seconds / 3600`
- Pan range: -145° to +145°
- Tilt range: -90° to +100°

### Pan/Tilt Speed
❌ V4L2 speed controls return error -5 (EIO) - requires proprietary protocol

### Solution Options

**Option 1: libuvc C++ approach**
- Project: [qqice/insta360_link_uvc_ctrl](https://github.com/qqice/insta360_link_uvc_ctrl)
- C++ with libuvc, OpenCV
- Working gimbal control

**Option 2: WebSocket Protocol**
- Reverse-engineered at [dt.in.th](https://dt.in.th/Insta360LinkControllerWebSocketProtocol)
- Uses protobuf over WebSocket
- `uvcExtendRequest` with `[signX, magnitudeX, signY, magnitudeY]`
- sign: 0=stop, 1=positive, 255=negative
- magnitude: 1-30 (speed)
- paramType: PARAM_PAN_TILT_RELATIVE

### External Resources
- [cameractrls Issue #55](https://github.com/soyersoyer/cameractrls/issues/55) - Insta360 Link support tracking
- [qqice/insta360_link_uvc_ctrl](https://github.com/qqice/insta360_link_uvc_ctrl) - C++ libuvc implementation with gimbal control
- [dt.in.th WebSocket Protocol](https://dt.in.th/Insta360LinkControllerWebSocketProtocol) - Reverse-engineered protobuf protocol
- [nicjohnson145/WebCamControl](https://github.com/nicjohnson145/WebCamControl) - .NET/C# app, V4L2 only (no UVC XU), useful for presets pattern

---

## 📚 RELATED PROJECTS ANALYSIS

### WebCamControl (.NET/C#)
- **Path**: `/home/srb/code/linux/WebCamControl/`
- **Approach**: Standard V4L2 controls only
- **Does NOT** implement UVC Extension Units (no exposure mode, shutter, gain via XU)
- **Useful for**: Presets system design (save/restore pan, tilt, zoom positions)
- **Arc-seconds math**: `value / 3600 = degrees`

---

## 🛰️ 2026-09-19 — THE 0x04 COMMAND CHANNEL, AND THE SCHEMA BEHIND EVERYTHING

Two new tools carry this section. `tools/xu-probe.py` reads or writes any selector on any
unit and asks the device for its own lengths, so nothing here depends on a guess about
sizes. `tools/extract-proto.py` pulls the vendor app's entire protobuf schema out of the
exe; the result is checked in as `tools/vendor-proto.txt`.

### 0x04 XU_PTZ_CMD — framing, decoded

The 262 byte register is a command in, response out channel. Write a frame, wait about a
second, read the reply from the same selector. **Writes only stick while streaming**, the
usual rule.

    offset  0  1   2    3    4  5    6 ...
            a5 d0  cmd  len  tok      payload[len]

- `a5 d0` magic, always.
- `cmd` is echoed in the reply, or **0xff when the command is not supported**. That makes
  the channel self-describing: send a command, read the first three bytes, and the camera
  tells you whether it exists.
- `len` counts the payload only.
- `tok` is a CRC, and it is **not validated** — zeros work as well as the real thing. It is
  reproduced below anyway, because the Link 2 firmware may well check it.
- The device answers into its own 262 byte buffer and only overwrites the front, so bytes
  past the current reply are stale from an earlier one. Always trust `len`, never the tail.

### The checksum, recovered from the code

The routine sits at `0x140abbe70` in the 2025 build and is a reflected CCITT CRC-16 — X-25's
polynomial arrangement, init `0xFFFF` — over the **four header bytes plus a constant `0x2f`
salt**, stored little-endian at offset 4. The salt is not a separate step in the exe; the
loop runs over the header and then the tail does one more round with `0x2f` hard-coded.

```python
def token(header4):
    crc = 0xffff
    for b in header4 + b'\x2f':
        x = (crc ^ b) & 0xff
        x = (x ^ (x << 4)) & 0xff
        crc = ((crc >> 8) ^ (x << 8) ^ (x << 3) ^ (x >> 4)) & 0xffff
    return crc.to_bytes(2, 'little')
```

`token(bytes.fromhex('a5d00300'))` is `f1 32`, the exact bytes the vendor app sent. It also
reproduces the device's own replies — `a5 d0 ff 00` → `66 1b`, `a5 d0 41 00` → `3f 81` —
**but only when the payload is empty**. Replies that carry a payload put something else in
those two bytes (`aa 00` for the 40 byte identity block, `01 01` for a 1 byte reply); no
combination of range, init or salt reproduces those, so the field is not a payload CRC.

### The commands this firmware answers

Swept 0x00 to 0xfe with an empty payload. Thirteen exist:

| cmd | reply len | payload | reading |
|---|---|---|---|
| 0x03 | 40 | see below | factory / gimbal identity |
| 0x04 | 0 | — | ack only |
| 0x05 | 1 | `61` (seen `71` once) | status byte, bit 0x10 changed once unprompted |
| 0x06 | 0 | — | ack only |
| 0x07 | 14 | `SWWYYNPTZXXX[5` | second serial field, also a template |
| 0x09 | 3 | `00 bb d9` | stable across 30 s and across gimbal commands |
| 0x10, 0x20, 0x31, 0x40, 0x41 | 0 | — | ack only |
| 0x30 | 1 | `b5` | stable |
| 0x32 | takes 3 bytes in | — | the only command the exe builds with a payload |

Everything else returns `0xff`. The camera answered normally after both sweeps and
`XU_DEVICE_SN` still read `IBJLA23066B543` — but see the warning below before repeating this.

> ⚠️ **The sweep is not harmless. Do not repeat it.** Minutes after it, the gimbal began
> panning and tilting continuously and would not stop. It was not the speed register —
> `XU_PANTILT_RELATIVE` 0x16 read the idle `00 01 00 01` the whole time — and not tracking,
> with `XU_FUNC_ENABLE` 0x1b at `0x0020`, auto tracking clear. Something in the 0x00-0xfe
> range starts a gimbal routine that outlives the command and ignores the stop pattern. A
> USB power cycle clears it. The status byte from command 0x05 also changed from `71` to
> `61` around the same time and never came back. If a command id must be tested, test it
> alone, with a hand on the cable.

The buffer also turns up holding a `0x09` reply that nobody asked for, so the camera
pushes at least one frame on its own. A 15 s watch with the camera idle caught none, so
whatever triggers it is not a timer.

The exe builds six of these headers as 32 bit immediates, which is how the list was
seeded rather than guessed: `a5d00300`, `a5d03000`, `a5d03203`, `a5d04100` and two more.
Find them again with a scan for `c7 44 24 ?? a5 d0` — `mov dword [rsp+disp], imm32`.

### cmd 0x03, the 40 byte identity block

    00 00 | "083TPP" | 10 ff 28 3a ff ff | 05 01 01
          | "INSWWYYNPTZXXX" | 07 00 00 | 70 63 00 20 43 8b

`INSWWYYNPTZXXX` is a **serial template, not a serial** — week, year and sequence
placeholders that were never burned in at the factory. The camera's real serial lives at
`XU_DEVICE_SN` 0x0c and matches the sticker. `05 01 01` is version shaped and is the best
candidate for the app's `ptzVersion` field.

For contrast, `XU_DEVICE_INFO` 0x03 (the *selector*, not the command) carries a third
serial `13B586099180472`, a UUID, and the firmware string `v1.4.5.8_build1`.

### Video mode id 1 is AUTO_COMPOSITION

From `VideoModeType` in the exe, so these are the vendor's own names:

| id | name | id | name |
|---|---|---|---|
| 0 | NORMAL_MODE | 7 | AUTOFRAMEING_MODE |
| 1 | **AUTO_COMPOSITION** | 8 | SMARTWHITEBOARD_MODE |
| 2 | TRACKING_MODE | 9 | REGIONALTRACK_MODE |
| 4 | WHITEBOARD_MODE | 10 | SMARTWHITEBOARD_QUERY |
| 5 | OVERHEAD_MODE | 11 | SMARTWHITEBOARD_CONFIG |
| 6 | DESKVIEW_MODE | | |

There is no 3. Ids 7 to 11 are almost certainly Link 2 only, but they cost nothing to try.

### DeviceSettingInfo, named field by field

`tools/vendor-proto.txt` holds the whole schema. The installed build defines
`DeviceSettingInfo` up to **field 55**, which settles part of an old question: the ten
fields 56 to 65 seen in a `--dump-state` come from the **newer app in the VM**, and
decoding them needs that build's exe, not this one. Nothing else is missing — every field
the Linux side cares about has a name now, including `funeTuningValue` (53, the vendor's
typo), `verScreenLock` (54) and `enableTrackForiddenArea` (55, also theirs).

`WebTransport.proto` also explains how the app's remote protocol reaches the camera:
`UVCExtendRequest` carries a `ParamType`, a `ControlSelector`, a repeated int32 `data`
**and a `presetPosIndex`**. So presets are a parameter on an ordinary selector write, not
a storage area of their own.

### Unit 10 is not a preset store

The old table guessed "preset slot 1/2/3" for unit 10 selectors 0x03 to 0x05. There is no
evidence for that and some against it:

- All three read zeros for CUR, MIN, MAX, RES and DEF alike. A slot array would show
  *something* in MAX.
- Unit 10's GUID sits **immediately after unit 9's** in the exe, inside the vendor's own
  `deps/UVCCamera/src/win/uvc_camera_win.cc`. It is the second GUID their UVC layer looks
  for, and the source path is `E:\workspace\puc2\...` — PUC2 is the Link 2 family in the
  `MettingCameraType` enum. Unit 10 most likely belongs to a later model and is inert here.
- `PresetPosInfo` is `{name, index}` and `DeviceBasicInfo.curPresetPos` is a single int32.
  Names are host side. Only the position has to reach the camera.

The live hypothesis for preset save and recall is **0x04 command 0x32**, the one command
the exe builds with a payload, and it builds it with exactly 3 bytes — enough for an
operation and an index. Untested: it writes camera state, so it wants a human watching.

### How far the gimbal actually turns

V4L2 reports angles in arcseconds, and the mapping to the struct's tenths of a degree is
exactly 1:1 — commanded 20°, 45°, 90° and 130° all arrive dead on. What is *not* right is the
range the camera advertises:

| Axis | V4L2 advertises | Actually reaches |
|---|---|---|
| pan | ±145.0° | **+136.7° / -137.5°** |
| tilt up | +100.0° | **+67.6°** |
| tilt down | -90.0° | **-69.4°** |

Repeated twice by absolute command and once more by holding a speed against the stop; all
three agree. **An earlier note here said +41.4° up — that was wrong**, a position read taken
while the gimbal was still travelling. Six seconds is not enough to settle a full sweep.

So the axis is close to symmetric, ±68°, and the camera advertises roughly half again as
much as it has. The published specs are no help: Insta360's marketing says "pan almost 360°"
and "tilt 90°", and their own naming calls the *portrait rotation* the tilt axis, so the
-90/+100 the camera reports over UVC may describe a different axis entirely.

### The tilt speed runs backwards from the tilt angle

`insta360_tilt_speed` positive drove the gimbal **down**, while `tilt_absolute` positive is
up. Overhead mode settles the question — it parks at -90° pointing straight down, so negative
is down — which makes the speed control the odd one out. Now negated when encoding, so
positive is up on both, matching the up arrow key. Measured after the fix: +10 reaches
+52.6°, -10 reaches -52.9°.

### Level compensation is not a camera control

The Windows app's few-degrees levelling slider does **not** reach the camera. `XU_BIAS` 0x18
is a float32 and currently reads 0.000247, which matches the app's `funeTuningValue`, and it
accepts and echoes anything written — 5.0, -5.0, 10.0 all read back exactly. The image does
not move: against a static scene with a noise floor of 0.89, every value landed between 0.98
and 1.27, with the horizontal correction bit 0x80 enabled the whole time.

That agrees with the older finding that driving fine-tuning through the vendor's own protocol
produced no bus traffic. **The app rotates the image host-side.** Exposing it here would mean
rotating in `cameraview.py`, not adding a control.

### Power-on defaults, read straight after a replug

| Selector | Value | Note |
|---|---|---|
| 0x16 `PANTILT_RELATIVE` | `00 03 00 03` | **not** the `00 01 00 01` the vendor app sends to stop. Sign 0 is what halts the gimbal; the magnitude beside it is ignored |
| 0x1b `FUNC_ENABLE` | `0x0030` | gestures 0x10 and high frame rate 0x20 on, everything else off |

### Position readback stays at zero

`XU_PANTILT_ABSOLUTE` 0x1a reads eight zero bytes in every state tried, before and after
movement commands. The camera's V4L2 `pan_absolute` and `tilt_absolute` agree — both sit at
0 — yet both **accept writes** and report the written value back (`pan_absolute=180000`
reads back as 180000). Whether the motor follows a V4L2 absolute write is unconfirmed; the
room was too busy for frame differencing to separate a pan from the person in shot.

If the motor does follow, absolute positioning is a far better preset mechanism than
replaying speed pulses, and the whole unit 10 question stops mattering.

---

## 🧭 2026-09-19, SECOND PASS — THE STATUS REGISTER, AND A BUG THAT BLOCKED VIDEO MODE

### 0x02 XU_VIDEO_MODE is the status register, not just a mode byte

The 52 byte struct carries the **live gimbal position**. Confirmed by driving the gimbal to
known angles and reading it back, not by inference:

| Offset | Type | Meaning |
|---|---|---|
| 0 | u8 | video mode id, `VideoModeType` |
| 1 | u8 | flags, **unresolved** |
| 38 | i32 LE | **pan, tenths of a degree** |
| 42 | i32 LE | **tilt, tenths of a degree** |
| 50 | u16 LE | zoom, 100 to 400 |

`pan_absolute=90000` (25° in the arcseconds V4L2 uses) reads back as 250. `-90000` reads
back as -250. A tilt write of 72000 reads back as 200. Arcseconds are the struct value × 360.

Byte 1 was seen as 0x00, 0x01 and 0x10 in the captures and does **not** follow auto
tracking, smart composition, portrait, HDR or the gesture master bit — all four were toggled
and watched.

**Reads work with the camera idle.** Only writes need a stream, so a GUI can poll the
position without holding the device open for video.

### The gimbal moves, and the old position source never did

Two things were unconfirmed for a month and are now settled:

- **Both movement paths work.** A speed write to 0x16 took the gimbal to 65.9°, and
  `pan_absolute=0` brought it home. No eyes needed — the struct reports it.
- **`XU_PANTILT_ABSOLUTE` 0x1a is dead.** Eight zero bytes in every state. The vendor app
  never issues a GET_CUR on it either; the only 0x1a traffic in the captures is the startup
  MIN/MAX/RES/DEF sweep, all zeros, plus one write of eight zeros.

### ⚠️ The absolute sliders snap back after a speed move

V4L2 `pan_absolute` reads back **whatever was last written to it**, not where the gimbal is.
Because pan and tilt share one UVC control, the driver read-modify-writes from that stale
value, so touching either axis yanks the other one back. Measured:

| Step | Real pan | V4L2 thinks |
|---|---|---|
| `pan_absolute=90000` | 25.0° | 90000 |
| `tilt_absolute=36000` | 25.0° | 90000, consistent, nothing moves |
| speed pan for 1.2 s | **73.9°** | still 90000 |
| `tilt_absolute=0` | **snaps back to 25.0°** | 90000 |

The fix is to resync the driver's idea of the position from the struct once the gimbal
settles. Not done — it needs a decision about where to put the write so it does not fight
the coast.

### 🐛 Every video mode write failed, and the cause was one byte

`insta360_video_mode` had never once been driven through cameractrls. It could not be:
every write returned **ENOBUFS**.

`to_buf()` wraps `ctypes.create_string_buffer()`, which appends a NUL, so a 52 byte read
came back as 53 bytes. Video mode is the one control that feeds a read straight back into a
write — it has to, since the mode is one byte of a struct it must otherwise preserve — so it
handed the driver 53 bytes for a 52 byte register and uvcvideo rejected the size. Fixed by
slicing `Insta360Ctrls.query()` to the requested length. All four modes now set and read
back.

### Verified on the camera, after the fix

Parked at pan 15.0°, then cycled through every mode:

| Mode | id | Gimbal |
|---|---|---|
| whiteboard | 4 | **untouched**, held at pan 15.0° tilt 0.0° |
| overhead | 5 | tilt to **-90.0°**, straight down |
| deskview | 6 | tilt **-45.0°**, pan recentred to 0 |
| normal | 0 | back to 0.0°, 0.0° |

Whiteboard holding position is the proof the 3610 sentinel works — the write no longer
commands a move. The angles under overhead and deskview are the camera aiming itself,
camera-side behaviour that no cameractrls code asks for.

### The exposure curve framing, confirmed from the vendor's own writes

Three chunk writes in the capture decode exactly as this code already builds them:

    [start index byte] [u16 LE, 2 on the first two chunks, 1 on the last] [126 × u16 LE points]

Start indices 0, 126, 252 and 3 + 252 = the 255 byte register. The third chunk's real
payload is the top of the ramp, 1008, 1012, 1016, 1023, and the rest is the previous
chunk's tail. All five presets write without error.

Whether they *look* different is still unmeasured: at ISO 3200 and 1/30 in evening light,
`lift_shadows` moved the frame mean from about 75 to 83 and pulled p95 from 178 to 159,
which is the right direction, but the scene drifted as much across two identical `linear`
readings. **Retest in daylight.**

### Two more registers decoded, both read-only in practice

- **0x14 XU_HEAD_LIST**, 244 bytes: `[u8 count][count × 4 × float32 LE]`, a normalised
  bounding box per detected head. One sample: count 1, box `0.276, 0.0083, 0.263, 0.369`.
  Room for 15 heads.
- **0x1c XU_VIDEO_RES**, 10 bytes: `[u32 width][u32 height][u16 fps]` — `1920, 1080, 30`.

### The gimbal speeds the vendor app actually uses

Every 0x16 write in the capture: `00 01 00 01` idle, and magnitudes of only **4 and 8** on
either axis, either sign. Our range of ±30 is wider than anything the app sends.

---

## 🧾 2026-09-19 — FIELDS 56-65 NAMED, AND A CORRECTION

The app build in the VM is **2.2.4.14**; the one on the Windows partition is **2.0.6.2**.
That is the whole reason those ten fields looked undecodable — the older schema stops at 55.
The newer exe is kept at `~/vm/insta360-app-2.2.4.14.exe` and `tools/vendor-proto.txt` is
now generated from it.

| Field | Type | Matches the live dump |
|---|---|---|
| 56 | int32 `audioDirectionMode` | 0 |
| 57 | `BeautyParam` | four -1 placeholders and `enabled` — beauty sliders, unset |
| 58 | `MakeupParam` | templateId -1, intensity -1, enabled |
| 59 | `GreenScreenParam` | **the colour `#00ff00`**, plus intensity, smooth, remove, enhance |
| 60 | bool `enable4KResolution` | |
| 61 | bool `supportSuperBokeh` | |
| 62 | bool `support4KSuperBokeh` | |
| 63 | int32 `pitch` | |
| 64 | bool `isVirtualCamera` | |
| 65 | bool `supportGreenScreen` | |

`GreenScreenParam.color` being exactly the `#00ff00` the dump showed is the confirmation
that these are the right names.

### The newer app adds nothing that reaches the camera

`ControlSelector` is **byte for byte identical** between 2.0.6.2 and 2.2.4.14. Everything
new is host side: `ParamType` grows by fifteen — beauty, makeup, green screen, overlays,
4K, super bokeh — and five new messages appear for background templates and overlay scenes.
None of it is a new selector.

Two of the new parameters are worth noting anyway. `PARAM_PITCH` has no selector of its own,
which fits the **third angle field** in the 0x02 struct at offset 46 — the one the app fills
with the 3610 sentinel alongside pan and tilt. And `PARAM_FRAME_RATE` joins the existing
high frame rate bit rather than replacing it.

### ⚠️ Correction: the "second independent build" cross-check was weaker than recorded

An earlier note said the 2.2.4.14 enum was "a clean 0-30 list with no aliases", and read
meaning into the newer build supposedly dropping BLEND_DRAW, AF_MODE and EXPOSURE_CURVE.
**That difference does not exist.** Reading the enum out of the exe shows all three aliased
pairs present in both builds, at 8, 15 and 16.

The earlier reading came from the app's web bundle, where protobufjs represents an enum as a
name-to-number object — and an aliased value simply collapses in that form. The conclusion
it supported is still true, and now trivially so: every selector matches across both builds,
because the enum is the same enum. Take schemas from the exe, not from the web bundle.
