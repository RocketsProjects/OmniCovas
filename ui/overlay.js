/**
 * OmniCOVAS Overlay — Critical Event Banner Handler
 *
 * Subscribes to the /ws/events endpoint and renders critical events
 * as transient banners. Handles banner queue, priority preemption, and
 * auto-dismiss timers.
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

/**
 * Show a banner with auto-dismiss. Preempt lower-priority banners.
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

  if (currentBanner && config.priority < currentBanner.config.priority) {
    // Preempt: clear current and show new
    clearTimeout(currentBanner.timeoutId);
    renderBanner(banner);
    currentBanner = banner;
  } else if (!currentBanner) {
    // No banner active: show immediately
    renderBanner(banner);
    currentBanner = banner;
  } else {
    // Lower priority: queue
    bannerQueue.push(banner);
  }

  currentBanner.timeoutId = setTimeout(() => {
    dismissBanner();
  }, config.duration);
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
  valueEl.textContent =
    typeof banner.value === 'number'
      ? banner.value.toFixed(0) + '%'
      : (banner.value == null ? '' : String(banner.value));

  bannerEl.appendChild(sourceEl);
  bannerEl.appendChild(iconEl);
  bannerEl.appendChild(labelEl);
  bannerEl.appendChild(valueEl);

  container.appendChild(bannerEl);
}

/**
 * Dismiss current banner and show next in queue if available.
 */
function dismissBanner() {
  if (!currentBanner) return;

  const container = document.getElementById('overlay-container');
  const banner = container.querySelector('.banner');
  if (banner) banner.remove();

  currentBanner = null;

  if (bannerQueue.length > 0) {
    const next = bannerQueue.shift();
    showBanner(next.eventType, next.value);
  } else if (window.__TAURI__) {
    const invoke = window.__TAURI__?.core?.invoke;
    if (typeof invoke === 'function') invoke('hide_overlay').catch(() => {});
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

  if (typeof invoke !== 'function') return;

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
      console.log('[Overlay] WebSocket connected');
    };

    wsConnection.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        if (message.type === 'event' && CRITICAL_EVENTS[message.event_type]) {
          // Extract the most relevant value from the payload
          const value = message.payload.hull_health
            || message.payload.fuel_percent
            || message.payload.heat_level
            || message.payload.module_health
            || (message.payload.shields_down !== undefined ? 'DOWN' : '—');

          showBanner(message.event_type, value);

          // Show the overlay window when a critical event fires
          if (window.__TAURI__) {
            const invoke = window.__TAURI__?.core?.invoke;
            if (typeof invoke === 'function') {
              invoke('show_overlay').catch(e =>
                console.error('[Overlay] Failed to show overlay:', e)
              );
            }
          }
        }
      } catch (e) {
        console.error('[Overlay] Failed to parse message:', e);
      }
    };

    wsConnection.onerror = (error) => {
      console.error('[Overlay] WebSocket error:', error);
    };

    wsConnection.onclose = () => {
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
  document.body.appendChild(dot);

  // Show the overlay window so the indicator is visible
  if (window.__TAURI__) {
    const invoke = window.__TAURI__?.core?.invoke;
    if (typeof invoke === 'function') {
      invoke('show_overlay').catch(e =>
        console.error('[Overlay] Failed to show overlay for feedback:', e)
      );
    }
  }

  // Fade out after 3 seconds if no banner is active
  if (statusDotTimeout) clearTimeout(statusDotTimeout);
  statusDotTimeout = setTimeout(() => {
    const dot = document.querySelector('.status-dot');
    if (dot && !document.querySelector('.banner')) {
      dot.remove();
      // If no banner, hide the window again to stay hidden-by-default
      if (window.__TAURI__) {
        const invoke = window.__TAURI__?.core?.invoke;
        if (typeof invoke === 'function') invoke('hide_overlay').catch(() => {});
      }
    }
  }, 3000);
}


const ANCHOR_CLASS_MAP = {
  'center': 'anchor-center',
  'tl': 'anchor-top-left',
  'tr': 'anchor-top-right',
  'bl': 'anchor-bottom-left',
  'br': 'anchor-bottom-right',
  // Accept long-form aliases too
  'top-left': 'anchor-top-left',
  'top-right': 'anchor-top-right',
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

  // PB05-05: route-safety poll — at most one interval (lifecycle guard)
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
 * No external calls. Fires at most once per unique stale-state key.
 */
async function checkRouteStale() {
  if (!bridgeHttpBase) return;
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
  if (currentBanner?.timeoutId) clearTimeout(currentBanner.timeoutId);
  currentBanner = null;
  bannerQueue = [];
  _lastRouteNoticeKey = null;
  if (routeStalePollHandle) { clearInterval(routeStalePollHandle); routeStalePollHandle = null; }
}

export { renderBanner, showBanner, dismissBanner, CRITICAL_EVENTS, _resetState, checkRouteStale };
