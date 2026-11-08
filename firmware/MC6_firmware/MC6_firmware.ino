#include <Arduino.h>
#include <EEPROM.h>
#include "SlowI2C.h"
#include <U8x8lib.h>
#include <Adafruit_NeoPixel.h>
#include <avr/pgmspace.h>
#include <stdio.h>
#include <string.h>
#if defined(ARDUINO_UNOWIFIR4) && __has_include("arduino_secrets.h")
#include "arduino_secrets.h"
#include "../firmware/rav_wifi.h"
#endif

#if defined(ARDUINO_ARCH_RENESAS_UNO)
extern "C" void *_sbrk(int increment);
#endif

const uint8_t PIN_START = 2;
const uint8_t PIN_STOP = 10;
const uint8_t PIN_TIME = 12;
const uint8_t PIN_POWER = 5;
// Requirements for this simulated appliance; sensor reporting always remains active.
bool requireLidClosed = true;
bool requireTubePresent = false;
// R4 Serial is native USB; D0/D1 are available because Serial1 is unused.
// Exclude the ring, analog sensors, board LED and I2C pins.
const uint8_t BUTTON_SCAN_PINS[] = {0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12};
const uint8_t BUTTON_SCAN_COUNT = sizeof(BUTTON_SCAN_PINS) / sizeof(BUTTON_SCAN_PINS[0]);
const uint16_t DISPLAY_STARTUP_MS = 500;
const uint16_t MIN_LIGHT_CONTRAST = 40, MIN_LIGHT_SEPARATION = 8;
const uint16_t CAL_MAGIC = 0x4D36;
const uint8_t CAL_VERSION = 2, CAL_HAS_TUBE = 1;
const uint8_t PIN_RING = 6, PIN_SPEED = A0, PIN_LID = A2, PIN_TUBE = A1;
const bool OLED_FLIPPED = true;
const uint8_t PIXELS = 24, BRIGHTNESS = 50;
const uint8_t OLED_PRIMARY = 0x3C, OLED_FALLBACK = 0x3D;
const uint16_t DEBOUNCE_MS = 20, SENSOR_MS = 20, HEARTBEAT_MS = 1000;
const uint16_t LIGHT_SETTLE_MS = 100, CAL_SAMPLE_MS = 5;
const uint8_t CAL_SAMPLES = 16, READ_SAMPLES = 8;
const uint8_t SHADED_PERCENT = 55, CLEAR_PERCENT = 70, MIN_CAL_LEVEL = 20;
const uint16_t DEFAULT_RPM = 1000, MAX_RPM = 6000, RPM_STEP = 100;
const uint16_t DEFAULT_TIME = 30, TIME_STEP = 10, MAX_TIME = 600;
const uint16_t POT_HYSTERESIS = 4;
const bool INVERT_POT = false;
const uint16_t ROTATION_SLOW_MS = 180, ROTATION_FAST_MS = 40;
const uint32_t DONE_MS = 60000UL;
const uint8_t COMMAND_SIZE = 16;

typedef const __FlashStringHelper *Flash;

struct Button {
  uint8_t pin;
  bool raw = false, held = false, pressed = false;
  uint32_t changed = 0;
  explicit Button(uint8_t p = 0) : pin(p) {}
  void begin() { pinMode(pin, INPUT_PULLUP); }
  bool poll(uint32_t now) {
    pressed = false;
    bool value = digitalRead(pin) == LOW;
    if (value != raw) { raw = value; changed = now; }
    if (held == raw || uint32_t(now - changed) < DEBOUNCE_MS) return false;
    held = raw;
    pressed = held;
    return true;
  }
};

struct Light {
  uint8_t pin;
  uint16_t raw = 0, level = 0, shadedLevel = 0, low = 0, high = 0;
  bool shaded = false;
  explicit Light(uint8_t p) : pin(p) {}
};

enum CalStage : uint8_t { CAL_IDLE, CAL_BOOT, WAIT_OPEN, READ_OPEN, WAIT_CLOSED, READ_CLOSED, WAIT_TUBE, READ_TUBE };
enum CalibrationMode : uint8_t { CAL_DEFAULT, CAL_LID_ONLY, CAL_TUBE_ONLY };
CalibrationMode calibrationMode = CAL_DEFAULT;
struct CalRecord {
  uint16_t magic;
  uint8_t version, flags;
  uint16_t lidOpen, lidClosed, tubeEmpty, tubeLoaded, checksum;
};

enum State : uint8_t { OFF, READY, RUNNING, DONE, REFUSED };
enum Reason : uint8_t { NO_REASON, LID, TUBE };
enum Colour : uint8_t { BLACK, WHITE, BLUE, GREEN, RED };

Button startButton(PIN_START), stopButton(PIN_STOP), timeButton(PIN_TIME), powerSwitch(PIN_POWER);
Light lid(PIN_LID), tube(PIN_TUBE);
U8X8_SSD1306_128X64_NONAME_SW_I2C oled(A5, A4, U8X8_PIN_NONE);
Button scanButtons[BUTTON_SCAN_COUNT];
bool buttonTest = false, calSaved = false, tubeCalSaved = false, calFailed = false;
CalStage calStage = CAL_IDLE;
uint16_t pendingLidOpen = 0, pendingLidClosed = 0, pendingTubeEmpty = 0;
uint16_t lidMin = 1023, lidMax = 0, tubeMin = 1023, tubeMax = 0;
uint16_t openMinimum = 0, emptyMinimum = 0;
bool displayStarted = false, oledTransfer = false;
uint8_t oledAddress = 0, oledClearTile = 128, oledRows = 0, oledColumn = 0;
uint32_t displayStartupAt = 0;
Adafruit_NeoPixel ring(PIXELS, PIN_RING, NEO_GRB + NEO_KHZ800);
State state = OFF;
Reason reason = NO_REASON;
Colour colour = BLACK;
uint16_t rpm = DEFAULT_RPM, setTime = DEFAULT_TIME, remaining = DEFAULT_TIME;
uint16_t potRaw = 0, potAnchor = 0;
bool potActive = false, oledPresent = false, tubeValid = false;
bool calibrating = false, uiDirty = true;
uint8_t calCount = 0, segment = 0;
uint32_t lidSum = 0, tubeSum = 0;
uint32_t calStarted = 0, calLast = 0, sensorLast = 0, tickLast = 0;
uint32_t doneSince = 0, heartbeatLast = 0, colourSince = 0, rotationLast = 0;
char display1[17] = {}, display2[17] = {};
char command[COMMAND_SIZE];
uint8_t commandLength = 0;
bool commandOverflow = false;

