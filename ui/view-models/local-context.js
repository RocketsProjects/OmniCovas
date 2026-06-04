/**
 * OmniCOVAS local-context view-model.
 *
 * Converts GET /intel/local-context/snapshot into commander-facing
 * Pilot / Detail / Proof models. This file does not create source facts:
 * it only formats local Journal / companion JSON state already supplied
 * by the backend local context backplane.
 */

'use strict';

import {
  commodityComparisonKey,
  formatCredits,
  formatDisplayValue,
  normalizeCommodityName,
  normalizeMarketCategory,
  normalizeModuleName,
  normalizeSourceLabel,
  normalizeTruthClass,
} from '../utils/display-names.js';

export const LOCAL_CONTEXT_SNAPSHOT_PATH = '/intel/local-context/snapshot';

const UNKNOWN = 'Unknown';
const NOT_LOADED = 'not_loaded';

const PROOF_KEYS = Object.freeze([
  'source',
  'source_event',
  'event_timestamp',
  'freshness',
  'truth_class',
  'caveat',
  'fallback',
]);

const SERVICE_LABELS = Object.freeze({
  apexinterstellar: 'Apex Interstellar',
  apex: 'Apex Interstellar',
  bartender: 'Bartender',
  blackmarket: 'Black Market',
  commodities: 'Market',
  contacts: 'Contacts',
  crewlounge: 'Crew Lounge',
  dock: 'Docking',
  engineer: 'Engineer',
  exploration: 'Universal Cartographics',
  frontline: 'Frontline Solutions',
  market: 'Market',
  materialtrader: 'Material Trader',
  missions: 'Missions',
  missionboard: 'Mission Board',
  outfitting: 'Outfitting',
  refuel: 'Refuel',
  rearm: 'Rearm',
  repair: 'Repair',
  restock: 'Restock',
  shipyard: 'Shipyard',
  socialspace: 'Social Space',
  stationmenu: 'Station Services',
  techbroker: 'Technology Broker',
  tuning: 'Advanced Maintenance',
  universalcartographics: 'Universal Cartographics',
});

export async function fetchLocalContextSnapshot(apiBase, fetcher = globalThis.fetch) {
  if (!apiBase || typeof fetcher !== 'function') {
    return null;
  }

  try {
    const response = await fetcher(`${apiBase}${LOCAL_CONTEXT_SNAPSHOT_PATH}`);
    if (!response?.ok) {
      return null;
    }
    return await response.json();
  } catch {
    return null;
  }
}

function objectOrNull(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : null;
}

function asArray(value) {
  return Array.isArray(value) ? value.filter((entry) => entry !== null && entry !== undefined) : [];
}

function cleanString(value) {
  if (value === null || value === undefined) return null;
  const text = String(value).trim();
  return text ? text : null;
}

function cleanNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const num = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(num) ? num : null;
}

function displayValue(value) {
  const text = cleanString(value);
  return text || UNKNOWN;
}

function titleCase(value) {
  return String(value)
    .split(/[\s_-]+/)
    .filter(Boolean)
    .map((part) => {
      const lower = part.toLowerCase();
      if (/^[ivxlcdm]+$/i.test(part)) return part.toUpperCase();
      if (/^[a-z]+\d+$/i.test(part)) return part.toUpperCase();
      return lower.charAt(0).toUpperCase() + lower.slice(1);
    })
    .join(' ');
}

function displayToken(value) {
  const text = cleanString(value);
  if (!text) return UNKNOWN;
  if (/[<>]/.test(text)) return UNKNOWN;
  let working = text.replace(/^\$/, '').replace(/;$/, '');
  working = working
    .replace(/^system_security_/i, '')
    .replace(/^security_/i, '')
    .replace(/^economy_/i, '')
    .replace(/^government_/i, '')
    .replace(/^allegiance_/i, '')
    .replace(/^stationtype_/i, '')
    .replace(/^market_category_/i, '');
  return titleCase(working);
}

function displayMaybeToken(value) {
  return cleanString(value) ? displayToken(value) : UNKNOWN;
}

function displayInt(value) {
  const num = cleanNumber(value);
  return num === null ? UNKNOWN : Math.round(num).toLocaleString('en-US');
}

