/**
 * OmniCOVAS — Shared Command-Deck Visual Primitives.
 *
 * Phase 7.5 foundation (PB07.5-01).
 *
 * Pure DOM helper functions. Every dynamic value goes through textContent
 * (createElement + textContent) per ADR 0003. No innerHTML / outerHTML /
 * insertAdjacentHTML / document.write / eval / new Function / string timers.
 *
 * Route-specific playbooks (PB07.5-02..06) consume these primitives.
 *
 * Patterns:
 *   - createRouteHero
 *   - createCommandCard
 *   - createStatusBadge
 *   - createActionLinkGroup
 *   - createDetailDrawer
 *   - createEmptyState
 *   - createReservedFeatureRow
 */

'use strict';

import { setSafeText } from '../utils/safe-dom.js';

export {
  commodityComparisonKey,
  formatCredits,
  formatDisplayValue,
  formatLightYears,
  formatPercent,
  formatTons,
  normalizeCommodityName,
  normalizeMarketCategory,
  normalizeModuleName,
  normalizeShipName,
  normalizeSourceLabel,
  normalizeTruthClass,
} from '../utils/display-names.js';

export {
  createCommandContextSpine,
  createWatchStrip,
  createInterruptBanner,
  createOperationHeader,
  createSupportCard,
  createPrimaryActionBlock,
  createQuickToolStrip,
  createSearchPanel,
  createOperationSelector,
  createProofToggle,
} from './command-deck-primitives.js';

/* Allowed StatusBadge variants — keeps badges short and prevents
 * Audit-Mode caveat strings from leaking into the badge surface. */
export const STATUS_BADGE_VARIANTS = Object.freeze([
  'live',
  'off',
  'locked',
  'reserved',
  'not-loaded',
  'stale',
  'cached',
  'available',
  'needs-setup',
  'disabled',
  'requires-auth',
  'local-only',
]);

const STATUS_BADGE_LABELS = Object.freeze({
  live: 'Live',
  off: 'Off',
  locked: 'Locked',
  reserved: 'Reserved',
  'not-loaded': 'Not loaded',
  stale: 'Stale',
  cached: 'Cached',
  available: 'Available',
  'needs-setup': 'Needs setup',
  disabled: 'Disabled',
  'requires-auth': 'Requires Authorization',
  'local-only': 'Local-only',
});

/* Internal: element creation that always uses textContent for dynamic values. */
function makeEl(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined && text !== null) setSafeText(el, text);
  return el;
}

/* ──────────────────────────────────────────────────────────────────────
 * StatusBadge
 *
 * Short state pill. Variant controls color + canonical label.
 * Custom label is allowed but must remain short; sentence-length labels
 * are rejected so Audit-Mode caveat strings cannot leak in.
 * ────────────────────────────────────────────────────────────────────── */
export function createStatusBadge(variant, customLabel) {
  const variantKey = (variant || 'available').toString().toLowerCase();
  if (!STATUS_BADGE_VARIANTS.includes(variantKey)) {
    throw new Error(
      `[command-primitives] Unknown StatusBadge variant: ${variantKey}. ` +
        `Allowed: ${STATUS_BADGE_VARIANTS.join(', ')}`,
    );
  }
  let label = customLabel === undefined || customLabel === null
    ? STATUS_BADGE_LABELS[variantKey]
    : String(customLabel);
  if (label.length > 32) {
    throw new Error(
      `[command-primitives] StatusBadge label too long (${label.length} chars). ` +
        'Status badges are short pills; move long detail to a DetailDrawer or ProofDrawer.',
    );
  }
  const badge = makeEl('span', `status-badge status-badge--${variantKey}`, label);
  badge.setAttribute('data-variant', variantKey);
  return badge;
}

/* ──────────────────────────────────────────────────────────────────────
 * RouteHero
 *
 * Route landing band. Visually dominant on route entry.
 *
 *   { title, kicker?, statusText?, statusVariant?, primaryValues?, action? }
 *
 *   primaryValues: [{ label, value }] up to 4 entries
 *   action: { label, onClick, href }
 * ────────────────────────────────────────────────────────────────────── */
