/**
 * OmniCOVAS Shell — navigation, routing, connection management.
 *
 * Responsibilities:
 *  - UI v3 route activation via hash (#/intel mounts the Intel workspace)
 *  - Autoconnect to Python FastAPI bridge when Tauri emits "bridge-ready"
 *  - Fallback command lookup via get_bridge_info if UI missed the event
 *  - WebSocket connection to /ws/events with exponential-backoff reconnect
 *  - HTTP /state polling fallback every 2 seconds while disconnected
 *  - Publishes events to a global bus (window.OmniEvents) for views to consume
 *  - Connection status dot in topbar
 */

'use strict';

/* ── Event bus ── */
window.OmniEvents = window.OmniEvents || new EventTarget();

function emit(type, detail) {
  window.OmniEvents.dispatchEvent(new CustomEvent(type, { detail }));
}

/* ── State ── */
const Shell = {
  port: null,
  httpBase: null,
  wsBase: null,
  ws: null,
  wsReconnectDelay: 1000,
  wsReconnectTimer: null,
  pollTimer: null,
  connected: false,
  booting: false,
};
Shell.uiv3FrameState = {
  publicState: null,
  shipState: null,
  localContextRaw: null,
  localContext: null,
  navSnap: null,
  sourceSnap: null,
  location: null,
};

let uiv3FrameViewModelsPromise = null;
let uiv3FrameRefreshPromise = null;

/* ── Small helpers ── */
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function normalizeBridge(payload) {
  if (!payload) return null;

  const port = Number(payload.port);

  if (!Number.isInteger(port) || port <= 0) {
    return null;
  }

  return {
    port,
    httpBase: payload.httpBase || `http://127.0.0.1:${port}`,
    wsBase: payload.wsBase || `ws://127.0.0.1:${port}`,
  };
}

const UIV3_STATUS_KINDS = new Set(['ok', 'warn', 'alert', 'info']);

function setUiv3StatusDot(dot, kind, label, options = {}) {
  if (!dot) return;

  const safeKind = UIV3_STATUS_KINDS.has(kind) ? kind : 'info';
  dot.className = `status-dot uiv3-dot uiv3-dot--${safeKind}`;
  if (options.connected) {
    dot.classList.add('connected');
  }
  dot.setAttribute('aria-label', label || `${safeKind} status`);
}

function setUiv3StatusValueState(el, kind) {
  if (!el) return;

  UIV3_STATUS_KINDS.forEach((statusKind) => {
    el.classList.remove(`uiv3-status-value--${statusKind}`);
  });

  const safeKind = UIV3_STATUS_KINDS.has(kind) ? kind : 'info';
  el.classList.add(`uiv3-status-value--${safeKind}`);
}

function sessionStatusKind(state) {
  switch (normalizeEliteSessionState(state)) {
    case 'Active':
      return 'ok';
    case 'Last known':
      return 'info';
    case 'Unknown':
      return 'alert';
    case 'Waiting':
    default:
      return 'warn';
  }
}

function updateUiv3Clock() {
  const target = document.getElementById('uiv3-clock');
  if (!target) return;

  const now = new Date();
  const hours = String(now.getUTCHours()).padStart(2, '0');
  const minutes = String(now.getUTCMinutes()).padStart(2, '0');
  target.textContent = `${hours}:${minutes} UTC`;
}

function uiv3TabRouteFor(routeName) {
  const route = normalizeRouteName(routeName) || '/dashboard';
  if (route === '/activity-log') return route;
  if (route === '/squadrons') return route;
  if (route === '/systems' || route.startsWith('/systems/')) return '/systems';
  if (route === '/dashboard'
    || route === '/operations'
    || route === '/intel'
    || route === '/navigation'
    || route === '/engineering') {
    return route;
  }
  return '';
}

function updateUiv3ActiveTab(routeName) {
  const activeRoute = uiv3TabRouteFor(routeName);
  document.querySelectorAll('[data-uiv3-route]').forEach((tab) => {
    const isActive = Boolean(activeRoute) && tab.getAttribute('data-uiv3-route') === activeRoute;
    tab.classList.toggle('is-active', isActive);
    if (isActive) {
      tab.setAttribute('aria-current', 'page');
    } else {
      tab.removeAttribute('aria-current');
    }
  });
}

function isDisabledSystemsTab(target) {
  return Boolean(target?.closest?.('[data-uiv3-route="/systems"][aria-disabled="true"]'));
}

function guardDisabledSystemsTab(event) {
  if (!isDisabledSystemsTab(event.target)) return;
  event.preventDefault();
  event.stopPropagation();
}

document.addEventListener('click', guardDisabledSystemsTab, true);

/* ── Connection status UI ──
   Correction #16: Backend (WS to Python core) and Elite session (live
   journal events) are separate concepts. Port label is no longer shown
   here — it lives on Sources & Diagnostics surface. */
function setConnected(yes, _portNum) {
  Shell.connected = yes;

  const dot = document.getElementById('status-dot');
  const text = document.getElementById('status-text');

  if (!dot || !text) return;

  if (yes) {
    setUiv3StatusDot(dot, 'ok', 'Backend connected', { connected: true });
    setUiv3StatusValueState(text, 'ok');
    text.textContent = 'Connected';
  } else {
    setUiv3StatusDot(dot, 'warn', 'Backend disconnected');
    setUiv3StatusValueState(text, 'warn');
    text.textContent = 'Disconnected';
  }
}

function setCoreNotFound() {
  const text = document.getElementById('status-text');
  const dot = document.getElementById('status-dot');

  if (dot) {
    setUiv3StatusDot(dot, 'alert', 'Backend not found');
  }

  if (text) {
    setUiv3StatusValueState(text, 'alert');
    text.textContent = 'Core not found';
  }
}

/* ── Elite-session state (Active / Waiting / Last known / Unknown) ──
   The /intel/local-context/snapshot endpoint returns a fresh
   generated_at on every call even when Elite Dangerous is not running,
   so it cannot be used as an Active signal. The repaired local-context
   endpoint owns the session state; WebSocket journal activity is only a
   back-compat fallback when that endpoint is not loaded yet. */
const ELITE_SESSION_STATES = new Set(['Active', 'Waiting', 'Last known', 'Unknown']);
Shell.eliteSessionState = 'Waiting';
Shell.lastJournalEventAt = 0;
Shell.hasLocalSnapshot = false;
Shell.sessionActivityState = null;

/* Journal-derived event types that genuinely indicate Elite is producing
   live journal output. State pushes that the backend can synthesize from
   stale local files are NOT included. */
