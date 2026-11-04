// Presentation of the canonical Journal inventory and portfolio output only.
// Counts and allocations are never recomputed or persisted by this workspace.
import { createMaterialRequirements } from './engineering-material-requirements.js';
import { createMaterialAcquisition } from './engineering-material-acquisition.js';
import { createGuide } from './material-intelligence.js';
import { atlasIntent, intelligenceFor, materialIntel, navigationIntent } from '../view-models/material-intelligence.js';
import { createMaterialTrader } from './engineering-material-trader.js';
const node = (tag, cls = '', text) => {
  const element = document.createElement(tag);
  element.className = cls;
  if (text != null) element.textContent = String(text);
  return element;
};
const quantity = (value) => Number.isFinite(value) ? String(value) : 'Unknown';
const categories = { raw: 'Raw', manufactured: 'Manufactured', encoded: 'Encoded', unknown: 'Category not checked' };
const date = (value) => {
  if (!value) return 'Not checked';
  // Journal timestamps stored in SQLite are returned as UTC without an offset.
  const timestamp = /(?:Z|[+-]\d\d:\d\d)$/i.test(value) ? value : `${value}Z`;
  if (!Number.isFinite(Date.parse(timestamp))) return 'Not checked';
  return new Date(timestamp).toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZoneName: 'short' });
};
const field = (name, value) => {
  const row = node('div', 'materials-fact');
  row.append(node('dt', '', name), node('dd', '', value));
  return row;
};
const control = (name, entries, current) => {
  const select = node('select');
  select.name = name;
  entries.forEach(([value, text]) => {
    const option = node('option', '', text);
    option.value = value;
    option.selected = value === current;
    select.append(option);
  });
  return select;
};
const label = (text, input) => {
  const result = node('label', 'materials-control');
  input.setAttribute('aria-label', text);
  result.append(node('span', '', text), input);
  return result;
};

