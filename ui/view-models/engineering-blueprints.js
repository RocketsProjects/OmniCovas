/**
 * Blueprints & Engineers view model.
 *
 * A pure join over data the Engineering overview already carries: Journal
 * EngineerCraft recipes, the optional local reference catalogue, the shared
 * Journal-derived inventory and the saved-build assessments. It adds no game
 * facts and does no cost calculation of its own beyond comparing a published
 * bill with published counts. Anything the sources do not state stays
 * `null`/`unknown` so the view can say so instead of guessing.
 */

export const GRADES = Object.freeze([1, 2, 3, 4, 5]);

const text = (value) => (typeof value === 'string' ? value.trim() : '');
const list = (value) => (Array.isArray(value) ? value : []);

/** Same keying the backend applies to Journal and reference-pack materials. */
export function materialKey(value) {
  if (typeof value !== 'string') return String(value ?? '');
  const clean = value.trim().replace(/^\$+|\$+$/g, '').replace(/_name;$/i, '');
  return clean.toLowerCase() || String(value);
}

export const idKey = (value) => text(value).toLowerCase();

export function humanizeCategory(id) {
  const label = text(id).replace(/[_-]+/g, ' ').trim();
  return label ? label.charAt(0).toUpperCase() + label.slice(1) : 'Unspecified';
}

export const UNVERIFIED_EQUIPMENT = 'Equipment not verified';

/** Display order of the Blueprints list: equipment groups A-Z, unverified last, then name. */
export function blueprintDisplayOrder(a, b) {
  const unverified = Number(!a.group) - Number(!b.group);
  if (unverified) return unverified;
  const label = (bp) => bp.equipment.labels[0] || '';
  return (
    label(a).localeCompare(label(b), undefined, { sensitivity: 'base' }) ||
    a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
  );
}

function inventoryModel(progression) {
  const inventory = progression.inventory || {};
  const known = inventory.state === 'verified_local';
  const counts = new Map();
  if (known) {
    list(inventory.materials).forEach((row) => {
      if (Number.isInteger(row?.count)) counts.set(materialKey(row.material_id), row.count);
    });
  }
  const reserved = new Map();
  list(progression.builds).forEach((build) => {
    list(build.materials).forEach((row) => {
      if (Number.isInteger(row?.reserved)) {
        const key = materialKey(row.material_id);
        reserved.set(key, (reserved.get(key) || 0) + row.reserved);
      }
    });
  });
  return { known, state: inventory.state || 'unknown', counts, reserved };
}

/**
 * Compare one published bill with the observed inventory.
 * A complete Materials baseline is authoritative: an omitted material is an
 * observed zero. Without one nothing is claimed (`unknown`), never zero.
 */
export function assessBill(materials, inventory) {
  const rows = list(materials).map((material) => {
    const key = materialKey(material.material_id);
    const need = material.count;
    const have = inventory.known ? inventory.counts.get(key) ?? 0 : null;
    const reserved = inventory.known ? inventory.reserved.get(key) || 0 : null;
    const free = have === null ? null : Math.max(have - reserved, 0);
    return {
      id: material.material_id,
      name: material.display_name || material.material_id,
      need,
      have,
      reserved,
      free,
      short: free === null ? null : Math.max(need - free, 0),
    };
  });
  if (!inventory.known) return { state: 'unknown', rows, shortCount: null };
  const short = rows.filter((row) => row.short > 0);
  return {
    state: short.length ? 'short' : 'affordable',
    rows,
    shortCount: short.length,
    // Every shortfall is stock that is held, but reserved by saved plans.
    reservedOnly: short.length > 0 && short.every((row) => row.have >= row.need),
  };
}

function observedByBlueprint(progression) {
  const map = new Map();
  list(progression.observed_recipes).forEach((recipe) => {
    const key = idKey(recipe.blueprint_id);
    if (!key) return;
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(recipe);
  });
  return map;
}

function sameBill(a, b) {
  const flat = (rows) =>
    list(rows)
      .map((row) => `${materialKey(row.material_id)}:${row.count}`)
      .sort()
      .join('|');
  return flat(a) === flat(b);
}

