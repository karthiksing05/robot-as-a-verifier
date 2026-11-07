# The appliance's Pico

The Pico inside the printed appliance reports its controls to the laptop over USB, and every verdict on the real arm comes from what it reports. On the laptop, `system-1/hardware/pico_readout.py` reads it, and `hw_rig.make_rig(..., readout_port="COM7")` puts it on the rig. Owner: Max. [`main.py`](main.py) is only a starting point.

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
