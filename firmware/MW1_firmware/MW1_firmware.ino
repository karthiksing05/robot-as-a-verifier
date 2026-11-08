#include <Arduino.h>
#include <EEPROM.h>
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

const uint8_t PIN_TIME = 5;
const uint8_t PIN_30S = 6;
const uint8_t PIN_POWER = 7;
const uint8_t PIN_START = 4;
const uint8_t PIN_STOP = 3;
// D13 is the board LED; A0 is the door sensor, A1 is the buzzer, A4/A5 are the LCD.
const uint8_t BUTTON_SCAN_PINS[] = {2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, A2, A3};
const uint8_t BUTTON_SCAN_COUNT = sizeof(BUTTON_SCAN_PINS) / sizeof(BUTTON_SCAN_PINS[0]);
const uint8_t PIN_DOOR = A0, PIN_BUZZER = A1;
const bool requireDoorClosed = false;
const uint8_t PIN_SOFT_SDA = A4, PIN_SOFT_SCL = A5;
const uint16_t I2C_DELAY_US = 20, I2C_CLOCK_TIMEOUT_US = 1000;
const uint8_t TEXT_I2C_ADDRESS = 0x3E;
const uint8_t BACKLIGHT_V4_I2C_ADDRESS = 0x62, BACKLIGHT_V5_I2C_ADDRESS = 0x30;
const uint16_t DISPLAY_STARTUP_MS = 500;
const uint8_t SCAN_MAX_ADDRESSES = 16;
const uint16_t DEBOUNCE_MS = 20, SENSOR_MS = 20, HEARTBEAT_MS = 1000;
const uint8_t CAL_SAMPLES = 16, READ_SAMPLES = 8, CAL_SAMPLE_MS = 20;
const uint8_t SHADED_PERCENT = 55, CLEAR_PERCENT = 70, MIN_CAL_LEVEL = 20;
const uint16_t MIN_DOOR_CONTRAST = 40, MIN_DOOR_SEPARATION = 8;
const uint8_t DOOR_CLOSE_PERCENT = 40, DOOR_OPEN_PERCENT = 60;
const uint16_t DOOR_CAL_MAGIC = 0x4D57, DOOR_CAL_ADDRESS = 0;
const uint8_t DOOR_CAL_VERSION = 1;
const uint16_t BUTTON_BEEP_MS = 60, ALERT_BEEP_MS = 150, BEEP_GAP_MS = 120;
const uint16_t MAX_TIME = 1800, TIME_SHORT_STEP = 10, TIME_LONG_STEP = 60;
const uint16_t TIME_STEP_BOUNDARY = 60, QUICK_TIME = 30;
const uint16_t MESSAGE_MS = 2000, DONE_MS = 10000;
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
    held = raw; pressed = held; return true;
  }
};
enum State : uint8_t { READY, SET, COOKING, PAUSED, DONE };
enum Power : uint8_t { HI, MED, LO };
enum Message : uint8_t { NO_MESSAGE, CLOSE_DOOR, SET_TIME, CAL_SAVED };
enum Colour : uint8_t { COLOUR_WHITE, COLOUR_AMBER, COLOUR_RED, COLOUR_GREEN };
enum I2cError : uint8_t { IO_OK, SDA_BUSY, CLOCK_TIMEOUT, ADDRESS_NACK, CONTROL_NACK, DATA_NACK };
enum DoorCalStage : uint8_t { CAL_IDLE, CAL_BOOT, CAL_WAIT_OPEN, CAL_SAMPLE_OPEN, CAL_WAIT_CLOSED, CAL_SAMPLE_CLOSED };
struct DoorCalRecord {
  uint16_t magic;
  uint8_t version;
  uint16_t open, closed, checksum;
};

Button startButton(PIN_START), stopButton(PIN_STOP), timeButton(PIN_TIME);
Button powerButton(PIN_POWER), quickButton(PIN_30S);
Button scanButtons[BUTTON_SCAN_COUNT];
State state = READY;
Power powerLevel = HI;
Message message = NO_MESSAGE;
Colour colour = COLOUR_WHITE;
uint16_t seconds = 0, doorRaw = 0, doorLevel = 0;
uint16_t doorClosedLevel = 0, doorCloseCutoff = 0, doorOpenCutoff = 0;
bool doorSaved = false, doorCalFailed = false;
DoorCalStage doorCalStage = CAL_IDLE;
uint16_t pendingOpen = 0, openMinimum = 0, calMinimum = 1023, calMaximum = 0;
bool doorShut = false, doorPause = false, uiDirty = true;
bool lcdPresent = false, rgbPresent = false, uiInitialized = false;
bool displayStarted = false;
I2cError lastI2cError = IO_OK;
I2cError lcdIoError = IO_OK, rgbIoError = IO_OK;
uint8_t lastI2cAddress = 0;
uint8_t lcdPendingRows = 0, lcdRow = 0, lcdColumn = 0;
bool lcdCursorSet = false;
uint8_t rgbAddress = 0;
uint32_t displayStartupAt = 0;
uint8_t scanAddress = 0, scanCount = 0, scanFound[SCAN_MAX_ADDRESSES];
bool scanTruncated = false;
bool calibrating = false;
bool buzzerOn = false;
uint8_t beepsLeft = 0;
uint16_t beepLength = BUTTON_BEEP_MS;
uint32_t beepSince = 0;
bool buttonTest = false;
uint8_t lightCalCount = 0;
uint32_t lightSum = 0;
uint32_t lightCalLast = 0, sensorLast = 0;
uint32_t tickLast = 0, doneSince = 0, messageSince = 0, heartbeatLast = 0;
char display1[17] = {}, display2[17] = {};
char command[COMMAND_SIZE];
uint8_t commandLength = 0;
bool commandOverflow = false;

