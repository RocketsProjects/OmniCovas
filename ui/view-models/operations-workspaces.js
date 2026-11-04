/**
 * OmniCOVAS Operations workspaces view-model.
 *
 * Converts source-backed local state into operation-specific workspace decks
 * (Mining, Trading, Combat, Exploration, Travel, Station, Squadron, Idle).
 *
 * Pilot-first. Source posture lives in the proof bundle, not the workspace
 * default surface.
 */

'use strict';

import { deriveSupportSystems, derivePrimaryAction, operationLabel } from './commander-context.js';

const WORKSPACE_QUESTIONS = Object.freeze({
  idle:        'Select an operation to focus the command deck.',
  mining:      'What am I mining, how full am I, what tools matter, and where should I sell?',
  trading:     'What should I buy or sell, where, and why?',
  combat:      'Am I threatened, engaged, damaged, or ready?',
  exploration: 'What discovery and system information matters now?',
  travel:      'Where am I going, what is next, and is movement safe?',
  station:     'What can I do here?',
  squadron:    'What local coordination context exists now?',
  bgs:         'Which BGS objective am I pursuing right now?',
  powerplay:   'Which Power objective am I pursuing right now?',
});

/* R2-3: these are SUPPORT TOOLS inside the one canonical next-action surface,
   not a second "quick next actions" concept. `deriveWorkflowOutlook` folds them
   in and de-duplicates against workflow and handoff actions.

   R2-9: entries that pointed at `#/operations` without switching mode were
   removed — a link to the route you are already on is not a handoff. The
   `open-cargo` / `cargo` entries stay because they do switch operation. */
const WORKSPACE_QUICK_TOOLS = Object.freeze({
  idle:        [],
  mining:      [
    { id: 'sell-search', label: 'Search sell prices', route: '#/intel' },
    { id: 'open-cargo',  label: 'Open Cargo',         operation: 'trading' },
    { id: 'route',       label: 'Open Route',         route: '#/navigation' },
  ],
  trading:     [
    { id: 'commodity',   label: 'Commodity search', route: '#/intel' },
    { id: 'station',     label: 'Station brief',    route: '#/intel' },
    { id: 'route',       label: 'Open Route',       route: '#/navigation' },
    { id: 'cargo',       label: 'Open Cargo',       operation: 'trading' },
  ],
  combat:      [
    { id: 'loadout',     label: 'Loadout',      route: '#/dashboard' },
    { id: 'log',         label: 'Recent events',route: '#/activity-log' },
  ],
  exploration: [
    { id: 'system',      label: 'System brief', route: '#/intel' },
    { id: 'route',       label: 'Open Route',   route: '#/navigation' },
    { id: 'log',         label: 'Recent scans', route: '#/activity-log' },
  ],
  travel:      [
    { id: 'route',       label: 'Open Route',   route: '#/navigation' },
    { id: 'system',      label: 'System brief', route: '#/intel' },
  ],
  /* R2-3: `route` and `engineering` were the two affordances that existed
     ONLY on the deleted static Docked Context card. They are preserved here so
     removing that card removed duplication without removing reachability. */
  station:     [
    /* No 'Station brief' tool here: the primary action for this mode already
       IS "Open Station Brief" to the same route, and two entries that differ
       only in wording read as a duplicate even though they de-duplicate
       cleanly by identity. */
    { id: 'commodity',   label: 'Commodity search',  route: '#/intel' },
    { id: 'module',      label: 'Module search',     route: '#/intel' },
    { id: 'cargo',       label: 'Open Cargo',        operation: 'trading' },
    { id: 'route',       label: 'Plot route',        route: '#/navigation' },
    { id: 'engineering', label: 'Engineering plans', route: '#/engineering' },
  ],
  squadron:    [
    { id: 'squadron',    label: 'Open Squadron', route: '#/squadrons' },
    { id: 'log',         label: 'Recent events', route: '#/activity-log' },
  ],
  bgs:         [
    { id: 'intel-faction', label: 'Faction facts',  route: '#/intel' },
    { id: 'route',         label: 'Open Route',     route: '#/navigation' },
    { id: 'log',           label: 'Recent events',  route: '#/activity-log' },
  ],
  powerplay:   [
    { id: 'intel-power',   label: 'Power facts',    route: '#/intel' },
    { id: 'route',         label: 'Open Route',     route: '#/navigation' },
    { id: 'log',           label: 'Recent events',  route: '#/activity-log' },
  ],
});

export function workspaceQuestion(operation) {
  return WORKSPACE_QUESTIONS[operation] || WORKSPACE_QUESTIONS.idle;
}

export function workspaceQuickTools(operation) {
  return (WORKSPACE_QUICK_TOOLS[operation] || WORKSPACE_QUICK_TOOLS.idle).slice();
}

/**
 * deriveObjective
 *
 * Returns a short pilot-facing objective line for the workspace header.
 * Returns null when no honest objective is available from local state.
 */
