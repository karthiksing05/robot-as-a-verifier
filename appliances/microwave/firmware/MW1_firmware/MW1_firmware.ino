// MW-1 Mock Microwave firmware, v1.1
// Arduino Uno or UNO R4 WiFi + Grove Base Shield v2 (VCC switch on 5V).
// Library: Grove - LCD RGB Backlight (Seeed, rgb_lcd.h).
// Serial: 115200 baud, one JSON object per line. Commands: ping, status, cal, reset.
// WiFi (UNO R4 WiFi with arduino_secrets.h): also POSTs a snapshot of every channel to rav-server (rav_wifi.h).

#include <Arduino.h>
#include <Wire.h>
#include "rgb_lcd.h"
#include "rav_wifi.h"

// ---------------- pins
const uint8_t PIN_START = 2;     // INPUT_PULLUP, LOW = pressed
const uint8_t PIN_STOP = 3;
const uint8_t PIN_TIME = 4;
const uint8_t PIN_POWER = 5;
const uint8_t PIN_ADD30 = 6;
const uint8_t PIN_BUZZER = 8;    // Grove Buzzer on shield port D8, HIGH = sound
const uint8_t PIN_DOOR = A0;     // Grove light sensor, shaded = door shut

// ---------------- tuning
const uint16_t DEBOUNCE_MS = 20;
const uint8_t SHADE_PCT = 55;    // shaded when below 55 % of the calibrated (door open) level
const uint8_t CLEAR_PCT = 70;    // clear again when above 70 %
const uint8_t CAL_SAMPLES = 16;
const uint8_t READ_SAMPLES = 8;
const uint16_t SENSOR_PERIOD_MS = 50;
const uint16_t TIME_MAX = 1800;
const uint16_t MSG_MS = 2000;
const uint16_t DONE_MS = 10000;
const bool BUZZER_TONE = true;   // true: tone() with pitches; false: plain on/off (if your buzzer only clicks with tone())
const uint16_t BEEP_HZ = 2700, LOW_HZ = 900;
const uint16_t BEEP_MS = 60, DONE_BEEP_MS = 200, LOW_BEEP_MS = 150, GAP_MS = 120;

rgb_lcd lcd;

enum State : uint8_t { S_READY, S_SET, S_COOK, S_PAUSED, S_DOOR, S_DONE };
const char *const STATE_NAME[] = {"ready", "set", "cooking", "paused", "door_open", "done"};
State st = S_READY;
uint16_t cookTime = 0;            // seconds left (or set)
uint8_t power = 0;                // 0 HI, 1 MED, 2 LO
const char *const PWR[] = {"HI", "MED", "LO"};
uint32_t stateSince = 0, lastTick = 0;
const char *msg = nullptr; bool msgRed = false; uint32_t msgSince = 0;
const char *lastCook = "";       // the last cook event's value, for the WiFi snapshot

struct Btn { uint8_t pin; const char *ev; bool stable; bool raw; uint32_t changed; };
Btn btns[] = {{PIN_START, "btn_start", 0, 0, 0}, {PIN_STOP, "btn_stop", 0, 0, 0}, {PIN_TIME, "btn_time", 0, 0, 0},
              {PIN_POWER, "btn_power", 0, 0, 0}, {PIN_ADD30, "btn_30s", 0, 0, 0}};
enum { B_START, B_STOP, B_TIME, B_POWER, B_ADD30 };

uint16_t doorCal = 0, doorRaw = 0; bool doorShut = false;
uint32_t lastSensor = 0, lastHb = 0;
char line1[17] = "", line2[17] = ""; uint8_t bl[3] = {0, 0, 0}; const char *blName = "off";