function displayBool(value, trueLabel = 'Yes', falseLabel = 'No', unknownLabel = UNKNOWN) {
  if (value === true) return trueLabel;
  if (value === false) return falseLabel;
  return unknownLabel;
}

function sourceLoaded(node) {
  return objectOrNull(node)?.freshness !== NOT_LOADED;
}

function proofFrom(id, label, sourceNode) {
  const source = objectOrNull(sourceNode) || {};
  const rows = PROOF_KEYS.map((key) => {
    let value = source[key];
    if (key === 'source') value = normalizeSourceLabel(value).display;
    if (key === 'truth_class') value = normalizeTruthClass(value).display;
    if (key === 'caveat' && typeof value === 'string' && /global market truth/i.test(value)) {
      value = value.replace(/not live and not global market truth/ig, 'not live beyond the current station snapshot');
    }
    return {
      key,
      label: titleCase(key),
      value: value === null || value === undefined || value === '' ? UNKNOWN : String(value),
      raw: source[key] ?? null,
    };
  });

  return {
    id,
    label,
    source: normalizeSourceLabel(source.source).display,
    event: displayValue(source.source_event),
    timestamp: displayValue(source.event_timestamp),
    freshness: displayValue(source.freshness),
    truthClass: normalizeTruthClass(source.truth_class).display,
    caveat: displayValue(
      typeof source.caveat === 'string' && /global market truth/i.test(source.caveat)
        ? source.caveat.replace(/not live and not global market truth/ig, 'not live beyond the current station snapshot')
        : source.caveat,
    ),
    fallback: cleanString(source.fallback),
    nullproviderSafe: source.nullprovider_safe === true,
    rows,
  };
}

function normalizeServiceKey(value) {
  return cleanString(value)?.toLowerCase().replace(/[^a-z0-9]/g, '') || '';
}

function serviceLabel(value) {
  const key = normalizeServiceKey(value);
  return SERVICE_LABELS[key] || displayToken(value);
}

function normalizeServices(values) {
  const seen = new Set();
  return asArray(values)
    .map((raw) => {
      const key = normalizeServiceKey(raw);
      if (!key || seen.has(key)) return null;
      seen.add(key);
      return { key, raw: cleanString(raw), label: serviceLabel(raw) };
    })
    .filter(Boolean)
    .sort((a, b) => a.label.localeCompare(b.label));
}

function hasService(services, names) {
  const desired = new Set(names.map(normalizeServiceKey));
  return services.some((service) => desired.has(service.key));
}

function namedObject(value) {
  const obj = objectOrNull(value);
  if (!obj) return null;
  return cleanString(obj.Name) || cleanString(obj.name) || cleanString(obj.Faction) || cleanString(obj.faction);
}

function economyRows(values) {
  return asArray(values).map((entry) => {
    const obj = objectOrNull(entry) || {};
    const name = cleanString(obj.Name) || cleanString(obj.name) || cleanString(obj.Economy) || cleanString(obj.economy);
    const proportion = cleanNumber(obj.Proportion ?? obj.proportion);
    return {
      label: displayMaybeToken(name),
      value: proportion === null ? '' : `${Math.round(proportion * 100)}%`,
    };
  });
}

function landingPadSummary(value) {
  const pads = objectOrNull(value);
  if (!pads) return UNKNOWN;
  const rows = Object.entries(pads)
    .filter(([, count]) => count !== null && count !== undefined)
    .map(([size, count]) => `${displayToken(size)} ${count}`);
  return rows.length ? rows.join(', ') : UNKNOWN;
}

function shortListSummary(values, emptyText) {
  const list = asArray(values).map((entry) => cleanString(entry?.label ?? entry)).filter(Boolean);
  if (list.length === 0) return emptyText;
  if (list.length <= 3) return list.join(', ');
  return `${list.slice(0, 3).join(', ')} +${list.length - 3}`;
}

