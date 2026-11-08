# MC-6 and MW-1 firmware

This is the monorepo's current physical-board project. Open this `firmware/` folder as its own VS Code/PlatformIO workspace; run the commands below from here, not from the monorepo root. The tiny `firmware/*.cpp` files inside this project are build wrappers around the two sketches.

Current bench settings: MC-6 requires the calibrated A2 lid sensor and ignores the A1 tube sensor. MW-1's `requireDoorClosed` is currently `false`; its calibrated A0 door state is still reported. Change requirement settings in the corresponding sketch and rebuild/upload when needed.

Saved records under `config/` retain the measured values and verification events. Their `.pio/` trace paths refer to local, uncommitted session logs. Generated build output and machine-specific IntelliSense/debug files are excluded.

Two independent appliance boards, each with its own USB serial connection. Build and upload **one firmware per board**. Both physical boards are **Arduino Uno R4 WiFi** boards, as confirmed during bring-up.

The project defaults to PlatformIO environment `mw1_r4_wifi` (`renesas-ra@1.9.0`). Select **Arduino UNO R4 WiFi** in Arduino IDE for the connected MW-1. Environment `mc6` targets the separate MC-6 Uno R4 WiFi. The sketches select the appropriate RAM diagnostic at compile time and explicitly use 10-bit ADC readings on R4.

The [LCD investigation](docs/MW1_LCD_INVESTIGATION.md) records the pull-up evidence, startup problem, fix and live hardware checks.

| Device | Standalone Arduino sketch | PlatformIO environment | Bring-up |
|---|---|---|---|
| MC-6 centrifuge | [MC6_firmware.ino](MC6_firmware/MC6_firmware.ino) | `mc6` | [Checklist](MC6_firmware/README.md) |
| MW-1 microwave | [MW1_firmware.ino](MW1_firmware/MW1_firmware.ino) | `mw1_r4_wifi` | [Checklist](MW1_firmware/README.md) |

The tiny files in `firmware/` include the sketches for PlatformIO. Source filters ensure that each build contains exactly one `setup()` and `loop()`. Neither board requires the other to be connected. These are mock appliance interfaces; there are no motor or heater outputs.

## Build and upload

