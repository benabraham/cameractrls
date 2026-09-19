# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

cameractrls is a Linux camera control utility providing CLI, GUI (GTK3/GTK4), and camera viewer (SDL2) interfaces for V4L2 cameras. It supports standard V4L2 controls plus manufacturer-specific extensions (Logitech, Razer Kiyo Pro, Dell UltraSharp, AnkerWork).

**This fork** adds Insta360 Link camera support via UVC Extension Units.

## Insta360 Link support — state of play

Branch `insta360`, forked from upstream `main`. `insta360.md` is the full reverse
engineering record; read it before touching any selector. `tools/` holds the rig that
produced it.

### Device

- USB ID `2e1a:4c01` (gen 1 Link), firmware `v1.4.5.8_build1`
- Extension unit 9, GUID `faf1672d-b71b-4793-8c91-7b1c9b7f95f8`, 30 selectors
- The Link 2 family (`4c04`-`4c07`) shares the same unit and is served by the same class

**Selector names are not guesses.** They come from the `ControlSelector` protobuf enum
embedded in the vendor's Windows app, cross-checked against two different app builds. Do not
rename or renumber them from inference — see "How the names were recovered" in `insta360.md`.

### Shipping controls

| Control | Selector | Notes |
|---|---|---|
| exposure_mode | 0x1e | 1 manual, 2 auto |
| iso | 0x19 | 100-3200 |
| shutter | 0x1d | **denominator**, 60 means 1/60s |
| exposure_bias | 0x09 | signed, **0.01 EV per unit**, ±300 = ±3.00 EV |
| exposure_curve | 0x10 | 256 points in 3 chunks, cannot be read back |
| hdr, smart_composition, auto_tracking, portrait, horizontal_correction, privacy_mode, high_framerate | 0x1b | bits 0x04, 0x01, 0x100, 0x400, 0x80, 0x800, 0x20 |
| gesture_palm / _l / _v | 0x05 | bits 0x02, 0x04, 0x08; master switch is 0x1b bit 0x10 |
| track_speed | 0x12 | 1 slow, 2 medium, 3 fast |
| composition | 0x13 | 1 head, 2 half body, 3 whole body |
| video_mode | 0x02 | byte 0: 0 normal, 4 whiteboard, 5 overhead, 6 deskview |
| pan_speed / tilt_speed | 0x16 | `[pan sign, pan mag, tilt sign, tilt mag]`, stop is `00 01 00 01` |
| serial | 0x0c | read-only |

### Traps that cost real time

- **XU writes only stick while the camera is streaming.** Written at idle they are accepted,
  echoed by GET_CUR, then silently reverted about a second later. Every test needs an
  `ffmpeg` capture running; `tools/daylight-probe.py` does this for you.
- **0x19 is ISO, not exposure time.** An earlier version wrote microseconds into the ISO
  register and got a plausible brightness change for entirely the wrong reason.
- **0x1b bit 0x20 makes the camera re-enumerate.** That is the portrait / high frame rate
  feature working, not a crash. Writes issued mid-re-enumeration fail with EPROTO.
- **The camera's hub lives in the monitor.** Switch the monitor off and the camera leaves
  the USB bus. Check whether the hubs went with it before suspecting the device.
- **GET_MIN / GET_MAX are unreliable.** 0x09 reports ±4 when the real range is ±300.

### How this reaches the system

The NixOS config consumes this branch as a flake input, so a change is not testable until it
is pushed:

1. commit and push to `insta360`
2. in `~/nixos`: `nix flake update cameractrls-insta360`, and **commit `flake.lock`**
3. ask the user to run the rebuild — **the assistant must never run it**, it is blocked
   by a hook and by that repo's own rules

The NixOS config is a separate repo at `~/nixos` with its own CLAUDE.md, which will not
be loaded when working here. What matters from it: the rebuild command is the user's to
run, and `flake.lock` is committed there, not here.

`configuration.nix` overrides the nixpkgs package's `src` with the input. Going through the
package matters: it rewrites `cameraview.py`'s `find_library('SDL2-2.0')` call with a store
path, so running this source directly has **no preview**. A local path cannot be used,
pure flake evaluation rejects it.