// ---------------- buzzer: a small queue of (hz, on ms, off ms), played without blocking
struct Note { uint16_t hz, on, off; };
Note q[6]; uint8_t qn = 0, qi = 0; bool sounding = false; uint32_t noteAt = 0;
void play(const Note *n, uint8_t k) { for (uint8_t i = 0; i < k; i++) q[i] = n[i]; qn = k; qi = 0; sounding = false; noteAt = 0; }
void keyBeep() { Note n[] = {{BEEP_HZ, BEEP_MS, 0}}; play(n, 1); }
void doneBeeps() { Note n[] = {{BEEP_HZ, DONE_BEEP_MS, GAP_MS}, {BEEP_HZ, DONE_BEEP_MS, GAP_MS}, {BEEP_HZ, DONE_BEEP_MS, 0}}; play(n, 3); }
void refuseBeeps() { Note n[] = {{LOW_HZ, LOW_BEEP_MS, GAP_MS}, {LOW_HZ, LOW_BEEP_MS, 0}}; play(n, 2); }
void buzzOn(uint16_t hz) { if (BUZZER_TONE) tone(PIN_BUZZER, hz); else digitalWrite(PIN_BUZZER, HIGH); }
void buzzOff() { if (BUZZER_TONE) noTone(PIN_BUZZER); digitalWrite(PIN_BUZZER, LOW); }
void buzzer() {
  if (qi >= qn) return;
  uint32_t now = millis();
  if (!sounding && now >= noteAt) { buzzOn(q[qi].hz); sounding = true; noteAt = now + q[qi].on; }
  else if (sounding && now >= noteAt) { buzzOff(); sounding = false; noteAt = now + q[qi].off; qi++; }
}

// ---------------- serial helpers
#if defined(__AVR__)
int freeRam() { extern int __heap_start, *__brkval; int v; return (int)&v - (__brkval == 0 ? (int)&__heap_start : (int)__brkval); }
#else
int freeRam() { return -1; }     // the R4 has 32 KB: nothing to watch
#endif
void evStart(const char *ev) { Serial.print(F("{\"t\":")); Serial.print(millis()); Serial.print(F(",\"ev\":\"")); Serial.print(ev); Serial.print('"'); }
void evInt(const char *ev, long v) { evStart(ev); Serial.print(F(",\"v\":")); Serial.print(v); Serial.println('}'); }
void evStr(const char *ev, const char *v) { evStart(ev); Serial.print(F(",\"v\":\"")); Serial.print(v); Serial.println(F("\"}")); }
void evCook(const char *v) { lastCook = v; evStr("cook", v); }

// ---------------- door sensor
uint16_t avgRead(uint8_t pin, uint8_t n) { uint32_t s = 0; for (uint8_t i = 0; i < n; i++) s += analogRead(pin); return s / n; }
void calibrate() {   // assumes the door is OPEN
  doorCal = avgRead(PIN_DOOR, CAL_SAMPLES); doorShut = false;
  evStart("cal"); Serial.print(F(",\"door\":")); Serial.print(doorCal);
  Serial.println(F(",\"note\":\"calibrate with the door OPEN\"}"));
}
bool updateDoor() {
  doorRaw = avgRead(PIN_DOOR, READ_SAMPLES);
  bool s = doorShut;
  if (!doorShut && (uint32_t)doorRaw * 100 < (uint32_t)doorCal * SHADE_PCT) s = true;
  else if (doorShut && (uint32_t)doorRaw * 100 > (uint32_t)doorCal * CLEAR_PCT) s = false;
  if (s == doorShut) return false;
  doorShut = s;
  evStart("door"); Serial.print(F(",\"v\":")); Serial.print(s ? 1 : 0); Serial.print(F(",\"raw\":")); Serial.print(doorRaw); Serial.println('}');
  return true;
}

