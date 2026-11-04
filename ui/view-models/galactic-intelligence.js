/**
 * GKI-04 Galactic Intelligence view-model.
 *
 * Plain-language shaping for automatic briefings, Intel's "Documented here"
 * section and the Settings panel. Payloads come from /knowledge/intelligence;
 * nothing here decides eligibility, which the backend owns. A documented place
 * is never presented as visited: visit wording comes from the match fields.
 * GKI-07 adds the Historian's sections (namesake, founders, faction history
 * beside the faction your Journal reports, mysteries, expedition chapters,
 * explore next) and the Commander Chronicle's record of earlier visits.
 */
import { formatWhen } from './galactic-historian.js';

export const BRIEFING_EVENT = 'GALACTIC_INTELLIGENCE_BRIEFING';
/* A commander's intelligence was erased (forgotten in Privacy). */
export const CLEARED_EVENT = 'GALACTIC_INTELLIGENCE_CLEARED';
/* Journal events that change which commander is active. */
export const COMMANDER_EVENTS = Object.freeze(['Commander', 'LoadGame', 'NewCommander']);
export const PATHS = Object.freeze({
  context: '/knowledge/intelligence/context',
  preferences: '/knowledge/intelligence/preferences',
  reset: '/knowledge/intelligence/preferences/reset',
  briefings: '/knowledge/intelligence/briefings',
  dismiss: (id) => `/knowledge/intelligence/briefings/${encodeURIComponent(id)}/dismiss`,
});
export const MAX_VISIBLE_BRIEFINGS = 3;

export const CATEGORY_HELP = Object.freeze({
  station_history: 'Briefings about documented starports, systems, bodies and settlements.',
  figures_events: 'People and historical events tied to a place.',
  factions_politics: 'Organisations and the factions that historically controlled a place. Never shown as current control.',
  discoveries: 'Documented landmarks, wrecks and exploration discoveries in a system you arrive in.',
  practical: 'Documented ways to gather materials at a place. No yields are promised.',
  recommendations: 'A place documents a material one of your active Engineering builds is short of.',
  expedition_stories: 'Lets expedition story moments be offered when the Journal shows you at their places. Stories in Navigation › Plan are always there to read.',
  suggestions: 'Connected documented places worth a visit, with straight-line distances. Never a route or a jump count.',
});

/* Quiet, Discoverer and Storyteller are presets over the existing fields, the
   same reading GKI-06 expeditions make of them. */
export const MODES = Object.freeze({
  quiet: {
    label: 'Quiet (manual only)',
    help: 'Nothing is offered automatically. The Atlas, the Chronicle and your expeditions are always there to read.',
    fields: { enabled: false },
  },
  discoverer: {
    label: 'Discoverer',
    help: 'Arrival and discovery briefings the first time OmniCOVAS sees you at each documented place.',
    fields: { enabled: true, frequency: 'first', quietMode: false },
  },
  storyteller: {
    label: 'Storyteller',
    help: 'Every eligible arrival, at most once every 6 hours per place, with story moments.',
    fields: { enabled: true, frequency: 'all', quietMode: false },
  },
});

export function modeOf(form) {
  if (!form?.enabled || form.frequency === 'off' || form.quietMode) return 'quiet';
  return form.frequency === 'all' ? 'storyteller' : 'discoverer';
}

export const FREQUENCY_TEXT = Object.freeze({
  off: { label: 'Off', help: 'No automatic briefings, even when enabled above.' },
  important: {
    label: 'Important discoveries only',
    help: 'Only places where a documented historical event or discovery took place, once each.',
  },
  first: {
    label: 'First eligible encounter',
    help: 'The first time OmniCOVAS observes you at each documented place. This never claims it is your first visit.',
  },
  all: {
    label: 'All eligible encounters',
    help: 'Every eligible arrival, at most once every 6 hours for the same place.',
  },
});

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
  location: 'Place',
});

