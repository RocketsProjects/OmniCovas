// Read-only presentation of portfolio allocations. No cost or reservation math.
import { materialKey } from '../view-models/engineering-blueprints.js';
const node = (tag, cls = '', text) => {
  const element = document.createElement(tag);
  element.className = cls;
  if (text != null) element.textContent = String(text);
  return element;
};
const known = Number.isFinite;
const quantity = (value) => known(value) ? String(value) : 'Unknown';
const priorities = { high: 'High priority', normal: 'Normal priority', unsorted: 'Unsorted priority', low: 'Low priority' };
const key = (value) => String(value || '').toLowerCase();
const rowKey = (row) => JSON.stringify([row.build.build_plan_id, row.material_id || null]);
const status = (row) => row.budgetOnly ? budgetComplete(row.build) ? 'covered' : 'unknown'
  : !known(row.required) || !known(row.reserved) || !known(row.deficit) ? 'unknown' : row.deficit > 0 ? 'missing' : 'covered';
const budgetComplete = (build) => Boolean(build.modules?.length) && !(build.unknown_inputs || []).length;
const budgetLabel = (build) => budgetComplete(build) ? 'Recorded material budget complete' : 'Material budget incomplete or conditional';
const action = (text, onClick, cls = 'materials-build-link') => {
  const button = node('button', cls, text);
  button.type = 'button'; button.addEventListener('click', onClick);
  return button;
};
const facts = (entries) => {
  const list = node('dl', 'materials-requirement-values');
  entries.forEach(([term, value]) => {
    const row = node('div'); row.append(node('dt', '', term), node('dd', '', value)); list.append(row);
  });
  return list;
};

// Recipe membership supplies a relationship, never a per-module allocation.
// Use the matching catalogue version, or the existing observed-recipe service.
function recipeLinks(build, materialId, progression) {
  const reference = progression.reference_catalog || {};
  const matchingPack = reference.state === 'commander_supplied_validated'
    && build.catalog_version === `${reference.catalog_id}@${reference.version}`;
  const observedScope = build.catalog_version === progression.catalog_version;
  return (build.modules || []).filter((module) => {
    if (!module.blueprint_id) return false;
    const blueprint = matchingPack ? (reference.blueprints || []).find((bp) => key(bp.id) === key(module.blueprint_id)) : null;
    const bills = blueprint ? Object.entries(blueprint.grades || {}).filter(([grade]) => Number(grade) <= module.target_grade).map(([, bill]) => bill)
      : observedScope ? (progression.observed_recipes || []).filter((r) => key(r.blueprint_id) === key(module.blueprint_id) && r.grade <= module.target_grade).map((r) => r.materials) : [];
    const effect = blueprint?.experimentals?.find((e) => e.id === module.experimental_effect);
    if (effect?.materials) bills.push(effect.materials);
    return bills.some((bill) => (bill || []).some((m) => materialKey(m.material_id) === materialKey(materialId)));
  });
}

