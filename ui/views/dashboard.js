/**
 * OmniCOVAS Dashboard — Command Surface (compact commander home, iteration 1).
 *
 * Authority: UI/UX Master Blueprint v2, ADRs 0003/0004/0005 and the
 * Commander's Dashboard Design Iteration 1 commission.
 *
 * Commander identity/location, ship watch, cargo and a recorded destination
 * read the shared Shell snapshot. Focused details retain the global Director.
 * Legacy formatter/schematic helpers below support existing component
 * contracts and the shared connection surface, not a hidden old Dashboard.
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
import { formatActivityEventType } from '../utils/display-names.js';
import { describeFreshness } from '../utils/freshness.js';
import { createCommanderHome } from '../components/dashboard-command-deck.js';

let commandHome = null;

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
  /* Loadout is not observed until the commander's first loadout event, so
     these counts are null until then. `null > 0` is false, which would have
     painted the critical row green and the card healthy — colour-coded
     reassurance derived from a source that was never read. Unknown is styled
     as unknown. */
  const known = summary.critical != null && summary.warning != null;
  const critEl = el('dash-mod-critical');
  if (critEl) {
    critEl.className = 'field-value'
      + (!known ? ' unknown' : (summary.critical > 0 ? ' critical' : ' ok'));
  }
  const warnEl = el('dash-mod-warning');
  if (warnEl) {
    warnEl.className = 'field-value'
      + (!known ? ' unknown' : (summary.warning > 0 ? ' warn' : ''));
  }
  if (!known) setCardState('dash-panel-modules', null);
  else if (summary.critical > 0) setCardState('dash-panel-modules', 'critical');
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
      posture: loaded === total ? 'Current' : (loaded > 0 ? 'Partial' : 'Not checked'),
      kind: loaded === total ? 'ok' : (loaded > 0 ? 'warn' : 'info'),
    };
  }

  if (rawLocalContext) {
    const loaded = DASHBOARD_SOURCE_NODES
      .filter((key) => sourceNodeLoaded(rawLocalContext[key]))
      .length;
    return {
      label: `${loaded}/${DASHBOARD_SOURCE_NODES.length} local`,
      posture: loaded > 0 ? 'Last seen' : 'Not checked',
      kind: loaded > 0 ? 'info' : 'warn',
    };
  }

  return { label: 'Local data waiting', posture: 'Not checked', kind: 'warn' };
}

function deriveDashboardOperation(input, ctx) {
  const local = input.localContext || null;
  const station = local?.stationBrief || null;
  const location = ctx?.location || null;
  const route = input.navSnap?.active_route || null;

  const confidenceValues = new Set(['observed', 'suggested', 'manual', 'unknown']);
  const confidence = confidenceValues.has(ctx?.operationConfidence)
    ? ctx.operationConfidence
    : 'unknown';
  const contextualOperation = PRIMARY_OPERATIONS.includes(ctx?.primaryOperation)
    ? ctx.primaryOperation
    : null;
  const confidenceEligible = confidence === 'manual'
    || confidence === 'observed'
    || (confidence === 'suggested' && ctx?.telemetryActive === true);
  const operation = contextualOperation && contextualOperation !== 'idle' && confidenceEligible
    ? contextualOperation
    : null;
  const displayedConfidence = operation ? confidence : 'unknown';
  const source = operation
    ? cleanText(ctx?.operationEvidence, 'local context')
    : 'unknown';

  const label = operation ? operationLabel(operation) : 'None selected';
  const confidenceSuffix = displayedConfidence === 'manual'
    ? ' · SELECTED'
    : displayedConfidence === 'suggested'
      ? ' · SUGGESTED'
      : '';
  const badge = operation ? `OP ${label.toUpperCase()}${confidenceSuffix}` : 'OP UNKNOWN';
  const destination = cleanText(route?.destination, null);
  const stationName = cleanText(station?.stationName || location?.stationName, null);
  const systemName = cleanText(station?.systemName || location?.systemName, null);

  let title = 'What are you doing?';
  let description = 'Choose an activity to focus the command deck.';
  if (operation && displayedConfidence === 'manual') {
    title = `${label} workspace selected.`;
    description = 'Commander-selected workspace. Facts inside it remain limited to available local sources.';
  } else if (operation && displayedConfidence === 'suggested') {
    title = `${label} workspace suggested.`;
    description = `Suggested from ${source}; this is not asserted as an active operation.`;
  } else if (operation === 'station') {
    title = stationName ? `Docked at ${stationName}.` : 'Docked context observed.';
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
    title = 'Combat context observed.';
    description = 'Current-session local combat telemetry is present. Open Operations for the combat workspace.';
  } else if (operation) {
    title = `${label} context observed.`;
    description = 'Current-session local evidence supports this workspace.';
  }

  return {
    operation,
    label,
    badge,
    source,
    confidence: displayedConfidence,
    title,
    description,
  };
}

