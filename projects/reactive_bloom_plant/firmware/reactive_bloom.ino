/**
 * Reactive Blooming Plant Firmware (`reactive_bloom.ino`)
 * Target MCU: NodeMCU (ESP8266 ESP-12E) or ESP32 DevKit
 * Actuator  : SG90 / MG90S Micro Servo inside `pot_base` (mounted on `soil_lid` cradle)
 * Sensor    : TTP223 Capacitive Touch Sensor (or LDR Photoresistor) inside `sensor_toadstool`
 *
 * Mechanical Coupling (Single Servo -> 3 Synchronized Kinetic Motions via 1.75mm Filament Core):
 *   1. Staggered 6-Petal Lotus Head (`stamen_piston` + 3x `petal_inner` + 3x `petal_outer`):
 *      Sweeps 67.7 deg from Closed Bud (dz = -5.0 mm) to Full Open Bloom (dz = +5.0 mm).
 *   2. Articulated Stem Leaves (`leaf_collar` + 2x `stem_leaf` at Z = 132.0 mm):
 *      Sweeps 72.0 deg from Wilted/Drooping (-36.0 deg) to Perked/Proud (+36.0 deg).
 *   3. Pop-Up Baby Sprout (`bottom_plunger` + `baby_sprout` on `soil_lid`):
 *      Rises +10.0 mm out of its mossy burrow when satisfied, hides when dissatisfied.
 */

#include <Arduino.h>
#if defined(ESP8266)
  #include <Servo.h>
#elif defined(ESP32)
  #include <ESP32Servo.h>
#else
  #include <Servo.h>
#endif

// ---------------------------------------------------------------------------
// PIN DEFINITIONS & CALIBRATION CONSTANTS
// ---------------------------------------------------------------------------
constexpr uint8_t PIN_SERVO        = D4;   // GPIO2 on NodeMCU ESP8266
constexpr uint8_t PIN_TOUCH_SENSOR = D2;   // GPIO4: TTP223 Touch Sensor inside `sensor_toadstool`
constexpr uint8_t PIN_ANALOG_SENSE = A0;   // Optional LDR / Soil Moisture analog input

// Servo Horn Angles (with R_horn = 10.0 mm driving +/- 5.0 mm vertical stroke):
//   dz = R_horn * sin(theta - theta_mid)  ==>  +/- 30 deg around 90 deg neutral!
constexpr float SERVO_ANGLE_CLOSED = 60.0f;   // dz = -5.0 mm (Closed Bud, Leaves Droop -36°, Sprout Hides)
constexpr float SERVO_ANGLE_OPEN   = 120.0f;  // dz = +5.0 mm (Open Bloom, Leaves Perk +36°, Sprout Pops Up)

// Smooth Botanical Motion Durations (milliseconds):
constexpr uint32_t BLOOM_OPEN_DURATION_MS  = 3800;  // 3.8s slow, graceful morning bloom
constexpr uint32_t BLOOM_CLOSE_DURATION_MS = 4600;  // 4.6s gentle, sleepy evening close

// Analog threshold with hysteresis (prevents chatter near boundary):
constexpr int ANALOG_SATISFIED_HIGH = 560;
constexpr int ANALOG_SATISFIED_LOW  = 460;
constexpr bool USE_TOUCH_TOGGLE     = true;   // Touching the toadstool toggles or satisfies the plant

// ---------------------------------------------------------------------------
// STATE VARIABLES
// ---------------------------------------------------------------------------
Servo bloomServo;

bool isConditionSatisfied = false;
bool touchLatchState      = false;
bool lastTouchReading     = false;
uint32_t lastDebounceMs   = 0;

float currentProgress     = 0.0f;  // 0.0 = Fully Closed (dz = -5 mm), 1.0 = Fully Open (dz = +5 mm)
float startProgress       = 0.0f;
float targetProgress      = 0.0f;
uint32_t transitionStartMs = 0;
uint32_t transitionDurMs   = BLOOM_OPEN_DURATION_MS;
bool isMoving             = false;
bool servoAttached        = false;

