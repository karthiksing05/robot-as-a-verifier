// Post snapshots to System 1 through the Vultr HTTPS endpoint by default.
#pragma once

#define RAV_WIFI 1
#include <WiFiS3.h>

#ifndef RAV_USE_TLS
#define RAV_USE_TLS 1
#endif
#if RAV_USE_TLS
#include <WiFiSSLClient.h>
#endif

namespace rav {
constexpr size_t SNAPSHOT_MAX = 320;
const uint32_t SEND_EVERY_MS = 500;
const uint16_t TIMEOUT_MS = RAV_USE_TLS ? 1500 : 300;
const uint16_t CONNECT_TIMEOUT_MS = 1200;
const uint32_t RETRY_POST_MS = 5000;
const uint32_t REJOIN_MS = 15000;
constexpr uint8_t EDGE_QUEUE_SIZE = 8;
const uint32_t EDGE_MAX_AGE_MS = 2000;

#if RAV_USE_TLS
WiFiSSLClient client;
#else
WiFiClient client;
#endif
char last[SNAPSHOT_MAX] = "";
uint32_t sentAt = 0, joinAt = 0;
bool joinedOnce = false;
int lastLink = -1;
int lastStatus = -1;
bool pending = false;
bool pendingEdge = false;
struct ButtonSnapshot {
  char body[SNAPSHOT_MAX];
  uint32_t capturedAt;
};
ButtonSnapshot edges[EDGE_QUEUE_SIZE];
uint8_t edgeHead = 0, edgeCount = 0;
int lastButtons = -1;
uint32_t polledAt = 0;
char statusLine[32];
size_t statusLength = 0;
uint32_t tail = 0;
int responseStatus = 0;

inline void join() {
  joinedOnce = true;
  client.stop();
  WiFi.setTimeout(CONNECT_TIMEOUT_MS);
  WiFi.begin(SECRET_SSID, SECRET_PASS);
  joinAt = millis();
}

inline bool post(const char *body, size_t len) {
  if (!client.connected()) {
    client.stop();
    client.setConnectionTimeout(CONNECT_TIMEOUT_MS);
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
  if (status == 204 && pendingEdge) {
    edgeHead = (edgeHead + 1) % EDGE_QUEUE_SIZE;
    --edgeCount;
  }
  pendingEdge = false;
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

// Capture debounced button changes even while an earlier request is in flight.
inline void update(const char *body, uint8_t buttons) {
  uint32_t now = millis();
  if (lastButtons >= 0 && buttons != lastButtons) {
    if (edgeCount < EDGE_QUEUE_SIZE) {
      auto &edge = edges[(edgeHead + edgeCount) % EDGE_QUEUE_SIZE];
      strcpy(edge.body, body);
      edge.capturedAt = now;
      ++edgeCount;
    } else {
      Serial.println(F("{\"ev\":\"wifi_button_edge_dropped\",\"reason\":\"queue_full\"}"));
    }
  }
  lastButtons = buttons;
  if (pending) { pollResponse(now); return; }
  while (edgeCount && now - edges[edgeHead].capturedAt >= EDGE_MAX_AGE_MS) {
    edgeHead = (edgeHead + 1) % EDGE_QUEUE_SIZE;
    --edgeCount;
    Serial.println(F("{\"ev\":\"wifi_button_edge_dropped\",\"reason\":\"expired\"}"));
  }
  const char *outgoing = edgeCount ? edges[edgeHead].body : body;
  bool changed = edgeCount || strcmp(outgoing, last) != 0;
  if (now - sentAt < (lastStatus == 204 && changed ? 50 : SEND_EVERY_MS)) return;
  const bool connected = WiFi.status() == WL_CONNECTED;
  const bool linkChanged = connected != lastLink;
  if (linkChanged) {
    lastLink = connected;
    Serial.print(F("{\"t\":")); Serial.print(now);
    Serial.print(F(",\"ev\":\"wifi_link\",\"v\":\""));
    Serial.print(connected ? F("connected") : F("disconnected"));
    Serial.println(F("\"}"));
  }
  if (!connected) {
    if (!joinedOnce || now - joinAt >= REJOIN_MS) join();
    sentAt = millis();
    return;
  }
  if (!linkChanged && lastStatus != -1 && lastStatus != 204 && now - sentAt < RETRY_POST_MS) return;
  strcpy(last, outgoing);  // each sketch builds its snapshot in a SNAPSHOT_MAX byte buffer
  pendingEdge = edgeCount != 0;
  pending = post(outgoing, strlen(outgoing));
  sentAt = millis();
  polledAt = sentAt;
  statusLength = tail = responseStatus = 0;
  if (!pending) complete(0);
}
}  // namespace rav
