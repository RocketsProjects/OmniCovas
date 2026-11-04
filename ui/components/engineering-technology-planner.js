// Technology unlock planner (GKI-01): Guardian FSD Booster first.
// ADR 0003: every value is rendered with textContent. Reference knowledge
// (requirements, procedures, sites) and observed Commander data (owned
// counts, unlock evidence) are labelled separately; checklist ticks are the
// Commander's own record and never touch observed inventory.
import {
  CATEGORIES, TRANSACTION_FILTERS, catalogueGroups, categoryCounts, checklistGroups,
  collectText, evidenceText, formatDate, haveText, navigationIntent, offeringLabel,
  originText, readinessSummary, rowStatus, sourcesFor, statusText,
  transactionLabel, unlockStateText,
} from '../view-models/technology-planner.js';

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

function sourceList(plan, ids, summaryText = 'Sources') {
  const sources = sourcesFor(plan, ids);
  const details = node('details', 'tech-sources');
  details.append(node('summary', '', `${summaryText} (${sources.length})`));
  const list = node('ul', 'tech-source-list');
  sources.forEach((source) => {
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
      `source licence: ${source.licence}`,
    ].filter(Boolean).join(' · ');
    item.append(node('span', 'tech-source-meta', meta));
    list.append(item);
  });
  details.append(list);
  return details;
}

function claimList(plan, claims) {
  const list = node('ul', 'tech-claims');
  claims.forEach((claim) => {
    const item = node('li', '', claim.text);
    item.title = evidenceText(claim.evidence);
    list.append(item);
  });
  return list;
}

export function createTechnologyPlanner(controller) {
  const knowledge = controller.knowledge || {};
  const state = controller._technologyState ||= { unlockId: null, selected: null };
  const section = node('section', 'tech-planner');
  section.setAttribute('aria-label', 'Technology unlock planner');

  if (knowledge.loading || (!knowledge.catalog && !knowledge.error)) {
    section.append(node('p', 'tech-empty', 'Loading Guardian technology knowledge…'));
    return section;
  }
  const catalog = knowledge.catalog;
  if (!catalog || catalog.state !== 'available') {
    const reason = catalog?.reason === 'not_included'
      ? 'Technology knowledge is not included in this build. Commander-entered special unlock records below still work.'
      : 'Technology knowledge could not be loaded. Commander-entered special unlock records below still work.';
    section.append(node('p', 'tech-empty', reason));
    return section;
  }

  /* Two panes: the catalogue browser and the selected offering's planner. */
  const workstation = node('div', 'tech-workstation');
  const detail = node('div', 'tech-detail');
  workstation.append(catalogueBrowser(controller, catalog, state), detail);
  section.append(workstation);

  const plan = knowledge.plan;
  if (!plan) {
    detail.append(node('p', 'tech-empty', knowledge.error
      ? 'The plan could not be loaded. Your saved plans were not changed.'
      : 'Loading plan…'));
    return section;
  }

  detail.append(overviewCard(controller, plan), readinessCard(controller, plan, state),
    expeditionCard(controller, plan), aboutCard(plan));
  return section;
}

/* Catalogue browser: category tabs, unlock/per-item filter, search, and every
   variant as its own entry grouped by family. Selection lives on the controller
   so it survives stage changes, route changes and re-renders. */
