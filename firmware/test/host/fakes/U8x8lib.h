#pragma once
#include <cstdint>
constexpr uint8_t U8X8_PIN_NONE = 255;
inline uint8_t u8x8_font_chroma48medium8_r[1];
constexpr uint8_t U8X8_MSG_BYTE_INIT = 1, U8X8_MSG_BYTE_START_TRANSFER = 2;
constexpr uint8_t U8X8_MSG_BYTE_SEND = 3, U8X8_MSG_BYTE_END_TRANSFER = 4;
constexpr uint8_t U8X8_MSG_GPIO_AND_DELAY_INIT = 40;
struct u8x8_t {
  uint8_t address = 0;
  uint8_t (*byte_cb)(u8x8_t *, uint8_t, uint8_t, void *) = nullptr;
  uint8_t (*gpio_and_delay_cb)(u8x8_t *, uint8_t, uint8_t, void *) = nullptr;
};
inline uint8_t u8x8_gpio_and_delay_arduino(u8x8_t *, uint8_t message, uint8_t, void *) {
  if (message == U8X8_MSG_GPIO_AND_DELAY_INIT) { pinMode(A5, OUTPUT); pinMode(A4, OUTPUT); }
  return 1;
}
inline uint8_t u8x8_GetI2CAddress(u8x8_t *display) { return display->address; }
struct U8X8_SSD1306_128X64_NONAME_SW_I2C {
  u8x8_t display;
  uint8_t flip = 0;
  struct Glyph { uint8_t x, y, width, value; };
  std::vector<Glyph> glyphs;
  explicit U8X8_SSD1306_128X64_NONAME_SW_I2C(uint8_t, uint8_t, uint8_t) { display.gpio_and_delay_cb = u8x8_gpio_and_delay_arduino; }
  u8x8_t *getU8x8() { return &display; }
  void setI2CAddress(uint8_t a) { display.address = a; }
  void transfer(uint8_t control, uint8_t count, uint8_t *data) {
    display.byte_cb(&display, U8X8_MSG_BYTE_START_TRANSFER, 0, nullptr);
    display.byte_cb(&display, U8X8_MSG_BYTE_SEND, 1, &control);
    display.byte_cb(&display, U8X8_MSG_BYTE_SEND, count, data);
    display.byte_cb(&display, U8X8_MSG_BYTE_END_TRANSFER, 0, nullptr);
  }
  void initDisplay() {
    display.gpio_and_delay_cb(&display, U8X8_MSG_GPIO_AND_DELAY_INIT, 0, nullptr);
    display.byte_cb(&display, U8X8_MSG_BYTE_INIT, 0, nullptr);
    uint8_t command = 0xAE; transfer(0x00, 1, &command);
  }
  void setPowerSave(uint8_t save) { uint8_t command = save ? 0xAE : 0xAF; transfer(0x00, 1, &command); }
  void setFlipMode(uint8_t mode) { flip = mode; uint8_t command = mode ? 0xA0 : 0xA1; transfer(0x00, 1, &command); }
  void setFont(const uint8_t *) {}
  void drawTile(uint8_t, uint8_t, uint8_t count, uint8_t *data) { transfer(0x40, count * 8, data); }
  void drawGlyph(uint8_t x, uint8_t y, uint8_t width, uint8_t value) {
    glyphs.push_back({x, y, width, value});
    uint8_t glyph[16]; std::fill(glyph, glyph + 16, value);
    transfer(0x40, width * 8, glyph);
    transfer(0x40, width * 8, glyph);
  }
  void draw1x2Glyph(uint8_t x, uint8_t y, uint8_t value) { drawGlyph(x, y, 1, value); }
  void draw2x2Glyph(uint8_t x, uint8_t y, uint8_t value) { drawGlyph(x, y, 2, value); }
};
struct U8X8_SSD1306_128X64_NONAME_HW_I2C {
  uint8_t address = 0;
  explicit U8X8_SSD1306_128X64_NONAME_HW_I2C(uint8_t) {}
  void setI2CAddress(uint8_t a) { address = a; }
  void begin() {}
  void setFont(const uint8_t *) {}
  void clearDisplay() {}
  void drawString(uint8_t, uint8_t, const char *) {}
};
