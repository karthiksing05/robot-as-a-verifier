# Firmware — MC-6 centrifuge and MW-1 microwave

One Arduino Uno + Grove Base Shield v2 per appliance (shield VCC switch on **5V**).

| Folder | Board | Libraries (Library Manager) |
|---|---|---|
| `centrifuge/firmware/MC6_firmware/` | centrifuge | U8g2 (2.34+), Adafruit NeoPixel (1.12+) |
| `microwave/firmware/MW1_firmware/` | microwave | Grove - LCD RGB Backlight (Seeed) |
| `tools/monitor.py` | laptop | `pip install pyserial`; prints decoded events, lets you type commands |

Also here: `MakeCU_Electronics_Guide.pdf` (wiring for both, with part pictures, schematics and test sketches) and `firmware_prompt.md` (the full behaviour spec these sketches implement).

Behaviour, channel names and state tables are in each appliance's `source/electronics/electronics.md`.

## Pins
| | MC-6 | MW-1 |
|---|---|---|
| D2 | START | START |
| D3 | STOP | STOP |
| D4 | TIME+ | TIME |
| D5 | POWER toggle (LOW = ON) | POWER |
| D6 | NeoPixel ring | +30s |
| D8 | — | **Grove Buzzer** (port D8; keep port D7 empty) |
| A0 | SPEED pot | door light sensor |
| A1 | lid light sensor | — |
| A2 | tube light sensor | — |
| I2C | SSD1306 OLED 0x3C | Grove LCD 0x3E / 0x62 |

## Bring-up checklist
Open `python tools/monitor.py <port>` (or the Serial Monitor at 115200).

**MC-6** — power up with the lid **open** and no tube in well A.
1. Boot: `hello` (dev MC-6, ram > 1000), then `cal` with the lid and tube levels.
2. Flip POWER up: `power v=1`; ring white, display `1000rpm` / `0:30`.
3. Press START / STOP / TIME+: `btn_start v=1` then `v=0`, etc. TIME+ also sends `time v=40`.
4. Turn SPEED clockwise: `speed` rises in steps of 100. If it falls, set `SPEED_INVERT = true`.
5. Close the lid: `lid v=1 raw=…`. Open it: `lid v=0`.
6. Seat a tube in well A (lid open, ring white): `tube v=1 raw=…`.
7. Close the lid, press START: `run v=start`, ring blue and spinning, `time` counts down, then `run v=done`, ring green.
8. START with the lid open: `run v=refused:LID`, red, `LID`.

**MW-1** — power up with the door **open**.
1. Boot: `hello` (dev MW-1), `cal` with the door level, one beep.
2. Shut the door: `door v=1 raw=…`.
3. Press each button: `btn_* v=1 / v=0`, one beep each.
4. TIME ×3: `time v=10, 20, 30`; display `COOK 0:30`. POWER: `power_level v=MED`.
5. START: `cook v=start`, amber, counting down. Open the door: `cook v=pause:DOOR`, red `DOOR OPEN`.
6. Close, START: `cook v=resume`. At 0:00: `cook v=done`, three beeps, green `DONE`.
7. Open the door and press START: `cook v=refused:DOOR`, two low beeps, red `CLOSE DOOR`.

## Assumptions
- Sketches were syntax-checked here against stub headers, not compiled with the Arduino toolchain or run on hardware. Expect small fixes on first upload.
- Light thresholds 55 % / 70 % of the calibrated open level; tube readings only under steady white light. All `const`s at the top.
- Buzzer driven with `tone()`. Grove Buzzer modules differ; if yours only clicks, set `BUZZER_TONE = false`.
- OLED at 0x3C. Some boards are 0x3D: change the constructor to `U8X8_SSD1306_128X64_NONAME_HW_I2C oled(U8X8_PIN_NONE); oled.setI2CAddress(0x3D * 2);` before `begin()`.