function catalogueBrowser(controller, catalog, state) {
  const unlocks = catalog.unlocks || [];
  const current = unlocks.find((u) => u.id === state.unlockId);
  state.category ||= current?.category || 'module';
  state.filter ||= 'all';
  state.search ??= '';
  const panel = node('nav', 'tech-catalogue');
  panel.setAttribute('aria-label', 'Guardian technology catalogue');
  panel.append(node('p', 'tech-catalogue-title', 'Guardian technology'));

  const search = node('input', 'tech-search');
  search.type = 'search';
  search.name = 'technology_search';
  search.placeholder = 'Search Guardian technology';
  search.setAttribute('aria-label', 'Search Guardian technology');
  search.value = state.search;
  search.addEventListener('input', () => { state.search = search.value; renderList(); });

  const counts = categoryCounts(unlocks);
  const tabs = node('div', 'tech-category-tabs');
  tabs.setAttribute('role', 'tablist');
  tabs.setAttribute('aria-label', 'Technology category');
  const tabButtons = CATEGORIES.map(([id, label]) => {
    const tab = node('button', 'tech-category-tab', `${label} ${counts[id]}`);
    tab.type = 'button';
    tab.dataset.category = id;
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-selected', String(state.category === id));
    tab.tabIndex = state.category === id ? 0 : -1;
    tab.addEventListener('click', () => { state.category = id; state.filter = 'all'; state.search = ''; search.value = ''; refresh(true); });
    tab.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      const at = CATEGORIES.findIndex(([c]) => c === id);
      const next = CATEGORIES[(at + (event.key === 'ArrowRight' ? 1 : CATEGORIES.length - 1)) % CATEGORIES.length][0];
      state.category = next; state.filter = 'all'; refresh(true);
      panel.querySelector(`.tech-category-tab[data-category="${next}"]`)?.focus();
    });
    return tab;
  });
  tabs.append(...tabButtons);


  const filters = node('div', 'tech-filters');
  filters.setAttribute('role', 'group');
  filters.setAttribute('aria-label', 'Transaction type');
  const list = node('div', 'tech-catalogue-list');
  const count = node('p', 'tech-catalogue-count');
  count.setAttribute('role', 'status');
  panel.append(tabs, search, filters, count, list);

  function renderFilters() {
    const inCategory = unlocks.filter((u) => u.category === state.category);
    const mixed = new Set(inCategory.map((u) => u.transaction)).size > 1;
    filters.hidden = !mixed;
    filters.replaceChildren(...TRANSACTION_FILTERS.map(([id, label]) => {
      const b = node('button', 'tech-filter', label);
      b.type = 'button';
      b.name = `technology_filter_${id}`;
      b.setAttribute('aria-pressed', String(state.filter === id));
      b.addEventListener('click', () => { state.filter = id; refresh(); });
      return b;
    }));
  }
  function renderList() {
    // Search reaches across categories, so a match is never hidden by a tab.
    const searching = state.search.trim().length > 0;
    const mixed = new Set(unlocks.filter((u) => u.category === state.category).map((u) => u.transaction)).size > 1;
    filters.hidden = searching || !mixed;
    const groups = searching
      ? CATEGORIES.flatMap(([id]) => catalogueGroups(unlocks, { category: id, filter: 'all', search: state.search }))
      : catalogueGroups(unlocks, { category: state.category, filter: state.filter });
    const total = groups.reduce((n, g) => n + g.items.length, 0);
    count.textContent = searching
      ? `${total} match${total === 1 ? '' : 'es'} across all categories`
      : `${total} item${total === 1 ? '' : 's'}`;
    list.replaceChildren();
    if (!total) list.append(node('p', 'tech-muted', 'Nothing matches. Clear the search or pick another category.'));
    groups.forEach((group) => {
      const box = node('div', 'tech-family');
      box.append(node('p', 'tech-family-name', group.family));
      const ul = node('ul', 'tech-variants');
      group.items.forEach((unlock) => {
        const li = node('li');
        const b = node('button', 'tech-variant');
        b.type = 'button';
        b.dataset.unlockId = unlock.id;
        b.setAttribute('aria-pressed', String(unlock.id === state.unlockId));
        b.append(node('span', 'tech-variant-name', unlock.variant || offeringLabel(unlock)));
        const tags = node('span', 'tech-variant-tags');
        tags.append(node('span', `tech-tag tech-tag-${unlock.transaction}`, unlock.transaction === 'per_item_purchase' ? 'Per item' : 'Unlock'));
        if (unlock.recipe_conflict) tags.append(node('span', 'tech-tag tech-tag-conflict', 'Sources differ'));
        b.append(tags);
        b.setAttribute('aria-label', `${offeringLabel(unlock)}, ${transactionLabel(unlock.transaction)}${unlock.recipe_conflict ? ', sources differ on the recipe' : ''}`);
        b.addEventListener('click', () => controller.selectTechnology?.(unlock.id));
        li.append(b);
        ul.append(li);
      });
      box.append(ul);
      list.append(box);
    });
  }
  function refresh(focusTab = false) {
    tabButtons.forEach((tab) => {
      const on = tab.dataset.category === state.category;
      tab.setAttribute('aria-selected', String(on));
      tab.tabIndex = on ? 0 : -1;
    });
    renderFilters();
    renderList();
    if (focusTab) panel.querySelector('.tech-category-tab[aria-selected=true]')?.focus?.();
  }
  renderFilters();
  renderList();
  return panel;
}

