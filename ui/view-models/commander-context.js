/**
 * OmniCOVAS Commander Context view-model.
 *
 * Converts source-backed ship/heat/navigation/cargo state into a human-facing
 * Primary / Support / Watch / Interrupt decision model.
 *
 * Authority: authority_files/documents/02_ui_ux_authority/OmniCOVAS_UI_UX_Master_Blueprint_v2_0_Human_Reference.md
 *   §6 Primary/Support/Watch/Interrupt
 *   §7 Commander Context Engine
 *   §8 Pilot / Detail / Proof
 *
 * Source: local Status.json, Loadout, NavRoute, Cargo only. No invented facts.
 */

'use strict';

export const PRIMARY_OPERATIONS = Object.freeze([
  'idle', 'mining', 'trading', 'combat', 'exploration', 'travel', 'station', 'squadron',
]);

/**
 * deriveCommanderLocationState
 *
 * Single source of truth for the Commander's current system / station /
 * docking state across the UI. Resolves the contradiction where ship_state
 * may report is_docked=false while local context still knows a last-known
 * docked station from a recent journal Docked event.
 *
 * Priority order:
 *  1. localContext.stationBrief.isDocked === true → docked / last-known docked
 *  2. localContext.stationBrief.contextKind === 'market_snapshot_only' →
 *     partial knowledge from local Market.json snapshot
 *  3. live ship state proves in-space during an Active Elite session →
 *     Flight state: In space
 *  4. otherwise → Last known / Unknown
 *
 * Inputs:
 *   localContext  — output of deriveLocalContext (or null)
 *   shipState     — /pillar1/ship-state payload (or null)
 *   navSnap       — /navigation/snapshot payload (or null)
 *   options.sessionState — 'Active' | 'Last known' | 'Waiting' | 'Unknown'
 *
 * Output:
 *   {
 *     systemName, stationName,
 *     flightLabel,        // 'Docking state' | 'Flight state' | 'Status'
 *     flightValue,        // 'Docked' | 'Last known docked' | 'In space' | ...
 *     dockingState,       // 'docked' | 'last_known_docked' | 'partial' | 'in_space' | 'unknown'
 *     contextKind,
 *     isStale,
 *     sessionState,
 *   }
 */
export function deriveCommanderLocationState(localContext, shipState, navSnap, options = {}) {
  const sessionState = options.sessionState || null;
  const isActive = sessionState === 'Active' || sessionState === 'active';
  const isLastKnown = sessionState === 'Last known' || sessionState === 'last_known';

  const stationBrief = localContext?.stationBrief || null;
  const systemBrief = localContext?.systemBrief || null;
  const marketSearch = localContext?.marketSearch || null;

  const localStation = stationBrief?.stationName || null;
  const localSystem = systemBrief?.systemName
    || stationBrief?.systemName
    || marketSearch?.starSystem
    || null;
  const localStationFromMarket = marketSearch?.stationName || null;

  const shipDockedTrue  = shipState?.is_docked === true;
  const shipDockedFalse = shipState?.is_docked === false;
  const localDockedTrue = stationBrief?.isDocked === true;
  const localPartial = stationBrief?.contextKind === 'market_snapshot_only'
    || stationBrief?.partialFromMarket === true;

  /* Pick names. Live ship-state wins only when it agrees with — or is the
     only signal for — the current system. Otherwise fall back to local
     context names. */
  const systemName = (isActive ? shipState?.current_system : null)
    || shipState?.current_system
    || navSnap?.current_system
    || localSystem
    || null;

  const stationName = (isActive ? shipState?.current_station : null)
    || (shipDockedTrue ? shipState?.current_station : null)
    || localStation
    || localStationFromMarket
    || (shipState?.current_station && !shipDockedFalse ? shipState.current_station : null)
    || null;

  /* Priority 1: local context proves we were docked. */
  if (localDockedTrue || shipDockedTrue) {
    return {
      systemName,
      stationName,
      flightLabel: 'Docking state',
      flightValue: shipDockedTrue && isActive ? 'Docked' : 'Last known docked',
      dockingState: shipDockedTrue && isActive ? 'docked' : 'last_known_docked',
      contextKind: stationBrief?.contextKind || 'journal_station_context',
      isStale: !isActive,
      sessionState,
    };
  }

  /* Priority 2: only a local market snapshot knows the station. */
  if (localPartial && (localStation || localStationFromMarket)) {
    return {
      systemName,
      stationName: localStation || localStationFromMarket,
      flightLabel: 'Docking state',
      flightValue: 'Not loaded in this app session',
      dockingState: 'partial',
      contextKind: 'market_snapshot_only',
      isStale: true,
      sessionState,
    };
  }

  /* Priority 3: live ship-state proves we are in space. */
  if (shipDockedFalse && isActive) {
    return {
      systemName,
      stationName: null,
      flightLabel: 'Flight state',
      flightValue: 'In space',
      dockingState: 'in_space',
      contextKind: null,
      isStale: false,
      sessionState,
    };
  }

  /* Priority 4: last-known / unknown. */
  const haveLastKnown = systemName || stationName;
  return {
    systemName,
    stationName,
    flightLabel: haveLastKnown ? 'Docking state' : 'Flight state',
    flightValue: haveLastKnown ? (isLastKnown ? 'Last known' : 'Unknown') : 'Unknown',
    dockingState: 'unknown',
    contextKind: stationBrief?.contextKind || null,
    isStale: !isActive,
    sessionState,
  };
}

