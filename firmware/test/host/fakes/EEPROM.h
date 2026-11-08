#pragma once
#include <cstdint>
#include <cstring>
struct FakeEEPROM {
  uint8_t bytes[256];
  unsigned writes = 0;
  FakeEEPROM() { memset(bytes, 0xFF, sizeof(bytes)); }
  template<class T> T &get(int address, T &value) { memcpy(&value, bytes + address, sizeof(T)); return value; }
  template<class T> const T &put(int address, const T &value) {
    memcpy(bytes + address, &value, sizeof(T)); ++writes; return value;
  }
};
inline FakeEEPROM EEPROM;
