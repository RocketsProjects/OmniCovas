// W0 registry. Candidate references stay aliases; only stable semantic IDs are
// used by manifests. No editor/preferences schema is introduced in this wave.
const definitions = [
  ['ship.cargo', 'CMD-06', 'Cargo Hold', 'How much room remains?', 'Dashboard', 'metric', ['S','M','L'], 'M', 'observed', 'local_context_facts.cargo_hold_payload', ['cargo_hold.total_count','cargo_hold.capacity','cargo_hold.inventory','cargo_hold.inventory_complete','cargo_hold.event_timestamp','cargo_hold.vessel']],
  ['commander.location', 'CMD-03', 'Current Location', 'Where am I?', 'Dashboard', 'state', ['S','M'], 'M', 'observed', 'commander-context.deriveCommanderLocationState', ['location.systemName','location.stationName','location.flightValue']],
  ['ops.mining.target', 'MIN-01', 'Mining Target', 'What am I mining for?', 'Operations', 'planner-preview', ['M','L'], 'M', 'plan', 'operations_mining_workflow.derive_target', ['target.selected','target.commodity','target.quantity']],
  ['ops.mining.fill', 'MIN-02', 'Target Fill', 'How close am I?', 'Operations', 'progress', ['M','L'], 'M', 'calculated', 'operations_mining_workflow.derive_target', ['target.held','target.quantity','target.commodity_key','cargo.observed']],
  ['ops.mining.limpets', 'MIN-03', 'Limpets Aboard', 'How many limpets are left?', 'Operations', 'metric', ['S','M'], 'S', 'observed', 'operations_mining_workflow.derive_limpets', ['limpets.count','cargo.observed']],
  ['ops.mining.next-step', 'MIN-06', 'Next Mining Step', 'What should I do next?', 'Operations', 'next-action', ['M','L'], 'M', 'calculated', 'operations_mining_workflow.derive_step', ['step.label','step.kind','handoffs','blockers']],
  // MIN-14 research gate resolved by the separately commissioned Journal
  // ingestion/alert slice. Field mapping and remaining live-game limits are in
  // docs/rcd-mining-review.md. This is the latest report, never a live locator.
  ['ops.mining.prospector', 'MIN-14', 'Latest Prospector', 'Is this asteroid worth mining?', 'Operations', 'briefing', ['M','L'], 'L', 'observed', 'mining_prospector.snapshot', ['prospector.latest.observed_at','prospector.latest.composition','prospector.latest.remaining','prospector.latest.core','prospector.latest.matched']],
];

export function createRegistry(entries, aliasEntries = {}) {
  const map = new Map();
  for (const entry of entries) {
    if (!entry.id || map.has(entry.id)) throw new Error('Widget IDs must be unique');
    if (!['S','C'].includes(entry.gate) || entry.verified !== true) throw new Error('Unverified widget');
    if (!entry.allowedSizes?.length || entry.allowedSizes.some(s => !['S','M','L','W','F'].includes(s))) throw new Error('Invalid widget footprint');
    if (!entry.allowedSizes.includes(entry.preferredSize)) throw new Error('Invalid preferred footprint');
    map.set(entry.id, Object.freeze({ ...entry, allowedSizes: Object.freeze([...entry.allowedSizes]) }));
  }
  const canonicalId = (id) => {
    const visited = new Set();
    while (Object.hasOwn(aliasEntries, id)) {
      if (visited.has(id)) throw new Error('Widget alias cycle');
      visited.add(id); id = aliasEntries[id];
    }
    return map.has(id) ? id : null;
  };
  Object.keys(aliasEntries).forEach(id => { if (!canonicalId(id)) throw new Error('Missing alias target'); });
  return Object.freeze({ canonicalId, get: id => map.get(canonicalId(id)) || null, list: () => [...map.values()] });
}

const aliases = Object.fromEntries(definitions.map(d => [d[1],d[0]]));
Object.assign(aliases, { 'TRD-07': 'ship.cargo', 'TRV-03': 'commander.location', 'NAV-03': 'commander.location' });
export const widgetRegistry = createRegistry(definitions.map(([id,candidate,title,question,category,type,allowedSizes,preferredSize,truth,source,fields]) => ({
  id, candidate, title, question, category, subcategory: category === 'Operations' ? 'Mining' : 'Ship',
  tags: category === 'Operations' ? ['Mining'] : ['Command','Mining','Trading','Travel'],
  schemaVersion: 1, gate: 'S', verified: true, type, allowedSizes, preferredSize,
  minimumSize: allowedSizes[0], maximumSize: allowedSizes.at(-1), compactFallback: 'detail-launcher',
  truth, source, fields, refreshPolicy: 'shared-snapshot', privacyClass: 'local-commander',
  detailDestination: 'bounded-detail', actions: ['inspect'],
})), aliases);

export const miningPreset = Object.freeze([
  { instanceId: 'mining-prospector', widgetId: 'ops.mining.prospector', size: 'L' },
  { instanceId: 'mining-cargo', widgetId: 'ship.cargo', size: 'M' },
  { instanceId: 'mining-limpets', widgetId: 'ops.mining.limpets', size: 'S' },
]);

export function miningManifest(objective, workflow) {
  const instances=[...miningPreset];
  if(objective?.state === 'active' && objective?.target_commodity && objective?.target_quantity > 0)
    instances.push({ instanceId: 'mining-fill', widgetId: 'ops.mining.fill', size: 'M' });
  // Do not spend a tile telling an actively mining player to keep mining.
  // The source-owned next step earns space when preparation, a full hold,
  // return or selling changes the decision.
  if(workflow?.step?.kind && (!['extract','select_target'].includes(workflow.step.kind) || workflow.cargo?.hold_full === true))
    instances.push({instanceId:'mining-next',widgetId:'ops.mining.next-step',size:'M'});
  return instances;
}

export function validateManifest(instances, registry = widgetRegistry) {
  const seen = new Set();
  return instances.map(instance => {
    const descriptor = registry.get(instance.widgetId);
    if (!descriptor || seen.has(instance.instanceId) || !instance.instanceId || !descriptor.allowedSizes.includes(instance.size)) throw new Error('Invalid deck instance');
    seen.add(instance.instanceId);
    return Object.freeze({ ...instance, widgetId: descriptor.id });
  });
}
