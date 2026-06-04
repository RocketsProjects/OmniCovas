/**
 * OmniCOVAS — Source / Proof / State Primitives.
 *
 * Phase 7.6 PB07.6-03.
 *
 * Implements the controlled vocabulary contract from
 * authority_files/documents/02_ui_ux_authority/OmniCOVAS_UI_Interaction_Design_System_v1_0.md
 * §7 (State Badge), §8 (Source Chip), §9 (Proof Disclosure), §11 (Empty State).
 *
 * Pure DOM helpers. Every dynamic value goes through textContent
 * (createElement + textContent) per ADR 0003. No innerHTML / outerHTML /
 * insertAdjacentHTML / document.write / eval / new Function / string timers.
 *
 * Pairs with command-primitives.js — these helpers do not replace
 * StatusBadge; they introduce the human-facing state/source/proof grammar.
 *
 * Surface intent:
 *   - createOmniStateBadge: §7 state vocabulary, fact-or-surface state.
 *   - createSourceChip:     §8 source vocabulary, provenance summary.
 *   - createProofDrawer:    §9 collapsed-by-default proof disclosure.
 *   - createMissingFieldsSummary: §11/§9 grouped fallback reduction.
 *   - mapSourceIdToChipLabel / mapFactToState: controlled mapping helpers.
 */

'use strict';

import { setSafeText, appendTextChild } from '../utils/safe-dom.js';

/* §7.1 controlled state-badge vocabulary. The visible label and the key
 * are both stable: code must reference STATE_LABEL keys, not free strings. */
export const OMNI_STATE_LABELS = Object.freeze({
  available: 'Available',
  not_loaded: 'Not loaded',
  no_route_plotted: 'No route plotted',
  no_verified_source: 'No verified source',
  unsupported: 'Unsupported',
  disabled: 'Disabled',
  stale: 'Stale',
  future: 'Future',
  manual: 'Manual',
  blocked: 'Blocked',
});

export const OMNI_STATE_KEYS = Object.freeze(Object.keys(OMNI_STATE_LABELS));

/* §8.1 controlled source-chip vocabulary. AI is intentionally absent:
 * AI is never a source value (Engineering Standards §17,
 * Source Capability Reference §1.1). */
export const SOURCE_CHIP_LABELS = Object.freeze({
  local_telemetry: 'Local telemetry',
  local_event_history: 'Local event history',
  local_snapshot: 'Local snapshot',
  commander_entered: 'Commander-entered',
  knowledge_reference: 'Reference material from KB',
  external_disabled: 'External disabled',
  no_verified_source: 'No verified source',
  stale: 'Stale',
  future_reserved: 'Future / reserved',
});

export const SOURCE_CHIP_KEYS = Object.freeze(Object.keys(SOURCE_CHIP_LABELS));

/* Companion JSON source identifiers that map to the Local snapshot chip
 * (Local Data Surface Reference §10, UI Design System §8.1). */
const LOCAL_SNAPSHOT_SOURCE_IDS = Object.freeze(new Set([
  'cargo.json', 'cargo_json', 'cargojson',
  'market.json', 'market_json', 'marketjson',
  'outfitting.json', 'outfitting_json', 'outfittingjson',
  'shipyard.json', 'shipyard_json', 'shipyardjson',
  'modulesinfo.json', 'modulesinfo_json', 'modulesinfojson',
  'navroute.json', 'navroute_json', 'navroutejson', 'local_navroute',
  'backpack.json', 'shiplocker.json', 'fcmaterials.json',
  'local_screen_snapshot', 'local_snapshot',
]));

const LOCAL_EVENT_HISTORY_SOURCE_IDS = Object.freeze(new Set([
  'journal', 'local_journal', 'local_event_history',
]));

const LOCAL_TELEMETRY_SOURCE_IDS = Object.freeze(new Set([
  'status.json', 'status_json', 'statusjson',
  'live_local_telemetry', 'local_telemetry',
]));

const NO_VERIFIED_SOURCE_IDS = Object.freeze(new Set([
  'no_verified_source', 'unsupported', 'unknown', 'unavailable',
]));

