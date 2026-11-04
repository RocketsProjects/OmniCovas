/**
 * OmniCOVAS human freshness vocabulary and source-precedence contract.
 *
 * This module is the executable presentation boundary for the Phase 11
 * Three-Lens model. Backend tokens remain available in proof, but workflow
 * surfaces must use these stable human labels. A label never creates truth.
 */

'use strict';

export const FRESHNESS = Object.freeze({
  live_now: Object.freeze({ key: 'live_now', label: 'Live now', rank: 700, usable: true }),
  current_snapshot: Object.freeze({ key: 'current_snapshot', label: 'Current snapshot', rank: 600, usable: true }),
  checked_here: Object.freeze({ key: 'checked_here', label: 'Checked here', rank: 500, usable: true }),
  commander_entered: Object.freeze({ key: 'commander_entered', label: 'Commander-entered', rank: 450, usable: true }),
  remembered: Object.freeze({ key: 'remembered', label: 'Remembered', rank: 400, usable: true }),
  imported_current_galaxy: Object.freeze({
    key: 'imported_current_galaxy',
    label: 'Imported dataset',
    rank: 300,
    usable: true,
  }),
  stale: Object.freeze({ key: 'stale', label: 'Stale', rank: 200, usable: true }),
  requires_authorization: Object.freeze({
    key: 'requires_authorization',
    label: 'Requires Authorization',
    rank: 0,
    usable: false,
  }),
  not_loaded: Object.freeze({ key: 'not_loaded', label: 'Not Loaded', rank: 0, usable: false }),
  disabled: Object.freeze({ key: 'disabled', label: 'Disabled', rank: 0, usable: false }),
  unsupported: Object.freeze({ key: 'unsupported', label: 'Unsupported', rank: 0, usable: false }),
  unknown: Object.freeze({ key: 'unknown', label: 'Unknown', rank: 0, usable: false }),
});

export const FRESHNESS_KEYS = Object.freeze(Object.keys(FRESHNESS));

const LIVE_SOURCES = new Set([
  'journal',
  'local_journal',
  'live_local_telemetry',
  'local_telemetry',
  'status.json',
  'status_json',
  'statusjson',
]);

const SNAPSHOT_SOURCES = new Set([
  'cargo.json',
  'cargo_json',
  'market.json',
  'market_json',
  'modulesinfo.json',
  'modulesinfo_json',
  'outfitting.json',
  'outfitting_json',
  'shipyard.json',
  'shipyard_json',
  'navroute.json',
  'navroute_json',
  'local_navroute',
  'backpack.json',
  'shiplocker.json',
  'fcmaterials.json',
  'local_screen_snapshot',
  'local_snapshot',
]);

function normalized(value) {
  if (value === null || value === undefined) return '';
  return String(value).trim().toLowerCase().replace(/[\s-]+/g, '_');
}

function descriptor(key, rawFreshness) {
  const value = FRESHNESS[key] || FRESHNESS.unknown;
  return Object.freeze({ ...value, rawFreshness: rawFreshness ?? null });
}

/**
 * Convert source-bearing backend vocabulary to the stable human vocabulary.
 * Explicit terminal states are evaluated before source-family inference.
 */