export function deriveObjective(operation, input) {
  const state = input?.state || null;
  const cargo = input?.cargo || null;
  const navSnap = input?.navSnap || null;
  const local = input?.localContext || null;

  const localCargoItems = Array.isArray(local?.cargoHold?.inventory) ? local.cargoHold.inventory : [];
  const items = Array.isArray(cargo?.inventory) && cargo.inventory.length > 0
    ? cargo.inventory
    : localCargoItems;
  const top = items[0]?.display || items[0]?.name;
  const route = navSnap?.active_route?.destination;
  const station = state?.current_station || local?.stationBrief?.stationName;
  const docked = state?.is_docked === true || local?.stationBrief?.dockedLabel === 'Docked';
  const market = local?.marketSearch;

  switch (operation) {
    case 'mining':
      if (items.length > 0) {
        /* R0-1: the market snapshot is not necessarily this station's market.
           Use the provenance vocabulary owned by deriveMarketSearch rather
           than asserting "current station". */
        const marketSuffix = market?.available
          ? ` Market snapshot: ${market.rowsPhrase}.`
          : ' No local market snapshot loaded.';
        return `${items.length} cargo type${items.length === 1 ? '' : 's'} on board${top ? ` - top: ${top}` : ''}.${marketSuffix}`;
      }
      return 'No cargo detected - start mining or open Cargo support.';
    case 'trading':
      if (items.length > 0) return `${items.length} cargo type${items.length === 1 ? '' : 's'} ready for local price search.`;
      return market?.available
        ? `${market.rowsPhrase}.`
        : 'No cargo to sell - search the local market snapshot when loaded.';
    case 'combat': {
      /* R7 (P14-E05): this was the constant 'Watching for hostile contact.',
         which claimed a posture regardless of what telemetry said. The derived
         summary is the workflow's own reading; it is still NOT the Commander
         Objective, which `deriveGoalSlot` owns separately. */
      const combat = input?.combatWorkflow || null;
      if (combat?.available === true) {
        return combat.stage_detail || combat.stage_label || 'Combat state Unknown.';
      }
      return 'Combat workflow not loaded.';
    }
    case 'exploration':
      if (route) return `Plotted to ${route}.`;
      if (state?.current_system || local?.systemBrief?.systemName) {
        return `Currently in ${state?.current_system || local.systemBrief.systemName}.`;
      }
      return 'Scan and discovery context will appear here.';
    case 'travel':
      if (route) return `Next destination: ${route}.`;
      return 'No route plotted - open Navigation to plot one.';
    case 'station':
      if (docked && station) return `Docked at ${station}.`;
      if (docked) return 'Docked.';
      return 'Undocked - dock to enable station services.';
    case 'squadron':
      return 'Local coordination only. No outbound transport in this build.';
    case 'bgs':
      // Derives from API response only (no invented state).
      // No localStorage auto-reopen for Phase 9 modes.
      return input?.activeCampaign?.title
        ? `BGS campaign: ${input.activeCampaign.title}`
        : 'No active BGS objective. Add one to focus the deck.';
    case 'powerplay':
      return input?.activeCampaign?.title
        ? `Powerplay campaign: ${input.activeCampaign.title}`
        : 'No active Powerplay objective. Add one to focus the deck.';
    case 'idle':
    default:
      return 'Select an operation to focus the command deck.';
  }
}

/* ── Exploration workflow seam (R5) ───────────────────────────────────
   The backend derives the exploration stage, its blockers and its handoffs.
   These helpers are the only place the cockpit reads that payload, so the
   stage drives the primary action, the Blockers slot and the Next Actions list
   from ONE reading rather than three surfaces each interpreting it their own
   way.

   Two boundaries are held here deliberately:

     * a derived exploration step is NOT the Commander objective. It never
       reaches `deriveGoalSlot`, never overwrites a persisted objective, and
       carries `owner: derived` all the way from the service;
     * work remaining is NOT a blocker. Only the conditions the backend
       declares with a `condition_id` reach the blocker mapping, and relevance
       is still decided by `isBlockingCondition` above. */

export function explorationWorkflow(input) {
  const workflow = input?.explorationSnapshot?.workflow || null;
  return workflow && workflow.available === true ? workflow : null;
}

/* Stage-driven handoffs, by the id the service assigns them. Operations names
   the route that owns the detail; it never renders that detail itself. */
const EXPLORATION_STAGE_HANDOFF = Object.freeze({
  transit: 'navigation_route',
  arrived: 'intel_system',
  system_survey: 'intel_system',
  surface_survey: 'intel_system',
  biology: 'intel_biology',
  departure_ready: 'navigation_route',
});

const EXPLORATION_ROUTE_HASH = Object.freeze({
  '/intel': '#/intel',
  '/navigation': '#/navigation',
});

/* The action list already carries a canonical command for plotting a route,
   and Navigation is a support system in more modes than this one. A stage
   action reading "Plot next route in Navigation" beside an existing "Plot a
   route" is one command listed twice under two names — the R1-4 duplication,
   reintroduced by wording. The stage action adopts the canonical label so the
   two merge and the survivor takes the stronger tier; the exploration card's
   handoff strip keeps the longer label, because there its job is to name the
   route that owns route planning. */
const EXPLORATION_CANONICAL_ACTION_LABEL = Object.freeze({
  navigation_route: 'Plot a route',
});

/* R5-10: the action that answers the CURRENT stage, rather than the mode's
   generic "Open Navigation". It replaces the generic action rather than being
   listed beside it, so there is still exactly one primary action per mode and
   the Commander is not offered two doors to the same room. */
