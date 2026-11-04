// Galactic Atlas workstation (GKI-03): browse documented places, people,
// organizations and events, read their sourced history, follow connections and
// hand a destination to Navigation or a material to Engineering.
// ADR 0003: every value is rendered with textContent. Reference knowledge is
// never presented as the Commander's own observation; relevance to builds comes
// from the Engineering portfolio and stays unknown when inventory is unknown.
import {
  CATEGORIES, categoryCounts, certaintyText, claimsByTopic, evidenceText,
  filterSubjects, groupConnections, kindLabel, locationLines, matchSupportText,
  materialsIntent, navigationIntent, precisionText, relevanceText, rememberAtlas,
} from '../view-models/galactic-atlas.js';

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

function sourceIndex(entry) {
  return new Map((entry?.sources || []).map((source) => [source.id, source]));
}

function citation(entry, ids) {
  const index = sourceIndex(entry);
  const names = [...new Set(ids || [])].map((id) => index.get(id)?.name).filter(Boolean);
  return names.length ? node('span', 'atlas-cite', names.join(' · ')) : null;
}

function claimItem(entry, claim) {
  const item = node('li', 'atlas-claim');
  item.append(node('span', 'atlas-claim-text', claim.text));
  const meta = node('span', 'atlas-claim-meta', evidenceText(claim.evidence));
  const cite = citation(entry, claim.sources);
  item.append(meta);
  if (cite) item.append(cite);
  return item;
}

function sourceList(entry) {
  const details = node('details', 'atlas-sources');
  details.append(node('summary', '', `Sources (${(entry.sources || []).length})`));
  const list = node('ul', 'atlas-source-list');
  (entry.sources || []).forEach((source) => {
    const item = node('li');
    if (/^https:\/\//.test(source.url)) {
      const link = node('a', '', source.name);
      link.href = source.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      item.append(link);
    } else {
      item.append(node('span', '', source.name));
    }
    const meta = [
      source.revision ? `revision ${source.revision.revision_id}` : null,
      `reviewed ${source.accessed}`,
      source.reuse === 'not_retrieved' ? 'not retrieved' : null,
      `source licence: ${source.licence}`,
    ].filter(Boolean).join(' · ');
    item.append(node('span', 'atlas-source-meta', meta));
    list.append(item);
  });
  details.append(list);
  return details;
}

/* `recordCard(entry)` (GKI-07, optional) returns the Commander Chronicle's
   "Your record" card for an entry: the Commander's own evidence, kept beside
   the reference record and never mixed into it. */
