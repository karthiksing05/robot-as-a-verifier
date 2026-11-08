// MC-6 Mini Centrifuge firmware, v1.1
// Arduino Uno or UNO R4 WiFi + Grove Base Shield v2 (VCC switch on 5V).
// Libraries: U8g2 (2.34+), Adafruit NeoPixel (1.12+).
// Serial: 115200 baud, one JSON object per line. Commands: ping, status, cal, reset.
// WiFi (UNO R4 WiFi with arduino_secrets.h): also POSTs a snapshot of every channel to rav-server (rav_wifi.h).

#include <Arduino.h>
#include <Wire.h>
#include <U8x8lib.h>
#include <Adafruit_NeoPixel.h>
#include "rav_wifi.h"

// ---------------- pins
const uint8_t PIN_START = 2;     // INPUT_PULLUP, LOW = pressed
const uint8_t PIN_STOP = 3;
const uint8_t PIN_TIME = 4;
const uint8_t PIN_POWER = 5;     // SPDT toggle, LOW = ON
const uint8_t PIN_RING = 6;      // 24 x WS2812B, GRB
const uint8_t PIN_SPEED = A0;    // 10k pot
const uint8_t PIN_LID = A2;      // Grove light sensor, shaded = lid closed
const uint8_t PIN_TUBE = A1;     // Grove light sensor under well A, shaded = tube seated

// ---------------- tuning
const uint8_t RING_N = 24;
const uint8_t RING_BRIGHT = 50;          // cap: 24 LEDs at 50/255 stay well under the USB budget
const uint16_t DEBOUNCE_MS = 20;
const uint8_t SHADE_PCT = 55;            // shaded when below 55 % of the calibrated (open) level
const uint8_t CLEAR_PCT = 70;            // clear again when above 70 %
const uint8_t CAL_SAMPLES = 16;
const uint8_t READ_SAMPLES = 8;
const uint16_t SENSOR_PERIOD_MS = 50;
const bool SPEED_INVERT = false;         // set true if clockwise lowers the reading
const uint16_t RPM_MIN = 1000, RPM_MAX = 6000, RPM_STEP = 100;
const uint16_t SPEED_HYST = 6;           // ADC counts a step must be passed by before it changes
const uint16_t TIME_DEFAULT = 30, TIME_STEP = 10, TIME_MAX = 600;
const uint32_t DONE_HOLD_MS = 60000;
const uint32_t TUBE_SETTLE_MS = 300;     // ring must be steady this long before a tube reading counts

U8X8_SSD1306_128X64_NONAME_HW_I2C oled(U8X8_PIN_NONE);
Adafruit_NeoPixel ring(RING_N, PIN_RING, NEO_GRB + NEO_KHZ800);

// ---------------- state
enum State : uint8_t { S_OFF, S_READY, S_RUNNING, S_DONE, S_REFUSED };
const char *const STATE_NAME[] = {"off", "ready", "running", "done", "refused"};
State st = S_OFF;
uint16_t rpm = RPM_MIN, setTime = TIME_DEFAULT, left = 0;
char reason[5] = "";
uint32_t stateSince = 0, lastTick = 0, ringSteadySince = 0;
const char *lastRun = "";        // the last run event's value, for the WiFi snapshot

struct Btn { uint8_t pin; const char *ev; bool stable; bool raw; uint32_t changed; };
Btn btns[] = {{PIN_START, "btn_start", 0, 0, 0}, {PIN_STOP, "btn_stop", 0, 0, 0},
              {PIN_TIME, "btn_time", 0, 0, 0}, {PIN_POWER, "power", 0, 0, 0}};
enum { B_START, B_STOP, B_TIME, B_POWER };

struct Light { uint8_t pin; const char *ev; uint16_t cal; uint16_t raw; bool shaded; };
Light lid = {PIN_LID, "lid", 0, 0, false};
Light tube = {PIN_TUBE, "tube", 0, 0, false};
uint16_t speedRaw = 0;
uint32_t lastSensor = 0, lastHb = 0;
uint8_t ringPos = 0; uint32_t lastSpin = 0;
char line1[17] = "", line2[17] = "";
const char *ringName = "off";

