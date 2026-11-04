/**
 * OmniCOVAS Overlay — the separate in-game attention lane.
 *
 * Two presentation paths share this window, never at the same time:
 *
 *  - Director (NHI-03/04): the backend Notification Director owns arbitration.
 *    This file renders exactly the slot in the latest `notification_presentation`
 *    snapshot and reports what it actually rendered through delivery receipts.
 *    Raw alert events are ignored while the Director owns presentation, so a
 *    migrated alert is never shown twice.
 *  - Legacy fallback: the original banner queue, used when the snapshot says the
 *    legacy path owns presentation (configured rollback or Director failure).
 *
 * The window is shown once and afterwards parked (emptied and shrunk) instead of
 * hidden: re-showing a hidden window activates it on Windows, which would take
 * focus from the game. It never calls focus and stays click-through unless the
 * Commander toggles input with Ctrl+Shift+O.
 */

const CRITICAL_EVENTS = {
  HULL_CRITICAL_10: {
    icon: '⚠',
    label: 'HULL CRITICAL',
    severity: 'critical',
    duration: 30000,
    priority: 1,
  },
  SHIELDS_DOWN: {
    icon: '▼',
    label: 'SHIELDS DOWN',
    severity: 'critical',
    duration: 5000,
    priority: 2,
  },
  HULL_CRITICAL_25: {
    icon: '⚡',
    label: 'HULL WARNING',
    severity: 'warning',
    duration: 10000,
    priority: 3,
  },
  FUEL_CRITICAL: {
    icon: '🛢',
    label: 'FUEL CRITICAL',
    severity: 'critical',
    duration: 30000,
    priority: 4,
  },
  MODULE_CRITICAL: {
    icon: '🔧',
    label: 'MODULE CRITICAL',
    severity: 'critical',
    duration: 15000,
    priority: 5,
  },
  FUEL_LOW: {
    icon: '⚠',
    label: 'FUEL LOW',
    severity: 'warning',
    duration: 10000,
    priority: 6,
  },
  HEAT_WARNING: {
    icon: '🔥',
    label: 'HEAT WARNING',
    severity: 'warning',
    duration: 8000,
    priority: 7,
  },
  HEAT_DAMAGE: {
    icon: '🔥',
    label: 'CRITICAL HEAT',
    severity: 'critical',
    duration: 15000,
    priority: 3,
  },
  // PB04-04 D3: sparse, urgent-only interdiction start alert.
  // INTERDICTION_ENDED is intentionally omitted: ended-state visibility
  // belongs in Operations and Activity Log, not the overlay lane.
  INTERDICTION_STARTED: {
    icon: '⚠',
    label: 'INTERDICTION DETECTED',
    severity: 'critical',
    duration: 8000,
    priority: 2,
    ariaLive: 'assertive',
  },
  OMNICOVAS_TEST: {
    icon: '⚙',
    label: 'OMNICOVAS TEST BANNER',
    severity: 'warning',
    duration: 5000,
    priority: 99, // lowest priority, but show_test_banner will force it
  },
  // PB05-05: sparse route-safety notice — fires only when NavRoute.json is stale/expired
  // while a route destination is known. Priority 8 (below all combat-critical events).
  // Legacy path only: under the Director, route age stays in Navigation's Route Watch.
  NAV_ROUTE_STALE: {
    icon: '⚠',
    label: 'NAV ROUTE STALE',
    severity: 'warning',
    duration: 15000,
    priority: 8,
  },
};

let currentBanner = null;
let bannerQueue = [];
let clickThrough = true;
let wsConnection = null;
let statusDotTimeout = null;
let bridgeHttpBase = null;
let bridgeWsBase = null;
let wsReconnectDelay = 1000;

// Presentation ownership. Until the first snapshot arrives the legacy path is
// assumed; the bridge sends a snapshot on connect, before any event.
let owner = 'legacy';
let directorSlot = null;
let directorElement = null;
let renderedId = null;
let lastSeq = -1;
let display = { anchor: 'tr', opacity: 0.95, text_scale: 100, reduced_motion: 'system', overlay: true };