function deriveStationServices(payload) {
  const stationContext = objectOrNull(payload?.station_context) || {};
  const stationServices = objectOrNull(payload?.station_services) || {};
  const services = normalizeServices(stationServices.services ?? stationContext.station_services);
  const marketAvailable = services.length > 0 && hasService(services, ['commodities', 'market']);
  const outfittingAvailable = services.length > 0 && hasService(services, ['outfitting']);
  const shipyardAvailable = services.length > 0 && hasService(services, ['shipyard']);

  return {
    available: services.length > 0,
    services,
    summary: services.length
      ? shortListSummary(services, 'No station services observed yet.')
      : 'No station services observed yet.',
    marketAvailable,
    outfittingAvailable,
    shipyardAvailable,
    proof: proofFrom('station_services', 'Station services', stationServices),
  };
}

function deriveCargoHold(payload, marketAvailable) {
  const cargo = objectOrNull(payload?.cargo_hold) || {};
  const inventory = asArray(cargo.inventory)
    .map((item) => {
      const obj = objectOrNull(item) || {};
      const count = cleanNumber(obj.count);
      if (!cleanString(obj.name) && !cleanString(obj.name_localised)) return null;
      const display = cleanString(obj.name_localised) || normalizeCommodityName(obj.name).display;
      const stolen = cleanNumber(obj.stolen);
      const missionId = cleanNumber(obj.mission_id);
      const flags = [];
      if (stolen !== null && stolen > 0) flags.push(`Stolen ${stolen}`);
      if (missionId !== null) flags.push(`Mission ${Math.round(missionId)}`);
      return {
        name: cleanString(obj.name) || display,
        display,
        count: count === null ? 0 : count,
        stolen,
        missionId,
        flags,
        searchQuery: cleanString(obj.name_localised) || cleanString(obj.name) || display,
      };
    })
    .filter(Boolean);

  const capacity = cleanNumber(cargo.capacity);
  const used = cleanNumber(cargo.total_count) ?? inventory.reduce((sum, item) => sum + item.count, 0);
  const remaining = capacity === null ? null : Math.max(capacity - used, 0);
  const loaded = sourceLoaded(cargo) || Array.isArray(cargo.inventory);
  const hasCargo = inventory.length > 0 && used > 0;

  return {
    available: loaded,
    hasCargo,
    vessel: displayValue(cargo.vessel),
    capacity,
    used,
    remaining,
    capacityLabel: capacity === null ? UNKNOWN : `${displayInt(capacity)} t`,
    usedLabel: `${displayInt(used)} t`,
    remainingLabel: remaining === null ? UNKNOWN : `${displayInt(remaining)} t`,
    inventory,
    topRows: inventory.slice(0, 6),
    emptyMessage: loaded
      ? 'Cargo hold empty.'
      : 'No local cargo context loaded. Open Cargo in Elite Dangerous to build a Cargo Hold.',
    actions: [
      {
        id: 'search-sell-prices',
        label: 'Search sell prices',
        enabled: true,
        reason: hasCargo
          ? 'Stages Market Search with cargo context.'
          : 'Stages Market Search; cargo is currently empty or not loaded.',
      },
      {
        id: 'open-market-search',
        label: 'Open Market Search',
        enabled: true,
        reason: 'Searches the current local market snapshot when loaded.',
      },
      {
        id: 'compare-current-station',
        label: 'Compare current station',
        enabled: marketAvailable,
        reason: marketAvailable
          ? 'Uses only the current local station snapshot.'
          : 'No local market snapshot loaded for comparison.',
      },
    ],
    proof: proofFrom('cargo_hold', 'Cargo hold', cargo),
  };
}

