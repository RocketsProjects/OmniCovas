/**
 * OmniCOVAS display-name and value formatting helpers.
 *
 * UI formatting only: these helpers do not change source truth and do not
 * create Elite Dangerous facts. Raw values remain in the returned result.
 */

const UNKNOWN = "Unknown";

const KNOWN_SHIP_NAMES = Object.freeze({
  anaconda: "Anaconda",
  krait_mkii: "Krait Mk II",
  kraitmkii: "Krait Mk II",
  panthermkii: "Panther Clipper Mk II",
  python: "Python",
  sidewinder: "Sidewinder",
});

const KNOWN_COMMODITY_NAMES = Object.freeze({
  platinum: "Platinum",
});

const KNOWN_MARKET_CATEGORIES = Object.freeze({
  metals: "Metals",
});

const KNOWN_TRUTH_CLASSES = Object.freeze({
  local_event_history: "Local event history",
  local_screen_snapshot: "Local snapshot",
  live_local_telemetry: "Live local telemetry",
  synthetic_local_derivative: "Local derived state",
});

const KNOWN_SOURCE_LABELS = Object.freeze({
  cargo_json: "Cargo.json",
  cargojson: "Cargo.json",
  journal: "Journal",
  local_event_history: "Local event history",
  local_journal: "Local journal",
  local_navroute: "Local NavRoute",
  local_screen_snapshot: "Local snapshot",
  live_local_telemetry: "Live local telemetry",
  market_json: "Market.json",
  marketjson: "Market.json",
  modulesinfo_json: "ModulesInfo.json",
  modulesinfojson: "ModulesInfo.json",
  navroute_json: "NavRoute.json",
  navroutejson: "NavRoute.json",
  outfitting_json: "Outfitting.json",
  outfittingjson: "Outfitting.json",
  shipyard_json: "Shipyard.json",
  shipyardjson: "Shipyard.json",
  status_json: "Status.json",
  statusjson: "Status.json",
});

const KNOWN_ACTIVITY_EVENT_LABELS = Object.freeze({
  "phase_9.bgs.facts_projected": "Phase 9 BGS facts projected",
  "phase_9.bgs.faction_observation_recorded": "Phase 9 BGS faction observation recorded",
  "phase_9.bgs.faction_effects_projected": "Phase 9 BGS faction effects projected",
  "phase_9.powerplay.facts_projected": "Phase 9 Powerplay facts projected",
  "phase_9.powerplay.pledge_changed": "Phase 9 Powerplay pledge changed",
  "phase_9.powerplay.rank_observed": "Phase 9 Powerplay rank observed",
  "phase_9.powerplay.merits_observed": "Phase 9 Powerplay merits observed",
  "phase_9.powerplay.collect_observed": "Phase 9 Powerplay collection observed",
  "phase_9.powerplay.deliver_observed": "Phase 9 Powerplay delivery observed",
  "phase_9.powerplay.vote_observed": "Phase 9 Powerplay vote observed",
  "phase_9.powerplay.voucher_observed": "Phase 9 Powerplay voucher observed",
  "phase_9.powerplay.salary_observed": "Phase 9 Powerplay salary observed",
  "phase_9.powerplay.fast_track_observed": "Phase 9 Powerplay fast track observed",
  "phase_9.powerplay.micro_resource_requested": "Phase 9 Powerplay micro resource requested",
  "phase_9.powerplay.micro_resource_delivered": "Phase 9 Powerplay micro resource delivered",
  "phase_9.campaign.objective_created": "Campaign objective created",
  "phase_9.campaign.objective_updated": "Campaign objective updated",
  "phase_9.campaign.objective_state_changed": "Campaign objective state changed",
  "phase_9.campaign.objective_blocked": "Campaign objective blocked",
  "phase_9.campaign.objective_completed": "Campaign objective completed",
  "phase_9.campaign.objective_archived": "Campaign objective archived",
  "phase_9.campaign.intel_fact_linked": "Campaign Intel fact linked",
  "phase_9.campaign.intel_fact_unlinked": "Campaign Intel fact unlinked",
  "phase_9.campaign.navigation_circuit_linked": "Campaign Navigation circuit linked",
  "phase_9.campaign.navigation_circuit_unlinked": "Campaign Navigation circuit unlinked",
  "phase_9.campaign.ai_draft_requested_gate_shown": "AI draft confirmation gate shown",
  "phase_9.campaign.ai_draft_confirmed_gate": "AI draft confirmation gate approved",
  "phase_9.campaign.ai_draft_canceled_gate": "AI draft confirmation gate canceled",
  "phase_9.campaign.ai_draft_emitted": "AI draft emitted",
  "phase_9.campaign.ai_draft_rejected_validation": "AI draft rejected by validation",
  "phase_9.campaign.handoff_to_intel": "Campaign handoff to Intel",
  "phase_9.campaign.handoff_to_navigation": "Campaign handoff to Navigation",
  "phase_9.campaign.handoff_to_squadrons": "Campaign handoff to Squadrons",
  "phase_9.campaign.handoff_to_activity_log": "Campaign handoff to Activity Log",
  "phase_9.navigation.circuit_created": "Navigation campaign circuit created",
  "phase_9.navigation.circuit_updated": "Navigation campaign circuit updated",
  "phase_9.navigation.circuit_archived": "Navigation campaign circuit archived",
  "phase_9.navigation.stop_added": "Navigation campaign stop added",
  "phase_9.navigation.stop_updated": "Navigation campaign stop updated",
  "phase_9.navigation.stop_removed": "Navigation campaign stop removed",
  "phase_9.navigation.bookmark_tagged": "Navigation bookmark tagged",
  "phase_9.navigation.circuit_linked_to_campaign": "Navigation circuit linked to campaign",
  "phase_9.navigation.circuit_unlinked_from_campaign": "Navigation circuit unlinked from campaign",
  "phase_9.navigation.spansh_link_opened": "Navigation external link opened",
  "phase_9.squadron.local_note_created": "Squadron local note created",
  "phase_9.squadron.local_note_updated": "Squadron local note updated",
  "phase_9.squadron.local_note_archived": "Squadron local note archived",
  "phase_9.squadron.local_note_linked_to_campaign": "Squadron local note linked to campaign",
  "phase_9.squadron.local_note_unlinked_from_campaign": "Squadron local note unlinked from campaign",
  "phase_9.source_attempt_blocked": "Phase 9 source attempt blocked",
  "phase_9.source_attempt_disabled": "Phase 9 source attempt disabled",
  "phase_9.source_attempt_requires_auth": "Phase 9 source attempt requires authorization",
  "phase_9.source_attempt_unsupported": "Phase 9 source attempt unsupported",
  "phase_9.source_attempt_no_verified_source": "Phase 9 source attempt has no verified source",
});

