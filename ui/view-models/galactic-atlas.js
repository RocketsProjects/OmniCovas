// Presentation rules for the Galactic Atlas (GKI-03).
// Pure functions over /knowledge/atlas and /knowledge/atlas/{id}. The Atlas is
// reference knowledge: nothing here reads or claims anything about the
// Commander's own position, holdings or control of a place.

export const STORAGE_KEY = 'omnicovas.intel.atlas';

export const CATEGORIES = [
  ['all', 'All'],
  ['place', 'Places'],
  ['person', 'People'],
  ['organization', 'Organizations'],
  ['event', 'Events'],
  ['mystery', 'Mysteries'],
];

const KIND_LABELS = {
  star_system: 'Star system',
  body: 'Planet or moon',
  station: 'Starport',
  settlement: 'Settlement',
  landmark: 'Landmark',
  vessel: 'Historic vessel',
  person: 'Person',
  organization: 'Organization',
  event: 'Historical event',
  discovery: 'Discovery',
  mystery: 'Mystery',
  location: 'Documented site',
  material: 'Material',
  activity: 'Activity',
  technology_broker: 'Technology broker',
};

export function kindLabel(kind) {
  return KIND_LABELS[kind] || 'Reference record';
}

export function categoryCounts(subjects) {
  const counts = Object.fromEntries(CATEGORIES.map(([id]) => [id, 0]));
  (subjects || []).forEach((subject) => {
    counts.all += 1;
    if (subject.category in counts) counts[subject.category] += 1;
  });
  return counts;
}

/* Search covers names, aliases, the associated system and topics, so "HIP 12099"
   finds the crash site and "INRA" finds the organisation by its alias. */
export function filterSubjects(subjects, { category = 'all', search = '' } = {}) {
  const term = search.trim().toLocaleLowerCase();
  return (subjects || []).filter((subject) => {
    if (!term && category !== 'all' && subject.category !== category) return false;
    if (!term) return true;
    const haystack = [
      subject.name, ...(subject.aliases || []), subject.system, subject.summary,
      kindLabel(subject.kind), subject.period,
    ].filter(Boolean).join(' ').toLocaleLowerCase();
    return haystack.includes(term);
  });
}

const RELATION_LABELS = {
  located_in: ['Located in', 'Contains'],
  named_after: ['Named after', 'Namesake of'],
  associated_with: ['Associated with', 'Associated with'],
  discovered_by: ['Discovered by', 'Credited with'],
  participated_in: ['Took part in', 'Participants'],
  member_of: ['Member of', 'Members'],
  historically_controlled_by: ['Historically controlled by', 'Historically controlled'],
  occurred_at: ['Took place at', 'Events here'],
  related_to: ['Related to', 'Related to'],
  located_at: ['Found at', 'Available here'],
  obtained_from: ['Obtained from', 'Yields'],
  founded_by: ['Founded by', 'Founded'],
  part_of_expedition: ['Part of the expedition', 'Places and people of the expedition'],
  related_to_mystery: ['Connected mystery', 'Connected to this mystery'],
};

export function relationLabel(type, direction) {
  const pair = RELATION_LABELS[type];
  if (!pair) return String(type || 'Related').replace(/_/g, ' ');
  return direction === 'incoming' ? pair[1] : pair[0];
}

/* Connections grouped by their reading, in a stable, story-first order. */
const RELATION_ORDER = [
  'Located in', 'Contains', 'Named after', 'Namesake of', 'Founded by', 'Founded',
  'Took part in', 'Participants', 'Took place at', 'Events here',
  'Part of the expedition', 'Places and people of the expedition', 'Member of', 'Members',
  'Associated with', 'Discovered by', 'Credited with', 'Historically controlled by',
  'Historically controlled', 'Connected mystery', 'Connected to this mystery',
  'Related to', 'Available here', 'Found at',
];

export function groupConnections(connections) {
  const groups = new Map();
  (connections || []).forEach((row) => {
    const label = relationLabel(row.type, row.direction);
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(row);
  });
  const rank = (label) => {
    const index = RELATION_ORDER.indexOf(label);
    return index === -1 ? RELATION_ORDER.length : index;
  };
  return [...groups.entries()]
    .sort((a, b) => rank(a[0]) - rank(b[0]))
    .map(([label, rows]) => ({ label, rows }));
}

export function certaintyText(certainty) {
  return {
    uncertain: 'Uncertain',
    disputed: 'Disputed',
  }[certainty] || null;
}

const TOPICS = [
  ['history', 'History'],
  ['uncertainty', 'What is not known'],
  ['identity', 'At a glance'],
  ['service', 'Documented services'],
  ['gameplay', 'Gameplay'],
  ['community_report', 'Community reports'],
  /* GKI-07: how a source or the community reads the record, and unproven ideas,
     kept apart from the record itself. */
  ['interpretation', 'Interpretations'],
  ['theory', 'Theories (unproven)'],
];

/* Historical record, gameplay guidance and community reports stay apart. Claims
   from a record another pack keeps (no topic) read as reference. */
export function claimsByTopic(claims) {
  const groups = TOPICS.map(([id, label]) => ({
    id, label, claims: (claims || []).filter((claim) => claim.topic === id),
  }));
  const other = (claims || []).filter((claim) => !claim.topic);
  if (other.length) groups.push({ id: 'reference', label: 'Reference', claims: other });
  return groups.filter((group) => group.claims.length);
}