function buildGrades({ catalogueBlueprint, observed, inventory }) {
  return GRADES.map((grade) => {
    const catalogue = catalogueBlueprint?.grades?.[String(grade)]
      ? { materials: catalogueBlueprint.grades[String(grade)] }
      : null;
    const seen = observed.find((recipe) => recipe.grade === grade) || null;
    let agreement = 'unknown';
    if (catalogue && seen) {
      agreement = sameBill(catalogue.materials, seen.materials) ? 'agrees' : 'differs';
    } else if (catalogue) {
      agreement = 'catalogue_only';
    } else if (seen) {
      agreement = 'observed_only';
    }
    // The bill the game actually charged outranks a reference value.
    const primary = seen ? 'observed' : catalogue ? 'catalogue' : null;
    const materials = seen ? seen.materials : catalogue ? catalogue.materials : null;
    return {
      grade,
      catalogue,
      observed: seen,
      agreement,
      primary,
      materials,
      assessment: materials ? assessBill(materials, inventory) : null,
    };
  });
}

function equipmentFor({ catalogueBlueprint, observedSlots }) {
  if (catalogueBlueprint?.module_categories?.length) {
    const ids = catalogueBlueprint.module_categories.map(text).filter(Boolean);
    return { kind: 'catalogue', ids, labels: ids.map(humanizeCategory) };
  }
  if (observedSlots.length) {
    return { kind: 'observed_slot', ids: [], labels: observedSlots };
  }
  return { kind: 'unknown', ids: [], labels: [] };
}

/**
 * Wording for the Journal's own `Progress` token. Only tokens the project has
 * seen are given a label; anything else is shown as "not recognised" together
 * with exactly what was reported, never translated or guessed at.
 */
const PROGRESS_LABELS = Object.freeze({
  unlocked: 'Unlocked',
  invited: 'Invited',
  acquainted: 'Acquainted',
  barred: 'Barred',
  known: 'Known',
});

export function engineerStatus(observed) {
  if (!observed) return { observed: false, label: 'Not observed', tone: 'muted', recognised: false };
  const token = text(observed.progress);
  if (!token) return { observed: true, label: 'Status not reported', tone: 'muted', recognised: false };
  const label = PROGRESS_LABELS[token.toLowerCase()];
  if (!label) {
    return { observed: true, label: 'Status not recognised', tone: 'warn', recognised: false, reportedAs: token };
  }
  // Barred is shown plainly, without a tone that would read as a judgement.
  const tone = label === 'Unlocked' ? 'ok' : label === 'Barred' ? 'muted' : 'info';
  return { observed: true, label, tone, recognised: true };
}

export const rankLabel = (observed) =>
  Number.isInteger(observed?.rank) ? `Rank ${observed.rank}` : null;

export const rankProgressLabel = (observed) =>
  typeof observed?.rankProgress === 'number' ? `${observed.rankProgress}%` : null;

/** "2026-10-01 12:00 UTC" from a stored Journal timestamp (always UTC). */
export function observedAtLabel(value) {
  const match = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(text(value));
  return match ? `${match[1]} ${match[2]} UTC` : 'time not recorded';
}

function engineerProgressModel(raw) {
  const source = raw && typeof raw === 'object' ? raw : {};
  const engineers = list(source.engineers)
    .filter((row) => row && typeof row === 'object')
    .map((row) => ({
      key: text(row.key),
      engineerId: Number.isInteger(row.engineer_id) ? row.engineer_id : null,
      name: text(row.name),
      progress: text(row.progress) || null,
      rank: Number.isInteger(row.rank) ? row.rank : null,
      rankProgress: typeof row.rank_progress === 'number' ? row.rank_progress : null,
      progressObservedAt: text(row.progress_observed_at) || null,
      observedAt: text(row.observed_at) || null,
      firstObservedAt: text(row.first_observed_at) || null,
      observationCount: Number.isInteger(row.observation_count) ? row.observation_count : 1,
      history: list(row.history).map((entry) => ({
        progress: text(entry.progress) || null,
        rank: Number.isInteger(entry.rank) ? entry.rank : null,
        rankProgress: typeof entry.rank_progress === 'number' ? entry.rank_progress : null,
        observedAt: text(entry.observed_at) || null,
      })),
    }));
  return {
    state: engineers.length ? 'observed' : 'not_observed',
    engineers,
    lastEventAt: text(source.last_event_at) || null,
    caveats: list(source.caveats).map(text).filter(Boolean),
  };
}