const JOURNAL_EVENT_TYPES = new Set([
  'FSD_JUMP', 'FSDJump',
  'DOCKED', 'Docked',
  'UNDOCKED', 'Undocked',
  'LOCATION', 'Location',
  'LIFTOFF', 'Liftoff',
  'TOUCHDOWN', 'Touchdown',
  'CARGO_CHANGED',
  'MARKET',
  'LOADOUT_CHANGED', 'Loadout',
  'INTERDICTION_STARTED', 'INTERDICTION_ENDED',
  'COMBAT_STATE_CHANGED', 'COMBAT_SESSION_STATE_CHANGED',
  'SUPERCRUISE_ENTRY', 'SUPERCRUISE_EXIT',
  'JET_CONE_BOOST', 'HEAT_DAMAGE', 'SHIELDS_DOWN', 'SHIELDS_UP',
  'HULL_DAMAGE',
  'HEAT_WARNING',
]);

function markJournalActivity() {
  Shell.lastJournalEventAt = Date.now();
  recomputeEliteSessionState();
}

function recomputeEliteSessionState() {
  if (Shell.sessionActivityState) {
    if (Shell.sessionActivityState !== Shell.eliteSessionState) {
      setEliteSessionState(Shell.sessionActivityState);
    }
    return;
  }
  let next;
  const ageMs = Date.now() - (Shell.lastJournalEventAt || 0);
  if (Shell.lastJournalEventAt && ageMs < 60_000) {
    next = 'Active';
  } else if (Shell.hasLocalSnapshot || Shell.lastJournalEventAt) {
    next = 'Last known';
  } else {
    next = 'Waiting';
  }
  if (next !== Shell.eliteSessionState) {
    setEliteSessionState(next);
  }
}

function setEliteSessionState(state) {
  const next = normalizeEliteSessionState(state) || 'Waiting';
  Shell.eliteSessionState = next;
  const target = document.getElementById('elite-session-text');
  const dot = document.getElementById('elite-session-dot');
  const kind = sessionStatusKind(next);
  if (target) {
    setUiv3StatusValueState(target, kind);
    target.textContent = next;
  }
  setUiv3StatusDot(dot, kind, `Elite session ${next.toLowerCase()}`);
  emit('elite-session-state', { state: next });
}

function normalizeEliteSessionState(value) {
  const raw = String(value || '').trim().toLowerCase().replace(/[-\s]+/g, '_');
  switch (raw) {
    case 'active': return 'Active';
    case 'last_known': return 'Last known';
    case 'waiting': return 'Waiting';
    case 'unknown': return 'Unknown';
    default: return null;
  }
}

function backendSessionState(snapshotOrInput) {
  if (!snapshotOrInput || typeof snapshotOrInput !== 'object') return null;
  const activity = snapshotOrInput.session_activity || snapshotOrInput.sessionActivity || null;
  const fromActivity = normalizeEliteSessionState(
    activity?.state ?? activity?.elite_session_state ?? activity?.eliteSessionState,
  );
  return fromActivity || normalizeEliteSessionState(
    snapshotOrInput.elite_session_state ?? snapshotOrInput.eliteSessionState,
  );
}

function deriveEliteSessionState(snapshotOrInput) {
  /* Prefer backend session_activity. Back-compat fallback only uses
     generated_at to prove that local data exists; it never proves Active. */
  if (snapshotOrInput == null) {
    return Shell.hasLocalSnapshot ? 'Last known' : 'Waiting';
  }
  const fromBackend = backendSessionState(snapshotOrInput);
  if (fromBackend) {
    Shell.sessionActivityState = fromBackend;
    Shell.hasLocalSnapshot = Shell.hasLocalSnapshot || fromBackend === 'Last known'
      || fromBackend === 'Active'
      || Boolean(snapshotOrInput.generated_at);
    return fromBackend;
  }
  const generatedAt = typeof snapshotOrInput === 'string'
    ? Date.parse(snapshotOrInput)
    : Date.parse(snapshotOrInput?.generated_at);
  if (!Number.isFinite(generatedAt)) return Shell.hasLocalSnapshot ? 'Last known' : 'Waiting';
  /* Snapshot has data — at least Last known is correct now. */
  Shell.hasLocalSnapshot = true;
  const journalAge = Date.now() - (Shell.lastJournalEventAt || 0);
  if (Shell.lastJournalEventAt && journalAge < 60_000) return 'Active';
  return 'Last known';
}

/* ── Persistent UI v3 frame projection ──
   The shell owns the frame outside Dashboard. Dashboard may replace these
   slots with its richer cockpit rendering while active, then hands ownership
   back here on route leave. All values below come from existing local
   backplane endpoints; absent fields remain absent or explicitly unknown. */
function uiv3FrameEl(tagName, className = '', text = null) {
  const node = document.createElement(tagName);
  if (className) node.className = className;
  if (text !== null && text !== undefined) node.textContent = String(text);
  return node;
}

function uiv3FrameText(value, fallback = 'Unknown') {
  if (value === null || value === undefined || value === '') return fallback;
  const text = String(value).trim();
  return text || fallback;
}

function uiv3FrameFirstText(values, fallback = 'Unknown') {
  for (const value of values) {
    const text = uiv3FrameText(value, '');
    if (text) return text;
  }
  return fallback;
}

function uiv3FramePct(value) {
  return Number.isFinite(value) ? `${Math.round(value)}%` : null;
}

function uiv3FrameCargo(shipState) {
  if (!Number.isFinite(shipState?.cargo_count) || !Number.isFinite(shipState?.cargo_capacity)) {
    return null;
  }
  return `${shipState.cargo_count}/${shipState.cargo_capacity} t`;
}

function uiv3FrameSourceLoaded(node) {
  return Boolean(node && typeof node === 'object' && node.freshness !== 'not_loaded' && !node.fallback);
}

function uiv3FrameLocalSourceSummary(rawLocalContext) {
  const nodes = [
    'station_context',
    'system_context',
    'station_services',
    'market_snapshot',
    'cargo_hold',
    'module_loadout',
  ];
  const loaded = nodes.filter((key) => uiv3FrameSourceLoaded(rawLocalContext?.[key])).length;
  return loaded > 0
    ? { label: `${loaded}/${nodes.length} local`, topbar: 'Local data loaded', kind: 'ok' }
    : { label: 'Local data waiting', topbar: 'Local data waiting', kind: 'warn' };
}