function deriveMarketSearch(payload, cargoHold) {
  const market = objectOrNull(payload?.market_snapshot) || {};
  const items = asArray(market.items)
    .map((item) => {
      const obj = objectOrNull(item) || {};
      const name = cleanString(obj.name);
      const localised = cleanString(obj.name_localised);
      const category = cleanString(obj.category);
      const categoryLocalised = cleanString(obj.category_localised);
      const displayName = localised || normalizeCommodityName(name).display;
      const displayCategory = categoryLocalised || normalizeMarketCategory(category).display;
      const row = {
        id: obj.id ?? null,
        name,
        nameLocalised: localised,
        displayName,
        category,
        categoryLocalised,
        displayCategory,
        buyPrice: cleanNumber(obj.buy_price),
        sellPrice: cleanNumber(obj.sell_price),
        meanPrice: cleanNumber(obj.mean_price),
        stock: cleanNumber(obj.stock),
        demand: cleanNumber(obj.demand),
        consumer: obj.consumer === true,
        producer: obj.producer === true,
        rare: obj.rare === true,
        prohibited: obj.prohibited === true,
        statusFlags: asArray(obj.status_flags).map((flag) => displayToken(flag)),
      };
      row.searchText = [
        row.name,
        row.nameLocalised,
        row.displayName,
        row.category,
        row.categoryLocalised,
        row.displayCategory,
      ].filter(Boolean).join(' ').toLowerCase();
      row.sortScore = (row.demand || 0) + (row.stock || 0);
      return row;
    });

  const available = sourceLoaded(market) && items.length > 0;
  const stationName = cleanString(market.station_name);
  const starSystem = cleanString(market.star_system);
  const marketId = market.market_id ?? null;
  const cargoQueries = asArray(cargoHold?.inventory)
    .filter((item) => item.count > 0)
    .map((item) => ({
      label: item.display,
      query: item.searchQuery,
      count: item.count,
    }));

  return {
    available,
    stationName,
    starSystem,
    marketId,
    itemCount: items.length,
    items,
    cargoQueries,
    statusLine: available
      ? `Current local market snapshot: ${items.length} commodities observed${stationName ? ` at ${stationName}` : ''}.`
      : 'No local market snapshot loaded. Open the Commodities Market at a station to load Market.json.',
    scopeLine: available ? 'Observed at this station. Known from Market.json.' : 'Local station market data only.',
    detailRows: [
      { label: 'Station', value: displayValue(stationName) },
      { label: 'System', value: displayValue(starSystem) },
      { label: 'Market ID', value: marketId === null || marketId === undefined ? UNKNOWN : String(marketId) },
      { label: 'Items', value: String(items.length) },
    ],
    proof: proofFrom('market_snapshot', 'Market snapshot', market),
  };
}

function deriveModuleSearch(payload, stationServices) {
  const loadout = objectOrNull(payload?.module_loadout) || {};
  const shield = objectOrNull(loadout.shield_generator) || {};
  const modules = asArray(loadout.modules)
    .map((entry) => {
      const obj = objectOrNull(entry) || {};
      const on = obj.on === true ? true : (obj.on === false ? false : null);
      return {
        slot: displayValue(obj.slot),
        item: cleanString(obj.item),
        display: cleanString(obj.item_localised) || normalizeModuleName(obj.item).display,
        on,
        stateLabel: on === true ? 'On' : (on === false ? 'Off' : UNKNOWN),
        priority: cleanNumber(obj.priority),
        health: cleanNumber(obj.health),
        power: cleanNumber(obj.power),
      };
    });

  const loadoutAvailable = sourceLoaded(loadout) && modules.length > 0;
  const outfittingObserved = stationServices.outfittingAvailable;
  return {
    available: loadoutAvailable || outfittingObserved,
    loadoutAvailable,
    outfittingObserved,
    moduleCount: modules.length,
    modules,
    shieldGenerator: {
      fitted: shield.fitted === true ? true : (shield.fitted === false ? false : null),
      item: cleanString(shield.item),
      display: cleanString(shield.item_localised) || (cleanString(shield.item) ? normalizeModuleName(shield.item).display : null),
      slot: cleanString(shield.slot),
      proof: objectOrNull(shield.provenance) || null,
    },
    summary: loadoutAvailable
      ? `${modules.length} local loadout modules observed.`
      : (outfittingObserved
        ? 'Outfitting service observed at this station; inventory search is not loaded.'
        : 'Module loadout not loaded yet.'),
    proof: proofFrom('module_loadout', 'Module loadout', loadout),
  };
}

