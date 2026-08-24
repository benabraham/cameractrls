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
| hdr, smart_composition, auto_tracking, single_tap_tracking, horizontal_correction, privacy_mode, high_framerate | 0x1b | bits 0x04, 0x01, 0x100, 0x400, 0x80, 0x800, 0x20 |
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

### Task at hand

Three code paths are implemented but have **never been exercised against hardware**, because
the camera went offline right after they were written. Everything they rest on is verified;
it is the cameractrls plumbing that has not run.

1. `insta360_pan_speed` / `insta360_tilt_speed` — the 0x16 protocol is confirmed on the
   device (a 2 second burst at magnitude 8 swung the gimbal ~40°, reversible), but never
   through `cameractrls.py -c`.
2. `insta360_video_mode` — read path and the byte-0-in-52-byte-struct write path.
3. `insta360_exposure_curve` — the chunked protocol is confirmed (gamma 2.2 vs 0.5 moved p5
   from 31 to 47 with p95 held), but the five presets have not been driven through the menu.

To verify, with the monitor on so the camera is present:

```bash
D=/dev/v4l/by-id/usb-Insta360_Insta360_Link-video-index0
ffmpeg -nostdin -loglevel error -f v4l2 -input_format mjpeg -video_size 1280x720 \
  -framerate 30 -i $D -f null - &          # writes need a live stream
./cameractrls.py -d $D -c insta360_pan_speed=8      # gimbal should sweep right
./cameractrls.py -d $D -c insta360_pan_speed=0      # and stop
./cameractrls.py -d $D -c insta360_video_mode=overhead
./cameractrls.py -d $D -c insta360_exposure_curve=bright
```

### Next steps, in order

1. **Verify the three paths above**, then drop this list to whatever is left.
2. **One small upstream PR: the PTZ key handler guard.** This is the only fix here that is a
   genuine upstream bug, verified against `upstream/main` (6f38825). `V4L2_CTRL_ZEROERS`
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
6. **Open leads**, all needing the Windows app in a VM plus a usbmon capture:
   - presets, unit 10 selectors 0x03-0x05, currently reading zeros
   - `0x04 XU_PTZ_CMD`, a 262 byte command channel seen once as `a5 d0 03 00 f1 32 ...`
   - video mode id 1, observed once and unidentified
   - the ten `DeviceSettingInfo` fields (56-65) the app's own web client does not decode
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
