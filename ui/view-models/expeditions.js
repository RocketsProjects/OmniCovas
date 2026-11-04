// Galactic Expeditions (GKI-06): pure helpers for the Navigation › Plan workspace.
// Labels say what the evidence shows and no more: a straight-line distance is not
// a route, a teaser is not a visit, and a stop the Journal cannot confirm says so.

export const PATHS = Object.freeze({
  list: '/navigation/expeditions',
  catalog: '/navigation/expeditions/catalog',
  opportunities: '/navigation/expeditions/opportunities',
  materials: (scope, expeditionId) => `/navigation/expeditions/materials?scope=${encodeURIComponent(scope || 'all')}`
    + (expeditionId ? `&expedition_id=${encodeURIComponent(expeditionId)}` : ''),
  theme: (themeId, expeditionId) => `/navigation/expeditions/themes/${encodeURIComponent(themeId)}`
    + (expeditionId ? `?expedition_id=${encodeURIComponent(expeditionId)}` : ''),
  search: (query) => `/navigation/expeditions/search?q=${encodeURIComponent(query)}`,
  narrative: (id, reveal) => `/navigation/expeditions/narratives/${encodeURIComponent(id)}${reveal ? '?reveal=true' : ''}`,
  detail: (id) => `/navigation/expeditions/${encodeURIComponent(id)}`,
  stops: (id) => `/navigation/expeditions/${encodeURIComponent(id)}/stops`,
  stop: (id, stopId) => `/navigation/expeditions/${encodeURIComponent(id)}/stops/${encodeURIComponent(stopId)}`,
  order: (id) => `/navigation/expeditions/${encodeURIComponent(id)}/order`,
  chapter: (id, narrativeId, chapterId) => `/navigation/expeditions/${encodeURIComponent(id)}/chapters/`
    + `${encodeURIComponent(narrativeId)}/${encodeURIComponent(chapterId)}`,
  suggestions: (id) => `/navigation/expeditions/${encodeURIComponent(id)}/suggestions`,
  recap: (id) => `/navigation/expeditions/${encodeURIComponent(id)}/recap`,
  claim: (id) => `/navigation/expeditions/${encodeURIComponent(id)}/claim`,
  dismiss: (id) => `/navigation/expeditions/opportunities/${encodeURIComponent(id)}/dismiss`,
});

export const SECTION_ID = 'navigation-expeditions';
export const STOP_PREFIX = 'navigation-expedition-stop-';
export const STORAGE_KEY = 'omnicovas.navigation.expeditions';
// Journal events that can move an expedition on; the open workspace refreshes on them.
export const PROGRESS_EVENTS = new Set([
  'FSDJump', 'CarrierJump', 'Location', 'Docked', 'DockingRequested', 'DockingGranted',
  'SupercruiseExit', 'ApproachBody', 'ApproachSettlement', 'Touchdown',
]);
export const CLEARED_EVENT = 'EXPEDITIONS_CLEARED';

export const FIND_TABS = Object.freeze([
  ['story', 'Story'],
  ['themes', 'Themes'],
  ['materials', 'Materials'],
  ['along', 'Along the way'],
  ['search', 'Search'],
]);

export const STATUS = Object.freeze({
  planned: { label: 'Planned', tone: 'planned' },
  in_system: { label: 'In the system', tone: 'partial' },
  approached: { label: 'Approached', tone: 'partial' },
  reached: { label: 'Reached', tone: 'done' },
  completed: { label: 'Marked complete', tone: 'done' },
  skipped: { label: 'Skipped', tone: 'skipped' },
});

export const EXPEDITION_STATUS = Object.freeze({
  planning: 'Planning',
  active: 'Under way',
  completed: 'Complete',
  archived: 'Archived',
});

const ENTRY_TEXT = {
  destination: 'Journey',
  theme: 'Themed journey',
  goal: 'Materials run',
  custom: 'Expedition',
};

export function statusOf(stop) {
  return STATUS[stop?.status] || STATUS.planned;
}