const OPERATION_LABELS = Object.freeze({
  idle:        'Idle',
  mining:      'Mining',
  trading:     'Trading',
  combat:      'Combat',
  exploration: 'Exploration',
  travel:      'Travel',
  station:     'Docked Context',
  squadron:    'Squadron',
});

const OPERATION_TAGLINES = Object.freeze({
  idle:        'Standing by for orders.',
  mining:      'Cargo, sell plan, and refinery support.',
  trading:     'Commodity search and sell decisions.',
  combat:      'Threats, target, and ship readiness.',
  exploration: 'Discovery, scanning, and route fuel.',
  travel:      'Route, next hop, and ship readiness.',
  station:     'Docked services and local station context.',
  squadron:    'Local coordination context.',
});

export function operationLabel(op) {
  return OPERATION_LABELS[op] || OPERATION_LABELS.idle;
}

export function operationTagline(op) {
  return OPERATION_TAGLINES[op] || OPERATION_TAGLINES.idle;
}

/**
 * deriveSuggestedOperation
 *
 * Picks a single suggested operation based on local evidence only.
 * Returns 'idle' if no signal exists. Never invents data.
 */
export function deriveSuggestedOperation(input) {
  const state    = input?.state || null;
  const heat     = input?.heat || null;
  const cargo    = input?.cargo || null;
  const navSnap  = input?.navSnap || null;
  const combat   = input?.combat || null;
  const local    = input?.localContext || null;

  if (combat?.under_attack === true || combat?.interdiction_active === true) {
    return 'combat';
  }

  if (state?.is_docked === true || local?.stationBrief?.dockedLabel === 'Docked') return 'station';

  const route = navSnap?.active_route;
  if (route?.destination) return 'travel';

  const items = Array.isArray(cargo?.inventory) ? cargo.inventory : [];
  const localCargoItems = Array.isArray(local?.cargoHold?.inventory) ? local.cargoHold.inventory : [];
  if (items.length > 0 || localCargoItems.length > 0) {
    // Pure mining-relevant cargo with refinery loadout would point at mining.
    // Without a verified loadout signal, prefer the trading workspace by default.
    return 'trading';
  }

  if (heat?.state === 'damage' || heat?.state === 'critical') return 'exploration';

  return 'idle';
}

/**
 * deriveActiveInterrupts
 *
 * Returns a stable list of interrupt records derived from local state.
 * Critical states render in the InterruptBanner regardless of primary operation.
 */
