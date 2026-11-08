# MW-1 — electronics and controller behaviour

Controller code: `../../firmware/MW1_firmware/MW1_firmware.ino` (Arduino Uno + Grove Base Shield v2). Wiring: `schematic.png`, `grove_ports.png`, and `../../firmware/MakeCU_Electronics_Guide.pdf`. The Uno and shield sit on the base in the electronics bay (engraved ARDUINO mark), the buzzer on the BUZ mark next to it.

## Channels (serial event names)
| Channel (`ev`) | Hardware | Pin / port | Value | CAD body |
|---|---|---|---|---|
| `btn_start` | 16 mm pushbutton | D2 | 1 = pressed | `ref_cap_START` |
| `btn_stop` | 16 mm pushbutton | D3 | 1 = pressed | `ref_cap_STOP` |
| `btn_time` | 16 mm pushbutton | D4 | 1 = pressed | `ref_cap_TIME` |
| `btn_power` | 16 mm pushbutton | D5 | 1 = pressed | `ref_cap_POWER` |
| `btn_30s` | 16 mm pushbutton | D6 | 1 = pressed | `ref_cap_+30s` |
| `door` | Grove Light Sensor v1.2 | A0 | 1 = shut (shaded) | `ref_light_door` |
| `time` | — | — | seconds (set, or left while cooking) | |
| `power_level` | — | — | `HI` / `MED` / `LO` | |
| `cook` | — | — | `start`, `pause`, `resume`, `clear`, `done`, `pause:DOOR`, `refused:DOOR`, `refused:TIME` | |
| display | Grove LCD RGB Backlight v4.0, 16 × 2 | I2C (0x3E, 0x62) | text + backlight colour | `ref_lcd_grove` |
| sound | **Grove Buzzer** | **port D8** | output only (state in the heartbeat) | `ref_buzzer` |

Buttons: pin → GND, `INPUT_PULLUP`, 20 ms debounce, no auto-repeat. Door sensor: calibrated at power-up with the **door open**; shut below 55 % of that level, open again above 70 %.

## States, display and backlight
| State | Line 1 | Line 2 | Backlight |
|---|---|---|---|
| READY | `READY` | | white |
| SET (time set, not running) | `COOK 1:30` | `POWER HI` | white |
| COOKING | `1:29` counting down | `POWER HI` | amber |
| PAUSED (STOP) | `PAUSED  1:29` | `POWER HI` | amber |
| DOOR OPEN (door opened while cooking) | `DOOR OPEN` | `1:29` | red |
| DONE (10 s, then READY) | `DONE` | | green |
| message, 2 s | `SET TIME` / `CLOSE DOOR` | | white / red |

## What each button does in each state
| | READY / DONE | SET | COOKING | PAUSED / DOOR OPEN |
|---|---|---|---|---|
| TIME | time = 0:10 → SET | +10 s up to 1:00, then +1 min, max 30:00 | ignored | adds time, stays paused |
| POWER | cycles HI → MED → LO | cycles | ignored | cycles |
| +30s | door shut: 0:30 on HI, starts at once; door open: `CLOSE DOOR` | +30 s | +30 s | +30 s |
| START | door open → `CLOSE DOOR`; else `SET TIME` (refused) | door shut → COOKING; open → `CLOSE DOOR` | ignored | door shut → COOKING (`resume`); open → `CLOSE DOOR` |
| STOP | nothing | clears time → READY | → PAUSED | clears time → READY |
| Door opens | — | — | → DOOR OPEN (`pause:DOOR`) | — |

Closing the door never resumes by itself; START does. Countdown at 0:00 → DONE.

## Buzzer
| Sound | When |
|---|---|
| one short beep (~2.7 kHz, 60 ms) | every button press |
| three beeps (200 ms each) | cook reaches DONE |
| two low beeps (~900 Hz, 150 ms) | START or +30s refused |

Uses `tone()` on D8. If the buzzer only clicks, set `BUZZER_TONE = false` (plain HIGH/LOW).

## Serial
115200 baud, one JSON object per line. Boot `{"ev":"hello","dev":"MW-1",…}`; each change `{"t":ms,"ev":…,"v":…}` (door adds `"raw"`); heartbeat every second with all inputs, raw sensor and calibration values, LCD lines, backlight, power level, time and buzzer state. Commands `ping`, `status`, `cal`, `reset`.

## Wiring change you need to make
The Grove module is a **buzzer**, not a sound sensor, so it moves **from port A1 to port D8** (it's an output). Leave port D7 empty, since its second pin is D8. Nothing else changes. No breadboard: chain the five buttons' GND lugs and take one wire to the black pin of the port-D6 cable.
