/**
 * OmniCOVAS Dashboard — Command Surface (UI v3 target rebuild).
 *
 * Authority: docs/internal/blueprints/OmniCOVAS_UI_UX_Master_Blueprint_v2_0_Human_Reference.md §9.1
 *
 * Dashboard answers "What matters right now?":
 *   1. InterruptBanner (critical states elevate over everything)
 *   2. WatchStrip      (compact ship/route vitals)
 *   3. CommandContextSpine (ship · system · station · destination)
 *   4. UI v3 Command Surface cards inside #dashboard-root
 *
 * Proof layer (collapsed) keeps source/route pins.
 *
 * All dynamic values render via createElement + textContent per ADR 0003.
 * No invented data: only local Status / Loadout / Cargo / NavRoute / Heat.
 */

import {
  formatCredits,
  formatDisplayValue,
  formatLightYears,
  formatTons,
  normalizeCommodityName,
  normalizeShipName,
} from '../components/command-primitives.js';

import {
  PRIMARY_OPERATIONS,
  deriveCommanderContext,
  deriveCommanderLocationState,
  operationLabel,
} from '../view-models/commander-context.js';

import { deriveLocalContext } from '../view-models/local-context.js';

/* ── Utility helpers ── */
const fmt = {
  pct:     (v, dp = 1) => v == null ? '—' : `${v.toFixed(dp)}%`,
  num:     (v) => v == null ? '—' : formatDisplayValue(v, 'number'),
  ly:      (v) => v == null ? '—' : formatLightYears(v),
  t:       (v) => v == null ? '—' : formatTons(v),
  credits: (v) => v == null ? '—' : formatCredits(v),
};

function el(id) { return document.getElementById(id); }

function displayShipName(raw, fallback = 'Unknown ship') {
  const display = normalizeShipName(raw).display;
  return display || fallback;
}

function hullClass(pct) {
  if (pct == null) return '';
  if (pct <= 10) return 'critical';
  if (pct <= 25) return 'warn';
  return 'ok';
}

function fuelClass(pct) {
  if (pct == null) return '';
  if (pct <= 10) return 'critical';
  if (pct <= 25) return 'warn';
  return '';
}

function heatClass(pct) {
  if (pct == null) return '';
  if (pct >= 120) return 'critical';
  if (pct >= 95)  return 'critical';
  if (pct >= 80)  return 'warn';
  return '';
}

/* ── Manual operation override persisted to localStorage. ── */
const OPERATION_STORAGE_KEY = 'omnicovas.manualOperation';

/* Smoke R3: Operations default is selector-only across the entire UI.
   The Commander does not want legacy localStorage values reopening old
   operations automatically; only an explicit current-session click opens
   the workspace. On init we clear stale state and never read it back. */
function readManualOperation() {
  try {
    window.localStorage?.removeItem(OPERATION_STORAGE_KEY);
  } catch { /* localStorage unavailable */ }
  return null;
}

function writeManualOperation(op) {
  try {
    if (op === null) window.sessionStorage?.removeItem(OPERATION_STORAGE_KEY);
    else window.sessionStorage?.setItem(OPERATION_STORAGE_KEY, op);
  } catch { /* localStorage unavailable; redux not required */ }
}

/* ── Legacy schematic / detail helpers retained for the detail drawer ── */

function setCardState(cardId, state) {
  const card = el(cardId);
  if (!card) return;
  card.classList.remove('ok', 'warn', 'critical', 'destroyed');
  if (state) card.classList.add(state);
}