/* What an expedition is about, in one line: its story, theme or goal. */
export function kickerText(expedition, story) {
  if (story?.title) return `Story journey · ${story.title}`;
  if (expedition?.theme?.label) return `${ENTRY_TEXT[expedition.entry] || 'Expedition'} · ${expedition.theme.label}`;
  return ENTRY_TEXT[expedition?.entry] || 'Expedition';
}

export function progressText(expedition, story) {
  const parts = [`${expedition?.done || 0} of ${expedition?.stops || 0} stops done`];
  if (story) parts.push(`${story.read} of ${story.count} chapters read`);
  return parts.join(' · ');
}

export function distanceText(ly) {
  return Number.isFinite(ly) ? `${ly.toLocaleString('en-GB', { maximumFractionDigits: 1 })} ly` : 'Distance unknown';
}

/* A purpose as the Commander reads it: why this stop is on the trip. */
export function purposeText(purpose) {
  switch (purpose?.type) {
    case 'story':
      return purpose.chapter_title
        ? `Chapter ${purpose.chapter_position}: ${purpose.chapter_title}`
        : 'Story chapter';
    case 'discovery':
      return `Optional discovery${purpose.narrative_title ? ` · ${purpose.narrative_title}` : ''}`;
    case 'acquisition':
      return `Materials · ${(purpose.materials || []).map((m) => m.name).join(', ')}`;
    case 'sightseeing':
      return purpose.theme_label ? `Sightseeing · ${purpose.theme_label}` : 'Sightseeing';
    case 'destination':
      return 'Destination';
    default:
      return 'Your stop';
  }
}

export function relevanceTone(relevance) {
  return { relevant: 'short', partly: 'short', no_longer_needed: 'ready', unknown: 'unknown' }[relevance?.state]
    || 'unknown';
}

/* Where the stop is, compactly: system, then the body or station when known. */
export function locationText(stop) {
  const where = stop?.location || {};
  return [where.system, where.station || where.body].filter(Boolean).join(' · ') || 'Unknown system';
}

/* Why the Journal has or has not recorded progress at a stop. */
export function evidenceText(stop) {
  const evidence = stop?.evidence || {};
  const replay = evidence.replayed ? ' (rebuilt from your Journal)' : '';
  if (stop?.status === 'completed') {
    return evidence.reached
      ? `You marked this complete. The Journal also showed you here (${evidence.reached_event}).`
      : 'You marked this complete. The Journal has not shown you here.';
  }
  if (evidence.reached) return `The Journal showed you here: ${evidence.reached_event}${replay}.`;
  if (evidence.approached && Number.isFinite(evidence.landed_km)) {
    return `The Journal showed you landing about ${evidence.landed_km.toFixed(1)} km away, not at the place itself. `
      + 'Only a landing within 1 km of it counts.';
  }
  if (evidence.approached) {
    return `The Journal showed you nearby (${evidence.approach_event}), not at the place itself.`;
  }
  if (evidence.in_system_at) return 'The Journal showed you in this system, which is not a visit to the place.';
  if (stop?.status === 'skipped') return 'Skipped. It stays on the itinerary until you remove it.';
  return 'No Journal evidence yet.';
}

/* The figures a pilot needs to find the stop in the galaxy map. */
export function navigationLines(stop) {
  const where = stop?.location || {};
  const lines = [['System', where.system || 'Unknown']];
  if (where.station) lines.push(['Station', where.station]);
  if (where.body) lines.push(['Body', where.body]);
  if (where.surface) {
    const exact = where.precision === 'exact';
    lines.push(['Surface', exact ? where.surface : `${where.surface} (approximate)`]);
  }
  return lines;
}

export function legText(leg) {
  if (!leg) return '';
  if (leg.same_system) return 'Same system as the previous stop';
  return leg.known ? `${distanceText(leg.distance_ly)} from the previous stop` : 'Distance from the previous stop unknown';
}

export function modeText(mode) {
  if (!mode) return '';
  const stages = mode.stages?.length
    ? `may offer: ${mode.stages.map((s) => STAGE_TEXT[s] || s).join(', ')}`
    : 'nothing is offered automatically';
  return `${mode.label}: ${stages}.`;
}