const MODULE_PREFIXES = Object.freeze([
  "int_",
  "hpt_",
  "mod_",
  "wpn_",
]);

const MODULE_TOKEN_LABELS = Object.freeze({
  afmu: "AFMU",
  armour: "Armour",
  beamlaser: "Beam Laser",
  cargorack: "Cargo Rack",
  chafflauncher: "Chaff Launcher",
  class1: "Class 1",
  class2: "Class 2",
  class3: "Class 3",
  class4: "Class 4",
  class5: "Class 5",
  class6: "Class 6",
  class7: "Class 7",
  class8: "Class 8",
  collectorlimpet: "Collector Limpet",
  detailedsurfacescanner: "Detailed Surface Scanner",
  engine: "Thrusters",
  fixed: "Fixed",
  frameshiftdrive: "Frame Shift Drive",
  fuel_scoop: "Fuel Scoop",
  fuelscoop: "Fuel Scoop",
  fueltank: "Fuel Tank",
  gimbal: "Gimballed",
  heatsinklauncher: "Heat Sink Launcher",
  hyperdrive: "Frame Shift Drive",
  large: "Large",
  lifesupport: "Life Support",
  medium: "Medium",
  mininglaser: "Mining Laser",
  multicannon: "Multi-cannon",
  powerdistributor: "Power Distributor",
  powerplant: "Power Plant",
  prospectorlimpet: "Prospector Limpet",
  pulselaser: "Pulse Laser",
  refinery: "Refinery",
  sensors: "Sensors",
  shieldgenerator: "Shield Generator",
  size1: "Size 1",
  size2: "Size 2",
  size3: "Size 3",
  size4: "Size 4",
  size5: "Size 5",
  size6: "Size 6",
  size7: "Size 7",
  size8: "Size 8",
  small: "Small",
  tiny: "Tiny",
  turret: "Turret",
});

function makeResult(display, raw, confidence, proofLabel) {
  return {
    display,
    raw,
    confidence,
    proofLabel,
  };
}

function rawString(value) {
  if (value === null || value === undefined) return "";
  return String(value);
}

