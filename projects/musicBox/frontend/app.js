/* ==========================================================================
   KIKKER-15 // ELECTRO-MECHANICAL COMB & PUNCH-TAPE WORKBENCH
   3-Column Edge-to-Edge Client Engine
   ========================================================================== */

(() => {
  'use strict';

  const PRINTED_LABELS = ['C', 'D', 'E', 'F', 'G', 'A', 'B', 'C', 'D', 'E', 'F', 'G', 'A', 'B', 'C'];
  const RELATIVE_SEMITONES = [0, 2, 4, 5, 7, 9, 11, 12, 14, 16, 17, 19, 21, 23, 24];
  const BOLD_COLS = new Set([2, 4, 6, 8, 10]); // E, G, B, D, F treble staff lines

  const state = {
    hardware: null,
    crateMode: 'song',
    searchResults: [],
    artistMatches: [],
    activeArtistId: null,
    activeArtistName: '',
    artistCatalogSongs: [],

    activeSong: null,
    arrangement: null,
    selectedTracks: null,
    startBeat: 0,
    endBeat: 32,
    transposeSemitones: null,
    accidentalMode: 'omit',
    rangeMode: 'fold_octave',
    mmPerBeat: 8.0,
    existingUsableMm: 412.0,
    existingGridMm: 2.0,
    autoResolveRepeats: true,
    manualEdits: [],

    checkedRows: new Set(),
    focusedRowIdx: 0,
    outputMode: 'punch', // 'punch' | 'a4'
    a4PageIndex: 0,

    // Mechanical Comb & Crank Animation State
    tineEnergy: new Float32Array(15),
    crankAngleRad: 0,
    manualCrankBeat: 0,
    isHandCranking: false,

    // WebAudio Engine State
    audioCtx: null,
    scheduledNodes: [],
    scheduledTimers: [],
    isPlaying: false,
    playMode: null,
    playStartAudioTime: 0,
    playDurationBeats: 0,
    playBpm: 120,
    animFrameId: null,
    currentPlayBeatOffset: null,
  };

  const el = {
    vfdSongReadout: document.getElementById('vfdSongReadout'),
    vfdScaleReadout: document.getElementById('vfdScaleReadout'),
    vfdFootageReadout: document.getElementById('vfdFootageReadout'),

    playKikkerlandBtn: document.getElementById('playKikkerlandBtn'),
    playOriginalBtn: document.getElementById('playOriginalBtn'),
    stopAudioBtn: document.getElementById('stopAudioBtn'),
    playbackBpmInput: document.getElementById('playbackBpmInput'),

    crateTabSong: document.getElementById('crateTabSong'),
    crateTabArtist: document.getElementById('crateTabArtist'),
    crateTabImport: document.getElementById('crateTabImport'),
    cratePaneSong: document.getElementById('cratePaneSong'),
    cratePaneArtist: document.getElementById('cratePaneArtist'),
    cratePaneImport: document.getElementById('cratePaneImport'),

    searchForm: document.getElementById('searchForm'),
    songSearchInput: document.getElementById('songSearchInput'),
    artistFilterInput: document.getElementById('artistFilterInput'),
    searchSourceSelect: document.getElementById('searchSourceSelect'),
    searchSubmitBtn: document.getElementById('searchSubmitBtn'),
    searchStatusMsg: document.getElementById('searchStatusMsg'),
    searchResultsGrid: document.getElementById('searchResultsGrid'),

    artistSearchForm: document.getElementById('artistSearchForm'),
    artistCatalogQueryInput: document.getElementById('artistCatalogQueryInput'),
    artistSearchBtn: document.getElementById('artistSearchBtn'),
    artistStatusMsg: document.getElementById('artistStatusMsg'),
    artistMatchesBar: document.getElementById('artistMatchesBar'),
    artistCatalogFilterWrap: document.getElementById('artistCatalogFilterWrap'),
    catalogLiveFilterInput: document.getElementById('catalogLiveFilterInput'),
    artistCatalogGrid: document.getElementById('artistCatalogGrid'),

    fileUploadInput: document.getElementById('fileUploadInput'),
    directMidiUrlInput: document.getElementById('directMidiUrlInput'),
    loadMidiUrlBtn: document.getElementById('loadMidiUrlBtn'),
    customAbcTextarea: document.getElementById('customAbcTextarea'),
    loadAbcTextBtn: document.getElementById('loadAbcTextBtn'),

    fitOneStripBtn: document.getElementById('fitOneStripBtn'),
    selectAllBeatsBtn: document.getElementById('selectAllBeatsBtn'),
    trackPickerWrap: document.getElementById('trackPickerWrap'),
    trackListContainer: document.getElementById('trackListContainer'),

    sliceDurationReadout: document.getElementById('sliceDurationReadout'),
    totalBeatsReadout: document.getElementById('totalBeatsReadout'),
    overviewWrap: document.getElementById('overviewWrap'),
    overviewCanvas: document.getElementById('overviewCanvas'),
    startBeatInput: document.getElementById('startBeatInput'),
    endBeatInput: document.getElementById('endBeatInput'),

    scaleStatusBanner: document.getElementById('scaleStatusBanner'),
    scaleBannerKicker: document.getElementById('scaleBannerKicker'),
    scaleBannerMessage: document.getElementById('scaleBannerMessage'),
    applyBestShiftBtn: document.getElementById('applyBestShiftBtn'),

    octDownBtn: document.getElementById('octDownBtn'),
    semiDownBtn: document.getElementById('semiDownBtn'),
    shiftValueDisplay: document.getElementById('shiftValueDisplay'),
    semiUpBtn: document.getElementById('semiUpBtn'),
    octUpBtn: document.getElementById('octUpBtn'),

    accidentalModeSelect: document.getElementById('accidentalModeSelect'),
    rangeModeSelect: document.getElementById('rangeModeSelect'),
    mmPerBeatInput: document.getElementById('mmPerBeatInput'),
    candidateChipsRow: document.getElementById('candidateChipsRow'),
    autoResolveRepeatsCheckbox: document.getElementById('autoResolveRepeatsCheckbox'),

    combStageWrap: document.getElementById('combStageWrap'),
    combMechCanvas: document.getElementById('combMechCanvas'),
    crankCanvas: document.getElementById('crankCanvas'),
    stripViewport: document.getElementById('stripViewport'),
    stripCanvas: document.getElementById('stripCanvas'),
    clearManualEditsBtn: document.getElementById('clearManualEditsBtn'),

    bayTabPunchGuide: document.getElementById('bayTabPunchGuide'),
    bayTabPrintA4: document.getElementById('bayTabPrintA4'),
    bayPanelPunchGuide: document.getElementById('bayPanelPunchGuide'),
    bayPanelPrintA4: document.getElementById('bayPanelPrintA4'),

    existingUsableMmInput: document.getElementById('existingUsableMmInput'),
    existingGridSpacingSelect: document.getElementById('existingGridSpacingSelect'),
    resetCheckedRowsBtn: document.getElementById('resetCheckedRowsBtn'),
    printChecklistBtn: document.getElementById('printChecklistBtn'),
    hudActiveCoord: document.getElementById('hudActiveCoord'),
    punchProgressText: document.getElementById('punchProgressText'),
    hudPinMatrix: document.getElementById('hudPinMatrix'),
    hudLandmarkReadout: document.getElementById('hudLandmarkReadout'),
    prevPunchRowBtn: document.getElementById('prevPunchRowBtn'),
    stampAndAdvanceBtn: document.getElementById('stampAndAdvanceBtn'),
    nextPunchRowBtn: document.getElementById('nextPunchRowBtn'),
    punchChecklistContainer: document.getElementById('punchChecklistContainer'),

    downloadA4PdfBtn: document.getElementById('downloadA4PdfBtn'),
    downloadA4SvgBtn: document.getElementById('downloadA4SvgBtn'),
    a4PageSelectWrap: document.getElementById('a4PageSelectWrap'),
    a4PageSelect: document.getElementById('a4PageSelect'),
    a4SvgContainer: document.getElementById('a4SvgContainer'),
  };

  /**
   * Dynamically scales the 15-tine steel comb and paper strip canvas to fill
   * the Center Bay width while preserving exact Kikkerland 41mm proportions!
   */
  function getStripGeom() {
    const stageW = (el.combStageWrap && el.combStageWrap.clientWidth) || 480;
    // Leave clean clearance on wide bays so the floating crank pod never overlaps tine #15
    const availableW = stageW > 520 ? stageW - 180 : stageW - 28;
    const width = Math.max(330, Math.min(760, Math.floor(availableW)));
    const leftMargin = Math.round(width * (6.5 / 41.0));
    const colSpacing = (width - 2 * leftMargin) / 14.0;
    const pxPerMm = Math.max(2.9, colSpacing / 5.2);
    const holeRadius = Math.max(4.6, Math.min(7.8, colSpacing * 0.25));
    return {
      width,
      leftMargin,
      colSpacing,
      topHeader: 34,
      bottomPad: 32,
      pxPerMm,
      holeRadius,
    };
  }

  // --------------------------------------------------------------------------
  // Network Helpers
  // --------------------------------------------------------------------------

  async function apiJson(url, options = {}) {
    const resp = await fetch(url, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`;
      try {
        const err = await resp.json();
        detail = err.detail || detail;
      } catch (_) {}
      throw new Error(detail);
    }
    return resp.json();
  }

  function buildArrangePayload(extra = {}) {
    return {
      song_id: state.activeSong.song_id,
      selected_tracks: state.selectedTracks,
      start_beat: state.startBeat,
      end_beat: state.endBeat,
      transpose_semitones: state.transposeSemitones,
      accidental_mode: state.accidentalMode,
      range_mode: state.rangeMode,
      mm_per_beat: state.mmPerBeat,
      grid_snap_mm: state.existingGridMm,
      existing_strip_usable_mm: state.existingUsableMm,
      existing_grid_spacing_mm: state.existingGridMm,
      auto_resolve_repeats: state.autoResolveRepeats,
      manual_edits: state.manualEdits,
      page_index: state.a4PageIndex,
      ...extra,
    };
  }

  let arrangeTimer = null;
  function requestRearrange(immediate = false) {
    if (!state.activeSong) return;
    clearTimeout(arrangeTimer);
    const exec = async () => {
      try {
        stopAudio();
        const arr = await apiJson('/api/arrange', {
          method: 'POST',
          body: JSON.stringify(buildArrangePayload()),
        });
        state.arrangement = arr;
        state.transposeSemitones = arr.scale_analysis.chosen_shift;
        renderAll();
      } catch (err) {
        console.error('Arrange failed:', err);
      }
    };
    if (immediate) exec();
    else arrangeTimer = setTimeout(exec, 80);
  }

  // --------------------------------------------------------------------------
  // Crate Digger: Song+Artist Search & Full Artist Catalog Explorer
  // --------------------------------------------------------------------------

  async function performSongSearch() {
    const q = el.songSearchInput.value.trim();
    const artist = el.artistFilterInput.value.trim();
    const source = el.searchSourceSelect.value;

    el.searchSubmitBtn.disabled = true;
    el.searchStatusMsg.textContent = (q || artist)
      ? `SCANNING [${[q, artist].filter(Boolean).join(' // ')}]...`
      : 'LOADING STARTER REELS...';

    try {
      const params = new URLSearchParams({ q, artist, source });
      const data = await apiJson(`/api/search?${params.toString()}`);
      state.searchResults = data.results || [];
      renderCartridgeList(el.searchResultsGrid, state.searchResults);

      if (data.warnings && data.warnings.length > 0) {
        el.searchStatusMsg.textContent = `${state.searchResults.length} REELS (WARN: ${data.warnings.join('; ')})`;
      } else {
        el.searchStatusMsg.textContent = (q || artist)
          ? `FOUND ${state.searchResults.length} RANKED REELS — CLICK TO MOUNT`
          : 'STARTER REELS READY — SEARCH OR BROWSE ARTIST CATALOG';
      }
    } catch (err) {
      el.searchStatusMsg.textContent = `SEARCH FAULT: ${err.message}`;
    } finally {
      el.searchSubmitBtn.disabled = false;
    }
  }

  async function performArtistSearch() {
    const q = el.artistCatalogQueryInput.value.trim();
    if (!q) return;

    el.artistSearchBtn.disabled = true;
    el.artistStatusMsg.textContent = `INDEXING ARTISTS MATCHING "${q.toUpperCase()}"...`;
    el.artistMatchesBar.classList.add('hidden');
    el.artistCatalogGrid.innerHTML = '';

    try {
      const data = await apiJson(`/api/artists?q=${encodeURIComponent(q)}`);
      state.artistMatches = data.artists || [];
      if (state.artistMatches.length === 0) {
        el.artistStatusMsg.textContent = `NO ARTIST CATALOG FOUND FOR "${q}".`;
        return;
      }
      renderArtistChips();
      await loadArtistCatalog(state.artistMatches[0]);
    } catch (err) {
      el.artistStatusMsg.textContent = `ARTIST LOOKUP ERROR: ${err.message}`;
    } finally {
      el.artistSearchBtn.disabled = false;
    }
  }

  function renderArtistChips() {
    el.artistMatchesBar.innerHTML = '';
    el.artistMatchesBar.classList.remove('hidden');

    state.artistMatches.forEach((art) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'hw-btn hw-btn-sm' + (art.artist_id === state.activeArtistId ? ' hw-btn-cyan' : '');
      btn.textContent = `${art.name} [${art.badge}]`;
      btn.addEventListener('click', () => loadArtistCatalog(art));
      el.artistMatchesBar.appendChild(btn);
    });
  }

  async function loadArtistCatalog(artObj) {
    state.activeArtistId = artObj.artist_id;
    renderArtistChips();
    el.artistStatusMsg.textContent = `PULLING CATALOG FOR [${artObj.name.toUpperCase()}]...`;
    el.artistCatalogGrid.innerHTML = '';

    try {
      const cat = await apiJson(`/api/artists/catalog?artist_id=${encodeURIComponent(artObj.artist_id)}`);
      state.activeArtistName = cat.artist_name || artObj.name;
      state.artistCatalogSongs = cat.songs || [];
      el.catalogLiveFilterInput.value = '';
      el.artistCatalogFilterWrap.classList.remove('hidden');
      renderFilteredArtistCatalog();
    } catch (err) {
      el.artistStatusMsg.textContent = `CATALOG FETCH ERROR: ${err.message}`;
    }
  }

  function renderFilteredArtistCatalog() {
    const filterQ = el.catalogLiveFilterInput.value.trim().toLowerCase();
    const filtered = filterQ
      ? state.artistCatalogSongs.filter((s) => s.title.toLowerCase().includes(filterQ))
      : state.artistCatalogSongs;

    el.artistStatusMsg.textContent =
      `${state.activeArtistName.toUpperCase()} — ${filtered.length} / ${state.artistCatalogSongs.length} TRACKS`;
    renderCartridgeList(el.artistCatalogGrid, filtered);
  }

  function renderCartridgeList(container, items) {
    container.innerHTML = '';
    const activeId = state.activeSong ? state.activeSong.song_id : null;

    items.forEach((item) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'cartridge-item' + (item.id === activeId ? ' active' : '');
      const isK15 = Boolean(item.is_native_k15 || (item.badge && item.badge.includes('Native')));

      const titleDiv = document.createElement('div');
      titleDiv.className = 'cart-title';
      titleDiv.textContent = item.title;

      const subDiv = document.createElement('div');
      subDiv.className = 'cart-sub';

      const srcSpan = document.createElement('span');
      srcSpan.textContent = item.subtitle || item.source;
      srcSpan.style.overflow = 'hidden';
      srcSpan.style.textOverflow = 'ellipsis';
      srcSpan.style.whiteSpace = 'nowrap';

      const chipSpan = document.createElement('span');
      chipSpan.className = 'cart-chip' + (isK15 ? ' k15' : '');
      chipSpan.textContent = isK15 ? 'K15 NATIVE' : (item.badge || item.source);

      subDiv.appendChild(srcSpan);
      subDiv.appendChild(chipSpan);
      btn.appendChild(titleDiv);
      btn.appendChild(subDiv);

      btn.addEventListener('click', () => loadSongById(item.id));
      container.appendChild(btn);
    });
  }

  async function loadSongById(songId) {
    el.vfdSongReadout.textContent = 'MOUNTING & DECODING REEL...';
    try {
      const bundle = await apiJson('/api/load', {
        method: 'POST',
        body: JSON.stringify({ song_id: songId }),
      });
      applyLoadedSongBundle(bundle);
    } catch (err) {
      el.vfdSongReadout.textContent = 'MOUNT ERROR';
      el.scaleBannerMessage.textContent = err.message;
    }
  }

  function applyLoadedSongBundle(bundle) {
    stopAudio();
    state.activeSong = bundle.song;
    state.arrangement = bundle.arrangement;
    state.selectedTracks = bundle.arrangement.settings.selected_tracks;
    state.startBeat = bundle.arrangement.slice.start_beat;
    state.endBeat = bundle.arrangement.slice.end_beat;
    state.transposeSemitones = bundle.arrangement.scale_analysis.chosen_shift;
    state.manualEdits = [];
    state.checkedRows.clear();
    state.focusedRowIdx = 0;
    state.a4PageIndex = 0;
    state.manualCrankBeat = 0;
    state.playBpm = Math.round(bundle.song.bpm || 120);

    el.playbackBpmInput.value = state.playBpm;
    el.startBeatInput.value = Math.round(state.startBeat * 10) / 10;
    el.endBeatInput.value = Math.round(state.endBeat * 10) / 10;
    el.clearManualEditsBtn.classList.add('hidden');

    renderCartridgeList(el.searchResultsGrid, state.searchResults);
    if (state.artistCatalogSongs.length) renderFilteredArtistCatalog();
    renderTrackMixer();
    renderAll();
  }

  // --------------------------------------------------------------------------
  // Channel Mixer & Master Render
  // --------------------------------------------------------------------------

  function renderTrackMixer() {
    const tracks = (state.activeSong && state.activeSong.tracks) || [];
    if (tracks.length <= 1) {
      el.trackPickerWrap.classList.add('hidden');
      return;
    }
    el.trackPickerWrap.classList.remove('hidden');
    el.trackListContainer.innerHTML = '';
    const sel = new Set(state.selectedTracks || []);

    tracks.forEach((tr) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      const active = sel.has(tr.index);
      btn.className = 'chan-btn' + (active ? ' engaged' : '');

      const led = document.createElement('span');
      led.className = 'led' + (active ? ' on-cyan' : '');

      const lbl = document.createElement('span');
      lbl.textContent = `${tr.name} (${tr.note_count})`;

      btn.appendChild(led);
      btn.appendChild(lbl);
      btn.addEventListener('click', () => {
        const next = new Set(state.selectedTracks || []);
        if (next.has(tr.index)) {
          if (next.size > 1) next.delete(tr.index);
        } else {
          next.add(tr.index);
        }
        state.selectedTracks = Array.from(next);
        state.transposeSemitones = null;
        renderTrackMixer();
        requestRearrange(true);
      });
      el.trackListContainer.appendChild(btn);
    });
  }

  function renderAll() {
    if (!state.activeSong || !state.arrangement) return;
    const song = state.activeSong;
    const arr = state.arrangement;
    const sc = arr.scale_analysis;
    const st = arr.stats;

    const shiftSign = sc.chosen_shift > 0 ? `+${sc.chosen_shift}` : `${sc.chosen_shift}`;

    el.vfdSongReadout.textContent = `${song.title} [${song.source.toUpperCase()}]`;
    el.vfdScaleReadout.textContent = `${sc.detected_key.toUpperCase()} · ${shiftSign} ST · ${sc.chosen_eval.in_scale_pct}% C-MAJ`;
    el.vfdScaleReadout.className = 'vfd-readout' + (sc.status === 'chromatic_warning' ? ' warn' : '');

    el.vfdFootageReadout.textContent =
      `${st.output_punches} HOLES · ${st.pattern_length_cm}CM · ${st.existing_strips_needed}/4 SHEETS`;
    el.vfdFootageReadout.className = 'vfd-readout' + (st.exceeds_owned_strips ? ' warn' : '');

    el.sliceDurationReadout.textContent =
      `WINDOW: ${(state.endBeat - state.startBeat).toFixed(1)} BEATS (${arr.slice.duration_seconds}s)`;
    el.totalBeatsReadout.textContent = `REEL: ${song.total_beats.toFixed(0)} BEATS`;

    el.scaleStatusBanner.className = `scale-vfd-box ${sc.status}`;
    const kickerMap = {
      native_match: 'SCALE LOCK // 100% NATIVE C-MAJOR FIT',
      transposed_match: `SCALE LOCK // TRANSPOSED ${sc.detected_key.toUpperCase()} → C-MAJOR (100% CLEAN)`,
      chromatic_warning: `⚠ CHROMATIC ALERT // ${sc.detected_key.toUpperCase()} CONTAINS NON-DIATONIC PINS`,
      empty: 'EMPTY WINDOW // EXPAND GATE OR ENABLE CHANNEL',
    };
    el.scaleBannerKicker.textContent = kickerMap[sc.status] || 'SCALE DIAGNOSTIC';
    el.scaleBannerMessage.textContent = sc.message;

    if (sc.chosen_shift !== sc.best_shift) {
      el.applyBestShiftBtn.classList.remove('hidden');
      const bs = sc.best_shift > 0 ? `+${sc.best_shift}` : `${sc.best_shift}`;
      el.applyBestShiftBtn.textContent = `AUTO-LOCK (${bs} ST)`;
    } else {
      el.applyBestShiftBtn.classList.add('hidden');
    }

    el.shiftValueDisplay.textContent = `${shiftSign} ST`;

    el.candidateChipsRow.innerHTML = '';
    (sc.top_candidates || []).forEach((cand, idx) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      const sgn = cand.shift > 0 ? `+${cand.shift}` : `${cand.shift}`;
      btn.className = 'pad-btn' + (cand.shift === sc.chosen_shift ? ' active' : '');
      btn.innerHTML = `<strong>P${idx + 1}: ${sgn} ST</strong><br/><span>${cand.in_scale_pct}% C-Maj · ${cand.in_range_pct}% Span</span>`;
      btn.addEventListener('click', () => {
        state.transposeSemitones = cand.shift;
        requestRearrange(true);
      });
      el.candidateChipsRow.appendChild(btn);
    });

    drawOverviewCanvas();
    drawCombMechanism();
    drawCrankDial();
    drawStripCanvas();
    renderOperatorPunchGuide();
    if (state.outputMode === 'a4') refreshA4Preview();
  }

  // --------------------------------------------------------------------------
  // Oscilloscope Gate Slicer Canvas
  // --------------------------------------------------------------------------

  function drawOverviewCanvas() {
    const canvas = el.overviewCanvas;
    const rect = el.overviewWrap.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(240, Math.floor(rect.width));
    const h = 76;
    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
      canvas.width = w * dpr;
      canvas.height = h * dpr;
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = '#06090c';
    ctx.fillRect(0, 0, w, h);

    ctx.strokeStyle = 'rgba(0, 240, 200, 0.08)';
    ctx.lineWidth = 1;
    for (let gy = 19; gy < h; gy += 19) {
      ctx.beginPath();
      ctx.moveTo(0, gy);
      ctx.lineTo(w, gy);
      ctx.stroke();
    }

    const song = state.activeSong;
    if (!song) return;
    const totalBeats = Math.max(1, song.total_beats);
    const selSet = new Set(state.selectedTracks || []);
    const notes = (song.note_preview || []).filter((n) => selSet.has(n.t));

    const barBeats = Math.max(1, song.beats_per_bar || 4);
    for (let b = 0; b <= totalBeats; b += barBeats * 2) {
      const x = (b / totalBeats) * w;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }

    let minM = 48, maxM = 84;
    if (notes.length > 0) {
      minM = Math.min(...notes.map((n) => n.m)) - 2;
      maxM = Math.max(...notes.map((n) => n.m)) + 2;
    }
    const spanM = Math.max(12, maxM - minM);

    notes.forEach((n) => {
      const x = (n.b / totalBeats) * w;
      const nw = Math.max(2, (n.d / totalBeats) * w);
      const y = h - 7 - ((n.m - minM) / spanM) * (h - 14);
      const inside = n.b >= state.startBeat && n.b < state.endBeat;
      ctx.fillStyle = inside ? '#00f0c8' : 'rgba(100, 116, 139, 0.36)';
      ctx.fillRect(x, y - 1.5, nw, 3);
    });

    const sx = (state.startBeat / totalBeats) * w;
    const ex = (state.endBeat / totalBeats) * w;

    ctx.fillStyle = 'rgba(4, 6, 9, 0.62)';
    ctx.fillRect(0, 0, sx, h);
    ctx.fillRect(ex, 0, w - ex, h);

    ctx.strokeStyle = '#ff5500';
    ctx.lineWidth = 2;
    ctx.strokeRect(sx + 1, 1, Math.max(2, ex - sx - 2), h - 2);

    ctx.fillStyle = '#ff5500';
    ctx.fillRect(sx, 0, 5, h);
    ctx.fillRect(Math.max(0, ex - 5), 0, 5, h);

    if (state.currentPlayBeatOffset !== null) {
      const px = ((state.startBeat + state.currentPlayBeatOffset) / totalBeats) * w;
      ctx.strokeStyle = '#ffd000';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(px, 0);
      ctx.lineTo(px, h);
      ctx.stroke();
    }
  }

  function setupOverviewDrag() {
    let dragMode = null;
    let dragInitBeat = 0;
    let initStart = 0;
    let initEnd = 0;

    const clientXToBeat = (cx) => {
      const rect = el.overviewWrap.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (cx - rect.left) / Math.max(1, rect.width)));
      return ratio * (state.activeSong ? state.activeSong.total_beats : 32);
    };

    el.overviewWrap.addEventListener('pointerdown', (e) => {
      if (!state.activeSong) return;
      el.overviewWrap.setPointerCapture(e.pointerId);
      const rect = el.overviewWrap.getBoundingClientRect();
      const total = Math.max(1, state.activeSong.total_beats);
      const sx = (state.startBeat / total) * rect.width;
      const ex = (state.endBeat / total) * rect.width;
      const lx = e.clientX - rect.left;

      initStart = state.startBeat;
      initEnd = state.endBeat;
      dragInitBeat = clientXToBeat(e.clientX);

      if (Math.abs(lx - sx) <= 12) dragMode = 'start';
      else if (Math.abs(lx - ex) <= 12) dragMode = 'end';
      else if (lx > sx && lx < ex) dragMode = 'pan';
      else {
        const span = initEnd - initStart;
        let ns = Math.round(dragInitBeat - span / 2);
        ns = Math.max(0, Math.min(total - span, ns));
        state.startBeat = ns;
        state.endBeat = Math.min(total, ns + span);
        initStart = state.startBeat;
        initEnd = state.endBeat;
        dragMode = 'pan';
        syncBeatInputs(true);
      }
    });

    el.overviewWrap.addEventListener('pointermove', (e) => {
      if (!dragMode || !state.activeSong) return;
      const total = Math.max(1, state.activeSong.total_beats);
      const delta = clientXToBeat(e.clientX) - dragInitBeat;

      if (dragMode === 'start') {
        state.startBeat = Math.max(0, Math.min(state.endBeat - 2, Math.round((initStart + delta) * 2) / 2));
      } else if (dragMode === 'end') {
        state.endBeat = Math.min(total, Math.max(state.startBeat + 2, Math.round((initEnd + delta) * 2) / 2));
      } else if (dragMode === 'pan') {
        const span = initEnd - initStart;
        const ns = Math.max(0, Math.min(total - span, Math.round((initStart + delta) * 2) / 2));
        state.startBeat = ns;
        state.endBeat = Math.round((ns + span) * 2) / 2;
      }
      syncBeatInputs(false);
    });

    const stopDrag = () => {
      if (dragMode) {
        dragMode = null;
        requestRearrange(true);
      }
    };
    el.overviewWrap.addEventListener('pointerup', stopDrag);
    el.overviewWrap.addEventListener('pointercancel', stopDrag);
  }

  function syncBeatInputs(immediate) {
    el.startBeatInput.value = state.startBeat;
    el.endBeatInput.value = state.endBeat;
    drawOverviewCanvas();
    requestRearrange(immediate);
  }

  // --------------------------------------------------------------------------
  // Center Bay: Dynamically-Scaled 15-Tine Steel Comb & Hand-Crank
  // --------------------------------------------------------------------------

  function triggerTineVisual(colIdx) {
    if (colIdx >= 0 && colIdx < 15) {
      state.tineEnergy[colIdx] = 1.0;
      startCombDecayLoop();
    }
  }

  let combDecayRaf = null;
  function startCombDecayLoop() {
    if (combDecayRaf) return;
    const step = () => {
      let anyActive = false;
      for (let i = 0; i < 15; i++) {
        if (state.tineEnergy[i] > 0.01) {
          state.tineEnergy[i] *= 0.91;
          anyActive = true;
        } else {
          state.tineEnergy[i] = 0;
        }
      }
      drawCombMechanism();
      if (anyActive) combDecayRaf = requestAnimationFrame(step);
      else combDecayRaf = null;
    };
    combDecayRaf = requestAnimationFrame(step);
  }

  function drawCombMechanism() {
    const geom = getStripGeom();
    const canvas = el.combMechCanvas;
    const dpr = window.devicePixelRatio || 1;
    const w = geom.width;
    const h = 108;

    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const spineX = geom.leftMargin - 16;
    const spineW = w - (geom.leftMargin - 16) * 2;

    const baseGrad = ctx.createLinearGradient(0, 3, 0, 27);
    baseGrad.addColorStop(0, '#647084');
    baseGrad.addColorStop(0.5, '#3b4352');
    baseGrad.addColorStop(1, '#242933');
    ctx.fillStyle = baseGrad;
    ctx.fillRect(spineX, 3, spineW, 24);
    ctx.strokeStyle = '#111419';
    ctx.strokeRect(spineX, 3, spineW, 24);

    [spineX + 14, spineX + spineW - 14].forEach((bx) => {
      ctx.beginPath();
      ctx.arc(bx, 15, 5, 0, Math.PI * 2);
      ctx.fillStyle = '#c99738';
      ctx.fill();
      ctx.strokeStyle = '#111';
      ctx.stroke();
    });

    ctx.fillStyle = '#cbd5e1';
    ctx.font = '700 8.5px "IBM Plex Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText('KIKKERLAND 15-TINE TEMPERED STEEL COMB', w / 2, 18);

    const rollerY = 92;
    const brassGrad = ctx.createLinearGradient(0, rollerY - 6, 0, rollerY + 6);
    brassGrad.addColorStop(0, '#f5d061');
    brassGrad.addColorStop(0.5, '#b8861b');
    brassGrad.addColorStop(1, '#5e4208');
    ctx.fillStyle = brassGrad;
    ctx.fillRect(spineX + 4, rollerY - 5, spineW - 8, 10);

    const tineW = Math.max(10, Math.min(18, geom.colSpacing * 0.56));

    for (let c = 0; c < 15; c++) {
      const cx = geom.leftMargin + c * geom.colSpacing;
      const energy = state.tineEnergy[c];
      const vibOffset = energy > 0 ? Math.sin(performance.now() * 0.09 + c) * energy * 2.8 : 0;

      const rootY = 27;
      const tipY = 84 - c * 0.4;
      const isBold = BOLD_COLS.has(c);

      ctx.fillStyle = energy > 0.08
        ? `rgb(${Math.round(200 + 55 * energy)}, ${Math.round(140 + 90 * (1 - energy))}, ${Math.round(70 * (1 - energy))})`
        : (isBold ? '#cbd5e1' : '#94a3b8');
      ctx.fillRect(cx - tineW / 2 + vibOffset, rootY, tineW, tipY - rootY);

      ctx.fillStyle = 'rgba(255,255,255,0.22)';
      ctx.fillRect(cx - tineW / 2 + vibOffset, rootY, 2, tipY - rootY);

      if (energy > 0.12) {
        ctx.beginPath();
        ctx.arc(cx, rollerY, 6 + energy * 7, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(255, 110, 20, ${energy * 0.65})`;
        ctx.fill();
      }

      ctx.fillStyle = '#fcd34d';
      ctx.fillRect(cx - 2, rollerY - 7, 4, 14);

      ctx.fillStyle = energy > 0.2 ? '#090b0e' : (isBold ? '#0f172a' : '#1e293b');
      ctx.font = `${isBold ? '700' : '600'} 10px "IBM Plex Mono", monospace`;
      ctx.textAlign = 'center';
      ctx.fillText(PRINTED_LABELS[c], cx + vibOffset, tipY - 5);
    }
  }

  function setupCombInteraction() {
    el.combMechCanvas.addEventListener('pointerdown', (e) => {
      const geom = getStripGeom();
      const rect = el.combMechCanvas.getBoundingClientRect();
      const scaleX = geom.width / Math.max(1, rect.width);
      const x = (e.clientX - rect.left) * scaleX;
      const col = Math.round((x - geom.leftMargin) / geom.colSpacing);
      if (col >= 0 && col < 15) {
        triggerTineVisual(col);
        playSingleMusicBoxPluck(72 + RELATIVE_SEMITONES[col]);
      }
    });
  }

  function drawCrankDial() {
    const canvas = el.crankCanvas;
    const dpr = window.devicePixelRatio || 1;
    const sz = 78;
    if (canvas.width !== sz * dpr) {
      canvas.width = sz * dpr;
      canvas.height = sz * dpr;
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, sz, sz);

    const cx = sz / 2;
    const cy = sz / 2;

    ctx.beginPath();
    ctx.arc(cx, cy, 31, 0, Math.PI * 2);
    ctx.fillStyle = '#1e232c';
    ctx.fill();
    ctx.lineWidth = 2.6;
    ctx.strokeStyle = '#d49b2a';
    ctx.stroke();

    const armLen = 24;
    const kx = cx + Math.cos(state.crankAngleRad) * armLen;
    const ky = cy + Math.sin(state.crankAngleRad) * armLen;

    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 4.5;
    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(kx, ky);
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(cx, cy, 6, 0, Math.PI * 2);
    ctx.fillStyle = '#94a3b8';
    ctx.fill();

    ctx.beginPath();
    ctx.arc(kx, ky, 7.5, 0, Math.PI * 2);
    ctx.fillStyle = '#ff5500';
    ctx.fill();
    ctx.lineWidth = 1.8;
    ctx.strokeStyle = '#090b0e';
    ctx.stroke();
  }

  function setupManualHandCrank() {
    let dragging = false;
    let prevAngle = 0;

    const getPointerAngle = (e) => {
      const rect = el.crankCanvas.getBoundingClientRect();
      return Math.atan2(e.clientY - (rect.top + rect.height / 2), e.clientX - (rect.left + rect.width / 2));
    };

    el.crankCanvas.addEventListener('pointerdown', (e) => {
      if (!state.arrangement) return;
      stopAudio();
      ensureAudioCtx();
      dragging = true;
      state.isHandCranking = true;
      el.crankCanvas.setPointerCapture(e.pointerId);
      prevAngle = getPointerAngle(e);
      if (state.currentPlayBeatOffset === null) {
        state.manualCrankBeat = 0;
        state.currentPlayBeatOffset = 0;
      }
    });

    el.crankCanvas.addEventListener('pointermove', (e) => {
      if (!dragging || !state.arrangement) return;
      const ang = getPointerAngle(e);
      let delta = ang - prevAngle;
      if (delta > Math.PI) delta -= Math.PI * 2;
      if (delta < -Math.PI) delta += Math.PI * 2;
      prevAngle = ang;

      state.crankAngleRad += delta;
      const prevBeat = state.manualCrankBeat;
      const maxSliceBeats = Math.max(2, state.endBeat - state.startBeat);
      state.manualCrankBeat = Math.max(0, Math.min(maxSliceBeats, prevBeat + (delta / (Math.PI * 2)) * 4.0));
      state.currentPlayBeatOffset = state.manualCrankBeat;

      if (state.manualCrankBeat > prevBeat) {
        const y0 = prevBeat * state.mmPerBeat;
        const y1 = state.manualCrankBeat * state.mmPerBeat;
        (state.arrangement.punches || []).forEach((p) => {
          if (p.y_mm > y0 && p.y_mm <= y1) {
            triggerTineVisual(p.col);
            playSingleMusicBoxPluck(p.sounding_midi);
          }
        });
      }

      drawCrankDial();
      drawOverviewCanvas();
      drawStripCanvas();

      const geom = getStripGeom();
      const playPx = geom.topHeader + state.manualCrankBeat * state.mmPerBeat * geom.pxPerMm;
      el.stripViewport.scrollTop = Math.max(0, playPx - 100);
    });

    const release = () => {
      dragging = false;
      state.isHandCranking = false;
    };
    el.crankCanvas.addEventListener('pointerup', release);
    el.crankCanvas.addEventListener('pointercancel', release);
  }

  // --------------------------------------------------------------------------
  // Interactive Manila Punch-Tape Canvas
  // --------------------------------------------------------------------------

  function drawStripCanvas() {
    if (!state.arrangement) return;
    const geom = getStripGeom();
    const punches = state.arrangement.punches || [];
    const vpHeight = (el.stripViewport && el.stripViewport.clientHeight) || 500;
    const maxMm = Math.max(90, state.arrangement.stats.pattern_length_mm || 90);

    const w = geom.width;
    const h = Math.max(vpHeight - 6, Math.ceil(geom.topHeader + maxMm * geom.pxPerMm + geom.bottomPad));
    const dpr = window.devicePixelRatio || 1;
    const canvas = el.stripCanvas;

    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    ctx.fillStyle = '#f2ead8';
    ctx.fillRect(0, 0, w, h);

    ctx.fillStyle = '#e5dbc3';
    ctx.fillRect(0, 0, w, geom.topHeader - 5);

    const gridStepMm = Math.max(2.0, state.existingGridMm);
    const mmPerBeat = Math.max(2.0, state.mmPerBeat);
    const totalDrawMm = (h - geom.topHeader - 12) / geom.pxPerMm;

    for (let yMm = 0; yMm <= totalDrawMm; yMm += gridStepMm) {
      const py = geom.topHeader + yMm * geom.pxPerMm;
      const isBeat = Math.abs(yMm / mmPerBeat - Math.round(yMm / mmPerBeat)) < 0.05;
      ctx.strokeStyle = isBeat ? 'rgba(24, 26, 31, 0.34)' : 'rgba(24, 26, 31, 0.12)';
      ctx.lineWidth = isBeat ? 0.95 : 0.45;
      ctx.beginPath();
      ctx.moveTo(geom.leftMargin, py);
      ctx.lineTo(w - geom.leftMargin, py);
      ctx.stroke();

      if (isBeat && Math.round(yMm / mmPerBeat) % 2 === 0) {
        ctx.fillStyle = '#5c5549';
        ctx.font = '600 10px "IBM Plex Mono", monospace';
        ctx.textAlign = 'right';
        ctx.fillText(`${Math.round(yMm)}mm`, geom.leftMargin - 8, py + 3);
      }
    }

    const sheetMm = Math.max(50, state.existingUsableMm);
    for (let sMm = sheetMm; sMm < totalDrawMm; sMm += sheetMm) {
      const py = geom.topHeader + sMm * geom.pxPerMm;
      ctx.save();
      ctx.setLineDash([6, 4]);
      ctx.strokeStyle = '#ff5500';
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      ctx.moveTo(6, py);
      ctx.lineTo(w - 6, py);
      ctx.stroke();
      ctx.fillStyle = '#c23d00';
      ctx.font = '700 10px "IBM Plex Mono", monospace';
      ctx.textAlign = 'right';
      ctx.fillText(`✂ END SHEET ${Math.round(sMm / sheetMm)} (${sMm}MM)`, w - 10, py - 5);
      ctx.restore();
    }

    for (let c = 0; c < 15; c++) {
      const cx = geom.leftMargin + c * geom.colSpacing;
      const isBold = BOLD_COLS.has(c);
      ctx.strokeStyle = isBold ? '#181a1f' : 'rgba(24, 26, 31, 0.42)';
      ctx.lineWidth = isBold ? 2.2 : 0.85;
      ctx.beginPath();
      ctx.moveTo(cx, geom.topHeader - 4);
      ctx.lineTo(cx, h - 10);
      ctx.stroke();

      ctx.fillStyle = isBold ? '#b83700' : '#181a1f';
      ctx.font = `${isBold ? '700' : '600'} 11.5px "IBM Plex Mono", monospace`;
      ctx.textAlign = 'center';
      ctx.fillText(PRINTED_LABELS[c], cx, 21);
    }

    punches.forEach((p) => {
      const cx = geom.leftMargin + p.col * geom.colSpacing;
      const cy = geom.topHeader + p.y_mm * geom.pxPerMm;

      ctx.beginPath();
      ctx.arc(cx, cy, geom.holeRadius, 0, Math.PI * 2);
      if (p.repeat_warning) ctx.fillStyle = '#ff3b30';
      else if (p.is_manual) ctx.fillStyle = '#008c72';
      else ctx.fillStyle = '#0d1014';
      ctx.fill();

      ctx.lineWidth = 1.5;
      ctx.strokeStyle = p.repeat_warning ? '#7f1d1d' : '#ff5500';
      ctx.stroke();
    });

    if (state.currentPlayBeatOffset !== null) {
      const py = geom.topHeader + state.currentPlayBeatOffset * state.mmPerBeat * geom.pxPerMm;
      ctx.strokeStyle = '#ff5500';
      ctx.lineWidth = 2.5;
      ctx.beginPath();
      ctx.moveTo(0, py);
      ctx.lineTo(w, py);
      ctx.stroke();
    }
  }

  function setupStripCanvasClick() {
    el.stripCanvas.addEventListener('click', (e) => {
      if (!state.arrangement) return;
      const geom = getStripGeom();
      const rect = el.stripCanvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;

      const col = Math.round((x - geom.leftMargin) / geom.colSpacing);
      if (col < 0 || col > 14) return;
      const rawYMm = (y - geom.topHeader) / geom.pxPerMm;
      if (rawYMm < -1) return;

      const snap = Math.max(1.0, state.existingGridMm);
      const snappedYMm = Math.max(0, Math.round(rawYMm / snap) * snap);

      const existing = (state.arrangement.punches || []).find(
        (p) => p.col === col && Math.abs(p.y_mm - snappedYMm) <= snap * 0.55
      );

      if (existing) {
        state.manualEdits.push({ action: 'remove', col, y_mm: existing.y_mm });
      } else {
        state.manualEdits.push({ action: 'add', col, y_mm: snappedYMm });
        triggerTineVisual(col);
        playSingleMusicBoxPluck(72 + RELATIVE_SEMITONES[col]);
      }
      el.clearManualEditsBtn.classList.remove('hidden');
      requestRearrange(true);
    });
  }

  // --------------------------------------------------------------------------
  // Right Bay: Die-Punch Operator HUD & Row Log + 1:1 A4 Blueprint Plotter
  // --------------------------------------------------------------------------

  function renderOperatorPunchGuide() {
    const rows = (state.arrangement && state.arrangement.punch_rows) || [];
    el.punchChecklistContainer.innerHTML = '';

    if (state.focusedRowIdx >= rows.length) {
      state.focusedRowIdx = Math.max(0, rows.length - 1);
    }

    const doneCount = rows.filter((r) => state.checkedRows.has(r.global_row)).length;
    el.punchProgressText.textContent = `${doneCount} / ${rows.length} STAMPED`;

    el.hudPinMatrix.innerHTML = '';
    const activeRow = rows[state.focusedRowIdx];
    if (!activeRow) {
      el.hudActiveCoord.textContent = 'NO PUNCH ROWS IN GATE';
      el.hudLandmarkReadout.textContent = 'Select a song slice with notes.';
      return;
    }

    el.hudActiveCoord.textContent =
      `SHEET ${activeRow.sheet_number}/4 // LINE ${activeRow.sheet_row} (${activeRow.sheet_y_mm.toFixed(1)} MM)`;

    const activeCols = new Set(activeRow.punches.map((p) => p.col));
    for (let c = 0; c < 15; c++) {
      const cell = document.createElement('div');
      cell.className =
        'hud-pin' +
        (BOLD_COLS.has(c) ? ' bold-staff' : '') +
        (activeCols.has(c) ? ' target' : '');
      cell.innerHTML = `<span>${PRINTED_LABELS[c]}</span><span class="hud-pin-led"></span>`;
      el.hudPinMatrix.appendChild(cell);
    }

    el.hudLandmarkReadout.innerHTML = activeRow.punches
      .map((p) => `<span style="color:var(--sig-yellow); font-weight:700;">[${p.label} · COL ${p.col_num}]</span> ${p.landmark_hint}`)
      .join(' &nbsp;·&nbsp; ');

    let curSheet = 0;
    rows.forEach((row, idx) => {
      if (row.sheet_number !== curSheet) {
        curSheet = row.sheet_number;
        const hdr = document.createElement('div');
        hdr.style.padding = '6px 10px';
        hdr.style.fontFamily = 'var(--font-mono)';
        hdr.style.fontSize = '0.7rem';
        hdr.style.fontWeight = '700';
        hdr.style.background = curSheet > 4 ? 'rgba(255, 59, 48, 0.2)' : '#1c212b';
        hdr.style.color = curSheet > 4 ? '#ff6b6b' : 'var(--vfd-cyan)';
        hdr.textContent = curSheet <= 4
          ? `=== KIKKERLAND SHEET #${curSheet} (OF YOUR 4 SHEETS) ===`
          : `=== SHEET #${curSheet} (EXCEEDS 4 SHEETS — TRIM GATE OR USE A4 PLOTTER) ===`;
        el.punchChecklistContainer.appendChild(hdr);
      }

      const isDone = state.checkedRows.has(row.global_row);
      const rEl = document.createElement('div');
      rEl.className =
        'punch-log-row' +
        (isDone ? ' done' : '') +
        (idx === state.focusedRowIdx ? ' focused' : '');

      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = isDone;

      const coord = document.createElement('div');
      coord.innerHTML = `<strong style="color:var(--text-hi);">LN ${row.sheet_row}</strong> <span style="color:var(--text-low);">${row.sheet_y_mm.toFixed(0)}mm</span>`;

      const mini = document.createElement('div');
      mini.className = 'mini-15-bar';
      const rHits = new Set(row.punches.map((p) => p.col));
      for (let c = 0; c < 15; c++) {
        const mc = document.createElement('div');
        mc.className = 'm15-c' + (BOLD_COLS.has(c) ? ' b' : '') + (rHits.has(c) ? ' hit' : '');
        mc.innerHTML = '<span class="m15-dot"></span>';
        mini.appendChild(mc);
      }

      const txt = document.createElement('div');
      txt.style.color = 'var(--text-mid)';
      txt.textContent = row.punches.map((p) => `${p.label}(#${p.col_num})`).join(', ');

      rEl.addEventListener('click', (e) => {
        if (e.target === cb) return;
        state.focusedRowIdx = idx;
        row.punches.forEach((p) => {
          triggerTineVisual(p.col);
          playSingleMusicBoxPluck(72 + RELATIVE_SEMITONES[p.col]);
        });
        renderOperatorPunchGuide();
      });

      cb.addEventListener('change', () => {
        if (cb.checked) state.checkedRows.add(row.global_row);
        else state.checkedRows.delete(row.global_row);
        renderOperatorPunchGuide();
      });

      rEl.appendChild(cb);
      rEl.appendChild(coord);
      rEl.appendChild(mini);
      rEl.appendChild(txt);
      el.punchChecklistContainer.appendChild(rEl);
    });
  }

  function stampCurrentRowAndAdvance() {
    const rows = (state.arrangement && state.arrangement.punch_rows) || [];
    if (!rows.length) return;
    const cur = rows[state.focusedRowIdx];
    if (cur) {
      state.checkedRows.add(cur.global_row);
      cur.punches.forEach((p) => {
        triggerTineVisual(p.col);
        playSingleMusicBoxPluck(72 + RELATIVE_SEMITONES[p.col]);
      });
    }
    state.focusedRowIdx = Math.min(rows.length - 1, state.focusedRowIdx + 1);
    renderOperatorPunchGuide();
  }

  async function refreshA4Preview() {
    if (!state.activeSong || !state.arrangement) return;
    const totalPages = state.arrangement.stats.a4_pages_needed || 1;
    if (state.a4PageIndex >= totalPages) state.a4PageIndex = 0;

    if (totalPages > 1) {
      el.a4PageSelectWrap.classList.remove('hidden');
      el.a4PageSelect.innerHTML = '';
      for (let i = 0; i < totalPages; i++) {
        const opt = document.createElement('option');
        opt.value = String(i);
        opt.textContent = `PAGE ${i + 1} / ${totalPages}`;
        if (i === state.a4PageIndex) opt.selected = true;
        el.a4PageSelect.appendChild(opt);
      }
    } else {
      el.a4PageSelectWrap.classList.add('hidden');
    }

    try {
      const resp = await fetch('/api/export/svg', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildArrangePayload({ page_index: state.a4PageIndex })),
      });
      if (resp.ok) el.a4SvgContainer.innerHTML = await resp.text();
    } catch (err) {
      console.error('A4 preview error:', err);
    }
  }

  async function downloadExport(endpoint, fallbackName) {
    if (!state.activeSong) return;
    const resp = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildArrangePayload({ page_index: state.a4PageIndex })),
    });
    if (!resp.ok) {
      alert('Export failed.');
      return;
    }
    const blob = await resp.blob();
    const cd = resp.headers.get('Content-Disposition') || '';
    const m = cd.match(/filename="([^"]+)"/);
    const filename = m ? m[1] : fallbackName;
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  // --------------------------------------------------------------------------
  // WebAudio Steel-Tine Synthesizer + Synchronized Comb & Crank Animation
  // --------------------------------------------------------------------------

  function ensureAudioCtx() {
    if (!state.audioCtx) {
      const Cls = window.AudioContext || window.webkitAudioContext;
      state.audioCtx = new Cls();
    }
    if (state.audioCtx.state === 'suspended') state.audioCtx.resume();
    return state.audioCtx;
  }

  function midiToFreq(m) {
    return 440 * Math.pow(2, (m - 69) / 12);
  }

  function schedulePluck(ctx, midi, whenSec, style = 'kikkerland') {
    const freq = midiToFreq(midi);
    const master = ctx.createGain();
    master.connect(ctx.destination);

    if (style === 'kikkerland') {
      const oscMain = ctx.createOscillator();
      oscMain.type = 'sine';
      oscMain.frequency.setValueAtTime(freq, whenSec);

      const oscChime = ctx.createOscillator();
      oscChime.type = 'sine';
      oscChime.frequency.setValueAtTime(freq * 4.07, whenSec);

      const chimeGain = ctx.createGain();
      chimeGain.gain.setValueAtTime(0.085, whenSec);
      chimeGain.gain.exponentialRampToValueAtTime(0.0001, whenSec + 0.085);

      master.gain.setValueAtTime(0.0001, whenSec);
      master.gain.linearRampToValueAtTime(0.22, whenSec + 0.005);
      master.gain.exponentialRampToValueAtTime(0.0008, whenSec + 1.38);

      oscMain.connect(master);
      oscChime.connect(chimeGain);
      chimeGain.connect(master);

      oscMain.start(whenSec);
      oscChime.start(whenSec);
      oscMain.stop(whenSec + 1.42);
      oscChime.stop(whenSec + 0.11);
      state.scheduledNodes.push(oscMain, oscChime);
    } else {
      const osc = ctx.createOscillator();
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(freq, whenSec);

      master.gain.setValueAtTime(0.0001, whenSec);
      master.gain.linearRampToValueAtTime(0.17, whenSec + 0.012);
      master.gain.exponentialRampToValueAtTime(0.0008, whenSec + 0.72);

      osc.connect(master);
      osc.start(whenSec);
      osc.stop(whenSec + 0.78);
      state.scheduledNodes.push(osc);
    }
  }

  function playSingleMusicBoxPluck(midi) {
    const ctx = ensureAudioCtx();
    schedulePluck(ctx, midi, ctx.currentTime + 0.008, 'kikkerland');
  }

  function stopAudio() {
    state.scheduledNodes.forEach((n) => {
      try { n.stop(); } catch (_) {}
    });
    state.scheduledNodes = [];
    state.scheduledTimers.forEach((t) => clearTimeout(t));
    state.scheduledTimers = [];
    state.isPlaying = false;
    state.playMode = null;
    state.currentPlayBeatOffset = null;
    if (state.animFrameId) {
      cancelAnimationFrame(state.animFrameId);
      state.animFrameId = null;
    }
    el.playKikkerlandBtn.classList.remove('latched');
    el.playOriginalBtn.classList.remove('latched');
    el.playKikkerlandBtn.innerHTML = '<span>▶ CRANK 15-NOTE</span>';
    el.playOriginalBtn.innerHTML = '<span>⇄ A/B ORIG</span>';
    drawOverviewCanvas();
    drawStripCanvas();
  }

  function startPlayback(mode) {
    if (!state.arrangement) return;
    if (state.isPlaying && state.playMode === mode) {
      stopAudio();
      return;
    }
    stopAudio();

    const ctx = ensureAudioCtx();
    const bpm = Math.max(40, Math.min(240, Number(el.playbackBpmInput.value) || 120));
    state.playBpm = bpm;
    const secPerBeat = 60.0 / bpm;
    const startAt = ctx.currentTime + 0.06;

    let maxBeat = 0;
    if (mode === 'kikkerland') {
      const punches = state.arrangement.punches || [];
      if (!punches.length) return;
      punches.forEach((p) => {
        const b = p.y_mm / Math.max(1, state.mmPerBeat);
        maxBeat = Math.max(maxBeat, b);
        const delaySec = b * secPerBeat;
        schedulePluck(ctx, p.sounding_midi, startAt + delaySec, 'kikkerland');
        const tid = setTimeout(() => triggerTineVisual(p.col), Math.max(0, (delaySec + 0.05) * 1000));
        state.scheduledTimers.push(tid);
      });
      el.playKikkerlandBtn.classList.add('latched');
      el.playKikkerlandBtn.innerHTML = '<span>⏸ CRANKING...</span>';
    } else {
      const orig = state.arrangement.original_audio_notes || [];
      if (!orig.length) return;
      orig.forEach((n) => {
        maxBeat = Math.max(maxBeat, n.beat + n.dur);
        const playMidi = n.midi < 65 ? n.midi + 12 : n.midi;
        schedulePluck(ctx, playMidi, startAt + n.beat * secPerBeat, 'original');
      });
      el.playOriginalBtn.classList.add('latched');
      el.playOriginalBtn.innerHTML = '<span>⏸ A/B PLAYING</span>';
    }

    state.isPlaying = true;
    state.playMode = mode;
    state.playStartAudioTime = startAt;
    state.playDurationBeats = maxBeat + 1.0;

    const animate = () => {
      if (!state.isPlaying) return;
      const elapsedSec = ctx.currentTime - state.playStartAudioTime;
      const curBeat = Math.max(0, elapsedSec / secPerBeat);
      if (curBeat > state.playDurationBeats) {
        stopAudio();
        return;
      }
      state.currentPlayBeatOffset = curBeat;
      state.crankAngleRad = (curBeat / 4.0) * Math.PI * 2;
      drawCrankDial();
      drawOverviewCanvas();
      drawStripCanvas();

      const geom = getStripGeom();
      const playPx = geom.topHeader + curBeat * state.mmPerBeat * geom.pxPerMm;
      const vp = el.stripViewport;
      if (playPx > vp.scrollTop + vp.clientHeight - 75 || playPx < vp.scrollTop) {
        vp.scrollTop = Math.max(0, playPx - 85);
      }

      state.animFrameId = requestAnimationFrame(animate);
    };
    state.animFrameId = requestAnimationFrame(animate);
  }

  // --------------------------------------------------------------------------
  // Hardware Switches & Keyboard Bindings
  // --------------------------------------------------------------------------

  function bindEvents() {
    const setCrateMode = (mode) => {
      state.crateMode = mode;
      el.crateTabSong.classList.toggle('active', mode === 'song');
      el.crateTabArtist.classList.toggle('active', mode === 'artist');
      el.crateTabImport.classList.toggle('active', mode === 'import');
      el.cratePaneSong.classList.toggle('hidden', mode !== 'song');
      el.cratePaneArtist.classList.toggle('hidden', mode !== 'artist');
      el.cratePaneImport.classList.toggle('hidden', mode !== 'import');
    };
    el.crateTabSong.addEventListener('click', () => setCrateMode('song'));
    el.crateTabArtist.addEventListener('click', () => setCrateMode('artist'));
    el.crateTabImport.addEventListener('click', () => setCrateMode('import'));

    el.searchForm.addEventListener('submit', (e) => {
      e.preventDefault();
      performSongSearch();
    });

    el.artistSearchForm.addEventListener('submit', (e) => {
      e.preventDefault();
      performArtistSearch();
    });

    el.catalogLiveFilterInput.addEventListener('input', () => {
      renderFilteredArtistCatalog();
    });

    el.loadMidiUrlBtn.addEventListener('click', async () => {
      const url = el.directMidiUrlInput.value.trim();
      if (!url) return;
      try {
        const bundle = await apiJson('/api/load', { method: 'POST', body: JSON.stringify({ midi_url: url }) });
        applyLoadedSongBundle(bundle);
      } catch (err) {
        alert(err.message);
      }
    });

    el.loadAbcTextBtn.addEventListener('click', async () => {
      const abc = el.customAbcTextarea.value.trim();
      if (!abc) return;
      try {
        const bundle = await apiJson('/api/load', { method: 'POST', body: JSON.stringify({ abc_text: abc }) });
        applyLoadedSongBundle(bundle);
      } catch (err) {
        alert(err.message);
      }
    });

    el.fileUploadInput.addEventListener('change', async () => {
      const f = el.fileUploadInput.files && el.fileUploadInput.files[0];
      if (!f) return;
      const fd = new FormData();
      fd.append('file', f);
      try {
        const resp = await fetch('/api/upload', { method: 'POST', body: fd });
        if (!resp.ok) throw new Error((await resp.json()).detail || 'Upload failed');
        applyLoadedSongBundle(await resp.json());
      } catch (err) {
        alert(err.message);
      } finally {
        el.fileUploadInput.value = '';
      }
    });

    el.startBeatInput.addEventListener('change', () => {
      state.startBeat = Math.max(0, Number(el.startBeatInput.value) || 0);
      if (state.startBeat >= state.endBeat) state.endBeat = state.startBeat + 4;
      syncBeatInputs(true);
    });
    el.endBeatInput.addEventListener('change', () => {
      const maxB = state.activeSong ? state.activeSong.total_beats : 64;
      state.endBeat = Math.min(maxB, Math.max(state.startBeat + 2, Number(el.endBeatInput.value) || 16));
      syncBeatInputs(true);
    });
    el.fitOneStripBtn.addEventListener('click', () => {
      if (!state.activeSong) return;
      const maxBeats = Math.floor((state.existingUsableMm - 12) / Math.max(1, state.mmPerBeat));
      state.endBeat = Math.min(state.activeSong.total_beats, state.startBeat + Math.max(4, maxBeats));
      syncBeatInputs(true);
    });
    el.selectAllBeatsBtn.addEventListener('click', () => {
      if (!state.activeSong) return;
      state.startBeat = 0;
      state.endBeat = state.activeSong.total_beats;
      syncBeatInputs(true);
    });

    el.playKikkerlandBtn.addEventListener('click', () => startPlayback('kikkerland'));
    el.playOriginalBtn.addEventListener('click', () => startPlayback('original'));
    el.stopAudioBtn.addEventListener('click', stopAudio);

    el.applyBestShiftBtn.addEventListener('click', () => {
      if (!state.arrangement) return;
      state.transposeSemitones = state.arrangement.scale_analysis.best_shift;
      requestRearrange(true);
    });
    const bumpShift = (d) => {
      state.transposeSemitones = (state.transposeSemitones || 0) + d;
      requestRearrange(true);
    };
    el.octDownBtn.addEventListener('click', () => bumpShift(-12));
    el.semiDownBtn.addEventListener('click', () => bumpShift(-1));
    el.semiUpBtn.addEventListener('click', () => bumpShift(1));
    el.octUpBtn.addEventListener('click', () => bumpShift(12));

    el.accidentalModeSelect.addEventListener('change', () => {
      state.accidentalMode = el.accidentalModeSelect.value;
      requestRearrange(true);
    });
    el.rangeModeSelect.addEventListener('change', () => {
      state.rangeMode = el.rangeModeSelect.value;
      requestRearrange(true);
    });
    el.mmPerBeatInput.addEventListener('change', () => {
      state.mmPerBeat = Number(el.mmPerBeatInput.value) || 8.0;
      requestRearrange(true);
    });
    el.autoResolveRepeatsCheckbox.addEventListener('change', () => {
      state.autoResolveRepeats = el.autoResolveRepeatsCheckbox.checked;
      requestRearrange(true);
    });
    el.clearManualEditsBtn.addEventListener('click', () => {
      state.manualEdits = [];
      el.clearManualEditsBtn.classList.add('hidden');
      requestRearrange(true);
    });

    // Right Output Bay Toggle (Existing Strip vs A4 Print)
    const setOutputMode = (m) => {
      state.outputMode = m;
      el.bayTabPunchGuide.classList.toggle('active', m === 'punch');
      el.bayTabPrintA4.classList.toggle('active', m === 'a4');
      el.bayPanelPunchGuide.classList.toggle('hidden', m !== 'punch');
      el.bayPanelPrintA4.classList.toggle('hidden', m !== 'a4');
      if (m === 'a4') refreshA4Preview();
    };
    el.bayTabPunchGuide.addEventListener('click', () => setOutputMode('punch'));
    el.bayTabPrintA4.addEventListener('click', () => setOutputMode('a4'));

    el.existingUsableMmInput.addEventListener('change', () => {
      state.existingUsableMm = Math.max(80, Number(el.existingUsableMmInput.value) || 412);
      requestRearrange(true);
    });
    el.existingGridSpacingSelect.addEventListener('change', () => {
      state.existingGridMm = Number(el.existingGridSpacingSelect.value) || 2.0;
      requestRearrange(true);
    });
    el.resetCheckedRowsBtn.addEventListener('click', () => {
      state.checkedRows.clear();
      renderOperatorPunchGuide();
    });
    el.printChecklistBtn.addEventListener('click', () => window.print());
    el.prevPunchRowBtn.addEventListener('click', () => {
      state.focusedRowIdx = Math.max(0, state.focusedRowIdx - 1);
      renderOperatorPunchGuide();
    });
    el.nextPunchRowBtn.addEventListener('click', () => {
      const rows = (state.arrangement && state.arrangement.punch_rows) || [];
      state.focusedRowIdx = Math.min(Math.max(0, rows.length - 1), state.focusedRowIdx + 1);
      renderOperatorPunchGuide();
    });
    el.stampAndAdvanceBtn.addEventListener('click', stampCurrentRowAndAdvance);

    el.a4PageSelect.addEventListener('change', () => {
      state.a4PageIndex = Number(el.a4PageSelect.value) || 0;
      refreshA4Preview();
    });
    el.downloadA4PdfBtn.addEventListener('click', () => downloadExport('/api/export/pdf', 'kikker15_A4.pdf'));
    el.downloadA4SvgBtn.addEventListener('click', () => downloadExport('/api/export/svg', 'kikker15_A4.svg'));

    const KEY_TO_COL = {
      q: 0, w: 1, e: 2, r: 3, t: 4, y: 5, u: 6,
      i: 7, o: 8, p: 9, '[': 10, ']': 11, z: 12, x: 13, c: 14,
    };

    window.addEventListener('keydown', (e) => {
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) return;

      if (state.outputMode === 'punch') {
        const rows = (state.arrangement && state.arrangement.punch_rows) || [];
        if (rows.length) {
          if (e.key === ' ') {
            e.preventDefault();
            stampCurrentRowAndAdvance();
            return;
          }
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            state.focusedRowIdx = Math.min(rows.length - 1, state.focusedRowIdx + 1);
            renderOperatorPunchGuide();
            return;
          }
          if (e.key === 'ArrowUp') {
            e.preventDefault();
            state.focusedRowIdx = Math.max(0, state.focusedRowIdx - 1);
            renderOperatorPunchGuide();
            return;
          }
        }
      }

      const k = e.key.toLowerCase();
      if (!e.metaKey && !e.ctrlKey && !e.altKey && Object.prototype.hasOwnProperty.call(KEY_TO_COL, k)) {
        const col = KEY_TO_COL[k];
        triggerTineVisual(col);
        playSingleMusicBoxPluck(72 + RELATIVE_SEMITONES[col]);
      }
    });

    window.addEventListener('resize', () => {
      drawOverviewCanvas();
      drawCombMechanism();
      drawStripCanvas();
    });
  }

  async function init() {
    bindEvents();
    setupOverviewDrag();
    setupCombInteraction();
    setupManualHandCrank();
    setupStripCanvasClick();
    drawCombMechanism();
    drawCrankDial();

    try {
      state.hardware = await apiJson('/api/hardware');
    } catch (_) {}

    await performSongSearch();
    await loadSongById('builtin:happy-birthday');
  }

  init();
})();
