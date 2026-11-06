// Pure UI projections over existing source owners. No HTTP, timers, polling,
// mode selection, provider access or independent game-state store.
import { widgetRegistry } from '../components/widget-registry.js';

export const subjectKey = subject => JSON.stringify([subject?.commander_profile_key ?? null, subject?.ship_id ?? null]);
export function subjectFromState(state) {
  return { commander_profile_key: state?.commander_name ?? null, ship_id: state?.current_ship_id ?? null };
}
export const objectiveKey = record => JSON.stringify([record?.objective_id ?? null, record?.target_commodity ?? null, record?.target_quantity ?? null, record?.state ?? null]);
export function miningWorkflowForSnapshot(snapshot = {}) {
  const subject=snapshot.subject || subjectFromState(snapshot.publicState);
  return subject.commander_profile_key && subject.ship_id != null
    && snapshot.factSubject && subjectKey(snapshot.factSubject) === subjectKey(subject)
    && snapshot.workflowSubject && subjectKey(snapshot.workflowSubject) === subjectKey(subject)
    && snapshot.workflowTarget === objectiveKey(snapshot.objective)
    && snapshot.workflowOperation === 'mining' ? snapshot.miningWorkflow : null;
}
const quantity = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
const count = value => Number.isInteger(quantity(value)) ? value : null;
const amount = value => value.toLocaleString(undefined, { maximumFractionDigits: 1 });

