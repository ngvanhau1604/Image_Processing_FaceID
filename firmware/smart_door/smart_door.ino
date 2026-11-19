#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <esp_camera.h>
#include <esp_random.h>
#include <esp_timer.h>
#include <mbedtls/md.h>
#include <driver/gpio.h>
#include <sys/time.h>
#if __has_include("private_config.h")
#include "private_config.h"
#else
#include "defaults.h"
#endif

struct Ticket { String request, nonce, binding; int64_t sent; };
const char* VERIFY = "/api/v1/access/verify";
const char* ACK = "/api/v1/access/ack";
constexpr int PULSE_MS = 2000;
static_assert(PULSE_MS > 0 && PULSE_MS < 5000, "LY-03 requires pulses shorter than five seconds");
String bootId;
uint8_t keyBytes[32];
esp_timer_handle_t cutOff = nullptr;
volatile uint32_t stoppedAt = 0;
volatile bool stopped = true;
portMUX_TYPE relayMux = portMUX_INITIALIZER_UNLOCKED;
bool ready = false;

String hexBytes(const uint8_t* bytes, size_t count) {
  static const char digits[] = "0123456789abcdef";
  String out;
  out.reserve(count * 2);
  for (size_t i = 0; i < count; ++i) { out += digits[bytes[i] >> 4]; out += digits[bytes[i] & 15]; }
  return out;
}

String randomId() {
  uint8_t bytes[16];
  esp_fill_random(bytes, sizeof(bytes));
  return hexBytes(bytes, sizeof(bytes));
}

int64_t utcMs() {
  timeval tv;
  gettimeofday(&tv, nullptr);
  return int64_t(tv.tv_sec)*1000 + tv.tv_usec/1000;
}

Ticket makeTicket() {
  Ticket t;
  t.request = randomId(); t.nonce = randomId(); t.sent = utcMs();
  t.binding = String(DEVICE_ID)+"\n"+bootId+"\n"+t.request+"\n"+t.nonce+"\n"+String(t.sent);
  return t;
}

String digest(const uint8_t* data, size_t len, bool keyed) {
  const auto* md = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  uint8_t out[32];
  int rc = keyed ? mbedtls_md_hmac(md,keyBytes,sizeof(keyBytes),data,len,out) : mbedtls_md(md,data,len,out);
  return rc == 0 ? hexBytes(out,sizeof(out)) : String();
}

String signText(const String& text) {
  return digest(reinterpret_cast<const uint8_t*>(text.c_str()), text.length(), true);
}

bool sameSignature(const String& a, const String& b) {
  if (a.length()!=64 || b.length()!=64) return false;
  uint8_t diff = 0;
  for (size_t i=0; i<64; ++i) diff |= a[i]^b[i];
  return diff==0;
}

bool post(const char* path, const Ticket& t, uint8_t* data, size_t len, String& reply) {
  WiFiClientSecure tls;
  tls.setCACert(TRUST_CA);
  HTTPClient http;
  http.setTimeout(4500); http.setConnectTimeout(2200);
  if (!http.begin(tls,String(BASE_URL)+path)) return false;
  String bodyHash = digest(data,len,false);
  if (bodyHash.isEmpty()) return false;
  String signature = signText(String("v1\n")+path+"\n"+t.binding+"\n"+bodyHash);
  if (signature.isEmpty()) return false;
  http.addHeader("Content-Type",strcmp(path,VERIFY)==0 ? "image/jpeg" : "text/plain");
  http.addHeader("X-Device",DEVICE_ID); http.addHeader("X-Boot",bootId);
  http.addHeader("X-Request",t.request); http.addHeader("X-Nonce",t.nonce);
  http.addHeader("X-Sent",String(t.sent)); http.addHeader("X-Signature",signature);
  int status=http.POST(data,len);
  bool ok=status==200 && http.getSize()>0 && http.getSize()<512;
  if (ok) reply=http.getString();
  http.end();
  return ok;
}

bool grantValid(const String& reply, const Ticket& t, uint32_t started) {
  String fields[5];
  int pos=0;
  for (int i=0;i<4;++i) {
    int sep=reply.indexOf('\n',pos);
    if (sep<pos) return false;
    fields[i]=reply.substring(pos,sep); pos=sep+1;
  }
  fields[4]=reply.substring(pos);
  if (fields[0]!="GRANTED" || fields[3]!="2000" || fields[2].length()!=13) return false;
  for (char c : fields[2]) if (c<'0'||c>'9') return false;
  int64_t expires=strtoll(fields[2].c_str(),nullptr,10);
  String expected=signText("reply\n"+t.binding+"\n"+reply.substring(0,pos-1));
  return sameSignature(fields[4],expected) && utcMs()<=expires && expires<=t.sent+6500 && millis()-started<=6500;
}

void turnOff(void*) {
  portENTER_CRITICAL(&relayMux);
  if (RELAY_PIN>=0) gpio_set_level(static_cast<gpio_num_t>(RELAY_PIN),!RELAY_ACTIVE_HIGH);
  stoppedAt=millis();
  stopped=true;
  portEXIT_CRITICAL(&relayMux);
}

