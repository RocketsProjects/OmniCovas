/**
 * Local context UI surfaces.
 *
 * Reusable safe-DOM renderers for Station Brief, System Brief, Cargo Hold,
 * current local Market Search, local context diagnostics, and module search
 * status. These surfaces render Pilot content first, with Detail and Proof
 * tucked into native disclosure controls.
 */

'use strict';

import {
  filterMarketItems,
} from '../view-models/local-context.js';

import {
  formatCredits,
} from '../utils/display-names.js';

function safeEl(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function detailDrawer(summary, content, className = 'local-detail-drawer') {
  const drawer = safeEl('details', className);
  const summaryEl = safeEl('summary', 'local-detail-summary', summary);
  const body = safeEl('div', 'local-detail-body');
  if (content instanceof Node) body.appendChild(content);
  else if (content !== undefined && content !== null) body.textContent = String(content);
  drawer.append(summaryEl, body);
  return drawer;
}

function row(label, value, className = 'local-field-row') {
  const node = safeEl('div', className);
  node.appendChild(safeEl('span', `${className}-label`, label));
  node.appendChild(safeEl('span', `${className}-value`, value ?? 'Unknown'));
  return node;
}

function listRows(rows, className = 'local-field-list') {
  const dl = safeEl('dl', className);
  (rows || []).forEach((entry) => {
    dl.appendChild(safeEl('dt', `${className}-label`, entry.label || ''));
    dl.appendChild(safeEl('dd', `${className}-value`, entry.value ?? 'Unknown'));
  });
  return dl;
}

function proofPanel(proofs) {
  const entries = Array.isArray(proofs) ? proofs.filter(Boolean) : [];
  const wrap = safeEl('div', 'local-proof-panel');
  if (entries.length === 0) {
    wrap.appendChild(safeEl('p', 'local-proof-line', 'No proof metadata loaded.'));
    return wrap;
  }

  entries.forEach((proof) => {
    const section = safeEl('section', 'local-proof-entry');
    section.appendChild(safeEl('h4', 'local-proof-title', proof.label || 'Proof'));
    section.appendChild(listRows(proof.rows || [], 'local-proof-list'));
    wrap.appendChild(section);
  });
  return wrap;
}

function actionButton(action, handlers = {}) {
  if (!action?.label) return null;
  const button = safeEl('button', 'local-context-action', action.label);
  button.type = 'button';
  button.setAttribute('data-action', action.id || '');
  if (action.enabled === false) {
    button.disabled = true;
    if (action.reason) button.setAttribute('title', action.reason);
  }
  const handler = handlers[action.id];
  if (typeof handler === 'function') {
    button.addEventListener('click', () => handler(action));
  }
  if (action.reason) {
    button.setAttribute('aria-label', `${action.label}: ${action.reason}`);
  }
  return button;
}

function actionBar(actions, handlers) {
  const bar = safeEl('div', 'local-action-bar');
  (actions || []).forEach((action) => {
    const button = actionButton(action, handlers);
    if (!button) return;
    const entry = safeEl('div', 'local-context-action-entry');
    entry.appendChild(button);
    if (action.enabled === false && action.reason) {
      entry.appendChild(safeEl('p', 'local-context-action-reason', action.reason));
    }
    bar.appendChild(entry);
  });
  return bar;
}

function briefShell(kind, title, subtitle, options = {}) {
  const section = safeEl('section', `local-brief local-brief--${kind}`);
  if (options.id) section.id = options.id;
  section.setAttribute('data-local-surface', kind);
  const header = safeEl('header', 'local-brief-header');
  header.appendChild(safeEl('p', 'local-brief-kicker', options.kicker || `${title}`));
  header.appendChild(safeEl('h3', 'local-brief-title', title));
  if (subtitle) header.appendChild(safeEl('p', 'local-brief-subtitle', subtitle));
  section.appendChild(header);
  return section;
}

export function createStationBriefSurface(model, options = {}) {
  const station = model || {};
  const surface = briefShell(
    'station',
    station.title || 'Station Brief',
    station.headline,
    { id: options.id, kicker: 'Station Brief' },
  );

  if (!station.available) {
    surface.appendChild(safeEl('p', 'local-empty-state', station.headline));
  } else {
    const pilotRows = [
      { label: 'Docked', value: station.dockedLabel },
      { label: 'Type', value: station.stationType },
      { label: 'Services', value: station.serviceSummary },
      { label: 'Economy', value: station.economySummary },
      { label: 'Faction', value: station.factionSummary },
      { label: 'Market', value: station.marketAvailable ? 'Local snapshot available' : 'No local snapshot loaded' },
      { label: 'Outfitting', value: station.outfittingAvailable ? 'Observed' : 'Not observed locally' },
      { label: 'Shipyard', value: station.shipyardAvailable ? 'Observed' : 'Not observed locally' },
    ];
    surface.appendChild(listRows(pilotRows, 'local-pilot-list'));
  }

  if (station.primaryAction && options.showAction !== false) {
    surface.appendChild(actionBar([station.primaryAction], options.handlers || {}));
  }
  surface.appendChild(detailDrawer('Station detail', listRows(station.detailRows || [], 'local-detail-list')));
  surface.appendChild(detailDrawer('Station proof', proofPanel([station.proof]), 'local-proof-drawer'));
  return surface;
}

export function createSystemBriefSurface(model, options = {}) {
  const system = model || {};
  const surface = briefShell(
    'system',
    system.title || 'System Brief',
    system.headline,
    { id: options.id, kicker: 'System Brief' },
  );

  if (!system.available) {
    surface.appendChild(safeEl('p', 'local-empty-state', system.headline));
  } else {
    surface.appendChild(listRows(system.facts || [], 'local-pilot-list'));
  }
  surface.appendChild(detailDrawer('System detail', listRows(system.detailRows || [], 'local-detail-list')));
  surface.appendChild(detailDrawer('System proof', proofPanel([system.proof]), 'local-proof-drawer'));
  return surface;
}

export function createCargoHoldSurface(model, options = {}) {
  const cargo = model || {};
  const surface = briefShell(
    'cargo',
    'Cargo Hold',
    cargo.hasCargo ? `${cargo.usedLabel} used, ${cargo.remainingLabel} remaining.` : cargo.emptyMessage,
    { id: options.id, kicker: 'Cargo Hold' },
  );

  const summary = [
    { label: 'Capacity', value: cargo.capacityLabel },
    { label: 'Used', value: cargo.usedLabel },
    { label: 'Remaining', value: cargo.remainingLabel },
  ];
  surface.appendChild(listRows(summary, 'local-pilot-list'));

  const rows = Array.isArray(cargo.topRows) ? cargo.topRows : [];
  if (rows.length === 0) {
    surface.appendChild(safeEl('p', 'local-empty-state', cargo.emptyMessage));
  } else {
    const list = safeEl('ul', 'local-cargo-list');
    list.setAttribute('role', 'list');
    rows.forEach((item) => {
      const li = safeEl('li', 'local-cargo-row');
      li.appendChild(safeEl('span', 'local-cargo-name', item.display));
      li.appendChild(safeEl('span', 'local-cargo-count', `${item.count} t`));
      if (item.flags?.length) {
        li.appendChild(safeEl('span', 'local-cargo-flags', item.flags.join(', ')));
      }
      list.appendChild(li);
    });
    surface.appendChild(list);
  }

  surface.appendChild(actionBar(cargo.actions || [], options.handlers || {}));
  const detailRows = (cargo.inventory || []).map((item) => ({
    label: item.display,
    value: `${item.count} t${item.flags?.length ? ` (${item.flags.join(', ')})` : ''}`,
  }));
  surface.appendChild(detailDrawer('Cargo detail', listRows(detailRows, 'local-detail-list')));
  surface.appendChild(detailDrawer('Cargo proof', proofPanel([cargo.proof]), 'local-proof-drawer'));
  return surface;
}

function priceText(value) {
  return value === null || value === undefined ? 'Unknown' : formatCredits(value);
}

function renderMarketRows(container, market, query, cargoAware = false) {
  container.replaceChildren();
  const cargoNames = cargoAware ? (market.cargoQueries || []).map((entry) => entry.query) : [];
  const matches = filterMarketItems(market, query, { cargoNames }).slice(0, 24);

  if (!market.available) {
    container.appendChild(safeEl('p', 'local-market-empty',
      'No local market snapshot loaded. Open the Commodities Market in Elite Dangerous to load Market.json.'));
    return;
  }

  if (matches.length === 0) {
    container.appendChild(safeEl('p', 'local-market-empty',
      'No local commodity match in the current station snapshot.'));
    return;
  }

  const list = safeEl('div', 'local-market-results-list');
  matches.forEach((item) => {
    const rowNode = safeEl('article', 'local-market-row');
    rowNode.appendChild(safeEl('h4', 'local-market-row-name', item.displayName));
    rowNode.appendChild(safeEl('p', 'local-market-row-category', item.displayCategory));
    rowNode.appendChild(row('Sell', priceText(item.sellPrice), 'local-market-field'));
    rowNode.appendChild(row('Buy', priceText(item.buyPrice), 'local-market-field'));
    rowNode.appendChild(row('Demand', item.demand === null ? 'Unknown' : String(item.demand), 'local-market-field'));
    rowNode.appendChild(row('Stock', item.stock === null ? 'Unknown' : String(item.stock), 'local-market-field'));
    if (item.prohibited) {
      rowNode.appendChild(safeEl('p', 'local-market-warning', 'Prohibited at this station.'));
    }
    list.appendChild(rowNode);
  });
  container.appendChild(list);
}

export function createMarketSearchSurface(model, options = {}) {
  const market = model || {};
  const surface = briefShell(
    'market',
    'Market Search',
    market.statusLine,
    { id: options.id, kicker: 'Market Intel' },
  );
  surface.classList.add('local-market-search');

  surface.appendChild(safeEl('p', 'local-scope-line', market.scopeLine));

  const cargoQueries = Array.isArray(market.cargoQueries) ? market.cargoQueries : [];
  if (!options.suppressSearch && cargoQueries.length > 0) {
    const cargoBar = safeEl('div', 'local-market-cargo-bar');
    cargoBar.appendChild(safeEl('span', 'local-market-cargo-label', 'Cargo-aware search'));
    cargoQueries.slice(0, 5).forEach((entry) => {
      const button = safeEl('button', 'local-market-cargo-query', `${entry.label} (${entry.count})`);
      button.type = 'button';
      button.addEventListener('click', () => {
        const input = surface.querySelector('.local-market-search-input');
        const results = surface.querySelector('.local-market-results');
        if (input) input.value = entry.query;
        if (results) renderMarketRows(results, market, entry.query, false);
      });
      cargoBar.appendChild(button);
    });
    surface.appendChild(cargoBar);
  }

  const results = safeEl('section', 'local-market-results');
  results.setAttribute('aria-live', 'polite');
  surface.appendChild(results);

  if (!options.suppressSearch) {
    const search = safeEl('div', 'local-market-search-row');
    const id = options.id ? `${options.id}-input` : 'local-market-search-input';
    const input = document.createElement('input');
    input.className = 'local-market-search-input';
    input.type = 'search';
    input.id = id;
    input.name = id;
    input.setAttribute('aria-label', 'Search current local market snapshot');
    input.setAttribute('placeholder', 'Search current local market snapshot');
    if (options.initialQuery) input.value = String(options.initialQuery);
    const submit = safeEl('button', 'local-market-search-submit', 'Search');
    submit.type = 'button';
    search.append(input, submit);
    surface.insertBefore(search, results);

    const runSearch = () => renderMarketRows(results, market, input.value, false);
    submit.addEventListener('click', runSearch);
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') runSearch();
    });
    renderMarketRows(results, market, input.value, !input.value);
  } else {
    const initialQuery = String(options.initialQuery || '');
    if (options.deferResults === true && !initialQuery.trim()) {
      results.appendChild(safeEl('p', 'local-market-empty',
        'Search local commodities in the current station snapshot.'));
    } else {
      renderMarketRows(results, market, initialQuery, false);
    }
  }

  surface.appendChild(detailDrawer('Market detail', listRows(market.detailRows || [], 'local-detail-list')));
  surface.appendChild(detailDrawer('Market proof', proofPanel([market.proof]), 'local-proof-drawer'));
  return surface;
}

