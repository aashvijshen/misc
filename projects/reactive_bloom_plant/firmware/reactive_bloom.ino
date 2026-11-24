/**
 * BloomCore v2 — Modular Reactive Plant Platform Firmware (`reactive_bloom.ino`)
 *
 * Target MCU : ESP32-C3 SuperMini (22.52 x 18.00 mm, Native USB-C, Wi-Fi + BLE)
 * Actuator   : SG90/MG90S on Slide-In `actuator_sled_sg90` (or Silent Stepper Sled)
 * Input Bay  : MX Mechanical Keyswitch / 6x6mm Tactile Switch inside `sensor_toadstool`
 * Lighting   : WS2812B Warm/RGB NeoPixel inside `stamen_crown`
 * Expansion  : Pre-allocated I2C (`GPIO8/GPIO9`) for plug-in Soil Props (OLED Sign / Sensors)
 *
 * Single-Actuator Synchronized 4-Way Expression (`dz = -5.0 mm` to `+5.0 mm`):
 *   1. Kawaii Pot Eyes (`eye_slider`): Droopy Sleepy `u w u` <-> Happy Arched `^ w ^`
 *   2. Lotus Topper (`petal_inner/outer`): Tight Bud (-33.2°) <-> Full Bloom (+34.5°)
 *   3. Cradling Stem Leaves (`stem_leaf`): Wilted (-30°) <-> Proudly Cradling (+54°)
 *   4. Soil Companion (`baby_sprout`): Tucked in Moss <-> Pops +10.0 mm Out of Soil
 *
 * Built-In Features:
 *   - Standalone Multi-Click Toadstool Rituals (1x Feed/Start, 2x Timer Preset, Hold Sleep)
 *   - Continuous Gradual Timer Wilting (Pomodoro Focus / Hydration Companion)
 *   - Selectable Product-Line Plant Personalities (Graceful Lotus, Snappy Flytrap, Shy Mimosa)
 *   - Ambient Circadian Wake/Sleep (LDR) + Subtle Periodic "Sign-of-Life" Stretch
 *   - Embedded Zero-Install Mobile Web Companion (`http://bloom.local`) + JSON Webhook API
 */

#include <Arduino.h>
#include <Wire.h>

#if defined(ESP32)
  #include <WiFi.h>
  #include <WebServer.h>
  #include <ESPmDNS.h>
  #include <ESP32Servo.h>
  #define HAS_WIFI_WEB 1
#elif defined(ESP8266)
  #include <ESP8266WiFi.h>
  #include <ESP8266WebServer.h>
  #include <ESP8266mDNS.h>
  #include <Servo.h>
  using WebServer = ESP8266WebServer;
  #define HAS_WIFI_WEB 1
#else
  #include <Servo.h>
  #define HAS_WIFI_WEB 0
#endif

// Optional Adafruit_NeoPixel support (compiles cleanly even if library isn't installed yet)
#if __has_include(<Adafruit_NeoPixel.h>)
  #include <Adafruit_NeoPixel.h>
  #define HAS_NEOPIXEL 1
#else
  #define HAS_NEOPIXEL 0
#endif

// ---------------------------------------------------------------------------
// 1. ESP32-C3 SUPERMINI STANDARD BLOOMCORE PINOUT
// ---------------------------------------------------------------------------
constexpr uint8_t PIN_SERVO      = 2;   // GPIO2: Actuator Sled PWM
constexpr uint8_t PIN_SWITCH     = 3;   // GPIO3: Toadstool MX / Tactile Switch (Active LOW w/ Pullup)
constexpr uint8_t PIN_NEOPIXEL   = 4;   // GPIO4: Stamen WS2812B LED Data
constexpr uint8_t PIN_LDR_ANALOG = 0;   // GPIO0 (ADC1_CH0): Optional Ambient Light Sensor
constexpr uint8_t PIN_I2C_SDA    = 8;   // GPIO8: Expansion I2C SDA (OLED Garden Sign / Soil Sensor)
constexpr uint8_t PIN_I2C_SCL    = 9;   // GPIO9: Expansion I2C SCL

