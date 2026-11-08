# Wiring (MC-6 v7)

Arduino Uno + Grove Base Shield v2 (VCC switch on 5 V), beside or behind the centrifuge; wires go in through the open
back. Source: `source/electronics/electronics.md` and the firmware `firmware/MC6_firmware/MC6_firmware.ino` (v1.0). Where
they differ, the firmware is what runs (notes at the end). All grounds common.

| Part | Pin | Mode | Reads |
|---|---|---|---|
| START, 16 mm panel pushbutton | D2 → GND | INPUT_PULLUP | pressed = LOW |
| STOP, 16 mm panel pushbutton | D3 → GND | INPUT_PULLUP | pressed = LOW |
| TIME+, 16 mm panel pushbutton | D4 → GND | INPUT_PULLUP | pressed = LOW |
| POWER, SPDT mini toggle | D5 → GND | INPUT_PULLUP | ON = LOW. Software power: the board stays on and on serial when OFF |
| NeoPixel ring, 24 × WS2812B (GRB) | D6 | output | brightness capped at 50/255 |
| SPEED, WH148 10 kΩ pot | A0 | analog | 0-1023 over the 270° sweep, clockwise up (`SPEED_INVERT` false) |
| Lid light, Grove Light Sensor v1.2 | A2 | analog | shaded by the lid's fin = lid closed |
| Tube light, Grove Light Sensor v1.2, under well A | A1 | analog | shaded by a seated tube |
| SSD1306 OLED 128 × 64, I2C 0x3C | A4/A5 (header SDA/SCL) | I2C | two lines of 2× text |
| USB | | | power and serial |

Buttons and toggle: 20 ms debounce, no auto-repeat. Light sensors: calibrated at boot (and on `cal`) as the open level,
16 readings, **with the lid open and no tube in well A**; 8-sample average every 50 ms; shaded below 55 % of that level,
clear again above 70 %. The tube light is only judged while the ring has shown steady white (READY) for 300 ms, because
the ring lights it from below; START uses the last such judgement.

## Serial stream (ground truth for the verifier)

115200 baud, one JSON object per line. Boot: `{"ev":"hello","dev":"MC-6","fw":"1.0","ram":…}`, then a `cal` line, then
`power`. Each change: `{"t": ms, "ev": name, "v": value}` (the light sensors add `"raw"`). Heartbeat every second:
`{"ev":"hb","state":…,"power","btn_start","btn_stop","btn_time","speed","speed_raw","time","left","lid","lid_raw",
"lid_cal","tube","tube_raw","tube_cal","lcd":[line1, line2],"ring"}`. Commands: `ping`, `status`, `cal`, `reset`.

| ev | v | Sent when |
|---|---|---|
| power | 0 / 1 | toggle flips |
| btn_start, btn_stop, btn_time | 1 down, 0 up | button changes (also while OFF: only the UI ignores them) |
| speed | rpm, 1000-6000 in steps of 100 | the dial crosses a step (with 6 counts of hysteresis); not sent while OFF or RUNNING, though rpm still follows the dial |
| lid | 1 closed (shaded) / 0 open | the lid light changes |
| tube | 1 seated (shaded) / 0 clear | the tube light's judgement changes (READY only) |
| run | `start`, `stop`, `done`, `refused:LID`, `refused:TUBE`, `abort:LID`, `reset` | run state changes |
| time | seconds | TIME+, STOP in READY (back to 30), and each second of a run (the time left) |

In the sim (`device.yaml`'s firmware) the channels are the same names. `time` holds the set time, as the heartbeat does;
the countdown is on the display. `speed_raw` is the heartbeat's wiper reading. `tube_raw_1` and `tube_raw_2` stand in for
the heartbeat's `tube_raw`, as 1 when tube 1 or tube 2 shades the tube light (one per tube: a sim sensor watches one
object).

## Where the firmware and electronics.md differ (the firmware wins)

- **Speed at power-on.** electronics.md: POWER → ON gives "READY, 1000 rpm, 30 s" (the manual says the same). The
  firmware's `powerOn()` resets the time to 30 s but reads the speed from the dial, so it shows wherever the dial is.
- **Dial while RUNNING.** electronics.md: "ignored". The firmware keeps updating rpm (no `speed` event), and RUNNING's
  display shows the new rpm at its next second.
- **TIME+ at 600 s.** Not stated; the firmware stays at 600 (no wrap) and still sends `time`.
- **REFUSED `TUBE` and START.** electronics.md: "REFUSED `TUBE` clears on any button press". START in REFUSED is judged
  again on the last tube reading, which isn't updated under the red ring: after a TUBE refusal, seating the tube and
  pressing START gives TUBE again until STOP or TIME+ brings back READY (and 300 ms of white).