const DISABLED_SOURCE_IDS = Object.freeze(new Set([
  'disabled', 'external_disabled', 'requires_authorization', 'requires_consent',
]));

const MANUAL_SOURCE_IDS = Object.freeze(new Set([
  'commander_entered', 'commander_note', 'manual',
]));

const KNOWLEDGE_REFERENCE_SOURCE_IDS = Object.freeze(new Set([
  'knowledge_reference',
]));

function normalizeKey(value) {
  if (value === null || value === undefined) return '';
  return String(value).trim().toLowerCase();
}

function makeEl(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined && text !== null) setSafeText(el, text);
  return el;
}

/* ──────────────────────────────────────────────────────────────────────
 * OmniStateBadge
 *
 * §7 — describes the state of a fact or surface, not its source.
 *
 *   createOmniStateBadge('no_verified_source', { ariaLabel?: string })
 *
 * - Rejects unknown state keys so off-vocabulary states cannot leak in.
 * - Renders the controlled label via textContent (ADR 0003).
 * ────────────────────────────────────────────────────────────────────── */
export function createOmniStateBadge(state, options) {
  const stateKey = normalizeKey(state).replace(/-/g, '_');
  if (!Object.prototype.hasOwnProperty.call(OMNI_STATE_LABELS, stateKey)) {
    throw new Error(
      `[source-proof] Unknown OmniStateBadge state: ${state}. ` +
        `Allowed: ${OMNI_STATE_KEYS.join(', ')}`,
    );
  }
  const label = OMNI_STATE_LABELS[stateKey];
  const badge = makeEl('span', `omni-state-badge omni-state-badge--${stateKey.replace(/_/g, '-')}`, label);
  badge.setAttribute('data-state', stateKey);
  badge.setAttribute('role', 'status');
  const ariaLabel = options && options.ariaLabel ? String(options.ariaLabel) : label;
  badge.setAttribute('aria-label', ariaLabel);
  return badge;
}

/* ──────────────────────────────────────────────────────────────────────
 * SourceChip
 *
 * §8 — compact provenance summary that lives beside the primary value.
 *
 *   createSourceChip('local_snapshot', { ariaLabel?: string })
 *
 * - Rejects unknown chip keys.
 * - Refuses 'ai' / 'ai_provider' / etc. — AI is not a source.
 * ────────────────────────────────────────────────────────────────────── */
const FORBIDDEN_CHIP_KEYS = Object.freeze(new Set([
  'ai', 'ai_provider', 'ai_draft', 'ai_generated', 'claude', 'gpt', 'gemini',
]));

export function createSourceChip(chip, options) {
  const chipKey = normalizeKey(chip).replace(/-/g, '_');
  if (FORBIDDEN_CHIP_KEYS.has(chipKey)) {
    throw new Error(
      `[source-proof] AI is not a source label. Source chips describe ` +
        `verified provenance. Refused: ${chip}`,
    );
  }
  if (!Object.prototype.hasOwnProperty.call(SOURCE_CHIP_LABELS, chipKey)) {
    throw new Error(
      `[source-proof] Unknown SourceChip: ${chip}. ` +
        `Allowed: ${SOURCE_CHIP_KEYS.join(', ')}`,
    );
  }
  const label = SOURCE_CHIP_LABELS[chipKey];
  const el = makeEl('span', `omni-source-chip omni-source-chip--${chipKey.replace(/_/g, '-')}`, label);
  el.setAttribute('data-source', chipKey);
  const ariaLabel = options && options.ariaLabel ? String(options.ariaLabel) : `Source: ${label}`;
  el.setAttribute('aria-label', ariaLabel);
  return el;
}

/* ──────────────────────────────────────────────────────────────────────
 * mapSourceIdToChipLabel
 *
 * Best-effort mapping from a backend-supplied source_id (and optional
 * freshness) to a controlled SourceChip key. Unknown sources are reported
 * as 'no_verified_source' rather than being invented as a new chip.
 *
 *   mapSourceIdToChipLabel('local_navroute')              → 'local_snapshot'
 *   mapSourceIdToChipLabel('Journal')                     → 'local_event_history'
 *   mapSourceIdToChipLabel('Status.json', 'fresh')        → 'local_telemetry'
 *   mapSourceIdToChipLabel('disabled')                    → 'external_disabled'
 *   mapSourceIdToChipLabel('unknown')                     → 'no_verified_source'
 *   mapSourceIdToChipLabel('anything', 'stale')           → 'stale'
 * ────────────────────────────────────────────────────────────────────── */