// Optional Wi-Fi Credentials (falls back to SoftAP "BloomCore-Plant" if left empty!)
const char* WIFI_SSID = "";
const char* WIFI_PASS = "";

// ---------------------------------------------------------------------------
// 2. SCOTCH-YOKE KINEMATIC CALIBRATION (`R_HORN = 14.50 mm`, `dz = +/- 5.00 mm`)
// ---------------------------------------------------------------------------
constexpr float R_HORN_MM        = 14.50f;
constexpr float STROKE_HALF_MM   = 5.00f;   // dz in [-5.0, +5.0] mm
constexpr float SERVO_NEUTRAL_DEG = 90.0f;  // Calibrate horn horizontal (+X) at 90 deg

// Switch polarity: false = MX Keyswitch / Tactile Button to GND; true = TTP223 Active-HIGH Touch
constexpr bool SWITCH_ACTIVE_HIGH = false;

// ---------------------------------------------------------------------------
// 3. PRODUCT-LINE PLANT PERSONALITY PROFILES (For Swappable Toppers!)
// ---------------------------------------------------------------------------
enum PlantPersonality : uint8_t {
  PERSONALITY_LOTUS   = 0,  // Graceful Kawaii Lotus (smooth S-curve bloom, gentle breathing)
  PERSONALITY_FLYTRAP = 1,  // Snappy Venus Flytrap ("Chompy" task-eater, fast spring snap!)
  PERSONALITY_MIMOSA  = 2   // Shy Mimosa Fern (instant shy fold on press, slow timid peek-open)
};

struct TimerPreset {
  const char* label;
  uint32_t durationSec;
};

constexpr TimerPreset PRESETS[] = {
  {"Companion Toggle (No Countdown)", 0},
  {"25m Pomodoro Focus",              25 * 60},
  {"50m Deep Work",                   50 * 60},
  {"90m Hydration Reminder",          90 * 60},
};
constexpr uint8_t NUM_PRESETS = sizeof(PRESETS) / sizeof(PRESETS[0]);

// ---------------------------------------------------------------------------
// 4. RUNTIME STATE
// ---------------------------------------------------------------------------
Servo bloomServo;
#if HAS_NEOPIXEL
Adafruit_NeoPixel pixel(1, PIN_NEOPIXEL, NEO_GRB + NEO_KHZ800);
#endif
#if HAS_WIFI_WEB
WebServer server(80);
#endif

PlantPersonality activePersonality = PERSONALITY_LOTUS;
uint8_t activePresetIdx            = 1;      // Default: 25m Pomodoro
bool sleepingMode                  = false;

float currentHealth  = 1.0f;  // 0.0 = Fully Wilted (dz=-5mm), 1.0 = Full Bloom (dz=+5mm)
float startPos       = 0.0f;
float targetPos      = 1.0f;
float currentPos     = 0.0f;

uint32_t animStartMs = 0;
uint32_t animDurMs   = 3600;
bool isAnimating     = false;
bool servoAttached   = false;
uint32_t detachAtMs  = 0;

uint32_t timerStartMs     = 0;
uint32_t timerDurationMs  = 25UL * 60UL * 1000UL;
bool timerRunning         = false;
uint32_t completedStreaks = 0;
uint32_t lastIdleBreathMs = 0;

// Multi-click button state machine
bool lastBtnState        = false;
uint32_t lastDebounceMs  = 0;
uint32_t btnDownMs       = 0;
bool longPressHandled    = false;
uint8_t pendingClicks    = 0;
uint32_t lastClickUpMs   = 0;

// Shy Mimosa recovery timer
uint32_t mimosaPeekAtMs  = 0;

