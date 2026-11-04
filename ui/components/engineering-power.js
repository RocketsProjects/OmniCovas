// Only presentation and commander input. Physics and proposals are API results.
const el = (tag, cls = '', text) => {
  const n = document.createElement(tag);
  n.className = cls;
  if (text != null) n.textContent = String(text);
  return n;
};
const fmt = (v, unit = 'MW') =>
  v == null
    ? '—'
    : `${Number(v).toLocaleString('en-US', { maximumFractionDigits: unit === '%' ? 2 : 6 })}${unit ? ` ${unit}` : ''}`;
const states = {
  powered: 'Powered',
  passive: 'No power required',
  switched_off: 'Switched off',
  not_drawing: 'Retracted · no draw',
  priority_shutdown: 'Priority shutdown',
  insufficient_power: 'Insufficient power',
  unknown: 'Unknown',
  empty: 'Empty slot',
};
export const powerStateLabel = (state) => states[state] || 'Unknown';
const conclusions = {
  all_required_powered: 'All required modules powered',
  nonessential_shed: 'Power priorities disable nonessential equipment',
  required_lost: 'Required modules lose power',
  cannot_verify: 'Cannot verify power safety',
  requirements_not_set: 'Required modules not selected',
};
const field = (text, control) => {
  const n = el('label');
  n.append(el('span', '', text), control);
  return n;
};
const choose = (name, values) => {
  const n = el('select');
  n.name = name;
  values.forEach(([value, text]) => {
    const op = el('option', '', text);
    op.value = value;
    n.append(op);
  });
  return n;
};
const action = (text, call) => {
  const n = el('button', 'ocv-btn-ghost engineering-action', text);
  n.type = 'button';
  n.addEventListener('click', call);
  return n;
};

// "Keep powered" is the planner's existing per-scenario `required_in` flag, the
// same one Analysis → Power calls "Required here". There is no second store.
export const powerContext = (plan) =>
  `${plan?.scenario || 'normal'}:${plan?.deployment || 'deployed'}`;
export const isKeepPowered = (plan, slot) =>
  !!plan?.modules
    ?.find((r) => r.slot === slot)
    ?.required_in?.includes(powerContext(plan));
export function withKeepPowered(plan, slot, on) {
  const next = structuredClone(plan || {});
  next.modules ||= [];
  let row = next.modules.find((r) => r.slot === slot);
  if (!row) {
    row = { slot, required_in: [] };
    next.modules.push(row);
  }
  const keys = new Set(row.required_in || []);
  if (on) keys.add(powerContext(next));
  else keys.delete(powerContext(next));
  row.required_in = [...keys];
  return next;
}
export const scopeLabel = (data, plan) => {
  const scenario = powerContext(plan).split(':')[0];
  const name =
    data?.scenarios?.find((s) => s.id === scenario)?.label || scenario;
  return `${name} · ${plan?.deployment === 'retracted' ? 'retracted' : 'deployed'}`;
};
export const keepPoweredCount = (plan) =>
  (plan?.modules || []).filter((r) =>
    r.required_in?.includes(powerContext(plan)),
  ).length;

const SVG = 'http://www.w3.org/2000/svg';
// Compact shield toggle for an Outfitting row. State is passed in, never kept.
export function createKeepPoweredButton({
  slot,
  name,
  on,
  scope,
  switchedOff = false,
  toggle,
}) {
  const n = el('button', 'engineering-keep-powered');
  n.type = 'button';
  n.name = 'outfitting_row_keep';
  n.dataset.slot = slot;
  n.dataset.keepPowered = String(on);
  n.setAttribute('aria-pressed', String(on));
  n.setAttribute('aria-label', `Keep ${name} powered in ${scope}`);
  n.title = `${on ? 'Keep powered: ON' : 'Keep powered: off'} · ${scope}. ${
    on
      ? 'Suggest priorities will protect this module. Click to remove.'
      : 'Click to have Suggest priorities protect this module.'
  }${switchedOff ? ' It is switched off and Suggest will not switch it on.' : ''}`;
  const icon = document.createElementNS(SVG, 'svg');
  icon.setAttribute('viewBox', '0 0 16 16');
  icon.setAttribute('aria-hidden', 'true');
  const path = document.createElementNS(SVG, 'path');
  path.setAttribute('d', 'M8 1.5l5.5 2v4c0 3.2-2.3 5.6-5.5 7-3.2-1.4-5.5-3.8-5.5-7v-4z');
  icon.append(path);
  n.append(icon);
  n.addEventListener('click', (event) => {
    event.stopPropagation();
    toggle(slot, !on);
  });
  return n;
}