function uiv3FrameShipLabel(shipState, publicState) {
  return uiv3FrameFirstText([
    shipState?.ship_name,
    shipState?.ship_type,
    publicState?.current_ship_name,
    publicState?.current_ship_type,
  ]);
}

function uiv3FrameCommanderLabel(publicState) {
  return uiv3FrameText(
    publicState?.commander_name || publicState?.commander || publicState?.cmdr,
    'Unknown',
  );
}

function uiv3FrameRouteLabel(navSnap) {
  return uiv3FrameText(navSnap?.active_route?.destination, 'No route plotted');
}

function uiv3FrameLocationFallback(shipState, navSnap) {
  const haveLocation = Boolean(shipState?.current_system || shipState?.current_station || navSnap?.current_system);
  return {
    systemName: shipState?.current_system || navSnap?.current_system || null,
    stationName: shipState?.current_station || navSnap?.current_station || null,
    flightLabel: shipState?.is_docked === true ? 'Docking state' : 'Flight state',
    flightValue: shipState?.is_docked === true
      ? (Shell.eliteSessionState === 'Active' ? 'Docked' : 'Last known docked')
      : (shipState?.is_docked === false && Shell.eliteSessionState === 'Active' ? 'In space' : (haveLocation ? 'Last known' : 'Unknown')),
    dockingState: shipState?.is_docked === true ? 'last_known_docked' : (haveLocation ? 'unknown' : 'unknown'),
    isStale: Shell.eliteSessionState !== 'Active',
  };
}

function uiv3FrameChip(location) {
  switch (location?.dockingState) {
    case 'docked':
      return { label: 'Live docked', kind: 'ok' };
    case 'in_space':
      return { label: 'Live in space', kind: 'ok' };
    case 'partial':
      return { label: 'Partial local', kind: 'warn' };
    case 'last_known_docked':
      return { label: 'Last-known docked', kind: 'info' };
    default:
      return { label: location?.isStale ? 'Last-known' : 'Unknown', kind: 'info' };
  }
}

function uiv3FrameMetric(label, value) {
  if (value === null || value === undefined || value === '') return null;
  const row = uiv3FrameEl('div', 'uiv3-frame-metric-row');
  row.append(
    uiv3FrameEl('span', 'uiv3-frame-metric-label', label),
    uiv3FrameEl('span', 'uiv3-frame-metric-value', value),
  );
  return row;
}

function uiv3FrameWatchItem(label, value, kind = 'info') {
  const item = uiv3FrameEl('span', 'uiv3-watch-item');
  const dot = uiv3FrameEl('span', `uiv3-dot uiv3-dot--${kind}`);
  dot.setAttribute('aria-hidden', 'true');
  item.append(dot, document.createTextNode(label), uiv3FrameEl('span', 'uiv3-watch-value', value));
  return item;
}

function uiv3FrameSpineItem(label, value) {
  const item = uiv3FrameEl('span', 'uiv3-spine-item');
  item.append(uiv3FrameEl('span', null, label), uiv3FrameEl('span', 'uiv3-spine-value', value));
  return item;
}

function replaceShellOwnedSlot(node, children) {
  if (!node) return;
  node.setAttribute('data-uiv3-owner', 'shell');
  node.replaceChildren(...children);
}

function renderUiv3IdentityFrame(frame, location, sourceSummary) {
  const commander = document.getElementById('uiv3-commander-value');
  const ship = document.querySelector('[data-uiv3-identity-slot="ship"]');
  const system = document.getElementById('uiv3-system-value');
  const station = document.getElementById('uiv3-station-value');
  const chip = document.querySelector('.uiv3-last-known-chip');
  const badge = document.getElementById('uiv3-context-badge');
  const sourceDot = document.getElementById('sources-status-dot');
  const sourceText = document.getElementById('sources-status-text');
  const chipModel = uiv3FrameChip(location);

  if (commander) commander.textContent = uiv3FrameCommanderLabel(frame.publicState);
  if (ship) ship.textContent = `Ship: ${uiv3FrameShipLabel(frame.shipState, frame.publicState)}`;
  if (system) system.textContent = uiv3FrameText(location.systemName);
  if (station) {
    station.textContent = location.dockingState === 'in_space'
      ? 'In space'
      : uiv3FrameText(location.stationName, 'Not Loaded');
  }
  if (chip) {
    chip.replaceChildren();
    const dot = uiv3FrameEl('span', `uiv3-dot uiv3-dot--${chipModel.kind}`);
    dot.setAttribute('aria-hidden', 'true');
    chip.append(dot, document.createTextNode(chipModel.label));
  }
  if (badge) {
    const dot = uiv3FrameEl('span', `uiv3-dot uiv3-dot--${chipModel.kind}`);
    dot.setAttribute('aria-hidden', 'true');
    badge.replaceChildren(dot, document.createTextNode(location.flightValue === 'Unknown' ? 'Location unknown' : location.flightValue));
  }
  if (sourceDot) setUiv3StatusDot(sourceDot, sourceSummary.kind, sourceSummary.topbar);
  if (sourceText) {
    setUiv3StatusValueState(sourceText, sourceSummary.kind);
    sourceText.textContent = sourceSummary.topbar;
  }
}

