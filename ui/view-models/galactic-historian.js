/**
 * GKI-07 Living Galactic Historian and Commander Chronicle view-model.
 *
 * Plain-language shaping for the Intel Chronicle workspace, the "Here and now"
 * Historian card and the Atlas "Your record" card. Payloads come from
 * /knowledge/historian and /knowledge/chronicle; nothing here decides evidence,
 * which the backend owns. Evidence classes differ in shape as well as colour,
 * and a place without a record is "Unknown", never "not visited".
 */

export const RECORDED_EVENT = 'CHRONICLE_RECORDED';
export const CLEARED_EVENT = 'CHRONICLE_CLEARED';
export const COMMANDER_EVENTS = Object.freeze(['Commander', 'LoadGame', 'NewCommander']);
export const PATHS = Object.freeze({
  context: '/knowledge/historian/context',
  subject: (id, reveal = false) => `/knowledge/historian/subjects/${encodeURIComponent(id)}${reveal ? '?reveal=true' : ''}`,
  chronicle: '/knowledge/chronicle',
  confirmations: '/knowledge/chronicle/confirmations',
  confirmation: (id) => `/knowledge/chronicle/confirmations/${encodeURIComponent(id)}`,
  saved: '/knowledge/chronicle/saved',
  savedEntry: (id) => `/knowledge/chronicle/saved/${encodeURIComponent(id)}`,
});

export const EVIDENCE = Object.freeze({
  observed: { label: 'Observed', glyph: '●', help: 'The Journal showed you here.' },
  commander_confirmed: { label: 'Commander-confirmed', glyph: '◆', help: 'You said so. OmniCOVAS did not observe it.' },
  suggested: { label: 'Suggested', glyph: '◇', help: 'A suggestion, not a record of a visit.' },
  unknown: { label: 'Unknown', glyph: '○', help: 'No record either way. OmniCOVAS only knows what it saw in your Journal.' },
});

export const FILTERS = Object.freeze([
  ['all', 'Everything'],
  ['observed', 'Observed'],
  ['commander_confirmed', 'Commander-confirmed'],
  ['suggested', 'Suggested'],
]);

const KIND_LABELS = Object.freeze({
  star_system: 'Star system',
  body: 'Planet or moon',
  station: 'Starport',
  settlement: 'Settlement',
  landmark: 'Landmark',
  vessel: 'Historic vessel',
  person: 'Person',
  organization: 'Organisation',
  event: 'Event',
  discovery: 'Discovery',
  mystery: 'Mystery',
  location: 'Documented site',
});

export function kindLabel(kind) {
  return KIND_LABELS[kind] || 'Record';
}

export function evidenceOf(value) {
  return EVIDENCE[value] ? value : 'unknown';
}

/* A Journal or commander time as "31 Oct 2026, 19:59 UTC". Deterministic: the
   Chronicle is a record, so it never depends on the viewer's time zone. */
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
export function formatWhen(iso) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(String(iso || ''));
  if (!match) return '';
  const [, year, month, day, hour, minute] = match;
  return `${Number(day)} ${MONTHS[Number(month) - 1]} ${year}, ${hour}:${minute} UTC`;
}