function overviewCard(controller, plan) {
  const card = node('section', 'tech-overview');
  card.setAttribute('aria-labelledby', 'tech-unlock-title');
  const module = plan.module || {};
  const classes = module.attributes?.classes || [];
  const perItem = plan.transaction === 'per_item_purchase';
  const category = { module: 'Guardian module', weapon: 'Guardian weapon', fighter: 'Guardian fighter' }[plan.unlock.category] || 'Guardian technology';
  card.append(node('p', 'tech-eyebrow', `${category} · ${transactionLabel(plan.transaction)}`));
  const title = node('h3', 'tech-title', module.name || offeringLabel(plan.unlock));
  title.id = 'tech-unlock-title';
  title.tabIndex = -1;
  card.append(title, node('p', 'tech-summary', module.summary || plan.unlock.summary));
  if (module.attributes?.summary_line) card.append(node('p', 'tech-benefit', module.attributes.summary_line));
  (plan.equipment_needs || []).forEach((need) => card.append(node('p', 'tech-needs', `Needs a ${need.name} to use: ${need.summary}`)));

  const status = unlockStateText(plan.unlock_state);
  const unlockLine = node('div', `tech-unlock-state tech-tone-${status.tone}`);
  unlockLine.setAttribute('role', 'status');
  unlockLine.append(node('strong', '', status.label), node('span', '', status.detail));
  card.append(unlockLine);

  const broker = plan.unlock.broker || {};
  const facts = node('ul', 'tech-facts');
  const factRows = perItem
    ? [['Per-item purchase', 'Each hand-in gives one pre-engineered weapon in storage. A second copy costs the full recipe again.'],
       ['Where', `${broker.name || 'Guardian Technology Broker'}. ${broker.claims?.[0]?.text || ''}`.trim()]]
    : [['One-time unlock', 'Hand in the requirements once. After that, the equipment costs credits only in Outfitting.'],
       ['Where', 'Any Guardian Technology Broker. Every item must be handed in together.']];
  factRows.forEach(([label, text]) => {
    const item = node('li');
    item.append(node('strong', '', label), node('span', '', text));
    facts.append(item);
  });
  card.append(facts);
  if (perItem) card.append(purchaseControls(controller, plan));
  if (plan.recipes?.length) card.append(recipeControls(controller, plan));

  if (classes.length) {
    const table = node('details', 'tech-class-table');
    table.append(node('summary', '', 'Jump bonus and listed value by class'));
    const grid = node('table');
    const head = node('tr');
    ['Class', 'Jump bonus', 'Listed value'].forEach((h) => head.append(node('th', '', h)));
    grid.append(head);
    classes.forEach((row) => {
      const tr = node('tr');
      tr.append(node('td', '', `${row.class}${row.rating}`), node('td', '', `+${row.jump_range_bonus_ly} ly`),
        node('td', '', `${Number(row.listed_value_cr).toLocaleString()} CR`));
      grid.append(tr);
    });
    table.append(grid, node('p', 'tech-muted', 'Station prices can differ from the listed value.'));
    card.append(table);
  }

  card.append(trackingBar(controller, plan));
  const actions = node('div', 'tech-actions');
  actions.append(button('Open Outfitting', 'tech-link', () => controller.openFromTechnology?.('builds', { label: 'Outfitting' })));
  const vendor = (broker.id && plan.expedition?.broker_stations?.[0]) || null;
  if (perItem && vendor) {
    actions.append(button('Review vendor in Navigation', 'tech-link', () => {
      const intent = navigationIntent(vendor, offeringLabel(plan.unlock));
      if (intent && window.Shell?.startRouteTransfer) window.Shell.startRouteTransfer(intent);
    }));
  }
  card.append(actions);
  return card;
}

/* Number of items for a per-item purchase; requirements scale with it. */
function purchaseControls(controller, plan) {
  const row = node('div', 'tech-quantity');
  const input = node('input');
  input.type = 'number';
  input.name = 'technology_quantity';
  input.min = '1';
  input.max = String(plan.max_quantity || 1);
  input.value = String(plan.quantity || 1);
  const label = node('label', 'tech-quantity-label');
  label.append(node('span', '', 'Items to buy'), input);
  const apply = () => {
    const value = Math.max(1, Math.min(Number(input.value) || 1, plan.max_quantity || 1));
    input.value = String(value);
    if (value !== plan.quantity) controller.setTechnologyOptions?.({ quantity: value });
  };
  input.addEventListener('change', apply);
  row.append(label, node('span', 'tech-muted', 'Requirements below are for this many items.'));
  return row;
}

