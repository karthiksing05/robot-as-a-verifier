# MW-1 bring-up

Use this board's own USB port and a Grove Base Shield v2 at 5 V. Buttons connect their pins to GND. D0/D1 stay free.

The connected MW-1 board is an **Arduino Uno R4 WiFi**. Select **Arduino UNO R4 WiFi** in the IDE, or build/upload PlatformIO environment `mw1_r4_wifi`. This is the project's only MW-1 environment; `mc6` is for the separate centrifuge board.

| Function | Pin |
|---|---|
| TIME / +30s / POWER / START / STOP | D5 / D6 / D7 / D4 / D3 |
| Door light sensor / active-HIGH Grove buzzer | A0 / A1 |
| Grove LCD RGB Backlight v4.0 | A4 SDA / A5 SCL, text 0x3E / backlight 0x62 |

The display uses a built-in **slow software-I2C driver** with 20 microsecond signal phases, 500 ms startup settling and an explicit bus STOP before initialization. No `Wire` or `rgb_lcd` library is needed. Keep the shield's A4 analog connector empty; A4/A5 belong to this bus. The driver also recognizes v5 backlights at 0x30 and uses that controller's register layout. See the [investigation](../docs/MW1_LCD_INVESTIGATION.md) for live measurements and resistor findings.

Use 115200 baud. Examples omit `t`; actual events include it. Button events use 1 for pressed and 0 for released.

If labels operate the wrong actions, run `python tools/calibrate_mw1_buttons.py COM6 --apply` from the project root, with other serial monitors closed. The script requests **TIME, +30s, POWER, START, STOP** twice, records the raw pins, and updates only verified pin constants. It uses a button-test mode that suppresses appliance actions during measurement. After success, rebuild/upload. The persistent evidence is `config/mw1_buttons.json`; the physical order of labels is not assumed to be D2 through D6.

The table above is the verified result saved in [mw1_buttons.json](../config/mw1_buttons.json). TIME and +30s each passed two new press/release trials after their D5/D6 connections were swapped; keep that working arrangement. POWER/START/STOP retain their unchanged verified assignments. POWER uses D7, which was outside the original five-pin assignment. Use `python tools/calibrate_mw1_buttons.py COM6 --observe 60` to see raw changes without assigning labels. The reader preserves partial serial lines, shows USB liveness, and logs events under `.pio` for troubleshooting.

Run the VS Code task **Calibrate MW-1 door light sensor**, or `python tools/calibrate_mw1_door.py COM6`, with other serial monitors closed. Open the door fully and press/release START. When prompted, close it fully and press/release START again. Hold the door still during each measurement. STOP cancels. Cooking pauses for calibration and never resumes automatically. Successful thresholds are saved in board EEPROM and recorded in [mw1_door.json](../config/mw1_door.json); restart loads them without recalibrating.

The measured open/closed averages must differ by at least 40 ADC counts, with the lowest open sample more than eight counts above the highest closed sample. Failed calibration preserves previous thresholds and prompts a retry. Closed/open thresholds sit 40%/60% of the way from the closed average to the open average; equality and the band between preserve the previous state. If lighting or sensor alignment changes, rerun calibration. With no valid saved calibration, boot retains the original open-baseline 55%/70% fallback until guided calibration succeeds.

A1 drives the Grove buzzer HIGH to sound, LOW to silence. Buttons beep for 60 ms, completed cooking gives three 150 ms beeps, and calibration success/failure gives two. Beeps use a timer without blocking button/sensor polling. A1 is no longer sampled as a sound sensor; `sound_raw`, `loudness`, `quiet` and `noise` events have been removed. Send `beep` for a single 150 ms test.

`const bool requireDoorClosed = false;` near the top of the sketch controls the simulated microwave's door requirement. `true` requires closure for START/resume and instant +30s, and pauses cooking when the door opens. Set it to `false` and rebuild/upload to allow those actions with an open door and disable automatic door-open pausing. Sensor measurement, calibration, time validation and manual STOP still work.

The current door requirement is disabled. Door-refusal and door-open pause checks in this table apply when it is set to `true`.

