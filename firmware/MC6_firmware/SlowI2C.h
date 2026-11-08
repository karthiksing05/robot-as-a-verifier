#pragma once
#include <Arduino.h>

// Open-drain transport adapted from the verified MW-1 driver. Never drive HIGH.
namespace Mc6I2c {
const uint8_t SDA_PIN = A4, SCL_PIN = A5;
const uint16_t DELAY_US = 20, TIMEOUT_US = 1000;
enum Error : uint8_t { OK, SDA_BUSY, CLOCK_TIMEOUT, ADDRESS_NACK, DATA_NACK };
Error error = OK;
void low(uint8_t pin) { digitalWrite(pin, LOW); pinMode(pin, OUTPUT); }
void release(uint8_t pin) { pinMode(pin, INPUT_PULLUP); }
bool clockHigh() {
  release(SCL_PIN);
  uint32_t started = micros();
  while (digitalRead(SCL_PIN) == LOW) {
    if (uint32_t(micros() - started) >= TIMEOUT_US) { error = CLOCK_TIMEOUT; return false; }
  }
  delayMicroseconds(DELAY_US); return true;
}
bool start() {
  release(SDA_PIN);
  if (!clockHigh()) return false;
  if (digitalRead(SDA_PIN) == LOW) { error = SDA_BUSY; return false; }
  low(SDA_PIN); delayMicroseconds(DELAY_US);
  low(SCL_PIN); delayMicroseconds(DELAY_US); return true;
}
bool stop() {
  low(SDA_PIN); delayMicroseconds(DELAY_US);
  bool ok = clockHigh();
  release(SDA_PIN); delayMicroseconds(DELAY_US); return ok;
}
bool write(uint8_t value, Error nack = DATA_NACK) {
  for (uint8_t mask = 0x80; mask; mask >>= 1) {
    if (value & mask) release(SDA_PIN); else low(SDA_PIN);
    delayMicroseconds(DELAY_US);
    if (!clockHigh()) return false;
    low(SCL_PIN); delayMicroseconds(DELAY_US);
  }
  release(SDA_PIN); delayMicroseconds(DELAY_US);
  if (!clockHigh()) return false;
  bool ack = digitalRead(SDA_PIN) == LOW;
  low(SCL_PIN); delayMicroseconds(DELAY_US);
  if (!ack) error = nack;
  return ack;
}
void begin() {
  release(SDA_PIN); low(SCL_PIN); stop(); error = OK;
}
bool probe(uint8_t address) {
  error = OK;
  bool ok = start() && write(address << 1, ADDRESS_NACK);
  bool stopped = stop(); return ok && stopped;
}
}