// Cosine S-Curve Easing: zero velocity at start and end for organic, silent motion
float easeInOutSine(float t) {
  if (t <= 0.0f) return 0.0f;
  if (t >= 1.0f) return 1.0f;
  return 0.5f * (1.0f - cosf(PI * t));
}

void startBloomTransition(float newTarget) {
  if (fabsf(newTarget - targetProgress) < 0.001f) {
    return;
  }
  startProgress     = currentProgress;
  targetProgress    = constrain(newTarget, 0.0f, 1.0f);
  float delta       = fabsf(targetProgress - startProgress);
  uint32_t baseDur  = (targetProgress > startProgress) ? BLOOM_OPEN_DURATION_MS : BLOOM_CLOSE_DURATION_MS;
  transitionDurMs   = max<uint32_t>(250, static_cast<uint32_t>(baseDur * delta));
  transitionStartMs = millis();
  isMoving          = true;

  if (!servoAttached) {
    bloomServo.attach(PIN_SERVO, 500, 2400);
    servoAttached = true;
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_TOUCH_SENSOR, INPUT);

  bloomServo.attach(PIN_SERVO, 500, 2400);
  servoAttached = true;
  bloomServo.write(static_cast<int>(SERVO_ANGLE_CLOSED));
  delay(600);
  bloomServo.detach();
  servoAttached = false;

  Serial.println(F("\n=== 3D Reactive Blooming Plant Ready ==="));
  Serial.println(F("Touch the kawaii toadstool (or shine light) to bloom!"));
}

void loop() {
  const uint32_t now = millis();

  // 1. Read Capacitive Touch Sensor inside `sensor_toadstool` (with 50ms debounce)
  bool rawTouch = digitalRead(PIN_TOUCH_SENSOR) == HIGH;
  if (rawTouch != lastTouchReading && (now - lastDebounceMs) > 50) {
    lastDebounceMs = now;
    lastTouchReading = rawTouch;
    if (rawTouch && USE_TOUCH_TOGGLE) {
      touchLatchState = !touchLatchState;
      Serial.printf("[Sensor] Toadstool touched! Toggle state -> %s\n",
                    touchLatchState ? "SATISFIED (BLOOM)" : "DISSATISFIED (CLOSE)");
    }
  }

  // 2. Read Analog Condition (e.g. LDR Sunlight or Soil Moisture with hysteresis)
  int analogVal = analogRead(PIN_ANALOG_SENSE);
  bool analogSatisfied = isConditionSatisfied
                           ? (analogVal >= ANALOG_SATISFIED_LOW)
                           : (analogVal >= ANALOG_SATISFIED_HIGH);

  isConditionSatisfied = touchLatchState || analogSatisfied;
  startBloomTransition(isConditionSatisfied ? 1.0f : 0.0f);

  // 3. Non-Blocking Sine-Eased Servo Trajectory Update (20ms / 50Hz frame rate)
  if (isMoving) {
    uint32_t elapsed = now - transitionStartMs;
    float u = static_cast<float>(elapsed) / static_cast<float>(transitionDurMs);
    if (u >= 1.0f) {
      currentProgress = targetProgress;
      isMoving = false;
    } else {
      float eased = easeInOutSine(u);
      currentProgress = startProgress + (targetProgress - startProgress) * eased;
    }

    float servoDeg = SERVO_ANGLE_CLOSED + currentProgress * (SERVO_ANGLE_OPEN - SERVO_ANGLE_CLOSED);
    // Write microsecond pulse for sub-degree smoothness (500us = 0 deg, 2400us = 180 deg)
    int pulseUs = static_cast<int>(500.0f + (servoDeg / 180.0f) * 1900.0f);
    bloomServo.writeMicroseconds(pulseUs);

    // Detach servo 300ms after reaching target to prevent idle hum/power drain
    if (!isMoving && servoAttached) {
      delay(250);
      bloomServo.detach();
      servoAttached = false;
      Serial.printf("[Motion Complete] Plant is now %s (progress=%.2f)\n",
                    (currentProgress > 0.5f) ? "IN FULL BLOOM" : "CLOSED BUD", currentProgress);
    }
  }

  delay(20);
}
