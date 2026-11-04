// Acquisition perspective. Presents the portfolio's own shortages (summed per
// material by the backend, never re-allocated here) and any read-only trade
// proposals computed from reference-pack rules. It stores nothing itself: a
// recorded plan goes through the existing acquisition-plan contract.
import { materialKey } from '../view-models/engineering-blueprints.js';
import { createActivitySummary, createStrategy } from './material-intelligence.js';
import { intelligenceFor, materialIntel } from '../view-models/material-intelligence.js';

const node = (tag, cls = '', text) => {
  const element = document.createElement(tag);
  element.className = cls;
  if (text != null) element.textContent = String(text);
  return element;
};
const known = Number.isFinite;
const quantity = (value) => (known(value) ? String(value) : 'Unknown');
const priorities = { high: 'High priority', normal: 'Normal priority', unsorted: 'Unsorted priority', low: 'Low priority' };
const categories = { raw: 'Raw', manufactured: 'Manufactured', encoded: 'Encoded', unknown: 'Category not checked' };
const PLAN_STATES = {
  draft: 'Draft',
  handoff_sent_to_navigation: 'Sent to Navigation',
  route_candidates_returned: 'Route options returned',
  commander_chose_candidate: 'Route chosen',
  handoff_sent_to_operations: 'Sent to Operations',
  operations_active: 'Active',
  complete: 'Complete',
};
const action = (text, onClick, cls = 'materials-build-link') => {
  const button = node('button', cls, text);
  button.type = 'button';
  button.addEventListener('click', onClick);
  return button;
};
const facts = (entries) => {
  const list = node('dl', 'materials-requirement-values');
  entries.forEach(([term, value]) => {
    const row = node('div');
    row.append(node('dt', '', term), node('dd', '', value));
    list.append(row);
  });
  return list;
};
const VERIFICATION = {
  declared_unverified: 'The pack states no source for its rules',
  community_reported: 'The pack cites community references; not verified in game',
  independently_verified: 'The pack records independent verification; OmniCOVAS has not re-checked it',
};
const EVIDENCE_KIND = {
  official_documentation: 'Official documentation',
  observed_in_game: 'Observed in game',
  community_reference: 'Community reference',
  derived_from_observation: 'Derived from observed trades (does not verify a rule)',
  assumption: 'Assumption',
};
const TRADE_SUFFIX = {
  pack_declared_unverified: 'not verified in game',
  pack_community_reported: 'community-reported, not verified in game',
  pack_independently_verified: 'verification recorded by the pack',
};
const budgetComplete = (build) => Boolean(build.modules?.length) && !(build.unknown_inputs || []).length;

