# MC-6 bring-up

The MC-6 is an **Arduino Uno R4 WiFi** with a Grove Base Shield at 5 V. Build/upload **`mc6`**. The detected MC-6 USB port is COM7 (it can change after reconnecting). The microwave remains independent under `mw1_r4_wifi`; never upload one board's firmware to the other.

| Function | Pin |
|---|---|
| START / STOP / TIME buttons | D2 / D10 / D12 (verified twice; saved in `config/mc6_buttons.json`) |
| POWER toggle, active LOW | D5 (confirmed wiring; not remapped by button calibration) |
| 24-pixel GRB WS2812B ring data input (D0/DIN on module) | Arduino D6 |
| Speed rotary knob / upward-facing lid light / bottom tube light | A0 / A2 / A1 |
| SSD1306 128x64 I2C OLED | A4 SDA / A5 SCL, 0x3C or 0x3D |

On the R4, `Serial` uses native USB; D0/D1 may therefore be discovered as button pins while `Serial1` is unused. The ring module's D0 label refers to its data input wired to Arduino D6. A1/A2 are analog sensor inputs with pull-ups disabled; button discovery leaves them untouched. The MC-6 has no confirmed buzzer connection.

## Discover the three physical buttons

Upload current MC-6 firmware, close other serial monitors, leave the POWER toggle OFF and run:

```powershell
python tools/calibrate_mc6_buttons.py COM7 --apply
```

The tool prompts **TIME, START, STOP** twice. Press/release only the requested button and hold about half a second. It requires matching press/release trials, rejects duplicate/reserved pins and refuses source edits if firmware changed during the session. POWER stays D5. Button-test mode logs inputs without running the centrifuge or changing its settings. It scans D0-D5 and D7-D12; ring D6, analog sensors and I2C stay reserved. D5 is observed but cannot be assigned to a button.

Verified evidence goes to `config/mc6_buttons.json`, and backups to `.pio/button-calibration`. Rebuild/upload after source changes. `--observe 60` records raw input edges without remapping. Ctrl+C cancels; `.pio/mc6-button-calibration.cancel` provides cooperative cancellation. The serial reader preserves fragmented lines and stops if USB heartbeats disappear for eight seconds. `normal` exits button-test mode without restarting a run.

## Calibrate the lid and tube sensors

After button discovery and upload, run the VS Code task **Calibrate MC-6 lid and tube sensors**, or:

```powershell
python tools/calibrate_mc6_sensors.py COM7
```

Recalibrate after swapping the sensor pins. The saved record is tied to the pin assignments, so firmware rejects calibration from the old wiring.

The current configuration **ignores A1** (`requireTubePresent = false`). Keep the lid still during each of the two prompts.

1. Open the lid and press/release START.
2. Close the lid and press/release START.

No tube measurement is requested or required. A1 is not sampled during normal operation or calibration, and its value cannot block a run. The ring stays white while measuring. Each capture waits at least 100 ms and collects 16 eight-reading averages. The closed average must be at least 40 ADC counts below open, with more than eight counts separating their sample ranges. Failed calibration keeps previous thresholds; STOP or `calstop` cancels. Active runs stop and never resume automatically.

The saved hardware calibration measured **open 763 / closed 561**, with cutoffs **641 / 682**. Below the lower cutoff is closed; above the upper cutoff is open. Equality and the band preserve the previous state. Lid thresholds are saved in EEPROM, read back for validation and loaded at restart. The record explicitly marks the tube uncalibrated. Invalid checksums/versions/pin assignments are ignored; identical values are not rewritten. The PC evidence is [mc6_sensors.json](../config/mc6_sensors.json). No rebuild/upload is needed after calibration.

To use A1 later, set `requireTubePresent = true`, rebuild/upload and rerun the tool. It will then request OPEN/EMPTY, CLOSED/EMPTY and TUBE INSERTED/LID CLOSED. The empty and loaded tube readings are compared with the lid shut under steady white light. Both sensors must pass contrast/noise checks; a lid-only saved record cannot satisfy the re-enabled tube requirement.

To calibrate both sensors in one pass, upload the current MC-6 firmware and run this from `firmware/` with the serial monitor closed:

```powershell
python tools/calibrate_mc6_sensors.py COM7 --both
```

Replace `COM7` with the centrifuge port. Press START at each prompt with the lid open and well empty, then with the lid closed and well empty, then with the lid closed and tube inserted. Wait for each measurement to finish. The script verifies the EEPROM save and records both thresholds in `.pio/mc6-both-calibration.json`. The interlock settings stay as configured.

To calibrate A1 on its own, first complete lid calibration, then run this from `firmware/` with the serial monitor closed:

```powershell
python tools/calibrate_mc6_sensors.py COM7 --tube-only
```

Replace `COM7` with the centrifuge port. With the lid closed, press START to capture the empty well. Insert the tube, close the lid, and press START again. The script checks the board's EEPROM confirmation and writes the result to `.pio/mc6-tube-calibration.json`. This preserves the saved lid thresholds and leaves the tube interlock setting as configured.