// Overlay settings (persisted via Tauri config vault)
let overlaySettings = {
  opacity: 0.95,
  anchor: 'center',
  events: {
    HULL_CRITICAL_10: true,
    SHIELDS_DOWN: true,
    HULL_CRITICAL_25: true,
    FUEL_CRITICAL: true,
    MODULE_CRITICAL: true,
    FUEL_LOW: true,
    HEAT_WARNING: true,
    HEAT_DAMAGE: true,
  },
};

function tauriInvoke() {
  const invoke = window.__TAURI__?.core?.invoke;
  return typeof invoke === 'function' ? invoke : null;
}

/* ── Native window ─────────────────────────────────────────────────────── */

/**
 * Size and place the native window around `element` on the selected monitor.
 * Sizes are CSS (logical) pixels; the native side converts to physical pixels
 * once, using that monitor's scale factor. Resolves false when it fails.
 */
async function presentWindow(element) {
  const invoke = tauriInvoke();
  if (!invoke) return true; // browser preview: the page itself is the surface
  const rect = element.getBoundingClientRect();
  const width = Math.ceil(rect.width) + 16;
  const height = Math.ceil(rect.height) + 16;
  try {
    await invoke('present_overlay', { anchor: display.anchor || overlaySettings.anchor, width, height });
    return true;
  } catch (e) {
    console.warn('[Overlay] present failed:', e);
    return false;
  }
}

function parkWindow() {
  const invoke = tauriInvoke();
  if (invoke) invoke('park_overlay').catch(() => {});
}

/* ── Legacy path ───────────────────────────────────────────────────────── */

/**
 * The value a legacy alert shows, from its producer's documented payload.
 * Percent fields are percentages, fraction fields are 0–1; nothing is guessed
 * from truthiness, so 0% renders as 0% and missing evidence renders nothing.
 */
function extractValue(eventType, payload) {
  const p = payload && typeof payload === 'object' ? payload : {};
  const finite = (v, lo, hi) => typeof v === 'number' && Number.isFinite(v) && v >= lo && v <= hi;
  switch (eventType) {
    case 'HULL_CRITICAL_10':
    case 'HULL_CRITICAL_25':
      if (finite(p.health_pct, 0, 100)) return p.health_pct;
      if (finite(p.health, 0, 1)) return p.health * 100;
      if (finite(p.hull_health, 0, 100)) return p.hull_health;
      return null;
    case 'FUEL_CRITICAL':
    case 'FUEL_LOW':
      if (finite(p.fuel_fraction, 0, 1)) return p.fuel_fraction * 100;
      if (finite(p.fuel_percent, 0, 100)) return p.fuel_percent;
      return null;
    case 'HEAT_WARNING':
      return finite(p.heat, 0, 10) ? p.heat * 100 : null;
    case 'MODULE_CRITICAL':
      return finite(p.health, 0, 1) ? p.health * 100 : null;
    case 'SHIELDS_DOWN':
      return 'DOWN';
    default:
      return null;
  }
}

function startBannerTimer(banner) {
  // Each displayed banner owns its own timer; nothing else may reset it.
  clearTimeout(banner.timeoutId);
  banner.timeoutId = setTimeout(() => {
    if (currentBanner === banner) dismissBanner();
  }, banner.remaining ?? banner.config.duration);
  banner.startedAt = Date.now();
}

function enqueue(banner) {
  const same = bannerQueue.findIndex((b) => b.eventType === banner.eventType);
  if (same >= 0) bannerQueue.splice(same, 1); // repeated observations coalesce
  bannerQueue.push(banner);
  bannerQueue.sort((a, b) => a.config.priority - b.config.priority);
}

/**
 * Show a banner with auto-dismiss. Preempt lower-priority banners; a preempted
 * banner returns to the queue with its remaining time. A lower-priority banner
 * waits and never changes the timing of the banner on screen.
 */
