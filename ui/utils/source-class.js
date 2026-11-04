/**
 * PB13-02 source-class vocabulary — the presentation mirror.
 *
 * `omnicovas/core/source_class.py` is the definition; this file must agree
 * with it exactly, and `source-class.test.js` asserts that by reading the
 * Python module. Keep both sides in step or the parity test fails.
 *
 * `resolveSourceClass` returns null for a value it does not recognise
 * rather than falling back to 'unknown'. An unmapped name means an emitter
 * introduced a class this vocabulary has never seen, and 'unknown' is a
 * real answer meaning "we do not know this fact" — collapsing the two
 * would hide a defect behind a legitimate label.
 */

'use strict';

export const SOURCE_CLASS = Object.freeze({
  live_local: Object.freeze({
    key: 'live_local',
    label: 'Live local',
    meaning: "Read from this machine's live telemetry now.",
  }),
  local_snapshot: Object.freeze({
    key: 'local_snapshot',
    label: 'Local snapshot',
    meaning: 'Read from a companion file this machine wrote. Current as of the '
      + 'last time the game wrote it, not necessarily now.',
  }),
  observed_history: Object.freeze({
    key: 'observed_history',
    label: 'Observed history',
    meaning: 'Derived from what this machine recorded. Recorded sessions only — '
      + 'absence is never proof something did not happen.',
  }),
  commander_entered: Object.freeze({
    key: 'commander_entered',
    label: 'Commander-entered',
    meaning: 'You entered this. OmniCOVAS did not verify it.',
  }),
  authority_reference: Object.freeze({
    key: 'authority_reference',
    label: 'Reference',
    meaning: 'Curated local reference material, not live game data. Verify '
      + 'against the current game patch.',
  }),
  imported_dataset: Object.freeze({
    key: 'imported_dataset',
    label: 'Imported dataset',
    meaning: 'From an imported dataset, subordinate to current local truth.',
  }),
  disabled_provider: Object.freeze({
    key: 'disabled_provider',
    label: 'Provider disabled',
    meaning: 'A source that could supply this is switched off. Nothing was '
      + 'fetched and nothing was guessed.',
  }),
  unsupported: Object.freeze({
    key: 'unsupported',
    label: 'Unsupported',
    meaning: 'OmniCOVAS cannot supply this fact.',
  }),
  unknown: Object.freeze({
    key: 'unknown',
    label: 'Unknown',
    meaning: 'Not known. No value is being implied.',
  }),
});

export const SOURCE_CLASS_KEYS = Object.freeze(Object.keys(SOURCE_CLASS));

/* Every truth_class the app emits, mapped to its PB13-02 class. Some of
   these names are fixed by ratified authority records, so they are mapped
   rather than renamed. */
const TRUTH_CLASS_TO_SOURCE_CLASS = Object.freeze({
  live_local_telemetry: 'live_local',
  local_telemetry: 'live_local',
  local_screen_snapshot: 'local_snapshot',
  local_snapshot: 'local_snapshot',
  local_event_history: 'observed_history',
  local_observed_history: 'observed_history',
  commander_entered: 'commander_entered',
  knowledge_reference: 'authority_reference',
  imported_current_galaxy: 'imported_dataset',
  imported_dataset: 'imported_dataset',
  disabled_source: 'disabled_provider',
  disabled_provider: 'disabled_provider',
  unsupported: 'unsupported',
  unknown: 'unknown',
});

/** Map an emitted truth_class onto its PB13-02 source class, or null. */
export function resolveSourceClass(truthClass) {
  if (truthClass === null || truthClass === undefined) return null;
  const key = String(truthClass).trim().toLowerCase();
  if (!key) return null;
  return TRUTH_CLASS_TO_SOURCE_CLASS[key] || null;
}

/** Human label for a truth_class, or null when it cannot be resolved. */
export function sourceClassLabel(truthClass) {
  const key = resolveSourceClass(truthClass);
  return key ? SOURCE_CLASS[key].label : null;
}

/** What the class means for the Commander, limit included, or null. */
export function sourceClassMeaning(truthClass) {
  const key = resolveSourceClass(truthClass);
  return key ? SOURCE_CLASS[key].meaning : null;
}

/** Every truth_class value this vocabulary recognises. */
export function knownTruthClasses() {
  return Object.keys(TRUTH_CLASS_TO_SOURCE_CLASS).sort();
}
