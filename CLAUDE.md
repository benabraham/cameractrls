# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

cameractrls is a Linux camera control utility providing CLI, GUI (GTK3/GTK4), and camera viewer (SDL2) interfaces for V4L2 cameras. It supports standard V4L2 controls plus manufacturer-specific extensions (Logitech, Razer Kiyo Pro, Dell UltraSharp, AnkerWork).

**This fork** adds Insta360 Link camera support via UVC Extension Units.

## Insta360 Link Extension (Work in Progress)

**Research**: `insta360.md` - reverse engineering notes for UVC Extension Units
**Prototype**: `insta360-ctrl.py` - standalone CLI script for testing

### Device Info
- USB ID: `2e1a:4c01`
- Unit 9 GUID: `faf1672d-b71b-4793-8c91-7b1c9b7f95f8`

### Confirmed Working Controls
| Control | Selector | Size | Notes |
|---------|----------|------|-------|
| Exposure Mode | 0x1e | 1B | 1=manual, 2=auto (default), 3-5=auto variants |
| Shutter Speed | 0x19 | 2B LE | µs, 100-33333, only works in manual mode |
| Gain | 0x1b | 2B LE | 0-100 safe range, >100 crashes camera! |

### TODO
1. Create `Insta360LinkCtrls` class following `KiyoProCtrls` pattern
2. Add to `CameraCtrls` aggregation in `cameractrls.py`
3. Find HDR, tracking mode, gesture controls
4. Test preset storage (Unit 10 slots)
5. Submit PR to upstream

## Running the Applications

No build step required - pure Python with direct execution:

```bash
./cameractrls.py -l                    # List camera controls (CLI)
./cameractrls.py -c brightness=128     # Set controls (CLI)
./cameractrlsgtk.py                    # GTK3 GUI
./cameractrlsgtk4.py                   # GTK4 GUI
./cameraview.py -d /dev/video0         # SDL camera viewer
./cameractrlsd.py                      # Control restore daemon

# Insta360 Link standalone (prototype)
./insta360-ctrl.py                     # Show current values
./insta360-ctrl.py mode manual         # Enable manual exposure
./insta360-ctrl.py shutter 1/60        # Set shutter speed
./insta360-ctrl.py gain 50             # Set gain (0-100)
```

## Architecture

**Core Library** (`cameractrls.py`):
- V4L2 ioctl bindings via ctypes (no external Python packages)
- Extensible control plugin system - each manufacturer has a `*Ctrls` class
- `CameraCtrls` aggregates all control sources (V4L2, format, manufacturer extensions)

**Key Classes**:
- `BaseCtrl` - Abstract base for all controls (integer, boolean, menu, button types)
- `V4L2Ctrls` - Standard V4L2 controls via VIDIOC_QUERYCTRL
- `KiyoProCtrls`, `LogitechCtrls`, `DellUltraSharpCtrls`, `AnkerWorkCtrls` - UVC extension units
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