const plural = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`;

export function distanceText(ly) {
  if (!Number.isFinite(ly)) return 'Distance unknown';
  return `${ly.toLocaleString('en-GB', { maximumFractionDigits: 1 })} ly in a straight line`;
}

/* A visit is a distinct arrival or stay; a login during a stay is one more
   observation of it. With no supported number of visits, only observations are
   counted, and "At least" never turns those into visits. */
export function visitLine(record) {
  const { visits, count } = record;
  const floor = record.visits_is_minimum ? 'At least ' : '';
  if (visits == null) {
    if (!(count > 0)) return null;
    return `${record.count_is_minimum ? 'At least ' : ''}${plural(count, 'Journal observation')} on record; they do not show how many visits.`;
  }
  if (visits > 1 || record.visits_is_minimum) return `${floor}${plural(visits, 'visit')} on record.`;
  return count > 1 ? `One visit on record, seen in ${count} Journal observations.` : null;
}

/* One evidence record as lines a commander reads. Presence in a system and an
   approach are context, said as such, never a visit. */
export function recordModel(record) {
  const kind = evidenceOf(record?.class);
  const lines = [];
  if (kind === 'observed') {
    const latest = record.observations?.[record.observations.length - 1];
    if (latest?.how) lines.push(`${latest.how}.`);
    if (record.first_at) lines.push(`First observed ${formatWhen(record.first_at)}.`);
    const visits = visitLine(record);
    if (visits) lines.push(visits);
  }
  if (record?.confirmation) {
    const via = record.confirmation.via === 'expedition'
      ? `You marked it complete on the expedition ${record.confirmation.expedition || ''}`.trim()
      : 'You confirmed this visit';
    const when = record.confirmation.at ? ` on ${formatWhen(record.confirmation.at)}` : '';
    lines.push(`${via}${when}.${record.confirmation.note ? ` “${record.confirmation.note}”` : ''}`);
  }
  if (kind !== 'observed' && record?.in_system?.last_at) {
    lines.push(`You were in its system, last on ${formatWhen(record.in_system.last_at)}. That is not a visit to it.`);
  }
  if (record?.approached?.last_at) {
    const nearby = Number.isFinite(record.approached.distance_km) ? 'nearby' : 'an approach';
    lines.push(`${record.approached.how} on ${formatWhen(record.approached.last_at)}: ${nearby}, not a visit.`);
  }
  return {
    kind,
    label: EVIDENCE[kind].label,
    glyph: EVIDENCE[kind].glyph,
    note: record?.note || EVIDENCE[kind].help,
    lines,
    confirmed: Boolean(record?.confirmation && record.confirmation.via === 'chronicle'),
    confirmable: Boolean(record?.confirmable),
  };
}

/* A connection as one sentence. Historical control always says it is not
   current control; a namesake is only ever a documented one. */
export function connectionText(row) {
  if (!row?.entity) return '';
  const certainty = row.certainty && row.certainty !== 'documented' ? ` (${row.certainty})` : '';
  const head = `${row.label} ${row.entity.name}${certainty}`;
  const extra = [row.role, row.period, row.note].filter(Boolean).join(' · ');
  if (row.historical_only) {
    return `${head}: historical record only${extra ? ` (${extra})` : ''}. Not current control.`;
  }
  return extra ? `${head}: ${extra}` : head;
}

const GROUPS = [
  ['namesake', 'Named after'],
  ['founders', 'Founded by'],
  ['founded', 'Founded'],
  ['faction_history', 'Faction history'],
  ['people', 'People'],
  ['organizations', 'Organisations'],
  ['events', 'Events'],
  ['expeditions', 'Expeditions'],
  ['mysteries', 'Mysteries'],
  ['places', 'Places'],
];

/* The same sentence without the subject's name, for a row that already shows
   the name as its link. */
export function connectionDetail(row) {
  if (!row?.entity) return '';
  const certainty = row.certainty && row.certainty !== 'documented' ? ` (${row.certainty})` : '';
  const extra = [row.role, row.period, row.note].filter(Boolean).join(' · ');
  if (row.historical_only) {
    return `${row.label}${certainty}: historical record only${extra ? ` (${extra})` : ''}. Not current control.`;
  }
  return extra ? `${row.label}${certainty}: ${extra}` : `${row.label}${certainty}`;
}

export function connectionGroups(connections) {
  return GROUPS
    .map(([id, label]) => ({
      id,
      label,
      rows: (connections?.[id] || []).map((row) => ({ ...row, text: connectionText(row), detail: connectionDetail(row) })),
    }))
    .filter((group) => group.rows.length);
}

const TOPICS = [
  ['history', 'The record'],
  ['uncertainty', 'What is not known'],
  ['interpretation', 'Interpretations'],
  ['theory', 'Theories (unproven)'],
  ['community_report', 'Community reports'],
  ['identity', 'At a glance'],
  ['service', 'Services'],
  ['gameplay', 'Gameplay'],
];

export function subjectModel(subject) {
  if (!subject?.entity) return null;
  return {
    id: subject.entity.id,
    name: subject.entity.name,
    kind: kindLabel(subject.entity.kind),
    period: subject.period || null,
    summary: subject.summary || '',
    significance: subject.significance || null,
    topics: TOPICS
      .map(([id, label]) => ({ id, label, claims: subject.topics?.[id] || [] }))
      .filter((topic) => topic.claims.length),
    practical: subject.practical || [],
    spoilersHidden: subject.spoilers_hidden || 0,
  };
}

export function nextModel(rows) {
  return (rows || []).map((row) => {
    const kind = evidenceOf(row.record?.class);
    return {
      id: row.place.id,
      name: row.place.name,
      kind: kindLabel(row.place.kind),
      system: row.system,
      reason: row.reason,
      distance: distanceText(row.distance_ly),
      evidence: kind,
      evidenceLabel: EVIDENCE[kind].label,
      glyph: EVIDENCE[kind].glyph,
      plannable: Boolean(row.plannable),
      planNote: row.plan_note || null,
    };
  });
}

/* The "Here and now" card: the five Historian questions for the current place. */
export function contextModel(payload) {
  if (!payload) return { state: 'loading' };
  const state = payload.state || 'unavailable';
  const where = payload.where || {};
  const system = where.system?.state !== 'unknown' ? where.system?.name : null;
  const station = where.station?.state !== 'unknown' && where.station?.docked ? where.station?.name : null;
  const base = {
    state,
    whereLine: station ? `Docked at ${station}, ${system || where.station?.system || ''}`.replace(/, $/, '')
      : system ? `In ${system}` : 'No location observed yet',
    spoilersShown: Boolean(payload.spoilers_shown),
  };
  if (state !== 'available') return base;
  const current = payload.current_faction;
  return {
    ...base,
    here: (payload.here || []).map((row) => ({
      id: row.entity.id,
      name: row.entity.name,
      kind: kindLabel(row.entity.kind),
      reason: row.reason,
      record: recordModel(row.record),
    })),
    subject: subjectModel(payload.subject),
    groups: connectionGroups(payload.connections),
    currentFaction: current
      ? `Your Journal reports ${current.name} controlling this ${current.scope} now${current.observed_at ? ` (${formatWhen(current.observed_at)})` : ''}. Documented history is shown apart.`
      : null,
    nearby: (payload.nearby || []).map((row) => ({
      id: row.entity.id,
      name: row.entity.name,
      kind: kindLabel(row.entity.kind),
      text: row.significance || row.summary || '',
      record: recordModel(row.record),
      note: evidenceOf(row.record?.class) === 'observed' ? 'You have been here.' : 'Nearby. No record of you reaching it.',
    })),
    next: nextModel(payload.next),
    stories: (payload.stories || []).map((row) => ({
      narrativeId: row.narrative.id,
      text: `Chapter ${row.chapter.position} of ${row.chapter.count} in ${row.narrative.title}: ${row.chapter.title}`,
      teaser: row.chapter.teaser,
    })),
    chapters: (payload.chapters || []).map((row) => ({
      text: `Your expedition ${row.expedition.name}: chapter ${row.chapter.position} of ${row.narrative.title}, ${row.chapter.title}${row.read ? ' (read)' : ''}`,
      expeditionId: row.expedition.id,
      stopId: row.stop_id,
    })),
  };
}

/* The Chronicle workspace, by evidence class. */
export function chronicleModel(payload, filter = 'all') {
  if (!payload) return { state: 'loading' };
  const profile = payload.profile || {};
  if (profile.forgotten) return { state: 'forgotten' };
  if (!profile.commander_known) return { state: 'no_commander' };
  const counts = payload.counts || {};
  const places = (payload.places || []).map((row) => ({
    id: row.place.id,
    name: row.place.name,
    kind: kindLabel(row.place.kind),
    system: row.system,
    atlas: Boolean(row.atlas),
    record: recordModel(row.record),
  }));
  const suggested = nextModel(payload.suggested);
  const visible = filter === 'all' || filter === 'suggested'
    ? places
    : places.filter((row) => row.record.kind === filter);
  return {
    state: places.length || (payload.codex || []).length || (payload.expeditions || []).length
      || (payload.saved || []).length ? 'available' : 'empty',
    paused: Boolean(profile.memory_paused),
    filter,
    tiles: [
      { id: 'observed', label: 'Observed places', value: counts.observed || 0, glyph: EVIDENCE.observed.glyph },
      { id: 'commander_confirmed', label: 'Commander-confirmed', value: counts.commander_confirmed || 0, glyph: EVIDENCE.commander_confirmed.glyph },
      { id: 'codex', label: 'Codex discoveries', value: counts.codex || 0, glyph: '✦' },
      { id: 'expeditions', label: 'Expeditions', value: counts.expeditions || 0, glyph: '➤' },
    ],
    unknownNote: `${counts.unknown || 0} documented ${counts.unknown === 1 ? 'place has' : 'places have'} no record. That is not proof you never went.`,
    memoryNote: `Commander Memory holds ${plural(payload.memory?.systems || 0, 'system')} and ${plural(payload.memory?.stations || 0, 'station')} you have visited; the Observed Galaxy lists them all.`,
    places: filter === 'suggested' ? [] : visible,
    suggested: filter === 'all' || filter === 'suggested' ? suggested : [],
    codex: filter === 'all' || filter === 'observed' ? (payload.codex || []).map((row) => ({
      key: `${row.entry_id}-${row.system_address}-${row.body_id ?? ''}`,
      name: row.name,
      line: [row.category, row.subcategory, row.region].filter(Boolean).join(' · '),
      where: `${row.system || 'Unknown system'}${row.body_id != null ? `, body ${row.body_id}` : ''}`,
      when: formatWhen(row.last_at),
      count: row.count,
      flags: [
        row.new_entry ? 'The Journal marked it new to your Codex' : null,
        row.voucher ? `Voucher ${row.voucher.toLocaleString('en-GB')} Cr` : null,
      ].filter(Boolean),
      note: row.note,
    })) : [],
    expeditions: filter === 'all' ? (payload.expeditions || []).map((row) => ({
      id: row.id,
      name: row.name,
      status: row.status,
      line: `${row.done} of ${row.stops} stops reached or done · ${row.chapters_read} chapter${row.chapters_read === 1 ? '' : 's'} read`,
      next: row.next ? `Next: ${row.next.name}` : null,
    })) : [],
    saved: filter === 'all' ? (payload.saved || []).map((row) => ({
      id: row.entry_id,
      type: row.type,
      targetId: row.target_id,
      chapterId: row.chapter_id,
      title: row.title,
      kind: row.type === 'atlas' ? kindLabel(row.kind) : row.type === 'chapter' ? 'Story chapter' : 'Story',
      available: Boolean(row.available),
      when: formatWhen(row.at),
    })) : [],
    timeline: filter === 'all' ? (payload.timeline || []).map((row, index) => ({
      key: `${row.at || ''}-${index}`,
      when: formatWhen(row.at),
      title: row.title,
      detail: row.detail || '',
      evidence: evidenceOf(row.evidence),
      glyph: EVIDENCE[evidenceOf(row.evidence)].glyph,
      evidenceLabel: EVIDENCE[evidenceOf(row.evidence)].label,
      subjectId: row.subject?.id || null,
    })) : [],
    caveat: payload.caveat,
  };
}

/* The Atlas "Your record" card for one subject. */
export function subjectRecordModel(payload) {
  if (!payload) return { state: 'loading' };
  const profile = payload.profile || {};
  const base = {
    state: 'available',
    plannable: Boolean(payload.plannable),
    saved: payload.saved || null,
    forgotten: Boolean(profile.forgotten),
    commanderKnown: Boolean(profile.commander_known),
    inExpeditions: (payload.in_expeditions || []).map((row) => ({
      expeditionId: row.expedition.id,
      name: row.expedition.name,
      stopId: row.stop_id,
    })),
    stories: (payload.stories || []).map((row) => `Chapter ${row.chapter.position} of ${row.narrative.title}: ${row.chapter.title}`),
    next: nextModel(payload.next).slice(0, 4),
  };
  if (!payload.place) {
    return { ...base, record: null, note: 'Not a place: it has no documented location, so it can be read and saved but never visited or planned.' };
  }
  return {
    ...base,
    record: recordModel(payload.record),
    confirmable: Boolean(payload.place.confirmable),
    note: payload.place.confirmable
      ? null
      : 'Its position is not documented exactly, so the Journal cannot confirm a visit. Only you can.',
  };
}

/* Handoffs. Each names the Chronicle entry to return to. */
export function atlasIntent(entityId, label, origin = {}) {
  return {
    originRoute: '/intel',
    originPackage: 'Commander Chronicle',
    originSectionId: 'intel-domain-chronicle',
    originSectionLabel: origin.sectionLabel || label || 'Chronicle',
    targetRoute: '/intel',
    targetSectionId: 'intel-domain-atlas',
    targetEntityId: entityId,
    targetLabel: label || entityId,
    reason: origin.reason || 'Read the documented record.',
    returnLabel: 'Back to the Chronicle',
    returnTarget: { route: '/intel', sectionId: 'intel-domain-chronicle', entityId: origin.returnEntityId || entityId },
  };
}

/* `origin.returnTarget: null` leaves the return to the Shell, which then goes
   back to the origin route (a briefing can be opened from anywhere). */
export function chronicleIntent(entityId, label, origin = {}) {
  const route = origin.route || '/intel';
  const intent = {
    originRoute: route,
    originPackage: origin.package || 'Galactic Atlas',
    originSectionId: origin.sectionId ?? 'intel-domain-atlas',
    originSectionLabel: origin.sectionLabel || label || '',
    targetRoute: '/intel',
    targetSectionId: 'intel-domain-chronicle',
    targetEntityId: entityId || '',
    targetLabel: label ? `Chronicle · ${label}` : 'Chronicle',
    reason: origin.reason || 'See what your Chronicle holds about this place.',
    returnLabel: origin.returnLabel || 'Back to the Galactic Atlas',
  };
  if (origin.returnTarget !== null) {
    intent.returnTarget = origin.returnTarget
      || { route: '/intel', sectionId: 'intel-domain-atlas', entityId: entityId || '' };
  }
  return intent;
}

/* Intel → Navigation › Plan: the destination card offers "Add to …". Only a
   place with a documented identity is ever offered. */
export function planIntent(place, origin = {}) {
  if (!place?.id || !place.system) return null;
  return {
    originRoute: '/intel',
    originPackage: origin.package || 'Commander Chronicle',
    originSectionId: origin.sectionId || 'intel-domain-chronicle',
    originSectionLabel: origin.sectionLabel || place.name,
    targetRoute: '/navigation',
    targetSectionId: 'acquisition',
    targetEntityId: place.id,
    targetLabel: place.name,
    targetDestination: place.system,
    targetContext: [place.name, place.kind, place.planNote].filter(Boolean).join(' · '),
    reason: 'Plan a visit to this documented place. Plotting stays with you in Elite Dangerous.',
    returnLabel: origin.returnLabel || 'Back to the Chronicle',
    returnTarget: origin.returnTarget || { route: '/intel', sectionId: 'intel-domain-chronicle', entityId: place.id },
  };
}

/* Back to the expedition stop a place belongs to (GKI-06's own target). */
export function expeditionIntent(expeditionId, stopId, label) {
  return {
    originRoute: '/intel',
    originPackage: 'Commander Chronicle',
    originSectionId: 'intel-domain-chronicle',
    originSectionLabel: label || 'Chronicle',
    targetRoute: '/navigation',
    targetSectionId: `navigation-expedition-stop-${stopId}`,
    targetEntityId: `${expeditionId}:${stopId}`,
    targetLabel: label || 'Expedition stop',
    reason: 'Open this stop in your expedition.',
    returnLabel: 'Back to the Chronicle',
    returnTarget: { route: '/intel', sectionId: 'intel-domain-chronicle', entityId: '' },
  };
}