/* Configuration check: does the loadout include a ShieldGenerator?
   Returns null if loadout is not yet loaded — then "shields down" is
   ambiguous. Returns false if loadout is loaded and contains no
   shield generator — then "shields down" is a configuration fact,
   not an interrupt. */
function loadoutHasShieldGenerator(input) {
  const local = input?.localContext || null;
  const explicit = [
    local?.moduleSearch?.shieldGenerator?.fitted,
    input?.moduleLoadout?.shield_generator?.fitted,
    input?.moduleLoadout?.shieldGenerator?.fitted,
    input?.localContextSnap?.module_loadout?.shield_generator?.fitted,
  ];
  for (const fitted of explicit) {
    if (fitted === true || fitted === false) return fitted;
    if (fitted === null) return null;
  }
  const modulesFromLocal = Array.isArray(local?.moduleSearch?.modules)
    ? local.moduleSearch.modules
    : null;
  /* Some callers may pass the raw local-context snapshot. */
  const modulesFromRaw = Array.isArray(input?.moduleLoadout?.modules)
    ? input.moduleLoadout.modules
    : null;
  const list = modulesFromLocal || modulesFromRaw;
  if (!Array.isArray(list)) return null;
  return list.some((m) => {
    const slot = (m?.slot || m?.Slot || '').toString().toLowerCase();
    const item = (m?.item || m?.Item || m?.display || m?.name || '').toString().toLowerCase();
    return slot.includes('shieldgenerator') || item.includes('shieldgenerator')
      || item.includes('shield generator');
  });
}

export function deriveActiveInterrupts(input) {
  const state  = input?.state || null;
  const heat   = input?.heat || null;
  const combat = input?.combat || null;
  const mods   = input?.mods || null;

  const interrupts = [];
  const push = (id, severity, label, detail) => {
    interrupts.push({ id, severity, label, detail });
  };

  if (combat?.interdiction_active === true) {
    push('interdiction', 'critical', 'Interdiction', 'Hostile interdiction in progress.');
  } else if (combat?.under_attack === true) {
    push('combat', 'critical', 'Under fire', 'Hostile contact engaged.');
  }

  const hull = state?.hull_health;
  if (hull != null && hull <= 10) {
    push('hull-critical', 'critical', 'Hull critical', `Hull at ${hull.toFixed?.(0) ?? hull}%`);
  } else if (hull != null && hull <= 25) {
    push('hull-low', 'warning', 'Hull low', `Hull at ${hull.toFixed?.(0) ?? hull}%`);
  }

  /* Correction #2 (repaired): a ship without a shield generator fitted
     must not trigger an ATTENTION interrupt for "Shields down." That is
     a configuration fact, not an emergency. Only raise the interrupt
     when a shield generator is present OR loadout is unknown. */
  if (state?.shield_up === false && (hull == null || hull > 10)) {
    const fitted = loadoutHasShieldGenerator(input);
    if (fitted !== false) {
      push('shields-down', 'warning', 'Shields down', 'Shields offline.');
    }
  }

  const heatPct = Number.isFinite(heat?.level_pct) ? heat.level_pct : null;
  if (heat?.state === 'damage' || heat?.state === 'critical' || (heatPct != null && heatPct >= 120)) {
    push('heat-critical', 'critical', 'Heat damage', heatPct != null ? `Heat ${heatPct.toFixed?.(0) ?? heatPct}%` : 'Heat damaging modules.');
  } else if (heat?.state === 'warning' || (heatPct != null && heatPct >= 95)) {
    push('heat-warning', 'warning', 'Heat warning', heatPct != null ? `Heat ${heatPct.toFixed?.(0) ?? heatPct}%` : 'Heat near threshold.');
  }

  const fuelPct = state?.fuel_pct;
  if (fuelPct != null && fuelPct <= 10) {
    push('fuel-critical', 'critical', 'Fuel critical', `Fuel at ${fuelPct.toFixed?.(0) ?? fuelPct}%`);
  } else if (fuelPct != null && fuelPct <= 25) {
    push('fuel-low', 'warning', 'Fuel low', `Fuel at ${fuelPct.toFixed?.(0) ?? fuelPct}%`);
  }

  if (mods && Number.isInteger(mods.critical) && mods.critical > 0) {
    push('module-critical', 'warning', 'Module critical',
      `${mods.critical} module${mods.critical === 1 ? '' : 's'} critical.`);
  }

  return interrupts;
}