// ---------------------------------------------------------------------------
// 5. KINEMATICS, EASING & LIGHTING HELPERS
// ---------------------------------------------------------------------------
float easeCurve(float u, PlantPersonality p, bool opening) {
  u = constrain(u, 0.0f, 1.0f);
  if (p == PERSONALITY_FLYTRAP && !opening) {
    // Snappy Venus Flytrap jaw close with slight elastic overshoot clamp
    return u * u * (3.0f - 2.0f * u);
  }
  // Smooth organic cosine S-curve (zero jerk/velocity at endpoints)
  return 0.5f * (1.0f - cosf(PI * u));
}

void writePlungerProgress(float progress01) {
  progress01 = constrain(progress01, 0.0f, 1.0f);
  // Exact inverse Scotch-Yoke kinematics: dz = (2*p - 1) * 5.0 mm, sin(theta) = dz / R_HORN
  float dz = (2.0f * progress01 - 1.0f) * STROKE_HALF_MM;
  float sinTheta = constrain(dz / R_HORN_MM, -1.0f, 1.0f);
  float thetaDeg = asinf(sinTheta) * (180.0f / PI);
  float servoDeg = SERVO_NEUTRAL_DEG + thetaDeg;

  int pulseUs = static_cast<int>(500.0f + (servoDeg / 180.0f) * 1900.0f);
  if (!servoAttached) {
    bloomServo.attach(PIN_SERVO, 500, 2400);
    servoAttached = true;
  }
  bloomServo.writeMicroseconds(pulseUs);
}

void movePlantTo(float newTarget, uint32_t customDurMs = 0) {
  newTarget = constrain(newTarget, 0.0f, 1.0f);
  if (fabsf(newTarget - targetPos) < 0.004f && !isAnimating) {
    return;
  }
  startPos    = currentPos;
  targetPos   = newTarget;
  bool open   = (targetPos >= startPos);
  float delta = fabsf(targetPos - startPos);

  uint32_t baseDur = 3600;
  if (activePersonality == PERSONALITY_FLYTRAP) {
    baseDur = open ? 1400 : 320;   // Fast chomp!
  } else if (activePersonality == PERSONALITY_MIMOSA) {
    baseDur = open ? 6500 : 280;   // Instant shy flinch, slow timid open!
  } else {
    baseDur = open ? 3600 : 4400;  // Graceful Lotus
  }

  animDurMs   = (customDurMs > 0) ? customDurMs : max<uint32_t>(180, static_cast<uint32_t>(baseDur * delta));
  animStartMs = millis();
  isAnimating = true;
}

void updateStamenLED(uint32_t now) {
#if HAS_NEOPIXEL
  float breath = 0.5f * (1.0f + sinf(now * 0.0022f));
  uint8_t r = 0, g = 0, b = 0;
  if (sleepingMode) {
    // Cozy dim twilight ember
    r = static_cast<uint8_t>(18 + 12 * breath);
    g = static_cast<uint8_t>(6 + 4 * breath);
    b = 2;
  } else if (activePersonality == PERSONALITY_FLYTRAP) {
    // Crisp botanical lime -> amber
    r = static_cast<uint8_t>(80 + 140 * (1.0f - currentPos));
    g = static_cast<uint8_t>(40 + 180 * currentPos);
    b = 15;
  } else {
    // Warm honey-gold stamen glow scaled by bloom health
    float intensity = (0.18f + 0.82f * currentPos) * (0.78f + 0.22f * breath);
    r = static_cast<uint8_t>(255 * intensity);
    g = static_cast<uint8_t>(165 * intensity);
    b = static_cast<uint8_t>(28 * intensity);
  }
  pixel.setPixelColor(0, pixel.Color(r, g, b));
  pixel.show();
#else
  (void)now;
#endif
}

void blinkConfirm(uint8_t count) {
#if HAS_NEOPIXEL
  for (uint8_t i = 0; i < count; ++i) {
    pixel.setPixelColor(0, pixel.Color(255, 220, 80));
    pixel.show();
    delay(120);
    pixel.setPixelColor(0, pixel.Color(0, 0, 0));
    pixel.show();
    delay(110);
  }
#else
  (void)count;
#endif
}