export function kindLabel(kind) {
  return KIND_LABELS[kind] || 'Record';
}

const CERTAINTY_TEXT = Object.freeze({ uncertain: 'uncertain', disputed: 'disputed' });

/* One association line, keeping its qualifications. Historical control never
   reads as current control. */
export function associationText(row) {
  if (!row?.entity) return '';
  const certainty = CERTAINTY_TEXT[row.certainty];
  const head = `${row.label} ${row.entity.name}${certainty ? ` (${certainty})` : ''}`;
  if (row.historical_only) {
    return `${head}: historical record only. ${row.period || 'Live faction control is not tracked.'}`;
  }
  return row.note ? `${head}: ${row.note}` : head;
}

/* What an observation proves about a place, from the match, not from prose. */
export function visitText(match, kind) {
  if (!match) return '';
  if (match.reached && match.exact) return kind === 'station' ? 'You are docked here.' : 'You are here.';
  if (match.reached) return 'Identified by name only, so this is probable, not certain.';
  if (match.needs === 'site') {
    return 'Its documented position is not exact, so arriving in the system never counts as reaching it.';
  }
  if (match.needs === 'surface') return 'Documented here. Arriving in the system is not a visit to the site.';
  return 'Documented in this system. Being in the system is not a visit to it.';
}

export function briefingModel(briefing) {
  if (!briefing?.briefing_id) return null;
  const lines = [];
  const lead = briefing.significance || briefing.summary;
  if (lead) lines.push(lead);
  const details = [];
  (briefing.history || []).forEach((text) => details.push({ label: 'History', text }));
  /* GKI-07 gives namesakes, founders and faction history their own lines; the
     same relationship is not repeated as a plain connection. */
  const own = new Set([
    ...(briefing.namesake?.length ? ['named_after'] : []),
    ...(briefing.founders?.length ? ['founded_by'] : []),
    ...(briefing.faction?.historical?.length ? ['historically_controlled_by'] : []),
  ]);
  (briefing.associations || [])
    .filter((row) => !own.has(row.relation))
    .forEach((row) => details.push({ label: 'Connection', text: associationText(row) }));
  /* GKI-07: who the place is named after (documented only), who founded it,
     and its faction history kept apart from the faction the Journal reports. */
  (briefing.namesake || []).forEach((row) => {
    details.push({ label: 'Named after', text: `${row.entity?.name}${row.note ? `: ${row.note}` : ''}` });
  });
  (briefing.founders || []).forEach((row) => {
    const when = [row.period, row.note].filter(Boolean).join(' · ');
    details.push({ label: 'Founded by', text: `${row.entity?.name}${when ? ` (${when})` : ''}` });
  });
  if (briefing.faction) {
    (briefing.faction.historical || []).forEach((row) => {
      details.push({
        label: 'Faction history',
        text: `${row.entity?.name}${row.role ? `, ${row.role}` : ''}: historical record only. ${row.period || ''}`.trim(),
      });
    });
    if (briefing.faction.current) {
      details.push({
        label: 'Controlled now',
        text: `${briefing.faction.current.name}, as your Journal reports. This is not documented history.`,
      });
    }
  }
  (briefing.places || []).forEach((place) => {
    const record = place.record == null ? ''
      : place.record === 'observed' ? ' You have been here.' : ' Nearby: no record of you reaching it.';
    details.push({
      label: kindLabel(place.entity?.kind),
      text: `${place.entity?.name}: ${place.significance || place.summary || ''} ${place.note || ''}${record}`.trim(),
    });
  });
  (briefing.mysteries || []).forEach((row) => {
    details.push({ label: 'Mystery', text: `${row.entity?.name}${row.note ? `: ${row.note}` : ''}` });
  });
  (briefing.chapters || []).forEach((row) => {
    details.push({
      label: 'Your expedition',
      text: `${row.expedition?.name}: chapter ${row.chapter?.position} of ${row.narrative?.title}, “${row.chapter?.title}”${row.read ? ' (read)' : ''}.`,
    });
  });
  (briefing.next || []).forEach((row) => {
    const ly = Number.isFinite(row.distance_ly) ? ` · ${row.distance_ly} ly in a straight line` : '';
    details.push({ label: 'Explore next', text: `${row.place?.name} (${row.system}) · ${row.reason}${ly}` });
  });
  (briefing.practical || []).forEach((row) => {
    const materials = (row.materials || []).map((m) => m.name).join(', ');
    details.push({
      label: 'Practical',
      text: `${row.place?.name}: ${row.activity?.name}${materials ? ` (${materials})` : ''}. No yields are promised.`,
    });
  });
  const recommendation = briefing.recommendation
    ? {
      text: briefing.recommendation.explanation,
      reasons: (briefing.recommendation.reasons || []).map((r) => (
        `${r.build}: ${r.deficit} ${r.material?.name || 'material'} short`
      )),
    }
    : null;
  const before = briefing.record?.class === 'observed' && briefing.record.first_at
    ? `Your Chronicle has you here before, first on ${formatWhen(briefing.record.first_at)}.`
    : null;
  const kicker = briefing.moment === 'nearby' ? 'Discovery suggestion' : (briefing.category_label || 'Galactic Intelligence');
  return {
    id: briefing.briefing_id,
    title: briefing.title,
    kicker: `${kicker}${briefing.importance === 'major' ? ' · Notable' : ''}`,
    headline: briefing.headline,
    lines,
    visit: briefing.location_note || visitText(briefing.subject_match, briefing.kind),
    before,
    chronicleId: (briefing.actions || []).some((a) => a.type === 'open_chronicle') ? briefing.subject?.id : null,
    uncertainty: briefing.uncertainty || [],
    details,
    recommendation,
    spoilerNote: briefing.spoilers_hidden
      ? 'Spoiler protection held back some story details. The Atlas entry has them.'
      : null,
    encounterNote: briefing.encounter_note || null,
    sources: (briefing.sources || []).map((s) => s.name),
    subjectId: briefing.subject?.id,
    actions: (briefing.actions || []).filter((a) => a.type === 'open_atlas'),
    earlier: null,
  };
}