// ---------------- serial helpers
#if defined(__AVR__)
int freeRam() { extern int __heap_start, *__brkval; int v; return (int)&v - (__brkval == 0 ? (int)&__heap_start : (int)__brkval); }
#else
int freeRam() { return -1; }     // the R4 has 32 KB: nothing to watch
#endif
void evStart(const __FlashStringHelper *ev) { Serial.print(F("{\"t\":")); Serial.print(millis()); Serial.print(F(",\"ev\":\"")); Serial.print(ev); Serial.print('"'); }
void evStart(const char *ev) { Serial.print(F("{\"t\":")); Serial.print(millis()); Serial.print(F(",\"ev\":\"")); Serial.print(ev); Serial.print('"'); }
void evInt(const char *ev, long v) { evStart(ev); Serial.print(F(",\"v\":")); Serial.print(v); Serial.println('}'); }
void evStr(const __FlashStringHelper *ev, const char *v) { evStart(ev); Serial.print(F(",\"v\":\"")); Serial.print(v); Serial.println(F("\"}")); }
void evRun(const char *v) { lastRun = v; evStr(F("run"), v); }

// ---------------- sensors
uint16_t avgRead(uint8_t pin, uint8_t n) { uint32_t s = 0; for (uint8_t i = 0; i < n; i++) s += analogRead(pin); return s / n; }

void calibrate() {
  // assumes lid open, no tube, ring steady white (it is made white here)
  for (uint8_t i = 0; i < RING_N; i++) ring.setPixelColor(i, ring.Color(255, 255, 255));
  ring.show(); delay(150);
  lid.cal = avgRead(lid.pin, CAL_SAMPLES);
  tube.cal = avgRead(tube.pin, CAL_SAMPLES);
  lid.shaded = tube.shaded = false;
  evStart(F("cal")); Serial.print(F(",\"lid\":")); Serial.print(lid.cal); Serial.print(F(",\"tube\":")); Serial.print(tube.cal);
  Serial.println(F(",\"note\":\"calibrate with the lid OPEN and no tube in well A\"}"));
}

bool updateLight(Light &L) {   // returns true if the state changed
  L.raw = avgRead(L.pin, READ_SAMPLES);
  bool s = L.shaded;
  if (!L.shaded && (uint32_t)L.raw * 100 < (uint32_t)L.cal * SHADE_PCT) s = true;
  else if (L.shaded && (uint32_t)L.raw * 100 > (uint32_t)L.cal * CLEAR_PCT) s = false;
  if (s == L.shaded) return false;
  L.shaded = s;
  evStart(L.ev); Serial.print(F(",\"v\":")); Serial.print(s ? 1 : 0); Serial.print(F(",\"raw\":")); Serial.print(L.raw); Serial.println('}');
  return true;
}

// the ring lights the tube sensor from below; readings only count under the steady white it was calibrated with
bool ringSteady() { return !strcmp(ringName, "white") && millis() - ringSteadySince >= TUBE_SETTLE_MS; }

void readSpeed() {
  uint16_t a = avgRead(PIN_SPEED, 4);
  if (SPEED_INVERT) a = 1023 - a;
  speedRaw = a;
  const uint16_t steps = (RPM_MAX - RPM_MIN) / RPM_STEP;   // 50
  uint16_t cur = (rpm - RPM_MIN) / RPM_STEP;
  // band edges for the current step, widened by SPEED_HYST
  long lo = (long)cur * 1023 / steps - (long)1023 / steps / 2 - SPEED_HYST;
  long hi = (long)cur * 1023 / steps + (long)1023 / steps / 2 + SPEED_HYST;
  if ((long)a < lo || (long)a > hi) {
    uint16_t n = ((uint32_t)a * steps + 511) / 1023;
    uint16_t r = RPM_MIN + n * RPM_STEP;
    if (r != rpm) { rpm = r; if (st != S_OFF && st != S_RUNNING) evInt("speed", rpm); }
  }
}

// ---------------- UI
void setRing(uint8_t r, uint8_t g, uint8_t b, const char *name) {
  for (uint8_t i = 0; i < RING_N; i++) ring.setPixelColor(i, ring.Color(r, g, b));
  ring.show(); ringName = name; ringSteadySince = millis();
}

void showLines(const char *a, const char *b) {
  if (strcmp(a, line1) == 0 && strcmp(b, line2) == 0) return;
  strncpy(line1, a, 16); line1[16] = 0; strncpy(line2, b, 16); line2[16] = 0;
  oled.clear();
  oled.draw2x2String(0, 1, line1);   // 8 chars wide at 2x2
  oled.draw2x2String(0, 5, line2);
}

void fmtTime(char *out, uint16_t s) { sprintf(out, "%u:%02u", s / 60, s % 60); }