// ---------------------------------------------------------------------------
// 6. HABIT / TIMER ACTIONS
// ---------------------------------------------------------------------------
void feedAndStartGoal() {
  sleepingMode = false;
  if (activePersonality == PERSONALITY_MIMOSA) {
    // Shy Mimosa flinches closed when touched, then peeks back open!
    movePlantTo(0.05f);
    mimosaPeekAtMs = millis() + 4000;
    return;
  }

  if (timerRunning && currentHealth < 0.95f) {
    completedStreaks++;
  }
  currentHealth = 1.0f;
  movePlantTo(1.0f);

  uint32_t sec = PRESETS[activePresetIdx].durationSec;
  if (sec > 0) {
    timerDurationMs = sec * 1000UL;
    timerStartMs    = millis();
    timerRunning    = true;
    Serial.printf("[BloomCore] Fed! Starting '%s' (%lu s) | Streaks=%lu\n",
                  PRESETS[activePresetIdx].label, (unsigned long)sec, (unsigned long)completedStreaks);
  } else {
    timerRunning = false;
    // Free companion toggle
    float next = (targetPos > 0.5f && currentPos > 0.5f) ? 0.0f : 1.0f;
    movePlantTo(next);
  }
}

void cyclePreset() {
  activePresetIdx = (activePresetIdx + 1) % NUM_PRESETS;
  blinkConfirm(activePresetIdx + 1);
  Serial.printf("[BloomCore] Preset -> %u: %s\n", activePresetIdx, PRESETS[activePresetIdx].label);
  if (PRESETS[activePresetIdx].durationSec > 0) {
    timerDurationMs = PRESETS[activePresetIdx].durationSec * 1000UL;
    timerStartMs    = millis();
    timerRunning    = true;
    movePlantTo(1.0f);
  } else {
    timerRunning = false;
  }
}

void toggleSleepMode() {
  sleepingMode = !sleepingMode;
  timerRunning = false;
  movePlantTo(sleepingMode ? 0.0f : 1.0f);
  Serial.printf("[BloomCore] Sleep Mode -> %s\n", sleepingMode ? "ON (u w u)" : "OFF (^ w ^)");
}

