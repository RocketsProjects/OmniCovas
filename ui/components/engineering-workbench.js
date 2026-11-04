import { normalizeShipName } from '../utils/display-names.js';
import {
  createEngineeringPower,
  createKeepPoweredButton,
  createModulePower,
  isKeepPowered,
  keepPoweredCount,
  powerStateLabel,
  scopeLabel,
  withKeepPowered,
} from './engineering-power.js';

// Presentation only. Fitting, attributes, costs and reservations come from the
// shared Engineering API; no game formula or legal-fit inference lives here.
const node = (tag, cls = '', text) => {
  const result = document.createElement(tag);
  result.className = cls;
  if (text != null) result.textContent = String(text);
  return result;
};
const select = (name, entries, value = '') => {
  const result = node('select');
  result.name = name;
  entries.forEach(([id, label]) => {
    const option = node('option', '', label);
    option.value = id;
    option.selected = String(id) === String(value);
    result.append(option);
  });
  return result;
};
const label = (text, control) => {
  const result = node('label', 'engineering-form-field');
  result.append(node('span', 'engineering-form-label', text), control);
  return result;
};
const button = (text, action, cls = '') => {
  const result = node(
    'button',
    `ocv-btn-ghost engineering-action ${cls}`,
    text,
  );
  result.type = 'button';
  result.addEventListener('click', action);
  return result;
};
const idOf = (module) => module.module_id || module.technical?.item || '';
// Restored targets contain backend evidence. Requests contain commander choices
// only; the API re-resolves attributes and fitting rules from the pinned source.
const targetRequest = (target) =>
  Object.fromEntries(
    [
      'slot',
      'module_id',
      'module_label',
      'target_state',
      'blueprint_id',
      'target_grade',
      'experimental_effect',
    ]
      .filter((key) => target[key] !== undefined)
      .map((key) => [key, target[key]]),
  );
const moduleName = (module) =>
  /^\d+[A-I]\b/.test(module.name || '') || !module.class || !module.rating
    ? module.name
    : `${module.class}${module.rating} ${module.name}`;
const identity = (ship = {}) => `${ship.ship_type || ''}:${ship.ship_id ?? ''}`;
const slotLabel = (module) =>
  (module.slot_label || module.slot || '')
    .replace(/^TinyHardpoint(\d+)$/i, 'Utility $1')
    .replace(/^(Small|Medium|Large|Huge)Hardpoint(\d+)$/i, '$1 $2')
    .replace(/^Slot0*(\d+)_Size(\d+)$/i, 'Internal $1 · class $2')
    .replace(/^Military0*(\d+)$/i, 'Military $1')
    .replace(/^Cargo0*(\d+)$/i, 'Cargo $1')
    .replace(/([a-z])([A-Z])/g, '$1 $2');
const physical = {
  mass: ['Mass', 't'],
  pwrcap: ['Output', 'MW'],
  pwrdraw: ['Draw', 'MW'],
  heateff: ['Heat coefficient', 'coef'],
  integ: ['Integrity', ''],
};
const shipMetrics = [
  ['operating_power_capacity', 'Available power'],
  ['power_draw', 'Deployed draw'],
  ['deployed_power_headroom', 'Deployed headroom'],
  ['retracted_power_draw', 'Retracted draw'],
  ['retracted_power_headroom', 'Retracted headroom'],
  ['unladen_mass', 'Unladen mass'],
  ['cargo_capacity', 'Cargo capacity'],
  ['fully_laden_jump_range', 'Laden jump'],
  ['configured_jump_range', 'Configured jump'],
  ['max_jump_range', 'Max jump · no cargo'],
];
const format = (value, unit = '', decimals = 3) =>
  value == null || !Number.isFinite(Number(value))
    ? '—'
    : `${Number(value).toLocaleString('en-US', { maximumFractionDigits: decimals })}${unit ? ` ${unit}` : ''}`;
const statTable = (cls, baselineLabel = 'Installed') => {
  const table = node('table', cls);
  const head = node('thead');
  const row = node('tr');
  ['Attribute', baselineLabel, 'Planned', 'Δ'].forEach((text) => {
    const cell = node('th', '', text);
    cell.scope = 'col';
    row.append(cell);
  });
  head.append(row);
  table.append(head);
  const body = node('tbody');
  table.append(body);
  return { table, body };
};

