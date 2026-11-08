#pragma once
#include <cassert>
#include <iostream>
#include "Arduino.h"
int __heap_start;
void *__brkval = nullptr;

inline void initPins() {
  for (int &pin : pins) pin = HIGH;
  for (int &value : analogs) value = 700;
}
inline void contains(const char *text) { assert(Serial.output.find(text) != std::string::npos); }
inline void noEvent(const char *text) { assert(Serial.output.find(text) == std::string::npos); }
inline void finish(const char *name) {
  std::cout << Serial.history;
  std::cerr << name << " state-machine checks passed\n";
}
