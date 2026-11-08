# The appliance's Pico

The Pico inside the printed appliance reports its controls to the laptop over USB, and every verdict on the real arm comes from what it reports. On the laptop, `system-1/hardware/pico_readout.py` reads it, and `hw_rig.make_rig(..., readout_port="COM7")` puts it on the rig. `rav-server --robot real ... --readout serial --readout-port COM7` uses it; [over WiFi](#over-wifi) the board POSTs the same snapshots instead. Owner: Max. [`main.py`](main.py) is only a starting point.

## What the Pico sends

One JSON object per line, on the USB serial port that MicroPython's `print` writes to. Each line holds the current value of every control:

```
{"BTN1": 0, "BTN2": 1, "BTN3": 0, "DOOR": 0, "LCD": "BTN 2"}
```

- **Channel names** follow the sim's devices: `BTN1`, `BTN2`, ... for buttons in panel order (`button_1` is `BTN1`), `DOOR` (1 when open), `POWER` for a toggle, `MODE` for a dial's position, `TEMP` for a knob, `FAN` for a slider.
- **Switches and positions are ints.** The laptop logs every change in one, and a press only passes with that change logged.
- **Continuous values are floats**, such as a slider from 0.0 to 1.0. Always send them with a decimal point (`1.0`, not `1`), because an int would read as a switch. Their changes aren't logged; slides compare the value before and after.
- **`LCD`** is optional: the text on the display.
- **Send a line as soon as anything changes, and at least every 0.5 s otherwise.** A button press can be shorter than any fixed rate, and 2 s without a line tells the laptop the Pico is gone, which stops the next test.
- **Debounce switches, and move a float only past a deadband.** The laptop compares readings for equality, so a flickering value looks like the control moving.

Anything that isn't a JSON object on one line is skipped, so boot messages and tracebacks do no harm. The laptop also drops whatever came before it opened the port, which is another reason to repeat the line.

## Trying it

Close Thonny first: Windows lets one program at a time open the port. Device Manager shows the Pico as a USB serial device (COMn), and `python -m serial.tools.list_ports -v` lists it too. Then:

```
python -m serial.tools.miniterm COM7      # the lines as they come; Ctrl+] to quit
```

```python
import pico_readout                       # from system-1/hardware
r = pico_readout.PicoReadout("COM7")
r.readings, r.events, r.lcd
r.close()
```

## Over WiFi

A board on the WiFi (UNO R4 WiFi, Pico W, ESP32) can send the same snapshots to rav-server over HTTP instead of USB. Nothing about the snapshot changes: the same flat object, on every change and at least every 0.5 s.

```
POST http://<System 1 laptop>:8780/readout/<device>
Authorization: Bearer <RAV_DEVICE_KEY>
Content-Type: application/json

{"BTN1": 0, "BTN2": 1, "DOOR": 0, "LCD": "BTN 2"}
```

| Reply | Meaning |
|---|---|
| 204 | taken |
| 400 | not one flat JSON object (values must be numbers, strings, bools or null) |
| 401 | wrong key. The device key is `RAV_DEVICE_KEY`, never `RAV_TOKEN`: a board can feed readings but never move the arm |
| 404 | rav-server was started for another `--readout-device` |
| 413 | over 4 KB |

Start the server for it, on the laptop's LAN address, with both keys set and different:

```
RAV_TOKEN=... RAV_DEVICE_KEY=... uv run rav-server --robot real --arm-port COM5 --calibration makecu.json --host 0.0.0.0 --readout http --readout-device mw1
```

Until the first POST, no test step runs (it stops with "no readings yet"), and 2 s without one stops the next step, as with USB. On Windows, allow port 8780 inbound in the firewall.

Check it from any laptop on the WiFi, or post by hand to try the server without a board:

```
curl -H "Authorization: Bearer $RAV_DEVICE_KEY" http://<laptop>:8780/readout/mw1
curl -X POST -H "Authorization: Bearer $RAV_DEVICE_KEY" -H "Content-Type: application/json" -d '{"BTN1": 1}' http://<laptop>:8780/readout/mw1
```

The MC-6 and MW-1 sketches (`appliances/{centrifuge,microwave}/firmware/`) do this on an UNO R4 WiFi; their firmware README has the setup. [`wifi_uno_r4/`](wifi_uno_r4/wifi_uno_r4.ino) is a starting point for a new appliance, with placeholder pins. Each uses the same `rav_wifi.h`; copy `arduino_secrets.h.example` to `arduino_secrets.h` (gitignored) and fill it in. Each still sends over USB too. In `system-1/hardware`, `http_readout.HttpReadout` is the laptop's side; `rav_server/device_api.py` serves the endpoint.