export function deriveExplorationStageAction(operation, input) {
  if (operation !== 'exploration') return null;
  const workflow = explorationWorkflow(input);
  if (!workflow) return null;

  const handoffId = EXPLORATION_STAGE_HANDOFF[workflow.stage];
  if (!handoffId) return null;
  const handoff = (workflow.handoffs || []).find((entry) => entry.id === handoffId);
  if (!handoff) return null;

  const route = EXPLORATION_ROUTE_HASH[handoff.route];
  if (!route) return null;

  /* The step names the thing to do in the game; the handoff names where the
     app can help with it. Both are shown, and neither is presented as the
     other. */
  const step = workflow.step?.label || null;
  return {
    label: EXPLORATION_CANONICAL_ACTION_LABEL[handoffId] || handoff.label,
    route,
    operation: null,
    why: step
      ? `${step}. ${workflow.stage_detail || ''}`.trim()
      : (workflow.stage_detail || null),
    handoff: {
      sectionId: handoff.section_id || '',
      entityId: handoff.entity_id || '',
      targetLabel: handoff.label,
      reason: handoff.reason || '',
    },
  };
}

/* R5-9 / P14-F05: exploration blockers reach the Commander through the ONE
   outlook card, in the same shape as every other blocker, rather than as a
   parallel list inside the exploration card. The service already decided what
   genuinely blocks; this maps it, and `isBlockingCondition` still has the
   final say on relevance. */
export function deriveExplorationBlockerEntries(operation, input) {
  if (operation !== 'exploration') return [];
  const snapshot = input?.explorationSnapshot || null;
  const blockers = Array.isArray(snapshot?.blockers) ? snapshot.blockers : [];
  return blockers
    .filter((blocker) => blocker && blocker.condition_id)
    .map((blocker) => ({
      id: `exploration-${blocker.blocker_id}`,
      conditionId: blocker.condition_id,
      label: blocker.label || 'Unknown',
      detail: blocker.detail || 'Reported by the local exploration workflow.',
      source: blocker.source_id || 'Local exploration history',
      /* Only the route condition has an action Operations can offer; an
         unreadable local history is not something a button fixes, and
         inventing one would be a dead end (R2-9). */
      action: blocker.condition_id === 'exploration_route'
        /* Same canonical command as the stage action and the Navigation
           support entry, so all three merge into one line at the strongest
           tier rather than stacking three ways to open the planner. */
        ? { label: 'Plot a route', route: '#/navigation', operation: null }
        : null,
    }));
}

/* ── Economic workflow seam (R6) ────────────────────────────────────
   Trade and Mining follow the shape R5 established for Exploration: the
   backend derives the stage, its blockers and its handoffs, and this is the one
   place the cockpit reads that payload. The stage drives the primary action,
   the Blockers slot and the Next Actions list from ONE reading.

   Both keep the same two boundaries:

     * a derived step is NOT the Commander objective — it never reaches
       `deriveGoalSlot` and carries `owner: derived` from the service;
     * work remaining is NOT a blocker. Only conditions the backend declares
       with a `condition_id` are mapped, and `isBlockingCondition` still has the
       final say. */

export function tradeWorkflow(input) {
  const workflow = input?.tradeWorkflow || null;
  return workflow && workflow.available === true ? workflow : null;
}

export function miningWorkflow(input) {
  const workflow = input?.miningWorkflow || null;
  return workflow && workflow.available === true ? workflow : null;
}

/* Stage-driven handoffs, by the id the service assigns them. Stages with no
   entry deliberately fall back to the mode's generic primary action: there is
   no app action for "fit a refinery" or "point the lasers at an asteroid", and
   inventing one would be a button that does nothing (R2-9, R6-7). */
const TRADE_STAGE_HANDOFF = Object.freeze({
  cargo_aboard: 'intel_market',
  market_review: 'intel_commodity',
  no_local_demand: 'intel_commodity',
  sell_opportunity: 'intel_commodity',
});

const MINING_STAGE_HANDOFF = Object.freeze({
  return: 'navigation_route',
  sell: 'intel_commodity',
  complete_ready: 'navigation_route',
});

const ECONOMY_ROUTE_HASH = Object.freeze({
  '/intel': '#/intel',
  '/navigation': '#/navigation',
});

/* The canonical route command, so a stage action and a blocker remediation
   pointing at Navigation merge into one line rather than stacking two names for
   one door. R5 established this after acceptance caught the duplicate. */
const ECONOMY_CANONICAL_ACTION_LABEL = Object.freeze({
  navigation_route: 'Plot a route',
});

function economyStageAction(workflow, stageMap, originSection) {
  if (!workflow) return null;
  const handoffId = stageMap[workflow.stage];
  if (!handoffId) return null;
  const handoff = (workflow.handoffs || []).find((entry) => entry.id === handoffId);
  if (!handoff) return null;
  const route = ECONOMY_ROUTE_HASH[handoff.route];
  if (!route) return null;

  const step = workflow.step?.label || null;
  return {
    label: ECONOMY_CANONICAL_ACTION_LABEL[handoffId] || handoff.label,
    route,
    operation: null,
    why: step
      ? `${step}. ${workflow.stage_detail || ''}`.trim()
      : (workflow.stage_detail || null),
    handoff: {
      sectionId: handoff.section_id || '',
      entityId: handoff.entity_id || '',
      targetLabel: handoff.label,
      targetQuery: handoff.query || '',
      reason: handoff.reason || '',
      originSectionId: originSection,
    },
  };
}

