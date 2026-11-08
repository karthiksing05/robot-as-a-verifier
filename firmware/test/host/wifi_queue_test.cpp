#include <cstring>
#include "support.h"

#define RAV_HOST "test"
#define RAV_PORT 443
#define SECRET_SSID "test"
#define SECRET_PASS "test"
#define DEVICE_NAME "mc6-01"
#define DEVICE_KEY "test"
#include "../../firmware/rav_wifi.h"
#include "../../MC6_firmware/MC6_firmware.ino"

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

  rav::client.reply = "HTTP/1.1 401 Unauthorized\r\n\r\n";
  fakeNow = 1080;
  rav::update(released, 0);
  assert(rav::lastStatus == 401);
  const auto statusCalls = WiFi.statusCalls;
  for (fakeNow = 1081; fakeNow < 31080; ++fakeNow) rav::update(released, 0);
  assert(rav::client.posts.size() == 3);
  assert(WiFi.statusCalls - statusCalls <= 60);

  // Check the actual Wi-Fi JSON channel while the applied speed is frozen.
  state = OFF;
  rpm = 3500;
  char snapshot[rav::SNAPSHOT_MAX];
  analogs[PIN_SPEED] = 0; pollSensors(fakeNow);
  formatSnapshot(snapshot, sizeof(snapshot));
  assert(strstr(snapshot, "\"speed\":1000"));
  analogs[PIN_SPEED] = 1023; pollSensors(fakeNow + SENSOR_MS);
  formatSnapshot(snapshot, sizeof(snapshot));
  assert(strstr(snapshot, "\"speed\":6000"));
  assert(strstr(snapshot, "\"applied_speed\":3500"));
}