int freeRam();
void prefix(Flash name);
void event(Flash name, uint16_t value);
void event(Flash name, Flash value);
Flash stateName();
Flash colourName();
void changeState(State next, Reason why = NO_REASON);
void setSeconds(uint16_t seconds);
void restoreTime();
void setSpeed(uint16_t speed);
uint16_t average(uint8_t pin);
uint16_t readPot();
void defaults();
uint8_t oledByte(u8x8_t *display, uint8_t message, uint8_t count, void *data);
uint8_t oledGpio(u8x8_t *display, uint8_t message, uint8_t count, void *data);
void initializeDisplay();
void oledPoll();
void oledFault();
void buttonEvent(Flash name, const Button &button);
void buttonTestReply();
void setButtonTest(bool enabled);
uint32_t buttonInputMask();
void guidedCalibrationStart(uint32_t now, CalibrationMode mode = CAL_DEFAULT);
void calibrationCancel();
void calibrationReply(Flash stage = nullptr);
void calibrationFailure(Flash why, uint16_t lidMean, uint16_t tubeMean);
void startCapture(CalStage stage, uint32_t now);
uint16_t calibrationChecksum(const CalRecord &record);
bool validCalibration(const CalRecord &record);
bool loadCalibration();
bool saveCalibration(const CalRecord &record);
bool completeCalibration(bool withTube, uint16_t tubeMean);
void applyCalibration(const CalRecord &record);
void configureLight(Light &sensor, uint16_t clear, uint16_t shaded);
void copyText(char *dest, Flash source);
void showRing();
void render(uint32_t now);
void sampleLight(Light &sensor, Flash name);
void calibrationStart(uint32_t now);
void calibrationPoll(uint32_t now);
void pollButtons(uint32_t now);
void pollSensors(uint32_t now);
void stateMachine(uint32_t now);
void heartbeat();
void executeCommand(uint32_t now);
void serialPoll(uint32_t now);
void actionEvent(Flash action);
void setup();
void loop();

int freeRam() {
#if defined(ARDUINO_ARCH_RENESAS_UNO)
  char stack;
  // Renesas uses newlib; report the current stack-to-heap gap.
  return &stack - static_cast<char *>(_sbrk(0));
#else
  extern int __heap_start;
  extern void *__brkval;
  int stack;
  return reinterpret_cast<char *>(&stack) -
         (__brkval ? reinterpret_cast<char *>(__brkval) : reinterpret_cast<char *>(&__heap_start));
#endif
}