For quick iteration without a rebuild, `cameractrls.py -c` works straight from the checkout;
only the GTK GUI and the preview need the packaged build.

### Code traps in this file

- **A boolean from the command line is the string `'0'`, which is truthy.** Every boolean
  path goes through `to_bool()`. Getting this wrong made `insta360_hdr=0` turn HDR on, and
  the bug came in with PR #101's code.
- **`to_buf()` returns one byte more than you asked for.** `ctypes.create_string_buffer()`
  appends a NUL, so `Insta360Ctrls.query()` had to slice back to `length`. Any control that
  reads a register and writes it back — `insta360_video_mode` is the only one — otherwise
  hands uvcvideo an oversized payload and **every write fails with ENOBUFS**. It failed
  silently for a month because nothing else round-trips a read into a write.
- **usbmon's text interface truncates payloads at 32 bytes.** Anything larger — the 52 byte
  video mode struct, the 255 byte curve, the PTZ commands — needs `tools/usbmon-bin.py`,
  which reads the binary interface. Its header is 48 bytes on the `read()` path; the 64 byte
  layout belongs to the mmap ABI only.

### Camera quirks that are not bugs in this code

- **The gimbal does not move at all unless something is streaming.** The relative move
  command at 0x16 is accepted and reads back correctly, and nothing happens. Same root cause
  as the general write-while-streaming rule, but worth stating separately because the
  register looks fine while the camera sits still.
- **The gimbal position lives in the video mode struct**, selector 0x02, pan at offset 38
  and tilt at offset 42 as int32 in tenths of a degree, zoom at 50. `XU_PANTILT_ABSOLUTE`
  0x1a reads zeros forever and the vendor app never polls it either. Position reads work
  with the camera idle; only writes need a stream.
- **V4L2 `pan_absolute` reads back the last value written, not the position.** Pan and tilt
  share one UVC control, so after a speed move, writing either axis snaps the other back to
  its stale value. Measured: a speed pan to 73.9° was undone by a tilt write.
- **Hue is accepted and ignored.** Driving V4L2 hue across its full ±15 moved mean RGB by
  about 1, less than the drift between two readings at the same setting. The other colour
  controls work.
- **The gimbal coasts** roughly 6° after a stop, which is why the position poll keeps running
  for three seconds after the speed returns to zero.

### GUI behaviour worth knowing before changing it

- The speed sliders are `zeroer`: releasing the mouse returns them to zero, which is what
  stops the gimbal. **Scrolling a slider never produces a button release**, so that path had
  to be handled separately or the camera kept panning forever.
- Absolute pan and tilt are polled while a speed is non-zero. Movement over the extension
  unit emits no `V4L2_EVENT_CTRL`, so the GUI has nothing to react to and the sliders would
  show a stale position.
- The camera's own V4L2 `pan_speed` and `tilt_speed` are dropped when `Insta360Ctrls` loads.
  It advertises them, reports a zero range, then fails every write with EIO.

### Acceptance checklist — the gate before any upstream PR

Every control must be confirmed working by the user, or have a bug filed, before this goes
upstream. Status is honest about *how* each was established, because bits named by lining
send timestamps against a usbmon capture have already been wrong once.

