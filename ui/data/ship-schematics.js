/**
 * OmniCOVAS Ship Schematic Registry
 *
 * Provides ship key resolution, schematic data, and hotspot metadata.
 * Classic script — exposes window.OmniShipSchematics.
 * Safe: uses only safe DOM APIs — no dynamic HTML rendering sinks.
 */

(function () {
  'use strict';

  const SCHEMATICS = {
    sidewinder: {
      id: 'sidewinder',
      displayName: 'Sidewinder',
      aliases: [
        'sidewinder',
        'sidewindermk_i',
        'sidewinder_mk_i',
        'Sidewinder',
        'SideWinder'
      ],
      viewBox: '0 0 1000 560',
      supportedSubsystems: ['hull', 'shield', 'fuel', 'heat', 'cargo', 'modules', 'pips'],
      defaultPanelAnchors: {
        hull: 'left-top',
        shield: 'left-top',
        fuel: 'right-top',
        heat: 'right-mid',
        cargo: 'right-bottom',
        modules: 'left-bottom',
        pips: 'bottom-center'
      },
      shapes: [
        {
          type: 'polygon',
          className: 'ship-schematic-shape ship-schematic-outline',
          points: '500,80 625,175 790,255 710,325 660,468 582,510 418,510 340,468 290,325 210,255 375,175'
        },
        {
          type: 'line',
          className: 'ship-schematic-shape ship-schematic-line',
          x1: 500, y1: 80, x2: 500, y2: 510
        },
        {
          type: 'line',
          className: 'ship-schematic-shape ship-schematic-line',
          x1: 340, y1: 310, x2: 660, y2: 310
        },
        {
          type: 'circle',
          className: 'ship-schematic-shape ship-schematic-core',
          cx: 500, cy: 195, r: 28
        },
        {
          type: 'circle',
          className: 'ship-schematic-shape ship-schematic-line',
          cx: 388, cy: 482, r: 20
        },
        {
          type: 'circle',
          className: 'ship-schematic-shape ship-schematic-line',
          cx: 612, cy: 482, r: 20
        },
        {
          type: 'polyline',
          className: 'ship-schematic-shape ship-schematic-line',
          points: '440,195 460,215 500,195 540,215 560,195'
        }
      ],
      hotspots: [
        {
          id: 'hull',
          panelId: 'dash-panel-hull-shields',
          label: 'Toggle hull integrity telemetry',
          x: 155,
          y: 195,
          defaultExpanded: true,
          className: 'ship-schematic-hotspot ship-schematic-hotspot--hull'
        },
        {
          id: 'shield',
          panelId: 'dash-panel-hull-shields',
          label: 'Toggle shield status telemetry',
          x: 155,
          y: 270,
          defaultExpanded: true,
          className: 'ship-schematic-hotspot ship-schematic-hotspot--shield'
        },
        {
          id: 'fuel',
          panelId: 'dash-panel-fuel-jump',
          label: 'Toggle fuel and jump telemetry',
          x: 845,
          y: 195,
          defaultExpanded: true,
          className: 'ship-schematic-hotspot ship-schematic-hotspot--fuel'
        },
        {
          id: 'heat',
          panelId: 'dash-panel-heat-core',
          label: 'Toggle heat management telemetry',
          x: 845,
          y: 295,
          defaultExpanded: true,
          className: 'ship-schematic-hotspot ship-schematic-hotspot--heat'
        },
        {
          id: 'cargo',
          panelId: 'dash-panel-cargo',
          label: 'Toggle cargo hold telemetry',
          x: 845,
          y: 400,
          defaultExpanded: true,
          className: 'ship-schematic-hotspot ship-schematic-hotspot--cargo'
        },
        {
          id: 'modules',
          panelId: 'dash-panel-modules',
          label: 'Toggle module health telemetry',
          x: 155,
          y: 400,
          defaultExpanded: true,
          className: 'ship-schematic-hotspot ship-schematic-hotspot--modules'
        },
        {
          id: 'pips',
          panelId: 'dash-panel-pips',
          label: 'Toggle power distribution telemetry',
          x: 420,
          y: 540,
          defaultExpanded: true,
          className: 'ship-schematic-hotspot ship-schematic-hotspot--pips'
        }
      ]
    },

    generic: {
      id: 'generic',
      displayName: 'Unknown Ship',
      aliases: [],
      viewBox: '0 0 1000 560',
      supportedSubsystems: ['hull', 'shield', 'fuel', 'heat', 'cargo', 'modules', 'pips'],
      defaultPanelAnchors: {
        hull: 'left-top',
        shield: 'left-top',
        fuel: 'right-top',
        heat: 'right-mid',
        cargo: 'right-bottom',
        modules: 'left-bottom',
        pips: 'bottom-center'
      },
      shapes: [
        {
          type: 'rect',
          className: 'ship-schematic-shape ship-schematic-outline ship-schematic-fallback',
          x: 340, y: 100, width: 320, height: 360, rx: 16
        },
        {
          type: 'line',
          className: 'ship-schematic-shape ship-schematic-line',
          x1: 500, y1: 100, x2: 500, y2: 460
        },
        {
          type: 'line',
          className: 'ship-schematic-shape ship-schematic-line',
          x1: 340, y1: 280, x2: 660, y2: 280
        },
        {
          type: 'circle',
          className: 'ship-schematic-shape ship-schematic-core',
          cx: 500, cy: 200, r: 30
        }
      ],
      hotspots: [
        {
          id: 'hull',
          panelId: 'dash-panel-hull-shields',
          label: 'Toggle hull integrity telemetry',
          x: 155,
          y: 195,
          defaultExpanded: true,
          className: 'ship-schematic-hotspot ship-schematic-hotspot--hull'
        },
        {
          id: 'shield',
          panelId: 'dash-panel-hull-shields',
          label: 'Toggle shield status telemetry',
          x: 155,
          y: 270,
          defaultExpanded: true,
          className: 'ship-schematic-hotspot ship-schematic-hotspot--shield'
        },
        {
          id: 'fuel',
          panelId: 'dash-panel-fuel-jump',
          label: 'Toggle fuel and jump telemetry',
          x: 845,
          y: 195,
          defaultExpanded: true,
          className: 'ship-schematic-hotspot ship-schematic-hotspot--fuel'
        },
        {
          id: 'heat',
          panelId: 'dash-panel-heat-core',
          label: 'Toggle heat management telemetry',
          x: 845,
          y: 295,
          defaultExpanded: true,
          className: 'ship-schematic-hotspot ship-schematic-hotspot--heat'
        },
        {
          id: 'cargo',
          panelId: 'dash-panel-cargo',
          label: 'Toggle cargo hold telemetry',
          x: 845,
          y: 400,
          defaultExpanded: true,
          className: 'ship-schematic-hotspot ship-schematic-hotspot--cargo'
        },
        {
          id: 'modules',
          panelId: 'dash-panel-modules',
          label: 'Toggle module health telemetry',
          x: 155,
          y: 400,
          defaultExpanded: true,
          className: 'ship-schematic-hotspot ship-schematic-hotspot--modules'
        },
        {
          id: 'pips',
          panelId: 'dash-panel-pips',
          label: 'Toggle power distribution telemetry',
          x: 420,
          y: 540,
          defaultExpanded: true,
          className: 'ship-schematic-hotspot ship-schematic-hotspot--pips'
        }
      ]
    }
  };

  const ALIAS_MAP = (function () {
    const map = {};
    for (const id in SCHEMATICS) {
      const entry = SCHEMATICS[id];
      map[id] = id;
      entry.aliases.forEach(function (alias) {
        map[alias] = id;
        map[alias.toLowerCase()] = id;
      });
    }
    return map;
  })();

  window.OmniShipSchematics = {
    resolveShipKey(rawShipType) {
      if (!rawShipType) return 'generic';
      const raw = String(rawShipType).trim();
      if (ALIAS_MAP[raw]) return ALIAS_MAP[raw];
      const lower = raw.toLowerCase();
      if (ALIAS_MAP[lower]) return ALIAS_MAP[lower];
      return 'generic';
    },

    getSchematic(shipType) {
      const key = this.resolveShipKey(shipType);
      return SCHEMATICS[key] || SCHEMATICS['generic'];
    },

    hasSchematic(shipType) {
      if (!shipType) return false;
      const raw = String(shipType).trim();
      return !!(ALIAS_MAP[raw] || ALIAS_MAP[raw.toLowerCase()]);
    },

    listSupported() {
      return Object.keys(SCHEMATICS);
    }
  };
})();