void prefix(Flash name) {
  Serial.print(F("{\"t\":")); Serial.print(millis());
  Serial.print(F(",\"ev\":\"")); Serial.print(name); Serial.print(F("\""));
}
void event(Flash name, uint16_t value) {
  prefix(name); Serial.print(F(",\"v\":")); Serial.print(value); Serial.println(F("}"));
}
void event(Flash name, Flash value) {
  prefix(name); Serial.print(F(",\"v\":\"")); Serial.print(value); Serial.println(F("\"}"));
}
Flash stateName() {
  switch (state) {
    case OFF: return F("OFF"); case READY: return F("READY");
    case RUNNING: return F("RUNNING"); case DONE: return F("DONE");
    default: return F("REFUSED");
  }
}
Flash colourName() {
  switch (colour) {
    case WHITE: return F("white"); case BLUE: return F("blue");
    case GREEN: return F("green"); case RED: return F("red");
    default: return F("off");
  }
}
void changeState(State next, Reason why) {
  if (state != next || reason != why) {
    state = next; reason = why; uiDirty = true;
    event(F("state"), stateName());
  }
}
void setSeconds(uint16_t seconds) {
  if (setTime != seconds || remaining != seconds) { setTime = seconds; event(F("time"), seconds); }
  remaining = setTime; uiDirty = true;
}
void restoreTime() {
  if (remaining != setTime) { remaining = setTime; event(F("time"), remaining); }
  uiDirty = true;
}
void setSpeed(uint16_t speed) {
  if (rpm != speed) { rpm = speed; event(F("speed"), rpm); uiDirty = true; }
}
uint16_t average(uint8_t pin) {
  uint16_t sum = 0;
  for (uint8_t i = 0; i < READ_SAMPLES; ++i) sum += analogRead(pin);
  return sum / READ_SAMPLES;
}
uint16_t readPot() {
  return average(PIN_SPEED);
}
void defaults() {
  setSpeed(DEFAULT_RPM); setSeconds(DEFAULT_TIME);
  potRaw = potAnchor = readPot(); potActive = false;
}
uint8_t oledGpio(u8x8_t *display, uint8_t message, uint8_t count, void *data) {
  if (message == U8X8_MSG_GPIO_AND_DELAY_INIT) {
    // U8x8's default setup makes its I2C pins OUTPUT. Preserve open-drain release.
    Mc6I2c::release(A4); Mc6I2c::release(A5); return 1;
  }
  return u8x8_gpio_and_delay_arduino(display, message, count, data);
}
uint8_t oledByte(u8x8_t *display, uint8_t message, uint8_t count, void *data) {
  switch (message) {
    case U8X8_MSG_BYTE_INIT: return 1;
    case U8X8_MSG_BYTE_START_TRANSFER:
      if (Mc6I2c::error != Mc6I2c::OK) return 0;
      oledTransfer = Mc6I2c::start();
      return oledTransfer && Mc6I2c::write(u8x8_GetI2CAddress(display), Mc6I2c::ADDRESS_NACK);
    case U8X8_MSG_BYTE_SEND:
      if (!oledTransfer || Mc6I2c::error != Mc6I2c::OK) return 0;
      for (uint8_t i = 0; i < count; ++i)
        if (!Mc6I2c::write(static_cast<uint8_t *>(data)[i])) return 0;
      return 1;
    case U8X8_MSG_BYTE_END_TRANSFER: {
      bool ok = !oledTransfer || Mc6I2c::stop(); oledTransfer = false; return ok;
    }
    default: return 1;
  }
}
void oledFault() {
  oledPresent = false; oledRows = 0; oledClearTile = 128;
  prefix(F("warning")); Serial.print(F(",\"msg\":\"OLED I2C failure\",\"addr\":")); Serial.print(oledAddress);
  Serial.print(F(",\"io_error\":")); Serial.print(uint8_t(Mc6I2c::error)); Serial.println(F("}"));
}
void initializeDisplay() {
  displayStarted = true; Mc6I2c::begin();
  oledAddress = Mc6I2c::probe(OLED_PRIMARY) ? OLED_PRIMARY : Mc6I2c::probe(OLED_FALLBACK) ? OLED_FALLBACK : 0;
  oledPresent = oledAddress != 0;
  if (!oledPresent) { oledFault(); return; }
  Mc6I2c::error = Mc6I2c::OK;
  oled.setI2CAddress(oledAddress << 1); oled.getU8x8()->byte_cb = oledByte;
  oled.getU8x8()->gpio_and_delay_cb = oledGpio;
  oled.initDisplay(); oled.setFlipMode(OLED_FLIPPED ? 1 : 0); oled.setPowerSave(0); oled.setFont(u8x8_font_chroma48medium8_r);
  if (Mc6I2c::error != Mc6I2c::OK) { oledFault(); return; }
  // Clear and redraw incrementally so a slow bus does not block input polling.
  oledClearTile = 0; oledRows = 3; oledColumn = 0;
}
void oledPoll() {
  if (!oledPresent || (oledClearTile == 128 && !oledRows)) return;
  if (oledClearTile < 128) {
    uint8_t blank[8] = {};
    oled.drawTile(oledClearTile % 16, oledClearTile / 16, 1, blank); ++oledClearTile;
  } else {
    uint8_t row = (oledRows & 1) ? 0 : 1;
    const char *line = row ? display2 : display1;
    char glyph[2] = {oledColumn < strlen(line) ? line[oledColumn] : ' ', '\0'};
    oled.drawString(oledColumn, row * 2, glyph);
    if (++oledColumn == 16) { oledRows &= ~(1 << row); oledColumn = 0; }
  }
  if (Mc6I2c::error != Mc6I2c::OK) oledFault();
  else if (oledClearTile == 128 && !oledRows) event(F("oled_sync"), uint16_t(1));
}
void copyText(char *dest, Flash source) {
  strncpy_P(dest, reinterpret_cast<PGM_P>(source), 16); dest[16] = '\0';
}
void showRing() {
  ring.clear();
  uint32_t rgb = 0;
  if (colour == WHITE) rgb = ring.Color(255, 255, 255);
  if (colour == BLUE) rgb = ring.Color(0, 0, 255);
  if (colour == GREEN) rgb = ring.Color(0, 255, 0);
  if (colour == RED) rgb = ring.Color(255, 0, 0);
  if (colour == BLUE) ring.setPixelColor(segment, rgb);
  else ring.fill(rgb);
  ring.show();
}
void render(uint32_t now) {
  Colour next = calibrating ? WHITE :
      state == OFF ? BLACK : state == READY ? WHITE :
      state == RUNNING ? BLUE : state == DONE ? GREEN : RED;
  if (colour != next) {
    colour = next; colourSince = now; tubeValid = false;
    segment = 0; rotationLast = now; showRing(); event(F("light"), colourName());
  }
  if (state == RUNNING && !calibrating) {
    uint16_t period = map(rpm, DEFAULT_RPM, MAX_RPM, ROTATION_SLOW_MS, ROTATION_FAST_MS);
    if (uint32_t(now - rotationLast) >= period) {
      rotationLast = now; segment = (segment + 1) % PIXELS;
      showRing(); event(F("segment"), segment);
    }
  }
  if (!uiDirty) return;
  char first[17] = {}, second[17] = {};
  if (buttonTest) { copyText(first, F("BUTTON TEST")); copyText(second, F("FOLLOW PC PROMPT")); }
  else if (calibrating) {
    const bool measureTube = calibrationMode == CAL_TUBE_ONLY || (calibrationMode == CAL_DEFAULT && requireTubePresent);
    copyText(first, calFailed ? F("CAL FAILED") : calStage == WAIT_CLOSED ? (measureTube ? F("CLOSE LID/EMPTY") : F("CLOSE LID")) :
        calStage == WAIT_TUBE ? F("TUBE IN/LID SHUT") : calStage == WAIT_OPEN || calStage == CAL_BOOT ? (measureTube ? F("OPEN LID/EMPTY") : F("OPEN LID")) : F("MEASURING"));
    if (calStage == WAIT_OPEN || calStage == WAIT_CLOSED || calStage == WAIT_TUBE) copyText(second, F("THEN PRESS START"));
  }
  else if (state == DONE) copyText(first, F("DONE"));
  else if (state == REFUSED) copyText(first, reason == LID ? F("LID") : F("TUBE"));
  else if (state != OFF) {
    snprintf_P(first, sizeof(first), reinterpret_cast<PGM_P>(F("%u RPM")), rpm);
    uint16_t seconds = state == RUNNING ? remaining : setTime;
    snprintf_P(second, sizeof(second), reinterpret_cast<PGM_P>(F("%u:%02u")), seconds / 60, seconds % 60);
  }
  if (strcmp(first, display1) || strcmp(second, display2)) {
    strcpy(display1, first); strcpy(display2, second);
    oledRows = 3; oledColumn = 0;
    prefix(F("display")); Serial.print(F(",\"v\":[\"")); Serial.print(display1);
    Serial.print(F("\",\"")); Serial.print(display2); Serial.println(F("\"]}"));
  }
  uiDirty = false;
}
void sampleLight(Light &sensor, Flash name) {
  sensor.raw = average(sensor.pin);
  bool next = sensor.shaded;
  // Strict inequalities retain the previous state inside the hysteresis band.
  if (calSaved && (sensor.pin == lid.pin || tubeCalSaved)) {
    if (sensor.raw < sensor.low) next = true;
    if (sensor.raw > sensor.high) next = false;
  } else {
    if (uint32_t(sensor.raw) * 100 < uint32_t(sensor.level) * SHADED_PERCENT) next = true;
    if (uint32_t(sensor.raw) * 100 > uint32_t(sensor.level) * CLEAR_PERCENT) next = false;
  }
  if (next != sensor.shaded) {
    sensor.shaded = next;
    prefix(name); Serial.print(F(",\"v\":")); Serial.print(next ? 1 : 0);
    Serial.print(F(",\"raw\":")); Serial.print(sensor.raw); Serial.println(F("}"));
  }
}
void calibrationStart(uint32_t now) {
  calibrationMode = CAL_DEFAULT;
  if (state == RUNNING) { actionEvent(F("stop")); changeState(READY); restoreTime(); }
  calibrating = true; calStage = CAL_BOOT; calCount = 0; lidSum = tubeSum = 0;
  calStarted = calLast = now; tubeValid = false; uiDirty = true;
  prefix(F("notice")); Serial.println(requireTubePresent ? F(",\"msg\":\"Calibration: open lid, remove tube; ring white\"}") : F(",\"msg\":\"Calibration: open lid; tube ignored; ring white\"}"));
  render(now);
}
uint16_t calibrationChecksum(const CalRecord &r) {
  return uint16_t(0xA55A ^ r.magic ^ r.version ^ r.flags ^ (uint16_t(PIN_LID) << 8) ^ PIN_TUBE ^
      r.lidOpen * 31U ^ r.lidClosed * 17U ^ r.tubeEmpty * 13U ^ r.tubeLoaded * 7U);
}
bool validCalibration(const CalRecord &r) {
  return r.magic == CAL_MAGIC && r.version == CAL_VERSION && !(r.flags & ~CAL_HAS_TUBE) && r.lidOpen <= 1023 &&
      r.lidOpen > r.lidClosed && r.lidOpen - r.lidClosed >= MIN_LIGHT_CONTRAST &&
      (!(r.flags & CAL_HAS_TUBE) || (r.tubeEmpty <= 1023 && r.tubeEmpty > r.tubeLoaded && r.tubeEmpty - r.tubeLoaded >= MIN_LIGHT_CONTRAST)) &&
      r.checksum == calibrationChecksum(r);
}
void configureLight(Light &sensor, uint16_t clear, uint16_t shaded) {
  sensor.level = clear; sensor.shadedLevel = shaded;
  sensor.low = shaded + uint32_t(clear - shaded) * 40 / 100;
  sensor.high = shaded + uint32_t(clear - shaded) * 60 / 100;
}
void applyCalibration(const CalRecord &r) {
  configureLight(lid, r.lidOpen, r.lidClosed); calSaved = true; tubeCalSaved = (r.flags & CAL_HAS_TUBE) != 0;
  if (tubeCalSaved) configureLight(tube, r.tubeEmpty, r.tubeLoaded);
  else { tube.level = tube.shadedLevel = tube.low = tube.high = 0; tube.shaded = false; tubeValid = false; }
}
bool loadCalibration() {
  CalRecord r; EEPROM.get(0, r);
  if (!validCalibration(r)) return false;
  applyCalibration(r); return true;
}
bool saveCalibration(const CalRecord &r) {
  if (!validCalibration(r)) return false;
  CalRecord previous; EEPROM.get(0, previous);
  if (!validCalibration(previous) || previous.flags != r.flags || previous.lidOpen != r.lidOpen || previous.lidClosed != r.lidClosed ||
      previous.tubeEmpty != r.tubeEmpty || previous.tubeLoaded != r.tubeLoaded) EEPROM.put(0, r);
  CalRecord check; EEPROM.get(0, check);
  return validCalibration(check) && check.flags == r.flags && check.lidOpen == r.lidOpen && check.lidClosed == r.lidClosed &&
      check.tubeEmpty == r.tubeEmpty && check.tubeLoaded == r.tubeLoaded;
}
bool completeCalibration(bool withTube, uint16_t tubeMean) {
  if (calibrationMode == CAL_LID_ONLY && tubeCalSaved) {
    withTube = true;
    pendingTubeEmpty = tube.level;
    tubeMean = tube.shadedLevel;
  }
  CalRecord r = {};
  r.magic = CAL_MAGIC; r.version = CAL_VERSION; r.flags = withTube ? CAL_HAS_TUBE : 0;
  r.lidOpen = pendingLidOpen; r.lidClosed = pendingLidClosed;
  if (withTube) { r.tubeEmpty = pendingTubeEmpty; r.tubeLoaded = tubeMean; }
  r.checksum = calibrationChecksum(r);
  if (!saveCalibration(r)) return false;
  applyCalibration(r); calibrating = false; calStage = CAL_IDLE; calFailed = false;
  sampleLight(lid, F("lid"));
  if (withTube && requireTubePresent && calibrationMode != CAL_LID_ONLY) { sampleLight(tube, F("tube")); tubeValid = true; }
  calibrationReply(F("saved")); uiDirty = true; return true;
}
void calibrationReply(Flash stage) {
  if (!stage) {
    stage = calStage == WAIT_OPEN ? F("open") : calStage == WAIT_CLOSED ? F("closed") : calStage == WAIT_TUBE ? F("tube") :
        calStage == READ_OPEN || calStage == READ_CLOSED || calStage == READ_TUBE ? F("measuring") :
        calStage == CAL_BOOT ? F("baseline") : F("idle");
  }
  prefix(F("lightcal")); Serial.print(F(",\"stage\":\"")); Serial.print(stage);
  Serial.print(F("\",\"saved\":")); Serial.print(calSaved);
  Serial.print(F(",\"tube_required\":")); Serial.print(requireTubePresent);
  Serial.print(F(",\"tube_saved\":")); Serial.print(tubeCalSaved);
  Serial.print(F(",\"lid\":{\"clear\":")); Serial.print(lid.level);
  Serial.print(F(",\"shaded\":")); Serial.print(lid.shadedLevel);
  Serial.print(F(",\"lo\":")); Serial.print(lid.low); Serial.print(F(",\"hi\":")); Serial.print(lid.high);
  Serial.print(F("},\"tube\":{\"clear\":")); Serial.print(tube.level);
  Serial.print(F(",\"shaded\":")); Serial.print(tube.shadedLevel);
  Serial.print(F(",\"lo\":")); Serial.print(tube.low); Serial.print(F(",\"hi\":")); Serial.print(tube.high);
  Serial.println(F("}}"));
}
void calibrationCancel() {
  calibrating = false; calStage = CAL_IDLE; calFailed = false; tubeValid = false; uiDirty = true;
  calibrationReply(F("cancelled"));
}
void calibrationFailure(Flash why, uint16_t lidMean, uint16_t tubeMean) {
  prefix(F("cal_error")); Serial.print(F(",\"reason\":\"")); Serial.print(why);
  Serial.print(F("\",\"lid_clear\":")); Serial.print(pendingLidOpen);
  Serial.print(F(",\"lid_measured\":")); Serial.print(lidMean);
  Serial.print(F(",\"tube_empty\":")); Serial.print(pendingTubeEmpty);
  Serial.print(F(",\"tube_measured\":")); Serial.print(tubeMean);
  Serial.print(F(",\"lid_min\":")); Serial.print(lidMin); Serial.print(F(",\"lid_max\":")); Serial.print(lidMax);
  Serial.print(F(",\"tube_min\":")); Serial.print(tubeMin); Serial.print(F(",\"tube_max\":")); Serial.print(tubeMax);
  Serial.println(F("}"));
}
void guidedCalibrationStart(uint32_t now, CalibrationMode mode) {
  if (buttonTest) setButtonTest(false);
  if (state == RUNNING) { actionEvent(F("stop")); changeState(READY); restoreTime(); }
  if (state != OFF) changeState(READY);
  calibrationMode = mode;
  if (mode == CAL_TUBE_ONLY) { pendingLidOpen = lid.level; pendingLidClosed = lid.shadedLevel; }
  calibrating = true; calStage = mode == CAL_TUBE_ONLY ? WAIT_CLOSED : WAIT_OPEN;
  calFailed = false; tubeValid = false; uiDirty = true;
  render(now); calibrationReply();
}
void startCapture(CalStage stage, uint32_t now) {
  calStage = stage; calCount = 0; lidSum = tubeSum = 0;
  lidMin = tubeMin = 1023; lidMax = tubeMax = 0;
  calStarted = calLast = now; uiDirty = true; calibrationReply();
}
void calibrationPoll(uint32_t now) {
  if (!calibrating) return;
  if (calStage != CAL_BOOT && stopButton.pressed) { calibrationCancel(); return; }
  if (startButton.pressed) {
    if (calStage == WAIT_OPEN) { calFailed = false; startCapture(READ_OPEN, now); }
    else if (calStage == WAIT_CLOSED) { calFailed = false; startCapture(READ_CLOSED, now); }
    else if (calStage == WAIT_TUBE) startCapture(READ_TUBE, now);
  }
  bool capturing = calStage == CAL_BOOT || calStage == READ_OPEN || calStage == READ_CLOSED || calStage == READ_TUBE;
  if (!capturing || uint32_t(now - calStarted) < LIGHT_SETTLE_MS || uint32_t(now - calLast) < CAL_SAMPLE_MS) return;
  calLast = now;
  const bool measureTube = calibrationMode == CAL_TUBE_ONLY || (calibrationMode == CAL_DEFAULT && requireTubePresent);
  lid.raw = average(lid.pin); tube.raw = measureTube ? average(tube.pin) : 0;
  lidSum += lid.raw; tubeSum += tube.raw;
  lidMin = min(lidMin, lid.raw); tubeMin = min(tubeMin, tube.raw);
  if (lid.raw > lidMax) lidMax = lid.raw;
  if (tube.raw > tubeMax) tubeMax = tube.raw;
  if (++calCount != CAL_SAMPLES) return;
  uint16_t lidMean = lidSum / CAL_SAMPLES, tubeMean = tubeSum / CAL_SAMPLES;
  if (calStage == CAL_BOOT) {
    lid.level = lidMean; tube.level = tubeMean;
    calibrating = false; calStage = CAL_IDLE; uiDirty = true;
    prefix(F("cal")); Serial.print(F(",\"lid\":")); Serial.print(lid.level);
    Serial.print(F(",\"tube\":")); Serial.print(tube.level); Serial.println(F(",\"saved\":0}"));
    if (lid.level < MIN_CAL_LEVEL || (requireTubePresent && tube.level < MIN_CAL_LEVEL)) event(F("warning"), F("low calibration light"));
    sampleLight(lid, F("lid"));
    if (requireTubePresent) { sampleLight(tube, F("tube")); tubeValid = true; }
    return;
  }
  if (calStage == READ_OPEN) {
    pendingLidOpen = lidMean; openMinimum = lidMin; calStage = WAIT_CLOSED;
  } else if (calStage == READ_CLOSED) {
    if (calibrationMode == CAL_TUBE_ONLY) {
      if (lidMean < lid.high) { pendingTubeEmpty = tubeMean; emptyMinimum = tubeMin; calStage = WAIT_TUBE; }
      else { calibrationFailure(F("lid_open"), lidMean, tubeMean); calStage = WAIT_CLOSED; calFailed = true; }
    } else if (pendingLidOpen > lidMean && pendingLidOpen - lidMean >= MIN_LIGHT_CONTRAST && openMinimum > lidMax + MIN_LIGHT_SEPARATION) {
      pendingLidClosed = lidMean;
      if (!measureTube) {
        if (completeCalibration(false, 0)) return;
        calibrationFailure(F("storage_failed"), lidMean, tubeMean); calStage = WAIT_OPEN; calFailed = true;
      } else { pendingTubeEmpty = tubeMean; emptyMinimum = tubeMin; calStage = WAIT_TUBE; }
    } else {
      calibrationFailure(F("insufficient_lid_contrast"), lidMean, tubeMean); calStage = WAIT_OPEN; calFailed = true;
    }
  } else {
    bool contrast = pendingTubeEmpty > tubeMean && pendingTubeEmpty - tubeMean >= MIN_LIGHT_CONTRAST &&
        emptyMinimum > tubeMax + MIN_LIGHT_SEPARATION &&
        lidMean < pendingLidClosed + uint32_t(pendingLidOpen - pendingLidClosed) * 60 / 100;
    if (contrast && completeCalibration(true, tubeMean)) return;
    calibrationFailure(contrast ? F("storage_failed") : F("insufficient_tube_contrast_or_lid_open"), lidMean, tubeMean);
    calStage = calibrationMode == CAL_TUBE_ONLY ? WAIT_CLOSED : WAIT_OPEN; calFailed = true;
  }
  uiDirty = true; calibrationReply();
}
void buttonEvent(Flash name, const Button &button) {
  prefix(name); Serial.print(F(",\"v\":")); Serial.print(button.held);
  Serial.print(F(",\"pin\":")); Serial.print(button.pin); Serial.println(F("}"));
}
uint32_t buttonInputMask() {
  uint32_t mask = 0;
  for (uint8_t i = 0; i < BUTTON_SCAN_COUNT; ++i) if (scanButtons[i].held) mask |= uint32_t(1) << scanButtons[i].pin;
  return mask;
}
void buttonTestReply() {
  prefix(F("buttons")); Serial.print(F(",\"v\":")); Serial.print(buttonTest);
  Serial.print(F(",\"pins\":{\"btn_start\":")); Serial.print(PIN_START);
  Serial.print(F(",\"btn_stop\":")); Serial.print(PIN_STOP);
  Serial.print(F(",\"btn_time\":")); Serial.print(PIN_TIME);
  Serial.print(F(",\"btn_power\":")); Serial.print(PIN_POWER);
  Serial.print(F("},\"scan_pins\":["));
  for (uint8_t i = 0; i < BUTTON_SCAN_COUNT; ++i) { if (i) Serial.print(','); Serial.print(BUTTON_SCAN_PINS[i]); }
  Serial.println(F("]}"));
}
void setButtonTest(bool enabled) {
  if (enabled && !buttonTest) {
    if (calibrating) calibrationCancel();
    if (state == RUNNING) { actionEvent(F("stop")); restoreTime(); changeState(READY); }
    for (uint8_t i = 0; i < BUTTON_SCAN_COUNT; ++i) {
      Button &button = scanButtons[i]; button.pin = BUTTON_SCAN_PINS[i]; button.begin();
      button.raw = button.held = digitalRead(button.pin) == LOW; button.pressed = false; button.changed = millis();
    }
  } else if (!enabled && buttonTest) {
    for (uint8_t i = 0; i < BUTTON_SCAN_COUNT; ++i) {
      uint8_t pin = scanButtons[i].pin;
      if (pin != PIN_START && pin != PIN_STOP && pin != PIN_TIME && pin != PIN_POWER) pinMode(pin, INPUT);
    }
    restoreTime(); changeState(powerSwitch.held ? READY : OFF);
  }
  buttonTest = enabled; uiDirty = true; buttonTestReply();
}
void pollButtons(uint32_t now) {
  if (startButton.poll(now)) buttonEvent(F("btn_start"), startButton);
  if (stopButton.poll(now)) buttonEvent(F("btn_stop"), stopButton);
  if (timeButton.poll(now)) buttonEvent(F("btn_time"), timeButton);
  if (buttonTest) {
    powerSwitch.poll(now);
    for (uint8_t i = 0; i < BUTTON_SCAN_COUNT; ++i)
      if (scanButtons[i].poll(now)) buttonEvent(F("input"), scanButtons[i]);
    return;
  }
  if (powerSwitch.poll(now)) {
    buttonEvent(F("power"), powerSwitch);
    if (state == RUNNING) actionEvent(F("stop"));
    if (powerSwitch.held) { defaults(); changeState(READY); }
    else { changeState(OFF); restoreTime(); }
  }
}
void pollSensors(uint32_t now) {
  if (calibrating || uint32_t(now - sensorLast) < SENSOR_MS) return;
  sensorLast = now;
  sampleLight(lid, F("lid"));
  // Animation, darkness, and colour settling cannot produce a valid tube check.
  tubeValid = requireTubePresent && (!calSaved || tubeCalSaved) && colour != BLACK && colour != BLUE && uint32_t(now - colourSince) >= LIGHT_SETTLE_MS;
  if (tubeValid) sampleLight(tube, F("tube"));
  potRaw = readPot();
  uint16_t position = INVERT_POT ? 1023 - potRaw : potRaw;
  if (state == OFF || state == RUNNING || buttonTest) return;
  if (!potActive) {
    if (abs(int(potRaw) - int(potAnchor)) <= POT_HYSTERESIS) return;
    potActive = true;
    setSpeed(DEFAULT_RPM + ((uint32_t(position) * 50 + 511) / 1023) * RPM_STEP);
    return;
  }
  uint8_t step = (rpm - DEFAULT_RPM) / RPM_STEP;
  int upper = (uint32_t(2 * step + 1) * 1023) / 100 + POT_HYSTERESIS;
  int lower = (int32_t(2 * step - 1) * 1023) / 100 - POT_HYSTERESIS;
  if ((step < 50 && int(position) > upper) || (step > 0 && int(position) < lower))
    setSpeed(DEFAULT_RPM + ((uint32_t(position) * 50 + 511) / 1023) * RPM_STEP);
}
void stateMachine(uint32_t now) {
  if (calibrating || buttonTest || state == OFF) return;
  if (state == RUNNING) {
    if (requireLidClosed && !lid.shaded) {
      actionEvent(F("abort:LID")); restoreTime(); changeState(REFUSED, LID); return;
    }
    if (stopButton.pressed) {
      actionEvent(F("stop")); restoreTime(); changeState(READY); return;
    }
    while (state == RUNNING && uint32_t(now - tickLast) >= 1000UL) {
      tickLast += 1000UL; --remaining; event(F("time"), remaining); uiDirty = true;
      if (!remaining) { actionEvent(F("done")); changeState(DONE); doneSince = now; }
    }
    return;
  }
  if (state == DONE) {
    if (!lid.shaded || uint32_t(now - doneSince) >= DONE_MS) {
      restoreTime(); changeState(READY);
    }
    return;
  }
  if (state == REFUSED) {
    if ((reason == LID && (!requireLidClosed || lid.shaded)) || (reason == TUBE && (!requireTubePresent || (tubeValid && tube.shaded))) ||
        startButton.pressed || stopButton.pressed || timeButton.pressed) changeState(READY);
    return;
  }
  // STOP wins over simultaneous TIME/START presses. A held button never repeats.
  if (stopButton.pressed) { setSeconds(DEFAULT_TIME); return; }
  if (timeButton.pressed) setSeconds(min(uint16_t(setTime + TIME_STEP), MAX_TIME));
  if (!startButton.pressed) return;
  if (requireLidClosed && !lid.shaded) { actionEvent(F("refused:LID")); changeState(REFUSED, LID); }
  else if (requireTubePresent && (!tubeValid || !tube.shaded)) { actionEvent(F("refused:TUBE")); changeState(REFUSED, TUBE); }
  else {
    remaining = setTime; tickLast = now; tubeValid = false;
    actionEvent(F("start")); changeState(RUNNING);
  }
}
void heartbeat() {
  prefix(F("hb"));
  Serial.print(F(",\"power\":")); Serial.print(powerSwitch.held);
  Serial.print(F(",\"btn_start\":")); Serial.print(startButton.held);
  Serial.print(F(",\"btn_stop\":")); Serial.print(stopButton.held);
  Serial.print(F(",\"btn_time\":")); Serial.print(timeButton.held);
  Serial.print(F(",\"pot_raw\":")); Serial.print(potRaw);
  Serial.print(F(",\"lid\":")); Serial.print(lid.shaded);
  Serial.print(F(",\"lid_raw\":")); Serial.print(lid.raw);
  Serial.print(F(",\"lid_cal\":")); Serial.print(lid.level);
  Serial.print(F(",\"tube\":")); Serial.print(tube.shaded);
  Serial.print(F(",\"tube_raw\":")); Serial.print(tube.raw);
  Serial.print(F(",\"tube_cal\":")); Serial.print(tube.level);
  Serial.print(F(",\"tube_valid\":")); Serial.print(tubeValid);
  Serial.print(F(",\"tube_required\":")); Serial.print(requireTubePresent);
  Serial.print(F(",\"rpm\":")); Serial.print(rpm);
  Serial.print(F(",\"time\":")); Serial.print(setTime);
  Serial.print(F(",\"remaining\":")); Serial.print(remaining);
  Serial.print(F(",\"state\":\"")); Serial.print(stateName());
  Serial.print(F("\",\"reason\":\"")); Serial.print(reason == LID ? F("LID") : reason == TUBE ? F("TUBE") : F(""));
  Serial.print(F("\",\"display\":[\"")); Serial.print(display1);
  Serial.print(F("\",\"")); Serial.print(display2);
  Serial.print(F("\"],\"light\":\"")); Serial.print(colourName());
  Serial.print(F("\",\"segment\":")); Serial.print(segment);
  Serial.print(F(",\"calibrating\":")); Serial.print(calibrating);
  Serial.print(F(",\"oled_present\":")); Serial.print(oledPresent);
  Serial.print(F(",\"oled_pending\":")); Serial.print(oledClearTile < 128 || oledRows != 0);
  Serial.print(F(",\"i2c\":\"software\",\"i2c_us\":20,\"cal_saved\":")); Serial.print(calSaved);
  Serial.print(F(",\"button_test\":")); Serial.print(buttonTest);
  if (buttonTest) { Serial.print(F(",\"input_mask\":")); Serial.print(buttonInputMask()); }
  Serial.println(F("}"));
}
void executeCommand(uint32_t now) {
  if (!commandOverflow && !strcmp_P(command, reinterpret_cast<PGM_P>(F("ping")))) {
    prefix(F("pong")); Serial.println(F("}"));
  } else if (!commandOverflow && !strcmp_P(command, reinterpret_cast<PGM_P>(F("status")))) heartbeat();
  else if (!commandOverflow && !strcmp_P(command, reinterpret_cast<PGM_P>(F("raw")))) {
    prefix(F("raw"));
    Serial.print(F(",\"a0\":")); Serial.print(average(A0));
    Serial.print(F(",\"a1\":")); Serial.print(average(A1));
    Serial.print(F(",\"a2\":")); Serial.print(average(A2));
    Serial.print(F(",\"a3\":")); Serial.print(average(A3)); Serial.println(F("}"));
  }
  else if (!commandOverflow && !strcmp_P(command, reinterpret_cast<PGM_P>(F("cal")))) {
    if (calibrating) { prefix(F("error")); Serial.println(F(",\"msg\":\"calibration busy\"}")); }
    else guidedCalibrationStart(now);
  } else if (!commandOverflow && !strcmp_P(command, reinterpret_cast<PGM_P>(F("callid")))) {
    if (calibrating) { prefix(F("error")); Serial.println(F(",\"msg\":\"calibration busy\"}")); }
    else guidedCalibrationStart(now, CAL_LID_ONLY);
  } else if (!commandOverflow && !strcmp_P(command, reinterpret_cast<PGM_P>(F("caltube")))) {
    if (calibrating) { prefix(F("error")); Serial.println(F(",\"msg\":\"calibration busy\"}")); }
    else if (!calSaved) { prefix(F("error")); Serial.println(F(",\"msg\":\"calibrate the lid first\"}")); }
    else guidedCalibrationStart(now, CAL_TUBE_ONLY);
  } else if (!commandOverflow && !strcmp_P(command, reinterpret_cast<PGM_P>(F("calstop")))) {
    calibrationCancel();
  } else if (!commandOverflow && !strcmp_P(command, reinterpret_cast<PGM_P>(F("calstatus")))) {
    calibrationReply();
  } else if (!commandOverflow && !strcmp_P(command, reinterpret_cast<PGM_P>(F("buttons")))) {
    setButtonTest(true);
  } else if (!commandOverflow && !strcmp_P(command, reinterpret_cast<PGM_P>(F("normal")))) {
    setButtonTest(false);
  } else if (!commandOverflow && !strcmp_P(command, reinterpret_cast<PGM_P>(F("oled")))) {
    initializeDisplay();
  } else if (!commandOverflow && !strcmp_P(command, reinterpret_cast<PGM_P>(F("reset")))) {
    if (state == RUNNING) actionEvent(F("stop"));
    defaults(); changeState(powerSwitch.held ? READY : OFF); uiDirty = true; render(now);
    prefix(F("reset")); Serial.println(F("}"));
  } else { prefix(F("error")); Serial.println(F(",\"msg\":\"unknown command\"}")); }
}
void serialPoll(uint32_t now) {
  uint8_t budget = COMMAND_SIZE;
  while (budget-- && Serial.available()) {
    char ch = Serial.read();
    if (ch == '\r') continue;
    if (ch == '\n') {
      command[commandLength] = '\0'; executeCommand(now);
      commandLength = 0; commandOverflow = false;
      break;
    }
    if (ch >= 'A' && ch <= 'Z') ch += 'a' - 'A';
    if (ch == '\0') commandOverflow = true;
    if (commandLength < COMMAND_SIZE - 1) command[commandLength++] = ch;
    else commandOverflow = true;
  }
}
#ifdef RAV_WIFI
static Flash lastAction = F("");
#endif