export function createRouteHero(options) {
  const { title, kicker, statusText, statusVariant, primaryValues, action } = options || {};

  const hero = makeEl('section', 'route-hero');
  hero.setAttribute('role', 'region');
  if (title) hero.setAttribute('aria-label', String(title));

  const top = makeEl('div', 'route-hero-top');
  if (kicker) top.appendChild(makeEl('p', 'route-hero-kicker', kicker));
  if (title) top.appendChild(makeEl('h1', 'route-hero-title', title));
  if (statusText) {
    const statusEl = makeEl('p', 'route-hero-status', statusText);
    if (statusVariant && STATUS_BADGE_VARIANTS.includes(statusVariant)) {
      statusEl.setAttribute('data-variant', statusVariant);
    }
    top.appendChild(statusEl);
  }
  hero.appendChild(top);

  if (Array.isArray(primaryValues) && primaryValues.length > 0) {
    const valuesGrid = makeEl('div', 'route-hero-values');
    primaryValues.slice(0, 4).forEach((entry) => {
      const item = makeEl('div', 'route-hero-value');
      item.appendChild(makeEl('span', 'route-hero-value-label', entry.label || ''));
      item.appendChild(makeEl('span', 'route-hero-value-figure', entry.value ?? ''));
      valuesGrid.appendChild(item);
    });
    hero.appendChild(valuesGrid);
  }

  if (action && action.label) {
    const actionEl = action.href ? makeEl('a', 'route-hero-action', action.label) : makeEl('button', 'route-hero-action', action.label);
    if (action.href) actionEl.setAttribute('href', String(action.href));
    if (!action.href) actionEl.setAttribute('type', 'button');
    if (typeof action.onClick === 'function') actionEl.addEventListener('click', action.onClick);
    hero.appendChild(actionEl);
  }

  return hero;
}

/* ──────────────────────────────────────────────────────────────────────
 * CommandCard
 *
 * Summary-first card. Detail content lives in a collapsed DetailDrawer.
 *
 *   { title, primaryValue?, statusBadge?, action?, detail? }
 *
 *   statusBadge: { variant, label? } or an existing element
 *   action:      { label, onClick, href }
 *   detail:      Node | string | () => Node   (rendered inside DetailDrawer)
 * ────────────────────────────────────────────────────────────────────── */
export function createCommandCard(options) {
  const { title, primaryValue, statusBadge, action, detail } = options || {};

  const card = makeEl('section', 'command-card');
  if (title) card.setAttribute('aria-label', String(title));

  const header = makeEl('header', 'command-card-header');
  if (title) header.appendChild(makeEl('h3', 'command-card-title', title));
  if (statusBadge) {
    if (statusBadge instanceof Element) {
      header.appendChild(statusBadge);
    } else if (typeof statusBadge === 'object') {
      header.appendChild(createStatusBadge(statusBadge.variant, statusBadge.label));
    }
  }
  card.appendChild(header);

  if (primaryValue !== undefined && primaryValue !== null && primaryValue !== '') {
    card.appendChild(makeEl('p', 'command-card-primary', primaryValue));
  }

  if (action && action.label) {
    const actionEl = action.href ? makeEl('a', 'command-card-action', action.label) : makeEl('button', 'command-card-action', action.label);
    if (action.href) actionEl.setAttribute('href', String(action.href));
    if (!action.href) actionEl.setAttribute('type', 'button');
    if (typeof action.onClick === 'function') actionEl.addEventListener('click', action.onClick);
    card.appendChild(actionEl);
  }

  if (detail) {
    card.appendChild(createDetailDrawer({ summary: 'Details', content: detail }));
  }

  return card;
}

/* ──────────────────────────────────────────────────────────────────────
 * ActionLinkGroup
 *
 * Replaces malformed adjacent inline anchors with a spaced, keyboard-
 * navigable, accessible group. Each link gets a delimiter element between
 * siblings so adjacent text content cannot run together.
 *
 *   links: [{ label, href?, onClick? }]
 *   options: { ariaLabel?, delimiter? }   default delimiter "·"
 * ────────────────────────────────────────────────────────────────────── */
export function createActionLinkGroup(links, options) {
  const { ariaLabel, delimiter } = options || {};
  const group = makeEl('nav', 'action-link-group');
  group.setAttribute('role', 'group');
  if (ariaLabel) group.setAttribute('aria-label', String(ariaLabel));

  const delim = delimiter ? String(delimiter) : '·';

  (links || []).forEach((link, index) => {
    if (index > 0) {
      const sep = makeEl('span', 'action-link-delimiter', delim);
      sep.setAttribute('aria-hidden', 'true');
      group.appendChild(sep);
    }
    const el = link.href ? makeEl('a', 'action-link', link.label) : makeEl('button', 'action-link', link.label);
    if (link.href) el.setAttribute('href', String(link.href));
    if (!link.href) el.setAttribute('type', 'button');
    if (typeof link.onClick === 'function') el.addEventListener('click', link.onClick);
    group.appendChild(el);
  });

  return group;
}