export function deriveEconomyStageAction(operation, input) {
  if (operation === 'trading') {
    return economyStageAction(
      tradeWorkflow(input), TRADE_STAGE_HANDOFF, 'operations-trading-workspace',
    );
  }
  if (operation === 'mining') {
    return economyStageAction(
      miningWorkflow(input), MINING_STAGE_HANDOFF, 'operations-mining-workspace',
    );
  }
  return null;
}

/* Blockers reach the Commander through the ONE outlook card, in the same shape
   as every other blocker, rather than as a second list inside the workflow
   card. The service already decided what genuinely blocks. */
export function deriveEconomyBlockerEntries(operation, input) {
  const workflow = operation === 'trading'
    ? (input?.tradeWorkflow || null)
    : (operation === 'mining' ? (input?.miningWorkflow || null) : null);
  const blockers = Array.isArray(workflow?.blockers) ? workflow.blockers : [];
  return blockers
    .filter((blocker) => blocker && blocker.condition_id)
    .map((blocker) => ({
      id: `${operation}-${blocker.blocker_id}`,
      conditionId: blocker.condition_id,
      label: blocker.label || 'Unknown',
      detail: blocker.detail || 'Reported by the local workflow.',
      source: blocker.source_id || 'Local state',
      /* Only a route condition has an action Operations can offer. An
         unreadable manifest, an unfitted refinery and an empty limpet rack are
         not things a button in this app fixes, and offering one would be a
         dead end (R2-9). */
      action: String(blocker.condition_id || '').endsWith('_route')
        ? { label: 'Plot a route', route: '#/navigation', operation: null }
        : null,
    }));
}

/* ── Combat workflow seam (R7) ────────────────────────────
   Same seam as R5/R6: the backend derives the stage, its blockers and its
   handoffs, and this is the only place the cockpit reads that payload, so the
   stage drives the primary action, the Blockers slot and the Next Actions list
   from ONE reading.

   Two Combat-specific boundaries are held here:

     * a threat is NOT a blocker. Hostile contact reaches the Commander through
       `attention` and through the existing watch strip; it never enters the
       blocker mapping, because it does not prevent the combat workflow — it is
       the combat workflow;
     * a derived combat step is NOT the Commander objective. It carries
       `owner: derived` from the service and never reaches `deriveGoalSlot`. */

export function combatWorkflow(input) {
  const workflow = input?.combatWorkflow || null;
  return workflow && workflow.available === true ? workflow : null;
}

/* Stages with no entry fall back to the mode's generic primary action. There is
   deliberately no entry for `preparation` or `idle`: OmniCOVAS cannot repair a
   hull, restock a module or start a fight, and offering a button that does none
   of those would be the dead end R2-9 closed. */
const COMBAT_STAGE_HANDOFF = Object.freeze({
  interdicted: 'navigation_route',
  engaged: 'navigation_route',
  recovery: 'navigation_route',
  post_engagement: 'activity_log',
  review_ready: 'activity_log',
});

const COMBAT_ROUTE_HASH = Object.freeze({
  '/intel': '#/intel',
  '/navigation': '#/navigation',
  '/activity-log': '#/activity-log',
});

const COMBAT_CANONICAL_ACTION_LABEL = Object.freeze({
  navigation_route: 'Plot a route',
  activity_log: 'Open Activity Log',
});

export function deriveCombatStageAction(operation, input) {
  if (operation !== 'combat') return null;
  const workflow = combatWorkflow(input);
  if (!workflow) return null;
  const handoffId = COMBAT_STAGE_HANDOFF[workflow.stage];
  if (!handoffId) return null;
  const handoff = (workflow.handoffs || []).find((entry) => entry.id === handoffId);
  if (!handoff) return null;
  const route = COMBAT_ROUTE_HASH[handoff.route];
  if (!route) return null;

  const step = workflow.step?.label || null;
  return {
    label: COMBAT_CANONICAL_ACTION_LABEL[handoffId] || handoff.label,
    route,
    operation: null,
    why: step
      ? `${step}. ${workflow.stage_detail || ''}`.trim()
      : (workflow.stage_detail || null),
    handoff: {
      sectionId: handoff.section_id || '',
      entityId: handoff.entity_id || '',
      targetLabel: handoff.label,
      targetQuery: handoff.query || '',
      reason: handoff.reason || '',
      originSectionId: 'operations-combat-workspace',
    },
  };
}

/* Blockers reach the Commander through the ONE outlook card. The service
   already decided what genuinely blocks; `isBlockingCondition` still decides
   relevance for the mode. */
export function deriveCombatBlockerEntries(operation, input) {
  if (operation !== 'combat') return [];
  const workflow = input?.combatWorkflow || null;
  const blockers = Array.isArray(workflow?.blockers) ? workflow.blockers : [];
  return blockers
    .filter((blocker) => blocker && blocker.condition_id)
    .map((blocker) => ({
      id: `combat-${blocker.blocker_id}`,
      conditionId: blocker.condition_id,
      label: blocker.label || 'Unknown',
      detail: blocker.detail || 'Reported by the local workflow.',
      source: blocker.source_id || 'Local state',
      /* Only the escape-route condition has an action this app can offer. A
         damaged hull and a destroyed module are not things a button here
         fixes, and OmniCOVAS performs no in-game action at all. */
      action: String(blocker.condition_id || '').endsWith('_route')
        ? { label: 'Plot a route', route: '#/navigation', operation: null }
        : null,
    }));
}

/**
 * deriveWorkspace
 *
 * Composes the full workspace view-model for a primary operation.
 */