// The same commander overrides and resolved power rows drive both surfaces.
export function createModulePower({ slot, change, keepPowered = () => {} }) {
  const root = el('div', 'engineering-module-power');
  root.setAttribute('aria-label', 'Selected module power');
  const enabled = el('input');
  enabled.type = 'checkbox';
  enabled.name = 'outfitting_power_enabled';
  const priority = choose(
    'outfitting_power_priority',
    [1, 2, 3, 4, 5].map((n) => [n, `P${n}`]),
  );
  enabled.dataset.slot = priority.dataset.slot = slot;
  const draw = el('strong', 'engineering-module-power-draw');
  const state = el('span', 'engineering-module-power-state');
  enabled.addEventListener('change', () =>
    change(slot, { enabled: enabled.checked }),
  );
  priority.addEventListener('change', () =>
    change(slot, { priority: Number(priority.value) }),
  );
  const keep = el('input');
  keep.type = 'checkbox';
  keep.name = 'outfitting_power_keep';
  keep.dataset.slot = slot;
  keep.addEventListener('change', () => keepPowered(slot, keep.checked));
  root.append(
    field('On', enabled),
    field('Priority', priority),
    field('Keep powered', keep),
    draw,
    state,
  );
  function render(data, plan, pending, error) {
    const module = data?.planned_modules?.find((r) => r.slot === slot);
    root.hidden = !module || module.empty || module.draw_mw === 0;
    if (root.hidden) return;
    const setting = plan.modules?.find((r) => r.slot === slot);
    enabled.checked = setting?.enabled ?? module.enabled === true;
    keep.checked = isKeepPowered(plan, slot);
    keep.title = `Keep powered in ${scopeLabel(data, plan)}`;
    priority.value = String(setting?.priority ?? module.priority ?? '');
    enabled.disabled = priority.disabled =
      !!module.power_lock || !module.controls_verified;
    root.title = !module.controls_verified
      ? 'Verified power-control rules are unavailable in this catalogue.'
      : module.power_lock
        ? `Fixed at priority ${module.power_lock}; cannot switch off.`
        : '';
    const context = `${plan.scenario || 'normal'}:${plan.deployment || 'deployed'}`;
    const result = data.cases
      .find((c) => c.id === context)
      ?.planned.modules.find((r) => r.slot === slot);
    draw.textContent = pending || error ? '— MW' : fmt(result?.requested_mw);
    state.textContent = pending
      ? 'Calculating…'
      : error
        ? 'Unknown'
        : states[result?.state] || 'Unknown';
    root.dataset.state = pending || error ? 'unknown' : result?.state;
    state.title =
      pending || error
        ? ''
        : `Requested ${fmt(result?.requested_mw)} · powered ${fmt(result?.effective_mw)}. Planning simulation.`;
  }
  return { root, render };
}