function showBanner(eventType, value) {
  const config = CRITICAL_EVENTS[eventType];
  if (!config) return;

  // Check if this event type is enabled in settings
  if (overlaySettings.events[eventType] === false) return;

  const banner = {
    eventType,
    config,
    value,
    id: Date.now(),
  };

  if (currentBanner && currentBanner.eventType === eventType) {
    // Same alert observed again: refresh its value, keep its own timer.
    currentBanner.value = value;
    renderBanner(currentBanner);
    return;
  }
  if (currentBanner && config.priority < currentBanner.config.priority) {
    const preempted = currentBanner;
    clearTimeout(preempted.timeoutId);
    const elapsed = Date.now() - (preempted.startedAt || Date.now());
    preempted.remaining = Math.max(0, (preempted.remaining ?? preempted.config.duration) - elapsed);
    if (preempted.remaining > 0) enqueue(preempted);
    currentBanner = banner;
    renderBanner(banner);
    startBannerTimer(banner);
  } else if (!currentBanner) {
    currentBanner = banner;
    renderBanner(banner);
    startBannerTimer(banner);
  } else {
    enqueue(banner);
  }
}

function formatValue(value) {
  if (typeof value === 'number') return Number.isFinite(value) ? `${Math.floor(value)}%` : '';
  return value == null ? '' : String(value);
}

/**
 * Render a banner to the DOM with opacity applied.
 */
function renderBanner(banner) {
  const container = document.getElementById('overlay-container');
  const existing = container.querySelector('.banner');
  if (existing) existing.remove();

  const bannerEl = document.createElement('div');
  bannerEl.className = `banner ${banner.config.severity}`;
  bannerEl.style.opacity = overlaySettings.opacity.toString();

  // PB04-04 D3: opt-in live-region attributes for urgent alerts.
  // Set BEFORE appending children so screen readers announce the assembled
  // banner as a single atomic unit. Does not call focus() — non-focus-stealing
  // is preserved.
  if (banner.config.ariaLive === 'assertive') {
    bannerEl.setAttribute('role', 'alert');
    bannerEl.setAttribute('aria-live', 'assertive');
    bannerEl.setAttribute('aria-atomic', 'true');
  }

  const sourceEl = document.createElement('span');
  sourceEl.className = 'banner-source';
  sourceEl.textContent = 'OmniCOVAS';

  const iconEl = document.createElement('span');
  iconEl.className = 'banner-icon';
  iconEl.textContent = banner.config.icon;

  const labelEl = document.createElement('span');
  labelEl.className = 'banner-label';
  labelEl.textContent = banner.config.label;

  const valueEl = document.createElement('span');
  valueEl.className = 'banner-value';
  valueEl.textContent = formatValue(banner.value);

  bannerEl.appendChild(sourceEl);
  bannerEl.appendChild(iconEl);
  bannerEl.appendChild(labelEl);
  bannerEl.appendChild(valueEl);

  container.appendChild(bannerEl);
  presentWindow(bannerEl);
}

/**
 * Dismiss current banner and show next in queue if available.
 */
function dismissBanner() {
  if (!currentBanner) return;

  clearTimeout(currentBanner.timeoutId);
  const container = document.getElementById('overlay-container');
  const banner = container.querySelector('.banner');
  if (banner) banner.remove();

  currentBanner = null;

  if (bannerQueue.length > 0) {
    const next = bannerQueue.shift();
    currentBanner = next;
    renderBanner(next);
    startBannerTimer(next);
  } else {
    parkWindow();
  }
}

function clearLegacy() {
  if (currentBanner?.timeoutId) clearTimeout(currentBanner.timeoutId);
  currentBanner = null;
  bannerQueue.forEach((b) => clearTimeout(b.timeoutId));
  bannerQueue = [];
  document.querySelector('#overlay-container .banner')?.remove();
}

/* ── Director path ─────────────────────────────────────────────────────── */