export function deriveWorkspace(operation, input) {
  const supports = deriveSupportSystems(operation, input);
  const action = deriveExplorationStageAction(operation, input)
    || deriveEconomyStageAction(operation, input)
    || deriveCombatStageAction(operation, input)
    || derivePrimaryAction(operation, input);
  const objective = deriveObjective(operation, input);
  const readiness = deriveOperationReadiness(operation, input);
  return {
    operation,
    title: operationLabel(operation),
    question: workspaceQuestion(operation),
    objective,
    supports,
    action,
    quickTools: workspaceQuickTools(operation),
    readiness,
    outlook: deriveWorkflowOutlook(operation, input, {
      objective, supports, action, readiness,
    }),
  };
}

/* ── Goals / blockers / next actions (PB14-02 first slice) ─────────────────
   Read-only synthesis over derivations that are already source-backed:
   goals come from the active campaign (commander-entered) or the derived
   objective (source-derived) and are labeled as such; blockers are named
   readiness attentions and empty support systems — Unknown readings are
   never blockers; next actions carry an honest "why" naming the state or
   blocker that makes them relevant. No persistence, no AI, no invention. */

const OUTLOOK_CAVEAT =
  'Synthesized from source-backed local state and existing derivations '
  + 'only. Unknown readings are never treated as blockers. Commander-entered '
  + 'goals are labeled.';

/* ── The one objective slot (R2-1 / PB14-R1) ──────────────────────────────
   R2 established a single objective line in the Operations hierarchy and
   marked it as PB14-R1's insertion point. R3 fills it: a persisted
   Commander-entered objective becomes another `kind` on this same line, never
   another card. There is exactly one semantic objective owner in Operations,
   and this is it.

   Ranking, per PB14-R1 §3 ("ranked above the derived objective and alongside
   the campaign title"):

     1. the persisted Commander objective for this mode  — stated intent
     2. Unknown, when the objective store could not be read
     3. the active campaign title (BGS / Powerplay only)  — also authored, but
        it belongs to a campaign entity rather than to this cockpit slot
     4. the derived objective                            — a labelled stand-in
     5. Not set

   A persisted objective outranks the campaign title because it is the direct
   answer to "what am I trying to accomplish in this mode?", given by the
   Commander in this slot. The campaign keeps its own surface; nothing is
   hidden, and no second objective owner is created to show both.

   Package is not objective and mode is not objective: when nothing above
   resolves, this says Not set rather than naming the mode. Unknown is never
   collapsed into Not set — a store that did not answer has not told us the
   Commander has no objective. */
export function deriveGoalSlot(operation, input, parts = {}) {
  const objective = parts.objective !== undefined
    ? parts.objective : deriveObjective(operation, input);
  const campaignTitle = parts.campaignTitle !== undefined
    ? parts.campaignTitle
    : ((operation === 'bgs' || operation === 'powerplay')
      ? (input?.activeCampaign?.title || null) : null);

  const served = input?.commanderObjective || null;
  const servedOperation = served?.operation || null;
  /* R1's scope guard, applied to this payload too: an answer computed for a
     different mode is never shown in this one's place. */
  const scoped = served && (!servedOperation || servedOperation === operation)
    ? served : null;

  const base = {
    text: 'Not set',
    kind: 'not_set',
    kindLabel: 'Not set',
    isSet: false,
    commanderEntered: false,
    objectiveId: null,
    state: null,
    /* Lifecycle facts the renderer needs. Kept here so affordances are
       decided once, from state, rather than re-derived per surface. */
    commanderObjectiveSet: false,
    available: true,
    pending: false,
  };

  if (input?.commanderObjectivePending === true && !scoped) {
    return {
      ...base,
      text: 'Loading',
      kind: 'pending',
      kindLabel: 'Loading',
      pending: true,
    };
  }

  if (scoped && scoped.available === false) {
    return {
      ...base,
      text: 'Unknown',
      kind: 'unknown',
      kindLabel: 'Unknown',
      available: false,
    };
  }

  const record = scoped?.objective || null;
  if (record && record.text) {
    const completed = record.state === 'completed';
    return {
      ...base,
      text: record.text,
      kind: completed ? 'commander_entered_completed' : 'commander_entered',
      kindLabel: completed ? 'Commander-entered · Completed' : 'Commander-entered',
      isSet: true,
      commanderEntered: true,
      objectiveId: record.objective_id || null,
      state: record.state || 'active',
      commanderObjectiveSet: true,
    };
  }

  if (campaignTitle) {
    return {
      ...base,
      text: campaignTitle,
      kind: 'commander_entered',
      kindLabel: 'Commander-entered',
      isSet: true,
      commanderEntered: true,
    };
  }

  if (objective) {
    return {
      ...base,
      text: objective,
      kind: 'source_derived',
      kindLabel: 'From local state',
      isSet: true,
      commanderEntered: false,
    };
  }

  return base;
}