export function updateMarketSearchResults(surface, model, query, options = {}) {
  const results = surface?.querySelector?.('.local-market-results');
  if (!results) return;
  renderMarketRows(results, model || {}, query || '', Boolean(options.cargoAware));
}

export function createModuleSearchSurface(model, options = {}) {
  const moduleSearch = model || {};
  const surface = briefShell(
    'module',
    'Module Search',
    moduleSearch.summary,
    { id: options.id, kicker: 'Module Search' },
  );
  surface.classList.add('local-module');

  if (options.showAction !== false) {
    const action = {
      id: 'open-module-search',
      label: 'Open Module Search',
      enabled: moduleSearch.available,
      reason: moduleSearch.available
        ? 'Stages local module/loadout context.'
        : 'No local module loadout or outfitting support loaded yet.',
    };
    surface.appendChild(actionBar([action], options.handlers || {}));
  }

  /* Correction #9: clean Module Search panel with a local filter input.
     Filters the existing loadout client-side; no provider call, no scrape. */
  if (moduleSearch.modules?.length && options.deferResults === true) {
    const results = safeEl('section', 'local-module-results');
    results.setAttribute('aria-live', 'polite');
    results.appendChild(safeEl('p', 'local-module-deferred',
      `Search local loadout modules. ${moduleSearch.modules.length} local modules observed.`));
    surface.appendChild(results);
  } else if (moduleSearch.modules?.length) {
    let input = null;
    if (options.enableFilter === true) {
      const id = options.id ? `${options.id}-filter-input` : 'local-module-filter-input';
      input = document.createElement('input');
      input.type = 'search';
      input.id = id;
      input.name = id;
      input.className = 'local-module-search-input';
      input.placeholder = 'Filter modules by slot or name';
      input.setAttribute('aria-label', 'Filter modules in loadout');
      surface.appendChild(input);
    }

    const list = safeEl('div', 'local-module-list local-module-list--table');
    const header = safeEl('div', 'local-module-row local-module-row--header');
    ['Slot', 'Module', 'Power', 'Priority', 'State'].forEach((label) => {
      header.appendChild(safeEl('span', 'local-module-header-cell', label));
    });
    list.appendChild(header);
    moduleSearch.modules.forEach((entry) => {
      const item = safeEl('div', 'local-module-row');
      const slot = safeEl('span', 'local-module-slot', entry.slot);
      const name = safeEl('span', 'local-module-name', entry.display);
      const power = safeEl('span', 'local-module-power',
        entry.power === null || entry.power === undefined ? 'Unknown' : String(entry.power));
      const priority = safeEl('span', 'local-module-priority',
        entry.priority === null || entry.priority === undefined ? 'Unknown' : String(entry.priority));
      const state = safeEl('span', 'local-module-state', entry.stateLabel || 'Unknown');
      item.append(slot, name, power, priority, state);
      item.dataset.haystack =
        `${(entry.slot || '').toLowerCase()}\n${(entry.display || '').toLowerCase()}`;
      list.appendChild(item);
    });
    surface.appendChild(list);

    if (input) {
      input.addEventListener('input', () => {
        const q = input.value.trim().toLowerCase();
        list.querySelectorAll('.local-module-row:not(.local-module-row--header)').forEach((row) => {
          row.hidden = q.length > 0 && !row.dataset.haystack.includes(q);
        });
      });
    }
  } else {
    /* Honest deferred state per Commander direction. */
    const deferred = safeEl(
      'p',
      'local-module-deferred',
      'Local module loadout not loaded — search will activate when a Loadout event arrives.',
    );
    deferred.textContent = 'Module search is limited until local outfitting/module data is loaded.';
    surface.appendChild(deferred);
  }

  surface.appendChild(detailDrawer('Module proof', proofPanel([moduleSearch.proof]), 'local-proof-drawer'));
  return surface;
}

