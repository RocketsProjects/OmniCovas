/**
 * OmniCOVAS Ship-State Rail — shared persistent left-rail schematic card.
 *
 * PB-PHASE10-SUPER-08R3: the left rail is persistent shell chrome shown on every
 * route, so the identity-gated Sidewinder schematic must be built by ONE shared
 * renderer used by both the shell (non-Dashboard routes) and the Dashboard rail.
 * Previously the schematic card was Dashboard-only, so other routes fell back to
 * the shell placeholder with no schematic.
 *
 * Classic script — exposes window.OmniShipStateRail. Safe DOM only (no innerHTML).
 * Depends on window.OmniShipSchematics (ship-schematics.js) for identity resolution.
 *
 * Mandatory identity rule:
 *   - verified ship identity === Sidewinder  -> detailed Sidewinder wireframe asset
 *   - known non-Sidewinder (e.g. panthermkii) -> "Schematic currently unavailable."
 *   - unknown identity                         -> honest unknown wording, never Sidewinder
 *   - asset load failure                       -> "Schematic currently unavailable."
 * The schematic is static decorative reference art; text vitals remain authoritative.
 */

(function () {
  'use strict';

  const SCHEMATIC_UNAVAILABLE_TEXT = 'Schematic currently unavailable.';
  const SCHEMATIC_UNKNOWN_TEXT = 'Ship identity not loaded yet.';
  /* Local detailed Sidewinder wireframe (white linework, transparent bg).
     Path is relative to index.html (static / Tauri frontend root). */
  const SIDEWINDER_SCHEMATIC_ASSET = 'assets/schematics/sidewinder.png';

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function resolveSchematicMode(shipType) {
    const raw = (shipType === undefined || shipType === null ? '' : String(shipType)).trim();
    if (!raw) return 'unknown';
    const key = (window.OmniShipSchematics
      && typeof window.OmniShipSchematics.resolveShipKey === 'function')
      ? window.OmniShipSchematics.resolveShipKey(raw)
      : null;
    return key === 'sidewinder' ? 'sidewinder' : 'unavailable';
  }

  /* Honest empty/unknown box: neutral reticle glyph + message. Never blank, never
     the Sidewinder art. */
  function createSchematicEmptyBox(text) {
    const box = el('div', 'dashboard-uiv3-schematic-empty');
    const reticle = el('div', 'dashboard-uiv3-reticle');
    reticle.setAttribute('aria-hidden', 'true');
    box.append(reticle, el('p', 'dashboard-uiv3-schematic-empty-text', text));
    return box;
  }

  /* The detailed Sidewinder wireframe as a decorative <img>. On asset load
     failure it degrades in place to "Schematic currently unavailable." */
  function createSidewinderSchematicArt() {
    const wrap = el('div', 'ship-schematic ship-schematic--static');
    wrap.setAttribute('data-ship-schematic', 'sidewinder');
    const img = document.createElement('img');
    img.className = 'ship-schematic-art';
    img.src = SIDEWINDER_SCHEMATIC_ASSET;
    img.alt = 'Sidewinder schematic — decorative reference';
    img.setAttribute('decoding', 'async');
    img.setAttribute('draggable', 'false');
    img.addEventListener('error', function () {
      wrap.replaceChildren(createSchematicEmptyBox(SCHEMATIC_UNAVAILABLE_TEXT));
      wrap.classList.add('ship-schematic--unavailable');
    });
    wrap.appendChild(img);
    return wrap;
  }

  function defaultShipLabel(shipType, mode) {
    if (mode === 'sidewinder') return 'SIDEWINDER';
    if (!shipType) return 'UNKNOWN';
    return String(shipType).toUpperCase();
  }

  /**
   * Build the persistent SHIP STATE schematic card (a left-rail panel section).
   *
   * @param {string|null} shipType  verified local ship type (e.g. "sidewinder")
   * @param {object} [options]
   * @param {string} [options.shipLabel]  display label for the head (uppercased by CSS)
   * @param {Array<[string,string]>} [options.metrics]  optional [label,value] rows
   */
  function buildShipSchematicCard(shipType, options) {
    const opts = options || {};
    const mode = resolveSchematicMode(shipType);
    /* Honesty: when identity is not yet verified (mode 'unknown'), the header
       must NOT echo a cached/stale ship label that contradicts the
       "identity not loaded yet" body. Known ships (sidewinder / unavailable)
       keep their real label so non-Sidewinder hulls still name themselves. */
    const shipLabel = mode === 'unknown' ? 'UNKNOWN' : (opts.shipLabel || defaultShipLabel(shipType, mode));

    const card = el(
      'section',
      'uiv3-left-rail-panel dashboard-uiv3-rail-panel dashboard-uiv3-reticle-card '
        + 'dashboard-uiv3-schematic-card uiv3-corner-frame',
    );
    card.setAttribute('aria-label', 'Ship state schematic');
    card.setAttribute('data-schematic-mode', mode);
    if (shipType) card.setAttribute('data-ship-type', String(shipType).toLowerCase());

    const inner = el('div', 'uiv3-corner-frame-inner');

    const head = el('div', 'dashboard-uiv3-schematic-head');
    head.append(
      el('p', 'dashboard-uiv3-eyebrow', 'SHIP SCHEMATIC'),
      el('span', 'dashboard-uiv3-schematic-ship uiv3-data-label', shipLabel),
    );
    inner.appendChild(head);

    if (mode === 'sidewinder') {
      inner.appendChild(createSidewinderSchematicArt());
    } else {
      inner.appendChild(
        createSchematicEmptyBox(mode === 'unavailable' ? SCHEMATIC_UNAVAILABLE_TEXT : SCHEMATIC_UNKNOWN_TEXT),
      );
    }

    const metrics = Array.isArray(opts.metrics) ? opts.metrics : [];
    metrics.forEach(function (entry) {
      const row = el('div', 'dashboard-uiv3-metric-row');
      row.append(
        el('span', 'dashboard-uiv3-metric-label', entry[0]),
        el('span', 'dashboard-uiv3-metric-value uiv3-tabnum', entry[1]),
      );
      inner.appendChild(row);
    });

    if (mode === 'sidewinder') {
      inner.appendChild(el('p', 'dashboard-uiv3-rail-note', 'Static reference schematic'));
    }

    card.appendChild(inner);
    return card;
  }

  window.OmniShipStateRail = {
    resolveSchematicMode,
    buildShipSchematicCard,
    createSidewinderSchematicArt,
    createSchematicEmptyBox,
    SCHEMATIC_UNAVAILABLE_TEXT,
    SCHEMATIC_UNKNOWN_TEXT,
    SIDEWINDER_SCHEMATIC_ASSET,
  };
})();