| Control | Status | How it stands today |
|---|---|---|
| `insta360_exposure_mode` | ✅ measured | manual mode changes the image |
| `insta360_iso` | ✅ measured | 100→3200 ladder, near linear |
| `insta360_shutter` | ✅ measured | nine stops, halving each time |
| `insta360_exposure_bias` | ✅ measured | ±3 EV sweep in daylight |
| `insta360_high_framerate` | ✅ measured | format list gains 50/60 fps and portrait |
| `insta360_pan_speed` / `_tilt_speed` | ✅ measured | the gimbal's own position readout confirms a speed write moves it and the stop halts it; GUI sliders still untested |
| `insta360_track_speed` | ✅ user confirmed | blind A/B, fast vs slow |
| `insta360_composition` | ✅ user confirmed | head crops tighter than whole body, effect weak at distance |
| `insta360_gesture_palm` | ✅ user confirmed | A/B, bit off means the gesture stops firing |
| `insta360_portrait` | ✅ user confirmed | switches portrait/landscape — **was mislabelled single tap tracking** |
| `insta360_serial` | ✅ | matches the sticker |
| `insta360_gesture_l` / `_v` | ⚠️ inferred | from PR #101, never isolated in a test |
| `insta360_hdr` | ⚠️ capture only | bit captured from the vendor protocol, effect never seen |
| `insta360_auto_tracking` | ⚠️ capture only | same |
| `insta360_privacy_mode` | ⚠️ capture only | same |
| `insta360_smart_composition` | ⚠️ timestamp only | the weakest evidence class |
| `insta360_horizontal_correction` | ⚠️ timestamp only | same |
| `insta360_video_mode` | ✅ measured | all four modes set and read back; overhead tilts to -90°, deskview to -45°, whiteboard leaves the gimbal alone |
| `insta360_exposure_curve` | ⚠️ writes clean | all five presets write, framing confirmed against the vendor's capture, visual effect still unmeasured |

Also unconfirmed, all added 2026-09-19: the scroll-stop guard and the dead V4L2 speed
controls disappearing. The position poll was **rewritten** — it used to read V4L2
`pan_absolute`, which never updates; it now reads the extension unit, which does.

### Task at hand

Both remaining "never driven through cameractrls" items were driven on 2026-09-19, and one
of them was broken:

1. `insta360_video_mode` — **fixed and working**. Every write had been failing with ENOBUFS
   because `Insta360Ctrls.query()` returned one byte more than the register holds. All four
   modes now set and read back.
2. `insta360_exposure_curve` — all five presets write without error, and the chunk framing
   was independently confirmed against the vendor's own capture. Whether they *look*
   different is still unmeasured; the test needs daylight.

What still needs a person watching the image: **smart composition, horizontal correction,
composition style**, plus the visual effect of the video modes and the curve presets. Those
bits were named by lining send timestamps up against a usbmon capture, which is how the
portrait bit came to be mislabelled.

```bash
D=/dev/v4l/by-id/usb-Insta360_Insta360_Link-video-index0
ffmpeg -nostdin -loglevel error -f v4l2 -input_format mjpeg -video_size 1280x720 \
  -framerate 30 -i $D -f null - &          # writes need a live stream, reads do not
./cameractrls.py -d $D -c insta360_video_mode=overhead
./cameractrls.py -d $D -c insta360_exposure_curve=bright
```

### Next steps, in order

1. **Verify the video mode fix on hardware.** The payload now matches the vendor app byte
   for byte, including the 3610 "leave the gimbal alone" sentinel; before that every mode
   change also commanded a move, which is why the modes behaved oddly. Untested since the
   change. Then the remaining bits that need a person watching: smart composition,
   horizontal correction, composition style, and the curve presets in daylight.
2. **One small upstream PR: the PTZ key handler guard.** This is the only fix here that is a
   genuine upstream bug, re-verified against `upstream/main` (still 6f38825 on 2026-09-19).
   **Issue #91 is not it** — that one is an AnkerWork C310 FOV menu `ValueError` in
   `AnkerWorkCtrls.setup_ctrls`, unrelated. So nothing upstream describes this crash.
   The fix has to cover **both** handlers: guarding only `key_pressed` leaves
   `key_released` to raise on the very next event, which is the shape our branch shipped
   until 2026-09-19. It must also not swallow the zoom keys — `handle_ptz_speed_key_pressed`
   falls through to `handle_ptz_key_pressed_zoom`, so an early return disables zoom for
   exactly the camera that triggers the bug. `V4L2_CTRL_ZEROERS`
   includes `ZOOM_CONTINUOUS`, the GUI attaches `handle_ptz_speed_key_pressed` to *any*
   zeroer slider, and the handler unconditionally dereferences `self.pan_speed_sc`. A camera
   with continuous zoom and no pan/tilt speed raises `AttributeError` on an arrow key.
   Present in both GTK3 and GTK4. Nothing open upstream describes it — searches for
   `zoom_continuous` and `AttributeError` return zero. Read issue #91 "ValueError with GTK
   client" first in case it is the same crash reported vaguely.
