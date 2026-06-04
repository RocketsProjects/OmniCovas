/**
 * OmniCOVAS Internal SVG Icon System
 *
 * Provides a registry of minimalist SVG icons using safe DOM APIs.
 * Supports currentColor and token-controlled styling.
 */

(function() {
  'use strict';

  const SVG_NS = "http://www.w3.org/2000/svg";

  const ICON_DATA = {
    'dashboard': [
      { tag: 'rect', attrs: { x: '3', y: '3', width: '7', height: '7' } },
      { tag: 'rect', attrs: { x: '14', y: '3', width: '7', height: '7' } },
      { tag: 'rect', attrs: { x: '14', y: '14', width: '7', height: '7' } },
      { tag: 'rect', attrs: { x: '3', y: '14', width: '7', height: '7' } }
    ],
    'activity-log': [
      { tag: 'circle', attrs: { cx: '12', cy: '12', r: '10' } },
      { tag: 'polyline', attrs: { points: '12 6 12 12 16 14' } }
    ],
    'settings': [
      { tag: 'circle', attrs: { cx: '12', cy: '12', r: '3' } },
      { tag: 'path', attrs: { d: 'M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z' } }
    ],
    'privacy': [
      { tag: 'rect', attrs: { x: '3', y: '11', width: '18', height: '11', rx: '2', ry: '2' } },
      { tag: 'path', attrs: { d: 'M7 11V7a5 5 0 0 1 10 0v4' } }
    ],
    'resources': [
      { tag: 'path', attrs: { d: 'M3 3v18h18' } },
      { tag: 'path', attrs: { d: 'M7 16V8' } },
      { tag: 'path', attrs: { d: 'M12 16V12' } },
      { tag: 'path', attrs: { d: 'M17 16V4' } }
    ],
    'credits': [
      { tag: 'polygon', attrs: { points: '12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2' } }
    ],
    'future-systems': [
      { tag: 'circle', attrs: { cx: '12', cy: '12', r: '10' } },
      { tag: 'path', attrs: { d: 'M12 8l4 4-4 4M8 12h7' } }
    ],
    'combat': [
      { tag: 'circle', attrs: { cx: '12', cy: '12', r: '10' } },
      { tag: 'path', attrs: { d: 'M14.5 9l-5 5M9.5 9l5 5' } }
    ],
    'exploration': [
      { tag: 'circle', attrs: { cx: '12', cy: '12', r: '10' } },
      { tag: 'polygon', attrs: { points: '16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76' } }
    ],
    'trade-mining': [
      { tag: 'path', attrs: { d: 'M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z' } },
      { tag: 'polyline', attrs: { points: '3.27 6.96 12 12.01 20.73 6.96' } },
      { tag: 'line', attrs: { x1: '12', y1: '22.08', x2: '12', y2: '12' } }
    ],
    'squadron': [
      { tag: 'path', attrs: { d: 'M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2' } },
      { tag: 'circle', attrs: { cx: '9', cy: '7', r: '4' } },
      { tag: 'path', attrs: { d: 'M23 21v-2a4 4 0 0 0-3-3.87' } },
      { tag: 'path', attrs: { d: 'M16 3.13a4 4 0 0 1 0 7.75' } }
    ],
    'engineering': [
      { tag: 'path', attrs: { d: 'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z' } }
    ],
    'powerplay-bgs': [
      { tag: 'path', attrs: { d: 'M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z' } },
      { tag: 'line', attrs: { x1: '4', y1: '22', x2: '4', y2: '15' } }
    ],
    'ship': [
      { tag: 'path', attrs: { d: 'M12 2L2 7l10 5 10-5-10-5z' } },
      { tag: 'path', attrs: { d: 'M2 17l10 5 10-5' } },
      { tag: 'path', attrs: { d: 'M2 12l10 5 10-5' } }
    ],
    'shield': [
      { tag: 'path', attrs: { d: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z' } }
    ],
    'fuel': [
      { tag: 'path', attrs: { d: 'M12 2c-4 4.5-6 8-6 11a6 6 0 0 0 12 0c0-3-2-6.5-6-11z' } },
      { tag: 'path', attrs: { d: 'M9 13c0 2 1.5 3 3 3s3-1 3-3' } }
    ],
    'heat': [
      { tag: 'path', attrs: { d: 'M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z' } },
      { tag: 'circle', attrs: { cx: '12', cy: '17.5', r: '2', fill: 'currentColor' } },
      { tag: 'line', attrs: { x1: '12', y1: '6', x2: '12', y2: '13', 'stroke-width': '2' } }
    ],
    'cargo': [
      { tag: 'rect', attrs: { x: '3', y: '3', width: '18', height: '18', rx: '2', ry: '2' } },
      { tag: 'line', attrs: { x1: '3', y1: '9', x2: '21', y2: '9' } },
      { tag: 'line', attrs: { x1: '9', y1: '21', x2: '9', y2: '9' } }
    ],
    'modules': [
      { tag: 'rect', attrs: { x: '3', y: '3', width: '18', height: '18', rx: '2', ry: '2' } },
      { tag: 'line', attrs: { x1: '3', y1: '12', x2: '21', y2: '12' } },
      { tag: 'line', attrs: { x1: '12', y1: '3', x2: '12', y2: '21' } }
    ],
    'pips': [
      { tag: 'polygon', attrs: { points: '13 2 3 14 12 14 11 22 21 10 12 10 13 2' } }
    ],
    'rebuy': [
      { tag: 'rect', attrs: { x: '1', y: '4', width: '22', height: '16', rx: '2', ry: '2' } },
      { tag: 'line', attrs: { x1: '1', y1: '10', x2: '23', y2: '10' } }
    ],
    'connection': [
      { tag: 'path', attrs: { d: 'M5 12.55a11 11 0 0 1 14.08 0' } },
      { tag: 'path', attrs: { d: 'M1.42 9a16 16 0 0 1 21.16 0' } },
      { tag: 'path', attrs: { d: 'M8.53 16.11a6 6 0 0 1 6.95 0' } },
      { tag: 'line', attrs: { x1: '12', y1: '20', x2: '12.01', y2: '20' } }
    ],
    'warning': [
      { tag: 'path', attrs: { d: 'M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z' } },
      { tag: 'line', attrs: { x1: '12', y1: '9', x2: '12', y2: '13' } },
      { tag: 'line', attrs: { x1: '12', y1: '17', x2: '12.01', y2: '17' } }
    ],
    'critical': [
      { tag: 'circle', attrs: { cx: '12', cy: '12', r: '10' } },
      { tag: 'line', attrs: { x1: '15', y1: '9', x2: '9', y2: '15' } },
      { tag: 'line', attrs: { x1: '9', y1: '9', x2: '15', y2: '15' } }
    ],
    'lock': [
      { tag: 'rect', attrs: { x: '3', y: '11', width: '18', height: '11', rx: '2', ry: '2' } },
      { tag: 'path', attrs: { d: 'M7 11V7a5 5 0 0 1 10 0v4' } }
    ],
    'chevron': [
      { tag: 'polyline', attrs: { points: '9 18 15 12 9 6' } }
    ],
    'test-banner': [
      { tag: 'path', attrs: { d: 'M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z' } },
      { tag: 'line', attrs: { x1: '4', y1: '22', x2: '4', y2: '15' } }
    ],
    'fallback': [
      { tag: 'rect', attrs: { x: '2', y: '2', width: '20', height: '20', rx: '2', ry: '2' } },
      { tag: 'line', attrs: { x1: '12', y1: '8', x2: '12', y2: '12' } },
      { tag: 'line', attrs: { x1: '12', y1: '16', x2: '12.01', y2: '16' } }
    ]
  };

  const OmniIcons = {
    /**
     * Creates an SVG element for the given icon name.
     * @param {string} name - The name of the icon in the registry.
     * @returns {SVGSVGElement} The SVG element.
     */
    create(name) {
      const svg = document.createElementNS(SVG_NS, "svg");
      svg.setAttribute("viewBox", "0 0 24 24");
      svg.setAttribute("fill", "none");
      svg.setAttribute("stroke", "currentColor");
      svg.setAttribute("stroke-width", "2");
      svg.setAttribute("stroke-linecap", "round");
      svg.setAttribute("stroke-linejoin", "round");
      svg.setAttribute("aria-hidden", "true");
      svg.setAttribute("focusable", "false");

      let data = ICON_DATA[name];
      if (!data) {
        data = ICON_DATA['fallback'];
        svg.setAttribute('data-icon-fallback', 'true');
      }

      data.forEach(item => {
        const node = document.createElementNS(SVG_NS, item.tag);
        for (const [attr, value] of Object.entries(item.attrs)) {
          node.setAttribute(attr, value);
        }
        svg.appendChild(node);
      });

      return svg;
    },

    /**
     * Replaces all placeholders with SVG icons.
     * @param {HTMLElement} root - The root element to search within.
     */
    mountAll(root = document) {
      const placeholders = root.querySelectorAll('.ocv-icon[data-icon]');
      placeholders.forEach(el => {
        const name = el.getAttribute('data-icon');
        const iconSvg = this.create(name);

        // Clear existing content (e.g. old unicode icons) safely
        while (el.firstChild) {
          el.removeChild(el.firstChild);
        }

        el.appendChild(iconSvg);
      });
    },

    /**
     * Checks if an icon exists in the registry.
     * @param {string} name
     * @returns {boolean}
     */
    has(name) {
      return !!ICON_DATA[name];
    },

    /**
     * Returns an array of all registered icon names.
     */
    get names() {
      return Object.keys(ICON_DATA).filter(n => n !== 'fallback');
    }
  };

  window.OmniIcons = OmniIcons;

  // Mount on load
  document.addEventListener('DOMContentLoaded', () => {
    OmniIcons.mountAll();
  });

})();
