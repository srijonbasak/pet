#include <SPI.h>
#include <ST7789_ESP32C3.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <Preferences.h>
#include <SPIFFS.h>
#include <math.h>

const uint16_t UDP_PORT = 4210;
// Original sample wiring: battery through a 2:1 divider to GPIO1 (ADC1).
const int BAT_PIN = 1;

const char *SERVICE_UUID = "4fafc201-1fb5-459e-8fcc-c5c9c331914b";
const char *CHAR_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8";

ST7789_ESP32C3 tft;
ST7789_Sprite canvas(&tft);
WiFiUDP udp;
Preferences settingsStore;

struct DisplaySettings {
  int mode = 0;          // 0: alternate, 1: animation, 2: usage
  int animation = 0;     // 0: full sequence, 1: standing, 2: laptop
  int animationSeconds = 11;
  int usageSeconds = 7;
  int widgets = 7;       // context, five-hour, weekly
  uint32_t background = 0xFFFFFF;
  uint32_t accent = 0x6EA0FF;
} displaySettings;
String serialInput;
bool serialOverflow = false;
unsigned long screenCycleStart = 0;
uint16_t configuredAccent;

uint16_t rgb565(uint32_t rgb) {
  return tft.color565((rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255);
}

#define BG       TFT_BLACK
#define PANEL    tft.color565(16, 22, 36)
#define TRACK    tft.color565(48, 65, 92)
#define MUTED    tft.color565(115, 143, 185)
#define CODEX    configuredAccent
#define CODEX_HI tft.color565(150, 220, 255)
#define FACE     tft.color565(5, 9, 18)
#define PET_FACE tft.color565(110, 190, 255)

struct Usage {
  String project = "Waiting for Codex";
  String chat = "No live update";
  int context = -1;
  long used = 0;
  long maximum = 0;
  int fiveHour = -1;
  String fiveReset = "--";
  int weekly = -1;
  String weekReset = "--";
} usage;

String incoming;
unsigned long lastPacket = 0;
unsigned long lastFrame = 0;
bool usageScreen = false;
void acceptPacket(String line);
void sceneCommand(const String &line);
bool drawScene(char page);
File sceneUpload;
size_t sceneExpected = 0, sceneReceived = 0;
uint32_t sceneHash = 2166136261UL, sceneExpectedHash = 0;
bool sceneReady = false;
bool batteryEnabled = false;
int batteryPercent = -1;
unsigned long lastBatteryCheck = 0, lastWifiCheck = 0;
bool wifiOnline = false;
bool wifiPending = false;
unsigned long wifiAttemptAt = 0;
bool wifiScanPending = false;
bool wifiResumeAfterScan = false;

void resumeWifiAfterScan() {
  if (!wifiResumeAfterScan) return;
  wifiResumeAfterScan = false;
  String ssid = settingsStore.getString("wifiSsid", "");
  if (!ssid.length()) return;
  String password = settingsStore.getString("wifiPass", "");
  WiFi.begin(ssid.c_str(), password.c_str());
  wifiPending = true;
  wifiAttemptAt = millis();
}

bool decodeHex(const String &hex, String &out) {
  if (hex.length() % 2) return false;
  out = "";
  for (unsigned int i = 0; i < hex.length(); i += 2) {
    char pair[] = {hex[i], hex[i + 1], 0}; char *end;
    long c = strtol(pair, &end, 16);
    if (*end || c == 0) return false;
    out += (char)c;
  }
  return true;
}

void sendWifiStatus() {
  if (WiFi.status() == WL_CONNECTED) Serial.println("WIFI|CONNECTED|" + WiFi.localIP().toString());
  else Serial.println("WIFI|DISCONNECTED");
}

String fieldAt(const String &line, int wanted) {
  int start = 0;
  for (int field = 0; field <= wanted; field++) {
    int end = line.indexOf('|', start);
    if (field == wanted) return line.substring(start, end < 0 ? line.length() : end);
    if (end < 0) return "";
    start = end + 1;
  }
  return "";
}

void loadDisplaySettings() {
  settingsStore.begin("codex-display", false);
  displaySettings.mode = constrain(settingsStore.getInt("mode", 0), 0, 2);
  displaySettings.animation = constrain(settingsStore.getInt("animation", 0), 0, 2);
  displaySettings.animationSeconds = constrain(settingsStore.getInt("animSecs", 11), 2, 60);
  displaySettings.usageSeconds = constrain(settingsStore.getInt("usageSecs", 7), 2, 60);
  displaySettings.widgets = constrain(settingsStore.getInt("widgets", 7), 1, 7);
  displaySettings.background = settingsStore.getUInt("background", 0xFFFFFF) & 0xFFFFFF;
  displaySettings.accent = settingsStore.getUInt("accent", 0x6EA0FF) & 0xFFFFFF;
  configuredAccent = rgb565(displaySettings.accent);
  batteryEnabled = settingsStore.getBool("battery", false);
}

bool parseNumber(const String &value, long minimum, long maximum, long &result, int base = 10) {
  if (!value.length()) return false;
  char *end = nullptr;
  result = strtol(value.c_str(), &end, base);
  return end && *end == '\0' && result >= minimum && result <= maximum;
}

void sendDisplaySettings() {
  char response[96];
  snprintf(response, sizeof(response), "SET|%d|%d|%d|%d|%d|%06lX|%06lX",
    displaySettings.mode, displaySettings.animation, displaySettings.animationSeconds,
    displaySettings.usageSeconds, displaySettings.widgets,
    (unsigned long)displaySettings.background, (unsigned long)displaySettings.accent);
  Serial.println(response);
}

void handleSerialCommand(String line) {
  line.trim();
  if (line == "HELLO|1") { Serial.println("READY|1"); Serial.println("ENGINE|4"); sendDisplaySettings(); sendWifiStatus(); Serial.printf("BATTERY|%d\n", batteryPercent); return; }
  if (line == "GET|1") { sendDisplaySettings(); return; }
  if (line == "WIFI|GET") { sendWifiStatus(); return; }
  if (line == "WIFI|SCAN") {
    if (wifiScanPending) { Serial.println("SCAN|START"); return; }
    // ESP-IDF can reject a scan while an association attempt is in progress.
    // Pause that attempt only while disconnected, then resume it afterwards.
    if (wifiPending && WiFi.status() != WL_CONNECTED) {
      wifiResumeAfterScan = true;
      wifiPending = false;
      WiFi.disconnect(false, false);
    }
    WiFi.scanDelete();
    int result = WiFi.scanNetworks(true, false, false, 300);
    if (result == WIFI_SCAN_FAILED) { resumeWifiAfterScan(); Serial.println("SCAN|FAILED"); }
    else { wifiScanPending = true; Serial.println("SCAN|START"); }
    return;
  }
  if (line.startsWith("WIFI|SET|")) {
    String ssid, password;
    if (!decodeHex(fieldAt(line, 2), ssid) || !decodeHex(fieldAt(line, 3), password) ||
        ssid.length() < 1 || ssid.length() > 32 || password.length() > 63 ||
        (password.length() > 0 && password.length() < 8)) { Serial.println("ERR|wifi-input"); return; }
    bool saved = settingsStore.putString("wifiSsid", ssid) > 0;
    saved &= settingsStore.putString("wifiPass", password) > 0 || password.length() == 0;
    if (!saved) { Serial.println("ERR|wifi-save"); return; }
    WiFi.disconnect();
    WiFi.begin(ssid.c_str(), password.c_str());
    wifiPending = true; wifiAttemptAt = millis();
    Serial.println("WIFI|CONNECTING");
    return;
  }
  if (line == "BAT|1" || line == "BAT|0") {
    batteryEnabled = line == "BAT|1";
    if (!settingsStore.putBool("battery", batteryEnabled)) { Serial.println("ERR|battery-save"); return; }
    batteryPercent = -1; lastBatteryCheck = 0;
    Serial.println(batteryEnabled ? "ACK|BAT|1" : "ACK|BAT|0");
    if (!batteryEnabled) Serial.println("BATTERY|-1");
    return;
  }
  if (line.startsWith("SCN|")) { sceneCommand(line); return; }
  if (line.startsWith("CD2|")) { acceptPacket(line); return; }
  if (!line.startsWith("CFG|1|")) { Serial.println("ERR|command"); return; }
  long values[7];
  if (!parseNumber(fieldAt(line, 2), 0, 2, values[0]) ||
      !parseNumber(fieldAt(line, 3), 0, 2, values[1]) ||
      !parseNumber(fieldAt(line, 4), 2, 60, values[2]) ||
      !parseNumber(fieldAt(line, 5), 2, 60, values[3]) ||
      !parseNumber(fieldAt(line, 6), 1, 7, values[4]) ||
      fieldAt(line, 7).length() != 6 || fieldAt(line, 8).length() != 6 ||
      !parseNumber(fieldAt(line, 7), 0, 0xFFFFFF, values[5], 16) ||
      !parseNumber(fieldAt(line, 8), 0, 0xFFFFFF, values[6], 16) ||
      fieldAt(line, 9).length()) { Serial.println("ERR|config"); return; }
  displaySettings.mode = values[0]; displaySettings.animation = values[1];
  displaySettings.animationSeconds = values[2]; displaySettings.usageSeconds = values[3];
  displaySettings.widgets = values[4]; displaySettings.background = values[5];
  displaySettings.accent = values[6]; configuredAccent = rgb565(displaySettings.accent);
  bool saved = settingsStore.putInt("mode", displaySettings.mode) > 0;
  saved &= settingsStore.putInt("animation", displaySettings.animation) > 0;
  saved &= settingsStore.putInt("animSecs", displaySettings.animationSeconds) > 0;
  saved &= settingsStore.putInt("usageSecs", displaySettings.usageSeconds) > 0;
  saved &= settingsStore.putInt("widgets", displaySettings.widgets) > 0;
  saved &= settingsStore.putUInt("background", displaySettings.background) > 0;
  saved &= settingsStore.putUInt("accent", displaySettings.accent) > 0;
  screenCycleStart = millis();
  if (!saved) { Serial.println("ERR|save"); return; }
  Serial.println("ACK|CFG|1");
  sendDisplaySettings();
}

void pollSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      if (serialOverflow) Serial.println("ERR|length");
      else if (serialInput.length()) handleSerialCommand(serialInput);
      serialInput = ""; serialOverflow = false;
    } else if (!serialOverflow && c != '\r') {
      if (serialInput.length() < 220) serialInput += c;
      else { serialInput = ""; serialOverflow = true; }
    }
  }
}

