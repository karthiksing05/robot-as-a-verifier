# Prompt: Arduino firmware for the MC-6 centrifuge and the MW-1 microwave

Write Arduino firmware for two mock lab/kitchen appliances built for a hackathon project. A robot arm (SO-101) operates them, and a verifier program on a laptop watches each appliance over USB serial to check what the robot did. The firmware has two jobs:
1. Make each appliance behave like the real thing, as described in its user manual (below).
2. Report every input and state change over serial, accurately and immediately, so the verifier has ground truth.

Deliver **two separate sketches**: `MC6_firmware/MC6_firmware.ino` and `MW1_firmware/MW1_firmware.ino`. Each runs on its own board.

---

## Hardware (both appliances)

- **Board:** Arduino Uno (ATmega328P, 5 V, 2 KB RAM, 32 KB flash) with a Seeed Grove Base Shield v2. The shield's VCC switch is set to 5 V.
- **Power:** USB from the laptop, about 500 mA available. The same USB cable carries serial.
- **Buttons and switches:** wired from the pin to GND. Use `INPUT_PULLUP`. Pressed or closed reads `LOW`.
- **Grove Light Sensor v1.2:** analog on its pin, 0 (dark) to ~750 (bright room). It has no light source of its own. A lid, door or tube **shades** it, and the reading **drops**.
- **Grove Buzzer** (MW-1 only): digital output on D8. HIGH = sound; `tone()` on the same pin gives a pitch.
- **Don't use D0/D1.** They're the USB serial link.

---

## Rules that apply to both sketches

1. **Non-blocking.**
   - One `loop()` driven by `millis()`. No `delay()` in normal operation. Buzzer patterns play from a small non-blocking queue.
   - Structure it as small modules: input reading (debounce), sensor processing, a state machine, UI output (display + light), and the serial protocol.
2. **Fit in 2 KB of RAM.**
   - Use `F()` for every constant string. No `String` objects.
   - Build JSON with `Serial.print` calls, not ArduinoJson.
   - For the MC-6 OLED, **use U8g2's `U8X8` text-only mode** (no frame buffer). Adafruit_SSD1306 alone needs 1 KB of buffer.
   - Report free RAM in the boot message.