/* Sources disagree on this recipe: show which figures are in use and let the
   Commander switch. Nothing is averaged or merged. */
function recipeControls(controller, plan) {
  const box = node('fieldset', 'tech-recipes');
  box.append(node('legend', '', 'Sources disagree on this recipe'));
  // The default is a reference choice so the planner has something to compute,
  // not a resolution: neither figure has been confirmed in game.
  const fallback = plan.recipes[0];
  box.append(node('p', 'tech-muted tech-recipe-default',
    `Shown by default as a reference choice: ${fallback.label.toLowerCase()}. Neither recipe is verified game data.`));
  plan.recipes.forEach((recipe) => {
    const label = node('label', 'tech-recipe');
    const radio = node('input');
    radio.type = 'radio';
    radio.name = 'technology_recipe';
    radio.value = recipe.id;
    radio.checked = recipe.id === plan.recipe;
    radio.addEventListener('change', () => { if (radio.checked) controller.setTechnologyOptions?.({ recipe: recipe.id }); });
    const text = node('span');
    text.append(node('strong', '', recipe.label), node('span', 'tech-muted', ` ${recipe.note}`));
    label.append(radio, text);
    box.append(label);
  });
  return box;
}

function trackingBar(controller, plan) {
  const bar = node('div', 'tech-tracking');
  const tracking = plan.tracking;
  const statusNode = node('p', 'tech-action-status');
  statusNode.setAttribute('role', 'status');
  if (tracking) {
    bar.append(node('span', 'tech-badge', 'Tracked goal'),
      node('span', 'tech-muted', `“${tracking.title}” · ${tracking.state}. Your checklist below is saved with this goal.`));
  } else {
    const perItem = plan.transaction === 'per_item_purchase';
    const track = button(perItem ? 'Track this purchase' : 'Track this unlock', 'cmd-btn cmd-btn--primary tech-track', async () => {
      track.disabled = true;
      statusNode.textContent = 'Saving goal locally…';
      const ok = await controller.trackTechnologyUnlock?.(plan);
      if (!ok) { statusNode.textContent = 'The goal could not be saved. Nothing was changed.'; track.disabled = false; }
    });
    bar.append(track, node('span', 'tech-muted', 'Saves this exact item as an Engineering goal so the plan and your checklist are here next time.'));
  }
  bar.append(statusNode);
  return bar;
}

function readinessCard(controller, plan, state) {
  const card = node('section', 'tech-readiness');
  card.setAttribute('aria-labelledby', 'tech-readiness-title');
  const heading = node('h3', '', 'Readiness');
  heading.id = 'tech-readiness-title';
  const summary = readinessSummary(plan);
  const summaryNode = node('div', `tech-readiness-summary tech-tone-${summary.tone}`);
  summaryNode.append(node('strong', '', summary.headline), node('span', '', summary.detail));
  card.append(heading, summaryNode);

  const layout = node('div', 'tech-readiness-main');
  const list = node('ul', 'tech-requirements');
  list.setAttribute('aria-label', 'Unlock requirements');
  const inspector = node('section', 'tech-inspector');
  inspector.id = 'tech-acquisition';
  inspector.setAttribute('aria-label', 'Acquisition guidance');
  inspector.setAttribute('aria-live', 'polite');

  const rows = plan.requirements || [];
  if (!rows.some((row) => row.entity_id === state.selected)) state.selected = rows[0]?.entity_id || null;
  const buttons = [];
  const select = (id, moveFocus = false) => {
    state.selected = id;
    buttons.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.entityId === id)));
    const row = rows.find((r) => r.entity_id === id);
    inspector.replaceChildren(acquisitionPanel(controller, plan, row));
    if (moveFocus) inspector.querySelector('h4')?.focus();
  };
  rows.forEach((row, index) => {
    const item = node('li');
    const status = rowStatus(row);
    const b = node('button', `tech-requirement tech-status-${status}`);
    b.type = 'button';
    b.dataset.entityId = row.entity_id;
    const identity = node('span', 'tech-requirement-identity');
    identity.append(node('strong', '', row.name), node('span', 'tech-requirement-type', row.resource_type),
      node('span', 'tech-requirement-origin', originText(row)));
    const amounts = node('span', 'tech-requirement-amounts');
    amounts.append(
      node('span', 'tech-amount', `${haveText(row)} / ${row.quantity}`),
      node('span', 'tech-requirement-status', statusText(row)),
    );
    b.setAttribute('aria-label', `${row.name}: need ${row.quantity}, have ${haveText(row)}, ${statusText(row)}`);
    b.append(identity, amounts);
    b.addEventListener('click', () => select(row.entity_id, true));
    b.addEventListener('keydown', (event) => {
      if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
      event.preventDefault();
      const next = buttons[(index + (event.key === 'ArrowDown' ? 1 : buttons.length - 1)) % buttons.length];
      next.focus();
    });
    buttons.push(b);
    item.append(b);
    list.append(item);
  });
  layout.append(list, inspector);
  card.append(layout);
  if (state.selected) select(state.selected);
  return card;
}

