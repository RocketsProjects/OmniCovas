// Galactic Expeditions workspace (GKI-06), Navigation › Plan.
// Plan a journey from a story, a theme, Engineering shortages or nothing; read
// its story as you go; keep what the Journal confirmed apart from what you marked.
// ADR 0003: every value is rendered with textContent. Distances are straight
// lines; plotting stays in the game or Spansh. Nothing here interrupts flight:
// story moments the Journal earned are listed for reading, never pushed.
import {
  CLEARED_EVENT, EXPEDITION_STATUS, FIND_TABS, PATHS, PROGRESS_EVENTS, SECTION_ID, STOP_PREFIX,
  atlasIntent, distanceText, evidenceText, kickerText, legText, locationText, materialsIntent,
  modeText, navigationLines, progressText, purposeText, relevanceTone, remember, remembered,
  requirementTone, statusOf,
} from '../view-models/expeditions.js';

const cssEscape = (value) => (window.CSS?.escape
  ? window.CSS.escape(value)
  : String(value).replace(/["\\]/g, '\\$&'));

const node = (tag, cls = '', text) => {
  const element = document.createElement(tag);
  if (cls) element.className = cls;
  if (text != null) element.textContent = String(text);
  return element;
};

function button(text, cls, onClick, focusKey) {
  const element = node('button', `cmd-btn ${cls || 'cmd-btn--quiet'}`, text);
  element.type = 'button';
  if (focusKey) element.dataset.focus = focusKey;
  element.addEventListener('click', onClick);
  return element;
}

function chip(text, tone) {
  return node('span', `expedition-chip expedition-chip--${tone}`, text);
}

function drawer(summary, content, { open = false, cls = '' } = {}) {
  const details = node('details', `expedition-drawer ${cls}`.trim());
  if (open) details.open = true;
  details.append(node('summary', '', summary));
  if (content instanceof Node) details.append(content);
  else if (content != null) details.append(node('p', 'expedition-muted', content));
  return details;
}

function sourcesLine(sources) {
  const names = (sources || []).map((s) => s.name).filter(Boolean);
  return names.length ? node('p', 'expedition-sources', `Sources: ${names.join(' · ')}`) : null;
}

const EVIDENCE_TEXT = {
  official_canon: 'Official canon',
  developer_statement: 'Developer statement',
  community_reference: 'Community reference',
  community_report: 'Community report',
};

export function createExpeditionWorkspace({
  fetchJson, sendJson, startTransfer, openSettings, state = {}, events = window.OmniEvents,
}) {
  const root = node('section', 'expeditions');
  root.id = SECTION_ID;
  root.setAttribute('aria-label', 'Expeditions');
  Object.assign(state, { findTab: 'story', ...remembered(), ...state });
  let refreshTimer = null;

  /* ── Data ───────────────────────────────────────────────────────────── */

  async function call(task, failure) {
    state.busy = true;
    try {
      return await task();
    } catch (error) {
      console.warn('Expeditions request failed:', error);
      state.message = failure;
      return null;
    } finally {
      state.busy = false;
    }
  }

  async function load() {
    const [list, catalog] = await Promise.all([
      fetchJson(PATHS.list).catch(() => null),
      fetchJson(PATHS.catalog).catch(() => null),
    ]);
    state.list = list;
    state.catalog = catalog;
    state.unavailable = !list || !Array.isArray(list.expeditions);
    const rows = list?.expeditions || [];
    if (!rows.some((row) => row.id === state.selectedId)) {
      const open = rows.find((row) => row.status !== 'archived');
      state.selectedId = open?.id || null;
      state.selectedStopId = null;
    }
    if (state.selectedId) await loadDetail();
    else { state.detail = null; render(); }
  }

  async function loadDetail() {
    const id = state.selectedId;
    if (!id) { state.detail = null; render(); return; }
    const detail = await fetchJson(PATHS.detail(id)).catch(() => null);
    if (state.selectedId !== id) return;
    state.detail = detail;
    if (!detail) {
      state.selectedId = null;
      state.message = 'That expedition is no longer available.';
    } else if (!detail.stops.some((s) => s.stop_id === state.selectedStopId)) {
      state.selectedStopId = null;
    }
    const narrativeId = detail?.story?.id;
    if (narrativeId && state.narrative?.id !== narrativeId) {
      const reader = await fetchJson(PATHS.narrative(narrativeId)).catch(() => null);
      state.narrative = reader?.narrative || null;
      state.revealed = {};
    }
    remember(state);
    render();
    loadFindTab();
  }

  function loadFindTab() {
    const id = state.selectedId;
    if (!id) return;
    if (state.findTab === 'along' && state.suggestionsFor !== id) {
      state.suggestionsFor = id;
      state.suggestions = null;
      fetchJson(PATHS.suggestions(id))
        .then((payload) => { state.suggestions = payload; })
        .catch(() => { state.suggestions = { failed: true }; })
        .finally(() => renderFind());
    }
    if (state.findTab === 'materials' && state.materialsFor !== id) {
      state.materialsFor = id;
      state.materials = null;
      fetchJson(PATHS.materials(state.materialsScope || 'all', id))
        .then((payload) => { state.materials = payload; })
        .catch(() => { state.materials = { failed: true }; })
        .finally(() => renderFind());
    }
    if (state.findTab === 'themes' && state.themeId && state.themeFor !== `${id}:${state.themeId}`) {
      state.themeFor = `${id}:${state.themeId}`;
      state.theme = null;
      fetchJson(PATHS.theme(state.themeId, id))
        .then((payload) => { state.theme = payload; })
        .catch(() => { state.theme = { failed: true }; })
        .finally(() => renderFind());
    }
  }

  /* After a change the side lists are stale: what is already added has moved. */
  function invalidateFind() {
    state.suggestionsFor = null;
    state.storySuggestionsFor = null;
    state.materialsFor = null;
    state.themeFor = null;
  }

  async function mutate(method, path, body, failure, focusKey) {
    const result = await call(() => sendJson(method, path, body), failure);
    if (result === null) { render(); return null; }
    state.message = null;
    if (focusKey) state.focus = focusKey;
    invalidateFind();
    if (result?.expedition && result?.stops) {
      state.detail = result;
      render();
      loadFindTab();
    } else if (result?.expedition?.stops) {
      state.detail = result.expedition;
      render();
      loadFindTab();
    } else {
      await loadDetail();
    }
    return result;
  }

  async function refreshList() {
    state.list = await fetchJson(PATHS.list).catch(() => state.list);
  }

  async function create(payload, focusKey = 'expedition-name') {
    const detail = await call(() => sendJson('POST', PATHS.list, payload), 'The expedition could not be created.');
    if (!detail?.expedition) { render(); return null; }
    state.selectedId = detail.expedition.id;
    state.selectedStopId = null;
    state.creating = false;
    state.detail = detail;
    state.focus = focusKey;
    state.message = null;
    invalidateFind();
    await refreshList();
    const narrativeId = detail.story?.id;
    if (narrativeId && state.narrative?.id !== narrativeId) {
      const reader = await fetchJson(PATHS.narrative(narrativeId)).catch(() => null);
      state.narrative = reader?.narrative || null;
      state.revealed = {};
    }
    remember(state);
    render();
    loadFindTab();
    return detail;
  }

  function select(expeditionId, stopId = null) {
    state.selectedId = expeditionId;
    state.selectedStopId = stopId;
    state.creating = false;
    state.confirm = null;
    invalidateFind();
    remember(state);
    return loadDetail();
  }

  /* Open an expedition and stop, as a return from the Atlas or Materials does. */
  async function open(expeditionId, stopId) {
    if (!state.list) await load();
    if (expeditionId && expeditionId !== state.selectedId) await select(expeditionId, stopId);
    else if (expeditionId) {
      state.selectedStopId = stopId;
      await loadDetail();
    }
    return stopId ? document.getElementById(`${STOP_PREFIX}${stopId}`) : root;
  }

  function scheduleRefresh() {
    if (!state.selectedId || !root.isConnected) return;
    clearTimeout(refreshTimer);
    // The Journal event reaches the UI before the service has recorded it.
    refreshTimer = setTimeout(() => { if (root.isConnected) loadDetail(); }, 900);
  }

  events?.addEventListener?.('event', (event) => {
    const type = event?.detail?.event_type || event?.detail?.event;
    if (type === CLEARED_EVENT) {
      Object.assign(state, { list: null, detail: null, selectedId: null, selectedStopId: null, narrative: null });
      if (root.isConnected) load();
    } else if (PROGRESS_EVENTS.has(type)) scheduleRefresh();
  });

  /* ── Rendering ────────────────────────────────────────────────────────── */

  function render() {
    const focusKey = state.focus || (root.contains(document.activeElement) ? document.activeElement?.dataset?.focus : null);
    state.focus = null;
    root.replaceChildren(bar());
    if (state.message) {
      const message = node('p', 'expedition-message', state.message);
      message.setAttribute('role', 'status');
      root.append(message);
    }
    if (state.unavailable) {
      root.append(empty('Expeditions are unavailable right now.', 'They come back when the OmniCOVAS service is reachable.'));
    } else if (state.list?.profile?.forgotten) {
      root.append(empty('Nothing is kept for this commander.',
        'This commander was forgotten in Privacy, so OmniCOVAS keeps no expeditions for them.'));
    } else if (state.creating || !state.detail) {
      if (state.list) root.append(unassigned(), starts());
    } else {
      root.append(workspace(state.detail));
    }
    if (focusKey) root.querySelector(`[data-focus="${cssEscape(focusKey)}"]`)?.focus?.();
  }

  function empty(status, reason) {
    const wrap = node('div', 'expedition-empty');
    wrap.setAttribute('role', 'status');
    wrap.append(node('p', 'expedition-empty-status', status), node('p', 'expedition-muted', reason));
    return wrap;
  }

  function bar() {
    const header = node('header', 'expeditions-bar');
    header.append(node('h3', 'expeditions-title', 'Expeditions'));
    const rows = state.list?.expeditions || [];
    if (rows.length) {
      const label = node('label', 'expeditions-pick');
      label.append(node('span', 'expedition-visually-hidden', 'Open an expedition'));
      const pick = node('select');
      pick.name = 'expedition_pick';
      pick.dataset.focus = 'expedition-pick';
      rows.forEach((row) => {
        const option = node('option', '', `${row.name} · ${EXPEDITION_STATUS[row.status] || row.status}`);
        option.value = row.id;
        option.selected = row.id === state.selectedId && !state.creating;
        pick.append(option);
      });
      if (state.creating || !state.selectedId) {
        const placeholder = node('option', '', 'Choose an expedition');
        placeholder.value = '';
        placeholder.selected = true;
        pick.prepend(placeholder);
      }
      pick.addEventListener('change', () => { if (pick.value) { state.focus = 'expedition-pick'; select(pick.value); } });
      label.append(pick);
      header.append(label);
    }
    if (!state.list?.profile?.forgotten && !state.unavailable) {
      header.append(button('New expedition', 'cmd-btn--secondary', () => {
        state.creating = true;
        state.focus = 'start-story';
        render();
      }, 'expedition-new'));
    }
    return header;
  }

  function unassigned() {
    const count = state.list?.unassigned || 0;
    if (!count) return document.createDocumentFragment();
    const wrap = node('div', 'expedition-unassigned');
    wrap.append(node('p', '', count === 1
      ? 'One expedition was planned before OmniCOVAS identified a commander.'
      : `${count} expeditions were planned before OmniCOVAS identified a commander.`));
    wrap.append(button('Show and claim', 'cmd-btn--quiet', async () => {
      const payload = await fetchJson('/navigation/expeditions/unassigned').catch(() => null);
      state.unassignedRows = payload?.expeditions || [];
      render();
    }, 'unassigned-show'));
    (state.unassignedRows || []).forEach((row) => {
      const line = node('p', 'expedition-unassigned-row');
      line.append(node('span', '', `${row.name} · ${row.stops} stops`));
      line.append(button('Claim for this commander', 'cmd-btn--quiet', async () => {
        const detail = await call(() => sendJson('POST', PATHS.claim(row.id)), 'That expedition could not be claimed.');
        if (detail?.expedition) {
          state.unassignedRows = null;
          await refreshList();
          await select(detail.expedition.id);
        } else render();
      }));
      wrap.append(line);
    });
    return wrap;
  }

  /* Four ways in, one workflow: each start makes an expedition, then stops are
     found the same way whichever it began from. */
  function starts() {
    const wrap = node('div', 'expedition-starts');
    wrap.append(node('h4', '', 'Plan a journey'));
    wrap.append(node('p', 'expedition-lead',
      'Follow a story across the galaxy, explore a theme, gather what your Engineering builds need, or start empty. You can add stops from any of these later.'));
    const grid = node('div', 'expedition-start-grid');

    const story = node('section', 'expedition-start');
    story.append(node('h5', '', 'Follow a story'));
    const narratives = state.catalog?.narratives || [];
    if (!narratives.length) story.append(node('p', 'expedition-muted', 'No stories are bundled in this build.'));
    narratives.forEach((row, index) => {
      const item = node('div', 'expedition-start-story');
      item.append(node('p', 'expedition-start-name', row.title), node('p', 'expedition-muted', row.teaser));
      const facts = [`${row.chapters} chapters`, row.systems?.join(', ')];
      if (Number.isFinite(row.nearest_ly)) facts.push(`nearest ${distanceText(row.nearest_ly)} away`);
      item.append(node('p', 'expedition-meta', facts.filter(Boolean).join(' · ')));
      item.append(button('Start this journey', 'cmd-btn--primary',
        () => create({ entry: 'theme', narrative_id: row.id, theme_id: row.theme || undefined }),
        index === 0 ? 'start-story' : `start-story-${row.id}`));
      story.append(item);
    });

    const theme = node('section', 'expedition-start');
    theme.append(node('h5', '', 'Explore a theme'));
    const themes = state.catalog?.themes || [];
    const label = node('label', 'expedition-field');
    label.append(node('span', '', 'Theme'));
    const choose = node('select');
    choose.name = 'start_theme';
    themes.forEach((row) => {
      const option = node('option', '', row.needs_shortages ? `${row.label} (uses your shortages)` : `${row.label} (${row.places})`);
      option.value = row.id;
      choose.append(option);
    });
    label.append(choose);
    theme.append(label);
    const chosen = () => themes.find((row) => row.id === choose.value);
    const summary = node('p', 'expedition-muted', chosen()?.summary || '');
    choose.addEventListener('change', () => { summary.textContent = chosen()?.summary || ''; });
    theme.append(summary, button('Start with this theme', 'cmd-btn--secondary', async () => {
      if (!choose.value) return;
      state.findTab = 'themes';
      state.themeId = choose.value;
      await create({ entry: 'theme', theme_id: choose.value });
    }, 'start-theme'));

    const goal = node('section', 'expedition-start');
    goal.append(node('h5', '', 'Gather Engineering materials'));
    goal.append(node('p', 'expedition-muted',
      'Uses the shortages your active builds have in Engineering, after reservations and the Material Trader plan.'));
    goal.append(button('Plan a materials run', 'cmd-btn--secondary', async () => {
      state.findTab = 'materials';
      await create({ entry: 'goal', goal_scope: 'all' });
    }, 'start-goal'));

    const custom = node('section', 'expedition-start');
    custom.append(node('h5', '', 'Start empty'));
    const nameLabel = node('label', 'expedition-field');
    nameLabel.append(node('span', '', 'Name'));
    const name = node('input');
    name.name = 'start_name';
    name.maxLength = 80;
    name.placeholder = 'My expedition';
    nameLabel.append(name);
    custom.append(nameLabel, button('Create expedition', 'cmd-btn--secondary', async () => {
      state.findTab = 'search';
      await create({ entry: 'custom', name: name.value.trim() || undefined }, 'find-search');
    }, 'start-custom'));

    grid.append(story, theme, goal, custom);
    wrap.append(grid);
    if (state.creating && state.detail) {
      wrap.append(button('Back to the current expedition', 'cmd-btn--quiet', () => {
        state.creating = false;
        render();
      }, 'start-cancel'));
    }
    return wrap;
  }

  /* ── The expedition ─────────────────────────────────────────────────── */

  function workspace(detail) {
    const article = node('article', 'expedition');
    article.append(head(detail));
    const following = detail.stops.find((s) => s.stop_id === detail.spatial?.next?.stop_id);
    if (following) article.append(nextStop(detail, following));
    const columns = node('div', 'expedition-columns');
    const main = node('div', 'expedition-main');
    main.append(itinerary(detail), findStops(detail));
    const side = node('div', 'expedition-side');
    if (detail.story) side.append(storyReader(detail));
    if (detail.opportunities?.length) side.append(moments(detail));
    side.append(preflight(detail), storytelling(detail), recap(detail));
    columns.append(main, side);
    article.append(columns);
    return article;
  }

  function head(detail) {
    const trip = detail.expedition;
    const header = node('header', 'expedition-head');
    header.append(node('p', 'expedition-kicker', kickerText(trip, detail.story)));
    if (state.renaming) {
      const label = node('label', 'expedition-field expedition-rename');
      label.append(node('span', '', 'Expedition name'));
      const input = node('input');
      input.name = 'expedition_name';
      input.maxLength = 80;
      input.value = trip.name;
      input.dataset.focus = 'expedition-rename-input';
      input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') save();
        if (event.key === 'Escape') { state.renaming = false; state.focus = 'expedition-rename'; render(); }
      });
      const save = () => {
        state.renaming = false;
        mutate('PATCH', PATHS.detail(trip.id), { name: input.value }, 'The new name was not saved.', 'expedition-rename')
          .then(refreshList).then(render);
      };
      label.append(input);
      header.append(label, button('Save name', 'cmd-btn--secondary', save));
    } else {
      const title = node('h4', 'expedition-name', trip.name);
      title.tabIndex = -1;
      title.dataset.focus = 'expedition-name';
      header.append(title);
    }
    const status = node('div', 'expedition-status');
    status.append(chip(EXPEDITION_STATUS[trip.status] || trip.status, trip.status === 'active' ? 'done' : 'planned'));
    status.append(node('span', 'expedition-progress', progressText(trip, detail.story)));
    header.append(status);

    const actions = node('div', 'expedition-actions');
    const change = (status_, label, cls, key) => button(label, cls, () => mutate(
      'PATCH', PATHS.detail(trip.id), { status: status_ }, 'The expedition could not be updated.', key,
    ).then(refreshList).then(render), key);
    if (trip.status === 'planning') {
      actions.append(change('active', 'Start expedition', 'cmd-btn--primary', 'status-start'));
      actions.append(node('span', 'expedition-muted', 'Progress is recorded from the moment you start.'));
    } else if (trip.status === 'active') {
      actions.append(change('completed', 'Mark expedition complete', 'cmd-btn--secondary', 'status-complete'));
      actions.append(change('planning', 'Pause', 'cmd-btn--quiet', 'status-pause'));
    } else {
      actions.append(change('active', 'Resume', 'cmd-btn--secondary', 'status-resume'));
    }
    if (trip.status !== 'archived') actions.append(change('archived', 'Archive', 'cmd-btn--quiet', 'status-archive'));
    actions.append(button('Rename', 'cmd-btn--quiet', () => {
      state.renaming = true;
      state.focus = 'expedition-rename-input';
      render();
    }, 'expedition-rename'));
    if (state.confirm === 'delete') {
      actions.append(node('span', 'expedition-confirm', 'Delete this expedition and its history?'));
      actions.append(button('Delete', 'cmd-btn--danger', async () => {
        state.confirm = null;
        const done = await call(() => sendJson('DELETE', PATHS.detail(trip.id)), 'The expedition could not be deleted.');
        if (done) {
          state.selectedId = null;
          state.detail = null;
          state.narrative = null;
          state.focus = 'expedition-new';
          await load();
        } else render();
      }, 'delete-confirm'));
      actions.append(button('Keep it', 'cmd-btn--quiet', () => { state.confirm = null; state.focus = 'delete'; render(); }));
    } else {
      actions.append(button('Delete…', 'cmd-btn--quiet', () => {
        state.confirm = 'delete';
        state.focus = 'delete-confirm';
        render();
      }, 'delete'));
    }
    header.append(actions);
    return header;
  }

  function nextStop(detail, stop) {
    const card = node('section', 'expedition-next');
    card.setAttribute('aria-label', 'Next stop');
    card.append(node('p', 'expedition-kicker', 'Next stop'));
    const title = node('p', 'expedition-next-name', stop.name);
    card.append(title, node('p', 'expedition-meta', locationText(stop)));
    const why = stop.purposes.map(purposeText).join(' · ');
    if (why) card.append(node('p', 'expedition-next-why', why));
    const away = detail.spatial?.next;
    const origin = detail.spatial?.origin;
    card.append(node('p', 'expedition-meta', origin?.star_pos && Number.isFinite(away?.distance_ly)
      ? `${distanceText(away.distance_ly)} in a straight line from ${origin.system}, your last known position`
      : 'Straight-line distance unknown: your position or this stop\'s is not known.'));
    const actions = node('div', 'expedition-actions');
    actions.append(button('Show stop details', 'cmd-btn--secondary', () => {
      state.selectedStopId = stop.stop_id;
      state.focus = `stop-${stop.stop_id}`;
      remember(state);
      render();
    }, 'next-details'));
    if (detail.next_leg?.spansh_url) actions.append(spanshLink(detail.next_leg.spansh_url, 'Plot this leg in Spansh ↗'));
    card.append(actions);
    return card;
  }

  function spanshLink(url, text) {
    const link = node('a', 'cmd-btn cmd-btn--quiet expedition-external', text);
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.title = 'Opens the Spansh route plotter in your browser. OmniCOVAS sends nothing to Spansh or the game.';
    return link;
  }

  /* ── Itinerary ──────────────────────────────────────────────────────── */

  function itinerary(detail) {
    const section = node('section', 'expedition-itinerary');
    section.setAttribute('aria-labelledby', 'expedition-itinerary-title');
    const heading = node('h5', '', 'Itinerary');
    heading.id = 'expedition-itinerary-title';
    section.append(heading);
    if (!detail.stops.length) {
      section.append(node('p', 'expedition-muted', 'No stops yet. Find some below: stories, themes, materials or a system you name.'));
      return section;
    }
    const legs = new Map((detail.spatial?.legs || []).map((leg) => [leg.to.stop_id, leg]));
    const list = node('ol', 'expedition-stops');
    detail.stops.forEach((stop, index) => list.append(stopRow(detail, stop, index, legs.get(stop.stop_id))));
    section.append(list, orders(detail));
    section.append(node('p', 'expedition-caveat', detail.spatial?.caveat || ''));
    return section;
  }

  function stopRow(detail, stop, index, leg) {
    const item = node('li', 'expedition-stop');
    item.id = `${STOP_PREFIX}${stop.stop_id}`;
    item.dataset.stopId = stop.stop_id;
    const status = statusOf(stop);
    item.dataset.status = stop.status;
    const open = state.selectedStopId === stop.stop_id;
    if (open) item.classList.add('is-selected');
    if (leg) item.append(node('p', 'expedition-leg', legText(leg)));
    const main = node('button', 'expedition-stop-main');
    main.type = 'button';
    main.dataset.focus = `stop-${stop.stop_id}`;
    main.setAttribute('aria-expanded', String(open));
    main.setAttribute('aria-controls', `${item.id}-detail`);
    const number = node('span', 'expedition-stop-number', String(index + 1));
    number.setAttribute('aria-hidden', 'true');
    const text = node('span', 'expedition-stop-text');
    text.append(node('span', 'expedition-stop-name', stop.name), node('span', 'expedition-meta', locationText(stop)));
    main.append(number, text, chip(status.label, status.tone));
    main.addEventListener('click', () => {
      state.selectedStopId = open ? null : stop.stop_id;
      state.focus = `stop-${stop.stop_id}`;
      remember(state);
      render();
    });
    item.append(main);
    const purposes = node('p', 'expedition-purposes');
    stop.purposes.forEach((purpose) => purposes.append(node('span', 'expedition-purpose', purposeText(purpose))));
    item.append(purposes);
    if (open) item.append(stopDetail(detail, stop, index));
    return item;
  }

  function stopDetail(detail, stop, index) {
    const trip = detail.expedition;
    const panel = node('div', 'expedition-stop-detail');
    panel.id = `${STOP_PREFIX}${stop.stop_id}-detail`;
    if (stop.location_note) panel.append(node('p', 'expedition-note-line', stop.location_note));
    panel.append(node('p', 'expedition-evidence', evidenceText(stop)));

    const where = node('dl', 'expedition-where');
    navigationLines(stop).forEach(([label, value]) => {
      where.append(node('dt', '', label), node('dd', '', value));
    });
    panel.append(where);
    if (stop.location?.system) {
      const copy = node('div', 'expedition-copy');
      const field = node('input', 'expedition-copy-field');
      field.readOnly = true;
      field.value = stop.location.system;
      field.setAttribute('aria-label', 'System name for the galaxy map');
      copy.append(field, button('Copy system name', 'cmd-btn--quiet', () => {
        field.select();
        const done = navigator.clipboard?.writeText?.(stop.location.system);
        state.copied = stop.stop_id;
        Promise.resolve(done).catch(() => {}).finally(() => {
          copy.querySelector('.expedition-copied')?.remove();
          copy.append(node('span', 'expedition-copied', 'Copied. Paste it into the galaxy map search.'));
        });
      }));
      panel.append(copy);
    }

    stop.purposes.forEach((purpose) => {
      if (purpose.type === 'acquisition') {
        const box = node('div', `expedition-relevance expedition-tone-${relevanceTone(purpose.relevance)}`);
        box.append(node('p', '', purpose.relevance?.explanation || 'Shortages not checked yet.'));
        if (purpose.relevance?.note) box.append(node('p', 'expedition-muted', purpose.relevance.note));
        if (purpose.methods?.length) {
          box.append(node('p', 'expedition-muted', `Method: ${purpose.methods.map((m) => m.name).join(', ')}`));
        }
        const links = node('div', 'expedition-actions');
        (purpose.materials || []).forEach((material) => {
          const intent = materialsIntent(trip, stop, material, purpose.scope || '');
          if (intent) links.append(button(`${material.name} in Materials`, 'cmd-btn--quiet', () => startTransfer(intent)));
        });
        box.append(links);
        panel.append(box);
      }
      if (purpose.type === 'story' && state.narrative) {
        panel.append(button(`Read chapter ${purpose.chapter_position}: ${purpose.chapter_title}`, 'cmd-btn--quiet', () => {
          state.openChapter = purpose.chapter;
          state.focus = `chapter-${purpose.chapter}`;
          render();
        }));
      }
    });

    const requirements = (detail.preflight?.stops || []).find((row) => row.stop_id === stop.stop_id)?.requirements || [];
    if (requirements.length) {
      const list = node('ul', 'expedition-requirements');
      requirements.forEach((req) => list.append(requirementItem(req)));
      panel.append(list);
    }

    const noteLabel = node('label', 'expedition-field');
    noteLabel.append(node('span', '', 'Your note'));
    const note = node('textarea');
    note.name = 'stop_note';
    note.rows = 2;
    note.maxLength = 500;
    note.value = stop.note || '';
    noteLabel.append(note);
    panel.append(noteLabel);

    const actions = node('div', 'expedition-actions');
    actions.append(button('Save note', 'cmd-btn--quiet', () => mutate(
      'PATCH', PATHS.stop(trip.id, stop.stop_id), { note: note.value }, 'The note was not saved.', `stop-${stop.stop_id}`,
    ), `note-${stop.stop_id}`));
    const manual = (stateName, label, key) => button(label, 'cmd-btn--quiet', () => mutate(
      'PATCH', PATHS.stop(trip.id, stop.stop_id), { manual_state: stateName }, 'The stop could not be updated.', key,
    ), key);
    if (stop.manual_state !== 'completed') actions.append(manual('completed', 'Mark complete', `complete-${stop.stop_id}`));
    if (stop.manual_state !== 'skipped') actions.append(manual('skipped', 'Skip', `skip-${stop.stop_id}`));
    if (stop.manual_state !== 'planned') actions.append(manual('planned', 'Plan again', `replan-${stop.stop_id}`));
    const ids = detail.stops.map((s) => s.stop_id);
    const move = (offset, label, key) => {
      const target = index + offset;
      const control = button(label, 'cmd-btn--quiet', () => {
        const order = [...ids];
        [order[index], order[target]] = [order[target], order[index]];
        mutate('PUT', PATHS.order(trip.id), { stop_ids: order }, 'The order was not saved.', key);
      }, key);
      control.disabled = target < 0 || target >= ids.length;
      return control;
    };
    actions.append(move(-1, 'Move up', `up-${stop.stop_id}`), move(1, 'Move down', `down-${stop.stop_id}`));
    const atlas = atlasIntent(trip, stop);
    if (atlas) actions.append(button('Open in the Galactic Atlas', 'cmd-btn--quiet', () => startTransfer(atlas), `atlas-${stop.stop_id}`));
    if (state.confirm === `remove-${stop.stop_id}`) {
      actions.append(node('span', 'expedition-confirm', 'Remove this stop?'));
      actions.append(button('Remove', 'cmd-btn--danger', () => {
        state.confirm = null;
        state.selectedStopId = null;
        mutate('DELETE', PATHS.stop(trip.id, stop.stop_id), undefined, 'The stop could not be removed.', 'expedition-name');
      }, `remove-confirm-${stop.stop_id}`));
      actions.append(button('Keep it', 'cmd-btn--quiet', () => { state.confirm = null; state.focus = `remove-${stop.stop_id}`; render(); }));
    } else {
      actions.append(button('Remove…', 'cmd-btn--quiet', () => {
        state.confirm = `remove-${stop.stop_id}`;
        state.focus = `remove-confirm-${stop.stop_id}`;
        render();
      }, `remove-${stop.stop_id}`));
    }
    panel.append(actions);
    return panel;
  }

  function requirementItem(req) {
    const item = node('li', `expedition-requirement expedition-requirement--${requirementTone(req)}`);
    item.append(node('span', 'expedition-requirement-label', req.status_label));
    item.append(node('span', '', req.text));
    if (req.applies_from) item.append(node('span', 'expedition-muted', `Applies to all of ${req.applies_from}.`));
    if (req.note) item.append(node('span', 'expedition-muted', req.note));
    if (req.hint) item.append(node('span', 'expedition-muted', req.hint));
    return item;
  }

  function orders(detail) {
    const wrap = node('div', 'expedition-orders');
    const shortest = detail.orders?.shortest;
    const story = detail.orders?.story;
    const trip = detail.expedition;
    if (shortest?.changed && shortest.saves_ly > 0) {
      const line = node('p', 'expedition-order-line');
      line.append(node('span', '', `A different order is ${distanceText(shortest.saves_ly)} shorter in straight lines.`));
      line.append(button('Use the shorter order', 'cmd-btn--quiet', () => mutate(
        'PUT', PATHS.order(trip.id), { apply: 'shortest' }, 'The order was not saved.', 'order-shortest',
      ), 'order-shortest'));
      wrap.append(line, drawer('What this order does', shortest.explanation));
    }
    if (story?.changed) {
      const line = node('p', 'expedition-order-line');
      line.append(node('span', '', 'Your stops are not in story order.'));
      line.append(button('Use story order', 'cmd-btn--quiet', () => mutate(
        'PUT', PATHS.order(trip.id), { apply: 'story' }, 'The order was not saved.', 'order-story',
      ), 'order-story'));
      wrap.append(line);
    }
    return wrap;
  }

  /* ── Finding stops ──────────────────────────────────────────────────── */

  function findStops(detail) {
    const section = node('section', 'expedition-find');
    section.setAttribute('aria-labelledby', 'expedition-find-title');
    const heading = node('h5', '', 'Find stops');
    heading.id = 'expedition-find-title';
    section.append(heading);
    const tabs = node('div', 'expedition-find-tabs');
    tabs.setAttribute('role', 'tablist');
    tabs.setAttribute('aria-label', 'Ways to find stops');
    FIND_TABS.forEach(([id, label]) => {
      const tab = node('button', 'expedition-find-tab', label);
      tab.type = 'button';
      tab.id = `expedition-find-tab-${id}`;
      tab.dataset.focus = `find-${id}`;
      tab.setAttribute('role', 'tab');
      tab.setAttribute('aria-controls', 'expedition-find-panel');
      const selected = state.findTab === id;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
      tab.addEventListener('click', () => {
        state.findTab = id;
        state.focus = `find-${id}`;
        remember(state);
        render();
        loadFindTab();
      });
      tab.addEventListener('keydown', (event) => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const all = [...tabs.querySelectorAll('.expedition-find-tab')];
        const at = all.indexOf(tab);
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? all.length - 1
          : (at + (event.key === 'ArrowRight' ? 1 : -1) + all.length) % all.length;
        all[next].click();
      });
      tabs.append(tab);
    });
    const panel = node('div', 'expedition-find-panel');
    panel.id = 'expedition-find-panel';
    panel.setAttribute('role', 'tabpanel');
    panel.setAttribute('aria-labelledby', `expedition-find-tab-${state.findTab}`);
    section.append(tabs, panel);
    fillFind(panel, detail);
    return section;
  }

  function renderFind() {
    const panel = root.querySelector('#expedition-find-panel');
    if (panel && state.detail) fillFind(panel, state.detail);
  }

  function fillFind(panel, detail) {
    panel.replaceChildren();
    const tab = state.findTab;
    if (tab === 'story') panel.append(findStory(detail));
    else if (tab === 'themes') panel.append(findThemes(detail));
    else if (tab === 'materials') panel.append(findMaterials(detail));
    else if (tab === 'along') panel.append(findAlong(detail));
    else panel.append(findSearch(detail));
  }

  function addButton(detail, row, purpose, key) {
    if (row.in_expedition && !purpose) return node('span', 'expedition-in', 'On the itinerary');
    return button(row.in_expedition ? 'Add this purpose' : 'Add to expedition', 'cmd-btn--quiet', () => {
      const body = { place_id: row.place.id };
      if (purpose) body.purposes = [purpose];
      mutate('POST', PATHS.stops(detail.expedition.id), body, 'That stop could not be added.', key);
    }, key);
  }

  function candidateList(detail, rows, purposeFor, emptyText) {
    if (!rows.length) return node('p', 'expedition-muted', emptyText);
    const list = node('ul', 'expedition-candidates');
    rows.forEach((row) => {
      const item = node('li', 'expedition-candidate');
      const text = node('div', 'expedition-candidate-text');
      text.append(node('span', 'expedition-candidate-name', row.place.name));
      const facts = [row.place.system];
      if (Number.isFinite(row.distance_ly)) facts.push(`${distanceText(row.distance_ly)} away`);
      if (Number.isFinite(row.detour_ly)) facts.push(row.same_system ? 'same system as a stop' : `adds ${distanceText(row.detour_ly)}`);
      text.append(node('span', 'expedition-meta', facts.filter(Boolean).join(' · ')));
      text.append(node('span', 'expedition-candidate-why', (row.why || []).join(' · ')));
      item.append(text, addButton(detail, row, purposeFor?.(row), `add-${row.place.id}`));
      list.append(item);
    });
    return list;
  }

  function findStory(detail) {
    const wrap = node('div');
    const narratives = state.catalog?.narratives || [];
    if (!detail.story) {
      wrap.append(node('p', 'expedition-muted', 'Follow a story on this expedition: its chapters become stops you can add.'));
      narratives.forEach((row) => {
        const line = node('p', 'expedition-order-line');
        line.append(node('span', '', `${row.title} · ${row.chapters} chapters`));
        line.append(button('Follow this story', 'cmd-btn--quiet', () => mutate(
          'PATCH', PATHS.detail(detail.expedition.id), { narrative_id: row.id }, 'The story could not be attached.', 'find-story',
        ), `follow-${row.id}`));
        wrap.append(line);
      });
      return wrap;
    }
    const story = state.storySuggestions;
    if (!story || state.storySuggestionsFor !== detail.expedition.id) {
      state.storySuggestionsFor = detail.expedition.id;
      state.storySuggestions = null;
      fetchJson(PATHS.suggestions(detail.expedition.id))
        .then((payload) => { state.storySuggestions = payload?.story || []; state.suggestions = payload; state.suggestionsFor = detail.expedition.id; })
        .catch(() => { state.storySuggestions = []; })
        .finally(() => renderFind());
      wrap.append(node('p', 'expedition-muted', 'Looking for the story\'s places…'));
      return wrap;
    }
    wrap.append(candidateList(detail, story, (row) => row.purpose,
      'Every chapter and discovery of this story is already on the itinerary.'));
    return wrap;
  }

  function findThemes(detail) {
    const wrap = node('div');
    const themes = state.catalog?.themes || [];
    const label = node('label', 'expedition-field');
    label.append(node('span', '', 'Theme'));
    const choose = node('select');
    choose.name = 'find_theme';
    choose.dataset.focus = 'find-theme-select';
    const blank = node('option', '', 'Choose a theme');
    blank.value = '';
    choose.append(blank);
    themes.forEach((row) => {
      const option = node('option', '', row.label);
      option.value = row.id;
      option.selected = row.id === (state.themeId || detail.expedition.theme_id);
      choose.append(option);
    });
    state.themeId ||= detail.expedition.theme_id || null;
    choose.addEventListener('change', () => {
      state.themeId = choose.value || null;
      state.focus = 'find-theme-select';
      renderFind();
      loadFindTab();
    });
    label.append(choose);
    wrap.append(label);
    if (!state.themeId) return wrap;
    if (!state.theme || state.themeFor !== `${detail.expedition.id}:${state.themeId}`) {
      wrap.append(node('p', 'expedition-muted', 'Finding places…'));
      loadFindTab();
      return wrap;
    }
    if (state.theme.failed) { wrap.append(node('p', 'expedition-muted', 'Theme places are unavailable right now.')); return wrap; }
    wrap.append(node('p', 'expedition-muted', state.theme.theme?.summary || ''));
    const purpose = { type: 'sightseeing', theme: state.themeId };
    wrap.append(candidateList(detail, state.theme.candidates || [], () => purpose,
      state.theme.theme?.select?.acquisition
        ? 'No documented places match your current shortages.'
        : 'No documented places match this theme.'));
    return wrap;
  }

  function findMaterials(detail) {
    const wrap = node('div');
    const found = state.materials;
    if (!found || state.materialsFor !== detail.expedition.id) {
      wrap.append(node('p', 'expedition-muted', 'Checking your Engineering shortages…'));
      return wrap;
    }
    if (found.failed || found.state === 'knowledge_unavailable' || found.state === 'unavailable') {
      wrap.append(node('p', 'expedition-muted', 'Material planning is unavailable right now.'));
      return wrap;
    }
    if (found.state === 'no_shortages') {
      wrap.append(node('p', 'expedition-muted', 'Your active Engineering builds are not short of anything.'));
      return wrap;
    }
    if (found.inventory_state && found.inventory_state !== 'verified_local') {
      wrap.append(node('p', 'expedition-note-line',
        'Your Materials record is incomplete, so these are documented sources, not confirmed shortages.'));
    }
    const purposeFor = (row) => ({
      type: 'acquisition',
      materials: row.materials.map((m) => ({ material_id: m.material_id, name: m.name })),
      activities: row.activities,
      scope: found.scope || 'all',
    });
    wrap.append(candidateList(detail, found.destinations || [], purposeFor,
      'No documented place serves your shortages; see the methods below.'));
    if (found.conditional?.length) {
      const list = node('ul', 'expedition-conditions');
      found.conditional.forEach((row) => {
        const item = node('li', '');
        item.append(node('span', 'expedition-candidate-name', row.name));
        item.append(node('span', 'expedition-meta', row.materials.map((m) => m.name).join(', ')));
        item.append(node('span', 'expedition-muted', row.note));
        list.append(item);
      });
      wrap.append(drawer(`Not tied to a place (${found.conditional.length})`, list));
    }
    return wrap;
  }

  function findAlong(detail) {
    const wrap = node('div');
    const found = state.suggestions;
    if (!found || state.suggestionsFor !== detail.expedition.id) {
      wrap.append(node('p', 'expedition-muted', 'Checking the straight lines between your stops…'));
      return wrap;
    }
    const along = found.along_the_way;
    if (!along) { wrap.append(node('p', 'expedition-muted', 'Suggestions are unavailable right now.')); return wrap; }
    if (!along.legs_checked) {
      wrap.append(node('p', 'expedition-muted',
        'Add at least one stop with a known position, and come back once your position is known, to see places along the way.'));
      return wrap;
    }
    wrap.append(node('p', 'expedition-muted', along.rule));
    if (along.thematic.length) {
      wrap.append(node('h6', '', 'Fits this expedition'));
      wrap.append(candidateList(detail, along.thematic, null, ''));
    }
    wrap.append(node('h6', '', 'Also near your route'));
    wrap.append(candidateList(detail, along.geographic, null, 'Nothing documented lies close to your route.'));
    if (along.stops_without_position) {
      wrap.append(node('p', 'expedition-note-line',
        `${along.stops_without_position} stop${along.stops_without_position === 1 ? ' has' : 's have'} no documented position, so the legs around ${along.stops_without_position === 1 ? 'it are' : 'them are'} not checked.`));
    }
    if (found.related?.length) {
      wrap.append(node('h6', '', 'Connected to your stops'));
      wrap.append(candidateList(detail, found.related, null, ''));
    }
    return wrap;
  }

  function findSearch(detail) {
    const wrap = node('div');
    const label = node('label', 'expedition-field');
    label.append(node('span', '', 'Place or system'));
    const input = node('input');
    input.type = 'search';
    input.name = 'find_search';
    input.dataset.focus = 'find-search';
    input.placeholder = 'Jameson Memorial, HIP 12099, Sol…';
    input.value = state.searchQuery || '';
    label.append(input);
    wrap.append(label);
    const results = node('div', 'expedition-search-results');
    wrap.append(results);
    const show = () => {
      results.replaceChildren();
      const found = state.searchResults;
      if (!found || !(state.searchQuery || '').trim() || state.searchQuery.trim().length < 2) return;
      results.append(candidateList(detail, found.places || [], null, 'No documented place matches.'));
      const system = found.system;
      if (system?.name) {
        const line = node('p', 'expedition-order-line');
        line.append(node('span', '', system.documented_position
          ? `The system ${system.name}`
          : `${system.name}: no documented position, so its distances will be unknown`));
        line.append(button('Add this system', 'cmd-btn--quiet', () => mutate(
          'POST', PATHS.stops(detail.expedition.id), { system: system.name }, 'That system could not be added.', 'find-search',
        ), 'add-system'));
        results.append(line);
      }
    };
    let timer = null;
    input.addEventListener('input', () => {
      state.searchQuery = input.value;
      clearTimeout(timer);
      timer = setTimeout(() => {
        const query = input.value.trim();
        if (query.length < 2) { state.searchResults = null; show(); return; }
        fetchJson(PATHS.search(query))
          .then((payload) => { if (state.searchQuery.trim() === query) { state.searchResults = payload; show(); } })
          .catch(() => { state.searchResults = null; show(); });
      }, 250);
    });
    show();
    return wrap;
  }

  /* ── Story ──────────────────────────────────────────────────────────── */

  function storyReader(detail) {
    const story = detail.story;
    const narrative = state.narrative;
    const section = node('section', 'expedition-story');
    section.setAttribute('aria-labelledby', 'expedition-story-title');
    const heading = node('h5', '', story.title);
    heading.id = 'expedition-story-title';
    section.append(heading, node('p', 'expedition-muted', story.summary));
    if (!narrative) {
      section.append(node('p', 'expedition-muted', 'The story text is unavailable right now.'));
      return section;
    }
    section.append(passage('Introduction', narrative.introduction, { open: story.read === 0 && !state.openChapter }));
    const list = node('ol', 'expedition-chapters');
    story.chapters.forEach((chapter) => {
      const full = narrative.chapters.find((c) => c.id === chapter.id) || {};
      list.append(chapterItem(detail, chapter, full));
    });
    section.append(list);
    if (narrative.discoveries?.length) {
      const extra = node('div', 'expedition-discoveries');
      extra.append(node('h6', '', 'Optional discoveries'));
      narrative.discoveries.forEach((item, index) => {
        const box = node('div', 'expedition-discovery');
        box.append(node('p', 'expedition-candidate-name', item.title || item.place_name));
        const inTrip = story.discoveries?.[index]?.stop_id;
        box.append(node('p', 'expedition-meta', `${item.place_name}${inTrip ? ' · on the itinerary' : ''}`));
        box.append(passage('Read', item, {}));
        if (!inTrip) {
          box.append(button('Add to expedition', 'cmd-btn--quiet', () => mutate(
            'POST', PATHS.stops(detail.expedition.id),
            { place_id: item.place, purposes: [{ type: 'discovery', narrative: narrative.id }] },
            'That stop could not be added.', `discovery-${item.place}`,
          ), `discovery-${item.place}`));
        }
        extra.append(box);
      });
      section.append(extra);
    }
    const conclusion = node('div', 'expedition-conclusion');
    conclusion.append(node('h6', '', narrative.conclusion?.title || 'Conclusion'));
    if (story.complete) conclusion.append(passageBody(narrative.conclusion));
    else conclusion.append(node('p', 'expedition-muted', 'The conclusion opens when every chapter has been read, reached or skipped.'));
    section.append(conclusion);
    return section;
  }

  function passageBody(item) {
    const body = node('div', 'expedition-passage');
    if (item?.text) body.append(node('p', 'expedition-passage-text', item.text));
    else body.append(node('p', 'expedition-muted', 'Hidden by spoiler protection.'));
    const meta = [EVIDENCE_TEXT[item?.evidence] || item?.evidence, item?.uncertain ? 'includes uncertainty' : null]
      .filter(Boolean).join(' · ');
    if (meta) body.append(node('p', 'expedition-meta', meta));
    const sources = sourcesLine(item?.sources);
    if (sources) body.append(sources);
    return body;
  }

  function passage(label, item, { open = false }) {
    return drawer(item?.title ? `${label}: ${item.title}` : label, passageBody(item), { open, cls: 'expedition-passage-drawer' });
  }

  function chapterItem(detail, chapter, full) {
    const item = node('li', 'expedition-chapter');
    item.id = `expedition-chapter-${chapter.id}`;
    const head = node('div', 'expedition-chapter-head');
    head.append(node('span', 'expedition-chapter-title', `${chapter.position}. ${chapter.title}`));
    const badges = node('span', 'expedition-badges');
    if (chapter.read) badges.append(chip('Read', 'done'));
    const place = {
      reached: ['Place reached', 'done'], completed: ['Marked complete', 'done'], skipped: ['Skipped', 'skipped'],
      approached: ['Approached', 'partial'], in_system: ['In the system', 'partial'],
      not_in_expedition: ['Not on the itinerary', 'skipped'],
    }[chapter.stop_status];
    if (place) badges.append(chip(place[0], place[1]));
    head.append(badges);
    item.append(head, node('p', 'expedition-meta', chapter.place_name), node('p', 'expedition-teaser', chapter.teaser));
    const hidden = chapter.spoiler_hidden && !state.revealed?.[chapter.id];
    const open = state.openChapter === chapter.id;
    const read = node('details', 'expedition-drawer expedition-chapter-text');
    if (open) read.open = true;
    const summary = node('summary', '', hidden ? 'Contains spoilers' : 'Read the chapter');
    summary.dataset.focus = `chapter-${chapter.id}`;
    read.append(summary);
    if (hidden) {
      read.append(node('p', 'expedition-muted', 'This chapter tells how the story ends. Spoiler protection is on in your Galactic Intelligence settings.'));
      read.append(button('Show this chapter', 'cmd-btn--quiet', async () => {
        const reader = await fetchJson(PATHS.narrative(detail.story.id, true)).catch(() => null);
        const revealed = reader?.narrative?.chapters?.find((c) => c.id === chapter.id);
        if (!revealed) { state.message = 'The chapter could not be opened.'; render(); return; }
        state.revealed = { ...(state.revealed || {}), [chapter.id]: revealed };
        state.openChapter = chapter.id;
        state.focus = `chapter-${chapter.id}`;
        render();
      }, `reveal-${chapter.id}`));
    } else {
      const shown = state.revealed?.[chapter.id] || full;
      read.append(passageBody(shown));
      if (shown.connections?.length) {
        const links = node('ul', 'expedition-connections');
        shown.connections.forEach((link) => {
          const row = node('li');
          row.append(node('span', 'expedition-candidate-name', link.subject?.name || link.entity), node('span', '', link.text));
          links.append(row);
        });
        read.append(node('h6', '', 'Connections'), links);
      }
      read.append(button(chapter.read ? 'Mark as unread' : 'Mark as read', 'cmd-btn--quiet', () => mutate(
        'PUT', PATHS.chapter(detail.expedition.id, detail.story.id, chapter.id), { read: !chapter.read },
        'The chapter could not be marked.', `chapter-${chapter.id}`,
      ), `mark-${chapter.id}`));
    }
    read.addEventListener('toggle', () => { if (read.open) state.openChapter = chapter.id; });
    item.append(read);
    return item;
  }

  function moments(detail) {
    const section = node('section', 'expedition-moments');
    section.setAttribute('aria-labelledby', 'expedition-moments-title');
    const heading = node('h5', '', 'Story moments');
    heading.id = 'expedition-moments-title';
    section.append(heading, node('p', 'expedition-muted',
      'What your Journal unlocked this session. Shown only here: OmniCOVAS does not interrupt your flight.'));
    const list = node('ul', 'expedition-moment-list');
    detail.opportunities.forEach((offer) => {
      const item = node('li', 'expedition-moment');
      item.append(node('span', 'expedition-kicker', offer.stage_label));
      item.append(node('p', 'expedition-candidate-name', offer.chapter?.title || offer.narrative?.title || ''));
      item.append(node('p', 'expedition-teaser', offer.teaser));
      if (offer.stage === 'approach') {
        item.append(node('p', 'expedition-muted', 'You are near this place; the Journal has not shown you at it.'));
      }
      const actions = node('div', 'expedition-actions');
      if (offer.chapter?.id) {
        actions.append(button('Read', 'cmd-btn--quiet', () => {
          state.openChapter = offer.chapter.id;
          state.focus = `chapter-${offer.chapter.id}`;
          render();
          document.getElementById(`expedition-chapter-${offer.chapter.id}`)?.scrollIntoView?.({ block: 'nearest' });
        }));
      }
      actions.append(button('Dismiss', 'cmd-btn--quiet', async () => {
        await call(() => sendJson('POST', PATHS.dismiss(offer.opportunity_id)), 'That moment could not be dismissed.');
        state.focus = 'expedition-moments';
        await loadDetail();
      }));
      item.append(actions);
      list.append(item);
    });
    section.append(list);
    return section;
  }

  function preflight(detail) {
    const section = node('section', 'expedition-preflight');
    section.setAttribute('aria-labelledby', 'expedition-preflight-title');
    const heading = node('h5', '', 'Before you go');
    heading.id = 'expedition-preflight-title';
    section.append(heading);
    const ship = detail.preflight?.ship || {};
    const facts = node('dl', 'expedition-where');
    facts.append(node('dt', '', 'Ship'), node('dd', '', ship.ship_type || 'Not observed yet'));
    facts.append(node('dt', '', 'Fuel scoop'), node('dd', '', ship.fuel_scoop?.label || 'Unknown'));
    facts.append(node('dt', '', 'Jump range'), node('dd', '', Number.isFinite(ship.max_jump_range_ly)
      ? `${ship.max_jump_range_ly} ly maximum (from your loadout)`
      : 'Unknown'));
    section.append(facts);
    const rows = (detail.preflight?.stops || []).filter((row) => row.requirements.length);
    if (rows.length) {
      const list = node('ul', 'expedition-requirements');
      rows.forEach((row) => row.requirements.forEach((req) => {
        const item = requirementItem(req);
        item.prepend(node('span', 'expedition-candidate-name', row.name));
        list.append(item);
      }));
      section.append(list);
    } else {
      section.append(node('p', 'expedition-muted', 'Nothing is documented as needed for these stops.'));
    }
    const manual = detail.preflight?.summary?.manual_stops || 0;
    if (manual) {
      section.append(node('p', 'expedition-note-line', `${manual} stop${manual === 1 ? '' : 's'} cannot be confirmed by the Journal; mark ${manual === 1 ? 'it' : 'them'} complete yourself.`));
    }
    section.append(drawer('About these checks', detail.preflight?.caveat || ''));
    return section;
  }

  function storytelling(detail) {
    const mode = detail.storytelling;
    const section = node('section', 'expedition-storytelling');
    section.setAttribute('aria-labelledby', 'expedition-storytelling-title');
    const heading = node('h5', '', 'Storytelling');
    heading.id = 'expedition-storytelling-title';
    section.append(heading);
    if (mode) {
      section.append(node('p', '', modeText(mode)));
      section.append(node('p', 'expedition-muted', mode.note));
    }
    if (typeof openSettings === 'function') {
      section.append(button('Storytelling settings', 'cmd-btn--quiet', openSettings, 'story-settings'));
    }
    return section;
  }

  function recap(detail) {
    const section = node('section', 'expedition-recap');
    section.setAttribute('aria-labelledby', 'expedition-recap-title');
    const heading = node('h5', '', 'Journey so far');
    heading.id = 'expedition-recap-title';
    section.append(heading);
    const data = state.recap?.expedition?.id === detail.expedition.id ? state.recap : null;
    if (!data) {
      section.append(button('Show the recap', 'cmd-btn--quiet', async () => {
        state.recap = await fetchJson(PATHS.recap(detail.expedition.id)).catch(() => null);
        if (!state.recap) state.message = 'The recap is unavailable right now.';
        state.focus = 'recap-close';
        render();
      }, 'recap-open'));
      return section;
    }
    const counts = data.counts || {};
    section.append(node('p', '', [
      `${counts.reached || 0} reached`, `${counts.completed || 0} marked complete`,
      `${counts.skipped || 0} skipped`, `${data.chapters_read} of ${data.chapters} chapters read`,
    ].join(' · ')));
    if (data.reached_in_order?.length) {
      const list = node('ol', 'expedition-recap-list');
      data.reached_in_order.forEach((row) => list.append(node('li', '', `${row.name} · ${row.how === 'journal' ? 'Journal' : 'marked by you'}`)));
      section.append(list);
    }
    if (Number.isFinite(data.straight_line_ly)) {
      section.append(node('p', 'expedition-meta', `${distanceText(data.straight_line_ly)} in straight lines between them.`));
    }
    if (data.conclusion?.earned && data.conclusion.text) {
      section.append(node('h6', '', data.conclusion.title || 'Conclusion'), passageBody(data.conclusion));
    }
    section.append(node('p', 'expedition-muted', data.caveat));
    section.append(button('Hide the recap', 'cmd-btn--quiet', () => { state.recap = null; state.focus = 'recap-open'; render(); }, 'recap-close'));
    return section;
  }

  /* Add a destination handed over from the Atlas or Materials. */
  async function addIncoming(incoming, { create: startNew = false } = {}) {
    if (!incoming) return null;
    let purposes = [{ type: 'destination' }];
    if (incoming.fromMaterials && incoming.need) {
      // GKI-08: the shortage and the method the commander chose in Materials,
      // for the build they were planning; relevance is rechecked on every read.
      const { need } = incoming;
      purposes = [{
        type: 'acquisition',
        materials: [{ material_id: need.materialId, name: need.materialName || need.materialId }],
        activities: need.methodId ? [need.methodId] : [],
        scope: need.scope || 'all',
      }];
    } else if (incoming.fromMaterials && incoming.placeId) {
      const found = await fetchJson(PATHS.materials('all')).catch(() => null);
      const row = (found?.destinations || []).find((d) => d.place.id === incoming.placeId);
      if (row) {
        purposes = [{
          type: 'acquisition',
          materials: row.materials.map((m) => ({ material_id: m.material_id, name: m.name })),
          activities: row.activities,
          scope: 'all',
        }];
      }
    }
    const target = incoming.placeId ? { place_id: incoming.placeId } : { system: incoming.system };
    if (startNew || !state.selectedId) {
      return create({ entry: incoming.fromMaterials ? 'goal' : 'destination', ...target, stops: [] }, 'expedition-name')
        .then(async (detail) => {
          if (detail && purposes[0].type !== 'destination') {
            await mutate('POST', PATHS.stops(detail.expedition.id), { ...target, purposes }, 'That stop could not be added.');
          }
          return detail;
        });
    }
    const added = await mutate('POST', PATHS.stops(state.selectedId), { ...target, purposes }, 'That stop could not be added.', 'expedition-name');
    if (added) {
      state.message = `${incoming.label} is on the itinerary of ${state.detail?.expedition?.name || 'this expedition'}.`;
      render();
    }
    return added;
  }

  render();
  return {
    element: root,
    load,
    open,
    addIncoming,
    refresh: loadDetail,
    get state() { return state; },
  };
}