export const STAGE_TEXT = Object.freeze({
  approach: 'approach teasers',
  arrival: 'arrival briefings',
  continue: 'the next chapter',
  recap: 'the journey recap',
});

export function requirementTone(requirement) {
  return { unknown: 'unknown', unverified: 'unknown', advice: 'advice' }[requirement?.status] || 'unknown';
}

/* Handoff to the Galactic Atlas for a stop, returning to the same stop. */
export function atlasIntent(expedition, stop) {
  if (!stop?.place_id || !stop.atlas) return null;
  return {
    originRoute: '/navigation',
    originPackage: 'Expeditions',
    originSectionId: SECTION_ID,
    originSectionLabel: expedition.name,
    targetRoute: '/intel',
    targetSectionId: 'intel-domain-atlas',
    targetEntityId: stop.place_id,
    targetLabel: stop.name,
    reason: 'Read the history of this expedition stop.',
    returnLabel: `Back to ${expedition.name}`,
    returnTarget: returnTarget(expedition, stop),
  };
}

/* Handoff to Engineering › Materials for a material a stop helps gather. */
export function materialsIntent(expedition, stop, material, scope = '') {
  if (!material?.material_id) return null;
  return {
    originRoute: '/navigation',
    originPackage: 'Expeditions',
    originSectionId: SECTION_ID,
    originSectionLabel: expedition.name,
    targetRoute: '/engineering',
    targetSectionId: 'engineering-stage-materials',
    targetEntityId: material.material_id,
    targetLabel: material.name,
    // GKI-08: return to the build the stop was planned for, not just the material.
    targetPurpose: scope ? { materialId: material.material_id, materialName: material.name, scope } : null,
    reason: 'See how to gather this material at an expedition stop.',
    returnLabel: `Back to ${expedition.name}`,
    returnTarget: returnTarget(expedition, stop),
  };
}

function returnTarget(expedition, stop) {
  return { route: '/navigation', sectionId: `${STOP_PREFIX}${stop.stop_id}`, entityId: `${expedition.id}:${stop.stop_id}` };
}

/* Whether a Navigation handoff returns to an expedition, and to which stop. */
export function expeditionTarget(intent) {
  if (intent?.targetRoute !== '/navigation') return null;
  const section = String(intent.targetSectionId || '');
  if (section !== SECTION_ID && !section.startsWith(STOP_PREFIX)) return null;
  const [expeditionId, stopId] = String(intent.targetEntityId || '').split(':');
  return { expeditionId: expeditionId || null, stopId: stopId || null };
}

export function remember(state) {
  try {
    window.localStorage?.setItem(STORAGE_KEY, JSON.stringify({
      selectedId: state.selectedId || null,
      selectedStopId: state.selectedStopId || null,
      findTab: state.findTab || 'story',
    }));
  } catch { /* storage unavailable */ }
}

export function remembered() {
  try {
    const raw = JSON.parse(window.localStorage?.getItem(STORAGE_KEY) || 'null');
    return raw && typeof raw === 'object' ? raw : {};
  } catch {
    return {};
  }
}

/* Where an incoming Navigation destination came from, for its purpose. */
export function incomingStop(intent) {
  if (!intent || intent.targetRoute !== '/navigation') return null;
  const placeId = String(intent.targetEntityId || '').trim();
  const system = String(intent.targetDestination || '').trim();
  if (!placeId && !system) return null;
  return {
    placeId: placeId || null,
    system,
    label: String(intent.targetLabel || system),
    fromMaterials: intent.originRoute === '/engineering' && intent.originPackage === 'Materials',
    material: intent.originPackage === 'Materials' ? String(intent.returnTarget?.entityId || '') : '',
    // GKI-08: the shortage and method chosen in Materials, when the handoff says.
    need: intent.originPackage === 'Materials' && intent.targetPurpose?.materialId ? { ...intent.targetPurpose } : null,
  };
}