export function createLocalContextDiagnosticsSurface(model, options = {}) {
  const diagnostics = model || {};
  const surface = briefShell(
    'diagnostics',
    'Local Context Diagnostics',
    diagnostics.summary,
    { id: options.id, kicker: 'Sources & Diagnostics' },
  );

  const rows = [
    { label: 'Endpoint', value: diagnostics.endpointAvailable ? 'Available' : 'Unavailable' },
    { label: 'Generated', value: diagnostics.generatedAt || 'Unknown' },
    { label: 'NullProvider safe', value: diagnostics.nullproviderSafe ? 'Yes' : 'Unknown' },
  ];
  surface.appendChild(listRows(rows, 'local-pilot-list'));

  const gaps = safeEl('ul', 'local-missing-source-list');
  gaps.setAttribute('role', 'list');
  (diagnostics.missingSources || []).forEach((source) => {
    gaps.appendChild(safeEl('li', 'local-missing-source-item', source.label));
  });
  if (!gaps.children.length) {
    gaps.appendChild(safeEl('li', 'local-missing-source-item', 'No local source gaps reported.'));
  }
  surface.appendChild(detailDrawer('Missing local sources', gaps));
  surface.appendChild(detailDrawer('Local context proof summary', proofPanel(diagnostics.proofEntries || []), 'local-proof-drawer'));
  return surface;
}
