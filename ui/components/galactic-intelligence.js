// Galactic Intelligence (GKI-04): automatic briefings, Intel's "Documented here"
// and the Settings panel. ADR 0003: every value is rendered with textContent.
// Briefings are small, dismissible suggestions (UI/UX Blueprint §6): they never
// switch routes or take focus, and the Commander opens the Atlas when they choose.
import {
  BRIEFING_EVENT, CLEARED_EVENT, COMMANDER_EVENTS, MODES, PATHS, ROUTE_LABELS, applyMode, atlasIntent,
  LOCATION_EVENTS, briefingModel, documentedRows, earlierText, isElsewhere, isPast, mergeBriefings, modeOf, preferencesForm, preferencesPayload,
} from '../view-models/galactic-intelligence.js';
import { chronicleIntent } from '../view-models/galactic-historian.js';

const node = (tag, cls = '', text) => {
  const element = document.createElement(tag);
  if (cls) element.className = cls;
  if (text != null) element.textContent = String(text);
  return element;
};

const button = (text, cls, onClick) => {
  const element = node('button', cls, text);
  element.type = 'button';
  element.addEventListener('click', onClick);
  return element;
};

let sequence = 0;

/* ── Briefings ─────────────────────────────────────────────────────────── */

/* Only the newest briefing is shown in full; older ones are compact so the
   stack never grows over the route's own content. */
function briefingCard(model, { onOpen, onDismiss, onChronicle, compact = false }) {
  sequence += 1;
  const titleId = `gi-briefing-title-${sequence}`;
  const card = node('article', compact ? 'gi-briefing gi-briefing--compact' : 'gi-briefing');
  card.setAttribute('aria-labelledby', titleId);
  card.dataset.briefingId = model.id;
  card.append(node('p', 'gi-briefing-kicker', model.kicker));
  if (model.earlier) {
    card.classList.add('gi-briefing--earlier');
    card.append(node('p', 'gi-briefing-earlier', model.earlier));
  }
  const title = node('h2', 'gi-briefing-title', model.title);
  title.id = titleId;
  card.append(title, node('p', 'gi-briefing-headline', model.headline));
  if (compact) {
    card.append(briefingActions(model, { onOpen, onDismiss, onChronicle }));
    return withEscape(card, model, onDismiss);
  }
  model.lines.forEach((line) => card.append(node('p', 'gi-briefing-lead', line)));
  /* These speak of the moment as now; a card about the past leaves them out. */
  if (model.visit && !model.past) card.append(node('p', 'gi-briefing-visit', model.visit));
  if (model.before && !model.past) card.append(node('p', 'gi-briefing-visit', model.before));
  if (model.uncertainty.length) {
    card.append(node('p', 'gi-briefing-uncertain', `Not known: ${model.uncertainty[0]}`));
  }
  if (model.recommendation) {
    const rec = node('div', 'gi-briefing-recommendation');
    rec.append(node('p', '', model.recommendation.text));
    model.recommendation.reasons.forEach((reason) => rec.append(node('p', 'gi-briefing-reason', reason)));
    card.append(rec);
  }
  if (model.details.length || model.sources.length || model.spoilerNote || model.encounterNote) {
    const more = node('details', 'gi-briefing-more');
    more.append(node('summary', '', 'More'));
    const list = node('ul', 'gi-briefing-details');
    model.details.forEach((row) => {
      const item = node('li');
      item.append(node('span', 'gi-briefing-detail-label', row.label), node('span', '', row.text));
      list.append(item);
    });
    more.append(list);
    if (model.spoilerNote) more.append(node('p', 'gi-briefing-note', model.spoilerNote));
    if (model.encounterNote) more.append(node('p', 'gi-briefing-note', model.encounterNote));
    if (model.sources.length) more.append(node('p', 'gi-briefing-sources', `Sources: ${model.sources.join(' · ')}`));
    card.append(more);
  }
  card.append(briefingActions(model, { onOpen, onDismiss, onChronicle }));
  return withEscape(card, model, onDismiss);
}

function briefingActions(model, { onOpen, onDismiss, onChronicle }) {
  const actions = node('div', 'gi-briefing-actions');
  const read = button('Read in Atlas', 'gi-briefing-open', () => onOpen(model));
  read.setAttribute('aria-label', `Read about ${model.title} in the Galactic Atlas`);
  actions.append(read);
  /* GKI-07: the Historian's view and the Commander's own record. */
  if (model.chronicleId && onChronicle) {
    const chronicle = button('Open in Chronicle', 'gi-briefing-chronicle', () => onChronicle(model));
    chronicle.setAttribute('aria-label', `See ${model.title} in your Commander Chronicle`);
    actions.append(chronicle);
  }
  const dismiss = button('Dismiss', 'gi-briefing-dismiss', () => onDismiss(model));
  dismiss.setAttribute('aria-label', `Dismiss briefing about ${model.title}`);
  actions.append(dismiss);
  return actions;
}