export function deriveWorkflowOutlook(operation, input, parts = {}) {
  const readiness = parts.readiness || deriveOperationReadiness(operation, input);
  const supports = parts.supports || deriveSupportSystems(operation, input);
  const action = parts.action !== undefined
    ? parts.action
    : (deriveExplorationStageAction(operation, input)
      || deriveEconomyStageAction(operation, input)
      || deriveCombatStageAction(operation, input)
      || derivePrimaryAction(operation, input));
  const objective = parts.objective !== undefined
    ? parts.objective : deriveObjective(operation, input);

  const campaignTitle = (operation === 'bgs' || operation === 'powerplay')
    ? (input?.activeCampaign?.title || null) : null;
  const goal = deriveGoalSlot(operation, input, { objective, campaignTitle });

  /* R4-2: relevance is decided per operation, not by which cards a mode
     happens to render. Only a condition that blocks THIS operation reaches the
     Blockers slot; the rest stay where they already are.

     Unknown is never a blocker. A readiness row whose status is `unknown` means
     the local source has not reported — that is an absent fact, not an
     impediment, and treating it as one is the R0 defect class. */
  const blockers = [];
  const nonBlocking = [];
  (readiness?.checks || [])
    .filter((check) => check.status === 'attention')
    .forEach((check) => {
      const entry = {
        id: `readiness-${check.id}`,
        conditionId: check.id,
        label: check.label,
        detail: check.note || check.value || 'Needs attention.',
        source: 'Live local telemetry',
        action: null,
      };
      if (isBlockingCondition(operation, check.id)) blockers.push(entry);
      else nonBlocking.push(entry);
    });
  (supports || [])
    .filter((support) => support.empty && support.emptyAction)
    .forEach((support) => {
      const entry = {
        id: `support-${support.id}`,
        conditionId: support.id,
        label: support.label,
        detail: support.summary || 'Not available from local state.',
        source: 'Local state',
        action: { label: support.emptyAction, route: support.route,
          operation: support.operation || null },
      };
      if (isBlockingCondition(operation, support.id)) blockers.push(entry);
      else nonBlocking.push(entry);
    });
  /* R5-9 / R6-6 / R6-17 / R7-10: the workflow services' own blockers, through
     this one slot. Relevance is still decided by the declared condition, so a
     service cannot promote its own row past the cockpit's judgement. Combat's
     threat rows deliberately never arrive here — a hostile contact is an
     attention, not an impediment to the workflow it belongs to. */
  [
    ...deriveExplorationBlockerEntries(operation, input),
    ...deriveEconomyBlockerEntries(operation, input),
    ...deriveCombatBlockerEntries(operation, input),
  ].forEach((entry) => {
    if (isBlockingCondition(operation, entry.conditionId)) blockers.push(entry);
    else nonBlocking.push(entry);
  });

  const candidates = [];
  if (action) {
    candidates.push({
      label: action.label,
      route: action.route,
      operation: action.operation || null,
      /* The rationale explains why THIS action is relevant; it never restates
         the objective rendered one line above. Two layers carrying the same
         sentence is the duplication R2-6 closed, and a persisted Commander
         objective is not a campaign, so it must not be labelled as one. */
      /* R5: a stage-driven exploration action already carries its own reason —
         the current step and the stage that produced it — which is strictly
         more informative than the mode standing objective line. */
      why: action.why
        || ((goal.kind === 'commander_entered' && !goal.commanderObjectiveSet)
          ? `Active campaign: ${goal.text}`
          : (objective || 'Primary action for this operation.')),
      kind: 'workflow',
      priority: NEXT_ACTION_PRIORITY_WORKFLOW,
      blockerId: null,
      /* R5-11: when the action is a cross-route handoff, the context it needs
         to land on the right thing travels with it. */
      handoff: action.handoff || null,
    });
  }
  /* R4-4: a real blocker's remediation is the coherent next step, so it
     outranks the mode's generic primary action. */
  blockers
    .filter((blocker) => blocker.action)
    .forEach((blocker) => {
      candidates.push({
        label: blocker.action.label,
        route: blocker.action.route,
        operation: blocker.action.operation || null,
        why: `${blocker.label}: ${blocker.detail}`,
        kind: 'blocker_remediation',
        priority: NEXT_ACTION_PRIORITY_BLOCKER,
        blockerId: blocker.id,
      });
    });
  /* A condition that does not block this operation still keeps its action
     reachable — relevance filtering must not delete capability (R2-3). It
     simply ranks below the workflow action instead of above it. */
  nonBlocking
    .filter((entry) => entry.action)
    .forEach((entry) => {
      candidates.push({
        label: entry.action.label,
        route: entry.action.route,
        operation: entry.action.operation || null,
        why: `${entry.label}: ${entry.detail}`,
        kind: 'handoff',
        priority: NEXT_ACTION_PRIORITY_HANDOFF,
        blockerId: null,
      });
    });
  /* R2-3: support tools are part of the one canonical action surface, not a
     second "quick actions" concept rendered elsewhere on the same screen. */
  (parts.quickTools || workspaceQuickTools(operation)).forEach((tool) => {
    candidates.push({
      label: tool.label,
      route: tool.route || null,
      operation: tool.operation || null,
      why: null,
      kind: 'support_tool',
      priority: NEXT_ACTION_PRIORITY_SUPPORT,
      blockerId: null,
      toolId: tool.id || null,
    });
  });

  return {
    goal,
    blockers,
    /* Conditions that need attention but do not block this operation. Exposed
       so a surface can show them subordinately rather than silently dropping
       them; they are never rendered in the Blockers slot. */
    nonBlocking,
    nextActions: dedupeNextActions(candidates),
    caveat: OUTLOOK_CAVEAT,
  };
}

