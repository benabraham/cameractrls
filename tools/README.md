# Insta360 Link research tools

Not part of cameractrls. These are what mapped the extension unit, kept here so the work is
reproducible on a firmware or app update. See `../insta360.md` for the findings.

| Tool | What it does |
|---|---|
| `insta360-ctrl.py` | Standalone read/set of the confirmed selectors, no cameractrls needed |
| `xu-probe.py` | Raw read/write of any selector on any unit. Asks the device for its own lengths, so it needs no table to explore one |
| `extract-proto.py` | Prints the vendor app's whole protobuf schema out of the exe. Output checked in as `vendor-proto.txt` |
| `daylight-probe.py` | Measures a selector's effect against frame statistics. Needs real light |
| `insta360-ws.py` | Speaks the Windows app's own remote-control protocol, protobuf over a WebSocket. Drives any of the 61 ParamTypes and dumps the app's full device state |
| `usbmon-xu.py` | Decodes a usbmon **text** capture into named XU transfers. Payloads truncated at 32 bytes |
| `usbmon-bin.py` | Same, from the usbmon **binary** interface, with full payloads. Needs root |

The rig that found HDR: run the Windows app in a VM with the camera passed through, capture
the host's usbmon, drive a feature with `insta360-ws.py`, decode with `usbmon-*.py`. The app
performs the feature, the bus shows which selector it used.

`vendor-proto.txt` is generated from app **2.2.4.14**, kept at
`~/vm/insta360-app-2.2.4.14.exe` — the copy installed on the Windows partition is 2.0.6.2 and
its schema stops ten fields short. It is the cheaper oracle and needs no VM: the exe is a C++ protobuf build,
so every `.proto` it was compiled from sits in it verbatim. Selector numbers, `ParamType`
ids, enum names and every `DeviceSettingInfo` field come from there, not from inference.
