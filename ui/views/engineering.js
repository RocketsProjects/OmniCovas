/**
 * Phase 8 Engineering route.
 *
 * Local-only planning workspace. ADR 0003: all dynamic data is rendered with
 * DOM nodes and textContent; source-gated imports only record blocked attempts.
 */
(function () {
  'use strict';

  const SELECTORS = Object.freeze({
    root: 'engineering-root',
  });

  const GOAL_KIND_OPTIONS = Object.freeze([
    ['module_engineering', 'Module engineering'],
    ['ship_unlock', 'Ship unlock'],
    ['engineer_unlock', 'Engineer unlock'],
    ['guardian_tech', 'Guardian tech'],
    ['tech_broker_unlock', 'Tech broker unlock'],
    ['suit_engineering', 'Suit engineering'],
    ['general_progression', 'General progression'],
    ['commander_defined_other', 'Commander defined'],
  ]);

  const PRIORITY_OPTIONS = Object.freeze([
    ['normal', 'Normal'],
    ['high', 'High'],
    ['low', 'Low'],
    ['unsorted', 'Unsorted'],
  ]);

  const READINESS_OPTIONS = Object.freeze([
    ['blueprint_progress', 'Blueprint'],
    ['engineer_unlock_state', 'Engineer'],
    ['guardian_tech_progress', 'Guardian tech'],
    ['suit_engineering_state', 'Suit engineering'],
  ]);

  function safeText(value, fallback = 'Unknown') {
    if (value === null || value === undefined || value === '') return fallback;
    return String(value);
  }

  function el(tagName, className = '', text = null) {
    const node = document.createElement(tagName);
    if (className) node.className = className;
    if (text !== null && text !== undefined) node.textContent = String(text);
    return node;
  }

  function field(label, value) {
    const row = el('div', 'engineering-field');
    row.append(el('span', 'engineering-field-label', label));
    row.append(el('span', 'engineering-field-value', value));
    return row;
  }

  function badge(text, variant = '') {
    const node = el('span', variant ? `engineering-badge ${variant}` : 'engineering-badge');
    node.textContent = safeText(text, 'Not Loaded');
    return node;
  }

  function option(value, label, selected = false) {
    const node = document.createElement('option');
    node.value = value;
    node.textContent = label;
    node.selected = selected;
    return node;
  }

  function labeledInput(labelText, input) {
    const label = el('label', 'engineering-form-field');
    label.append(el('span', 'engineering-form-label', labelText), input);
    return label;
  }

  function textInput(name, placeholder = '', options = {}) {
    const input = document.createElement('input');
    input.name = name;
    input.type = options.type || 'text';
    input.placeholder = placeholder;
    if (options.required) input.required = true;
    if (options.min !== undefined) input.min = String(options.min);
    if (options.maxLength !== undefined) input.maxLength = options.maxLength;
    return input;
  }

  function textArea(name, placeholder = '') {
    const area = document.createElement('textarea');
    area.name = name;
    area.rows = 3;
    area.placeholder = placeholder;
    return area;
  }

  function selectInput(name, options, initial = '') {
    const select = document.createElement('select');
    select.name = name;
    options.forEach(([value, label]) => select.append(option(value, label, value === initial)));
    return select;
  }

  function formValue(form, name) {
    const value = new FormData(form).get(name);
    return typeof value === 'string' ? value.trim() : '';
  }

  function optionalNumber(form, name) {
    const raw = formValue(form, name);
    if (!raw) return null;
    const value = Number(raw);
    return Number.isFinite(value) ? value : null;
  }

  function appendIfPresent(target, key, value) {
    if (value !== null && value !== undefined && value !== '') {
      target[key] = value;
    }
  }

  function emptyState(message) {
    return el('p', 'engineering-empty', message);
  }

  class EngineeringController {
    constructor(rootOverride = null) {
      this.root = rootOverride || document.getElementById(SELECTORS.root);
      this.overview = null;
      this.statusNode = null;
      this._activeStage = 'goals';
      this.init();
    }

    get apiBase() {
      if (window.Shell?.httpBase) return window.Shell.httpBase;
      return null;
    }

    apiUrl(path) {
      const base = this.apiBase;
      return base ? `${base}${path}` : null;
    }

    init() {
      if (!this.root) return;
      this.renderWaiting();
      if (this.apiBase) {
        this.fetchAndRender();
        return;
      }
      window.OmniEvents?.addEventListener('bridge-connected', () => this.fetchAndRender(), {
        once: true,
      });
    }

    async fetchJson(path, options = {}) {
      const url = this.apiUrl(path);
      if (!url) return null;
      const response = await window.fetch(url, options);
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        const message = body?.detail || `Request failed: ${response.status}`;
        throw new Error(String(message));
      }
      return body;
    }

    async fetchAndRender() {
      if (!this.root) return;
      try {
        const overview = await this.fetchJson('/engineering/overview');
        if (!overview) {
          this.renderWaiting();
          return;
        }
        this.overview = overview;
        this.render(overview);
      } catch (error) {
        this.renderUnavailable(error);
      }
    }

    async postJson(path, payload = {}) {
      const body = await this.fetchJson(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      await this.fetchAndRender();
      return body;
    }

    renderWaiting() {
      if (!this.root) return;
      const shell = el('section', 'engineering-shell');
      shell.append(
        this.createHeader({
          status: 'Bridge not ready',
          counts: {},
          dashboard_pin: { inventory: 'No Verified Source' },
        }),
        emptyState('Waiting for OmniCOVAS bridge.'),
      );
      this.root.replaceChildren(shell);
    }

    renderUnavailable(error) {
      if (!this.root) return;
      const shell = el('section', 'engineering-shell');
      shell.append(
        this.createHeader({
          status: 'Not Loaded',
          counts: {},
          dashboard_pin: { inventory: 'No Verified Source' },
        }),
        emptyState(error?.message || 'Engineering local store unavailable.'),
      );
      this.root.replaceChildren(shell);
    }

    render(overview) {
      const shell = el('section', 'engineering-shell');

      /* PB-UIV3-HARMONY §4·5 guided-helper rebuild. The route no longer stacks
         every planning form at one depth (the Commander-rejected "wall of
         boxes"). It now reads as a guided helper:
           1. a Current Engineering Focus lead card with one next action;
           2. a compact three-step planning band;
           3. a stage selector (Goals · Plans · Materials) that SWITCHES the
              visible workspace — only one stage's working surfaces show at a
              time, like the Operations mode workspace;
           4. readiness / source gates / proof folded into a collapsed
              secondary detail below.
         Every form/section the route owns is preserved; they are reorganized,
         not removed. */
      shell.append(
        this.createHeader(overview),
        this.createFocusCard(overview),
        this.createPlanningGuide(),
        this.createStageNav(),
      );

      const workspace = el('div', 'engineering-stage-workspace');
      workspace.append(
        this.createStagePanel('goals', [this.createGoalsSection(overview)]),
        this.createStagePanel('plans', [this.createBuildsSection(overview)]),
        this.createStagePanel('materials', [
          this.createMaterialGapsSection(overview),
          this.createAcquisitionSection(overview),
        ]),
      );
      shell.appendChild(workspace);

      shell.appendChild(this.createSecondaryDetail(overview));

      this.root.replaceChildren(shell);
      this._setStage(this._activeStage || 'goals');
      this.applyRouteTransferArrival();
    }

    /* One stage workspace panel. All panels live in the DOM; only the active
       one is visible (the others carry the hidden attribute) so the stage
       selector swaps the visible workspace rather than scrolling a long page. */
    createStagePanel(stageId, sections) {
      const panel = el('div', 'engineering-stage-panel');
      panel.id = `engineering-stage-${stageId}`;
      panel.setAttribute('data-stage-panel', stageId);
      panel.setAttribute('role', 'tabpanel');
      sections.forEach((section) => panel.appendChild(section));
      return panel;
    }

    /* Collapsed secondary: readiness, source gates, and proof are real but
       subordinate — folded below the working surface, not competing with it. */
    createSecondaryDetail(overview) {
      const details = el('details', 'engineering-secondary');
      const summary = el('summary', 'engineering-secondary-summary', 'Readiness, source gates & proof');
      details.appendChild(summary);
      const body = el('div', 'engineering-secondary-body');
      body.append(
        this.createReadinessSection(overview),
        this.createSourceGatesSection(overview),
        this.createProofSection(),
      );
      details.appendChild(body);
      return details;
    }

    /* PB-UIV3-HARMONY §4·5 — Current Engineering Focus / readiness lead card.
       Goal-oriented, material-gap-oriented, task-oriented: it names the active
       focus, summarizes local planning counts, and gives ONE state-backed next
       action (the single command-orange element on the route). All values are
       local counts — no invented inventory or readiness percentage. */
    createFocusCard(overview) {
      const counts = overview.counts || {};
      const goals = Array.isArray(overview.goals) ? overview.goals : [];
      const buildPlans = Array.isArray(overview.build_plans) ? overview.build_plans : [];
      const gaps = Array.isArray(overview.material_gaps) ? overview.material_gaps : [];
      const acquisitions = Array.isArray(overview.acquisition_plans) ? overview.acquisition_plans : [];

      const activeGoals = counts.active_goals ?? goals.filter((g) => g.state === 'active').length;
      const buildCount = counts.build_plans ?? buildPlans.length;
      const gapCount = counts.material_gap_rows ?? counts.material_gaps ?? gaps.length;
      const acqCount = counts.acquisition_plans ?? counts.pending_acquisition_plans ?? acquisitions.length;
      const leadGoal = goals.find((g) => g.state === 'active') || goals[0] || null;

      const card = el('section', 'engineering-focus-card');
      card.setAttribute('aria-label', 'Current engineering focus');
      card.append(
        el('p', 'engineering-focus-eyebrow', 'Current Engineering Focus'),
        el('h2', 'engineering-focus-title', leadGoal ? safeText(leadGoal.title, 'Active goal') : 'No active engineering goal'),
      );

      const sub = el('p', 'engineering-focus-sub');
      sub.textContent = leadGoal
        ? `${safeText(leadGoal.target_kind, 'Commander defined')} · ${safeText(leadGoal.priority, 'normal')} priority`
        : 'Define a goal to start tracking readiness and material gaps.';
      card.appendChild(sub);

      /* Local planning metric strip. */
      const metrics = el('div', 'engineering-focus-metrics');
      metrics.append(
        this.createSummaryMetric('Active goals', activeGoals),
        this.createSummaryMetric('Build plans', buildCount),
        this.createSummaryMetric('Material gaps', gapCount),
        this.createSummaryMetric('Acquisitions', acqCount),
      );
      card.appendChild(metrics);

      /* One state-backed next action. */
      let action;
      if (activeGoals === 0) {
        action = { label: 'Define an engineering goal', stage: 'goals',
          hint: 'Name the module, unlock, or progression outcome you want to reach.' };
      } else if (buildCount === 0) {
        action = { label: 'Record a build plan', stage: 'plans',
          hint: `Capture the target recipe for ${leadGoal ? safeText(leadGoal.title, 'this goal') : 'this goal'}.` };
      } else if (gapCount === 0) {
        action = { label: 'Track a material gap', stage: 'materials',
          hint: 'Add the materials this build needs to measure readiness.' };
      } else {
        action = { label: `Work ${gapCount} material gap${gapCount === 1 ? '' : 's'}`, stage: 'materials',
          hint: 'Drive the gap board and acquisition plans toward readiness.' };
      }

      const banner = el('div', 'engineering-next-action');
      banner.append(el('p', 'engineering-next-action-kicker', 'Next action'));
      const btn = el('button', 'engineering-next-action-btn', action.label);
      btn.type = 'button';
      btn.addEventListener('click', () => this._setStage(action.stage));
      banner.appendChild(btn);
      banner.appendChild(el('p', 'engineering-next-action-hint', action.hint));
      card.appendChild(banner);

      card.appendChild(el('p', 'engineering-focus-note',
        'Local planning only. Material inventory is not verified — enter counts manually to measure readiness.'));
      return card;
    }

    createPlanningGuide() {
      const guide = el('section', 'engineering-guide');
      guide.setAttribute('aria-labelledby', 'engineering-guide-title');
      guide.append(
        el('p', 'engineering-kicker', 'Local planning workflow'),
        el('h2', 'engineering-guide-title', 'Plan an Engineering goal in three steps'),
        el('p', 'engineering-guide-copy', 'This workspace records Commander-entered plans and local progress only. Imports stay disabled until an approved source workflow exists.'),
      );
      guide.querySelector('.engineering-guide-title').id = 'engineering-guide-title';

      const steps = el('ol', 'engineering-guide-steps');
      [
        ['1', 'Define a goal', 'Name the module, unlock, or progression outcome you want to track.'],
        ['2', 'Record a build plan', 'Capture the intended recipe or build notes from your verified source.'],
        ['3', 'Track gaps and acquisitions', 'Use local material gaps and acquisition notes as your working checklist.'],
      ].forEach(([number, title, copy]) => {
        const item = el('li', 'engineering-guide-step');
        item.append(
          el('span', 'engineering-guide-number', number),
          el('strong', 'engineering-guide-step-title', title),
          el('span', 'engineering-guide-step-copy', copy),
        );
        steps.appendChild(item);
      });
      guide.appendChild(steps);
      return guide;
    }

    /* PB-UIV3-HARMONY §4·5: guided-planning stage control. The planning surface
       reads as staged work (Goals -> Plans -> Materials), not a flat form stack.
       Cyan/neutral navigation grammar (§5), consistent with the other route
       tab strips; command-orange stays on actions. */
    createStageNav() {
      const nav = el('nav', 'engineering-stage-nav');
      nav.setAttribute('role', 'tablist');
      nav.setAttribute('aria-label', 'Engineering planning stages');
      const STAGES = [
        { id: 'goals', label: 'Goals' },
        { id: 'plans', label: 'Plans' },
        { id: 'materials', label: 'Materials' },
      ];
      const active = this._activeStage || 'goals';
      STAGES.forEach((stage) => {
        const tab = el('button', 'engineering-stage-tab', stage.label);
        tab.setAttribute('type', 'button');
        tab.setAttribute('role', 'tab');
        tab.setAttribute('data-stage', stage.id);
        if (stage.id === active) tab.setAttribute('aria-current', 'true');
        tab.addEventListener('click', () => this._setStage(stage.id));
        nav.appendChild(tab);
      });
      return nav;
    }

    /* Switch the visible workspace: show the selected stage panel, hide the
       others, and move the active indicator. This is a real workspace swap
       (not an anchor scroll), so domain selection changes what the route
       shows — the Commander-required behavior. */
    _setStage(stageId) {
      this._activeStage = stageId;
      if (!this.root) return;
      const panels = this.root.querySelectorAll('.engineering-stage-panel');
      panels.forEach((panel) => {
        const match = panel.getAttribute('data-stage-panel') === stageId;
        panel.hidden = !match;
        panel.classList.toggle('is-active', match);
      });
      const tabs = this.root.querySelectorAll('.engineering-stage-tab');
      tabs.forEach((tab) => {
        if (tab.getAttribute('data-stage') === stageId) tab.setAttribute('aria-current', 'true');
        else tab.removeAttribute('aria-current');
      });
    }

    createHeader(overview) {
      const header = el('header', 'engineering-header');
      const copy = el('div', 'engineering-header-copy');
      const kicker = el('p', 'engineering-kicker', 'Operations / Engineering');
      const title = el('h1', 'engineering-title', 'Engineering');
      title.id = 'engineering-title';
      const status = el('p', 'engineering-subtitle');
      status.textContent = safeText(overview.status, 'Local-only');
      copy.append(kicker, title, status);

      /* Local-posture badges. The planning-count metrics now lead inside the
         Current Engineering Focus card (§4·5), so the header stays a compact
         identity band rather than a second metric wall. */
      const source = el('div', 'engineering-header-source');
      source.append(
        badge('Local only', 'ok'),
        badge(overview.dashboard_pin?.inventory || 'No Verified Source', 'warn'),
        badge('Imports disabled', 'off'),
      );

      header.append(copy, source);
      return header;
    }

    createSummaryMetric(label, value) {
      const metric = el('div', 'engineering-metric');
      metric.append(el('span', 'engineering-metric-label', label));
      const display = safeText(value, '0');
      const valueNode = el('strong', 'engineering-metric-value', display);
      /* A zero/empty count should read as honest "none" — dim it so populated
         counts stand out and the empty planning state does not look broken
         (PB-UIV3-HARMONY Engineering guided-planning direction). */
      if (!display || display === '0' || Number(value) === 0) {
        valueNode.classList.add('is-zero');
      }
      metric.append(valueNode);
      return metric;
    }

    createSection(id, title, statusText = '') {
      const section = el('section', 'engineering-section');
      section.id = id;
      const header = el('div', 'engineering-section-header');
      header.append(el('h2', 'engineering-section-title', title));
      if (statusText) header.append(badge(statusText, 'muted'));
      section.appendChild(header);
      return section;
    }

    createGoalsSection(overview) {
      const section = this.createSection('engineering-goals', 'Goals', 'Manual');
      section.appendChild(this.createGoalForm());
      const list = el('div', 'engineering-list');
      const goals = Array.isArray(overview.goals) ? overview.goals : [];
      if (goals.length === 0) {
        list.appendChild(emptyState('Define an engineering goal — name the module, unlock, or progression outcome you want to track.'));
      } else {
        goals.forEach((goal) => list.appendChild(this.createGoalCard(goal)));
      }
      section.appendChild(list);
      return section;
    }

    createGoalForm() {
      const form = el('form', 'engineering-form engineering-form--goal');
      form.append(
        labeledInput('Goal', textInput('title', 'Goal title', { required: true })),
        labeledInput('Target', selectInput('target_kind', GOAL_KIND_OPTIONS, 'module_engineering')),
        labeledInput('Priority', selectInput('priority', PRIORITY_OPTIONS, 'normal')),
        labeledInput('Notes', textArea('notes', 'Commander note')),
      );
      const actions = el('div', 'engineering-form-actions');
      const submit = el('button', 'ocv-btn engineering-action', 'Add goal');
      submit.type = 'submit';
      actions.appendChild(submit);
      form.appendChild(actions);
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const payload = {
          title: formValue(form, 'title'),
          target_kind: formValue(form, 'target_kind') || 'commander_defined_other',
          priority: formValue(form, 'priority') || 'normal',
          state: 'active',
        };
        appendIfPresent(payload, 'notes', formValue(form, 'notes'));
        await this.handleAction(() => this.postJson('/engineering/goal', payload));
      });
      return form;
    }

    createGoalCard(goal) {
      const card = el('article', 'engineering-card');
      card.append(
        el('h3', 'engineering-card-title', safeText(goal.title, 'Untitled goal')),
        field('State', safeText(goal.state, 'Unknown')),
        field('Target', safeText(goal.target_kind, 'Commander defined')),
        field('Priority', safeText(goal.priority, 'Unsorted')),
      );
      return card;
    }

    createBuildsSection(overview) {
      const section = this.createSection('engineering-builds', 'Build Plans', 'Targets only');
      section.appendChild(this.createBuildForm());
      const list = el('div', 'engineering-list');
      const builds = Array.isArray(overview.build_plans) ? overview.build_plans : [];
      if (builds.length === 0) {
        list.appendChild(emptyState('No local target build plans yet.'));
      } else {
        builds.forEach((build) => list.appendChild(this.createBuildCard(build)));
      }
      section.appendChild(list);
      return section;
    }

    createBuildForm() {
      const form = el('form', 'engineering-form engineering-form--build');
      form.append(
        labeledInput('Plan', textInput('title', 'Build plan title', { required: true })),
        labeledInput('Source', selectInput('source', [
          ['commander_defined', 'Commander defined'],
          ['intel_current_loadout_reference', 'Intel current-loadout reference'],
        ], 'commander_defined')),
        labeledInput('Summary', textArea('summary', 'Target summary')),
      );
      const actions = el('div', 'engineering-form-actions');
      const submit = el('button', 'ocv-btn engineering-action', 'Add build');
      submit.type = 'submit';
      actions.appendChild(submit);
      form.appendChild(actions);
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const payload = {
          title: formValue(form, 'title'),
          source: formValue(form, 'source') || 'commander_defined',
          target_loadout_summary: {},
        };
        const summary = formValue(form, 'summary');
        if (summary) payload.target_loadout_summary = { commander_summary: summary };
        await this.handleAction(() => this.postJson('/engineering/builds', payload));
      });
      return form;
    }

    createBuildCard(build) {
      const card = el('article', 'engineering-card');
      card.append(
        el('h3', 'engineering-card-title', safeText(build.title, 'Untitled build')),
        field('Source', safeText(build.source, 'commander_defined')),
        field('Format', safeText(build.format_verification_state, 'not_applicable')),
        field('Truth boundary', safeText(build.separation_from_current_loadout, 'Target plan only.')),
      );
      return card;
    }

    createMaterialGapsSection(overview) {
      const section = this.createSection('engineering-materials', 'Material Gaps', 'Planning');
      section.appendChild(this.createMaterialGapForm());
      const posture = overview.source_posture?.materials || {};
      const postureLine = el('p', 'engineering-source-note');
      postureLine.textContent = `Inventory: ${safeText(posture.current_inventory_state, 'No Verified Source')}`;
      section.appendChild(postureLine);

      const list = el('div', 'engineering-list');
      const gaps = Array.isArray(overview.material_gaps) ? overview.material_gaps : [];
      if (gaps.length === 0) {
        list.appendChild(emptyState('No material gap selected — add a material to measure readiness.'));
      } else {
        gaps.forEach((gap) => list.appendChild(this.createGapCard(gap)));
      }
      section.appendChild(list);
      return section;
    }

    createMaterialGapForm() {
      const form = el('form', 'engineering-form engineering-form--gap');
      form.append(
        labeledInput('Material', textInput('material_id', 'Material name or id', { required: true })),
        labeledInput('Required', textInput('required_count', 'Required', { type: 'number', min: 0 })),
        labeledInput('Current', textInput('current_count', 'Unknown if blank', { type: 'number', min: 0 })),
      );
      const actions = el('div', 'engineering-form-actions');
      const submit = el('button', 'ocv-btn engineering-action', 'Compute gap');
      submit.type = 'submit';
      actions.appendChild(submit);
      form.appendChild(actions);
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const payload = {
          material_id: formValue(form, 'material_id'),
          material_display_name: formValue(form, 'material_id'),
        };
        const required = optionalNumber(form, 'required_count');
        const current = optionalNumber(form, 'current_count');
        if (required !== null) payload.commander_override_required = required;
        if (current !== null) payload.commander_override_current = current;
        await this.handleAction(() => this.postJson('/engineering/material-overrides', payload));
      });
      return form;
    }

    createGapCard(gap) {
      const card = el('article', 'engineering-card engineering-gap-card');
      card.append(el('h3', 'engineering-card-title', safeText(gap.material_display_name, 'Material')));

      /* Readiness progress (§4·5 "material gaps with progress") — honest: a bar
         only when both required and current counts are real numbers. When the
         current inventory is unknown (no verified source) the card states that
         plainly instead of drawing a fake progress bar. */
      const required = Number(gap.required_count);
      const current = Number(gap.current_count);
      const hasProgress = Number.isFinite(required) && required > 0 && Number.isFinite(current);
      if (hasProgress) {
        const pct = Math.max(0, Math.min(100, Math.round((current / required) * 100)));
        const track = el('div', 'engineering-gap-progress');
        track.setAttribute('role', 'progressbar');
        track.setAttribute('aria-valuemin', '0');
        track.setAttribute('aria-valuemax', String(required));
        track.setAttribute('aria-valuenow', String(Math.min(current, required)));
        const fill = el('span', 'engineering-gap-progress-fill');
        fill.style.width = `${pct}%`;
        if (pct >= 100) fill.classList.add('is-ready');
        track.appendChild(fill);
        card.appendChild(track);
        card.appendChild(el('p', 'engineering-gap-progress-label', `${current} / ${required} held · ${pct}% ready`));
      } else {
        card.appendChild(el('p', 'engineering-gap-progress-label engineering-gap-progress-label--unknown',
          'Inventory not verified — enter the current count to measure readiness.'));
      }

      card.append(
        field('Required', safeText(gap.required_count, 'Unsupported')),
        field('Current', safeText(gap.current_count, 'Unknown')),
        field('Gap', safeText(gap.gap, 'Unknown')),
        field('State', safeText(gap.state, 'Unknown')),
        el('p', 'engineering-card-note', safeText(gap.fallback, 'Unknown')),
      );
      return card;
    }

    createAcquisitionSection(overview) {
      const section = this.createSection('engineering-acquisition', 'Acquisition Plans', 'Handoffs');
      section.appendChild(this.createAcquisitionForm());
      const list = el('div', 'engineering-list');
      const plans = Array.isArray(overview.acquisition_plans) ? overview.acquisition_plans : [];
      if (plans.length === 0) {
        list.appendChild(emptyState('No acquisition plan yet — plan where to gather the materials this build needs.'));
      } else {
        plans.forEach((plan) => list.appendChild(this.createAcquisitionCard(plan)));
      }
      section.appendChild(list);
      return section;
    }

    createAcquisitionForm() {
      const form = el('form', 'engineering-form engineering-form--acquisition');
      form.append(
        labeledInput('Plan', textInput('title', 'Acquisition plan title', { required: true })),
        labeledInput('Material', textInput('material_id', 'Material name or id', { required: true })),
        labeledInput('Needed', textInput('quantity_needed', 'Needed', { type: 'number', min: 0 })),
        labeledInput('Notes', textArea('notes', 'Commander note')),
      );
      const actions = el('div', 'engineering-form-actions');
      const submit = el('button', 'ocv-btn engineering-action', 'Add plan');
      submit.type = 'submit';
      actions.appendChild(submit);
      form.appendChild(actions);
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const materialId = formValue(form, 'material_id');
        const material = {
          material_id: materialId,
          display_name: materialId,
        };
        const qty = optionalNumber(form, 'quantity_needed');
        if (qty !== null) material.quantity_needed = qty;
        const payload = {
          title: formValue(form, 'title'),
          target_materials: [material],
        };
        appendIfPresent(payload, 'notes', formValue(form, 'notes'));
        await this.handleAction(() => this.postJson('/engineering/acquisition-plan', payload));
      });
      return form;
    }

    createAcquisitionCard(plan) {
      const card = el('article', 'engineering-card engineering-acquisition-card');
      card.id = `acquisition_plan:${plan.acquisition_plan_id}`;
      card.append(
        el('h3', 'engineering-card-title', safeText(plan.title, 'Acquisition plan')),
        field('State', safeText(plan.state, 'draft')),
        field('Materials', String(Array.isArray(plan.target_materials) ? plan.target_materials.length : 0)),
      );

      const materials = el('ul', 'engineering-mini-list');
      (Array.isArray(plan.target_materials) ? plan.target_materials : []).forEach((material) => {
        const item = el('li', '', `${safeText(material.display_name || material.material_id, 'Material')} - ${safeText(material.quantity_needed, 'Unknown')}`);
        materials.appendChild(item);
      });
      card.appendChild(materials);

      const actions = el('div', 'engineering-card-actions');
      const nav = el('button', 'ocv-btn engineering-action', 'Send to Navigation');
      nav.type = 'button';
      nav.addEventListener('click', () => this.sendHandoff(plan.acquisition_plan_id, 'navigation'));
      const ops = el('button', 'ocv-btn-ghost engineering-action', 'Send to Operations');
      ops.type = 'button';
      ops.addEventListener('click', () => this.sendHandoff(plan.acquisition_plan_id, 'operations'));
      actions.append(nav, ops);
      card.appendChild(actions);
      return card;
    }

    createReadinessSection(overview) {
      const section = this.createSection('engineering-readiness', 'Readiness', 'Manual');
      section.appendChild(this.createReadinessForm());
      const readiness = overview.readiness || {};
      const groups = [
        ['Blueprints', readiness.blueprints || []],
        ['Engineers', readiness.engineers || []],
        ['Guardian tech', readiness.guardian_tech || []],
        ['Suit engineering', readiness.suit_engineering || []],
      ];
      groups.forEach(([label, items]) => {
        const group = el('div', 'engineering-readiness-group');
        group.append(el('h3', 'engineering-subsection-title', label));
        if (!items.length) {
          group.appendChild(emptyState('No local records.'));
        } else {
          items.slice(0, 4).forEach((item) => group.appendChild(this.createReadinessItem(item)));
        }
        section.appendChild(group);
      });
      return section;
    }

    createReadinessForm() {
      const form = el('form', 'engineering-form engineering-form--readiness');
      form.append(
        labeledInput('Type', selectInput('readiness_type', READINESS_OPTIONS, 'blueprint')),
        labeledInput('Label', textInput('label', 'Commander-entered label', { required: true })),
        labeledInput('State', textInput('state', 'State')),
        labeledInput('Requirements', textArea('requirements_text', 'Commander-entered requirements')),
      );
      const actions = el('div', 'engineering-form-actions');
      const submit = el('button', 'ocv-btn engineering-action', 'Add readiness');
      submit.type = 'submit';
      actions.appendChild(submit);
      form.appendChild(actions);
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        await this.submitReadiness(form);
      });
      return form;
    }

    async submitReadiness(form) {
      const type = formValue(form, 'readiness_type') || 'blueprint_progress';
      const label = formValue(form, 'label');
      const state = formValue(form, 'state');
      const requirementsText = formValue(form, 'requirements_text');
      const path = '/engineering/readiness-states';
      const payload = { kind: type, label };

      if (state) payload.state = state;
      if (requirementsText) {
        payload.requirements_known = 'manual';
        payload.requirements_text = requirementsText;
      }
      await this.handleAction(() => this.postJson(path, payload));
    }

    createReadinessItem(item) {
      const node = el('article', 'engineering-readiness-item');
      const label = item.blueprint_label
        || item.engineer_label
        || item.guardian_tech_label
        || item.suit_engineering_label
        || 'Readiness item';
      node.append(
        el('h4', 'engineering-readiness-title', label),
        field('State', safeText(item.state, 'unknown')),
      );
      if (item.requirements_known) {
        node.appendChild(field('Requirements', safeText(item.requirements_known, 'unknown')));
      }
      return node;
    }

    createSourceGatesSection(overview) {
      const section = this.createSection('engineering-source-gates', 'Source Gates', 'Disabled');
      const posture = overview.source_posture || {};
      section.append(
        this.createGateLine('CAPI', posture.capi_material_inventory || 'Source-gated'),
        this.createGateLine('EDSY', posture.edsy || 'Format unverified'),
        this.createGateLine('Coriolis', posture.coriolis || 'Format unverified'),
        this.createGateLine('Ardent', posture.ardent || 'Disabled / not used'),
      );

      const actions = el('div', 'engineering-gate-actions');
      [
        ['CAPI inventory', '/engineering/source-attempts/capi'],
        ['EDSY import', '/engineering/import-sources/edsy/attempt-import'],
        ['EDSY export', '/engineering/import-sources/edsy/attempt-export'],
        ['Coriolis import', '/engineering/import-sources/coriolis/attempt-import'],
        ['Coriolis export', '/engineering/import-sources/coriolis/attempt-export'],
        ['Ardent material truth', '/engineering/source-attempts/ardent'],
      ].forEach(([label, path]) => {
        const button = el('button', 'ocv-btn-ghost engineering-action', label);
        button.type = 'button';
        button.addEventListener('click', () => this.recordBlockedAttempt(path));
        actions.appendChild(button);
      });
      section.appendChild(actions);
      this.statusNode = el('p', 'engineering-action-status');
      section.appendChild(this.statusNode);
      return section;
    }

    createGateLine(label, state) {
      const line = el('div', 'engineering-gate-line');
      line.append(el('span', 'engineering-gate-label', label), badge(state, 'off'));
      return line;
    }

    createProofSection() {
      const section = this.createSection('engineering-proof', 'Proof', 'Activity Log');
      const button = el('button', 'ocv-btn-ghost engineering-action', 'Open Activity Log');
      button.type = 'button';
      button.addEventListener('click', () => {
        const intent = window.Shell?.createRouteTransferIntent?.({
          originRoute: '/engineering',
          originPackage: 'engineering',
          originSectionId: 'engineering-proof',
          targetRoute: '/activity-log',
          targetSectionId: 'log-section-sources',
          targetLabel: 'Engineering proof records',
          reason: 'Inspect Engineering source-chain and blocked-source records.',
          returnLabel: 'Back to Engineering',
          returnTarget: { route: '/engineering', sectionId: 'engineering-proof' },
        });
        if (intent && window.Shell?.startRouteTransfer) {
          window.Shell.startRouteTransfer(intent);
        } else {
          window.location.hash = '#/activity-log';
        }
      });
      section.append(
        emptyState('Engineering proof records are written to the local Activity Log.'),
        button,
      );
      return section;
    }

    async sendHandoff(acquisitionPlanId, target) {
      const path = `/engineering/acquisition-plans/${encodeURIComponent(acquisitionPlanId)}/handoff/${target}`;
      await this.handleAction(async () => {
        const result = await this.postJson(path, {});
        const intent = result?.route_transfer_intent || result?.route_intent;
        if (intent && window.Shell?.startRouteTransfer) {
          window.Shell.startRouteTransfer(intent);
        }
        return result;
      });
    }

    async recordBlockedAttempt(path) {
      await this.handleAction(() => this.postJson(path, {}), 'Blocked attempt recorded.');
    }

    async handleAction(action, successMessage = 'Saved locally.') {
      try {
        const result = await action();
        this.setStatus(successMessage);
        return result;
      } catch (error) {
        this.setStatus(error?.message || 'Request failed.');
        return null;
      }
    }

    setStatus(message) {
      if (this.statusNode) {
        this.statusNode.textContent = message;
      }
    }

    applyRouteTransferArrival() {
      if (window.Shell?.applyRouteTransferArrival && this.root) {
        window.Shell.applyRouteTransferArrival('/engineering', this.root);
      }
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    new EngineeringController();
  });

  if (typeof globalThis.__engineeringExports === 'undefined') {
    globalThis.__engineeringExports = {
      EngineeringController,
      safeText,
    };
  }
})();
