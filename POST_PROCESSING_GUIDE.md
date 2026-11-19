# From Cheap Raw PLA to Museum Finish: Bambu A1 Post-Processing & Painting Field Guide

> **Goal of This Guide**: Turn fast (`0.20 mm` layer height), cheap, loud-colored standard PLA (*Traffic Red*, *Bright Yellow*, etc.) printed on a single-extruder **Bambu Lab A1** into objects that look like matte ceramic, anodized aluminum, carved porcelain, or cast antique brass—without 14-hour prints, sore fingers, or complicated gear.
>
> **Two Clear Tracks**:
> * **Track 1 (Start Here! — 100% Indoor, Zero Fumes, No Mask Needed)**: Tailored for **Bangalore (`28°C+` & seasonal humidity)** using cheap local water-based supplies from **Blinkit/Instamart, Itsy Bitsy, local hardware stores, or Amazon.in** (~₹800 total).
> * **Track 2 (Future Pro Upgrade — Balcony Spray Cans)**: Faster for large enclosures once you invest in a proper organic-vapor respirator.

---

## Section 1: Zero-Time Bambu Studio Slicer Wins (Fix 70% Before Touching Primer)

Dropping global layer height from `0.20 mm` to `0.08 mm` triples print time for almost zero benefit on vertical walls. Use these **targeted Bambu Studio (`0.40 mm` nozzle)** settings instead—they add only **`5–12%`** total time while dramatically upgrading raw surface quality:

| Bambu Studio Setting | Exact Value to Use | Why It Works |
| :--- | :--- | :--- |
| **Variable / Adaptive Layer Height** *(Top toolbar icon with horizontal lines)* | Click **Adaptive** (`Quality/Speed = 0.3`), then **Smooth** (`Radius = 5`) | Prints vertical walls at fast `0.20–0.24 mm`, dropping to `0.08 mm` **only** on shallow curved top domes where stair-stepping happens! |
| **Outer Wall Speed** *(Speed tab)* | **`50–60 mm/s`** *(leave Inner Wall at `200+ mm/s` & Infill fast!)* | Bambu's default `200 mm/s` outer wall changes speed around corners/holes, causing ugly **shiny-vs-matte horizontal bands**. Slowing *only* the outer wall adds ~3–5 mins and makes sheen 100% uniform. |
| **Wall Printing Order** *(Quality tab)* | **`Inner / Outer / Inner`** *(for non-extreme overhangs)* | Prints the visible outer perimeter against an already-solid inner wall with consistent cooling, eliminating dimensional bulges. |
| **Seam Position + Scarf Seam** *(Quality tab)* | **`Back`** or **`Aligned`** (+ enable **Contour Scarf Joint Seam** on cylinders!) | Hides the vertical zipper line in one clean shadow corner so you only ever have *one* line to touch up, or blends it seamlessly on round pots/tubes. |
| **Top Surface Ironing** *(Quality tab — flat mechanical faces only)* | **`Top Surfaces`**, Speed **`30 mm/s`**, Flow **`22%`**, Spacing **`0.15 mm`** | The hot nozzle glides over flat gear faces & plinth tops a second time, melting top extrusion lines into a glass-flat injection-molded sheet. |
| **Micro-Matte "Fuzzy Skin"** *(Others tab — optional architectural parts)* | **`Contour`**, Point Distance **`0.15 mm`**, Thickness **`0.08–0.10 mm`** | *(Skip if sanding smooth!)* Ultra-fine micro-texture scatters glossy light on cheap Traffic Red / Bright Yellow PLA and hides horizontal layer lines completely. |

---

## Section 2: Clean-Snap Supports & 30-Second Scar Rescue

Default grid supports weld onto PLA and rip chunks out of undersides. Change these **5 numbers** in Bambu Studio's **Support** tab and supports will pop off like crisp LEGO bricks:

### Clean-Release Bambu A1 Support Recipe (For `0.20 mm` Layer Height)
1. **Type**: **`Tree (auto)`** · **Style**: **`Tree Slim`** or **`Tree Organic`** (touches only minimal branch tips instead of scarring whole surfaces).
2. **Top Z Distance**: **`0.25 mm`** *(Default `0.20 mm` fuses too tightly on glossy standard PLA; `0.24–0.26 mm` snaps right off!)*
3. **Top Interface Layers**: **`3`**
4. **Top Interface Spacing**: **`0.15 mm`** · **Interface Pattern**: **`Concentric`** (leaves smooth swirl rings instead of jagged cross-hatch).
5. **Support / Object XY Distance**: **`0.45 mm`** + check **`Support on build plate only`** whenever possible so tree branches never scar lower details on your model!

### CAD Habit + Stress-Mark Fix
* **In CAD**: Never put a rounded **fillet** tangent to the print bed (the bottom $20^\circ$ is an $80^\circ$ mid-air overhang that always curls and scars!). Start every bottom edge with a **$45^\circ$ chamfer ($1.0\text{–}1.5\text{ mm}$)**, then transition into a fillet above $45^\circ$.
* **Erasing White Stress Marks**: Pulling supports off *Traffic Red* PLA leaves chalky white stress marks and tiny plastic hairs. **Do not dry-sand them raw**—wave a **hair dryer on hot / heat gun** (or a `0.5-second` distant pass with a lighter from `6 cm` away) across the scar: the white stress marks snap right back to original red and micro-hairs shrink instantly!

