# Wiring

All grounds common. The button, the clamp switch and the tube sensor use the Pico's internal pull-ups, so a closed switch or a blocked beam reads as described below. There is no power switch: the unit runs whenever USB is connected.

| Part | Part pin | Pico pin | Notes |
|---|---|---|---|
| SEAL button | leg 1 / leg 2 | GP2 (pin 4) / GND | pressed = LOW |
| CLAMP lever switch (SPDT, over-centre) | common / one throw | GND / GP3 (pin 5) | lever up (jaws closed) = LOW |
| SSD1306 OLED (I2C) | VCC / GND / SDA / SCL | 3V3 pin 36 / GND / GP16 (pin 21) / GP17 (pin 22) | I2C0, address 0x3C, behind the front window |
| Status LED (WS2812, 1 px) | 5V / GND / DIN | VBUS pin 40 / GND / GP15 (pin 20) via 330 Ω | in the lamp bezel on the top deck |
| MOC7811, tube | LED anode / LED cathode | 3V3 via 220 Ω / GND | under the sealing slot |
| | phototransistor C / E | GP7 (pin 10) / GND | tube seated (nub in slot) = HIGH |
| Jaw heater (mock) | gate | GP10 (pin 14) | on only while sealing |
| USB | micro-USB | laptop | power + serial |

## Serial stream (ground truth for the verifier)

One JSON object per line, 115200 baud, sent on every change and once a second as a heartbeat:

```
{"t": 123456, "ev": "btn_seal", "v": 1}
```

| ev | v | Sent when |
|---|---|---|
| btn_seal | 1 down, 0 up | button changes (debounced 20 ms) |
| clamp | 0 open / 1 closed | lever crosses centre |
| tube | 0 clear / 1 seated | tube sensor changes |
| run | "start", "stop", "done", "refused:NO_TUBE", "refused:CLAMP" | seal state changes |

The event names match the device file's firmware channels.