void sceneCommand(const String &line) {
  String action = fieldAt(line, 1);
  if (action == "INIT") {
    if (sceneReady) { Serial.println("ACK|SCN|INIT"); return; }
    if (!SPIFFS.format() || !SPIFFS.begin(false)) { Serial.println("ERR|scene-storage"); return; }
    sceneReady = true;
    Serial.println("ACK|SCN|INIT");
  } else if (action == "BEGIN") {
    long size, hash;
    if (!sceneReady || !parseNumber(fieldAt(line, 2), 1, 60000, size) ||
        fieldAt(line, 3).length() != 8) { Serial.println("ERR|scene-begin"); return; }
    char *end = nullptr;
    String hashText = fieldAt(line, 3);
    unsigned long parsed = strtoul(hashText.c_str(), &end, 16);
    if (!end || *end) { Serial.println("ERR|scene-hash"); return; }
    hash = parsed;
    if (sceneUpload) sceneUpload.close();
    sceneUpload = SPIFFS.open("/scene.tmp", FILE_WRITE);
    if (!sceneUpload) { Serial.println("ERR|scene-storage"); return; }
    sceneExpected = size; sceneReceived = 0; sceneHash = 2166136261UL;
    sceneExpectedHash = (uint32_t)hash;
    Serial.println("ACK|SCN|0");
  } else if (action == "DATA") {
    long offset;
    String hex = fieldAt(line, 3);
    if (!sceneUpload || !parseNumber(fieldAt(line, 2), 0, 60000, offset) ||
        offset != (long)sceneReceived || hex.length() == 0 || hex.length() > 160 ||
        hex.length() % 2 || sceneReceived + hex.length() / 2 > sceneExpected) {
      Serial.println("ERR|scene-data"); return;
    }
    uint8_t bytes[80];
    for (unsigned int i = 0; i < hex.length(); i += 2) {
      char pair[] = {hex[i], hex[i + 1], 0}; char *end;
      long value = strtol(pair, &end, 16);
      if (*end) { Serial.println("ERR|scene-hex"); return; }
      bytes[i / 2] = value;
    }
    size_t length = hex.length() / 2;
    if (sceneUpload.write(bytes, length) != length) { Serial.println("ERR|scene-write"); return; }
    for (size_t i = 0; i < length; i++) { sceneHash ^= bytes[i]; sceneHash *= 16777619UL; }
    sceneReceived += length;
    Serial.printf("ACK|SCN|%u\n", (unsigned int)sceneReceived);
  } else if (action == "END") {
    if (!sceneUpload || sceneReceived != sceneExpected || sceneHash != sceneExpectedHash) {
      if (sceneUpload) sceneUpload.close();
      Serial.println("ERR|scene-checksum"); return;
    }
    sceneUpload.close();
    SPIFFS.remove("/scene.old");
    bool hadOld = SPIFFS.exists("/scene.txt");
    if (hadOld && !SPIFFS.rename("/scene.txt", "/scene.old")) { Serial.println("ERR|scene-commit"); return; }
    if (!SPIFFS.rename("/scene.tmp", "/scene.txt")) {
      if (hadOld) SPIFFS.rename("/scene.old", "/scene.txt");
      Serial.println("ERR|scene-commit"); return;
    }
    SPIFFS.remove("/scene.old");
    screenCycleStart = millis();
    Serial.println("ACK|SCN|DONE");
  } else if (action == "ABORT") {
    if (sceneUpload) sceneUpload.close();
    SPIFFS.remove("/scene.tmp");
    Serial.println("ACK|SCN|ABORT");
  } else Serial.println("ERR|scene-command");
}