| Check | Expected observation/log |
|---|---|
| USB power | `hello`, `dev:"MW-1"`, `fw:"1.1"`, positive `ram`. Valid saved calibration emits `doorcal` with `stage:"loaded"`; otherwise an open-door fallback baseline is measured over roughly 320 ms. READY, white, time zero. |
| Send `status` | `hb` includes all five buttons, door state/raw/calibration, `door_closed`, `door_lo`, `door_hi`, `door_saved`, `buzzer`, time, power, state, display and light. Expect `lcd_present:1`, `rgb_present:1`, `i2c:"software"`, `i2c_us:20` and `rgb_addr:98` (0x62), or 48 (0x30) for v5. `lcd_pending` clears when text drains. `lcd_error`/`rgb_error` are omitted when there is no fault. |
| Send `i2c` | One `i2c` result lists responding addresses in decimal. For v4 expect 62 (0x3E text) and 98 (0x62 backlight); for v5 expect 48 (0x30 backlight) and 62 (0x3E text). Empty results indicate no acknowledgements on the software bus. |
| Send `lcd` | Reinitializes the display without changing appliance settings. The `lcd` reply reports presence flags; `lcd_sync:1` follows when the intended text is fully written. |
| Press/release each button | `btn_start`, `btn_stop`, `btn_time`, `btn_power`, `btn_30s`, each with `v:1` then `v:0`. Holding a button never repeats. |
| Close/open door after calibration | `{"ev":"door","v":1,"raw":479}` / `v:0`, with measured raw values. Closed is strictly below `door_lo`; open is strictly above `door_hi`. Actual calibration measured open 541 / closed 481, giving cutoffs 505 / 517. |
| START with door open | `cook:"refused:DOOR"`, CLOSE DOOR/red for two seconds. |
| START with door shut and zero time | `cook:"refused:TIME"`, SET TIME/white for two seconds. |
| TIME from zero | `time:10`, SET, COOK 0:10 / POWER HI. Six presses total reach 60; next reaches 120. Continue to cap 1800. |
| POWER in READY/SET | `power_level:"MED"`, then `"LO"`, then `"HI"`; SET display follows. |
| STOP with time set | `time:0`, `cook:"clear"`, READY/white. |
| +30s from zero, door shut | `time:30`, HI, `cook:"start"`, COOKING, amber. |
| +30s from zero, door open | Sets 30 and HI; `cook:"refused:DOOR"`, CLOSE DOOR/red. Shut door and press START to cook. |
| +30s with time set/cooking/paused | Adds 30, cap 1800. Existing power retained; a paused run stays paused. |
| START with time and shut door | `cook:"start"`, amber countdown with POWER xx; one `time` event per second. |
| Press TIME or POWER while cooking | Press/release events still appear; settings stay unchanged. |
| First STOP while cooking | `cook:"pause"`, PAUSED with remaining time, amber. Countdown stops. START emits `cook:"resume"`; a second STOP while paused emits `cook:"clear"` and returns READY. |
| Open door while cooking | `door:0`, `cook:"pause:DOOR"`, DOOR OPEN with time, red. Close door: `door:1`, PAUSED/amber, still stopped. START resumes. |
| Let countdown expire | `time:0`, `cook:"done"`, three beeps, DONE/green for ten seconds, then READY/white. |
| Send `beep` | `beep` reply reports pin 15 (A1); `buzzer:1` then `buzzer:0` events accompany the audible 150 ms beep. |
| Send `PiNg`, `status`, `reset`, an unknown word | `pong`, immediate `hb`, zero time/HI/READY with `reset` reply, and `error` / `unknown command`. |
| Send `cal` or `doorcal` | Guided OPEN / START, CLOSED / START prompts. `doorcal` stage `saved` confirms EEPROM readback. `calstop` or physical STOP cancels. Inputs/heartbeats continue; START confirms measurements instead of starting cooking. |

If calibration reports insufficient contrast, correct physical alignment/lighting and retry. Calibration adapts thresholds to measured shading; it cannot repair a hinge or distinguish door movement when both positions produce overlapping sensor readings.

Display writes check every acknowledgement. A failed text/backlight write emits `warning` with its address/error, sets its presence flag to 0, and leaves the intended UI visible in serial status. After correcting wiring, send `lcd` or restart to initialize the controllers again. `I2C_DELAY_US`, `I2C_CLOCK_TIMEOUT_US` and `DISPLAY_STARTUP_MS` are tuning constants at the top of the sketch; there are no hardware-I2C calls in MW-1. Run `python tools/check_mw1_display.py COM6 --reinitialize 5` from the project root for an automated serial check.