/** A person's name as a join key: case, quotes and punctuation do not matter. */
export const personKey = (value) => text(value).toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '');

function directoryModel(raw) {
  const source = raw && typeof raw === 'object' ? raw : {};
  const engineers = list(source.engineers)
    .filter((row) => row && Number.isInteger(row.engineer_id) && text(row.name))
    .map((row) => ({
      engineerId: row.engineer_id,
      name: text(row.name),
      identity: {
        status: text(row.identity?.status) || 'community_sourced',
        evidence: list(row.identity?.evidence).map(text).filter(Boolean),
      },
      location: {
        status: text(row.location?.status) || 'unverified',
        system: text(row.location?.system) || null,
        base: text(row.location?.base) || null,
        evidence: list(row.location?.evidence).map(text).filter(Boolean),
        notes: list(row.location?.notes).map(text).filter(Boolean),
      },
    }));
  return {
    available: source.state === 'bundled_verified_subset' && engineers.length > 0,
    // Why it is absent: 'not_included' is the normal state of a public, preview or release build.
    reason: text(source.reason) || (source.state === 'bundled_verified_subset' ? '' : 'not_included'),
    developmentOnly: source.distribution?.status === 'development_only',
    version: text(source.version),
    reviewedAt: text(source.reviewed_at),
    scope: text(source.scope),
    rightsBasis: text(source.rights_basis),
    sources: list(source.sources).map((row) => ({
      id: text(row.id),
      name: text(row.name),
      url: text(row.url),
      role: text(row.role),
      accessed: text(row.accessed),
    })),
    unsupportedFields: list(source.unsupported_fields).map((row) => ({
      field: text(row.field),
      reason: text(row.reason),
    })),
    coverage: source.coverage && typeof source.coverage === 'object' ? source.coverage : {},
    engineers,
  };
}

function contributionsModel(raw) {
  const source = raw && typeof raw === 'object' ? raw : {};
  return list(source.engineers)
    .filter((row) => row && typeof row === 'object')
    .map((row) => ({
      engineerId: Number.isInteger(row.engineer_id) ? row.engineer_id : null,
      name: text(row.name),
      lines: list(row.contributions).map((line) => ({
        type: text(line.type),
        item: text(line.item) || null,
        total: Number.isInteger(line.total_quantity) ? line.total_quantity : null,
        last: Number.isInteger(line.last_quantity) ? line.last_quantity : null,
        observedAt: text(line.observed_at) || null,
        offers: Number.isInteger(line.offer_count) ? line.offer_count : 1,
      })),
    }));
}

/** "Commodity · soontillrelics: 3 offered in total" for one Journal contribution line. */
export function contributionLabel(line) {
  const kind = line.type === 'materials' ? 'Materials' : line.type;
  const subject = [kind, line.item].filter(Boolean).join(' · ');
  return Number.isInteger(line.total)
    ? `${subject}: ${line.total.toLocaleString('en-US')} offered in total`
    : `${subject}: total not reported`;
}

/**
 * What is known about getting access to one engineer, kept as two separate
 * questions: is a requirement documented anywhere, and has completion been seen
 * in the Journal. A documented requirement is never marked done by itself, and
 * the Journal's access state answers only the stage it names.
 */
