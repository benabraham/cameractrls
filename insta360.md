# Insta360 Link UVC Extension Unit Research

## Device Info
- **USB ID**: `2e1a:4c01`
- **Model**: IBJLA23066B543
- **Firmware**: v1.4.5.8_build1
- **Serial**: 13B586099180472

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
- The "strange" 252-4 range is a **signed byte in the low half**: `0xFC` = -4, `0x04` = +4.
  So gen 1 offers **-4..+4**, where the Link 2 family reports -100..+100 over both bytes.
  `Insta360Ctrls.read_signed_range()` handles both.
- Matches the "Exposure Compensation ±3 EV" row in the Windows feature table below.
- **Status**: ✅ Range confirmed by GET_MIN/GET_MAX, write effect not yet verified

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

**0x09 exposure bias — accepted, echoed, no image effect.** Swept -4, -2, 0, +2, +4 in
auto exposure mode, both byte layouts (`fc ff` sign-extended and `fc 00` low-byte-signed).
Every write echoed exactly on GET_CUR and luminance stayed at 104.6-106.0 with identical
stddev. The Windows app clearly has a working ±3.0EV slider in auto mode (screenshot
`…200627.png` at 3.0EV is visibly blown out), so either gen 1 firmware stores this value
and ignores it, or the EV control lives elsewhere and 0x09 is something else on gen 1.

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

## 🪟 OFFICIAL WINDOWS UI — COMPLETE OPTION INVENTORY

Source: 8 screenshots of **Insta360 Link Controller** taken 2025-12-10, this camera
(serial IBJLA23066B543). They live in `../` (one level above this repo, untracked):
`Screenshot 2025-12-10 2003 50 / 2004 20 / 2004 34 / 2005 02 / 2005 25 / 2005 39 / 2005 54 / 2006 27.png`,
originals also at `/mnt/winos/Users/DanielSrb/Downloads/`.

This is the full set of options the vendor app offers, i.e. the ceiling for what the
firmware can do. Everything not already covered by V4L2 has to come from an XU.

### View tab

| Option | Values seen | Linux status |
|---|---|---|
| View Adjustment: pan / tilt d-pad | — | ✅ V4L2 `pan_absolute` / `tilt_absolute` |
| View Adjustment: zoom | 1.2x shown | ✅ V4L2 `zoom_absolute` (100-400) |
| Presets | user-added slots (+) | 🔍 unit 10 selectors 0x03-0x05 suspected |
| Smart Composition | toggle | 🔍 unmapped |
| Composition framing | Head / Half Body / Whole Body | 🔍 unmapped |
| **Tracking Speed** | **Quick / Ordinary / Slow** | ✅ selector 0x12 (1/2/3) |
| Enable Auto Tracking | toggle | 🔍 unmapped (likely a 0x1b bit) |

Note the official names are **Quick / Ordinary / Slow**, PR #101 labels them fast /
medium / slow. Which integer maps to which is still unproven on gen 1.

### Effects tab (Color)

| Option | Values seen | Linux status |
|---|---|---|
| Exposure | Auto / M switch | ✅ selector 0x1e |
| — Auto: EV bias | **0.0EV .. 3.0EV** (±3 EV) | ⚠️ selector 0x09 reports -4..+4, writes stick but showed no luminance change |
| — Manual: ISO | **100 .. 3200** | ❌ selector unknown (0x1b was a misread) |
| — Manual: Shutter | **1/8000s .. 1/30s** | ✅ selector 0x19 (µs) |
| — Manual: Exposure curve | editable curve + reset | 🔍 **selector 0x10 (255 byte table) is the prime suspect** |
| Auto Focus | Auto / M + 0-100% | ✅ V4L2 `focus_automatic_continuous` / `focus_absolute` |
| Temperature | Auto / M + **2000K .. 10000K** | ✅ V4L2 `white_balance_temperature` |
| Brightness / Contrast / Saturation / Sharpness | 0-100% | ✅ V4L2 |
| HDR | toggle | 🔍 **selector 0x07 (1 byte, settable, effect unknown) is the prime suspect** |
| Anti-Flicker | dropdown, Auto | ✅ V4L2 `power_line_frequency` (roughly) |
| Set as startup | toggle | host-side app setting, not a camera control |

### More tab

