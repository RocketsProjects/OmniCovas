/**
 * Blueprints & Engineers workstation (Engineering Milestone 01).
 *
 * Three perspectives share one searchable list + contextual inspector:
 *   My Upgrades  - engineered targets in saved builds (Engineering's assessment)
 *   Blueprints   - catalogue reference recipes joined with Journal-observed ones
 *   Engineers    - Journal-observed progression, the catalogue and the Commander's own records
 *
 * Presentation only. Every figure comes from the Engineering overview; unknown
 * stays unknown. All dynamic text is set with textContent (ADR 0003).
 */
import {
  UNVERIFIED_EQUIPMENT,
  blueprintDisplayOrder,
  buildBlueprintModel,
  contributionLabel,
  engineerStatus,
  gradeSpan,
  matchesQuery,
  observedAtLabel,
  rankLabel,
  rankProgressLabel,
  searchText,
} from '../view-models/engineering-blueprints.js';

const PERSPECTIVES = Object.freeze([
  { id: 'upgrades', label: 'My Upgrades' },
  { id: 'blueprints', label: 'Blueprints' },
  { id: 'engineers', label: 'Engineers' },
]);

const UPGRADE_STATE = Object.freeze({
  verified_ready: ['Already engineered', 'ok'],
  work_remaining: ['Work remaining', 'warn'],
  unknown_actual: ['Current state unknown', 'muted'],
  planned_legal: ['Planned', 'info'],
});

const PRIORITY_LABEL = Object.freeze({
  high: 'High priority',
  normal: 'Normal priority',
  low: 'Low priority',
  unsorted: 'Unsorted',
});

function el(tag, className = '', content = null) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== null && content !== undefined) node.textContent = String(content);
  return node;
}

function opt(label, value) {
  const node = document.createElement('option');
  node.value = value;
  node.textContent = label;
  return node;
}

function chip(label, tone = 'muted') {
  return el('span', `blueprints-chip blueprints-chip--${tone}`, label);
}

function button(label, onClick, className = 'blueprints-link') {
  const node = el('button', className, label);
  node.type = 'button';
  node.addEventListener('click', onClick);
  return node;
}

let uid = 0;
const nextId = (prefix) => `${prefix}-${(uid += 1)}`;

const plural = (count, one, many = `${one}s`) => `${count} ${count === 1 ? one : many}`;

function dateOnly(value) {
  return typeof value === 'string' && value.length >= 10 ? value.slice(0, 10) : 'date not recorded';
}

function gradeLabel(upgrade) {
  const effect = upgrade.experimentalName ? ` · ${upgrade.experimentalName}` : '';
  return `Grade ${upgrade.targetGrade}${effect}`;
}

function materialSummary(materials) {
  return materials.map((row) => `${row.display_name || row.material_id} ×${row.count}`).join(' · ');
}

function assessmentChip(assessment) {
  if (!assessment) return chip('Recipe not known', 'muted');
  if (assessment.state === 'unknown') return chip('Materials not checked', 'muted');
  if (assessment.state === 'affordable') return chip('Can afford', 'ok');
  if (assessment.reservedOnly) return chip('Reserved by your plans', 'warn');
  return chip(`Short ${plural(assessment.shortCount, 'material')}`, 'warn');
}

/** Host actions that reach back into the Engineering route. */
function createHost(controller, overview) {
  return {
    openCatalogueSetup() {
      const details = controller.root?.querySelector('.engineering-secondary');
      if (!details) return;
      details.open = true;
      const target = details.querySelector('#engineering-reference-catalog') || details;
      target.scrollIntoView?.({ block: 'start' });
      (target.querySelector('input, button') || target).focus?.({ preventScroll: true });
    },
    openInOutfitting(upgrade) {
      // Same state the Outfitting variant selector sets for a saved build.
      controller._selectedBuildId = upgrade.buildId;
      controller._selectedObservationId = null;
      controller._observedWorkbench = null;
      controller._activeStage = 'builds';
      controller.render(controller.overview || overview);
      const row = controller.root?.querySelector(
        `.engineering-module-button[data-slot="${CSS.escape(upgrade.slot)}"]`,
      );
      if (row) {
        row.click();
        row.focus?.({ preventScroll: false });
      }
    },
    readinessSection() {
      return typeof controller.createReadinessSection === 'function'
        ? controller.createReadinessSection(overview)
        : null;
    },
  };
}

