# Vendor default exposure curve

The three writes the Windows app sends to `0x10` to load its stock linear curve, captured
verbatim. Replay them in order to restore the camera to the vendor default — the curve
cannot be read back, so this file is the only way to get exactly those bytes again.

```python
cam = Camera()                      # tools/daylight-probe.py
for line in open('vendor-default-curve.txt'):
    cam.write(0x10, bytes.fromhex(line.strip()))
    time.sleep(0.1)
```

The camera must be streaming for the writes to stick.