function drawSparkline(canvasEl, samples) {
  if (!canvasEl || !samples || samples.length < 2) return;
  const ctx = canvasEl.getContext('2d');
  const w = canvasEl.offsetWidth || 200;
  const h = canvasEl.offsetHeight || 32;
  canvasEl.width = w;
  canvasEl.height = h;
  ctx.clearRect(0, 0, w, h);
  const max = Math.max(...samples, 1.0);
  const step = w / (samples.length - 1);
  ctx.beginPath();
  ctx.strokeStyle = samples[samples.length - 1] >= 0.80
    ? 'var(--color-critical, #ff3333)'
    : 'var(--color-accent, #ff8800)';
  ctx.lineWidth = 1.5;
  samples.forEach((s, i) => {
    const x = i * step;
    const y = h - (s / max) * (h - 4) - 2;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();
}

/* Repair R11 + smoke R1: use the unified deriveCommanderLocationState so
   the Ship Identity card never contradicts the context bar.

   Specifically: when Elite is not running and ship-state reports
   is_docked=false but the local Journal context preserved a Docked event
   at the commander's last station, we must NOT render "Flight state: In
   flight" — we render "Docking state: Last known docked" instead. */
function renderShipState(s) {
  const set = (id, val) => { const e = el(id); if (e) e.textContent = val ?? '—'; };
  const localContext = currentLocalContext();
  const sessionState = window.Shell?.eliteSessionState || null;
  const loc = deriveCommanderLocationState(localContext, s, _lastNavSnap, { sessionState });

  const shipTypeDisplay = s.ship_type ? displayShipName(s.ship_type) : 'UNKNOWN';
  const sanitizedShipName = (s.ship_name && s.ship_name.trim().length > 0)
    ? s.ship_name.trim()
    : shipTypeDisplay;
  set('dash-ship-type',  shipTypeDisplay);
  set('dash-ship-name',  sanitizedShipName);
  set('dash-ship-ident', s.ship_ident);
  set('dash-system',     loc.systemName);
  set('dash-station',    loc.stationName);
  const dockedEl = el('dash-docked');
  const dockedLabelEl = el('dash-docked-label');
  if (dockedEl) {
    if (dockedLabelEl) dockedLabelEl.textContent = loc.flightLabel || 'Docking state';
    dockedEl.textContent = loc.flightValue || '—';
    const okState = loc.dockingState === 'docked' || loc.dockingState === 'last_known_docked'
      || loc.dockingState === 'partial';
    dockedEl.className = 'field-value ' + (okState ? 'ok' : (loc.dockingState === 'unknown' ? 'unknown' : ''));
  }
  const wantedEl = el('dash-wanted');
  if (wantedEl) {
    wantedEl.textContent = s.is_wanted_in_system ? 'WANTED' : '—';
    wantedEl.className = 'field-value ' + (s.is_wanted_in_system ? 'critical' : 'unknown');
  }
}

/* Correction #2 (repaired): the /pillar1/modules/summary endpoint
   returns only counts. The actual per-module list lives in the local
   context snapshot under module_loadout.modules. Accept either a raw
   modules-summary object (legacy callers / tests) OR the local context
   snapshot, and check for a ShieldGenerator slot in whichever has one. */
function shieldGeneratorFitted(modulesOrLocalContext) {
  if (!modulesOrLocalContext) return null;
  const explicit = [
    modulesOrLocalContext.shield_generator?.fitted,
    modulesOrLocalContext.shieldGenerator?.fitted,
    modulesOrLocalContext.module_loadout?.shield_generator?.fitted,
    modulesOrLocalContext.moduleLoadout?.shieldGenerator?.fitted,
    modulesOrLocalContext.moduleSearch?.shieldGenerator?.fitted,
  ];
  for (const fitted of explicit) {
    if (fitted === true || fitted === false) return fitted;
    if (fitted === null) return null;
  }
  const candidates = [
    modulesOrLocalContext.modules,
    modulesOrLocalContext.loadout?.modules,
    modulesOrLocalContext.module_loadout?.modules,
    modulesOrLocalContext.moduleSearch?.modules,
  ];
  const list = candidates.find((c) => Array.isArray(c));
  if (!Array.isArray(list)) return null;
  return list.some((m) => {
    const slot = (m?.slot || m?.Slot || '').toString().toLowerCase();
    const item = (m?.item || m?.Item || m?.display || m?.name || '').toString().toLowerCase();
    return slot.includes('shieldgenerator') || item.includes('shieldgenerator')
      || item.includes('shield generator');
  });
}

function renderHullShields(s, modules) {
  const hullPct = s.hull_health;
  const cls = hullClass(hullPct);
  const hullVal = el('dash-hull-value');
  if (hullVal) {
    hullVal.textContent = fmt.pct(hullPct);
    hullVal.className = 'field-value ' + cls;
  }
  const bar = el('dash-hull-bar');
  if (bar) {
    bar.style.width = (hullPct ?? 0) + '%';
    bar.className = 'progress-bar-fill ' + cls;
  }
  setCardState('dash-panel-hull-shields', cls || null);

  /* Correction #2: configuration-aware shield state.
       fitted=true  → ONLINE / DOWN / OFFLINE / UNKNOWN
       fitted=false → NO SHIELD GENERATOR INSTALLED (muted, not critical)
       fitted=null  → UNKNOWN until loadout arrives */
  const fitted = shieldGeneratorFitted(modules);
  const shieldEl = el('dash-shield');
  if (shieldEl) {
    if (fitted === false) {
      shieldEl.textContent = 'No shield generator installed';
      shieldEl.className = 'badge muted shield-no-generator';
    } else if (s.shield_up == null) {
      shieldEl.textContent = '—';
      shieldEl.className = 'badge muted';
    } else if (s.shield_up) {
      shieldEl.textContent = 'ONLINE';
      shieldEl.className = 'badge ok';
    } else {
      shieldEl.textContent = 'DOWN';
      shieldEl.className = 'badge critical';
    }
  }
  const shieldPctEl = el('dash-shield-pct');
  if (shieldPctEl) {
    if (fitted === false) {
      shieldPctEl.textContent = 'N/A';
      shieldPctEl.className = 'field-value unknown';
    } else {
      shieldPctEl.textContent = s.shield_strength_pct != null ? fmt.pct(s.shield_strength_pct) : '—';
      shieldPctEl.className = 'field-value' + (s.shield_strength_pct == null ? ' unknown' : '');
    }
  }
}

function renderFuel(s) {
  const fuelPct = s.fuel_pct;
  const cls = fuelClass(fuelPct);
  const fuelVal = el('dash-fuel-value');
  if (fuelVal) { fuelVal.textContent = fmt.pct(fuelPct); fuelVal.className = 'field-value ' + cls; }
  const bar = el('dash-fuel-bar');
  if (bar) { bar.style.width = (fuelPct ?? 0) + '%'; bar.className = 'progress-bar-fill ' + cls; }
  const fuelRaw = el('dash-fuel-raw');
  if (fuelRaw) fuelRaw.textContent = `${fmt.t(s.fuel_main)} / ${fmt.t(s.fuel_capacity)}`;
  const jump = el('dash-jump');
  if (jump) jump.textContent = fmt.ly(s.jump_range_ly);
  setCardState('dash-panel-fuel-jump', cls || null);
}

function renderCargo(s, inventory) {
  const countEl = el('dash-cargo-count');
  if (countEl) {
    countEl.textContent =
      s.cargo_count != null && s.cargo_capacity != null
        ? `${s.cargo_count} / ${s.cargo_capacity}`
        : '—';
  }
  const listEl = el('dash-cargo-list');
  if (listEl) {
    const items = (inventory || []).slice(0, 5);
    if (items.length === 0) {
      const emptyLi = document.createElement('li');
      emptyLi.className = 'field-value unknown';
      emptyLi.textContent = 'No cargo detected';
      listEl.replaceChildren(emptyLi);
    } else {
      const nodes = items.map(item => {
        const li = document.createElement('li');
        li.className = 'field-row';
        const nameSpan = document.createElement('span');
        nameSpan.className = 'field-label';
        nameSpan.textContent = normalizeCommodityName(item.name).display;
        const countSpan = document.createElement('span');
        countSpan.className = 'field-value';
        countSpan.textContent = item.count;
        li.appendChild(nameSpan);
        li.appendChild(countSpan);
        return li;
      });
      listEl.replaceChildren(...nodes);
    }
  }
}

function renderHeat(heat) {
  const heatPct = Number.isFinite(heat?.level_pct) ? heat.level_pct : null;
  const state   = heat?.state ?? null;
  const samples = Array.isArray(heat?.samples) ? heat.samples : [];
  const trend   = samples.length > 0 ? (heat?.trend ?? null) : null;
  const cls     = heatClass(heatPct);
  const heatVal = el('dash-heat-value');
  if (heatVal) { heatVal.textContent = heatPct != null ? fmt.pct(heatPct, 0) : 'UNKNOWN'; heatVal.className = 'field-value ' + cls; }
  const bar = el('dash-heat-bar');
  if (bar) { bar.style.width = heatPct != null ? (Math.min(heatPct, 150) / 1.5 + '%') : '0%'; bar.className = 'progress-bar-fill ' + cls; }
  const trendEl = el('dash-heat-trend');
  if (trendEl && trend) {
    const arrows = { rising: '↑', falling: '↓', steady: '→' };
    trendEl.textContent = (arrows[trend] || '') + ' ' + trend;
    trendEl.className = 'trend ' + (trend || 'steady');
  }
  const stateEl = el('dash-heat-state');
  if (stateEl) {
    if (heatPct == null && state == null) { stateEl.textContent = ''; stateEl.className = 'badge muted'; }
    else if (state) {
      stateEl.textContent = state.toUpperCase();
      stateEl.className = 'badge ' + (state === 'warning' ? 'warn' : (state === 'damage' || state === 'critical' ? 'critical' : 'ok'));
    } else { stateEl.textContent = 'NORMAL'; stateEl.className = 'badge ok'; }
  }
  const heatAbsenceEl = el('dash-heat-absence');
  if (heatAbsenceEl) heatAbsenceEl.style.display = 'none';
  drawSparkline(el('dash-heat-sparkline'), samples);
  setCardState('dash-panel-heat-core', cls || null);
}

function renderPipsGroup(groupId, value) {
  const group = el(groupId);
  if (!group) return;
  const dotsEl = group.querySelector('.pips-dots');
  if (!dotsEl) return;
  dotsEl.replaceChildren();
  for (let i = 0; i < 8; i++) {
    const pip = document.createElement('span');
    pip.className = 'pip' + (value != null && i < value ? ' filled' : '');
    pip.setAttribute('aria-hidden', 'true');
    dotsEl.appendChild(pip);
  }
}

function renderPips(s) {
  renderPipsGroup('pips-sys', s.sys_pips);
  renderPipsGroup('pips-eng', s.eng_pips);
  renderPipsGroup('pips-wep', s.wep_pips);
}

function renderModules(summary) {
  const absenceEl = el('dash-modules-absence');
  if (!summary) { if (absenceEl) absenceEl.style.display = ''; return; }
  if (absenceEl) absenceEl.style.display = 'none';
  const set = (id, val) => { const e = el(id); if (e) e.textContent = val ?? '—'; };
  set('dash-mod-ok', summary.ok);
  set('dash-mod-warning', summary.warning);
  set('dash-mod-critical', summary.critical);
  set('dash-mod-total', summary.total);
  const critEl = el('dash-mod-critical');
  if (critEl) critEl.className = 'field-value' + (summary.critical > 0 ? ' critical' : ' ok');
  const warnEl = el('dash-mod-warning');
  if (warnEl) warnEl.className = 'field-value' + (summary.warning > 0 ? ' warn' : '');
  if (summary.critical > 0) setCardState('dash-panel-modules', 'critical');
  else if (summary.warning > 0) setCardState('dash-panel-modules', 'warn');
  else setCardState('dash-panel-modules', null);
}

/* Repair R9: Commander Wallet bar. Every row is hidden until the local
   source supplies a real value. When no rows are populated, surface a
   single honest "Wallet not loaded" line — never a column of dashes. */
function walletValue(walletSnapshot, key) {
  const entry = walletSnapshot?.[key];
  if (!entry || typeof entry !== 'object') return null;
  return entry.value ?? null;
}

function renderWallet(walletSnapshot) {
  const credits = walletValue(walletSnapshot, 'credits');
  const rebuyCost = walletValue(walletSnapshot, 'rebuy');
  const insurance = walletValue(walletSnapshot, 'insurance');
  const carrierBalance = walletValue(walletSnapshot, 'carrier_balance');

  const showRow = (rowId, valueId, value) => {
    const row = el(rowId);
    const val = el(valueId);
    if (!row || !val) return false;
    if (value == null) { row.hidden = true; return false; }
    val.textContent = value;
    val.className = 'field-value';
    row.hidden = false;
    return true;
  };

  const rows = [
    showRow('dash-wallet-credits-row', 'dash-wallet-credits',
            credits != null ? fmt.credits(credits) : null),
    showRow('dash-wallet-rebuy-row', 'dash-wallet-rebuy',
            rebuyCost != null ? fmt.credits(rebuyCost) : null),
    showRow('dash-wallet-insurance-row', 'dash-wallet-insurance',
            insurance != null ? String(insurance) : null),
    showRow('dash-wallet-carrier-row', 'dash-wallet-carrier',
            carrierBalance != null ? fmt.credits(carrierBalance) : null),
  ];
  const anyRow = rows.some(Boolean);

  const emptyEl = el('dash-wallet-empty');
  if (emptyEl) emptyEl.hidden = Boolean(anyRow);
}

/* PB05-06 schematic — preserved inside the demoted detail drawer */
function resolveDashboardShipType(state) {
  return (state && state.ship_type) ? state.ship_type : null;
}
function renderSchematicStatus(shipType, resolvedKey) {
  const statusEl = el('dash-schematic-status');
  if (!statusEl) return;
  if (resolvedKey === 'sidewinder') {
    statusEl.textContent = 'Sidewinder schematic active';
  } else {
    const known = shipType && window.OmniShipSchematics &&
      window.OmniShipSchematics.hasSchematic(shipType) &&
      window.OmniShipSchematics.resolveShipKey(shipType) !== 'generic';
    statusEl.textContent = known
      ? resolvedKey + ' schematic active'
      : 'Generic schematic active — Ship-specific schematic not yet available';
  }
}
let _lastMountedSchematicKey = undefined;
function renderShipSchematic(state) {
  const frame    = el('dash-ship-schematic');
  const statusEl = el('dash-schematic-status');
  if (!frame) return;
  if (!window.OmniShipSchematic || !window.OmniShipSchematics) {
    if (statusEl) statusEl.textContent = 'Ship schematic unavailable';
    return;
  }
  const rawShipType = resolveDashboardShipType(state);
  const resolvedKey = window.OmniShipSchematics.resolveShipKey(rawShipType);
  if (_lastMountedSchematicKey === resolvedKey) return;
  _lastMountedSchematicKey = resolvedKey;
  frame.textContent = '';
  window.OmniShipSchematic.mount(frame, rawShipType);
  renderSchematicStatus(rawShipType, resolvedKey);
}

/* Panel toggle support — preserved for schematic hotspot UX */
let _togglesInitialized = false;
function setDashboardPanelVisibility(panelId, visible) {
  const panel = el(panelId);
  if (!panel) return;
  if (visible) { panel.removeAttribute('hidden'); panel.classList.remove('dashboard-panel-hidden'); }
  else { panel.setAttribute('hidden', ''); panel.classList.add('dashboard-panel-hidden'); }
}
function updateHotspotExpandedState(panelId, visible) {
  const frame = el('dash-ship-schematic');
  if (!frame) return;
  const selector = '.ship-schematic-hotspot-button[aria-controls="' + panelId + '"]';
  frame.querySelectorAll(selector).forEach(function (btn) {
    btn.setAttribute('aria-expanded', String(visible));
    if (visible) { btn.classList.add('is-expanded'); btn.classList.remove('is-collapsed'); }
    else { btn.classList.remove('is-expanded'); btn.classList.add('is-collapsed'); }
  });
}
function showAllDashboardPanels() {
  const frame    = el('dash-ship-schematic');
  const panelIds = new Set();
  if (frame) {
    frame.querySelectorAll('.ship-schematic-hotspot-button[aria-controls]').forEach(function (btn) {
      const pid = btn.getAttribute('aria-controls');
      if (pid) panelIds.add(pid);
    });
  }
  panelIds.forEach(function (panelId) {
    setDashboardPanelVisibility(panelId, true);
    updateHotspotExpandedState(panelId, true);
  });
}
function ensureDashboardResetControl() {
  const btn = el('dash-show-all-systems-btn');
  if (btn && !btn.dataset.toggleWired) {
    btn.dataset.toggleWired = 'true';
    btn.addEventListener('click', showAllDashboardPanels);
  }
  ensureDashboardDetailsToggle();
}

/* Correction #15: single Show details / Hide details toggle on the Ship
   Systems centerpiece. Flips visibility of every callout panel together. */
function hideAllDashboardPanels() {
  const frame = el('dash-ship-schematic');
  const panelIds = new Set();
  if (frame) {
    frame.querySelectorAll('.ship-schematic-hotspot-button[aria-controls]').forEach(function (btn) {
      const pid = btn.getAttribute('aria-controls');
      if (pid) panelIds.add(pid);
    });
  }
  panelIds.forEach(function (panelId) {
    setDashboardPanelVisibility(panelId, false);
    updateHotspotExpandedState(panelId, false);
  });
}

function ensureDashboardDetailsToggle() {
  const btn = el('dash-toggle-details-btn');
  if (!btn || btn.dataset.toggleWired) return;
  btn.dataset.toggleWired = 'true';
  btn.addEventListener('click', function () {
    const showing = btn.getAttribute('aria-pressed') === 'true';
    if (showing) {
      hideAllDashboardPanels();
      btn.setAttribute('aria-pressed', 'false');
      btn.textContent = 'Show details';
    } else {
      showAllDashboardPanels();
      btn.setAttribute('aria-pressed', 'true');
      btn.textContent = 'Hide details';
    }
  });
}

function initializeDashboardPanelToggles() {
  if (_togglesInitialized) return;
  _togglesInitialized = true;
  const frame = el('dash-schematic-frame');
  if (frame) {
    frame.addEventListener('click', function (ev) {
      const btn = ev.target.closest('.ship-schematic-hotspot-button');
      if (!btn) return;
      const panelId = btn.getAttribute('aria-controls');
      if (!panelId) return;
      const panel = el(panelId);
      if (!panel) return;
      const isVisible = !panel.hasAttribute('hidden') &&
                        !panel.classList.contains('dashboard-panel-hidden');
      setDashboardPanelVisibility(panelId, !isVisible);
      updateHotspotExpandedState(panelId, !isVisible);
    });
  }
  ensureDashboardResetControl();
}

/* ─────────────────────────────────────────────
   Fetch helpers
───────────────────────────────────────────── */
async function fetchJSON(path) {
  const base = window.Shell?.httpBase
    || (window.OMNICOVAS_PORT ? `http://127.0.0.1:${window.OMNICOVAS_PORT}` : null);
  if (!base) return null;
  try {
    const r = await fetch(`${base}${path}`);
    return r.ok ? await r.json() : null;
  } catch { return null; }
}

function safeEl(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function currentLocalContext() {
  return deriveLocalContext(_lastLocalContextSnap);
}

const DASHBOARD_SOURCE_NODES = [
  'station_context',
  'system_context',
  'market_snapshot',
  'cargo_hold',
  'module_loadout',
];

function isDashboardRouteActive() {
  const view = el('view-dashboard');
  if (!view) return true;
  const activeView = document.querySelector('.view.active');
  return !activeView || view.classList.contains('active');
}

function cleanText(value, fallback = '—') {
  if (value === null || value === undefined) return fallback;
  const text = String(value).trim();
  return text || fallback;
}

function cleanKnown(value, fallback = 'Unknown') {
  const text = cleanText(value, fallback);
  return /^unknown$/i.test(text) ? fallback : text;
}

function cleanShipIdentity(state, fallback = 'Unknown') {
  return cleanText(state?.ship_name, '') || cleanText(state?.ship_type, fallback);
}

function uppercaseValue(value, fallback = 'UNKNOWN') {
  return cleanText(value, fallback).toUpperCase();
}

function statusDot(kind = 'info') {
  const dot = safeEl('span', `uiv3-dot uiv3-dot--${kind}`);
  dot.setAttribute('aria-hidden', 'true');
  return dot;
}

function appendText(parent, text) {
  parent.appendChild(document.createTextNode(text));
}

/* DASHBOARD_STATUS_CLARITY_01: watch chips accept an accessible title and an
   optional detail route. When href is set the chip becomes a link to where the
   detail lives (Sources & Diagnostics, Activity Log) so an opaque counter is
   always one click from its explanation. title doubles as the aria-label. */
function createWatchItem(label, value, kind = 'info', options = {}) {
  const { title = null, href = null } = options;
  const item = safeEl(href ? 'a' : 'span', 'uiv3-watch-item');
  if (href) {
    item.setAttribute('href', href);
    item.classList.add('uiv3-watch-item--link');
  }
  if (title) {
    item.setAttribute('title', title);
    item.setAttribute('aria-label', title);
  }
  item.append(statusDot(kind), document.createTextNode(label), safeEl('span', 'uiv3-watch-value', value));
  return item;
}

function replaceDashboardOwnedSlot(node, children) {
  if (!node) return;
  node.setAttribute('data-uiv3-owner', 'dashboard');
  node.replaceChildren(...children);
}

function resetDashboardOwnedSlot(node, children) {
  if (!node || node.getAttribute('data-uiv3-owner') !== 'dashboard') return;
  node.removeAttribute('data-uiv3-owner');
  node.replaceChildren(...children);
}

function resetUiv3DashboardFrame() {
  if (typeof window.Shell?.renderUiv3Frame === 'function') {
    window.Shell.renderUiv3Frame();
    return;
  }

  [el('uiv3-watch-ribbon'), el('uiv3-left-rail'), el('uiv3-bottom-spine')]
    .forEach((node) => resetDashboardOwnedSlot(node, []));
}

function sourceNodeLoaded(node) {
  return Boolean(node && typeof node === 'object' && node.freshness !== 'not_loaded' && !node.fallback);
}

function sourceFreshnessSummary(rawLocalContext, sourceSnap) {
  if (Array.isArray(sourceSnap?.sources) && sourceSnap.sources.length > 0) {
    const total = sourceSnap.sources.length;
    const loaded = sourceSnap.sources.filter((entry) => {
      const state = String(entry?.state || entry?.status || '').toLowerCase();
      return state === 'loaded' || state === 'ready' || state === 'ok' || state === 'enabled';
    }).length;
    return {
      label: `${loaded}/${total} detailed checks`,
      posture: loaded === total ? 'Fresh' : (loaded > 0 ? 'Partial' : 'Not loaded'),
      kind: loaded === total ? 'ok' : (loaded > 0 ? 'warn' : 'info'),
    };
  }

  if (rawLocalContext) {
    const loaded = DASHBOARD_SOURCE_NODES
      .filter((key) => sourceNodeLoaded(rawLocalContext[key]))
      .length;
    return {
      label: `${loaded}/${DASHBOARD_SOURCE_NODES.length} local`,
      posture: loaded > 0 ? 'Last-known' : 'Not Loaded',
      kind: loaded > 0 ? 'info' : 'warn',
    };
  }

  return { label: 'Local data waiting', posture: 'Not Loaded', kind: 'warn' };
}

function hasNavigationRoute(navSnap) {
  const route = navSnap?.active_route || null;
  return Boolean(route?.destination);
}

function combatActive(combat) {
  if (!combat || typeof combat !== 'object') return false;
  const threat = combat.threat_level ?? combat.threatLevel;
  return Boolean(
    combat.active
    || combat.in_combat
    || combat.combat_active
    || combat.hostile
    || (Number.isFinite(combat.hostile_count) && combat.hostile_count > 0)
    || (Array.isArray(combat.contacts) && combat.contacts.length > 0)
    || (typeof threat === 'string' && !/^none|unknown|clear$/i.test(threat))
  );
}

function deriveDashboardOperation(input, ctx) {
  const local = input.localContext || null;
  const station = local?.stationBrief || null;
  const location = ctx?.location || null;
  const route = input.navSnap?.active_route || null;

  let operation = null;
  let source = 'unknown';
  if (_manualOperation && PRIMARY_OPERATIONS.includes(_manualOperation)) {
    operation = _manualOperation;
    source = 'active workspace';
  } else if (station?.available && (
    station.isDocked === true
    || location?.dockingState === 'docked'
    || location?.dockingState === 'last_known_docked'
    || location?.dockingState === 'partial'
  )) {
    operation = 'station';
    source = station.isDocked === true || location?.dockingState === 'docked'
      ? 'local docked context'
      : 'last-known station context';
  } else if (hasNavigationRoute(input.navSnap)) {
    operation = 'travel';
    source = 'navigation snapshot';
  } else if (combatActive(input.combat)) {
    operation = 'combat';
    source = 'combat snapshot';
  }

  const label = operation ? operationLabel(operation) : 'Unknown';
  const badge = operation ? label.toUpperCase() : 'OP UNKNOWN';
  const destination = cleanText(route?.destination, null);
  const stationName = cleanText(station?.stationName || location?.stationName, null);
  const systemName = cleanText(station?.systemName || location?.systemName, null);
  const stationPrefix = location?.dockingState === 'last_known_docked' ? 'Last known docked at' : 'Docked at';

  let title = 'No current operation selected.';
  let description = 'No current operation state is loaded from local context yet.';
  if (operation === 'station') {
    title = stationName ? `${stationPrefix} ${stationName}.` : 'Station operation context loaded.';
    const parts = [];
    if (systemName) parts.push(`System ${systemName}`);
    if (station?.economySummary && station.economySummary !== 'Unknown') parts.push(`${station.economySummary} economy`);
    if (station?.factionSummary && station.factionSummary !== 'Unknown') parts.push(`${station.factionSummary} local authority`);
    description = parts.length
      ? `${parts.join(' · ')}.`
      : 'Local station context is loaded; additional station fields remain unknown.';
  } else if (operation === 'travel') {
    title = destination ? `Route plotted to ${destination}.` : 'Travel operation context loaded.';
    description = 'Navigation snapshot reports an active route. Open Navigation for route detail and actions.';
  } else if (operation === 'combat') {
    title = 'Combat context active.';
    description = 'Combat state is present in the local snapshot. Expand Operations for the active combat workspace.';
  } else if (operation === 'idle') {
    title = 'Idle operations standing by.';
    description = 'No route, station task, or combat context is active in the current operation state.';
  } else if (operation) {
    title = `${label} operation selected.`;
    description = 'Operation state is present locally. Expand Operations for workflow detail.';
  }

  return { operation, label, badge, source, title, description };
}

function detailRowValue(rows, label, fallback = '—') {
  const row = Array.isArray(rows)
    ? rows.find((entry) => String(entry?.label || '').toLowerCase() === label.toLowerCase())
    : null;
  const value = cleanText(row?.value, fallback);
  return /^unknown$/i.test(value) ? fallback : value;
}

function cargoSummary(input, fallback = '—') {
  const state = input.state || {};
  const localCargo = input.localContext?.cargoHold || null;
  if (state.cargo_count != null && state.cargo_capacity != null) {
    return `${state.cargo_count}/${state.cargo_capacity} t`;
  }
  if (localCargo?.used != null && localCargo?.capacity != null) {
    return `${localCargo.used}/${localCargo.capacity} t`;
  }
  if (localCargo?.usedLabel && localCargo?.capacityLabel) {
    return `${localCargo.usedLabel}/${localCargo.capacityLabel}`;
  }
  const inventory = Array.isArray(input.cargo?.inventory) ? input.cargo.inventory : [];
  if (inventory.length > 0) return `${inventory.length} types`;
  return fallback;
}

function hullSummary(state) {
  return state?.hull_health != null ? `${Math.round(state.hull_health)}%` : '—';
}

function shieldsSummary(input) {
  const state = input.state || {};
  const fitted = shieldGeneratorFitted(input.localContext?.rawLoaded ? _lastLocalContextSnap : (_lastLocalContextSnap || input.mods));
  if (fitted === false) return 'None fitted';
  if (state.shield_up === true) return 'UP';
  if (state.shield_up === false) return 'DOWN';
  return '—';
}

function fuelSummary(state) {
  return state?.fuel_pct != null ? `${Math.round(state.fuel_pct)}%` : '—';
}

function heatSummary(heat) {
  return heat?.level_pct != null ? `${Math.round(heat.level_pct)}%` : '—';
}

function walletField(field, fallback = '—') {
  const wallet = _lastLocalContextSnap?.wallet_snapshot || null;
  return fmt.credits(wallet?.[field] ?? null) || fallback;
}

function jumpRangeValue(state) {
  const raw = state?.jump_range_ly ?? state?.jump_range ?? state?.max_jump_range;
  return raw != null ? fmt.ly(raw) : '—';
}

function routeSummary(navSnap) {
  const route = navSnap?.active_route || null;
  const destination = cleanText(route?.destination, null);
  if (!destination) {
    return {
      title: 'No route plotted.',
      summary: 'Navigation has no active local route snapshot.',
      status: 'Route',
      destination: 'No route plotted',
      action: 'OPEN NAVIGATION',
    };
  }
  const hopCount = route.hop_count ?? route.jumps ?? (Array.isArray(route.route) ? route.route.length : null);
  return {
    title: `Route to ${destination}.`,
    summary: hopCount != null ? `${hopCount} hop${hopCount === 1 ? '' : 's'} reported by navigation snapshot.` : 'Navigation snapshot reports an active destination.',
    status: 'Route active',
    destination,
    action: 'OPEN NAVIGATION',
  };
}

function activityEntries(activityLog) {
  if (Array.isArray(activityLog)) return activityLog;
  if (Array.isArray(activityLog?.entries)) return activityLog.entries;
  if (Array.isArray(activityLog?.events)) return activityLog.events;
  if (Array.isArray(activityLog?.items)) return activityLog.items;
  return [];
}

function activityLogText(value, fallback = '') {
  if (value === null || value === undefined) return fallback;
  return String(value).trim() || fallback;
}

function activityLogType(entry) {
  return activityLogText(entry?.event_type || entry?.event, 'Event');
}

function activityLogSummary(entry) {
  return activityLogText(entry?.summary || entry?.message, 'Event recorded');
}

function activityLogTimestamp(entry) {
  return activityLogText(entry?.timestamp || entry?.created_at, 'Time not recorded');
}

function buildDashboardModel(input, ctx) {
  const sourceSummary = sourceFreshnessSummary(_lastLocalContextSnap, input.sourceSnap);
  const operation = deriveDashboardOperation(input, ctx);
  const route = routeSummary(input.navSnap);
  const entries = activityEntries(input.activityLog).slice(0, 3);
  const station = input.localContext?.stationBrief || null;
  const interrupts = Array.isArray(ctx?.interrupts) ? ctx.interrupts : [];
  const attention = ctx?.interrupts ? interrupts.length : null;
  const sessionState = cleanText(input.sessionState || window.Shell?.eliteSessionState, 'Not Loaded');
  const hasSourceData = Boolean(_lastLocalContextSnap || input.sourceSnap);

  /* DASHBOARD_STATUS_CLARITY_01: derive a human reason for the watch/alert
     chips from the active interrupts so chips name the actual condition
     (e.g. "Fuel critical") instead of opaque counters. */
  const alertReasons = interrupts.map((i) => i.label).filter(Boolean);
  const primaryReason = (
    interrupts.find((i) => i.severity === 'critical')
    || interrupts.find((i) => i.severity === 'warning')
    || null
  )?.label || null;
  const reasonSummary = alertReasons.length ? alertReasons.join(', ') : null;
  const alertCountTitle = (count) =>
    `${count} active alert${count === 1 ? '' : 's'}${reasonSummary ? `: ${reasonSummary}` : ''}. Open Activity Log for detail.`;

  const watchState = attention === null
    ? { label: 'Unknown', kind: 'info',
        title: 'Watch state unknown — local telemetry not loaded yet.' }
    : attention > 0
      ? { label: primaryReason || 'Action needed', kind: 'warn', title: alertCountTitle(attention) }
      : { label: hasSourceData ? 'Nominal' : 'Unknown',
          kind: hasSourceData ? 'ok' : 'info',
          title: hasSourceData
            ? 'All monitored vitals nominal.'
            : 'Watch state unknown — local telemetry not loaded yet.' };

  const diagnosticsNotLoaded = /not\s*loaded/i.test(sourceSummary.posture);
  const diagnostics = {
    value: diagnosticsNotLoaded ? 'Not loaded' : sourceSummary.label,
    kind: sourceSummary.kind,
    title: diagnosticsNotLoaded
      ? 'Detailed source checks are not loaded yet. Open Sources & Diagnostics.'
      : `Source diagnostics: ${sourceSummary.label} (${sourceSummary.posture}). Open Sources & Diagnostics.`,
    href: '#/sources',
  };

  const alerts = {
    value: attention === null ? 'Unknown' : attention === 0 ? 'None' : `${attention} active`,
    kind: attention && attention > 0 ? 'warn' : (attention === null ? 'info' : 'ok'),
    title: attention === null
      ? 'Alert state unknown — local telemetry not loaded yet.'
      : attention === 0
        ? 'No active alerts.'
        : alertCountTitle(attention),
    href: attention && attention > 0 ? '#/activity-log' : null,
  };

  const dataPosture = /active/i.test(sessionState)
    ? 'LOCAL · LIVE'
    : /last/i.test(sessionState)
      ? 'LOCAL · LAST-KNOWN'
      : 'LOCAL · NOT LOADED';

  return {
    operation,
    sourceSummary,
    route,
    activityEntries: entries,
    alertLabel: attention === null
      ? 'ALERTS UNKNOWN'
      : attention === 0
        ? '0 ALERTS · NOTHING URGENT'
        : `${attention} ALERT${attention === 1 ? '' : 'S'} · ${(primaryReason || 'ATTENTION').toUpperCase()}`,
    alertKind: attention && attention > 0 ? 'warn' : 'ok',
    watch: {
      watchState,
      opLabel: operation.operation ? `OP ${operation.label.toUpperCase()}` : 'OP UNKNOWN',
      opKind: operation.operation ? 'ok' : 'warn',
      diagnostics,
      alerts,
      dataPosture,
    },
    facts: [
      ['Type', operation.operation === 'station' ? cleanKnown(station?.stationType, 'Unknown') : 'Unknown'],
      ['Distance from Star', operation.operation === 'station' ? detailRowValue(station?.detailRows, 'Distance from star') : '—'],
      ['Economy', operation.operation === 'station' ? cleanKnown(station?.economySummary, 'Unknown') : 'Unknown'],
      ['Docking', cleanText(ctx?.location?.flightValue || station?.dockedLabel, 'Unknown')],
    ],
    snapshot: cleanText(input.localContext?.generatedAt || _lastLocalContextSnap?.generated_at, '—'),
    vitals: {
      hull: hullSummary(input.state),
      shields: shieldsSummary(input),
      fuel: fuelSummary(input.state),
      heat: heatSummary(input.heat),
      cargo: cargoSummary(input),
      modules: input.localContext?.moduleSearch?.moduleCount != null
        ? String(input.localContext.moduleSearch.moduleCount)
        : (_lastMods?.total != null ? String(_lastMods.total) : '—'),
      credits: walletField('credits'),
      rebuy: walletField('rebuy'),
      jump: jumpRangeValue(input.state),
      fuelTank: input.state?.fuel_capacity != null ? fmt.t(input.state.fuel_capacity) : '—',
      route: route.destination,
      ship: cleanShipIdentity(input.state),
    },
  };
}

function getDashboardRoot() {
  const root = el('dashboard-root');
  if (!root) return null;
  root.classList.add('dashboard-uiv3-surface');
  root.removeAttribute('hidden');
  root.removeAttribute('aria-hidden');
  return root;
}

function createDashboardTitle() {
  const title = safeEl('h1', 'dashboard-uiv3-route-title', 'Dashboard');
  title.id = 'dashboard-title';
  return title;
}

function createDashboardBreadcrumb() {
  const nav = safeEl('nav', 'dashboard-uiv3-breadcrumb');
  nav.setAttribute('aria-label', 'Dashboard breadcrumb');
  nav.append(safeEl('span', null, 'DASHBOARD'), safeEl('span', null, '>'), safeEl('span', null, 'COMMAND SURFACE'));
  return nav;
}

function createMetricRow(label, value) {
  const row = safeEl('div', 'dashboard-uiv3-metric-row');
  row.append(safeEl('span', 'dashboard-uiv3-metric-label', label), safeEl('span', 'dashboard-uiv3-metric-value uiv3-tabnum', value));
  return row;
}

function createMeter(label, value, percent) {
  const item = safeEl('div', 'dashboard-uiv3-meter');
  item.appendChild(createMetricRow(label, value));
  const track = safeEl('span', 'dashboard-uiv3-meter-track');
  const fill = safeEl('span', 'dashboard-uiv3-meter-fill');
  if (Number.isFinite(percent)) fill.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  else fill.classList.add('is-unknown');
  track.appendChild(fill);
  item.appendChild(track);
  return item;
}

function createActionLink(label, href, className = 'uiv3-command-button') {
  const link = safeEl('a', className, label);
  link.setAttribute('href', href);
  return link;
}

function createDisabledAction(label, reason) {
  const button = safeEl('button', 'dashboard-uiv3-ghost-action is-disabled', label);
  button.type = 'button';
  button.disabled = true;
  button.setAttribute('aria-disabled', 'true');
  if (reason) button.setAttribute('title', reason);
  return button;
}

function createHero(model) {
  const header = safeEl('header', 'dashboard-uiv3-hero dashboard-uiv3-hero--compact');
  const copy = safeEl('div', 'dashboard-uiv3-hero-copy');
  copy.append(
    createDashboardBreadcrumb()
  );
  const alert = safeEl('span', `dashboard-uiv3-alert-pill dashboard-uiv3-alert-pill--${model.alertKind}`);
  alert.append(statusDot(model.alertKind === 'warn' ? 'warn' : 'ok'), document.createTextNode(model.alertLabel));
  header.append(copy, alert);
  return header;
}

function createCurrentOperationCard(model) {
  const card = safeEl('article', 'dashboard-uiv3-card dashboard-uiv3-card--primary uiv3-corner-frame');
  card.setAttribute('data-dashboard-zone', 'current-operation');
  const inner = safeEl('div', 'uiv3-corner-frame-inner dashboard-uiv3-card-inner');
  inner.append(
    safeEl('p', 'dashboard-uiv3-eyebrow', `CURRENT OPERATION · ${uppercaseValue(model.operation.label)}`),
    safeEl('h2', 'dashboard-uiv3-card-title', model.operation.title),
    safeEl('p', 'dashboard-uiv3-card-copy', model.operation.description),
  );

  const meta = safeEl('div', 'dashboard-uiv3-card-meta');
  meta.append(
    createMetricRow('Snapshot', model.snapshot),
    createMetricRow('Operation timer', '—'),
    createMetricRow('Source', model.operation.source),
  );
  inner.appendChild(meta);

  const facts = safeEl('dl', 'dashboard-uiv3-fact-row');
  model.facts.forEach(([label, value]) => {
    facts.append(safeEl('dt', 'dashboard-uiv3-fact-label', label), safeEl('dd', 'dashboard-uiv3-fact-value', value));
  });
  inner.appendChild(facts);

  const actions = safeEl('div', 'dashboard-uiv3-actions');
  actions.append(
    createActionLink('EXPAND OPERATION', '#/operations'),
    createDisabledAction('CHANGE OPERATION', 'Change operation is owned by Operations.'),
    createDisabledAction('PAUSE', 'No local operation timer is available.'),
  );
  inner.appendChild(actions);
  card.appendChild(inner);
  return card;
}

function createRouteCard(model) {
  const card = safeEl('article', 'dashboard-uiv3-card');
  card.setAttribute('data-dashboard-zone', 'route-destination');
  card.append(
    safeEl('p', 'dashboard-uiv3-eyebrow', 'ROUTE & DESTINATION'),
    safeEl('h2', 'dashboard-uiv3-card-title', model.route.title),
    safeEl('p', 'dashboard-uiv3-card-copy', model.route.summary),
    createMetricRow('Destination', model.route.destination),
    createActionLink(model.route.action, '#/navigation', 'dashboard-uiv3-card-action'),
  );
  return card;
}

function createActivityCard(model) {
  const card = safeEl('article', 'dashboard-uiv3-card');
  card.setAttribute('data-dashboard-zone', 'recent-activity');
  card.append(safeEl('p', 'dashboard-uiv3-eyebrow', 'RECENT ACTIVITY'), safeEl('h2', 'dashboard-uiv3-card-title', 'Recent Activity'));
  if (model.activityEntries.length === 0) {
    card.appendChild(safeEl('p', 'dashboard-uiv3-empty', 'No recent activity.'));
  } else {
    const list = safeEl('ul', 'dashboard-uiv3-activity-list');
    model.activityEntries.forEach((entry) => {
      const item = safeEl('li', 'dashboard-uiv3-activity-item');
      item.append(
        safeEl('span', 'dashboard-uiv3-activity-time', activityLogTimestamp(entry)),
        safeEl('span', 'dashboard-uiv3-activity-type', activityLogType(entry)),
        safeEl('span', 'dashboard-uiv3-activity-summary', activityLogSummary(entry)),
      );
      list.appendChild(item);
    });
    card.appendChild(list);
  }
  card.appendChild(createActionLink('OPEN LOG', '#/activity-log', 'dashboard-uiv3-card-action'));
  return card;
}

/* Quick Links: honest navigation shortcuts. Not commander-configurable pins —
   real pinning does not exist yet, so this is labelled "Quick Links", not
   "Pinned Tools" (PB-PHASE10-SUPER-03, Commander-reported issue #3). */
function createQuickLinksCard() {
  const card = safeEl('article', 'dashboard-uiv3-card');
  card.setAttribute('data-dashboard-zone', 'quick-links');
  card.append(safeEl('p', 'dashboard-uiv3-eyebrow', 'QUICK LINKS'), safeEl('h2', 'dashboard-uiv3-card-title', 'Quick Links'));
  const list = safeEl('div', 'dashboard-uiv3-tool-list');
  [
    ['Commodity Search', 'Intel-owned market lookup', '#/intel'],
    ['Module Search', 'Intel-owned outfitting lookup', '#/intel'],
    ['Engineering plans', 'Engineering goals and material planning', '#/engineering'],
    ['Sources & Diagnostics', 'Existing source diagnostics surface', '#/sources'],
  ].forEach(([label, summary, href]) => {
    const link = safeEl('a', 'dashboard-uiv3-tool-link');
    link.setAttribute('href', href);
    link.append(safeEl('span', 'dashboard-uiv3-tool-label', label), safeEl('span', 'dashboard-uiv3-tool-summary', summary));
    list.appendChild(link);
  });
  card.appendChild(list);
  return card;
}

/* PB09-08: Phase 9 summary pins — summary/navigation only, no workflow ownership.
   Each pin hides when its source state is Unknown / Not Loaded. */
function createPhase9PinsSection() {
  const pins = [];

  /* Pin 1: active_campaign_pin */
  const campaigns = Array.isArray(_lastPhase9Campaigns?.campaigns)
    ? _lastPhase9Campaigns.campaigns
    : [];
  const activeCampaign = campaigns[0] || null;
  if (activeCampaign && activeCampaign.state === 'active') {
    const pin = safeEl('article', 'dashboard-phase9-pin dashboard-phase9-pin--campaign');
    pin.setAttribute('aria-label', 'Active campaign');
    const wsType = String(activeCampaign.workflow_type || '');
    const chip = safeEl('span', `dashboard-phase9-pin-chip dashboard-phase9-pin-chip--${wsType || 'campaign'}`);
    chip.textContent = wsType || 'campaign';
    const title = safeEl('p', 'dashboard-phase9-pin-title');
    /* Title is commander-entered — truncate to 60 chars, render via textContent */
    const rawTitle = String(activeCampaign.title || '');
    title.textContent = rawTitle.slice(0, 60) + (rawTitle.length > 60 ? '…' : '');
    const statePill = safeEl('span', `dashboard-phase9-pin-state dashboard-phase9-pin-state--${activeCampaign.state}`);
    statePill.textContent = activeCampaign.state;
    const btn = safeEl('button', 'dashboard-phase9-pin-action', 'Open campaign');
    btn.setAttribute('type', 'button');
    btn.addEventListener('click', () => {
      if (typeof window.Shell?.startRouteTransfer !== 'function') {
        window.location.hash = '#/operations';
        return;
      }
      window.Shell.startRouteTransfer({
        originRoute: '/dashboard',
        originPackage: 'Dashboard',
        originSectionId: '',
        targetRoute: '/operations',
        targetSectionId: `operations-phase9-${wsType || 'bgs'}-workspace`,
        targetEntityId: activeCampaign.campaign_id || '',
        targetLabel: 'Operations campaign workspace',
        reason: 'Opening active campaign from Dashboard.',
        returnLabel: 'Return to Dashboard',
        returnTarget: { route: '/dashboard' },
      });
    });
    pin.append(chip, title, statePill, btn);
    pins.push(pin);
  }

  /* PB-PHASE10-SUPER-03 (Commander-reported issue #2): BGS and Powerplay facts
     are no longer surfaced on the default Dashboard. Real commander-configurable
     pinning does not exist yet, so showing them by default overclaimed a
     "pinned facts" capability. These facts remain owned by, and reachable from,
     Intel (Powerplay / BGS sections). Only the commander's own active campaign
     — current "what I am doing" context — remains as a summary pin here. */

  if (pins.length === 0) return null;
  const section = safeEl('section', 'dashboard-phase9-pins');
  section.setAttribute('aria-label', 'Phase 9 campaign summary');
  pins.forEach((p) => section.appendChild(p));
  return section;
}

function renderUiv3DashboardSurface(model) {
  const root = getDashboardRoot();
  if (!root) return;
  const primary = createCurrentOperationCard(model);
  const support = safeEl('section', 'dashboard-uiv3-support-grid');
  support.append(createRouteCard(model), createActivityCard(model), createQuickLinksCard());
  const phase9Pins = createPhase9PinsSection();
  const children = [createDashboardTitle(), createHero(model), primary, support];
  if (phase9Pins) children.push(phase9Pins);
  root.replaceChildren(...children);
}

function renderDashboardWatchRibbon(model) {
  const ribbon = el('uiv3-watch-ribbon');
  if (!ribbon) return;
  const right = safeEl('span', 'uiv3-watch-right');
  appendText(right, 'Data ');
  right.appendChild(safeEl('span', 'uiv3-watch-value', model.watch.dataPosture));
  replaceDashboardOwnedSlot(ribbon, [
    createWatchItem('Watch', model.watch.watchState.label, model.watch.watchState.kind,
      { title: model.watch.watchState.title }),
    createWatchItem('Operation', model.watch.opLabel, model.watch.opKind),
    createWatchItem('Diagnostics', model.watch.diagnostics.value, model.watch.diagnostics.kind,
      { title: model.watch.diagnostics.title, href: model.watch.diagnostics.href }),
    createWatchItem('Alerts', model.watch.alerts.value, model.watch.alerts.kind,
      { title: model.watch.alerts.title, href: model.watch.alerts.href }),
    createWatchItem('Route', model.route.destination, model.route.destination === 'No route plotted' ? 'info' : 'ok'),
    right,
  ]);
}

/* PB-PHASE10-SUPER-08R3: identity-gated ship schematic.

   The schematic card is built by the SHARED persistent-rail renderer
   (window.OmniShipStateRail, ui/components/ship-state-rail.js) so the shell
   (non-Dashboard routes) and the Dashboard render the identical card. The
   Dashboard is no longer a special schematic owner. These thin wrappers
   delegate to the shared renderer and are re-exported for tests. */
function resolveSchematicMode(shipType) {
  if (window.OmniShipStateRail && typeof window.OmniShipStateRail.resolveSchematicMode === 'function') {
    return window.OmniShipStateRail.resolveSchematicMode(shipType);
  }
  return shipType ? 'unavailable' : 'unknown';
}

function renderDashboardLeftRail(model) {
  const rail = el('uiv3-left-rail');
  if (!rail) return;
  const header = safeEl('div', 'uiv3-left-rail-header dashboard-uiv3-rail-header');
  header.append(safeEl('span', 'uiv3-label', 'SHIP STATE'), createActionLink('DETAILS', '#/activity-log', 'uiv3-data-label dashboard-uiv3-rail-link'));

  const shipType = _lastShipState?.ship_type || _lastShipState?.current_ship_type || null;
  const shipLabel = shipType ? displayShipName(shipType).toUpperCase() : 'UNKNOWN';

  /* Shared renderer: identical SHIP STATE schematic card used by the shell.
     The Dashboard passes its source/module/cargo readout as metric rows.
     Guarded: the real app always loads ui/components/ship-state-rail.js before
     dashboard.js; the guard only protects partial test setups that mount the
     surface without the classic helper script. */
  let reticlePanel;
  if (window.OmniShipStateRail && typeof window.OmniShipStateRail.buildShipSchematicCard === 'function') {
    reticlePanel = window.OmniShipStateRail.buildShipSchematicCard(shipType, {
      shipLabel,
      metrics: [
        ['Diagnostics', model.sourceSummary.posture],
        ['Modules', model.vitals.modules],
        ['Cargo', model.vitals.cargo],
      ],
    });
  } else {
    reticlePanel = safeEl('section', 'uiv3-left-rail-panel dashboard-uiv3-rail-panel dashboard-uiv3-schematic-card uiv3-corner-frame');
    reticlePanel.setAttribute('aria-label', 'Ship state schematic');
    reticlePanel.setAttribute('data-schematic-mode', resolveSchematicMode(shipType));
  }

  /* Frame Shift (Jump Range, Fuel Tank) is absorbed into Vitals as compact
     rows. A separate FRAME SHIFT card would oversize the rail and push
     Dashboard into vertical scroll. */
  const vitalsPanel = safeEl('section', 'uiv3-left-rail-panel dashboard-uiv3-rail-panel');
  vitalsPanel.setAttribute('aria-label', 'Ship vitals');
  vitalsPanel.append(
    safeEl('p', 'dashboard-uiv3-eyebrow', 'VITALS'),
    createMeter('Hull', model.vitals.hull, _lastShipState?.hull_health),
    createMetricRow('Shields', model.vitals.shields),
    createMetricRow('Fuel', model.vitals.fuel),
    createMetricRow('Heat', model.vitals.heat),
    createMetricRow('Cargo', model.vitals.cargo),
    createMetricRow('Jump range', model.vitals.jump),
    createMetricRow('Fuel tank', model.vitals.fuelTank),
  );

  const walletPanel = safeEl('section', 'uiv3-left-rail-panel dashboard-uiv3-rail-panel');
  walletPanel.setAttribute('aria-label', 'Wallet');
  walletPanel.append(
    safeEl('p', 'dashboard-uiv3-eyebrow', 'WALLET'),
    createMetricRow('Credits', model.vitals.credits),
    createMetricRow('Rebuy', model.vitals.rebuy),
  );

  replaceDashboardOwnedSlot(rail, [header, reticlePanel, vitalsPanel, walletPanel]);
}

function renderDashboardBottomSpine(model) {
  const spine = el('uiv3-bottom-spine');
  if (!spine) return;
  const anchor = safeEl('span', 'uiv3-spine-anchor');
  const icon = safeEl('span', 'uiv3-icon');
  icon.setAttribute('data-uiv3-icon', 'compass-diamond');
  icon.setAttribute('aria-hidden', 'true');
  anchor.append(
    icon,
    safeEl('span', null, 'Ship'),
    safeEl('span', 'uiv3-spine-value', model.vitals.ship),
    safeEl('span', 'uiv3-spine-value dashboard-uiv3-spine-op', model.watch.opLabel),
  );

  const vitals = safeEl('span', 'uiv3-spine-vitals');
  [
    ['Hull', model.vitals.hull],
    ['Shields', model.vitals.shields],
    ['Fuel', model.vitals.fuel],
    ['Cargo', model.vitals.cargo],
    ['Route', model.route.destination],
  ].forEach(([label, value]) => {
    const item = safeEl('span', 'uiv3-spine-item');
    item.append(safeEl('span', null, label), safeEl('span', 'uiv3-spine-value', value));
    vitals.appendChild(item);
  });
  const note = safeEl('span', 'uiv3-spine-note', `${model.sourceSummary.posture} diagnostics · resumes on next event`);
  replaceDashboardOwnedSlot(spine, [anchor, vitals, note]);
}

function renderEngineeringPin() {
  return null;
}

function renderUiv3DashboardFrame(model) {
  renderDashboardWatchRibbon(model);
  renderDashboardLeftRail(model);
  renderDashboardBottomSpine(model);
}

let _lastShipState = null;
let _lastHeat      = null;
let _lastMods      = null;
let _lastCargo     = null;
let _lastNavSnap   = null;
let _lastCombat    = null;
let _lastIntelSnap = null;
let _lastEconomicSnap = null;
let _lastLocalContextSnap = null;
let _lastSourceSnap = null;
let _lastActivityLog = null;
let _lastEngineeringSnap = null;
/* PB09-08 Phase 9 summary pin data */
let _lastPhase9Campaigns = null;
let _lastPhase9BgsFacts = null;
let _lastPhase9PowerplayFacts = null;
let _manualOperation = readManualOperation();

function mountCommandSurface() {
  if (!isDashboardRouteActive()) {
    resetUiv3DashboardFrame();
    return;
  }

  const input = {
    state: _lastShipState,
    heat:  _lastHeat,
    mods:  _lastMods,
    cargo: _lastCargo,
    navSnap: _lastNavSnap,
    combat: _lastCombat,
    sourceSnap: _lastSourceSnap,
    activityLog: _lastActivityLog,
    engineeringSnap: _lastEngineeringSnap,
    localContext: currentLocalContext(),
    sessionState: window.Shell?.eliteSessionState || null,
  };
  const ctx = deriveCommanderContext(input, _manualOperation);
  const dashboardModel = buildDashboardModel(input, ctx);
  renderUiv3DashboardFrame(dashboardModel);
  renderUiv3DashboardSurface(dashboardModel);
}

/* ─────────────────────────────────────────────
   Data load + event handlers
───────────────────────────────────────────── */

async function refreshShipState(skipSurface = false) {
  const s = await fetchJSON('/pillar1/ship-state');
  if (s) {
    _lastShipState = s;
    window._lastShipState = s;
    renderShipState(s);
    renderHullShields(s, _lastLocalContextSnap || _lastMods);
    renderFuel(s);
    renderPips(s);
    if (!skipSurface) mountCommandSurface();
  }
  return s;
}

async function refreshPips() {
  const p = await fetchJSON('/pillar1/pips');
  if (!p) return false;
  if (p.sys != null) renderPipsGroup('pips-sys', p.sys);
  if (p.eng != null) renderPipsGroup('pips-eng', p.eng);
  if (p.wep != null) renderPipsGroup('pips-wep', p.wep);
  return true;
}

async function loadDashboard() {
  const [ship, cargo, heat, mods, navSnap, combat] = await Promise.all([
    refreshShipState(true),
    fetchJSON('/pillar1/cargo'),
    fetchJSON('/pillar1/heat'),
    fetchJSON('/pillar1/modules/summary'),
    fetchJSON('/navigation/snapshot'),
    fetchJSON('/combat/snapshot'),
  ]);

  _lastCargo   = cargo;
  _lastHeat    = heat;
  _lastMods    = mods;
  _lastNavSnap = navSnap;
  _lastCombat  = combat;

  if (cargo) renderCargo(ship || {}, cargo.inventory);
  if (heat)  renderHeat(heat);
  if (mods)  renderModules(mods);
  renderWallet(null);

  mountCommandSurface();
  renderShipSchematic(ship || {});
  initializeDashboardPanelToggles();

  const [intelSnap, sourceSnap, economicSnap, activityLog, engineeringSnap,
    phase9Campaigns, phase9BgsFacts, phase9PowerplayFacts] = await Promise.all([
    fetchJSON('/intel/snapshot'),
    fetchJSON('/source/health'),
    fetchJSON('/intel/economic/snapshot'),
    fetchJSON('/activity-log'),
    fetchJSON('/engineering/overview'),
    /* PB09-08 Phase 9 summary pin sources — failures are non-fatal; pins hide on null */
    fetchJSON('/operations/phase9/campaigns?state=active&limit=1').catch(() => null),
    fetchJSON('/intel/phase9/bgs-facts').catch(() => null),
    fetchJSON('/intel/phase9/powerplay-facts').catch(() => null),
  ]);
  _lastIntelSnap = intelSnap;
  _lastSourceSnap = sourceSnap;
  _lastEconomicSnap = economicSnap;
  _lastActivityLog = activityLog;
  _lastEngineeringSnap = engineeringSnap;
  _lastPhase9Campaigns = phase9Campaigns;
  _lastPhase9BgsFacts = phase9BgsFacts;
  _lastPhase9PowerplayFacts = phase9PowerplayFacts;
  _lastLocalContextSnap = await fetchJSON('/intel/local-context/snapshot');
  updateEliteSessionState(_lastLocalContextSnap);
  renderWallet(_lastLocalContextSnap?.wallet_snapshot || null);
  renderHullShields(_lastShipState || ship || {}, _lastLocalContextSnap || _lastMods);
  renderShipState(_lastShipState || ship || {});
  mountCommandSurface();
}

/* Correction #16 (repaired): the snapshot endpoint always returns a fresh
   timestamp, so its presence proves local data exists but does NOT prove
   Elite Dangerous is actively producing journal events. shell.js tracks
   real journal arrivals over the WS bus; we just signal that snapshot
   data exists so the state can promote from Waiting to Last known. */
function updateEliteSessionState(localContextSnap) {
  if (!window.Shell) return;
  const loaded = (node) => node && node.freshness !== 'not_loaded';
  const hasSnapshot = Boolean(
    localContextSnap?.generated_at
    || loaded(localContextSnap?.station_context)
    || loaded(localContextSnap?.system_context)
    || loaded(localContextSnap?.market_snapshot)
    || loaded(localContextSnap?.cargo_hold)
    || loaded(localContextSnap?.module_loadout),
  );
  window.Shell.hasLocalSnapshot = window.Shell.hasLocalSnapshot || hasSnapshot;
  const next = typeof window.Shell.deriveEliteSessionState === 'function'
    ? window.Shell.deriveEliteSessionState(localContextSnap)
    : null;
  if (next) window.Shell.setEliteSessionState?.(next);
  else window.Shell.recomputeEliteSessionState?.();
}

let shipRefreshTimer = null;
let heatTtlTimer     = null;

function requestShipStateRefresh(reason) {
  if (shipRefreshTimer) return;
  if (window.OMNICOVAS_DEBUG === true) console.log(`Dashboard: scheduling refresh, reason: ${reason}`);
  shipRefreshTimer = setTimeout(() => {
    refreshShipState();
    shipRefreshTimer = null;
  }, 250);
}

function mountDashboardWithoutBridge() {
  mountCommandSurface();
  renderShipSchematic(_lastShipState || {});
  initializeDashboardPanelToggles();
}

function scheduleDashboardLoad(attempts = 20) {
  if (window.OMNICOVAS_PORT) loadDashboard();
  else if (attempts > 0) setTimeout(() => scheduleDashboardLoad(attempts - 1), 1000);
  else {
    console.warn('Dashboard: Bridge not ready after multiple retries.');
    mountDashboardWithoutBridge();
  }
}

function onStateUpdate(_state) { requestShipStateRefresh('state_update'); }

function onEvent(msg) {
  const { event_type } = msg;
  const type = event_type || msg.event;
  if (String(type || '').toLowerCase().startsWith('engineering.')) {
    fetchJSON('/engineering/overview').then((engineering) => {
      if (engineering) {
        _lastEngineeringSnap = engineering;
        mountCommandSurface();
      }
    });
  }
  switch (type) {
    case 'SHIP_STATE_CHANGED':
    case 'LOADOUT_CHANGED':
      loadDashboard();
      break;
    case 'Status':
    case 'HULL_DAMAGE':
    case 'HullDamage':
    case 'HULL_CRITICAL_25':
    case 'HULL_CRITICAL_10':
    case 'SHIELDS_DOWN':
    case 'ShieldsDown':
    case 'ShieldDown':
    case 'SHIELDS_UP':
    case 'ShieldsUp':
    case 'ShieldUp':
    case 'FUEL_LOW':
    case 'FUEL_CRITICAL':
      requestShipStateRefresh(type);
      break;
    case 'HEAT_WARNING':
    case 'HEAT_DAMAGE':
      fetchJSON('/pillar1/heat').then(h => {
        if (h) { renderHeat(h); _lastHeat = h; mountCommandSurface(); }
      });
      if (heatTtlTimer) clearTimeout(heatTtlTimer);
      heatTtlTimer = setTimeout(() => {
        heatTtlTimer = null;
        fetchJSON('/pillar1/heat').then(h => {
          if (h) { renderHeat(h); _lastHeat = h; mountCommandSurface(); }
        });
      }, 67000);
      break;
    case 'PIPS_CHANGED':
    case 'PipsChanged':
      refreshPips();
      requestShipStateRefresh(type);
      break;
    case 'CARGO_CHANGED':
      fetchJSON('/pillar1/cargo').then(c => {
        if (c) {
          _lastCargo = c;
          renderCargo(_lastShipState || {}, c.inventory);
          fetchJSON('/intel/local-context/snapshot').then((local) => {
            _lastLocalContextSnap = local;
            updateEliteSessionState(local);
            mountCommandSurface();
          });
        }
      });
      break;
    case 'MODULE_DAMAGED':
    case 'MODULE_CRITICAL':
      fetchJSON('/pillar1/modules/summary').then(m => {
        if (m) { _lastMods = m; renderModules(m); mountCommandSurface(); }
      });
      break;
    case 'INTERDICTION_STARTED':
    case 'INTERDICTION_ENDED':
    case 'COMBAT_STATE_CHANGED':
      fetchJSON('/combat/snapshot').then(c => {
        if (c) { _lastCombat = c; mountCommandSurface(); }
      });
      break;
    case 'DESTROYED':
      document.querySelectorAll('.card').forEach(c => c.classList.add('destroyed'));
      ['dash-hull-value', 'dash-shield', 'dash-fuel-value'].forEach(id => {
        const e = el(id); if (e) e.textContent = '—';
      });
      const shipTypeEl = el('dash-ship-type');
      if (shipTypeEl) shipTypeEl.textContent = 'DESTROYED';
      break;
    case 'FSD_JUMP':
    case 'FSDJump':
    case 'DOCKED':
    case 'Docked':
    case 'UNDOCKED':
    case 'Undocked':
      fetchJSON('/intel/local-context/snapshot').then((local) => {
        _lastLocalContextSnap = local;
        updateEliteSessionState(local);
        mountCommandSurface();
      });
      requestShipStateRefresh(type);
      break;
  }
}

/* ─────────────────────────────────────────────
   Init
───────────────────────────────────────────── */
window.OmniEvents?.addEventListener('state', (ev) => onStateUpdate(ev.detail));
window.OmniEvents?.addEventListener('event', (ev) => onEvent(ev.detail));

window.addEventListener('hashchange', () => {
  if (window.location.hash === '#/dashboard' || !window.location.hash) loadDashboard();
  else resetUiv3DashboardFrame();
});

window.OmniEvents?.addEventListener('bridge-connected', loadDashboard);
if (isDashboardRouteActive()) mountDashboardWithoutBridge();
else resetUiv3DashboardFrame();
scheduleDashboardLoad();

/* Test hook: exposes both legacy schematic/detail helpers and the new
 * v2 command surface entry points. Guards against double-assignment. */
if (typeof globalThis.__dashboardExports === 'undefined') {
  globalThis.__dashboardExports = {
    /* Legacy helpers — still used by detail-drawer tests */
    renderShipState,
    renderWallet,
    renderCargo,
    renderShipSchematic,
    renderHeat,
    initializeDashboardPanelToggles,
    setDashboardPanelVisibility,
    showAllDashboardPanels,
    hideAllDashboardPanels,
    ensureDashboardResetControl,
    shieldGeneratorFitted,
    resolveSchematicMode,
    updateEliteSessionState,
    __resetSchematicCache: () => { _lastMountedSchematicKey = undefined; },
    __resetToggleState:    () => { _togglesInitialized = false; },
    /* v2 Command Surface */
    mountCommandSurface,
    __setSurfaceInputs: (inputs) => {
      _lastShipState = inputs?.state ?? _lastShipState;
      _lastHeat      = inputs?.heat  ?? _lastHeat;
      _lastMods      = inputs?.mods  ?? _lastMods;
      _lastCargo     = inputs?.cargo ?? _lastCargo;
      _lastNavSnap   = inputs?.navSnap ?? _lastNavSnap;
      _lastCombat    = inputs?.combat ?? _lastCombat;
      _lastIntelSnap = inputs?.intelSnap ?? _lastIntelSnap;
      _lastEconomicSnap = inputs?.economicSnap ?? _lastEconomicSnap;
      _lastLocalContextSnap = inputs?.localContextSnap ?? _lastLocalContextSnap;
      _lastSourceSnap = inputs?.sourceSnap ?? _lastSourceSnap;
      _lastActivityLog = inputs?.activityLog ?? _lastActivityLog;
      _lastEngineeringSnap = inputs?.engineeringSnap ?? _lastEngineeringSnap;
    },
    __setManualOperation: (op) => { _manualOperation = op; },
    __resetSurface: () => {
      _lastShipState = null; _lastHeat = null; _lastMods = null;
      _lastCargo = null; _lastNavSnap = null; _lastCombat = null;
      _lastIntelSnap = null; _lastEconomicSnap = null; _lastLocalContextSnap = null; _lastSourceSnap = null;
      _lastActivityLog = null; _lastEngineeringSnap = null;
      _lastPhase9Campaigns = null; _lastPhase9BgsFacts = null; _lastPhase9PowerplayFacts = null;
      _manualOperation = null;
    },
    /* PB09-08 Phase 9 pin test hooks */
    createPhase9PinsSection,
    setPhase9Data: ({ campaigns, bgsFacts, powerplayFacts } = {}) => {
      if (campaigns !== undefined) _lastPhase9Campaigns = campaigns;
      if (bgsFacts !== undefined) _lastPhase9BgsFacts = bgsFacts;
      if (powerplayFacts !== undefined) _lastPhase9PowerplayFacts = powerplayFacts;
    },
  };
}