void acceptPacket(String line) {
  line.trim();
  if (!line.startsWith("CD2|")) return;
  usage.project = fieldAt(line, 1);
  usage.chat = fieldAt(line, 2);
  usage.context = fieldAt(line, 3) == "--" ? -1 : fieldAt(line, 3).toInt();
  usage.used = fieldAt(line, 4).toInt();
  usage.maximum = fieldAt(line, 5).toInt();
  usage.fiveHour = fieldAt(line, 6) == "--" ? -1 : fieldAt(line, 6).toInt();
  usage.fiveReset = fieldAt(line, 7);
  usage.weekly = fieldAt(line, 8) == "--" ? -1 : fieldAt(line, 8).toInt();
  usage.weekReset = fieldAt(line, 9);
  lastPacket = millis();
}

class Receiver : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *characteristic) override {
    std::string chunk = characteristic->getValue();
    for (char value : chunk) {
      if (value == '\n') { acceptPacket(incoming); incoming = ""; }
      else if (incoming.length() < 220) incoming += value;
    }
  }
};

void startBluetooth() {
  BLEDevice::init("CodexDisplay");
  BLEServer *server = BLEDevice::createServer();
  BLEService *service = server->createService(SERVICE_UUID);
  BLECharacteristic *characteristic = service->createCharacteristic(
    CHAR_UUID, BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR
  );
  characteristic->setCallbacks(new Receiver());
  service->start();
  BLEAdvertising *advertising = BLEDevice::getAdvertising();
  advertising->addServiceUUID(SERVICE_UUID);
  advertising->start();
}

void startWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(true);
  WiFi.persistent(false);
  String ssid = settingsStore.getString("wifiSsid", "");
  if (ssid.length()) {
    String password = settingsStore.getString("wifiPass", "");
    WiFi.begin(ssid.c_str(), password.c_str());
    wifiPending = true; wifiAttemptAt = millis();
  }
}

void updateWifi(unsigned long now) {
  if (wifiScanPending) {
    int count = WiFi.scanComplete();
    if (count >= 0) {
      for (int i = 0; i < min(count, 30); i++) {
        String ssid = WiFi.SSID(i);
        if (!ssid.length()) continue;
        Serial.print("SCAN|ITEM|");
        for (unsigned int j = 0; j < ssid.length(); j++) Serial.printf("%02X", (uint8_t)ssid[j]);
        Serial.printf("|%d|%d\n", WiFi.RSSI(i), WiFi.encryptionType(i) == WIFI_AUTH_OPEN ? 1 : 0);
      }
      WiFi.scanDelete(); wifiScanPending = false; resumeWifiAfterScan(); Serial.println("SCAN|DONE");
    } else if (count == WIFI_SCAN_FAILED) {
      WiFi.scanDelete(); wifiScanPending = false; resumeWifiAfterScan(); Serial.println("SCAN|FAILED");
    }
  }
  if (now - lastWifiCheck < 2000) return;
  lastWifiCheck = now;
  bool online = WiFi.status() == WL_CONNECTED;
  if (online) wifiPending = false;
  else if (wifiPending && now - wifiAttemptAt >= 20000) {
    wifiPending = false;
    Serial.println("WIFI|FAILED");
  }
  if (online != wifiOnline) {
    wifiOnline = online;
    if (online) udp.begin(UDP_PORT); else udp.stop();
    sendWifiStatus();
  }
}

void updateBattery(unsigned long now) {
  if (!batteryEnabled || (lastBatteryCheck && now - lastBatteryCheck < 10000)) return;
  lastBatteryCheck = now;
  uint32_t sum = 0;
  for (int i = 0; i < 8; i++) sum += analogReadMilliVolts(BAT_PIN);
  long batteryMv = (sum / 8) * 2L;
  batteryPercent = batteryMv >= 2800 && batteryMv <= 4400
      ? constrain(map(batteryMv, 3300, 4200, 0, 100), 0, 100) : -1;
  Serial.printf("BATTERY|%d\n", batteryPercent);
}

void pollWifi() {
  int size = udp.parsePacket();
  if (!size) return;
  char packet[256];
  int count = udp.read(packet, sizeof(packet) - 1);
  if (count > 0) { packet[count] = 0; acceptPacket(String(packet)); }
}

void textFit(String value, int x, int y, int maxChars, uint16_t color, int size = 1) {
  if (value.length() > maxChars) value = value.substring(0, maxChars - 1) + "~";
  canvas.setTextColor(color, BG);
  canvas.setTextSize(size);
  canvas.setCursor(x, y);
  canvas.print(value);
}

// ST7789_ESP32C3's sprite class exposes only a small drawing API. These tiny
// helpers keep the animation compatible without pulling in another library.
void spriteLine(int x0, int y0, int x1, int y1, uint16_t color) {
  int dx = abs(x1 - x0), sx = x0 < x1 ? 1 : -1;
  int dy = -abs(y1 - y0), sy = y0 < y1 ? 1 : -1;
  int error = dx + dy;
  while (true) {
    canvas.drawPixel(x0, y0, color);
    if (x0 == x1 && y0 == y1) break;
    int twice = 2 * error;
    if (twice >= dy) { error += dy; x0 += sx; }
    if (twice <= dx) { error += dx; y0 += sy; }
  }
}