function acquisitionPanel(controller, plan, row) {
  const panel = node('div', 'tech-acquisition-body');
  if (!row) return panel;
  const title = node('h4', 'tech-inspector-title', row.name);
  title.tabIndex = -1;
  panel.append(node('p', 'tech-eyebrow', row.resource_type), title);
  if (row.aliases?.length) panel.append(node('p', 'tech-muted', `In game: ${row.aliases.join(', ')}`));

  const values = node('dl', 'tech-values');
  [['Needed', row.quantity], ['You have', haveText(row)], ['Still needed', rowStatus(row) === 'unknown' ? 'Unknown' : row.missing]]
    .forEach(([label, value]) => {
      const pair = node('div');
      pair.append(node('dt', '', label), node('dd', '', value));
      values.append(pair);
    });
  panel.append(values, node('p', 'tech-origin', `Observed: ${originText(row)}`));
  (row.caveats || []).forEach((text) => panel.append(node('p', 'tech-muted', text)));

  const links = node('div', 'tech-actions');
  if (row.store === 'materials') {
    links.append(button('Show in Materials', 'tech-link', () => controller.openFromTechnology?.('materials', { materialId: row.symbol, label: row.name })));
  }
  if (row.material_trader) {
    links.append(button('Plan a trade in Material Trader', 'tech-link', () => controller.openFromTechnology?.('trader', { materialId: row.symbol, label: row.name })));
  }
  if (links.childElementCount) panel.append(links);

  panel.append(node('h5', '', 'How to get it'));
  (row.acquisition || []).forEach((method) => panel.append(methodBlock(controller, plan, method)));
  panel.append(claimList(plan, row.claims || []));
  const ids = [...(row.sources || []), ...(row.claims || []).flatMap((c) => c.sources),
    ...(row.acquisition || []).flatMap((m) => [...m.sources, ...m.claims.flatMap((c) => c.sources), ...m.steps.flatMap((s) => s.sources)])];
  panel.append(sourceList(plan, ids));
  return panel;
}

function methodBlock(controller, plan, method) {
  const block = node('article', 'tech-method');
  block.append(node('strong', '', method.name), node('p', '', method.summary));
  method.claims.forEach((claim) => block.append(node('p', 'tech-muted', claim.text)));
  const needs = method.needs || [];
  if (needs.length) {
    block.append(node('p', 'tech-needs', `Needs: ${needs.map((n) => (n.required ? n.name : `${n.name} (recommended)`)).join(', ')}`));
  }
  if (method.steps?.length) {
    // The expedition brief shows the procedure in full; here it stays one click away.
    const details = node('details', 'tech-step-details');
    details.append(node('summary', '', `Step by step (${method.steps.length})`));
    const steps = node('ol', 'tech-steps');
    method.steps.forEach((step) => steps.append(node('li', '', step.text)));
    details.append(steps);
    block.append(details);
  }
  const places = (method.locations || []).filter((p) => p.kind === 'location');
  if (places.length) block.append(siteList(controller, plan, places, 3));
  return block;
}

function siteList(controller, plan, places, visible) {
  const wrap = node('div', 'tech-sites');
  const render = (list, target) => list.forEach((place) => target.append(siteRow(controller, plan, place)));
  const top = node('ul', 'tech-site-list');
  render(places.slice(0, visible), top);
  wrap.append(top);
  if (places.length > visible) {
    const more = node('details', 'tech-more-sites');
    more.append(node('summary', '', `All ${places.length} documented sites`));
    const rest = node('ul', 'tech-site-list');
    render(places.slice(visible), rest);
    more.append(rest);
    wrap.append(more);
  }
  return wrap;
}

