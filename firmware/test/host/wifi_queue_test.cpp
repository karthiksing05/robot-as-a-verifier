#include <cstring>

#define RAV_HOST "test"
#define RAV_PORT 443
#define SECRET_SSID "test"
#define SECRET_PASS "test"
#define DEVICE_NAME "mc6-01"
#define DEVICE_KEY "test"
#include "../../firmware/rav_wifi.h"

int main() {
  const char *released = "{\"btn_time\":0}";
  const char *pressed = "{\"btn_time\":1}";
  const char *ack = "HTTP/1.1 204 No Content\r\n\r\n";

  // A complete 450 ms hold happens while the previous request awaits its response.
  fakeNow = 500;
  rav::update(released, 0);
  assert(rav::client.posts.size() == 1);
  fakeNow = 550;
  rav::update(pressed, 4);
  fakeNow = 1000;
  rav::update(released, 0);
  assert(rav::client.posts.size() == 1);

  rav::client.reply = ack;
  fakeNow = 1010;
  rav::update(released, 0);
  fakeNow = 1020;
  rav::update(released, 0);
  assert(rav::client.posts.back() == pressed);
  rav::client.reply = ack;
  fakeNow = 1030;
  rav::update(released, 0);
  fakeNow = 1070;
  rav::update(released, 0);
  assert((rav::client.posts == std::vector<std::string>{released, pressed, released}));
}
