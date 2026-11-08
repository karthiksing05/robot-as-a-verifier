# Wiring

All grounds common. The button, toggle and beam sensor use the Pico's internal pull-ups, so a closed switch or a blocked beam reads as described below. The mixer has no power switch: it runs whenever USB is connected.

| Part | Part pin | Pico pin | Notes |
|---|---|---|---|
| START button | leg 1 / leg 2 | GP2 (pin 4) / GND | pressed = LOW |
| MODE toggle (SPDT) | common / one throw | GND / GP5 (pin 7) | lever up (TOUCH) = LOW |
| SPEED pot (WH148) | end / wiper / end | 3V3(OUT) pin 36 / GP26 ADC0 (pin 31) / AGND pin 33 | 500-3000 rpm over the 270° sweep, steps of 100 |
| SSD1306 OLED (I2C) | VCC / GND / SDA / SCL | 3V3 pin 36 / GND / GP16 (pin 21) / GP17 (pin 22) | I2C0, address 0x3C, on the front panel |
| MOC7811, cup head | LED anode / LED cathode | 3V3 via 220 Ω / GND | about 9 mm under the head's top, across the bore |
| | phototransistor C / E | GP7 (pin 10) / GND | cup seated (tip in the beam) = HIGH |
| Motor driver (DRV8871) | IN1 / IN2 | GP14 (pin 19) PWM / GND | 5 V motor under the cup head; rpm from PWM duty |
| USB | micro-USB | laptop | power + serial |

## Serial stream (ground truth for the verifier)

One JSON object per line, 115200 baud, sent on every change and once a second as a heartbeat:

```
{"t": 123456, "ev": "rpm", "v": 1500}
```

| ev | v | Sent when |
|---|---|---|
| btn_start | 1 down, 0 up | button changes (debounced 20 ms) |
| touch | 1 TOUCH / 0 ON | the MODE switch's mode changes |
| speed | set rpm (500-3000, steps of 100) | the dial moves a step |
| cup | 0 clear / 1 seated | the head's beam changes |
| rpm | head speed, 0 when stopped | mixing starts, stops or changes speed |
| run | "start", "stop", "idle", "refused:CUP" | run state changes |
