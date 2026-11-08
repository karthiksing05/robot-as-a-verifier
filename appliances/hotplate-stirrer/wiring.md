# Wiring

All grounds common. The toggle and the beam sensor use the Pico's internal pull-ups, so a closed switch or a blocked beam reads as described below. The heater and the stirrer motor run from a separate supply through the driver board; the Pico only switches them.

| Part | Part pin | Pico pin | Notes |
|---|---|---|---|
| Power toggle (SPDT) | common / one throw | GND / GP5 (pin 7) | ON = LOW. Software power: the Pico stays on so serial keeps reporting |
| HEAT pot (WH148) | end / wiper / end | 3V3(OUT) pin 36 / GP26 ADC0 (pin 31) / AGND pin 33 | 0-300 °C in steps of 25 over the 270° sweep |
| STIR pot (WH148) | end / wiper / end | 3V3(OUT) pin 36 / GP27 ADC1 (pin 32) / AGND pin 33 | 0-1500 rpm in steps of 100 over the 270° sweep |
| SSD1306 OLED (I2C) | VCC / GND / SDA / SCL | 3V3 pin 36 / GND / GP16 (pin 21) / GP17 (pin 22) | I2C0, address 0x3C |
| HOT lamp (red LED) | anode / cathode | GP14 (pin 19) via 220 Ω / GND | lit = HIGH |
| MOC7811, cradle | LED anode / LED cathode | 3V3 via 220 Ω / GND | about 9 mA |
| | phototransistor C / E | GP7 (pin 10) / GND | beaker seated (collar in the beam) = HIGH |
| Heater relay (driver board) | IN | GP10 (pin 14) | on = HIGH |
| Stirrer motor (driver board) | PWM | GP11 (pin 15) | duty from the set speed |
| USB | micro-USB | laptop | power + serial |

## Serial stream (ground truth for the verifier)

One JSON object per line, 115200 baud, sent on every change and once a second as a heartbeat:

```
{"t": 123456, "ev": "heat", "v": 150}
```

| ev | v | Sent when |
|---|---|---|
| power | 0 / 1 | toggle flips |
| heat | set temperature, °C (0-300, steps of 25) | HEAT dial moves a step |
| stir | set speed, rpm (0-1500, steps of 100) | STIR dial moves a step |
| vessel | 0 clear / 1 seated | cradle sensor changes |
| heater | 0 off / 1 on | heater relay switches |
| motor | rpm the stirrer is driven at | stirrer speed changes |
| hot | 0 / 1 | HOT lamp changes |