/* GKI-08: a briefing stays readable after the moment it describes, but it never
   reads as the present. `presence` is the Commander Context's answer from the
   backend: known keys, or not known, which proves neither presence nor departure.
   With no answer at all (or a briefing without a key) nothing is claimed. */
export function placeKey(briefing) {
  return briefing?.presence_key || briefing?.location_key || null;
}

export function isElsewhere(briefing, presence) {
  const key = placeKey(briefing);
  return Boolean(key && presence?.known && !(presence.keys || []).includes(key));
}

export function earlierText(briefing, presence) {
  const key = placeKey(briefing);
  if (!key || !presence) return null;
  const when = briefing.observed_at ? formatWhen(briefing.observed_at) : null;
  if (!presence.known) return `From ${when || 'earlier'}. Where you are now is not known.`;
  if (isElsewhere(briefing, presence)) return `Earlier${when ? `, ${when}` : ''}: not where you are now.`;
  /* No projection keeps a surface position, so being in the system says nothing
     about still being at a site. The landing is history, with its time. */
  if (briefing.kind === 'site') return `Landed ${when || 'earlier'}. Whether you are still at the site is not known.`;
  return null;
}

/* Whether a card is about the past: its present-tense lines then stay out. */
export function isPast(briefing, presence) {
  return Boolean(placeKey(briefing) && presence && (!presence.known || isElsewhere(briefing, presence)));
}

/* Journal events that can change the Commander Context's location. */
export const LOCATION_EVENTS = Object.freeze(['FSDJump', 'CarrierJump', 'Location', 'Docked', 'Undocked']);