async function postReceipt(presentationId, status, detail = '') {
  if (!bridgeHttpBase) return;
  try {
    await fetch(`${bridgeHttpBase}/notifications/receipts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ presentation_id: presentationId, client: 'overlay', status, detail }),
    });
  } catch { /* the bridge is gone; the Director treats silence as not shown */ }
}

function applyDisplay(next) {
  if (next && typeof next === 'object') display = { ...display, ...next };
  const root = document.documentElement;
  const scale = [100, 125, 150, 200].includes(display.text_scale) ? display.text_scale : 100;
  root.style.setProperty('--ocv-alert-scale', String(scale / 100));
  root.dataset.reducedMotion = display.reduced_motion === 'reduce' ? 'reduce' : 'system';
}

function buildAlert(slot) {
  const el = document.createElement('section');
  el.className = `ocv-alert ocv-alert--${slot.severity === 'critical' ? 'critical' : slot.severity === 'warning' ? 'warning' : 'notice'}`;
  el.dataset.presentationId = slot.presentation_id;
  el.setAttribute('role', slot.live === 'assertive' ? 'alert' : 'status');
  el.setAttribute('aria-live', slot.live === 'assertive' ? 'assertive' : 'polite');
  el.setAttribute('aria-atomic', 'true');
  el.style.opacity = String(Math.max(0.5, Math.min(1, display.opacity ?? 0.95)));

  const label = document.createElement('p');
  label.className = 'ocv-alert-label';
  const heading = document.createElement('p');
  heading.className = 'ocv-alert-heading';
  const body = document.createElement('p');
  body.className = 'ocv-alert-body';
  el.append(label, heading, body);
  fillAlert(el, slot);
  return el;
}

function fillAlert(el, slot) {
  // Event- and knowledge-derived text is always inserted as text, never markup.
  el.querySelector('.ocv-alert-label').textContent = String(slot.label || 'OmniCOVAS');
  el.querySelector('.ocv-alert-heading').textContent = String(slot.heading || '');
  el.querySelector('.ocv-alert-body').textContent = String(slot.body || '');
  el.querySelector('.ocv-alert-dismiss')?.remove();
  if (!clickThrough && slot.presentation_id) {
    // Input is grabbed (Ctrl+Shift+O): offer a pointer acknowledgement. It
    // dismisses this alert only; the condition stays in the ship's Watch.
    const dismiss = document.createElement('button');
    dismiss.type = 'button';
    dismiss.className = 'ocv-alert-dismiss';
    dismiss.textContent = 'Dismiss';
    dismiss.setAttribute('aria-label', `Dismiss: ${slot.heading || 'alert'}`);
    dismiss.addEventListener('click', () => acknowledge(slot.presentation_id));
    el.append(dismiss);
  }
}

async function acknowledge(presentationId) {
  if (!bridgeHttpBase) return;
  try {
    await fetch(`${bridgeHttpBase}/notifications/acknowledge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ presentation_id: presentationId, client: 'overlay' }),
    });
  } catch { /* unchanged: the alert stays until its own lifetime ends */ }
}

function clearDirector(status = 'hidden') {
  if (directorElement) {
    directorElement.remove();
    directorElement = null;
  }
  if (renderedId) postReceipt(renderedId, status);
  renderedId = null;
}

async function renderDirector(slot) {
  if (!slot || slot.surface !== 'overlay' || display.overlay === false) {
    clearDirector();
    parkWindow();
    return;
  }
  const container = document.getElementById('overlay-container');
  if (renderedId === slot.presentation_id && directorElement) {
    // Same presentation, new sample: update text in place, no reanimation.
    fillAlert(directorElement, slot);
    return;
  }
  clearDirector('hidden');
  directorElement = buildAlert(slot);
  container.appendChild(directorElement);
  renderedId = slot.presentation_id;
  const placed = await presentWindow(directorElement);
  if (renderedId !== slot.presentation_id) return; // superseded while placing
  if (!placed) {
    postReceipt(slot.presentation_id, 'failed', 'window_present_failed');
    return;
  }
  postReceipt(slot.presentation_id, 'rendered');
  requestAnimationFrame(() => {
    const box = directorElement?.getBoundingClientRect();
    if (
      renderedId === slot.presentation_id
      && document.visibilityState === 'visible'
      && box && box.width > 0 && box.height > 0
    ) {
      postReceipt(slot.presentation_id, 'visible');
    }
  });
}