export function createMaterialAcquisition({
  progression, plans = [], buildId, state, onBuild, onInventory, onRequirements, onRecordPlan, onOpenPlans, onTrader,
  onNavigate, onAtlas,
}) {
  // GKI-05: where and how to get each short material, from the portfolio.
  const intel = intelligenceFor(progression, buildId);
  const builds = progression.builds || [];
  const acquisition = progression.acquisition;
  const selectedBuilds = buildId === 'all' ? builds : builds.filter((b) => b.build_plan_id === buildId);
  const scopeKey = buildId === 'all' ? (builds.length === 1 ? builds[0].build_plan_id : 'all') : buildId;
  const trading = acquisition?.trading || { state: 'no_rules', proposals: [], missing_for_bundled_rules: [] };
  // The built-in Material Trader (community-documented rules) plans per scope.
  const builtin = progression.material_trader?.state === 'available' ? progression.material_trader : null;
  const builtinKnown = builtin?.inventory_state === 'verified_local';
  const builtinPlan = builtinKnown ? builtin.plans?.[buildId === 'all' ? 'all' : buildId] || null : null;
  const plannedFor = (row) => (builtinPlan?.trades || []).filter((trade) => trade.for_material === row.material_id);
  const activePlans = plans.filter((plan) => plan.state !== 'archived');

  // One row per material for this scope. The backend already summed the builds,
  // so a single-build view reads that build's own entry and the shared stock once.
  const rows = (acquisition?.materials || []).flatMap((entry) => {
    const own = buildId === 'all' ? entry.builds : entry.builds.filter((b) => b.build_plan_id === buildId);
    if (!own.length) return [];
    if (buildId === 'all') return [{ ...entry, scoped: entry.builds }];
    const [only] = own;
    const unknown = !known(only.reserved) || !known(only.deficit) || !known(entry.observed);
    return [{
      ...entry,
      required: only.required,
      reserved: only.reserved,
      deficit: only.deficit,
      scoped: own,
      state: unknown ? 'unknown' : only.deficit > 0 ? 'missing' : 'covered',
    }];
  });
  const planFor = (row) => activePlans.filter((plan) => (plan.target_materials || []).some((m) => materialKey(m.material_id) === materialKey(row.material_id)
    || String(m.display_name || '').toLowerCase() === String(row.display_name || '').toLowerCase()));
  const proposalsFor = (row) => (trading.proposals || []).filter((p) => p.scope === scopeKey && p.to_material_id === row.material_id);

  const root = node('section', 'materials-acquisition');
  root.dataset.view = 'list';
  root.setAttribute('aria-label', 'Material acquisition');
  const summary = node('p', 'materials-requirements-summary');
  summary.setAttribute('role', 'status');
  summary.setAttribute('aria-live', 'polite');
  const missing = rows.filter((r) => r.state === 'missing');
  const unknownRows = rows.filter((r) => r.state === 'unknown');
  const covered = rows.filter((r) => r.state === 'covered');
  summary.textContent = !selectedBuilds.length ? 'No active saved builds to assess'
    : !rows.length ? 'No assessed material quantities'
      : `${missing.length} to collect · ${unknownRows.length} stock unknown · ${covered.length} covered`;
  root.append(summary);

  // Incomplete budgets: say so once, without inventing a quantity.
  const incomplete = selectedBuilds.filter((b) => !budgetComplete(b));
  if (incomplete.length) {
    const notice = node('details', 'materials-budget-review');
    notice.append(node('summary', '', `${incomplete.length} selected build${incomplete.length === 1 ? ' has' : 's have'} an incomplete or conditional material budget`));
    incomplete.forEach((build) => {
      const entry = node('article', 'materials-budget-entry');
      entry.append(node('strong', '', build.title));
      (build.unknown_inputs || []).forEach((note) => entry.append(node('p', 'materials-muted', note)));
      if (!build.modules?.length) entry.append(node('p', 'materials-muted', 'No assessed module targets. Open the saved build to choose engineering.'));
      entry.append(action('Open saved build', () => onBuild(build)));
      notice.append(entry);
    });
    notice.append(node('p', 'materials-muted', 'The queue below lists only costs the saved recipes record. Nothing is estimated for a missing recipe.'));
    root.append(notice);
  }

  const tradeLine = node('p', 'materials-trade-state');
  const feasibleCount = (trading.proposals || []).filter((p) => p.scope === scopeKey && p.feasible).length;
  tradeLine.dataset.tradeState = trading.state;
  tradeLine.textContent = trading.state === 'no_rules'
    ? 'Trading unavailable · no exchange rules are installed'
    : trading.state === 'inventory_unknown'
      ? 'Trading unavailable · stock is unknown'
      : feasibleCount ? `${feasibleCount} feasible single-step trade${feasibleCount === 1 ? '' : 's'} according to the installed reference pack · ${TRADE_SUFFIX[trading.rule_status] || TRADE_SUFFIX.pack_declared_unverified}`
        : 'Installed reference pack declares exchange rules · none is feasible for these shortages';
  if (builtinPlan) {
    tradeLine.dataset.tradeState = 'builtin';
    tradeLine.textContent = builtinPlan.shortage_before === 0 ? 'Material Trader · no shortage to trade for'
      : builtinPlan.trades.length ? `Material Trader · ${builtinPlan.trades.length} trade${builtinPlan.trades.length === 1 ? ' covers' : 's cover'} ${builtinPlan.resolved_by_trades} of ${builtinPlan.shortage_before} missing`
        : 'Material Trader · no spare stock can be traded for these shortages';
  }
  root.append(tradeLine);
  if (builtinPlan && trading.state === 'rules_declared') {
    // A reference pack's own exchange rules stay visible beside the built-in trader.
    const packLine = node('p', 'materials-trade-state materials-trade-state--pack', feasibleCount
      ? `Reference pack · ${feasibleCount} feasible single-step trade${feasibleCount === 1 ? '' : 's'} · ${TRADE_SUFFIX[trading.rule_status] || TRADE_SUFFIX.pack_declared_unverified}`
      : 'Reference pack declares exchange rules · none is feasible for these shortages');
    packLine.dataset.tradeState = trading.state;
    root.append(packLine);
  }

  const activities = createActivitySummary(intel, {
    onMaterial: (id) => {
      const row = rows.find((r) => r.material_id === id);
      if (row) inspect(row, true);
    },
  });
  if (activities) root.append(activities);

  const searchLabel = node('label', 'materials-control');
  const search = node('input');
  search.type = 'search'; search.name = 'acquisition_search'; search.value = state.acquisitionSearch || '';
  search.setAttribute('aria-label', 'Search acquisition'); search.placeholder = 'Material name…';
  searchLabel.append(node('span', '', 'Search acquisition'), search);
  root.append(searchLabel);

  const main = node('div', 'materials-requirements-main');
  const collection = node('div', 'materials-requirements-collection');
  collection.setAttribute('aria-label', 'Acquisition queue');
  const inspector = node('section', 'materials-requirement-inspector');
  inspector.id = 'materials-acquisition-inspector';
  inspector.setAttribute('aria-label', 'Acquisition details');
  main.append(collection, inspector);
  root.append(main);
  const selectionKey = (row) => `${scopeKey}|${row.material_id}`;
  const selections = state.acquisitionSelections ||= {};
  let visible = [];

  function ruleSetDetails() {
    const details = trading.rule_set_details || [];
    const box = node('details', 'materials-proof materials-rule-sets');
    box.append(node('summary', '', 'About these rules'));
    details.forEach((set) => {
      const entry = node('article', 'materials-rule-set');
      entry.dataset.verification = set.verification;
      entry.append(node('strong', '', set.id ? `${set.id} ${set.version || ''}`.trim() : set.label));
      entry.append(node('p', 'materials-muted', `Installed pack ${set.label}${set.game_version ? ` · game version ${set.game_version}` : ''}`));
      entry.append(node('p', 'materials-muted', VERIFICATION[set.verification] || VERIFICATION.declared_unverified));
      if (set.completeness) {
        entry.append(node('p', 'materials-muted', set.completeness.state === 'complete'
          ? `Declares itself complete for: ${set.completeness.covers.join(', ')}`
          : `Declares itself partial${set.completeness.covers.length ? ` (covers ${set.completeness.covers.join(', ')})` : ''}: an exchange it does not list is unknown, not forbidden`));
      } else {
        entry.append(node('p', 'materials-muted', 'Completeness is not stated: an exchange it does not list is unknown, not forbidden.'));
      }
      (set.evidence || []).forEach((item) => entry.append(node('p', 'materials-muted', `${EVIDENCE_KIND[item.kind] || item.kind}: ${item.name}`)));
      (set.limitations || []).forEach((note) => entry.append(node('p', 'materials-muted', `Limit: ${note}`)));
      box.append(entry);
    });
    box.append(node('p', 'materials-muted', builtin
      ? 'These rules come only from the pack you installed. The built-in Material Trader keeps its own rules, described in the Trader perspective.'
      : 'OmniCOVAS ships no exchange table. These rules come only from the pack you installed.'));
    return box;
  }

  function tradeSection(row) {
    const section = node('div', 'materials-trade');
    section.append(node('h4', '', 'Trading'));
    if (builtinPlan) {
      const block = node('div', 'materials-trader-advice');
      const trades = plannedFor(row);
      const left = builtinPlan.remaining.find((r) => r.material_id === row.material_id);
      if (row.state !== 'missing') block.append(node('p', 'materials-muted', 'No shortage to trade for.'));
      else if (!trades.length) block.append(node('p', 'materials-muted', 'No spare stock can be traded for this material at a Material Trader.'));
      trades.forEach((trade) => block.append(node('p', 'materials-trader-line', `Give ${trade.pay_total} ${trade.give_name} → receive ${trade.receive_total} ${trade.take_name} (${trade.why})`)));
      // Only planned trades have an "after"; with none, the line above says so.
      if (row.state === 'missing' && trades.length) {
        block.append(node('p', left ? 'materials-muted' : 'materials-requirement-outcome', left
          ? `After these trades, still collect ${left.collect}.`
          : 'These trades cover the shortage.'));
      }
      if (onTrader) block.append(action('Open in Material Trader', () => onTrader(row.material_id)));
      section.append(block);
      if (trading.state !== 'rules_declared') return section;
      section.append(node('h4', '', 'Installed reference pack'));
    }
    if (trading.state === 'inventory_unknown') {
      section.append(node('p', 'materials-requirement-warning', 'Your stock is not known, so OmniCOVAS cannot say what you hold or whether any trade is possible. Trading needs a complete Journal Materials baseline.'));
      return section;
    }
    if (trading.state === 'no_rules') {
      section.append(node('p', 'materials-muted', 'Trade feasibility is unavailable. OmniCOVAS has no verified Material Trader exchange rules, and no installed reference pack declares any. No exchange rate is assumed.'));
      const needs = node('details', 'materials-proof');
      needs.append(node('summary', '', 'What a verified rule set still needs'));
      (trading.missing_for_bundled_rules || []).forEach((item) => needs.append(node('p', 'materials-muted', item)));
      section.append(needs);
      return section;
    }
    const proposals = proposalsFor(row);
    if (trading.state === 'rules_declared' && (trading.rule_set_details || []).length) section.append(ruleSetDetails());
    if (row.state !== 'missing') {
      section.append(node('p', 'materials-muted', 'No shortage to trade for.'));
      return section;
    }
    if (!proposals.length) {
      section.append(node('p', 'materials-muted', row.trade?.state === 'none_declared'
        ? 'No installed rule declares an exchange that produces this material.'
        : 'No declared exchange applies to this shortage.'));
      return section;
    }
    proposals.forEach((p) => {
      const card = node('article', 'materials-trade-card');
      card.dataset.feasible = String(p.feasible);
      card.dataset.outcome = p.outcome;
      card.dataset.ruleStatus = p.rule_status || 'pack_declared_unverified';
      card.append(node('p', 'materials-trade-source', `According to installed reference pack ${(p.rule_sets || []).join(', ')}`));
      card.append(node('strong', '', p.feasible
        ? `Pay ${p.pay_total} ${p.from_display_name} → receive ${p.receive_total} ${p.to_display_name}`
        : `${p.from_display_name} → ${p.to_display_name} (${p.pay}:${p.receive})`));
      if (p.feasible) {
        card.append(node('p', 'materials-muted', `${p.lots} exchange${p.lots === 1 ? '' : 's'} at ${p.pay} for ${p.receive}, using only stock no build has reserved (${p.source_unreserved_before} → ${p.source_unreserved_after} ${p.from_display_name}).`));
        card.append(node('p', p.outcome === 'resolves_shortage' ? 'materials-requirement-outcome' : 'materials-muted',
          p.outcome === 'resolves_shortage' ? `If the rule holds, this would resolve the shortage: ${p.shortage_before} missing → 0.`
            : p.outcome === 'reduces_shortage' ? `If the rule holds, this would reduce the shortage from ${p.shortage_before} to ${p.shortage_after}. Not enough to resolve it.`
              : 'Would not reduce this shortage: builds with higher priority receive the units first.'));
      } else {
        card.append(node('p', 'materials-requirement-warning', p.reason === 'category_conflict'
          ? 'Not feasible: the rule’s declared category does not match the observed category of its materials.'
          : `Not feasible: each exchange needs ${p.pay} unreserved ${p.from_display_name}; ${p.source_unreserved_before} ${p.source_unreserved_before === 1 ? 'is' : 'are'} unreserved (${p.source_observed} observed${p.source_observed > p.source_unreserved_before ? ', the rest reserved by builds' : ''}). Covering the shortage needs ${p.pay_needed}.`));
      }
      p.builds.filter((b) => b.deficit_before !== b.deficit_after).forEach((b) => card.append(node('p', 'materials-muted', `${b.title}: ${b.deficit_before} missing → ${b.deficit_after}.`)));
      card.append(node('p', 'materials-muted', `${p.basis} Check the trader in game before relying on it. This is a suggestion only: not a Journal transaction, and it changes no stock.`));
      section.append(card);
    });
    return section;
  }

  function planSection(row) {
    const section = node('div', 'materials-plans');
    section.append(node('h4', '', 'Acquisition plans'));
    const existing = planFor(row);
    if (!existing.length) section.append(node('p', 'materials-muted', 'No acquisition plan records this material yet.'));
    existing.forEach((plan) => {
      const entry = node('article', 'materials-plan-entry');
      const target = (plan.target_materials || []).find((m) => materialKey(m.material_id) === materialKey(row.material_id)) || {};
      entry.append(node('strong', '', plan.title),
        node('p', 'materials-muted', `${PLAN_STATES[plan.state] || plan.state}${known(target.quantity_needed) ? ` · ${target.quantity_needed} needed` : ''}`));
      if (plan.notes) entry.append(node('p', 'materials-muted', plan.notes));
      section.append(entry);
    });
    const form = node('form', 'materials-plan-form');
    const noteLabel = node('label', 'materials-control');
    const note = node('input');
    note.name = 'acquisition_note'; note.maxLength = 500; note.setAttribute('aria-label', 'Plan note');
    note.placeholder = 'Optional note, for example where you will look';
    noteLabel.append(node('span', '', 'Note'), note);
    const scopeTitle = buildId === 'all' ? 'all builds' : selectedBuilds[0]?.title || 'build';
    const submit = node('button', 'materials-plan-submit', existing.length ? 'Record another plan' : 'Record acquisition plan');
    submit.type = 'submit';
    form.append(noteLabel, submit);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const material = { material_id: row.material_id, display_name: row.display_name, source: 'materials_acquisition' };
      if (known(row.deficit) && row.deficit > 0) material.quantity_needed = row.deficit;
      const payload = {
        title: `Collect ${row.display_name} for ${scopeTitle}`.slice(0, 128),
        linked_build_plan_ids: row.scoped.map((b) => b.build_plan_id),
        target_materials: [material],
        state: 'draft',
      };
      if (note.value.trim()) payload.notes = note.value.trim();
      onRecordPlan(payload);
    });
    section.append(form, action('Open acquisition plans', () => onOpenPlans()));
    return section;
  }

  function inspect(row, focus = false) {
    selections[scopeKey] = row ? selectionKey(row) : null;
    collection.querySelectorAll('button[data-acquisition-key]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.acquisitionKey === selections[scopeKey])));
    inspector.replaceChildren();
    if (!row) {
      inspector.append(node('h3', '', 'Acquisition details'), node('p', 'materials-muted', 'Select a material to see what is needed, what stock remains and any trade options.'));
      return;
    }
    inspector.append(action('Back to acquisition', () => {
      root.dataset.view = 'list';
      ([...collection.querySelectorAll('button')].find((b) => b.dataset.acquisitionKey === selectionKey(row)) || search).focus();
    }, 'materials-requirements-back'));
    inspector.append(node('p', 'materials-eyebrow', `${categories[row.category] || categories.unknown} · ${buildId === 'all' ? 'All active builds' : selectedBuilds[0]?.title}`));
    const title = node('h3', '', row.display_name);
    title.tabIndex = -1;
    inspector.append(title);
    inspector.append(facts([
      [buildId === 'all' ? 'Required by builds' : 'Required', quantity(row.required)],
      ['Held in inventory', quantity(row.observed)],
      ['Reserved for builds', quantity(row.reserved)],
      ['Still to collect', quantity(row.deficit)],
      ['Left after all builds', quantity(row.remaining)],
    ]));
    if (row.state === 'unknown') inspector.append(node('p', 'materials-requirement-warning', 'Stock is unknown, so no shortage or surplus is claimed. Missing stock is not treated as zero.'));
    else if (row.state === 'covered') inspector.append(node('p', 'materials-requirement-outcome', 'Covered by stock allocated to this requirement.'));
    else inspector.append(node('p', 'materials-requirement-outcome', `${row.deficit} more to collect${row.remaining > 0 ? '' : '; nothing is left over'}.`));
    const guidance = materialIntel(intel, row.material_id);
    if (guidance) inspector.append(createStrategy(guidance, { onNavigate, onAtlas }, intel.ranking));
    // GKI-05: the trades sit right under the strategy, so trading and collecting
    // can be compared without scrolling past the builds.
    inspector.append(tradeSection(row));
    inspector.append(node('p', 'materials-muted', 'Held stock is one shared pool, reported once. Reservations follow build priority and are never counted twice.'));
    inspector.append(node('p', 'materials-provenance', 'Sources: held stock from your Journal · required, reserved and missing from your saved builds · acquisition plans are your own records · trade rules, if any, from a reference pack you installed.'));

    inspector.append(node('h4', '', 'Needed by'));
    row.scoped.forEach((entry) => {
      const build = builds.find((b) => b.build_plan_id === entry.build_plan_id);
      const line = node('div', 'materials-planned-upgrade');
      line.append(node('strong', '', entry.title),
        node('span', '', `${priorities[entry.priority] || 'Priority not set'} · needs ${quantity(entry.required)} · reserved ${quantity(entry.reserved)} · missing ${quantity(entry.deficit)}`));
      if (build) line.append(action('Open saved build', () => onBuild(build)));
      inspector.append(line);
    });

    inspector.append(planSection(row));
    const links = node('div', 'materials-links');
    links.append(action('See in Requirements', () => onRequirements(row.material_id)), action('View inventory observation', () => onInventory(row.material_id)));
    inspector.append(links);
    if (focus && window.matchMedia?.('(max-width: 760px)').matches) {
      root.dataset.view = 'detail'; title.focus({ preventScroll: true }); inspector.scrollIntoView({ block: 'start', behavior: 'instant' });
    }
  }

  function rowButton(row) {
    const button = action('', () => inspect(row, true), 'materials-requirement-row');
    button.dataset.acquisitionKey = selectionKey(row);
    button.dataset.materialId = row.material_id;
    button.setAttribute('aria-controls', inspector.id);
    const identity = node('span', 'materials-row-identity');
    identity.append(node('strong', '', row.display_name),
      node('span', 'materials-row-note', row.state === 'unknown'
        ? `Required ${quantity(row.required)} · stock unknown`
        : `Required ${quantity(row.required)} · held ${quantity(row.observed)} · reserved ${quantity(row.reserved)}`));
    const side = node('span', 'materials-acquisition-side');
    side.append(node('span', 'materials-requirement-amount', row.state === 'missing' ? `${row.deficit} to collect` : row.state === 'covered' ? 'Covered' : 'Unknown'));
    const tags = node('span', 'materials-acquisition-tags');
    if (planFor(row).length) tags.append(node('span', 'materials-tag', 'Plan recorded'));
    if (row.state === 'missing' && plannedFor(row).length) tags.append(node('span', 'materials-tag materials-tag--trade', 'Trade planned'));
    if (row.state === 'missing' && proposalsFor(row).some((p) => p.feasible)) tags.append(node('span', 'materials-tag materials-tag--trade', 'Pack trade'));
    if (tags.children.length) side.append(tags);
    button.append(identity, side);
    const item = node('li');
    item.append(button);
    return item;
  }

  function renderList() {
    const needle = search.value.trim().toLocaleLowerCase();
    visible = rows.filter((r) => String(r.display_name).toLocaleLowerCase().includes(needle));
    collection.replaceChildren();
    if (!builds.length) {
      collection.append(node('h3', '', 'Begin a ship engineering plan'),
        node('p', 'materials-empty', 'Choose engineering in Outfitting and save a variant. Return here for what it still needs to collect; your Inventory remains browsable.'),
        action('Open Outfitting', () => onBuild(null)));
    } else if (!rows.length) {
      collection.append(node('p', 'materials-empty', 'These builds record no material quantities yet. Open a saved build to choose engineering. No shortage is inferred from an empty list.'));
    } else if (!visible.length) {
      collection.append(node('p', 'materials-empty', 'No matching material. Clear the search to see the whole queue.'));
    }
    const section = (rowsOf, title, open = true) => {
      if (!rowsOf.length) return;
      const wrap = open ? node('div', 'materials-acquisition-group') : node('details', 'materials-acquisition-group');
      if (open) wrap.append(node('h3', 'materials-category materials-group-title', `${title} · ${rowsOf.length}`));
      else wrap.append(node('summary', 'materials-category', `${title} · ${rowsOf.length}`));
      for (const key of ['raw', 'manufactured', 'encoded', 'unknown']) {
        const group = rowsOf.filter((r) => (categories[r.category] ? r.category : 'unknown') === key)
          .sort((a, b) => (b.deficit || 0) - (a.deficit || 0) || String(a.display_name).localeCompare(b.display_name));
        if (!group.length) continue;
        wrap.append(node('h4', 'materials-acquisition-category', categories[key]));
        const list = node('ul', 'materials-list');
        list.setAttribute('aria-label', `${title}: ${categories[key]}`);
        group.forEach((r) => list.append(rowButton(r)));
        wrap.append(list);
      }
      collection.append(wrap);
    };
    section(visible.filter((r) => r.state === 'missing'), 'Still to collect');
    section(visible.filter((r) => r.state === 'unknown'), 'Stock unknown');
    section(visible.filter((r) => r.state === 'covered'), 'Covered by stock', false);
    const coveredGroup = collection.querySelector('details.materials-acquisition-group');
    if (coveredGroup && (!missing.length || needle)) coveredGroup.open = true;
    if (rows.length && !missing.length && !needle) {
      collection.prepend(node('p', 'materials-requirement-outcome', unknownRows.length ? 'No confirmed shortage. Some stock is unknown.' : 'Nothing to collect. Every assessed requirement is covered by its allocation.'));
    }
    // A one-shot request to show a material (GKI-05: the inventory guide, or a
    // return from Navigation or the Atlas), resolved against this scope's rows.
    const focus = state.acquisitionFocus && visible.find((r) => r.material_id === state.acquisitionFocus);
    if (focus) selections[scopeKey] = selectionKey(focus);
    state.acquisitionFocus = null;
    const buttons = [...collection.querySelectorAll('button[data-acquisition-key]')];
    const chosen = visible.find((r) => selectionKey(r) === selections[scopeKey])
      || visible.find((r) => selectionKey(r) === buttons[0]?.dataset.acquisitionKey);
    inspect(chosen);
  }
  collection.addEventListener('keydown', (event) => {
    if (!event.target.matches('button[data-acquisition-key]') || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    const buttons = [...collection.querySelectorAll('button[data-acquisition-key]')];
    const index = buttons.indexOf(event.target);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : Math.max(0, Math.min(buttons.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)));
    event.preventDefault();
    buttons[next]?.focus();
  });
  search.addEventListener('input', () => { state.acquisitionSearch = search.value; renderList(); });
  if (!acquisition) {
    collection.append(node('p', 'materials-empty', 'Acquisition data is unavailable from Engineering right now. Requirements and Inventory still show your stock and shortages.'));
    inspector.append(node('h3', '', 'Acquisition details'));
  } else {
    renderList();
  }
  return root;
}
