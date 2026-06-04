/**
 * OmniCOVAS Ship Schematic Component
 *
 * Renders ship wireframe SVG and accessible hotspot buttons from registry data.
 * Classic script — exposes window.OmniShipSchematic.
 * Safe: uses only safe DOM APIs — no dynamic HTML rendering sinks.
 * Depends on window.OmniShipSchematics (ship-schematics.js must load first).
 */

(function () {
  'use strict';

  const SVG_NS = 'http://www.w3.org/2000/svg';

  function _createShapeEl(shape) {
    const el = document.createElementNS(SVG_NS, shape.type);
    if (shape.className) {
      el.setAttribute('class', shape.className);
    }
    switch (shape.type) {
      case 'polygon':
      case 'polyline':
        el.setAttribute('points', shape.points);
        break;
      case 'line':
        el.setAttribute('x1', shape.x1);
        el.setAttribute('y1', shape.y1);
        el.setAttribute('x2', shape.x2);
        el.setAttribute('y2', shape.y2);
        break;
      case 'circle':
        el.setAttribute('cx', shape.cx);
        el.setAttribute('cy', shape.cy);
        el.setAttribute('r', shape.r);
        break;
      case 'rect':
        el.setAttribute('x', shape.x);
        el.setAttribute('y', shape.y);
        el.setAttribute('width', shape.width);
        el.setAttribute('height', shape.height);
        if (shape.rx != null) el.setAttribute('rx', shape.rx);
        break;
      case 'path':
        el.setAttribute('d', shape.d);
        break;
    }
    return el;
  }

  function createHotspotButton(hotspot, options) {
    const opts = options || {};
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'ship-schematic-hotspot-button' +
      (hotspot.className ? ' ' + hotspot.className : '');
    btn.setAttribute('aria-label', hotspot.label);
    btn.setAttribute('aria-controls', hotspot.panelId);
    const expanded = opts.expanded != null ? opts.expanded : hotspot.defaultExpanded;
    btn.setAttribute('aria-expanded', String(expanded));
    btn.setAttribute('data-hotspot-id', hotspot.id);

    if (opts.viewBox) {
      const parts = opts.viewBox.split(' ').map(Number);
      const vbW = parts[2];
      const vbH = parts[3];
      btn.style.left = ((hotspot.x / vbW) * 100).toFixed(2) + '%';
      btn.style.top  = ((hotspot.y / vbH) * 100).toFixed(2) + '%';
    }

    const label = document.createElement('span');
    label.className = 'ship-schematic-hotspot-label';
    label.textContent = hotspot.id.toUpperCase();
    label.setAttribute('aria-hidden', 'true');
    btn.appendChild(label);

    return btn;
  }

  function create(shipType, options) {
    const opts = options || {};
    const schematic = window.OmniShipSchematics.getSchematic(shipType);

    const wrapper = document.createElement('div');
    wrapper.className = 'ship-schematic';
    wrapper.setAttribute('data-ship-schematic', schematic.id);

    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('class', 'ship-schematic-svg');
    svg.setAttribute('viewBox', schematic.viewBox);
    svg.setAttribute('fill', 'none');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');

    schematic.shapes.forEach(function (shape) {
      svg.appendChild(_createShapeEl(shape));
    });

    wrapper.appendChild(svg);

    const hotspotsDiv = document.createElement('div');
    hotspotsDiv.className = 'ship-schematic-hotspots';
    hotspotsDiv.setAttribute('aria-hidden', 'true');

    const hotspotOpts = { viewBox: schematic.viewBox };

    schematic.hotspots.forEach(function (hotspot) {
      const btnOpts = Object.assign({}, hotspotOpts);
      if (opts.expandedStates && opts.expandedStates[hotspot.id] != null) {
        btnOpts.expanded = opts.expandedStates[hotspot.id];
      }
      hotspotsDiv.appendChild(createHotspotButton(hotspot, btnOpts));
    });

    wrapper.appendChild(hotspotsDiv);
    return wrapper;
  }

  function mount(container, shipType, options) {
    const el = create(shipType, options);
    container.appendChild(el);
    return el;
  }

  function resolve(shipType) {
    return window.OmniShipSchematics.getSchematic(shipType);
  }

  window.OmniShipSchematic = {
    create,
    mount,
    resolve,
    createHotspotButton
  };
})();
