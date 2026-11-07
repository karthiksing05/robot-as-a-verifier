# Wiring

KB-1 temperature kettle (RAAV test device). All grounds common. Buttons, toggle and the lid switch use the Pico's internal pull-ups, so a closed switch reads as described below. The heater is a placeholder: the firmware times the heat and drives only the display and the ring.

| Part | Part pin | Pico pin | Notes |
|---|---|---|---|
| BOIL button | leg 1 / leg 2 | GP2 (pin 4) / GND | pressed = LOW |
| WARM button | leg 1 / leg 2 | GP3 (pin 5) / GND | pressed = LOW |
| Power toggle (SPDT) | common / one throw | GND / GP5 (pin 7) | ON = LOW. Software power: the Pico stays on so serial keeps reporting |
| TEMP encoder (EC11, no switch) | A / C / B | GP10 (pin 14) / GND / GP11 (pin 15) | quadrature; one count per 15° click, clockwise counts up |
| Lid microswitch (lever) | COM / NO | GND / GP6 (pin 9) | closed only when the lid is fully down (within 2°): lid closed = LOW |
| SSD1306 OLED (I2C) | VCC / GND / SDA / SCL | 3V3 pin 36 / GND / GP16 (pin 21) / GP17 (pin 22) | I2C0, address 0x3C, behind the front panel window |
| NeoPixel ring, 24 px (heater ring) | 5V / GND / DIN | VBUS pin 40 / GND / GP15 (pin 20) via 330 Ω | under the jug's foot; cap brightness at about 20% |
| USB | micro-USB | laptop | power + serial |

## Serial stream (ground truth for the verifier)

One JSON object per line, 115200 baud, sent on every change and once a second as a heartbeat:

```
{"t": 123456, "ev": "btn_boil", "v": 1}
```

| ev | v | Sent when |
|---|---|---|
| power | 0 / 1 | toggle flips |
| btn_boil, btn_warm | 1 down, 0 up | button changes (debounced 20 ms) |
| knob | encoder count since boot | the dial moves a click |
| temp | set temperature, °C (60-100, steps of 5) | power-on, or the dial changes it |
| warm | 0 off / 1 on | keep-warm toggles, or resets at power-on |
| lid | 0 open / 1 closed | lid switch changes |
| run | "start", "stop", "done", "warm", "idle", "refused:LID" | heating state changes |

The event names match the device file's firmware channels.
