# Wiring

All grounds common. Buttons, toggle and the cover sensor use the Pico's internal pull-ups, so a closed switch or a blocked beam reads as described below.

| Part | Part pin | Pico pin | Notes |
|---|---|---|---|
| FEED button | leg 1 / leg 2 | GP2 (pin 4) / GND | pressed = LOW |
| PRINT button | leg 1 / leg 2 | GP3 (pin 5) / GND | pressed = LOW |
| Power toggle (SPDT) | common / one throw | GND / GP5 (pin 7) | ON = LOW. Software power: the Pico stays on so serial keeps reporting |
| Darkness pot (WH148) | end / wiper / end | 3V3(OUT) pin 36 / GP26 ADC0 (pin 31) / AGND pin 33 | 1 to 9 over the 270° sweep, clockwise darker |
| SSD1306 OLED (I2C) | VCC / GND / SDA / SCL | 3V3 pin 36 / GND / GP16 (pin 21) / GP17 (pin 22) | I2C0, address 0x3C, behind the front panel |
| Status LED (one NeoPixel) | 5V / GND / DIN | VBUS pin 40 / GND / GP15 (pin 20) via 330 Ω | under the deck's light window |
| MOC7811, cover | LED anode / LED cathode | 3V3 via 220 Ω / GND | about 9 mA |
| | phototransistor C / E | GP6 (pin 9) / GND | cover closed (fin in slot) = HIGH |
| Print head | (stand-in) | none | the kit has no head: firmware runs a 3 s print timer |
| USB | micro-USB | laptop | power + serial |

## Serial stream (ground truth for the verifier)

One JSON object per line, 115200 baud, sent on every change and once a second as a heartbeat:

```
{"t": 123456, "ev": "btn_print", "v": 1}
```

| ev | v | Sent when |
|---|---|---|
| power | 0 / 1 | toggle flips |
| btn_feed, btn_print | 1 down, 0 up | button changes (debounced 20 ms) |
| darkness | 1 to 9 | dial moves a step |
| cover | 0 open / 1 closed | cover sensor changes |
| count | labels printed since power-on | a print finishes, or power-on resets it |
| run | "feed", "start", "done", "idle", "refused:COVER" | run state changes |