/**
 * Apply a presentation snapshot. Snapshots are idempotent state, so a stale or
 * duplicate one (lower sequence) is ignored.
 */
function applySnapshot(snapshot) {
  if (!snapshot || snapshot.type !== 'notification_presentation') return;
  if (typeof snapshot.seq === 'number' && snapshot.seq < lastSeq && snapshot.owner === owner) return;
  lastSeq = typeof snapshot.seq === 'number' ? snapshot.seq : lastSeq;
  applyDisplay(snapshot.display);
  const previous = owner;
  owner = snapshot.owner === 'director' ? 'director' : 'legacy';
  if (owner === 'director') {
    if (previous !== 'director') clearLegacy();
    directorSlot = snapshot.slot || null;
    renderDirector(directorSlot);
    return;
  }
  // Legacy owns presentation: drop the Director card, and hand an active
  // alert to the legacy queue so ownership changes never erase it.
  const handoff = snapshot.slot;
  clearDirector('hidden');
  directorSlot = null;
  if (previous === 'director' && handoff?.legacy_event && handoff.surface === 'overlay') {
    showBanner(handoff.legacy_event, handoff.value?.amount ?? null);
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Discover the dynamic bridge via Tauri get_bridge_info command and bridge-ready event.
 * Sets bridgeHttpBase and bridgeWsBase. Safe to call before Tauri is ready.
 */
async function discoverBridge() {
  const invoke = window.__TAURI__?.core?.invoke;
  const tauriListen = window.__TAURI__?.event?.listen;

  // Also watch for bridge-ready event in case it fires while we poll
  if (typeof tauriListen === 'function') {
    tauriListen('bridge-ready', (event) => {
      const info = event?.payload;
      if (info?.port && !bridgeHttpBase) {
        bridgeHttpBase = info.httpBase || `http://127.0.0.1:${info.port}`;
        bridgeWsBase = info.wsBase || `ws://127.0.0.1:${info.port}`;
        console.log('[Overlay] Bridge discovered via event:', bridgeWsBase);
        if (!wsConnection || wsConnection.readyState === WebSocket.CLOSED) {
          connectWebSocket();
        }
      }
    }).catch(() => {});
  }

  if (typeof invoke !== 'function') {
    // Browser preview (as the main UI): a loopback port named in the URL.
    const port = Number(new URLSearchParams(window.location.search).get('port'));
    if (Number.isInteger(port) && port > 0 && port < 65536) {
      bridgeHttpBase = `http://127.0.0.1:${port}`;
      bridgeWsBase = `ws://127.0.0.1:${port}`;
    }
    return;
  }

  for (let i = 0; i < 20; i++) {
    try {
      const info = await invoke('get_bridge_info');
      if (info && info.port) {
        bridgeHttpBase = info.httpBase || `http://127.0.0.1:${info.port}`;
        bridgeWsBase = info.wsBase || `ws://127.0.0.1:${info.port}`;
        console.log('[Overlay] Bridge discovered via command:', bridgeWsBase);
        return;
      }
    } catch {
      /* not ready yet */
    }
    await sleep(500);
  }

  console.warn('[Overlay] Bridge discovery timed out.');
}

function handleMessage(message) {
  if (message.type === 'notification_presentation') {
    applySnapshot(message);
    return;
  }
  if (owner !== 'legacy') return; // the Director owns every migrated alert
  if (message.type === 'event' && CRITICAL_EVENTS[message.event_type]) {
    showBanner(message.event_type, extractValue(message.event_type, message.payload));
  }
}

/**
 * Connect to /ws/events and subscribe to critical events.
 */
async function connectWebSocket() {
  if (!bridgeWsBase) {
    console.warn('[Overlay] Bridge not yet discovered; WS connection deferred.');
    return;
  }

  // Avoid duplicate connections
  if (wsConnection && wsConnection.readyState === WebSocket.OPEN) return;

  const wsUrl = `${bridgeWsBase}/ws/events`;

  try {
    wsConnection = new WebSocket(wsUrl);

    wsConnection.onopen = () => {
      wsReconnectDelay = 1000;
      lastSeq = -1;
      console.log('[Overlay] WebSocket connected');
      postReceipt(null, 'ready');
    };

    wsConnection.onmessage = (event) => {
      try {
        handleMessage(JSON.parse(event.data));
      } catch (e) {
        console.error('[Overlay] Failed to parse message:', e);
      }
    };

    wsConnection.onerror = (error) => {
      console.error('[Overlay] WebSocket error:', error);
    };

    wsConnection.onclose = () => {
      // Without the bridge nothing can confirm a Director alert is still
      // current: remove it rather than leave a stale warning on screen.
      clearDirector();
      directorSlot = null;
      parkWindow();
      console.log(`[Overlay] WebSocket closed, reconnecting in ${wsReconnectDelay}ms...`);
      setTimeout(() => {
        wsReconnectDelay = Math.min(wsReconnectDelay * 2, 16000);
        connectWebSocket();
      }, wsReconnectDelay);
    };
  } catch (e) {
    console.error('[Overlay] Failed to connect WebSocket:', e);
    setTimeout(() => {
      wsReconnectDelay = Math.min(wsReconnectDelay * 2, 16000);
      connectWebSocket();
    }, wsReconnectDelay);
  }
}

/**
 * Show or update the status indicator to indicate click-through state.
 */
function updateStatusDot(isClickThrough) {
  // Remove existing status dot
  const existing = document.querySelector('.status-dot');
  if (existing) existing.remove();

  // Create new status indicator badge
  const dot = document.createElement('div');
  dot.className = 'status-dot' + (isClickThrough ? '' : ' grab');
  dot.textContent = isClickThrough ? 'CLICK-THROUGH' : 'INPUT GRABBED';
  document.getElementById('overlay-container')?.appendChild(dot);
  presentWindow(directorElement || document.querySelector('.banner') || dot);

  // Re-render the Director card so it gains or loses its Dismiss control.
  if (directorElement && directorSlot) fillAlert(directorElement, directorSlot);

  // Fade out after 3 seconds if nothing else is on screen
  if (statusDotTimeout) clearTimeout(statusDotTimeout);
  statusDotTimeout = setTimeout(() => {
    const current = document.querySelector('.status-dot');
    if (current) current.remove();
    if (!document.querySelector('.banner') && !directorElement) parkWindow();
  }, 3000);
}


const ANCHOR_CLASS_MAP = {
  'center': 'anchor-center',
  'tl': 'anchor-top-left',
  'tr': 'anchor-top-right',
  'tc': 'anchor-top-center',
  'bl': 'anchor-bottom-left',
  'br': 'anchor-bottom-right',
  // Accept long-form aliases too
  'top-left': 'anchor-top-left',
  'top-right': 'anchor-top-right',
  'top-center': 'anchor-top-center',
  'bottom-left': 'anchor-bottom-left',
  'bottom-right': 'anchor-bottom-right',
};

/**
 * Apply the anchor setting to the overlay container element.
 * Falls back to center if anchor is invalid.
 */
function applyAnchor(anchor) {
  const container = document.getElementById('overlay-container');
  if (!container) return;

  // Remove all existing anchor classes
  for (const cls of Object.values(ANCHOR_CLASS_MAP)) {
    container.classList.remove(cls);
  }

  const cls = ANCHOR_CLASS_MAP[anchor] || 'anchor-center';
  container.classList.add(cls);
}

/**
 * Load overlay settings from the API and apply them.
 */
async function loadOverlaySettings() {
  if (!bridgeHttpBase) return;
  try {
    const response = await fetch(`${bridgeHttpBase}/pillar1/overlay/settings`);
    if (response.ok) {
      const settings = await response.json();
      overlaySettings = { ...overlaySettings, ...settings };
      if (typeof overlaySettings.click_through === 'boolean') {
        clickThrough = overlaySettings.click_through;
      }
      applyAnchor(overlaySettings.anchor);
      // Apply the persisted interaction state natively, not only in this page.
      const invoke = tauriInvoke();
      if (invoke) invoke('set_overlay_click_through', { enabled: clickThrough }).catch(() => {});
      console.log('[Overlay] Settings loaded:', overlaySettings);
    }
  } catch (e) {
    console.warn('[Overlay] Failed to load settings, using defaults:', e);
  }
}

/**
 * Initialize overlay on page load.
 */
document.addEventListener('DOMContentLoaded', async () => {
  // Discover bridge first, then load settings, then connect
  await discoverBridge();
  await loadOverlaySettings();

  connectWebSocket();

  // PB05-05: route-safety poll — at most one interval (lifecycle guard).
  // It only produces a legacy banner; under the Director it does nothing.
  if (routeStalePollHandle) clearInterval(routeStalePollHandle);
  routeStalePollHandle = setInterval(checkRouteStale, 60000);

  // Listen for click-through toggle event from Tauri
  if (window.__TAURI__) {
    const { listen } = window.__TAURI__.event;
    await listen('overlay:click_through_toggled', (event) => {
      clickThrough = event.payload;
      updateStatusDot(clickThrough);
      console.log('[Overlay] Click-through toggled:', clickThrough);
      // Persist the new click-through state so it survives restart
      if (bridgeHttpBase) {
        fetch(`${bridgeHttpBase}/pillar1/overlay/settings`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ click_through: clickThrough }),
        }).catch(e => console.warn('[Overlay] Failed to persist click-through:', e));
      }
    });

    // Banner Test Center previews: local only, never a Director presentation.
    await listen('overlay:show_test_banner', () => {
      console.log('[Overlay] Test banner requested');
      showBanner('OMNICOVAS_TEST', 'READY');
    });

    await listen('overlay:show_named_test_banner', (event) => {
      const eventType = event.payload;
      if (typeof eventType === 'string' && CRITICAL_EVENTS[eventType]) {
        console.log('[Overlay] Named test banner:', eventType);
        showBanner(eventType, 'TEST');
      }
    });
  }

  console.log('[Overlay] Ready. Click-through enabled by default.');
});