export function createEngineeringWorkbench(controller, overview) {
  const progression = overview.progression || {};
  const hullName = (ship = {}) =>
    progression.reference_catalog?.hulls?.find((h) => h.id === ship.ship_type)
      ?.name || normalizeShipName(ship.ship_type).display;
  const labelShip = (ship = {}) =>
    [hullName(ship), ship.ship_ident].filter(Boolean).join(' · ');
  const variants = progression.saved_configurations || [];
  const saved = variants.find(
    (v) => v.build_plan_id === controller._selectedBuildId,
  );
  const workbench =
    saved?.workbench ||
    controller._observedWorkbench ||
    progression.workbench ||
    {};
  const groups = [];
  for (const group of (workbench.groups || []).filter(
    (g) => g.id !== 'special',
  )) {
    const military = group.modules.filter(
      (m) =>
        m.reference_slot?.group === 'military' || /^Military/i.test(m.slot),
    );
    const armour = group.modules.filter((m) => m.slot === 'Armour');
    const rest = group.modules.filter(
      (m) => !military.includes(m) && !armour.includes(m),
    );
    if (rest.length) groups.push({ ...group, modules: rest });
    if (military.length)
      groups.push({
        id: 'military',
        label: 'Military compartments',
        modules: military,
      });
    if (armour.length)
      groups.push({ id: 'armour', label: 'Armour', modules: armour });
  }
  const modules = groups.flatMap((g) => g.modules || []);
  const section = node(
    'section',
    'engineering-build-designer engineering-compact-workbench',
  );
  section.id = 'engineering-build-designer';
  section.setAttribute('aria-label', 'Ship outfitting workbench');
  if (workbench.state !== 'verified_local' || !modules.length) {
    section.dataset.empty = 'true';
    section.append(
      node(
        'p',
        'engineering-empty',
        'No ship loadout available. Saved plans and catalogue ships remain available below.',
      ),
    );
    const hulls = progression.reference_catalog?.hulls || [];
    if (hulls.length) {
      const hull = select(
        'new_hull',
        hulls.map((h) => [h.id, h.name]),
      );
      const message = node('p', 'engineering-action-status');
      section.append(
        label('Choose a hull', hull),
        button('Start ship design', async () => {
          try {
            const result = await controller.fetchJson(
              `/engineering/workbench/hulls/${encodeURIComponent(hull.value)}`,
            );
            controller._observedWorkbench = result.workbench;
            controller._selectedBuildId = null;
            controller._selectedObservationId = null;
            controller.render(overview);
          } catch (e) {
            message.textContent = e.message;
          }
        }),
        message,
      );
    }
    return section;
  }
  const referenceHull = workbench.planning_hull_id || null;
  const configuration = saved ? workbench.planned_configuration : null;
  const key = `${saved?.build_plan_id || controller._selectedObservationId || 'current'}:${workbench.catalog?.catalog_id || ''}@${workbench.catalog?.version || ''}:${identity(workbench.ship)}:${JSON.stringify(modules.map((m) => [m.slot, idOf(m), m.installed_engineering, m.attribute_changes]))}`;
  controller._outfittingDrafts ||= new Map();
  if (!controller._outfittingDrafts.has(key))
    controller._outfittingDrafts.set(key, {
      key,
      targets: new Map(
        (configuration?.targets || []).map((t) => [t.slot, { ...t }]),
      ),
      title: saved?.title || `${hullName(workbench.ship)} variant`,
      selectedSlot:
        modules.find((m) => m.slot === 'PowerPlant')?.slot || modules[0].slot,
      cargoLock: configuration?.constraints?.preserve_cargo_capacity !== false,
      priority:
        progression.builds?.find(
          (b) => b.build_plan_id === saved?.build_plan_id,
        )?.priority || 'normal',
      performance: configuration?.performance || workbench.comparison,
      requirements: progression.builds?.find(
        (b) => b.build_plan_id === saved?.build_plan_id,
      ),
      conditions: configuration?.operating_conditions || {},
      conditionsDirty: false,
      dirty: false,
      powerPlan: structuredClone(
        configuration?.power_plan ||
          workbench.comparison?.power_management?.plan || {
            modules: [],
            scenario: 'normal',
            deployment: 'deployed',
            custom_percent: 100,
            protect: ['normal:deployed'],
          },
      ),
      powerDirty: false,
      powerView: controller._preferredWorkbenchView === 'power',
    });
  const draft = controller._outfittingDrafts.get(key);
  draft.history ||= [];
  const snapshot = () =>
    JSON.stringify({
      targets: [...draft.targets],
      powerPlan: draft.powerPlan,
      powerDirty: draft.powerDirty,
      cargoLock: draft.cargoLock,
      conditions: draft.conditions,
      conditionsDirty: draft.conditionsDirty,
    });
  draft.lastSnapshot ||= snapshot();
  function restoreSnapshot(value) {
    const old = JSON.parse(value);
    draft.targets = new Map(old.targets);
    draft.powerPlan = old.powerPlan;
    draft.powerDirty = old.powerDirty;
    draft.cargoLock = old.cargoLock;
    draft.conditions = old.conditions || {};
    draft.conditionsDirty = old.conditionsDirty;
    draft.lastSnapshot = value;
    cargo.checked = draft.cargoLock;
    renderEditor();
    renderNavigator();
    preview();
  }
  if (!draft.dirty) {
    draft.performance = configuration?.performance || workbench.comparison;
    draft.requirements = progression.builds?.find(
      (b) => b.build_plan_id === saved?.build_plan_id,
    );
  }
  let selected =
    modules.find((m) => m.slot === draft.selectedSlot) || modules[0];
  let pending = false,
    error = '';
  let performance = draft.performance || workbench.comparison;
  let requirements = draft.requirements;
  let modulePower;
  let fittingMessage = '';
  let acceptedSnapshot = snapshot();
  const hasDesign = () =>
    !!(
      draft.forceSave ||
      referenceHull ||
      draft.conditionsDirty ||
      draft.targets.size ||
      draft.powerDirty ||
      draft.powerPlan.modules?.length ||
      draft.powerPlan.scenario !== 'normal'
    );
  const form = node('form', 'engineering-build-workbench-form');
  const toolbar = node('div', 'engineering-workbench-toolbar');
  const ships = new Map([
    [
      identity(progression.workbench?.ship),
      ['current', `${labelShip(progression.workbench?.ship)} · current`],
    ],
  ]);
  (progression.observed_ships || []).forEach((s) => {
    if (!ships.has(identity(s)))
      ships.set(identity(s), [
        `obs:${s.observation_id}`,
        `${labelShip(s)} · ${s.observed_at?.slice(0, 10) || 'observed'}`,
      ]);
  });
  variants.forEach((v) => {
    const s = v.workbench.ship;
    if (!ships.has(identity(s)))
      ships.set(identity(s), [`saved:${v.build_plan_id}`, labelShip(s)]);
  });
  for (const hull of progression.reference_catalog?.hulls || [])
    ships.set(`hull:${hull.id}`, [
      `hull:${hull.id}`,
      `${hull.name} · new build`,
    ]);
  const currentShipValue =
    (referenceHull && !saved
      ? `hull:${referenceHull}`
      : ships.get(identity(workbench.ship))?.[0]) || 'current';
  const shipSelect = select('ship', [...ships.values()], currentShipValue);
  const loadShip = async (value) => {
    shipSelect.disabled = true;
    form.inert = true;
    try {
      if (value.startsWith('hull:')) {
        const result = await controller.fetchJson(
          `/engineering/workbench/hulls/${encodeURIComponent(value.slice(5))}`,
        );
        controller._selectedObservationId = null;
        controller._observedWorkbench = result.workbench;
        controller._selectedBuildId = null;
      } else if (value.startsWith('obs:')) {
        const id = Number(value.slice(4));
        const result = await controller.fetchJson(
          `/engineering/workbench/observations/${id}`,
        );
        controller._selectedObservationId = id;
        controller._observedWorkbench = result.workbench;
        controller._selectedBuildId = null;
      } else {
        controller._selectedObservationId = null;
        controller._observedWorkbench = null;
        controller._selectedBuildId = value.startsWith('saved:')
          ? value.slice(6)
          : null;
      }
      controller.render(overview);
      controller.root
        .querySelector('[name=ship]')
        ?.focus({ preventScroll: true });
    } catch (failure) {
      status.textContent = failure.message || 'Ship observation unavailable.';
      shipSelect.value = currentShipValue;
      shipSelect.disabled = false;
      form.inert = false;
    }
  };
  shipSelect.addEventListener('change', () => loadShip(shipSelect.value));
  const variantSelect = select(
    'saved_variant',
    [
      ['', referenceHull ? 'Stock · new variant' : 'Installed · new variant'],
      ...variants
        .filter((v) => identity(v.workbench.ship) === identity(workbench.ship))
        .map((v) => [v.build_plan_id, v.title]),
    ],
    saved?.build_plan_id || '',
  );
  variantSelect.addEventListener('change', () => {
    if (!variantSelect.value) {
      loadShip(shipSelect.value);
      return;
    }
    controller._selectedBuildId = variantSelect.value;
    controller.render(overview);
    controller.root
      .querySelector('[name=saved_variant]')
      ?.focus({ preventScroll: true });
  });
  const title = node('input');
  title.name = 'title';
  title.required = true;
  title.maxLength = 128;
  title.value = draft.title;
  title.addEventListener('input', () => {
    draft.title = title.value;
  });
  const save = node(
    'button',
    'ocv-btn engineering-action engineering-save',
    'Save variant',
  );
  save.type = 'submit';
  const status = node('span', 'engineering-action-status');
  status.setAttribute('role', 'status');
  toolbar.append(
    label('Ship', shipSelect),
    label('Build', variantSelect),
    label('Name', title),
    save,
  );
  const buildActions = node('div', 'engineering-build-actions');
  const clone = button('Clone', () => {
    draft.forceSave = true;
    title.value = draft.title =
      `${title.value.replace(/ · copy$/, '')} · copy`.slice(0, 128);
    preview();
    title.focus();
  });
  const undo = button('Undo', () => {
    const previous = draft.history.pop();
    if (previous) restoreSnapshot(previous);
  });
  const compareButton = button('Compare', () => openAnalysis('compare'));
  const transfer = node('details', 'engineering-build-transfer');
  transfer.append(node('summary', '', 'Import / export'));
  const transferText = node('textarea');
  transferText.name = 'build_transfer';
  transferText.setAttribute('aria-label', 'OmniCOVAS configuration JSON');
  transferText.placeholder = 'Paste an OmniCOVAS configuration';
  transfer.append(
    transferText,
    button('Export configuration', () => {
      transferText.value = JSON.stringify(
        {
          format: 'omnicovas-configuration-v1',
          hull: workbench.ship.ship_type,
          catalog: workbench.catalog,
          baseline_signature: JSON.stringify(
            modules.map((m) => [m.slot, idOf(m), m.installed_engineering]),
          ),
          title: title.value,
          module_targets: [...draft.targets.values()].map(targetRequest),
          power_plan: draft.powerPlan,
          operating_conditions: draft.conditions,
          preserve_cargo_capacity: draft.cargoLock,
        },
        null,
        2,
      );
      transferText.focus();
      transferText.select();
    }),
    button('Import configuration', () => {
      try {
        if (transferText.value.length > 100000)
          throw new Error('Configuration is too large.');
        const data = JSON.parse(transferText.value);
        if (
          data.format !== 'omnicovas-configuration-v1' ||
          data.hull !== workbench.ship.ship_type
        )
          throw new Error(
            'Choose the matching hull and an OmniCOVAS configuration.',
          );
        if (
          data.baseline_signature !==
          JSON.stringify(
            modules.map((m) => [m.slot, idOf(m), m.installed_engineering]),
          )
        )
          throw new Error(
            'Choose the original ship observation or stock hull before importing this variant.',
          );
        if (
          !Array.isArray(data.module_targets) ||
          data.module_targets.length > 64
        )
          throw new Error('Invalid module list.');
        const slots = new Set();
        for (const target of data.module_targets) {
          if (
            !modules.some((m) => m.slot === target.slot) ||
            slots.has(target.slot)
          )
            throw new Error('Unknown or repeated slot.');
          slots.add(target.slot);
        }
        draft.targets = new Map(
          data.module_targets.map((t) => [t.slot, targetRequest(t)]),
        );
        draft.powerPlan = structuredClone(
          data.power_plan || workbench.comparison?.power_management?.plan || {},
        );
        draft.powerDirty = true;
        draft.conditions = data.operating_conditions || {};
        draft.conditionsDirty = Object.keys(draft.conditions).length > 0;
        draft.cargoLock = data.preserve_cargo_capacity !== false;
        cargo.checked = draft.cargoLock;
        title.value = draft.title = String(
          data.title || 'Imported variant',
        ).slice(0, 128);
        renderEditor();
        preview();
      } catch (e) {
        status.textContent = e.message;
      }
    }),
    node(
      'p',
      '',
      'Local OmniCOVAS format. Every choice is revalidated. EDSY and Coriolis formats are not supported.',
    ),
  );
  buildActions.append(clone, undo, compareButton, transfer);
  toolbar.append(buildActions);
  form.append(toolbar);
  const flightStrip = node('div', 'engineering-flight-strip');
  flightStrip.setAttribute('aria-label', 'Live planned ship performance');
  form.append(flightStrip);
  const viewControls = node('div', 'engineering-workbench-views');
  const outfitView = button('Outfitting', () => setPowerView(false));
  const analysisView = button('Analysis', () => openAnalysis('navigation'));
  const powerScenario = select(
    'outfitting_power_scenario',
    (performance?.power_management?.scenarios || []).map((s) => [
      s.id,
      s.label,
    ]),
    draft.powerPlan.scenario,
  );
  powerScenario.setAttribute('aria-label', 'Power output scenario');
  powerScenario.addEventListener('change', () =>
    applyPowerPlan({
      ...structuredClone(draft.powerPlan),
      scenario: powerScenario.value,
    }),
  );
  const suggestPower = button('Suggest priorities', () => powerPanel.suggest());
  const resetPower = button('Reset priorities', () => powerPanel.reset());
  const keepScope = node('span', 'engineering-keep-powered-scope');
  keepScope.setAttribute('role', 'status');
  const mobileShip = button('Ship', () => {
    section.dataset.mobileView = 'ship';
  });
  const mobileEditor = button('Module', () => {
    section.dataset.mobileView = 'module';
  });
  mobileShip.classList.add('engineering-mobile-command');
  mobileEditor.classList.add('engineering-mobile-command');
  viewControls.append(
    outfitView,
    analysisView,
    powerScenario,
    suggestPower,
    resetPower,
    keepScope,
    mobileShip,
    mobileEditor,
  );
  section.dataset.mobileView = 'ship';
  form.append(viewControls);
  const workspace = node('div', 'engineering-builder-workspace');
  const navigator = node('nav', 'engineering-module-navigator');
  navigator.setAttribute('aria-label', 'Outfitting slots');
  const editor = node('section', 'engineering-module-editor');
  editor.setAttribute('aria-label', 'Selected module');
  const comparison = node('aside', 'engineering-performance-panel');
  comparison.setAttribute(
    'aria-label',
    'Installed and planned ship statistics',
  );
  const analysis = node('section', 'engineering-analysis-workspace');
  analysis.hidden = true;
  const analysisNav = node('nav', 'engineering-analysis-nav');
  analysisNav.setAttribute('aria-label', 'Ship analysis categories');
  const analysisContent = node('div', 'engineering-analysis-content');
  const categories = [
    ['overview', 'Ship summary'],
    ['navigation', 'Navigation'],
    ['handling', 'Handling'],
    ['thermal', 'Thermal'],
    ['power', 'Power'],
    ['shields', 'Shields & defence'],
    ['armour', 'Armour'],
    ['weapons', 'Weapons & distributor'],
    ['cost', 'Cost & rebuy'],
    ['retrofit', 'Retrofit & materials'],
    ['compare', 'Compare builds'],
  ];
  let analysisCategory = 'navigation';
  for (const [id, text] of categories) {
    const b = button(text, () => openAnalysis(id));
    b.dataset.analysis = id;
    analysisNav.append(b);
  }
  analysis.append(analysisNav, analysisContent);
  function openAnalysis(category) {
    analysisCategory = category;
    setPowerView(false);
    section.dataset.mobileView = 'analysis';
    workspace.hidden = true;
    analysis.hidden = false;
    outfitView.setAttribute('aria-pressed', 'false');
    analysisView.setAttribute('aria-pressed', 'true');
    renderAnalysis();
  }
  const moduleStats = node('div', 'engineering-module-statistics');
  const materialPanel = node('section', 'engineering-compact-materials');
  const notices = node('div', 'engineering-fitting-status');
  notices.setAttribute('role', 'status');
  const cargo = node('input');
  cargo.type = 'checkbox';
  cargo.name = 'preserve_cargo_capacity';
  cargo.checked = draft.cargoLock;
  cargo.addEventListener('change', () => {
    draft.cargoLock = cargo.checked;
    preview();
  });
  const mobileSlot = node('select');
  mobileSlot.name = 'slot';
  mobileSlot.setAttribute('aria-label', 'Module slot');
  groups.forEach((g) => {
    const optgroup = node('optgroup');
    optgroup.label = g.label;
    g.modules.forEach((m) => {
      const op = node('option', '', `${slotLabel(m)} · ${m.name}`);
      op.value = m.slot;
      op.selected = m.slot === selected.slot;
      optgroup.append(op);
    });
    mobileSlot.append(optgroup);
  });
  mobileSlot.addEventListener('change', () => chooseSlot(mobileSlot.value));
  const mobileLabel = label('Slot', mobileSlot);
  mobileLabel.classList.add('engineering-mobile-slot');
  form.append(mobileLabel);
  const powerPanel = createEngineeringPower({
    busyChanged: (busy) => {
      suggestPower.disabled = busy || pending || !!error;
    },
    baselineLabel: referenceHull ? 'catalogue stock' : 'installed',
    slotName: (slot) =>
      slotLabel(modules.find((m) => m.slot === slot) || { slot }),
    getPlan: () => draft.powerPlan,
    change: applyPowerPlan,
    editModule: (slot) => {
      setPowerView(false);
      chooseSlot(slot);
      editor.querySelector('[name=module_id]')?.focus({ preventScroll: true });
    },
    propose: async () => {
      const body = JSON.stringify(previewBody());
      const result = await controller.fetchJson(
        '/engineering/workbench/power-proposal',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body,
        },
      );
      if (body !== JSON.stringify(previewBody()))
        throw new Error('The build changed. Request a new proposal.');
      return result;
    },
  });
  form.append(powerPanel.proposalRoot);
  function applyPowerPlan(plan) {
    draft.powerPlan = plan;
    draft.powerDirty = true;
    preview();
  }
  function changePowerSlot(slot, fields) {
    const plan = structuredClone(draft.powerPlan);
    plan.modules ||= [];
    let row = plan.modules.find((r) => r.slot === slot);
    if (!row) {
      row = { slot, required_in: [] };
      plan.modules.push(row);
    }
    Object.assign(row, fields);
    applyPowerPlan(plan);
  }
  function toggleKeepPowered(slot, on) {
    applyPowerPlan(withKeepPowered(draft.powerPlan, slot, on));
  }
  function setPowerView(active) {
    if (active) {
      openAnalysis('power');
      return;
    }
    draft.powerView = active;
    controller._preferredWorkbenchView = active ? 'power' : 'outfitting';
    analysis.hidden = true;
    section.dataset.mobileView = 'ship';
    analysisView.setAttribute('aria-pressed', 'false');
    workspace.hidden = active;
    powerPanel.root.hidden = !active;
    mobileLabel.hidden = active;
    outfitView.setAttribute('aria-pressed', String(!active));
  }
  function previewBody() {
    return {
      module_targets: [...draft.targets.values()].map(targetRequest),
      ...(Object.keys(draft.conditions || {}).length
        ? { operating_conditions: draft.conditions }
        : {}),
      power_plan: draft.powerPlan,
      ...(!saved && referenceHull ? { hull_id: referenceHull } : {}),
      baseline_build_id: saved?.build_plan_id || null,
      baseline_observation_id:
        saved || referenceHull
          ? null
          : controller._selectedObservationId || null,
      preserve_cargo_capacity: cargo.checked,
      priority: draft.priority || 'normal',
    };
  }

  function choicesFor(module) {
    const entries = [
      ...(module.module_options || module.compatible_modules || []),
    ];
    const installedId = idOf(module);
    if (installedId && !entries.some((m) => m.id === installedId))
      entries.unshift({
        id: installedId,
        name: module.name,
        stats: module.base_stats || {},
        blueprint_options: module.blueprint_options || [],
      });
    return entries;
  }
  function blueprintsFor(module, choice) {
    if (Array.isArray(choice?.blueprint_ids))
      return (workbench.blueprint_definitions || [])
        .filter((b) => choice.blueprint_ids.includes(b.id))
        .map((b) => ({
          ...b,
          label: b.name,
          grades: Object.keys(b.grades || {})
            .map(Number)
            .sort(),
          experimentals: (b.experimentals || [])
            .filter(
              (e) =>
                !Array.isArray(choice.experimental_ids) ||
                choice.experimental_ids.includes(e.id),
            )
            .map((e) => ({ ...e, label: e.name })),
        }));
    return choice?.blueprint_options || module.blueprint_options || [];
  }
  function addStatRow(body, id, text, installed, planned, unit, cls = '') {
    const row = node('tr', cls);
    row.dataset.metric = id;
    const heading = node('th', '', text);
    heading.scope = 'row';
    const precision =
      id.includes('jump') || id === 'heateff' || unit === 'MW' ? 4 : 3;
    const old = node(
      'td',
      'engineering-performance-installed',
      format(installed, unit, precision),
    );
    const next = node(
      'td',
      'engineering-performance-planned',
      error ? '—' : pending ? '…' : format(planned, unit, precision),
    );
    const delta =
      error || installed == null || planned == null
        ? null
        : planned - installed;
    const change = node(
      'td',
      'engineering-performance-delta',
      pending
        ? '…'
        : delta == null
          ? '—'
          : `${delta > 0 ? '+' : ''}${format(delta, '', 4)}`,
    );
    if (delta)
      change.classList.add(
        (delta < 0 &&
          [
            'mass',
            'pwrdraw',
            'heateff',
            'unladen_mass',
            'power_draw',
            'retracted_power_draw',
          ].includes(id)) ||
          (delta > 0 &&
            ![
              'mass',
              'pwrdraw',
              'heateff',
              'unladen_mass',
              'power_draw',
              'retracted_power_draw',
            ].includes(id))
          ? 'beneficial'
          : 'adverse',
      );
    old.title = installed == null ? 'Unavailable' : String(installed);
    next.title =
      error ||
      (planned == null
        ? 'Unavailable; see calculation details'
        : String(planned));
    row.append(heading, old, next, change);
    body.append(row);
  }
  function renderModuleStats() {
    moduleStats.replaceChildren();
    const { table, body } = statTable(
      'engineering-selected-stat-table',
      referenceHull ? 'Stock' : 'Installed',
    );
    const target = draft.targets.get(selected.slot);
    const attrComparison = performance?.module_attribute_comparisons?.find(
      (m) => m.slot === selected.slot,
    );
    const installed = selected.installed_attributes || {};
    const plan = target
      ? Object.fromEntries(
          (attrComparison?.attributes || []).map((a) => [a.id, a.planned]),
        )
      : installed;
    const before = {
      ...installed,
      ...Object.fromEntries(
        (attrComparison?.attributes || []).map((a) => [a.id, a.installed]),
      ),
    };
    const definitions = selected.attribute_definitions || {};
    const relevant = [
      ...Object.keys(physical),
      'fsdoptmass',
      'maxfuel',
      'engoptmass',
      'engmaxmass',
      'engoptmul',
      'genoptmass',
      'genmaxmass',
      'genoptmul',
      'shieldbst',
      'cargocap',
      'fuelcap',
      'engcap',
      'engchg',
      'wepcap',
      'wepchg',
      'syscap',
      'syschg',
      'damage',
      'rof',
      'dps',
      'maximumrng',
      'ammoclip',
      'scooprate',
    ];
    relevant
      .filter((k) => k in before || k in plan)
      .slice(0, 13)
      .forEach((k) =>
        addStatRow(
          body,
          k,
          physical[k]?.[0] || definitions[k]?.name || k,
          before[k],
          target?.target_state === 'empty' ? null : plan[k],
          physical[k]?.[1] ?? definitions[k]?.unit ?? '',
        ),
      );
    if (!body.children.length) {
      const p = node(
        'p',
        'engineering-empty',
        'Module attributes unavailable.',
      );
      moduleStats.append(p);
    } else moduleStats.append(table);
    if (
      target &&
      target.target_state !== 'empty' &&
      selected.reference_variant_note
    )
      moduleStats.append(
        node(
          'p',
          'engineering-fitting-warning',
          selected.reference_variant_note,
        ),
      );
    const details = node('details', 'engineering-source-why');
    details.append(node('summary', '', 'All attributes & source'));
    (attrComparison?.attributes || []).forEach((a) =>
      details.append(
        node(
          'p',
          '',
          `${a.label}: ${format(a.installed, a.unit)} → ${error ? '—' : pending ? '…' : format(a.planned, a.unit)}`,
        ),
      ),
    );
    details.append(
      node(
        'p',
        '',
        `Slot: ${selected.slot}. Module: ${target?.module_id || idOf(selected)}.`,
      ),
    );
    (attrComparison?.notes || []).forEach((text) =>
      details.append(node('p', '', text)),
    );
    moduleStats.append(details);
  }
  function renderRequirements() {
    materialPanel.replaceChildren(node('h3', '', 'Materials'));
    materialSummary.textContent = 'Materials';
    if (error) {
      materialPanel.append(
        node('p', 'engineering-empty', 'Calculation unavailable'),
      );
      return;
    }
    if (pending) {
      materialSummary.textContent = 'Materials · calculating…';
      materialPanel.append(node('p', '', 'Calculating…'));
      return;
    }
    const materials = requirements?.materials || [];
    if (!draft.targets.size) {
      materialPanel.append(
        node(
          'p',
          'engineering-empty',
          hasDesign()
            ? 'No engineering materials needed'
            : 'No planned changes',
        ),
      );
      return;
    }
    if (!requirements) {
      materialPanel.append(
        node('p', 'engineering-empty', 'Requirements unavailable'),
      );
      return;
    }
    const shortage = materials.some((m) => m.deficit > 0);
    const unknown = materials.some((m) => m.reserved == null);
    materialSummary.textContent = `Materials · ${materials.length} types · ${unknown ? 'inventory unknown' : shortage ? 'shortfall' : 'budget covered'}`;
    const heading = node(
      'p',
      'engineering-material-budget',
      'Rank-5 completion budget',
    );
    heading.title =
      'Exact per-roll recipes; totals assume rank-5 access and completion of unfinished grades. Personal access and partial progress remain unverified.';
    materialPanel.append(heading);
    const table = node('table', 'engineering-requirements-table');
    const h = node('tr');
    ['Material', 'Need', 'Reserved', 'Short'].forEach((t) =>
      h.append(node('th', '', t)),
    );
    const thead = node('thead');
    thead.append(h);
    table.append(thead);
    const body = node('tbody');
    materials.forEach((m) => {
      const row = node('tr');
      const name = node('th', '', m.display_name);
      name.scope = 'row';
      name.title = `Available before this reservation: ${m.held_before_reservation ?? 'unknown'}`;
      row.append(
        name,
        node('td', '', m.required ?? '—'),
        node('td', '', m.reserved ?? '—'),
        node('td', m.deficit ? 'adverse' : '', m.deficit ?? '—'),
      );
      body.append(row);
    });
    table.append(body);
    materialPanel.append(
      materials.length
        ? table
        : node('p', 'engineering-empty', 'No additional materials'),
    );
    const detail = node('details', 'engineering-source-why');
    detail.append(node('summary', '', 'Recipes & reservations'));
    (requirements.unknown_inputs || []).forEach((t) =>
      detail.append(node('p', '', t)),
    );
    detail.append(
      node(
        'p',
        '',
        'Preview includes competing active builds. Saving creates a separate variant and its shared reservation.',
      ),
    );
    materialPanel.append(detail);
  }
  function renderFlightStrip() {
    flightStrip.replaceChildren();
    const configuredLoading = Object.values(draft.conditions || {}).some(
      (v) => v != null,
    );
    const metrics = performance?.metrics || [];
    const power = performance?.power_management;
    const scenario = draft.powerPlan.scenario || 'normal';
    const retracted = power?.cases.find(
      (c) => c.id === `${scenario}:retracted`,
    )?.planned;
    const deployed = power?.cases.find(
      (c) => c.id === `${scenario}:deployed`,
    )?.planned;
    for (const [id, text] of [
      ['retracted_power_draw', 'Retracted'],
      ['power_draw', 'Deployed'],
      ['operating_power_capacity', 'Generation'],
      ['deployed_power_headroom', 'Headroom'],
      [
        configuredLoading ? 'configured_jump_range' : 'fully_laden_jump_range',
        configuredLoading ? 'Configured jump' : 'Laden jump',
      ],
      ['unladen_mass', 'Unladen mass'],
      ['cargo_capacity', 'Cargo'],
    ]) {
      const metric = metrics.find((m) => m.id === id);
      const summary = id === 'retracted_power_draw' ? retracted : deployed;
      const powerValue =
        id === 'operating_power_capacity'
          ? deployed?.generation_mw
          : id === 'deployed_power_headroom'
            ? deployed?.headroom_mw
            : ['retracted_power_draw', 'power_draw'].includes(id)
              ? summary?.requested_mw
              : undefined;
      const value =
        power &&
        [
          'operating_power_capacity',
          'deployed_power_headroom',
          'retracted_power_draw',
          'power_draw',
        ].includes(id)
          ? powerValue
          : metric?.planned?.value;
      const tile = ['retracted_power_draw', 'power_draw'].includes(id)
        ? button('', () => {
          const deployment =
            id === 'retracted_power_draw' ? 'retracted' : 'deployed';
          if (draft.powerPlan.deployment !== deployment)
            applyPowerPlan({
              ...structuredClone(draft.powerPlan),
              deployment,
            });
          openAnalysis('power');
        })
        : node('div');
      tile.classList.add('engineering-flight-metric');
      tile.dataset.flightMetric = id;
      tile.append(
        node('span', '', text),
        node(
          'strong',
          '',
          error
            ? '—'
            : pending
              ? '…'
              : format(
                  value,
                  metric?.planned?.unit ||
                    (powerValue !== undefined ? 'MW' : ''),
                  2,
                ),
        ),
      );
      if (
        id === 'deployed_power_headroom' &&
        (value < 0 || deployed?.required_lost?.length)
      )
        tile.classList.add('adverse');
      if (['retracted_power_draw', 'power_draw'].includes(id))
        tile.append(
          node(
            'small',
            '',
            pending || error
              ? 'Headroom —'
              : `Headroom ${format(summary?.headroom_mw, 'MW', 2)}`,
          ),
        );
      if (id === 'operating_power_capacity')
        tile.append(
          node(
            'small',
            '',
            power?.scenarios.find((s) => s.id === scenario)?.label ||
              'Verified generation',
          ),
        );
      if (id === 'deployed_power_headroom')
        tile.append(
          node(
            'small',
            '',
            pending || error
              ? 'Calculating…'
              : deployed?.required_lost?.length
                ? `${deployed.required_lost.length} required systems lose power`
                : deployed?.shutdown_groups?.length
                  ? `Groups ${deployed.shutdown_groups.join(', ')} shut down`
                  : 'All enabled groups powered',
          ),
        );
      if (['retracted_power_draw', 'power_draw'].includes(id))
        tile.title = 'Open power priorities and shutdown simulation';
      flightStrip.append(tile);
    }
  }
  function renderAnalysis() {
    analysisNav
      .querySelectorAll('button')
      .forEach((b) =>
        b.setAttribute(
          'aria-pressed',
          String(b.dataset.analysis === analysisCategory),
        ),
      );
    if (analysisCategory === 'power') {
      if (powerPanel.root.parentElement !== analysisContent)
        analysisContent.replaceChildren(powerPanel.root);
      powerPanel.root.hidden = false;
      return;
    }
    analysisContent.replaceChildren();
    if (analysisCategory === 'compare') {
      const other = select('compare_build', [
        ['', referenceHull ? 'Stock baseline' : 'Installed / baseline'],
        ...variants
          .filter(
            (v) => v.workbench.ship.ship_type === workbench.ship.ship_type,
          )
          .map((v) => [v.build_plan_id, v.title]),
      ]);
      const results = node('div');
      const fill = () => {
        results.replaceChildren();
        const reference = variants.find((v) => v.build_plan_id === other.value)
          ?.workbench.planned_configuration?.performance;
        const { table, body } = statTable('engineering-variant-comparison');
        table.querySelector('thead').children[0].children[1].textContent =
          'Reference';
        table.querySelector('thead').children[0].children[2].textContent =
          'This draft';
        for (const m of performance?.metrics || []) {
          if (!shipMetrics.some(([id]) => id === m.id)) continue;
          const before =
            reference?.metrics?.find((r) => r.id === m.id)?.planned ||
            m.installed;
          addStatRow(
            body,
            m.id,
            m.label,
            before?.value,
            m.planned?.value,
            m.planned?.unit,
          );
        }
        results.append(table);
      };
      other.addEventListener('change', fill);
      analysisContent.append(label('Compare against', other), results);
      fill();
      return;
    }
    if (analysisCategory === 'retrofit') {
      analysisContent.append(
        node(
          'h3',
          '',
          referenceHull
            ? 'Stock fit → target → completion'
            : 'Installed → target → completion',
        ),
      );
      for (const [slot, target] of draft.targets) {
        const module = modules.find((m) => m.slot === slot);
        const choice = choicesFor(module).find(
          (c) => c.id === target.module_id,
        );
        const bp = blueprintsFor(module, choice).find(
          (b) => b.id === target.blueprint_id,
        );
        const exp = bp?.experimentals?.find(
          (e) => e.id === target.experimental_effect,
        );
        analysisContent.append(
          node(
            'p',
            'engineering-retrofit-row',
            `${slotLabel(module)}: ${module.name} → ${target.target_state === 'empty' ? 'Empty' : choice?.name || target.module_label}${bp ? ` · ${bp.label} G${target.target_grade}` : ''}${exp ? ` · ${exp.label || exp.name}` : ''}`,
          ),
        );
      }
      if (!draft.targets.size)
        analysisContent.append(node('p', '', 'No module changes planned.'));
      analysisContent.append(materialPanel);
      analysisContent.append(
        button('Reservations, traders & handoffs', () =>
          controller._setStage('materials'),
        ),
        button('Engineer access & unlocks', () =>
          controller._setStage('engineers'),
        ),
      );
      return;
    }
    if (analysisCategory === 'overview') {
      analysisContent.append(comparison);
      return;
    }
    if (analysisCategory === 'navigation') {
      const inputs = node('div', 'engineering-loading-controls');
      for (const [id, text] of [
        ['cargo_mass', 'Cargo carried · t'],
        ['fuel_mass', 'Main fuel · t'],
      ]) {
        const input = node('input');
        input.type = 'number';
        input.min = '0';
        input.step = 'any';
        input.name = id;
        input.max = performance?.loading_capacity?.[id] ?? '';
        input.disabled = !performance?.loading_capacity;
        input.placeholder = `Full · ${format(performance?.loading_capacity?.[id], 't', 1)}`;
        input.value = draft.conditions?.[id] ?? '';
        input.addEventListener('change', () => {
          draft.conditions = {
            ...draft.conditions,
            [id]: input.value === '' ? null : Number(input.value),
          };
          draft.conditionsDirty = true;
          preview();
        });
        inputs.append(label(text, input));
      }
      analysisContent.append(
        inputs,
        node(
          'p',
          'engineering-material-budget',
          'Blank = full capacity. Main tank only; 0 t reservoir. Jump projection retains the observed-range proof gate.',
        ),
      );
    }
    const ids =
      analysisCategory === 'navigation'
        ? [
            'configured_jump_range',
            'fully_laden_jump_range',
            'max_jump_range',
            'unladen_mass',
            'cargo_capacity',
          ]
        : analysisCategory === 'thermal'
          ? ['heat_efficiency']
          : analysisCategory === 'armour'
            ? ['integrity']
            : [];
    analysisContent.append(
      node('h3', '', categories.find(([id]) => id === analysisCategory)[1]),
    );
    if (ids.length) {
      const { table, body } = statTable(
        'engineering-analysis-table',
        referenceHull ? 'Stock' : 'Installed',
      );
      for (const m of performance?.metrics || [])
        if (ids.includes(m.id))
          addStatRow(
            body,
            m.id,
            m.label,
            m.installed?.value,
            m.planned?.value,
            m.planned?.unit,
          );
      if (body.children.length) analysisContent.append(table);
    }
    if (!['navigation', 'thermal'].includes(analysisCategory))
      analysisContent.prepend(
        node(
          'p',
          'engineering-unavailable-choice',
          'Whole-ship projection unavailable for this category. Verified module attributes remain available in the module editor.',
        ),
      );
  }
  function renderStatistics() {
    renderFlightStrip();
    modulePower?.render(
      performance?.power_management,
      draft.powerPlan,
      pending,
      error,
    );
    const selectedName = editor.querySelector('.engineering-selected-name');
    const selectedTarget = draft.targets.get(selected.slot);
    if (selectedName)
      selectedName.textContent =
        selectedTarget?.target_state === 'empty'
          ? 'Empty slot'
          : choicesFor(selected).find(
              (c) => c.id === (selectedTarget?.module_id || idOf(selected)),
            )?.name || selected.name;
    powerScenario.value = draft.powerPlan.scenario || 'normal';
    powerScenario.disabled = !performance?.power_management;
    suggestPower.disabled =
      pending || !!error || !!performance?.configuration_check?.errors?.length;
    resetPower.disabled = pending || !!error;
    const marked = keepPoweredCount(draft.powerPlan);
    keepScope.textContent = `Keep powered · ${scopeLabel(performance?.power_management, draft.powerPlan)} · ${marked} marked`;
    keepScope.title =
      'Modules marked Keep powered apply to this scenario and hardpoint state, matching Analysis → Power → Required here.';
    undo.disabled = !draft.history.length;
    comparison.replaceChildren(
      node(
        'h3',
        '',
        referenceHull
          ? 'Ship · stock baseline / planned'
          : 'Ship · installed / planned',
      ),
    );
    const { table, body } = statTable(
      'engineering-performance-table',
      referenceHull ? 'Stock' : 'Installed',
    );
    const metrics = performance?.metrics || [];
    const outputMetrics = metrics.some(
      (m) => m.id === 'operating_power_capacity',
    )
      ? shipMetrics
      : [['power_capacity', 'Available power'], ...shipMetrics.slice(1)];
    outputMetrics.forEach(([id, text]) => {
      const m = metrics.find((m) => m.id === id);
      if (m)
        addStatRow(
          body,
          id,
          text,
          m.installed?.value,
          m.planned?.value,
          m.planned?.unit || m.installed?.unit || '',
          'engineering-performance-row',
        );
    });
    comparison.append(table, label('Preserve cargo capacity', cargo));
    notices.replaceChildren();
    const check = performance?.configuration_check;
    const messages = error ? [error] : check?.errors || [];
    notices.dataset.state = pending
      ? 'pending'
      : messages.length
        ? 'invalid'
        : 'ready';
    if (pending) notices.append(node('span', '', 'Calculating…'));
    else if (messages.length)
      notices.append(node('span', 'engineering-fitting-warning', messages[0]));
    else if (fittingMessage)
      notices.append(
        node('span', 'engineering-fitting-warning', fittingMessage),
      );
    else if (hasDesign())
      notices.append(
        node(
          'span',
          '',
          check?.state === 'unknown'
            ? 'Some results unavailable'
            : 'Fits · power checked',
        ),
      );
    save.disabled =
      pending || !!error || !!check?.errors?.length || !hasDesign();
    status.textContent = draft.dirty
      ? 'Unsaved changes'
      : saved
        ? 'Saved variant'
        : referenceHull
          ? 'Catalogue stock · planned ship'
          : 'Installed observation';
    viewControls.append(notices);
    const detail = node('details', 'engineering-calculation-details');
    detail.append(node('summary', '', 'Calculation details'));
    detail.append(node('p', '', performance?.assumptions || ''));
    outputMetrics.forEach(([id, text]) => {
      const m = metrics.find((m) => m.id === id);
      if (m)
        detail.append(
          node(
            'p',
            '',
            `${text}: ${format(m.installed?.value, m.installed?.unit, 6)} → ${pending ? '…' : format(m.planned?.value, m.planned?.unit, 6)}`,
          ),
        );
    });
    [
      ...(check?.errors || []).slice(1),
      ...(check?.unknown || []),
      ...(check?.warnings || []),
    ].forEach((t) => detail.append(node('p', '', t)));
    metrics.forEach((m) => {
      if (m.planned?.unavailable_reason)
        detail.append(
          node('p', '', `${m.label}: ${m.planned.unavailable_reason}`),
        );
    });
    const validation = performance?.jump_model_validation;
    if (validation)
      detail.append(
        node(
          'p',
          '',
          `FSD check: ${validation.state}; observed ${format(validation.observed, 'ly', 6)}, calculated ${format(validation.calculated, 'ly', 6)}.`,
        ),
      );
    detail.append(
      node(
        'p',
        '',
        `Model: ${performance?.version || 'unavailable'}. Catalogue: ${progression.reference_catalog?.version || progression.catalog_version || 'unavailable'}.`,
      ),
    );
    (performance?.model_provenance?.sources || []).forEach((s) => {
      if (/^https:\/\//.test(s.url || '')) {
        const a = node('a', '', s.name);
        a.href = s.url;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        detail.append(a);
      }
    });
    comparison.append(detail);
    renderModuleStats();
    renderRequirements();
    const ranked = node('details', 'engineering-power-plant-variants');
    ranked.append(node('summary', '', 'Power-plant alternatives'));
    ranked.addEventListener('toggle', async () => {
      if (!ranked.open || ranked.dataset.loaded) return;
      ranked.dataset.loaded = 'true';
      const resultList = node(
        'div',
        'engineering-variant-results',
        'Calculating…',
      );
      ranked.append(resultList);
      try {
        const suffix = saved
          ? `?baseline_build_id=${encodeURIComponent(saved.build_plan_id)}`
          : controller._selectedObservationId
            ? `?baseline_observation_id=${controller._selectedObservationId}`
            : '';
        const result = await controller.fetchJson(
          `/engineering/workbench/power-plant-variants${suffix}`,
        );
        resultList.replaceChildren(
          node(
            'p',
            '',
            'Baseline ship · cargo preserved · range first, heat second. Other planned changes are excluded.',
          ),
        );
        [
          ...(result.variants || []),
          ...(result.explicit_candidates || []),
        ].forEach((v) => {
          const row = node('div', 'engineering-variant-row');
          row.append(
            node(
              'span',
              '',
              `${v.label} · ${format(v.metrics?.fully_laden_jump_range, 'ly', 4)} · ${v.power_sufficient ? format(v.metrics?.deployed_power_headroom, 'MW') : 'Insufficient power'}`,
            ),
            button('Compare', () => {
              draft.targets.set('PowerPlant', { ...v.target });
              chooseSlot('PowerPlant');
              preview();
              editor
                .querySelector('[name=experimental_effect]')
                ?.focus({ preventScroll: true });
            }),
          );
          resultList.append(row);
        });
        if (!(result.variants || []).length)
          resultList.append(
            node('p', '', result.reason || 'Verified ranking unavailable.'),
          );
      } catch (failure) {
        resultList.textContent = failure.message || 'Ranking unavailable.';
      }
    });
    comparison.append(ranked);
    powerPanel.render(performance?.power_management, pending, error);
    if (!analysis.hidden) {
      const activeName = analysisContent.contains(document.activeElement)
        ? document.activeElement.name
        : null;
      renderAnalysis();
      if (activeName)
        analysisContent
          .querySelector(`[name="${CSS.escape(activeName)}"]`)
          ?.focus({ preventScroll: true });
    }
  }
  async function preview() {
    fittingMessage = '';
    const nextSnapshot = snapshot();
    if (nextSnapshot !== draft.lastSnapshot) {
      draft.history.push(draft.lastSnapshot);
      if (draft.history.length > 40) draft.history.shift();
      draft.lastSnapshot = nextSnapshot;
    }
    const current = (draft.sequence = (draft.sequence || 0) + 1);
    draft.abort?.abort();
    draft.abort = new AbortController();
    error = '';
    draft.dirty = true;
    if (!hasDesign()) {
      pending = false;
      performance = workbench.comparison;
      requirements = null;
      draft.performance = performance;
      draft.requirements = null;
      acceptedSnapshot = snapshot();
      renderStatistics();
      renderNavigator();
      refreshReplacementAvailability();
      return;
    }
    pending = true;
    renderStatistics();
    renderNavigator();
    try {
      const result = await controller.fetchJson(
        '/engineering/workbench/preview',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: draft.abort.signal,
          body: JSON.stringify(previewBody()),
        },
      );
      if (current !== draft.sequence) return;
      if (!result?.performance) throw new Error('Calculation unavailable.');
      const oldViolations = performance?.configuration_check?.violations || [];
      const worsened = (
        result.performance.configuration_check?.violations || []
      ).some(
        (v) =>
          v.rule === 'quantity' &&
          v.excess >
            (oldViolations.find((o) => o.rule === v.rule && o.group === v.group)
              ?.excess || 0),
      );
      if (worsened) {
        fittingMessage =
          result.performance.configuration_check.errors.join(' ');
        const previous = JSON.parse(acceptedSnapshot);
        draft.targets = new Map(previous.targets);
        draft.powerPlan = previous.powerPlan;
        draft.powerDirty = previous.powerDirty;
        draft.conditions = previous.conditions || {};
        draft.conditionsDirty = previous.conditionsDirty;
        draft.cargoLock = previous.cargoLock;
        cargo.checked = draft.cargoLock;
        draft.lastSnapshot = acceptedSnapshot;
        if (draft.history.at(-1) === acceptedSnapshot) draft.history.pop();
        renderEditor();
      } else {
        performance = result.performance;
        requirements = result.requirements;
        draft.performance = performance;
        draft.requirements = requirements;
        acceptedSnapshot = snapshot();
      }
    } catch (failure) {
      if (current !== draft.sequence) return;
      error = failure.message || 'Calculation unavailable.';
    }
    pending = false;
    renderStatistics();
    renderNavigator();
    refreshReplacementAvailability();
  }
  function blockedReason(slot, id) {
    return (
      performance?.configuration_check?.blocked_replacements?.[slot]?.[id] || ''
    );
  }
  function refreshReplacementAvailability() {
    const chooser = editor.querySelector('[name=module_id]');
    if (chooser)
      for (const option of chooser.options) {
        option.dataset.fitLabel ||= option.textContent;
        option.disabled = !!blockedReason(selected.slot, option.value);
        option.title = blockedReason(selected.slot, option.value);
        option.textContent =
          option.dataset.fitLabel + (option.disabled ? ' · unavailable' : '');
      }
    editor.querySelectorAll('[data-catalogue-module]').forEach((b) => {
      b.disabled = !!blockedReason(selected.slot, b.dataset.catalogueModule);
      b.title = blockedReason(selected.slot, b.dataset.catalogueModule);
    });
  }
  function chooseSlot(slot) {
    selected = modules.find((m) => m.slot === slot) || selected;
    draft.selectedSlot = selected.slot;
    section.dataset.mobileView = 'module';
    mobileSlot.value = selected.slot;
    renderEditor();
    renderNavigator();
    renderModuleStats();
  }
  function renderNavigator() {
    const query = navigator.querySelector('input')?.value || '';
    const focusedSlot = navigator.contains(document.activeElement)
      ? document.activeElement.dataset?.slot
      : null;
    const focusedName = focusedSlot ? document.activeElement.name : null;
    navigator.replaceChildren();
    const search = node('input', 'engineering-slot-search');
    search.type = 'search';
    search.placeholder = 'Find slot or module';
    search.setAttribute('aria-label', 'Find slot or module');
    search.value = query;
    const list = node('div', 'engineering-slot-list');
    const fill = () => {
      const lanes = [0, 1, 2, 3].map(() =>
        node('div', 'engineering-equipment-lane'),
      );
      list.replaceChildren(...lanes);
      groups.forEach((g) => {
        const matching = g.modules.filter((m) =>
          `${slotLabel(m)} ${m.name}`
            .toLowerCase()
            .includes(search.value.toLowerCase()),
        );
        if (!matching.length) return;
        const group = node('section', 'engineering-equipment-group');
        group.dataset.equipmentGroup = g.id;
        const groupHeading = node('div', 'engineering-group-heading');
        groupHeading.append(
          node(
            'h3',
            'engineering-module-group-title',
            `${g.label} · ${g.modules.length}`,
          ),
        );
        if (!['core', 'armour'].includes(g.id)) {
          const actions = node('details', 'engineering-group-actions');
          const summary = node('summary', '', '⋯');
          summary.setAttribute('aria-label', `${g.label} actions`);
          actions.append(summary);
          actions.append(
            button('Clear removable', () => {
              for (const m of g.modules)
                if (m.reference_slot && !m.reference_slot.required)
                  draft.targets.set(m.slot, {
                    slot: m.slot,
                    module_id: null,
                    target_state: 'empty',
                  });
              renderEditor();
              preview();
            }),
          );
          actions.append(
            button('Fill empty from selected', () => {
              const source = currentTarget();
              if (!source) {
                status.textContent = 'Select a fitted module first.';
                return;
              }
              for (const m of g.modules)
                if (
                  (!idOf(m) ||
                    draft.targets.get(m.slot)?.target_state === 'empty') &&
                  choicesFor(m).some((c) => c.id === source.module_id) &&
                  !blockedReason(m.slot, source.module_id)
                )
                  draft.targets.set(m.slot, { ...source, slot: m.slot });
              renderEditor();
              preview();
            }),
          );
          groupHeading.append(actions);
        }
        group.append(groupHeading);
        matching.forEach((m) => {
          const target = draft.targets.get(m.slot);
          const choice = choicesFor(m).find(
            (c) => c.id === (target?.module_id || idOf(m)),
          );
          const equipmentRow = node('div', 'engineering-equipment-row');
          const row = button(
            '',
            () => chooseSlot(m.slot),
            'engineering-module-button',
          );
          equipmentRow.append(row);
          row.dataset.slot = m.slot;
          row.setAttribute('aria-pressed', String(m.slot === selected.slot));
          row.title = slotLabel(m);
          const size = choice?.class ?? m.size ?? m.reference_slot?.size;
          const rating = choice?.rating ?? m.rating ?? '';
          row.append(
            node('span', 'engineering-slot-label', `${size ?? '–'}${rating}`),
            node(
              'span',
              'engineering-module-button-name',
              target?.target_state === 'empty' || (!idOf(m) && !choice)
                ? 'Empty slot'
                : (!idOf(m) && !choice
                    ? 'Empty slot'
                    : choice?.name || m.name
                  ).replace(/^\d+[A-I]\s+/, ''),
            ),
          );
          const bp = (workbench.blueprint_definitions || []).find(
            (b) => b.id === target?.blueprint_id,
          );
          const installedBlueprint =
            (workbench.blueprint_definitions || []).find(
              (b) => b.id === m.installed_engineering?.blueprint_id,
            )?.name || m.installed_engineering?.blueprint_label;
          const text =
            target?.target_state === 'engineered'
              ? `${bp?.name || target.blueprint_label || 'Engineered'} G${target.target_grade}`
              : target?.target_state === 'stock'
                ? 'Stock'
                : m.installed_engineering?.blueprint_label
                  ? `${installedBlueprint} G${m.installed_engineering.grade}`
                  : '';
          if (text)
            row.append(node('small', 'engineering-module-button-state', text));
          const expId =
            target?.experimental_effect ||
            (!target ? m.installed_engineering?.experimental_effect : '');
          const exp = (workbench.blueprint_definitions || [])
            .flatMap((b) => b.experimentals || [])
            .find((e) => e.id === expId);
          if (expId) {
            const state = row.querySelector('.engineering-module-button-state');
            if (state) {
              state.textContent += ` · ${exp?.name || expId}`;
              state.title = state.textContent;
            } else
              row.append(
                node(
                  'small',
                  'engineering-module-experimental',
                  exp?.name || expId,
                ),
              );
          }
          const powerModule =
            performance?.power_management?.planned_modules?.find(
              (p) => p.slot === m.slot,
            );
          if (powerModule && !powerModule.empty && powerModule.draw_mw > 0) {
            const setting = draft.powerPlan.modules?.find(
              (p) => p.slot === m.slot,
            );
            const on = setting?.enabled ?? powerModule.enabled;
            const priority = setting?.priority ?? powerModule.priority;
            const context = `${draft.powerPlan.scenario || 'normal'}:${draft.powerPlan.deployment || 'deployed'}`;
            const operation = performance?.power_management?.cases
              .find((c) => c.id === context)
              ?.planned.modules.find((p) => p.slot === m.slot);
            const badge = node('span', 'engineering-row-power');
            const editable =
              !powerModule.power_lock && powerModule.controls_verified;
            const rank = editable
              ? select(
                  'outfitting_row_priority',
                  [1, 2, 3, 4, 5].map((p) => [p, `P${p}`]),
                  priority,
                )
              : node('span', '', on ? `P${priority ?? '?'}` : 'Off');
            if (editable) {
              rank.value = String(priority ?? '');
              rank.dataset.slot = m.slot;
              rank.setAttribute('aria-label', `${slotLabel(m)} planned priority`);
              rank.addEventListener('change', () => {
                // Capture the value before preview synchronously redraws the rows.
                changePowerSlot(m.slot, { priority: Number(rank.value) });
              });
            }
            const keepOn = isKeepPowered(draft.powerPlan, m.slot);
            equipmentRow.dataset.keepPowered = String(keepOn);
            badge.append(
              createKeepPoweredButton({
                slot: m.slot,
                name: powerModule.name || slotLabel(m),
                on: keepOn,
                scope: scopeLabel(performance.power_management, draft.powerPlan),
                switchedOff: on === false,
                toggle: toggleKeepPowered,
              }),
              rank,
              node(
                'small',
                '',
                pending || error
                  ? '…'
                  : on ? format(operation?.requested_mw, 'MW', 2) : 'Off',
              ),
            );
            const controlLabel = powerModule.power_lock
              ? `Fixed at P${powerModule.power_lock}`
              : editable
                ? 'Edit planned priority'
                : 'Verified power-control rules unavailable';
            badge.title = `${controlLabel} · ${on ? powerStateLabel(operation?.state) : 'Switched off'}. ${slotLabel(m)}.`;
            row.dataset.powerState =
              pending || error ? 'unknown' : operation?.state;
            equipmentRow.dataset.powerState = row.dataset.powerState;
            equipmentRow.append(badge);
          }
          if (powerModule?.enabled === false) row.classList.add('is-off');
          if (target) row.classList.add('has-planned-change');
          row.addEventListener('keydown', (event) => {
            if (
              event.key.toLowerCase() === 'p' &&
              !event.ctrlKey &&
              !event.metaKey &&
              powerModule?.draw_mw > 0
            ) {
              event.preventDefault();
              equipmentRow
                .querySelector('[name=outfitting_row_priority]')
                ?.focus({ preventScroll: true });
              return;
            }
            if (
              event.key.toLowerCase() === 'k' &&
              !event.ctrlKey &&
              !event.metaKey &&
              powerModule?.draw_mw > 0
            ) {
              event.preventDefault();
              toggleKeepPowered(
                m.slot,
                !isKeepPowered(draft.powerPlan, m.slot),
              );
              return;
            }
            if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key))
              return;
            event.preventDefault();
            const buttons = [
              ...list.querySelectorAll('.engineering-module-button'),
            ];
            const index = buttons.indexOf(row);
            const next =
              buttons[
                event.key === 'Home'
                  ? 0
                  : event.key === 'End'
                    ? buttons.length - 1
                    : Math.max(
                        0,
                        Math.min(
                          buttons.length - 1,
                          index + (event.key === 'ArrowDown' ? 1 : -1),
                        ),
                      )
              ];
            chooseSlot(next.dataset.slot);
            navigator
              .querySelector(`[data-slot="${CSS.escape(next.dataset.slot)}"]`)
              ?.focus({ preventScroll: true });
          });
          group.append(equipmentRow);
        });
        lanes[
          ['core', 'armour'].includes(g.id)
            ? 0
            : ['optional', 'military'].includes(g.id)
              ? 1
              : g.id === 'utility'
                ? 3
                : 2
        ].append(group);
      });
    };
    search.addEventListener('input', fill);
    navigator.append(search, list);
    fill();
    if (focusedSlot) {
      const control = ['outfitting_row_priority', 'outfitting_row_keep'].includes(
        focusedName,
      )
        ? `[name=${focusedName}]`
        : '.engineering-module-button';
      navigator
        .querySelector(`${control}[data-slot="${CSS.escape(focusedSlot)}"]`)
        ?.focus({ preventScroll: true });
    }
  }
  function currentTarget() {
    const target = draft.targets.get(selected.slot);
    if (target)
      return target.target_state === 'empty' ? null : targetRequest(target);
    if (!idOf(selected) || selected.reference_variant_note) return null;
    const installed = selected.installed_engineering || {};
    return {
      slot: selected.slot,
      module_id: idOf(selected),
      target_state: installed.blueprint_id ? 'engineered' : 'stock',
      ...(installed.blueprint_id
        ? {
            blueprint_id: installed.blueprint_id,
            target_grade: installed.grade,
            experimental_effect: installed.experimental_effect_id || null,
          }
        : {}),
    };
  }
  function renderEditor() {
    editor.replaceChildren();
    const installed = selected.installed_engineering || {};
    const target = draft.targets.get(selected.slot);
    const choices = choicesFor(selected);
    const selectedId = target?.module_id ?? idOf(selected);
    const kicker = node('div', 'engineering-editor-heading');
    kicker.append(
      node('h3', 'engineering-module-title', slotLabel(selected)),
      node(
        'span',
        'engineering-module-installed',
        installed.blueprint_label
          ? `Installed ${installed.blueprint_label} G${installed.grade}${installed.experimental_effect ? ` · ${installed.experimental_effect}` : ''}`
          : referenceHull
            ? 'Catalogue stock baseline'
            : 'Installed stock',
      ),
    );
    kicker.append(
      node(
        'strong',
        'engineering-selected-name',
        target?.target_state === 'empty'
          ? 'Empty slot'
          : choices.find((c) => c.id === (target?.module_id || idOf(selected)))
              ?.name || selected.name,
      ),
    );
    editor.append(kicker);
    const productivity = node('div', 'engineering-module-actions');
    productivity.append(
      button('Copy', () => {
        controller._moduleClipboard = currentTarget();
        status.textContent = controller._moduleClipboard
          ? 'Module copied · select a compatible slot'
          : 'No supported standard recipe to copy; observed nonstandard modifiers are preserved in this ship.';
      }),
    );
    const paste = button('Paste', () => {
      const source = controller._moduleClipboard;
      if (source && choices.some((c) => c.id === source.module_id)) {
        draft.targets.set(selected.slot, { ...source, slot: selected.slot });
        renderEditor();
        preview();
      }
    });
    paste.disabled =
      !controller._moduleClipboard ||
      !choices.some((c) => c.id === controller._moduleClipboard.module_id) ||
      !!blockedReason(selected.slot, controller._moduleClipboard?.module_id);
    paste.title = blockedReason(
      selected.slot,
      controller._moduleClipboard?.module_id,
    );
    productivity.append(
      paste,
      button('Reset slot', () => {
        draft.targets.delete(selected.slot);
        renderEditor();
        preview();
      }),
    );
    if (selected.reference_slot && !selected.reference_slot.required)
      productivity.append(
        button('Remove', () => {
          draft.targets.set(selected.slot, {
            slot: selected.slot,
            module_id: null,
            target_state: 'empty',
          });
          renderEditor();
          preview();
        }),
      );
    editor.append(productivity);
    modulePower = createModulePower({
      slot: selected.slot,
      change: changePowerSlot,
      keepPowered: toggleKeepPowered,
    });
    editor.append(modulePower.root);
    modulePower.render(
      performance?.power_management,
      draft.powerPlan,
      pending,
      error,
    );
    if (!choices.length) {
      editor.append(
        node('p', 'engineering-empty', 'No replacement data for this slot.'),
        moduleStats,
        materialPanel,
      );
      return;
    }
    const controls = node('div', 'engineering-context-controls');
    const modes = [
      ['keep', referenceHull ? 'Stock baseline' : 'Installed'],
      ['stock', 'Stock module'],
      ['engineered', 'Engineered module'],
    ];
    if (selected.reference_slot && !selected.reference_slot.required)
      modes.push(['empty', 'Empty slot']);
    const mode = select('target_state', modes, target?.target_state || 'keep');
    const moduleSelect = select(
      'module_id',
      [
        ...(!idOf(selected) ? [['', 'Empty slot']] : []),
        ...choices.map((c) => [c.id, moduleName(c)]),
      ],
      selectedId,
    );
    const filter = node('input', 'engineering-replacement-search');
    filter.type = 'search';
    filter.placeholder = 'Filter compatible modules';
    filter.setAttribute('aria-label', 'Filter compatible modules');
    filter.addEventListener('input', () => {
      const value = moduleSelect.value;
      moduleSelect.replaceChildren(
        ...choices
          .filter(
            (c) =>
              c.id === value ||
              c.name.toLowerCase().includes(filter.value.toLowerCase()),
          )
          .map((c) => {
            const op = node('option', '', c.name);
            op.value = c.id;
            op.selected = c.id === value;
            return op;
          }),
      );
      refreshReplacementAvailability();
    });
    const results = node('div', 'engineering-catalogue-results');
    const blueprint = select('blueprint_id', []),
      grade = select('target_grade', []),
      experimental = select('experimental_effect', []);
    let wanted = {
      bp: target?.blueprint_id || installed.blueprint_id || '',
      grade: target?.target_grade ?? installed.grade,
      exp:
        target?.experimental_effect ??
        installed.experimental_effect_id ??
        installed.experimental_effect ??
        '',
    };
    const drawChoices = () => {
      results.replaceChildren();
      const matching = choices.filter((c) =>
        `${c.name} ${c.class || ''}${c.rating || ''}`
          .toLowerCase()
          .includes(filter.value.toLowerCase()),
      );
      for (const c of matching.slice(0, 60)) {
        const row = button('', () => {
          const reason = blockedReason(selected.slot, c.id);
          if (reason) {
            fittingMessage = reason;
            renderStatistics();
            return;
          }
          moduleSelect.value = c.id;
          moduleSelect.dispatchEvent(new Event('change'));
          drawChoices();
        });
        row.classList.add('engineering-catalogue-choice');
        row.dataset.catalogueModule = c.id;
        row.disabled = !!blockedReason(selected.slot, c.id);
        row.title = blockedReason(selected.slot, c.id);
        row.setAttribute('aria-pressed', String(moduleSelect.value === c.id));
        row.append(
          node('span', '', c.name),
          node(
            'small',
            '',
            [
              c.stats?.mass != null ? `${format(c.stats.mass, 't', 1)}` : '',
              c.stats?.power_capacity != null
                ? format(c.stats.power_capacity, 'MW', 2)
                : '',
            ]
              .filter(Boolean)
              .join(' · '),
          ),
        );
        if (row.disabled)
          row.append(
            node(
              'small',
              'engineering-catalogue-blocked-reason',
              row.title.split('. ')[0],
            ),
          );
        results.append(row);
      }
      if (!matching.length)
        results.append(node('p', '', 'No compatible matches.'));
      if (matching.length > 60)
        results.append(
          node(
            'p',
            '',
            `${matching.length} matches · refine search or use the module selector.`,
          ),
        );
    };
    filter.addEventListener('input', drawChoices);
    // Hand off to the blueprint's inspector. Outfitting is only hidden, so this
    // draft, build and slot are exactly as left when the Commander comes back.
    const handoff = node('div', 'engineering-blueprint-handoff');
    const handoffNote = node('p', 'engineering-blueprint-handoff-note');
    handoffNote.setAttribute('role', 'status');
    const viewBlueprint = button('View blueprint', () => {
      const opened = controller.openBlueprint(blueprint.value, {
        grade: Number(grade.value) || null,
        returnTo: {
          slot: selected.slot,
          slotLabel: slotLabel(selected),
          buildTitle: saved?.title || draft.title,
        },
      });
      handoffNote.textContent = opened
        ? ''
        : `${blueprint.selectedOptions[0]?.textContent || 'This blueprint'} is not in Blueprints & Engineers: neither the ship data nor your Journal records it.`;
    });
    viewBlueprint.name = 'view_blueprint';
    handoff.append(viewBlueprint, handoffNote);
    const syncOptions = () => {
      const choice = choices.find((c) => c.id === moduleSelect.value);
      const bps = blueprintsFor(selected, choice);
      const bp = bps.find(
        (b) =>
          b.id === wanted.bp ||
          (b.label === installed.blueprint_label && !wanted.bp),
      );
      blueprint.replaceChildren(
        ...select(
          '',
          [['', 'None · stock'], ...bps.map((b) => [b.id, b.label || b.name])],
          bp?.id || '',
        ).children,
      );
      blueprint.value = bp?.id || '';
      const grades = bp?.grades || [];
      const g = grades.includes(Number(wanted.grade))
        ? Number(wanted.grade)
        : grades.at(-1);
      grade.replaceChildren(
        ...select(
          '',
          grades.map((n) => [String(n), `G${n}`]),
          String(g || ''),
        ).children,
      );
      grade.disabled = !bp;
      grade.value = String(g || '');
      const exps = bp?.experimentals || [];
      const exp = exps.find(
        (e) => e.id === wanted.exp || (e.label || e.name) === wanted.exp,
      );
      experimental.replaceChildren(
        ...select(
          '',
          [['', 'None'], ...exps.map((e) => [e.id, e.label || e.name])],
          exp?.id || '',
        ).children,
      );
      experimental.disabled = !bp;
      experimental.value = exp?.id || '';
      blueprint.disabled = !bps.length;
      mode.querySelector('[value=engineered]').disabled = !bps.length;
      viewBlueprint.disabled = !blueprint.value;
      handoffNote.textContent = '';
      wanted = { bp: bp?.id || '', grade: g, exp: exp?.id || '' };
    };
    const update = (engineeringChange = false) => {
      if (engineeringChange)
        mode.value = blueprint.value ? 'engineered' : 'stock';
      if (!moduleSelect.value) mode.value = idOf(selected) ? 'empty' : 'keep';
      if (mode.value === 'keep') draft.targets.delete(selected.slot);
      else if (mode.value === 'empty')
        draft.targets.set(selected.slot, {
          slot: selected.slot,
          module_id: null,
          target_state: 'empty',
        });
      else
        draft.targets.set(selected.slot, {
          slot: selected.slot,
          module_id: moduleSelect.value,
          target_state: mode.value,
          ...(mode.value === 'engineered'
            ? {
                blueprint_id: blueprint.value || null,
                target_grade: grade.value ? Number(grade.value) : null,
                experimental_effect: experimental.value || null,
              }
            : {}),
        });
      controls.dataset.mode = mode.value;
      preview();
    };
    moduleSelect.addEventListener('change', () => {
      const reason = blockedReason(selected.slot, moduleSelect.value);
      if (reason) {
        fittingMessage = reason;
        renderEditor();
        renderStatistics();
        return;
      }
      syncOptions();
      mode.value = blueprint.value ? 'engineered' : 'stock';
      update();
    });
    blueprint.addEventListener('change', () => {
      wanted.bp = blueprint.value;
      wanted.grade = Number(grade.value) || wanted.grade;
      wanted.exp = experimental.value;
      syncOptions();
      update(true);
    });
    grade.addEventListener('change', () => {
      wanted.grade = Number(grade.value);
      update(true);
    });
    experimental.addEventListener('change', () => {
      wanted.exp = experimental.value;
      update(true);
    });
    mode.addEventListener('change', () => {
      if (mode.value === 'keep') {
        const old = draft.targets.get(selected.slot);
        draft.targets.delete(selected.slot);
        renderEditor();
        if (old) preview();
        return;
      }
      if (mode.value === 'engineered' && !blueprint.value) {
        const bp = blueprintsFor(
          selected,
          choices.find((c) => c.id === moduleSelect.value),
        )[0];
        wanted.bp = bp?.id || '';
        syncOptions();
      }
      update();
    });
    syncOptions();
    controls.dataset.mode = mode.value;
    controls.append(
      label('Plan', mode),
      label('Module', moduleSelect),
      filter,
      label('Blueprint', blueprint),
      label('Grade', grade),
      handoff,
      label('Experimental', experimental),
    );
    const gaps =
      choices.find((c) => c.id === moduleSelect.value)?.engineering_gaps || [];
    if (gaps.length) {
      const detail = node('details', 'engineering-source-why');
      detail.append(node('summary', '', 'Unavailable recipes'));
      gaps.forEach((t) => detail.append(node('p', '', t)));
      controls.append(detail);
    }
    const catalogue = node('details', 'engineering-compatible-catalogue');
    catalogue.append(
      node('summary', '', `Browse ${choices.length} compatible modules`),
      filter,
      results,
    );
    catalogue.open = draft.layout === 'catalogue';
    drawChoices();
    const presets = node('details', 'engineering-module-presets');
    presets.append(node('summary', '', 'Reuse from saved builds'));
    let presetsFound = 0;
    for (const variant of variants)
      for (const source of variant.workbench.planned_configuration?.targets ||
        []) {
        if (
          source.target_state === 'empty' ||
          !choices.some((c) => c.id === source.module_id)
        )
          continue;
        presetsFound++;
        const module = choices.find((c) => c.id === source.module_id);
        presets.append(
          button(`${variant.title} · ${module.name}`, () => {
            draft.targets.set(selected.slot, {
              ...targetRequest(source),
              slot: selected.slot,
            });
            renderEditor();
            preview();
          }),
        );
      }
    if (!presetsFound)
      presets.append(
        node(
          'p',
          '',
          'Save an engineered variant to reuse its compatible modules here.',
        ),
      );
    editor.append(controls, catalogue, presets, moduleStats);
    const restrictions = node('details', 'engineering-fitting-restrictions');
    restrictions.append(node('summary', '', 'Ship-wide fitting limits'));
    const reasons = [
      ...new Set(
        Object.values(
          performance?.configuration_check?.blocked_replacements?.[
            selected.slot
          ] || {},
        ),
      ),
    ];
    reasons.forEach((reason) => restrictions.append(node('p', '', reason)));
    if (reasons.length) editor.append(restrictions);
    refreshReplacementAvailability();
    if (materialPanel.parentElement !== analysisContent)
      editor.append(materialPanel);
    renderModuleStats();
  }
  const preset = select('core_preset', [
    ['', 'Core preset…'],
    ['A', 'A-rated'],
    ['D', 'D-rated'],
  ]);
  preset.setAttribute('aria-label', 'Core preset');
  preset.addEventListener('change', () => {
    if (!preset.value) return;
    for (const m of groups.find((g) => g.id === 'core')?.modules || []) {
      const size = m.reference_slot?.size || m.size;
      const choice = choicesFor(m).find(
        (c) =>
          c.class === size &&
          c.rating === preset.value &&
          !/guardian|enhanced/i.test(c.name),
      );
      if (choice)
        draft.targets.set(m.slot, {
          slot: m.slot,
          module_id: choice.id,
          target_state: 'stock',
        });
    }
    preset.value = '';
    renderEditor();
    preview();
  });
  const layout = select(
    'workspace_layout',
    [
      ['ship', 'Whole ship'],
      ['catalogue', 'Catalogue & fitting'],
    ],
    draft.layout || 'ship',
  );
  layout.setAttribute('aria-label', 'Workspace layout');
  section.dataset.layout = draft.layout || 'ship';
  layout.addEventListener('change', () => {
    draft.layout = layout.value;
    section.dataset.layout = layout.value;
    renderEditor();
  });
  viewControls.append(preset, layout);
  const footer = node('div', 'engineering-workbench-footer');
  const materialSummary = button(
    'Materials',
    () => {
      openAnalysis('retrofit');
      materialPanel.scrollIntoView({ block: 'nearest' });
      materialPanel.tabIndex = -1;
      materialPanel.focus({ preventScroll: true });
    },
    'engineering-material-summary',
  );
  const priority = select(
    'priority',
    [
      ['normal', 'Normal'],
      ['high', 'High'],
      ['low', 'Low'],
      ['unsorted', 'Unsorted'],
    ],
    draft.priority,
  );
  priority.addEventListener('change', () => {
    draft.priority = priority.value;
    if (hasDesign()) preview();
  });
  const destination = node('input');
  destination.name = 'acquisition_destination';
  destination.placeholder = 'Acquisition destination';
  footer.append(
    status,
    materialSummary,
    button(referenceHull ? 'Reset to stock' : 'Reset to installed', () => {
      draft.targets.clear();
      draft.conditions = {};
      draft.conditionsDirty = false;
      draft.powerPlan = structuredClone(
        workbench.comparison?.power_management?.plan || {
          modules: [],
          scenario: 'normal',
          deployment: 'deployed',
          custom_percent: 100,
          protect: ['normal:deployed'],
        },
      );
      draft.powerDirty = false;
      renderEditor();
      preview();
    }),
    label('Priority', priority),
  );

  const planning = node('details', 'engineering-source-why');
  planning.append(
    node('summary', '', 'Acquisition'),
    label('Destination', destination),
  );
  footer.append(planning);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (save.disabled || !hasDesign()) return;
    save.disabled = true;
    status.textContent = 'Saving…';
    try {
      const result = await controller.fetchJson(
        '/engineering/workbench/builds',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: title.value.trim(),
            priority: priority.value,
            acquisition_destination: destination.value.trim() || null,
            module_targets: [...draft.targets.values()].map(targetRequest),
            ...(Object.keys(draft.conditions || {}).length
              ? { operating_conditions: draft.conditions }
              : {}),
            power_plan: draft.powerPlan,
            ...(!saved && referenceHull ? { hull_id: referenceHull } : {}),
            baseline_build_id: saved?.build_plan_id || null,
            baseline_observation_id:
              saved || referenceHull
                ? null
                : controller._selectedObservationId || null,
            preserve_cargo_capacity: cargo.checked,
          }),
        },
      );
      controller._selectedBuildId = result.build.build_plan_id;
      controller._outfittingDrafts.delete(key);
      await controller.fetchAndRender();
      controller.root
        .querySelector('[name=saved_variant]')
        ?.focus({ preventScroll: true });
    } catch (failure) {
      error = failure.message || 'Could not save variant.';
      renderStatistics();
    }
  });
  workspace.append(navigator, editor);
  analysisContent.append(comparison);
  form.append(workspace, powerPanel.root, analysis, footer);
  section.append(form);
  renderNavigator();
  renderEditor();
  renderStatistics();
  setPowerView(draft.powerView);
  if (draft.dirty && hasDesign()) preview();
  return section;
}
