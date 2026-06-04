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

const WORKSPACE_QUICK_TOOLS = Object.freeze({
  idle:        [{ id: 'open-ops', label: 'Pick operation', route: '#/operations' }],
  mining:      [
    { id: 'sell-search', label: 'Search sell prices', route: '#/intel' },
    { id: 'open-cargo',  label: 'Open Cargo',         route: '#/operations' },
    { id: 'threat',      label: 'Threat Watch',       route: '#/operations' },
    { id: 'route',       label: 'Open Route',         route: '#/navigation' },
  ],
  trading:     [
    { id: 'commodity',   label: 'Commodity search', route: '#/intel' },
    { id: 'station',     label: 'Station brief',    route: '#/intel' },
    { id: 'route',       label: 'Open Route',       route: '#/navigation' },
    { id: 'cargo',       label: 'Open Cargo',       route: '#/operations' },
  ],
  combat:      [
    { id: 'threat',      label: 'Threat Watch', route: '#/operations' },
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
    { id: 'threat',      label: 'Threat Watch', route: '#/operations' },
    { id: 'system',      label: 'System brief', route: '#/intel' },
  ],
  station:     [
    { id: 'station',     label: 'Station brief',    route: '#/intel' },
    { id: 'commodity',   label: 'Commodity search', route: '#/intel' },
    { id: 'module',      label: 'Module search',    route: '#/intel' },
    { id: 'cargo',       label: 'Open Cargo',       route: '#/operations' },
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
        const marketSuffix = market?.available
          ? ` Current station market has ${market.itemCount} local rows.`
          : ' No local market snapshot loaded.';
        return `${items.length} cargo type${items.length === 1 ? '' : 's'} on board${top ? ` - top: ${top}` : ''}.${marketSuffix}`;
      }
      return 'No cargo detected - start mining or open Cargo support.';
    case 'trading':
      if (items.length > 0) return `${items.length} cargo type${items.length === 1 ? '' : 's'} ready for local price search.`;
      return market?.available
        ? `${market.itemCount} current local market rows available.`
        : 'No cargo to sell - search the current local market when loaded.';
    case 'combat':
      return 'Watching for hostile contact.';
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

/**
 * deriveWorkspace
 *
 * Composes the full workspace view-model for a primary operation.
 */
export function deriveWorkspace(operation, input) {
  const supports = deriveSupportSystems(operation, input);
  const action = derivePrimaryAction(operation, input);
  return {
    operation,
    title: operationLabel(operation),
    question: workspaceQuestion(operation),
    objective: deriveObjective(operation, input),
    supports,
    action,
    quickTools: workspaceQuickTools(operation),
  };
}