3. **Comment on PR #101, do not open a competing PR.** Two of the fixes on this branch are
   *not* upstream bugs and must not be presented as such:
   - the `to_bool()` fix belongs to **PR #101's own unmerged code** (`hdr=0` turned HDR on,
     because the string `'0'` is truthy). It is theirs to fix; upstream `main` has no
     Insta360 code at all.
   - binding the key handler to `insta360_pan_speed` only matters because *we* added those
     controls. It is not upstreamable on its own.

   What is worth telling #101: their Link 2 selector guesses are **confirmed correct on gen 1
   hardware**, their gesture controls are never placed on a `CtrlPage` so they fall through
   to Advanced/Other, and the protobuf-enum extraction trick removes the guesswork entirely.
4. **Expect upstream to be slow.** Five PRs are open, oldest from February 2026, none merged;
   PR #101 has sat since March. PR #107 adds an HDR control for an Elgato Facecam — read how
   they modelled it before proposing ours, since it is the same shape of problem.
5. **Force-push `insta360`.** It was rebased onto upstream main, so `origin/insta360` has
   diverged. Backup ref: `insta360-pre-rebase-backup`.
6. **Open leads.** Four were closed on 2026-09-19 without the VM, see the 0x04 section
   in `insta360.md`:
   - `0x04 XU_PTZ_CMD` is **mapped** — `a5 d0 cmd len crc` + payload, an unsupported command
     answers `0xff`, and thirteen commands exist. The CRC is recovered from the exe and
     reproduces the vendor's bytes exactly; gen 1 ignores it, Link 2 may not
   - video mode id 1 is **AUTO_COMPOSITION**, from the vendor's own `VideoModeType` enum
   - unit 10 is **not presets** — it is the second GUID the vendor's UVC layer looks for,
     and the source path around it says PUC2, the Link 2 family
   - `DeviceSettingInfo` fields **56-65 are named** — beauty, makeup, green screen, 4K,
     bokeh, pitch. All host-side compositing; the newer app adds **no new XU selector**

   The position question is also answered: **a `pan_absolute` write does drive the motor**,
   and the gimbal's real position is in the 0x02 struct, not in 0x1a.

   **Presets are host side.** A capture of the vendor app saving and recalling one shows no
   0x04 traffic at all: it writes the stored position into the 0x02 struct and re-sends the
   exposure curve. The camera stores nothing. The 0x32 hypothesis is dead.

   Still open:
   - **which 0x04 command makes the gimbal run away.** Do not sweep the range again to find
     out; test one id at a time, with a hand on the cable
   - byte 1 of the 0x02 struct, the last unnamed field on the camera side. Seen as 0x00,
     0x01 and 0x10; it follows none of auto tracking, smart composition, portrait, HDR or
     the gesture master bit
7. **Not reachable, stop looking.** Horizontal fine-tuning, smart adjustment, mirror H/V,
   audio capture modes and the rock/OK gestures produce **zero** bus traffic when driven
   through the vendor's own protocol. The app does them host-side or the gen 1 firmware
   lacks them; `supportAudioCaptureMode` in the app's capability list confirms the latter.

### Where the evidence lives

Everything needed to continue is in this repo. These sit outside it and are referenced:

| Path | What | If it is gone |
|---|---|---|
| `../Screenshot 2025-12-10 2005*.png` | 8 shots of the Windows app UI, the source of the option inventory | originals also at `/mnt/winos/Users/DanielSrb/Downloads/` |
| `~/vm/cap*.txt`, `~/vm/xu*.txt` | raw usbmon captures, ~23MB | the findings are all transcribed into `insta360.md`; only re-capture if a new selector is needed |
| `~/vm/win11.qcow2` | the Windows VM with the vendor app installed | needed only for the discovery rig below |
| `~/vm/insta360-app-2.2.4.14.exe` | the **newer** app build, pulled out of the VM | `tools/vendor-proto.txt` was generated from it; the partition copy is 2.0.6.2 and stops at `DeviceSettingInfo` field 55 |
| `/mnt/winos/Program Files/Insta360 Link Controller/` | the app binary the protobuf enums came from | the extracted enums are in `insta360.md` |