int freeRam();
void prefix(Flash name);
void event(Flash name, uint16_t value);
void event(Flash name, Flash value);
void buttonEvent(Flash name, const Button &button);
void buttonTestReply();
void beginButtonTest();
uint32_t buttonInputMask();
Flash stateName();
Flash powerName();
Flash colourName();
void changeState(State next);
void setSeconds(uint16_t value);
void setPower(Power value);
void copyText(char *dest, Flash source);
void lineLow(uint8_t pin);
void lineRelease(uint8_t pin);
bool clockHigh();
bool i2cStart();
bool i2cStop();
bool i2cWriteByte(uint8_t value);
bool i2cWriteChecked(uint8_t value, I2cError nackError);
bool i2cWrite2(uint8_t address, uint8_t first, uint8_t second);
bool lcdCmd(uint8_t commandByte);
bool lcdData(uint8_t value);
bool rgbReg(uint8_t reg, uint8_t value);
bool lcdSetRGB(uint8_t red, uint8_t green, uint8_t blue);
bool probe(uint8_t address);
Flash i2cErrorName(I2cError error);
void displayWarning(Flash messageText);
void initializeDisplay();
void lcdPoll();
void scanPoll();
void render();
uint16_t average(uint8_t pin);
void sampleDoor();
void pauseCooking(bool byDoor);
void calibrationStart(uint32_t now);
void guidedCalibrationStart(uint32_t now);
void calibrationCancel();
void calibrationControls(uint32_t now);
Flash calibrationStageName();
void calibrationReply(Flash stageOverride = nullptr);
void startLightCapture(DoorCalStage stage, uint32_t now);
uint16_t calibrationChecksum(const DoorCalRecord &record);
bool validCalibration(const DoorCalRecord &record);
bool loadDoorCalibration();
bool saveDoorCalibration(uint16_t open, uint16_t closed);
void setDoorCalibration(uint16_t open, uint16_t closed);
void buzzerSet(bool on);
void startBeeps(uint8_t count, uint16_t duration);
void stopBeeps();
void pollBuzzer(uint32_t now);
void finishCalibration();
void pollLight(uint32_t now);
void pollButtons(uint32_t now);
void requestStart(uint32_t now);
void clearCooking();
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
void buttonEvent(Flash name, const Button &button) {
  prefix(name); Serial.print(F(",\"v\":")); Serial.print(button.held);
  Serial.print(F(",\"pin\":")); Serial.print(button.pin); Serial.println(F("}"));
}
void buttonTestReply() {
  prefix(F("buttons")); Serial.print(F(",\"v\":")); Serial.print(buttonTest);
  Serial.print(F(",\"pins\":{\"btn_start\":")); Serial.print(PIN_START);
  Serial.print(F(",\"btn_stop\":")); Serial.print(PIN_STOP);
  Serial.print(F(",\"btn_time\":")); Serial.print(PIN_TIME);
  Serial.print(F(",\"btn_power\":")); Serial.print(PIN_POWER);
  Serial.print(F(",\"btn_30s\":")); Serial.print(PIN_30S);
  Serial.print(F("},\"scan_pins\":["));
  for (uint8_t i = 0; i < BUTTON_SCAN_COUNT; ++i) {
    if (i) Serial.print(F(","));
    Serial.print(BUTTON_SCAN_PINS[i]);
  }
  Serial.println(F("]}"));
}
void beginButtonTest() {
  if (buttonTest) return;
  stopBeeps();
  for (uint8_t i = 0; i < BUTTON_SCAN_COUNT; ++i) {
    Button &button = scanButtons[i];
    button.pin = BUTTON_SCAN_PINS[i]; button.begin();
    button.raw = button.held = digitalRead(button.pin) == LOW;
    button.pressed = false; button.changed = millis();
  }
  buttonTest = true;
}
uint32_t buttonInputMask() {
  uint32_t mask = 0;
  for (uint8_t i = 0; i < BUTTON_SCAN_COUNT; ++i)
    if (scanButtons[i].held) mask |= uint32_t(1) << scanButtons[i].pin;
  return mask;
}
Flash stateName() {
  switch (state) {
    case READY: return F("READY"); case SET: return F("SET");
    case COOKING: return F("COOKING"); case PAUSED: return F("PAUSED");
    default: return F("DONE");
  }
}
Flash powerName() { return powerLevel == HI ? F("HI") : powerLevel == MED ? F("MED") : F("LO"); }
Flash colourName() {
  switch (colour) {
    case COLOUR_AMBER: return F("amber"); case COLOUR_RED: return F("red");
    case COLOUR_GREEN: return F("green"); default: return F("white");
  }
}
void changeState(State next) {
  if (state != next) { state = next; event(F("state"), stateName()); uiDirty = true; }
}
void setSeconds(uint16_t value) {
  if (seconds != value) { seconds = value; event(F("time"), seconds); uiDirty = true; }
}
void setPower(Power value) {
  if (powerLevel != value) { powerLevel = value; event(F("power_level"), powerName()); uiDirty = true; }
}
void copyText(char *dest, Flash source) {
  strncpy_P(dest, reinterpret_cast<PGM_P>(source), 16); dest[16] = '\0';
}
void lineLow(uint8_t pin) {
  // Set the latch before enabling output; never actively drive an I2C line high.
  digitalWrite(pin, LOW); pinMode(pin, OUTPUT);
}
void lineRelease(uint8_t pin) { pinMode(pin, INPUT_PULLUP); }
bool clockHigh() {
  lineRelease(PIN_SOFT_SCL);
  uint32_t started = micros();
  while (digitalRead(PIN_SOFT_SCL) == LOW) {
    if (uint32_t(micros() - started) >= I2C_CLOCK_TIMEOUT_US) {
      lastI2cError = CLOCK_TIMEOUT; return false;
    }
  }
  delayMicroseconds(I2C_DELAY_US);
  return true;
}
bool i2cStart() {
  lineRelease(PIN_SOFT_SDA);
  if (!clockHigh()) return false;
  if (digitalRead(PIN_SOFT_SDA) == LOW) { lastI2cError = SDA_BUSY; return false; }
  lineLow(PIN_SOFT_SDA); delayMicroseconds(I2C_DELAY_US);
  lineLow(PIN_SOFT_SCL); delayMicroseconds(I2C_DELAY_US);
  return true;
}
bool i2cStop() {
  lineLow(PIN_SOFT_SDA); delayMicroseconds(I2C_DELAY_US);
  bool ok = clockHigh();
  lineRelease(PIN_SOFT_SDA); delayMicroseconds(I2C_DELAY_US);
  return ok;
}
bool i2cWriteByte(uint8_t value) {
  for (uint8_t mask = 0x80; mask; mask >>= 1) {
    if (value & mask) lineRelease(PIN_SOFT_SDA); else lineLow(PIN_SOFT_SDA);
    delayMicroseconds(I2C_DELAY_US);
    if (!clockHigh()) return false;
    lineLow(PIN_SOFT_SCL); delayMicroseconds(I2C_DELAY_US);
  }
  lineRelease(PIN_SOFT_SDA); delayMicroseconds(I2C_DELAY_US);
  if (!clockHigh()) return false;
  bool ack = digitalRead(PIN_SOFT_SDA) == LOW;
  lineLow(PIN_SOFT_SCL); delayMicroseconds(I2C_DELAY_US);
  return ack;
}
bool i2cWriteChecked(uint8_t value, I2cError nackError) {
  bool ok = i2cWriteByte(value);
  if (!ok && lastI2cError == IO_OK) lastI2cError = nackError;
  return ok;
}
bool i2cWrite2(uint8_t address, uint8_t first, uint8_t second) {
  lastI2cError = IO_OK; lastI2cAddress = address;
  bool ok = i2cStart() && i2cWriteChecked(address << 1, ADDRESS_NACK) &&
            i2cWriteChecked(first, CONTROL_NACK) && i2cWriteChecked(second, DATA_NACK);
  bool stopped = i2cStop();
  return ok && stopped;
}
bool lcdCmd(uint8_t commandByte) { return i2cWrite2(TEXT_I2C_ADDRESS, 0x80, commandByte); }
bool lcdData(uint8_t value) { return i2cWrite2(TEXT_I2C_ADDRESS, 0x40, value); }
bool rgbReg(uint8_t reg, uint8_t value) { return i2cWrite2(rgbAddress, reg, value); }
bool lcdSetRGB(uint8_t red, uint8_t green, uint8_t blue) {
  if (rgbAddress == BACKLIGHT_V5_I2C_ADDRESS)
    return rgbReg(0x06, red) && rgbReg(0x07, green) && rgbReg(0x08, blue);
  return rgbReg(0x04, red) && rgbReg(0x03, green) && rgbReg(0x02, blue);
}
bool probe(uint8_t address) {
  lastI2cError = IO_OK; lastI2cAddress = address;
  bool ok = i2cStart() && i2cWriteChecked(address << 1, ADDRESS_NACK);
  bool stopped = i2cStop();
  return ok && stopped;
}
Flash i2cErrorName(I2cError error) {
  switch (error) {
    case SDA_BUSY: return F("sda_low"); case CLOCK_TIMEOUT: return F("scl_timeout");
    case ADDRESS_NACK: return F("address_nack"); case CONTROL_NACK: return F("control_nack");
    case DATA_NACK: return F("data_nack"); default: return F("none");
  }
}
void displayWarning(Flash messageText) {
  if (lastI2cAddress == TEXT_I2C_ADDRESS) lcdIoError = lastI2cError;
  else rgbIoError = lastI2cError;
  prefix(F("warning")); Serial.print(F(",\"v\":\"")); Serial.print(messageText);
  Serial.print(F("\",\"addr\":")); Serial.print(lastI2cAddress);
  Serial.print(F(",\"io_error\":\"")); Serial.print(i2cErrorName(lastI2cError)); Serial.println(F("\"}"));
}
void initializeDisplay() {
  displayStarted = true;
  lcdPendingRows = 0; lcdCursorSet = false; lcdColumn = 0;
  // The LCD remains powered across an R4 reset; establish a STOP before probing.
  lineLow(PIN_SOFT_SCL); i2cStop();
  lcdPresent = probe(TEXT_I2C_ADDRESS);
  if (lcdPresent) {
    bool ok = lcdCmd(0x28);
    delayMicroseconds(4500);
    ok = ok && lcdCmd(0x28);
    delayMicroseconds(150);
    ok = ok && lcdCmd(0x28) && lcdCmd(0x0C) && lcdCmd(0x01);
    delayMicroseconds(2000);
    lcdPresent = ok && lcdCmd(0x06);
  }
  if (!lcdPresent) displayWarning(F("LCD initialization failed"));
  else lcdIoError = IO_OK;
  // The two controller versions use different initialization and PWM registers.
  rgbAddress = probe(BACKLIGHT_V5_I2C_ADDRESS) ? BACKLIGHT_V5_I2C_ADDRESS :
               probe(BACKLIGHT_V4_I2C_ADDRESS) ? BACKLIGHT_V4_I2C_ADDRESS : 0;
  rgbPresent = rgbAddress != 0;
  if (rgbPresent) {
    if (rgbAddress == BACKLIGHT_V5_I2C_ADDRESS) {
      bool ok = rgbReg(0x00, 0x07);
      delayMicroseconds(200);
      rgbPresent = ok && rgbReg(0x04, 0x15);
    } else rgbPresent = rgbReg(0x00, 0x00) && rgbReg(0x08, 0xFF) && rgbReg(0x01, 0x20);
  }
  uiInitialized = false; uiDirty = true;
  if (!rgbPresent) displayWarning(F("RGB initialization failed"));
  else rgbIoError = IO_OK;
}
void scanPoll() {
  if (!scanAddress) return;
  // Probe one address per loop so buttons/countdown remain serviced.
  if (probe(scanAddress)) {
    if (scanCount < SCAN_MAX_ADDRESSES) scanFound[scanCount++] = scanAddress;
    else scanTruncated = true;
  }
  if (++scanAddress <= 126) return;
  scanAddress = 0;
  prefix(F("i2c")); Serial.print(F(",\"addresses\":["));
  for (uint8_t i = 0; i < scanCount; ++i) {
    if (i) Serial.print(F(","));
    Serial.print(scanFound[i]);
  }
  Serial.print(F("],\"truncated\":")); Serial.print(scanTruncated); Serial.println(F("}"));
}
void lcdPoll() {
  if (!lcdPresent || !lcdPendingRows) return;
  bool ok;
  if (!lcdCursorSet) {
    lcdRow = lcdPendingRows & 1 ? 0 : 1;
    lcdColumn = 0;
    ok = lcdCmd(0x80 | (lcdRow ? 0x40 : 0x00));
    lcdCursorSet = ok;
  } else {
    const char *text = lcdRow ? display2 : display1;
    ok = lcdData(lcdColumn < strlen(text) ? text[lcdColumn] : ' ');
    if (ok && ++lcdColumn == 16) {
      lcdPendingRows &= ~(1 << lcdRow); lcdCursorSet = false;
      if (!lcdPendingRows) event(F("lcd_sync"), uint16_t(1));
    }
  }
  if (!ok) {
    lcdPresent = false; lcdPendingRows = 0; lcdCursorSet = false;
    displayWarning(F("LCD write not acknowledged"));
  }
}
void render() {
  if (!uiDirty) return;
  char first[17] = {}, second[17] = {};
  Colour next = COLOUR_WHITE;
  if (calibrating) {
    if (doorCalStage == CAL_WAIT_OPEN) {
      copyText(first, doorCalFailed ? F("CAL FAILED") : F("OPEN DOOR"));
      copyText(second, F("THEN PRESS START"));
      if (doorCalFailed) next = COLOUR_RED;
    } else if (doorCalStage == CAL_WAIT_CLOSED) {
      copyText(first, F("CLOSE DOOR")); copyText(second, F("THEN PRESS START"));
    } else copyText(first, doorCalStage == CAL_SAMPLE_CLOSED ? F("MEASURING CLOSED") : F("MEASURING OPEN"));
  }
  else if (buttonTest) { copyText(first, F("BUTTON TEST")); copyText(second, F("FOLLOW PC PROMPT")); }
  else if (message != NO_MESSAGE) {
    copyText(first, message == CLOSE_DOOR ? F("CLOSE DOOR") : message == CAL_SAVED ? F("CAL SAVED") : F("SET TIME"));
    if (message == CLOSE_DOOR) next = COLOUR_RED;
    if (message == CAL_SAVED) next = COLOUR_GREEN;
  } else if (state == READY) copyText(first, F("READY"));
  else if (state == DONE) { copyText(first, F("DONE")); next = COLOUR_GREEN; }
  else if (state == PAUSED && doorPause) {
    copyText(first, F("DOOR OPEN")); next = COLOUR_RED;
    snprintf_P(second, sizeof(second), reinterpret_cast<PGM_P>(F("%u:%02u")), seconds / 60, seconds % 60);
  } else {
    Flash format = state == SET ? F("COOK %u:%02u") : state == PAUSED ? F("PAUSED  %u:%02u") : F("%u:%02u");
    snprintf_P(first, sizeof(first), reinterpret_cast<PGM_P>(format), seconds / 60, seconds % 60);
    copyText(second, F("POWER ")); strcat_P(second, reinterpret_cast<PGM_P>(powerName()));
    if (state == COOKING || state == PAUSED) next = COLOUR_AMBER;
  }
  if (!uiInitialized || next != colour) {
    colour = next;
    if (rgbPresent) {
      if (colour == COLOUR_WHITE) rgbPresent = lcdSetRGB(255, 255, 255);
      else if (colour == COLOUR_AMBER) rgbPresent = lcdSetRGB(255, 140, 0);
      else if (colour == COLOUR_GREEN) rgbPresent = lcdSetRGB(0, 255, 0);
      else rgbPresent = lcdSetRGB(255, 0, 0);
      if (!rgbPresent) displayWarning(F("RGB write not acknowledged"));
    }
    event(F("light"), colourName());
  }
  if (!uiInitialized || strcmp(first, display1) || strcmp(second, display2)) {
    if (lcdPresent) {
      if (!uiInitialized || strcmp(first, display1)) lcdPendingRows |= 1;
      if (!uiInitialized || strcmp(second, display2)) lcdPendingRows |= 2;
      lcdCursorSet = false; lcdColumn = 0;
    }
    strcpy(display1, first); strcpy(display2, second);
    prefix(F("display")); Serial.print(F(",\"v\":[\"")); Serial.print(display1);
    Serial.print(F("\",\"")); Serial.print(display2); Serial.println(F("\"]}"));
  }
  uiInitialized = true; uiDirty = false;
}
uint16_t average(uint8_t pin) {
  uint16_t sum = 0;
  for (uint8_t i = 0; i < READ_SAMPLES; ++i) sum += analogRead(pin);
  return sum / READ_SAMPLES;
}
void sampleDoor() {
  doorRaw = average(PIN_DOOR);
  bool next = doorShut;
  if (doorSaved) {
    if (doorRaw < doorCloseCutoff) next = true;
    if (doorRaw > doorOpenCutoff) next = false;
  } else {
    if (uint32_t(doorRaw) * 100 < uint32_t(doorLevel) * SHADED_PERCENT) next = true;
    if (uint32_t(doorRaw) * 100 > uint32_t(doorLevel) * CLEAR_PERCENT) next = false;
  }
  if (next != doorShut) {
    doorShut = next;
    prefix(F("door")); Serial.print(F(",\"v\":")); Serial.print(doorShut);
    Serial.print(F(",\"raw\":")); Serial.print(doorRaw); Serial.println(F("}"));
    if (doorShut && doorPause) { doorPause = false; uiDirty = true; }
  }
}
void pauseCooking(bool byDoor) {
  doorPause = byDoor; message = NO_MESSAGE;
  actionEvent(byDoor ? F("pause:DOOR") : F("pause")); changeState(PAUSED);
}
void calibrationStart(uint32_t now) {
  calibrating = true; doorCalStage = CAL_BOOT;
  lightCalCount = 0; lightSum = 0; lightCalLast = now;
  uiDirty = true;
  prefix(F("notice")); Serial.println(F(",\"msg\":\"Open door for baseline; use doorcal to measure both positions\"}"));
}
uint16_t calibrationChecksum(const DoorCalRecord &record) {
  return uint16_t(0xA55A ^ record.magic ^ record.version ^ (record.open * 31U) ^ (record.closed * 17U));
}
bool validCalibration(const DoorCalRecord &record) {
  return record.magic == DOOR_CAL_MAGIC && record.version == DOOR_CAL_VERSION &&
         record.open <= 1023 && record.closed <= 1023 && record.open > record.closed &&
         record.open - record.closed >= MIN_DOOR_CONTRAST && record.checksum == calibrationChecksum(record);
}
void setDoorCalibration(uint16_t open, uint16_t closed) {
  doorLevel = open; doorClosedLevel = closed; doorSaved = true;
  uint16_t span = open - closed;
  doorCloseCutoff = closed + uint32_t(span) * DOOR_CLOSE_PERCENT / 100;
  doorOpenCutoff = closed + uint32_t(span) * DOOR_OPEN_PERCENT / 100;
}
bool loadDoorCalibration() {
  DoorCalRecord record;
  EEPROM.get(DOOR_CAL_ADDRESS, record);
  if (!validCalibration(record)) return false;
  setDoorCalibration(record.open, record.closed);
  return true;
}
bool saveDoorCalibration(uint16_t open, uint16_t closed) {
  DoorCalRecord record = {};
  record.magic = DOOR_CAL_MAGIC; record.version = DOOR_CAL_VERSION;
  record.open = open; record.closed = closed; record.checksum = calibrationChecksum(record);
  DoorCalRecord previous;
  EEPROM.get(DOOR_CAL_ADDRESS, previous);
  if (!validCalibration(previous) || previous.open != open || previous.closed != closed)
    EEPROM.put(DOOR_CAL_ADDRESS, record);
  DoorCalRecord check;
  EEPROM.get(DOOR_CAL_ADDRESS, check);
  return validCalibration(check) && check.open == open && check.closed == closed;
}
Flash calibrationStageName() {
  switch (doorCalStage) {
    case CAL_BOOT: return F("baseline"); case CAL_WAIT_OPEN: return F("open");
    case CAL_SAMPLE_OPEN: return F("measure_open"); case CAL_WAIT_CLOSED: return F("closed");
    case CAL_SAMPLE_CLOSED: return F("measure_closed"); default: return F("idle");
  }
}
void calibrationReply(Flash stageOverride) {
  prefix(F("doorcal")); Serial.print(F(",\"stage\":\""));
  Serial.print(stageOverride ? stageOverride : calibrationStageName());
  Serial.print(F("\",\"open\":")); Serial.print(doorCalStage == CAL_WAIT_CLOSED || doorCalStage == CAL_SAMPLE_CLOSED ? pendingOpen : doorLevel);
  Serial.print(F(",\"closed\":")); Serial.print(doorClosedLevel);
  Serial.print(F(",\"close_below\":")); Serial.print(doorCloseCutoff);
  Serial.print(F(",\"open_above\":")); Serial.print(doorOpenCutoff);
  Serial.print(F(",\"saved\":")); Serial.print(doorSaved); Serial.println(F("}"));
}
void guidedCalibrationStart(uint32_t now) {
  (void)now;
  if (state == COOKING) pauseCooking(false);
  stopBeeps(); buttonTest = false; message = NO_MESSAGE;
  calibrating = true; doorCalStage = CAL_WAIT_OPEN; doorCalFailed = false;
  pendingOpen = 0; uiDirty = true; calibrationReply(); render();
}
void calibrationCancel() {
  calibrating = false; doorCalStage = CAL_IDLE; doorCalFailed = false;
  message = NO_MESSAGE; uiDirty = true; calibrationReply(F("cancelled"));
}
void startLightCapture(DoorCalStage stage, uint32_t now) {
  doorCalStage = stage; lightCalCount = 0; lightSum = 0;
  calMinimum = 1023; calMaximum = 0; lightCalLast = now;
  uiDirty = true; calibrationReply();
}
void calibrationControls(uint32_t now) {
  if (doorCalStage == CAL_BOOT) return;
  if (stopButton.pressed) { calibrationCancel(); return; }
  if (!startButton.pressed) return;
  if (doorCalStage == CAL_WAIT_OPEN) {
    doorCalFailed = false; startLightCapture(CAL_SAMPLE_OPEN, now);
  } else if (doorCalStage == CAL_WAIT_CLOSED) startLightCapture(CAL_SAMPLE_CLOSED, now);
}
void finishCalibration() {
  if (!calibrating || lightCalCount < CAL_SAMPLES) return;
  uint16_t measured = lightSum / CAL_SAMPLES;
  if (doorCalStage == CAL_BOOT) {
    doorLevel = measured; doorClosedLevel = 0;
    doorCloseCutoff = uint32_t(doorLevel) * SHADED_PERCENT / 100;
    doorOpenCutoff = uint32_t(doorLevel) * CLEAR_PERCENT / 100;
    calibrating = false; doorCalStage = CAL_IDLE; uiDirty = true;
    prefix(F("cal")); Serial.print(F(",\"door\":")); Serial.print(doorLevel); Serial.println(F(",\"saved\":0}"));
    if (doorLevel < MIN_CAL_LEVEL) event(F("warning"), F("low calibration light"));
    sampleDoor();
  } else if (doorCalStage == CAL_SAMPLE_OPEN) {
    pendingOpen = measured; openMinimum = calMinimum;
    doorCalStage = CAL_WAIT_CLOSED; uiDirty = true; calibrationReply();
  } else if (doorCalStage == CAL_SAMPLE_CLOSED) {
    bool contrast = pendingOpen > measured && pendingOpen - measured >= MIN_DOOR_CONTRAST &&
                    openMinimum > calMaximum + MIN_DOOR_SEPARATION;
    bool saved = contrast && saveDoorCalibration(pendingOpen, measured);
    if (!saved) {
      prefix(F("cal_error")); Serial.print(F(",\"reason\":\""));
      Serial.print(contrast ? F("storage_failed") : F("insufficient_contrast"));
      Serial.print(F("\",\"open\":")); Serial.print(pendingOpen);
      Serial.print(F(",\"closed\":")); Serial.print(measured);
      Serial.print(F(",\"open_min\":")); Serial.print(openMinimum);
      Serial.print(F(",\"closed_max\":")); Serial.print(calMaximum); Serial.println(F("}"));
      doorCalStage = CAL_WAIT_OPEN; doorCalFailed = true; uiDirty = true;
      startBeeps(2, ALERT_BEEP_MS); calibrationReply(); return;
    }
    setDoorCalibration(pendingOpen, measured);
    calibrating = false; doorCalStage = CAL_IDLE; uiDirty = true;
    message = CAL_SAVED; messageSince = millis(); sampleDoor();
    startBeeps(2, ALERT_BEEP_MS); calibrationReply(F("saved"));
  }
}
void pollLight(uint32_t now) {
  if (calibrating) {
    bool capturing = doorCalStage == CAL_BOOT || doorCalStage == CAL_SAMPLE_OPEN || doorCalStage == CAL_SAMPLE_CLOSED;
    if (capturing && lightCalCount < CAL_SAMPLES && uint32_t(now - lightCalLast) >= CAL_SAMPLE_MS) {
      lightCalLast = now; doorRaw = average(PIN_DOOR); lightSum += doorRaw; ++lightCalCount;
      if (doorRaw < calMinimum) calMinimum = doorRaw;
      if (doorRaw > calMaximum) calMaximum = doorRaw;
    }
    return;
  }
  if (uint32_t(now - sensorLast) >= SENSOR_MS) { sensorLast = now; sampleDoor(); }
}
void buzzerSet(bool on) {
  if (buzzerOn == on) return;
  buzzerOn = on; digitalWrite(PIN_BUZZER, on ? HIGH : LOW); event(F("buzzer"), uint16_t(on));
}
void startBeeps(uint8_t count, uint16_t duration) {
  beepsLeft = count; beepLength = duration; beepSince = millis(); buzzerSet(count != 0);
}
void stopBeeps() { beepsLeft = 0; buzzerSet(false); }
void pollBuzzer(uint32_t now) {
  if (!beepsLeft) return;
  if (buzzerOn && uint32_t(now - beepSince) >= beepLength) {
    buzzerSet(false); --beepsLeft; beepSince = now;
  } else if (!buzzerOn && uint32_t(now - beepSince) >= BEEP_GAP_MS) {
    buzzerSet(true); beepSince = now;
  }
}
void pollButtons(uint32_t now) {
  if (startButton.poll(now)) buttonEvent(F("btn_start"), startButton);
  if (stopButton.poll(now)) buttonEvent(F("btn_stop"), stopButton);
  if (timeButton.poll(now)) buttonEvent(F("btn_time"), timeButton);
  if (powerButton.poll(now)) buttonEvent(F("btn_power"), powerButton);
  if (quickButton.poll(now)) buttonEvent(F("btn_30s"), quickButton);
  if (buttonTest) {
    for (uint8_t i = 0; i < BUTTON_SCAN_COUNT; ++i)
      if (scanButtons[i].poll(now)) buttonEvent(F("input"), scanButtons[i]);
  } else if (startButton.pressed || stopButton.pressed || timeButton.pressed || powerButton.pressed || quickButton.pressed) {
    startBeeps(1, BUTTON_BEEP_MS);
  }
}
void requestStart(uint32_t now) {
  if (state == COOKING) return;
  bool doorBlocked = requireDoorClosed && !doorShut;
  if (doorBlocked || !seconds) {
    message = doorBlocked ? CLOSE_DOOR : SET_TIME; messageSince = now; uiDirty = true;
    actionEvent(doorBlocked ? F("refused:DOOR") : F("refused:TIME")); return;
  }
  bool resume = state == PAUSED;
  message = NO_MESSAGE; doorPause = false; tickLast = now;
  actionEvent(resume ? F("resume") : F("start")); changeState(COOKING);
}
void clearCooking() {
  setSeconds(0); doorPause = false; message = NO_MESSAGE; uiDirty = true;
  actionEvent(F("clear")); changeState(READY);
}
void stateMachine(uint32_t now) {
  if (calibrating) { calibrationControls(now); return; }
  if (buttonTest) return;
  if (message != NO_MESSAGE && uint32_t(now - messageSince) >= MESSAGE_MS) {
    message = NO_MESSAGE; uiDirty = true;
  }
  // Door safety is evaluated before buttons or countdown completion.
  if (state == COOKING && requireDoorClosed && !doorShut) { pauseCooking(true); return; }
  if (state == COOKING) {
    while (state == COOKING && uint32_t(now - tickLast) >= 1000UL) {
      tickLast += 1000UL; setSeconds(seconds - 1);
      if (!seconds) { actionEvent(F("done")); changeState(DONE); doneSince = now; startBeeps(3, ALERT_BEEP_MS); }
    }
  }
  if (state == DONE && uint32_t(now - doneSince) >= DONE_MS) changeState(READY);
  if (stopButton.pressed) {
    message = NO_MESSAGE; uiDirty = true;
    if (state == COOKING) pauseCooking(false);
    else if (state == PAUSED || state == SET) clearCooking();
    return;
  }
  if (timeButton.pressed && (state == READY || state == SET)) {
    message = NO_MESSAGE;
    uint16_t step = seconds < TIME_STEP_BOUNDARY ? TIME_SHORT_STEP : TIME_LONG_STEP;
    setSeconds(min(uint16_t(seconds + step), MAX_TIME)); changeState(SET); uiDirty = true;
  }
  if (powerButton.pressed && (state == READY || state == SET)) {
    message = NO_MESSAGE; setPower(Power((powerLevel + 1) % 3)); uiDirty = true;
  }
  if (quickButton.pressed) {
    bool instant = seconds == 0;
    message = NO_MESSAGE; uiDirty = true;
    if (instant) { setPower(HI); doorPause = false; changeState(SET); }
    setSeconds(min(uint16_t(seconds + QUICK_TIME), MAX_TIME));
    if (instant) requestStart(now);
  }
  if (startButton.pressed) requestStart(now);
}
void heartbeat() {
  prefix(F("hb"));
  Serial.print(F(",\"btn_start\":")); Serial.print(startButton.held);
  Serial.print(F(",\"btn_stop\":")); Serial.print(stopButton.held);
  Serial.print(F(",\"btn_time\":")); Serial.print(timeButton.held);
  Serial.print(F(",\"btn_power\":")); Serial.print(powerButton.held);
  Serial.print(F(",\"btn_30s\":")); Serial.print(quickButton.held);
  Serial.print(F(",\"door\":")); Serial.print(doorShut);
  Serial.print(F(",\"door_raw\":")); Serial.print(doorRaw);
  Serial.print(F(",\"door_cal\":")); Serial.print(doorLevel);
  Serial.print(F(",\"door_closed\":")); Serial.print(doorClosedLevel);
  Serial.print(F(",\"door_lo\":")); Serial.print(doorCloseCutoff);
  Serial.print(F(",\"door_hi\":")); Serial.print(doorOpenCutoff);
  Serial.print(F(",\"door_saved\":")); Serial.print(doorSaved);
  Serial.print(F(",\"buzzer\":")); Serial.print(buzzerOn);
  Serial.print(F(",\"time\":")); Serial.print(seconds);
  Serial.print(F(",\"power_level\":\"")); Serial.print(powerName());
  Serial.print(F("\",\"state\":\"")); Serial.print(stateName());
  Serial.print(F("\",\"door_pause\":")); Serial.print(doorPause);
  Serial.print(F(",\"display\":[\"")); Serial.print(display1);
  Serial.print(F("\",\"")); Serial.print(display2);
  Serial.print(F("\"],\"light\":\"")); Serial.print(colourName());
  Serial.print(F("\",\"calibrating\":")); Serial.print(calibrating);
  Serial.print(F(",\"lcd_present\":")); Serial.print(lcdPresent);
  Serial.print(F(",\"button_test\":")); Serial.print(buttonTest);
  if (buttonTest) { Serial.print(F(",\"input_mask\":")); Serial.print(buttonInputMask()); }
  Serial.print(F(",\"rgb_present\":")); Serial.print(rgbPresent);
  Serial.print(F(",\"rgb_addr\":")); Serial.print(rgbAddress);
  Serial.print(F(",\"lcd_pending\":")); Serial.print(lcdPendingRows != 0);
  if (lcdIoError != IO_OK) { Serial.print(F(",\"lcd_error\":\"")); Serial.print(i2cErrorName(lcdIoError)); Serial.print(F("\"")); }
  if (rgbIoError != IO_OK) { Serial.print(F(",\"rgb_error\":\"")); Serial.print(i2cErrorName(rgbIoError)); Serial.print(F("\"")); }
  Serial.print(F(",\"i2c\":\"software\",\"i2c_us\":")); Serial.print(I2C_DELAY_US); Serial.println(F("}"));
}
void executeCommand(uint32_t now) {
  if (!commandOverflow && !strcmp_P(command, reinterpret_cast<PGM_P>(F("ping")))) {
    prefix(F("pong")); Serial.println(F("}"));
  } else if (!commandOverflow && !strcmp_P(command, reinterpret_cast<PGM_P>(F("status")))) heartbeat();
  else if (!commandOverflow && !strcmp_P(command, reinterpret_cast<PGM_P>(F("buttons")))) {
    if (calibrating && doorCalStage != CAL_BOOT) calibrationCancel();
    if (state == COOKING) pauseCooking(false);
    beginButtonTest(); message = NO_MESSAGE; uiDirty = true; render(); buttonTestReply();
  }
  else if (!commandOverflow && !strcmp_P(command, reinterpret_cast<PGM_P>(F("normal")))) {
    buttonTest = false;
    for (uint8_t i = 0; i < BUTTON_SCAN_COUNT; ++i) {
      uint8_t pin = BUTTON_SCAN_PINS[i];
      if (pin != PIN_START && pin != PIN_STOP && pin != PIN_TIME && pin != PIN_POWER && pin != PIN_30S)
        pinMode(pin, INPUT);
    }
    uiDirty = true; render(); buttonTestReply();
  }
  else if (!commandOverflow && !strcmp_P(command, reinterpret_cast<PGM_P>(F("i2c")))) {
    if (scanAddress) { prefix(F("error")); Serial.println(F(",\"msg\":\"I2C scan busy\"}")); }
    else { scanAddress = 1; scanCount = 0; scanTruncated = false; }
  }
  else if (!commandOverflow && !strcmp_P(command, reinterpret_cast<PGM_P>(F("lcd")))) {
    initializeDisplay(); render();
    prefix(F("lcd")); Serial.print(F(",\"lcd_present\":")); Serial.print(lcdPresent);
    Serial.print(F(",\"rgb_present\":")); Serial.print(rgbPresent);
    Serial.print(F(",\"rgb_addr\":")); Serial.print(rgbAddress); Serial.println(F("}"));
  }
  else if (!commandOverflow && (!strcmp_P(command, reinterpret_cast<PGM_P>(F("cal"))) ||
                               !strcmp_P(command, reinterpret_cast<PGM_P>(F("doorcal"))))) {
    if (calibrating) { prefix(F("error")); Serial.println(F(",\"msg\":\"calibration busy\"}")); }
    else guidedCalibrationStart(now);
  } else if (!commandOverflow && !strcmp_P(command, reinterpret_cast<PGM_P>(F("calstop")))) {
    calibrationCancel();
  } else if (!commandOverflow && !strcmp_P(command, reinterpret_cast<PGM_P>(F("beep")))) {
    startBeeps(1, ALERT_BEEP_MS); prefix(F("beep")); Serial.print(F(",\"pin\":"));
    Serial.print(PIN_BUZZER); Serial.println(F("}"));
  } else if (!commandOverflow && !strcmp_P(command, reinterpret_cast<PGM_P>(F("reset")))) {
    stopBeeps(); clearCooking(); setPower(HI); render(); prefix(F("reset")); Serial.println(F("}"));
  } else { prefix(F("error")); Serial.println(F(",\"msg\":\"unknown command\"}")); }
}
void serialPoll(uint32_t now) {
  uint8_t budget = COMMAND_SIZE;
  while (budget-- && Serial.available()) {
    char ch = Serial.read();
    if (ch == '\r') continue;
    if (ch == '\n') {
      command[commandLength] = '\0'; executeCommand(now);
      commandLength = 0; commandOverflow = false; break;
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
  event(F("cook"), action);
}

#ifdef RAV_WIFI
static void publishSnapshot() {
  char body[rav::SNAPSHOT_MAX];

  snprintf(body, sizeof(body),
           "{\"btn_start\":%u,\"btn_stop\":%u,\"btn_time\":%u,\"btn_power\":%u,\"btn_30s\":%u,"
           "\"door\":%u,\"time\":%u,\"power_level\":\"%s\",\"cook\":\"%s\","
           "\"state\":\"%s\",\"backlight\":\"%s\",\"LCD\":\"%s  %s\"}",
           unsigned(startButton.held), unsigned(stopButton.held), unsigned(timeButton.held),
           unsigned(powerButton.held), unsigned(quickButton.held), unsigned(doorShut), unsigned(seconds),
           reinterpret_cast<const char *>(powerName()), reinterpret_cast<const char *>(lastAction),
           reinterpret_cast<const char *>(stateName()), reinterpret_cast<const char *>(colourName()),
           display1, display2);
  rav::update(body);
}
#endif

void setup() {
  Serial.begin(115200);
#if defined(ARDUINO_ARCH_RENESAS_UNO)
  analogReadResolution(10);
#endif
  startButton.begin(); stopButton.begin(); timeButton.begin(); powerButton.begin(); quickButton.begin();
  digitalWrite(PIN_BUZZER, LOW); pinMode(PIN_BUZZER, OUTPUT);
  lineRelease(PIN_SOFT_SDA); lineRelease(PIN_SOFT_SCL);
  displayStartupAt = millis();
  bool savedCalibration = loadDoorCalibration();
  prefix(F("hello")); Serial.print(F(",\"dev\":\"MW-1\",\"fw\":\"1.1\",\"ram\":"));
  Serial.print(freeRam()); Serial.println(F("}"));
  if (savedCalibration) {
    prefix(F("cal")); Serial.print(F(",\"door\":")); Serial.print(doorLevel); Serial.println(F(",\"saved\":1}"));
    calibrationReply(F("loaded")); sampleDoor();
  } else calibrationStart(millis());
}
void loop() {
  uint32_t now = millis();
  if (!displayStarted && uint32_t(now - displayStartupAt) >= DISPLAY_STARTUP_MS) {
    initializeDisplay(); now = millis();
  }
  pollButtons(now); pollLight(now); finishCalibration(); stateMachine(now); render(); serialPoll(millis());
  now = millis();
  if (uint32_t(now - heartbeatLast) >= HEARTBEAT_MS) { heartbeatLast = now; heartbeat(); }
  scanPoll(); lcdPoll(); pollBuzzer(millis());
#ifdef RAV_WIFI
  publishSnapshot();
#endif
}
