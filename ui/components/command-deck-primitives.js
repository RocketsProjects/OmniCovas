/**
 * OmniCOVAS — Command Deck Primitives (v2 UI/UX redesign).
 *
 * Pilot-first primitives for the Primary / Support / Watch / Interrupt model.
 * All dynamic values render via createElement + textContent per ADR 0003.
 *
 * Primitives:
 *   - createCommandContextSpine  — compact ship/system/station/route header line
 *   - createWatchStrip           — compact always-on vitals row
 *   - createInterruptBanner      — critical-state elevation banner
 *   - createOperationHeader      — operation title + question + objective
 *   - createSupportCard          — support system tile
 *   - createPrimaryActionBlock   — single emphasised next action
 *   - createQuickToolStrip       — small pinned tool/quick action strip
 *   - createSearchPanel          — search-first input panel
 *   - createOperationSelector    — manual operation picker
 *   - createProofToggle          — compact "Show proof" toggle wrapping a node
 */

'use strict';

import { setSafeText } from '../utils/safe-dom.js';

function makeEl(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined && text !== null) setSafeText(el, text);
  return el;
}

function buildAction(action, baseClass) {
  if (!action || !action.label) return null;
  const el = action.href ? makeEl('a', baseClass, action.label) : makeEl('button', baseClass, action.label);
  if (action.href) el.setAttribute('href', String(action.href));
  if (!action.href) el.setAttribute('type', 'button');
  if (typeof action.onClick === 'function') el.addEventListener('click', action.onClick);
  return el;
}

/* ──────────────────────────────────────────────────────────────────────
 * CommandContextSpine
 *
 * Single-line context strip used at the top of pilot surfaces.
 *
 *   items: [{ label, value }]
 * ────────────────────────────────────────────────────────────────────── */
export function createCommandContextSpine(items, options) {
  const spine = makeEl('div', 'command-spine');
  spine.setAttribute('role', 'region');
  spine.setAttribute('aria-label', options?.ariaLabel || 'Commander context');

  (items || []).forEach((entry, index) => {
    if (index > 0) {
      const sep = makeEl('span', 'command-spine-sep', '·');
      sep.setAttribute('aria-hidden', 'true');
      spine.appendChild(sep);
    }
    const item = makeEl('span', 'command-spine-item');
    item.setAttribute('data-item', entry.id || '');
    item.appendChild(makeEl('span', 'command-spine-label', entry.label || ''));
    item.appendChild(makeEl('span', 'command-spine-value', entry.value ?? '—'));
    spine.appendChild(item);
  });

  if ((items || []).length === 0) {
    spine.appendChild(makeEl('span', 'command-spine-empty', 'Awaiting telemetry'));
  }

  return spine;
}

/* ──────────────────────────────────────────────────────────────────────
 * WatchStrip
 *
 * Compact always-on watch row. Severity drives visual prominence.
 *
 *   items: [{ id, label, value, severity }]
 *   severity ∈ 'ok' | 'warning' | 'critical' | 'unknown'
 * ────────────────────────────────────────────────────────────────────── */
const WATCH_SEVERITIES = new Set(['ok', 'warning', 'critical', 'unknown']);

export function createWatchStrip(model, options) {
  const items = Array.isArray(model?.items) ? model.items : [];
  const strip = makeEl('section', 'watch-strip');
  strip.setAttribute('role', 'region');
  strip.setAttribute('aria-label', options?.ariaLabel || 'Watch — ship and route vitals');

  items.forEach((entry) => {
    const sev = WATCH_SEVERITIES.has(entry.severity) ? entry.severity : 'unknown';
    const cell = makeEl('div', `watch-strip-cell watch-strip-cell--${sev}`);
    cell.setAttribute('data-watch', entry.id || '');
    cell.setAttribute('data-severity', sev);
    cell.appendChild(makeEl('span', 'watch-strip-label', entry.label || ''));
    cell.appendChild(makeEl('span', 'watch-strip-value', entry.value ?? '—'));
    strip.appendChild(cell);
  });

  return strip;
}

/* ──────────────────────────────────────────────────────────────────────
 * InterruptBanner
 *
 * Critical/warning elevation banner. Returns null when no interrupts.
 *
 *   interrupts: [{ id, severity, label, detail }]
 *   options: { onResolveAction?: { label, onClick, href } }
 * ────────────────────────────────────────────────────────────────────── */