---

## Section 3: Track 1 (Start Here!) — The Easy Indoor Zero-Fume Bangalore Workflow

Why painting acrylic straight onto raw *Traffic Red* or *Bright Yellow* PLA frustrated you:
1. **Zero Tooth**: Raw PLA is slick non-porous plastic, so water-based acrylic beads up or scratches off corners.
2. **Capillary Gutter Effect**: Wet brushed paint wicks sideways down `0.20 mm` layer grooves, highlighting the lines.
3. **Color Bleed-Through**: Bright red and yellow bounce intense colored light right back through 2 coats of acrylic binder.

You can fix **all three indoors at your desk** with zero toxic solvents, zero masks, and zero humidity problems:

### Step 3A: Indoor Filling & Priming — **Water-Based Putty + Acrylic Gesso**
* **For Deep Layer Ridges & Support Scars (`Asian Paints TruCare Acrylic Wall Putty` — ~₹90 small tub at any hardware shop, or `Brustro Modeling Paste`)**:
  * Water-based, odorless, washes off fingers with tap water!
  * Dip your fingertip in water, rub a thin smear of **Acrylic Wall Putty** across curved domes or support scars, and let it dry **`20 mins`** at Bangalore room temp (`28°C+`).
* **For Priming & Blocking Red/Yellow (`White` + `Black Acrylic Gesso` — *Camlin*, *Brustro*, *Mont Marte*, or *Little Birdie*, ~₹180–₹280 at Itsy Bitsy / Amazon.in)**:
  * **What Gesso actually is**: Chalk/marble dust + high-opacity pigment + matte acrylic binder. Zero solvent fumes!
  * **How to apply with ZERO brush marks**: Tear off a corner of a **cosmetic foam makeup sponge** (~₹80 pack on Blinkit/Nykaa), dip lightly into Gesso, tap off excess, and **dab/stipple 2 thin coats** (`15 mins` apart).
  * **Color Rule**: Use **White Gesso** (or mix 1 drop black into White Gesso to make **Neutral Grey Gesso**!) before painting colors/pastels/ivory; use **Black Gesso** under all metallic gears and automaton frames! *(Optional hobby upgrade on Amazon.in: **Vallejo Polyurethane Surface Primer** squeeze bottle, ₹650, ultra-thin self-leveling water-based primer).*

### Step 3B: Lazy-Friendly Wet-Sanding (No Mask Needed, Tight Spots Solved!)
* **Why dry sandpaper ruined your print before**: PLA softens at **$55^\circ\text{C}$** (`27°C` above Bangalore room temp!). Three seconds of dry friction heats raw PLA into gummy rubber that tears into rough white fuzz.
* **The Easy Indoor Tools (Blinkit / Instamart / Hardware Shop — ~₹140 total)**:
  1. **4-Sided Foam Nail Buffer Block** (~₹90 on Blinkit/Instamart): Literally a multi-grit (`~240 / 400 / 800`) squishy foam sanding sponge that wraps effortlessly around curved domes without flat-spotting!
  2. **Cushioned Emery Nail Files** (~₹50): Flat, stiff, narrow sticks you can trim to a sharp point with scissors to slide straight into `2 mm` crevices and slots!
  3. **3M Waterproof ("Water-Paper") Sandpaper (`400` & `600` grit sheets, ₹25/sheet at any hardware/paint shop)**.
* **The 5-Minute Soapy-Bowl Routine**:
  * Keep a small bowl of **water + 1 drop of Vim/Pril dish liquid** on your desk.
  * Dip the foam nail buffer (or `400` water-paper wrapped over a sponge) into the soapy water and lightly glide in small circles over your **dry Putty / Gesso** (never bare unprimed PLA!).
  * **Zero Airborne Dust**: `99%` of sanded chalk/plastic stays trapped inside the wet soapy slurry—no respirator needed! Wipe clean with a damp tissue, let dry 5 mins, and stipple 1 thin final coat of Gesso if any red/yellow peaks peek through.

### Step 3C: Streak-Free Acrylic Painting in `28°C+` Bangalore Weather
1. **Turn OFF the Overhead Ceiling Fan While Painting + Build a 30-Second DIY Wet Palette**:
   * At `28–32°C` under a ceiling fan, acrylic paint skins over on a dry plate in 3 minutes—creating tiny half-dried crumbs that cause brush streaks!
   * **DIY Wet Palette**: Take a flat plastic takeaway/Tupperware lid $\rightarrow$ lay 2 folded wet tissues inside $\rightarrow$ press a square of white **kitchen butter/parchment paper** (*Oddy Ecobake*!) flat on top. Put your acrylic dabs on the parchment paper: moisture wicks up microscopically and keeps your paint creamy for hours!