void refreshUi() {
  char a[17], b[17];
  switch (st) {
    case S_OFF: oled.clear(); line1[0] = line2[0] = 0; ring.clear(); ring.show(); ringName = "off"; return;
    case S_READY: sprintf(a, "%u", rpm); fmtTime(b, setTime); strcat(a, "rpm"); showLines(a, b); if (strcmp(ringName, "white")) setRing(255, 255, 255, "white"); return;
    case S_RUNNING: sprintf(a, "%u", rpm); fmtTime(b, left); strcat(a, "rpm"); showLines(a, b); ringName = "blue"; return;
    case S_DONE: showLines("DONE", ""); if (strcmp(ringName, "green")) setRing(0, 255, 0, "green"); return;
    case S_REFUSED: showLines(reason, ""); if (strcmp(ringName, "red")) setRing(255, 0, 0, "red"); return;
  }
}

void spin() {   // one lit segment going round, faster with rpm
  uint16_t period = map(rpm, RPM_MIN, RPM_MAX, 120, 25);
  if (millis() - lastSpin < period) return;
  lastSpin = millis();
  ring.clear();
  for (uint8_t k = 0; k < 3; k++) ring.setPixelColor((ringPos + RING_N - k) % RING_N, ring.Color(0, 0, 255 >> k));
  ring.show(); ringPos = (ringPos + 1) % RING_N;
}

// ---------------- state machine
void go(State s) { st = s; stateSince = millis(); refreshUi(); }

void powerOn() { setTime = TIME_DEFAULT; left = 0; readSpeed(); go(S_READY); }

void onPress(uint8_t i) {
  if (st == S_OFF) return;                       // events still go out, but nothing happens
  if (i == B_START) {
    if (st == S_RUNNING) return;
    if (!lid.shaded) { strcpy(reason, "LID"); evRun("refused:LID"); go(S_REFUSED); return; }
    // tube is judged on the last reading taken while the ring was steady
    if (!tube.shaded) { strcpy(reason, "TUBE"); evRun("refused:TUBE"); go(S_REFUSED); return; }
    left = setTime; lastTick = millis(); evRun("start"); go(S_RUNNING);
  } else if (i == B_STOP) {
    if (st == S_RUNNING) { evRun("stop"); go(S_READY); }
    else if (st == S_READY) { setTime = TIME_DEFAULT; evInt("time", setTime); refreshUi(); }
    else go(S_READY);
  } else if (i == B_TIME) {
    if (st == S_RUNNING) return;
    if (setTime + TIME_STEP <= TIME_MAX) setTime += TIME_STEP;
    evInt("time", setTime);
    go(S_READY);
  }
}

void readButtons() {
  for (uint8_t i = 0; i < 4; i++) {
    Btn &b = btns[i];
    bool r = digitalRead(b.pin) == LOW;
    if (r != b.raw) { b.raw = r; b.changed = millis(); }
    if (r != b.stable && millis() - b.changed >= DEBOUNCE_MS) {
      b.stable = r;
      evInt(b.ev, r ? 1 : 0);
      if (i == B_POWER) { if (r) powerOn(); else { left = 0; if (st == S_RUNNING) evRun("stop"); go(S_OFF); } }
      else if (r) onPress(i);
    }
  }
}

void heartbeat() {
  evStart(F("hb"));
  Serial.print(F(",\"state\":\"")); Serial.print(STATE_NAME[st]);
  Serial.print(F("\",\"power\":")); Serial.print(btns[B_POWER].stable);
  Serial.print(F(",\"btn_start\":")); Serial.print(btns[B_START].stable);
  Serial.print(F(",\"btn_stop\":")); Serial.print(btns[B_STOP].stable);
  Serial.print(F(",\"btn_time\":")); Serial.print(btns[B_TIME].stable);
  Serial.print(F(",\"speed\":")); Serial.print(rpm); Serial.print(F(",\"speed_raw\":")); Serial.print(speedRaw);
  Serial.print(F(",\"time\":")); Serial.print(setTime); Serial.print(F(",\"left\":")); Serial.print(left);
  Serial.print(F(",\"lid\":")); Serial.print(lid.shaded); Serial.print(F(",\"lid_raw\":")); Serial.print(lid.raw); Serial.print(F(",\"lid_cal\":")); Serial.print(lid.cal);
  Serial.print(F(",\"tube\":")); Serial.print(tube.shaded); Serial.print(F(",\"tube_raw\":")); Serial.print(tube.raw); Serial.print(F(",\"tube_cal\":")); Serial.print(tube.cal);
  Serial.print(F(",\"lcd\":[\"")); Serial.print(line1); Serial.print(F("\",\"")); Serial.print(line2);
  Serial.print(F("\"],\"ring\":\"")); Serial.print(ringName); Serial.println(F("\"}"));
}