void spriteFillPanel(int x, int y, int width, int height, int radius, uint16_t color) {
  // Chamfered corners look crisp at this resolution and need only 3 rectangles.
  radius = constrain(radius, 0, min(width, height) / 2);
  canvas.fillRect(x + radius, y, width - 2 * radius, height, color);
  canvas.fillRect(x, y + radius, radius, height - 2 * radius, color);
  canvas.fillRect(x + width - radius, y + radius, radius, height - 2 * radius, color);
}

void spritePanelOutline(int x, int y, int width, int height, int radius, uint16_t color) {
  spriteLine(x + radius, y, x + width - radius - 1, y, color);
  spriteLine(x + radius, y + height - 1, x + width - radius - 1, y + height - 1, color);
  spriteLine(x, y + radius, x, y + height - radius - 1, color);
  spriteLine(x + width - 1, y + radius, x + width - 1, y + height - radius - 1, color);
  spriteLine(x, y + radius, x + radius, y, color);
  spriteLine(x + width - radius - 1, y, x + width - 1, y + radius, color);
  spriteLine(x, y + height - radius - 1, x + radius, y + height - 1, color);
  spriteLine(x + width - radius - 1, y + height - 1, x + width - 1, y + height - radius - 1, color);
}

void spriteFillTriangle(int x0, int y0, int x1, int y1, int x2, int y2, uint16_t color) {
  int minX = min(x0, min(x1, x2)), maxX = max(x0, max(x1, x2));
  int minY = min(y0, min(y1, y2)), maxY = max(y0, max(y1, y2));
  long area = (long)(x1 - x0) * (y2 - y0) - (long)(y1 - y0) * (x2 - x0);
  for (int y = minY; y <= maxY; y++) {
    for (int x = minX; x <= maxX; x++) {
      long a = (long)(x1 - x0) * (y - y0) - (long)(y1 - y0) * (x - x0);
      long b = (long)(x2 - x1) * (y - y1) - (long)(y2 - y1) * (x - x1);
      long c = (long)(x0 - x2) * (y - y2) - (long)(y0 - y2) * (x - x2);
      if ((area >= 0 && a >= 0 && b >= 0 && c >= 0) ||
          (area < 0 && a <= 0 && b <= 0 && c <= 0)) canvas.drawPixel(x, y, color);
    }
  }
}