For Wi-Fi snapshots from these same PlatformIO targets, see [the Vultr setup](../deploy/vultr/README.md#appliances). Each sketch accepts its own ignored `arduino_secrets.h`. USB operation works without that file.

Install these exact Arduino libraries, or let PlatformIO fetch the pinned dependencies:

| Device | Library | Version |
|---|---|---|
| MC-6 | [U8g2](https://github.com/olikraus/U8g2_Arduino) (U8x8 text mode) | 2.36.12 |
| MC-6 | [Adafruit NeoPixel](https://github.com/adafruit/Adafruit_NeoPixel) | 1.12.3 |

MW-1 has a self-contained slow software-I2C LCD/backlight driver and uses the board core's built-in EEPROM library. It requires **no external libraries**, and does not include `Wire` or `rgb_lcd`. MC-6 retains the libraries listed above.

Both environments use `renesas-ra@1.9.0` and `board = uno_r4_wifi`. There is one target per physical board.

VS Code `Ctrl+Shift+B` builds MW-1 for R4. **Terminal ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¡ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¦Ãƒâ€šÃ‚Â¾ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ Run Task** also offers explicit upload, monitor, calibration and LCD-check tasks, plus a separate MC-6 build.

```powershell
pio run
pio run -e mc6 -t upload --upload-port COM7
pio run -e mw1_r4_wifi -t upload --upload-port COM6
pio device monitor --port COM5 --baud 115200
```

Replace port names with the actual ports. Upload each environment to its corresponding board. If `pio` is absent from PATH on this computer, use `& "$env:USERPROFILE\.platformio\penv\Scripts\platformio.exe"` in its place.

For MW-1 use **`mw1_r4_wifi`**. The unused original-Uno MW-1 environment has been removed. COM6 was the detected R4 port during setup; it can change after reconnecting.

For Arduino IDE, open the appropriate `.ino` in its matching folder, select **Arduino UNO R4 WiFi**, install that board's libraries above, and upload. Each sketch is self-contained.

Select **Arduino UNO R4 WiFi** for either physical board. Arduino IDE requires its own library installation for MC-6; PlatformIO's `.pio/libdeps` is not searched by the IDE. The previously installed Grove library can remain installed, but MW-1 no longer uses it.

## Serial tester and protocol

### Match firmware buttons to physical labels

The physical buttons have been measured twice and the firmware updated:

| Physical label | Verified pin |
|---|---|
| TIME | D5 |
| +30s | D6 |
| POWER | D7 |
| START | D4 |
| STOP | D3 |

The [saved mapping](config/mw1_buttons.json) contains both observed press/release pairs per label and the applied source hash. If wiring changes, rerun calibration; the JSON record and sketch constants are the authoritative result of the latest session.

TIME and +30s were rechecked after swapping their D5/D6 connections during troubleshooting. Both now produce clean press/release events on the pins above; keep that wiring. The current record contains the two new trials for each changed label and preserves the unchanged POWER/START/STOP observations. This test demonstrated that both input paths and button/cable assemblies can work; it did not identify a permanently failed component.

Upload the current MW-1 firmware, close other serial monitors, then run the VS Code task **Calibrate MW-1 physical buttons and update source**, or:

```powershell
python tools/calibrate_mw1_buttons.py COM6 --apply
```

Follow its prompts in physical label order: **TIME, +30s, POWER, START, STOP**, then repeat the same sequence. Press only the requested button, hold roughly half a second, and release it completely. It requires a press/release pair, rejects reused pins and multiple simultaneous inputs, and checks that round two agrees with round one. A stuck or unobserved release causes a timeout instead of a guessed mapping.

The script enters `buttons` mode before collecting input. The LCD shows BUTTON TEST / FOLLOW PC PROMPT; active cooking is paused, and physical button presses are logged without operating the appliance. It scans D2-D12 and unused A2/A3, including pins outside the original D2-D6 assignments. D0/D1 remain reserved for serial, D13 for the board LED, A0 for the door sensor, A1 for the buzzer and A4/A5 for the LCD. It exits with `normal` even after cancellation. If the script is forcibly terminated, send `normal` or reset the board to leave test mode.

While waiting it displays USB heartbeat status, reports each detected pin immediately, and logs complete device events to `.pio/button-calibration-events.jsonl`. Serial fragments are buffered until a whole JSON line arrives. Missing heartbeats for eight seconds stop the session instead of guessing a mapping. Windows console Quick Edit is disabled for the calibration window so selecting text cannot pause its serial reader.

For a raw diagnostic without labeling or source edits, run the VS Code task **Observe MW-1 raw button inputs**, or `python tools/calibrate_mw1_buttons.py COM6 --observe 60`. It prints every input edge plus a live connection/held-input status. This is useful for distinguishing a shared/reused pin, missing wiring, or a stalled serial connection. For automated cancellation, create `.pio/button-calibration.cancel`; the script closes its port and attempts to restore normal mode. A new session clears this marker.

After a complete verified session, it saves the mapping and ten press/release observations to `config/mw1_buttons.json`. With `--apply`, it changes only the five `PIN_TIME`, `PIN_30S`, `PIN_POWER`, `PIN_START` and `PIN_STOP` values in the sketch; source backups go under `.pio/button-calibration`. It refuses to overwrite concurrent firmware edits. Build and upload the updated firmware to activate the new assignments; the wizard itself never uploads. Omitting `--apply` records the measurements without changing source. Press Ctrl+C to cancel. The default timeout is three minutes per requested press/release.

### MC-6 controls and sensor calibration

The MC-6 also uses an Uno R4 WiFi; choose **`mc6`** for build/upload. Its three buttons were verified twice: **TIME D12, START D2, STOP D10**; evidence is saved in [mc6_buttons.json](config/mc6_buttons.json). The confirmed POWER toggle stays D5, ring data D6, knob A0, upward-facing lid sensor A2, bottom tube sensor A1 and OLED A4/A5. Do not copy MW-1 pin assignments or its A1 buzzer wiring.

Run `python tools/calibrate_mc6_buttons.py COM7 --apply` on the MC-6's port with POWER off; follow TIME, START, STOP twice, then rebuild/upload the verified mapping. Run `python tools/calibrate_mc6_sensors.py COM7` for OPEN then CLOSED lid measurements, confirming each with physical START. A1 is currently ignored, so there is no tube step. Valid thresholds persist in EEPROM; STOP cancels. The scripts record only verified results in `config/mc6_buttons.json` and `config/mc6_sensors.json`.

The sketch currently sets `requireLidClosed = true` and `requireTubePresent = false`; the tube sensor does not block runs or lid calibration. Disabling them bypasses the corresponding simulated run requirements while preserving sensor reporting. See the [MC-6 checklist](MC6_firmware/README.md) for display diagnostics, thresholds, calibration and checks. New VS Code tasks provide MC-6 R4 upload and both calibration tools.

### Calibrate the MW-1 door sensor

The door light sensor connects to **A0**. Run the VS Code task **Calibrate MW-1 door light sensor**, or:

```powershell
python tools/calibrate_mw1_door.py COM6
```

Open the door fully and press/release physical START. When the LCD/console requests it, close the door fully and press/release START again. Keep the door still during each measurement; physical STOP cancels. The script records the result in [mw1_door.json](config/mw1_door.json). The firmware saves valid thresholds in EEPROM, checks the saved data by reading it back, and loads it on restart. No rebuild/upload is needed after calibration. Cooking stays paused throughout and does not resume automatically. To cancel a running script externally, create `.pio/door-calibration.cancel`.

The original open-only threshold expected deep shading: closed below 55% of the open reading. Actual measured readings were **open 541 / closed 481**, so that rule never recognized closure. Two-position calibration instead placed closed/open cutoffs at **505 / 517**. The live open/close verification passed, and the active-HIGH Grove buzzer on **A1** was audible. A1 now provides button, calibration and completion beeps; sound-sensor sampling and noise events have been removed.

Calibration requires at least 40 ADC counts between averages and more than eight counts of separation between all open and closed samples. It rejects overlapping readings and preserves the last working calibration. If ambient lighting or sensor alignment changes, recalibrate; measured thresholds cannot repair a hinge or distinguish positions producing the same readings.

```powershell
python -m pip install -r tools/requirements.txt
python tools/serial_probe.py COM5
```

Run a second instance on COM6 for the other board. The tester preserves boot output, sends `status` after the Uno's USB reset, then prints decoded JSON with the laptop's local timestamp and the device's `t` in milliseconds. Exit with Ctrl+C. Close other serial monitors before opening a port.

Firmware emits one JSON object per line at 115200 baud. `t` is an unsigned device uptime counter, wrapping after about 49.7 days. Events use numeric `0`/`1` for inputs, and every button has separate press and release events. Raw analog fluctuations appear in heartbeat snapshots; threshold crossings produce immediate `lid`, `tube`, or `door` events with the averaged `raw` value.

Send one command per line, case-insensitively; LF and CRLF are accepted:

| Command | Reply |
|---|---|
| `ping` | `{"t":123,"ev":"pong"}` |
| `status` | Immediate `hb` with all inputs, sensors, settings, UI and appliance state |
| `i2c` (MW-1 only) | Software bus scan: `{"t":123,"ev":"i2c","addresses":[62,98],"truncated":0}`; decimal 62 = 0x3E, 98 = 0x62 |
| `lcd` (MW-1 only) | Reinitialize text/backlight, then one `lcd` reply with presence flags and RGB address; appliance settings/calibration stay intact |
| `buttons` (MW-1 only) | Enter button-test mode; `buttons` reply reports `v:1` and a `pins` object mapping event names to actual digital pins |
| `normal` (MW-1 only) | Leave button-test mode; `buttons` reply has `v:0`; cooking remains paused if it was paused on entry |
| `cal` (MC-6) | Guided OPEN then CLOSED lid captures with physical START; a tube step is included only when `requireTubePresent` is enabled |
| `calstatus` / `calstop` (MC-6) | Read saved lid/tube thresholds / cancel calibration |
| `buttons` / `normal` (MC-6) | Enter/leave button-test mode for the three buttons; POWER remains on D5 |
| `oled` (MC-6) | Reinitialize OLED, then incrementally redraw current UI |
| `cal` / `doorcal` (MW-1) | Guided open/closed measurement using physical START; `doorcal` stages report progress, `saved` confirms persistence |
| `calstop` (MW-1) | Cancel guided calibration and retain previous thresholds |
| `beep` (MW-1) | One 150 ms active-HIGH beep on A1; `beep` reply reports the pin |
| `reset` | State/settings events as needed, then `{"t":123,"ev":"reset"}` |
| Anything else | `{"t":123,"ev":"error","msg":"unknown command"}` |

Commands longer than 15 characters, empty commands and embedded NULs are rejected. Overflow is discarded through the next newline so it cannot execute a truncated command. Repeating `cal` while calibration is active replies `error` / `calibration busy`. A heartbeat also arrives every second; asynchronous events may appear between command and reply.

Additional `state`, `display`, `light` and MC-6 `segment` events expose UI/state transitions. `notice` explains calibration, and `warning` reports missing display hardware, ring allocation failure, or a calibration light level below 20 ADC counts. A missing peripheral is also indicated in `hb`. Display text/colour describe the commanded UI; they do not prove that a physical display or LED worked.

Both boards' button events include the actual `pin`, for example `{"t":123,"ev":"btn_time","v":1,"pin":5}`. During calibration the event name reflects the currently compiled assignment, so the wizard uses the raw pin as evidence. Heartbeats include `button_test:0/1`; normal operation still uses fixed 20 ms debounce without auto-repeat.

In button-test mode, separate `input` events report each scanned pin's debounced edges independently of its current assigned action. The `buttons` reply lists `scan_pins`; heartbeat `input_mask` has bit N set when scanned digital pin N is held LOW. This lets calibration discover a button wired outside the old assignments. For A2/A3, numeric pins are 16/17 on the supported Uno boards. Scan pull-ups on unused pins are released when `normal` ends test mode.

MC-6 heartbeat `time` is the configured run duration; `remaining` is the countdown. MW-1 `time` is its current remaining cook time. On MC-6, `tube_valid:0` marks a frozen reading during animation, darkness or colour settling. `tube` and `tube_raw` retain the last valid observation. `pot_raw` is the actual averaged ADC input, before optional direction inversion. MW-1 reports `door_cal` (open average), `door_closed` (closed average), `door_lo`/`door_hi` (cutoffs), `door_saved` and `buzzer` (current HIGH/LOW output). Firmware 1.1 removes the former `sound_raw`, `loudness`, `quiet` and `noise` fields/events because A1 is a buzzer.

MW-1 heartbeat also reports `i2c:"software"`, `i2c_us:20`, and `rgb_addr` as a decimal address (98 = 0x62, 48 = 0x30, 0 = none detected). `lcd_present` and `rgb_present` initially reflect address acknowledgement and initialization; a later unacknowledged write sets the corresponding flag to 0 and emits a warning with `addr` and `io_error`. `lcd_error`/`rgb_error` retain the last fault until successful initialization and are omitted when no fault is present. Text/colour remain the intended UI. `lcd_pending:1` marks queued text; `lcd_sync:1` is emitted when the writes finish. Scanning probes one address per loop, retains up to 16 responding addresses, and marks overflow with `truncated:1`. A scan does not reinitialize peripherals; send `lcd` after correcting display wiring. Repeating `i2c` during a scan replies `I2C scan busy`.

Run `python tools/check_mw1_display.py COM6 --reinitialize 5` for a bounded display check; it verifies startup, bus addresses and acknowledged output. It does not judge the physical screen appearance.

## Calibration, timing and assumptions

- Both shields use 5 V and all buttons/switches connect to GND. MW-1 reserves D0/D1; MC-6 may use them for buttons because R4 `Serial` uses native USB and `Serial1` is unused. Nothing is connected to a motor/heater. There is no inter-board serial link.
- Both boards load valid saved light calibration. Only if none exists does MC-6 measure an open-lid/empty-well fallback or MW-1 an open-door fallback. Sensors cannot independently verify these physical assumptions. Use the printed levels and checklist before a demo.
- Normal light/pot observations average eight samples, nominally every 20 ms. MC-6 boot fallback averages 16 eight-reading measurements per sensor; shaded means **strictly below 55%** of baseline and clear means **strictly above 70%**. Equality and the intervening band preserve the previous state. Low baselines generate a warning and retain these percentages. Both boards use these ratios only as their unsaved boot fallback. Guided MC-6 calibration measures open/closed lid states under steady white, derives 40%/60% thresholds across the measured span and saves validated lid thresholds in EEPROM. A1 is ignored by the current configuration; enabling its requirement adds a tube-present calibration step.
- Guided MW-1 calibration captures 16 eight-reading averages per position, spaced 20 ms apart. Closed/open cutoffs are **40%/60% of the measured span above the closed average**. Equality and the hysteresis band preserve the previous state. EEPROM records include a version and checksum; invalid records are ignored. Identical saved values are not rewritten. Recalibration is manual, without ambient-light adaptation.
- MC-6 calibrates with the ring steady white at brightness 50/255, after 100 ms of light settling. Calibration temporarily overrides the normal OFF UI with white light and a calibration message, then restores the appropriate state. Normal OFF remains blank/dark.
- When its tube requirement is enabled, MC-6 tube measurements are taken under steady illuminated colours after 100 ms of settling. RUNNING and OFF freeze the tube observation. Starting requires a valid READY observation; pressing START immediately after a colour change can refuse with `TUBE` until a fresh reading exists. There is no tube check during the animation.
- MC-6 defaults really are 1000 rpm and 30 s after power-on/reset. The absolute pot takes control after movement greater than four ADC counts from its reset position. Thereafter, four ADC counts of hysteresis surround the 100 rpm step boundaries. `INVERT_POT` reverses the direction if needed. Movement during a run is ignored; an already active dial is read again after stopping.
- The MC-6 ring advances one pixel every 180 ms at 1000 rpm through 40 ms at 6000 rpm. This is visual simulation, not measured motor speed. Ring brightness is capped before the first `show()`.
- MC-6 refusal-clearing button presses only dismiss the refusal; they do not also start a run or edit settings. DONE ignores buttons and clears on lid opening or after 60 s. STOP/abort/power-off restore the configured duration, with a `time` event if the visible countdown changes.
- MW-1 A1 is an active-HIGH Grove buzzer, silent at boot. Normal physical button presses produce a 60 ms beep; DONE gives three 150 ms beeps; calibration success/failure gives two. Gaps are 120 ms. The scheduler does not block polling, and button-test mode stays silent. `beep` provides a single 150 ms test; `reset` silences pending beeps.
- Debounce remains exactly 20 ms with no repeat. Calibration continues to report buttons/heartbeats while suppressing appliance actions. MW-1 START confirms the requested door measurement and STOP cancels it. MC-6 START confirms its requested lid/tube capture and STOP cancels it; its power toggle still takes effect during calibration.
- `cal` stops an MC-6 run and restores its configured duration. On MW-1 it pauses cooking and preserves the remaining time. Calibration never automatically starts/resumes either appliance. `reset` restores software defaults, respects the MC-6 physical power toggle and retains calibration. A reset during calibration lets the measurement finish; both boards offer `calstop` to cancel it.
- MW-1 TIME and POWER work only in READY/SET. `+30s` in PAUSED adds time and remains paused. With zero time, including in DONE, `+30s` selects HI, sets 30 s and attempts to start; an open door leaves 30 s set and shows CLOSE DOOR. Adding time to an existing setting retains its power level.
- MW-1 door opening pauses before other actions. Closing the door replaces DOOR OPEN/red with PAUSED/amber and never resumes cooking. START while already cooking has no effect. STOP in READY/DONE has no state effect. DONE retains the power setting until changed/reset.
- MW-1 refusal messages overlay the underlying state for two seconds. An accepted setting/button action can dismiss them sooner. Pause/resume preserves whole seconds and restarts the one-second tick, discarding a partial elapsed second.
- Simultaneous presses are deterministic: safety checks first, then STOP; otherwise MC-6 TIME before START, and MW-1 TIME, POWER, +30s, START. A held STOP is logged and never given artificial release or repeat events.
- Uno `millis()` drives scheduling with wrap-safe unsigned subtraction. Small serial/I2C transfers still take time. MW-1 LCD probing/initialization starts 500 ms after boot with an explicit bus STOP and microsecond command-settling waits. Changed rows are queued, with one text transaction per loop. MC-6 OLED output also uses slow acknowledged software I2C, with one cleared tile or drawn glyph per loop and a 1000 microsecond clock timeout.
- MW-1 uses software I2C on A4/SDA and A5/SCL, with `I2C_DELAY_US = 20` between signal phases (nominal clock at most about 16.7 kHz, before GPIO overhead). HIGH releases the pin with `INPUT_PULLUP`; only LOW is actively driven. SCL waits are bounded to 1000 microseconds. All address/control/data bytes must be acknowledged; failures are reported rather than silently retried. Do not call `Wire.begin()` in MW-1 or attach an analog module to the shield's A4 connector. This transport change does not change button debounce or sensor thresholds.
- On the R4, boot `ram` is a stack-to-heap gap estimate obtained using newlib `_sbrk(0)`. AVR uses its own heap symbols. These diagnostics are architecture-specific and are not a measurement of maximum future stack usage.
- MC-6 OLED probes 0x3C, then 0x3D, and uses text-only U8x8 without a frame buffer. MW-1 probes the text controller at 0x3E and supports backlight 0x62 (v4) or 0x30 (v5), preferring v5 if both respond. The driver uses each version's initialization/PWM registers and reports the detected address. Seeed's [LCD documentation](https://wiki.seeedstudio.com/Grove-LCD_RGB_Backlight/) describes version/address differences.

## Verification

```powershell
pio run
python test/run_host_tests.py
python -m unittest discover -s test -p 'test_*calibration.py'
```

The host tests require `g++` with C++17. MW-1 is checked with its current door-requirement setting and the opposite setting; the latter uses a generated sketch copy that changes only that boolean initializer. Deployed sketch settings are never modified by the tests. They compile the actual sketches against hardware fakes and exercise debounce, threshold boundaries, sticky inputs, caps, refusal/start/stop/abort, countdown, pause/resume, guided door calibration, EEPROM validation, buzzer timing, command parsing and uptime rollover. The software-I2C fake decodes pin transitions and checks addressed bytes, v4/v5 RGB registers, data NACKs, scan results, bounded stuck-clock waits and that no I2C pin is driven HIGH. Tests also decode all emitted JSON. Python tests cover calibration validation, mapping guards and fragmented serial reads. They do not measure real hardware timing, sensor optics, LED current or display output.

Both R4 builds pass. Static memory fits within the target board's limits; MC-6 also allocates 72 bytes for the ring. Boot `ram` reports available space at that point in startup; MW-1 display initialization follows after its startup interval. Third-party U8g2/Arduino sources emit unused-code/parameter and signedness warnings under the extra warning flags; neither sketch emits compiler warnings. Complete the hardware checklists before relying on verifier logs.
