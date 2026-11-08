#pragma once
#include "Arduino.h"

constexpr int WL_CONNECTED = 3;
struct FakeWiFi {
  unsigned statusCalls = 0;
  int status() { ++statusCalls; return WL_CONNECTED; }
  void setTimeout(unsigned long) {}
  void begin(const char *, const char *) {}
};
inline FakeWiFi WiFi;

struct WiFiClient {
  bool open = false;
  std::string reply;
  std::vector<std::string> posts;
  bool connected() const { return open; }
  void stop() { open = false; }
  void setConnectionTimeout(int) {}
  bool connect(const char *, uint16_t) { return open = true; }
  template <typename T> void print(T) {}
  size_t write(const uint8_t *bytes, size_t count) {
    posts.emplace_back(reinterpret_cast<const char *>(bytes), count);
    return count;
  }
  int available() const { return int(reply.size()); }
  int read(uint8_t *bytes, size_t count) {
    std::copy_n(reply.begin(), count, bytes);
    reply.erase(0, count);
    return int(count);
  }
};