export function createMaterialsWorkspace(controller, overview) {
  const progression = overview.progression || {};
  const inventory = progression.inventory;
  const builds = progression.builds || [];
  const state = controller._materialsState ||= { search: '', category: 'all', availability: 'all', selected: null };
  state.perspective ||= 'inventory';
  // Follow the saved build chosen in Outfitting each time that choice changes;
  // in between, the build picked here stays.
  if (!('followedBuildId' in state) || state.followedBuildId !== (controller._selectedBuildId ?? null)) {
    state.followedBuildId = controller._selectedBuildId ?? null;
    if (builds.some((b) => b.build_plan_id === state.followedBuildId)) state.buildId = state.followedBuildId;
  }
  state.buildId ??= 'all';
  if (state.buildId !== 'all' && !builds.some((b) => b.build_plan_id === state.buildId)) state.buildId = 'all';
  const materials = new Map();
  (inventory?.materials || []).forEach((row) => materials.set(row.material_id, { ...row, allocations: [], observed: true }));
  // Include required materials absent from the inventory list. Use the first
  // portfolio held value, which is before this material's first reservation.
  builds.forEach((build) => (build.materials || []).forEach((allocation) => {
    if (!materials.has(allocation.material_id)) materials.set(allocation.material_id, {
      material_id: allocation.material_id, display_name: allocation.display_name,
      category: 'unknown', count: allocation.held_before_reservation,
      allocations: [], observed: false,
    });
    materials.get(allocation.material_id).allocations.push({ build, ...allocation });
  }));
  const rows = [...materials.values()].sort((a, b) => (a.display_name || a.material_id).localeCompare(b.display_name || b.material_id));
  const section = node('section', 'materials-workspace');
  section.dataset.view = state.detail ? 'detail' : 'list';
  section.id = 'engineering-materials-workspace';
  section.setAttribute('aria-labelledby', 'materials-heading');
  const heading = node('header', 'materials-heading');
  const title = node('h2', '', 'Materials');
  title.id = 'materials-heading';
  const context = builds.length
    ? `${builds.length} active build${builds.length === 1 ? '' : 's'} · ${builds.map((b) => b.title).join(' · ')}`
    : 'Your ship engineering inventory · No active builds';
  const contextNode = node('p', 'materials-context', context);
  heading.append(title, contextNode);
  section.append(heading);
  const perspectives = node('div', 'materials-perspectives');
  const tabs = node('div', 'materials-perspective-tabs');
  tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', 'Materials perspectives');
  const tabButtons = new Map();
  const PERSPECTIVES = ['inventory', 'requirements', 'acquisition', 'trader'];
  for (const [id, text] of [['inventory', 'Inventory'], ['requirements', 'Requirements'], ['acquisition', 'Acquisition'], ['trader', 'Trader']]) {
    const tab = node('button', 'materials-perspective-tab', text);
    tab.type = 'button'; tab.id = `materials-tab-${id}`; tab.dataset.materialsPerspective = id;
    tab.setAttribute('role', 'tab'); tab.setAttribute('aria-controls', `materials-panel-${id}`);
    tab.addEventListener('click', () => setPerspective(id));
    tabs.append(tab); tabButtons.set(id, tab);
  }
  tabs.addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const current = event.target.dataset.materialsPerspective;
    const at = PERSPECTIVES.indexOf(current);
    const id = event.key === 'Home' ? PERSPECTIVES[0] : event.key === 'End' ? PERSPECTIVES[PERSPECTIVES.length - 1]
      : PERSPECTIVES[(at + (event.key === 'ArrowRight' ? 1 : PERSPECTIVES.length - 1)) % PERSPECTIVES.length];
    setPerspective(id); tabButtons.get(id).focus();
  });
  const buildSelect = control('requirements_build', [['all', 'All active builds'], ...builds.map((b) => [b.build_plan_id, b.title])], state.buildId);
  const buildLabel = label('Requirements for', buildSelect);
  perspectives.append(tabs, buildLabel); section.append(perspectives);
  const source = node('p', 'materials-source');
  source.textContent = !inventory ? 'Inventory unavailable · Engineering inventory did not answer.'
    : inventory.state === 'unknown' ? 'Inventory not checked · No complete Journal Materials baseline is stored. Quantities are unknown, not zero.'
      : inventory.state === 'partial_inconsistent' ? 'Journal inventory needs a new baseline · Some quantities are unknown.'
        : `Observed in your Journal · Last recorded ${date(inventory.last_event_at || inventory.observed_at)}`;
  section.append(source);
  const inventoryPanel = node('section', 'materials-inventory-panel');
  inventoryPanel.id = 'materials-panel-inventory'; inventoryPanel.setAttribute('role', 'tabpanel'); inventoryPanel.setAttribute('aria-labelledby', 'materials-tab-inventory');
  const requirementPanel = node('section', 'materials-requirements-panel');
  requirementPanel.id = 'materials-panel-requirements'; requirementPanel.setAttribute('role', 'tabpanel'); requirementPanel.setAttribute('aria-labelledby', 'materials-tab-requirements');
  const acquisitionPanel = node('section', 'materials-acquisition-panel');
  acquisitionPanel.id = 'materials-panel-acquisition'; acquisitionPanel.setAttribute('role', 'tabpanel'); acquisitionPanel.setAttribute('aria-labelledby', 'materials-tab-acquisition');
  const traderPanel = node('section', 'materials-trader-panel');
  traderPanel.id = 'materials-panel-trader'; traderPanel.setAttribute('role', 'tabpanel'); traderPanel.setAttribute('aria-labelledby', 'materials-tab-trader');
  section.append(inventoryPanel, requirementPanel, acquisitionPanel, traderPanel);

  const toolbar = node('div', 'materials-toolbar');
  const search = node('input');
  search.type = 'search';
  search.name = 'material_search';
  search.placeholder = 'Search material names…';
  search.value = state.search;
  const category = control('material_category', [['all', 'All categories'], ...Object.entries(categories)], state.category);
  const availability = control('material_availability', [
    ['all', 'All materials'], ['stock', 'In stock'], ['empty', 'None on hand'],
    ['unknown', 'Quantity unknown'], ['needed', 'Used by active builds'], ['short', 'Short for a build'], ['reserved', 'Reserved for a build'],
  ], state.availability);
  toolbar.append(label('Search inventory', search), label('Category', category), label('Availability & builds', availability));
  inventoryPanel.append(toolbar);
  const count = node('p', 'materials-result-count');
  count.setAttribute('role', 'status');
  count.setAttribute('aria-live', 'polite');
  const main = node('div', 'materials-main');
  const collection = node('div', 'materials-collection');
  collection.setAttribute('aria-label', 'Material inventory');
  const inspector = node('section', 'materials-inspector');
  inspector.id = 'materials-inspector';
  inspector.setAttribute('aria-label', 'Material details');
  main.append(collection, inspector);
  inventoryPanel.append(count, main);

  function openBuild(build, slot) {
    if (build) {
      state.buildId = build.build_plan_id;
      const editable = (progression.saved_configurations || []).some((v) => v.build_plan_id === build.build_plan_id);
      if (!editable) {
        buildSelect.value = state.buildId;
        setPerspective(state.perspective);
        controller._setStage('builds');
        const record = controller.root?.querySelector(`[data-build-plan-id="${CSS.escape(build.build_plan_id)}"]`);
        const disclosure = record?.closest('details');
        if (disclosure) disclosure.open = true;
        if (record) { record.tabIndex = -1; record.focus(); record.scrollIntoView({ block: 'start' }); }
        return;
      }
      controller._selectedBuildId = build.build_plan_id;
      controller._selectedObservationId = null;
      controller._observedWorkbench = null;
      controller._activeStage = 'builds';
      controller.render(controller.overview || overview);
      const target = slot && controller.root?.querySelector(`.engineering-module-button[data-slot="${CSS.escape(slot)}"]`);
      if (target) { target.click(); target.focus({ preventScroll: true }); }
      else controller.root?.querySelector('[name=saved_variant]')?.focus();
    } else controller._setStage('builds');
  }
  function showRequirements() {
    requirementPanel.replaceChildren(createMaterialRequirements({ progression, buildId: state.buildId, state,
      initialMaterial: state.inventorySelectedByUser ? state.selected : null,
      onBuild: openBuild,
      onAcquisition: (id) => { state.acquisitionFocus = id; setPerspective('acquisition'); },
      onInventory: (id) => {
        state.selected = id; state.search = ''; state.category = 'all'; state.availability = 'all';
        search.value = ''; category.value = 'all'; availability.value = 'all';
        setPerspective('inventory'); renderCollection(); inspect(materials.get(id), true);
      },
    }));
  }
  /* GKI-05: leaving for Navigation or the Atlas remembers where the commander was,
     so the return lands on the same perspective and material. */
  function leave(intent, materialId) {
    if (!intent || !window.Shell?.startRouteTransfer) return;
    controller._materialsReturn = { perspective: state.perspective, material: materialId };
    window.Shell.startRouteTransfer(intent);
  }
  const handoffs = {
    onNavigate: (place, material, method) => leave(navigationIntent(place, material, method, state.buildId), material.material_id),
    onAtlas: (place, material) => leave(atlasIntent(place, material), material.material_id),
  };
  function showAcquisition() {
    acquisitionPanel.replaceChildren(createMaterialAcquisition({
      ...handoffs,
      progression, plans: controller.overview?.acquisition_plans || overview.acquisition_plans || [], buildId: state.buildId, state,
      onBuild: openBuild,
      onInventory: (id) => {
        state.selected = id; state.search = ''; state.category = 'all'; state.availability = 'all';
        search.value = ''; category.value = 'all'; availability.value = 'all';
        setPerspective('inventory'); renderCollection(); inspect(materials.get(id), true);
      },
      onRequirements: (id) => { state.requirementMaterial = id; state.inventorySelectedByUser = true; state.selected = id; setPerspective('requirements'); },
      onTrader: openTrader,
      onRecordPlan: (payload) => controller.handleAction(() => controller.postJson('/engineering/acquisition-plan', payload), 'Acquisition plan saved locally.'),
      onOpenPlans: () => {
        const target = controller.root?.querySelector('#engineering-acquisition');
        if (target) { target.tabIndex = -1; target.scrollIntoView({ block: 'start' }); target.focus({ preventScroll: true }); }
      },
    }));
  }
  function showTrader() {
    traderPanel.replaceChildren(createMaterialTrader({
      progression, buildId: state.buildId, state,
      onBuild: openBuild,
      onRequirements: () => setPerspective('requirements'),
    }));
  }
  function openTrader(materialId) {
    const trader = progression.material_trader;
    const material = (trader?.materials || []).find((m) => m.id === materialId);
    state.trader ||= { type: 'raw', search: '', filter: 'all', take: null, give: null, pick: 'take', mode: 'receive', amount: 1, basket: [] };
    if (material) { state.trader.type = material.type; state.trader.take = material.id; state.trader.give = null; state.trader.pick = 'take'; }
    setPerspective('trader');
  }
  function setPerspective(id) {
    state.perspective = id;
    inventoryPanel.hidden = id !== 'inventory'; requirementPanel.hidden = id !== 'requirements'; acquisitionPanel.hidden = id !== 'acquisition'; traderPanel.hidden = id !== 'trader';
    const labelText = id === 'acquisition' ? 'Acquisition for' : id === 'trader' ? 'Plan trades for' : 'Requirements for';
    buildLabel.querySelector('span').textContent = labelText; buildSelect.setAttribute('aria-label', labelText);
    section.dataset.view = id === 'inventory' && state.detail ? 'detail' : 'list';
    for (const [key, tab] of tabButtons) { tab.setAttribute('aria-selected', String(key === id)); tab.tabIndex = key === id ? 0 : -1; }
    const noun = id === 'acquisition' ? 'Acquisition' : id === 'trader' ? 'Material Trader' : 'Requirements';
    contextNode.textContent = id === 'inventory' ? context : state.buildId === 'all'
      ? `${noun} across ${builds.length} active build${builds.length === 1 ? '' : 's'}`
      : builds.find((b) => b.build_plan_id === state.buildId)?.title || 'No active saved build';
    if (id === 'requirements') showRequirements();
    if (id === 'acquisition') showAcquisition();
    if (id === 'trader') showTrader();
  }
  buildSelect.addEventListener('change', () => { state.buildId = buildSelect.value; setPerspective(state.perspective); });

  function inspect(row, moveFocus = false) {
    if (moveFocus) {
      state.inventorySelectedByUser = true;
      if (state.requirementSelections) state.requirementSelections[state.buildId] = null;
    }
    state.selected = row?.material_id || null;
    collection.querySelectorAll('button[data-material-id]').forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.materialId === state.selected)));
    inspector.replaceChildren();
    if (!row) {
      inspector.append(node('h3', '', 'Material details'), node('p', '', 'Select a material to inspect its stock and build requirements.'));
      return;
    }
    const back = node('button', 'materials-back', 'Back to inventory');
    back.type = 'button';
    back.addEventListener('click', () => {
      state.detail = false;
      section.dataset.view = 'list';
      const selected = [...collection.querySelectorAll('button')].find((b) => b.dataset.materialId === state.selected);
      (selected || search).focus();
    });
    const name = node('h3', '', row.display_name || row.material_id);
    name.tabIndex = -1;
    inspector.append(back, node('p', 'materials-eyebrow', categories[row.category] || categories.unknown), name);
    inspector.append(node('p', 'materials-stock', `${quantity(row.count)} on hand`));
    const facts = node('dl', 'materials-facts');
    facts.append(
      field('Stock source', row.observed ? (row.count == null ? 'Journal balance inconsistent' : 'Locally observed Journal inventory') : 'Existing portfolio comparison'),
      field('Baseline observed', date(inventory?.observed_at)),
      field('Last supported event', date(inventory?.last_event_at)),
      field('Freshness', inventory?.observed_at ? 'Last recorded observation; current in-game stock is not checked' : 'Not checked — no complete baseline'),
    );
    inspector.append(facts, node('h4', '', 'Build requirements & reservations'));
    if (!row.allocations.length) inspector.append(node('p', 'materials-muted', builds.length ? 'No assessed requirement for this material in the active builds.' : 'No active builds. Inventory is available independently of a plan.'));
    row.allocations.forEach((allocation) => {
      const build = node('article', 'materials-allocation');
      const link = node('button', 'materials-build-link', allocation.build.title);
      link.type = 'button';
      link.addEventListener('click', () => {
        controller._setStage('builds');
        const library = controller.root.querySelector('.engineering-build-library');
        if (library) library.open = true;
        const card = [...controller.root.querySelectorAll('[data-build-plan-id]')].find((el) => el.dataset.buildPlanId === allocation.build.build_plan_id);
        const target = card || library;
        if (target) { target.tabIndex = -1; target.focus(); target.scrollIntoView({ block: 'nearest' }); }
      });
      const details = node('dl', 'materials-allocation-values');
      details.append(field('Required', quantity(allocation.required)), field('Reserved', quantity(allocation.reserved)), field('Short', quantity(allocation.deficit)));
      build.append(link, details);
      if (allocation.deficit == null) build.append(node('p', 'materials-muted', 'Shortage not checked — inventory is unknown.'));
      inspector.append(build);
    });
    if (row.allocations.length) inspector.append(node('p', 'materials-muted', 'Planning reservations share one inventory pool across active builds. Observed stock is unchanged.'));
    inspector.append(howToGet(row));
    const proof = node('details', 'materials-proof');
    proof.append(node('summary', '', 'Observation details'));
    const identity = node('dl', 'materials-facts');
    identity.append(field('Material identifier', row.material_id));
    proof.append(identity);
    (inventory?.caveats || []).forEach((caveat) => proof.append(node('p', '', caveat)));
    (progression.builds || []).filter((build) => build.unknown_inputs?.length).forEach((build) => proof.append(node('p', '', `${build.title}: ${build.unknown_inputs.join(' ')}`)));
    inspector.append(proof);
    if (moveFocus && window.matchMedia?.('(max-width: 760px)').matches) {
      state.detail = true;
      section.dataset.view = 'detail';
      name.focus({ preventScroll: true });
      inspector.scrollIntoView({ block: 'start', behavior: 'instant' });
    }
  }

  /* Documented sources for any material, fetched once per material. A short
     material also offers its full strategy in the Acquisition perspective. */
  function howToGet(row) {
    const box = node('div', 'materials-how-to-get');
    const short = materialIntel(intelligenceFor(progression, 'all'), row.material_id);
    if (short) {
      const open = node('button', 'materials-build-link', `See the acquisition strategy (${short.recommendation.headline.toLowerCase()})`);
      open.type = 'button';
      open.addEventListener('click', () => {
        state.buildId = 'all';
        buildSelect.value = 'all';
        state.acquisitionFocus = row.material_id;
        setPerspective('acquisition');
        acquisitionPanel.querySelector('#materials-acquisition-inspector h3')?.focus({ preventScroll: true });
      });
      box.append(open);
    }
    const guides = state.guides ||= {};
    const render = (guide) => box.replaceChildren(...[box.firstChild].filter((n) => n?.classList?.contains('materials-build-link')), createGuide(guide, handoffs));
    const load = () => controller.fetchJson(`/knowledge/materials/${encodeURIComponent(row.material_id)}/acquisition`)
      .then((guide) => {
        if (!Array.isArray(guide?.methods)) throw new Error('no guide');
        guides[row.material_id] = guide;
        if (state.selected === row.material_id) render(guide);
      })
      .catch((error) => {
        console.warn('Material acquisition guide unavailable:', error);
        if (state.selected === row.material_id) render(null);
      });
    if (guides[row.material_id]) {
      render(guides[row.material_id]);
    } else if (typeof controller.fetchJson === 'function') {
      box.append(node('p', 'materials-muted', 'Looking up documented sources…'));
      // The workspace is built while other Engineering stages show; ask only
      // once this inspector is actually on screen.
      if (controller._activeStage === 'materials') load();
      else if (typeof IntersectionObserver === 'function') {
        const watch = new IntersectionObserver((entries) => {
          if (entries.some((entry) => entry.isIntersecting)) { watch.disconnect(); load(); }
        });
        watch.observe(box);
      }
    }
    return box;
  }

  function renderCollection() {
    const filtered = rows.filter((row) => {
      if (!String(row.display_name || row.material_id).toLocaleLowerCase().includes(state.search.trim().toLocaleLowerCase())) return false;
      if (state.category !== 'all' && (categories[row.category] ? row.category : 'unknown') !== state.category) return false;
      switch (state.availability) {
        case 'stock': return row.count > 0;
        case 'empty': return row.count === 0;
        case 'unknown': return row.count == null;
        case 'needed': return row.allocations.length > 0;
        case 'short': return row.allocations.some((a) => a.deficit > 0);
        case 'reserved': return row.allocations.some((a) => a.reserved > 0);
        default: return true;
      }
    });
    count.textContent = `${filtered.length} of ${rows.length} materials`;
    collection.replaceChildren();
    if (!filtered.length) collection.append(node('p', 'materials-empty', rows.length ? 'No matching materials. Change the search or filters.' : inventory?.state === 'verified_local' ? 'The last complete Journal baseline contains no materials.' : 'No observed inventory to show. Open a game session that records a complete Materials baseline.'));
    Object.entries(categories).forEach(([id, categoryName]) => {
      const group = filtered.filter((row) => (categories[row.category] ? row.category : 'unknown') === id);
      if (!group.length) return;
      const groupHeading = node('h3', 'materials-category', `${categoryName} · ${group.length}`);
      const list = node('ul', 'materials-list');
      list.setAttribute('aria-label', categoryName);
      group.forEach((row) => {
        const item = node('li');
        const button = node('button', 'materials-row');
        button.type = 'button';
        button.dataset.materialId = row.material_id;
        button.setAttribute('aria-controls', inspector.id);
        const identity = node('span', 'materials-row-identity');
        identity.append(node('strong', '', row.display_name || row.material_id));
        const relevance = row.allocations.map((a) => `${a.build.title}: ${quantity(a.required)} required · ${quantity(a.reserved)} reserved · ${quantity(a.deficit)} short`).join(' / ');
        if (relevance) identity.append(node('span', 'materials-row-note', relevance));
        const stock = node('span', 'materials-row-stock', quantity(row.count));
        stock.append(node('small', '', row.count === 0 ? 'none on hand' : 'on hand'));
        button.append(identity, stock);
        button.addEventListener('click', () => inspect(row, true));
        item.append(button);
        list.append(item);
      });
      collection.append(groupHeading, list);
    });
    inspect(filtered.find((row) => row.material_id === state.selected) || filtered[0]);
  }
  collection.addEventListener('keydown', (event) => {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key) || !event.target.matches('button[data-material-id]')) return;
    const buttons = [...collection.querySelectorAll('button')];
    const index = buttons.indexOf(event.target);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : Math.max(0, Math.min(buttons.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)));
    event.preventDefault();
    buttons[next]?.focus();
  });
  search.addEventListener('input', () => { state.search = search.value; renderCollection(); });
  category.addEventListener('change', () => { state.category = category.value; renderCollection(); });
  availability.addEventListener('change', () => { state.availability = availability.value; renderCollection(); });
  renderCollection();
  setPerspective(state.perspective);
  return section;
}