export function createInterruptBanner(interrupts, options) {
  const list = Array.isArray(interrupts) ? interrupts.slice() : [];
  if (list.length === 0) return null;

  const hasCritical = list.some(i => i?.severity === 'critical');
  const banner = makeEl('section',
    `interrupt-banner interrupt-banner--${hasCritical ? 'critical' : 'warning'}`);
  banner.setAttribute('role', 'alert');
  banner.setAttribute('aria-live', 'assertive');
  banner.setAttribute('data-severity', hasCritical ? 'critical' : 'warning');

  const head = makeEl('div', 'interrupt-banner-head');
  head.appendChild(makeEl('span', 'interrupt-banner-kicker',
    hasCritical ? 'Critical' : 'Attention'));
  head.appendChild(makeEl('span', 'interrupt-banner-count',
    `${list.length} active`));
  banner.appendChild(head);

  const ul = makeEl('ul', 'interrupt-banner-list');
  ul.setAttribute('role', 'list');
  list.forEach((item) => {
    const li = makeEl('li', `interrupt-banner-item interrupt-banner-item--${item.severity || 'warning'}`);
    li.appendChild(makeEl('span', 'interrupt-banner-label', item.label || ''));
    if (item.detail) li.appendChild(makeEl('span', 'interrupt-banner-detail', item.detail));
    ul.appendChild(li);
  });
  banner.appendChild(ul);

  const actionEl = buildAction(options?.onResolveAction, 'interrupt-banner-action');
  if (actionEl) banner.appendChild(actionEl);

  return banner;
}

/* ──────────────────────────────────────────────────────────────────────
 * OperationHeader
 *
 *   { operation, title, question, objective?, statusText? }
 * ────────────────────────────────────────────────────────────────────── */
export function createOperationHeader(options) {
  const { operation, title, question, objective, statusText } = options || {};
  const header = makeEl('header', 'operation-header');
  if (operation) header.setAttribute('data-operation', operation);
  header.setAttribute('role', 'region');
  if (title) header.setAttribute('aria-label', String(title));

  header.appendChild(makeEl('p', 'operation-header-kicker', operation ? 'Operation' : ''));
  if (title) header.appendChild(makeEl('h1', 'operation-header-title', title));
  if (question) header.appendChild(makeEl('p', 'operation-header-question', question));
  if (objective) header.appendChild(makeEl('p', 'operation-header-objective', objective));
  if (statusText) header.appendChild(makeEl('p', 'operation-header-status', statusText));
  return header;
}

/* ──────────────────────────────────────────────────────────────────────
 * SupportCard
 *
 *   { id, label, summary, route?, emptyAction?, empty?, onOpen? }
 * ────────────────────────────────────────────────────────────────────── */
export function createSupportCard(options) {
  const { id, label, summary, route, emptyAction, empty, onOpen } = options || {};
  const card = makeEl('article', `support-card${empty ? ' support-card--empty' : ''}`);
  if (id) card.setAttribute('data-support', id);
  card.setAttribute('role', 'region');
  if (label) card.setAttribute('aria-label', `${label} support`);

  card.appendChild(makeEl('h3', 'support-card-title', label || ''));
  card.appendChild(makeEl('p', 'support-card-summary', summary || ''));

  if (route || onOpen) {
    const action = makeEl(route ? 'a' : 'button', 'support-card-action', `Open ${label || 'support'}`);
    if (route) action.setAttribute('href', String(route));
    else action.setAttribute('type', 'button');
    if (typeof onOpen === 'function') action.addEventListener('click', onOpen);
    card.appendChild(action);
  }

  if (empty && emptyAction) {
    card.appendChild(makeEl('p', 'support-card-empty-hint', emptyAction));
  }

  return card;
}

/* ──────────────────────────────────────────────────────────────────────
 * PrimaryActionBlock
 *
 *   { label, hint?, route?, onClick? }
 * ────────────────────────────────────────────────────────────────────── */
export function createPrimaryActionBlock(action) {
  if (!action || !action.label) return null;
  const block = makeEl('section', 'primary-action');
  block.setAttribute('role', 'region');
  block.setAttribute('aria-label', 'Primary next action');

  block.appendChild(makeEl('p', 'primary-action-kicker', 'Next action'));
  const button = buildAction({
    label: action.label,
    href: action.route || action.href,
    onClick: action.onClick,
  }, 'primary-action-button');
  if (button) block.appendChild(button);
  if (action.hint) block.appendChild(makeEl('p', 'primary-action-hint', action.hint));
  return block;
}

/* ──────────────────────────────────────────────────────────────────────
 * QuickToolStrip
 *
 *   tools: [{ id, label, route?, onClick? }]
 * ────────────────────────────────────────────────────────────────────── */
export function createQuickToolStrip(tools, options) {
  const list = Array.isArray(tools) ? tools : [];
  const strip = makeEl('nav', 'quick-tools');
  strip.setAttribute('role', 'group');
  strip.setAttribute('aria-label', options?.ariaLabel || 'Quick tools');

  list.forEach((tool) => {
    const btn = buildAction({
      label: tool.label,
      href: tool.route || tool.href,
      onClick: tool.onClick,
    }, 'quick-tool');
    if (btn) {
      if (tool.id) btn.setAttribute('data-tool', tool.id);
      strip.appendChild(btn);
    }
  });

  return strip;
}

