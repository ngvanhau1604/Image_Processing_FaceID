#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <esp_camera.h>
#include <mbedtls/md.h>
#include <time.h>

#include "hardware_config.h"
#include "secrets.h"

// Do not guess relay GPIO from generic ESP32-S3 examples.
#if IOT_RELAY_GPIO < 0
#error "Choose IOT_RELAY_GPIO only after checking the MB0184 header and relay."
#endif
#if IOT_RELAY_GPIO == 4 || IOT_RELAY_GPIO == 5 || IOT_RELAY_GPIO == 6 || \
    IOT_RELAY_GPIO == 7 || IOT_RELAY_GPIO == 8 || IOT_RELAY_GPIO == 9 || \
    IOT_RELAY_GPIO == 10 || IOT_RELAY_GPIO == 11 || IOT_RELAY_GPIO == 12 || \
    IOT_RELAY_GPIO == 13 || IOT_RELAY_GPIO == 15 || IOT_RELAY_GPIO == 16 || \
    IOT_RELAY_GPIO == 17 || IOT_RELAY_GPIO == 18 || IOT_RELAY_GPIO == 38 || \
    IOT_RELAY_GPIO == 39 || IOT_RELAY_GPIO == 40
#error "Relay GPIO conflicts with camera/SD pinout."
#endif
#if IOT_RELAY_ACTIVE_HIGH != 0 && IOT_RELAY_ACTIVE_HIGH != 1
#error "Relay active level must be checked and set to 0 or 1."
#endif

constexpr uint32_t kMaxUnlockMs = 2000;
constexpr uint32_t kCapturePeriodMs = 1800;

void relayOff() {
  digitalWrite(IOT_RELAY_GPIO, IOT_RELAY_ACTIVE_HIGH ? LOW : HIGH);
}

void unlockPulse(uint32_t ms) {
  if (ms == 0 || ms > kMaxUnlockMs) return;
  digitalWrite(IOT_RELAY_GPIO, IOT_RELAY_ACTIVE_HIGH ? HIGH : LOW);
  delay(ms);
  relayOff();
}

String hexEncode(const uint8_t* data, size_t length) {
  const char alphabet[] = "0123456789abcdef";
  String out;
  out.reserve(length * 2);
  for (size_t i = 0; i < length; i++) {
    out += alphabet[data[i] >> 4];
    out += alphabet[data[i] & 15];
  }
  return out;
}

String sha256Hex(const uint8_t* data, size_t length) {
  uint8_t digest[32];
  const auto* type = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  if (!type || mbedtls_md(type, data, length, digest) != 0) return "";
  return hexEncode(digest, sizeof(digest));
}

String hmacHex(const String& message) {
  uint8_t digest[32];
  const auto* type = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  if (!type || mbedtls_md_hmac(
      type, reinterpret_cast<const uint8_t*>(IOT_HMAC_SECRET),
      strlen(IOT_HMAC_SECRET),
      reinterpret_cast<const uint8_t*>(message.c_str()),
      message.length(), digest) != 0) return "";
  return hexEncode(digest, sizeof(digest));
}

bool secureEqualHex(const String& a, const String& b) {
  if (a.length() != 64 || b.length() != 64) return false;
  uint8_t difference = 0;
  for (size_t i = 0; i < 64; ++i) difference |= static_cast<uint8_t>(a[i] ^ b[i]);
  return difference == 0;
}

String newNonce() {
  uint8_t bytes[16];
  esp_fill_random(bytes, sizeof(bytes));
  return hexEncode(bytes, sizeof(bytes));
}

