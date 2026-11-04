/**
 * UI v3 Systems workspace.
 *
 * Additive overview only: standalone Settings / Privacy / Sources /
 * Resources / Credits routes remain the detailed owners for their content.
 */
(function () {
  'use strict';

  const DEFAULT_TOPIC = 'sources-diagnostics';

  const ROUTE_TO_TOPIC = {
    '/systems': DEFAULT_TOPIC,
    '/systems/settings': 'settings',
    '/systems/privacy': 'privacy',
    '/systems/sources-diagnostics': 'sources-diagnostics',
    '/systems/resources': 'resources',
    '/systems/about': 'about',
  };

  const SYSTEMS_AREAS = [
    {
      key: 'settings',
      label: 'Settings',
      description: 'Behavior, output mode, presets, and overlay controls.',
      posture: 'Local-first',
      route: '/systems/settings',
      link: '#/settings',
    },
    {
      key: 'privacy',
      label: 'Privacy',
      description: 'Outbound data gates, export, and deletion controls.',
      posture: 'Local-first',
      route: '/systems/privacy',
      link: '#/privacy',
    },
    {
      key: 'sources-diagnostics',
      label: 'Sources & Diagnostics',
      description: 'Source health, provider posture, and local diagnostics.',
      posture: 'Open diagnostics',
      route: '/systems/sources-diagnostics',
      link: '#/sources',
    },
    {
      key: 'resources',
      label: 'Resources',
      description: 'Memory, CPU, disk, and budget status.',
      posture: 'Available',
      route: '/systems/resources',
      link: '#/resources',
    },
    {
      key: 'about',
      label: 'About',
      description: 'Project identity, build reference, and credits.',
      posture: 'Available',
      route: '/systems/about',
      link: '#/credits',
    },
    {
      key: 'future-capabilities',
      label: 'Future Capabilities',
      description: 'Reserved capabilities and enablement posture.',
      posture: 'Reserved',
      route: '',
      link: '',
      reserved: true,
    },
  ];

  /* PB-UIV3-HARMONY §4·7: group the admin cards by posture so Systems reads as
     a coherent app-posture hub, not a loose grid. */
  const SYSTEMS_GROUPS = [
    { label: 'Configuration', keys: ['settings', 'privacy'] },
    { label: 'Diagnostics & Resources', keys: ['sources-diagnostics', 'resources'] },
    { label: 'Reference', keys: ['about'] },
    { label: 'Future Capabilities', keys: ['future-capabilities'] },
  ];

  const PANEL_COPY = {
    settings: {
      eyebrow: 'Settings',
      title: 'Configuration console',
      body: 'Settings stay local-first and continue to own behavior, output mode, presets, controls, and overlay posture.',
      rows: [
        ['Configuration source', 'Local-first'],
        ['External provider', 'No external provider enabled'],
        ['Detailed route', '#/settings'],
      ],
      action: ['Open Settings', '#/settings'],
    },
    privacy: {
      eyebrow: 'Privacy',
      title: 'Local-first data posture',
      body: 'Privacy owns outbound gates, data export, and deletion controls. Outbound data remains opt-in and disabled by default.',
      rows: [
        ['Default posture', 'Local-first'],
        ['Outbound data', 'Disabled'],
        ['Detailed route', '#/privacy'],
      ],
      action: ['Open Privacy', '#/privacy'],
    },
    'sources-diagnostics': {
      eyebrow: 'Sources & Diagnostics',
      title: 'Local source and diagnostics posture',
      body: 'Open Sources & Diagnostics for current local file freshness and provider posture. This overview does not infer source state.',
      rows: [
        ['Local journal files', 'Inspect detailed route'],
        ['Source health', 'Inspect detailed route'],
        ['Provider status', 'No external provider enabled'],
        ['Detailed route', '#/sources'],
      ],
      action: ['Open Sources & Diagnostics', '#/sources'],
    },
    resources: {
      eyebrow: 'Resources',
      title: 'System resource monitor',
      body: 'Resources keeps memory, CPU, disk, and budget checks in their standalone diagnostics route.',
      rows: [
        ['Resource monitor', 'Available'],
        ['Runtime values', 'Not Loaded'],
        ['Detailed route', '#/resources'],
      ],
      action: ['Open Resources', '#/resources'],
    },
    about: {
      eyebrow: 'About',
      title: 'Project identity and credits',
      body: 'About keeps build reference, license posture, project identity, and credits reachable from the existing Credits route.',
      rows: [
        ['Build reference', 'Available'],
        ['Credits route', '#/credits'],
        ['External assets', 'No remote assets'],
      ],
      action: ['Open About / Credits', '#/credits'],
    },
    'future-capabilities': {
      eyebrow: 'Future Capabilities',
      title: 'Reserved capability posture',
      body: 'Future capabilities are reserved. This panel does not enable providers, automation, remote services, or unsupported source behavior.',
      rows: [
        ['Enablement', 'Disabled'],
        ['Provider state', 'No external provider enabled'],
        ['Configuration', 'Not configured'],
      ],
      action: null,
    },
  };

  function makeEl(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined && text !== null) el.textContent = String(text);
    return el;
  }

  function normalizeRoute(value) {
    const text = String(value || '').replace(/^#/, '');
    const routeOnly = text.includes('#') ? text.split('#')[0] : text;
    if (!routeOnly) return '/systems';
    return routeOnly.startsWith('/') ? routeOnly : `/${routeOnly}`;
  }

  function topicFromRoute(routeValue) {
    const route = normalizeRoute(routeValue);
    return ROUTE_TO_TOPIC[route] || DEFAULT_TOPIC;
  }

  function getArea(key) {
    return SYSTEMS_AREAS.find((area) => area.key === key) || SYSTEMS_AREAS[2];
  }

  function createHero(activeArea) {
    const hero = makeEl('header', 'systems-hero route-header');
    const copy = makeEl('div', 'systems-hero-copy');

    const breadcrumb = makeEl('p', 'systems-breadcrumb');
    breadcrumb.append(
      makeEl('span', '', 'Systems'),
      makeEl('span', 'systems-breadcrumb-separator', '>'),
      makeEl('span', 'systems-breadcrumb-active', 'Command Administration'),
    );

    const title = makeEl('h1', 'systems-title', 'Systems');
    title.id = 'systems-title';
    const subtitle = makeEl(
      'p',
      'systems-subtitle',
      'Settings, privacy, diagnostics, resources, and future capability posture.',
    );

    copy.append(breadcrumb, title, subtitle);

    const status = makeEl('div', 'systems-status-pill');
    status.append(
      makeEl('span', 'uiv3-dot uiv3-dot--info'),
      makeEl('span', '', `${activeArea.label} open`),
    );

    hero.append(copy, status);
    return hero;
  }

  function createAreaCard(area, activeKey, setActiveArea) {
    const isActive = area.key === activeKey;
    const card = makeEl(
      'button',
      `systems-area-card cmd-btn cmd-btn--quiet${isActive ? ' systems-area-card--active' : ''}${area.reserved ? ' systems-area-card--reserved' : ''}`,
    );
    card.type = 'button';
    card.dataset.systemsArea = area.key;
    card.setAttribute('aria-label', `Open ${area.label} in Systems`);
    /* `aria-current="page"` is reserved for the app-level tab row in
       shell.js — exactly one page marker exists at a time. A Systems card
       marks the current item *within* the Systems workspace, which is
       `aria-current="true"`. */
    if (isActive) {
      card.setAttribute('aria-current', 'true');
    }

    const topRow = makeEl('span', 'systems-area-topline');
    topRow.append(
      makeEl('span', 'systems-area-title', area.label),
      makeEl('span', 'systems-area-state', isActive ? 'Selected' : 'Open'),
    );

    const description = makeEl('span', 'systems-area-description', area.description);
    const posture = makeEl('span', 'systems-area-posture', area.posture);

    card.append(topRow, description, posture);
    card.addEventListener('click', () => {
      if (area.route) {
        const nextHash = `#${area.route}`;
        setActiveArea(area.key);
        if (window.location.hash !== nextHash) {
          window.location.hash = nextHash;
        }
        return;
      }
      setActiveArea(area.key);
    });
    return card;
  }

  function createPanel(activeArea) {
    const copy = PANEL_COPY[activeArea.key] || PANEL_COPY[DEFAULT_TOPIC];
    const panel = makeEl('section', 'systems-detail-panel');
    panel.setAttribute('role', 'region');
    panel.setAttribute('aria-labelledby', 'systems-detail-title');
    panel.dataset.systemsPanel = activeArea.key;

    const main = makeEl('div', 'systems-detail-main');
    main.appendChild(makeEl('p', 'systems-panel-eyebrow', copy.eyebrow));
    main.appendChild(makeEl('h2', 'systems-panel-title', copy.title));
    main.querySelector('.systems-panel-title').id = 'systems-detail-title';
    main.appendChild(makeEl('p', 'systems-panel-body', copy.body));

    if (copy.action) {
      const action = makeEl('a', 'systems-panel-link cmd-btn cmd-btn--quiet', copy.action[0]);
      action.href = copy.action[1];
      main.appendChild(action);
    }

    const rows = makeEl('div', 'systems-detail-rows');
    copy.rows.forEach(([label, value]) => {
      const row = makeEl('div', 'systems-detail-row');
      row.append(makeEl('span', 'systems-detail-label', label), makeEl('span', 'systems-detail-value', value));
      rows.appendChild(row);
    });

    panel.append(main, rows);
    return panel;
  }

  function renderSystems(root, options = {}) {
    const target = root || document.getElementById('systems-root');
    if (!target) return null;

    let activeKey = options.initialArea || topicFromRoute(window.location.hash);
    const setActiveArea = (nextKey) => {
      activeKey = getArea(nextKey).key;
      draw();
    };

    function draw() {
      const activeArea = getArea(activeKey);
      const surface = makeEl('div', 'systems-surface');
      surface.appendChild(createHero(activeArea));

      /* PB-UIV3-HARMONY §4·7 repair: master-detail hub. The grouped posture
         rail and the selected detail render side-by-side inside one workspace
         so the selected content sits in an integrated workspace area next to
         the rail — never detached at the bottom of the page after every group
         (the Commander-rejected regression). */
      const workspace = makeEl('div', 'systems-workspace');

      /* Left: grouped posture nav rail (§4·7) — each posture group is a
         labelled section of admin cards rather than one undifferentiated grid. */
      const groups = makeEl('div', 'systems-area-groups');
      groups.setAttribute('aria-label', 'System areas');
      SYSTEMS_GROUPS.forEach((group) => {
        const section = makeEl('section', 'systems-area-group');
        section.setAttribute('aria-label', group.label);
        section.appendChild(makeEl('p', 'systems-area-group-label', group.label));
        const grid = makeEl('div', 'systems-area-grid');
        group.keys.forEach((key) => {
          const area = SYSTEMS_AREAS.find((entry) => entry.key === key);
          if (area) grid.appendChild(createAreaCard(area, activeArea.key, setActiveArea));
        });
        section.appendChild(grid);
        groups.appendChild(section);
      });
      workspace.appendChild(groups);

      /* Right: the selected area's detail workspace, integrated beside the
         rail and top-aligned — the coherent "selected workspace area". */
      workspace.appendChild(createPanel(activeArea));

      surface.appendChild(workspace);
      target.replaceChildren(surface);
    }

    draw();
    return target;
  }

  function mountSystems() {
    return renderSystems(document.getElementById('systems-root'));
  }

  /* The Systems workspace keeps its last render while hidden. Without this,
     the selected card's current-item marker would stay in the DOM on every
     other route, leaving stale state for assistive technology. */
  function clearInactiveSystemsCurrent() {
    const root = document.getElementById('systems-root');
    if (!root) return;
    root
      .querySelectorAll('[data-systems-area][aria-current]')
      .forEach((card) => card.removeAttribute('aria-current'));
  }

  function handleHashChange() {
    const route = normalizeRoute(window.location.hash);
    if (route === '/systems' || route.startsWith('/systems/')) {
      mountSystems();
      return;
    }
    clearInactiveSystemsCurrent();
  }

  /* Initial mount goes through the same route-aware handler as every later
     navigation. Mounting unconditionally would render the Systems workspace
     — and its current-item marker — on a cold load of any other route, where
     the workspace is hidden and nothing may claim to be current. */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', handleHashChange);
  } else {
    handleHashChange();
  }
  window.addEventListener('hashchange', handleHashChange);

  globalThis.__systemsExports = {
    SYSTEMS_AREAS,
    mountSystems,
    renderSystems,
    topicFromRoute,
  };
}());
