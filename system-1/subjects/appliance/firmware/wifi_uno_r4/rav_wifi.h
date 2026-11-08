// rav_wifi.h: POSTs the appliance's snapshot to rav-server over WiFi, as the REST readout System 1 reads.
// The same file sits in every sketch folder (MC6_firmware, MW1_firmware, wifi_uno_r4): change one, copy it to the others.
//
// On an Arduino UNO R4 WiFi with an arduino_secrets.h next to the sketch (copy arduino_secrets.h.example), the sketch
// calls rav::begin() once and rav::update(snapshot) every loop. update POSTs the snapshot, one flat JSON object such as
// {"btn_start":0,"door":1,"LCD":"READY"}, to http://RAV_HOST:RAV_PORT/readout/DEVICE_NAME whenever it changes and at
// least every RAV_SEND_EVERY_MS, over one kept-open connection. On any other board, or without the secrets file,
// RAV_WIFI stays undefined and the sketch is USB serial only, as before.
//
// rav-server: --host 0.0.0.0 --readout http --readout-device DEVICE_NAME, with RAV_DEVICE_KEY = DEVICE_KEY
// (system-1/subjects/appliance/firmware/README.md, "Over WiFi").
#pragma once

#if defined(ARDUINO_UNOR4_WIFI) && __has_include("arduino_secrets.h")
#define RAV_WIFI 1
#include <WiFiS3.h>
#include "arduino_secrets.h"

#ifndef RAV_SNAPSHOT_MAX
#define RAV_SNAPSHOT_MAX 320
#endif
#ifndef RAV_SEND_EVERY_MS
#define RAV_SEND_EVERY_MS 500    // rav-server stops the next test step after 2 s without a snapshot
#endif
#ifndef RAV_LOG                  // how a WiFi status line goes out on Serial: an event, as these sketches send
#define RAV_LOG(what, v)                                                                                         \
  do {                                                                                                           \
    Serial.print(F("{\"t\":")); Serial.print(millis()); Serial.print(F(",\"ev\":\"wifi\",\"v\":\""));             \
    Serial.print(what); Serial.print(v); Serial.println(F("\"}"));                                               \
  } while (0)
#endif

namespace rav {
const uint16_t TIMEOUT_MS = 300;   // a slow reply mustn't hold up the buttons for long
const uint32_t REJOIN_MS = 10000;  // WiFi.begin blocks for a few seconds: don't retry it every loop

WiFiClient client;
char last[RAV_SNAPSHOT_MAX] = "";
uint32_t sentAt = 0, joinAt = 0;
int lastStatus = -1;

inline void join() {
  joinAt = millis();
  RAV_LOG("joining ", SECRET_SSID);
  WiFi.begin(SECRET_SSID, SECRET_PASS);
  if (WiFi.status() == WL_CONNECTED) RAV_LOG("joined ", WiFi.localIP());
}

inline void begin() { join(); }

// One request on the open connection (opened if needed). Returns the HTTP status, or 0 if the laptop didn't answer.
inline int postOnce(const char *body, size_t len) {
  if (!client.connected()) {
    client.stop();
    if (!client.connect(RAV_HOST, RAV_PORT)) return 0;
    client.setTimeout(TIMEOUT_MS);
  }
  client.print(F("POST /readout/" DEVICE_NAME " HTTP/1.1\r\nHost: " RAV_HOST "\r\nAuthorization: Bearer " DEVICE_KEY
                 "\r\nContent-Type: application/json\r\nConnection: keep-alive\r\nContent-Length: "));
  client.print(len);
  client.print(F("\r\n\r\n"));
  client.write((const uint8_t *)body, len);
  String line = client.readStringUntil('\n');  // "HTTP/1.1 204 No Content"
  if (line.length() < 12) { client.stop(); return 0; }
  int status = line.substring(9, 12).toInt();
  long length = 0;
  while (true) {  // the headers, then the body, so the next reply starts clean
    line = client.readStringUntil('\n');
    if (line.length() == 0) { client.stop(); return status; }  // timed out mid-reply: start fresh next time
    if (line == "\r") break;
    line.toLowerCase();
    if (line.startsWith("content-length:")) length = line.substring(15).toInt();
  }
  while (length-- > 0 && client.read() >= 0) {}
  return status;
}

// Call every loop with the current snapshot (a NUL-terminated flat JSON object).
inline void update(const char *body) {
  bool changed = strcmp(body, last) != 0;
  if (!changed && millis() - sentAt < RAV_SEND_EVERY_MS) return;
  if (WiFi.status() != WL_CONNECTED) {
    if (millis() - joinAt >= REJOIN_MS) join();
    return;
  }
  strncpy(last, body, sizeof(last) - 1);
  sentAt = millis();
  size_t len = strlen(body);
  int status = postOnce(body, len);
  if (status == 0) status = postOnce(body, len);  // the server closed the kept-open connection: once more, fresh
  if (status != lastStatus) {  // say it once, not every half second
    lastStatus = status;
    // 204 ok. 401 DEVICE_KEY isn't RAV_DEVICE_KEY. 404 rav-server has another --readout-device. 0 wrong RAV_HOST,
    // server not on --host 0.0.0.0, or the laptop's firewall
    RAV_LOG("post ", status);
  }
}
}  // namespace rav

#elif defined(ARDUINO_UNOR4_WIFI)
#warning "no arduino_secrets.h next to the sketch: WiFi readout off, USB serial only (copy arduino_secrets.h.example)"
#endif