3. **Report the truth. Don't hide faults.**
   - The hardware may have mechanical problems on purpose (the verifier's job is to find them). The firmware must not compensate for them.
   - Debounce is fixed at 20 ms; no longer filtering, no auto-repeat, no "smart" correction.
   - If a button sticks, the serial log must show it stuck.
4. **Calibrate sensors at boot.**
   - At power-up, average 16 readings of each light sensor. Assume the lid/door is **open** and no tube is in the well, and print a reminder.
   - Light state uses hysteresis:
     - **shaded** when below 55% of the calibrated level
     - **clear** when above 70%
   - Average 8 samples per reading.
   - The `cal` serial command re-runs calibration.
   - Make thresholds and percentages `const`s at the top of each sketch.
5. **Serial protocol (both sketches)** at 115200 baud, newline-terminated, one JSON object per line:
   - Boot: `{"t":<ms>,"ev":"hello","dev":"MC-6","fw":"1.0","ram":<bytes free>}`. `dev` is `"MW-1"` on the microwave.
   - On every change: `{"t":<ms>,"ev":"<name>","v":<value>}`. Event names are listed per appliance below. Send it the moment the change is detected.
   - Heartbeat once a second: `{"t":<ms>,"ev":"hb", ...full state snapshot...}`. The snapshot includes:
     - every input's current state
     - raw sensor values and calibration levels
     - the UI state (display text, light colour)
     - the run/cook state
   - Host-to-device commands, one word per line, case-insensitive. Each one replies with one JSON line:
     - `ping` → `{"ev":"pong"}`
     - `status` → a heartbeat right away
     - `cal` → recalibrate, then send `{"ev":"cal",...levels...}`
     - `reset` → back to the power-on state (settings default, run stopped)
   - Unknown commands reply `{"ev":"error","msg":"unknown command"}`.
6. **Pin numbers and tuning values** go in a clear block of `const`s at the top of each sketch.

---

## MC-6 Mini Centrifuge

### Pins

| Function | Pin | Notes |
|---|---|---|
| START button | D2 | INPUT_PULLUP, LOW = pressed |
| STOP button | D3 | INPUT_PULLUP, LOW = pressed |
| TIME+ button | D4 | INPUT_PULLUP, LOW = pressed |
| POWER toggle (SPDT) | D5 | INPUT_PULLUP, LOW = ON |
| NeoPixel ring, 24 × WS2812B, GRB | D6 | Adafruit_NeoPixel. **Brightness cap 50/255**; set it before the first `show()`, so there's no full-white flash at power-up |
| SPEED pot, 10 kΩ | A0 | 0–1023 |
| Lid light sensor | A1 | shaded = lid closed |
| Tube light sensor (under well A) | A2 | shaded = tube seated |
| OLED SSD1306 128 × 64, I2C | A4 SDA / A5 SCL | address 0x3C (fall back to 0x3D if not found); U8x8 text mode |

### Behaviour (matches the MC-6 user manual)

- **Power.**
  - The POWER toggle is a software power switch; the board stays on so serial keeps running.
  - **OFF:** display blank, ring off, the buttons do nothing (but their events still go out over serial).
  - **OFF → ON:** settings reset to defaults and the state becomes READY.
- **Settings.**
  - **Defaults:** 1000 rpm, 30 s.
  - **SPEED** = map A0 to 1000–6000 rpm in steps of 100.
    - Apply hysteresis so the value doesn't jitter between two steps.
    - The direction should be: dial clockwise raises the speed. If the pot is wired backwards, invert it with a `const`.
    - The dial is ignored during a run.
  - **TIME+** adds 10 s per press, up to 600 s (10:00). Ignored during a run.
  - **STOP while READY** resets the time to 30 s.
- **Display** (2 rows of large text, or 4 rows of normal text):

| State | Display | Ring |
|---|---|---|
| READY | `1000 RPM  0:30` (live speed and time) | white, steady |
| RUNNING | live rpm and remaining time counting down | blue, one lit segment rotating; rotation rate rises with the set rpm |
| DONE | `DONE` | green, steady |
| REFUSED | `LID` or `TUBE` (the reason) | red, steady |
| OFF | blank | off |

- **START, READY → RUNNING**, only if both checks pass:
  - **Lid closed** (lid sensor shaded). Otherwise REFUSED with reason `LID`.
  - **Tube seated** (tube sensor shaded). Otherwise REFUSED with reason `TUBE`.
  - The lid is checked first. Send `run:"start"` on success, or `run:"refused:LID"` / `run:"refused:TUBE"`.
- **Tube-check lighting.** The ring lights the tube sensor from below, so tube readings are only valid when the ring shows a **steady colour**.
  - Take the tube reading in READY (steady white) and use it at the moment START is pressed.
  - Don't evaluate the tube during the RUNNING animation; report it as unchanged.
  - Calibrate the tube sensor with the ring steady white.
- **REFUSED** stays until the reason clears (lid closed / tube seated) or any button is pressed. Then it returns to READY.
- **RUNNING.**
  - The time counts down once a second (send a `time` event each second).
  - STOP ends the run early: `run:"stop"`, back to READY with the time it was set to.
  - **If the lid opens during a run, abort:** `run:"abort:LID"`, ring red, display `LID`. The manual doesn't say this explicitly, but a real centrifuge does it.
  - At 0:00: `run:"done"`, state DONE.
- **DONE** stays until the lid is opened, or 60 s pass. Then it returns to READY with the same settings.

### Serial events (MC-6)

| ev | v | Sent when |
|---|---|---|
| power | 0 off / 1 on | toggle changes |
| btn_start, btn_stop, btn_time | 1 pressed / 0 released | after 20 ms debounce |
| speed | rpm | the setting changes by a step |
| time | seconds | TIME+, STOP-reset, or every second while running |
| lid | 0 open / 1 closed | lid sensor state changes (also send `"raw":<value>`) |
| tube | 0 clear / 1 seated | tube sensor state changes (also send `"raw":<value>`) |
| run | "start", "stop", "done", "refused:LID", "refused:TUBE", "abort:LID" | the run state changes |

---

## MW-1 Mock Microwave

### Pins

| Function | Pin | Notes |
|---|---|---|
| START button | D2 | INPUT_PULLUP, LOW = pressed |
| STOP button | D3 | INPUT_PULLUP, LOW = pressed |
| TIME button | D4 | INPUT_PULLUP, LOW = pressed |
| POWER button | D5 | INPUT_PULLUP, LOW = pressed |
| +30s button | D6 | INPUT_PULLUP, LOW = pressed |
| Door light sensor | A0 | shaded = door shut |
| Grove Buzzer | D8 | Grove cable in port D8 (leave port D7 empty). `tone()` or HIGH/LOW |
| Grove LCD RGB Backlight v4.0, 16 × 2 | A4 SDA / A5 SCL | Seeed `rgb_lcd.h`; text 0x3E, backlight 0x62 |

### Behaviour (matches the MW-1 user manual)

- **Settings.**
  - **Cook time** starts at 0:00.
  - **TIME:** +10 s per press up to 1:00, then +1 min per press, up to 30:00.
  - **POWER** cycles HI → MED → LO → HI; the default is HI.
  - Both buttons work in READY or SET. They're ignored while cooking.
  - **+30s:**
    - idle with no time set → set 0:30, power HI, and start cooking immediately (only if the door is shut)
    - time set or cooking → add 30 s (cap at 30:00)
- **START:**
  - door open → message `CLOSE DOOR` (red) for 2 s
  - no time set → message `SET TIME` (white) for 2 s
  - otherwise → start or resume COOKING
- **STOP:**
  - while cooking → PAUSED
  - in PAUSED or SET → clear the time and return to READY
- **Door opened while cooking** → PAUSED, with message `DOOR OPEN` and a red backlight. Closing the door doesn't resume; START does.
- **Countdown** reaches 0:00 → DONE: message `DONE`, green, for 10 s. Then back to READY.
- **LCD and backlight:**

| State | Line 1 | Line 2 | Backlight |
|---|---|---|---|
| READY | `READY` | (blank) | white |
| SET (time set, not running) | `COOK m:ss` | `POWER HI` / `MED` / `LO` | white |
| COOKING | `m:ss` counting down | `POWER xx` | amber (255, 140, 0) |
| PAUSED | `PAUSED  m:ss` | `POWER xx` | amber, steady |
| DOOR OPEN (paused by door) | `DOOR OPEN` | `m:ss` | red |
| DONE | `DONE` | (blank) | green |
| messages | `SET TIME` / `CLOSE DOOR` | (blank) | white / red, 2 s |

- **Buzzer:**
  - one short beep (~2.7 kHz, 60 ms) on every button press, in every state
  - three beeps (200 ms on, 120 ms off) when the cook reaches DONE
  - two low beeps (~900 Hz, 150 ms) when START or +30s is refused (`CLOSE DOOR` / `SET TIME`)
  - All non-blocking. A `const` switches between `tone()` and plain HIGH/LOW, in case the buzzer only clicks with `tone()`.

### Serial events (MW-1)

| ev | v | Sent when |
|---|---|---|
| btn_start, btn_stop, btn_time, btn_power, btn_30s | 1 pressed / 0 released | after 20 ms debounce |
| door | 0 open / 1 shut | door sensor state changes (also send `"raw":<value>`) |
| time | seconds | the setting changes, or every second while cooking |
| power_level | "HI" / "MED" / "LO" | POWER pressed |
| cook | "start", "pause", "resume", "clear", "done", "pause:DOOR", "refused:DOOR", "refused:TIME" | the cook state changes |

The heartbeat also carries whether the buzzer is sounding.

---

## What to deliver

1. The two complete sketches, compiling for **Arduino Uno** with no warnings that matter. List the libraries to install and their versions:
   - MC-6: U8g2, Adafruit NeoPixel
   - MW-1: Grove - LCD RGB Backlight
2. Comments only where the logic isn't obvious (thresholds, hysteresis, timing).
3. For each sketch, a short **bring-up checklist**: what to do and what the serial log should show, for every input and sensor.
   - Example: "flip POWER: `{"ev":"power","v":1}`"
   - Example: "close the lid: `{"ev":"lid","v":1,"raw":…}`"
4. A tiny Python 3 script (`pyserial`) that connects to a port, sends `status`, and prints decoded events with timestamps, so the verifier team can test against it.
5. A list of every assumption you made, especially sensor thresholds and anything the manuals don't cover.
