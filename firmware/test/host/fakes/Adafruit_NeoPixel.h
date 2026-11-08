#pragma once
#include <cassert>
#include <cstdint>
constexpr uint8_t NEO_GRB = 0, NEO_KHZ800 = 0;
struct Adafruit_NeoPixel {
  uint8_t brightness = 255, pixels[72] = {};
  Adafruit_NeoPixel(uint16_t, uint8_t, uint8_t) {}
  void begin() {}
  void setBrightness(uint8_t b) { brightness = b; }
  void clear() {}
  uint32_t Color(uint8_t r, uint8_t g, uint8_t b) { return uint32_t(r) << 16 | uint16_t(g) << 8 | b; }
  void setPixelColor(uint16_t, uint32_t) {}
  void fill(uint32_t) {}
  void show() { assert(brightness <= 50); }
  uint8_t *getPixels() { return pixels; }
};
