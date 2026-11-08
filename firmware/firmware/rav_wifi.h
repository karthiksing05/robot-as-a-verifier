// HTTPS snapshot publishing for the UNO R4 WiFi. USB operation requires no secrets file.
#pragma once

#define RAV_WIFI 1
#include <WiFiS3.h>
#include <WiFiSSLClient.h>

namespace rav {
constexpr size_t SNAPSHOT_MAX = 320;
const uint32_t SEND_EVERY_MS = 500;
const uint16_t TIMEOUT_MS = 300;   // a slow reply mustn't hold up the buttons for long
const uint32_t REJOIN_MS = 10000;  // WiFi.begin blocks for a few seconds: don't retry it every loop

WiFiSSLClient client;
char last[SNAPSHOT_MAX] = "";
uint32_t sentAt = 0, joinAt = 0;
bool joinedOnce = false;
int lastStatus = -1;
bool pending = false;
uint32_t polledAt = 0;
char statusLine[32];
size_t statusLength = 0;
uint32_t tail = 0;
int responseStatus = 0;

inline void join() {
  joinedOnce = true;
  client.stop();
  WiFi.begin(SECRET_SSID, SECRET_PASS);
  joinAt = millis();
}

inline bool post(const char *body, size_t len) {
  if (!client.connected()) {
    client.stop();
    if (!client.connect(RAV_HOST, RAV_PORT)) return false;
  }
  client.print(F("POST /readout/" DEVICE_NAME " HTTP/1.1\r\nHost: " RAV_HOST "\r\nAuthorization: Bearer " DEVICE_KEY
                 "\r\nContent-Type: application/json\r\nConnection: keep-alive\r\nContent-Length: "));
  client.print(len);
  client.print(F("\r\n\r\n"));
  return client.write(reinterpret_cast<const uint8_t *>(body), len) == len;
}

inline void complete(int status) {
  pending = false;
  if (status != 204) client.stop();
  if (status != lastStatus) {
    lastStatus = status;
    Serial.print(F("{\"t\":")); Serial.print(millis());
    Serial.print(F(",\"ev\":\"wifi\",\"v\":")); Serial.print(status); Serial.println(F("}"));
  }
}

inline void pollResponse(uint32_t now) {
  if (now - sentAt >= TIMEOUT_MS) { complete(0); return; }
  if (now - polledAt < 10) return;
  polledAt = now;
  uint8_t buffer[128];
  int count = client.available();
  if (count <= 0) return;
  count = client.read(buffer, count < int(sizeof(buffer)) ? count : sizeof(buffer));
  for (int i = 0; i < count; ++i) {
    uint8_t ch = buffer[i];
    if (!responseStatus) {
      if (ch == '\n') {
        statusLine[statusLength] = '\0';
        if (sscanf(statusLine, "HTTP/1.%*d %d", &responseStatus) != 1 || responseStatus != 204) {
          complete(responseStatus);
          return;
        }
      } else if (statusLength < sizeof(statusLine) - 1) {
        statusLine[statusLength++] = char(ch);
      }
    }
    tail = (tail << 8) | ch;
    if (tail == 0x0d0a0d0a) { complete(responseStatus); return; }  // 204 has no body
  }
}

// Call every loop with the current snapshot (a NUL-terminated flat JSON object).
inline void update(const char *body) {
  uint32_t now = millis();
  if (pending) { pollResponse(now); return; }
  bool changed = strcmp(body, last) != 0;
  if (now - sentAt < (lastStatus == 204 && changed ? 50 : SEND_EVERY_MS)) return;
  if (WiFi.status() != WL_CONNECTED) {
    if (!joinedOnce || now - joinAt >= REJOIN_MS) join();
    sentAt = millis();
    return;
  }
  strcpy(last, body);  // each sketch builds its snapshot in a SNAPSHOT_MAX byte buffer
  pending = post(body, strlen(body));
  sentAt = millis();
  polledAt = sentAt;
  statusLength = tail = responseStatus = 0;
  if (!pending) complete(0);
}
}  // namespace rav