// ---------------------------------------------------------------------------
// 7. EMBEDDED MOBILE WEB COMPANION (`http://bloom.local`)
// ---------------------------------------------------------------------------
#if HAS_WIFI_WEB
const char INDEX_HTML[] PROGMEM = R"rawliteral(
<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BloomCore Companion</title>
<style>
  body{font-family:system-ui,-apple-system,sans-serif;background:#FFF8F3;color:#2D1E1B;margin:0;padding:20px;text-align:center}
  .card{max-width:420px;margin:0 auto;background:#FFF;border-radius:22px;padding:22px;box-shadow:0 8px 28px rgba(45,30,27,.08)}
  h1{font-size:1.35rem;margin:0 0 6px} .sub{color:#7C625B;font-size:.9rem;margin-bottom:16px}
  .face{font-size:2.4rem;margin:10px 0;letter-spacing:4px}
  .bar{height:12px;background:#F3E5DC;border-radius:99px;overflow:hidden;margin:12px 0 18px}
  .fill{height:100%;background:linear-gradient(90deg,#FF7597,#4CD964);transition:width .4s}
  button,select{width:100%;padding:12px 14px;margin:6px 0;border-radius:12px;border:1.5px solid #EBD8CC;font-size:.95rem;font-weight:600;cursor:pointer;background:#FFF}
  .pri{background:#FF6B8B;color:#FFF;border:none;font-size:1.05rem}
  .row{display:flex;gap:8px}
</style></head><body>
<div class="card">
  <h1>BloomCore Companion</h1>
  <div class="sub" id="st">Connecting...</div>
  <div class="face" id="fc">^ w ^</div>
  <div class="bar"><div class="fill" id="fl" style="width:100%"></div></div>
  <button class="pri" onclick="act('/api/feed')">Water / Feed Plant</button>
  <div class="row">
    <button onclick="act('/api/timer?min=25')">25m Focus</button>
    <button onclick="act('/api/timer?min=50')">50m Deep</button>
    <button onclick="act('/api/timer?min=90')">90m Water</button>
  </div>
  <select id="ps" onchange="act('/api/personality?id='+this.value)">
    <option value="0">SKU 1: Graceful Kawaii Lotus</option>
    <option value="1">SKU 2: Snappy Venus Flytrap</option>
    <option value="2">SKU 3: Shy Mimosa Fern</option>
  </select>
  <button onclick="act('/api/sleep')">Toggle Sleep Mode (u w u)</button>
</div>
<script>
async function refresh(){
  const r=await fetch('/api/status'); const d=await r.json();
  document.getElementById('fl').style.width=Math.round(d.pos*100)+'%';
  document.getElementById('fc').textContent=d.pos>0.45?'^ w ^':'u w u';
  document.getElementById('st').textContent=`Health: ${Math.round(d.pos*100)}% | Streaks: ${d.streaks}`;
  document.getElementById('ps').value=d.personality;
}
async function act(u){await fetch(u,{method:'POST'}); setTimeout(refresh,150);}
setInterval(refresh,1500); refresh();
</script></body></html>
)rawliteral";

void setupWebRoutes() {
  server.on("/", HTTP_GET, []() {
    server.send_P(200, "text/html", INDEX_HTML);
  });
  server.on("/api/status", HTTP_GET, []() {
    char buf[192];
    snprintf(buf, sizeof(buf),
             "{\"pos\":%.2f,\"running\":%s,\"streaks\":%lu,\"personality\":%u,\"sleep\":%s}",
             currentPos, timerRunning ? "true" : "false",
             (unsigned long)completedStreaks, (unsigned)activePersonality,
             sleepingMode ? "true" : "false");
    server.send(200, "application/json", buf);
  });
  server.on("/api/feed", HTTP_POST, []() {
    feedAndStartGoal();
    server.send(200, "application/json", "{\"ok\":true}");
  });
  server.on("/api/sleep", HTTP_POST, []() {
    toggleSleepMode();
    server.send(200, "application/json", "{\"ok\":true}");
  });
  server.on("/api/timer", HTTP_POST, []() {
    int mins = server.hasArg("min") ? server.arg("min").toInt() : 25;
    mins = constrain(mins, 1, 240);
    sleepingMode    = false;
    timerDurationMs = static_cast<uint32_t>(mins) * 60UL * 1000UL;
    timerStartMs    = millis();
    timerRunning    = true;
    movePlantTo(1.0f);
    server.send(200, "application/json", "{\"ok\":true}");
  });
  server.on("/api/personality", HTTP_POST, []() {
    int id = server.hasArg("id") ? server.arg("id").toInt() : 0;
    activePersonality = static_cast<PlantPersonality>(constrain(id, 0, 2));
    blinkConfirm(id + 1);
    server.send(200, "application/json", "{\"ok\":true}");
  });
  server.begin();
}
#endif

// ---------------------------------------------------------------------------
// 8. SETUP & MAIN LOOP
// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  pinMode(PIN_SWITCH, SWITCH_ACTIVE_HIGH ? INPUT : INPUT_PULLUP);
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);

#if HAS_NEOPIXEL
  pixel.begin();
  pixel.setBrightness(180);
#endif

  // Greet user on boot with a smooth awakening bloom!
  currentPos = 0.0f;
  writePlungerProgress(0.0f);
  delay(350);
  movePlantTo(1.0f, 2800);
  timerStartMs      = millis();
  timerRunning      = true;
  lastIdleBreathMs  = millis();

#if HAS_WIFI_WEB
  if (strlen(WIFI_SSID) > 0) {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    uint32_t t0 = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - t0) < 6000) {
      delay(100);
    }
  }
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.mode(WIFI_AP);
    WiFi.softAP("BloomCore-Plant");
    Serial.println(F("[WiFi] SoftAP 'BloomCore-Plant' started at http://192.168.4.1"));
  } else {
    Serial.print(F("[WiFi] Connected: http://"));
    Serial.println(WiFi.localIP());
  }
  MDNS.begin("bloom");
  setupWebRoutes();
#endif

  Serial.println(F("=== BloomCore v2 Ready (1x Click=Feed, 2x=Preset, Hold=Sleep) ==="));
}

void loop() {
  const uint32_t now = millis();

#if HAS_WIFI_WEB
  server.handleClient();
#endif

  // 1. Multi-Click + Long-Press Toadstool Switch Handler
  bool rawPressed = SWITCH_ACTIVE_HIGH ? (digitalRead(PIN_SWITCH) == HIGH)
                                       : (digitalRead(PIN_SWITCH) == LOW);
  if (rawPressed != lastBtnState && (now - lastDebounceMs) > 35) {
    lastDebounceMs = now;
    lastBtnState   = rawPressed;
    if (rawPressed) {
      btnDownMs        = now;
      longPressHandled = false;
    } else if (!longPressHandled) {
      pendingClicks++;
      lastClickUpMs = now;
    }
  }
  if (lastBtnState && !longPressHandled && (now - btnDownMs) > 1400) {
    longPressHandled = true;
    pendingClicks    = 0;
    toggleSleepMode();
  }
  if (pendingClicks > 0 && !lastBtnState && (now - lastClickUpMs) > 320) {
    uint8_t clicks = pendingClicks;
    pendingClicks  = 0;
    if (clicks == 1) {
      feedAndStartGoal();
    } else {
      cyclePreset();
    }
  }

  // 2. Shy Mimosa Timid Recovery
  if (activePersonality == PERSONALITY_MIMOSA && mimosaPeekAtMs > 0 && now >= mimosaPeekAtMs) {
    mimosaPeekAtMs = 0;
    movePlantTo(1.0f);
  }

  // 3. Gradual Continuous Goal-Timer Wilting (stepped in 6% increments so servo stays silent 99% of the time!)
  if (timerRunning && !sleepingMode && !isAnimating) {
    uint32_t elapsed = now - timerStartMs;
    float rem = (elapsed >= timerDurationMs)
                  ? 0.0f
                  : 1.0f - (static_cast<float>(elapsed) / static_cast<float>(timerDurationMs));
    currentHealth = rem;
    // Quantize slow wilting into discrete graceful steps every ~6% health change so SG90 detaches silently between steps!
    float quantized = (rem <= 0.02f) ? 0.0f : roundf(rem * 16.0f) / 16.0f;
    if (fabsf(quantized - targetPos) >= 0.055f) {
      movePlantTo(quantized, 1200);
    }
  }

  // 4. Subtle Ambient "Sign of Life" Leaf Stretch every 20 minutes when idle & awake
  if (!sleepingMode && !timerRunning && !isAnimating && (now - lastIdleBreathMs) > 1200000UL) {
    lastIdleBreathMs = now;
    float nudge = (currentPos > 0.5f) ? (currentPos - 0.08f) : (currentPos + 0.08f);
    movePlantTo(nudge, 900);
  }

  // 5. Non-Blocking 50Hz Servo Trajectory + Automatic Quiet Detach
  if (isAnimating) {
    float u = static_cast<float>(now - animStartMs) / static_cast<float>(animDurMs);
    if (u >= 1.0f) {
      currentPos  = targetPos;
      isAnimating = false;
      detachAtMs  = now + 220;
    } else {
      float eased = easeCurve(u, activePersonality, targetPos >= startPos);
      currentPos  = startPos + (targetPos - startPos) * eased;
    }
    writePlungerProgress(currentPos);
  } else if (servoAttached && now >= detachAtMs) {
    bloomServo.detach();
    servoAttached = false;
  }

  // 6. Update Warm Breathing Stamen NeoPixel
  updateStamenLED(now);
  delay(20);
}