2. **Thin to "Toned Milk" + Stipple or Soft Flat Brush**:
   * Mix ~`4 parts acrylic : 1 part water`. Either **foam-sponge stipple** 2 thin coats (`15 mins` apart) for an airbrushed satin look, or use a wide (`#8` or `#10`) **soft synthetic flat Taklon brush** (*Brustro / Camlin*).
3. **90-Second "Cast Brass / Iron" Automaton Metal (Indoors, Zero Fumes)**:
   * Stipple **Black Gesso** onto your gear/linkage and let dry `15 mins`.
   * **Option A (Best — ₹220 at Itsy Bitsy / Amazon.in)**: **Little Birdie Metallic Wax Paste (`Antique Gold`, `Rich Gold`, or `Vintage Bronze`)** — India's exact equivalent of *Rub 'n Buff*! Rub a rice-grain dab on your fingertip/tissue, wipe most off on cardboard, and lightly buff across raised spokes and $45^\circ$ bevels!
   * **Option B (₹35 Stationary-Shop Classic)**: **Fevicryl Pearl Metallic Gold / Bronze**—dip a flat brush, **wipe `95%` of the paint off onto a dry tissue** until the brush looks nearly dry, and lightly dust across the black gear edges (*dry-brushing*).
4. **Crevice Shadow Wash**:
   * Mix `1 drop` black/burnt-umber acrylic + `10 drops` water + a *tiny toothpick touch* of Vim dish soap. Touch your brush tip into panel grooves or around rivets—capillary action pulls crisp dark shadows into every recess automatically!
5. **Humidity-Proof Final Boss — Water-Based Matte Acrylic Varnish**:
   * **What to buy**: **Brustro / Camlin / Little Birdie Matte Acrylic Varnish** (~₹180–₹250 bottle).
   * **Why it beats spray cans in Bangalore**: Spray clear coats trap moisture and turn milky-white whenever Bangalore evening/monsoon humidity crosses `75%`! Sponge-stippling or brushing 1 thin pass (`5 parts varnish : 1 part water`) indoors has zero smell, never fogs in humidity, protects against scratches, and **erases uneven brushstroke sheen completely**!

---

## Section 4: Track 2 (Future Pro Upgrade) — Balcony Spray Cans & Mask Rules

Whenever you later want to batch-finish large enclosures in 60 seconds on your balcony, keep these two rules in mind:

### 1. Throw Out Old Unsealed Mask Cartridges — And Never Rely on an N95 for Spray Cans!
* **Old Painter's Masks**: Activated carbon cartridges start absorbing ambient moisture/VOCs the day their foil pouch is opened—after a few months sitting unsealed, they offer **zero fume protection**.
* **Particles vs. Fumes**: An **N95 / KN95 mask blocks `0%` of organic solvent vapors** (acetone, toluene, xylene in spray primers/paints pass straight through paper filters). Even on a breezy balcony, wind eddies swirl fumes back off building walls.
* **What to Buy When You Upgrade (~₹2,600–₹3,200 on Amazon.in)**: **`3M 6200` Half-Facepiece Reusable Respirator** + **`3M 6001` (Organic Vapor) + `5N11` Particulate Prefilters** (or **`3M 60921` Pink `P100 + OV` combo cartridges**), stored sealed inside a Ziploc freezer bag after every use.

### 2. Balcony Spray Cans & Bangalore Humidity Warning
* **High-Build Spray Filler Primer**: *Rust-Oleum 2-in-1 Filler & Sandable Primer* or *Bosny / Samurai Grey Epoxi/Surfacer Primer* (widely sold in Bangalore auto/bike paint shops!). Shake 2 full minutes; spray `20–25 cm` away inside a tipped cardboard shipping box; leave outside on the balcony `25–30 mins` until odor-free before bringing indoors.
* **Humidity Limit (`< 75%` RH)**: Only spray aerosol clear coats during dry sunny mid-day/afternoon hours (`11 AM – 4 PM` in Bangalore)—never during rain or damp nights, or solvent chill will condense humid air into a cloudy white haze ("blushing").

---

## Section 5: Copy-Paste Starter Shopping List (~₹850 Indoor Bangalore Kit)

Everything below is non-toxic, odorless indoors, and available on **Blinkit/Instamart, Itsy Bitsy, local hardware stores, or Amazon.in**:

1. **White Acrylic Gesso** + **Black Acrylic Gesso** (*Brustro / Camlin / Little Birdie*) — ~₹380 for both
2. **Asian Paints TruCare Acrylic Wall Putty** (small `500g` tub at any hardware shop, or *Brustro Modeling Paste*) — ~₹90
3. **4-Sided Foam Nail Buffer Block** + **Pack of Emery Nail Files** + **Foam Makeup Sponges** (Blinkit/Nykaa) — ~₹200
4. **2 Sheets Waterproof Sandpaper** (`400` & `600` grit at local hardware shop) — ~₹50
5. **Little Birdie Metallic Wax Paste (`Antique Gold`)** *(or ₹35 **Fevicryl Pearl Metallic Gold**)* — ~₹35–₹220
6. **Water-Based Matte Acrylic Varnish** (*Brustro / Camlin / Little Birdie*) — ~₹200