function trimmedString(value) {
  return rawString(value).trim();
}

function containsMarkupLike(value) {
  return /[<>]/.test(value);
}

function normalizedKey(value) {
  return trimmedString(value).toLowerCase().replace(/\s+/g, "_");
}

function titleCase(value) {
  return value
    .split(/[\s_-]+/)
    .filter(Boolean)
    .map((part) => {
      const lower = part.toLowerCase();
      if (/^mk$/.test(lower)) return "Mk";
      if (/^[ivxlcdm]+$/i.test(part)) return part.toUpperCase();
      if (/^[a-z]+\d+$/i.test(part)) return part.toUpperCase();
      return lower.charAt(0).toUpperCase() + lower.slice(1);
    })
    .join(" ");
}

function frontierLocalizationBase(value) {
  let text = trimmedString(value);
  if (text.startsWith("$")) text = text.slice(1);
  if (text.endsWith(";")) text = text.slice(0, -1);
  return text;
}

function stripKnownNameSuffix(value) {
  return value.replace(/_name$/i, "");
}

function formatLocalisationKey(value) {
  const base = stripKnownNameSuffix(frontierLocalizationBase(value));
  return titleCase(base);
}

function formatMarketCategoryKey(value) {
  const base = frontierLocalizationBase(value).replace(/^MARKET_category_/i, "");
  return titleCase(base);
}

function formatReadableIdentifier(value) {
  return titleCase(trimmedString(value).replace(/([a-z])([A-Z])/g, "$1 $2"));
}

function numericValue(value) {
  if (value === null || value === undefined || value === "") return null;
  const num = typeof value === "number" ? value : Number(value);
  return Number.isFinite(num) ? num : null;
}

function formatFixedTrimmed(value, decimals) {
  const num = numericValue(value);
  if (num === null) return UNKNOWN;
  return num.toFixed(decimals).replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1");
}

function formatIntegerLike(value) {
  const num = numericValue(value);
  if (num === null) return UNKNOWN;
  return Number.isInteger(num) ? String(num) : formatFixedTrimmed(num, 1);
}

export function normalizeShipName(raw) {
  const value = trimmedString(raw);
  if (!value) return makeResult("Unknown ship", raw, "unknown", "Raw ship ID");
  if (containsMarkupLike(value)) {
    return makeResult("Unknown ship", raw, "unsafe_fallback", "Raw ship ID");
  }

  const key = normalizedKey(value);
  if (KNOWN_SHIP_NAMES[key]) {
    return makeResult(KNOWN_SHIP_NAMES[key], raw, "known_mapping", "Raw ship ID");
  }

  return makeResult(formatReadableIdentifier(value), raw, "readable_fallback", "Raw ship ID");
}

export function normalizeCommodityName(raw) {
  const value = trimmedString(raw);
  if (!value) return makeResult("Unknown commodity", raw, "unknown", "Raw commodity ID");
  if (containsMarkupLike(value)) {
    return makeResult("Unknown commodity", raw, "unsafe_fallback", "Raw commodity ID");
  }

  const frontierBase = stripKnownNameSuffix(frontierLocalizationBase(value));
  const key = normalizedKey(frontierBase);
  if (KNOWN_COMMODITY_NAMES[key]) {
    return makeResult(KNOWN_COMMODITY_NAMES[key], raw, "known_mapping", "Raw commodity ID");
  }

  if (value.startsWith("$")) {
    return makeResult(formatLocalisationKey(value), raw, "frontier_key_fallback", "Raw commodity ID");
  }

  return makeResult(formatReadableIdentifier(value), raw, "readable_fallback", "Raw commodity ID");
}

export function normalizeMarketCategory(raw) {
  const value = trimmedString(raw);
  if (!value) return makeResult("Unknown category", raw, "unknown", "Raw market category ID");
  if (containsMarkupLike(value)) {
    return makeResult("Unknown category", raw, "unsafe_fallback", "Raw market category ID");
  }

  const frontierBase = frontierLocalizationBase(value).replace(/^MARKET_category_/i, "");
  const key = normalizedKey(frontierBase);
  if (KNOWN_MARKET_CATEGORIES[key]) {
    return makeResult(KNOWN_MARKET_CATEGORIES[key], raw, "known_mapping", "Raw market category ID");
  }

  if (/^\$?MARKET_category_/i.test(value)) {
    return makeResult(formatMarketCategoryKey(value), raw, "frontier_key_fallback", "Raw market category ID");
  }

  return makeResult(formatReadableIdentifier(value), raw, "readable_fallback", "Raw market category ID");
}