export function selectWidget(id, snapshot = {}) {
  const descriptor = widgetRegistry.get(id);
  if (!descriptor) return null;
  const subject = snapshot.subject || subjectFromState(snapshot.publicState);
  const cargo = snapshot.localContextRaw?.cargo_hold;
  const observedAt = cargo?.event_timestamp || null;
  const identityOK = snapshot.factSubject && subjectKey(snapshot.factSubject) === subjectKey(subject);
  const knownCommander = Boolean(subject.commander_profile_key);
  const shipKnown = subject.ship_id !== null && subject.ship_id !== undefined;
  const permittedSource = !['not_loaded','disabled','unsupported','unknown','error','malformed'].includes(cargo?.freshness);
  const sourceOK = permittedSource && identityOK && knownCommander && shipKnown && cargo?.vessel === 'Ship'
    && observedAt && observedAt !== snapshot.blockedCargoTimestamp;
  const sourceState = !snapshot.connected ? 'stale' : cargo?.freshness === 'stale' || snapshot.sessionState === 'Last known' ? 'stale' : 'valid';
  const payload = {
    widget_id: descriptor.id, schema_version: 1, subject: { ...subject },
    observation: { truth: descriptor.truth, observed_at: observedAt, context_at: null, source_scope: 'ship',
      source_identity: descriptor.source, coverage: 'unknown', source_state: sourceOK ? sourceState : 'absent' },
    display: { headline: 'Not observed yet', unit: null, label: descriptor.title, secondary: 'Open for details', facts: [], state: 'unknown', emphasis: 'neutral' },
    interaction: { default: 'open_detail', detail_ref: descriptor.id, protected: false },
    visual: { type: descriptor.type, available_sizes: descriptor.allowedSizes, preferred_size: descriptor.preferredSize },
    detail: { lines: [], inventory: [], progress: null },
  };
  const d = payload.display;
  const ready = (headline, secondary, zero = false, staleOverride) => {
    const stale = staleOverride ?? (descriptor.truth !== 'plan' && sourceState === 'stale');
    Object.assign(d, { headline, secondary, state: stale ? 'stale' : zero ? 'zero' : 'ready' });
    if (stale) d.secondary = `${snapshot.connected ? 'Last known' : 'Disconnected · last known'}${secondary ? ` · ${secondary}` : ''}`;
  };
  const complete = sourceOK && cargo.inventory_complete === true && Array.isArray(cargo.inventory);
  if (descriptor.id === 'ship.cargo') {
    const used = sourceOK ? count(cargo.total_count) : null;
    const capacity = sourceOK ? count(cargo.capacity) : null;
    payload.observation.coverage = complete ? 'complete' : sourceOK ? 'partial' : 'unknown';
    if (used !== null) {
      ready(`${amount(used)}${capacity !== null ? ` / ${amount(capacity)}` : ''} t`, capacity !== null ? `${amount(Math.max(0, capacity-used))} t free${used > capacity ? ' · over reported capacity' : ''}` : 'Capacity not observed', used === 0);
      if (capacity > 0) payload.detail.progress = { value: Math.min(100, used / capacity * 100), text: `${used} of ${capacity} t` };
    }
    payload.detail.inventory = complete ? cargo.inventory.filter(item => item && typeof item.name === 'string' && count(item.count) !== null).map(item => ({ name: item.name_localised || item.name, count: item.count, mission: item.mission_id != null, stolen: Boolean(item.stolen) })) : [];
    payload.detail.lines.push(complete ? 'Complete ship manifest at the recorded observation.' : 'A complete ship manifest is not available. A total alone does not establish its contents.');
  } else if (descriptor.id === 'commander.location') {
    payload.observation.source_scope = 'system';
    payload.observation.observed_at = snapshot.localContextRaw?.system_context?.event_timestamp || null;
    if (identityOK && knownCommander && snapshot.location?.systemName) ready(snapshot.location.systemName, snapshot.location.stationName || snapshot.location.flightValue);
  } else {
    const workflow = snapshot.miningWorkflow;
    const workflowOK = Boolean(miningWorkflowForSnapshot(snapshot));
    const coherentCargo = sourceOK && complete && workflowOK && workflow.cargo?.observed === true
      && workflow.cargo?.event_timestamp === observedAt && workflow.cargo?.vessel === 'Ship';
    const target = workflow?.target;
    const targetMatches = target?.selected === true && typeof target.commodity === 'string'
      && target.commodity.toLowerCase() === String(snapshot.objective?.target_commodity || '').toLowerCase()
      && target.quantity === snapshot.objective?.target_quantity;
    const targetAligned = targetMatches || (target?.selected !== true && !snapshot.objective?.target_commodity);
    const goal = targetMatches ? quantity(target.quantity) : null;
    const held = coherentCargo ? quantity(target?.held) : null;
    payload.observation.source_identity = 'operations_mining_workflow';
    if (descriptor.id === 'ops.mining.target') {
      payload.observation.truth = 'plan';
      payload.observation.source_scope = 'profile';
      payload.observation.observed_at = snapshot.objective?.updated_at || null;
      payload.subject.configured_target = snapshot.objective?.objective_id || null;
      if (workflowOK && targetMatches) ready(target.commodity, goal > 0 ? `Optional goal: ${amount(goal)} t` : 'Tracking prospector finds · no quantity goal');
      else Object.assign(d, { headline: snapshot.objectiveAvailable === false ? 'Target unavailable' : 'Choose an ore to track', secondary: 'Used for prospector target-find alerts', state: 'unknown' });
    } else if (descriptor.id === 'ops.mining.fill') {
      if (!targetMatches || !(goal > 0)) Object.assign(d, { headline: 'No quantity goal', secondary: 'Ore tracking works without one' });
      else if (held !== null) {
        ready(`${amount(held)} / ${amount(goal)} t`, held > goal ? `${amount(held-goal)} t over goal` : held === goal ? 'Goal aboard' : `${amount(goal-held)} t remaining`, held === 0);
        payload.detail.progress = { value: Math.min(100, held / goal * 100), text: `${held} of ${goal} t · ${amount(held / goal * 100)}%` };
      }
      payload.detail.lines.push('Target fill counts matching sellable cargo aboard. Refined session output, stolen cargo and mission cargo are separate.');
    } else if (descriptor.id === 'ops.mining.limpets') {
      const limpets = coherentCargo ? count(workflow.limpets?.count) : null;
      if (limpets !== null) ready(amount(limpets), 'Limpets aboard', limpets === 0);
      payload.detail.lines.push('These are unused limpets in your hold. Elite does not report the number of active collectors here.');
      if (limpets === 0) payload.detail.lines.push('No limpets aboard at this reading. Restock at a station before your next run.');
    } else if (descriptor.id === 'ops.mining.next-step') {
      if (workflowOK && coherentCargo && targetAligned && workflow.step?.label) {
        const full = count(cargo.capacity) > 0 && count(cargo.total_count) >= cargo.capacity;
        if (sourceState === 'stale') ready('Resume with fresh readings', 'Game data is last known · check before acting');
        else if (full) ready('Make room for ore', 'Your cargo hold is full');
        else if (workflow.step.kind === 'fit_equipment') ready('Check mining equipment', 'Latest loadout did not show a required module');
        else if (workflow.step.kind === 'extract') {
          const report=workflow.prospector?.latest;
          if(report?.matched && !report.depleted) ready('Mine the reported target', 'Check you still have that asteroid selected in Elite');
          else ready('Prospect another asteroid', targetMatches ? `Looking for ${target.commodity}` : 'Composition appears here after a scan');
        }
        else if (workflow.step.kind === 'select_target') ready('Prospect an asteroid', 'Choose an ore only if you want target-find alerts');
        else ready(workflow.step.label, 'Open for the relevant action');
      } else Object.assign(d, { headline: 'Waiting for game readings', secondary: 'Cargo and ship setup have not been verified' });
    } else if (descriptor.id === 'ops.mining.prospector') {
      const data = workflowOK ? workflow.prospector : null;
      const report = data?.latest;
      payload.observation.source_identity = 'mining_prospector.snapshot';
      payload.observation.observed_at = report?.observed_at || null;
      payload.observation.coverage = report?.composition_observed ? 'complete' : report ? 'partial' : 'unknown';
      payload.observation.source_state = report ? (!snapshot.connected || snapshot.sessionState === 'Last known' ? 'stale' : 'valid') : 'absent';
      if (report) {
        const matching = report.matched && data.target;
        const first = report.composition?.find(row => row.proportion > 0);
        const headline = matching ? `${data.target}${report.proportion == null ? ' core' : ` · ${amount(report.proportion)}%`}`
          : first ? `${first.name} · ${amount(first.proportion)}%` : report.core ? `${report.core} core` : 'Composition not reported';
        const secondary = (report.depleted ? 'Depleted at this report' : matching ? 'Target found in this report' : data.target ? report.composition_observed ? `${data.target} not reported` : `${data.target} not confirmed` : 'Choose an ore for target-find alerts')
          + (report.remaining != null && !report.depleted ? ` · ${amount(report.remaining)}% remaining at scan` : '');
        ready(headline, secondary, false, payload.observation.source_state === 'stale');
        d.emphasis = matching && !report.depleted && payload.observation.source_state === 'valid' ? 'positive' : 'neutral';
        d.facts = (report.composition || []).slice(0, 3).map(row => `${row.name} ${row.proportion == null ? '—' : `${amount(row.proportion)}%`}`);
        if (report.core) d.facts.push(`Core: ${report.core}`);
        if (report.remaining != null) d.facts.push(`${amount(report.remaining)}% remaining when scanned`);
      } else Object.assign(d, { headline: 'Waiting for a prospector', secondary: 'Fire a prospector limpet in Elite · composition appears here' });
    }
    if (!workflowOK) payload.detail.lines.push('The Mining workflow has not answered for this Commander, ship and selected target.');
  }
  if (!knownCommander) payload.detail.lines.push('Commander identity has not been observed. Previous Commander facts are not shown.');
  if (!shipKnown) payload.detail.lines.push('Ship identity has not been observed. Ship facts are not borrowed from another vessel.');
  if (!identityOK) payload.detail.lines.push('Waiting for readings for the current Commander and ship.');
  if (!snapshot.connected && d.state === 'unknown') d.secondary = 'Disconnected · waiting for game data';
  return payload;
}