// ---------------- UI
void backlight(uint8_t r, uint8_t g, uint8_t b, const char *name) {
  if (bl[0] == r && bl[1] == g && bl[2] == b) return;
  bl[0] = r; bl[1] = g; bl[2] = b; blName = name; lcd.setRGB(r, g, b);
}
void show(const char *a, const char *b) {
  if (!strcmp(a, line1) && !strcmp(b, line2)) return;
  strncpy(line1, a, 16); line1[16] = 0; strncpy(line2, b, 16); line2[16] = 0;
  lcd.clear(); lcd.setCursor(0, 0); lcd.print(line1); lcd.setCursor(0, 1); lcd.print(line2);
}
void fmtTime(char *o, uint16_t s) { sprintf(o, "%u:%02u", s / 60, s % 60); }
void refreshUi() {
  char a[17], b[17], t[8]; fmtTime(t, cookTime);
  if (msg && millis() - msgSince < MSG_MS) { show(msg, ""); if (msgRed) backlight(255, 0, 0, "red"); else backlight(255, 255, 255, "white"); return; }
  msg = nullptr;
  sprintf(b, "POWER %s", PWR[power]);
  switch (st) {
    case S_READY: show("READY", ""); backlight(255, 255, 255, "white"); break;
    case S_SET: sprintf(a, "COOK %s", t); show(a, b); backlight(255, 255, 255, "white"); break;
    case S_COOK: show(t, b); backlight(255, 140, 0, "amber"); break;
    case S_PAUSED: sprintf(a, "PAUSED  %s", t); show(a, b); backlight(255, 140, 0, "amber"); break;
    case S_DOOR: show("DOOR OPEN", t); backlight(255, 0, 0, "red"); break;
    case S_DONE: show("DONE", ""); backlight(0, 255, 0, "green"); break;
  }
}
void message(const char *m, bool red) { msg = m; msgRed = red; msgSince = millis(); refreshUi(); }

// ---------------- state machine
void go(State s) { st = s; stateSince = millis(); refreshUi(); }
void setTime(uint16_t s) { cookTime = s > TIME_MAX ? TIME_MAX : s; evInt("time", cookTime); }
void startCook(const char *how) { lastTick = millis(); evCook(how); go(S_COOK); }

void onPress(uint8_t i) {
  keyBeep();
  bool cooking = st == S_COOK;
  switch (i) {
    case B_TIME:
      if (cooking) return;
      if (st == S_READY || st == S_DONE) cookTime = 0;
      setTime(cookTime < 60 ? cookTime + 10 : cookTime + 60);   // +10 s up to 1:00, then +1 min
      if (st == S_PAUSED || st == S_DOOR) refreshUi(); else go(S_SET);
      break;
    case B_POWER:
      if (cooking) return;
      power = (power + 1) % 3; evStr("power_level", PWR[power]);
      if (st == S_READY || st == S_DONE) { if (cookTime) go(S_SET); else refreshUi(); } else refreshUi();
      break;
    case B_ADD30:
      if (cooking || st == S_SET || st == S_PAUSED || st == S_DOOR) { setTime(cookTime + 30); refreshUi(); return; }
      if (!doorShut) { evCook("refused:DOOR"); refuseBeeps(); message("CLOSE DOOR", true); return; }
      power = 0; evStr("power_level", PWR[power]); setTime(30); startCook("start");
      break;
    case B_START:
      if (cooking) return;
      if (!doorShut) { evCook("refused:DOOR"); refuseBeeps(); message("CLOSE DOOR", true); return; }
      if (cookTime == 0 || st == S_READY || st == S_DONE) { evCook("refused:TIME"); refuseBeeps(); message("SET TIME", false); return; }
      startCook(st == S_SET ? "start" : "resume");
      break;
    case B_STOP:
      if (cooking) { evCook("pause"); go(S_PAUSED); }
      else if (st == S_PAUSED || st == S_SET || st == S_DOOR) { cookTime = 0; evInt("time", 0); evCook("clear"); go(S_READY); }
      else refreshUi();
      break;
  }
}

void readButtons() {
  for (uint8_t i = 0; i < 5; i++) {
    Btn &b = btns[i];
    bool r = digitalRead(b.pin) == LOW;
    if (r != b.raw) { b.raw = r; b.changed = millis(); }
    if (r != b.stable && millis() - b.changed >= DEBOUNCE_MS) {
      b.stable = r; evInt(b.ev, r ? 1 : 0);
      if (r) onPress(i);
    }
  }
}

void resetAll() { cookTime = 0; power = 0; msg = nullptr; go(S_READY); }

