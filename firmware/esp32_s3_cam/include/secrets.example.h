#pragma once
// Copy to secrets.h and fill with your own credentials. Do not commit secrets.h.
#define IOT_WIFI_SSID "YOUR_WIFI_SSID"
#define IOT_WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
#define IOT_SERVER_URL "https://your-laptop.local:8443/iot/door/capture"
#define IOT_DEVICE_ID "door-demo-01"
#define IOT_HMAC_SECRET "REPLACE_WITH_A_RANDOM_64_HEX_CHARACTER_SECRET"
#define IOT_TLS_ROOT_CA R"PEM(
-----BEGIN CERTIFICATE-----
REPLACE_WITH_VALID_CA_PEM_MATCHING_THE_SERVER_CERTIFICATE
-----END CERTIFICATE-----
)PEM"
