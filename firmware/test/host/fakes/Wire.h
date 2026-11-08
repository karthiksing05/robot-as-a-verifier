#pragma once
#include <cstdint>
struct FakeWire {
  uint8_t address = 0;
  bool missingPrimary = false, missingAll = false;
  bool missingV4 = false, missingV5 = true;
  void begin() {}
  void setWireTimeout(unsigned long, bool) {}
  void beginTransmission(uint8_t a) { address = a; }
  uint8_t endTransmission() {
    return missingAll || (missingPrimary && address == 0x3C) ||
           (missingV4 && address == 0x62) || (missingV5 && address == 0x30) ? 2 : 0;
  }
};
inline FakeWire Wire;
