#pragma once
// Compile-only defaults. Provision the actual board in the private data directory.
constexpr bool CAMERA_CONFIGURED = false;
constexpr int CAM_PINS[16] = {-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1};
constexpr int RELAY_PIN = -1;
constexpr bool RELAY_ACTIVE_HIGH = false;
constexpr char WIFI_NAME[] = "", WIFI_PASS[] = "", BASE_URL[] = "", NTP_HOST[] = "";
constexpr char DEVICE_ID[] = "door-kit", DEVICE_KEY[] = "", TRUST_CA[] = "";