export function createGalacticAtlas({ state, fetchJson, startTransfer, recordCard = null }) {
  const root = node('section', 'atlas');
  root.setAttribute('aria-label', 'Galactic Atlas');
  const api = { element: root, select, render };

  function load() {
    if (state.subjects) return;
    /* The request lives in the shared state, not this instance: Intel can
       rebuild the Atlas while it is in flight (a handoff arriving as Intel
       re-renders), and the instance on screen must be the one that renders. */
    state.loading ||= fetchJson('/knowledge/atlas')
      .then((payload) => { state.subjects = payload.subjects || []; state.error = null; })
      .catch((error) => {
        // The technical reason stays in diagnostics; Commanders get a plain message.
        state.error = error?.message || 'request failed';
        console.warn('Galactic Atlas unavailable:', error);
      })
      .finally(() => {
        state.loading = null;
        if (!state.selected && state.subjects?.length) state.selected = state.subjects[0].id;
      });
    state.loading.then(() => {
      render();
      if (state.selected) select(state.selected, { focus: false });
    });
  }

  function loadEntry(id) {
    state.entries ||= {};
    if (state.entries[id]) return Promise.resolve(state.entries[id]);
    // Shared like the subject list, so a rebuilt Atlas waits on the same request.
    state.inflight ||= {};
    state.inflight[id] ||= fetchJson(`/knowledge/atlas/${encodeURIComponent(id)}`)
      .then((entry) => { state.entries[id] = entry; return entry; })
      .catch(() => { state.entries[id] = { missing: true }; return state.entries[id]; })
      .finally(() => { delete state.inflight[id]; });
    return state.inflight[id];
  }

  function loadRelevance(id) {
    state.relevance ||= {};
    if (state.relevance[id]) return;
    state.relevance[id] = { loading: true };
    fetchJson(`/knowledge/atlas/${encodeURIComponent(id)}/relevance`)
      .then((payload) => { state.relevance[id] = payload; })
      .catch(() => { state.relevance[id] = { state: 'error' }; })
      .finally(() => {
        // Replace only the relevance panel so focus inside the entry is kept.
        const entry = state.entries?.[id];
        if (state.selected !== id || !entry) return;
        root.querySelectorAll('.atlas-relevance').forEach((card) => card.replaceWith(relevanceCard(entry)));
      });
  }

  /* Select an entry. ``from`` records where the Commander came from so the
     inspector offers a way back along the relationship they followed. */
  function select(id, { focus = true, from = null } = {}) {
    if (!id) return;
    if (from && from !== id) {
      state.trail = [...(state.trail || []), from].slice(-12);
    }
    state.selected = id;
    rememberAtlas(state);
    renderBrowserSelection();
    loadEntry(id).then(() => {
      if (state.selected !== id) return;
      renderInspector();
      if (focus) root.querySelector('#atlas-entry-title')?.focus?.();
    });
    renderInspector();
  }

  function back() {
    const trail = [...(state.trail || [])];
    const previous = trail.pop();
    state.trail = trail;
    if (previous) select(previous);
  }

  /* ── Browser ──────────────────────────────────────────────────────── */

  function browser() {
    const aside = node('nav', 'atlas-browser');
    aside.setAttribute('aria-label', 'Atlas subjects');
    aside.append(node('p', 'atlas-browser-title', 'Galactic Atlas · offline reference'));

    const counts = categoryCounts(state.subjects);
    const tabs = node('div', 'atlas-category-tabs');
    tabs.setAttribute('role', 'tablist');
    tabs.setAttribute('aria-label', 'Atlas categories');
    const searching = Boolean((state.search || '').trim());
    CATEGORIES.forEach(([id, label]) => {
      const tab = button(`${label} ${counts[id]}`, 'atlas-category-tab', () => {
        state.category = id;
        state.search = '';
        rememberAtlas(state);
        render();
        root.querySelector(`.atlas-category-tab[data-category="${id}"]`)?.focus();
      });
      tab.dataset.category = id;
      tab.setAttribute('role', 'tab');
      tab.setAttribute('aria-selected', String(!searching && (state.category || 'all') === id));
      tab.tabIndex = !searching && (state.category || 'all') === id ? 0 : -1;
      tab.addEventListener('keydown', (event) => {
        if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
        event.preventDefault();
        const all = [...tabs.querySelectorAll('.atlas-category-tab')];
        const step = event.key === 'ArrowRight' ? 1 : -1;
        all[(all.indexOf(tab) + step + all.length) % all.length].click();
      });
      tabs.append(tab);
    });
    aside.append(tabs);

    const label = node('label', 'atlas-search-label');
    label.append(node('span', 'atlas-search-text', 'Find in the Atlas'));
    const search = node('input', 'atlas-search');
    search.type = 'search';
    search.name = 'atlas_search';
    search.placeholder = 'Name, system, alias or topic';
    search.value = state.search || '';
    search.addEventListener('input', () => {
      state.search = search.value;
      rememberAtlas(state);
      renderList();
    });
    search.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        root.querySelector('.atlas-subject')?.focus();
      }
    });
    label.append(search);
    aside.append(label);
    aside.append(node('p', 'atlas-count'));
    const list = node('ul', 'atlas-subjects');
    aside.append(list);
    return aside;
  }

  function renderList() {
    const list = root.querySelector('.atlas-subjects');
    const count = root.querySelector('.atlas-count');
    if (!list) return;
    const term = (state.search || '').trim();
    const rows = filterSubjects(state.subjects, { category: state.category || 'all', search: term });
    root.querySelectorAll('.atlas-category-tab').forEach((tab) => {
      const active = !term && (state.category || 'all') === tab.dataset.category;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    count.textContent = term
      ? `${rows.length} match${rows.length === 1 ? '' : 'es'} across all categories`
      : `${rows.length} subject${rows.length === 1 ? '' : 's'}`;
    list.replaceChildren(...rows.map((subject) => {
      const item = node('li');
      const entry = button('', 'atlas-subject', () => select(subject.id));
      entry.dataset.entityId = subject.id;
      entry.setAttribute('aria-pressed', String(state.selected === subject.id));
      entry.append(node('span', 'atlas-subject-name', subject.name));
      const meta = [kindLabel(subject.kind), subject.system].filter(Boolean).join(' · ');
      entry.append(node('span', 'atlas-subject-meta', meta));
      const tags = node('span', 'atlas-subject-tags');
      if (subject.destination) tags.append(node('span', 'atlas-tag', 'Destination'));
      if (subject.practical) tags.append(node('span', 'atlas-tag atlas-tag-practical', 'Materials'));
      if (tags.childElementCount) entry.append(tags);
      entry.addEventListener('keydown', (event) => {
        if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
        event.preventDefault();
        const all = [...list.querySelectorAll('.atlas-subject')];
        const next = all[all.indexOf(entry) + (event.key === 'ArrowDown' ? 1 : -1)];
        (next || (event.key === 'ArrowUp' ? root.querySelector('.atlas-search') : null))?.focus();
      });
      item.append(entry);
      return item;
    }));
    if (!rows.length) {
      list.append(node('li', 'atlas-empty', term
        ? 'Nothing in the Atlas matches that search.'
        : 'No subjects in this category yet.'));
    }
  }

  function renderBrowserSelection() {
    root.querySelectorAll('.atlas-subject').forEach((entry) => {
      entry.setAttribute('aria-pressed', String(entry.dataset.entityId === state.selected));
    });
  }

  /* ── Inspector ────────────────────────────────────────────────────── */

  function connectionRow(entry, row) {
    const item = node('li', 'atlas-connection');
    const target = row.entity;
    if (target.atlas) {
      const link = button(target.name, 'atlas-link', () => select(target.id, { from: entry.entity.id }));
      link.dataset.entityId = target.id;
      item.append(link);
    } else {
      item.append(node('span', 'atlas-connection-name', target.name));
    }
    item.append(node('span', 'atlas-connection-kind', kindLabel(target.kind)));
    const details = [row.role, row.note].filter(Boolean).join(' · ');
    if (details) item.append(node('span', 'atlas-connection-note', details));
    if (row.type === 'historically_controlled_by') {
      item.append(node('span', 'atlas-connection-note atlas-historical',
        row.period || 'Historical record; not current control.'));
    }
    const certainty = certaintyText(row.certainty);
    if (certainty) item.append(node('span', `atlas-certainty atlas-certainty-${row.certainty}`, certainty));
    const cite = citation(entry, row.sources);
    if (cite) item.append(cite);
    return item;
  }

  function locationCard(entry) {
    const location = entry.location;
    const card = node('section', 'atlas-card atlas-location');
    card.setAttribute('aria-labelledby', 'atlas-location-title');
    const heading = node('h4', '', 'Location');
    heading.id = 'atlas-location-title';
    card.append(heading);
    const list = node('dl', 'atlas-location-lines');
    locationLines(location).forEach(([label, value]) => {
      list.append(node('dt', '', label), node('dd', '', value));
    });
    card.append(list);
    card.append(node('p', `atlas-precision atlas-precision-${location.precision}`, precisionText(location)));
    if (location.note) card.append(node('p', 'atlas-muted', location.note));
    const action = button('Open in Navigation', 'ocv-btn atlas-action', () => {
      const intent = navigationIntent(entry);
      if (intent) startTransfer(intent);
    });
    action.name = 'atlas_open_navigation';
    card.append(action);
    card.append(node('p', 'atlas-muted',
      'Navigation shows the destination for review. Plotting stays with you in Elite Dangerous; no route or travel time is invented.'));
    const identity = node('details', 'atlas-identity');
    identity.append(node('summary', '', 'Location identity'));
    const ids = node('dl', 'atlas-location-lines');
    [
      ['SystemAddress', location.system_address],
      ['StarPos', location.star_pos ? location.star_pos.join(', ') : null],
      ['MarketID', location.market_id],
      ['BodyID', location.body_id],
    ].filter(([, value]) => value != null).forEach(([label, value]) => {
      ids.append(node('dt', '', label), node('dd', '', value));
    });
    if (!ids.childElementCount) ids.append(node('dt', '', 'Identifiers'), node('dd', '', 'None documented'));
    identity.append(ids);
    const support = matchSupportText(entry.match_support);
    if (support) identity.append(node('p', 'atlas-muted', support));
    card.append(identity);
    return card;
  }

  function relevanceCard(entry) {
    const id = entry.entity.id;
    const payload = state.relevance?.[id];
    const card = node('div', 'atlas-relevance');
    card.setAttribute('aria-live', 'polite');
    if (!payload || payload.loading) {
      card.append(node('p', 'atlas-muted', 'Checking your Engineering builds…'));
      return card;
    }
    if (payload.state === 'error') {
      card.append(node('p', 'atlas-muted', 'Your Engineering builds could not be checked.'));
      return card;
    }
    const tone = relevanceText(payload);
    card.classList.add(`atlas-tone-${tone.tone}`);
    card.append(node('strong', '', tone.label));
    card.append(node('p', '', payload.explanation));
    (payload.reasons || []).forEach((reason) => {
      card.append(node('p', 'atlas-reason',
        `${reason.build}: ${reason.deficit} ${reason.material.name} short`));
    });
    const held = (payload.materials || []).map((row) => (row.quantity_state === 'observed'
      ? `${row.name}: you hold ${row.owned}`
      : `${row.name}: holding not checked`));
    if (held.length) card.append(node('p', 'atlas-muted', held.join(' · ')));
    return card;
  }

  function practicalCard(entry, activity) {
    const card = node('section', 'atlas-card atlas-practical');
    card.append(node('h4', '', activity.name));
    card.append(node('p', 'atlas-summary', activity.summary));
    if (activity.steps?.length) {
      const steps = node('ol', 'atlas-steps');
      activity.steps.forEach((step) => steps.append(node('li', '', step.text)));
      card.append(steps);
    }
    if (activity.materials?.length) {
      card.append(node('h5', '', 'Documented materials'));
      const list = node('ul', 'atlas-materials');
      activity.materials.forEach((material) => {
        const item = node('li', 'atlas-material');
        item.append(node('span', 'atlas-material-name', material.name));
        const grade = material.inventory?.grade ? `Grade ${material.inventory.grade} · encoded` : 'Encoded';
        item.append(node('span', 'atlas-material-meta', grade));
        const show = button('Show in Materials', 'ocv-btn-ghost atlas-link-action', () => {
          const intent = materialsIntent(entry, material);
          if (intent) startTransfer(intent);
        });
        show.dataset.material = material.inventory?.symbol || '';
        item.append(show);
        list.append(item);
      });
      card.append(list);
      card.append(relevanceCard(entry));
    }
    claimsByTopic(activity.claims).forEach((group) => {
      card.append(node('h5', '', group.label));
      const list = node('ul', 'atlas-claims');
      group.claims.forEach((claim) => list.append(claimItem(entry, claim)));
      card.append(list);
    });
    return card;
  }

  function inspector() {
    const article = node('article', 'atlas-inspector');
    article.setAttribute('aria-label', 'Atlas entry');
    return article;
  }

  function renderInspector() {
    const article = root.querySelector('.atlas-inspector');
    if (!article) return;
    const entry = state.entries?.[state.selected];
    if (!state.selected) {
      article.replaceChildren(node('p', 'atlas-empty', 'Choose a subject to read its history.'));
      return;
    }
    if (!entry) {
      article.replaceChildren(node('p', 'atlas-empty', 'Loading the entry…'));
      return;
    }
    if (entry.missing) {
      article.replaceChildren(node('p', 'atlas-empty', 'This entry could not be loaded.'));
      return;
    }
    const content = [];
    const header = node('header', 'atlas-header');
    if (state.trail?.length) {
      const previous = state.entries[state.trail[state.trail.length - 1]];
      const backButton = button(`Back to ${previous?.entity?.name || 'previous entry'}`, 'ocv-btn-ghost atlas-back', back);
      backButton.name = 'atlas_back';
      header.append(backButton);
    }
    if (entry.parents?.length) {
      const crumbs = node('p', 'atlas-breadcrumb');
      entry.parents.slice().reverse().forEach((parent, index) => {
        if (index) crumbs.append(node('span', 'atlas-crumb-sep', ' › '));
        crumbs.append(button(parent.name, 'atlas-link', () => select(parent.id, { from: entry.entity.id })));
      });
      header.append(crumbs);
    }
    header.append(node('p', 'atlas-eyebrow',
      [kindLabel(entry.entity.kind), entry.entity.attributes?.period].filter(Boolean).join(' · ')));
    const title = node('h3', 'atlas-title', entry.entity.name);
    title.id = 'atlas-entry-title';
    title.tabIndex = -1;
    header.append(title);
    if (entry.entity.aliases?.length) {
      header.append(node('p', 'atlas-muted', `Also known as ${entry.entity.aliases.join(', ')}`));
    }
    header.append(node('p', 'atlas-summary', entry.entity.summary));
    const why = node('div', 'atlas-why');
    why.append(node('strong', '', 'Why it matters'));
    why.append(node('p', '', entry.entity.attributes?.significance || ''));
    header.append(why);
    content.push(header);

    const columns = node('div', 'atlas-columns');
    const story = node('div', 'atlas-story');
    claimsByTopic(entry.entity.claims).forEach((group) => {
      const section = node('section', `atlas-card atlas-topic atlas-topic-${group.id}`);
      section.append(node('h4', '', group.label));
      const list = node('ul', 'atlas-claims');
      group.claims.forEach((claim) => list.append(claimItem(entry, claim)));
      section.append(list);
      story.append(section);
    });
    if (entry.reference) {
      const section = node('section', 'atlas-card atlas-reference');
      section.append(node('h4', '', 'Also in Guardian technology'));
      section.append(node('p', 'atlas-muted', entry.reference.summary));
      section.append(node('p', 'atlas-muted',
        'This is the same record the Technology planner uses, so the two never disagree about the place.'));
      story.append(section);
    }
    const groups = groupConnections(entry.connections);
    if (groups.length) {
      const section = node('section', 'atlas-card atlas-connections');
      section.append(node('h4', '', 'Connections'));
      groups.forEach((group) => {
        section.append(node('h5', '', group.label));
        const list = node('ul', 'atlas-connection-list');
        group.rows.forEach((row) => list.append(connectionRow(entry, row)));
        section.append(list);
      });
      story.append(section);
    }
    columns.append(story);

    const side = node('div', 'atlas-side');
    const record = recordCard?.(entry);
    if (record) side.append(record);
    if (entry.location) side.append(locationCard(entry));
    entry.practical?.forEach((activity) => side.append(practicalCard(entry, activity)));
    if (entry.practical?.length) loadRelevance(entry.entity.id);
    const nearby = (entry.related_destinations || []).filter((row) => row.id !== entry.entity.id);
    if (nearby.length) {
      const section = node('section', 'atlas-card atlas-destinations');
      section.append(node('h4', '', 'Connected destinations'));
      const list = node('ul', 'atlas-connection-list');
      nearby.slice(0, 8).forEach((row) => {
        const item = node('li', 'atlas-connection');
        const known = (state.subjects || []).some((subject) => subject.id === row.id);
        item.append(known
          ? button(row.name, 'atlas-link', () => select(row.id, { from: entry.entity.id }))
          : node('span', 'atlas-connection-name', row.name));
        item.append(node('span', 'atlas-connection-kind', row.system));
        if (row.through) item.append(node('span', 'atlas-connection-note', `Through ${row.through.name}`));
        list.append(item);
      });
      section.append(list);
      side.append(section);
    }
    if (side.childElementCount) columns.append(side);
    content.push(columns);
    content.push(sourceList(entry));
    article.replaceChildren(...content);
  }

  function render() {
    if (state.error && !state.subjects) {
      root.replaceChildren(node('p', 'atlas-empty',
        'The Galactic Atlas is unavailable right now: its bundled place and history knowledge could not be read. The rest of Intel still works.'));
      return;
    }
    if (!state.subjects) {
      root.replaceChildren(node('p', 'atlas-empty', 'Loading the Galactic Atlas…'));
      load();
      return;
    }
    if (!state.subjects.length) {
      root.replaceChildren(node('p', 'atlas-empty', 'Galactic Atlas knowledge is not included in this build.'));
      return;
    }
    const workstation = node('div', 'atlas-workstation');
    workstation.append(browser(), inspector());
    root.replaceChildren(workstation);
    renderList();
    renderInspector();
    if (state.selected && !state.entries?.[state.selected]) select(state.selected, { focus: false });
  }

  render();
  return api;
}