// Scene format is generated on the desktop. The fixed engine interprets
// background, rectangle, text, gauge and RGB565 animation-frame commands.
bool drawScene(char page) {
  File file = SPIFFS.open("/scene.txt", FILE_READ);
  if (!file) return false;
  bool found = false;
  int enabledBits[] = {2, 4, 1};
  int values[] = {usage.fiveHour, usage.weekly, usage.context};
  const char *names[] = {"5-HOUR LIMIT", "WEEKLY LIMIT", "CONTEXT"};
  while (file.available()) {
    String line = file.readStringUntil('\n');
    if (fieldAt(line, 1) != String(page)) continue;
    String kind = fieldAt(line, 0);
    if (kind == "S") {
      canvas.fillSprite(rgb565(strtoul(fieldAt(line, 2).c_str(), nullptr, 16)));
      found = true;
    } else if (kind == "R") {
      int x = fieldAt(line, 2).toInt(), y = fieldAt(line, 3).toInt();
      int w = fieldAt(line, 4).toInt(), h = fieldAt(line, 5).toInt();
      if (x >= 0 && y >= 0 && w > 0 && h > 0 && x + w <= 240 && y + h <= 240)
        canvas.fillRect(x, y, w, h, rgb565(strtoul(fieldAt(line, 6).c_str(), nullptr, 16)));
    } else if (kind == "T") {
      int x = fieldAt(line, 2).toInt(), y = fieldAt(line, 3).toInt();
      int size = constrain(fieldAt(line, 4).toInt(), 1, 4);
      if (x >= 0 && y >= 0 && x < 240 && y < 240) {
        canvas.setCursor(x, y); canvas.setTextSize(size);
        canvas.setTextColor(rgb565(strtoul(fieldAt(line, 5).c_str(), nullptr, 16)));
        canvas.print(fieldAt(line, 6));
      }
    } else if (kind == "D") {
      int x = fieldAt(line, 2).toInt(), y = fieldAt(line, 3).toInt();
      if (x < 0 || x > 190 || y < 0 || y > 225) continue;
      uint16_t ink = rgb565(strtoul(fieldAt(line, 4).c_str(), nullptr, 16));
      canvas.drawRect(x, y, 22, 11, ink);
      canvas.fillRect(x + 22, y + 3, 2, 5, ink);
      if (batteryPercent >= 0) canvas.fillRect(x + 2, y + 2, batteryPercent * 18 / 100, 7, ink);
      canvas.setTextColor(ink); canvas.setTextSize(1); canvas.setCursor(x + 28, y + 2);
      if (batteryPercent < 0) canvas.print("--");
      else { canvas.print(batteryPercent); canvas.print("%"); }
    } else if (kind == "B") {
      int x = fieldAt(line, 2).toInt(), y = fieldAt(line, 3).toInt();
      int w = fieldAt(line, 4).toInt();
      String binding = fieldAt(line, 6);
      int index = binding == "five" ? 0 : binding == "week" ? 1 : 2;
      if (x < 0 || y < 0 || w < 1 || x + w > 240 || y + 42 > 240) continue;
      uint16_t color = rgb565(strtoul(fieldAt(line, 5).c_str(), nullptr, 16));
      canvas.setTextSize(1); canvas.setTextColor(tft.color565(100, 116, 138));
      canvas.setCursor(x, y); canvas.print(names[index]);
      canvas.setTextSize(2); canvas.setTextColor(tft.color565(34, 45, 62));
      canvas.setCursor(x, y + 13);
      if (values[index] < 0) canvas.print("--");
      else { canvas.print(values[index]); canvas.print("% LEFT"); }
      canvas.fillRect(x, y + 35, w, 6, tft.color565(224, 230, 237));
      if (values[index] > 0) canvas.fillRect(x, y + 35, w * constrain(values[index], 0, 100) / 100, 6, color);
    } else if (kind == "G") {
      int cx = fieldAt(line, 2).toInt(), cy = fieldAt(line, 3).toInt();
      int radius = constrain(fieldAt(line, 4).toInt(), 30, 100);
      uint16_t color = rgb565(strtoul(fieldAt(line, 5).c_str(), nullptr, 16));
      int count = 0;
      for (int i = 0; i < 3; i++) if (displaySettings.widgets & enabledBits[i]) count++;
      int selected = ((millis() - screenCycleStart) / 2500) % max(count, 1), index = 0;
      for (int i = 0; i < 3; i++) if (displaySettings.widgets & enabledBits[i]) {
        if (selected-- == 0) { index = i; break; }
      }
      int lit = values[index] < 0 ? 0 : constrain(values[index], 0, 100) * 54 / 100;
      for (int i = 0; i <= 54; i++) {
        float a = (135.0f + i * 5.0f) * 0.017453293f;
        float dx = cosf(a), dy = sinf(a);
        spriteLine(cx + dx * (radius - 9), cy + dy * (radius - 9),
                   cx + dx * radius, cy + dy * radius,
                   i < lit ? color : tft.color565(224, 230, 237));
      }
      canvas.setTextColor(tft.color565(100, 116, 138)); canvas.setTextSize(1);
      canvas.setCursor(cx - strlen(names[index]) * 3, cy - 25); canvas.print(names[index]);
      String value = values[index] < 0 ? "--" : String(values[index]) + "%";
      canvas.setTextColor(tft.color565(34, 45, 62)); canvas.setTextSize(4);
      canvas.setCursor(cx - value.length() * 12, cy - 5); canvas.print(value);
      canvas.setTextColor(tft.color565(100, 116, 138)); canvas.setTextSize(1);
      canvas.setCursor(cx - 12, cy + 34); canvas.print("LEFT");
    } else if (kind == "I") {
      int frame = fieldAt(line, 2).toInt(), total = fieldAt(line, 3).toInt();
      int frameMs = constrain(fieldAt(line, 4).toInt(), 80, 2000);
      int x = fieldAt(line, 5).toInt(), y = fieldAt(line, 6).toInt();
      int scale = constrain(fieldAt(line, 7).toInt(), 1, 6);
      if (total <= 0 || frame != (int)(((millis() - screenCycleStart) / frameMs) % total) ||
          x < 0 || y < 0 || x + 32 * scale > 240 || y + 32 * scale > 240) continue;
      String pixels = fieldAt(line, 8);
      if (pixels.length() != 4096) continue;
      for (int i = 0; i < 1024; i++) {
        char colorText[5];
        for (int j = 0; j < 4; j++) colorText[j] = pixels[i * 4 + j];
        colorText[4] = 0;
        canvas.fillRect(x + (i % 32) * scale, y + (i / 32) * scale, scale, scale,
                        (uint16_t)strtoul(colorText, nullptr, 16));
      }
    }
  }
  file.close();
  return found;
}

