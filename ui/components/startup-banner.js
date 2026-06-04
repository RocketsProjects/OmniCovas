/**
 * OmniCOVAS Startup Banner — branded last-known state surface.
 *
 * Authority: authority_files/documents/02_ui_ux_authority/OmniCOVAS_UI_UX_Master_Blueprint_v2_0_Human_Reference.md §9.1
 * Correction #1: when Elite Dangerous is not actively running, the app
 * must look branded and useful, not like a dead ship-systems page. This
 * surface renders the OmniCOVAS wordmark, the Backend connection state,
 * the Elite session state (Active / Waiting / Last known) and the last
 * known ship / system / station from local snapshots. It is hidden when
 * the Elite session is Active so the live Command Center can dominate.
 *
 * Pure presentation over data the rest of the app already derives —
 * no new backend, no new endpoint, no fabricated facts.
 *
 * ADR 0003: all dynamic values via createElement + textContent.
 */
(function () {
  'use strict';

  function safeEl(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text != null) el.textContent = String(text);
    return el;
  }

  /**
   * @param {object} input
   * @param {string} input.backendState       - 'Connected' | 'Disconnected' | 'Core not found'
   * @param {string} input.eliteSessionState  - 'Active' | 'Waiting' | 'Last known' | 'Unknown'
   * @param {string|null} input.localFilesState - 'Loaded' | 'Not loaded' | null
   * @param {boolean} input.usingLastKnown
   * @param {object|null} input.lastKnown     - { shipDisplay, systemName, stationName, dockedLabel }
   * @returns {HTMLElement|null} banner element, or null if session is Active
   */
  function createStartupBanner(input) {
    const elite = input?.eliteSessionState || 'Waiting';
    if (elite === 'Active') return null;

    const backend = input?.backendState || 'Disconnected';
    const localFiles = input?.localFilesState || null;
    const usingLastKnown = input?.usingLastKnown === true || elite === 'Last known';
    const last = input?.lastKnown || null;

    const banner = safeEl('section', 'startup-banner startup-banner--landing');
    banner.setAttribute('role', 'region');
    banner.setAttribute('aria-label', 'OmniCOVAS session status');
    banner.dataset.eliteSession = elite;
    banner.dataset.prominent = elite === 'Waiting' || elite === 'Last known' ? 'true' : 'false';

    const head = safeEl('div', 'startup-banner-head');
    const wordmark = safeEl('h2', 'startup-banner-wordmark', 'OmniCOVAS');
    wordmark.setAttribute('aria-label', 'OmniCOVAS');
    const tagline = safeEl('p', 'startup-banner-tagline', 'Local command deck ready');
    head.append(wordmark, tagline);
    banner.appendChild(head);

    const grid = safeEl('dl', 'startup-banner-grid');
    appendRow(grid, 'Backend', backend, `startup-state startup-state--backend-${slug(backend)}`);
    appendRow(grid, 'Elite session', elite, `startup-state startup-state--elite-${slug(elite)}`);
    if (localFiles) appendRow(grid, 'Local files', localFiles, `startup-state startup-state--files-${slug(localFiles)}`);
    if (usingLastKnown) appendRow(grid, 'Local data', 'Using last-known local data');
    banner.appendChild(grid);

    if (last && (last.shipDisplay || last.systemName || last.stationName)) {
      const lastWrap = safeEl('section', 'startup-banner-last-known');
      lastWrap.setAttribute('aria-label', 'Last known commander context');
      lastWrap.appendChild(safeEl('h3', 'startup-banner-last-known-title', 'Last known'));
      const lkGrid = safeEl('dl', 'startup-banner-grid');
      if (last.shipDisplay)  appendRow(lkGrid, 'Ship',    last.shipDisplay);
      if (last.systemName)   appendRow(lkGrid, 'System',  last.systemName);
      if (last.stationName)  appendRow(lkGrid, 'Station', last.stationName);
      if (last.dockedLabel)  appendRow(lkGrid, 'Docked',  last.dockedLabel);
      lastWrap.appendChild(lkGrid);
      banner.appendChild(lastWrap);
    }

    const hint = safeEl('p', 'startup-banner-hint',
      elite === 'Waiting'
        ? 'Waiting for Elite Dangerous. Launch the game to begin a live session — last-known local data will be used until then.'
        : 'Using last-known local data. Live telemetry will resume on the next Elite Dangerous journal event.');
    if (elite === 'Waiting') {
      hint.textContent = 'Waiting for Elite Dangerous. Last-known local data remains visible until live journal activity resumes.';
    } else if (elite === 'Unknown') {
      hint.textContent = 'Elite session state is unknown. Local data remains visible when source files are loaded.';
    }
    banner.appendChild(hint);

    return banner;
  }

  function appendRow(dl, label, value, valueClass) {
    const dt = safeEl('dt', 'startup-banner-label', label);
    const dd = safeEl('dd', valueClass || 'startup-banner-value', value);
    dl.append(dt, dd);
  }

  function slug(text) {
    return String(text || '').toLowerCase().replace(/[^a-z0-9]+/g, '-');
  }

  /* Public global: dashboard.js mounts via window.OmniStartupBanner.create */
  window.OmniStartupBanner = { create: createStartupBanner };
})();