/* PB10-R4 (Phase 10 reconciliation): the Dashboard is the Live Command Surface,
   so it must answer "where am I?" even when local data is only last-known.

   The prior surface suppressed location entirely whenever the station snapshot
   could not be promoted to current — correct as anti-overclaim, useless as a
   command surface, and inconsistent with Navigation/Intel, which render the same
   fact labelled "last known". This reuses the authoritative
   `deriveCommanderLocationState` result (no parallel derivation) and renders it
   as a self-contained visual unit with an explicit freshness marker, per the
   Runtime UI Repair Doctrine rule against label/value detachment for
   current-system/station facts.

   The anti-overclaim guard is preserved: a station is shown only when the
   authoritative derivation already judged it coherent (no system mismatch, not
   stale, not contradicted by live undocked telemetry), and it is never
   presented as live unless the Elite session is Active. */
function deriveDashboardLocation(ctx, sessionState) {
  const loc = ctx?.location || null;
  const systemName = cleanText(loc?.systemName, null);

  if (!systemName) {
    return {
      systemName: null,
      stationName: null,
      freshnessLabel: 'Not checked',
      freshnessKey: 'not_checked',
      freshnessKind: 'warn',
      note: 'Location not checked this session.',
      isLive: false,
    };
  }

  const isLive = /active/i.test(String(sessionState || '')) && loc?.isStale !== true;
  return {
    systemName,
    /* Already mismatch-guarded and staleness-guarded upstream. */
    stationName: cleanText(loc?.stationName, null),
    dockingValue: cleanText(loc?.flightValue, null),
    freshnessLabel: isLive ? 'In game' : 'Last seen',
    freshnessKey: isLive ? 'live_now' : 'last_seen',
    freshnessKind: isLive ? 'ok' : 'info',
    note: isLive
      ? null
      : 'Last seen in your Journal history.',
    isLive,
  };
}

