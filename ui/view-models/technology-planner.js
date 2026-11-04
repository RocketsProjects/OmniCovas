// Presentation rules for the Technology unlock planner (GKI-01).
// Pure functions over the /knowledge/unlocks/{id}/plan payload. Nothing here
// computes inventory: owned and missing quantities arrive from the backend,
// and an unknown quantity stays unknown in every label.

export const STORAGE_KEY = 'omnicovas.engineering.technologyUnlock';

export function formatDate(value) {
  if (!value) return null;
  // Journal timestamps stored in SQLite are returned as UTC without an offset.
  const stamp = /(?:Z|[+-]\d\d:\d\d)$/i.test(value) ? value : `${value}Z`;
  if (!Number.isFinite(Date.parse(stamp))) return null;
  return new Date(stamp).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

export function rowStatus(row) {
  if (row?.quantity_state !== 'observed' || !Number.isFinite(row.owned)) return 'unknown';
  return row.missing > 0 ? 'short' : 'ready';
}

export function haveText(row) {
  if (rowStatus(row) === 'unknown') return 'Unknown';
  return String(row.owned);
}

export function statusText(row) {
  const status = rowStatus(row);
  if (status === 'unknown') return 'Not checked';
  if (status === 'short') return `${row.missing} short`;
  return 'Ready';
}

export function originText(row) {
  if (rowStatus(row) === 'unknown') return row.reason || 'Not observed yet.';
  const when = formatDate(row.origin?.observed_at);
  const where = row.store === 'ship_cargo' ? 'Current ship hold' : 'Journal materials';
  return when ? `${where} · ${when}` : where;
}

export const CATEGORIES = [['module', 'Modules'], ['weapon', 'Weapons'], ['fighter', 'Fighters']];
export const TRANSACTION_FILTERS = [['all', 'All'], ['permanent_unlock', 'Unlocks'], ['per_item_purchase', 'Per item']];

export function transactionLabel(transaction) {
  return transaction === 'per_item_purchase' ? 'Per-item purchase' : 'Permanent unlock';
}

export function offeringLabel(unlock) {
  return String(unlock?.name || '').replace(/ unlock$/, '');
}

/* Catalogue browsing: category, transaction filter and search, grouped by family
   in pack order. Each size and mount stays its own entry. */
export function catalogueGroups(unlocks, { category = 'module', filter = 'all', search = '' } = {}) {
  const term = search.trim().toLocaleLowerCase();
  const groups = new Map();
  (unlocks || []).forEach((unlock) => {
    if (unlock.category !== category) return;
    if (filter !== 'all' && unlock.transaction !== filter) return;
    const haystack = [unlock.name, unlock.family, unlock.variant].join(' ').toLocaleLowerCase();
    if (term && !haystack.includes(term)) return;
    const family = unlock.family || offeringLabel(unlock);
    if (!groups.has(family)) groups.set(family, []);
    groups.get(family).push(unlock);
  });
  return [...groups.entries()].map(([family, items]) => ({ family, items }));
}

export function categoryCounts(unlocks) {
  const counts = Object.fromEntries(CATEGORIES.map(([id]) => [id, 0]));
  (unlocks || []).forEach((unlock) => { if (unlock.category in counts) counts[unlock.category] += 1; });
  return counts;
}

export function readinessSummary(plan) {
  const r = plan?.readiness || {};
  const total = r.requirement_count || 0;
  const perItem = plan?.transaction === 'per_item_purchase';
  if (plan?.unlock_state?.state === 'observed_unlocked') {
    return { tone: 'done', headline: 'Already unlocked', detail: 'Your Journal recorded this unlock. Buy it with credits in Outfitting at a Guardian broker station.' };
  }
  if (r.all_ready) {
    return { tone: 'ready', headline: `All ${total} requirements ready`, detail: perItem
      ? `Enough for ${plan.quantity} item${plan.quantity === 1 ? '' : 's'}. Each exchange is a separate full hand-in.`
      : 'Take everything to a Guardian Technology Broker and hand it in at once.' };
  }
  const parts = [];
  if (r.ready) parts.push(`${r.ready} ready`);
  if (r.short) parts.push(`${r.short} short`);
  if (r.unknown) parts.push(`${r.unknown} not checked`);
  const detail = r.unknown
    ? 'Unchecked items have no reliable observation yet. They are not counted as zero.'
    : perItem
      ? `Collect the shortfall below for ${plan.quantity} item${plan.quantity === 1 ? '' : 's'}; each item is its own hand-in.`
      : 'Collect the shortfall below, then hand everything in together.';
  return { tone: r.short ? 'short' : 'unknown', headline: parts.join(' · ') || 'No requirements', detail };
}

export function unlockStateText(state) {
  const when = formatDate(state?.observed_at);
  const history = state?.history || {};
  switch (state?.state) {
    case 'not_applicable':
      return { tone: 'unknown', label: 'Bought per item', detail: 'Each exchange gives one weapon; nothing stays unlocked, and owning one does not let you buy another.' };
    case 'evidence_unsupported':
      return { tone: 'unknown', label: 'Unlock state not readable', detail: 'The Journal name this unlock records is not verified, so OmniCOVAS does not read it from your Journal.' };
    case 'observed_unlocked':
      return { tone: 'done', label: 'Unlocked', detail: `Recorded by a Technology Broker entry in your Journal${when ? ` on ${when}` : ''}.` };
    case 'module_observed':
      return { tone: 'done', label: 'Unlock very likely', detail: `This equipment appears in your ${state.evidence_event} record${when ? ` on ${when}` : ''}. It can only be bought after unlocking, but no broker record is stored.` };
    case 'not_observed': {
      const from = formatDate(history.earliest);
      const to = formatDate(history.latest);
      const range = from && to ? ` (${from} to ${to})` : '';
      return { tone: 'unknown', label: 'Unlock not seen', detail: `No unlock appears in the Journal history stored here${range}. Earlier play may not be included, so this is not treated as locked.` };
    }
    default:
      return { tone: 'unknown', label: 'Unlock state unknown', detail: 'No Journal history is stored yet. Play with OmniCOVAS running to record it.' };
  }
}

export function evidenceText(evidence) {
  return {
    community_corroborated: 'Listed by two sources',
    community_reference: 'Listed by one source',
    frontier_documentation: 'Frontier documentation',
    cross_check_only: 'Identifier cross-check',
    app_reference: 'OmniCOVAS reference',
  }[evidence] || 'Source not classified';
}

export function sourceIndex(plan) {
  return new Map((plan?.sources || []).map((source) => [source.id, source]));
}

export function sourcesFor(plan, ids) {
  const index = sourceIndex(plan);
  return [...new Set(ids || [])].map((id) => index.get(id)).filter(Boolean);
}

/* Commander-confirmed checklist, grouped. A tick is the Commander's own record
   and never changes the observed counts the same view shows elsewhere. */
export function checklistGroups(plan) {
  const saved = plan?.tracking?.checklist || {};
  const groups = new Map();
  (plan?.checklist || []).forEach((item) => {
    if (!groups.has(item.group)) groups.set(item.group, []);
    groups.get(item.group).push({ ...item, checked: saved[item.id] === true });
  });
  const items = [...groups.values()].flat();
  return {
    groups: [...groups.entries()].map(([name, entries]) => ({ name, items: entries })),
    confirmed: items.filter((item) => item.checked).length,
    total: items.length,
    saved: Boolean(plan?.tracking),
  };
}

export function collectText(item) {
  if (item.quantity_state !== 'observed') return `Amount not checked · needs ${item.quantity} in total`;
  return `${item.missing} more needed`;
}

/* Engineering → Navigation handoff for a documented site. Navigation shows the
   destination for review; plotting stays with the Commander in the game. */
export function navigationIntent(place, unlockName) {
  const system = place?.attributes?.system;
  if (!system) return null;
  const body = place.attributes.body ? ` · body ${place.attributes.body}` : '';
  return {
    originRoute: '/engineering',
    originPackage: 'Engineering technology',
    originSectionId: 'engineering-technology',
    targetRoute: '/navigation',
    targetSectionId: 'acquisition',
    targetEntityId: place.id || '',
    targetLabel: place.name,
    targetDestination: system,
    targetContext: `${place.attributes.station || 'Guardian site'}${body} · ${unlockName}`,
    reason: 'Review this documented destination before plotting it in Elite Dangerous.',
    returnLabel: 'Back to Guardian planner',
    returnTarget: { route: '/engineering', sectionId: 'engineering-technology' },
  };
}

export function rememberUnlock(unlockId) {
  try { window.localStorage?.setItem(STORAGE_KEY, unlockId); } catch { /* storage unavailable */ }
}

export function rememberedUnlock() {
  try { return window.localStorage?.getItem(STORAGE_KEY) || null; } catch { return null; }
}
