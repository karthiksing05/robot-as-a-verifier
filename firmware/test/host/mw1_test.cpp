#include "support.h"
#ifdef MW1_TEST_SKETCH
#include MW1_TEST_SKETCH
#else
#include "../../MW1_firmware/MW1_firmware.ino"
#endif

void step(uint32_t ms = 1) { fakeNow += ms; loop(); }
void press(uint8_t pin) {
  pins[pin] = LOW; step(); step(20);
  pins[pin] = HIGH; step(); step(20);
}
void send(const char *s) { Serial.input = s; while (Serial.available()) serialPoll(fakeNow); }

int main() {
  initPins(); advanceClock = true;
  fakeI2C.enabled = true; fakeI2C.devices[0x3E] = fakeI2C.devices[0x62] = true;
  fakeI2C.needsStop = true;
  setup();
  for (int i = 0; i < 100; ++i) step(50);
  assert(!calibrating && doorLevel == 700 && !doorSaved && state == READY);
  assert(pinModes[PIN_BUZZER] == OUTPUT && pins[PIN_BUZZER] == LOW);
  assert(lcdPresent && rgbPresent && rgbAddress == 0x62);
  auto hasPacket = [](std::vector<uint8_t> packet) {
    return std::find(fakeI2C.packets.begin(), fakeI2C.packets.end(), packet) != fakeI2C.packets.end();
  };
  assert(hasPacket({0x7C, 0x80, 0x28}));
  assert(hasPacket({0x7C, 0x40, 'R'}));
  assert(hasPacket({0xC4, 0x08, 0xFF}) && hasPacket({0xC4, 0x04, 255}));
  // A UI change during a partial row must eventually write the newest two lines.
  setSeconds(10); changeState(SET); render(); lcdPoll(); lcdPoll();
  setSeconds(20); render();
  for (int i = 0; i < 40 && lcdPendingRows; ++i) lcdPoll();
  assert(!lcdPendingRows && lcdPresent);
  char screen[2][17] = {"                ", "                "};
  uint8_t cursor = 0;
  for (const auto &packet : fakeI2C.packets) {
    if (packet.size() != 3 || packet[0] != 0x7C) continue;
    if (packet[1] == 0x80 && (packet[2] & 0x80)) cursor = packet[2] & 0x7F;
    else if (packet[1] == 0x40) {
      if (cursor < 16) screen[0][cursor] = packet[2];
      if (cursor >= 0x40 && cursor < 0x50) screen[1][cursor - 0x40] = packet[2];
      ++cursor;
    }
  }
  assert(std::string(screen[0]) == "COOK 0:20       ");
  assert(std::string(screen[1]) == "POWER HI        ");
  clearCooking(); render();
  fakeI2C.devices[0x62] = false; fakeI2C.devices[0x30] = true; initializeDisplay(); render();
  assert(lcdPresent && rgbPresent && rgbAddress == 0x30);
  assert(hasPacket({0x60, 0x04, 0x15}) && hasPacket({0x60, 0x06, 255}));
  fakeI2C.devices[0x30] = false; initializeDisplay(); render();
  assert(lcdPresent && !rgbPresent && rgbAddress == 0);
  fakeI2C.devices[0x3E] = false; initializeDisplay(); render();
  assert(!lcdPresent && !rgbPresent);
  fakeI2C.devices[0x3E] = fakeI2C.devices[0x62] = true; initializeDisplay(); render();
  fakeI2C.nackData = true;
  assert(!lcdCmd(0x28));
  assert(lastI2cAddress == 0x3E && lastI2cError == CONTROL_NACK);
  lcdPoll(); assert(!lcdPresent && !lcdPendingRows);
  contains("\"io_error\":\"control_nack\"");
  fakeI2C.nackData = false;
  fakeI2C.heldClock = true;
  uint32_t before = fakeMicros; assert(!probe(0x3E));
  assert(lastI2cError == CLOCK_TIMEOUT);
  assert(fakeMicros - before < 3000);
  fakeI2C.heldClock = false;
  lineRelease(PIN_SOFT_SCL);
  send("lcd\n"); assert(lcdPresent && rgbPresent && lcdPendingRows);
  for (int i = 0; i < 40 && lcdPendingRows; ++i) lcdPoll();
  assert(!lcdPendingRows); contains("\"ev\":\"lcd_sync\"");
  send("i2c\n"); assert(scanAddress == 1);
  send("i2c\n"); contains("I2C scan busy");
  for (int i = 0; i < 126; ++i) scanPoll();
  assert(scanAddress == 0); contains("\"ev\":\"i2c\"");
  assert(scanCount == 2 && scanFound[0] == 0x3E && scanFound[1] == 0x62);
  assert(fakeI2C.starts == fakeI2C.stops);
  analogs[PIN_DOOR] = 385; step(20); assert(!doorShut);
  analogs[PIN_DOOR] = 384; step(20); assert(doorShut);
  analogs[PIN_DOOR] = 490; step(20); assert(doorShut);
  analogs[PIN_DOOR] = 491; step(20); assert(!doorShut);
  analogs[PIN_DOOR] = 700;
  press(PIN_START);
  assert(message == (requireDoorClosed ? CLOSE_DOOR : SET_TIME));
  contains(requireDoorClosed ? "refused:DOOR" : "refused:TIME");
  step(MESSAGE_MS); assert(message == NO_MESSAGE);
  analogs[PIN_DOOR] = 100; step(20); assert(doorShut);
  press(PIN_START); assert(message == SET_TIME); contains("refused:TIME");
  for (int i = 0; i < 6; ++i) press(PIN_TIME);
  assert(seconds == 60 && state == SET); press(PIN_TIME); assert(seconds == 120);
  press(PIN_POWER); assert(powerLevel == MED); press(PIN_POWER); assert(powerLevel == LO);
  press(PIN_POWER); assert(powerLevel == HI);
  setSeconds(1790); press(PIN_TIME); assert(seconds == MAX_TIME);
  press(PIN_30S); assert(seconds == MAX_TIME);
  press(PIN_STOP); assert(seconds == 0 && state == READY);
  press(PIN_30S); assert(state == COOKING && seconds == 30 && powerLevel == HI);
  press(PIN_TIME); press(PIN_POWER); assert(powerLevel == HI);
  press(PIN_30S); assert(seconds >= 59 && seconds <= 60);
  analogs[PIN_DOOR] = 700; step(20);
  if (requireDoorClosed) assert(state == PAUSED && doorPause && colour == COLOUR_RED);
  else { assert(state == COOKING && !doorPause); press(PIN_STOP); assert(state == PAUSED); }
  uint16_t pausedTime = seconds; step(2000); assert(seconds == pausedTime);
  analogs[PIN_DOOR] = 100; step(20); assert(state == PAUSED && !doorPause && colour == COLOUR_AMBER);
  press(PIN_START); assert(state == COOKING); contains("\"v\":\"resume\"");
  press(PIN_STOP); assert(state == PAUSED); press(PIN_STOP); assert(state == READY && seconds == 0);
  analogs[PIN_DOOR] = 700; step(20); press(PIN_30S);
  assert(seconds == 30);
  if (requireDoorClosed) assert(state == SET && message == CLOSE_DOOR);
  else assert(state == COOKING && message == NO_MESSAGE);
  analogs[PIN_DOOR] = 100; step(20); setSeconds(2); press(PIN_START);
  step(2000); assert(state == DONE && seconds == 0 && colour == COLOUR_GREEN);
  step(DONE_MS); assert(state == READY);
  stopBeeps(); send("beep\n"); assert(buzzerOn && pins[PIN_BUZZER] == HIGH);
  step(ALERT_BEEP_MS); assert(!buzzerOn && pins[PIN_BUZZER] == LOW && beepsLeft == 0);
  startBeeps(3, ALERT_BEEP_MS);
  for (int i = 0; i < 3; ++i) {
    step(ALERT_BEEP_MS); assert(!buzzerOn);
    if (i < 2) { step(BEEP_GAP_MS); assert(buzzerOn); }
  }
  assert(beepsLeft == 0 && analogReads[PIN_BUZZER] == 0);
  fakeNow = UINT32_MAX - 500; setSeconds(2); changeState(SET); press(PIN_START);
  step(1000); assert(seconds == 1); step(1000); assert(state == DONE);
  send("PiNg\r\n"); contains("\"ev\":\"pong\"");
  send("xxxxxxxxxxxxxxxxxxxx\nstatus\n"); contains("unknown command"); contains("\"ev\":\"hb\"");
  send("reset\n"); assert(state == READY && seconds == 0 && powerLevel == HI);
  press(PIN_30S); assert(state == COOKING);
  analogs[PIN_DOOR] = 700; send("cal\n"); assert(calibrating && state == PAUSED);
  assert(doorCalStage == CAL_WAIT_OPEN);
  press(PIN_START);
  for (int i = 0; i < CAL_SAMPLES; ++i) step(CAL_SAMPLE_MS);
  assert(doorCalStage == CAL_WAIT_CLOSED && pendingOpen == 700);
  analogs[PIN_DOOR] = 650; press(PIN_START);
  for (int i = 0; i < CAL_SAMPLES; ++i) step(CAL_SAMPLE_MS);
  assert(!calibrating && state == PAUSED && doorSaved && doorLevel == 700 && doorClosedLevel == 650);
  assert(doorCloseCutoff == 670 && doorOpenCutoff == 680 && doorShut);
  contains("\"stage\":\"saved\"");
  unsigned writes = EEPROM.writes;
  assert(saveDoorCalibration(700,650) && EEPROM.writes == writes);
  analogs[PIN_DOOR] = 680; step(20); assert(doorShut);
  analogs[PIN_DOOR] = 681; step(20); assert(!doorShut);
  analogs[PIN_DOOR] = 670; step(20); assert(!doorShut);
  analogs[PIN_DOOR] = 669; step(20); assert(doorShut);
  doorSaved = false; doorLevel = doorClosedLevel = 0;
  assert(loadDoorCalibration() && doorLevel == 700 && doorClosedLevel == 650);
  DoorCalRecord good; EEPROM.get(DOOR_CAL_ADDRESS, good);
  DoorCalRecord corrupt = good; corrupt.checksum ^= 1; EEPROM.put(DOOR_CAL_ADDRESS, corrupt);
  assert(!loadDoorCalibration()); EEPROM.put(DOOR_CAL_ADDRESS, good);
  writes = EEPROM.writes;
  send("doorcal\n"); analogs[PIN_DOOR] = 700; press(PIN_START);
  for (int i = 0; i < CAL_SAMPLES; ++i) step(CAL_SAMPLE_MS);
  analogs[PIN_DOOR] = 680; press(PIN_START);
  for (int i = 0; i < CAL_SAMPLES; ++i) step(CAL_SAMPLE_MS);
  assert(calibrating && doorCalFailed && doorCalStage == CAL_WAIT_OPEN);
  assert(EEPROM.writes == writes && doorClosedLevel == 650);
  contains("insufficient_contrast"); send("calstop\n"); assert(!calibrating && doorSaved);
  send("reset\n"); analogs[PIN_DOOR] = 100; step(20);
  press(PIN_30S); assert(state == COOKING);
  send("buttons\n"); assert(buttonTest && state == PAUSED);
  uint16_t testTime = seconds;
  for (uint8_t pin : {PIN_TIME, PIN_30S, PIN_POWER, PIN_START, PIN_STOP}) press(pin);
  pins[8] = LOW; step(); step(20); assert(buttonInputMask() & (uint32_t(1) << 8));
  contains("\"ev\":\"input\",\"v\":1,\"pin\":8");
  pins[8] = HIGH; step(); step(20); assert(!(buttonInputMask() & (uint32_t(1) << 8)));
  assert(seconds == testTime && state == PAUSED && powerLevel == HI);
  contains("\"pin\":"); contains("\"ev\":\"buttons\",\"v\":1");
  assert(std::string(display1) == "BUTTON TEST");
  heartbeat();
  send("normal\n"); assert(!buttonTest && state == PAUSED);
  press(PIN_STOP); assert(state == READY && seconds == 0);
  press(PIN_TIME); assert(state == SET && seconds == 10);
  assert(analogReads[PIN_BUZZER] == 0);
  // Disabling the requirement bypasses START/+30s refusals and door-open pauses,
  // while retaining time validation, sensor reporting, and manual pause/resume.
  if (!requireDoorClosed) {
    send("reset\n");
    analogs[PIN_DOOR] = 700; step(20); assert(!doorShut);
    press(PIN_START); assert(state == READY && message == SET_TIME);
    press(PIN_TIME); press(PIN_START); assert(state == COOKING);
    step(1000); assert(state == COOKING && seconds == 9);
    analogs[PIN_DOOR] = 100; step(20); assert(doorShut);
    analogs[PIN_DOOR] = 700; step(20); assert(!doorShut && state == COOKING);
    press(PIN_STOP); assert(state == PAUSED && !doorPause);
    press(PIN_START); assert(state == COOKING && !doorPause);
    press(PIN_STOP); press(PIN_STOP); assert(state == READY);
    press(PIN_30S); assert(state == COOKING && seconds == 30);
  }
  heartbeat(); finish("MW-1");
}
