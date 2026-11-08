#pragma once
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <sstream>
#include <string>
#include <type_traits>
#include <vector>

constexpr uint8_t A0 = 14, A1 = 15, A2 = 16, A3 = 17, A4 = 18, A5 = 19;
constexpr int LOW = 0, HIGH = 1, INPUT = 0, OUTPUT = 1, INPUT_PULLUP = 2;
struct __FlashStringHelper {};
#define F(s) (reinterpret_cast<const __FlashStringHelper *>(s))
inline uint32_t fakeNow = 0;
inline bool advanceClock = false;
inline int pins[20] = {};
inline int analogs[20] = {};
inline unsigned analogReads[20] = {};
inline int pinModes[20] = {}, pinWrites[20] = {};
inline uint16_t audioAmplitude = 0;
inline int audioPin = -1;
inline bool audioHigh = false;
inline uint32_t fakeMicros = 0;
struct FakeI2C {
  bool enabled = false, devices[128] = {}, heldClock = false, nackData = false;
  bool needsStop = false;
  bool sda = true, scl = true, active = false, ack = false;
  bool latches[2] = {true, true};
  int modes[2] = {INPUT_PULLUP, INPUT_PULLUP};
  uint8_t bits = 0, value = 0, address = 0;
  unsigned starts = 0, stops = 0;
  std::vector<uint8_t> packet;
  std::vector<std::vector<uint8_t>> packets;
  void update(uint8_t pin) {
    uint8_t i = pin - A4;
    if (modes[i] == OUTPUT) assert(!latches[i]);
    bool high = modes[i] != OUTPUT;
    if (pin == A4) {
      if (sda != high && scl) {
        if (!high) { active = true; bits = value = 0; packet.clear(); ++starts; }
        else {
          if (active) { if (!packet.empty()) packets.push_back(packet); ++stops; }
          active = false; needsStop = false;
        }
      }
      sda = high;
    } else {
      high = high && !heldClock;
      if (!scl && high && active) {
        if (bits < 8) {
          value = uint8_t((value << 1) | sda);
          if (++bits == 8) {
            if (packet.empty()) address = value >> 1;
            ack = devices[address] && !needsStop && (packet.empty() || !nackData);
            packet.push_back(value);
          }
        } else ++bits;
      }
      if (scl && !high && bits == 9) { bits = value = 0; }
      scl = high;
    }
  }
};
inline FakeI2C fakeI2C;
inline uint32_t millis() { return advanceClock ? fakeNow++ : fakeNow; }
inline uint32_t micros() { return fakeMicros++; }
inline void delayMicroseconds(unsigned int us) { fakeMicros += us; }
inline void pinMode(uint8_t pin, int mode) {
  pinModes[pin] = mode;
  if (fakeI2C.enabled && (pin == A4 || pin == A5)) {
    fakeI2C.modes[pin - A4] = mode;
    if (mode == INPUT_PULLUP) fakeI2C.latches[pin - A4] = true;
    fakeI2C.update(pin);
  } else if (mode == OUTPUT) pins[pin] = pinWrites[pin];
}
inline void digitalWrite(uint8_t pin, int value) {
  pinWrites[pin] = value;
  if (fakeI2C.enabled && (pin == A4 || pin == A5)) {
    fakeI2C.latches[pin - A4] = value;
    if (fakeI2C.modes[pin - A4] == OUTPUT) fakeI2C.update(pin);
  } else if (pinModes[pin] == OUTPUT) pins[pin] = value;
}
inline int digitalRead(uint8_t pin) {
  if (fakeI2C.enabled && pin == A5) return fakeI2C.scl;
  if (fakeI2C.enabled && pin == A4) {
    if (fakeI2C.active && fakeI2C.scl && fakeI2C.bits == 9) return !fakeI2C.ack;
    return fakeI2C.sda;
  }
  return pins[pin];
}
inline int analogRead(uint8_t pin) {
  ++analogReads[pin];
  if (pin != audioPin) return analogs[pin];
  audioHigh = !audioHigh;
  return 512 + (audioHigh ? audioAmplitude / 2 : -int(audioAmplitude / 2));
}
inline long map(long x, long inMin, long inMax, long outMin, long outMax) {
  return (x - inMin) * (outMax - outMin) / (inMax - inMin) + outMin;
}
using std::min;
struct FakeSerial {
  std::string output, input, history;
  void begin(unsigned long) {}
  int available() { return int(input.size()); }
  int read() { char c = input.front(); input.erase(0, 1); return uint8_t(c); }
  void append(const std::string &s) { output += s; history += s; }
  void print(const __FlashStringHelper *s) { append(reinterpret_cast<const char *>(s)); }
  void print(const char *s) { append(s); }
  void print(char *s) { append(s); }
  void print(char c) { append(std::string(1, c)); }
  template<class T> void print(T n) { append(std::to_string(n)); }
  template<class T> void println(T value) { print(value); append("\n"); }
};
inline FakeSerial Serial;
