/**
 * UI v3 frame primitives.
 *
 * Small safe-DOM helpers for cockpit chrome. Dynamic values use
 * createElement/textContent; SVG icons are built from static local data.
 */

(function () {
  'use strict';

  const SVG_NS = 'http://www.w3.org/2000/svg';

  const ICON_DATA = {
    'dashboard-home': [
      { tag: 'rect', attrs: { x: '3', y: '3', width: '8', height: '8' } },
      { tag: 'rect', attrs: { x: '13', y: '3', width: '8', height: '8' } },
      { tag: 'rect', attrs: { x: '3', y: '13', width: '18', height: '8' } },
    ],
    operations: [
      { tag: 'rect', attrs: { x: '3', y: '3', width: '7', height: '7' } },
      { tag: 'rect', attrs: { x: '14', y: '3', width: '7', height: '7' } },
      { tag: 'rect', attrs: { x: '3', y: '14', width: '7', height: '7' } },
      { tag: 'rect', attrs: { x: '14', y: '14', width: '7', height: '7' } },
    ],
    intel: [
      { tag: 'circle', attrs: { cx: '11', cy: '11', r: '7' } },
      { tag: 'line', attrs: { x1: '16', y1: '16', x2: '21', y2: '21' } },
    ],
    navigation: [
      { tag: 'polygon', attrs: { points: '12 3 21 12 12 21 3 12' } },
      { tag: 'circle', attrs: { cx: '12', cy: '12', r: '2' } },
    ],
    engineering: [
      { tag: 'circle', attrs: { cx: '12', cy: '8', r: '3' } },
      { tag: 'path', attrs: { d: 'M5 20c1-4 4-6 7-6s6 2 7 6' } },
    ],
    squadron: [
      { tag: 'circle', attrs: { cx: '8', cy: '9', r: '3' } },
      { tag: 'circle', attrs: { cx: '16', cy: '9', r: '3' } },
      { tag: 'path', attrs: { d: 'M3 20c1.5-3 4-4 5-4M16 16c1 0 3.5 1 5 4' } },
    ],
    log: [
      { tag: 'line', attrs: { x1: '5', y1: '7', x2: '19', y2: '7' } },
      { tag: 'line', attrs: { x1: '5', y1: '12', x2: '19', y2: '12' } },
      { tag: 'line', attrs: { x1: '5', y1: '17', x2: '14', y2: '17' } },
    ],
    systems: [
      { tag: 'rect', attrs: { x: '4', y: '4', width: '16', height: '16', rx: '1' } },
      { tag: 'line', attrs: { x1: '9', y1: '4', x2: '9', y2: '20' } },
      { tag: 'line', attrs: { x1: '4', y1: '9', x2: '20', y2: '9' } },
    ],
    'station-badge': [
      { tag: 'circle', attrs: { cx: '12', cy: '12', r: '8' } },
      { tag: 'path', attrs: { d: 'M12 4v16M4 12h16' } },
    ],
    'settings-gear': [
      { tag: 'circle', attrs: { cx: '12', cy: '12', r: '3' } },
      { tag: 'path', attrs: { d: 'M19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.5-2.4 1a7.4 7.4 0 0 0-2-1.1L14.2 3h-4.4l-.3 2.7a7.4 7.4 0 0 0-2 1.1l-2.4-1-2 3.5 2 1.5A7 7 0 0 0 5 12c0 .4 0 .8.1 1.2l-2 1.5 2 3.5 2.4-1a7.4 7.4 0 0 0 2 1.1l.3 2.7h4.4l.3-2.7a7.4 7.4 0 0 0 2-1.1l2.4 1 2-3.5-2-1.5c.1-.4.1-.8.1-1.2z' } },
    ],
    'privacy-shield': [
      { tag: 'path', attrs: { d: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z' } },
      { tag: 'path', attrs: { d: 'M9 12l2 2 4-5' } },
    ],
    'sources-diagnostics': [
      { tag: 'circle', attrs: { cx: '12', cy: '12', r: '9' } },
      { tag: 'path', attrs: { d: 'M8 12h8M12 8v8' } },
      { tag: 'circle', attrs: { cx: '12', cy: '12', r: '2' } },
    ],
    resources: [
      { tag: 'path', attrs: { d: 'M3 3v18h18' } },
      { tag: 'path', attrs: { d: 'M7 16V8M12 16v-4M17 16V5' } },
    ],
    about: [
      { tag: 'circle', attrs: { cx: '12', cy: '12', r: '9' } },
      { tag: 'line', attrs: { x1: '12', y1: '10', x2: '12', y2: '17' } },
      { tag: 'line', attrs: { x1: '12', y1: '7', x2: '12.01', y2: '7' } },
    ],
    'future-capabilities': [
      { tag: 'circle', attrs: { cx: '12', cy: '12', r: '9' } },
      { tag: 'path', attrs: { d: 'M9 12h6M12 9v6' } },
      { tag: 'path', attrs: { d: 'M17 7l2-2M7 17l-2 2' } },
    ],
    'chevron-right': [
      { tag: 'polyline', attrs: { points: '9 18 15 12 9 6' } },
    ],
    plus: [
      { tag: 'line', attrs: { x1: '12', y1: '5', x2: '12', y2: '19' } },
      { tag: 'line', attrs: { x1: '5', y1: '12', x2: '19', y2: '12' } },
    ],
    search: [
      { tag: 'circle', attrs: { cx: '11', cy: '11', r: '7' } },
      { tag: 'line', attrs: { x1: '16', y1: '16', x2: '21', y2: '21' } },
    ],
    'compass-diamond': [
      { tag: 'polygon', attrs: { points: '12 2 20 12 12 22 4 12' } },
      { tag: 'polygon', attrs: { points: '12 6 15 12 12 18 9 12' } },
    ],
    fallback: [
      { tag: 'rect', attrs: { x: '4', y: '4', width: '16', height: '16' } },
      { tag: 'line', attrs: { x1: '8', y1: '8', x2: '16', y2: '16' } },
      { tag: 'line', attrs: { x1: '16', y1: '8', x2: '8', y2: '16' } },
    ],
  };

  function makeEl(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined && text !== null) el.textContent = String(text);
    return el;
  }

  function createUiv3StatusDot(kind, label) {
    const safeKind = ['ok', 'warn', 'alert', 'info'].includes(kind) ? kind : 'info';
    const dot = makeEl('span', `uiv3-dot uiv3-dot--${safeKind}`);
    dot.setAttribute('aria-label', label || `${safeKind} status`);
    return dot;
  }

  function createUiv3Eyebrow(text) {
    return makeEl('span', 'uiv3-eyebrow', text || '');
  }

  function createUiv3CornerBracketFrame(node) {
    const frame = makeEl('div', 'uiv3-corner-frame');
    const inner = makeEl('div', 'uiv3-corner-frame-inner');
    if (node instanceof Node) inner.appendChild(node);
    frame.appendChild(inner);
    return frame;
  }

  function createUiv3Icon(name) {
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.6');
    svg.setAttribute('stroke-linecap', 'round');
    svg.setAttribute('stroke-linejoin', 'round');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');

    let data = ICON_DATA[name];
    if (!data) {
      data = ICON_DATA.fallback;
      svg.setAttribute('data-uiv3-icon-fallback', 'true');
    }

    data.forEach((item) => {
      const child = document.createElementNS(SVG_NS, item.tag);
      Object.entries(item.attrs).forEach(([attr, value]) => {
        child.setAttribute(attr, value);
      });
      svg.appendChild(child);
    });

    return svg;
  }

  function mountUiv3Icons(root) {
    const scope = root || document;
    scope.querySelectorAll('[data-uiv3-icon]').forEach((target) => {
      const name = target.getAttribute('data-uiv3-icon');
      target.replaceChildren(createUiv3Icon(name));
    });
  }

  window.Uiv3Frame = {
    createUiv3StatusDot,
    createUiv3Eyebrow,
    createUiv3CornerBracketFrame,
    createUiv3Icon,
    mountUiv3Icons,
    icons: {
      has(name) {
        return Boolean(ICON_DATA[name]);
      },
      get names() {
        return Object.keys(ICON_DATA).filter((name) => name !== 'fallback');
      },
    },
  };

  document.addEventListener('DOMContentLoaded', () => {
    mountUiv3Icons(document);
  });
}());