export function describeFreshness(input, context = {}) {
  const fact = input && typeof input === 'object' && !Array.isArray(input)
    ? input
    : { freshness: input };
  const raw = fact.freshness ?? fact.freshness_label ?? context.freshness;
  const token = normalized(raw);
  const source = normalized(fact.source ?? fact.source_id ?? context.source);
  const truthClass = normalized(fact.truth_class ?? fact.truthClass ?? context.truthClass);

  if (token === 'stale' || token === 'expired') return descriptor('stale', raw);
  if (token === 'not_loaded' || token === 'missing' || token === 'unavailable') {
    return descriptor('not_loaded', raw);
  }
  if (token === 'disabled' || source === 'disabled' || source === 'external_disabled') {
    return descriptor('disabled', raw);
  }
  if (token === 'requires_authorization' || token === 'requires_consent') {
    return descriptor('requires_authorization', raw);
  }
  if (token === 'unsupported' || source === 'unsupported') return descriptor('unsupported', raw);

  if (
    token === 'remembered'
    || token === 'remembered_local'
    || token === 'last_known'
    || source === 'commander_memory'
    || truthClass === 'remembered_local'
  ) {
    return descriptor('remembered', raw);
  }

  if (token === 'commander_entered' || token === 'manual' || truthClass === 'commander_entered') {
    return descriptor('commander_entered', raw);
  }

  if (token === 'imported_current_galaxy' || truthClass === 'imported_current_galaxy') {
    return descriptor('imported_current_galaxy', raw);
  }

  if (
    token === 'checked_here'
    || token === 'commander_observed'
    || token === 'local_event_history'
    || truthClass === 'commander_observed'
  ) {
    return descriptor('checked_here', raw);
  }

  if (token === 'live_now' || token === 'live_local_telemetry') {
    return descriptor('live_now', raw);
  }
  if (token === 'current_snapshot' || token === 'local_only') {
    return descriptor('current_snapshot', raw);
  }

  if (token === 'fresh' || token === 'loaded' || token === 'current') {
    if (LIVE_SOURCES.has(source)) return descriptor('live_now', raw);
    if (SNAPSHOT_SOURCES.has(source) || /\.json$/i.test(source)) {
      return descriptor('current_snapshot', raw);
    }
    return descriptor(context.currentSnapshot === true ? 'current_snapshot' : 'checked_here', raw);
  }

  if (LIVE_SOURCES.has(source) && context.current === true) return descriptor('live_now', raw);
  if (SNAPSHOT_SOURCES.has(source) && context.current === true) return descriptor('current_snapshot', raw);
  return descriptor('unknown', raw);
}

export function freshnessLabel(input, context = {}) {
  return describeFreshness(input, context).label;
}

/**
 * Select the strongest same-field fact without hiding conflicts or history.
 * `ownsField` expresses the documented field-owner rule; it is deliberately
 * stronger than generic source-family ranking. Disabled/not-loaded/unknown
 * candidates cannot win. Stale data may win only when nothing stronger exists.
 */
export function choosePreferredFact(candidates) {
  const prepared = (Array.isArray(candidates) ? candidates : [])
    .map((candidate, index) => {
      const fact = candidate && typeof candidate === 'object' ? candidate : { value: candidate };
      const freshness = describeFreshness(fact);
      const hasValue = fact.value !== null && fact.value !== undefined && fact.value !== '';
      const ownerBoost = fact.ownsField === true ? 1000 : 0;
      const observedAt = Date.parse(fact.observed_at ?? fact.observedAt ?? fact.timestamp ?? '') || 0;
      return { fact, freshness, hasValue, ownerBoost, observedAt, index };
    });

  const eligible = prepared.filter((entry) => entry.hasValue && entry.freshness.usable);
  eligible.sort((a, b) => (
    (b.ownerBoost + b.freshness.rank) - (a.ownerBoost + a.freshness.rank)
    || b.observedAt - a.observedAt
    || a.index - b.index
  ));

  const winner = eligible[0] || null;
  if (!winner) {
    return Object.freeze({
      value: null,
      fact: null,
      freshness: FRESHNESS.unknown,
      conflict: false,
      alternatives: Object.freeze([]),
    });
  }

  const alternatives = eligible.slice(1).map((entry) => Object.freeze({
    fact: entry.fact,
    freshness: entry.freshness,
  }));
  const winnerValue = String(winner.fact.value);
  const conflict = alternatives.some((entry) => String(entry.fact.value) !== winnerValue);

  return Object.freeze({
    value: winner.fact.value,
    fact: winner.fact,
    freshness: winner.freshness,
    conflict,
    alternatives: Object.freeze(alternatives),
  });
}