void acknowledge(const String& target,const char* state,uint32_t elapsed) {
  String body=target+"\n"+state+"\n"+String(elapsed), reply;
  for (int i=0;i<2 && WiFi.status()==WL_CONNECTED;++i) {
    if (post(ACK,makeTicket(),reinterpret_cast<uint8_t*>(body.begin()),body.length(),reply)) break;
  }
}

void pulse(const String& target) {
  if (RELAY_PIN<0 || !cutOff || !stopped) return;
  uint32_t began=millis();
  stopped=false;
  if (esp_timer_start_once(cutOff,PULSE_MS*1000ULL)!=ESP_OK) { turnOff(nullptr); return; }
  portENTER_CRITICAL(&relayMux);
  bool energized = !stopped && millis()-began < PULSE_MS;
  if (energized) gpio_set_level(static_cast<gpio_num_t>(RELAY_PIN),RELAY_ACTIVE_HIGH);
  portEXIT_CRITICAL(&relayMux);
  if (!energized) return;
  acknowledge(target,"started",0);
  while (!stopped) delay(1);
  uint32_t elapsed=stoppedAt-began;
  Serial.printf("request=%s pulse_ms=%lu\n",target.c_str(),(unsigned long)elapsed);
  acknowledge(target,"stopped",elapsed);
}

bool initCamera() {
  if (!CAMERA_CONFIGURED || !psramFound()) return false;
  camera_config_t c={};
  c.pin_d0=CAM_PINS[0]; c.pin_d1=CAM_PINS[1]; c.pin_d2=CAM_PINS[2]; c.pin_d3=CAM_PINS[3];
  c.pin_d4=CAM_PINS[4]; c.pin_d5=CAM_PINS[5]; c.pin_d6=CAM_PINS[6]; c.pin_d7=CAM_PINS[7];
  c.pin_xclk=CAM_PINS[8]; c.pin_pclk=CAM_PINS[9]; c.pin_vsync=CAM_PINS[10]; c.pin_href=CAM_PINS[11];
  c.pin_sccb_sda=CAM_PINS[12]; c.pin_sccb_scl=CAM_PINS[13]; c.pin_pwdn=CAM_PINS[14]; c.pin_reset=CAM_PINS[15];
  c.ledc_timer=LEDC_TIMER_0; c.ledc_channel=LEDC_CHANNEL_0; c.xclk_freq_hz=20000000;
  c.pixel_format=PIXFORMAT_JPEG; c.frame_size=FRAMESIZE_VGA; c.jpeg_quality=12;
  c.fb_count=1; c.fb_location=CAMERA_FB_IN_PSRAM; c.grab_mode=CAMERA_GRAB_WHEN_EMPTY;
  if (esp_camera_init(&c)!=ESP_OK) return false;
  auto* sensor=esp_camera_sensor_get();
  return sensor && sensor->id.PID==OV3660_PID;
}

void setup() {
  if (RELAY_PIN>=0) {
    gpio_set_level(static_cast<gpio_num_t>(RELAY_PIN),!RELAY_ACTIVE_HIGH);
    gpio_set_direction(static_cast<gpio_num_t>(RELAY_PIN),GPIO_MODE_OUTPUT);
  }
  Serial.begin(115200);
  if (!initCamera()) { Serial.println("Camera idle: check verified OV3660 DVP map and OPI PSRAM."); return; }
  Serial.println("OV3660 ready");
  if (strlen(DEVICE_KEY)!=64 || !String(BASE_URL).startsWith("https://") || !strlen(TRUST_CA)) return;
  for (int i=0;i<32;++i) {
    char pair[3]={DEVICE_KEY[i*2],DEVICE_KEY[i*2+1],0};
    if (!isxdigit(pair[0]) || !isxdigit(pair[1])) return;
    keyBytes[i]=strtoul(pair,nullptr,16);
  }
  esp_timer_create_args_t args={}; args.callback=turnOff; args.name="relay_off";
  if (esp_timer_create(&args,&cutOff)!=ESP_OK) return;
  WiFi.mode(WIFI_STA); WiFi.setAutoReconnect(true); WiFi.begin(WIFI_NAME,WIFI_PASS);
  configTime(0,0,NTP_HOST);
  ready=true;
}

void loop() {
  if (!ready || WiFi.status()!=WL_CONNECTED || utcMs()<1700000000000LL) { delay(500); return; }
  if (bootId.isEmpty()) bootId=randomId();
  uint32_t started=millis();
  auto* frame=esp_camera_fb_get();
  if (!frame) { delay(500); return; }
  Ticket pending=makeTicket();
  String reply;
  bool ok=frame->format==PIXFORMAT_JPEG && post(VERIFY,pending,frame->buf,frame->len,reply);
  esp_camera_fb_return(frame);
  bool grant=ok && grantValid(reply,pending,started);
  Serial.printf("request=%s response=%s latency_ms=%lu\n",pending.request.c_str(),ok?"received":"unavailable",(unsigned long)(millis()-started));
  if (grant) pulse(pending.request);
  delay(600);
}
