# MC-6 — electronics and controller behaviour

The controller code is `../../firmware/MC6_firmware/MC6_firmware.ino` (Arduino Uno + Grove Base Shield v2). This page is the summary. Wiring pictures: `schematic.png`, `grove_ports.png`, and the full guide `../../firmware/MakeCU_Electronics_Guide.pdf`.

The Uno doesn't fit inside the centrifuge. The Uno, shield and a half breadboard sit beside or behind it; wires go in through the open back.

## Channels (serial event names)
| Channel (`ev`) | Hardware | Pin | Value | CAD body |
|---|---|---|---|---|
| `power` | SPDT toggle | D5 | 1 = ON | `ref_toggle_lever` |
| `btn_start` | 16 mm pushbutton | D2 | 1 = pressed | `cap_start` |
| `btn_stop` | 16 mm pushbutton | D3 | 1 = pressed | `cap_stop` |
| `btn_time` | 16 mm pushbutton | D4 | 1 = pressed | `cap_time` |
| `speed` | 10 kΩ pot | A0 | 1000–6000 rpm, step 100 | `dial_knob` |
| `lid` | Grove Light Sensor v1.2 | A1 | 1 = closed (shaded) | `ref_light_lid`, shaded by `lid_sensor_fin` |
| `tube` | Grove Light Sensor v1.2 under well A | A2 | 1 = seated (shaded) | `ref_light_tube`, shaded by the tube |
| `time` | — | — | seconds (set, or left while running) | |
| `run` | — | — | `start`, `stop`, `done`, `refused:LID`, `refused:TUBE`, `abort:LID` | |
| display | SSD1306 OLED 128×64, I2C 0x3C | A4/A5 | 2 lines of 2×-size text | `ref_oled` |
| light | NeoPixel ring, 24 × WS2812B | D6 | colour + animation | `ref_ring` |

Buttons are wired pin → GND with `INPUT_PULLUP`, 20 ms debounce, no auto-repeat.

## Light sensors
- They have no emitter. A closed lid or a seated tube shades them and the reading drops.
- At power-up (and on the `cal` command) the firmware averages 16 readings as the "open/empty" level. **Power up with the lid open and no tube in well A.**
- Shaded below 55 % of that level, clear again above 70 %. 8-sample average every 50 ms.
- The ring lights the tube sensor from below, so the tube is only read while the ring shows **steady white** (READY) for at least 300 ms. START uses the last such reading.

## States, display and light
| State | Display (line 1 / line 2) | Ring |
|---|---|---|
| OFF (toggle down) | blank | off |
| READY | `1000rpm` / `0:30` (live) | white, steady |
| RUNNING | `4500rpm` / `0:12` (counting down) | blue, 3-LED segment rotating; faster at higher rpm |
| DONE | `DONE` | green, steady |
| REFUSED | `LID` or `TUBE` | red, steady |

The board stays powered and on serial when the toggle is OFF; OFF only blanks the UI and ignores the buttons (their events still go out).

## What each control does in each state
| | OFF | READY | RUNNING | DONE | REFUSED |
|---|---|---|---|---|---|
| POWER → ON | → READY, 1000 rpm, 30 s | — | — | — | — |
| POWER → OFF | — | → OFF | → OFF (`run:stop`) | → OFF | → OFF |
| START | nothing | lid open → REFUSED `LID`; no tube → REFUSED `TUBE`; else → RUNNING | nothing | same as READY | same as READY |
| STOP | nothing | time back to 30 s | → READY (`run:stop`), time kept | → READY | → READY |
| TIME+ | nothing | +10 s, max 600 s | nothing | +10 s, → READY | +10 s, → READY |
| SPEED dial | tracked, not shown | changes speed | ignored | tracked | tracked |
| Lid opens | — | — | → REFUSED `LID` (`run:abort:LID`) | → READY | — |
| Lid closes | — | — | — | — | `LID` → READY |

- RUNNING counts down once a second (a `time` event each second). At 0 → DONE (`run:done`).
- DONE returns to READY when the lid opens or after 60 s.
- REFUSED `TUBE` clears on any button press.

## Serial protocol
115200 baud, one JSON object per line. Boot: `{"ev":"hello","dev":"MC-6","fw":"1.0","ram":…}`, then a `cal` line. Each change: `{"t":ms,"ev":name,"v":value}` (light sensors add `"raw"`). Heartbeat every second: `{"ev":"hb",…}` with every input, raw sensor values, calibration levels, the display lines and the ring colour. Commands: `ping`, `status`, `cal`, `reset`.

## Power
USB 5 V, ~350 mA worst case (ring capped at brightness 50/255).
