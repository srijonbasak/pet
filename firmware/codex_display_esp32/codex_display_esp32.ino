#include <SPI.h>
#include <ST7789_ESP32C3.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>

// Set these once before uploading. BLE still works when Wi-Fi is unavailable.
const char *WIFI_SSID = "YOUR_WIFI_NAME";
const char *WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const uint16_t UDP_PORT = 4210;

const char *SERVICE_UUID = "4fafc201-1fb5-459e-8fcc-c5c9c331914b";
const char *CHAR_UUID = "beb5483e-36e1-4688-b7f5-ea07361b26a8";

ST7789_ESP32C3 tft;
ST7789_Sprite canvas(&tft);
WiFiUDP udp;

#define BG       TFT_BLACK
#define PANEL    tft.color565(16, 22, 36)
#define TRACK    tft.color565(48, 65, 92)
#define MUTED    tft.color565(115, 143, 185)
#define CODEX    tft.color565(110, 160, 255)
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

void acceptPacket(String line) {
  line.trim();
  if (!line.startsWith("CD2|")) return;
  usage.project = fieldAt(line, 1);
  usage.chat = fieldAt(line, 2);
  usage.context = fieldAt(line, 3).toInt();
  usage.used = fieldAt(line, 4).toInt();
  usage.maximum = fieldAt(line, 5).toInt();
  usage.fiveHour = fieldAt(line, 6).toInt();
  usage.fiveReset = fieldAt(line, 7);
  usage.weekly = fieldAt(line, 8).toInt();
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
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long until = millis() + 8000;
  while (WiFi.status() != WL_CONNECTED && millis() < until) delay(80);
  if (WiFi.status() == WL_CONNECTED) udp.begin(UDP_PORT);
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

void drawPet() {
  const unsigned long sceneMs = millis() % 18000;
  const unsigned long frame = sceneMs / 40;
  const int phase = frame % 24;
  const int bob = phase < 12 ? phase / 6 : (23 - phase) / 6;
  const int hand = (frame / 5) & 1;
  const bool blink = frame % 101 < 3;
  const bool pulse = (frame / 6) & 1;
  const int antennaSway = (frame / 4) % 3 - 1;
  const bool laptop = sceneMs >= 3200 && sceneMs < 7800;
  const bool nullFace = (sceneMs >= 1500 && sceneMs < 3200) ||
                        (sceneMs >= 7800 && sceneMs < 9500);
  const bool happyFace = laptop && sceneMs >= 4700;
  const int x = 60, y = (laptop ? 18 : 32) + bob;

  // Clean white stage with one centered, high-contrast character.
  canvas.fillSprite(TFT_WHITE);

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
  textFit("CODEX USAGE", 16, 14, 20, CODEX_HI, 2);
  textFit(usage.project, 16, 42, 27, TFT_WHITE);
  textFit(usage.chat, 16, 57, 31, MUTED);

  spriteFillPanel(12, 79, 216, 58, 10, PANEL);
  textFit("5 HOUR", 24, 91, 10, MUTED);
  textFit(usage.fiveHour >= 0 ? String(usage.fiveHour) + "% LEFT" : "--", 24, 107, 15, TFT_WHITE, 2);
  bar(24, 126, 190, usage.fiveHour);

  spriteFillPanel(12, 145, 216, 58, 10, PANEL);
  textFit("WEEKLY", 24, 157, 10, MUTED);
  textFit(usage.weekly >= 0 ? String(usage.weekly) + "% LEFT" : "--", 24, 173, 15, TFT_WHITE, 2);
  bar(24, 192, 190, usage.weekly);

  String footer = usage.context >= 0 ? "CTX " + String(usage.context) + "% LEFT" : "WAITING FOR DATA";
  textFit(footer, 16, 218, 28, CODEX_HI);
}

void setup() {
  tft.init();
  tft.setRotation(0);
  tft.fillScreen(TFT_BLACK);
  canvas.createSprite(240, 240);
  canvas.fillSprite(TFT_BLACK);
  startBluetooth();
  startWifi();
}

void loop() {
  if (WiFi.status() == WL_CONNECTED) pollWifi();
  unsigned long now = millis();
  // Play the complete 11-second reference animation, then show usage for 7s.
  usageScreen = (now % 18000) >= 11000;
  if (now - lastFrame >= 40) {
    lastFrame = now;
    canvas.fillSprite(usageScreen ? TFT_BLACK : TFT_WHITE);
    usageScreen ? drawUsage() : drawPet();
    canvas.pushSprite(0, 0);
  }
  delay(2);
}