export function mapSourceIdToChipLabel(sourceId, freshness) {
  const fkey = normalizeKey(freshness);
  if (fkey === 'stale') return 'stale';

  const key = normalizeKey(sourceId);
  if (!key) return 'no_verified_source';

  if (LOCAL_TELEMETRY_SOURCE_IDS.has(key)) return 'local_telemetry';
  if (LOCAL_EVENT_HISTORY_SOURCE_IDS.has(key)) return 'local_event_history';
  if (LOCAL_SNAPSHOT_SOURCE_IDS.has(key)) return 'local_snapshot';
  if (MANUAL_SOURCE_IDS.has(key)) return 'commander_entered';
  if (KNOWLEDGE_REFERENCE_SOURCE_IDS.has(key)) return 'knowledge_reference';
  if (DISABLED_SOURCE_IDS.has(key)) return 'external_disabled';
  if (NO_VERIFIED_SOURCE_IDS.has(key)) return 'no_verified_source';

  if (/\.json$/i.test(key)) return 'local_snapshot';
  return 'no_verified_source';
}

/* ──────────────────────────────────────────────────────────────────────
 * mapFactToState
 *
 * Maps a backend-supplied fact/snapshot record to a controlled state key.
 * Returns 'available' when the fact has a non-empty value and no stale or
 * unsupported markers; otherwise classifies the absence honestly.
 * ────────────────────────────────────────────────────────────────────── */
export function mapFactToState(fact) {
  if (fact === null || fact === undefined || typeof fact !== 'object') {
    return 'not_loaded';
  }

  const freshness = normalizeKey(fact.freshness ?? fact.freshness_label);
  const source = normalizeKey(fact.source ?? fact.source_id);
  const fallback = fact.fallback;
  const value = fact.value;

  if (freshness === 'stale') return 'stale';
  if (DISABLED_SOURCE_IDS.has(source)) return 'disabled';
  if (source === 'unsupported') return 'unsupported';
  if (source === 'no_verified_source') return 'no_verified_source';

  const hasValue = value !== null && value !== undefined && value !== '';
  if (hasValue) return 'available';

  if (typeof fallback === 'string' && /no route/i.test(fallback)) return 'no_route_plotted';
  if (typeof fallback === 'string' && /not loaded/i.test(fallback)) return 'not_loaded';
  if (typeof fallback === 'string' && /no verified/i.test(fallback)) return 'no_verified_source';
  if (typeof fallback === 'string' && /unsupported/i.test(fallback)) return 'unsupported';

  return 'not_loaded';
}

/* ──────────────────────────────────────────────────────────────────────
 * ProofDrawer
 *
 * §9 — collapsed-by-default disclosure that exposes the proof fields the
 * backend already provides (source label, timestamp, freshness, truth
 * class, caveat, raw value, optional activity-log linkage). Does not
 * invent proof — only renders the fields actually present on `proof`.
 *
 *   createProofDrawer({
 *     source, timestamp, freshness, truthClass, caveat, rawValue,
 *     activityLogRef, extra,
 *   }, { summary? = 'Proof', open? = false })
 *
 * Returns a <details> element. Safe DOM throughout.
 * ────────────────────────────────────────────────────────────────────── */