function deriveStationBrief(payload, stationServices, marketSearch, cargoHold) {
  const station = objectOrNull(payload?.station_context) || {};
  const name = cleanString(station.station_name)
    || cleanString(marketSearch.stationName);
  const system = cleanString(station.star_system) || cleanString(marketSearch.starSystem);
  const stationFaction = namedObject(station.station_faction);
  const economies = economyRows(station.station_economies);
  const available = sourceLoaded(station) && Boolean(name || system);
  const serviceSummary = stationServices.summary;
  let primaryAction;
  if (marketSearch.available) {
    primaryAction = {
      id: 'open-market-intel',
      label: 'Open Market Intel',
      enabled: true,
      reason: 'Stages Market Search for the current local station snapshot.',
    };
  } else if (cargoHold.hasCargo) {
    primaryAction = {
      id: 'open-cargo',
      label: 'Open Cargo',
      enabled: true,
      reason: 'Stages Cargo Hold and cargo-aware market tools.',
    };
  } else {
    primaryAction = {
      id: 'open-station',
      label: 'Open Station',
      enabled: available,
      reason: available
        ? 'Stages the station workspace.'
        : 'No local station context loaded yet.',
    };
  }

  /* Correction #18: partial-station wording. If market snapshot or other
     local source already knows a station name, do not pretend nothing is
     known — say so explicitly and explain when the full context refreshes. */
  const partialFromMarket = station.context_kind === 'market_snapshot_only'
    || (!available && (marketSearch.available || Boolean(name)));

  return {
    available,
    stationName: name,
    systemName: system,
    contextKind: cleanString(station.context_kind),
    isDocked: station.is_docked === true ? true : (station.is_docked === false ? false : null),
    missingFields: asArray(station.missing_fields).map((entry) => cleanString(entry)).filter(Boolean),
    partialFromMarket,
    title: name || 'Station Brief',
    headline: partialFromMarket
      ? 'Station known from local market snapshot. Full station event context not loaded in this app session.'
      : available
        ? `${name || 'Station'}${system ? ` in ${system}` : ''}`
        : 'Dock at a station to load local context.',
    dockedLabel: displayBool(station.is_docked, 'Docked', 'Not docked', 'Docking state unknown'),
    stationType: displayMaybeToken(station.station_type),
    serviceSummary,
    marketAvailable: marketSearch.available || stationServices.marketAvailable,
    outfittingAvailable: stationServices.outfittingAvailable,
    shipyardAvailable: stationServices.shipyardAvailable,
    economySummary: cleanString(station.station_economy)
      ? displayToken(station.station_economy)
      : (economies[0]?.label || UNKNOWN),
    factionSummary: stationFaction ? displayToken(stationFaction) : UNKNOWN,
    primaryAction,
    facts: [
      { label: 'Station', value: displayValue(name) },
      { label: 'System', value: displayValue(system) },
      { label: 'Docked', value: displayBool(station.is_docked, 'Yes', 'No', UNKNOWN) },
      { label: 'Type', value: displayMaybeToken(station.station_type) },
      { label: 'Services', value: serviceSummary },
      { label: 'Economy', value: cleanString(station.station_economy) ? displayToken(station.station_economy) : UNKNOWN },
      { label: 'Faction', value: stationFaction ? displayToken(stationFaction) : UNKNOWN },
      { label: 'Market', value: marketSearch.available ? 'Current local snapshot loaded' : 'No local snapshot loaded' },
      { label: 'Outfitting', value: stationServices.outfittingAvailable ? 'Observed' : 'Not observed locally' },
      { label: 'Shipyard', value: stationServices.shipyardAvailable ? 'Observed' : 'Not observed locally' },
    ],
    detailRows: [
      { label: 'Full services', value: stationServices.services.map((service) => service.label).join(', ') || UNKNOWN },
      { label: 'Landing pads', value: landingPadSummary(station.landing_pads) },
      { label: 'Station economies', value: economies.map((row) => row.value ? `${row.label} ${row.value}` : row.label).join(', ') || UNKNOWN },
      { label: 'Market ID', value: station.market_id === null || station.market_id === undefined ? UNKNOWN : String(station.market_id) },
      { label: 'Station context kind', value: displayMaybeToken(station.context_kind) },
      { label: 'Missing station fields', value: asArray(station.missing_fields).map(displayToken).join(', ') || 'None reported' },
      { label: 'Distance from star', value: cleanNumber(station.dist_from_star_ls) === null ? UNKNOWN : `${formatDisplayValue(station.dist_from_star_ls, 'number')} ls` },
      { label: 'Government', value: displayMaybeToken(station.station_government) },
      { label: 'Allegiance', value: displayMaybeToken(station.station_allegiance) },
      { label: 'Economy', value: displayMaybeToken(station.station_economy) },
    ],
    services: stationServices.services,
    proof: proofFrom('station_context', 'Station context', station),
  };
}