/* ── Next-action identity and de-duplication (R1-4) ───────────────────────
   The primary action and a blocker remediation routinely resolve to the same
   command: Travel rendered "Plot a route" twice in one list — once because no
   route is plotted, once because the Navigation support card is empty — with
   two different rationales. One command, listed twice, is not two things to do.

   Identity is the destination (route) plus the command (label), never the
   label alone: two actions that read the same but target different entities
   carry different routes and must stay distinct. Rationales are not discarded
   — the highest-priority one is shown and every distinct one is carried on
   `whyAll` for surfaces that want the full reasoning.

   Order is deterministic: workflow outranks handoffs, which outrank support
   tools, and equal ranks keep derivation order (Array.prototype.sort is
   stable), so repeated reads of unchanged state cannot reshuffle the list.

   R2-3: `kind` distinguishes the three internally so a renderer can weight
   them. It is not a taxonomy shown to the Commander — they read one list. */

/* R4-4: an action that clears something actually blocking this operation
   outranks the mode's generic primary action, which in turn outranks
   non-blocking remediations and support tools. Deterministic integer tiers,
   not a scoring model — the order must be explainable from state alone. */
const NEXT_ACTION_PRIORITY_BLOCKER = 0;
const NEXT_ACTION_PRIORITY_WORKFLOW = 1;
const NEXT_ACTION_PRIORITY_HANDOFF = 2;
const NEXT_ACTION_PRIORITY_SUPPORT = 3;

/* ── Blocker relevance (R4-2 / P14-C10) ───────────────────────────────────
   Before R4 a "blocker" meant "a readiness row needing attention" or "an empty
   support card that happened to carry an emptyAction". Relevance was therefore
   an accident of which supports a mode listed: Squadron showed "Plot a route"
   as a blocker because Navigation is one of its support cards, and Docked
   Context treated a missing market snapshot the same way.

   A blocker is now a condition that actually prevents progress on the selected
   operation, declared per operation and per condition. Everything else keeps
   rendering — readiness attentions stay in the Readiness card, empty supports
   stay support cards and still offer their action — it simply stops occupying
   the Blockers slot.

   Condition ids are the existing vocabulary: readiness check ids
   (`fuel`, `hull`, `shields`, `rebuy`, `cargo_space`, `modules`) and support
   system ids (`navigation`, `station`, `marketIntel`, `cargo`). Nothing new is
   invented, and nothing is inferred from Commander objective text. */
const OPERATION_BLOCKING_CONDITIONS = Object.freeze({
  /* No operation is selected, so no operation is blocked. */
  idle: Object.freeze([]),
  /* A full hold stops mining; a route does not. R6 adds the three conditions
     the mining workflow can genuinely be stopped by: an unreadable manifest,
     equipment an OBSERVED loadout shows is not there, and no limpets to
     collect with. Unknown module coverage is deliberately absent — silence is
     not absence, and R0's shield doctrine settled that. So is hotspot
     coverage, which no Commander action can clear. */
  mining: Object.freeze([
    'cargo_space', 'mining_cargo', 'mining_equipment', 'mining_limpets',
    'mining_route',
  ]),
  /* No hold, or no observed market to trade against. R6 adds an unreadable
     cargo manifest, and a route only for the one state where the sale cannot
     happen here and nothing is plotted elsewhere. A historical snapshot merely
     existing is not on this list. */
  trading: Object.freeze([
    'cargo_space', 'marketIntel', 'trade_cargo', 'trade_route',
  ]),
  /* Survivability and weapons. Cargo space and routes do not block a fight. */
  /* R7: the workflow service names its own conditions. `hull`, `shields` and
     `modules` stay for the readiness-derived blockers R4 established; the
     `combat_*` ids are the ones the Combat workflow emits. Threat is
     deliberately absent — hostile contact is an attention, not a blocker. */
  combat: Object.freeze([
    'hull', 'shields', 'modules',
    'combat_hull', 'combat_modules', 'combat_escape_route',
  ]),
  /* Fuel is the exploration constraint, plus the two conditions the R5
     exploration workflow can genuinely be stopped by: a route it needs and
     cannot have, and local facts it needs and cannot read. Work remaining is
     deliberately absent — an unmapped body is work, not an impediment, and
     R5-9 turns on keeping those two words apart. */
  exploration: Object.freeze(['fuel', 'exploration_route', 'exploration_source']),
  /* Travel is the one operation a missing route genuinely stops. */
  travel: Object.freeze(['navigation', 'fuel']),
  /* Station services need a station. */
  station: Object.freeze(['station']),
  /* Nothing in local state blocks squadron coordination. */
  squadron: Object.freeze([]),
  bgs: Object.freeze([]),
  powerplay: Object.freeze([]),
  engineering: Object.freeze([]),
});

/* Returns the condition ids that block `operation`. An unlisted operation
   blocks on nothing rather than on everything: a mode we have not reasoned
   about must not inherit a wall of warnings. */
export function blockingConditionsFor(operation) {
  return OPERATION_BLOCKING_CONDITIONS[operation] || OPERATION_BLOCKING_CONDITIONS.idle;
}

export function isBlockingCondition(operation, conditionId) {
  return blockingConditionsFor(operation).includes(conditionId);
}

/* Operations is the route the Commander is already on, so an action pointing
   there is only real if it changes the operation. Anything else is a link to
   the current screen dressed as a handoff (R2-9). */
const OPERATIONS_ROUTE = '#/operations';