export function createProofDrawer(proof, options) {
  const opts = options || {};
  const summary = typeof opts.summary === 'string' && opts.summary.length > 0
    ? opts.summary
    : 'Proof';
  const drawer = makeEl('details', 'omni-proof-drawer');
  if (opts.open) drawer.setAttribute('open', '');

  const summaryEl = makeEl('summary', 'omni-proof-drawer-summary', summary);
  drawer.appendChild(summaryEl);

  const body = makeEl('div', 'omni-proof-drawer-body');
  drawer.appendChild(body);

  if (!proof || typeof proof !== 'object') {
    appendTextChild(body, 'p', 'No proof fields supplied.', 'omni-proof-drawer-empty');
    return drawer;
  }

  const list = makeEl('dl', 'omni-proof-drawer-list');
  appendProofField(list, 'Source', proof.source);
  appendProofField(list, 'Observed', proof.timestamp);
  appendProofField(list, 'Freshness', proof.freshness);
  appendProofField(list, 'Truth class', proof.truthClass);
  appendProofField(list, 'Raw value', proof.rawValue);
  if (list.childNodes.length > 0) body.appendChild(list);

  if (typeof proof.caveat === 'string' && proof.caveat.length > 0) {
    appendTextChild(body, 'p', proof.caveat, 'omni-proof-drawer-caveat');
  }

  if (proof.activityLogRef instanceof Element) {
    body.appendChild(proof.activityLogRef);
  } else if (typeof proof.activityLogRef === 'string' && proof.activityLogRef.length > 0) {
    const link = makeEl('a', 'omni-proof-drawer-log', 'View source event');
    link.setAttribute('href', '#/activity-log');
    link.setAttribute('data-activity-log-ref', proof.activityLogRef);
    body.appendChild(link);
  }

  if (proof.extra instanceof Element) {
    body.appendChild(proof.extra);
  }

  return drawer;
}

function appendProofField(list, label, value) {
  if (value === null || value === undefined || value === '') return;
  appendTextChild(list, 'dt', label, 'omni-proof-drawer-field-label');
  appendTextChild(list, 'dd', String(value), 'omni-proof-drawer-field-value');
}

/* ──────────────────────────────────────────────────────────────────────
 * MissingFieldsSummary
 *
 * §11 / §9 — grouped, scan-friendly reduction of repeated fallback rows.
 * Renders a compact summary line (state + count) above a collapsed
 * details element listing the affected field names.
 *
 *   createMissingFieldsSummary({
 *     state: 'no_verified_source',
 *     fields: ['Prospector controller', 'Collector controller', ...],
 *     summaryText? = 'X fields have no verified local source.',
 *     drawerSummary? = 'Show missing fields',
 *   })
 *
 * Returns a <section>. Safe DOM throughout. Each field name is rendered
 * via textContent.
 * ────────────────────────────────────────────────────────────────────── */
export function createMissingFieldsSummary(options) {
  const opts = options || {};
  const fields = Array.isArray(opts.fields) ? opts.fields.filter((f) => typeof f === 'string' && f.length > 0) : [];
  const stateKey = normalizeKey(opts.state).replace(/-/g, '_');
  const validState = Object.prototype.hasOwnProperty.call(OMNI_STATE_LABELS, stateKey)
    ? stateKey
    : 'no_verified_source';

  const wrap = makeEl('section', 'omni-missing-fields-summary');
  wrap.setAttribute('role', 'group');
  wrap.setAttribute('data-state', validState);

  const head = makeEl('div', 'omni-missing-fields-summary-head');
  head.appendChild(createOmniStateBadge(validState));

  const count = fields.length;
  const stateLabel = OMNI_STATE_LABELS[validState].toLowerCase();
  const defaultText = `${count} ${count === 1 ? 'field has' : 'fields have'} ${stateLabel}.`;
  const summaryText = typeof opts.summaryText === 'string' && opts.summaryText.length > 0
    ? opts.summaryText
    : defaultText;
  head.appendChild(makeEl('p', 'omni-missing-fields-summary-text', summaryText));
  wrap.appendChild(head);

  if (count > 0) {
    const drawer = makeEl('details', 'omni-missing-fields-drawer');
    const drawerSummary = typeof opts.drawerSummary === 'string' && opts.drawerSummary.length > 0
      ? opts.drawerSummary
      : 'Show missing fields';
    drawer.appendChild(makeEl('summary', 'omni-missing-fields-drawer-summary', drawerSummary));
    const list = makeEl('ul', 'omni-missing-fields-drawer-list');
    fields.forEach((field) => {
      appendTextChild(list, 'li', field, 'omni-missing-fields-drawer-item');
    });
    drawer.appendChild(list);
    wrap.appendChild(drawer);
  }

  return wrap;
}