function siteRow(controller, plan, place) {
  const item = node('li', 'tech-site');
  const a = place.attributes || {};
  const identity = node('div', 'tech-site-identity');
  identity.append(node('strong', '', a.system), node('span', 'tech-muted',
    [a.body ? `Body ${a.body}` : a.station, Number.isFinite(a.distance_from_sol_ly) ? `${a.distance_from_sol_ly.toLocaleString()} ly from Sol` : null]
      .filter(Boolean).join(' · ')));
  if (a.landing_note) identity.append(node('span', 'tech-site-note', a.landing_note));
  if (a.coordinates) identity.append(node('span', 'tech-muted', `Surface ${a.coordinates}${a.layout ? ` · ${a.layout} layout` : ''}`));
  identity.append(node('span', `tech-evidence tech-evidence-${a.evidence}`, evidenceText(a.evidence)));
  const go = button('Review in Navigation', 'tech-link', () => {
    const intent = navigationIntent(place, plan.module?.name || plan.unlock.name);
    if (intent && window.Shell?.startRouteTransfer) window.Shell.startRouteTransfer(intent);
    else window.location.hash = '#/navigation';
  });
  go.setAttribute('aria-label', `Review ${a.system} in Navigation`);
  item.append(identity, go);
  return item;
}

function expeditionCard(controller, plan) {
  const brief = plan.expedition || {};
  const card = node('section', 'tech-expedition');
  card.setAttribute('aria-labelledby', 'tech-expedition-title');
  const heading = node('h3', '', 'Guardian expedition brief');
  heading.id = 'tech-expedition-title';
  card.append(heading);
  if (!brief.applicable) {
    card.append(node('p', 'tech-empty', 'This unlock needs nothing from Guardian sites.'));
    return card;
  }
  const grid = node('div', 'tech-brief-grid');

  const where = node('div', 'tech-brief-block');
  where.append(node('h4', '', 'Destinations'));
  const region = brief.region || {};
  if (region.nearest_from_sol_ly) {
    where.append(node('p', '', `Sites with a listed distance are ${region.nearest_from_sol_ly.toLocaleString()}–${region.farthest_from_sol_ly.toLocaleString()} ly from Sol. Sites listed by two sources are shown first.`));
  }
  (brief.destination_groups || []).forEach((group) => {
    const box = node('div', 'tech-destination-group');
    box.append(node('p', 'tech-procedure-name', `${group.name} · ${group.places.length} documented site${group.places.length === 1 ? '' : 's'}`));
    box.append(siteList(controller, plan, group.places, 2));
    where.append(box);
  });
  where.append(node('p', 'tech-muted', 'Community-documented sites, not live availability. Your distance to them is not calculated.'));
  grid.append(where);

  const prep = node('div', 'tech-brief-block');
  prep.append(node('h4', '', 'Prepare'));
  const prepList = node('ul', 'tech-prep');
  (brief.preparations || []).forEach((p) => {
    const item = node('li');
    item.append(node('strong', '', p.required ? p.name : `${p.name} (recommended)`), node('span', '', p.text || ''));
    prepList.append(item);
  });
  prep.append(prepList);
  if (brief.site_notes?.length) prep.append(node('p', 'tech-site-notes-title', 'What to expect'));
  (brief.site_notes || []).forEach((claim) => prep.append(node('p', 'tech-muted', claim.text)));
  grid.append(prep);
  card.append(grid);

  const procedure = node('div', 'tech-brief-block');
  procedure.append(node('h4', '', 'At the site'));
  (brief.salvage || []).forEach((s) => procedure.append(node('p', '', `${s.name}: ${s.summary}`)));
  (brief.procedure || []).forEach((p) => {
    procedure.append(node('p', 'tech-procedure-name', p.name));
    const steps = node('ol', 'tech-steps');
    p.steps.forEach((step) => steps.append(node('li', '', step.text)));
    procedure.append(steps);
  });
  card.append(procedure);

  const collect = node('div', 'tech-brief-grid');
  const atSite = node('div', 'tech-brief-block');
  atSite.append(node('h4', '', 'Collect at the site'));
  atSite.append(itemList(brief.collect, 'Nothing more to collect at a Guardian site.'));
  const after = node('div', 'tech-brief-block');
  after.append(node('h4', '', 'Still needed after the site'));
  after.append(itemList(brief.outstanding_after, 'Nothing else is short.'));
  const stations = brief.broker_stations || [];
  if (stations.length) {
    const details = node('details', 'tech-more-sites');
    details.append(node('summary', '', `${stations.length} stations listed with a Guardian broker`));
    const list = node('ul', 'tech-site-list');
    stations.forEach((place) => list.append(siteRow(controller, plan, place)));
    details.append(list, node('p', 'tech-muted', 'Broker presence and station access can change and were not checked live.'));
    after.append(details);
  }
  collect.append(atSite, after);
  card.append(collect, checklistBlock(controller, plan));
  return card;
}

