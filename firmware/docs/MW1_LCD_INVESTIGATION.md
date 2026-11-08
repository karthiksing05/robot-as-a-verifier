# MW-1 LCD investigation — 2026-11-07

The connected Uno R4 WiFi could not detect the display using hardware I2C. Slow software I2C now initializes both controllers and completes acknowledged text writes. The VS Code project defaults to the actual R4 board and includes build, upload, monitor and LCD-check tasks.

## Findings

| Observation on COM6 | Result |
|---|---|
| Original hardware-I2C firmware | No scan acknowledgements; `lcd_present:0`, `rgb_present:0` |
| Software I2C, 10 us signal phases | Text address 0x3E and backlight address 0x62 acknowledge; backlight initializes, text initialization is unreliable |
| Software I2C, 20 us phases, no initial bus STOP | Manual initialization works repeatedly, but the first startup probe can return `address_nack` |
| Final driver: 20 us phases, initial STOP, 500 ms startup settling | Both controllers initialize after R4 reset; text queue completes; five consecutive manual reinitializations pass |
| Second R4 reset with the final driver | Both controllers initialize without a manual `lcd` command; scan and ping/status pass |

The scanner also observed an acknowledgement at 0x03. Its origin was not identified; it is a reserved address and is not treated as proof of another peripheral. The required display addresses are 0x3E and 0x62. No cable, shield or resistor changes were made by the agent during these comparisons.

The first-probe failure was repeatable before adding an explicit STOP. Increasing startup settling from 100 ms to 500 ms alone did not resolve it. The STOP resolved it in the subsequent tests. This is consistent with the powered LCD's bus state surviving a microcontroller reset; the exact internal controller state was not measured.

## What the resistor explanation means

I2C devices pull SDA/SCL LOW and release them for HIGH. Pull-up resistance and bus capacitance determine how quickly a released line rises; excessive resistance can prevent a valid HIGH at the expected clock rate. [Texas Instruments' pull-up calculation note](https://www.ti.com/lit/an/slva689/slva689.pdf) describes the relationship and sizing limits.

The [official Uno R4 WiFi schematic](https://docs.arduino.cc/resources/schematics/ABX00087-schematics.pdf) labels the board's I2C pull-ups as **not mounted**. The installed Renesas core enables the microcontroller's internal pull-ups in `Wire.cpp`; internal pull-ups do not establish that the complete bus meets I2C rise-time requirements. Arduino also documents that many boards require [external I2C pull-ups](https://support.arduino.cc/hc/en-us/articles/11153357842588-I2C-and-pull-up-resistors).

The before/after results support a signaling/timing compatibility problem, including startup bus synchronization. They do **not** establish that a particular resistor inside this display has failed. No oscilloscope rise-time measurement, resistance measurement or inspection of the actual RGB module's resistor population was performed. Seeed documents revision-dependent pull-ups in its [monochrome 16x2 family](https://wiki.seeedstudio.com/Grove-16x2_LCD_Series/); that does not identify the resistor population of this RGB module.

## Implemented fix

- A4/SDA and A5/SCL are controlled by software; MW-1 never calls `Wire.begin()` and needs no LCD library.
- LOW is actively driven; HIGH uses `INPUT_PULLUP`. The GPIO latch is set LOW before enabling output, avoiding an actively driven HIGH pulse.
- Signal phases are 20 us (nominal clock no faster than roughly 16.7 kHz before GPIO overhead). SCL waits are bounded to 1000 us.
- Initialization waits 500 ms after boot and establishes a bus STOP before probing the still-powered controllers.
- The text controller is 0x3E. Backlights at 0x62 (v4) and 0x30 (v5) have separate initialization and PWM register maps.
- Only changed text rows are queued. Each loop sends at most one text transaction so slower transfers do not block input processing for a whole screen redraw. `lcd_pending` reports queued output; `lcd_sync:1` means the queue finished with acknowledgements.
- Every byte is checked. A failed write disables that output and reports its address and error (`address_nack`, `control_nack`, `data_nack`, `sda_low` or `scl_timeout`). `lcd_error` and `rgb_error` retain the fault in heartbeats until successful manual initialization. Appliance button/door faults retain their original reporting and behavior.
- `i2c` scans the bus. `lcd` explicitly reinitializes the display without resetting appliance time, power or sensor calibration. There are no automatic hidden display retries.

## Use from VS Code

`Ctrl+Shift+B` runs **Build MW-1 (Uno R4 WiFi)**. Under **Terminal → Run Task**, choose **Upload MW-1 (Uno R4 WiFi)**, **Monitor MW-1 (115200 baud)** or **Check MW-1 LCD over serial**. Close serial monitors before upload/check tasks. Upload uses port auto-detection; monitor/check tasks prompt for the port, currently COM6.

`platformio.ini` defaults to `mw1_r4_wifi`, the only MW-1 environment. MC-6 remains independent under `mc6`. The unused ATmega328P MW-1 environment was removed to avoid selecting the wrong board target.

```powershell
python tools/check_mw1_display.py COM6 --reinitialize 5 --output .pio/mw1-display-check.jsonl
```

The checker allows for USB startup and calibration, verifies scan/ping/status, checks that pending text drains, and optionally repeats manual initialization. Latest hardware traces are in `.pio/mw1-display-check.jsonl` and `.pio/mw1-reset-verification.jsonl`. Those local measurements are intentionally in the ignored build directory. Controller acknowledgements do not prove the physical pixels or LED colour; inspect the panel as well.

Host tests also decode the software bus's GPIO transitions, check command/data/register bytes, test missing devices/data NACKs/stuck SCL, verify that a new UI update replaces a partial row, and exercise the appliance state machines. Both MW-1 board builds fit their RAM/flash budgets.

## Optional hardware remedy

For a stronger bus that can support normal hardware-I2C speeds, inspect the module/shield for existing pull-ups and measure rise time. On this project's 5 V-only bus, one external pull-up from SDA to 5 V and one from SCL to 5 V is the usual topology. Values around 4.7–5.1 kOhm are a starting point for a short bus, subject to existing parallel resistance, capacitance and the devices' sink-current/rise-time limits. This is a proposed hardware improvement, not a modification that was performed. Recheck the voltage if any 3.3 V-only peripheral is added.

Keep the shield at 5 V, leave its A4 analog connector empty, and reserve A4/A5 for the display. The verified software driver can remain in use without a soldering change.