export function evidenceText(evidence) {
  return {
    community_corroborated: 'Two sources agree',
    community_reference: 'One source',
    frontier_documentation: 'Frontier documentation',
    cross_check_only: 'Identifier cross-check',
    app_reference: 'OmniCOVAS reference',
  }[evidence] || 'Source not classified';
}

export function precisionText(location) {
  if (!location) return null;
  return {
    exact: 'Exact location documented',
    approximate: 'Approximate position',
    historical: 'Historical position (may have moved)',
    system_only: 'System only',
  }[location.precision] || 'Position not classified';
}

/* Where the place is, in the order a commander reads a destination. */
export function locationLines(location) {
  if (!location) return [];
  const lines = [['System', location.system]];
  if (location.body) lines.push(['Body', location.body]);
  if (location.station) lines.push(['Station', location.station]);
  if (Number.isFinite(location.latitude)) {
    lines.push(['Surface position', `${location.latitude.toFixed(2)}, ${location.longitude.toFixed(2)}`]);
  }
  return lines;
}

const LEVEL_TEXT = {
  system: 'system',
  body: 'body',
  station: 'station',
  surface: 'surface site',
};

/* What a future arrival check could prove about this place, in plain words. */
export function matchSupportText(support) {
  if (!support?.place) return null;
  const levels = support.levels || {};
  const exact = Object.entries(levels).filter(([, how]) => how === 'exact').map(([level]) => LEVEL_TEXT[level]);
  const named = Object.entries(levels).filter(([, how]) => how === 'name_only').map(([level]) => LEVEL_TEXT[level]);
  const parts = [];
  if (exact.length) parts.push(`Exact identifiers for the ${exact.join(', ')}.`);
  if (named.length) parts.push(`Name only for the ${named.join(', ')}, so a match is probable, not certain.`);
  if (levels.surface === 'unsupported') parts.push('The surface position is not precise enough to confirm a visit.');
  if (support.reached_at === 'site') {
    parts.push('Its documented position is not exact, so arriving in the system or at a body never counts as reaching it.');
  } else {
    parts.push(`Reaching it means arriving at the ${LEVEL_TEXT[support.reached_at] || 'place'}, not just the system.`);
  }
  const surface = support.surface;
  if (surface) {
    parts.push(`A landing counts only within ${surface.at_site_km} km of its documented position, `
      + `which is known to about ${Math.round(surface.uncertainty_km * 1000)} m. `
      + `Closer than ${surface.nearby_km} km is shown as nearby, never as a visit.`);
  }
  return parts.join(' ');
}

export function relevanceText(relevance) {
  if (!relevance) return null;
  return {
    relevant: { tone: 'short', label: 'Useful for your builds' },
    not_needed: { tone: 'ready', label: 'Not needed right now' },
    unknown: { tone: 'unknown', label: 'Cannot tell yet' },
    no_active_builds: { tone: 'unknown', label: 'No active builds' },
    no_documented_opportunity: { tone: 'unknown', label: 'No documented opportunity' },
  }[relevance.state] || { tone: 'unknown', label: 'Relevance unknown' };
}

/* Intel → Navigation handoff. Navigation shows the destination for review;
   plotting stays with the Commander in the game. */
export function navigationIntent(entry) {
  const location = entry?.location;
  if (!location?.system) return null;
  const name = entry.entity?.name || location.system;
  const detail = [
    location.station ? `Station ${location.station}` : null,
    location.body ? `Body ${location.body}` : null,
    Number.isFinite(location.latitude)
      ? `Surface ${location.latitude.toFixed(2)}, ${location.longitude.toFixed(2)}`
      : null,
    precisionText(location),
  ].filter(Boolean).join(' · ');
  return {
    originRoute: '/intel',
    originPackage: 'Galactic Atlas',
    originSectionId: 'intel-domain-atlas',
    originSectionLabel: name,
    targetRoute: '/navigation',
    targetSectionId: 'acquisition',
    targetEntityId: entry.entity.id,
    targetLabel: name,
    targetDestination: location.system,
    targetContext: detail ? `${name} · ${detail}` : name,
    reason: 'Review this documented destination before plotting it in Elite Dangerous.',
    returnLabel: 'Back to Galactic Atlas',
    returnTarget: { route: '/intel', sectionId: 'intel-domain-atlas', entityId: entry.entity.id },
  };
}

/* Intel → Engineering Materials handoff for a documented material source. */
export function materialsIntent(entry, material) {
  if (!material?.inventory?.symbol) return null;
  return {
    originRoute: '/intel',
    originPackage: 'Galactic Atlas',
    originSectionId: 'intel-domain-atlas',
    originSectionLabel: entry?.entity?.name || '',
    targetRoute: '/engineering',
    targetSectionId: 'engineering-stage-materials',
    targetEntityId: material.inventory.symbol,
    targetLabel: material.name,
    reason: `Documented at ${entry?.entity?.name || 'this place'}.`,
    returnLabel: 'Back to Galactic Atlas',
    returnTarget: { route: '/intel', sectionId: 'intel-domain-atlas', entityId: entry?.entity?.id || '' },
  };
}

export function rememberAtlas(state) {
  try {
    window.localStorage?.setItem(STORAGE_KEY, JSON.stringify({
      selected: state.selected || null, category: state.category || 'all', search: state.search || '',
    }));
  } catch { /* storage unavailable */ }
}

export function rememberedAtlas() {
  try {
    const value = JSON.parse(window.localStorage?.getItem(STORAGE_KEY) || 'null');
    return value && typeof value === 'object' ? value : null;
  } catch { return null; }
}
