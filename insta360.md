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

### ⚠️ 0x1b bit 0x20 disconnects the camera

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
| — Auto: EV bias | **0.0EV .. 3.0EV** (±3 EV) | ✅ selector 0x09, 0.01 EV units, ±300 |
| — Manual: ISO | **100 .. 3200** | ❌ selector unknown — but the app log proves one exists (0x1b and 0x16 both ruled out) |
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

## 📋 UNIT 9 SELECTORS — AUTHORITATIVE MAP

The names below are **not guesses**. The Windows app embeds its own protobuf
`ControlSelector` enum, and the descriptor carries the numbers. See "How the names were
recovered" below to redo it. ✅ = verified on this camera, gen 1, firmware v1.4.5.8_build1.

| Sel | Official name | Len | RW | Meaning / value seen |
|---|---|---|---|---|
| 0x01 | XU_EXEC_SCRIPT_CONTROL | 4 | rw | zeros |
| 0x02 | XU_VIDEO_MODE_CONTROL | 52 | rw | AI Tracking / Whiteboard / Overhead / DeskView. Tail holds ints -33, -809, 0, 100 — looks like pan, tilt, ?, zoom×100 |
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
| 0x10 | XU_UPLOAD_FILE / XU_EXPOSURE_CURVE | 255 | rw* | ✅ **exposure curve LUT**: 127 × u16 LE at offset 1, identity ramp 0,0,4…500. Writes revert |
| 0x11 | XU_USB_MODE_SWITCH_CONTROL | 1 | rw | 0. **Do not write** — it can change how the device enumerates |
| 0x12 | XU_TRACK_SPEED_CONTROL | 1 | rw | ✅ tracking speed, **1 slow, 2 medium, 3 fast**, confirmed by blind A/B. Vendor labels them Slow, Ordinary, Quick |
| 0x13 | XU_LAYOUT_STYLE_CONTROL | 1 | rw | ✅ composition, **1 Head, 2 Half Body, 3 Whole Body**, 0 rejected. Direction confirmed with a person in frame, but the effect is weak at distance on this firmware |
| 0x14 | XU_HEAD_LIST_CONTROL | 240 | ro | ✅ **detected head boxes as floats**. All-zero with nobody in frame, populated otherwise |
| 0x15 | XU_TRACK_TARGET_CONTROL | 8 | rw | zeros |
| 0x16 | XU_PANTILT_RELATIVE_CONTROL | 4 | rw | 768, 768 |
| 0x17 | XU_MOBVOI_PUBKEY_CONTROL | 129 | rw | per-device blob, don't paste |
| 0x18 | XU_BIAS_CONTROL | 4 | rw | 48, 2643. Distinct from 0x09 — the ParamType enum groups PARAM_BIAS with the PTZ family, so this is likely the horizontal fine-tuning |
| 0x19 | XU_ISO_CONTROL | 2 | rw | ✅ **ISO**. 100 → luminance 3.8, 400 → 10.2, 1600 → 26.4, 3200 → 40.5 |
| 0x1a | XU_PANTILT_ABSOLUTE_CONTROL | 8 | rw | ✅ 2 × int32 LE in arc-seconds, matches the V4L2 pan/tilt |
| 0x1b | XU_FUNC_ENABLE_CONTROL | 2 | rw | ✅ function bitmask, 0x10 = gestures. **Never write bits ≥ 0x20, 0x20 drops the camera off the bus** |
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
4. [ ] Find the HDR toggle. Ruled out: AE modes, low 0x1b bits, any selector of its own. Left: the 0x02 video-mode struct or the command channel
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