void handleSerial() {
  static char buf[12]; static uint8_t n = 0;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c != '\n') { if (n < sizeof(buf) - 1) buf[n++] = tolower(c); continue; }
    buf[n] = 0; n = 0;
    if (!strcmp(buf, "ping")) Serial.println(F("{\"ev\":\"pong\"}"));
    else if (!strcmp(buf, "status")) heartbeat();
    else if (!strcmp(buf, "cal")) { calibrate(); refreshUi(); }
    else if (!strcmp(buf, "reset")) { if (btns[B_POWER].stable) powerOn(); else go(S_OFF); evRun("reset"); }
    else if (buf[0]) Serial.println(F("{\"ev\":\"error\",\"msg\":\"unknown command\"}"));
  }
}

#ifdef RAV_WIFI
// Every channel the sim's device has (device.yaml's firmware.channels, minus its sim-only tube_raw_*), plus state, ring
// and the display's two lines as LCD, joined as the sim shows them. time is what the time events say: the set time,
// or what's left while running.
void snapshot(char *o, size_t n) {
  char shown[36];
  if (line2[0]) snprintf(shown, sizeof(shown), "%s  %s", line1, line2); else snprintf(shown, sizeof(shown), "%s", line1);
  snprintf(o, n, "{\"power\":%u,\"btn_start\":%u,\"btn_stop\":%u,\"btn_time\":%u,\"speed\":%u,\"lid\":%u,\"tube\":%u,"
           "\"run\":\"%s\",\"time\":%u,\"state\":\"%s\",\"ring\":\"%s\",\"LCD\":\"%s\"}",
           btns[B_POWER].stable, btns[B_START].stable, btns[B_STOP].stable, btns[B_TIME].stable, rpm, lid.shaded,
           tube.shaded, lastRun, st == S_RUNNING ? left : setTime, STATE_NAME[st], ringName, shown);
}
#endif

void setup() {
  Serial.begin(115200);
  for (uint8_t i = 0; i < 4; i++) pinMode(btns[i].pin, INPUT_PULLUP);
  ring.begin(); ring.setBrightness(RING_BRIGHT); ring.clear(); ring.show();   // brightness before the first show
  oled.begin(); oled.setFont(u8x8_font_chroma48medium8_r);
  Serial.print(F("{\"t\":")); Serial.print(millis()); Serial.print(F(",\"ev\":\"hello\",\"dev\":\"MC-6\",\"fw\":\"1.0\",\"ram\":")); Serial.print(freeRam()); Serial.println('}');
  calibrate();
  ring.clear(); ring.show();
  for (uint8_t i = 0; i < 4; i++) { btns[i].raw = btns[i].stable = digitalRead(btns[i].pin) == LOW; }
  evInt("power", btns[B_POWER].stable);
  if (btns[B_POWER].stable) powerOn(); else go(S_OFF);
#ifdef RAV_WIFI
  rav::begin();                  // blocks a few seconds while it joins; the display is already up
#endif
}

void loop() {
  handleSerial();
  readButtons();
  uint32_t now = millis();
  if (now - lastSensor >= SENSOR_PERIOD_MS) {
    lastSensor = now;
    readSpeed();
    if (st == S_READY && rpm != 0) refreshUi();
    bool lidChanged = updateLight(lid);
    if (ringSteady()) updateLight(tube);         // tube only read under a steady ring colour
    if (st == S_RUNNING && lidChanged && !lid.shaded) { strcpy(reason, "LID"); left = 0; evRun("abort:LID"); go(S_REFUSED); }
    if (st == S_REFUSED && !strcmp(reason, "LID") && lid.shaded) go(S_READY);   // TUBE clears on any button press
    if (st == S_DONE && !lid.shaded) go(S_READY);
  }
  if (st == S_RUNNING) {
    spin();
    if (now - lastTick >= 1000) {
      lastTick += 1000;
      if (left) left--;
      evInt("time", left);
      if (left == 0) { evRun("done"); go(S_DONE); } else refreshUi();
    }
  }
  if (st == S_DONE && now - stateSince >= DONE_HOLD_MS) go(S_READY);
  if (now - lastHb >= 1000) { lastHb = now; heartbeat(); }
#ifdef RAV_WIFI
  static uint32_t lastSnap = 0;
  if (now - lastSnap >= 10) { lastSnap = now; char b[RAV_SNAPSHOT_MAX]; snapshot(b, sizeof(b)); rav::update(b); }
#endif
}