function withEscape(card, model, onDismiss) {
  card.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      event.stopPropagation();
      onDismiss(model);
    }
  });
  return card;
}

/* The shell-level stack of active briefings. `shell` is window.Shell; the
   stack listens on window.OmniEvents and asks the backend, never the Journal. */
/* How long a briefing the Director held may still be shown on a rollback: the
   Director's own limit for a waiting knowledge moment (two minutes). */
const HELD_FRESH_MS = 120000;
const LOCATE_DELAY_MS = 400;

export function createBriefingStack({ fetchJson, postJson, shell, events }) {
  const root = node('aside', 'gi-briefings');
  root.setAttribute('aria-label', 'Galactic Intelligence briefings');
  const live = node('div', 'gi-briefings-live');
  live.setAttribute('aria-live', 'polite');
  live.setAttribute('aria-relevant', 'additions');
  root.append(live);
  /* Narrow windows show one compact card; this says the others are not lost. */
  const waiting = node('p', 'gi-briefings-waiting');
  waiting.hidden = true;
  root.append(waiting);
  let briefings = [];
  /* The Commander Context's current places (GKI-08), or null before any answer. */
  let presence = null;
  let locating = null;
  const dismissed = new Set();
  /* NHI-03/04: while the Notification Director owns presentation it decides
     when a briefing may appear (e.g. not mid-combat). Arrivals wait here until
     the Director releases them; the backend still holds every briefing, so a
     refresh or the Intel workstation always shows them. */
  const held = new Map();
  const directorOwns = () => document.documentElement.dataset.notificationOwner === 'director';

  /* While cards show, the route content keeps the stack's height free at its
     foot, so every control can be scrolled clear of it (GKI-07 corrections). */
  function reserve() {
    const open = root.isConnected && !root.hidden;
    const height = open ? Math.ceil(root.getBoundingClientRect().height) : 0;
    document.body.classList.toggle('gi-briefings-open', open);
    document.documentElement.style.setProperty('--gi-briefings-height', `${height}px`);
  }
  if (typeof ResizeObserver === 'function') new ResizeObserver(reserve).observe(root);

  function render() {
    const focused = root.contains(document.activeElement)
      ? document.activeElement.closest('.gi-briefing')?.dataset.briefingId
      : null;
    const shown = briefings.filter((row) => !dismissed.has(row.briefing_id));
    const cards = shown
      .map((row) => {
        const model = briefingModel(row);
        if (model) {
          model.earlier = earlierText(row, presence);
          model.past = isPast(row, presence);
        }
        return model;
      })
      .filter(Boolean)
      .map((model, index) => briefingCard(model, {
        onOpen: open, onDismiss: dismiss, onChronicle: chronicle, compact: index > 0,
      }));
    live.replaceChildren(...cards);
    const others = cards.length - 1;
    waiting.hidden = others < 1;
    waiting.textContent = others < 1 ? '' : `${others} more waiting. Dismiss this one to read the next.`;
    root.hidden = cards.length === 0;
    reserve();
    if (focused) root.querySelector(`[data-briefing-id="${CSS.escape(focused)}"] .gi-briefing-open`)?.focus();
  }

  /* Ask where the Commander is now. A card is redrawn only if its wording would
     change, so an open "More" and the live region stay undisturbed. */
  async function locate() {
    const before = briefings.map((row) => earlierText(row, presence)).join('|');
    let answer = null;
    try {
      answer = (await fetchJson(PATHS.context))?.presence || null;
    } catch (error) {
      console.warn('Commander location unavailable for briefings:', error);
    }
    presence = answer;
    if (briefings.map((row) => earlierText(row, presence)).join('|') !== before) render();
  }

  /* The Journal line reaches this page before the state handlers finish, so the
     context is read just after it. */
  function locateSoon() {
    clearTimeout(locating);
    locating = setTimeout(locate, LOCATE_DELAY_MS);
  }

  async function refresh() {
    try {
      const payload = await fetchJson(PATHS.briefings);
      briefings = mergeBriefings([], payload?.briefings || []);
    } catch (error) {
      console.warn('Galactic Intelligence briefings unavailable:', error);
      briefings = [];
    }
    render();
    await locate();
  }

  function add(briefing) {
    if (!briefing?.briefing_id || dismissed.has(briefing.briefing_id)) return;
    briefings = mergeBriefings(briefings, [briefing]);
    render();
    locateSoon();
  }

  function arrive(briefing) {
    if (!briefing?.briefing_id) return;
    if (!directorOwns()) {
      add(briefing);
      return;
    }
    held.set(briefing.briefing_id, briefing);
    while (held.size > 20) held.delete(held.keys().next().value);
  }

  /* Called by the attention lane when the Director presents this briefing. */
  function release(briefingId) {
    const briefing = held.get(briefingId);
    if (briefing) held.delete(briefingId);
    const known = briefing || briefings.find((row) => row.briefing_id === briefingId);
    if (!known || dismissed.has(briefingId)) return false;
    add(known);
    return true;
  }

  /* Presentation went back to the legacy path: show what was waiting, but only
     briefings still about the present (GKI-08). An older one would read as a
     new arrival; it stays in Intel and Galactic Intelligence for reading. */
  function releaseHeld(now = Date.now()) {
    const queued = [...held.values()];
    held.clear();
    queued.filter((briefing) => {
      const observed = Date.parse(briefing.observed_at || briefing.created_at || '');
      return Number.isFinite(observed) && now - observed <= HELD_FRESH_MS
        && !isElsewhere(briefing, presence);
    }).forEach(add);
  }

  async function dismiss(model, { moveFocus = true } = {}) {
    const hadFocus = moveFocus && root.contains(document.activeElement);
    dismissed.add(model.id);
    briefings = briefings.filter((row) => row.briefing_id !== model.id);
    render();
    if (hadFocus) {
      (root.querySelector('.gi-briefing-open') || document.getElementById('content-area'))?.focus?.();
    }
    try {
      await postJson(PATHS.dismiss(model.id));
    } catch (error) {
      console.warn('Galactic Intelligence dismissal not saved:', error);
    }
  }

  function open(model) {
    const route = (window.location.hash || '#/dashboard').replace(/^#/, '').split('?')[0] || '/dashboard';
    shell?.startRouteTransfer?.(atlasIntent(model.subjectId, model.title, {
      route,
      sectionLabel: 'Briefing',
      reason: 'Read the documented record behind this briefing.',
    }));
    /* The full record is now on screen; the card would only cover it. The
       Atlas owns focus from here, so the stack does not move it. */
    dismiss(model, { moveFocus: false });
  }

  function chronicle(model) {
    const route = (window.location.hash || '#/dashboard').replace(/^#/, '').split('?')[0] || '/dashboard';
    shell?.startRouteTransfer?.(chronicleIntent(model.chronicleId, model.title, {
      route,
      package: 'Galactic Intelligence',
      sectionId: '',
      sectionLabel: 'Briefing',
      reason: 'The Historian and your own record for this place.',
      returnLabel: `Back to ${ROUTE_LABELS[route] || 'previous view'}`,
      returnTarget: null,
    }));
    dismiss(model, { moveFocus: false });
  }

  events?.addEventListener('event', (event) => {
    const message = event.detail || {};
    const type = message.event_type || message.event;
    if (type === BRIEFING_EVENT) arrive(message.payload);
    if (LOCATION_EVENTS.includes(type)) locateSoon();
    /* Briefings belong to one commander. When the active commander changes, or
       one is forgotten, show only what the backend holds for the current one. */
    if (type === CLEARED_EVENT || COMMANDER_EVENTS.includes(type)) refresh();
  });
  events?.addEventListener('bridge-connected', refresh);
  root.hidden = true;
  return {
    element: root, refresh, add, release, releaseHeld, dismiss,
    get briefings() { return briefings; },
    get held() { return [...held.keys()]; },
  };
}

/* ── Intel: Documented here ────────────────────────────────────────────── */

export function createDocumentedHere(documented, { scope, onOpen, onChronicle = null }) {
  const rows = documentedRows(documented, scope);
  if (!rows.length) return null;
  const section = node('section', 'gi-documented');
  section.setAttribute('aria-labelledby', `gi-documented-${scope}`);
  const heading = node('h3', 'gi-documented-title', 'Documented here');
  heading.id = `gi-documented-${scope}`;
  section.append(
    heading,
    node('p', 'gi-documented-lead', scope === 'station'
      ? 'Source-backed history for the station you are docked at.'
      : 'Source-backed places and history for this system. A place listed here is documented, not visited.'),
  );
  const list = node('ul', 'gi-documented-list');
  rows.forEach((row) => {
    const item = node('li', 'gi-documented-item');
    item.dataset.entityId = row.id;
    const open = button(row.name, 'gi-documented-open', () => onOpen(row));
    open.setAttribute('aria-label', `${row.name}: open in the Galactic Atlas`);
    item.append(open, node('span', 'gi-documented-kind', row.kind));
    if (row.significance) item.append(node('p', 'gi-documented-text', row.significance));
    item.append(node('p', 'gi-documented-reason', row.visit || row.reason));
    if (row.uncertainty.length) item.append(node('p', 'gi-documented-uncertain', `Not known: ${row.uncertainty[0]}`));
    if (row.associations.length) {
      const links = node('ul', 'gi-documented-associations');
      row.associations.forEach((text) => links.append(node('li', '', text)));
      item.append(links);
    }
    list.append(item);
  });
  section.append(list);
  /* GKI-07: who and what is connected, and whether you have been here. */
  if (onChronicle) {
    const historian = button('People, history and your record', 'ocv-btn-ghost gi-documented-chronicle', onChronicle);
    historian.setAttribute('aria-label', 'Open the Historian and your Commander Chronicle');
    section.append(historian);
  }
  return section;
}

/* ── Settings ──────────────────────────────────────────────────────────── */

export function createIntelligenceSettings({ fetchJson, sendJson }) {
  const root = node('section', 'gi-settings');
  root.setAttribute('aria-labelledby', 'gi-settings-heading');
  let form = null;
  let status = null;

  function field(labelText, input, help) {
    const wrap = node('div', 'gi-settings-field');
    const label = node('label', 'gi-settings-label');
    label.append(input, node('span', '', labelText));
    wrap.append(label);
    if (help) wrap.append(node('p', 'gi-settings-help', help));
    return wrap;
  }

  function checkbox(name, checked, onChange) {
    const input = node('input');
    input.type = 'checkbox';
    input.name = name;
    input.checked = checked;
    input.addEventListener('change', () => onChange(input.checked));
    return input;
  }

  function render() {
    const heading = node('h2', '', 'Galactic Intelligence');
    heading.id = 'gi-settings-heading';
    root.replaceChildren(heading);
    root.append(node('p', '', 'Short, source-backed briefings about documented places when the Journal shows you arriving or docking. The Galactic Atlas and Intel always stay available to read yourself.'));
    if (!form) {
      root.append(node('p', 'gi-settings-status', status || 'Loading preferences…'));
      return;
    }
    if (form.forgotten) {
      root.append(node('p', 'gi-settings-scope',
        'This commander was forgotten in Privacy. Galactic Intelligence keeps nothing for them, so settings cannot be saved and nothing is announced.'));
    } else {
      root.append(node('p', 'gi-settings-scope', form.commanderKnown
        ? 'These settings apply to the commander OmniCOVAS currently observes. Each commander keeps their own.'
        : 'No commander observed yet. These settings become the starting point for each commander.'));
    }
    /* GKI-07: Quiet, Discoverer and Storyteller as presets over the fields
       below. Choosing one changes the form only; nothing is saved until Save. */
    const modes = node('fieldset', 'gi-settings-group gi-settings-modes');
    modes.append(node('legend', '', 'Storytelling mode'));
    const current = modeOf(form);
    modes.append(node('p', 'gi-settings-help', `Current mode: ${MODES[current].label}. A preset sets the switches below; you can still change each one.`));
    const presetRow = node('div', 'gi-settings-presets');
    Object.entries(MODES).forEach(([id, mode]) => {
      const preset = button(mode.label, 'ocv-btn-ghost gi-settings-preset', () => {
        applyMode(form, id);
        status = `${mode.label} selected. Save to keep it.`;
        render();
        root.querySelector(`.gi-settings-preset[data-mode="${id}"]`)?.focus();
      });
      preset.dataset.mode = id;
      preset.setAttribute('aria-pressed', String(current === id));
      preset.title = mode.help;
      presetRow.append(preset);
    });
    modes.append(presetRow, node('p', 'gi-settings-help', MODES[current].help));
    root.append(modes);

    root.append(field('Enable automatic Galactic Intelligence', checkbox('gi_enabled', form.enabled, (v) => { form.enabled = v; }),
      'Off by default. When off, nothing is announced automatically. When on, briefings appear in this window only, '
        + 'never in the in-game overlay, which is kept for critical ship alerts.'));

    const content = node('fieldset', 'gi-settings-group');
    content.append(node('legend', '', 'What briefings may include'));
    content.append(node('p', 'gi-settings-help',
      'These choose what an automatic briefing may say; on their own they show nothing. '
        + 'The Atlas and your Chronicle always show everything when you open them.'));
    form.categories.forEach((category) => {
      content.append(field(category.label, checkbox(`gi_content_${category.id}`, category.on, (v) => { category.on = v; }), category.help));
    });
    root.append(content);

    const historian = node('fieldset', 'gi-settings-group');
    historian.append(node('legend', '', 'Historian'));
    historian.append(
      field('Arrival briefings', checkbox('gi_arrival_briefings', form.arrivalBriefings, (v) => { form.arrivalBriefings = v; }),
        'When the Journal shows you docking at a documented starport, entering a documented system or landing at a documented site. Off: only documented sites nearby are suggested, if Discoveries are on.'),
      field('Only places with no earlier record of you', checkbox('gi_first_visit_only', form.firstVisitOnly, (v) => { form.firstVisitOnly = v; }),
        'Skips places your Chronicle already has you at. An empty record is not read as "never visited".'),
    );
    root.append(historian);

    const frequency = node('fieldset', 'gi-settings-group');
    frequency.append(node('legend', '', 'How often'));
    form.frequencies.forEach((option) => {
      const radio = node('input');
      radio.type = 'radio';
      radio.name = 'gi_frequency';
      radio.value = option.id;
      radio.checked = form.frequency === option.id;
      radio.addEventListener('change', () => { if (radio.checked) form.frequency = option.id; });
      frequency.append(field(option.label, radio, option.help));
    });
    root.append(frequency);

    root.append(
      field('Quiet mode', checkbox('gi_quiet', form.quietMode, (v) => { form.quietMode = v; }),
        'Only briefings tied to an active Engineering build shortfall. History and lore wait until you open them.'),
      field('Spoiler protection', checkbox('gi_spoilers', form.spoilerProtection, (v) => { form.spoilerProtection = v; }),
        'Keeps story revelations out of automatic briefings. The Atlas still shows everything when you open it.'),
    );
    const actions = node('div', 'gi-settings-actions');
    actions.append(
      button('Save Galactic Intelligence settings', 'gi-settings-save', save),
      button('Restore defaults', 'gi-settings-reset', reset),
    );
    if (form.forgotten) actions.querySelectorAll('button').forEach((b) => { b.disabled = true; });
    root.append(actions);
    const message = node('p', 'gi-settings-status', status || '');
    message.setAttribute('role', 'status');
    root.append(message);
  }

  async function load() {
    try {
      form = preferencesForm(await fetchJson(PATHS.preferences));
      status = null;
    } catch (error) {
      console.warn('Galactic Intelligence preferences unavailable:', error);
      form = null;
      status = 'Galactic Intelligence settings are unavailable right now.';
    }
    render();
  }

  async function save() {
    try {
      form = preferencesForm(await sendJson('PUT', PATHS.preferences, preferencesPayload(form)));
      status = 'Saved.';
    } catch (error) {
      console.warn('Galactic Intelligence preferences not saved:', error);
      status = 'Not saved. Your previous settings are unchanged.';
    }
    render();
    root.querySelector('.gi-settings-save')?.focus();
  }

  async function reset() {
    try {
      form = preferencesForm(await sendJson('POST', PATHS.reset));
      status = 'Defaults restored: automatic intelligence is off.';
    } catch (error) {
      console.warn('Galactic Intelligence preferences not reset:', error);
      status = 'Defaults could not be restored.';
    }
    render();
    root.querySelector('.gi-settings-reset')?.focus();
  }

  render();
  return { element: root, load, get form() { return form; } };
}

/* Mount the briefing stack once, at the frame level, for every route. */
export function mountBriefings({ shell = window.Shell, events = window.OmniEvents, host = document.body } = {}) {
  if (host.querySelector('.gi-briefings')) return null;
  const base = () => shell?.httpBase;
  const stack = createBriefingStack({
    shell,
    events,
    fetchJson: async (path) => {
      if (!base()) return { briefings: [] };
      const response = await fetch(`${base()}${path}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    },
    postJson: async (path) => {
      if (!base()) return null;
      const response = await fetch(`${base()}${path}`, { method: 'POST' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    },
  });
  host.append(stack.element);
  if (base()) stack.refresh();
  return stack;
}
