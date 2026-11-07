# Wiring

All grounds common. Buttons use the Pico's internal pull-ups, so a closed switch reads LOW.

| Part | Part pin | Pico pin | Notes |
|---|---|---|---|
| MODE button | leg 1 / leg 2 | GP2 (pin 4) / GND | pressed = LOW |
| DOWN button | leg 1 / leg 2 | GP3 (pin 5) / GND | pressed = LOW |
| UP button | leg 1 / leg 2 | GP4 (pin 6) / GND | pressed = LOW |
| SSD1306 OLED (I2C) | VCC / GND / SDA / SCL | 3V3 pin 36 / GND / GP16 (pin 21) / GP17 (pin 22) | I2C0, address 0x3C. Mounted upright behind the face's window: no rotation in firmware |
| Status LED (RGB, common cathode) | R / G / B / K | GP13 (pin 17) / GP14 (pin 19) / GP15 (pin 20) / GND | each via 330 Ω. Orange = R full + G about 40% (PWM), blue = B |
| USB | micro-USB | laptop | power + serial. No power switch: the thermostat is on while USB is connected |

## Serial stream (ground truth for the verifier)

One JSON object per line, 115200 baud, sent on every change and once a second as a heartbeat:

```
{"t": 123456, "ev": "setpoint", "v": 205}
```

| ev | v | Sent when |
|---|---|---|
| btn_mode, btn_down, btn_up | 1 down, 0 up | button changes (debounced 20 ms) |
| setpoint | tenths of a degree C (100-300, steps of 5) | UP or DOWN changes it |
| mode | "OFF", "HEAT", "COOL" | MODE changes it |

The setpoint starts at 200 (20.0 °C) and the mode at "OFF" on every power-up. Nothing is kept across power cycles.