export function normalizeModuleName(raw) {
  const value = trimmedString(raw);
  if (!value) return makeResult("Unknown module type", raw, "unknown", "Raw module ID");
  if (containsMarkupLike(value)) {
    return makeResult("Unknown module type", raw, "unsafe_fallback", "Raw module ID");
  }

  let working = normalizedKey(value);
  MODULE_PREFIXES.forEach((prefix) => {
    if (working.startsWith(prefix)) working = working.slice(prefix.length);
  });

  const tokens = working.split("_").filter(Boolean);
  if (!tokens.length) return makeResult("Unknown module type", raw, "unknown", "Raw module ID");

  const displayTokens = tokens.map((token) => MODULE_TOKEN_LABELS[token] || titleCase(token));
  return makeResult(displayTokens.join(" "), raw, "readable_fallback", "Raw module ID");
}

export function normalizeTruthClass(raw) {
  const value = trimmedString(raw);
  if (!value) return makeResult(UNKNOWN, raw, "unknown", "Raw truth class");
  if (containsMarkupLike(value)) {
    return makeResult(UNKNOWN, raw, "unsafe_fallback", "Raw truth class");
  }

  const key = normalizedKey(value);
  if (KNOWN_TRUTH_CLASSES[key]) {
    return makeResult(KNOWN_TRUTH_CLASSES[key], raw, "known_mapping", "Raw truth class");
  }

  return makeResult(formatReadableIdentifier(value), raw, "readable_fallback", "Raw truth class");
}

export function normalizeSourceLabel(raw) {
  const value = trimmedString(raw);
  if (!value) return makeResult(UNKNOWN, raw, "unknown", "Raw source ID");
  if (containsMarkupLike(value)) {
    return makeResult(UNKNOWN, raw, "unsafe_fallback", "Raw source ID");
  }

  const key = normalizedKey(value.replace(/\./g, "_"));
  if (KNOWN_SOURCE_LABELS[key]) {
    return makeResult(KNOWN_SOURCE_LABELS[key], raw, "known_mapping", "Raw source ID");
  }

  if (/\.json$/i.test(value)) {
    return makeResult(value, raw, "source_filename", "Raw source ID");
  }

  return makeResult(formatReadableIdentifier(value), raw, "readable_fallback", "Raw source ID");
}

export function formatActivityEventType(raw) {
  const value = trimmedString(raw);
  if (!value) return UNKNOWN;
  const key = value.toLowerCase();
  if (KNOWN_ACTIVITY_EVENT_LABELS[key]) return KNOWN_ACTIVITY_EVENT_LABELS[key];
  return formatReadableIdentifier(value.replace(/\./g, " "));
}

export function commodityComparisonKey(raw) {
  const value = trimmedString(raw);
  if (!value || containsMarkupLike(value)) return "";
  return normalizedKey(stripKnownNameSuffix(frontierLocalizationBase(value)));
}

export function formatCredits(value) {
  const num = numericValue(value);
  if (num === null) return UNKNOWN;
  return `${Math.round(num).toLocaleString("en-US")} cr`;
}

export function formatTons(value) {
  const num = numericValue(value);
  if (num === null) return UNKNOWN;
  return `${formatIntegerLike(num)} t`;
}

export function formatPercent(value, maxFractionDigits = 1) {
  const num = numericValue(value);
  if (num === null) return UNKNOWN;
  return `${formatFixedTrimmed(num, maxFractionDigits)}%`;
}

export function formatLightYears(value) {
  const num = numericValue(value);
  if (num === null) return UNKNOWN;
  return `${num.toFixed(2)} ly`;
}

export function formatDisplayValue(value, unitOrKind) {
  if (value === null || value === undefined || value === "") return UNKNOWN;
  const kind = trimmedString(unitOrKind).toLowerCase();
  if (kind === "credits" || kind === "credit" || kind === "cr") return formatCredits(value);
  if (kind === "tons" || kind === "tonnes" || kind === "ton" || kind === "t") return formatTons(value);
  if (kind === "percent" || kind === "percentage" || kind === "%") return formatPercent(value);
  if (kind === "lightyears" || kind === "light_years" || kind === "light-years" || kind === "ly") {
    return formatLightYears(value);
  }
  if (typeof value === "boolean") return value ? "True" : "False";
  if (typeof value === "number") return value.toLocaleString("en-US");
  return String(value);
}
