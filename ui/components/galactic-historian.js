// Living Galactic Historian and Commander Chronicle (GKI-07): the Intel
// Chronicle workspace, its "Here and now" Historian card, and the Atlas
// "Your record" card. ADR 0003: every value is rendered with textContent.
// A place's evidence is always labelled by class, and an empty record reads
// "Unknown", never "not visited". Nothing here presents itself: it is read
// when the Commander opens it.
import {
  CLEARED_EVENT, COMMANDER_EVENTS, EVIDENCE, FILTERS, PATHS, RECORDED_EVENT,
  atlasIntent, chronicleModel, contextModel, expeditionIntent, planIntent,
  subjectRecordModel,
} from '../view-models/galactic-historian.js';

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
const uid = (prefix) => { sequence += 1; return `${prefix}-${sequence}`; };

/* Entity ids reach an attribute selector only escaped (Intel's own rule). */
const escapeAttr = (value) => (typeof CSS !== 'undefined' && typeof CSS.escape === 'function'
  ? CSS.escape(String(value))
  : String(value).replace(/["\\]/g, '\\$&'));

/* An evidence class as a badge whose shape differs as well as its colour. */
export function evidenceBadge(kind, label) {
  const known = EVIDENCE[kind] ? kind : 'unknown';
  const badge = node('span', `gh-evidence gh-evidence-${known}`);
  badge.append(node('span', 'gh-evidence-glyph', EVIDENCE[known].glyph), node('span', '', label || EVIDENCE[known].label));
  badge.firstChild.setAttribute('aria-hidden', 'true');
  return badge;
}

function heading(tag, text, cls = '') {
  const element = node(tag, cls, text);
  element.id = uid('gh-heading');
  return element;
}

function section(cls, title, level = 'h4') {
  const wrap = node('section', `gh-card ${cls}`);
  const head = heading(level, title);
  wrap.setAttribute('aria-labelledby', head.id);
  wrap.append(head);
  return wrap;
}

function lines(list, cls = 'gh-line') {
  return list.map((text) => node('p', cls, text));
}

/* ── Here and now ─────────────────────────────────────────────────────── */

const CONTEXT_STATES = {
  loading: 'Reading the archive for where you are…',
  error: 'The Historian could not read your location right now.',
  unavailable: 'The bundled galactic knowledge is not available in this build.',
  no_location: 'No location observed yet. Jump, dock or land, and the Historian will tell you what is documented there.',
  nothing_documented: 'Nothing is documented where you are. That is normal: the Atlas covers notable places only, and nothing is invented about the rest.',
};

export function createHistorianCard(model, handlers = {}) {
  const card = node('section', 'gh-here');
  const title = heading('h3', 'Here and now', 'gh-here-title');
  card.setAttribute('aria-labelledby', title.id);
  card.append(node('p', 'gh-kicker', 'Historian · where you are'), title, node('p', 'gh-where', model.whereLine || ''));
  if (model.state !== 'available') {
    card.append(node('p', 'gh-muted', CONTEXT_STATES[model.state] || CONTEXT_STATES.error));
    return card;
  }
  const subject = model.subject;
  const dossier = node('article', 'gh-dossier');
  const name = node('h4', 'gh-dossier-title', subject.name);
  name.id = uid('gh-dossier');
  dossier.setAttribute('aria-labelledby', name.id);
  dossier.append(node('p', 'gh-eyebrow', [subject.kind, subject.period].filter(Boolean).join(' · ')), name);
  const here = model.here[0];
  if (here) {
    const record = node('div', 'gh-record-line');
    record.append(evidenceBadge(here.record.kind, here.record.label));
    lines(here.record.lines.length ? here.record.lines : [here.record.note]).forEach((p) => record.append(p));
    dossier.append(record);
  }
  if (subject.significance) dossier.append(node('p', 'gh-significance', subject.significance));
  dossier.append(node('p', 'gh-summary', subject.summary));
  subject.topics.slice(0, 3).forEach((topic) => {
    const block = topic.id === 'history' ? node('div', 'gh-topic') : node('details', 'gh-topic');
    if (topic.id === 'history') block.append(node('h5', '', topic.label));
    else block.append(node('summary', '', `${topic.label} (${topic.claims.length})`));
    const list = node('ul', 'gh-claims');
    topic.claims.slice(0, topic.id === 'history' ? 3 : 6).forEach((claim) => list.append(node('li', '', claim.text)));
    block.append(list);
    dossier.append(block);
  });
  if (subject.spoilersHidden) {
    dossier.append(node('p', 'gh-muted', `${subject.spoilersHidden} story revelation${subject.spoilersHidden === 1 ? '' : 's'} held back by spoiler protection.`));
    if (handlers.reveal) dossier.append(button('Show spoilers here', 'ocv-btn-ghost gh-reveal', handlers.reveal));
  }
  if (subject.practical.length) {
    const practical = node('div', 'gh-practical');
    practical.append(node('h5', '', 'Practical (kept apart from the history)'));
    subject.practical.forEach((row) => practical.append(node('p', 'gh-line', `${row.activity.name}${row.materials.length ? `: ${row.materials.join(', ')}` : ''}. No yields are promised.`)));
    dossier.append(practical);
  }
  const actions = node('div', 'gh-actions');
  if (handlers.openAtlas) {
    const read = button('Read in Atlas', 'ocv-btn gh-open-atlas', () => handlers.openAtlas(subject.id, subject.name));
    read.setAttribute('aria-label', `Read about ${subject.name} in the Galactic Atlas`);
    actions.append(read);
  }
  if (handlers.save) actions.append(button('Save to Chronicle', 'ocv-btn-ghost gh-save', () => handlers.save({ type: 'atlas', id: subject.id })));
  dossier.append(actions);
  card.append(dossier);

  const side = node('div', 'gh-here-side');
  if (model.groups.length || model.currentFaction) {
    const people = section('gh-connections', 'People, factions and events');
    model.groups.forEach((group) => {
      people.append(node('h5', '', group.label));
      const list = node('ul', 'gh-list');
      group.rows.forEach((row) => {
        const item = node('li', `gh-connection${row.historical_only ? ' gh-historical' : ''}`);
        if (handlers.openAtlas) {
          const link = button(row.entity.name, 'gh-link', () => handlers.openAtlas(row.entity.id, row.entity.name));
          link.dataset.entityId = row.entity.id;
          item.append(link, node('span', 'gh-connection-text', row.detail));
        } else {
          item.append(node('span', 'gh-connection-text', row.text));
        }
        list.append(item);
      });
      people.append(list);
    });
    if (model.currentFaction) people.append(node('p', 'gh-current', model.currentFaction));
    side.append(people);
  }
  if (model.nearby.length) {
    const nearby = section('gh-nearby', 'Documented nearby');
    const list = node('ul', 'gh-list');
    model.nearby.forEach((row) => {
      const item = node('li', 'gh-nearby-item');
      item.dataset.entityId = row.id;
      const head = node('div', 'gh-next-head');
      head.append(evidenceBadge(row.record.kind, row.record.label));
      head.append(handlers.openAtlas
        ? button(row.name, 'gh-link', () => handlers.openAtlas(row.id, row.name))
        : node('span', 'gh-name', row.name));
      head.append(node('span', 'gh-meta', row.kind));
      item.append(head);
      if (row.text) item.append(node('p', 'gh-line', row.text));
      item.append(node('p', 'gh-muted', row.note));
      list.append(item);
    });
    nearby.append(list);
    side.append(nearby);
  }
  if (model.stories.length || model.chapters.length) {
    const stories = section('gh-stories', 'Stories set here');
    model.chapters.forEach((row) => {
      const item = node('p', 'gh-line', row.text);
      stories.append(item);
      if (handlers.openExpedition) {
        stories.append(button('Open in your expedition', 'ocv-btn-ghost', () => handlers.openExpedition(row.expeditionId, row.stopId, row.text)));
      }
    });
    model.stories.forEach((row) => stories.append(node('p', 'gh-line', row.text), node('p', 'gh-muted', row.teaser)));
    side.append(stories);
  }
  if (model.next.length) side.append(nextSection(model.next, handlers, 'Explore next'));
  card.append(side);
  return card;
}

function nextSection(rows, handlers, title) {
  const next = section('gh-next', title);
  next.append(node('p', 'gh-muted', 'Connected documented places. Distances are straight lines, not routes or jump counts.'));
  const list = node('ul', 'gh-list');
  rows.forEach((row) => {
    const item = node('li', 'gh-next-item');
    item.dataset.entityId = row.id;
    const head = node('div', 'gh-next-head');
    head.append(evidenceBadge(row.evidence, row.evidenceLabel));
    if (handlers.openAtlas) {
      const link = button(row.name, 'gh-link', () => handlers.openAtlas(row.id, row.name));
      head.append(link);
    } else {
      head.append(node('span', 'gh-name', row.name));
    }
    head.append(node('span', 'gh-meta', `${row.kind} · ${row.system}`));
    item.append(head, node('p', 'gh-line', `${row.reason}. ${row.distance}.`));
    if (row.planNote) item.append(node('p', 'gh-muted', row.planNote));
    if (row.plannable && handlers.plan) {
      const plan = button('Add to expedition', 'ocv-btn-ghost gh-plan', () => handlers.plan(row));
      plan.setAttribute('aria-label', `Add ${row.name} to an expedition`);
      item.append(plan);
    }
    list.append(item);
  });
  next.append(list);
  return next;
}

/* ── Chronicle workspace ─────────────────────────────────────────────── */

const CHRONICLE_STATES = {
  loading: 'Opening the archive…',
  error: 'The Chronicle could not be read right now. Nothing has been lost; try again in a moment.',
  no_commander: 'No commander identified yet. The Chronicle starts once the Journal names your commander.',
  forgotten: 'This commander was forgotten in Privacy. The Chronicle keeps nothing for them.',
  empty: 'Nothing in your Chronicle yet. Dock at a documented starport, land at a documented site or register a Codex entry, or confirm a visit yourself from any place in the Atlas.',
};

export function createChronicle({ fetchJson, sendJson, startTransfer, events, state = {} }) {
  const root = node('section', 'gh-chronicle');
  root.setAttribute('aria-label', 'Commander Chronicle');
  state.filter ||= 'all';
  let status = '';
  let loadToken = 0;
  /* While a read is in flight the content on screen is about to be replaced,
     so a handoff's entry is focused after the render, not in the old content. */
  let loading = false;

  const handlers = {
    openAtlas: (id, label) => startTransfer?.(atlasIntent(id, label, { sectionLabel: label })),
    plan: (row) => {
      const intent = planIntent({ id: row.id, name: row.name, system: row.system, kind: row.kind, planNote: row.planNote });
      if (intent) startTransfer?.(intent);
    },
    openExpedition: (expeditionId, stopId, label) => startTransfer?.(expeditionIntent(expeditionId, stopId, label)),
    save: (target) => act(() => sendJson('POST', PATHS.saved, target), 'Saved to your Chronicle.'),
    reveal: () => { state.reveal = true; load(); },
  };

  async function act(call, done) {
    try {
      await call();
      status = done;
    } catch (error) {
      console.warn('Chronicle action failed:', error);
      status = 'That did not work. Nothing was changed.';
    }
    await load();
  }

  async function load() {
    const token = ++loadToken;
    loading = true;
    try {
      const [context, chronicle] = await Promise.all([
        fetchJson(`${PATHS.context}${state.reveal ? '?reveal=true' : ''}`),
        fetchJson(PATHS.chronicle),
      ]);
      if (token !== loadToken) return;
      state.context = context;
      state.chronicle = chronicle;
      state.error = null;
    } catch (error) {
      if (token !== loadToken) return;
      console.warn('Commander Chronicle unavailable:', error);
      state.error = error?.message || 'request failed';
    }
    loading = false;
    render();
  }

  function focusEntry(entityId) {
    if (!entityId) return false;
    const target = root.querySelector(`[data-entity-id="${escapeAttr(entityId)}"]`);
    if (!target) return false;
    target.scrollIntoView?.({ block: 'center' });
    (target.matches('button') ? target : target.querySelector('button') || target).focus?.();
    return true;
  }

  function filterTabs(model) {
    const tabs = node('div', 'gh-filter');
    tabs.setAttribute('role', 'tablist');
    tabs.setAttribute('aria-label', 'Show in the Chronicle');
    FILTERS.forEach(([id, label]) => {
      const tab = button(label, 'gh-filter-tab', () => {
        state.filter = id;
        render();
        root.querySelector(`.gh-filter-tab[data-filter="${id}"]`)?.focus();
      });
      tab.dataset.filter = id;
      tab.setAttribute('role', 'tab');
      tab.setAttribute('aria-selected', String(model.filter === id));
      tab.tabIndex = model.filter === id ? 0 : -1;
      tab.addEventListener('keydown', (event) => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const all = [...tabs.querySelectorAll('.gh-filter-tab')];
        const index = all.indexOf(tab);
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? all.length - 1
          : (index + (event.key === 'ArrowRight' ? 1 : -1) + all.length) % all.length;
        all[next].click();
      });
      tabs.append(tab);
    });
    return tabs;
  }

  function placesSection(model) {
    const places = section('gh-places', 'Places in your Chronicle');
    if (!model.places.length) {
      places.append(node('p', 'gh-muted', model.filter === 'all'
        ? 'No documented place on record yet.'
        : 'Nothing with this evidence class yet.'));
      return places;
    }
    const list = node('ul', 'gh-list');
    model.places.forEach((row) => {
      const item = node('li', 'gh-place');
      item.dataset.entityId = row.id;
      const head = node('div', 'gh-next-head');
      head.append(evidenceBadge(row.record.kind, row.record.label));
      head.append(row.atlas
        ? button(row.name, 'gh-link', () => handlers.openAtlas(row.id, row.name))
        : node('span', 'gh-name', row.name));
      head.append(node('span', 'gh-meta', `${row.kind} · ${row.system}`));
      item.append(head);
      lines(row.record.lines).forEach((p) => item.append(p));
      list.append(item);
    });
    places.append(list);
    return places;
  }

  function codexSection(model) {
    const codex = section('gh-codex', 'Codex discoveries');
    if (!model.codex.length) {
      codex.append(node('p', 'gh-muted', 'No Codex registration observed yet.'));
      return codex;
    }
    const list = node('ul', 'gh-list');
    model.codex.forEach((row) => {
      const item = node('li', 'gh-codex-item');
      const head = node('div', 'gh-next-head');
      head.append(evidenceBadge('observed'), node('span', 'gh-name', row.name), node('span', 'gh-meta', row.where));
      item.append(head, node('p', 'gh-line', row.line), node('p', 'gh-muted', `${row.when}${row.count > 1 ? ` · ${row.count} times` : ''}`));
      row.flags.forEach((flag) => item.append(node('p', 'gh-flag', flag)));
      if (row.note) item.append(node('p', 'gh-muted', row.note));
      list.append(item);
    });
    codex.append(list);
    return codex;
  }

  function timelineSection(model) {
    const timeline = section('gh-timeline', 'Timeline');
    if (!model.timeline.length) {
      timeline.append(node('p', 'gh-muted', 'Nothing on the timeline yet.'));
      return timeline;
    }
    const list = node('ol', 'gh-timeline-list');
    model.timeline.forEach((row) => {
      const item = node('li', `gh-moment gh-moment-${row.evidence}`);
      if (row.subjectId) item.dataset.entityId = row.subjectId;
      item.append(node('span', 'gh-when', row.when), evidenceBadge(row.evidence, row.evidenceLabel), node('span', 'gh-moment-title', row.title));
      if (row.detail) item.append(node('p', 'gh-muted', row.detail));
      list.append(item);
    });
    timeline.append(list);
    return timeline;
  }

  function journeysSection(model) {
    const journeys = section('gh-journeys', 'Expeditions and chapters');
    if (!model.expeditions.length) {
      journeys.append(node('p', 'gh-muted', 'No expedition yet. Plan one in Navigation › Plan.'));
      return journeys;
    }
    const list = node('ul', 'gh-list');
    model.expeditions.forEach((row) => {
      const item = node('li', 'gh-journey');
      item.append(node('span', 'gh-name', row.name), node('span', 'gh-meta', row.status), node('p', 'gh-line', row.line));
      if (row.next) item.append(node('p', 'gh-muted', row.next));
      list.append(item);
    });
    journeys.append(list);
    return journeys;
  }

  function savedSection(model) {
    const saved = section('gh-saved', 'Saved stories');
    if (!model.saved.length) {
      saved.append(node('p', 'gh-muted', 'Save an Atlas entry or a story chapter to keep it here.'));
      return saved;
    }
    const list = node('ul', 'gh-list');
    model.saved.forEach((row) => {
      const item = node('li', 'gh-saved-item');
      if (row.type === 'atlas' && row.available) {
        item.dataset.entityId = row.targetId;
        item.append(button(row.title, 'gh-link', () => handlers.openAtlas(row.targetId, row.title)));
      } else {
        item.append(node('span', 'gh-name', row.title));
      }
      item.append(node('span', 'gh-meta', `${row.kind} · saved ${row.when}`));
      if (!row.available) item.append(node('p', 'gh-muted', 'No longer in the bundled knowledge.'));
      const remove = button('Remove', 'ocv-btn-ghost gh-unsave', () => act(
        () => sendJson('DELETE', PATHS.savedEntry(row.id)), 'Removed from your Chronicle.',
      ));
      remove.setAttribute('aria-label', `Remove ${row.title} from your Chronicle`);
      item.append(remove);
      list.append(item);
    });
    saved.append(list);
    return saved;
  }

  function render() {
    const content = [];
    const header = node('header', 'gh-chronicle-header');
    const title = heading('h3', 'Your Chronicle', 'gh-chronicle-title');
    header.append(node('p', 'gh-kicker', 'Commander Chronicle · ship’s archive'), title);
    root.setAttribute('aria-labelledby', title.id);
    content.push(header);
    if (state.error && !state.chronicle) {
      header.append(node('p', 'gh-muted', CHRONICLE_STATES.error));
      header.append(button('Try again', 'ocv-btn-ghost gh-retry', load));
      root.replaceChildren(...content);
      return;
    }
    const model = chronicleModel(state.chronicle, state.filter);
    if (model.state === 'loading') {
      header.append(node('p', 'gh-muted', CHRONICLE_STATES.loading));
      root.replaceChildren(...content);
      return;
    }
    content.push(createHistorianCard(contextModel(state.context), handlers));
    if (['no_commander', 'forgotten'].includes(model.state)) {
      header.append(node('p', 'gh-state', CHRONICLE_STATES[model.state]));
      root.replaceChildren(...content);
      return;
    }
    header.append(node('p', 'gh-lead', model.caveat || ''));
    if (model.paused) header.append(node('p', 'gh-state', 'Commander Memory is paused, so the Chronicle records nothing new until you resume it in Privacy.'));
    const tiles = node('ul', 'gh-tiles');
    tiles.setAttribute('aria-label', 'Chronicle totals');
    model.tiles.forEach((tile) => {
      const item = node('li', `gh-tile gh-tile-${tile.id}`);
      const glyph = node('span', 'gh-tile-glyph', tile.glyph);
      glyph.setAttribute('aria-hidden', 'true');
      item.append(glyph, node('span', 'gh-tile-value', tile.value), node('span', 'gh-tile-label', tile.label));
      tiles.append(item);
    });
    header.append(tiles, node('p', 'gh-muted', model.unknownNote), node('p', 'gh-muted', model.memoryNote));
    if (status) {
      const message = node('p', 'gh-status', status);
      message.setAttribute('role', 'status');
      header.append(message);
    }
    if (model.state === 'empty') header.append(node('p', 'gh-state', CHRONICLE_STATES.empty));
    content.push(filterTabs(model));
    const columns = node('div', 'gh-columns');
    const main = node('div', 'gh-main');
    main.append(placesSection(model));
    if (model.filter === 'all' || model.filter === 'observed') main.append(codexSection(model));
    if (model.filter === 'all') main.append(timelineSection(model));
    const side = node('div', 'gh-side');
    if (model.suggested.length) side.append(nextSection(model.suggested, handlers, 'Suggested next'));
    if (model.filter === 'all') side.append(journeysSection(model), savedSection(model));
    columns.append(main);
    if (side.childElementCount) columns.append(side);
    content.push(columns);
    root.replaceChildren(...content);
    if (state.focusEntity && focusEntry(state.focusEntity)) state.focusEntity = null;
  }

  function refresh() { load(); }
  events?.addEventListener('event', (event) => {
    const message = event.detail || {};
    const type = message.event_type || message.event;
    if (type === RECORDED_EVENT || type === CLEARED_EVENT || COMMANDER_EVENTS.includes(type)) refresh();
  });

  render();
  return {
    element: root,
    load,
    render,
    focus(entityId) {
      state.focusEntity = entityId;
      if (!loading && focusEntry(entityId)) state.focusEntity = null;
    },
  };
}

/* ── Atlas: Your record ──────────────────────────────────────────────── */

export function createRecordCard({ entityId, name, fetchJson, sendJson, startTransfer, cache = {} }) {
  const card = node('section', 'atlas-card gh-record');
  const title = heading('h4', 'Your record');
  card.setAttribute('aria-labelledby', title.id);
  card.dataset.entityId = entityId;
  let status = '';

  async function load(force = false) {
    if (force) delete cache[entityId];
    if (!cache[entityId]) {
      cache[entityId] = fetchJson(PATHS.subject(entityId)).catch((error) => {
        console.warn('Chronicle record unavailable:', error);
        return { failed: true };
      });
    }
    const payload = await cache[entityId];
    render(payload);
  }

  async function act(call, done, focusClass) {
    try {
      await call();
      status = done;
    } catch (error) {
      console.warn('Chronicle record action failed:', error);
      status = error?.message?.includes('409')
        ? 'Not saved: no commander is identified yet, or this commander was forgotten.'
        : 'That did not work. Nothing was changed.';
    }
    await load(true);
    card.querySelector(focusClass)?.focus();
  }

  function render(payload) {
    card.replaceChildren(title);
    if (!payload) {
      card.append(node('p', 'atlas-muted', 'Checking your Chronicle…'));
      return;
    }
    if (payload.failed) {
      card.append(node('p', 'atlas-muted', 'Your Chronicle could not be read right now.'));
      return;
    }
    const model = subjectRecordModel(payload);
    if (model.record) {
      const row = node('div', 'gh-record-line');
      row.append(evidenceBadge(model.record.kind, model.record.label));
      lines(model.record.lines.length ? model.record.lines : [model.record.note], 'atlas-muted').forEach((p) => row.append(p));
      card.append(row);
    }
    if (model.note) card.append(node('p', 'atlas-muted', model.note));
    model.inExpeditions.forEach((row) => {
      const item = node('p', 'atlas-muted', `In your expedition ${row.name}.`);
      card.append(item, button('Open the stop', 'ocv-btn-ghost gh-open-stop', () => startTransfer?.(expeditionIntent(row.expeditionId, row.stopId, name))));
    });
    model.stories.forEach((text) => card.append(node('p', 'atlas-muted', text)));
    const actions = node('div', 'gh-actions');
    const writable = model.commanderKnown && !model.forgotten;
    if (model.record && writable) {
      actions.append(model.record.confirmed
        ? button('Withdraw my confirmation', 'ocv-btn-ghost gh-unconfirm', () => act(
          () => sendJson('DELETE', PATHS.confirmation(entityId)), 'Your confirmation was withdrawn.', '.gh-confirm',
        ))
        : button('I have been here', 'ocv-btn-ghost gh-confirm', () => act(
          () => sendJson('POST', PATHS.confirmations, { place_id: entityId }),
          'Recorded as commander-confirmed: you said so, the Journal did not show it.', '.gh-unconfirm',
        )));
    }
    if (writable) {
      actions.append(model.saved
        ? button('Saved · remove', 'ocv-btn-ghost gh-unsave', () => act(
          () => sendJson('DELETE', PATHS.savedEntry(model.saved)), 'Removed from your Chronicle.', '.gh-save',
        ))
        : button('Save to Chronicle', 'ocv-btn-ghost gh-save', () => act(
          () => sendJson('POST', PATHS.saved, { type: 'atlas', id: entityId }), 'Saved to your Chronicle.', '.gh-unsave',
        )));
    }
    if (model.plannable && payload.place) {
      const plan = button('Add to expedition', 'ocv-btn gh-plan', () => {
        const intent = planIntent(
          { id: payload.place.id, name: payload.place.name, system: payload.place.system, kind: '', planNote: model.note },
          {
            package: 'Galactic Atlas',
            sectionId: 'intel-domain-atlas',
            returnLabel: 'Back to Galactic Atlas',
            returnTarget: { route: '/intel', sectionId: 'intel-domain-atlas', entityId },
          },
        );
        if (intent) startTransfer?.(intent);
      });
      plan.setAttribute('aria-label', `Add ${name || entityId} to an expedition`);
      actions.append(plan);
    }
    actions.append(button('Open in Chronicle', 'ocv-btn-ghost gh-open-chronicle', () => startTransfer?.({
      originRoute: '/intel',
      originPackage: 'Galactic Atlas',
      originSectionId: 'intel-domain-atlas',
      originSectionLabel: name || entityId,
      targetRoute: '/intel',
      targetSectionId: 'intel-domain-chronicle',
      targetEntityId: entityId,
      targetLabel: 'Commander Chronicle',
      reason: 'See your Chronicle beside this record.',
      returnLabel: 'Back to Galactic Atlas',
      returnTarget: { route: '/intel', sectionId: 'intel-domain-atlas', entityId },
    })));
    card.append(actions);
    if (!writable) {
      card.append(node('p', 'atlas-muted', model.forgotten
        ? 'This commander was forgotten; nothing can be recorded for them.'
        : 'No commander identified yet, so nothing can be recorded.'));
    }
    if (status) {
      const message = node('p', 'atlas-muted gh-status', status);
      message.setAttribute('role', 'status');
      card.append(message);
    }
  }

  render(null);
  load();
  return { element: card, load };
}
