# Wiring

All grounds common. Buttons, toggle and sensors use the Pico's internal pull-ups, so a closed switch or a blocked beam reads as described below.

| Part | Part pin | Pico pin | Notes |
|---|---|---|---|
| Start button | leg 1 / leg 2 | GP2 (pin 4) / GND | pressed = LOW |
| Stop button | leg 1 / leg 2 | GP3 (pin 5) / GND | pressed = LOW |
| Time+ button | leg 1 / leg 2 | GP4 (pin 6) / GND | pressed = LOW |
| Power toggle (SPDT) | common / one throw | GND / GP5 (pin 7) | ON = LOW. Software power: the Pico stays on so serial keeps reporting |
| Speed pot (WH148) | end / wiper / end | 3V3(OUT) pin 36 / GP26 ADC0 (pin 31) / AGND pin 33 | 1000-6000 rpm mapped over the 270° sweep |
| SSD1306 OLED (I2C) | VCC / GND / SDA / SCL | 3V3 pin 36 / GND / GP16 (pin 21) / GP17 (pin 22) | I2C0, address 0x3C. Mounted header-down: rotate the display 180° in firmware |
| NeoPixel ring, 24 px | 5V / GND / DIN | VBUS pin 40 / GND / GP15 (pin 20) via 330 Ω | cap brightness at about 20% (full white is ~1.4 A, over a laptop USB port) |
| MOC7811, lid | LED anode / LED cathode | 3V3 via 220 Ω / GND | about 9 mA |
| | phototransistor C / E | GP6 (pin 9) / GND | lid closed (tab in slot) = HIGH |
| MOC7811, tube | LED anode / LED cathode | 3V3 via 220 Ω / GND | |
| | phototransistor C / E | GP7 (pin 10) / GND | tube seated (nub in slot) = HIGH |
| USB | micro-USB | laptop | power + serial |

## Serial stream (ground truth for the verifier)

One JSON object per line, 115200 baud, sent on every change and once a second as a heartbeat:

```
{"t": 123456, "ev": "btn_stop", "v": 1}
```

| ev | v | Sent when |
|---|---|---|
| power | 0 / 1 | toggle flips |
| btn_start, btn_stop, btn_time | 1 down, 0 up | button changes (debounced 20 ms) |
| speed | rpm (1000-6000, steps of 100) | dial moves a step |
| lid | 0 open / 1 closed | lid sensor changes |
| tube | 0 clear / 1 seated | tube sensor changes |
| run | "start", "stop", "done", "refused:LID", "refused:TUBE" | run state changes |
| time | seconds | Time+ or countdown |

The event names match the `serial` field in features.json.
