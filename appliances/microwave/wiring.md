# Wiring

Arduino Uno with a Grove Base Shield v2, on the base in the electronics bay. All grounds common. Buttons use the Uno's
internal pull-ups, so a closed switch reads LOW (20 ms debounce, no auto-repeat). From `firmware/MW1_firmware/MW1_firmware.ino`
and `source/electronics/electronics.md`; where they differ, the firmware is what's simulated (notes at the end).

| Part | Pin / port | Channel | Notes |
|---|---|---|---|
| START button (16 mm) | D2 / GND | `btn_start` | pressed = LOW, reported 1 |
| STOP button | D3 / GND | `btn_stop` | |
| TIME button | D4 / GND | `btn_time` | |
| POWER button | D5 / GND | `btn_power` | |
| +30s button | D6 / GND | `btn_30s` | the five GND lugs chained to the port-D6 cable's black pin |
| Grove Light Sensor v1.2 | A0 | `door` | behind the door's free end; 1 = shut (shaded below 55 % of the power-up level, clear again above 70 %) |
| Grove LCD RGB Backlight v4.0, 16 x 2 | I2C (0x3E text, 0x62 backlight) | display | text and backlight colour |
| Grove Buzzer | D8 (port D7 left empty) | `buzzer`, `beeps` (sim) | `tone()`: key 2.7 kHz 60 ms, done 3 x 200 ms, refused 2 x 900 Hz 150 ms |
| USB | | | 5 V power and the serial stream |

## Serial stream (ground truth for the verifier)

115200 baud, one JSON object per line: `{"t": ms, "ev": ..., "v": ...}` on each change (the door adds `"raw"`), a boot
`hello`, and a heartbeat every second. Commands: `ping`, `status`, `cal`, `reset`.

| ev | v |
|---|---|
| btn_start, btn_stop, btn_time, btn_power, btn_30s | 1 down, 0 up |
| door | 1 shut, 0 open |
| time | seconds: set, or left while cooking (whole seconds, rounded up) |
| power_level | `HI`, `MED`, `LO` |
| cook | `start`, `pause`, `resume`, `clear`, `done`, `pause:DOOR`, `refused:DOOR`, `refused:TIME`, and `reset` (the serial command) |

## Sim channels

The sim adds what the heartbeat carries as state: `buzzer` (the last sound: `key`, `done` or `refused`), `beeps` (a
count of sounds, so two identical sounds in a row still show) and `backlight` (`white`, `amber`, `red`, `green`, which
is also the display's ring). The state names are the firmware's, with COOK as `running`, and the two 2 s messages as
`msg_settime` and `msg_closedoor`.

## Firmware vs electronics.md, and what the sim leaves out

- `cook: "reset"` is sent on the serial `reset` command; electronics.md's list omits it. The sim has no serial commands.
- A refused START or +30s: `play()` replaces the key beep, so only the two low beeps sound (electronics.md lists both).
- POWER in READY or DONE: the firmware goes to SET if a time is set, which can't happen there (both have time 0); it stays.
- The door sensor calibrates at power-up assuming the door is open, so a door shut at power-up never reads shut until
  `cal`. The sim starts calibrated, door shut (`door: 1`).
- Sim only: a press during DONE, or during a message over DONE, restarts DONE's 10 s; a press during a message ends the
  message at once (the firmware too acts on the state under it, but redraws the message until its 2 s are up); the same
  `cook` value twice in a row logs once.