/**
 * deriveWatchModel
 *
 * Compact watch strip values for the Watch row. Each value carries an optional
 * severity so the strip can highlight unsafe states without rendering proof.
 */
export function deriveWatchModel(input) {
  const state = input?.state || {};
  const heat  = input?.heat  || null;
  const cargo = input?.cargo || null;
  const navSnap = input?.navSnap || null;
  const local = input?.localContext || null;

  const hull   = state.hull_health;
  const fuel   = state.fuel_pct;
  const heatPct = Number.isFinite(heat?.level_pct) ? heat.level_pct : null;
  const route  = navSnap?.active_route?.destination || null;

  const items = Array.isArray(cargo?.inventory) ? cargo.inventory : [];
  const localCargo = local?.cargoHold || null;
  const cargoSummary = state.cargo_count != null && state.cargo_capacity != null
    ? `${state.cargo_count}/${state.cargo_capacity} t`
    : (localCargo?.capacity !== null && localCargo?.capacity !== undefined && localCargo?.used !== null && localCargo?.used !== undefined
      ? `${localCargo.used}/${localCargo.capacity} t`
      : (items.length > 0 ? `${items.length} types` : (localCargo?.hasCargo ? localCargo.usedLabel : '0 t')));

  function severity({ value, criticalAt, warnAt, descending }) {
    if (value == null) return 'unknown';
    if (descending) {
      if (value <= criticalAt) return 'critical';
      if (value <= warnAt) return 'warning';
      return 'ok';
    }
    if (value >= criticalAt) return 'critical';
    if (value >= warnAt) return 'warning';
    return 'ok';
  }

  return {
    items: [
      {
        id: 'hull',
        label: 'Hull',
        value: hull != null ? `${hull.toFixed?.(0) ?? Math.round(hull)}%` : '—',
        severity: severity({ value: hull, criticalAt: 10, warnAt: 25, descending: true }),
      },
      (() => {
        /* Repair R2: configuration-aware shield strip cell. */
        const fitted = loadoutHasShieldGenerator(input);
        if (fitted === false) {
          return {
            id: 'shields', label: 'Shields',
            value: 'None fitted',
            severity: 'unknown',
          };
        }
        return {
          id: 'shields', label: 'Shields',
          value: state.shield_up === true ? 'UP' : state.shield_up === false ? 'DOWN' : '—',
          severity: state.shield_up === false ? 'warning' : (state.shield_up === true ? 'ok' : 'unknown'),
        };
      })(),
      {
        id: 'heat',
        label: 'Heat',
        value: heatPct != null ? `${Math.round(heatPct)}%` : '—',
        severity: severity({ value: heatPct, criticalAt: 95, warnAt: 80 }),
      },
      {
        id: 'fuel',
        label: 'Fuel',
        value: fuel != null ? `${fuel.toFixed?.(0) ?? Math.round(fuel)}%` : '—',
        severity: severity({ value: fuel, criticalAt: 10, warnAt: 25, descending: true }),
      },
      {
        id: 'cargo',
        label: 'Cargo',
        value: cargoSummary,
        severity: 'ok',
      },
      {
        id: 'route',
        label: 'Route',
        value: route ? route : 'None',
        severity: route ? 'ok' : 'unknown',
      },
    ],
  };
}

/**
 * deriveCommanderContext
 *
 * Top-level builder. Returns the full Commander Context model that drives
 * Dashboard, Operations, and other surfaces.
 */
