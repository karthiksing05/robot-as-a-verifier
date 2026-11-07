# Wiring

All grounds common. Buttons and the toggle use the Pico's internal pull-ups, so a closed switch reads LOW.

| Part | Part pin | Pico pin | Notes |
|---|---|---|---|
| +MIN button | leg 1 / leg 2 | GP2 (pin 4) / GND | pressed = LOW. Closes at 0.2 mm of its 0.3 mm travel |
| +SEC button | leg 1 / leg 2 | GP3 (pin 5) / GND | pressed = LOW |
| START/STOP button | leg 1 / leg 2 | GP4 (pin 6) / GND | pressed = LOW. 14 mm cap |
| Power toggle (SPDT) | common / one throw | GND / GP5 (pin 7) | ON = LOW. Software power: the Pico stays on so serial keeps reporting |
| SSD1306 OLED 128×32 (I2C) | VCC / GND / SDA / SCL | 3V3 pin 36 / GND / GP16 (pin 21) / GP17 (pin 22) | I2C0, address 0x3C. Behind the front bezel window |
| Status LED, RGB NeoPixel (1 px) | 5V / GND / DIN | VBUS pin 40 / GND / GP15 (pin 20) via 330 Ω | under the lens on top. Blue running, green done, off otherwise |
| USB | micro-USB | laptop | power + serial, through the port at the back |

## Serial stream (ground truth for the verifier)

One JSON object per line, 115200 baud, sent on every change and once a second as a heartbeat:

```
{"t": 123456, "ev": "btn_go", "v": 1}
```

| ev | v | Sent when |
|---|---|---|
| power | 0 / 1 | toggle flips |
| btn_min, btn_sec, btn_go | 1 down, 0 up | button changes (debounced 20 ms). btn_go is START/STOP |
| time | seconds set (0 to 5999) | +MIN or +SEC changes the set time, or power off clears it |
| run | "start", "pause", "resume", "done", "idle" | run state changes |

The countdown itself is shown on the display only; `time` keeps the set time so DONE can recall it.