function deriveSystemBrief(payload) {
  const system = objectOrNull(payload?.system_context) || {};
  const name = cleanString(system.star_system);
  const factionName = namedObject(system.system_faction);
  const factions = asArray(system.factions);
  const conflicts = asArray(system.conflicts);
  const powers = asArray(system.powers).map(displayToken);
  const available = sourceLoaded(system) && Boolean(name);

  return {
    available,
    systemName: name,
    title: name || 'System Brief',
    headline: available
      ? `${name} local system context`
      : 'No local system context loaded. Jump or load into a system to build a System Brief.',
    facts: [
      { label: 'System', value: displayValue(name) },
      { label: 'Government', value: displayMaybeToken(system.system_government) },
      { label: 'Security', value: displayMaybeToken(system.system_security) },
      { label: 'Economy', value: displayMaybeToken(system.system_economy) },
      { label: 'Second economy', value: displayMaybeToken(system.system_second_economy) },
      { label: 'Allegiance', value: displayMaybeToken(system.system_allegiance) },
      { label: 'Population', value: displayInt(system.population) },
      { label: 'Controlling faction', value: factionName ? displayToken(factionName) : UNKNOWN },
      { label: 'Factions', value: factions.length ? `${factions.length} observed` : UNKNOWN },
      { label: 'Conflicts', value: conflicts.length ? `${conflicts.length} observed` : 'None observed locally' },
    ],
    detailRows: [
      { label: 'Factions', value: factions.map((entry) => displayToken(namedObject(entry) || entry.Name || entry.name || 'Faction')).join(', ') || UNKNOWN },
      { label: 'Conflicts', value: conflicts.map((entry) => displayToken(entry.WarType || entry.war_type || entry.Status || entry.status || 'Conflict')).join(', ') || 'None observed locally' },
      { label: 'Powers', value: powers.join(', ') || UNKNOWN },
      { label: 'Powerplay state', value: displayMaybeToken(system.powerplay_state) },
      { label: 'Star position', value: asArray(system.star_pos).length ? asArray(system.star_pos).join(', ') : UNKNOWN },
      { label: 'Body', value: displayValue(system.body) },
      { label: 'Body ID', value: system.body_id === null || system.body_id === undefined ? UNKNOWN : String(system.body_id) },
      { label: 'Body type', value: displayMaybeToken(system.body_type) },
      { label: 'System address', value: system.system_address === null || system.system_address === undefined ? UNKNOWN : String(system.system_address) },
    ],
    factions,
    conflicts,
    powers,
    proof: proofFrom('system_context', 'System context', system),
  };
}

function deriveDiagnostics(payload, proofEntries) {
  const missingRaw = asArray(payload?.missing_sources).map((entry) => cleanString(entry)).filter(Boolean);
  return {
    endpointAvailable: Boolean(payload),
    generatedAt: cleanString(payload?.generated_at),
    nullproviderSafe: payload?.nullprovider_safe === true,
    missingSources: missingRaw.map((entry) => ({
      key: entry,
      label: titleCase(entry),
    })),
    summary: payload
      ? `${missingRaw.length} local source gap${missingRaw.length === 1 ? '' : 's'} reported.`
      : 'Local context endpoint unavailable.',
    proofEntries,
  };
}

