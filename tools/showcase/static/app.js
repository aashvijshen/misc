/**
 * Maker Deck & Pricing Studio — Decluttered Mobile-First Logic (v4)
 */
(function () {
  "use strict";

  const PRIVATE_CFG_KEY = "maker_deck_private_cfg_v1";

  const state = {
    catalog: { settings: {}, spools: [], items: [], orders: [] },
    activeView: "deck",        // "deck" | "calc" | "ops"
    selectedCalcSlug: null,
    selectedVariant: {},       // slug -> variantId
    selectedSwatches: {},      // slug -> Set(spoolId)

    // Product Sheet & Modal state
    sheetSlug: null,
    sheetSlideIdx: 0,
    mediaMgrOpen: false,
    shareMode: "card",         // "card" | "raw"
    upiSplitMode: "full",      // "full" | "half" | "custom"
    privateCfg: loadPrivateCfg(),
  };

  function loadPrivateCfg() {
    try {
      const raw = localStorage.getItem(PRIVATE_CFG_KEY);
      if (raw) return JSON.parse(raw);
    } catch (_) {}
    return { payeeName: "Aashvij", upiId: "", countryCode: "91" };
  }

  function savePrivateCfgToStorage() {
    localStorage.setItem(PRIVATE_CFG_KEY, JSON.stringify(state.privateCfg));
  }

  function formatINR(num) {
    const n = Math.round(Number(num) || 0);
    const sign = n < 0 ? "-" : "";
    return sign + "₹" + Math.abs(n).toLocaleString("en-IN");
  }

  function formatSignedINR(num) {
    const n = Math.round(Number(num) || 0);
    return (n >= 0 ? "+" : "-") + "₹" + Math.abs(n).toLocaleString("en-IN");
  }

  function formatSignedPct(pct) {
    const val = Number(pct) || 0;
    return (val >= 0 ? "+" : "") + val.toFixed(1) + "%";
  }

  function roundToCleanPrice(val) {
    if (val <= 250) return Math.max(99, Math.ceil(val / 50) * 50 - 1);
    return Math.round(val / 50) * 50 - 1;
  }

  function showToast(msg) {
    const el = document.getElementById("app-toast");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => {
      el.hidden = true;
    }, 2200);
  }

  function getSpoolMap() {
    const map = {};
    for (const s of state.catalog.spools || []) map[s.id] = s;
    return map;
  }

  function getActiveVariant(item) {
    if (!item.variants || item.variants.length === 0) return null;
    const wanted = state.selectedVariant[item.slug] || item.variants[0].id;
    return item.variants.find((v) => v.id === wanted) || item.variants[0];
  }

  function getEffectiveItem(item) {
    const v = getActiveVariant(item);
    return {
      variant: v,
      price: Number(v ? v.price : item.price) || 0,
      dimensions: v ? v.dimensions : item.dimensions,
      filamentGrams: Number(v ? v.filamentGrams : item.filamentGrams) || 0,
      printHours: Number(v ? v.printHours : item.printHours) || 0,
    };
  }

  function computeEconomics(item) {
    const cfg = state.catalog.settings || {};
    const eff = getEffectiveItem(item);

    const plaPerKg = Number(item.filamentRatePerKg || cfg.defaultFilamentPerKg || 1350);
    const wastePct = Number(cfg.wasteBufferPct ?? 8);
    const machinePerHr = Number(cfg.printerWearPerHr ?? 14) + Number(cfg.electricityPerHr ?? 1);
    const laborPerHr = Number(cfg.craftLaborPerHr ?? 450);
    const wrapCost = Number(cfg.giftWrapCost ?? 20);

    const gramsBuffered = eff.filamentGrams * (1 + wastePct / 100);
    const filamentCost = (gramsBuffered / 1000) * plaPerKg;
    const bomCost = (item.bom || []).reduce((acc, r) => acc + (Number(r.cost) || 0), 0);
    const machineCost = eff.printHours * machinePerHr;
    const hardCogs = filamentCost + bomCost + machineCost + wrapCost;

    const batch = Math.max(1, Number(item.batchSize) || 1);
    const swapMins = ((Number(item.plateSwaps) || 1) * 3.0) / batch;
    const paintFactor = batch > 1 ? 0.7 : 1.0;
    const activeMins =
      swapMins + (Number(item.assemblyMins) || 0) + (Number(item.paintingMins) || 0) * paintFactor;
    const laborCost = (activeMins / 60) * laborPerHr;
    const totalCostWithLabor = hardCogs + laborCost;

    const price = eff.price;
    const grossProfit = price - hardCogs;
    const grossMarginPct = price > 0 ? (grossProfit / price) * 100 : 0;

    const netProfit = price - totalCostWithLabor;
    const netMarginPct = price > 0 ? (netProfit / price) * 100 : 0;

    const suggestedPrice = roundToCleanPrice(Math.max(totalCostWithLabor * 1.45, hardCogs * 2.75));

    return {
      price,
      filamentCost,
      bomCost,
      machineCost,
      hardCogs,
      activeMins,
      laborCost,
      totalCostWithLabor,
      grossProfit,
      grossMarginPct,
      netProfit,
      netMarginPct,
      suggestedPrice,
    };
  }

  function getItemMedia(item) {
    return (item.media || []).filter((m) => !m.isDiagnostic);
  }

  function getSelectedColors(item) {
    const spoolMap = getSpoolMap();
    const sel = state.selectedSwatches[item.slug];
    if (!sel || sel.size === 0) return [];
    return Array.from(sel)
      .map((id) => (spoolMap[id] ? spoolMap[id].name : ""))
      .filter(Boolean);
  }

  function buildConciseMessage(item, includeUpi) {
    const eff = getEffectiveItem(item);
    const title = eff.variant ? `${item.name} (${eff.variant.name})` : item.name;
    const parts = [];
    if (eff.dimensions && eff.dimensions !== "—") parts.push(eff.dimensions);
    if (item.summary) parts.push(item.summary);
    const colors = getSelectedColors(item);
    if (colors.length > 0) parts.push(colors.join(" + "));

    let msg = `${title} — ${formatINR(eff.price)}`;
    if (parts.length > 0) {
      msg += `\n${parts.join(" · ")}`;
    }
    if (includeUpi && state.privateCfg.upiId) {
      msg += `\nUPI: ${state.privateCfg.upiId}`;
    }
    return msg;
  }

  /* ========================================================================
     API Sync
     ======================================================================== */

  async function fetchCatalog() {
    const res = await fetch("/api/catalog");
    if (!res.ok) throw new Error("Failed to load catalog");
    state.catalog = await res.json();
    initDefaults();
    renderAll();
  }

  async function persistCatalog(toastMsg) {
    try {
      const res = await fetch("/api/catalog", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(state.catalog),
      });
      if (res.ok && toastMsg) showToast(toastMsg);
    } catch (_) {}
  }

  function initDefaults() {
    const items = state.catalog.items || [];
    if (!state.selectedCalcSlug && items.length > 0) {
      state.selectedCalcSlug = items[0].slug;
    }
    for (const it of items) {
      if (it.variants && it.variants.length > 0 && !state.selectedVariant[it.slug]) {
        state.selectedVariant[it.slug] = it.variants[0].id;
      }
      if (!state.selectedSwatches[it.slug]) {
        state.selectedSwatches[it.slug] = new Set();
      }
    }
  }

  function renderAll() {
    if (state.catalog.settings && state.catalog.settings.studioName) {
      document.getElementById("studio-brand-title").textContent = state.catalog.settings.studioName;
    }
    renderDeckView();
    renderCalcView();
    renderOpsView();
    if (!document.getElementById("modal-item").hidden && state.sheetSlug) {
      renderItemSheetContent(state.sheetSlug);
    }
  }

  /* ========================================================================
     Reusable Scroll-Snap Media Carousel Builder
     ======================================================================== */

  function buildSnapCarousel(mediaList, initialIdx, onSlideChange) {
    const frag = document.createDocumentFragment();
    const track = document.createElement("div");
    track.className = "snap-track";

    if (!mediaList || mediaList.length === 0) {
      const empty = document.createElement("div");
      empty.className = "snap-slide";
      empty.innerHTML = `<div class="empty-media-placeholder">No photos yet · Tap ✎ Media to add</div>`;
      track.appendChild(empty);
      frag.appendChild(track);
      return { frag, track };
    }

    mediaList.forEach((m) => {
      const slide = document.createElement("div");
      slide.className = "snap-slide";
      if (m.kind === "video") {
        const vid = document.createElement("video");
        vid.src = m.url;
        vid.autoplay = true;
        vid.loop = true;
        vid.muted = true;
        vid.playsInline = true;
        vid.setAttribute("playsinline", "");
        slide.appendChild(vid);
        const badge = document.createElement("span");
        badge.className = "motion-badge";
        badge.textContent = "VIDEO";
        slide.appendChild(badge);
      } else {
        const img = document.createElement("img");
        img.src = m.url;
        img.alt = m.label || "";
        img.loading = "lazy";
        slide.appendChild(img);
        if (m.kind === "gif" || m.url.toLowerCase().endsWith(".gif")) {
          const badge = document.createElement("span");
          badge.className = "motion-badge";
          badge.textContent = "GIF";
          slide.appendChild(badge);
        }
      }
      track.appendChild(slide);
    });

    frag.appendChild(track);

    if (mediaList.length > 1) {
      const dots = document.createElement("div");
      dots.className = "dots-bar";
      mediaList.forEach((_, idx) => {
        const d = document.createElement("span");
        d.className = "dot" + (idx === initialIdx ? " active" : "");
        dots.appendChild(d);
      });
      frag.appendChild(dots);

      track.addEventListener(
        "scroll",
        () => {
          const w = track.clientWidth || 1;
          const idx = Math.round(track.scrollLeft / w);
          Array.from(dots.children).forEach((d, i) => d.classList.toggle("active", i === idx));
          if (onSlideChange) onSlideChange(idx);
        },
        { passive: true }
      );
    }

    if (initialIdx > 0) {
      requestAnimationFrame(() => {
        track.scrollLeft = initialIdx * track.clientWidth;
      });
    }

    return { frag, track };
  }

  /* ========================================================================
     VIEW 1: MINIMAL DECK GRID (Photo + Name + Price Only)
     ======================================================================== */

  function renderDeckView() {
    const grid = document.getElementById("deck-grid");
    grid.innerHTML = "";

    const deckItems = (state.catalog.items || []).filter((i) => i.inDeck);

    for (const item of deckItems) {
      const eff = getEffectiveItem(item);
      const mediaList = getItemMedia(item);

      const card = document.createElement("article");
      card.className = "deck-card";
      card.id = `deck-card-${item.slug}`;

      const carouselBox = document.createElement("div");
      carouselBox.className = "snap-carousel-wrap";
      const { frag, track } = buildSnapCarousel(mediaList, 0, null);
      carouselBox.appendChild(frag);
      card.appendChild(carouselBox);

      const footer = document.createElement("div");
      footer.className = "deck-card-footer";
      footer.innerHTML = `
        <h2 class="deck-card-title">${escapeHtml(item.name)}</h2>
        <span class="deck-card-price">${formatINR(eff.price)}</span>
      `;
      card.appendChild(footer);

      // Distinguish horizontal swipe from tap
      let startX = 0;
      let startY = 0;
      card.addEventListener(
        "pointerdown",
        (e) => {
          startX = e.clientX;
          startY = e.clientY;
        },
        { passive: true }
      );
      card.addEventListener("click", (e) => {
        if (Math.abs(e.clientX - startX) > 12 || Math.abs(e.clientY - startY) > 12) return;
        const w = track.clientWidth || 1;
        const currentSlide = Math.round(track.scrollLeft / w);
        openItemSheet(item.slug, currentSlide);
      });

      grid.appendChild(card);
    }
  }

  /* ========================================================================
     PRODUCT SHEET + PHOTO / GIF / VIDEO MANAGER
     ======================================================================== */

  function openItemSheet(slug, initialSlide) {
    state.sheetSlug = slug;
    state.sheetSlideIdx = initialSlide || 0;
    state.mediaMgrOpen = false;
    renderItemSheetContent(slug);
    document.getElementById("modal-item").hidden = false;
  }

  function renderItemSheetContent(slug) {
    const item = (state.catalog.items || []).find((i) => i.slug === slug);
    if (!item) return;

    const eff = getEffectiveItem(item);
    const mediaList = getItemMedia(item);
    state.sheetSlideIdx = Math.min(state.sheetSlideIdx, Math.max(0, mediaList.length - 1));

    document.getElementById("item-sheet-title").textContent = item.name;
    document.getElementById("item-sheet-price").textContent = formatINR(eff.price);
    document.getElementById("item-sheet-dims").textContent =
      eff.dimensions && eff.dimensions !== "—" ? eff.dimensions : "";

    const sumEl = document.getElementById("item-sheet-summary");
    sumEl.textContent = item.summary || "";
    sumEl.hidden = !item.summary;

    // Carousel
    const carEl = document.getElementById("item-sheet-carousel");
    carEl.innerHTML = "";
    const { frag } = buildSnapCarousel(mediaList, state.sheetSlideIdx, (idx) => {
      state.sheetSlideIdx = idx;
    });
    carEl.appendChild(frag);

    // Media Manager Drawer
    const mgrEl = document.getElementById("item-media-manager");
    mgrEl.hidden = !state.mediaMgrOpen;
    const stripEl = document.getElementById("item-media-strip");
    stripEl.innerHTML = "";
    if (state.mediaMgrOpen) {
      mediaList.forEach((m, idx) => {
        const thumb = document.createElement("div");
        thumb.className = "media-thumb-card";
        if (m.kind === "video") {
          const v = document.createElement("video");
          v.src = m.url;
          v.muted = true;
          v.playsInline = true;
          thumb.appendChild(v);
        } else {
          const im = document.createElement("img");
          im.src = m.url;
          im.alt = m.label || "";
          thumb.appendChild(im);
        }

        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "thumb-del-btn";
        delBtn.title = "Delete from gallery";
        delBtn.textContent = "✕";
        delBtn.addEventListener("click", async (ev) => {
          ev.stopPropagation();
          await deleteMediaItem(item.slug, m.url);
        });
        thumb.appendChild(delBtn);

        const covBtn = document.createElement("button");
        covBtn.type = "button";
        covBtn.className = "thumb-cover-btn" + (idx === 0 ? " is-cover" : "");
        covBtn.textContent = idx === 0 ? "★ Cover" : "Set Cover";
        covBtn.addEventListener("click", async (ev) => {
          ev.stopPropagation();
          if (idx === 0) return;
          await setCoverMediaItem(item.slug, m.url);
        });
        thumb.appendChild(covBtn);

        stripEl.appendChild(thumb);
      });
    }

    // Variants
    const varEl = document.getElementById("item-sheet-variants");
    varEl.innerHTML = "";
    if (item.variants && item.variants.length > 0) {
      varEl.hidden = false;
      for (const v of item.variants) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "seg-pill" + (eff.variant && eff.variant.id === v.id ? " active" : "");
        b.textContent = `${v.name} · ${formatINR(v.price)}`;
        b.addEventListener("click", () => {
          state.selectedVariant[item.slug] = v.id;
          if (typeof v.heroMediaIndex === "number" && v.heroMediaIndex < mediaList.length) {
            state.sheetSlideIdx = v.heroMediaIndex;
          }
          renderAll();
        });
        varEl.appendChild(b);
      }
    } else {
      varEl.hidden = true;
    }

    // Color Dots
    const swEl = document.getElementById("item-sheet-swatches");
    swEl.innerHTML = "";
    const spoolMap = getSpoolMap();
    const selSet = state.selectedSwatches[item.slug] || new Set();
    for (const sid of item.swatches || []) {
      const sp = spoolMap[sid];
      if (!sp) continue;
      const dot = document.createElement("button");
      dot.type = "button";
      dot.className =
        "swatch-dot" + (selSet.has(sid) ? " selected" : "") + (!sp.inStock ? " out" : "");
      dot.style.backgroundColor = sp.hex;
      dot.title = sp.name;
      dot.addEventListener("click", () => {
        if (!state.selectedSwatches[item.slug]) state.selectedSwatches[item.slug] = new Set();
        if (state.selectedSwatches[item.slug].has(sid)) state.selectedSwatches[item.slug].delete(sid);
        else state.selectedSwatches[item.slug].add(sid);
        renderItemSheetContent(slug);
      });
      swEl.appendChild(dot);
    }
    swEl.hidden = swEl.children.length === 0;
  }

  async function deleteMediaItem(slug, url) {
    const res = await fetch("/api/delete_media", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug, url }),
    });
    if (res.ok) {
      const data = await res.json();
      state.catalog = data.catalog;
      state.sheetSlideIdx = 0;
      renderAll();
      showToast("Removed media");
    }
  }

  async function setCoverMediaItem(slug, url) {
    const res = await fetch("/api/set_cover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug, url }),
    });
    if (res.ok) {
      const data = await res.json();
      state.catalog = data.catalog;
      state.sheetSlideIdx = 0;
      renderAll();
      showToast("Updated cover");
    }
  }

  /* ========================================================================
     VIEW 2: COST CALCULATOR + LIVE PROFIT / LOSS MARGIN %
     ======================================================================== */

  function renderCalcView() {
    const items = state.catalog.items || [];
    const cfg = state.catalog.settings || {};

    document.getElementById("global-pla-rate").value = cfg.defaultFilamentPerKg ?? 1350;
    document.getElementById("global-waste-pct").value = cfg.wasteBufferPct ?? 8;
    document.getElementById("global-machine-hr").value =
      Number(cfg.printerWearPerHr ?? 14) + Number(cfg.electricityPerHr ?? 1);
    document.getElementById("global-labor-hr").value = cfg.craftLaborPerHr ?? 450;

    const listEl = document.getElementById("calc-project-list");
    listEl.innerHTML = "";
    for (const it of items) {
      const ec = computeEconomics(it);
      const b = document.createElement("button");
      b.type = "button";
      b.className = "proj-item-btn" + (state.selectedCalcSlug === it.slug ? " active" : "");
      b.innerHTML = `
        <div style="min-width:0;">
          <div style="font-weight:600;font-size:0.84rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${escapeHtml(it.name)}</div>
          <div class="mono" style="font-size:0.72rem;color:var(--ink-muted);">${formatINR(ec.price)} · ${formatSignedPct(ec.netMarginPct)}</div>
        </div>
        <span class="badge-mini ${it.inDeck ? "live" : ""}">${it.inDeck ? "Deck" : "Draft"}</span>
      `;
      b.addEventListener("click", () => {
        state.selectedCalcSlug = it.slug;
        renderCalcView();
      });
      listEl.appendChild(b);
    }

    const active = items.find((i) => i.slug === state.selectedCalcSlug) || items[0];
    const panel = document.getElementById("calc-detail-panel");
    if (!active) {
      panel.innerHTML = "";
      return;
    }

    const eff = getEffectiveItem(active);
    const ec = computeEconomics(active);

    panel.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px;">
        <h2 style="margin:0;font-family:var(--font-display);font-size:1.15rem;">${escapeHtml(active.name)}</h2>
        <div style="display:flex;gap:8px;align-items:center;">
          <label style="display:inline-flex;align-items:center;gap:6px;font-size:0.8rem;font-weight:600;padding:6px 10px;border-radius:9px;background:var(--bg-subtle);cursor:pointer;">
            <input id="calc-toggle-indeck" type="checkbox" ${active.inDeck ? "checked" : ""} />
            <span>Show in Deck</span>
          </label>
          <button id="btn-use-suggested" class="icon-pill" type="button" title="Set price to suggested ${formatINR(ec.suggestedPrice)}">
            Suggested: ${formatINR(ec.suggestedPrice)}
          </button>
        </div>
      </div>

      ${
        active.variants && active.variants.length > 0
          ? `<div id="calc-variant-pills" class="segmented-pills"></div>`
          : ""
      }

      <!-- Live Profit / Loss & Margin % Tiles -->
      <div id="calc-margin-tiles" class="margin-grid"></div>

      <div class="inputs-grid">
        <div class="field">
          <label for="ci-price">Selling Price (₹)</label>
          <input id="ci-price" class="mono" type="number" step="10" min="1" value="${eff.price}" style="font-weight:700;border-color:var(--border-strong);" />
        </div>
        <div class="field">
          <label for="ci-grams">Filament (g)</label>
          <input id="ci-grams" class="mono" type="number" step="1" min="1" value="${eff.filamentGrams}" />
        </div>
        <div class="field">
          <label for="ci-pla-rate">Spool (₹/kg)</label>
          <input id="ci-pla-rate" class="mono" type="number" step="50" min="300" value="${active.filamentRatePerKg || cfg.defaultFilamentPerKg || 1350}" />
        </div>
        <div class="field">
          <label for="ci-hours">Print Time (h)</label>
          <input id="ci-hours" class="mono" type="number" step="0.2" min="0.1" value="${eff.printHours}" />
        </div>
        <div class="field">
          <label for="ci-swaps">Plates / Swaps</label>
          <input id="ci-swaps" class="mono" type="number" step="1" min="1" value="${active.plateSwaps || 1}" />
        </div>
        <div class="field">
          <label for="ci-assembly">Assembly (m)</label>
          <input id="ci-assembly" class="mono" type="number" step="1" min="0" value="${active.assemblyMins || 0}" />
        </div>
        <div class="field">
          <label for="ci-painting">Painting (m)</label>
          <input id="ci-painting" class="mono" type="number" step="5" min="0" value="${active.paintingMins || 0}" />
        </div>
        <div class="field">
          <label for="ci-batch">Batch Size</label>
          <input id="ci-batch" class="mono" type="number" step="1" min="1" value="${active.batchSize || 1}" />
        </div>
      </div>

      <div class="inputs-grid" style="grid-template-columns:1fr 2fr;">
        <div class="field">
          <label for="ci-dims">Dimensions</label>
          <input id="ci-dims" type="text" value="${escapeAttr(eff.dimensions || "")}" />
        </div>
        <div class="field">
          <label for="ci-summary">One-Line Note</label>
          <input id="ci-summary" type="text" value="${escapeAttr(active.summary || "")}" placeholder="e.g. Hand-painted base · LED tealight included" />
        </div>
      </div>

      <div style="display:flex;justify-content:space-between;align-items:center;margin:12px 0 8px;">
        <strong style="font-size:0.84rem;">Hardware &amp; Paint BOM</strong>
        <button id="btn-add-bom" class="icon-pill" type="button" style="height:30px;font-size:0.75rem;">+ BOM Item</button>
      </div>
      <div id="calc-bom-list"></div>
    `;

    function updateMarginTilesOnly() {
      const m = computeEconomics(active);
      const tilesEl = document.getElementById("calc-margin-tiles");
      if (!tilesEl) return;
      tilesEl.innerHTML = `
        <div class="metric-tile">
          <div class="metric-label">Hard Cost (COGS)</div>
          <div class="metric-big">${formatINR(m.hardCogs)}</div>
          <div class="metric-sub">PLA ${formatINR(m.filamentCost)} + BOM ${formatINR(m.bomCost)}</div>
        </div>
        <div class="metric-tile">
          <div class="metric-label">Total Cost (w/ Labor)</div>
          <div class="metric-big">${formatINR(m.totalCostWithLabor)}</div>
          <div class="metric-sub">+${Math.round(m.activeMins)}m craft (${formatINR(m.laborCost)})</div>
        </div>
        <div class="metric-tile ${m.grossProfit >= 0 ? "profit" : "loss"}">
          <div class="metric-label">Margin (vs. COGS)</div>
          <div class="metric-big">${formatSignedPct(m.grossMarginPct)}</div>
          <div class="metric-sub">${formatSignedINR(m.grossProfit)} / unit</div>
        </div>
        <div class="metric-tile ${m.netProfit >= 0 ? "profit" : "loss"}">
          <div class="metric-label">Net Margin (w/ Labor)</div>
          <div class="metric-big">${formatSignedPct(m.netMarginPct)}</div>
          <div class="metric-sub">${formatSignedINR(m.netProfit)} net</div>
        </div>
      `;
    }

    updateMarginTilesOnly();

    if (active.variants && active.variants.length > 0) {
      const vpBox = document.getElementById("calc-variant-pills");
      for (const v of active.variants) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "seg-pill" + (eff.variant && eff.variant.id === v.id ? " active" : "");
        b.textContent = v.name;
        b.addEventListener("click", () => {
          state.selectedVariant[active.slug] = v.id;
          renderCalcView();
        });
        vpBox.appendChild(b);
      }
    }

    // BOM rows
    const bomBox = document.getElementById("calc-bom-list");
    (active.bom || []).forEach((row, idx) => {
      const div = document.createElement("div");
      div.className = "bom-row";
      div.innerHTML = `
        <input type="text" value="${escapeAttr(row.name)}" data-bom-name="${idx}" style="padding:6px 9px;border-radius:8px;border:1px solid var(--border-hairline);background:var(--bg-canvas);" />
        <input type="number" class="mono" value="${row.cost}" step="1" min="0" data-bom-cost="${idx}" style="padding:6px 9px;border-radius:8px;border:1px solid var(--border-hairline);background:var(--bg-canvas);" />
        <button type="button" class="icon-pill" data-bom-del="${idx}" style="padding:0;">✕</button>
      `;
      bomBox.appendChild(div);
    });

    document.getElementById("calc-toggle-indeck").addEventListener("change", (e) => {
      active.inDeck = e.target.checked;
      persistCatalog(active.inDeck ? "Shown in Deck" : "Moved to Drafts");
      renderAll();
    });

    document.getElementById("btn-use-suggested").addEventListener("click", () => {
      const sug = computeEconomics(active).suggestedPrice;
      if (eff.variant) eff.variant.price = sug;
      active.price = sug;
      persistCatalog("Updated price");
      renderAll();
    });

    const bindLiveInput = (id, applyFn) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener("input", () => {
        applyFn(el.value);
        updateMarginTilesOnly();
      });
      el.addEventListener("change", () => {
        applyFn(el.value);
        persistCatalog("Saved");
        renderDeckView();
      });
    };

    bindLiveInput("ci-price", (val) => {
      const n = Math.max(0, Math.round(Number(val) || 0));
      if (eff.variant) eff.variant.price = n;
      else active.price = n;
      if (eff.variant && active.variants[0].id === eff.variant.id) active.price = n;
    });
    bindLiveInput("ci-grams", (val) => {
      const n = Math.max(1, Number(val) || 1);
      if (eff.variant) eff.variant.filamentGrams = n;
      else active.filamentGrams = n;
    });
    bindLiveInput("ci-pla-rate", (val) => (active.filamentRatePerKg = Math.max(200, Number(val) || 1350)));
    bindLiveInput("ci-hours", (val) => {
      const n = Math.max(0.1, Number(val) || 0.5);
      if (eff.variant) eff.variant.printHours = n;
      else active.printHours = n;
    });
    bindLiveInput("ci-swaps", (val) => (active.plateSwaps = Math.max(1, Number(val) || 1)));
    bindLiveInput("ci-assembly", (val) => (active.assemblyMins = Math.max(0, Number(val) || 0)));
    bindLiveInput("ci-painting", (val) => (active.paintingMins = Math.max(0, Number(val) || 0)));
    bindLiveInput("ci-batch", (val) => (active.batchSize = Math.max(1, Number(val) || 1)));
    bindLiveInput("ci-dims", (val) => {
      if (eff.variant) eff.variant.dimensions = val.trim();
      else active.dimensions = val.trim();
    });
    bindLiveInput("ci-summary", (val) => (active.summary = val.trim()));

    document.getElementById("btn-add-bom").addEventListener("click", () => {
      active.bom = active.bom || [];
      active.bom.push({ name: "Item", cost: 20 });
      persistCatalog();
      renderCalcView();
    });

    bomBox.querySelectorAll("[data-bom-name]").forEach((inp) => {
      inp.addEventListener("change", () => {
        active.bom[Number(inp.getAttribute("data-bom-name"))].name = inp.value;
        persistCatalog();
      });
    });
    bomBox.querySelectorAll("[data-bom-cost]").forEach((inp) => {
      inp.addEventListener("input", () => {
        active.bom[Number(inp.getAttribute("data-bom-cost"))].cost = Math.max(0, Number(inp.value) || 0);
        updateMarginTilesOnly();
      });
      inp.addEventListener("change", () => persistCatalog("Saved BOM"));
    });
    bomBox.querySelectorAll("[data-bom-del]").forEach((btn) => {
      btn.addEventListener("click", () => {
        active.bom.splice(Number(btn.getAttribute("data-bom-del")), 1);
        persistCatalog();
        renderCalcView();
      });
    });
  }

  /* ========================================================================
     VIEW 3: ORDERS QUEUE & IN-STOCK SPOOLS
     ======================================================================== */

  function renderOpsView() {
    const ordersBox = document.getElementById("orders-list-container");
    const orders = state.catalog.orders || [];
    ordersBox.innerHTML = "";

    if (orders.length === 0) {
      ordersBox.innerHTML = `<p style="margin:0;font-size:0.83rem;color:var(--ink-muted);">No queued orders.</p>`;
    } else {
      orders.forEach((ord, idx) => {
        const div = document.createElement("div");
        div.className = "order-row";
        div.innerHTML = `
          <div>
            <div style="font-weight:600;font-size:0.88rem;">${escapeHtml(ord.buyer)} · ${escapeHtml(ord.itemName)}</div>
            <div class="mono" style="font-size:0.76rem;color:var(--ink-secondary);">${formatINR(ord.price)}${ord.colors ? " · " + escapeHtml(ord.colors) : ""}</div>
          </div>
          <div style="display:flex;gap:5px;align-items:center;">
            <select data-ord-paid="${idx}" style="padding:4px 7px;border-radius:7px;border:1px solid var(--border-hairline);background:var(--bg-surface);font-size:0.75rem;">
              ${["Unpaid", "50% Adv", "Paid"]
                .map((s) => `<option value="${s}" ${ord.paid === s ? "selected" : ""}>${s}</option>`)
                .join("")}
            </select>
            <select data-ord-stage="${idx}" style="padding:4px 7px;border-radius:7px;border:1px solid var(--border-hairline);background:var(--bg-surface);font-size:0.75rem;">
              ${["Queued", "Printing", "Painting", "Done"]
                .map((s) => `<option value="${s}" ${ord.stage === s ? "selected" : ""}>${s}</option>`)
                .join("")}
            </select>
            <button type="button" class="icon-pill" data-ord-del="${idx}" style="height:28px;min-width:28px;padding:0;">✕</button>
          </div>
        `;
        ordersBox.appendChild(div);
      });

      ordersBox.querySelectorAll("[data-ord-paid]").forEach((s) =>
        s.addEventListener("change", () => {
          orders[Number(s.getAttribute("data-ord-paid"))].paid = s.value;
          persistCatalog();
        })
      );
      ordersBox.querySelectorAll("[data-ord-stage]").forEach((s) =>
        s.addEventListener("change", () => {
          orders[Number(s.getAttribute("data-ord-stage"))].stage = s.value;
          persistCatalog();
        })
      );
      ordersBox.querySelectorAll("[data-ord-del]").forEach((b) =>
        b.addEventListener("click", () => {
          orders.splice(Number(b.getAttribute("data-ord-del")), 1);
          persistCatalog();
          renderOpsView();
        })
      );
    }

    const spoolsBox = document.getElementById("spools-grid-container");
    spoolsBox.innerHTML = "";
    (state.catalog.spools || []).forEach((sp, idx) => {
      const lbl = document.createElement("label");
      lbl.className = "spool-chip-btn";
      lbl.innerHTML = `
        <span style="display:flex;align-items:center;gap:7px;">
          <span style="width:14px;height:14px;border-radius:50%;background:${sp.hex};border:1px solid var(--border-strong);"></span>
          <span>${escapeHtml(sp.name)}</span>
        </span>
        <input type="checkbox" data-spool-idx="${idx}" ${sp.inStock ? "checked" : ""} />
      `;
      spoolsBox.appendChild(lbl);
    });

    spoolsBox.querySelectorAll("[data-spool-idx]").forEach((chk) => {
      chk.addEventListener("change", () => {
        const sp = state.catalog.spools[Number(chk.getAttribute("data-spool-idx"))];
        sp.inStock = chk.checked;
        persistCatalog();
      });
    });
  }

  /* ========================================================================
     SHARE COMPOSER (Stamped Price Card + Raw Photo / GIF / Video Share)
     ======================================================================== */

  async function openShareModal(slug) {
    const item = (state.catalog.items || []).find((i) => i.slug === slug);
    if (!item) return;

    const mediaList = getItemMedia(item);
    const activeMedia = mediaList[state.sheetSlideIdx] || mediaList[0] || null;

    // Default to Original Media if the user is viewing a video or GIF clip
    if (activeMedia && (activeMedia.kind === "video" || activeMedia.kind === "gif")) {
      state.shareMode = "raw";
    } else {
      state.shareMode = "card";
    }

    document.getElementById("share-caption-text").value = buildConciseMessage(item, false);
    document.getElementById("modal-share").hidden = false;
    await refreshSharePreview();
  }

  async function refreshSharePreview() {
    const item = (state.catalog.items || []).find((i) => i.slug === state.sheetSlug);
    if (!item) return;

    document.getElementById("share-mode-card").classList.toggle("active", state.shareMode === "card");
    document.getElementById("share-mode-raw").classList.toggle("active", state.shareMode === "raw");

    const stage = document.getElementById("share-preview-stage");
    const mediaList = getItemMedia(item);
    const activeMedia = mediaList[state.sheetSlideIdx] || mediaList[0] || null;

    if (state.shareMode === "raw" && activeMedia) {
      stage.innerHTML = "";
      if (activeMedia.kind === "video") {
        const v = document.createElement("video");
        v.src = activeMedia.url;
        v.autoplay = true;
        v.loop = true;
        v.muted = true;
        v.playsInline = true;
        stage.appendChild(v);
      } else {
        const im = document.createElement("img");
        im.src = activeMedia.url;
        stage.appendChild(im);
      }
      document.getElementById("btn-copy-card-img").hidden = activeMedia.kind === "video";
      return;
    }

    document.getElementById("btn-copy-card-img").hidden = false;
    stage.innerHTML = `<canvas id="quote-card-canvas" width="900" height="1040"></canvas>`;
    const canvas = document.getElementById("quote-card-canvas");
    await drawMinimalQuoteCard(canvas, item, activeMedia);
  }

  async function drawMinimalQuoteCard(canvas, item, activeMedia) {
    const ctx = canvas.getContext("2d");
    const W = 900;
    const H = 1040;
    canvas.width = W;
    canvas.height = H;

    const eff = getEffectiveItem(item);

    ctx.fillStyle = "#F7F4EF";
    ctx.fillRect(0, 0, W, H);

    const pad = 32;
    const imgW = W - pad * 2;
    const imgH = 820;

    ctx.save();
    roundRectPath(ctx, pad, pad, imgW, imgH, 22);
    ctx.clip();
    ctx.fillStyle = "#E8E2D8";
    ctx.fillRect(pad, pad, imgW, imgH);

    const imgCandidate =
      activeMedia && activeMedia.kind !== "video"
        ? activeMedia
        : getItemMedia(item).find((m) => m.kind !== "video");

    if (imgCandidate) {
      try {
        const img = await loadImage(imgCandidate.url);
        const scale = Math.max(imgW / img.naturalWidth, imgH / img.naturalHeight);
        const dw = img.naturalWidth * scale;
        const dh = img.naturalHeight * scale;
        ctx.drawImage(img, pad + (imgW - dw) / 2, pad + (imgH - dh) / 2, dw, dh);
      } catch (_) {}
    }
    ctx.restore();

    // Clean footer: Name + Price on one row, short summary + dots below
    const title = eff.variant ? `${item.name} (${eff.variant.name})` : item.name;
    ctx.fillStyle = "#1D1916";
    ctx.font = "600 36px Georgia, serif";
    ctx.fillText(truncateText(ctx, title, W - pad * 2 - 220), pad, 922);

    const priceStr = formatINR(eff.price);
    ctx.fillStyle = "#C64E2A";
    ctx.font = "700 40px 'JetBrains Mono', monospace";
    const pw = ctx.measureText(priceStr).width;
    ctx.fillText(priceStr, W - pad - pw, 922);

    ctx.fillStyle = "#6B635B";
    ctx.font = "500 22px -apple-system, BlinkMacSystemFont, sans-serif";
    const subParts = [];
    if (eff.dimensions && eff.dimensions !== "—") subParts.push(eff.dimensions);
    if (item.summary) subParts.push(item.summary);
    ctx.fillText(truncateText(ctx, subParts.join(" · "), W - pad * 2), pad, 968);

    const spoolMap = getSpoolMap();
    let sx = pad;
    for (const sid of (item.swatches || []).slice(0, 6)) {
      const sp = spoolMap[sid];
      if (!sp) continue;
      ctx.beginPath();
      ctx.arc(sx + 11, 1004, 11, 0, Math.PI * 2);
      ctx.fillStyle = sp.hex;
      ctx.fill();
      ctx.strokeStyle = "#BDB4A7";
      ctx.lineWidth = 2;
      ctx.stroke();
      sx += 30;
    }
  }

  function loadImage(src) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => resolve(img);
      img.onerror = reject;
      img.src = src;
    });
  }

  function canvasToBlob(canvas) {
    return new Promise((resolve) => canvas.toBlob(resolve, "image/png", 0.95));
  }

  /* ========================================================================
     WHATSAPP & OFFLINE UPI QR MODALS
     ======================================================================== */

  function openWhatsAppModal(slug) {
    const item = (state.catalog.items || []).find((i) => i.slug === slug);
    if (!item) return;
    const incl = document.getElementById("wa-include-upi");
    incl.checked = Boolean(state.privateCfg.upiId);
    document.getElementById("wa-message-box").value = buildConciseMessage(item, incl.checked);
    document.getElementById("modal-whatsapp").hidden = false;
  }

  function getUpiAmount(item) {
    const base = getEffectiveItem(item).price;
    if (state.upiSplitMode === "half") return Math.ceil(base * 0.5);
    if (state.upiSplitMode === "custom") {
      return Math.max(1, Math.round(Number(document.getElementById("upi-custom-amount").value) || base));
    }
    return base;
  }

  function buildUpiUri(item, amount) {
    const pa = (state.privateCfg.upiId || "your-upi-id@okicici").trim();
    const pn = encodeURIComponent((state.privateCfg.payeeName || "Aashvij").trim());
    const tn = encodeURIComponent(item.name.slice(0, 36));
    return `upi://pay?pa=${encodeURIComponent(pa)}&pn=${pn}&am=${amount.toFixed(2)}&cu=INR&tn=${tn}`;
  }

  function openUpiModal(slug) {
    const item = (state.catalog.items || []).find((i) => i.slug === slug);
    if (!item) return;
    state.upiSplitMode = "full";
    document.getElementById("upi-custom-amount").value = getEffectiveItem(item).price;
    document.getElementById("modal-upi").hidden = false;
    refreshUpiQr();
  }

  function refreshUpiQr() {
    const item = (state.catalog.items || []).find((i) => i.slug === state.sheetSlug);
    if (!item) return;

    const hasUpi = Boolean(state.privateCfg.upiId && state.privateCfg.upiId.includes("@"));
    document.getElementById("upi-missing-banner").hidden = hasUpi;
    document.getElementById("upi-custom-row").hidden = state.upiSplitMode !== "custom";

    ["full", "half", "custom"].forEach((m) =>
      document.getElementById(`upi-split-${m}`).classList.toggle("active", state.upiSplitMode === m)
    );

    const amount = getUpiAmount(item);
    const uri = buildUpiUri(item, amount);
    document.getElementById("upi-qr-svg-container").innerHTML = window.LocalQR.toSVG(uri, {
      margin: 2,
      dark: "#1B1917",
      light: "#FFFFFF",
    });
    document.getElementById("upi-qr-amount-display").textContent = formatINR(amount);
    document.getElementById("upi-qr-note-display").textContent = hasUpi
      ? `${item.name} · ${state.privateCfg.upiId}`
      : `${item.name} · Preview (set UPI ID above)`;
  }

  /* ========================================================================
     Global Event Listeners
     ======================================================================== */

  function bindGlobalEvents() {
    // View Switcher
    document.querySelectorAll(".nav-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.activeView = btn.getAttribute("data-view");
        document.querySelectorAll(".nav-tab").forEach((b) => b.classList.toggle("active", b === btn));
        document.getElementById("view-deck").hidden = state.activeView !== "deck";
        document.getElementById("view-calc").hidden = state.activeView !== "calc";
        document.getElementById("view-ops").hidden = state.activeView !== "ops";
        renderAll();
      });
    });

    // Dim Toggle
    document.getElementById("btn-theme-toggle").addEventListener("click", (e) => {
      const root = document.documentElement;
      const isDim = root.getAttribute("data-theme") === "dim";
      root.setAttribute("data-theme", isDim ? "light" : "dim");
      e.currentTarget.textContent = isDim ? "Dim" : "Light";
    });

    // Close modals
    document.querySelectorAll("[data-close-modal]").forEach((b) =>
      b.addEventListener("click", () => {
        document.getElementById(b.getAttribute("data-close-modal")).hidden = true;
      })
    );
    document.querySelectorAll(".modal-backdrop").forEach((bd) =>
      bd.addEventListener("click", (e) => {
        if (e.target === bd) bd.hidden = true;
      })
    );

    // Product Sheet actions
    document.getElementById("btn-toggle-media-mgr").addEventListener("click", () => {
      state.mediaMgrOpen = !state.mediaMgrOpen;
      if (state.sheetSlug) renderItemSheetContent(state.sheetSlug);
    });

    document.getElementById("btn-upload-media").addEventListener("click", () => {
      const inp = document.getElementById("hidden-media-input");
      inp.value = "";
      inp.click();
    });

    document.getElementById("hidden-media-input").addEventListener("change", async (e) => {
      const files = Array.from(e.target.files || []);
      if (!files.length || !state.sheetSlug) return;
      showToast(`Uploading ${files.length} file(s)...`);

      for (const f of files) {
        const qs = `slug=${encodeURIComponent(state.sheetSlug)}&filename=${encodeURIComponent(f.name)}`;
        const res = await fetch(`/api/upload_media?${qs}`, {
          method: "POST",
          headers: { "Content-Type": f.type || "application/octet-stream" },
          body: f,
        });
        if (res.ok) {
          const data = await res.json();
          state.catalog = data.catalog;
        }
      }
      state.sheetSlideIdx = 0;
      renderAll();
      showToast("Added to gallery!");
    });

    document.getElementById("btn-sheet-share").addEventListener("click", () => {
      if (state.sheetSlug) openShareModal(state.sheetSlug);
    });
    document.getElementById("btn-sheet-whatsapp").addEventListener("click", () => {
      if (state.sheetSlug) openWhatsAppModal(state.sheetSlug);
    });
    document.getElementById("btn-sheet-upi").addEventListener("click", () => {
      if (state.sheetSlug) openUpiModal(state.sheetSlug);
    });

    // Share Sheet controls
    document.getElementById("share-mode-card").addEventListener("click", () => {
      state.shareMode = "card";
      refreshSharePreview();
    });
    document.getElementById("share-mode-raw").addEventListener("click", () => {
      state.shareMode = "raw";
      refreshSharePreview();
    });

    document.getElementById("btn-native-share").addEventListener("click", async () => {
      const item = (state.catalog.items || []).find((i) => i.slug === state.sheetSlug);
      if (!item) return;
      const caption = document.getElementById("share-caption-text").value;
      const mediaList = getItemMedia(item);
      const activeMedia = mediaList[state.sheetSlideIdx] || mediaList[0] || null;

      let fileToShare = null;
      let blobToFallback = null;
      let fallbackName = `${item.slug}.png`;

      if (state.shareMode === "raw" && activeMedia) {
        const res = await fetch(activeMedia.url);
        blobToFallback = await res.blob();
        const ext = activeMedia.url.split(".").pop() || "jpg";
        fallbackName = `${item.slug}.${ext}`;
        fileToShare = new File([blobToFallback], fallbackName, {
          type: blobToFallback.type || "application/octet-stream",
        });
      } else {
        const canvas = document.getElementById("quote-card-canvas");
        blobToFallback = await canvasToBlob(canvas);
        fallbackName = `${item.slug}_price.png`;
        fileToShare = new File([blobToFallback], fallbackName, { type: "image/png" });
      }

      if (navigator.canShare && navigator.canShare({ files: [fileToShare] })) {
        try {
          await navigator.share({ files: [fileToShare], text: caption });
          return;
        } catch (err) {
          if (err.name === "AbortError") return;
        }
      }

      if (blobToFallback.type === "image/png" && navigator.clipboard && window.ClipboardItem) {
        try {
          await navigator.clipboard.write([new ClipboardItem({ "image/png": blobToFallback })]);
          showToast("Copied image! Paste (Ctrl+V) in chat");
          return;
        } catch (_) {}
      }
      downloadBlob(blobToFallback, fallbackName);
      showToast(`Downloaded ${fallbackName}`);
    });

    document.getElementById("btn-copy-card-img").addEventListener("click", async () => {
      const canvas = document.getElementById("quote-card-canvas");
      if (!canvas) return;
      const blob = await canvasToBlob(canvas);
      if (navigator.clipboard && window.ClipboardItem) {
        try {
          await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
          showToast("Image copied to clipboard");
          return;
        } catch (_) {}
      }
      downloadBlob(blob, `${state.sheetSlug || "quote"}.png`);
      showToast("Downloaded PNG");
    });

    document.getElementById("btn-copy-share-text").addEventListener("click", async () => {
      await navigator.clipboard.writeText(document.getElementById("share-caption-text").value);
      showToast("Copied text");
    });

    // WhatsApp Modal
    document.getElementById("wa-include-upi").addEventListener("change", (e) => {
      const item = (state.catalog.items || []).find((i) => i.slug === state.sheetSlug);
      if (item) {
        document.getElementById("wa-message-box").value = buildConciseMessage(item, e.target.checked);
      }
    });

    document.getElementById("btn-launch-whatsapp").addEventListener("click", () => {
      const digits = document.getElementById("wa-recipient-phone").value.replace(/\D/g, "");
      const msg = document.getElementById("wa-message-box").value;
      const full = digits.length === 10 ? (state.privateCfg.countryCode || "91") + digits : digits;
      const url = full
        ? `https://wa.me/${full}?text=${encodeURIComponent(msg)}`
        : `https://api.whatsapp.com/send?text=${encodeURIComponent(msg)}`;
      window.open(url, "_blank", "noopener");
    });

    document.getElementById("btn-log-from-wa").addEventListener("click", () => {
      const item = (state.catalog.items || []).find((i) => i.slug === state.sheetSlug);
      if (!item) return;
      const eff = getEffectiveItem(item);
      const buyer = document.getElementById("wa-buyer-name").value.trim() || "Walk-in";
      state.catalog.orders = state.catalog.orders || [];
      state.catalog.orders.unshift({
        buyer,
        itemName: eff.variant ? `${item.name} (${eff.variant.name})` : item.name,
        price: eff.price,
        colors: getSelectedColors(item).join(" + "),
        paid: "Unpaid",
        stage: "Queued",
      });
      persistCatalog("Added to Queue");
      document.getElementById("modal-whatsapp").hidden = true;
    });

    // UPI Modal
    document.getElementById("btn-save-quick-upi").addEventListener("click", () => {
      const val = document.getElementById("upi-quick-id-input").value.trim();
      if (!val.includes("@")) {
        showToast("Enter valid UPI ID (e.g. name@okicici)");
        return;
      }
      state.privateCfg.upiId = val;
      savePrivateCfgToStorage();
      refreshUpiQr();
      showToast("UPI ID saved");
    });

    ["full", "half", "custom"].forEach((m) =>
      document.getElementById(`upi-split-${m}`).addEventListener("click", () => {
        state.upiSplitMode = m;
        refreshUpiQr();
      })
    );
    document.getElementById("upi-custom-amount").addEventListener("input", refreshUpiQr);

    document.getElementById("btn-copy-upi-uri").addEventListener("click", async () => {
      const item = (state.catalog.items || []).find((i) => i.slug === state.sheetSlug);
      if (!item) return;
      await navigator.clipboard.writeText(buildUpiUri(item, getUpiAmount(item)));
      showToast("Copied upi:// link");
    });

    document.getElementById("btn-share-upi-card").addEventListener("click", async () => {
      const item = (state.catalog.items || []).find((i) => i.slug === state.sheetSlug);
      if (!item) return;
      const amt = getUpiAmount(item);
      const uri = buildUpiUri(item, amt);
      const c = document.createElement("canvas");
      c.width = 680;
      c.height = 800;
      const ctx = c.getContext("2d");
      ctx.fillStyle = "#FFFFFF";
      ctx.fillRect(0, 0, 680, 800);
      ctx.fillStyle = "#1D1916";
      ctx.font = "600 28px Georgia, serif";
      const t = truncateText(ctx, item.name, 580);
      ctx.fillText(t, (680 - ctx.measureText(t).width) / 2, 85);
      window.LocalQR.drawOnCanvas(ctx, uri, 140, 120, 400, { margin: 2 });
      const aStr = formatINR(amt);
      ctx.fillStyle = "#C64E2A";
      ctx.font = "700 48px 'JetBrains Mono', monospace";
      ctx.fillText(aStr, (680 - ctx.measureText(aStr).width) / 2, 595);
      if (state.privateCfg.upiId) {
        ctx.fillStyle = "#6B635B";
        ctx.font = "500 20px 'JetBrains Mono', monospace";
        ctx.fillText(state.privateCfg.upiId, (680 - ctx.measureText(state.privateCfg.upiId).width) / 2, 645);
      }
      const blob = await canvasToBlob(c);
      const file = new File([blob], `${item.slug}_upi.png`, { type: "image/png" });
      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        try {
          await navigator.share({ files: [file], text: `${item.name} — ${formatINR(amt)}` });
          return;
        } catch (err) {
          if (err.name === "AbortError") return;
        }
      }
      if (navigator.clipboard && window.ClipboardItem) {
        try {
          await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
          showToast("Copied QR image!");
          return;
        } catch (_) {}
      }
      downloadBlob(blob, `${item.slug}_upi.png`);
    });

    // Settings
    document.getElementById("btn-open-settings").addEventListener("click", () => {
      document.getElementById("cfg-payee-name").value = state.privateCfg.payeeName || "";
      document.getElementById("cfg-upi-id").value = state.privateCfg.upiId || "";
      document.getElementById("cfg-country-code").value = state.privateCfg.countryCode || "91";
      document.getElementById("modal-settings").hidden = false;
    });
    document.getElementById("btn-save-private-cfg").addEventListener("click", () => {
      state.privateCfg.payeeName = document.getElementById("cfg-payee-name").value.trim() || "Aashvij";
      state.privateCfg.upiId = document.getElementById("cfg-upi-id").value.trim();
      state.privateCfg.countryCode = document.getElementById("cfg-country-code").value.replace(/\D/g, "") || "91";
      savePrivateCfgToStorage();
      document.getElementById("modal-settings").hidden = true;
      showToast("Saved");
    });

    // Shop defaults & Rescan
    const bindRate = (id, fn) =>
      document.getElementById(id).addEventListener("change", (e) => {
        fn(Number(e.target.value));
        persistCatalog("Saved defaults");
        renderCalcView();
      });
    bindRate("global-pla-rate", (v) => (state.catalog.settings.defaultFilamentPerKg = Math.max(300, v || 1350)));
    bindRate("global-waste-pct", (v) => (state.catalog.settings.wasteBufferPct = Math.max(0, v || 0)));
    bindRate("global-machine-hr", (v) => {
      state.catalog.settings.printerWearPerHr = Math.max(0, (v || 15) - 1);
      state.catalog.settings.electricityPerHr = 1;
    });
    bindRate("global-labor-hr", (v) => (state.catalog.settings.craftLaborPerHr = Math.max(0, v || 0)));

    document.getElementById("btn-rescan-projects").addEventListener("click", async () => {
      const res = await fetch("/api/rescan", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        state.catalog = data.catalog;
        renderAll();
        showToast("Synced STLs & media");
      }
    });

    // Manual new order
    document.getElementById("btn-new-order").addEventListener("click", () => {
      const first = (state.catalog.items || []).find((i) => i.inDeck) || state.catalog.items[0];
      if (!first) return;
      const buyer = prompt("Buyer name:");
      if (buyer === null) return;
      state.catalog.orders = state.catalog.orders || [];
      state.catalog.orders.unshift({
        buyer: buyer.trim() || "Walk-in",
        itemName: first.name,
        price: getEffectiveItem(first).price,
        colors: "",
        paid: "Unpaid",
        stage: "Queued",
      });
      persistCatalog("Order added");
      renderOpsView();
    });
  }

  /* ========================================================================
     Helpers
     ======================================================================== */

  function roundRectPath(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function truncateText(ctx, str, maxW) {
    if (ctx.measureText(str).width <= maxW) return str;
    let s = str;
    while (s.length > 0 && ctx.measureText(s + "…").width > maxW) s = s.slice(0, -1);
    return s + "…";
  }

  function downloadBlob(blob, filename) {
    const u = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = u;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(u), 1000);
  }

  function escapeHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escapeAttr(s) {
    return escapeHtml(s).replace(/'/g, "&#39;");
  }

  // Bump SW cache version so old v1 CSS/JS never lingers
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.getRegistrations().then((regs) => regs.forEach((r) => r.update()));
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }

  bindGlobalEvents();
  fetchCatalog().catch(console.error);
})();