void heartbeat() {
  evStart("hb");
  Serial.print(F(",\"state\":\"")); Serial.print(STATE_NAME[st]); Serial.print('"');
  for (uint8_t i = 0; i < 5; i++) { Serial.print(F(",\"")); Serial.print(btns[i].ev); Serial.print(F("\":")); Serial.print(btns[i].stable); }
  Serial.print(F(",\"door\":")); Serial.print(doorShut); Serial.print(F(",\"door_raw\":")); Serial.print(doorRaw); Serial.print(F(",\"door_cal\":")); Serial.print(doorCal);
  Serial.print(F(",\"time\":")); Serial.print(cookTime); Serial.print(F(",\"power_level\":\"")); Serial.print(PWR[power]);
  Serial.print(F("\",\"buzzer\":")); Serial.print(sounding ? 1 : 0);
  Serial.print(F(",\"lcd\":[\"")); Serial.print(line1); Serial.print(F("\",\"")); Serial.print(line2);
  Serial.print(F("\"],\"backlight\":\"")); Serial.print(blName); Serial.println(F("\"}"));
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
    else if (!strcmp(buf, "cal")) calibrate();
    else if (!strcmp(buf, "reset")) { resetAll(); evCook("reset"); }
    else if (buf[0]) Serial.println(F("{\"ev\":\"error\",\"msg\":\"unknown command\"}"));
  }
}

#ifdef RAV_WIFI
// Every channel the sim's device has (device.yaml's firmware.channels, minus the buzzer's stand-ins), plus state and
// the display's two lines as LCD, joined as the sim shows them.
void snapshot(char *o, size_t n) {
  char shown[36];
  if (line2[0]) snprintf(shown, sizeof(shown), "%s  %s", line1, line2); else snprintf(shown, sizeof(shown), "%s", line1);
  snprintf(o, n, "{\"btn_start\":%u,\"btn_stop\":%u,\"btn_time\":%u,\"btn_power\":%u,\"btn_30s\":%u,\"door\":%u,"
           "\"time\":%u,\"power_level\":\"%s\",\"cook\":\"%s\",\"state\":\"%s\",\"backlight\":\"%s\",\"LCD\":\"%s\"}",
           btns[B_START].stable, btns[B_STOP].stable, btns[B_TIME].stable, btns[B_POWER].stable, btns[B_ADD30].stable,
           doorShut, cookTime, PWR[power], lastCook, STATE_NAME[st], blName, shown);
}
#endif

void setup() {
  Serial.begin(115200);
  for (uint8_t i = 0; i < 5; i++) pinMode(btns[i].pin, INPUT_PULLUP);
  pinMode(PIN_BUZZER, OUTPUT); digitalWrite(PIN_BUZZER, LOW);
  lcd.begin(16, 2);
  Serial.print(F("{\"t\":")); Serial.print(millis()); Serial.print(F(",\"ev\":\"hello\",\"dev\":\"MW-1\",\"fw\":\"1.0\",\"ram\":")); Serial.print(freeRam()); Serial.println('}');
  calibrate();
  for (uint8_t i = 0; i < 5; i++) btns[i].raw = btns[i].stable = digitalRead(btns[i].pin) == LOW;
  resetAll();
  keyBeep();
#ifdef RAV_WIFI
  rav::begin();                  // blocks a few seconds while it joins; the display already shows READY
#endif
}

void loop() {
  handleSerial();
  readButtons();
  buzzer();
  uint32_t now = millis();
  if (now - lastSensor >= SENSOR_PERIOD_MS) {
    lastSensor = now;
    if (updateDoor() && !doorShut && st == S_COOK) { evCook("pause:DOOR"); go(S_DOOR); }
  }
  if (st == S_COOK && now - lastTick >= 1000) {
    lastTick += 1000;
    if (cookTime) cookTime--;
    evInt("time", cookTime);
    if (cookTime == 0) { evCook("done"); doneBeeps(); go(S_DONE); } else refreshUi();
  }
  if (st == S_DONE && now - stateSince >= DONE_MS) go(S_READY);
  if (msg && now - msgSince >= MSG_MS) refreshUi();
  if (now - lastHb >= 1000) { lastHb = now; heartbeat(); }
#ifdef RAV_WIFI
  static uint32_t lastSnap = 0;
  if (now - lastSnap >= 10) { lastSnap = now; char b[RAV_SNAPSHOT_MAX]; snapshot(b, sizeof(b)); rav::update(b); }
#endif
}