function renderUiv3ShellSlots(frame, location, sourceSummary) {
  const ribbon = document.getElementById('uiv3-watch-ribbon');
  const rail = document.getElementById('uiv3-left-rail');
  const spine = document.getElementById('uiv3-bottom-spine');
  const shipLabel = uiv3FrameShipLabel(frame.shipState, frame.publicState);
  const routeLabel = uiv3FrameRouteLabel(frame.navSnap);
  const sessionKind = sessionStatusKind(Shell.eliteSessionState);

  /* SCHEMATIC-RACE-01: the empty/default hash IS the Dashboard home route.
     Resolve it to '/dashboard' so the shell defers to (never clobbers) the
     dashboard-owned left rail and its Sidewinder schematic on cold load —
     before the location hash has been written. Previously, when the shell's
     async snapshot refresh resolved after the Dashboard rendered, the empty
     hash failed this guard and the shell overwrote the rail with its
     placeholder, dropping the schematic until a route remount re-ran the
     Dashboard renderer last. */
  const activeRoute = normalizeRouteName(window.location.hash) || '/dashboard';
  if (activeRoute === '/dashboard'
      && (ribbon?.getAttribute('data-uiv3-owner') === 'dashboard'
        || rail?.getAttribute('data-uiv3-owner') === 'dashboard'
        || spine?.getAttribute('data-uiv3-owner') === 'dashboard')) {
    return;
  }

  const right = uiv3FrameEl('span', 'uiv3-watch-right');
  right.append(document.createTextNode('Data '), uiv3FrameEl('span', 'uiv3-watch-value', 'Local'), document.createTextNode(` - ${Shell.eliteSessionState}`));
  replaceShellOwnedSlot(ribbon, [
    uiv3FrameWatchItem('Session', Shell.eliteSessionState, sessionKind),
    uiv3FrameWatchItem(location.flightLabel, location.flightValue, uiv3FrameChip(location).kind),
    uiv3FrameWatchItem('Sources', sourceSummary.label, sourceSummary.kind),
    uiv3FrameWatchItem('Route', routeLabel, 'info'),
    right,
  ]);

  /* RAIL-HEADER-HARMONY-01: the left rail is shell-owned and persistent, so its
     header uses the SAME grammar as the Dashboard rail — a "Ship state" label
     plus a "Details" affordance that opens the Activity Log proof console (one
     click to proof, Design Authority §7). This replaces the former static
     "Local telemetry" caption so every route's rail header reads identically.
     Reuses the shared dashboard-uiv3-rail-* classes for identical styling. */
  const railHeader = uiv3FrameEl('div', 'uiv3-left-rail-header dashboard-uiv3-rail-header');
  const railDetailsLink = uiv3FrameEl('a', 'uiv3-data-label dashboard-uiv3-rail-link', 'Details');
  railDetailsLink.setAttribute('href', '#/activity-log');
  railHeader.append(uiv3FrameEl('span', 'uiv3-label', 'Ship state'), railDetailsLink);

  const locationPanel = uiv3FrameEl('section', 'uiv3-left-rail-panel uiv3-corner-frame');
  locationPanel.setAttribute('aria-label', 'Local ship and location context');
  const locationInner = uiv3FrameEl('div', 'uiv3-corner-frame-inner');
  locationInner.append(uiv3FrameEl('span', 'uiv3-label', 'Commander context'));
  [
    uiv3FrameMetric('Ship', shipLabel),
    uiv3FrameMetric('System', uiv3FrameText(location.systemName)),
    uiv3FrameMetric(location.flightLabel, location.flightValue),
  ].filter(Boolean).forEach((row) => locationInner.appendChild(row));
  if (location.stationName) locationInner.appendChild(uiv3FrameMetric('Docked context', location.stationName));
  locationPanel.appendChild(locationInner);

  const vitalsPanel = uiv3FrameEl('section', 'uiv3-left-rail-panel');
  vitalsPanel.setAttribute('aria-label', 'Local ship vitals');
  vitalsPanel.appendChild(uiv3FrameEl('span', 'uiv3-label', 'Vitals'));
  const vitalRows = [
    uiv3FrameMetric('Hull', uiv3FramePct(frame.shipState?.hull_health)),
    uiv3FrameMetric('Shields', frame.shipState?.shield_up === true ? 'UP' : (frame.shipState?.shield_up === false ? 'DOWN' : null)),
    uiv3FrameMetric('Fuel', uiv3FramePct(frame.shipState?.fuel_pct)),
    uiv3FrameMetric('Cargo', uiv3FrameCargo(frame.shipState)),
    uiv3FrameMetric('Jump range', Number.isFinite(frame.shipState?.jump_range_ly) ? `${frame.shipState.jump_range_ly} ly` : null),
  ].filter(Boolean);
  if (vitalRows.length > 0) vitalRows.forEach((row) => vitalsPanel.appendChild(row));
  else vitalsPanel.appendChild(uiv3FrameEl('p', null, 'No local ship vitals loaded.'));

  /* RAIL-SCHEMATIC-01: the left rail is persistent shell chrome shown on every
     route, so the identity-gated ship schematic is rendered here by the SAME
     shared renderer the Dashboard uses — not Dashboard-only. The card sits at
     the top of the rail above Commander context + vitals. Guarded so the very
     first synchronous shell render (before the classic helper script has run)
     simply omits it; later renders include it. */
  const railChildren = [railHeader];
  if (window.OmniShipStateRail && typeof window.OmniShipStateRail.buildShipSchematicCard === 'function') {
    const railShipType = frame.shipState?.ship_type || frame.shipState?.current_ship_type || null;
    railChildren.push(window.OmniShipStateRail.buildShipSchematicCard(railShipType, {
      shipLabel: String(shipLabel || 'UNKNOWN').toUpperCase(),
    }));
  }
  railChildren.push(locationPanel, vitalsPanel);
  replaceShellOwnedSlot(rail, railChildren);

  const anchor = uiv3FrameEl('span', 'uiv3-spine-anchor');
  const icon = uiv3FrameEl('span', 'uiv3-icon');
  icon.setAttribute('data-uiv3-icon', 'compass-diamond');
  icon.setAttribute('aria-hidden', 'true');
  anchor.append(icon, uiv3FrameEl('span', null, 'Ship'), uiv3FrameEl('span', 'uiv3-spine-value', shipLabel));
  const vitals = uiv3FrameEl('span', 'uiv3-spine-vitals');
  [
    uiv3FrameSpineItem('Hull', uiv3FramePct(frame.shipState?.hull_health)),
    uiv3FrameSpineItem('Shields', frame.shipState?.shield_up === true ? 'UP' : (frame.shipState?.shield_up === false ? 'DOWN' : null)),
    uiv3FrameSpineItem('Fuel', uiv3FramePct(frame.shipState?.fuel_pct)),
    uiv3FrameSpineItem('Cargo', uiv3FrameCargo(frame.shipState)),
    uiv3FrameSpineItem('Route', routeLabel),
  ].filter((item) => item.querySelector('.uiv3-spine-value')?.textContent).forEach((item) => vitals.appendChild(item));
  replaceShellOwnedSlot(spine, [
    anchor,
    vitals,
    uiv3FrameEl('span', 'uiv3-spine-note', `${Shell.eliteSessionState} local state`),
  ]);

  window.Uiv3Frame?.mountUiv3Icons?.(document);
}

function renderUiv3Frame() {
  const frame = Shell.uiv3FrameState;
  const location = frame.location || uiv3FrameLocationFallback(frame.shipState, frame.navSnap);
  const sourceSummary = uiv3FrameLocalSourceSummary(frame.localContextRaw);
  renderUiv3IdentityFrame(frame, location, sourceSummary);
  renderUiv3ShellSlots(frame, location, sourceSummary);
}