export function createEngineeringPower({
  getPlan,
  change,
  propose,
  editModule,
  slotName = (slot) => slot,
  baselineLabel = 'installed',
  busyChanged = () => {},
}) {
  const root = el('section', 'engineering-power-workspace');
  root.hidden = true;
  root.setAttribute('aria-label', 'Power management and priorities');
  const controls = el('div', 'engineering-power-controls');
  const scenario = choose('power_scenario', []);
  const deployment = choose('power_deployment', [
    ['retracted', 'Retracted'],
    ['deployed', 'Deployed'],
  ]);
  const custom = el('input');
  custom.name = 'power_custom_percent';
  custom.type = 'number';
  custom.min = 0;
  custom.max = 100;
  custom.step = 'any';
  const customField = field('Custom output %', custom);
  const protect = el('input');
  protect.type = 'checkbox';
  protect.name = 'power_protect';
  const main = el('div', 'engineering-power-main');
  const statistics = el('aside', 'engineering-power-statistics');
  statistics.setAttribute('aria-label', 'Power comparison');
  const assignments = el('div', 'engineering-power-assignments');
  assignments.setAttribute('aria-label', 'Priority groups');
  const proposalBox = el('div', 'engineering-power-proposal');
  proposalBox.setAttribute('role', 'status');
  let staleMessage = 'The build changed. Request a new proposal.';
  let last,
    busy = false,
    reviewFingerprint = null;
  const fingerprint = () =>
    JSON.stringify([
      getPlan(),
      last?.planned_modules,
      last?.cases?.map((c) => [c.id, c.planned.generation_mw]),
    ]);
  const context = () => `${scenario.value}:${deployment.value}`;
  const alter = (update) => {
    const plan = structuredClone(getPlan());
    update(plan);
    change(plan);
  };
  const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
  const moduleNames = (slots, names) =>
    slots.map((s) => `${names[s] || slotName(s)} (${slotName(s)})`).join(', ');
  const priorityOf = (value) => (value == null ? '?' : `P${value}`);
  const stateOf = (outcome, slot) =>
    powerStateLabel(outcome.after.states[slot]);
  // One reviewable block per protected scenario: demand, who stays on, who goes.
  function outcomeBlock(outcome, changed) {
    const block = el('section', 'engineering-power-outcome');
    block.dataset.context = outcome.context;
    const [, mode] = outcome.context.split(':');
    block.append(
      el(
        'h4',
        '',
        `${outcome.label} · ${mode === 'retracted' ? 'Hardpoints retracted' : 'Hardpoints deployed'}`,
      ),
      el(
        'p',
        'engineering-power-outcome-totals',
        `Requested ${fmt(outcome.requested_mw)} of ${fmt(outcome.generation_mw)} available. Powered: ${fmt(outcome.before.effective_mw)} now → ${fmt(outcome.after.effective_mw)} after.`,
      ),
    );
    const powered = el('p', 'engineering-power-outcome-powered');
    powered.dataset.outcome = 'powered';
    powered.append(
      el('strong', '', `Remain powered (${outcome.after.powered.length}): `),
      document.createTextNode(
        outcome.after.powered.length
          ? moduleNames(outcome.after.powered, outcome.names)
          : 'none',
      ),
    );
    const shut = el('p', 'engineering-power-outcome-shutdown');
    shut.dataset.outcome = 'shutdown';
    shut.append(
      el('strong', '', `Will shut down (${outcome.after.shutdown.length}): `),
      document.createTextNode(
        outcome.after.shutdown.length
          ? moduleNames(outcome.after.shutdown, outcome.names)
          : 'none',
      ),
    );
    block.append(powered, shut);
    if (changed) {
      const gained = outcome.after.powered.filter(
        (s) => !outcome.before.powered.includes(s),
      );
      const lost = outcome.after.shutdown.filter(
        (s) => !outcome.before.shutdown.includes(s),
      );
      if (gained.length || lost.length)
        block.append(
          el(
            'p',
            'engineering-power-outcome-delta',
            `Compared with now: ${gained.length ? `powered again — ${moduleNames(gained, outcome.names)}` : 'no module regains power'}; ${lost.length ? `newly shut down — ${moduleNames(lost, outcome.names)}` : 'no new shutdowns'}.`,
          ),
        );
    }
    return block;
  }
  function changeTable(result) {
    const table = el('table', 'engineering-power-changes');
    const head = el('tr');
    ['Module', 'Priority now', 'Proposed', 'Result after applying'].forEach(
      (t) => head.append(el('th', '', t)),
    );
    const body = el('tbody');
    table.append(el('thead'), body);
    table.firstChild.append(head);
    result.changes.forEach((c) => {
      const tr = el('tr');
      tr.dataset.slot = c.slot;
      const proposed = [
        c.proposed_priority !== c.current_priority
          ? priorityOf(c.proposed_priority)
          : `${priorityOf(c.proposed_priority)} (unchanged)`,
        ...(c.proposed_enabled !== c.current_enabled
          ? [c.proposed_enabled ? 'switch on' : 'switch off']
          : []),
      ].join(' · ');
      const effects = result.outcomes.map(
        (o) =>
          `${powerStateLabel(o.before.states[c.slot])} → ${stateOf(o, c.slot)}`,
      );
      // Name the scenario only when the effect differs between scenarios.
      const effectText =
        new Set(effects).size > 1
          ? result.outcomes
              .map((o, i) => `${o.label}: ${effects[i]}`)
              .join('; ')
          : effects[0] || '';
      tr.append(
        el('td', '', `${c.name} · ${slotName(c.slot)}`),
        el('td', '', priorityOf(c.current_priority)),
        el('td', '', proposed),
        el('td', '', effectText),
      );
      body.append(tr);
    });
    return table;
  }
  const suggest = async () => {
    if (busy) return;
    busy = true;
    busyChanged(true);
    proposalButton.disabled = true;
    proposalBox.textContent = 'Testing assignments…';
    staleMessage = 'The build changed. Request a new proposal.';
    try {
      const requested = fingerprint();
      const result = await propose();
      if (requested !== fingerprint())
        throw new Error('The build changed. Request a new proposal.');
      reviewFingerprint = requested;
      proposalBox.replaceChildren(el('p', '', result.reason));
      const reviewActions = el('div', 'engineering-power-proposal-actions');
      proposalBox.append(reviewActions);
      const proposing =
        result.state === 'verified_proposal' && result.changes?.length;
      if (result.state === 'verified_proposal' || result.state === 'no_change_needed') {
        proposalBox.dataset.state = proposing
          ? 'verified_proposal'
          : 'no_change_needed';
        const names = result.outcomes?.[0]?.names || {};
        const marked = (result.plan?.modules || []).filter((r) =>
          r.required_in?.some((k) => result.plan.protect.includes(k)),
        );
        proposalBox.append(
          el(
            'p',
            '',
            `Required: ${marked.map((r) => names[r.slot] || slotName(r.slot)).join(', ') || 'none selected'}.`,
          ),
        );
        if (proposing) {
          proposalBox.append(
            el(
              'strong',
              '',
              `${plural(result.changes.length, 'module assignment')} would change`,
            ),
            changeTable(result),
          );
        } else {
          proposalBox.append(
            el(
              'strong',
              '',
              'No changes needed. Nothing was changed and nothing will be applied.',
            ),
          );
        }
        (result.outcomes || []).forEach((o) =>
          proposalBox.append(outcomeBlock(o, proposing)),
        );
        if (proposing)
          reviewActions.append(
            action('Apply proposed priorities', () => {
              if (reviewFingerprint !== fingerprint()) {
                proposalBox.textContent =
                  'The build changed. Request a new proposal.';
                return;
              }
              change(result.plan);
              proposalBox.dataset.state = 'applied';
              proposalBox.textContent = `Applied ${plural(result.changes.length, 'module assignment')}: ${result.changes.map((c) => `${c.name} ${priorityOf(c.current_priority)} → ${priorityOf(c.proposed_priority)}`).join('; ')}. Undo is available in the build toolbar.`;
              reviewFingerprint = null;
            }),
          );
      } else proposalBox.dataset.state = result.state;
      reviewActions.append(
        action(proposing ? 'Cancel proposal' : 'Dismiss', () => {
          reviewFingerprint = null;
          proposalBox.dataset.state = 'cancelled';
          proposalBox.textContent = proposing
            ? 'Proposal cancelled. Priorities unchanged.'
            : '';
        }),
      );
      proposalBox.scrollIntoView?.({ block: 'nearest' });
    } catch (failure) {
      proposalBox.textContent = failure.message || 'Proposal unavailable.';
    }
    busy = false;
    busyChanged(false);
    proposalButton.disabled = false;
  };
  const proposalButton = action('Suggest priorities', suggest);
  // Reset restores priorities only. The baseline is the installed Journal
  // observation; a hull with no observation falls back to the catalogue stock
  // default (P1), and a newly fitted module starts at P1. On/Off, Keep powered,
  // scenarios, modules and engineering are never touched.
  const baselineName = baselineLabel === 'installed' ? 'Installed' : 'Stock';
  const baselineText =
    baselineLabel === 'installed'
      ? 'installed priorities observed in the Journal'
      : 'catalogue stock defaults (P1 for every module; no Journal observation exists for this hull)';
  const resetDifferences = (plan) => {
    const baseline = new Map(last.installed_modules.map((r) => [r.slot, r]));
    const found = [];
    for (const r of last.planned_modules) {
      if (r.empty) continue;
      const from =
        plan.modules?.find((s) => s.slot === r.slot)?.priority ?? r.priority;
      const to = r.new_fit ? 1 : baseline.get(r.slot)?.priority;
      if (to === undefined || from === to) continue;
      found.push({ slot: r.slot, name: r.name || r.slot, from, to });
    }
    return found;
  };
  // A catalogue hull has no Journal observation; never describe stock as observed.
  const priorityBasis = (module) =>
    baselineLabel === 'installed' || module.new_fit || module.power_lock
      ? module.priority_basis
      : 'Catalogue stock default (no Journal observation for this hull)';
  const priorityText = (value) => (value == null ? 'P?' : `P${value}`);
  const dismissAction = (text) =>
    action(text, () => {
      reviewFingerprint = null;
      proposalBox.dataset.state = 'dismissed';
      proposalBox.textContent = '';
    });
  const reset = () => {
    if (!last || busy) return;
    const differences = resetDifferences(getPlan());
    reviewFingerprint = null;
    if (!differences.length) {
      proposalBox.dataset.state = 'reset_no_change';
      const actions = el('div', 'engineering-power-proposal-actions');
      actions.append(dismissAction('Dismiss'));
      proposalBox.replaceChildren(
        el(
          'p',
          '',
          `Priorities already match the ${baselineText}. No reset was needed and nothing was changed.`,
        ),
        actions,
      );
      return;
    }
    reviewFingerprint = fingerprint();
    staleMessage = 'The build changed. Choose Reset priorities again.';
    proposalBox.dataset.state = 'reset_review';
    const table = el('table', 'engineering-power-changes');
    const head = el('tr');
    ['Module', 'Priority now', 'After reset'].forEach((t) =>
      head.append(el('th', '', t)),
    );
    const body = el('tbody');
    table.append(el('thead'), body);
    table.firstChild.append(head);
    differences.forEach((d) => {
      const tr = el('tr');
      tr.dataset.slot = d.slot;
      tr.append(
        el('td', '', `${d.name} · ${slotName(d.slot)}`),
        el('td', '', priorityText(d.from)),
        el('td', '', priorityText(d.to)),
      );
      body.append(tr);
    });
    const confirm = action('Confirm reset', () => {
      if (reviewFingerprint !== fingerprint()) {
        proposalBox.textContent = staleMessage;
        reviewFingerprint = null;
        return;
      }
      const before = structuredClone(getPlan());
      const next = structuredClone(before);
      (next.modules || []).forEach((r) => {
        delete r.priority;
      });
      reviewFingerprint = null;
      change(next);
      const undo = action('Undo power reset', () => {
        change(before);
        proposalBox.dataset.state = 'reset_undone';
        proposalBox.textContent = `Power reset undone. ${plural(differences.length, 'priority', 'priorities')} restored: ${differences.map((d) => `${d.name} ${priorityText(d.to)} → ${priorityText(d.from)}`).join('; ')}.`;
      });
      undo.dataset.undoReset = 'true';
      proposalBox.dataset.state = 'reset_applied';
      proposalBox.replaceChildren(
        el(
          'p',
          '',
          `Reset ${plural(differences.length, 'priority', 'priorities')} to the ${baselineText}. On/Off, Keep powered, scenarios, modules and engineering were not changed.`,
        ),
        undo,
      );
      undo.focus();
    });
    const cancel = dismissAction('Cancel reset');
    cancel.addEventListener('click', () => {
      proposalBox.textContent = 'Reset cancelled. Priorities unchanged.';
    });
    const actions = el('div', 'engineering-power-proposal-actions');
    actions.append(confirm, cancel);
    proposalBox.replaceChildren(
      el(
        'p',
        '',
        `Reset ${plural(differences.length, 'priority', 'priorities')} to the ${baselineText}? Only priorities change; On/Off, Keep powered, scenarios, modules and engineering are kept.`,
      ),
      actions,
      table,
    );
    proposalBox.scrollIntoView?.({ block: 'nearest' });
    confirm.focus();
  };
  proposalBox.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && proposalBox.dataset.state === 'reset_review') {
      event.preventDefault();
      reviewFingerprint = null;
      proposalBox.dataset.state = 'dismissed';
      proposalBox.textContent = 'Reset cancelled. Priorities unchanged.';
    }
  });
  scenario.addEventListener('change', () =>
    alter((p) => {
      p.scenario = scenario.value;
    }),
  );
  deployment.addEventListener('change', () =>
    alter((p) => {
      p.deployment = deployment.value;
    }),
  );
  custom.addEventListener('change', () =>
    alter((p) => {
      p.custom_percent = Number(custom.value);
    }),
  );
  protect.addEventListener('change', () =>
    alter((p) => {
      const keys = new Set(p.protect || []);
      protect.checked ? keys.add(context()) : keys.delete(context());
      p.protect = [...keys];
    }),
  );
  const sourceToggle = el('input');
  sourceToggle.type = 'checkbox';
  sourceToggle.name = 'power_source_details';
  sourceToggle.addEventListener('change', () => {
    root.dataset.showSources = String(sourceToggle.checked);
  });
  const resetButton = action('Reset priorities', reset);
  controls.append(
    field('Output scenario', scenario),
    field('Hardpoints', deployment),
    customField,
    field('Protect in proposal', protect),
    proposalButton,
    field('Source details', sourceToggle),
    resetButton,
  );
  main.append(statistics, assignments);
  root.append(controls, main, proposalBox);
  function updateSlot(slot, update) {
    alter((p) => {
      p.modules ||= [];
      let r = p.modules.find((r) => r.slot === slot);
      if (!r) {
        r = { slot, required_in: [] };
        p.modules.push(r);
      }
      update(r);
    });
  }
  function render(data, pending = false, error = '') {
    const active = root.contains(document.activeElement)
      ? {
          slot: document.activeElement.dataset.slot,
          name: document.activeElement.name,
        }
      : null;
    if (!data) {
      statistics.textContent = 'Power data unavailable.';
      return;
    }
    last = data;
    if (pending && proposalBox.querySelector('[data-undo-reset]'))
      proposalBox.replaceChildren();
    if (
      !busy &&
      reviewFingerprint &&
      (pending || reviewFingerprint !== fingerprint())
    ) {
      proposalBox.textContent = staleMessage;
      reviewFingerprint = null;
    }
    const plan = getPlan();
    if (!scenario.options.length)
      data.scenarios.forEach((s) => {
        const op = el('option', '', s.label);
        op.value = s.id;
        scenario.append(op);
      });
    scenario.value = plan.scenario || 'normal';
    deployment.value = plan.deployment || 'deployed';
    custom.value = plan.custom_percent ?? 100;
    customField.hidden = scenario.value !== 'custom';
    protect.checked = (plan.protect || []).includes(context());
    proposalButton.disabled = busy || pending || !!error;
    resetButton.disabled = pending || !!error;
    const current = data.cases.find((c) => c.id === context());
    if (!current) return;
    statistics.replaceChildren(
      el('h3', '', `Power simulation · ${baselineName.toLowerCase()} / planned`),
    );
    const table = el('table'),
      head = el('tr'),
      th = el('thead'),
      body = el('tbody');
    ['', baselineName, 'Planned'].forEach((t) => head.append(el('th', '', t)));
    th.append(head);
    table.append(th, body);
    const stat = (id, label, old, next) => {
      const tr = el('tr');
      tr.dataset.powerMetric = id;
      const name = el('th', '', label);
      name.scope = 'row';
      tr.append(
        name,
        el('td', '', old),
        el('td', '', pending ? '…' : error ? '—' : next),
      );
      body.append(tr);
    };
    stat(
      'generation',
      'Available generation',
      fmt(current.installed.generation_mw),
      fmt(current.planned.generation_mw),
    );
    for (const mode of ['retracted', 'deployed']) {
      const c = data.cases.find((c) => c.id === `${scenario.value}:${mode}`);
      stat(
        `${mode}_requested`,
        `${mode === 'deployed' ? 'Deployed' : 'Retracted'} requested`,
        `${fmt(c.installed.requested_mw)} / ${fmt(c.installed.requested_percent, '%')}`,
        `${fmt(c.planned.requested_mw)} / ${fmt(c.planned.requested_percent, '%')}`,
      );
      stat(
        `${mode}_headroom`,
        `${mode === 'deployed' ? 'Deployed' : 'Retracted'} margin`,
        fmt(c.installed.headroom_mw),
        fmt(c.planned.headroom_mw),
      );
    }
    stat(
      'effective',
      'Powered draw · selected state',
      fmt(current.installed.effective_mw),
      fmt(current.planned.effective_mw),
    );
    stat(
      'remaining',
      'Margin after shutdowns',
      fmt(current.installed.remaining_headroom_mw),
      fmt(current.planned.remaining_headroom_mw),
    );
    statistics.append(table);
    const names = new Map(data.planned_modules.map((r) => [r.slot, r.name]));
    for (const side of ['installed', 'planned']) {
      const r = current[side],
        waiting = pending && side === 'planned',
        failed = error && side === 'planned';
      const summary = el('div', 'engineering-power-conclusion');
      summary.dataset.conclusion = waiting
        ? 'pending'
        : failed
          ? 'cannot_verify'
          : r.conclusion;
      summary.append(
        el(
          'strong',
          '',
          `${side === 'planned' ? 'Planned' : baselineName} · ${waiting ? 'Calculating…' : failed ? 'Cannot verify power safety' : conclusions[r.conclusion]}`,
        ),
      );
      if (!waiting && !failed && r.required_lost.length)
        summary.append(
          el(
            'p',
            '',
            r.required_lost
              .map((s) => `${names.get(s) || s} (${slotName(s)})`)
              .join(', '),
          ),
        );
      if (!waiting && !failed && r.shutdown_groups.length)
        summary.append(
          el('p', '', `Shutdown groups: ${r.shutdown_groups.join(', ')}`),
        );
      if (r.missing.length) summary.append(el('p', '', r.missing.join('; ')));
      statistics.append(summary);
    }
    const details = el('details', 'engineering-source-why');
    details.append(
      el('summary', '', 'Scenario & calculation details'),
      el(
        'p',
        '',
        data.scenarios.find((s) => s.id === scenario.value)?.description,
      ),
    );
    data.limitations.forEach((t) => details.append(el('p', '', t)));
    data.sources.forEach((s) => {
      if (/^https:\/\//.test(s.url)) {
        const a = el('a', '', s.name);
        a.href = s.url;
        a.target = '_blank';
        a.rel = 'noopener noreferrer';
        details.append(a);
      }
    });
    statistics.append(details);
    const installed = new Map(data.installed_modules.map((r) => [r.slot, r]));
    const oldStates = new Map(
      current.installed.modules.map((r) => [r.slot, r]),
    );
    const nextStates = new Map(current.planned.modules.map((r) => [r.slot, r]));
    assignments.replaceChildren();
    for (const priority of [1, 2, 3, 4, 5, null]) {
      const members = data.planned_modules.filter(
        (r) =>
          (plan.modules?.find((s) => s.slot === r.slot)?.priority ??
            r.priority) === priority,
      );
      if (!members.length && priority == null) continue;
      const group = current.planned.groups.find((g) => g.priority === priority),
        section = el('section', 'engineering-power-group');
      section.dataset.priorityGroup = priority ?? 'unknown';
      section.append(
        el(
          'h3',
          '',
          `${priority ? `Priority ${priority}` : 'Priority unverified'} · ${pending || error ? '—' : fmt(group?.requested_mw)}${!pending && !error && group?.shutdown ? ' · shutdown' : ''}`,
        ),
      );
      members.forEach((module) => {
        const old = installed.get(module.slot),
          before = oldStates.get(module.slot),
          after = nextStates.get(module.slot),
          settings = plan.modules?.find((r) => r.slot === module.slot);
        const tr = el('div', 'engineering-power-module');
        tr.dataset.powerSlot = module.slot;
        tr.dataset.state = pending || error ? 'unknown' : after?.state;
        const name = action(module.name || module.slot, () =>
          editModule(module.slot),
        );
        name.classList.add('engineering-power-module-name');
        name.append(el('small', '', slotName(module.slot)));
        const observed = el(
          'div',
          'engineering-power-observed',
          `${baselineName} ${old?.priority ?? '—'} · ${old?.enabled == null ? '?' : old.enabled ? 'On' : 'Off'} · ${fmt(before?.requested_mw)}`,
        );
        observed.title = states[before?.state] || 'Not fitted';
        const on = el('input');
        on.type = 'checkbox';
        on.name = 'power_enabled';
        on.dataset.slot = module.slot;
        on.checked = (settings?.enabled ?? module.enabled) === true;
        on.setAttribute('aria-label', `${module.slot} planned enabled`);
        const rank = choose('power_priority', [
          [1, '1'],
          [2, '2'],
          [3, '3'],
          [4, '4'],
          [5, '5'],
        ]);
        rank.dataset.slot = module.slot;
        rank.value = String(settings?.priority ?? module.priority ?? '');
        rank.setAttribute('aria-label', `${module.slot} planned priority`);
        on.disabled = rank.disabled =
          !!module.power_lock ||
          module.draw_mw === 0 ||
          module.empty ||
          !module.controls_verified;
        if (!module.controls_verified)
          tr.title =
            'Update the local catalogue for verified switch and priority rules.';
        on.addEventListener('change', () =>
          updateSlot(module.slot, (r) => {
            r.enabled = on.checked;
          }),
        );
        rank.addEventListener('change', () =>
          updateSlot(module.slot, (r) => {
            r.priority = Number(rank.value);
          }),
        );
        const required = el('input');
        required.type = 'checkbox';
        required.name = 'power_required';
        required.dataset.slot = module.slot;
        required.checked = (settings?.required_in || []).includes(context());
        required.setAttribute(
          'aria-label',
          `${module.slot} required in ${context()}`,
        );
        required.addEventListener('change', () =>
          updateSlot(module.slot, (r) => {
            const keys = new Set(r.required_in || []);
            required.checked ? keys.add(context()) : keys.delete(context());
            r.required_in = [...keys];
          }),
        );
        const status = el(
          'div',
          'engineering-power-module-status',
          pending
            ? 'Calculating…'
            : error
              ? 'Unknown'
              : states[after?.state] || 'Unknown',
        );
        status.append(
          el(
            'small',
            '',
            pending || error
              ? '—'
              : ['priority_shutdown', 'insufficient_power'].includes(
                    after?.state,
                  )
                ? `${fmt(after.requested_mw)} → ${fmt(after.effective_mw)}`
                : fmt(after?.requested_mw),
          ),
        );
        const source = el('details', 'engineering-power-source');
        source.append(
          el('summary', '', 'Source'),
          el(
            'p',
            '',
            `${module.module_id || 'Empty'} · ${module.reference_version}. ${module.draw_basis}: ${fmt(module.draw_mw)}. ${module.deployment_basis}. ${priorityBasis(module)}.${module.power_lock ? ` Locked priority ${module.power_lock}; cannot switch off.` : ''}${module.new_fit ? ' New fit: starts enabled at priority 1.' : ''}`,
          ),
        );
        tr.append(
          name,
          observed,
          field('On', on),
          field('Priority', rank),
          field('Required here', required),
          status,
          source,
        );
        section.append(tr);
      });
      assignments.append(section);
    }
    if (active?.slot && active.name)
      root
        .querySelector(
          `[name="${active.name}"][data-slot="${CSS.escape(active.slot)}"]`,
        )
        ?.focus({ preventScroll: true });
  }
  return { root, render, proposalRoot: proposalBox, suggest, reset };
}
