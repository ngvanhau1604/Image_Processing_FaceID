# Keyestudio MB0184 ESP32-S3-CAM + OV3660

This is a **hardware-unverified demonstration sketch**, not a tested access
controller. The 12V LY-03 solenoid must NEVER be connected directly to a GPIO.

1. In this directory, copy include/secrets.example.h to include/secrets.h.
2. Copy include/hardware_config.example.h to include/hardware_config.h.
3. Supply the actual Wi-Fi network, HTTPS backend URL, CA certificate and
   32+ character HMAC secret (the same as laptop .env).
4. Verify Keyestudio pinout and the exact relay board first; choose a GPIO
   exposed at the header, not occupied by camera, SD, USB or boot functions.
   Set IOT_RELAY_GPIO and IOT_RELAY_ACTIVE_HIGH after electrical checks.
   By default the build intentionally fails with GPIO=-1.
5. With PlatformIO, build environment keyestudio-mb0184 and flash only after
   verifying boot-state output with LED/dummy load and power isolation.
6. Do not expose the FastAPI endpoint to the public Internet. Avoid insecure
   TLS; the URL hostname must match a certificate signed by IOT_TLS_ROOT_CA.
   Accurate device time is required (SNTP); no clock sync -> no unlock.

The official Keyestudio MB0184 camera pin assignment is used for OV3660.
ESP32 powers via USB-C 5V; 12V adapter powers LY-03 through a suitable driver,
with flyback suppression and appropriate wiring. Physical actuation remains
pending until its relay module, pin and power measurement are confirmed.