function itemList(items, empty) {
  if (!items?.length) return node('p', 'tech-muted', empty);
  const list = node('ul', 'tech-collect');
  items.forEach((item) => {
    const li = node('li');
    li.append(node('strong', '', item.name), node('span', '', collectText(item)));
    list.append(li);
  });
  return list;
}

function checklistBlock(controller, plan) {
  const model = checklistGroups(plan);
  const block = node('fieldset', 'tech-checklist');
  block.append(node('legend', '', `Your checklist · ${model.confirmed} of ${model.total} confirmed`));
  block.append(node('p', 'tech-muted', model.saved
    ? 'Ticks are your own record. They are saved with your goal and do not change the observed counts above.'
    : 'Track this unlock to save ticks. They are your own record and never change observed counts.'));
  const statusNode = node('p', 'tech-action-status');
  statusNode.setAttribute('role', 'status');
  model.groups.forEach((group) => {
    block.append(node('p', 'tech-checklist-group', group.name));
    group.items.forEach((entry) => {
      const label = node('label', 'tech-check');
      const box = node('input');
      box.type = 'checkbox';
      box.name = entry.id;
      box.checked = entry.checked;
      box.disabled = !model.saved;
      box.addEventListener('change', async () => {
        box.disabled = true;
        const ok = await controller.saveTechnologyChecklist?.(plan, entry.id, box.checked);
        if (!ok) { box.checked = !box.checked; statusNode.textContent = 'Not saved. Your checklist was not changed.'; }
        else statusNode.textContent = 'Saved locally.';
        box.disabled = false;
        const legend = block.querySelector('legend');
        const confirmed = block.querySelectorAll('input[type=checkbox]:checked').length;
        legend.textContent = `Your checklist · ${confirmed} of ${model.total} confirmed`;
      });
      label.append(box, node('span', '', entry.text));
      block.append(label);
    });
  });
  block.append(statusNode);
  return block;
}

/* One line on what this pack is and under which terms it is included. */
function distributionNote(distribution) {
  const note = node('p', 'tech-muted tech-distribution');
  const terms = distribution.content_license;
  if (distribution.class === 'licensed_content' && terms) {
    note.append(`Includes content under ${terms.name}. ${terms.notice} `);
    if (/^https:\/\//.test(terms.url)) {
      const link = node('a', '', 'Licence terms');
      link.href = terms.url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      note.append(link);
    }
  } else if (distribution.class === 'development_only') {
    note.textContent = 'Development reference data, not part of public or release builds.';
  } else {
    note.textContent = 'Original OmniCOVAS records of game facts, credited to the sources below. No text or images from those sources are reproduced.';
  }
  return note;
}

function aboutCard(plan) {
  const details = node('details', 'tech-about');
  details.append(node('summary', '', 'About this knowledge'));
  const pack = plan.pack || {};
  details.append(
    node('p', '', `Guardian technology snapshot ${pack.version}, reviewed ${pack.reviewed_at}. Works offline; nothing is downloaded.`),
    node('p', 'tech-muted', pack.game_version),
  );
  details.append(distributionNote(pack.distribution || {}));
  details.append(node('p', 'tech-muted', plan.truth_boundary));
  if (plan.unsupported?.length) {
    details.append(node('p', 'tech-procedure-name', 'Not covered'));
    const list = node('ul', 'tech-claims');
    plan.unsupported.forEach((row) => list.append(node('li', '', `${row.subject}: ${row.reason}`)));
    details.append(list);
  }
  details.append(sourceList(plan, (plan.sources || []).map((s) => s.id), 'All sources'));
  return details;
}