/* ──────────────────────────────────────────────────────────────────────
 * SearchPanel
 *
 *   { modes: [{ id, label, placeholder }], initialMode?, onSearch?(query, mode) }
 * ────────────────────────────────────────────────────────────────────── */
export function createSearchPanel(options) {
  const modes = Array.isArray(options?.modes) ? options.modes : [];
  const initialMode = options?.initialMode || (modes[0]?.id || 'search');

  const panel = makeEl('section', 'search-panel');
  panel.setAttribute('role', 'search');
  panel.setAttribute('aria-label', options?.ariaLabel || 'Intel search');

  const tabs = makeEl('div', 'search-panel-modes');
  tabs.setAttribute('role', 'tablist');
  modes.forEach((mode) => {
    const tab = makeEl('button',
      `search-panel-mode${mode.id === initialMode ? ' is-active' : ''}`,
      mode.label);
    tab.setAttribute('type', 'button');
    tab.setAttribute('role', 'tab');
    tab.setAttribute('data-mode', mode.id);
    tab.setAttribute('aria-selected', mode.id === initialMode ? 'true' : 'false');
    tab.addEventListener('click', () => {
      panel.querySelectorAll('.search-panel-mode').forEach(b => {
        b.classList.remove('is-active');
        b.setAttribute('aria-selected', 'false');
      });
      tab.classList.add('is-active');
      tab.setAttribute('aria-selected', 'true');
      const input = panel.querySelector('.search-panel-input');
      if (input) {
        input.setAttribute('placeholder', mode.placeholder || '');
        input.setAttribute('data-mode', mode.id);
        input.focus();
      }
    });
    tabs.appendChild(tab);
  });
  panel.appendChild(tabs);

  const row = makeEl('div', 'search-panel-row');
  const input = document.createElement('input');
  input.className = 'search-panel-input';
  input.id = 'intel-search-input';
  input.name = 'intel-search-input';
  input.setAttribute('type', 'search');
  input.setAttribute('data-mode', initialMode);
  const initial = modes.find(m => m.id === initialMode) || modes[0];
  if (initial?.placeholder) input.setAttribute('placeholder', initial.placeholder);
  input.setAttribute('aria-label', 'Intel search query');
  row.appendChild(input);

  const submit = makeEl('button', 'search-panel-submit', 'Search');
  submit.setAttribute('type', 'button');
  submit.addEventListener('click', () => {
    if (typeof options?.onSearch === 'function') {
      options.onSearch(input.value || '', input.getAttribute('data-mode') || initialMode);
    }
  });
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') submit.click();
  });
  row.appendChild(submit);

  panel.appendChild(row);
  return panel;
}

/* ──────────────────────────────────────────────────────────────────────
 * OperationSelector
 *
 *   options: { operations: [{ id, label }], current, onSelect(id) }
 * ────────────────────────────────────────────────────────────────────── */
export function createOperationSelector(options) {
  const list = Array.isArray(options?.operations) ? options.operations : [];
  const current = options?.current || null;
  const onSelect = typeof options?.onSelect === 'function' ? options.onSelect : null;

  const sel = makeEl('nav', 'operation-selector');
  sel.setAttribute('role', 'tablist');
  sel.setAttribute('aria-label', 'Active operation');

  list.forEach((op) => {
    const btn = makeEl('button',
      `operation-selector-tab${op.id === current ? ' is-active' : ''}`,
      op.label || op.id);
    btn.setAttribute('type', 'button');
    btn.setAttribute('role', 'tab');
    btn.setAttribute('data-operation', op.id);
    btn.setAttribute('aria-selected', op.id === current ? 'true' : 'false');
    btn.addEventListener('click', () => {
      if (onSelect) onSelect(op.id);
    });
    sel.appendChild(btn);
  });

  return sel;
}

/* ──────────────────────────────────────────────────────────────────────
 * ProofToggle
 *
 * Wraps a Node (raw proof rows, source chips) in a native <details> drawer
 * with a compact summary line. Caller is responsible for passing safe
 * content; createDetailDrawer in command-primitives.js works equally well,
 * but this name signals proof-specific intent.
 * ────────────────────────────────────────────────────────────────────── */
export function createProofToggle(content, summary) {
  const drawer = makeEl('details', 'proof-toggle');
  const sum = makeEl('summary', 'proof-toggle-summary', summary || 'Show proof');
  drawer.appendChild(sum);
  const body = makeEl('div', 'proof-toggle-body');
  if (content instanceof Node) {
    body.appendChild(content);
  } else if (content !== undefined && content !== null) {
    setSafeText(body, content);
  }
  drawer.appendChild(body);
  return drawer;
}
