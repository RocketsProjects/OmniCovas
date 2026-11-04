/**
 * Commander-facing semantic language boundary.
 *
 * These helpers translate presentation state only. They never infer game
 * facts, change provenance, or turn missing evidence into a negative fact.
 */

export const COMMANDER_STATUS = Object.freeze({
  NOT_FITTED: 'not_fitted',
  NOT_CHECKED: 'not_checked',
  NOT_SUPPORTED: 'not_supported',
  OFF: 'off',
  OUT_OF_DATE: 'out_of_date',
  LAST_SEEN: 'last_seen',
  YOUR_PLAN: 'your_plan',
  GAME_OBSERVED: 'game_observed',
});

const STATUS_LABELS = Object.freeze({
  [COMMANDER_STATUS.NOT_FITTED]: 'Not fitted',
  [COMMANDER_STATUS.NOT_CHECKED]: 'Not checked',
  [COMMANDER_STATUS.NOT_SUPPORTED]: 'Not supported',
  [COMMANDER_STATUS.OFF]: 'Off',
  [COMMANDER_STATUS.OUT_OF_DATE]: 'Out of date',
  [COMMANDER_STATUS.LAST_SEEN]: 'Last seen',
  [COMMANDER_STATUS.YOUR_PLAN]: 'Your plan',
  [COMMANDER_STATUS.GAME_OBSERVED]: 'From your Journal',
});

export function commanderStatus(kind, subject, options = {}) {
  if (!STATUS_LABELS[kind]) throw new Error(`Unsupported Commander status: ${kind}`);
  const object = String(subject || '').trim();
  if (!object) throw new Error('Commander status requires a named subject');
  const observedAt = String(options.observedAt || '').trim();
  const label = STATUS_LABELS[kind];
  const text = kind === COMMANDER_STATUS.LAST_SEEN && observedAt
    ? `${object} — last seen ${observedAt}`
    : kind === COMMANDER_STATUS.OUT_OF_DATE && observedAt
      ? `${object} — out of date (last updated ${observedAt})`
      : `${object} — ${label.toLowerCase()}`;
  return Object.freeze({ kind, subject: object, label, text, observedAt: observedAt || null });
}

const ERROR_PATTERNS = Object.freeze([
  [/proposal action mismatch/i, 'That request no longer matches the open confirmation.'],
  [/unknown, expired, or already-used confirmation/i, 'This request is no longer active. Start it again.'],
  [/no consumable commander decision/i, 'This confirmation has expired. Start the action again.'],
  [/engineering persistence not initialized/i, 'Engineering could not open.'],
  [/operations campaign persistence not initialized/i, 'Operations could not load saved plans.'],
  [/statemanager not initiali[sz]ed|session factory not initiali[sz]ed/i, 'Local data could not open.'],
]);

export function commanderError(error, options = {}) {
  const raw = String(error?.message || error || '').trim();
  const task = String(options.task || 'This task').trim();
  const impact = String(options.impact || 'Nothing was changed.').trim();
  const recovery = String(options.recovery || 'Try again or open connection details.').trim();
  const mapped = ERROR_PATTERNS.find(([pattern]) => pattern.test(raw));
  const title = mapped?.[1] || `${task} could not open.`;
  return Object.freeze({
    title,
    impact,
    recovery,
    technicalDetail: raw || null,
  });
}

export function confirmationLabels(actionLabel) {
  const action = String(actionLabel || '').trim();
  if (!action) throw new Error('Confirmation requires an action label');
  return Object.freeze({ confirmLabel: action, cancelLabel: 'Cancel' });
}