export function deriveCommanderContext(input, manualOperation) {
  const suggested  = deriveSuggestedOperation(input);
  const interrupts = deriveActiveInterrupts(input);

  const hasManualOperation = Boolean(
    manualOperation && PRIMARY_OPERATIONS.includes(manualOperation));
  let primary = hasManualOperation ? manualOperation : suggested;

  /* ALERT_OWNERSHIP_01: a critical interrupt (fuel / hull / heat / module) is
     shared, global attention state. It always surfaces in the InterruptBanner
     regardless of operation, but it must NOT hijack an operation the Commander
     explicitly selected. Previously any critical interrupt forced
     primaryOperation to 'combat', which trapped the Operations workspace on the
     Combat tab and broke operation-tab switching while fuel was critical.
     Auto-elevation to the Combat workspace now applies only to the *suggested*
     operation (i.e. when the Commander has not explicitly chosen a tab). */
  if (!hasManualOperation && interrupts.some(i => i.severity === 'critical')) {
    primary = 'combat';
  }

  const state = input?.state || null;
  const navSnap = input?.navSnap || null;
  const local = input?.localContext || null;

  /* Unified location derivation. All spine rows use the same authoritative
     answer so the Commander never sees "Docked: In flight" or
     "Station: Undocked" while another surface knows the station name. */
  const location = deriveCommanderLocationState(local, state, navSnap, {
    sessionState: input?.sessionState || null,
  });

  const spine = [];
  const shipName = (state?.ship_name && state.ship_name.trim()) || state?.ship_type || null;
  if (shipName) spine.push({ id: 'ship', label: 'Ship', value: shipName });
  if (location.systemName) spine.push({ id: 'system', label: 'System', value: location.systemName });
  if (location.stationName) spine.push({ id: 'station', label: 'Station', value: location.stationName });
  if (location.flightValue) {
    spine.push({ id: 'flight', label: location.flightLabel, value: location.flightValue });
  }
  if (navSnap?.active_route?.destination) {
    spine.push({ id: 'destination', label: 'Destination', value: navSnap.active_route.destination });
  }

  return {
    primaryOperation: primary,
    suggestedOperation: suggested,
    manualOperation: manualOperation || null,
    location,
    contextSpine: spine,
    watch: deriveWatchModel(input),
    interrupts,
  };
}

/**
 * deriveSupportSystems
 *
 * Returns a stable list of support cards for a given primary operation.
 * Support systems are derived from current state; they are never invented.
 */
