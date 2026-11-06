// NHI-03/04 desktop attention lane: the main window's side of the single
// attention slot owned by the Notification Director.
//
// It renders the Director's slot only when that slot's surface is the desktop:
// optional Glance Notices (by Commander preference) and critical alerts when the
// in-game overlay is off or failed to display. A Galactic Intelligence briefing
// is handed to the existing briefing stack instead of being drawn twice. It
// never switches routes or moves focus; ADR 0003: all text via textContent.
//
// Every rendered/visible/hidden state is reported to the Director as a delivery
// receipt; acknowledgement dismisses the presentation, never the condition.

const node = (tag, cls = '', text) => {
  const element = document.createElement(tag);
  if (cls) element.className = cls;
  if (text != null) element.textContent = String(text);
  return element;
};

const DESTINATIONS = {
  mining: { route: '/operations', label: 'Review prospector report' },
  exploration: { route: '/operations', label: 'Review in Operations' },
  engineering: { route: '/engineering', label: 'Review in Engineering' },
  'activity-log': { route: '/activity-log', label: 'Review in Activity Log' },
};

export function createAttentionLane({ shell = window.Shell, events = window.OmniEvents, briefings = () => window.OmniGalacticIntelligence } = {}) {
  const root = node('aside', 'ocv-attention');
  root.setAttribute('aria-label', 'OmniCOVAS notices');
  // Stable live regions: assertive for alerts, polite for notices. Messages
  // are announced when they change; focus never moves on arrival.
  const urgent = node('div', 'ocv-attention-live');
  urgent.setAttribute('role', 'alert');
  urgent.setAttribute('aria-live', 'assertive');
  urgent.setAttribute('aria-atomic', 'true');
  const polite = node('div', 'ocv-attention-live');
  polite.setAttribute('role', 'status');
  polite.setAttribute('aria-live', 'polite');
  polite.setAttribute('aria-atomic', 'true');
  root.append(urgent, polite);
  root.hidden = true;

  const state = { owner: 'legacy', slot: null, renderedId: null, seq: -1 };
  const base = () => shell?.httpBase;

  /* While a notice shows, the route keeps its height free at the foot (as the
     briefing stack does), so every control can be scrolled clear of it. */
  function reserve() {
    const open = root.isConnected && !root.hidden;
    const height = open ? Math.ceil(root.getBoundingClientRect().height) : 0;
    document.body.classList.toggle('ocv-attention-open', open);
    document.documentElement.style.setProperty('--ocv-attention-height', `${height}px`);
  }
  if (typeof ResizeObserver === 'function') new ResizeObserver(reserve).observe(root);

  async function post(path, body) {
    if (!base()) return null;
    try {
      const response = await fetch(`${base()}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      return response.ok ? response.json() : null;
    } catch {
      return null;
    }
  }

  const receipt = (presentationId, status, detail = '') =>
    post('/notifications/receipts', { presentation_id: presentationId, client: 'desktop', status, detail });

  function clear(status = 'hidden') {
    const had = state.renderedId;
    urgent.replaceChildren();
    polite.replaceChildren();
    root.hidden = true;
    reserve();
    state.renderedId = null;
    if (had) receipt(had, status);
  }

  async function acknowledge(slot) {
    const previous = document.activeElement;
    const hadFocus = root.contains(previous);
    await post('/notifications/acknowledge', { presentation_id: slot.presentation_id, client: 'desktop' });
    // Return focus to a stable place only if the Commander was in the card.
    if (hadFocus) document.getElementById('content-area')?.focus?.({ preventScroll: true });
  }

  function review(slot) {
    const target = DESTINATIONS[slot.destination];
    if (!target) return;
    const route = (window.location.hash || '#/dashboard').replace(/^#/, '').split('?')[0] || '/dashboard';
    shell?.startRouteTransfer?.({
      originRoute: route,
      originPackage: 'Notifications',
      targetRoute: target.route,
      targetEntityId: slot.destination === 'mining' ? 'mining' : undefined,
      targetSectionId: slot.destination === 'mining' ? 'operations-mining-workspace' : undefined,
      targetLabel: slot.heading,
      reason: 'Review what this notice was about.',
      returnLabel: 'Back',
    });
  }

  function card(slot) {
    const critical = slot.level === 'interrupt';
    const el = node('section', `ocv-attention-card ocv-attention-card--${slot.severity || 'notice'}`);
    el.dataset.presentationId = slot.presentation_id;
    el.setAttribute('aria-label', `${slot.label || 'OmniCOVAS'}: ${slot.heading || ''}`);
    el.append(
      node('p', 'ocv-attention-label', slot.label || 'OmniCOVAS'),
      node('p', 'ocv-attention-heading', slot.heading || ''),
      node('p', 'ocv-attention-body', slot.body || ''),
    );
    if (critical) {
      el.append(node('p', 'ocv-attention-note', 'Shown here because the in-game overlay is off or unavailable.'));
    }
    const actions = node('div', 'ocv-attention-actions');
    const target = DESTINATIONS[slot.destination];
    if (!critical && target) {
      const open = node('button', 'ocv-btn-ghost ocv-attention-review', target.label);
      open.type = 'button';
      open.addEventListener('click', () => review(slot));
      actions.append(open);
    }
    const dismiss = node('button', 'ocv-btn-ghost ocv-attention-dismiss', critical ? 'Acknowledge' : 'Dismiss');
    dismiss.type = 'button';
    dismiss.setAttribute('aria-label', `${critical ? 'Acknowledge' : 'Dismiss'}: ${slot.heading || 'notice'}`);
    dismiss.addEventListener('click', () => acknowledge(slot));
    actions.append(dismiss);
    el.append(actions);
    el.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        acknowledge(slot);
      }
    });
    return el;
  }

  function render(slot) {
    if (!slot || slot.surface !== 'desktop' || state.owner !== 'director') {
      clear();
      return;
    }
    if (slot.subject && slot.category === 'knowledge') {
      // The briefing stack owns briefing cards; the Director only times them.
      clear();
      const shown = briefings()?.release?.(slot.subject);
      receipt(slot.presentation_id, shown ? 'rendered' : 'failed', shown ? 'briefing_stack' : 'briefing_unavailable');
      if (shown) receipt(slot.presentation_id, 'visible', 'briefing_stack');
      return;
    }
    if (state.renderedId === slot.presentation_id) {
      const existing = root.querySelector('.ocv-attention-card');
      if (existing) {
        existing.querySelector('.ocv-attention-body').textContent = slot.body || '';
        return;
      }
    }
    if (state.renderedId) receipt(state.renderedId, 'hidden');
    const region = slot.live === 'assertive' ? urgent : polite;
    (region === urgent ? polite : urgent).replaceChildren();
    region.replaceChildren(card(slot));
    root.hidden = false;
    reserve();
    state.renderedId = slot.presentation_id;
    receipt(slot.presentation_id, 'rendered');
    requestAnimationFrame(() => {
      const box = region.firstChild?.getBoundingClientRect?.();
      if (state.renderedId === slot.presentation_id && document.visibilityState === 'visible' && box?.height > 0) {
        receipt(slot.presentation_id, 'visible');
      }
    });
  }

  function apply(snapshot) {
    if (!snapshot || snapshot.type !== 'notification_presentation') return;
    const previous = state.owner;
    state.owner = snapshot.owner === 'director' ? 'director' : 'legacy';
    state.slot = snapshot.slot || null;
    state.seq = snapshot.seq ?? state.seq;
    document.documentElement.dataset.notificationOwner = state.owner;
    if (previous === 'director' && state.owner === 'legacy') briefings()?.releaseHeld?.();
    render(state.slot);
  }

  async function refresh() {
    if (!base()) return;
    try {
      const response = await fetch(`${base()}/notifications/presentation`);
      if (response.ok) apply(await response.json());
    } catch { /* bridge not ready; the next snapshot arrives over the socket */ }
  }

  document.addEventListener('visibilitychange', () => {
    if (state.renderedId && document.visibilityState === 'visible') receipt(state.renderedId, 'visible');
  });
  events?.addEventListener('notification', (event) => apply(event.detail));
  events?.addEventListener('bridge-connected', refresh);
  events?.addEventListener('bridge-disconnected', () => {
    // Without the bridge nothing confirms the slot is current.
    state.owner = 'legacy';
    clear();
  });

  return {
    element: root,
    apply,
    refresh,
    get owner() { return state.owner; },
    get slot() { return state.slot; },
  };
}

export function mountAttentionLane({ host = document.body, ...options } = {}) {
  if (host.querySelector('.ocv-attention')) return null;
  const lane = createAttentionLane(options);
  host.append(lane.element);
  lane.refresh();
  return lane;
}