export function filterMarketItems(marketSearch, query, options = {}) {
  const items = asArray(marketSearch?.items);
  const rawQuery = cleanString(query) || '';
  const cargoNames = asArray(options.cargoNames)
    .map((name) => commodityComparisonKey(name))
    .filter(Boolean);

  let rows = items;
  if (rawQuery) {
    const normalized = rawQuery.toLowerCase();
    const key = commodityComparisonKey(rawQuery);
    rows = rows.filter((item) => {
      if (key && commodityComparisonKey(item.name || item.displayName) === key) return true;
      return item.searchText.includes(normalized);
    });
  } else if (cargoNames.length > 0) {
    rows = rows.filter((item) => cargoNames.includes(commodityComparisonKey(item.name || item.displayName)));
  }

  return rows
    .slice()
    .sort((a, b) => {
      const aExact = rawQuery && commodityComparisonKey(a.name || a.displayName) === commodityComparisonKey(rawQuery) ? 1 : 0;
      const bExact = rawQuery && commodityComparisonKey(b.name || b.displayName) === commodityComparisonKey(rawQuery) ? 1 : 0;
      if (aExact !== bExact) return bExact - aExact;
      if (b.sortScore !== a.sortScore) return b.sortScore - a.sortScore;
      return a.displayName.localeCompare(b.displayName);
    });
}

const MODULE_ALIAS_MAP = Object.freeze([
  [/^fsd$|^frameshift$|^frame\s+shift$/, 'hyperdrive'],
  [/^pp$|^powerplant$|^power\s*plant$/, 'powerplant'],
  [/^distro$|^distributor$|^power\s*dist/, 'powerdistributor'],
  [/^shields?$|^shield\s*gen/, 'shieldgenerator'],
  [/^fuel\s*scoop$|^fuelscoop$/, 'fuelscoop'],
  [/^cargo\s*rack$|^cargo\s*bay$|^cargobay$/, 'cargobay'],
  [/^thrusters?$/, 'engine'],
]);

export function expandModuleQuery(rawQuery) {
  const q = String(rawQuery || '').trim().toLowerCase();
  if (!q) return q;
  for (const [pattern, canonical] of MODULE_ALIAS_MAP) {
    if (pattern.test(q)) return canonical;
  }
  return q;
}

export function deriveOutfittingModules(economicSnapshot) {
  const outfitting = objectOrNull(economicSnapshot?.outfitting) || {};
  const rawItems = asArray(outfitting.items);
  const stationName = cleanString(outfitting.station_name) || cleanString(economicSnapshot?.station_name);
  const available = rawItems.length > 0;
  const modules = rawItems.map((item) => {
    const obj = objectOrNull(item) || {};
    const rawName = cleanString(obj.name) || '';
    const normalized = normalizeModuleName(rawName);
    const display = normalized.display || rawName;
    return {
      item: rawName,
      display,
      haystack: `${rawName.toLowerCase()} ${display.toLowerCase()}`,
      buyPrice: cleanNumber(obj.buy_price),
    };
  });
  return {
    available,
    stationName,
    moduleCount: modules.length,
    modules,
    source: 'Outfitting.json',
    summary: available
      ? `${modules.length} modules at ${stationName || 'current station'} (local snapshot).`
      : 'Local outfitting snapshot not loaded. Open Outfitting at a station to populate local module availability.',
    caveat: 'Local station outfitting snapshot only; not global or guaranteed module availability.',
  };
}

export function deriveLocalContext(payload) {
  const stationServices = deriveStationServices(payload);
  const cargoHold = deriveCargoHold(payload, sourceLoaded(objectOrNull(payload?.market_snapshot)));
  const marketSearch = deriveMarketSearch(payload, cargoHold);
  const stationBrief = deriveStationBrief(payload, stationServices, marketSearch, cargoHold);
  const systemBrief = deriveSystemBrief(payload);
  const moduleSearch = deriveModuleSearch(payload, stationServices);
  const proofEntries = [
    stationBrief.proof,
    systemBrief.proof,
    stationServices.proof,
    marketSearch.proof,
    cargoHold.proof,
    moduleSearch.proof,
  ];
  const diagnostics = deriveDiagnostics(payload, proofEntries);

  return {
    rawLoaded: Boolean(payload),
    generatedAt: diagnostics.generatedAt,
    stationBrief,
    systemBrief,
    stationServices,
    cargoHold,
    marketSearch,
    moduleSearch,
    diagnostics,
    missingSources: diagnostics.missingSources,
    proof: {
      entries: proofEntries,
    },
  };
}
