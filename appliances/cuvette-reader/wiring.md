# Wiring

All grounds common. Buttons, toggle and sensors use the Pico's internal pull-ups, so a closed switch or a blocked beam reads as described below.

| Part | Part pin | Pico pin | Notes |
|---|---|---|---|
| BLANK button | leg 1 / leg 2 | GP2 (pin 4) / GND | pressed = LOW |
| READ button | leg 1 / leg 2 | GP3 (pin 5) / GND | pressed = LOW |
| Power toggle (SPDT) | common / one throw | GND / GP5 (pin 7) | ON = LOW. Software power: the Pico stays on so serial keeps reporting |
| 16x2 character LCD (I2C backpack) | VCC / GND / SDA / SCL | VBUS pin 40 / GND / GP16 (pin 21) / GP17 (pin 22) | I2C0, address 0x27 |
| Status LED (RGB, common cathode) | R / G / B / K | GP13 / GP14 / GP15 via 220 Ω each / GND | green ready or done, blue measuring, red refused |
| Lid switch (MOC7811) | LED anode / LED cathode | 3V3 via 220 Ω / GND | the lid's flag sits in the slot when the lid is down |
| | phototransistor C / E | GP6 (pin 9) / GND | lid closed = HIGH |
| Cuvette beam (IR LED + phototransistor across the chamber floor) | LED anode / LED cathode | 3V3 via 220 Ω / GND | about 9 mA |
| | phototransistor C / E | GP7 (pin 10) / GND | cuvette seated (beam blocked) = HIGH |
| 600 nm LED + photodiode (measurement path) | LED / photodiode | GP18 via 100 Ω / GP26 ADC0 (pin 31) | read only during BLANKING and READING |
| USB | micro-USB | laptop | power + serial |

## Serial stream (ground truth for the verifier)

One JSON object per line, 115200 baud, sent on every change and once a second as a heartbeat:

```
{"t": 123456, "ev": "btn_read", "v": 1}
```

| ev | v | Sent when |
|---|---|---|
| power | 0 / 1 | toggle flips |
| btn_blank, btn_read | 1 down, 0 up | button changes (debounced 20 ms) |
| lid | 0 open / 1 closed | lid switch changes |
| cuvette | 0 clear / 1 seated | cuvette beam changes |
| meas | "idle", "blanking", "blanked", "reading", "read", "refused:LID", "refused:BLANK", "refused:SAMPLE" | measurement state changes |

The event names match the `serial` field in features.json.