export function accessPlan(engineer) {
  const declared = engineer.declared;
  const requirement = declared?.requirements
    ? {
        state: 'documented',
        label: 'Requirement documented',
        text: declared.requirements,
        source: 'Reference catalogue you installed',
      }
    : {
        state: 'unavailable',
        label: 'Requirement information unavailable',
        text: declared
          ? 'The installed catalogue lists this engineer but gives no requirement text.'
          : 'No bundled directory or installed catalogue supplies unlock requirements for this engineer.',
        source: null,
      };
  const observed = engineer.observed;
  const token = text(observed?.progress).toLowerCase();
  const when = observedAtLabel(observed?.progressObservedAt || observed?.observedAt);
  let completion;
  if (token === 'unlocked') {
    completion = {
      state: 'observed',
      label: 'Completion observed',
      detail: `Your Journal reported this engineer as Unlocked (${when}).`,
    };
  } else if (token === 'invited') {
    completion = {
      state: 'partial',
      label: 'Invitation observed',
      detail: `Your Journal reported this engineer as Invited (${when}). Unlocking has not been seen.`,
    };
  } else if (observed && token) {
    completion = {
      state: 'not_verified',
      label: 'Completion not verified',
      detail: `Your Journal reported “${observed.progress}” (${when}), which does not show the requirement as met.`,
    };
  } else {
    completion = {
      state: 'not_verified',
      label: 'Completion not verified',
      detail: observed
        ? 'Your Journal reported a rank but no access state for this engineer.'
        : 'Your Journal has no access state for this engineer. That does not mean it is not met.',
    };
  }
  return {
    requirement,
    referral: declared?.referral || null,
    completion,
    contributions: engineer.contributions || [],
  };
}

