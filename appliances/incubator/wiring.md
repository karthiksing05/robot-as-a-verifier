# Wiring

All grounds common. Buttons, toggle and the door switch use the Pico's internal pull-ups, so a closed switch reads as described below.

| Part | Part pin | Pico pin | Notes |
|---|---|---|---|
| TEMP− button | leg 1 / leg 2 | GP2 (pin 4) / GND | pressed = LOW |
| TEMP+ button | leg 1 / leg 2 | GP3 (pin 5) / GND | pressed = LOW |
| Power toggle (SPDT) | common / one throw | GND / GP5 (pin 7) | ON = LOW. Software power: the Pico stays on so serial keeps reporting |
| Door switch (lever microswitch, NO) | COM / NO | GND / GP6 (pin 9) | under the door's front skirt. Door shut (lever down, within 2°) = LOW |
| SSD1306 OLED (I2C) | VCC / GND / SDA / SCL | 3V3 pin 36 / GND / GP16 (pin 21) / GP17 (pin 22) | I2C0, address 0x3C, behind the front panel window |
| Status LED (bicolour, common cathode) | green / red / K | GP14 (pin 19) via 220 Ω / GP15 (pin 20) via 220 Ω / GND | on the brow, left of the door |
| Heater pad (5 V, 10 W) | + / − | VBUS pin 40 via IRLZ44N drain, gate GP18 (pin 24) via 100 Ω | not driven in the sim: the set temperature only |
| NTC 10k (chamber) | ends | 3V3 via 10k / GP26 ADC0 (pin 31) | not read in the sim |
| USB | micro-USB | laptop | power + serial |

## Serial stream (ground truth for the verifier)

One JSON object per line, 115200 baud, sent on every change and once a second as a heartbeat:

```
{"t": 123456, "ev": "setpoint", "v": 375}
```

| ev | v | Sent when |
|---|---|---|
| power | 0 / 1 | toggle flips |
| btn_down, btn_up | 1 down, 0 up | TEMP− or TEMP+ changes (debounced 20 ms) |
| door | 0 open / 1 shut | door switch changes |
| setpoint | tenths of a °C (250-450) | the set temperature changes, and 370 at each power-on |

The display shows `SET {setpoint/10}C` while the door is shut or has been open under 5 s, and `DOOR` once it has been open 5 s; the LED is green, or red with `DOOR`.