// PB05-05 route-safety poll state — module-level for lifecycle safety
let routeStalePollHandle = null;
let _lastRouteNoticeKey = null;

/**
 * Check NavRoute.json freshness via local snapshot endpoint.
 * Shows NAV_ROUTE_STALE banner only when stale/expired with a known destination,
 * and only when the destination+freshness combination changes (deduplication guard).
 * No external calls. Fires at most once per unique stale-state key. Legacy only.
 */
async function checkRouteStale() {
  if (!bridgeHttpBase || owner !== 'legacy') return;
  try {
    const resp = await fetch(bridgeHttpBase + '/navigation/snapshot');
    if (!resp.ok) return;
    const snap = await resp.json();
    const route = snap?.active_route;
    if (!route) return;

    const isStale = route.freshness_label === 'stale' || route.freshness_label === 'expired';
    const hasDest = route.destination && route.destination !== 'Unknown';

    if (!isStale || !hasDest) {
      _lastRouteNoticeKey = null;
      return;
    }

    const noticeKey = route.destination + '|' + route.freshness_label;
    if (noticeKey === _lastRouteNoticeKey) return;
    _lastRouteNoticeKey = noticeKey;
    showBanner('NAV_ROUTE_STALE', route.destination);
  } catch { /* bridge unreachable — no-op */ }
}

function _resetState() {
  clearLegacy();
  if (directorElement) directorElement.remove();
  directorElement = null;
  renderedId = null;
  directorSlot = null;
  owner = 'legacy';
  lastSeq = -1;
  clickThrough = true;
  _lastRouteNoticeKey = null;
  if (routeStalePollHandle) { clearInterval(routeStalePollHandle); routeStalePollHandle = null; }
}

function _setBridgeForTest(httpBase) {
  bridgeHttpBase = httpBase;
}

function _setClickThroughForTest(value) {
  clickThrough = value;
}

export {
  renderBanner,
  showBanner,
  dismissBanner,
  CRITICAL_EVENTS,
  _resetState,
  checkRouteStale,
  extractValue,
  applySnapshot,
  handleMessage,
  _setBridgeForTest,
  _setClickThroughForTest,
};