bool initCamera() {
  camera_config_t cfg = {};
  // Camera wiring from official Keyestudio MB0184 OV3660 pinout.
  cfg.pin_d0 = 11; cfg.pin_d1 = 9; cfg.pin_d2 = 8; cfg.pin_d3 = 10;
  cfg.pin_d4 = 12; cfg.pin_d5 = 18; cfg.pin_d6 = 17; cfg.pin_d7 = 16;
  cfg.pin_xclk = 15; cfg.pin_pclk = 13; cfg.pin_vsync = 6; cfg.pin_href = 7;
  cfg.pin_sccb_sda = 4; cfg.pin_sccb_scl = 5;
  cfg.pin_pwdn = -1; cfg.pin_reset = -1;
  cfg.ledc_channel = LEDC_CHANNEL_0;
  cfg.ledc_timer = LEDC_TIMER_0;
  cfg.xclk_freq_hz = 20000000;
  cfg.pixel_format = PIXFORMAT_JPEG;
  cfg.frame_size = FRAMESIZE_VGA;
  cfg.jpeg_quality = 12;
  cfg.fb_count = 1;
  cfg.fb_location = CAMERA_FB_IN_PSRAM;
  return esp_camera_init(&cfg) == ESP_OK;
}

void sendCameraFrame() {
  relayOff();
  if (WiFi.status() != WL_CONNECTED || time(nullptr) < 1700000000) return;
  camera_fb_t* frame = esp_camera_fb_get();
  if (!frame) return;

  const String timestamp = String(static_cast<unsigned long>(time(nullptr)));
  const String nonce = newNonce();
  const String sha = sha256Hex(frame->buf, frame->len);
  const String signedFields = String(IOT_DEVICE_ID) + "\n" + timestamp +
                              "\n" + nonce + "\n" + sha;
  const String signature = hmacHex(signedFields);
  if (sha.isEmpty() || signature.isEmpty()) {
    esp_camera_fb_return(frame);
    return;
  }

  WiFiClientSecure tls;
  tls.setCACert(IOT_TLS_ROOT_CA);
  HTTPClient http;
  if (!http.begin(tls, IOT_SERVER_URL)) {
    esp_camera_fb_return(frame);
    return;
  }
  http.setTimeout(8000);
  const char* responseHeaderNames[] = {"X-Door-Response-Signature"};
  http.collectHeaders(responseHeaderNames, 1);
  http.addHeader("Content-Type", "image/jpeg");
  http.addHeader("X-Device-ID", IOT_DEVICE_ID);
  http.addHeader("X-Timestamp", timestamp);
  http.addHeader("X-Nonce", nonce);
  http.addHeader("X-Signature", signature);

  const int status = http.POST(frame->buf, frame->len);
  esp_camera_fb_return(frame);
  if (status != HTTP_CODE_OK) {
    http.end();
    return;
  }
  const String body = http.getString();
  const String responseSignature = http.header("X-Door-Response-Signature");
  http.end();
  if (!secureEqualHex(responseSignature, hmacHex(body))) return;

  JsonDocument decoded;
  if (deserializeJson(decoded, body)) return;
  if (decoded["request_nonce"].as<String>() != nonce) return;
  const long now = static_cast<long>(time(nullptr));
  const long validUntil = decoded["valid_until"] | 0L;
  if (validUntil < now || validUntil > now + 5) return;
  if (decoded["decision"].as<String>() != "unlock") return;
  const uint32_t pulse = decoded["unlock_ms"] | 0U;
  unlockPulse(pulse);
}

void setup() {
  // A hardware pull resistor is required to keep the relay OFF during boot.
  relayOff(); // Set output latch before enabling output.
  pinMode(IOT_RELAY_GPIO, OUTPUT);
  relayOff();
  Serial.begin(115200);
  if (strlen(IOT_HMAC_SECRET) < 32 || strlen(IOT_TLS_ROOT_CA) < 100 ||
      String(IOT_SERVER_URL).indexOf("https://") != 0) {
    Serial.println("Invalid HMAC secret or TLS settings: locked.");
    return;
  }
  if (!initCamera()) {
    Serial.println("Camera init failed: locked.");
    return;
  }
  WiFi.mode(WIFI_STA);
  WiFi.begin(IOT_WIFI_SSID, IOT_WIFI_PASSWORD);
  configTime(0, 0, "pool.ntp.org", "time.google.com");
}

void loop() {
  static uint32_t lastCaptureMs = 0;
  if (millis() - lastCaptureMs >= kCapturePeriodMs) {
    lastCaptureMs = millis();
    sendCameraFrame();
  }
  delay(100);
}