function isDeadEndAction(candidate) {
  /* An action that switches the Operations mode is real work and carries
     `operation`. An action whose only destination is `#/operations` is a link
     to the screen the Commander is already looking at. */
  if (candidate?.operation) return false;
  return String(candidate?.route || '').trim().toLowerCase() === OPERATIONS_ROUTE;
}

export function nextActionIdentity(action) {
  const route = String(action?.route ?? (action?.operation ? `operation:${action.operation}` : ''))
    .trim().toLowerCase();
  const label = String(action?.label ?? '').trim().toLowerCase().replace(/\s+/g, ' ');
  return `${route}::${label}`;
}

function dedupeNextActions(candidates) {
  const byIdentity = new Map();
  candidates.filter((candidate) => !isDeadEndAction(candidate)).forEach((candidate) => {
    const id = nextActionIdentity(candidate);
    const existing = byIdentity.get(id);
    if (!existing) {
      byIdentity.set(id, {
        id,
        label: candidate.label,
        route: candidate.route,
        operation: candidate.operation || null,
        why: candidate.why,
        whyAll: candidate.why ? [candidate.why] : [],
        kind: candidate.kind,
        /* R1-5: keeps the action correlatable with the blocker it clears. */
        blockerId: candidate.blockerId,
        toolId: candidate.toolId || null,
        /* R5-11: the landing context travels with the action. Dropping it here
           was silent — the rendered handoff still worked, it just arrived with
           nothing to point at — which is exactly the class of loss a merge step
           is prone to. */
        handoff: candidate.handoff || null,
        priority: candidate.priority,
      });
      return;
    }
    if (candidate.why && !existing.whyAll.includes(candidate.why)) {
      existing.whyAll.push(candidate.why);
      if (!existing.why) existing.why = candidate.why;
    }
    if (existing.blockerId === null && candidate.blockerId) {
      existing.blockerId = candidate.blockerId;
    }
    if (!existing.toolId && candidate.toolId) existing.toolId = candidate.toolId;
    /* R4-4: one command reached from two places takes the stronger claim. The
       mode's primary action and a blocker's remediation are routinely the same
       command — Travel's "Plot a route" is both — and merging them must
       not leave the survivor wearing the weaker tier just because it happened
       to be pushed first. Ordering is then independent of insertion order. */
    if (candidate.priority < existing.priority) {
      existing.priority = candidate.priority;
      existing.kind = candidate.kind;
      /* The stronger claim brings its own context; a merged action must not
         keep pointing where the weaker one was going. */
      if (candidate.handoff) existing.handoff = candidate.handoff;
    }
    if (!existing.handoff && candidate.handoff) existing.handoff = candidate.handoff;
  });
  /* Stable: equal priorities keep insertion order, so the list does not
     reshuffle between renders of identical state. */
  return Array.from(byIdentity.values()).sort((a, b) => a.priority - b.priority);
}

/* ── Operation readiness (LNA-028) ────────────────────────────────────────
   The engine lives in the backend readiness service, which also answers the
   Dashboard and Engineering. This maps the served answer for rendering and
   deliberately does not recompute: a second implementation here is how ship
   vitals came to disagree with themselves across two renderers (LNA-027).
   When the service does not answer, that is said plainly rather than
   answered with a locally invented second opinion. */

const READINESS_CAVEAT =
  'State-backed checks from local telemetry only. Unknown means the local '
  + 'source has not reported that fact yet — never a failure.';

export function deriveOperationReadiness(operation, input) {
  const served = input?.readiness || null;
  /* R1-1: the served payload names the operation it was computed for. Before
     this, readiness was fetched once for `idle` and never re-fetched, so every
     mode rendered the idle profile as though it were its own. A payload that
     belongs to another operation is now never shown — the Commander is told
     this mode's readiness has not resolved yet rather than being handed the
     previous mode's answer under a new heading. */
  if (served && served.operation && served.operation !== operation) {
    return unresolvedReadiness(operation,
      'Readiness for this operation has not been resolved yet. The answer held '
      + 'locally was computed for a different operation and is not shown in its '
      + 'place.');
  }
  if (!served || !Array.isArray(served.checks)) {
    /* A request still in flight is not the same as a service that refused to
       answer, and must not be reported as one. */
    if (input?.readinessPending === true) {
      return unresolvedReadiness(operation,
        'Readiness for this operation is still being read from local state.');
    }
    return {
      operation,
      summary: 'Readiness unavailable',
      checks: [],
      unavailable: true,
      pending: false,
      caveat: 'The local readiness service did not answer. No readiness '
        + 'judgement is shown rather than one computed here from partial data.',
    };
  }
  return {
    operation: served.operation || operation,
    summary: served.summary || '',
    checks: served.checks.map((check) => ({
      id: check.id,
      label: check.label,
      value: check.value,
      status: check.status,
      note: check.note || null,
      readFrom: check.read_from || null,
    })),
    unavailable: false,
    pending: false,
    caveat: served.caveat || READINESS_CAVEAT,
  };
}

/* Readiness that has not resolved for the selected operation. Deliberately not
   `unavailable`: nothing has failed, and no check rows exist, so no blocker or
   next action can be synthesised from another operation's answer. */
function unresolvedReadiness(operation, caveat) {
  return {
    operation,
    summary: 'Readiness loading',
    checks: [],
    unavailable: false,
    pending: true,
    caveat,
  };
}