export function deriveSupportSystems(primary, input) {
  const state = input?.state || null;
  const navSnap = input?.navSnap || null;
  const cargo = input?.cargo || null;
  const local = input?.localContext || null;

  const cargoItems = Array.isArray(cargo?.inventory) ? cargo.inventory : [];
  const localCargo = local?.cargoHold || null;
  const cargoCount = state?.cargo_count != null
    ? state.cargo_count
    : (localCargo?.used != null ? localCargo.used : cargoItems.length);
  const cargoCap   = state?.cargo_capacity ?? localCargo?.capacity;
  const route      = navSnap?.active_route?.destination || null;
  const location = deriveCommanderLocationState(local, state, navSnap, {});
  const stationName = location.stationName;
  const dockingState = location.dockingState;
  const docked = dockingState === 'docked';
  const lastKnownDocked = dockingState === 'last_known_docked';
  const partialStation = dockingState === 'partial';
  const marketLine = local?.marketSearch?.available
    ? `${local.marketSearch.itemCount} local market rows`
    : 'No local market snapshot loaded';

  const cargoSummary = cargoCount != null && cargoCap != null
    ? `${cargoCount} / ${cargoCap} t`
    : (cargoItems.length > 0
      ? `${cargoItems.length} cargo types`
      : (localCargo?.hasCargo ? localCargo.usedLabel : 'No cargo detected'));

  const navSummary = route ? route : 'No route plotted';
  let stationSummary;
  if (docked) stationSummary = stationName || 'Docked';
  else if (lastKnownDocked) stationSummary = stationName ? `${stationName} (last known docked)` : 'Last known docked';
  else if (partialStation) stationSummary = stationName ? `${stationName} (partial)` : 'Partial station context';
  else if (location.dockingState === 'in_space') stationSummary = 'In space';
  else stationSummary = stationName ? `${stationName} (last known)` : 'Unknown';

  const ALL = {
    navigation: {
      id: 'navigation', label: 'Navigation', summary: navSummary,
      route: '#/navigation', emptyAction: 'Plot a route', empty: !route,
    },
    cargo: {
      id: 'cargo', label: 'Cargo', summary: cargoSummary,
      route: '#/operations', emptyAction: null, empty: cargoItems.length === 0,
    },
    station: {
      id: 'station', label: 'Station', summary: stationSummary,
      route: '#/intel',
      emptyAction: docked || lastKnownDocked || partialStation ? null : 'Dock to enable station services',
      empty: !(docked || lastKnownDocked || partialStation),
    },
    marketIntel: {
      id: 'marketIntel', label: 'Market Intel', summary: marketLine,
      route: '#/intel', emptyAction: 'Open the Commodities Market to load Market.json.', empty: !local?.marketSearch?.available,
    },
    moduleSearch: {
      id: 'moduleSearch', label: 'Module Search', summary: local?.moduleSearch?.summary || 'Search known outfitting observations',
      route: '#/intel', emptyAction: null, empty: !local?.moduleSearch?.available,
    },
    combatWatch: {
      id: 'combatWatch', label: 'Threat Watch', summary: 'No hostile contact',
      route: '#/operations', emptyAction: null, empty: false,
    },
    shipStatus: {
      id: 'shipStatus', label: 'Ship Status', summary: 'Hull, shields, heat, fuel',
      route: '#/dashboard', emptyAction: null, empty: false,
    },
    activityLog: {
      id: 'activityLog', label: 'Activity Log', summary: 'Recent events and proof',
      route: '#/activity-log', emptyAction: null, empty: false,
    },
  };

  const map = {
    idle:        ['shipStatus', 'navigation', 'station'],
    mining:      ['cargo', 'navigation', 'combatWatch', 'station'],
    trading:     ['cargo', 'marketIntel', 'navigation', 'station'],
    combat:      ['shipStatus', 'combatWatch', 'navigation'],
    exploration: ['navigation', 'shipStatus', 'station'],
    travel:      ['navigation', 'shipStatus', 'combatWatch'],
    station:     ['station', 'marketIntel', 'moduleSearch', 'cargo'],
    squadron:    ['shipStatus', 'navigation', 'activityLog'],
  };
  return (map[primary] || map.idle).map(key => ALL[key]);
}

/**
 * derivePrimaryAction
 *
 * One commander-facing primary action per primary operation. Returns null when
 * the operation does not have a useful default action in the current state.
 */
export function derivePrimaryAction(primary, input) {
  const state = input?.state || null;
  const navSnap = input?.navSnap || null;
  const cargo = input?.cargo || null;
  const local = input?.localContext || null;
  const cargoItems = Array.isArray(cargo?.inventory) ? cargo.inventory : [];
  const hasLocalCargo = local?.cargoHold?.hasCargo === true;

  switch (primary) {
    case 'mining':
      if (cargoItems.length > 0 || hasLocalCargo) return { label: 'Search sell prices', route: '#/intel' };
      return { label: 'Open Cargo', route: '#/operations' };
    case 'trading':
      return { label: 'Search a commodity', route: '#/intel' };
    case 'combat':
      return { label: 'Open Threat Watch', route: '#/operations' };
    case 'exploration':
      return { label: 'Open Navigation', route: '#/navigation' };
    case 'travel':
      return navSnap?.active_route?.destination
        ? { label: 'Open Navigation', route: '#/navigation' }
        : { label: 'Plot a route', route: '#/navigation' };
    case 'station':
      return { label: 'Open Station Brief', route: '#/intel' };
    case 'squadron':
      return { label: 'Open Squadron', route: '#/squadrons' };
    default:
      return state ? { label: 'Select an operation', route: '#/operations' } : null;
  }
}