void actionEvent(Flash action) {
#ifdef RAV_WIFI
  lastAction = action;
#endif
  event(F("run"), action);
}

#ifdef RAV_WIFI
static void publishSnapshot() {
  char body[rav::SNAPSHOT_MAX];

  snprintf(body, sizeof(body),
           "{\"power\":%u,\"btn_start\":%u,\"btn_stop\":%u,\"btn_time\":%u,\"speed\":%u,"
           "\"lid\":%u,\"tube\":%u,\"tube_valid\":%u,\"time\":%u,\"run\":\"%s\","
           "\"state\":\"%s\",\"ring\":\"%s\",\"LCD\":\"%s  %s\"}",
           unsigned(powerSwitch.held), unsigned(startButton.held), unsigned(stopButton.held),
           unsigned(timeButton.held), unsigned(rpm), unsigned(lid.shaded), unsigned(tube.shaded),
           unsigned(tubeValid), unsigned(state == RUNNING ? remaining : setTime),
           reinterpret_cast<const char *>(lastAction), reinterpret_cast<const char *>(stateName()),
           reinterpret_cast<const char *>(colourName()), display1, display2);
  rav::update(body, startButton.held | (stopButton.held << 1) | (timeButton.held << 2));
}
#endif

void setup() {
  Serial.begin(115200);
#if defined(ARDUINO_ARCH_RENESAS_UNO)
  analogReadResolution(10);
#endif
  startButton.begin(); stopButton.begin(); timeButton.begin(); powerSwitch.begin();
  pinMode(PIN_LID, INPUT); pinMode(PIN_TUBE, INPUT);
  ring.begin(); ring.setBrightness(BRIGHTNESS); ring.clear(); ring.show();
  Mc6I2c::begin(); displayStartupAt = millis();
  potRaw = potAnchor = readPot();
  prefix(F("hello")); Serial.print(F(",\"dev\":\"MC-6\",\"fw\":\"1.2\",\"ram\":"));
  Serial.print(freeRam()); Serial.println(F("}"));
  if (!ring.getPixels()) event(F("warning"), F("ring allocation failed"));
  if (loadCalibration()) calibrationReply(F("loaded"));
  else calibrationStart(millis());
}
void loop() {
  uint32_t now = millis();
  if (!displayStarted && uint32_t(now - displayStartupAt) >= DISPLAY_STARTUP_MS) { initializeDisplay(); now = millis(); }
  pollButtons(now); calibrationPoll(now); pollSensors(now); stateMachine(now);
  render(now); serialPoll(millis()); oledPoll();
  now = millis();
  if (uint32_t(now - heartbeatLast) >= HEARTBEAT_MS) { heartbeatLast = now; heartbeat(); }
#ifdef RAV_WIFI
  publishSnapshot();
#endif
}
