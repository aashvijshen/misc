# BloomCore v2: Bill of Materials (BOM), Setup Guide & Product Sellability Notes

Cross-reference: See [`PROJECT_LOG.md`](PROJECT_LOG.md) for full part dimensions, clearances, and iteration history, and `previews/diagnostic_views.png` for the 4-panel assembly & X-ray views.

---

## 1. India Bill of Materials (BOM) & Verified Supplier Links

Estimated single-unit electronics + hardware BOM is **~₹460–₹560**, plus ~145g of PLA/PETG filament (**~₹190–₹230**) $\rightarrow$ **~₹680–₹790 total unit COGS**.

| # | Component | Spec & CAD Fit Notes | Est. Cost / Plant | Supplier Links (India) |
|---|---|---|---|---|
| 1 | **Microcontroller** | **ESP32-C3 SuperMini** (`22.52 × 18.00 mm`, Native USB-C, Wi-Fi + BLE). *Buy the unsoldered-header variant so wires solder flush and clear the `Z = 7.9 mm` floor trough.* | ~₹190–₹240 | [Robu (Unsoldered)](https://robu.in/product/pro-mini-wifi-bluetooth-development-board-pin/) · [Robu (Soldered)](https://robu.in/product/esp32-c3-development-board-with-soldering/) · [Amazon.in](https://www.amazon.in/s?k=ESP32-C3+SuperMini) |
| 2 | **Micro Servo** | **MG90S Metal Gear** *(recommended—resists gear stripping if petals are bumped)* or **SG90** (`22.8 × 12.2 mm` body; uses included single-arm horn + 2 mounting screws on `actuator_sled_sg90`). | ~₹95 (SG90) – ₹165 (MG90S) | [Robu (MG90S Metal Gear)](https://robu.in/product/mg90s-9g-servo-metal-gear/) · [Robu (SG90)](https://robu.in/product/sg-90-9g-mini-micro-servo-plastic-gear/) |
| 3 | **Toadstool Switch** *(Pick A or B)* | **Option A (Product Feel):** **Gateron Pro 3.0 Yellow/Brown MX Switch** (`14 × 14 mm` snap frame in `switch_carrier`; `+` cross stem mates directly with `toadstool_spots`). Sold in 10-packs (~₹300/pack).<br>**Option B (Bench Fallback):** **`6×6×5 mm` Tactile Push Button** (fits lower `6.35 × 6.35 mm` pocket of `switch_carrier`). | ~₹30/plant *(MX)*<br>or ₹3/plant *(Tactile)* | [Meckeys (Gateron Pro 3.0 10-Pack)](https://meckeys.com/shop/accessories/keyboard-accessories/key-switches/gateron-g-pro-3-0-switch/) · [Robu (6×6×5mm Tactile Pack)](https://robu.in/product/6x6x5mm-tactile-push-button-switch-pack-of-20/) |
| 4 | **Stamen Glow LED** | **WS2812B 5050 RGB Addressable Pixel** (mini breakout or 1 pixel cut from a 5V non-waterproof WS2812B strip; trim copper pad edges slightly to seat inside the $\varnothing 9.2\text{ mm}$ diffuser dome of `stamen_crown`). | ~₹15–₹35 | [Robu (WS2812B Module)](https://robu.in/product/ws2812b-rgb-addressable-led-module/) · [Robu (CJMCU-123)](https://robu.in/product/cjmcu-123-ws2811-rgb-led-breakout-module/) |
| 5 | **Flexible Stem Wire** | **28 AWG or 30 AWG Silicone Stranded Wire** (3× ~22 cm leads routed through the `+Y` duct of `flower_stem`; ultra-limp silicone prevents wire stiffness or fatigue across the $10\text{ mm}$ stroke). | ~₹20 | [Robu (24–30 AWG Silicone Wires)](https://robu.in/product-category/24-to-30-awg/) |
| 6 | **Crank Roller Pin** | **`M2 × 8 mm` Machine Screw + Nut** (mounted through the servo horn hole at $R = 14.5\text{ mm}$ to ride inside the `2.90 mm` horizontal Scotch-Yoke slot of `bottom_plunger`). | ~₹5 | [Amazon.in (M2 Screw Assortment)](https://www.amazon.in/s?k=M2+screw+nut+assortment) / Local hardware |
| 7 | **Feet & Heft Ballast** | **4× `10 mm` Self-Adhesive Silicone Bumper Pads** (recessed into the 4 bun feet of `pot_base`) + **~120–150g of M10/M12 Steel Washers or ₹2/₹5 Coins** (stacked in the 2 ballast cups of `core_cartridge`). | ~₹40 | [Amazon.in (10mm Silicone Bumpers)](https://www.amazon.in/s?k=10mm+self+adhesive+silicone+bumper+pads) |
| 8 | **Optional Light Sensor** | **5mm LDR Photoresistor + 10kΩ Pull-Down Resistor** (enables morning auto-wake & evening sleep via `GPIO0`). | ~₹10 | [Robu (5mm LDR)](https://robu.in/product-category/light-dependant-resistors-ldr/) |
| 9 | **USB-C Power Cable** | Braided **USB-C Cable** (5V $\ge 1\text{ A}$). | ~₹99 | [Amazon.in (Braided USB-C Cable)](https://www.amazon.in/s?k=braided+usb+c+cable+1m) |

---

## 2. Bambu Lab A1 Slicing, Wiring, Calibration & Assembly Guide

### 2.1 Slicing & Material Recommendations
1. **Zero-AMS 6-Plate Breakdown**: Slice single-color groups per Section 4 of [`PROJECT_LOG.md`](PROJECT_LOG.md) (`0.40 mm` nozzle, `0.42 mm` line width, `0.16 mm` layer height for inlays/petals, `0.20 mm` for structural parts).
2. **Material Selection for Snap-Fits**:
   - Print **Plate 4** (`pushrod`, `bottom_plunger`, `leaf_slider`, `stamen_hub`, `core_cartridge`, `actuator_sled_sg90`, `switch_carrier`) and C-clip parts (`stem_leaf`, `petal_inner`, `petal_outer`) in **PETG or Tough PLA+** so the $\varnothing 2.75\text{ mm}$ C-clip shafts flex cleanly through the `2.45 mm` snap throats without cracking.
   - Orient [`pushrod.stl`](pushrod.stl) **flat on its $3.2\text{ mm}$ side** on the PEI bed for continuous longitudinal strand strength and zero supports.
3. **Ceramic Stoneware Texture Trick**:
   - In Bambu Studio, enable **Fuzzy Skin** (`Contour`, `0.12 mm` point distance, `0.12 mm` thickness) on the exterior of [`pot_base.stl`](pot_base.stl) while masking out the inner $\varnothing 85\text{ mm}$ bore and front `eye_slider` dovetail track with a cylindrical modifier. This eliminates visible layer lines and gives the pot a boutique bisque-ceramic finish.

### 2.2 `ESP32-C3 SuperMini` Wiring Map
Solder flexible leads to the `ESP32-C3 SuperMini` before snapping it into `core_cartridge`:

| Module / Signal | `ESP32-C3 SuperMini` Pad | Notes |
|---|---|---|
| **MG90S / SG90 `+5V` (Red)** | `5V` (`VBUS`) | Powered directly from 5V USB-C rail |
| **MG90S / SG90 `GND` (Brown/Black)** | `GND` | Common ground |
| **MG90S / SG90 `Signal` (Orange/Yellow)** | **`GPIO2`** | 50 Hz microsecond-interpolated PWM |
| **Toadstool MX / Tactile Switch** | **`GPIO3`** & **`GND`** | Uses internal `INPUT_PULLUP` (`SWITCH_ACTIVE_HIGH = false`) |
| **Stamen `WS2812B` Pixel (`5V`, `GND`, `DIN`)** | `5V`, `GND`, **`GPIO4`** | 3× 30AWG silicone wires routed up the `+Y` stem duct |
| **Optional `LDR` Voltage Divider** | **`GPIO0` (`A0`)** | LDR to `3V3`, `10kΩ` pull-down to `GND` |
| **Reserved Expansion I2C Bus** | **`GPIO8` (`SDA`)**, **`GPIO9` (`SCL`)** | Pre-initialized for plug-in OLED "Garden Sign" or soil sensors |

### 2.3 Firmware Flashing & 90° Servo Horn Calibration
1. Open [`firmware/reactive_bloom.ino`](firmware/reactive_bloom.ino) in **Arduino IDE 2.x**:
   - Install board package **`esp32` by Espressif Systems** and select **`ESP32C3 Dev Module`** (enable **`USB CDC On Boot: Enabled`**).
   - Install libraries **`ESP32Servo`** and **`Adafruit NeoPixel`**.
   - *(Optional)* Enter your `WIFI_SSID` / `WIFI_PASS` at the top of the sketch; if left blank, the plant automatically hosts a `BloomCore-Plant` Wi-Fi hotspot (`http://192.168.4.1` or `http://bloom.local`).
2. **Center the Horn Before Final Assembly**:
   - Power the flashed ESP32-C3 with the servo plugged in **before attaching the plastic horn**.
   - Command mid-stroke (`writePlungerProgress(0.5f)` / `90.0°`), press the single-arm horn onto the spline pointing **strictly horizontal toward `+X` (pot center)**, and tighten its center hub screw.
   - Install the `M2 × 8 mm` screw + nut through the horn hole at **$R = 14.5\text{ mm}$** pointing forward (`-Y`) to act as the smooth Scotch-Yoke crank pin.

### 2.4 5-Minute Snap-Together Mechanical Assembly
1. **Pot Shell & Reactive Face**:
   - Press `2× blush_cheek` and `1× cat_mouth` into the front pockets of `pot_base`.
   - Lay `eye_faceplate` over `eye_slider` and slide the pair straight down from the top into `pot_base`'s front inner dovetail track. Stick 4× `10 mm` silicone bumper pads into the foot recesses.
2. **BloomCore Cartridge**:
   - Snap the wired `ESP32-C3 SuperMini` into the rear `+Y` floor cradle of `core_cartridge` (USB-C port facing out the rear arch).
   - Drop ~120–150g of M10/M12 steel washers or coins into the two floor ballast cups (prevents USB cable drag).
   - Screw the MG90S/SG90 onto `actuator_sled_sg90`, slide the sled down the `-X` vertical T-slot of `core_cartridge`, and drop `core_cartridge` into `pot_base`.
3. **Soil Plate, Toadstool & Sprout**:
   - Insert `bottom_plunger` into the underside guide bore of `soil_lid`.
   - Lower `soil_lid` onto `pot_base`'s 3 keyways while guiding the servo's M2 crank pin into `bottom_plunger`'s horizontal Scotch-Yoke slot and slipping the front C-jaw around `eye_slider`'s bottom lug.
   - Snap `moss_inlay` onto `soil_lid`, press `baby_sprout`'s stem through the right moss hole into `bottom_plunger`, and snap `switch_carrier` + MX/tactile switch + `toadstool_spots` + `sensor_toadstool` into the left bay.
4. **Twist-Lock Plant Topper**:
   - Thread `pushrod` (and the 3 silicone NeoPixel wires) up through `flower_stem`.
   - Through the rear `+Y` stipule window, click the 2× `stem_leaf` C-clip shafts into their sockets and snap `leaf_slider` onto `pushrod` (between its mid-stem index collars), capturing both leaf cam trunnions.
   - Slide `stamen_hub` onto the top T-head of `pushrod`, snap the 6 petals (`3× petal_inner` at `0°, 120°, 240°` and `3× petal_outer` at `60°, 180°, 300°`) straight down into the open-top calyx C-clips so their inner trunnions rest in `stamen_hub`'s open grooves, tuck the `WS2812B` pixel into `stamen_crown`, and click `stamen_crown` down onto `stamen_hub` to lock all 6 petals captive.
   - Hook the bottom T-foot of `pushrod` into `bottom_plunger`'s top T-slot, lower `flower_stem` into `soil_lid`, and **twist $45^\circ$ to lock**!

### 2.5 Standalone Controls & Web Companion
- **1× Toadstool Click**: Feed / Water plant (blooms to `100%`, happy `^ w ^` eyes, restarts active focus/hydration timer).
- **2× Toadstool Click**: Cycle timer preset (`1 blink` = Free Toggle, `2 blinks` = 25m Pomodoro, `3 blinks` = 50m Deep Work, `4 blinks` = 90m Hydration).
- **Long Press (`1.5s`)**: Toggle Sleep / Do-Not-Disturb Mode (`u w u` droopy eyes, closed bud, dim amber nightlight).
- **Mobile Web UI (`http://bloom.local` or `http://192.168.4.1`)**: View live health & streaks, set custom countdown minutes, switch **Plant Personality Profiles** (*Graceful Lotus, Snappy Flytrap, Shy Mimosa*), or trigger via HTTP webhooks (`POST /api/feed`, `/api/timer?min=25`).

---

## 3. Product Strategy & Sellability Assessment

### 3.1 Where We Stand Today (Prototype v1 vs. BloomCore v2)

| Product Dimension | Prototype v1 | BloomCore v2 | Why It Moved |
|---|---|---|---|
| **Visual Hook & Short-Form Video Appeal** | `4.0 / 10` | **`8.5 / 10`** | Compact ~180 mm baby-schema proportions, hidden stem linkages, bouncy MX mushroom, and synchronized `u w u` $\leftrightarrow$ `^ w ^` eyes + pop-up sprout create an instant 5-second Reel/TikTok hook. |
| **Product-Line / Repeat-Purchase Moat** | `1.0 / 10` | **`9.0 / 10`** | Standardized $\varnothing 16\text{ mm}$ twist-lock toppers, $\varnothing 85\text{ mm}$ swappable pot shells, modular soil bays, and multi-personality firmware enable high-margin (~80% GM) add-on SKUs. |
| **Small-Batch Print-Farm Economics** | `3.0 / 10` | **`8.0 / 10`** | ~₹700–₹790 total COGS, zero AMS purge waste, zero cut-filament pins, and ~5-minute snap assembly make a 25–100 unit Bambu A1 run viable at **₹2,499–₹3,499 ($39–$49)**. |
| **Physical Endurance & Tolerance Proof** | `0.0 / 10` | **`4.0 / 10`** *(CAD-verified)* | `0.0000 mm³` multi-pose Boolean simulation eliminated geometric lockups, **but** Unit #001 still needs real-world print validation across 200–500 cycles. |
| **Mainstream Non-Maker Retail Polish** | `2.0 / 10` | **`5.5 / 10`** | Two upgrades separate indie/Kickstarter beta from ₹4,999–₹5,999 ($69+) boutique retail: **0 dB silent stepper actuation** and a **plug-and-play carrier PCB**. |

### 3.2 Three Concrete Milestones to Commercial Launch
1. **Milestone 1 — Print & Burn-In Unit #001 (Validates Physics)**:
   - Print 1 complete unit on the Bambu Lab A1 and run 200+ full bloom/wilt cycles. Fine-tune 2–3 real-world clearances by $\pm 0.05\text{–}0.10\text{ mm}$ if needed (C-clip snap feel on your specific PETG spool, `eye_slider` track smoothness, MG90S torque margin).
2. **Milestone 2 — Silent Linear Stepper Sled (`actuator_sled_stepper`)**:
   - Evaluate MG90S gear sound in a silent work room. Design a drop-in replacement sled holding a tiny **N20 / $15\text{ mm}$ lead-screw stepper + silent `TMC2209` driver**—unlocking **0 dB whisper-silent continuous motion** with zero changes to the pot, soil, stem, or petals.
3. **Milestone 3 — ₹150 Carrier PCB + 3-SKU Launch Lineup**:
   - Replace hand-soldered point-to-point wires inside `core_cartridge` with a compact JLCPCB carrier board (USB-C ESP32-C3 + JST-XH plugs for actuator, switch, NeoPixel, and I2C soil sign).
   - Model **Topper SKU #2 (*Snappy Venus Flytrap*)** and **Shell SKU #2 (*Minimalist Fluted Stoneware Pot*)** so launch videos showcase a true modular ecosystem (*"1 Base, Endless Desk Companions"*).
