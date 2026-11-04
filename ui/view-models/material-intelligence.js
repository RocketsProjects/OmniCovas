/**
 * GKI-05 material acquisition intelligence view-model.
 *
 * Plain-language shaping of the backend's `acquisition_intelligence` (portfolio)
 * and single-material guides. Nothing here decides a strategy or computes a
 * shortage: those come from the portfolio and the Material Trader plan.
 */

export const STRATEGY_TONE = Object.freeze({
  trade: 'ready',
  trade_then_collect: 'short',
  collect: 'short',
  unplannable: 'unknown',
  no_documented_source: 'unknown',
  inventory_unknown: 'unknown',
});

const EVIDENCE = Object.freeze({
  community_reference: 'Community reference',
  community_corroborated: 'Community, corroborated',
  frontier_documentation: 'Frontier documentation',
});

export function evidenceText(value) {
  return EVIDENCE[value] || 'Community reference';
}

export function scopeKey(buildId) {
  return !buildId || buildId === 'all' ? 'all' : buildId;
}

export function intelligenceFor(progression, buildId) {
  const scopes = progression?.acquisition_intelligence;
  return scopes?.[scopeKey(buildId)] || scopes?.all || null;
}

export function materialIntel(intel, materialId) {
  return (intel?.materials || []).find((m) => m.material_id === materialId) || null;
}

export function shortText(material) {
  if (material.short == null) return 'Stock unknown';
  const reserved = material.reserved ? ` · ${material.reserved} reserved` : '';
  return `Short ${material.short}${reserved}`;
}

/* What the observed system means for an HGE method. */
export function hereText(here) {
  if (!here) return null;
  // The last observed system, never assumed to be where the Commander is now.
  const old = here.freshness === 'historical' ? ', may have changed' : '';
  const when = `(recorded ${dateText(here.observed_at)}${old})`;
  const why = (here.factions || []).map((f) => f.because).filter(Boolean).join('; ');
  if (here.state === 'possible') return `Possible in ${here.system}, your last known system: ${why || 'a faction there qualifies'} ${when}.`;
  // Sources disagree, or the population is unknown: never presented as possible.
  if (here.state === 'uncertain') return `Uncertain in ${here.system}, your last known system: ${why} ${when}.`;
  if (here.state === 'unchecked') return `Only the controlling faction of ${here.system}, your last known system, was recorded, so other factions cannot be checked ${when}.`;
  if (here.state === 'not_here') return `Not from High Grade Emissions in ${here.system}, your last known system ${when}.`;
  return 'Your current system’s factions are not recorded, so this cannot be checked here.';
}

export function dateText(value) {
  if (!value) return 'at an unknown time';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? 'at an unknown time' : parsed.toISOString().slice(0, 16).replace('T', ' ');
}

export function servesText(method) {
  const others = method.serves || [];
  if (!others.length) return null;
  return `Also gives ${others.map((o) => o.name).join(', ')}, which you are short of.`;
}

export function activityLine(activity) {
  const materials = activity.materials.map((m) => (m.short == null ? m.name : `${m.name} ${m.short}`));
  return materials.join(' · ');
}

/* Navigation handoff for a documented place, returning to this material. */
export function navigationIntent(place, material, method, scope = 'all') {
  if (!place?.system) return null;
  const detail = [place.body ? `Body ${place.body}` : null, place.coordinates ? `Surface ${place.coordinates}` : null]
    .filter(Boolean).join(' · ');
  return {
    originRoute: '/engineering',
    originPackage: 'Materials',
    originSectionId: 'engineering-stage-materials',
    originSectionLabel: `Acquisition · ${material.name}`,
    targetRoute: '/navigation',
    targetSectionId: 'acquisition',
    targetEntityId: place.id || '',
    targetLabel: place.name,
    targetDestination: place.system,
    targetContext: [`${material.name} · ${method.name}`, detail].filter(Boolean).join(' · '),
    targetPurpose: {
      materialId: material.material_id, materialName: material.name, methodId: method.id, methodName: method.name, scope: scope || 'all',
    },
    reason: 'Review this documented acquisition destination before plotting it in Elite Dangerous.',
    returnLabel: 'Back to Materials',
    returnTarget: { route: '/engineering', sectionId: 'engineering-stage-materials', entityId: material.material_id },
  };
}

/* Atlas handoff for a place with documented history (GKI-03). */
export function atlasIntent(place, material) {
  return {
    originRoute: '/engineering',
    originPackage: 'Materials',
    originSectionId: 'engineering-stage-materials',
    originSectionLabel: `Acquisition · ${material.name}`,
    targetRoute: '/intel',
    targetSectionId: 'intel-domain-atlas',
    targetEntityId: place.id,
    targetLabel: place.name,
    reason: 'Read the history of this acquisition site.',
    returnLabel: 'Back to Materials',
    returnTarget: { route: '/engineering', sectionId: 'engineering-stage-materials', entityId: material.material_id },
  };
}
