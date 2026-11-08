# Wiring

BG-12 burr coffee grinder. All grounds common. The button, toggle and lid switch use the Pico's internal pull-ups, so a closed switch reads as described below. The burr motor is a placeholder: the grind is shown on the display, and no motor is driven.

| Part | Part pin | Pico pin | Notes |
|---|---|---|---|
| START button | leg 1 / leg 2 | GP2 (pin 4) / GND | pressed = LOW |
| POWER toggle (SPDT) | common / one throw | GND / GP5 (pin 7) | ON = LOW. Software power: the Pico stays on so serial keeps reporting |
| GRIND selector pot (WH148) | end / wiper / end | 3V3(OUT) pin 36 / GP26 ADC0 (pin 31) / AGND pin 33 | settings 1 to 12 over the 270° sweep, clockwise coarser |
| TIME selector pot (WH148, stiff) | end / wiper / end | 3V3(OUT) pin 36 / GP27 ADC1 (pin 32) / AGND pin 33 | 5 to 30 s in steps of 5 over the 270° sweep, clockwise longer |
| Lid switch (lever microswitch) | common / NO | GND / GP6 (pin 9) | lid shut (the lid's fin presses the lever) = LOW |
| SSD1306 OLED (I2C) | VCC / GND / SDA / SCL | 3V3 pin 36 / GND / GP16 (pin 21) / GP17 (pin 22) | I2C0, address 0x3C |
| USB | micro-USB | laptop | power + serial |

## Serial stream (ground truth for the verifier)

One JSON object per line, 115200 baud, sent on every change and once a second as a heartbeat:

```
{"t": 123456, "ev": "time", "v": 15}
```

| ev | v | Sent when |
|---|---|---|
| power | 0 / 1 | toggle flips |
| btn_start | 1 down, 0 up | button changes (debounced 20 ms) |
| grind | setting, 1-12 | GRIND moves a step |
| time | seconds | TIME moves a step |
| lid | 0 open / 1 shut | lid switch changes |
| run | "start", "stop", "done", "refused:LID", "idle" | grind state changes |

The event names match the `serial` field in features.json.
