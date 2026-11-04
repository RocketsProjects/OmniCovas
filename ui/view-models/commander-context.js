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

/* Campaign workspaces (Phase 9). Deliberately NOT in PRIMARY_OPERATIONS.
   That list means "modes local telemetry can derive", and it is what
   `deriveOperationSignal` picks from and what the Dashboard reads. A campaign
   is Commander-declared strategy: no journal event implies one, and nothing
   should ever suggest one.

   They are still selectable, which is the whole of `P14-K07`. The audit found
   the deepest workflow Operations owns was reachable only by being handed off
   from another route — "A Commander who has never been handed off from Intel
   cannot find their campaign workspace." */
export const CAMPAIGN_OPERATIONS = Object.freeze(['bgs', 'powerplay']);

/* What the mode selector offers. One selector, one list — R8 forbids a
   parallel selector, and this is not one: it is the same widget fed the modes
   a Commander may choose, derived and declared alike. */
export const SELECTABLE_OPERATIONS = Object.freeze([
  ...PRIMARY_OPERATIONS, ...CAMPAIGN_OPERATIONS,
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
  const stationFreshness = String(stationBrief?.freshness || '').toLowerCase();
  const stationStale = stationFreshness === 'stale' || marketSearch?.isStale === true;

  /* Current ship/navigation location outranks historical station snapshots. */
  const systemName = shipState?.current_system
    || navSnap?.current_system
    || localSystem
    || null;
  const stationSystem = stationBrief?.systemName || marketSearch?.starSystem || null;
  const normalizeSystem = (value) => String(value || '').trim().toLocaleLowerCase();
  const contextMismatch = Boolean(
    systemName
    && stationSystem
    && normalizeSystem(systemName) !== normalizeSystem(stationSystem)
  );
  const historicalStationName = localStation || localStationFromMarket || null;
  const coherentLocalDock = localDockedTrue
    && !stationStale
    && !contextMismatch
    && !(isActive && shipDockedFalse);
  const currentShipStation = shipState?.current_station && !shipDockedFalse
    ? shipState.current_station
    : null;
  const stationName = shipDockedTrue
    ? (shipState?.current_station || (!contextMismatch ? localStation : null))
    : coherentLocalDock
      ? localStation
      : currentShipStation;

  /* Priority 1: coherent evidence proves a current or last-known dock. */
  if (shipDockedTrue || coherentLocalDock || currentShipStation) {
    return {
      systemName,
      stationName,
      flightLabel: 'Docking state',
      flightValue: shipDockedTrue && isActive ? 'Docked' : 'Last known docked',
      dockingState: shipDockedTrue && isActive ? 'docked' : 'last_known_docked',
      contextKind: stationBrief?.contextKind || 'journal_station_context',
      isStale: !isActive,
      sessionState,
      historicalStationName,
      historicalSystemName: stationSystem,
      contextMismatch,
      currentEligible: true,
    };
  }

  /* Priority 2: Market.json is station-scoped evidence, not docking proof.
     Keep it available to Intel/proof surfaces without placing it in the
     current Commander context spine. */
  if (localPartial && (localStation || localStationFromMarket)) {
    return {
      systemName,
      stationName: null,
      flightLabel: 'Docking state',
      flightValue: 'Docking not checked this session',
      dockingState: 'partial',
      contextKind: 'market_snapshot_only',
      isStale: true,
      sessionState,
      historicalStationName,
      historicalSystemName: stationSystem,
      contextMismatch,
      currentEligible: false,
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
      historicalStationName,
      historicalSystemName: stationSystem,
      contextMismatch,
      currentEligible: false,
    };
  }

  /* Priority 4: last-known / unknown. */
  const haveLastKnown = systemName || stationName || historicalStationName;
  return {
    systemName,
    stationName,
    flightLabel: haveLastKnown ? 'Docking state' : 'Flight state',
    flightValue: haveLastKnown ? (isLastKnown ? 'Last known' : 'Unknown') : 'Unknown',
    dockingState: 'unknown',
    contextKind: stationBrief?.contextKind || null,
    isStale: !isActive,
    sessionState,
    historicalStationName,
    historicalSystemName: stationSystem,
    contextMismatch,
    currentEligible: Boolean(stationName),
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
  bgs:         'BGS Campaign',
  powerplay:   'Powerplay Campaign',
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
  bgs:         'Local BGS campaign intent, evidence and next steps.',
  powerplay:   'Local Powerplay campaign intent, evidence and next steps.',
});

export function operationLabel(op) {
  return OPERATION_LABELS[op] || OPERATION_LABELS.idle;
}

export function operationTagline(op) {
  return OPERATION_TAGLINES[op] || OPERATION_TAGLINES.idle;
}

function hasActiveTelemetrySession(input) {
  const session = String(input?.sessionState || '').trim().toLowerCase();
  return session === 'active';
}

/**
 * deriveOperationSignal
 *
 * Picks one operation candidate from local evidence and labels why it may be
 * shown. "Observed" is reserved for current-session telemetry that directly
 * supports the mode. Heuristics remain "suggested"; no signal remains
 * "unknown". A Commander selection is applied later by deriveCommanderContext.
 */
/* R0-4 hostile contact truth.

   `/combat/snapshot` returns `{ combat: { threat: { under_attack: { value } },
   workflow: { interdiction_active: { value } } } }` — provenance-wrapped
   fields nested two levels deep. Consumers previously read `combat.under_attack`,
   a flat property that never exists on that payload, so hostile contact could
   never be reported at all while the Threat Watch card separately hardcoded
   "No hostile contact". This accessor reads the real shape (tolerating an
   already-unwrapped object) and, critically, returns `null` — Unknown — when
   the fact has not been reported, so absence of telemetry is never rendered as
   absence of threat. */
function combatFactValue(input, group, fieldName) {
  const root = input?.combat || null;
  if (!root) return null;
  const combat = root.combat || root;
  /* Real payload: combat[group][fieldName].value. A flat combat[fieldName]
     shape is also accepted so a caller holding an already-flattened object
     still resolves. Anything unreported stays null, i.e. Unknown. */
  const field = combat?.[group]?.[fieldName] !== undefined
    ? combat[group][fieldName]
    : combat?.[fieldName];
  if (field === undefined || field === null) return null;
  const value = (typeof field === 'object' && 'value' in field) ? field.value : field;
  return value === undefined ? null : value;
}

/**
 * deriveHostileContact
 *
 * Single source of hostile-contact truth for every Operations surface.
 * Returns one of:
 *   { state: 'hostile',  ... }  a supported local fact says hostile contact
 *   { state: 'clear',    ... }  a supported local fact says no hostile contact
 *   { state: 'unknown',  ... }  no supported reading — never claimed as clear
 */
export function deriveHostileContact(input) {
  const interdiction = combatFactValue(input, 'workflow', 'interdiction_active');
  const underAttack = combatFactValue(input, 'threat', 'under_attack');

  if (interdiction === true) {
    return { state: 'hostile', label: 'Hostile interdiction', detail: 'Interdiction in progress.' };
  }
  if (underAttack === true) {
    return { state: 'hostile', label: 'Hostile contact', detail: 'Hostile contact engaged.' };
  }
  /* An explicit `false` reading is a supported fact and may be reported as
     clear. A missing reading may not — that is Unknown.

     R1 wording review: `under_attack=false` is written only by
     `record_session_boundary` (combat_state.py) on an observed journal
     boundary such as FSDJump or Docked, and the only signal that raises it
     again is HullDamage. So the reading is anchored to an observed event, but
     its continued truth rests on no hostile telemetry having arrived since —
     a hostile that has not yet hit the hull is not represented. "Detected" is
     therefore the accurate verb: it claims the state of local detection, not
     the state of local space. */
  if (underAttack === false) {
    return {
      state: 'clear',
      label: 'No hostile contact detected',
      detail: 'Local combat telemetry has detected no hostile contact since the '
        + 'last observed session boundary.',
    };
  }
  return {
    state: 'unknown',
    label: 'Hostile contact: Unknown',
    detail: 'Local combat telemetry has not reported threat state.',
  };
}

export function deriveOperationSignal(input) {
  const state    = input?.state || null;
  const heat     = input?.heat || null;
  const cargo    = input?.cargo || null;
  const navSnap  = input?.navSnap || null;
  const combat   = input?.combat || null;
  const local    = input?.localContext || null;
  const telemetryActive = hasActiveTelemetrySession(input);

  /* R0-4: read the real nested combat payload shape. */
  if (telemetryActive && deriveHostileContact(input).state === 'hostile') {
    return {
      operation: 'combat',
      confidence: 'observed',
      evidence: 'active local combat telemetry',
    };
  }

  const localDocked = local?.stationBrief?.dockedLabel === 'Docked'
    && local?.stationBrief?.currentEligible !== false;
  if (state?.is_docked === true || localDocked) {
    return {
      operation: 'station',
      confidence: telemetryActive ? 'observed' : 'suggested',
      evidence: telemetryActive
        ? 'current-session local docking state'
        : 'last-known local docking context',
    };
  }

  const route = navSnap?.active_route;
  if (route?.destination) {
    return {
      operation: 'travel',
      confidence: telemetryActive ? 'observed' : 'suggested',
      evidence: telemetryActive
        ? 'current-session local navigation route'
        : 'last-known local navigation route',
    };
  }

  const items = Array.isArray(cargo?.inventory) ? cargo.inventory : [];
  const localCargoItems = Array.isArray(local?.cargoHold?.inventory) ? local.cargoHold.inventory : [];
  if (items.length > 0 || localCargoItems.length > 0) {
    // Pure mining-relevant cargo with refinery loadout would point at mining.
    // Without a verified loadout signal, prefer the trading workspace by default.
    return {
      operation: 'trading',
      confidence: 'suggested',
      evidence: 'local cargo is present',
    };
  }

  if (telemetryActive && (
    heat?.state === 'damage' || heat?.state === 'critical'
  )) {
    return {
      operation: 'exploration',
      confidence: 'suggested',
      evidence: 'local heat state may need a safety-focused workspace',
    };
  }

  return {
    operation: 'idle',
    confidence: 'unknown',
    evidence: 'no operation signal is loaded',
  };
}

/**
 * Compatibility helper retained for existing consumers that only need the
 * operation id. New surfaces should consume deriveOperationSignal or the full
 * Commander Context so confidence is never lost.
 */
export function deriveSuggestedOperation(input) {
  return deriveOperationSignal(input).operation;
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

function collectActiveInterrupts(input) {
  const state  = input?.state || null;
  const heat   = input?.heat || null;
  const combat = input?.combat || null;
  const mods   = input?.mods || null;

  const interrupts = [];
  const push = (id, severity, label, detail) => {
    interrupts.push({ id, severity, label, detail });
  };

  /* R0-4: previously read flat properties that never exist on the combat
     snapshot payload, so neither interrupt could ever fire. */
  const hostile = deriveHostileContact(input);
  if (hostile.state === 'hostile') {
    const isInterdiction = hostile.label === 'Hostile interdiction';
    push(
      isInterdiction ? 'interdiction' : 'combat',
      'critical',
      isInterdiction ? 'Interdiction' : 'Under fire',
      hostile.detail,
    );
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

export function deriveActiveInterrupts(input) {
  return hasActiveTelemetrySession(input) ? collectActiveInterrupts(input) : [];
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
      /* R0-5 (same class): '0 t' asserted an empty hold from the absence of
         any reading. Unknown stays Unknown. */
      : (items.length > 0 ? `${items.length} types` : (localCargo?.hasCargo ? localCargo.usedLabel : 'Unknown')));

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

  const watchItems = [
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
    ];
  return {
    items: hasActiveTelemetrySession(input)
      ? watchItems
      : watchItems.map((item) => ({ ...item, severity: 'unknown' })),
  };
}

/**
 * deriveCommanderContext
 *
 * Top-level builder. Returns the full Commander Context model that drives
 * Dashboard, Operations, and other surfaces.
 */
export function deriveCommanderContext(input, manualOperation) {
  const operationSignal = deriveOperationSignal(input);
  const suggested  = operationSignal.operation;
  const telemetryActive = hasActiveTelemetrySession(input);
  const observedInterrupts = collectActiveInterrupts(input);
  const interrupts = telemetryActive ? observedInterrupts : [];

  const hasManualOperation = Boolean(
    manualOperation && PRIMARY_OPERATIONS.includes(manualOperation));
  let primary = hasManualOperation ? manualOperation : suggested;
  let operationConfidence = hasManualOperation ? 'manual' : operationSignal.confidence;
  let operationEvidence = hasManualOperation
    ? 'Commander-selected workspace'
    : operationSignal.evidence;

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
    operationConfidence = 'suggested';
    operationEvidence = 'active critical local interrupt suggests a safety-focused workspace';
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
    operationConfidence,
    operationEvidence,
    manualOperation: hasManualOperation ? manualOperation : null,
    location,
    contextSpine: spine,
    watch: deriveWatchModel(input),
    interrupts,
    telemetryActive,
    interruptsSuppressed: !telemetryActive && observedInterrupts.length > 0,
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
  /* R0-5 (same class): an unread cargo count is not zero. Falling back to
     `cargoItems.length` turned an empty/unloaded inventory into a confident
     0, which then rendered as "No cargo detected" during cold start. Only a
     genuinely observed count is used; otherwise the count stays null and the
     summary says so. */
  const cargoCount = state?.cargo_count != null
    ? state.cargo_count
    : (localCargo?.used != null
      ? localCargo.used
      : (cargoItems.length > 0 ? cargoItems.length : null));
  const cargoCap   = state?.cargo_capacity ?? localCargo?.capacity ?? null;
  const route      = navSnap?.active_route?.destination || null;
  const location = deriveCommanderLocationState(local, state, navSnap, {});
  const stationName = location.stationName;
  const dockingState = location.dockingState;
  const docked = dockingState === 'docked';
  const lastKnownDocked = dockingState === 'last_known_docked';
  const partialStation = dockingState === 'partial';
  /* R0-1: a market snapshot may be from another station entirely, so the
     summary names its provenance instead of implying the current station. */
  const marketLine = local?.marketSearch?.available
    ? local.marketSearch.rowsPhrase
    : 'No local market snapshot loaded';

  const cargoSummary = cargoCount != null && cargoCap != null
    ? `${cargoCount} / ${cargoCap} t`
    : (cargoItems.length > 0
      ? `${cargoItems.length} cargo types`
      /* R0-5 (same class): absence of a cargo reading is not an empty hold. */
      : (localCargo?.hasCargo ? localCargo.usedLabel
        : (cargoCount === 0 ? 'Hold empty' : 'Cargo not loaded')));

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
    /* R2-9: `operation` marks an affordance that switches the Operations mode
       rather than transferring to another route. Without it this rendered a
       bare link to `#/operations` — the route the Commander is already on. */
    cargo: {
      id: 'cargo', label: 'Cargo', summary: cargoSummary,
      route: null, operation: 'trading',
      emptyAction: null, empty: cargoItems.length === 0,
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
    /* R0-4: was the constant 'No hostile contact', asserted regardless of
       telemetry. Now reports only what local combat telemetry supports, and
       says Unknown when it supports nothing. */
    /* R2-9: Threat Watch IS this card. Its "Open Threat Watch" link pointed at
       `#/operations`, i.e. at the surface already showing it, so the link is
       gone rather than pointed somewhere invented. */
    combatWatch: {
      id: 'combatWatch', label: 'Threat Watch',
      summary: deriveHostileContact(input).label,
      route: null, emptyAction: null, empty: false,
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
      /* R2-9: switches operation rather than linking to the current route. */
      return { label: 'Open Cargo', route: null, operation: 'trading' };
    case 'trading':
      return { label: 'Search a commodity', route: '#/intel' };
    /* R2-9 (closing the P14-E04 remainder): this returned
       { 'Open Threat Watch', '#/operations' } — a primary action pointing at
       the route the Commander is already on, and at a Threat Watch surface
       that is the support card two rows below it. A handoff to nowhere is not
       an action, and no destination is invented to replace it: Combat's
       primary action is whatever local state actually supports, which today is
       nothing. Combat still renders readiness, the Threat Watch state, its
       blockers and its support tools. */
    case 'combat':
      return null;
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