function loadUiv3FrameViewModels() {
  if (!uiv3FrameViewModelsPromise) {
    uiv3FrameViewModelsPromise = Promise.all([
      import('../view-models/local-context.js'),
      import('../view-models/commander-context.js'),
    ]).then(([localContext, commanderContext]) => ({
      deriveLocalContext: localContext.deriveLocalContext,
      deriveCommanderLocationState: commanderContext.deriveCommanderLocationState,
    }));
  }
  return uiv3FrameViewModelsPromise;
}

async function fetchUiv3FrameJson(path) {
  if (!Shell.httpBase) return null;
  try {
    const response = await fetch(`${Shell.httpBase}${path}`);
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

async function refreshUiv3FrameSnapshots() {
  if (!Shell.httpBase) {
    renderUiv3Frame();
    return;
  }
  if (uiv3FrameRefreshPromise) return uiv3FrameRefreshPromise;

  uiv3FrameRefreshPromise = Promise.all([
    fetchUiv3FrameJson('/pillar1/ship-state'),
    fetchUiv3FrameJson('/intel/local-context/snapshot'),
    fetchUiv3FrameJson('/navigation/snapshot'),
    fetchUiv3FrameJson('/source/health'),
    loadUiv3FrameViewModels().catch(() => null),
  ]).then(([shipState, localContextRaw, navSnap, sourceSnap, viewModels]) => {
    const frame = Shell.uiv3FrameState;
    if (shipState) frame.shipState = shipState;
    if (localContextRaw) {
      frame.localContextRaw = localContextRaw;
      const next = deriveEliteSessionState(localContextRaw);
      if (next) setEliteSessionState(next);
    }
    if (navSnap) frame.navSnap = navSnap;
    if (sourceSnap) frame.sourceSnap = sourceSnap;
    if (viewModels && frame.localContextRaw) {
      frame.localContext = viewModels.deriveLocalContext(frame.localContextRaw);
      frame.location = viewModels.deriveCommanderLocationState(
        frame.localContext,
        frame.shipState,
        frame.navSnap,
        { sessionState: Shell.eliteSessionState },
      );
    } else {
      frame.location = uiv3FrameLocationFallback(frame.shipState, frame.navSnap);
    }
    renderUiv3Frame();
  }).finally(() => {
    uiv3FrameRefreshPromise = null;
  });

  return uiv3FrameRefreshPromise;
}

function updateUiv3FrameFromPublicState(state) {
  if (state && typeof state === 'object') {
    Shell.uiv3FrameState.publicState = state;
  }
  renderUiv3Frame();
  refreshUiv3FrameSnapshots();
}

/* Re-evaluate Elite session every 15s so we slip from Active to Last
   known automatically once journal activity goes quiet. */
setInterval(recomputeEliteSessionState, 15_000);

/* ── Timer cleanup ── */
function clearReconnectTimer() {
  if (Shell.wsReconnectTimer) {
    clearTimeout(Shell.wsReconnectTimer);
    Shell.wsReconnectTimer = null;
  }
}

function stopPolling() {
  if (Shell.pollTimer) {
    clearInterval(Shell.pollTimer);
    Shell.pollTimer = null;
  }
}

function startPolling() {
  stopPolling();
  Shell.pollTimer = setInterval(fetchState, 2000);
}

/* ── Bridge configuration ── */
function setBridge(port, httpBase, wsBase) {
  Shell.port = port;
  Shell.httpBase = httpBase || `http://127.0.0.1:${port}`;
  Shell.wsBase = wsBase || `ws://127.0.0.1:${port}`;
  window.OMNICOVAS_PORT = port;
}

/* ── Tauri bridge-ready listener ── */
function waitForTauriBridgeReady(timeoutMs = 10000) {
  return new Promise((resolve) => {
    let resolved = false;
    let unlistenPromise = null;

    function finish(payload) {
      if (resolved) return;
      resolved = true;

      if (unlistenPromise) {
        unlistenPromise
          .then((unlisten) => {
            if (typeof unlisten === 'function') unlisten();
          })
          .catch(() => {});
      }

      resolve(normalizeBridge(payload));
    }

    if (window.OMNICOVAS_PORT) {
      finish({ port: window.OMNICOVAS_PORT });
      return;
    }

    const params = new URLSearchParams(window.location.search);
    if (params.has('port')) {
      finish({ port: parseInt(params.get('port'), 10) });
      return;
    }

    const tauriListen = window.__TAURI__?.event?.listen;

    if (typeof tauriListen === 'function') {
      unlistenPromise = tauriListen('bridge-ready', (event) => {
        finish(event?.payload || null);
      });
    }

    setTimeout(() => finish(null), timeoutMs);
  });
}

/* ── Tauri command fallback ── */
async function getBridgeFromTauriCommand() {
  const invoke = window.__TAURI__?.core?.invoke;

  if (typeof invoke !== 'function') {
    return null;
  }

  for (let i = 0; i < 20; i += 1) {
    try {
      const bridge = normalizeBridge(await invoke('get_bridge_info'));

      if (bridge) {
        return bridge;
      }
    } catch {
      /* command unavailable or not ready yet */
    }

    await sleep(500);
  }

  return null;
}

/* ── Last-resort dev probe ── */
async function probeForBridge() {
  for (let p = 50000; p <= 65000; p += 500) {
    try {
      const response = await fetch(`http://127.0.0.1:${p}/health`, {
        signal: AbortSignal.timeout(300),
      });

      if (response.ok) {
        return normalizeBridge({ port: p });
      }
    } catch {
      /* try next candidate port */
    }
  }

  return null;
}

/* ── Port discovery ── */
async function discover() {
  const fromTauriEvent = await waitForTauriBridgeReady();

  if (fromTauriEvent) {
    return fromTauriEvent;
  }

  const fromTauriCommand = await getBridgeFromTauriCommand();

  if (fromTauriCommand) {
    return fromTauriCommand;
  }

  return probeForBridge();
}

/* ── License status check (fires before onboarding gate) ── */
async function checkLicenseStatus() {
  try {
    const response = await fetch(`${Shell.httpBase}/week13/license/status`);
    if (!response.ok) return false;
    const status = await response.json();
    if (status.needs_acceptance === true) {
      if (typeof window.OmniOnboarding?.showLicenseScreen === 'function') {
        window.OmniOnboarding.showLicenseScreen();
      } else {
        /* onboarding.js not yet initialized; drain when it loads */
        window.__pendingLicenseShow = true;
      }
      return true; /* license gate active; skip onboarding check */
    }
    return false;
  } catch (err) {
    console.warn('license_status_unavailable', err);
    return false;
  }
}

/* ── Onboarding status check ── */
async function checkOnboardingStatus() {
  try {
    const response = await fetch(`${Shell.httpBase}/week13/onboarding/status`);
    if (!response.ok) return;
    const status = await response.json();
    if (status.should_show_wizard === true) {
      if (typeof window.OmniOnboarding?.show === 'function') {
        window.OmniOnboarding.show();
      } else {
        /* onboarding.js not yet initialized; drain when it loads */
        window.__pendingOnboardingShow = true;
      }
    }
  } catch (err) {
    console.warn('onboarding_status_unavailable', err);
  }
}

/* ── HTTP state fetch ── */
async function fetchState() {
  if (!Shell.httpBase) return;

  try {
    const response = await fetch(`${Shell.httpBase}/state`);

    if (response.ok) {
      emit('state', await response.json());
    }
  } catch {
    /* silent — WebSocket is primary, polling is safety net */
  }
}

/* ── WebSocket ── */
function closeExistingWebSocket() {
  if (!Shell.ws) return;

  Shell.ws.onopen = null;
  Shell.ws.onmessage = null;
  Shell.ws.onclose = null;
  Shell.ws.onerror = null;

  try {
    Shell.ws.close();
  } catch {
    /* ignore close failure */
  }

  Shell.ws = null;
}

function openWebSocket() {
  if (!Shell.wsBase || !Shell.port) return;

  clearReconnectTimer();
  closeExistingWebSocket();

  const ws = new WebSocket(`${Shell.wsBase}/ws/events`);
  Shell.ws = ws;

  ws.onopen = () => {
    Shell.wsReconnectDelay = 1000;
    setConnected(true, Shell.port);
    stopPolling();

    emit('bridge-connected', {
      port: Shell.port,
      httpBase: Shell.httpBase,
      wsBase: Shell.wsBase,
    });
  };

  ws.onmessage = (event) => {
    try {
      const message = JSON.parse(event.data);

      if (message.type === 'initial_state') {
        emit('state', message.state ?? message);
      } else if (message.type === 'event') {
        emit('event', message);
        const evtType = message.event_type || message.event;
        if (evtType && JOURNAL_EVENT_TYPES.has(evtType)) {
          markJournalActivity();
        }
      } else if (message.state) {
        emit('state', message.state);
      } else {
        emit('event', message);
        const evtType = message.event_type || message.event;
        if (evtType && JOURNAL_EVENT_TYPES.has(evtType)) {
          markJournalActivity();
        }
      }
    } catch {
      /* malformed WebSocket frame; ignore */
    }
  };

  ws.onclose = () => {
    setConnected(false, null);
    emit('bridge-disconnected', { port: Shell.port });

    startPolling();

    Shell.wsReconnectTimer = setTimeout(() => {
      Shell.wsReconnectDelay = Math.min(Shell.wsReconnectDelay * 2, 16000);
      openWebSocket();
    }, Shell.wsReconnectDelay);
  };

  ws.onerror = () => {
    try {
      ws.close();
    } catch {
      /* ignore */
    }
  };
}

/* ── Boot ── */
async function boot() {
  if (Shell.booting) return;

  Shell.booting = true;
  setConnected(false, null);

  const bridge = await discover();

  if (!bridge?.port) {
    Shell.booting = false;
    setCoreNotFound();

    setTimeout(boot, 5000);
    return;
  }

  setBridge(bridge.port, bridge.httpBase, bridge.wsBase);

  await fetchState();
  refreshUiv3FrameSnapshots();
  openWebSocket();
  checkLicenseStatus().then(licenseGateActive => { /* non-fatal */
    if (!licenseGateActive) checkOnboardingStatus();
  });

  Shell.booting = false;
}

/* ── Routing ── */
const ROUTES = {
  '/dashboard': 'view-dashboard',
  '/intel': 'view-intel',
  '/navigation': 'view-navigation',
  '/engineering': 'view-engineering',
  '/operations': 'view-operations',
  '/systems': 'view-systems',
  '/systems/settings': 'view-systems',
  '/systems/privacy': 'view-systems',
  '/systems/sources-diagnostics': 'view-systems',
  '/systems/resources': 'view-systems',
  '/systems/about': 'view-systems',
  '/squadrons': 'view-squadrons',
  '/activity-log': 'view-activity-log',
  '/settings': 'view-settings',
  '/privacy': 'view-privacy',
  '/resources': 'view-resources',
  '/credits': 'view-credits',
  /* Correction #14: Sources & Diagnostics is a real top-level Systems
     surface (not a Settings sub-tab). */
  '/sources': 'view-sources-diagnostics',
  '/diagnostics': 'view-sources-diagnostics',
};

const ROUTE_LABELS = {
  '/dashboard': 'Dashboard',
  '/intel': 'Intel',
  '/navigation': 'Navigation',
  '/engineering': 'Engineering',
  '/operations': 'Operations',
  '/systems': 'Systems',
  '/systems/settings': 'Systems / Settings',
  '/systems/privacy': 'Systems / Privacy',
  '/systems/sources-diagnostics': 'Systems / Sources & Diagnostics',
  '/systems/resources': 'Systems / Resources',
  '/systems/about': 'Systems / About',
  '/squadrons': 'Squadrons',
  '/activity-log': 'Activity Log',
  '/settings': 'Settings',
  '/privacy': 'Privacy',
  '/resources': 'Resources',
  '/credits': 'About / Credits',
};

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

function toRouteTransferText(value, fallback = '') {
  if (value === null || value === undefined || value === '') {
    return fallback;
  }

  return String(value);
}

function normalizeRouteName(value) {
  const text = toRouteTransferText(value, '').trim();
  if (!text) {
    return '';
  }

  const withoutHash = text.replace(/^#/, '');
  const routeOnly = withoutHash.includes('#') ? withoutHash.split('#')[0] : withoutHash;

  if (!routeOnly) {
    return '';
  }

  return routeOnly.startsWith('/') ? routeOnly : `/${routeOnly}`;
}

function routeLabel(routeName) {
  const route = normalizeRouteName(routeName);
  return ROUTE_LABELS[route] || toRouteTransferText(routeName, 'Unknown route');
}

function normalizeReturnTarget(value, fallbackRoute, fallbackSectionId) {
  const target = value && typeof value === 'object' ? value : {};
  const route = normalizeRouteName(target.route) || fallbackRoute || '/dashboard';

  return {
    route,
    package: toRouteTransferText(target.package, ''),
    sectionId: toRouteTransferText(target.sectionId, fallbackSectionId || ''),
    entityId: toRouteTransferText(target.entityId, ''),
  };
}

function routeHashForTarget(target) {
  const route = normalizeRouteName(target?.route || target);
  const safeRoute = ROUTES[route] ? route : '/dashboard';
  const sectionId = toRouteTransferText(target?.sectionId, '');

  if (!sectionId) {
    return `#${safeRoute}`;
  }

  return `#${safeRoute}#${encodeURIComponent(sectionId)}`;
}

function isModalOrGateFocusActive() {
  const active = document.activeElement;
  const activeModal = active?.closest?.('[aria-modal="true"], [role="dialog"], #confirmation-gate-root, .confirmation-gate, .confirmation-card, .sq-gate-modal');
  if (activeModal) {
    return true;
  }

  const modal = document.querySelector('[aria-modal="true"], [role="dialog"], #confirmation-gate-root, .confirmation-gate, .confirmation-card, .sq-gate-modal');
  if (!modal) {
    return false;
  }

  if (modal.hidden || modal.getAttribute('aria-hidden') === 'true') {
    return false;
  }

  if (typeof window.getComputedStyle !== 'function') {
    return true;
  }

  const style = window.getComputedStyle(modal);
  return style.display !== 'none' && style.visibility !== 'hidden';
}

function prefersReducedMotion() {
  return typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function ensureFocusable(element) {
  if (!element) {
    return;
  }

  if (element.matches?.(FOCUSABLE_SELECTOR)) {
    return;
  }

  if (!element.hasAttribute('tabindex')) {
    element.setAttribute('tabindex', '-1');
    element.setAttribute('data-route-handoff-tabindex', 'added');
  }
}

function resolveRouteTransferTarget(root, intent, options) {
  if (typeof options?.resolveTarget === 'function') {
    const resolved = options.resolveTarget(intent, root);
    if (resolved && root.contains(resolved)) {
      return resolved;
    }
  }

  const sectionId = toRouteTransferText(intent.targetSectionId, '');
  if (!sectionId) {
    return null;
  }

  const byId = document.getElementById(sectionId);
  if (byId && root.contains(byId)) {
    return byId;
  }

  return null;
}

function createRouteTransferLine(label, value) {
  const line = document.createElement('p');
  line.className = 'route-arrival-line';

  const labelEl = document.createElement('span');
  labelEl.className = 'route-arrival-line-label';
  labelEl.textContent = label;

  const valueEl = document.createElement('span');
  valueEl.className = 'route-arrival-line-value';
  valueEl.textContent = value;

  line.append(labelEl, valueEl);
  return line;
}

function createReturnIntent(intent) {
  const returnTarget = normalizeReturnTarget(intent.returnTarget, intent.originRoute, intent.originSectionId);

  return Shell.createRouteTransferIntent({
    originRoute: intent.targetRoute,
    originPackage: routeLabel(intent.targetRoute),
    originSectionId: intent.targetSectionId,
    targetRoute: returnTarget.route,
    targetSectionId: returnTarget.sectionId,
    targetEntityId: returnTarget.entityId,
    targetLabel: intent.returnLabel || routeLabel(returnTarget.route),
    reason: `Return from ${routeLabel(intent.targetRoute)}.`,
    returnLabel: intent.targetLabel ? `Return to ${intent.targetLabel}` : `Return to ${routeLabel(intent.targetRoute)}`,
    returnTarget: {
      route: intent.targetRoute,
      package: '',
      sectionId: intent.targetSectionId,
      entityId: intent.targetEntityId,
    },
  });
}

function createRouteTransferBanner(intent, target, unavailable) {
  const banner = document.createElement('section');
  banner.className = unavailable
    ? 'route-arrival-banner route-arrival-banner--unavailable'
    : 'route-arrival-banner';
  banner.setAttribute('role', 'status');
  banner.setAttribute('aria-live', 'polite');
  banner.setAttribute('tabindex', '-1');

  const title = document.createElement('h2');
  title.className = 'route-arrival-title';
  title.textContent = unavailable ? 'Handoff Target Unavailable' : 'Route Handoff';

  const originParts = [routeLabel(intent.originRoute)];
  if (intent.originPackage) {
    originParts.push(intent.originPackage);
  }
  if (intent.originSectionId) {
    originParts.push(intent.originSectionId);
  }

  const shown = intent.targetLabel
    || intent.targetEntityId
    || intent.targetSectionId
    || routeLabel(intent.targetRoute);
  const reason = intent.reason || 'Route handoff requested.';

  banner.append(
    title,
    createRouteTransferLine('From', originParts.join(' / ')),
    createRouteTransferLine('Showing', shown),
    createRouteTransferLine('Why', reason),
  );

  if (unavailable) {
    banner.appendChild(createRouteTransferLine(
      'Target',
      target ? 'Available' : 'Unavailable on this route.',
    ));
  }

  const returnTarget = normalizeReturnTarget(intent.returnTarget, intent.originRoute, intent.originSectionId);
  const returnHref = routeHashForTarget(returnTarget);
  const returnLink = document.createElement('a');
  returnLink.className = 'route-arrival-return';
  returnLink.setAttribute('href', returnHref);
  returnLink.textContent = intent.returnLabel || `Return to ${routeLabel(returnTarget.route)}`;
  returnLink.addEventListener('click', (event) => {
    if (typeof Shell.startRouteTransfer !== 'function') {
      return;
    }

    const returnIntent = createReturnIntent(intent);
    event.preventDefault();
    if (!Shell.startRouteTransfer(returnIntent)) {
      window.location.hash = returnHref;
    }
  });

  banner.appendChild(returnLink);
  return banner;
}

function scrollAndFocusRouteTransferTarget(target) {
  if (!target) {
    return;
  }

  if (typeof target.scrollIntoView === 'function') {
    target.scrollIntoView({
      block: 'start',
      behavior: prefersReducedMotion() ? 'auto' : 'smooth',
    });
  }

  if (isModalOrGateFocusActive()) {
    return;
  }

  ensureFocusable(target);

  if (typeof target.focus === 'function') {
    try {
      target.focus({ preventScroll: true });
    } catch (_error) {
      target.focus();
    }
  }
}

function createRouteTransferIntent(input = {}) {
  const originRoute = normalizeRouteName(input.originRoute) || normalizeRouteName(window.location.hash) || '/dashboard';
  const targetRoute = normalizeRouteName(input.targetRoute);
  const originSectionId = toRouteTransferText(input.originSectionId, '');

  return {
    originRoute,
    originPackage: toRouteTransferText(input.originPackage, ''),
    originSectionId,
    targetRoute,
    targetSectionId: toRouteTransferText(input.targetSectionId, ''),
    targetEntityId: toRouteTransferText(input.targetEntityId, ''),
    targetLabel: toRouteTransferText(input.targetLabel, ''),
    reason: toRouteTransferText(input.reason, ''),
    returnLabel: toRouteTransferText(input.returnLabel, ''),
    returnTarget: normalizeReturnTarget(input.returnTarget, originRoute, originSectionId),
    timestamp: toRouteTransferText(input.timestamp, new Date().toISOString()),
  };
}

function startRouteTransfer(intentInput) {
  const intent = createRouteTransferIntent(intentInput);

  if (!ROUTES[intent.targetRoute]) {
    return null;
  }

  Shell.routeTransferIntent = intent;
  const nextHash = `#${intent.targetRoute}`;
  window.location.hash = nextHash;
  navigate(nextHash);
  applyMountedRouteTransferIfReady(intent);
  emit('route-transfer-started', { intent });
  return intent;
}

function getRouteTransferIntent(routeName) {
  const route = normalizeRouteName(routeName);
  const intent = Shell.routeTransferIntent;

  if (!intent || !route || intent.targetRoute !== route) {
    return null;
  }

  return intent;
}

function clearRouteTransferIntent(intent) {
  if (!intent || Shell.routeTransferIntent?.timestamp === intent.timestamp) {
    Shell.routeTransferIntent = null;
  }
}

function applyRouteTransferArrival(routeName, root, options = {}) {
  if (!root) {
    return null;
  }

  const intent = getRouteTransferIntent(routeName);
  if (!intent) {
    return null;
  }

  root.querySelectorAll('.route-arrival-banner').forEach((banner) => banner.remove());
  root.querySelectorAll('.route-handoff-target--active').forEach((activeTarget) => {
    activeTarget.classList.remove('route-handoff-target--active');
    activeTarget.removeAttribute('data-route-handoff-target');
  });

  const target = resolveRouteTransferTarget(root, intent, options);
  const unavailable = !target;
  const banner = createRouteTransferBanner(intent, target, unavailable);

  root.prepend(banner);

  if (target) {
    target.classList.add('route-handoff-target--active');
    target.setAttribute('data-route-handoff-target', 'active');
    scrollAndFocusRouteTransferTarget(target);
  } else if (!isModalOrGateFocusActive() && typeof banner.focus === 'function') {
    try {
      banner.focus({ preventScroll: true });
    } catch (_error) {
      banner.focus();
    }
  }

  clearRouteTransferIntent(intent);
  emit('route-transfer-arrived', { intent, targetFound: Boolean(target) });
  return { intent, banner, target };
}

function applyMountedRouteTransferIfReady(intent) {
  const viewId = ROUTES[intent.targetRoute];
  const routeView = viewId ? document.getElementById(viewId) : null;
  const target = intent.targetSectionId ? document.getElementById(intent.targetSectionId) : null;

  if (!routeView || !target || !routeView.contains(target)) {
    return null;
  }

  return applyRouteTransferArrival(intent.targetRoute, routeView);
}

function navigate(hash) {
  const rawHash = String(hash || '').replace(/^#/, '');
  /* Split route from deliberate in-route anchor: "/operations#combat" -> route "/operations", anchor "combat". */
  const hashSepIndex = rawHash.indexOf('#');
  const routePart = (hashSepIndex >= 0 ? rawHash.slice(0, hashSepIndex) : rawHash) || '/dashboard';
  const route = routePart.startsWith('/') ? routePart : `/${routePart}`;
  const inRouteAnchor = hashSepIndex >= 0 ? rawHash.slice(hashSepIndex + 1) : '';
  const viewId = ROUTES[route] || ROUTES['/dashboard'];

  updateUiv3ActiveTab(route);

  document.querySelectorAll('.view').forEach((view) => {
    view.classList.remove('active');
  });

  const target = document.getElementById(viewId);
  if (target) {
    target.classList.add('active');
  }

  /* PB07.5-01: route navigation resets content scroll to top unless a deliberate in-route anchor is given. */
  const contentArea = document.getElementById('content-area');
  if (contentArea) {
    if (inRouteAnchor) {
      const anchorEl = document.getElementById(inRouteAnchor);
      if (anchorEl && typeof anchorEl.scrollIntoView === 'function') {
        anchorEl.scrollIntoView({ block: 'start' });
      }
    } else {
      contentArea.scrollTop = 0;
    }
  }

  renderUiv3Frame();
}

window.addEventListener('hashchange', () => {
  navigate(window.location.hash);
});

/* ── DOM ready ── */
document.addEventListener('DOMContentLoaded', () => {
  if (window.Uiv3Frame?.mountUiv3Icons) {
    window.Uiv3Frame.mountUiv3Icons(document);
  }
  updateUiv3Clock();
  setInterval(updateUiv3Clock, 30_000);
  navigate(window.location.hash || '#/dashboard');
  document.getElementById('uiv3-settings-button')?.addEventListener('click', () => {
    window.location.hash = '#/settings';
  });
  boot();
});

/* ── Expose for views/devtools/tests ── */
window.OmniEvents.addEventListener('state', (event) => updateUiv3FrameFromPublicState(event.detail));
window.OmniEvents.addEventListener('bridge-connected', refreshUiv3FrameSnapshots);
window.OmniEvents.addEventListener('elite-session-state', () => {
  renderUiv3Frame();
  refreshUiv3FrameSnapshots();
});
Shell.navigate = navigate;
Shell.routeTransferIntent = null;
Shell.createRouteTransferIntent = createRouteTransferIntent;
Shell.startRouteTransfer = startRouteTransfer;
Shell.getRouteTransferIntent = getRouteTransferIntent;
Shell.clearRouteTransferIntent = clearRouteTransferIntent;
Shell.applyRouteTransferArrival = applyRouteTransferArrival;
Shell.setEliteSessionState = setEliteSessionState;
Shell.deriveEliteSessionState = deriveEliteSessionState;
Shell.markJournalActivity = markJournalActivity;
Shell.recomputeEliteSessionState = recomputeEliteSessionState;
Shell.updateUiv3ActiveTab = updateUiv3ActiveTab;
Shell.renderUiv3Frame = renderUiv3Frame;
Shell.refreshUiv3FrameSnapshots = refreshUiv3FrameSnapshots;
window.Shell = Shell;