To recalibrate only the A2 lid sensor while preserving any saved tube calibration, upload the current MC-6 firmware and run from `firmware/` with the serial monitor closed:

```powershell
python tools/calibrate_mc6_lid.py COM7
```

Press START once with the lid fully open and once with it fully closed. Wait for each measurement to finish before moving the lid. The result is written to `.pio/mc6-lid-calibration.json` after the board confirms its EEPROM save.

Until a valid saved calibration exists, boot retains the original open-lid/empty-well baseline with 55%/70% fallback thresholds. Recalibrate after changing illumination or sensor alignment. Threshold calibration cannot distinguish positions whose readings overlap or repair a hinge.

## Requirement switches

Near the top of the sketch:

```cpp
bool requireLidClosed = true;
bool requireTubePresent = false;
```

`requireLidClosed` controls lid refusal at START and lid-open abort during a run. `requireTubePresent` controls the tube-present/validity check at START, automatic A1 sampling and whether calibration requires a tube measurement. It is currently disabled. Set either to `false` and rebuild/upload to bypass that requirement for this simulated appliance. Sensor reporting and calibration remain active. DONE still clears when the lid opens or after 60 seconds.

## Display and serial checks

`OLED_FLIPPED = true` rotates the OLED 180 degrees for its physical mounting. The OLED uses U8x8 with an acknowledged, open-drain software-I2C transport adapted from MW-1: 20 microsecond phases, a 1000 microsecond clock timeout, 500 ms startup settling and a STOP before probing. No `Wire.begin()` runs in this sketch. Each loop clears one tile or writes one glyph, so slow OLED updates do not hold up button/sensor polling for a full screen. `oled_pending` indicates queued output; `oled_sync:1` confirms completion. On an I2C fault, a warning gives its address and numeric error (1 SDA busy, 2 clock timeout, 3 address NACK, 4 data NACK), and `oled_present` becomes 0. Correct wiring and send `oled` to reinitialize.

Use 115200 baud. Commands are case-insensitive and newline terminated:

| Command | Result |
|---|---|
| `ping`, `status` | `pong`, immediate `hb` |
| `raw` | Eight-reading averages of A0, A1, A2 and A3, independent of the assigned sensor roles |
| `cal` | Guided lid-only calibration; includes a tube step only when `requireTubePresent` is enabled |
| `calstatus` | `lightcal` reply with stage, saved flag, `tube_required`, `tube_saved` and clear/shaded/lo/hi values |
| `calstop` | Cancel calibration, keep previous thresholds |
| `buttons`, `normal` | Enter/leave button-test mode; reply includes physical pin map and scan list |
| `oled` | Reinitialize OLED and queue current UI |
| `reset` | Restore 1000 RPM / 30 s defaults and physical power state, keeping calibration |

Button and power events include the actual `pin` and separate `v:1`/`v:0` edges. Heartbeats report all controls, sensor values, tube validity, RPM, configured/remaining time, UI, `cal_saved`, `button_test`, OLED presence/pending state and software-I2C timing. Test-mode `input` events and `input_mask` expose raw scanned inputs independently of labels.

| Physical check | Expected result |
|---|---|
| POWER on/off | READY with 1000 RPM / 0:30 and white ring; OFF blanks UI. ON resets defaults. |
| TIME in READY / hold TIME | Add 10 s up to 600; no auto-repeat. |
| STOP in READY | Restore 30 s. Sticky inputs stay held in logs until physical release. |
| Turn knob after power-on | Movement beyond four ADC counts activates 100 RPM steps, 1000-6000 RPM; `INVERT_POT` changes direction. |
| START with requirements enabled | Open lid refuses LID first; missing/invalid tube refuses TUBE. Wait for steady-white tube sampling after a colour change. |
| START with lid shut/tube seated | RUNNING, blue rotating segment and one-second countdown. |
| Tube sensor during animation | Frozen last reading, `tube_valid:0`; no checks from changing illumination. |
| STOP / lid opens during run | Stop to READY / abort to LID refusal; configured time restored. |
| Countdown completes | DONE/green; opening lid or 60 s timeout returns READY. |

Validate on hardware after calibration; controller acknowledgements do not prove physical pixels or optical alignment.

For a live A1 tube sensor check, run `python tools/monitor_mc6_a1.py COM7` or the VS Code task **Monitor MC-6 A1 sensor**. It displays the 0-1023 value and observed min/max, saving a CSV to `.pio/mc6-a1-readings.csv`. Add `--all` to display/record A0, A2 and A3 alongside A1 when checking wiring. It requests readings without changing calibration or appliance settings. Ctrl+C stops; `--seconds 10` limits the run, and `.pio/mc6-a1-monitor.cancel` provides cooperative cancellation. Close it before opening another serial tool.

Wi-Fi `speed` and `dial_speed` both report the physical A0 dial position mapped to 1000–6000 RPM, including while the power toggle is off or a run is active. Wi-Fi `applied_speed` and serial `rpm` report the applied speed setting. Serial `dial_speed` shows the live dial position.