/* ──────────────────────────────────────────────────────────────────────
 * DetailDrawer
 *
 * Keyboard-accessible expandable details. Backed by native <details>/<summary>
 * so the disclosure pattern works without JS and supports keyboard activation
 * out of the box.
 *
 *   { summary, content, open? }
 *
 *   content: string | Node | () => (string | Node)
 * ────────────────────────────────────────────────────────────────────── */
export function createDetailDrawer(options) {
  const { summary, content, open } = options || {};
  const drawer = makeEl('details', 'detail-drawer');
  if (open) drawer.setAttribute('open', '');

  const summaryEl = makeEl('summary', 'detail-drawer-summary', summary || 'Details');
  drawer.appendChild(summaryEl);

  const body = makeEl('div', 'detail-drawer-body');
  const resolved = typeof content === 'function' ? content() : content;
  if (resolved instanceof Node) {
    body.appendChild(resolved);
  } else if (resolved !== undefined && resolved !== null) {
    setSafeText(body, resolved);
  }
  drawer.appendChild(body);

  return drawer;
}

/* ──────────────────────────────────────────────────────────────────────
 * EmptyState
 *
 * Three-line maximum: status / reason / optional action.
 *
 *   { status, reason?, action? }
 *
 *   action: { label, onClick?, href? }
 * ────────────────────────────────────────────────────────────────────── */
export function createEmptyState(options) {
  const { status, reason, action } = options || {};

  const wrap = makeEl('div', 'empty-state');
  wrap.setAttribute('role', 'status');

  wrap.appendChild(makeEl('p', 'empty-state-status', status || 'Unavailable'));
  if (reason) wrap.appendChild(makeEl('p', 'empty-state-reason', reason));

  if (action && action.label) {
    const actionEl = action.href ? makeEl('a', 'empty-state-action', action.label) : makeEl('button', 'empty-state-action', action.label);
    if (action.href) actionEl.setAttribute('href', String(action.href));
    if (!action.href) actionEl.setAttribute('type', 'button');
    if (typeof action.onClick === 'function') actionEl.addEventListener('click', action.onClick);
    wrap.appendChild(actionEl);
  }

  return wrap;
}

/* ──────────────────────────────────────────────────────────────────────
 * ReservedFeatureRow
 *
 * Compact row representing a not-yet-shipped feature. Visually subordinate
 * to live CommandCards. Never renders a toggle/checkbox so reserved
 * features cannot present as live controls.
 *
 *   { name, badge?, onInspect?, inspectLabel? }
 *
 *   badge: 'reserved' (default) or any STATUS_BADGE_VARIANTS value that
 *          is not a live-positive variant
 * ────────────────────────────────────────────────────────────────────── */
const RESERVED_ALLOWED_BADGE_VARIANTS = Object.freeze([
  'reserved',
  'locked',
  'disabled',
  'not-loaded',
  'needs-setup',
  'requires-auth',
  'off',
]);

export function createReservedFeatureRow(options) {
  const { name, badge, onInspect, inspectLabel } = options || {};

  const variant = badge && RESERVED_ALLOWED_BADGE_VARIANTS.includes(badge) ? badge : 'reserved';

  const row = makeEl('div', 'reserved-feature-row');
  row.setAttribute('role', 'group');
  if (name) row.setAttribute('aria-label', `${name} — ${STATUS_BADGE_LABELS[variant]}`);

  row.appendChild(makeEl('span', 'reserved-feature-name', name || 'Reserved feature'));
  row.appendChild(createStatusBadge(variant));

  if (typeof onInspect === 'function') {
    const btn = makeEl('button', 'reserved-feature-inspect', inspectLabel || 'Inspect');
    btn.setAttribute('type', 'button');
    btn.addEventListener('click', onInspect);
    row.appendChild(btn);
  }

  return row;
}

/* Convenience: list-style assertion used by tests to confirm a reserved
 * row contains no enabled form controls. */
export function reservedRowHasNoLiveControls(row) {
  if (!(row instanceof Element)) return true;
  const inputs = row.querySelectorAll('input, select, textarea');
  for (const input of inputs) {
    if (!input.disabled) return false;
  }
  return true;
}