export function createEngineeringBlueprints(controller, overview = {}) {
  const model = buildBlueprintModel(overview);
  const host = createHost(controller, overview);
  const state = (controller._blueprintsState ||= {
    perspective: null,
    search: '',
    equipment: '',
    source: '',
    materials: '',
    selection: { upgrades: null, blueprints: null, engineers: null },
    detail: false,
    expanded: new Set(),
  });
  if (!state.perspective) state.perspective = model.counts.upgrades ? 'upgrades' : 'blueprints';

  const root = el('section', 'blueprints-workspace');
  root.setAttribute('aria-label', 'Blueprints and engineers');
  const titleId = nextId('blueprints-title');

  // ---- heading --------------------------------------------------------
  const heading = el('div', 'blueprints-heading');
  const title = el('h2', '', 'Blueprints & Engineers');
  title.id = titleId;
  const context = el('p', 'blueprints-context');
  const journalCount = model.blueprints.filter((bp) => bp.inJournal).length;
  context.textContent = [
    model.catalogue.active
      ? `Catalogue: ${model.catalogue.title || model.catalogue.id} · ${plural(model.catalogue.blueprintCount, 'blueprint')}`
      : 'Catalogue: not installed',
    `Journal: ${plural(journalCount, 'blueprint')} crafted`,
    model.inventory.known ? 'Materials: from your Journal' : 'Materials: not checked',
  ].join('   ·   ');
  heading.append(title, context);

  // ---- perspectives ---------------------------------------------------
  const tabs = el('div', 'blueprints-perspectives');
  tabs.setAttribute('role', 'tablist');
  tabs.setAttribute('aria-label', 'Engineering perspectives');
  const tabButtons = new Map();
  PERSPECTIVES.forEach((perspective) => {
    const tab = el('button', 'blueprints-tab');
    tab.type = 'button';
    tab.id = nextId('blueprints-tab');
    tab.dataset.perspective = perspective.id;
    tab.setAttribute('role', 'tab');
    tab.append(
      el('span', '', perspective.label),
      el('span', 'blueprints-tab-count', model.counts[perspective.id]),
    );
    tab.addEventListener('click', () => setPerspective(perspective.id));
    tab.addEventListener('keydown', (event) => {
      const order = PERSPECTIVES.map((row) => row.id);
      const index = order.indexOf(perspective.id);
      const next = {
        ArrowRight: order[(index + 1) % order.length],
        ArrowLeft: order[(index - 1 + order.length) % order.length],
        Home: order[0],
        End: order[order.length - 1],
      }[event.key];
      if (!next) return;
      event.preventDefault();
      setPerspective(next);
      tabButtons.get(next).focus();
    });
    tabButtons.set(perspective.id, tab);
    tabs.append(tab);
  });

  const panel = el('div', 'blueprints-panel');
  panel.setAttribute('role', 'tabpanel');
  const notice = el('div', 'blueprints-notice-slot');
  const toolbar = el('div', 'blueprints-toolbar');
  const count = el('p', 'blueprints-result-count');
  count.setAttribute('aria-live', 'polite');
  const main = el('div', 'blueprints-main');
  const collection = el('div', 'blueprints-collection');
  const inspector = el('aside', 'blueprints-inspector');
  inspector.setAttribute('aria-label', 'Selected item details');
  main.append(collection, inspector);
  panel.append(notice, toolbar, count, main);

  const secondary = el('div', 'blueprints-secondary-slot');
  root.append(heading, tabs, panel, secondary);

  // ---- state helpers --------------------------------------------------
  const isNarrow = () => window.matchMedia?.('(max-width: 760px)').matches === true;

  function visibleBlueprints() {
    return model.blueprints.filter((bp) => {
      if (state.equipment && !bp.equipment.ids.includes(state.equipment)) return false;
      if (state.source === 'catalogue' && !bp.inCatalogue) return false;
      if (state.source === 'journal' && !bp.inJournal) return false;
      if (state.source === 'planned' && !bp.upgrades.length) return false;
      if (state.materials === 'affordable' && !bp.anyAffordable) return false;
      return matchesQuery(searchText(bp), state.search);
    });
  }

  function visibleUpgrades() {
    return model.upgrades.filter((upgrade) =>
      matchesQuery(
        [upgrade.buildTitle, upgrade.moduleLabel, upgrade.blueprintName, upgrade.experimentalName, upgrade.slot]
          .filter(Boolean)
          .join(' ')
          .toLowerCase(),
        state.search,
      ),
    );
  }

  function visibleEngineers() {
    return model.engineers.filter((engineer) =>
      matchesQuery(
        [
          engineer.name,
          engineer.location,
          engineer.id ? String(engineer.id) : '',
          engineer.place?.system,
          engineer.place?.base,
          engineer.access.completion.label,
          engineerStatus(engineer.observed).label,
          rankLabel(engineer.observed),
          ...engineer.capabilities.map((cap) => cap.blueprintName),
          ...engineer.crafts.map((craft) => craft.blueprint_label),
        ]
          .filter(Boolean)
          .join(' ')
          .toLowerCase(),
        state.search,
      ),
    );
  }

  const visibleItems = () => {
    if (state.perspective === 'upgrades') return visibleUpgrades().map((row) => ({ key: row.id, row }));
    if (state.perspective === 'engineers') return visibleEngineers().map((row) => ({ key: row.key, row }));
    return visibleBlueprints()
      .sort(blueprintDisplayOrder)
      .map((row) => ({ key: row.key, row }));
  };

  function ensureSelection(items) {
    const current = state.selection[state.perspective];
    if (!items.some((item) => item.key === current)) {
      state.selection[state.perspective] = items[0]?.key ?? null;
    }
  }

  // ---- perspective switching -----------------------------------------
  function setPerspective(id, { focusTab = false } = {}) {
    state.perspective = id;
    state.detail = false;
    renderPanel();
    if (focusTab) tabButtons.get(id).focus();
  }

  function goToBlueprint(key, { grade = null } = {}) {
    // An unknown id must never fall back to some other blueprint's inspector.
    if (!model.byKey.has(key)) return false;
    state.perspective = 'blueprints';
    state.search = '';
    state.equipment = '';
    state.source = '';
    state.materials = '';
    state.selection.blueprints = key;
    if (grade) state.expanded.add(`${key}:${grade}`);
    state.detail = true;
    renderPanel();
    focusInspector();
    return true;
  }

  function goToUpgrade(id) {
    state.perspective = 'upgrades';
    state.search = '';
    state.selection.upgrades = id;
    state.detail = true;
    renderPanel();
    focusInspector();
  }

  function goToEngineer(key) {
    state.perspective = 'engineers';
    state.search = '';
    state.selection.engineers = key;
    state.detail = true;
    renderPanel();
    focusInspector();
  }

  function focusInspector() {
    inspector.querySelector('h3')?.focus({ preventScroll: false });
  }

  // ---- rendering ------------------------------------------------------
  function renderTabs() {
    PERSPECTIVES.forEach(({ id }) => {
      const tab = tabButtons.get(id);
      const active = id === state.perspective;
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
      if (active) {
        panel.id = panel.id || nextId('blueprints-panel');
        panel.setAttribute('aria-labelledby', tab.id);
        tab.setAttribute('aria-controls', panel.id);
      }
    });
  }

  function renderNotice() {
    notice.replaceChildren();
    if (state.perspective === 'upgrades') return;
    if (!model.catalogue.active) {
      const note = el('div', 'blueprints-notice');
      note.setAttribute('role', 'note');
      note.append(
        el('strong', '', 'No reference catalogue installed'),
        el(
          'span',
          '',
          ' Only blueprints recorded from your Journal are listed. Applicable equipment, other grades and experimental effects stay unavailable until you enable a local catalogue. Nothing is downloaded unless you choose to.',
        ),
        button('Review catalogue options', () => host.openCatalogueSetup(), 'blueprints-link blueprints-notice-action'),
      );
      notice.append(note);
    } else if (model.catalogue.updateAvailable) {
      const note = el('div', 'blueprints-notice blueprints-notice--quiet');
      note.setAttribute('role', 'note');
      note.append(
        el('span', '', 'A newer private reference version is available in Details; the one in use is unchanged.'),
        button('Review catalogue options', () => host.openCatalogueSetup(), 'blueprints-link blueprints-notice-action'),
      );
      notice.append(note);
    }
    if (state.perspective === 'engineers' && model.engineerProgress.state === 'not_observed') {
      const note = el('div', 'blueprints-notice blueprints-notice--quiet');
      note.setAttribute('role', 'note');
      note.append(
        el('strong', '', 'No engineer progress observed yet'),
        el(
          'span',
          '',
          ' OmniCOVAS learns it from EngineerProgress entries in your Journal. Until one is seen, every engineer here is simply not observed. That does not mean they are locked.',
        ),
      );
      notice.append(note);
    }
    if (state.perspective === 'engineers') notice.append(directoryNotice());
  }

  /** What the bundled directory covers, where it came from and what it leaves out. */
  function directoryNotice() {
    const directory = model.directory;
    const box = el('details', 'blueprints-notice blueprints-notice--quiet blueprints-directory-note');
    box.dataset.directory = directory.available ? 'available' : 'unavailable';
    if (!directory.available) {
      const invalid = directory.reason === 'invalid';
      box.dataset.reason = invalid ? 'invalid' : 'not_included';
      box.append(
        el('summary', '', invalid ? 'Reference directory unavailable' : 'Reference directory not included in this build'),
        el(
          'p',
          'blueprints-muted',
          invalid
            ? 'The bundled engineer directory could not be loaded. Only engineers from your Journal, an installed catalogue or your records are listed.'
            : 'This build does not ship a reference engineer directory. Engineers are listed from your Journal, from a reference catalogue you install (it can carry engineer IDs, systems, bases and requirements), and from your own records. Nothing is assumed about engineers none of them mention.',
        ),
      );
      return box;
    }
    const coverage = directory.coverage;
    box.append(el('summary', '', `Reference directory · ${coverage.engineers} ship engineers, locations cross-checked`));
    box.append(
      el(
        'p',
        '',
        `Locations are cross-checked for ${coverage.location_verified} engineers and the system only for ${coverage.location_system_only || 0}. Specializations, grade limits and unlock requirements are not included because no current source could be verified. They stay unknown rather than guessed.`,
      ),
    );
    const sources = el('ul', 'blueprints-plain-list');
    directory.sources.forEach((source) => sources.append(el('li', '', `${source.name} — ${source.role}`)));
    box.append(el('strong', '', 'Sources'), sources);
    const gaps = el('ul', 'blueprints-plain-list');
    directory.unsupportedFields.forEach((row) =>
      gaps.append(el('li', '', `${row.field.replace(/_/g, ' ')}: ${row.reason}`)),
    );
    box.append(el('strong', '', 'Not included'), gaps);
    box.append(
      el('p', 'blueprints-muted', `Version ${directory.version}, reviewed ${directory.reviewedAt}. ${directory.scope}`),
    );
    if (directory.developmentOnly) {
      box.append(
        el('p', 'blueprints-muted', 'Development reference data. It is not Frontier-published game data and is excluded from public, preview and release builds until its sources are cleared for redistribution.'),
      );
    }
    return box;
  }

  function control(labelText, input) {
    const label = el('label', 'blueprints-control');
    label.append(el('span', '', labelText), input);
    return label;
  }

  function renderToolbar() {
    toolbar.replaceChildren();
    toolbar.dataset.mode = state.perspective;
    const search = el('input');
    search.type = 'search';
    search.name = 'blueprints_search';
    search.autocomplete = 'off';
    search.value = state.search;
    search.placeholder =
      state.perspective === 'blueprints'
        ? 'Blueprint, equipment, material or engineer'
        : state.perspective === 'engineers'
          ? 'Engineer, location or blueprint'
          : 'Build, module or blueprint';
    search.setAttribute('aria-keyshortcuts', '/');
    search.addEventListener('input', () => {
      state.search = search.value;
      state.detail = false;
      renderResults();
    });
    toolbar.append(control('Search', search));

    if (state.perspective === 'blueprints') {
      const equipment = el('select');
      equipment.name = 'blueprints_equipment';
      equipment.append(opt('All equipment', ''));
      model.categories.forEach((category) =>
        equipment.append(opt(`${category.label} (${category.count})`, category.id)),
      );
      equipment.value = state.equipment;
      if (!model.categories.length) {
        equipment.disabled = true;
        equipment.title = 'Equipment types come from a reference catalogue, which is not installed.';
      }
      equipment.addEventListener('change', () => {
        state.equipment = equipment.value;
        state.detail = false;
        renderResults();
      });

      const source = el('select');
      source.name = 'blueprints_source';
      [
        ['', 'All sources'],
        ['catalogue', 'In the catalogue'],
        ['journal', 'Crafted in my Journal'],
        ['planned', 'In my plans'],
      ].forEach(([value, label]) => source.append(opt(label, value)));
      source.value = state.source;
      source.addEventListener('change', () => {
        state.source = source.value;
        state.detail = false;
        renderResults();
      });

      const materials = el('select');
      materials.name = 'blueprints_materials';
      materials.append(opt('Any materials', ''), opt('A grade I can afford now', 'affordable'));
      if (!model.inventory.known) {
        materials.disabled = true;
        materials.title = 'Materials on hand have not been checked from your Journal.';
        state.materials = '';
      }
      materials.value = state.materials;
      materials.addEventListener('change', () => {
        state.materials = materials.value;
        state.detail = false;
        renderResults();
      });
      toolbar.append(
        control('Equipment', equipment),
        control('Source', source),
        control('Materials', materials),
      );
    }
  }

  function emptyMessage() {
    const filtered = state.search || state.equipment || state.source || state.materials;
    if (filtered) return 'Nothing matches the current search and filters.';
    if (state.perspective === 'upgrades') {
      return 'No planned engineering yet. Choose a module and blueprint in Outfitting, or browse Blueprints to see what is available.';
    }
    if (state.perspective === 'engineers') {
      return 'No engineers known yet. Engineers appear here once your Journal reports engineer progress or a craft, or a reference catalogue declares them.';
    }
    return 'No blueprints known yet. No EngineerCraft recipes observed yet, and no reference catalogue is installed.';
  }

  function rowButton(item, content) {
    const row = el('button', 'blueprints-row');
    row.type = 'button';
    row.dataset.key = item.key;
    row.setAttribute('aria-pressed', String(item.key === state.selection[state.perspective]));
    row.append(...content);
    row.addEventListener('click', () => {
      select(item.key, { detail: true });
      if (isNarrow()) focusInspector();
    });
    return row;
  }

  function identity(name, meta) {
    const block = el('span', 'blueprints-row-identity');
    block.append(el('strong', '', name));
    if (meta) block.append(el('span', 'blueprints-row-note', meta));
    return block;
  }

  function blueprintRow(item) {
    const bp = item.row;
    const meta = [gradeSpan(bp.knownGrades)];
    if (bp.equipment.ids.length > 1) meta.push(`also ${bp.equipment.labels.slice(1).join(', ')}`);
    const side = el('span', 'blueprints-row-side');
    if (bp.upgrades.length) side.append(chip(`Planned ×${bp.upgrades.length}`, 'info'));
    if (!model.inventory.known) side.append(el('span', 'blueprints-row-status', 'Materials not checked'));
    else if (bp.highestAffordableGrade) {
      side.append(el('span', 'blueprints-row-status blueprints-row-status--ok', `Affordable up to G${bp.highestAffordableGrade}`));
    } else if (bp.knownGrades.length) {
      side.append(el('span', 'blueprints-row-status', 'No grade affordable now'));
    } else {
      side.append(el('span', 'blueprints-row-status', 'No recipe known'));
    }
    const sources = el('span', 'blueprints-row-sources');
    if (bp.inCatalogue) sources.append(chip('Catalogue', 'muted'));
    if (bp.inJournal) sources.append(chip('Journal', 'muted'));
    const identityBlock = identity(bp.name, meta.join(' · '));
    identityBlock.append(sources);
    return rowButton(item, [identityBlock, side]);
  }

  function upgradeRow(item) {
    const upgrade = item.row;
    const [label, tone] = UPGRADE_STATE[upgrade.state] || ['Status unknown', 'muted'];
    const side = el('span', 'blueprints-row-side');
    side.append(chip(label, tone));
    return rowButton(item, [
      identity(
        `${upgrade.moduleLabel}`,
        `${upgrade.blueprintName} · ${gradeLabel(upgrade)}`,
      ),
      side,
    ]);
  }

  function engineerRow(item) {
    const engineer = item.row;
    const status = engineerStatus(engineer.observed);
    const meta = [
      engineer.location || (engineer.declared ? 'Location not recorded' : null),
      engineer.crafts.length ? `You crafted ${engineer.crafts.length}×` : null,
      engineer.declared ? 'In catalogue' : null,
      engineer.records.length ? 'Your record' : null,
    ].filter(Boolean);
    const side = el('span', 'blueprints-row-side');
    if (status.observed) {
      side.append(chip(status.label, status.tone));
      const rank = rankLabel(engineer.observed);
      if (rank) side.append(el('span', 'blueprints-row-status', rank));
    } else {
      side.append(el('span', 'blueprints-row-status', status.label));
    }
    return rowButton(item, [identity(engineer.name, meta.join(' · ')), side]);
  }

  function renderList(items) {
    collection.replaceChildren();
    if (!items.length) {
      collection.append(el('p', 'blueprints-empty', emptyMessage()));
      return;
    }
    const rowFor =
      state.perspective === 'upgrades' ? upgradeRow : state.perspective === 'engineers' ? engineerRow : blueprintRow;
    const groups = new Map();
    items.forEach((item) => {
      let groupKey;
      let groupLabel;
      let groupNote = '';
      if (state.perspective === 'upgrades') {
        groupKey = item.row.buildId;
        groupLabel = item.row.buildTitle;
        groupNote = [item.row.ship, PRIORITY_LABEL[item.row.priority] || item.row.priority]
          .filter(Boolean)
          .join(' · ');
      } else if (state.perspective === 'engineers') {
        // Grouping only helps once something has been observed; before that the
        // list is one honest "not observed" set, explained by the notice above.
        const observed = Boolean(item.row.observed);
        groupKey = model.counts.observedEngineers ? (observed ? '__observed' : '__unobserved') : 'all';
        groupLabel = !model.counts.observedEngineers
          ? ''
          : observed
            ? 'Observed in your Journal'
            : 'Not observed';
        if (model.counts.observedEngineers && !observed) {
          groupNote = 'No EngineerProgress seen. Not the same as locked';
        }
      } else {
        groupKey = item.row.group || '__unverified';
        groupLabel = item.row.group ? item.row.equipment.labels[0] : UNVERIFIED_EQUIPMENT;
        if (!item.row.group) groupNote = 'Known only from your Journal';
      }
      if (!groups.has(groupKey)) groups.set(groupKey, { label: groupLabel, note: groupNote, items: [] });
      groups.get(groupKey).items.push(item);
    });
    // Equipment groups read alphabetically with the unverified bucket last; build
    // groups keep Engineering's own priority order.
    const ordered = [...groups.entries()];
    if (state.perspective === 'blueprints') {
      ordered.sort(
        ([ka, a], [kb, b]) =>
          (ka === '__unverified') - (kb === '__unverified') ||
          a.label.localeCompare(b.label, undefined, { sensitivity: 'base' }),
      );
    }
    ordered.forEach(([, group]) => {
      const section = el('section', 'blueprints-group');
      if (group.label) {
        const header = el('h3', 'blueprints-group-title');
        header.append(el('span', '', group.label));
        if (group.note) header.append(el('span', 'blueprints-group-note', group.note));
        header.append(el('span', 'blueprints-group-count', group.items.length));
        section.append(header);
      }
      const ul = el('ul', 'blueprints-list');
      group.items.forEach((item) => {
        const li = el('li');
        li.append(rowFor(item));
        ul.append(li);
      });
      section.append(ul);
      collection.append(section);
    });
  }

  function onListKeydown(event) {
    if (event.key === '/' && !(event.target instanceof HTMLInputElement)) {
      event.preventDefault();
      toolbar.querySelector('input')?.focus();
      return;
    }
    const rows = [...collection.querySelectorAll('.blueprints-row')];
    const index = rows.indexOf(document.activeElement);
    if (index < 0) return;
    const next = {
      ArrowDown: rows[Math.min(index + 1, rows.length - 1)],
      ArrowUp: rows[Math.max(index - 1, 0)],
      Home: rows[0],
      End: rows[rows.length - 1],
    }[event.key];
    if (!next) return;
    event.preventDefault();
    select(next.dataset.key, { detail: false });
    collection.querySelector(`.blueprints-row[data-key="${CSS.escape(next.dataset.key)}"]`)?.focus();
  }

  function select(key, { detail }) {
    state.selection[state.perspective] = key;
    state.detail = detail;
    collection.querySelectorAll('.blueprints-row').forEach((row) => {
      row.setAttribute('aria-pressed', String(row.dataset.key === key));
    });
    root.dataset.view = state.detail ? 'detail' : 'list';
    renderInspector();
  }

  function renderResults() {
    const items = visibleItems();
    ensureSelection(items);
    const total =
      state.perspective === 'upgrades'
        ? model.counts.upgrades
        : state.perspective === 'engineers'
          ? model.counts.engineers
          : model.counts.blueprints;
    const noun = { upgrades: 'planned upgrade', blueprints: 'blueprint', engineers: 'engineer' }[state.perspective];
    count.textContent =
      items.length === total
        ? plural(total, noun)
        : `${plural(items.length, noun)} shown of ${total}`;
    root.dataset.view = state.detail ? 'detail' : 'list';
    renderList(items);
    renderInspector();
  }

  function renderPanel() {
    renderTabs();
    renderNotice();
    renderToolbar();
    renderResults();
    renderSecondary();
  }

  function renderSecondary() {
    secondary.replaceChildren();
    if (state.perspective !== 'engineers') return;
    const section = host.readinessSection();
    if (!section) return;
    const details = el('details', 'blueprints-secondary');
    details.append(el('summary', '', 'Engineer notes and readiness records you entered'), section);
    secondary.append(details);
  }

  // ---- inspectors -----------------------------------------------------
  function backButton() {
    return button('Back to list', () => {
      state.detail = false;
      root.dataset.view = 'list';
      collection
        .querySelector(`.blueprints-row[data-key="${CSS.escape(String(state.selection[state.perspective]))}"]`)
        ?.focus();
    }, 'blueprints-link blueprints-back');
  }

  function inspectorHead(eyebrow, name) {
    const wrapper = el('header', 'blueprints-inspector-head');
    wrapper.append(el('p', 'blueprints-eyebrow', eyebrow));
    const h3 = el('h3', '', name);
    h3.tabIndex = -1;
    wrapper.append(h3);
    return wrapper;
  }

  function fact(term, value) {
    const row = el('div', 'blueprints-fact');
    row.append(el('dt', '', term));
    const dd = el('dd');
    if (value instanceof Node) dd.append(value);
    else dd.textContent = value;
    row.append(dd);
    return row;
  }

  function billTable(assessmentOrMaterials, caption) {
    const table = el('table', 'blueprints-bill');
    table.append(el('caption', 'blueprints-visually-hidden', caption));
    const head = el('thead');
    const headRow = el('tr');
    ['Material', 'Need', 'On hand', 'Status'].forEach((label) => {
      const th = el('th', '', label);
      th.scope = 'col';
      headRow.append(th);
    });
    head.append(headRow);
    table.append(head);
    const body = el('tbody');
    assessmentOrMaterials.rows.forEach((row) => {
      const tr = el('tr');
      const have = row.have === null ? 'Not checked' : String(row.have);
      const onHand = el('td', 'blueprints-num', have);
      if (row.reserved) onHand.append(el('small', '', ` (${row.reserved} reserved)`));
      let status = '—';
      if (row.short === 0) status = 'Enough';
      else if (row.short > 0) status = row.have >= row.need ? 'Reserved by plans' : `Short ${row.short}`;
      tr.append(
        el('th', '', row.name),
        el('td', 'blueprints-num', row.need),
        onHand,
        el('td', row.short > 0 ? 'blueprints-short' : '', status),
      );
      tr.firstChild.scope = 'row';
      body.append(tr);
    });
    table.append(body);
    return table;
  }

  function sourceLine(kind, text) {
    const p = el('p', 'blueprints-source-line');
    p.append(chip(kind, kind === 'Journal' ? 'info' : 'muted'), document.createTextNode(` ${text}`));
    return p;
  }

  function gradeRow(bp, row) {
    const key = `${bp.key}:${row.grade}`;
    const details = el('details', 'blueprints-grade');
    details.open = state.expanded.has(key);
    details.addEventListener('toggle', () => {
      if (details.open) state.expanded.add(key);
      else state.expanded.delete(key);
    });
    const summary = el('summary');
    summary.append(
      el('span', 'blueprints-grade-name', `Grade ${row.grade}`),
      el('span', 'blueprints-grade-bill', row.materials ? materialSummary(row.materials) : 'No recipe known for this grade'),
      assessmentChip(row.assessment),
    );
    details.append(summary);
    const body = el('div', 'blueprints-grade-body');
    if (!row.materials) {
      body.append(
        el(
          'p',
          'blueprints-muted',
          bp.inCatalogue
            ? 'The catalogue has no recipe for this grade and no craft of it appears in your Journal.'
            : 'No catalogue is installed and your Journal has not recorded a craft at this grade.',
        ),
      );
    } else {
      body.append(billTable(row.assessment, `Materials for ${bp.name} grade ${row.grade}`));
      if (row.observed) {
        const seen = row.observed;
        body.append(
          sourceLine(
            'Journal',
            `Observed ${dateOnly(seen.observed_at)}${seen.engineer ? ` with ${seen.engineer}` : ''}.`,
          ),
        );
      }
      if (row.catalogue) {
        body.append(
          sourceLine('Catalogue', `${model.catalogue.title || 'Reference catalogue'}${model.catalogue.version ? ` · ${model.catalogue.version}` : ''}.`),
        );
      }
      if (row.agreement === 'differs') {
        const diff = el('div', 'blueprints-callout');
        diff.append(
          el('strong', '', 'Journal and catalogue bills differ. '),
          document.createTextNode(`The table shows the Journal bill. Catalogue lists: ${materialSummary(row.catalogue.materials)}.`),
        );
        body.append(diff);
      } else if (row.agreement === 'agrees') {
        body.append(el('p', 'blueprints-muted', 'Journal and catalogue agree on this bill.'));
      }
    }
    details.append(body);
    return details;
  }

  /**
   * Engineers connected to one blueprint, with three separate statements per
   * engineer: what a reference lists, what the Journal shows you crafted, and
   * the access the Journal last reported. An unlocked engineer is not assumed to
   * offer every grade, and no ranking or recommendation is made.
   */
  function engineerLinks(blueprint, targetGrade = null) {
    const section = el('div');
    section.append(el('h4', 'blueprints-section-title', targetGrade ? 'Engineers for this blueprint' : 'Engineers'));
    if (!blueprint || !blueprint.engineers.length) {
      section.append(
        el(
          'p',
          'blueprints-muted',
          model.catalogue.active
            ? 'No engineer is declared for this blueprint and your Journal has no craft of it.'
            : 'No engineer is known. Your Journal records no craft of this blueprint, and no catalogue is installed to declare one. No bundled directory or installed catalogue lists what each engineer offers.',
        ),
      );
      return section;
    }
    const ul = el('ul', 'blueprints-plain-list blueprints-engineer-links');
    blueprint.engineers.forEach((link) => {
      const li = el('li');
      li.append(button(link.engineer.name, () => goToEngineer(link.engineer.key)));
      const bits = [];
      if (link.declared) {
        let listed = `Catalogue lists up to grade ${link.maxGrade}`;
        if (Number.isInteger(targetGrade)) {
          listed += link.maxGrade >= targetGrade ? `, which covers your target G${targetGrade}` : `, below your target G${targetGrade}`;
        }
        bits.push(listed);
      } else {
        bits.push('Not listed by an installed catalogue');
      }
      if (link.crafted.length) bits.push(`You crafted G${[...new Set(link.crafted)].sort().join(', G')} with them`);
      const observed = link.engineer.observed;
      if (observed) {
        const access = [engineerStatus(observed).label, rankLabel(observed)]
          .filter(Boolean)
          .join(', ')
          .toLowerCase()
          .replace(/^./, (letter) => letter.toUpperCase());
        bits.push(`Your access: ${access}`);
      } else {
        bits.push('Your access: not observed');
      }
      li.append(el('span', 'blueprints-link-facts', ` — ${bits.join(' · ')}`));
      ul.append(li);
    });
    section.append(
      ul,
      el(
        'p',
        'blueprints-muted',
        model.engineerProgress.state === 'observed'
          ? 'Access and rank come from EngineerProgress entries in your Journal; an engineer without one is not observed, which does not mean locked. Being unlocked does not mean every grade is available: the engineer’s rank and the blueprint’s grade limit still apply.'
          : 'Your Journal has reported no engineer progress yet, so access is unknown here and never assumed.',
      ),
    );
    return section;
  }

  function inspectBlueprint(bp) {
    inspector.replaceChildren(backButton());
    const equipment = bp.equipment.labels.length
      ? bp.equipment.labels.join(', ')
      : UNVERIFIED_EQUIPMENT;
    inspector.append(inspectorHead(equipment, bp.name));
    const chips = el('div', 'blueprints-chips');
    if (bp.inCatalogue) chips.append(chip('Catalogue reference', 'muted'));
    if (bp.inJournal) chips.append(chip('Seen in your Journal', 'info'));
    if (bp.upgrades.length) chips.append(chip(`In ${plural(bp.upgrades.length, 'planned upgrade')}`, 'info'));
    inspector.append(chips);

    const facts = el('dl', 'blueprints-facts');
    facts.append(
      fact(
        'Applies to',
        bp.equipment.kind === 'catalogue'
          ? bp.equipment.labels.join(', ')
          : bp.equipment.kind === 'observed_slot'
            ? `Seen on your current ship: ${bp.equipment.labels.join(', ')}. Wider compatibility is not verified.`
            : 'Not verified. This blueprint is known only from your Journal, which does not say what it fits.',
      ),
    );
    if (bp.special) facts.append(fact('Note', bp.special));
    inspector.append(facts);
    if (bp.numericalDataComplete === false || bp.caveats.length) {
      const caveat = el('div', 'blueprints-callout');
      caveat.append(el('strong', '', 'Catalogue limits. '));
      caveat.append(
        document.createTextNode(
          [bp.numericalDataComplete === false ? 'Numeric data for this blueprint is marked incomplete.' : '', ...bp.caveats]
            .filter(Boolean)
            .join(' '),
        ),
      );
      inspector.append(caveat);
    }

    inspector.append(el('h4', 'blueprints-section-title', 'Grades and materials'));
    inspector.append(el('p', 'blueprints-muted', 'Recipe bills are per craft. Affordability uses stock left after all saved-plan reservations; it is not a saved upgrade’s remaining shortage.'));
    if (!model.inventory.known) {
      inspector.append(
        el('p', 'blueprints-muted', 'Materials on hand have not been checked from your Journal, so affordability is not claimed. Missing counts are never treated as zero.'),
      );
    }
    const grades = el('div', 'blueprints-grades');
    bp.grades.forEach((row) => grades.append(gradeRow(bp, row)));
    inspector.append(grades);

    if (bp.experimentals.length || bp.observedEffects.length) {
      inspector.append(el('h4', 'blueprints-section-title', 'Experimental effects'));
      const ul = el('ul', 'blueprints-plain-list');
      bp.experimentals.forEach((effect) => {
        const li = el('li');
        li.append(el('strong', '', effect.name));
        li.append(
          document.createTextNode(
            effect.materials
              ? ` — ${materialSummary(effect.materials)}`
              : ' — cost is not in the supported source',
          ),
        );
        if (effect.assessment) li.append(' ', assessmentChip(effect.assessment));
        ul.append(li);
      });
      bp.observedEffects.forEach((name) => {
        if (bp.experimentals.some((effect) => effect.id === name || effect.name === name)) return;
        const li = el('li');
        li.append(el('strong', '', name), document.createTextNode(' — applied in a craft recorded in your Journal; cost not recorded'));
        ul.append(li);
      });
      inspector.append(ul);
    }

    inspector.append(engineerLinks(bp));

    if (bp.upgrades.length) {
      inspector.append(el('h4', 'blueprints-section-title', 'In your plans'));
      const ul = el('ul', 'blueprints-plain-list blueprints-plans');
      bp.upgrades.forEach((upgrade) => {
        const li = el('li');
        li.append(
          el('span', '', `${upgrade.moduleLabel} · ${gradeLabel(upgrade)} — ${upgrade.buildTitle}`),
        );
        const actions = el('span', 'blueprints-actions');
        actions.append(
          button('Open upgrade', () => goToUpgrade(upgrade.id)),
          button('Open in Outfitting', () => host.openInOutfitting(upgrade)),
        );
        li.append(actions);
        ul.append(li);
      });
      inspector.append(ul);
    }

    inspector.append(provenanceDisclosure(bp));
  }

  function provenanceDisclosure(bp) {
    const details = el('details', 'blueprints-provenance');
    details.append(el('summary', '', 'Sources and provenance'));
    const dl = el('dl', 'blueprints-facts');
    dl.append(
      fact(
        'Catalogue reference',
        bp.inCatalogue
          ? `${model.catalogue.title} (${model.catalogue.id}) · version ${model.catalogue.version}. Commander-supplied; structure validated, accuracy not independently verified.`
          : 'Not in a catalogue.',
      ),
      fact(
        'Journal',
        bp.inJournal
          ? `${plural(bp.grades.filter((row) => row.observed).length, 'grade')} observed in EngineerCraft events. Latest per grade is shown.`
          : 'No EngineerCraft event for this blueprint.',
      ),
    );
    if (model.catalogue.provenance) {
      dl.append(
        fact('Pack source', `${model.catalogue.provenance.source_name}; licence: ${model.catalogue.provenance.license}.`),
      );
    }
    if (model.catalogue.verificationBoundary) dl.append(fact('Verification', model.catalogue.verificationBoundary));
    details.append(dl);
    return details;
  }

  function inspectUpgrade(upgrade) {
    inspector.replaceChildren(backButton());
    inspector.append(inspectorHead(`${upgrade.buildTitle} · ${upgrade.slot}`, `${upgrade.moduleLabel}`));
    const [label, tone] = UPGRADE_STATE[upgrade.state] || ['Status unknown', 'muted'];
    const chips = el('div', 'blueprints-chips');
    chips.append(chip(label, tone), chip('Planned engineering', 'info'));
    inspector.append(chips);

    const facts = el('dl', 'blueprints-facts');
    facts.append(
      fact('Blueprint', upgrade.blueprintName),
      fact('Target', gradeLabel(upgrade)),
      fact(
        'Currently',
        upgrade.actualBlueprint
          ? `${upgrade.actualBlueprint}${upgrade.actualGrade ? ` G${upgrade.actualGrade}` : ''}`
          : upgrade.actualGrade === null
            ? 'Not known'
            : 'Not engineered',
      ),
    );
    inspector.append(facts);

    const actions = el('div', 'blueprints-actions blueprints-actions--block');
    const open = button('Open in Outfitting', () => host.openInOutfitting(upgrade), 'blueprints-button');
    actions.append(open);
    if (upgrade.blueprintKnown) {
      actions.append(
        button('View blueprint', () => goToBlueprint(upgrade.blueprintKey, { grade: upgrade.targetGrade }), 'blueprints-button blueprints-button--quiet'),
      );
    }
    inspector.append(actions);

    inspector.append(engineerLinks(model.byKey.get(upgrade.blueprintKey) || null, upgrade.targetGrade));

    inspector.append(el('h4', 'blueprints-section-title', `Materials for ${upgrade.buildTitle}`));
    inspector.append(
      el('p', 'blueprints-muted', 'Engineering totals every upgrade in this build against one shared inventory, so this is the whole build, not only this module.'),
    );
    if (upgrade.materials.length) {
      const table = el('table', 'blueprints-bill');
      table.append(el('caption', 'blueprints-visually-hidden', `Materials for ${upgrade.buildTitle}`));
      const head = el('thead');
      const headRow = el('tr');
      ['Material', 'Need', 'Reserved', 'Short'].forEach((labelText) => {
        const th = el('th', '', labelText);
        th.scope = 'col';
        headRow.append(th);
      });
      head.append(headRow);
      const body = el('tbody');
      upgrade.materials.forEach((row) => {
        const tr = el('tr');
        const name = el('th', '', row.display_name || row.material_id);
        name.scope = 'row';
        tr.append(
          name,
          el('td', 'blueprints-num', row.required),
          el('td', 'blueprints-num', row.reserved === null ? 'Not checked' : row.reserved),
          el('td', row.deficit > 0 ? 'blueprints-num blueprints-short' : 'blueprints-num', row.deficit === null ? 'Unknown' : row.deficit),
        );
        body.append(tr);
      });
      table.append(head, body);
      inspector.append(table);
    } else {
      inspector.append(el('p', 'blueprints-muted', 'No material requirement is available for this build.'));
    }
    if (upgrade.unknownInputs.length) {
      const unknown = el('div', 'blueprints-callout');
      unknown.append(el('strong', '', 'Not yet known'));
      const ul = el('ul', 'blueprints-plain-list');
      upgrade.unknownInputs.forEach((entry) => ul.append(el('li', '', entry)));
      unknown.append(ul);
      inspector.append(unknown);
    }
    if (upgrade.nextAction) inspector.append(el('p', 'blueprints-muted', `Next: ${upgrade.nextAction}`));

    const bp = model.byKey.get(upgrade.blueprintKey);
    if (bp) {
      inspector.append(el('h4', 'blueprints-section-title', 'Recipe for each grade this needs'));
      inspector.append(el('p', 'blueprints-muted', 'These individual recipe bills assess an additional craft after saved-plan reservations. The build totals above already include this upgrade’s allocation and roll budget.'));
      const from = (upgrade.actualGrade || 0) + 1;
      const grades = el('div', 'blueprints-grades');
      bp.grades
        .filter((row) => row.grade >= from && row.grade <= upgrade.targetGrade)
        .forEach((row) => grades.append(gradeRow(bp, row)));
      if (!grades.childElementCount) {
        grades.append(el('p', 'blueprints-muted', 'The current module already meets this grade.'));
      }
      inspector.append(grades);
    } else {
      inspector.append(
        el('p', 'blueprints-muted', 'This blueprint is not in the installed catalogue or your Journal crafts, so its recipe is not available here.'),
      );
    }
  }

  const ACCESS_TONE = {
    observed: 'ok',
    partial: 'info',
    not_verified: 'muted',
    documented: 'info',
    unavailable: 'muted',
  };
  const LOCATION_STATUS = {
    verified: 'Community-observed; cross-checked against two sources',
    system_only: 'System cross-checked; base not asserted',
    declared: 'Declared by an installed catalogue',
  };

  function sourceNames(ids) {
    const names = new Map(model.directory.sources.map((source) => [source.id, source.name]));
    return ids.map((id) => names.get(id) || id).join('; ');
  }

  /** Who this engineer is and where they are, with where each claim came from. */
  function identityAndLocation(engineer) {
    const section = el('div');
    section.append(el('h4', 'blueprints-section-title', 'Identity and location'));
    const facts = el('dl', 'blueprints-facts');
    facts.append(
      fact(
        'Engineer ID',
        engineer.id
          ? `Frontier engineer ID ${engineer.id}`
          : 'No engineer ID. Only a display name is known for this entry',
      ),
    );
    const reference = engineer.reference;
    if (reference) {
      const identityText =
        reference.identity.status === 'documented'
          ? 'Documented in Frontier’s Journal documentation'
          : 'Community-sourced; not independently confirmed';
      facts.append(
        fact(
          'ID source',
          engineer.identityConfirmed
            ? `${identityText}. Your Journal reported the same ID and name`
            : identityText,
        ),
      );
    }
    const place = engineer.place;
    if (place) {
      if (place.system) {
        facts.append(fact('System', place.system));
        facts.append(fact('Base', place.base || (place.source === 'directory' ? 'Not asserted' : 'Not recorded')));
      } else {
        facts.append(fact('Location', place.text || 'Not recorded'));
      }
      facts.append(
        fact(
          'Location source',
          place.source === 'directory'
            ? `Reference directory · ${LOCATION_STATUS[place.status] || place.status}`
            : 'Reference catalogue you installed',
        ),
      );
    } else {
      facts.append(fact('Location', 'Unknown. No reference lists where this engineer is'));
    }
    section.append(facts);
    if (place?.source === 'directory') {
      const evidence = el('details', 'blueprints-provenance');
      evidence.append(el('summary', '', 'Where the location comes from'));
      const lines = el('ul', 'blueprints-plain-list');
      lines.append(el('li', '', sourceNames(reference.location.evidence)));
      place.notes.forEach((note) => lines.append(el('li', '', note)));
      if (place.catalogueText) {
        lines.append(
          el('li', '', `Your installed catalogue says “${place.catalogueText}”. It is noted here, not used.`),
        );
      }
      evidence.append(lines);
      section.append(evidence);
    }
    if (engineer.identityNote) {
      section.append(
        el(
          'p',
          'blueprints-callout',
          `The reference directory lists this ID as “${engineer.identityNote.referenceName}”, but your Journal reports “${engineer.identityNote.journalName}”. The ID is what joins them. Check which is right before relying on either name.`,
        ),
      );
    }
    if (engineer.idBackedTwin) {
      const twin = el('p', 'blueprints-callout');
      twin.append(
        document.createTextNode(
          'An engineer with this name and a Frontier ID is also listed. This entry came from an event with no ID, so the two are not merged. ',
        ),
        button('Show the ID-backed entry', () => goToEngineer(engineer.idBackedTwin.key)),
      );
      section.append(twin);
    }
    return section;
  }

  /** What this engineer is listed as offering; nothing is inferred from rank or status. */
  function capabilitiesSection(engineer) {
    const section = el('div');
    section.append(el('h4', 'blueprints-section-title', 'What this engineer can do'));
    if (!engineer.capabilities.length) {
      section.append(
        el(
          'p',
          'blueprints-muted',
          engineer.declared
            ? 'The installed catalogue lists this engineer without any blueprints.'
            : 'Not available. No installed catalogue declares this engineer, and no bundled directory or installed catalogue lists specializations or grade limits for them. Crafts you have made with them are listed below.',
        ),
      );
      return section;
    }
    section.append(
      el(
        'p',
        'blueprints-muted',
        'Listed by the reference catalogue you installed. A listed grade is the most the catalogue says they offer, not what you can use now.',
      ),
    );
    const ul = el('ul', 'blueprints-plain-list');
    engineer.capabilities.forEach((cap) => {
      const li = el('li');
      if (model.byKey.has(cap.blueprintKey)) {
        li.append(button(cap.blueprintName, () => goToBlueprint(cap.blueprintKey)));
      } else {
        li.append(document.createTextNode(cap.blueprintName));
      }
      li.append(document.createTextNode(` — up to grade ${cap.maxGrade}`));
      ul.append(li);
    });
    section.append(ul);
    return section;
  }

  /** Requirement information and completion evidence, kept as separate questions. */
  function accessSection(engineer) {
    const plan = engineer.access;
    const section = el('div');
    section.append(el('h4', 'blueprints-section-title', 'Access requirements'));
    const requirement = el('div', 'blueprints-access-row');
    requirement.append(
      chip(plan.requirement.label, ACCESS_TONE[plan.requirement.state]),
      el('p', '', plan.requirement.text),
    );
    if (plan.requirement.source) {
      requirement.append(el('p', 'blueprints-muted', `Source: ${plan.requirement.source}.`));
    }
    section.append(requirement);
    const referral = el('div', 'blueprints-access-row');
    referral.append(
      el('strong', '', 'Referral'),
      el(
        'p',
        '',
        plan.referral ||
          'Referral information unavailable. No installed catalogue states who introduces this engineer.',
      ),
    );
    section.append(referral);
    const completion = el('div', 'blueprints-access-row');
    completion.append(
      chip(plan.completion.label, ACCESS_TONE[plan.completion.state]),
      el('p', '', plan.completion.detail),
    );
    section.append(completion);
    if (plan.contributions.length) {
      const offers = el('div', 'blueprints-access-row');
      offers.append(el('strong', '', 'Offers your Journal recorded'));
      const ul = el('ul', 'blueprints-plain-list');
      plan.contributions.forEach((line) =>
        ul.append(el('li', '', `${contributionLabel(line)} (${dateOnly(line.observedAt)})`)),
      );
      offers.append(
        ul,
        el(
          'p',
          'blueprints-muted',
          'The Journal does not say which requirement an offer answered, so this does not mark any requirement as met.',
        ),
      );
      section.append(offers);
    }
    section.append(
      el(
        'p',
        'blueprints-muted',
        'A documented requirement is never marked complete here. Only the Journal’s own access state counts as completion.',
      ),
    );
    return section;
  }

  function inspectEngineer(engineer) {
    inspector.replaceChildren(backButton());
    inspector.append(
      inspectorHead(engineer.location || (engineer.declared ? 'Location not recorded' : 'Location unknown'), engineer.name),
    );
    const status = engineerStatus(engineer.observed);
    const chips = el('div', 'blueprints-chips');
    chips.append(chip(status.label, status.tone));
    const rank = rankLabel(engineer.observed);
    if (rank) chips.append(chip(rank, 'muted'));
    if (engineer.reference) chips.append(chip('In reference directory', 'muted'));
    if (engineer.declared) chips.append(chip('Declared by catalogue', 'muted'));
    if (engineer.crafts.length) chips.append(chip('Crafts in your Journal', 'info'));
    if (engineer.records.length) chips.append(chip('Your records', 'muted'));
    inspector.append(chips);

    inspector.append(identityAndLocation(engineer));
    inspector.append(capabilitiesSection(engineer));
    inspector.append(accessSection(engineer));

    inspector.append(el('h4', 'blueprints-section-title', 'Observed progression'));
    inspector.append(observedFacts(engineer, status));
    if (engineer.observed && engineer.observed.history.length > 1) {
      const history = el('details', 'blueprints-provenance');
      history.append(el('summary', '', `Earlier observations (${engineer.observed.history.length - 1})`));
      const ul = el('ul', 'blueprints-plain-list');
      engineer.observed.history.slice(1).forEach((entry) => {
        const label = engineerStatus(entry).label;
        ul.append(
          el(
            'li',
            '',
            `${observedAtLabel(entry.observedAt)} — ${[label, rankLabel(entry), entry.rankProgress !== null ? `${entry.rankProgress}% rank progress` : null].filter(Boolean).join(', ')}`,
          ),
        );
      });
      history.append(ul);
      inspector.append(history);
    }

    if (engineer.crafts.length) {
      inspector.append(el('h4', 'blueprints-section-title', 'Crafts in your Journal'));
      inspector.append(
        el(
          'p',
          'blueprints-muted',
          `${plural(engineer.crafts.length, 'craft')} recorded; latest ${dateOnly(engineer.crafts[0].observed_at)}`,
        ),
      );
      const ul = el('ul', 'blueprints-plain-list');
      engineer.crafts.forEach((craft) => {
        const li = el('li');
        const known = model.byKey.has(String(craft.blueprint_id).toLowerCase());
        const label = craft.blueprint_label || craft.blueprint_id;
        li.append(
          known
            ? button(label, () => goToBlueprint(String(craft.blueprint_id).toLowerCase(), { grade: craft.grade }))
            : document.createTextNode(label),
          document.createTextNode(` — grade ${craft.grade}, ${dateOnly(craft.observed_at)}`),
        );
        ul.append(li);
      });
      inspector.append(ul);
    }
    if (engineer.records.length) {
      inspector.append(el('h4', 'blueprints-section-title', 'Records you entered'));
      inspector.append(
        el('p', 'blueprints-muted', 'Your own notes. They are separate from what the Journal observed and never change it.'),
      );
      const ul = el('ul', 'blueprints-plain-list');
      engineer.records.forEach((record) =>
        ul.append(el('li', '', `${record.engineer_label}: ${record.state || 'state unknown'}`)),
      );
      inspector.append(ul);
    }
    const matched = [...engineer.matchedByName];
    if (engineer.ambiguousName) {
      inspector.append(
        el('p', 'blueprints-callout', 'More than one engineer in the Journal shares this name, so crafts, catalogue entries and records that carry only a name are kept apart rather than guessed.'),
      );
    } else if (matched.length) {
      const sources = {
        progress: 'progress entries',
        crafts: 'journal crafts',
        catalogue: 'the catalogue',
        records: 'your records',
        contributions: 'contribution entries',
        directory: 'the reference directory',
      };
      const subject = matched.map((m) => sources[m]).join(' and ');
      inspector.append(
        el(
          'p',
          'blueprints-muted',
          `${subject.charAt(0).toUpperCase()}${subject.slice(1)} matched this engineer by display name only; they carry no engineer ID.`,
        ),
      );
    }
  }

  /** The observed block: values only where a Journal observation supports them. */
  function observedFacts(engineer, status) {
    const facts = el('dl', 'blueprints-facts');
    const observed = engineer.observed;
    if (!observed) {
      facts.append(fact('Status', 'Not observed'));
      const wrapper = el('div');
      wrapper.append(
        facts,
        el(
          'p',
          'blueprints-muted',
          'Your Journal has no EngineerProgress entry for this engineer. That does not mean they are locked; it means OmniCOVAS has not seen one. Unlock requirements are not reported by the Journal.',
        ),
      );
      return wrapper;
    }
    facts.append(fact('Status', status.label));
    if (observed.progress && observed.progressObservedAt && observed.progressObservedAt !== observed.observedAt) {
      // A rank-only update leaves the access state as last reported, at its own time.
      facts.append(fact('Status reported', observedAtLabel(observed.progressObservedAt)));
    }
    if (status.reportedAs) {
      facts.append(fact('Journal reported', `“${status.reportedAs}”, shown as reported`));
    }
    facts.append(
      fact('Rank', Number.isInteger(observed.rank) ? String(observed.rank) : 'Not reported'),
      fact('Rank progress', rankProgressLabel(observed) || 'Not reported'),
      fact('Last observed', observedAtLabel(observed.observedAt)),
      fact(
        'Observations',
        observed.observationCount > 1
          ? `${observed.observationCount}, first ${observedAtLabel(observed.firstObservedAt)}`
          : '1',
      ),
      fact('Source', 'Journal · EngineerProgress'),
      fact(
        'Identity',
        observed.engineerId
          ? `Frontier engineer ID ${observed.engineerId}`
          : 'Name only. The event carried no engineer ID',
      ),
    );
    const wrapper = el('div');
    wrapper.append(
      facts,
      el('p', 'blueprints-muted', 'As of the time shown. The game may have changed since.'),
    );
    return wrapper;
  }

  function renderInspector() {
    const key = state.selection[state.perspective];
    inspector.replaceChildren();
    inspector.dataset.mode = state.perspective;
    if (key === null || key === undefined) {
      inspector.append(
        el(
          'p',
          'blueprints-empty',
          state.perspective === 'upgrades'
            ? 'Select a planned upgrade to see its blueprint, grade and material needs.'
            : state.perspective === 'engineers'
              ? 'Select an engineer to see what is known about them.'
              : 'Select a blueprint to see its grades, materials and engineers.',
        ),
      );
      return;
    }
    if (state.perspective === 'upgrades') {
      const upgrade = model.upgrades.find((row) => row.id === key);
      if (upgrade) inspectUpgrade(upgrade);
    } else if (state.perspective === 'engineers') {
      const engineer = model.engineers.find((row) => row.key === key);
      if (engineer) inspectEngineer(engineer);
    } else {
      const blueprint = model.byKey.get(key);
      if (blueprint) inspectBlueprint(blueprint);
    }
  }

  collection.addEventListener('keydown', onListKeydown);
  root.addEventListener('keydown', (event) => {
    if (event.key !== '/' || event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return;
    if (collection.contains(event.target)) return; // handled by the list
    event.preventDefault();
    toolbar.querySelector('input')?.focus();
  });

  renderPanel();
  root.api = {
    model,
    state,
    goToBlueprint,
    goToUpgrade,
    goToEngineer,
    setPerspective,
  };
  return root;
}