function createLocationUnit(location) {
  const unit = safeEl('div', 'dashboard-uiv3-location');
  unit.setAttribute('data-dashboard-zone', 'current-location');
  unit.setAttribute('data-location-freshness', location.freshnessKey || 'unknown');

  const head = safeEl('div', 'dashboard-uiv3-location-head');
  head.append(safeEl('span', 'dashboard-uiv3-location-label', location.isLive ? 'CURRENT LOCATION' : 'LAST KNOWN LOCATION'));
  const pill = safeEl(
    'span',
    `dashboard-uiv3-location-pill dashboard-uiv3-location-pill--${location.freshnessKind}`,
    location.freshnessLabel,
  );
  head.appendChild(pill);
  unit.appendChild(head);

  if (location.systemName) {
    unit.appendChild(safeEl('p', 'dashboard-uiv3-location-system', location.systemName));
    if (location.stationName) {
      unit.appendChild(
        safeEl('p', 'dashboard-uiv3-location-station', `Station · ${location.stationName}`),
      );
    }
    if (location.dockingValue) {
      unit.appendChild(
        safeEl('p', 'dashboard-uiv3-location-docking', location.dockingValue),
      );
    }
  }

  if (location.note) {
    unit.appendChild(safeEl('p', 'dashboard-uiv3-location-note', location.note));
  }

  return unit;
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
  /* An unobserved capacity is not a denominator. Rendering "9 t/Unknown"
     dressed a missing fact as part of a ratio; the tonnage carried stands on
     its own until a Loadout supplies the hold size. */
  if (localCargo?.usedLabel && localCargo?.capacity != null) {
    return `${localCargo.usedLabel}/${localCargo.capacityLabel}`;
  }
  if (localCargo?.usedLabel && localCargo?.hasCargo) {
    return localCargo.usedLabel;
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
  /* R0-3: prefer the served answer. The local-context derivation below is
     correct but depends on a snapshot that is not always loaded, and when it
     was absent this fell through to "DOWN" for a ship with no generator. */
  if (state.shield_generator_fitted === false) return 'None fitted';
  const fitted = state.shield_generator_fitted === true
    ? true
    : shieldGeneratorFitted(input.localContext?.rawLoaded ? _lastLocalContextSnap : (_lastLocalContextSnap || input.mods));
  if (fitted === false) return 'None fitted';
  if (state.shield_up === true) return 'UP';
  if (state.shield_up === false) return 'DOWN';
  return '—';
}

function fuelSummary(state) {
  /* Capacity comes from Loadout and is unknown until one is observed, so a
     percentage cannot always be computed. Reporting nothing in that window
     hid tonnage the app already had. Show what is known; never invent a
     denominator. */
  const pct = state?.fuel_pct;
  const main = state?.fuel_main;
  const tons = Number.isFinite(main) ? `${Math.round(main * 10) / 10} t` : null;
  if (pct != null) return tons ? `${tons} (${Math.round(pct)}%)` : `${Math.round(pct)}%`;
  return tons || '—';
}

function heatSummary(heat) {
  return heat?.level_pct != null ? `${Math.round(heat.level_pct)}%` : '—';
}

function walletField(field, fallback = '—') {
  const wallet = _lastLocalContextSnap?.wallet_snapshot || null;
  const entry = wallet?.[field] ?? null;
  /* Wallet fields are provenance objects ({value, source, freshness, ...});
     format the source-backed value, never the envelope object. */
  const value = entry && typeof entry === 'object' ? (entry.value ?? null) : entry;
  return value == null ? fallback : fmt.credits(value);
}

/* FU-014 observed session change: arithmetic over source-backed balance
   observations only — explicitly not a transaction record. */
function walletSessionChange(fallback = '—') {
  const change = _lastLocalContextSnap?.wallet_snapshot?.observed_session_change;
  if (!change || typeof change !== 'object' || change.value == null) return fallback;
  const sign = change.value > 0 ? '+' : change.value < 0 ? '−' : '±';
  return `${sign}${fmt.credits(Math.abs(change.value))}`;
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
  return formatActivityEventType(activityLogText(entry?.event_type || entry?.event, 'Event'));
}

function activityLogSummary(entry) {
  return activityLogText(entry?.summary || entry?.message, 'Event recorded');
}

function activityLogTimestamp(entry) {
  return activityLogText(entry?.timestamp || entry?.created_at, 'Time not recorded');
}

function latestLocalObservationTimestamp(rawLocalContext) {
  if (!rawLocalContext || typeof rawLocalContext !== 'object') return null;
  const candidates = [
    rawLocalContext.session_activity?.last_game_activity_at,
    rawLocalContext.session_activity?.event_timestamp,
    rawLocalContext.station_context?.event_timestamp,
    rawLocalContext.system_context?.event_timestamp,
    rawLocalContext.market_snapshot?.event_timestamp,
    rawLocalContext.outfitting_snapshot?.event_timestamp,
    rawLocalContext.shipyard_snapshot?.event_timestamp,
    rawLocalContext.cargo_hold?.event_timestamp,
    rawLocalContext.module_loadout?.event_timestamp,
  ].filter(Boolean);
  return candidates.reduce((latest, candidate) => {
    const time = Date.parse(candidate);
    if (!Number.isFinite(time)) return latest;
    return !latest || time > latest.time ? { value: candidate, time } : latest;
  }, null)?.value || null;
}

function buildDashboardModel(input, ctx) {
  const sourceSummary = sourceFreshnessSummary(_lastLocalContextSnap, input.sourceSnap);
  const operation = deriveDashboardOperation(input, ctx);
  const route = routeSummary(input.navSnap);
  const entries = activityEntries(input.activityLog).slice(0, 3);
  const station = input.localContext?.stationBrief || null;
  const interrupts = Array.isArray(ctx?.interrupts) ? ctx.interrupts : [];
  const telemetryActive = ctx?.telemetryActive === true;
  const attention = ctx?.interrupts
    ? (telemetryActive ? interrupts.length : null)
    : null;
  const sessionState = cleanText(input.sessionState || window.Shell?.eliteSessionState, 'Waiting');
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
    ? { label: 'Not checked', kind: 'info',
        title: 'Ship watch has not been checked from current game data.' }
    : attention > 0
      ? { label: primaryReason || 'Action needed', kind: 'warn', title: alertCountTitle(attention) }
      : { label: hasSourceData ? 'Nominal' : 'Not checked',
          kind: hasSourceData ? 'ok' : 'info',
          title: hasSourceData
            ? 'All monitored vitals nominal.'
            : 'Ship watch has not been checked from current game data.' };

  /* A ship always has modules, so a count of 0 is never a no-data state — it
     is a claim that the hull is stripped. The loadout view model reports
     `moduleCount: modules.length`, which is 0 for an unobserved Loadout
     (backend `modules: null` -> empty list), while carrying the honest
     `loadoutAvailable` flag alongside it. Read the flag, not the length.
     The /pillar1/modules/summary fallback now reports null rather than 0 for
     the same window, so both sources agree on unknown. */
  const moduleCountValue = (input) => {
    const search = input.localContext?.moduleSearch;
    if (search?.loadoutAvailable === true && search.moduleCount != null) {
      return String(search.moduleCount);
    }
    return _lastMods?.total != null ? String(_lastMods.total) : '—';
  };

  const diagnosticsNotLoaded = /not\s*(?:loaded|checked)/i.test(sourceSummary.posture);
  const diagnostics = {
    value: diagnosticsNotLoaded ? 'Not checked' : sourceSummary.label,
    kind: sourceSummary.kind,
    title: diagnosticsNotLoaded
      ? 'Game-data checks are still starting. Open connection details.'
      : `Source diagnostics: ${sourceSummary.label} (${sourceSummary.posture}). Open Sources & Diagnostics.`,
    href: '#/sources',
  };

  const alerts = {
    value: attention === null ? 'Not checked' : attention === 0 ? 'None' : `${attention} active`,
    kind: attention && attention > 0 ? 'warn' : (attention === null ? 'info' : 'ok'),
    title: attention === null
      ? 'Alerts have not been checked from current game data.'
      : attention === 0
        ? 'No active alerts.'
        : alertCountTitle(attention),
    href: attention && attention > 0 ? '#/activity-log' : null,
  };

  const dataFreshness = describeFreshness(
    /active/i.test(sessionState) ? 'live_now' : (/last/i.test(sessionState) ? 'remembered' : 'not_loaded'),
  );
  const dataPosture = `LOCAL · ${dataFreshness.label.toUpperCase()}`;

  return {
    operation,
    sourceSummary,
    route,
    familiarity: _lastMemoryFamiliarity,
    activityEntries: entries,
    alertLabel: attention === null
      ? 'ALERTS NOT CHECKED'
      : attention === 0
        ? '0 ALERTS · NOTHING URGENT'
        : `${attention} ALERT${attention === 1 ? '' : 'S'} · ${(primaryReason || 'ATTENTION').toUpperCase()}`,
    alertKind: attention && attention > 0 ? 'warn' : (attention === null ? 'info' : 'ok'),
    watch: {
      watchState,
      opLabel: operation.operation ? `ACTIVITY ${operation.label.toUpperCase()}` : 'NO ACTIVITY SELECTED',
      opKind: operation.operation ? 'ok' : 'warn',
      diagnostics,
      alerts,
      dataPosture,
    },
    location: deriveDashboardLocation(ctx, sessionState),
    facts: [
      ['Type', operation.operation === 'station' ? cleanKnown(station?.stationType, 'Unknown') : 'Unknown'],
      ['Distance from Star', operation.operation === 'station' ? detailRowValue(station?.detailRows, 'Distance from star') : '—'],
      ['Economy', operation.operation === 'station' ? cleanKnown(station?.economySummary, 'Unknown') : 'Unknown'],
      ['Docking', cleanText(ctx?.location?.flightValue || station?.dockedLabel, 'Unknown')],
    ],
    snapshot: cleanText(latestLocalObservationTimestamp(_lastLocalContextSnap), '—'),
    vitals: {
      hull: hullSummary(input.state),
      shields: shieldsSummary(input),
      fuel: fuelSummary(input.state),
      heat: heatSummary(input.heat),
      cargo: cargoSummary(input),
      modules: moduleCountValue(input),
      credits: walletField('credits'),
      rebuy: walletField('rebuy'),
      sessionChange: walletSessionChange(),
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

function createActionLink(label, href, className = 'uiv3-command-button cmd-btn cmd-btn--quiet') {
  const link = safeEl('a', className, label);
  link.setAttribute('href', href);
  return link;
}

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

function renderUiv3DashboardSurface() {
  const root = getDashboardRoot();
  if (!root) return;
  document.body.classList.add('dashboard-home-active');
  if (!commandHome || commandHome.root.parentNode !== root) {
    commandHome?.dispose();
    commandHome = createCommanderHome({ getSnapshot: () => ({
      ...window.Shell?.getWidgetSnapshot?.(),
      navSnap: window.Shell?.uiv3FrameState?.navSnap || null,
    }) });
    root.replaceChildren(commandHome.root);
  } else commandHome.update();
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
  header.append(safeEl('span', 'uiv3-label', 'SHIP STATE'), createActionLink('Details', '#/activity-log', 'uiv3-data-label dashboard-uiv3-rail-link cmd-btn cmd-btn--quiet'));

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
  const sessionChangeRow = createMetricRow('Session Δ', model.vitals.sessionChange);
  sessionChangeRow.title =
    'Observed balance change across source-backed balance observations '
    + 'this app session. Not a transaction record.';
  walletPanel.append(
    safeEl('p', 'dashboard-uiv3-eyebrow', 'WALLET'),
    createMetricRow('Credits', model.vitals.credits),
    createMetricRow('Rebuy', model.vitals.rebuy),
    sessionChangeRow,
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
  const note = safeEl('span', 'uiv3-spine-note', model.sourceSummary.posture === 'Not checked'
    ? 'Waiting for new game data'
    : 'Last seen game data');
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
let _lastMemoryFamiliarity = null;
/* PB09-08 Phase 9 summary pin data */
let _lastPhase9Campaigns = null;
let _lastPhase9BgsFacts = null;
let _lastPhase9PowerplayFacts = null;
let _manualOperation = null;

function mountCommandSurface() {
  if (!isDashboardRouteActive()) {
    commandHome?.dispose(); commandHome = null;
    document.body.classList.remove('dashboard-home-active');
    resetUiv3DashboardFrame();
    return;
  }

  // The shell owns all reads, identity invalidation and observation timestamps.
  const snapshot = window.Shell?.getWidgetSnapshot?.();
  if (snapshot) {
    _lastShipState = snapshot.shipState;
    _lastLocalContextSnap = snapshot.localContextRaw;
    _lastNavSnap = window.Shell?.uiv3FrameState?.navSnap || null;
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
  renderUiv3DashboardSurface();
}

/* ─────────────────────────────────────────────
   Data load + event handlers
───────────────────────────────────────────── */

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


window.OmniEvents?.addEventListener('route-changed', () => {
  mountCommandSurface();
});
window.OmniEvents?.addEventListener('widget-snapshot', () => {
  if (isDashboardRouteActive()) mountCommandSurface();
});
window.OmniEvents?.addEventListener('elite-session-state', () => commandHome?.update());
window.OmniEvents?.addEventListener('bridge-disconnected', () => commandHome?.update());

mountCommandSurface();

/* Test hook: exposes both legacy schematic/detail helpers and the new
 * v2 command surface entry points. Guards against double-assignment. */
if (typeof globalThis.__dashboardExports === 'undefined') {
  globalThis.__dashboardExports = {
    /* Legacy helpers — still used by detail-drawer tests */
    renderShipState,
    renderWallet,
    renderCargo,
    /* B10: exposed so the unobserved-loadout styling is protected by tests
       rather than only by inspection. */
    renderModules,
    renderShipSchematic,
    renderHeat,
    initializeDashboardPanelToggles,
    setDashboardPanelVisibility,
    showAllDashboardPanels,
    hideAllDashboardPanels,
    ensureDashboardResetControl,
    shieldGeneratorFitted,
    /* LNA-027: exposed so the partial-capacity vitals behaviour is protected
       by tests rather than only by inspection. */
    fuelSummary,
    cargoSummary,
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
      _lastMemoryFamiliarity = inputs?.memoryFamiliarity ?? _lastMemoryFamiliarity;
    },
    __setManualOperation: (op) => { _manualOperation = op; },
    __resetSurface: () => {
      commandHome?.dispose(); commandHome = null;
      document.body.classList.remove('dashboard-home-active');
      _lastShipState = null; _lastHeat = null; _lastMods = null;
      _lastCargo = null; _lastNavSnap = null; _lastCombat = null;
      _lastIntelSnap = null; _lastEconomicSnap = null; _lastLocalContextSnap = null; _lastSourceSnap = null;
      _lastActivityLog = null; _lastEngineeringSnap = null;
      _lastMemoryFamiliarity = null;
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