| Option | Values seen | Linux status |
|---|---|---|
| **Gesture** master switch | on | ✅ selector 0x1b bit 0x10 |
| — AI Tracking gesture | checkbox | ✅ 0x05 bit 0x02 (palm) |
| — Whiteboard gesture | checkbox | ✅ 0x05 bit 0x08 (V) |
| — Zoom gesture | checkbox | ✅ 0x05 bit 0x04 (L) |
| Horizontal Flip | checkbox | 🔍 unmapped (no V4L2 hflip on this camera) |
| Smart Adjustment | checkbox | 🔍 unmapped |
| Horizontal fine-tuning | slider, centre 0, reset | 🔍 unmapped |
| Portrait Resolution and High Frame rate | checkbox (Compatibility) | 🔍 unmapped, probably re-enumerates formats |

### Bottom bar

Mode buttons **AI Tracking / Whiteboard / Overhead / DeskView**, resolution selector
(1080p30), snapshot, record. The four modes are almost certainly bits in the 0x1b
function status word — the same word the gesture master switch lives in.

### Not camera controls at all

`%LOCALAPPDATA%/Insta360/Insta360 Link Controller/virtual_camera_params.json` shows
beauty, background replace, bokeh/blur and spot are **host-side processing** on a
virtual camera, not firmware features. Don't go looking for XU selectors for those.
`en-US.json` in that folder is the full UI string table if more option names are needed.

## 📋 WINDOWS FEATURES TO MAP

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

## 📋 ALL UNIT 9 SELECTORS (Complete Map)

| Sel | Size | RW | Default | Purpose |
|-----|------|-----|---------|---------|
| 0x01 | 4B | RW | 0 | Unknown |
| 0x02 | 52B | RW | complex | Unknown |
| 0x03 | 170B | RO | info | Device info (serial, firmware) |
| 0x05 | 1B | RW | 0x0e | **Gesture bitmask** (palm 0x02, L 0x04, V 0x08) ✅ |
| 0x06 | 5B | RW | zeros | Unknown |
| 0x07 | 1B | RW | 1 | Toggle, settable, **no measurable image effect** (not HDR?) |
| 0x09 | 2B | RW | 0 | **Exposure bias**, -4..+4 signed ✅ |
| 0x0a | 129B | RW | zeros | Unknown |
| 0x0b | 5B | RO | varies | Status |
| 0x0c | 32B | RO | model | **Serial / model ID** string ✅ |
| 0x0d | 129B | RW | hash | Unknown |
| 0x0e | 1B | RW | - | Unknown |
| 0x0f | 12B | RW | varies | Unknown |
| 0x10 | 255B | RO* | ramp | **Exposure curve LUT**, 127 u16 LE identity ramp, writes revert |
| 0x11 | 1B | RO | 0 | Status (not settable) |
| 0x12 | 1B | RW | 1 | **Tracking speed** 1=slow 2=medium 3=fast ✅ |
| 0x13 | 1B | RO | 1 | Status (not settable) |
| 0x14 | 240B | RO | volatile | Telemetry, contents change between reads |
| 0x15 | 8B | RW | zeros | Preset data? |
| 0x16 | 4B | RW | varies | Unknown |
| 0x17 | 129B | RW | hash | Unknown |
| 0x18 | 4B | RW | varies | Unknown |
| **0x19** | 2B | RW | auto | **Exposure time (µs)** ✅ |
| 0x1a | 8B | RW | pan/tilt | **Gimbal position**, 2 int32 LE arc-seconds ✅ |
| **0x1b** | 2B | RW | 0x10 | **Function status bitmask** (0x10 = gestures) ✅ |
| 0x1c | 10B | RW | varies | Unknown |
| 0x1d | 2B | RO | ~33 | Status (not settable) |
| **0x1e** | 1B | RW | 2 | **Exposure mode (0-5)** ✅ |

---

## 📝 TODO

1. [x] Write cameractrls extension class — now `Insta360Ctrls`, shared with the Link 2 family
2. [ ] Verify writes with a stream running: 0x12 tracking speed → 0x09 bias → 0x05 gestures → 0x1b bits
3. [ ] Test 0x07 effect visually (HDR?)
4. [ ] Find HDR toggle
5. [ ] Find the real ISO/gain selector (0x1b was a misread)
6. [ ] Test presets (Unit 10 slots?)
7. [ ] Feed the gen 1 findings back into cameractrls PR #101 / issue #55

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