void drawPet() {
  const unsigned long sceneMs = (millis() - screenCycleStart) % 11000;
  const unsigned long frame = sceneMs / 40;
  const int phase = frame % 24;
  const int bob = phase < 12 ? phase / 6 : (23 - phase) / 6;
  const int hand = (frame / 5) & 1;
  const bool blink = frame % 101 < 3;
  const bool pulse = (frame / 6) & 1;
  const int antennaSway = (frame / 4) % 3 - 1;
  const bool laptop = displaySettings.animation == 2 ||
                      (displaySettings.animation == 0 && sceneMs >= 3200 && sceneMs < 7800);
  const bool nullFace = displaySettings.animation != 2 && ((sceneMs >= 1500 && sceneMs < 3200) ||
                        (sceneMs >= 7800 && sceneMs < 9500));
  const bool happyFace = laptop && (displaySettings.animation == 2 || sceneMs >= 4700);
  const int x = 60, y = (laptop ? 18 : 32) + bob;

  // Clean white stage with one centered, high-contrast character.
  canvas.fillSprite(rgb565(displaySettings.background));

  // Two-pixel antenna and large, crisp monitor head.
  spriteLine(x + 60, y + 13, x + 60, y + 1, TRACK);
  spriteLine(x + 61, y + 13, x + 61, y + 1, TRACK);
  spriteLine(x + 60, y + 1, x + 52 + antennaSway, y - 6, TRACK);
  spriteLine(x + 61, y + 1, x + 53 + antennaSway, y - 6, TRACK);
  canvas.fillCircle(x + 50 + antennaSway, y - 6, 3, CODEX);

  spriteFillPanel(x + 8, y + 12, 104, 82, 10, TRACK);
  spritePanelOutline(x + 11, y + 15, 98, 76, 8, CODEX);
  spriteFillPanel(x + 21, y + 27, 78, 48, 4, FACE);
  canvas.fillRect(x, y + 40, 8, 27, TRACK);
  canvas.fillRect(x + 112, y + 40, 8, 27, TRACK);
  canvas.fillRect(x + 2, y + 46, 4, 15, CODEX);
  canvas.fillRect(x + 114, y + 46, 4, 15, CODEX);

  // Face sequence from the reference: dots, NULL, happy, NULL, dots.
  if (nullFace) {
    canvas.setTextColor(PET_FACE, FACE);
    canvas.setTextSize(2);
    canvas.setCursor(x + 35, y + 43);
    canvas.print("NULL");
  } else if (blink) {
    canvas.fillRect(x + 35, y + 51, 14, 3, PET_FACE);
    canvas.fillRect(x + 71, y + 51, 14, 3, PET_FACE);
  } else if (happyFace) {
    spriteLine(x + 34, y + 56, x + 42, y + 47, PET_FACE);
    spriteLine(x + 42, y + 47, x + 50, y + 56, PET_FACE);
    spriteLine(x + 70, y + 56, x + 78, y + 47, PET_FACE);
    spriteLine(x + 78, y + 47, x + 86, y + 56, PET_FACE);
  } else {
    canvas.fillCircle(x + 36, y + 52, 4, PET_FACE);
    canvas.fillCircle(x + 60, y + 52, 4, PET_FACE);
    canvas.fillCircle(x + 84, y + 52, 4, PET_FACE);
  }

  // Compact torso and bright Codex chest mark.
  spriteFillPanel(x + 35, y + 94, 50, 45, 6, TRACK);
  canvas.fillCircle(x + 60, y + 113, 7, FACE);
  canvas.drawCircle(x + 60, y + 113, 7, CODEX);
  spriteLine(x + 56, y + 109, x + 64, y + 117, CODEX_HI);
  spriteLine(x + 64, y + 109, x + 56, y + 117, CODEX_HI);

  if (laptop) {
    // Hands type above the laptop edge; legs and tail remain visible behind it.
    spriteFillPanel(x + 17, y + 111 + (hand ? 3 : 0), 34, 11, 3, CODEX);
    spriteFillPanel(x + 69, y + 114 - (hand ? 3 : 0), 34, 11, 3, CODEX);
    canvas.fillRect(x + 38, y + 137, 17, 24, TRACK);
    canvas.fillRect(x + 69, y + 137, 17, 24, TRACK);
    spriteLine(x + 88, y + 128, x + 112, y + 128, TRACK);
    spriteLine(x + 112, y + 128, x + 116 + pulse, y + 148, TRACK);
    spriteLine(x + 116 + pulse, y + 148, x + 102, y + 157, TRACK);

    // Simple clean laptop: one solid screen, thin blue rim, flat keyboard base.
    spriteFillTriangle(x - 13, y + 110, x + 87, y + 110, x + 101, y + 163, TRACK);
    spriteFillTriangle(x - 13, y + 110, x + 101, y + 163, x, y + 163, TRACK);
    spritePanelOutline(x - 9, y + 114, 94, 44, 3, CODEX);
    canvas.fillRect(x - 2, y + 164, 108, 6, TRACK);
    canvas.fillCircle(x + 40, y + 137, 8, FACE);
    canvas.drawCircle(x + 40, y + 137, 8, CODEX);
    spriteLine(x + 36, y + 133, x + 44, y + 141, CODEX_HI);
    spriteLine(x + 44, y + 133, x + 36, y + 141, CODEX_HI);
    canvas.fillRect(x + 9 + hand * 44, y + 155, 22, 3, CODEX_HI);
  } else {
    // Symmetrical standing pose with clear gaps between limbs.
    spriteFillPanel(x + 15, y + 101, 18, 38, 4, TRACK);
    spriteFillPanel(x + 87, y + 101, 18, 38, 4, TRACK);
    canvas.fillRect(x + 41, y + 139, 16, 31, TRACK);
    canvas.fillRect(x + 67, y + 139, 16, 31, TRACK);
    canvas.fillRect(x + 36, y + 166, 24, 7, TRACK);
    canvas.fillRect(x + 64, y + 166, 24, 7, TRACK);
  }
}

