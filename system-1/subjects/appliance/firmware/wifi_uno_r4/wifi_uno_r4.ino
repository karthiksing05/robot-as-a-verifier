// A starting point for an appliance on an Arduino UNO R4 WiFi, for Max to change: reads the switches and sends one flat
// JSON snapshot whenever one changes and every 0.5 s otherwise, to USB serial (as the Pico does) and, with
// arduino_secrets.h next to the sketch, POSTed to rav-server over WiFi (rav_wifi.h; ../README.md has the format).
// The pins and channels are placeholders. appliances/*/firmware/MC6_firmware and MW1_firmware do the same for the
// MC-6 and MW-1. Needs only the board package's WiFiS3.

// WiFi status lines go to Serial as comments, not JSON, so a laptop reading this board over USB skips them
#define RAV_LOG(what, v) do { Serial.print(F("# wifi: ")); Serial.print(what); Serial.println(v); } while (0)
#include "rav_wifi.h"

struct Channel { const char *name; uint8_t pin; bool activeLow; };
// each switch wired from its pin to ground, INPUT_PULLUP. A button reads LOW while pressed; the door's reed switch
// reads LOW while the magnet holds the door shut, so DOOR is 1 when open
Channel CHANNELS[] = {{"BTN1", 2, true}, {"BTN2", 3, true}, {"BTN3", 4, true}, {"DOOR", 5, false}};
const uint8_t N = sizeof(CHANNELS) / sizeof(CHANNELS[0]);
const uint16_t SEND_EVERY_MS = 500;   // the laptop gives up on a board after 2 s without a snapshot
const uint16_t DEBOUNCE_MS = 10;      // a reading must hold this long before it counts

uint8_t state[N], last[N];
uint32_t sentAt = 0, sampledAt = 0;

uint8_t readPin(const Channel &c) {
  bool low = digitalRead(c.pin) == LOW;
  return c.activeLow ? low : !low;
}

// {"BTN1":0,"BTN2":1,...}. Add floats with a decimal point (1.0, not 1) and "LCD" as a string.
void snapshot(char *buf, size_t size) {
  int n = snprintf(buf, size, "{");
  for (uint8_t i = 0; i < N; i++) n += snprintf(buf + n, size - n, "%s\"%s\":%u", i ? "," : "", CHANNELS[i].name, state[i]);
  snprintf(buf + n, size - n, "}");
}

void setup() {
  Serial.begin(115200);
  for (uint8_t i = 0; i < N; i++) {
    pinMode(CHANNELS[i].pin, INPUT_PULLUP);
    state[i] = last[i] = readPin(CHANNELS[i]);
  }
#ifdef RAV_WIFI
  rav::begin();
#endif
}

void loop() {
  if (millis() - sampledAt < DEBOUNCE_MS) return;
  sampledAt = millis();
  bool changed = false;
  for (uint8_t i = 0; i < N; i++) {
    uint8_t now = readPin(CHANNELS[i]);
    if (now == last[i] && now != state[i]) { state[i] = now; changed = true; }  // the same twice, DEBOUNCE_MS apart
    last[i] = now;
  }
  char body[128];
  snapshot(body, sizeof(body));
#ifdef RAV_WIFI
  rav::update(body);  // POSTs on a change, and every 0.5 s
#endif
  if (changed || millis() - sentAt >= SEND_EVERY_MS) { sentAt = millis(); Serial.println(body); }
}