/** Entire view model for the Blueprints & Engineers workstation. */
export function buildBlueprintModel(overview = {}) {
  const progression = overview.progression || {};
  const reference = progression.reference_catalog || {};
  const catalogueActive = reference.state === 'commander_supplied_validated';
  const inventory = inventoryModel(progression);
  const observedMap = observedByBlueprint(progression);
  const loadoutModules = list(progression.observed_loadout_catalog?.modules);

  const catalogue = {
    active: catalogueActive,
    title: catalogueActive ? text(reference.title) : '',
    id: catalogueActive ? text(reference.catalog_id) : '',
    version: catalogueActive ? text(reference.version) : '',
    provenance: catalogueActive ? reference.provenance || null : null,
    limitations: catalogueActive ? list(reference.limitations) : [],
    verificationBoundary: catalogueActive ? text(reference.verification_boundary) : '',
    updateAvailable: catalogueActive && reference.private_reference_update_available === true,
    blueprintCount: catalogueActive ? list(reference.blueprints).length : 0,
  };

  const catalogueBlueprints = new Map();
  if (catalogueActive) {
    list(reference.blueprints).forEach((bp) => catalogueBlueprints.set(idKey(bp.id), bp));
  }

  const keys = new Set([...catalogueBlueprints.keys(), ...observedMap.keys()]);
  const blueprints = [];
  keys.forEach((key) => {
    const catalogueBlueprint = catalogueBlueprints.get(key) || null;
    const observed = (observedMap.get(key) || []).slice().sort((a, b) => a.grade - b.grade);
    const observedSlots = loadoutModules
      .filter((module) => idKey(module.observed_blueprint) === key)
      .map((module) => text(module.module_label) || text(module.slot))
      .filter(Boolean);
    const name =
      text(catalogueBlueprint?.name) ||
      text(observed[0]?.blueprint_label) ||
      text(observed[0]?.blueprint_id) ||
      key;
    const equipment = equipmentFor({ catalogueBlueprint, observedSlots });
    const grades = buildGrades({ catalogueBlueprint, observed, inventory });
    const known = grades.filter((row) => row.materials);
    const affordable = known.filter((row) => row.assessment?.state === 'affordable');
    blueprints.push({
      key,
      id: text(catalogueBlueprint?.id) || text(observed[0]?.blueprint_id) || key,
      name,
      inCatalogue: Boolean(catalogueBlueprint),
      inJournal: observed.length > 0,
      equipment,
      group: equipment.ids[0] || null,
      grades,
      knownGrades: known.map((row) => row.grade),
      highestAffordableGrade: affordable.length
        ? Math.max(...affordable.map((row) => row.grade))
        : 0,
      anyAffordable: affordable.length > 0,
      experimentals: list(catalogueBlueprint?.experimentals).map((effect) => ({
        id: effect.id,
        name: text(effect.name) || effect.id,
        materials: Array.isArray(effect.materials) ? effect.materials : null,
        assessment: Array.isArray(effect.materials)
          ? assessBill(effect.materials, inventory)
          : null,
        special: text(effect.special),
      })),
      observedEffects: [
        ...new Set(observed.map((recipe) => text(recipe.experimental_effect)).filter(Boolean)),
      ],
      caveats: list(catalogueBlueprint?.cost_caveats).map(text).filter(Boolean),
      numericalDataComplete: catalogueBlueprint
        ? catalogueBlueprint.numerical_data_complete !== false
        : null,
      special: text(catalogueBlueprint?.special),
      observedSlots,
      engineers: [],
      upgrades: [],
    });
  });
  blueprints.sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));
  const byKey = new Map(blueprints.map((bp) => [bp.key, bp]));

  // Planned upgrades: engineered module targets in saved builds, as assessed by Engineering.
  const configurations = list(progression.saved_configurations);
  const hullName = (shipType) =>
    list(reference.hulls).find((hull) => idKey(hull.id) === idKey(shipType))?.name ||
    text(shipType);
  const upgrades = [];
  list(progression.builds).forEach((build) => {
    const configuration = configurations.find((row) => row.build_plan_id === build.build_plan_id);
    const ship = hullName(configuration?.workbench?.ship?.ship_type);
    list(build.modules).forEach((module) => {
      if (!module.blueprint_id) return;
      const key = idKey(module.blueprint_id);
      const bp = byKey.get(key) || null;
      const effect = bp?.experimentals.find((row) => row.id === module.experimental_effect);
      const upgrade = {
        id: `${build.build_plan_id}:${module.slot}`,
        buildId: build.build_plan_id,
        buildTitle: text(build.title) || 'Saved build',
        ship,
        priority: text(build.priority) || 'unsorted',
        buildReadiness: build.readiness,
        slot: module.slot,
        moduleLabel: text(module.module_label) || module.slot,
        blueprintKey: key,
        blueprintId: module.blueprint_id,
        blueprintName: bp?.name || module.blueprint_id,
        blueprintKnown: Boolean(bp),
        targetGrade: module.target_grade,
        experimentalId: module.experimental_effect || null,
        experimentalName: module.experimental_effect
          ? effect?.name || module.experimental_effect
          : null,
        actualBlueprint: module.actual_blueprint || null,
        actualGrade: Number.isInteger(module.actual_grade) ? module.actual_grade : null,
        state: module.state,
        compatibility: module.compatibility_state,
        materials: list(build.materials),
        unknownInputs: list(build.unknown_inputs),
        nextAction: text(build.next_action),
      };
      upgrades.push(upgrade);
      bp?.upgrades.push(upgrade);
    });
  });

  // Engineers: what the Journal observed, the catalogue declares or the Commander
  // entered. Identity is the Journal's numeric EngineerID where an event carries
  // one; a display name is only ever matched when it is unambiguous, and that is
  // recorded so the inspector can say so.
  const engineerList = [];
  const byId = new Map();
  const byName = new Map();
  const ambiguous = new Map();
  const newEngineer = ({ key, id = null, name = '' }) => {
    const engineer = {
      key,
      id,
      name: text(name) || (id ? `Unnamed engineer (ID ${id})` : ''),
      nameKnown: Boolean(text(name)),
      observed: null,
      reference: null,
      location: null,
      place: null,
      declared: null,
      capabilities: [],
      crafts: [],
      contributions: [],
      records: [],
      matchedByName: new Set(),
      ambiguousName: false,
      identityNote: null,
      identityConfirmed: false,
      idBackedTwin: null,
    };
    engineerList.push(engineer);
    if (id) byId.set(id, engineer);
    const nameKey = personKey(name);
    if (nameKey) byName.set(nameKey, [...(byName.get(nameKey) || []), engineer]);
    return engineer;
  };
  /** Find or create the engineer for an id and/or name; name matches are recorded by source. */
  const resolveEngineer = ({ id = null, name = '' }, source) => {
    const validId = Number.isInteger(id) && id > 0 ? id : null;
    const nameKey = personKey(name);
    if (validId) {
      const known = byId.get(validId) || newEngineer({ key: `id:${validId}`, id: validId, name });
      if (!known.nameKnown && nameKey) {
        known.name = text(name);
        known.nameKnown = true;
        byName.set(nameKey, [...(byName.get(nameKey) || []), known]);
      }
      return known;
    }
    if (!nameKey) return null;
    const candidates = byName.get(nameKey) || [];
    if (candidates.length === 1) {
      candidates[0].matchedByName.add(source);
      return candidates[0];
    }
    if (candidates.length === 0) return newEngineer({ key: nameKey, name });
    // Several engineers share this display name: do not guess which one is meant.
    if (!ambiguous.has(nameKey)) {
      const engineer = newEngineer({ key: `name-unmatched:${nameKey}`, name });
      engineer.ambiguousName = true;
      byName.set(nameKey, candidates);
      ambiguous.set(nameKey, engineer);
    }
    const engineer = ambiguous.get(nameKey);
    engineer.matchedByName.add(source);
    return engineer;
  };

  const progress = engineerProgressModel(progression.engineer_progress);
  progress.engineers.forEach((entry) => {
    // Progress identities are already resolved by the Journal derivation.
    // A name-only observation cannot replace an ID-backed observation, even
    // when their display names match. Other sources retain disclosed name matching.
    const engineer = entry.engineerId
      ? resolveEngineer({ id: entry.engineerId, name: entry.name }, 'progress')
      : newEngineer({ key: entry.key || `name:${idKey(entry.name)}`, name: entry.name });
    if (engineer) engineer.observed = entry;
  });
  list(progression.observed_recipes).forEach((recipe) => {
    const engineer = resolveEngineer({ id: recipe.engineer_id, name: recipe.engineer }, 'crafts');
    if (engineer) engineer.crafts.push(recipe);
  });
  // The bundled reference directory. It joins the Journal by Frontier engineer ID
  // only; a name is never used to attach reference facts to a Journal identity.
  const directory = directoryModel(progression.engineer_directory);
  directory.engineers.forEach((entry) => {
    const earlier = byId.get(entry.engineerId);
    const engineer = resolveEngineer({ id: entry.engineerId, name: entry.name }, 'directory');
    engineer.reference = entry;
    if (earlier?.nameKnown && personKey(earlier.name) !== personKey(entry.name)) {
      engineer.identityNote = { journalName: earlier.name, referenceName: entry.name };
    } else if (earlier?.nameKnown && (earlier.observed || earlier.crafts.length)) {
      // The Journal itself reported this ID with this name.
      engineer.identityConfirmed = true;
    }
  });
  contributionsModel(progression.engineer_contributions).forEach((entry) => {
    const engineer = resolveEngineer({ id: entry.engineerId, name: entry.name }, 'contributions');
    if (engineer) engineer.contributions.push(...entry.lines);
  });
  list(reference.engineers).forEach((row) => {
    const engineer = resolveEngineer({ id: row.engineer_id, name: row.name }, 'catalogue');
    if (!engineer) return;
    engineer.location = text(row.location) || [text(row.system), text(row.base)].filter(Boolean).join(' · ') || null;
    engineer.declared = {
      state: text(row.access?.state) || null,
      requirements: text(row.access?.requirements) || null,
      referral: text(row.access?.referral) || null,
      system: text(row.system) || null,
      base: text(row.base) || null,
    };
    engineer.capabilities = list(row.blueprints).map((cap) => ({
      blueprintKey: idKey(cap.blueprint_id),
      blueprintId: cap.blueprint_id,
      maxGrade: cap.max_grade,
    }));
  });
  list(overview.readiness?.engineers).forEach((record) => {
    const engineer = resolveEngineer({ name: record.engineer_label }, 'records');
    if (engineer) engineer.records.push(record);
  });
  const engineers = engineerList.sort(
    (a, b) =>
      Number(Boolean(b.observed)) - Number(Boolean(a.observed)) ||
      a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }),
  );
  const withId = new Map();
  engineers.forEach((engineer) => {
    if (engineer.id && engineer.nameKnown) withId.set(personKey(engineer.name), engineer);
  });
  engineers.forEach((engineer) => {
    const referenced = engineer.reference?.location;
    if (referenced?.system) {
      engineer.place = {
        source: 'directory',
        status: referenced.status,
        system: referenced.system,
        base: referenced.base,
        notes: referenced.notes,
      };
    } else if (engineer.declared && engineer.location) {
      engineer.place = {
        source: 'catalogue',
        status: 'declared',
        system: engineer.declared.system,
        base: engineer.declared.base,
        text: engineer.location,
        notes: [],
      };
    }
    if (engineer.place) {
      const label = engineer.place.system
        ? [engineer.place.system, engineer.place.base].filter(Boolean).join(' · ')
        : engineer.place.text;
      if (
        engineer.place.source === 'directory' &&
        engineer.declared &&
        engineer.location &&
        personKey(engineer.location) !== personKey(label)
      ) {
        engineer.place.catalogueText = engineer.location;
      }
      engineer.location = label || engineer.location;
    }
    engineer.access = accessPlan(engineer);
    if (!engineer.id && !engineer.ambiguousName) {
      const twin = withId.get(personKey(engineer.name));
      if (twin) engineer.idBackedTwin = { key: twin.key, id: twin.id };
    }
  });
  engineers.forEach((engineer) => {
    engineer.crafts.sort((a, b) => String(b.observed_at).localeCompare(String(a.observed_at)));
    engineer.capabilities.forEach((cap) => {
      cap.blueprintName = byKey.get(cap.blueprintKey)?.name || cap.blueprintId;
      const bp = byKey.get(cap.blueprintKey);
      if (bp && !bp.engineers.some((row) => row.engineer.key === engineer.key)) {
        bp.engineers.push({ engineer, maxGrade: cap.maxGrade, declared: true, crafted: [] });
      }
    });
    engineer.crafts.forEach((recipe) => {
      const bp = byKey.get(idKey(recipe.blueprint_id));
      if (!bp) return;
      let link = bp.engineers.find((row) => row.engineer.key === engineer.key);
      if (!link) {
        link = { engineer, maxGrade: null, declared: false, crafted: [] };
        bp.engineers.push(link);
      }
      link.crafted.push(recipe.grade);
    });
  });

  const categories = new Map();
  blueprints.forEach((bp) => {
    bp.equipment.ids.forEach((id, index) => {
      if (!categories.has(id)) categories.set(id, { id, label: bp.equipment.labels[index], count: 0 });
      categories.get(id).count += 1;
    });
  });

  return {
    catalogue,
    inventory: { known: inventory.known, state: inventory.state },
    blueprints,
    byKey,
    upgrades,
    engineers,
    categories: [...categories.values()].sort((a, b) =>
      a.label.localeCompare(b.label, undefined, { sensitivity: 'base' }),
    ),
    counts: {
      blueprints: blueprints.length,
      upgrades: upgrades.length,
      engineers: engineers.length,
      observedEngineers: engineers.filter((engineer) => engineer.observed).length,
      referenceEngineers: directory.engineers.length,
    },
    engineerProgress: progress,
    directory,
  };
}

/** Everything a search should be able to find, lower-cased. */
export function searchText(blueprint) {
  const parts = [blueprint.name, blueprint.id, ...blueprint.equipment.labels];
  blueprint.grades.forEach((row) =>
    list(row.materials).forEach((material) => parts.push(material.display_name)),
  );
  blueprint.experimentals.forEach((effect) => parts.push(effect.name));
  blueprint.observedEffects.forEach((effect) => parts.push(effect));
  blueprint.engineers.forEach((link) => parts.push(link.engineer.name));
  blueprint.upgrades.forEach((upgrade) => parts.push(upgrade.buildTitle, upgrade.moduleLabel));
  return parts.filter(Boolean).join(' \n ').toLowerCase();
}

export function matchesQuery(haystack, query) {
  const tokens = text(query).toLowerCase().split(/\s+/).filter(Boolean);
  return tokens.every((token) => haystack.includes(token));
}

export function gradeSpan(grades) {
  if (!grades.length) return 'No recipe known';
  const first = grades[0];
  const last = grades[grades.length - 1];
  const contiguous = grades.length === last - first + 1;
  if (grades.length === 1) return `Grade ${first}`;
  return contiguous ? `Grades ${first}–${last}` : `Grades ${grades.join(', ')}`;
}