/* Newest first, one card per briefing id, bounded. */
export function mergeBriefings(current, incoming) {
  const seen = new Set();
  return [...(incoming || []), ...(current || [])]
    .filter((row) => row?.briefing_id && !seen.has(row.briefing_id) && seen.add(row.briefing_id))
    .sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')))
    .slice(0, MAX_VISIBLE_BRIEFINGS);
}

export function documentedRows(documented, scope) {
  if (!documented || documented.state !== 'available') return [];
  return (documented[scope] || []).map((row) => ({
    id: row.entity.id,
    name: row.entity.name,
    kind: kindLabel(row.entity.kind),
    relation: row.relation,
    reason: row.reason,
    visit: row.relation === 'in_system' ? visitText(row.match, row.entity.kind) : null,
    significance: row.significance || row.summary,
    uncertainty: row.uncertainty || [],
    associations: (row.associations || []).map(associationText),
    spoilers: row.spoilers_hidden || 0,
  }));
}

export const ROUTE_LABELS = Object.freeze({
  '/dashboard': 'Dashboard',
  '/operations': 'Operations',
  '/intel': 'Intel',
  '/navigation': 'Navigation',
  '/engineering': 'Engineering',
  '/squadron': 'Squadron',
  '/log': 'Log',
  '/systems': 'Systems',
  '/settings': 'Settings',
});

/* The handoff that opens an Atlas entry from a briefing or from Intel, so the
   Shell shows the return link to wherever the Commander was. */
export function atlasIntent(entityId, label, origin = {}) {
  const route = origin.route || '/dashboard';
  return {
    originRoute: route,
    originPackage: 'Galactic Intelligence',
    originSectionId: origin.sectionId || '',
    originSectionLabel: origin.sectionLabel || '',
    targetRoute: '/intel',
    targetSectionId: 'intel-domain-atlas',
    targetEntityId: entityId,
    targetLabel: label || entityId,
    reason: origin.reason || 'Read the documented record behind this briefing.',
    returnLabel: `Back to ${origin.returnLabel || ROUTE_LABELS[route] || 'previous view'}`,
  };
}

export function preferencesForm(payload) {
  const prefs = payload?.preferences;
  if (!prefs) return null;
  return {
    commanderKnown: Boolean(payload.commander_known),
    forgotten: Boolean(payload.forgotten),
    ownRecord: Boolean(payload.own_record),
    enabled: Boolean(prefs.enabled),
    frequency: prefs.frequency,
    quietMode: Boolean(prefs.quiet_mode),
    spoilerProtection: Boolean(prefs.spoiler_protection),
    /* GKI-07: an older record without these reads as the backend's defaults. */
    arrivalBriefings: prefs.arrival_briefings !== false,
    firstVisitOnly: prefs.first_visit_only === true,
    categories: (payload.categories || []).map((c) => ({
      id: c.id,
      label: c.label,
      help: CATEGORY_HELP[c.id] || '',
      on: Boolean(prefs.content?.[c.id]),
    })),
    frequencies: (payload.frequencies || Object.keys(FREQUENCY_TEXT)).map((id) => ({
      id, ...(FREQUENCY_TEXT[id] || { label: id, help: '' }),
    })),
  };
}

export function preferencesPayload(form) {
  return {
    enabled: Boolean(form.enabled),
    frequency: form.frequency,
    quiet_mode: Boolean(form.quietMode),
    spoiler_protection: Boolean(form.spoilerProtection),
    arrival_briefings: Boolean(form.arrivalBriefings),
    first_visit_only: Boolean(form.firstVisitOnly),
    content: Object.fromEntries(form.categories.map((c) => [c.id, Boolean(c.on)])),
  };
}

/* Apply a mode preset to the form; every field stays editable afterwards. */
export function applyMode(form, mode) {
  const preset = MODES[mode];
  if (!form || !preset) return form;
  Object.assign(form, preset.fields);
  return form;
}
