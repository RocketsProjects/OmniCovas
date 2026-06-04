/**
 * OmniCOVAS Intel briefing/search view-model.
 *
 * Converts the local intel snapshot into a briefing-first / search-first
 * surface model. Source posture and proof chips live in the proof bundle,
 * not the default pilot view.
 *
 * Authority: authority_files/documents/02_ui_ux_authority/OmniCOVAS_UI_UX_Master_Blueprint_v2_0_Human_Reference.md §9.3, §10
 */

'use strict';

/* Field keys that summarise where the commander is right now.
 * Used to extract a location briefing from the raw fact snapshot
 * without forcing every fact's source chip into pilot view. */
const SYSTEM_KEY = 'system.current_system';
const LOCATION_KEY = 'location.current_location';
const STATION_KEY = 'station.current_station';

export const INTEL_SEARCH_MODES = Object.freeze([
  { id: 'commodity', label: 'Commodity', placeholder: 'Search known commodities (e.g. Platinum, Gold)' },
  { id: 'module',    label: 'Module',    placeholder: 'Search known modules (e.g. 5A FSD, Shield Booster)' },
  { id: 'station',   label: 'Station',   placeholder: 'Search known stations and services' },
  { id: 'system',    label: 'System',    placeholder: 'Search known systems' },
]);

function findFact(sections, key) {
  if (!Array.isArray(sections)) return null;
  for (const section of sections) {
    const facts = Array.isArray(section?.facts) ? section.facts : [];
    for (const fact of facts) {
      if (fact?.field_key === key) return fact;
    }
  }
  return null;
}

function valueOf(fact) {
  if (!fact) return null;
  const v = fact.value;
  if (v == null || v === '') return null;
  return String(v);
}

/**
 * deriveLocationBriefing
 *
 * Returns a short pilot-facing briefing for the current system and station.
 * Returns null when no local fact is available; caller should render an
 * empty-state describing how to populate the briefing.
 */
export function deriveLocationBriefing(snapshot, localContext = null) {
  if (localContext?.systemBrief?.systemName || localContext?.stationBrief?.stationName) {
    const system = localContext.systemBrief.systemName || localContext.stationBrief.systemName || null;
    const station = localContext.stationBrief.stationName || null;
    return {
      system,
      location: system,
      station,
      primaryLine: system || station,
      detailLine: [station, system].filter(Boolean).slice(1).join(' . ') || null,
    };
  }

  const sections = Array.isArray(snapshot?.sections) ? snapshot.sections : [];
  const system = valueOf(findFact(sections, SYSTEM_KEY));
  const location = valueOf(findFact(sections, LOCATION_KEY));
  const station = valueOf(findFact(sections, STATION_KEY));

  if (!system && !location && !station) return null;

  return {
    system,
    location,
    station,
    primaryLine: system || location || station,
    detailLine: [station, location, system].filter(Boolean).slice(1).join(' · ') || null,
  };
}

/**
 * deriveStationBriefing
 *
 * Returns a station-services briefing derived only from local known data.
 * Uses station-services hints from the intel snapshot if present, otherwise
 * returns null to indicate no station knowledge yet.
 */
export function deriveStationBriefing(snapshot, localContext = null) {
  if (localContext?.stationBrief?.available) {
    return {
      station: localContext.stationBrief.stationName,
      services: localContext.stationServices?.services || [],
      model: localContext.stationBrief,
    };
  }

  const sections = Array.isArray(snapshot?.sections) ? snapshot.sections : [];
  const localSection = sections.find(s => s?.id === 'local') || null;
  const facts = Array.isArray(localSection?.facts) ? localSection.facts : [];
  const station = valueOf(findFact(sections, STATION_KEY));

  const services = facts
    .filter(f => typeof f?.field_key === 'string' && f.field_key.startsWith('station.service.') && valueOf(f))
    .map(f => ({ key: f.field_key, label: f.label || f.field_key, value: valueOf(f) }));

  if (!station && services.length === 0) return null;

  return { station, services };
}

/**
 * deriveKnownFactsSummary
 *
 * Returns a small count summary of how many facts are present per section,
 * for the "Known data" detail card. Caller should keep raw values out of
 * pilot view.
 */
export function deriveKnownFactsSummary(snapshot) {
  const sections = Array.isArray(snapshot?.sections) ? snapshot.sections : [];
  return sections.map(s => ({
    id: s?.id || 'unknown',
    label: s?.label || s?.id || 'Unknown',
    factCount: Array.isArray(s?.facts) ? s.facts.filter(f => valueOf(f) !== null).length : 0,
    totalFacts: Array.isArray(s?.facts) ? s.facts.length : 0,
  }));
}

/**
 * deriveEconomicSummary
 *
 * Returns a compact economic summary suitable for pilot view:
 * a count, a freshness label, and whether external lookups are gated.
 * Does NOT expose raw market rows; that belongs in detail/search.
 */
export function deriveEconomicSummary(economicSnapshot, localContext = null) {
  if (localContext?.marketSearch) {
    const market = localContext.marketSearch;
    if (market.available) {
      return {
        available: true,
        itemCount: market.itemCount,
        stationName: market.stationName,
        line: market.stationName
          ? `${market.itemCount} local market rows at ${market.stationName}.`
          : `${market.itemCount} local market rows loaded.`,
      };
    }
  }

  if (!economicSnapshot) {
    return { available: false, line: 'No local market observations yet.' };
  }
  const items = Array.isArray(economicSnapshot?.market?.items) ? economicSnapshot.market.items : [];
  const stationName = economicSnapshot?.market?.station_name || economicSnapshot?.station_name || null;
  if (items.length === 0) {
    return {
      available: false,
      line: stationName ? `No market observations from ${stationName} yet.` : 'No local market observations yet.',
    };
  }
  return {
    available: true,
    itemCount: items.length,
    stationName,
    line: stationName
      ? `${items.length} known prices at ${stationName}.`
      : `${items.length} known commodity prices on file.`,
  };
}

/**
 * deriveIntelBriefing
 *
 * Top-level pilot view model for the Intel route.
 */
export function deriveIntelBriefing(snapshot, economicSnapshot, localContext = null) {
  return {
    location: deriveLocationBriefing(snapshot, localContext),
    station: deriveStationBriefing(snapshot, localContext),
    economic: deriveEconomicSummary(economicSnapshot, localContext),
    sectionsSummary: deriveKnownFactsSummary(snapshot),
    searchModes: INTEL_SEARCH_MODES,
    localContext,
    stationBrief: localContext?.stationBrief || null,
    systemBrief: localContext?.systemBrief || null,
    marketSearch: localContext?.marketSearch || null,
    cargoHold: localContext?.cargoHold || null,
    moduleSearch: localContext?.moduleSearch || null,
    diagnostics: localContext?.diagnostics || null,
  };
}