void bar(int x, int y, int width, int percent) {
  spriteFillPanel(x, y, width, 9, 4, TRACK);
  if (percent >= 0) spriteFillPanel(x, y, width * constrain(percent, 0, 100) / 100, 9, 4, CODEX);
}

void drawUsage() {
  const int bits[] = {2, 4, 1};
  const char *labels[] = {"5-HOUR LIMIT", "WEEKLY LIMIT", "CONTEXT"};
  const int values[] = {usage.fiveHour, usage.weekly, usage.context};
  int count = 0;
  for (int i = 0; i < 3; i++) if (displaySettings.widgets & bits[i]) count++;
  int selected = ((millis() - screenCycleStart) / 2500) % max(count, 1);
  int current = 0;
  for (int i = 0; i < 3; i++) {
    if (!(displaySettings.widgets & bits[i])) continue;
    if (selected-- == 0) { current = i; break; }
  }

  const uint16_t ink = tft.color565(34, 45, 62);
  const uint16_t soft = tft.color565(135, 149, 166);
  const uint16_t track = tft.color565(224, 230, 237);
  canvas.fillSprite(TFT_WHITE);

  // A 270-degree speedometer. Drawing short radial strokes keeps the arc
  // compatible with the lightweight ST7789 sprite library.
  int percent = values[current];
  int lit = percent < 0 ? 0 : constrain(percent, 0, 100) * 54 / 100;
  for (int i = 0; i <= 54; i++) {
    float angle = (135.0f + i * 5.0f) * 0.017453293f;
    float dx = cosf(angle), dy = sinf(angle);
    uint16_t color = i < lit ? CODEX : track;
    spriteLine(120 + dx * 82, 108 + dy * 82,
               120 + dx * 91, 108 + dy * 91, color);
    spriteLine(120 + dx * 83, 108 + dy * 83,
               120 + dx * 90, 108 + dy * 90, color);
    if (i % 9 == 0) {
      spriteLine(120 + dx * 96, 108 + dy * 96,
                 120 + dx * 100, 108 + dy * 100, soft);
    }
  }
  canvas.setTextColor(soft, TFT_WHITE);
  canvas.setTextSize(1);
  canvas.setCursor(120 - strlen(labels[current]) * 3, 85);
  canvas.print(labels[current]);
  String value = percent < 0 ? "--" : String(percent) + "%";
  canvas.setTextColor(ink, TFT_WHITE);
  canvas.setTextSize(4);
  canvas.setCursor(120 - value.length() * 12, 103);
  canvas.print(value);
  canvas.setTextSize(1);
  canvas.setTextColor(soft, TFT_WHITE);
  canvas.setCursor(108, 143);
  canvas.print("LEFT");
  canvas.fillRect(85, 169, 70, 2, CODEX);

  // The selected label and page indicators make it clear which limit is shown.
  canvas.setCursor(64, 199);
  canvas.print("0");
  canvas.setCursor(157, 199);
  canvas.print("100%");
  for (int i = 0; i < count; i++) {
    int x = 120 - (count - 1) * 7 + i * 14;
    canvas.fillCircle(x, 220, 3, i == ((millis() - screenCycleStart) / 2500) % count ? CODEX : track);
  }
}

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  analogSetPinAttenuation(BAT_PIN, ADC_11db);
  loadDisplaySettings();
  sceneReady = SPIFFS.begin(false);
  if (sceneReady && !SPIFFS.exists("/scene.txt") && SPIFFS.exists("/scene.old"))
    SPIFFS.rename("/scene.old", "/scene.txt");
  tft.init();
  tft.setRotation(0);
  tft.fillScreen(TFT_BLACK);
  canvas.createSprite(240, 240);
  canvas.fillSprite(TFT_BLACK);
  startBluetooth();
  startWifi();
}

void loop() {
  pollSerial();
  unsigned long now = millis();
  updateWifi(now);
  updateBattery(now);
  if (wifiOnline) pollWifi();
  unsigned long animationMs = (unsigned long)displaySettings.animationSeconds * 1000;
  unsigned long cycleMs = animationMs + (unsigned long)displaySettings.usageSeconds * 1000;
  usageScreen = displaySettings.mode == 2 || (displaySettings.mode == 0 &&
    (now - screenCycleStart) % cycleMs >= animationMs);
  if (now - lastFrame >= (usageScreen ? 250 : 100)) {
    lastFrame = now;
    canvas.fillSprite(usageScreen ? TFT_BLACK : rgb565(displaySettings.background));
    if (!drawScene(usageScreen ? 'U' : 'A')) {
      usageScreen ? drawUsage() : drawPet();
    }
    canvas.pushSprite(0, 0);
  }
  delay(2);
}