The vendor default exposure curve was the one thing that existed *only* in a capture; it is
now `tools/vendor-default-curve.txt`.

### The discovery rig, when a selector needs finding

The method that found HDR after luminance testing had failed on it:

1. Windows 11 in libvirt, camera passed through with `virsh attach-device`
2. `virsh -c qemu:///system attach-device win11 tools/insta360-hostdev.xml --live`, and the
   same with `detach-device` to take it back. A detach sometimes leaves the interfaces bound
   to `usbfs` with no `/dev/video0`, fixed by a replug or by rebinding `3-1.4`
3. `sudo tools/usbmon-bin.py 3 --seconds 240 --out cap.txt --all` on the **host** — QEMU
   passes USB through usbfs, so the transfers still cross the host kernel
4. `tools/insta360-ws.py --url '<qr url>' --set hdr=1` drives the app's own remote protocol.
   **The URL comes from the QR code in the app's sidebar and its token changes every run**,
   so it cannot be recorded here — read it off the app each session
5. The capture shows exactly which selector the app wrote

`insta360-ws.py --dump-state` also prints the app's full 50-field view of the camera, which
is the authoritative list of what the hardware supports.

## Running the Applications

No build step required - pure Python with direct execution:

```bash
./cameractrls.py -l                    # List camera controls (CLI)
./cameractrls.py -c brightness=128     # Set controls (CLI)
./cameractrlsgtk.py                    # GTK3 GUI
./cameractrlsgtk4.py                   # GTK4 GUI
./cameraview.py -d /dev/video0         # SDL camera viewer
./cameractrlsd.py                      # Control restore daemon

# Insta360 Link research tools, see tools/README.md
./tools/insta360-ctrl.py               # Standalone read/set of the confirmed selectors
./tools/daylight-probe.py              # Measure a selector against frame statistics
./tools/xu-probe.py --scan             # Raw read/write of any selector on any unit
./tools/extract-proto.py               # The vendor app's protobuf schema, straight from the exe
./tools/insta360-ws.py --dump-state --url '<qr url>'   # The app's own remote protocol
```

## Architecture

**Core Library** (`cameractrls.py`):
- V4L2 ioctl bindings via ctypes (no external Python packages)
- Extensible control plugin system - each manufacturer has a `*Ctrls` class
- `CameraCtrls` aggregates all control sources (V4L2, format, manufacturer extensions)

**Key Classes**:
- `BaseCtrl` - Abstract base for all controls (integer, boolean, menu, button types)
- `V4L2Ctrls` - Standard V4L2 controls via VIDIOC_QUERYCTRL
- `KiyoProCtrls`, `LogitechCtrls`, `DellUltraSharpCtrls`, `AnkerWorkCtrls`, `Insta360Ctrls` - UVC extension units
- `ConfigPreset`, `ColorPreset` - Save/restore control presets
- `PTZController`, `PTZHWControllers` - Pan/Tilt/Zoom input handling

**PTZ Hardware Input** (separate processes):
- `cameraptzgame.py` - Game controllers (PS5, Xbox)
- `cameraptzmidi.py` - MIDI controllers
- `cameraptzspnav.py` - SpaceMouse 6DoF

## Code Style

- No type hints
- f-strings for formatting
- ctypes for all V4L2/SDL2/native library bindings
- No external Python package dependencies
- Control classes use `setup_ctrls()` and `get_ctrls()` interface pattern

## Dependencies

Native libraries only (no pip packages):
- `libSDL2-2.0`, `libturbojpeg` - for cameraview.py
- GTK 3.0 or 4.0 - for GUI applications
- `libspnav` - optional SpaceMouse support

## Adding Camera Support

To add support for a new camera's proprietary controls:
1. Create a new `*Ctrls` class inheriting control patterns from existing extensions
2. Implement UVC extension unit queries using `uvc_xu_control_query`
3. Add to the `CameraCtrls` class aggregation list in `cameractrls.py`