export function createMaterialRequirements({ progression, buildId, state, onInventory, onBuild, onAcquisition, initialMaterial }) {
  const builds = progression.builds || [];
  const selected = buildId === 'all' ? builds : builds.filter((b) => b.build_plan_id === buildId);
  const inventoryRows = new Map((progression.inventory?.materials || []).map((r) => [r.material_id, r]));
  const allAllocations = builds.flatMap((build) => (build.materials || []).map((row) => ({ ...row, build })));
  const rows = selected.flatMap((build) => {
    const requirements = (build.materials || []).map((row) => ({ ...row, build }));
    if (!requirements.length) requirements.push({ build, budgetOnly: true });
    return requirements;
  });
  const root = node('section', 'materials-requirements');
  root.dataset.view = 'list';
  root.setAttribute('aria-label', 'Build material requirements');
  const summary = node('p', 'materials-requirements-summary');
  summary.setAttribute('role', 'status');
  summary.setAttribute('aria-live', 'polite');
  const materialRows = rows.filter((r) => !r.budgetOnly);
  const counts = ['missing', 'unknown', 'covered'].map((s) => `${materialRows.filter((r) => status(r) === s).length} ${s === 'unknown' ? 'stock unknown' : s === 'missing' ? 'confirmed missing' : s}`);
  summary.textContent = `${counts.join(' · ')} material requirements`;
  if (!materialRows.length) summary.textContent = 'No assessed material quantities';
  if (!selected.length) summary.textContent = 'No active saved builds to assess';
  const budgets = node('details', 'materials-budget-review');
  const incomplete = selected.filter((b) => !budgetComplete(b)).length;
  budgets.append(node('summary', '', `${selected.length - incomplete} complete recorded build budgets · ${incomplete} incomplete or conditional`));
  selected.forEach((build) => {
    const entry = node('article', 'materials-budget-entry');
    entry.append(node('strong', '', build.title), node('p', 'materials-muted', budgetLabel(build)));
    (build.unknown_inputs || []).forEach((note) => entry.append(node('p', 'materials-muted', note)));
    if (!build.modules?.length) entry.append(node('p', 'materials-muted', 'No assessed module targets. Open the saved build to choose engineering.'));
    entry.append(action('Open saved build', () => onBuild(build)));
    budgets.append(entry);
  });
  const searchLabel = node('label', 'materials-control');
  const search = node('input');
  search.type = 'search'; search.name = 'requirement_search'; search.value = state.requirementSearch || '';
  search.setAttribute('aria-label', 'Search requirements'); search.placeholder = 'Material or build name…';
  searchLabel.append(node('span', '', 'Search requirements'), search);
  const scope = node('p', 'materials-muted', 'Counts refer to requirements per build. Stock is one shared pool; material coverage does not verify engineer access, rank or the ability to craft.');
  root.append(summary, budgets, scope, searchLabel);
  const main = node('div', 'materials-requirements-main');
  const collection = node('div', 'materials-requirements-collection');
  collection.setAttribute('aria-label', 'Requirements list');
  const inspector = node('section', 'materials-requirement-inspector');
  inspector.id = 'materials-requirement-inspector';
  inspector.setAttribute('aria-label', 'Requirement details');
  main.append(collection, inspector); root.append(main);
  let visible = [];
  const selectedByBuild = state.requirementSelections ||= {};

  function inspect(row, focus = false) {
    selectedByBuild[buildId] = row ? rowKey(row) : null;
    if (row?.material_id) state.requirementMaterial = row.material_id;
    collection.querySelectorAll('button[data-requirement-key]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.requirementKey === selectedByBuild[buildId])));
    inspector.replaceChildren();
    if (!row) { inspector.append(node('h3', '', 'Requirement details'), node('p', 'materials-muted', 'Select a requirement to inspect its allocation and planned build.')); return; }
    inspector.append(action('Back to requirements', () => {
      root.dataset.view = 'list';
      ([...collection.querySelectorAll('button')].find((b) => b.dataset.requirementKey === rowKey(row)) || search).focus();
    }, 'materials-requirements-back'));
    inspector.append(node('p', 'materials-eyebrow', `${row.build.title} · ${priorities[row.build.priority] || 'Priority not set'}`));
    const title = node('h3', '', row.budgetOnly ? 'Build material budget' : row.display_name || row.material_id);
    title.tabIndex = -1; inspector.append(title);
    inspector.append(node('p', 'materials-budget-state', budgetLabel(row.build)));
    if (row.budgetOnly) {
      inspector.append(node('p', 'materials-muted', !budgetComplete(row.build)
        ? 'A complete remaining material budget is not available. No shortage or affordability is inferred from an empty requirement list.'
        : 'The portfolio reports no remaining material requirement for this build. This does not establish engineer access.'));
    } else {
      const observed = inventoryRows.get(row.material_id);
      // First occurrence is before this material's first portfolio allocation.
      const first = allAllocations.find((a) => a.material_id === row.material_id);
      const owned = observed ? observed.count : first?.held_before_reservation;
      inspector.append(facts([['Required', quantity(row.required)], ['Held in inventory', quantity(owned)],
        ['Before this allocation', quantity(row.held_before_reservation)], ['Reserved for this build', quantity(row.reserved)], ['Missing', quantity(row.deficit)]]));
      inspector.append(node('p', 'materials-muted', 'Held is the observed pool; “before this allocation” is the remaining stock after earlier builds. Reserved units are already included in this build’s coverage.'));
      if (status(row) === 'unknown') inspector.append(node('p', 'materials-requirement-warning', 'Material coverage is unknown. Missing stock is not treated as zero.'));
      else inspector.append(node('p', 'materials-requirement-outcome', row.deficit > 0 ? `${row.deficit} more needed for this assessed requirement.` : 'This assessed requirement is covered by its allocation.'));
      // GKI-05: straight to the acquisition strategy, for the same build.
      if (onAcquisition && (row.deficit > 0 || status(row) === 'unknown')) inspector.append(action('How to get it', () => onAcquisition(row.material_id)));
      const index = builds.indexOf(row.build);
      const earlier = allAllocations.filter((a) => builds.indexOf(a.build) < index && a.material_id === row.material_id && a.reserved > 0);
      if (earlier.length) {
        inspector.append(node('h4', '', 'Earlier allocations'));
        earlier.forEach((a) => inspector.append(node('p', 'materials-muted', `${a.build.title} (${priorities[a.build.priority] || 'priority not set'}) already has ${a.reserved} reserved before this build.`)));
      }
      const allocationOrder = node('details', 'materials-proof');
      allocationOrder.append(node('summary', '', 'Shared allocation order'));
      allAllocations.filter((a) => a.material_id === row.material_id).forEach((a) => {
        allocationOrder.append(node('p', 'materials-muted', `${a.build.title} · ${priorities[a.build.priority] || 'priority not set'} · ${quantity(a.reserved)} reserved · ${quantity(a.deficit)} missing`));
      });
      allocationOrder.append(node('p', 'materials-muted', progression.allocation_policy || 'The portfolio allocates one pool in priority order, then creation order.'));
      inspector.append(allocationOrder, action('View inventory observation', () => onInventory(row.material_id)));
    }
    if (row.build.unknown_inputs?.length) {
      const notes = node('div', 'materials-requirement-warning');
      notes.append(node('strong', '', 'Budget limits'));
      row.build.unknown_inputs.forEach((note) => notes.append(node('p', '', note)));
      inspector.append(notes);
    }
    const modules = (row.build.modules || []).filter((m) => m.blueprint_id);
    const related = row.budgetOnly ? [] : recipeLinks(row.build, row.material_id, progression);
    inspector.append(node('h4', '', related.length ? 'Recipe links to planned upgrades' : 'Planned upgrades in this build'));
    inspector.append(node('p', 'materials-muted', related.length
      ? 'Recorded recipes for these upgrades include this material. Allocations and totals are for the whole build, not individual modules.'
      : 'The portfolio supplies a combined build budget, without a material allocation for each upgrade.'));
    const reference = progression.reference_catalog || {};
    const editable = (progression.saved_configurations || []).some((v) => v.build_plan_id === row.build.build_plan_id);
    if (!editable) inspector.append(node('p', 'materials-muted', 'This saved plan has no editable variant. Open its record under Outfitting’s saved plans.'));
    (related.length ? related : modules).forEach((module) => {
      const blueprint = (reference.blueprints || []).find((bp) => key(bp.id) === key(module.blueprint_id));
      const observed = (progression.observed_recipes || []).find((r) => key(r.blueprint_id) === key(module.blueprint_id));
      const entry = node('div', 'materials-planned-upgrade');
      entry.append(node('strong', '', module.module_label || module.slot),
        node('span', '', `${blueprint?.name || observed?.blueprint_label || module.blueprint_id} · Grade ${module.target_grade ?? 'unknown'}`));
      if (editable) entry.append(action('Open upgrade in Outfitting', () => onBuild(row.build, module.slot)));
      inspector.append(entry);
    });
    if (!modules.length) inspector.append(node('p', 'materials-muted', 'No assessed engineering targets. Open the build to begin a plan.'));
    inspector.append(action('Open saved build', () => onBuild(row.build)));
    if (focus && window.matchMedia?.('(max-width: 760px)').matches) {
      root.dataset.view = 'detail'; title.focus({ preventScroll: true }); inspector.scrollIntoView({ block: 'start', behavior: 'instant' });
    }
  }

  function renderList() {
    visible = rows.filter((row) => `${row.display_name || row.material_id || ''} ${row.build.title}`.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase()));
    collection.replaceChildren();
    if (!builds.length) {
      collection.append(node('h3', '', 'Begin a ship engineering plan'), node('p', 'materials-empty', 'Choose engineering in Outfitting and save a variant. Return here to see its requirements; your Inventory remains browsable.'), action('Open Outfitting', () => onBuild(null)));
    } else if (!visible.length) collection.append(node('p', 'materials-empty', 'No matching requirements. Clear the search to see this build’s assessed needs.'));
    for (const [group, title] of [['missing', 'Missing materials'], ['unknown', 'Unknown or unassessed'], ['covered', 'Covered requirements']]) {
      const groupRows = visible.filter((r) => status(r) === group).sort((a, b) => (b.deficit || 0) - (a.deficit || 0) || String(a.display_name || '').localeCompare(b.display_name || ''));
      if (!groupRows.length) continue;
      collection.append(node('h3', 'materials-category', `${title} · ${groupRows.length}`));
      const list = node('ul', 'materials-list'); list.setAttribute('aria-label', title);
      groupRows.forEach((row) => {
        const button = action('', () => inspect(row, true), 'materials-requirement-row');
        button.dataset.requirementKey = rowKey(row); button.dataset.buildId = row.build.build_plan_id;
        if (row.material_id) button.dataset.materialId = row.material_id;
        button.setAttribute('aria-controls', inspector.id);
        const identity = node('span', 'materials-row-identity');
        identity.append(node('strong', '', row.budgetOnly ? row.build.title : row.display_name || row.material_id),
          node('span', 'materials-row-note', row.budgetOnly ? budgetComplete(row.build) ? 'No remaining material requirement reported' : 'Material budget needs review' : `${row.build.title} · ${quantity(row.reserved)} of ${quantity(row.required)} reserved`));
        const amount = node('span', 'materials-requirement-amount', row.budgetOnly ? budgetComplete(row.build) ? 'None reported' : 'Review' : group === 'unknown' ? 'Unknown' : group === 'covered' ? 'Covered' : `${row.deficit} missing`);
        button.append(identity, amount);
        const item = node('li'); item.append(button); list.append(item);
      });
      collection.append(list);
    }
    // Default to the first actionable row in the actual rendered order.
    const buttons = [...collection.querySelectorAll('button[data-requirement-key]')];
    const previous = selectedByBuild[buildId];
    const chosen = visible.find((r) => rowKey(r) === previous)
      || (initialMaterial && visible.find((r) => r.material_id === initialMaterial))
      || visible.find((r) => rowKey(r) === buttons[0]?.dataset.requirementKey);
    inspect(chosen);
  }
  collection.addEventListener('keydown', (event) => {
    if (!event.target.matches('button[data-requirement-key]') || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    const buttons = [...collection.querySelectorAll('button[data-requirement-key]')];
    const index = buttons.indexOf(event.target);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : Math.max(0, Math.min(buttons.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1)));
    event.preventDefault(); buttons[next]?.focus();
  });
  search.addEventListener('input', () => { state.requirementSearch = search.value; renderList(); });
  renderList();
  return root;
}
