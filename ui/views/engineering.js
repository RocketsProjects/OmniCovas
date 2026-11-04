/**
 * Phase 8 Engineering route.
 *
 * Local-only planning workspace. ADR 0003: all dynamic data is rendered with
 * DOM nodes and textContent; source-gated imports only record blocked attempts.
 */
import '../components/uiv3-frame-primitives.js';
import { freshnessLabel } from '../utils/freshness.js';
import { normalizeModuleName, normalizeShipName } from '../utils/display-names.js';
import { commanderError } from '../utils/commander-language.js';
import { createEngineeringBlueprints } from '../components/engineering-blueprints.js';
import { createEngineeringWorkbench } from '../components/engineering-workbench.js';
import { createMaterialsWorkspace } from '../components/engineering-materials.js';
import { createTechnologyPlanner } from '../components/engineering-technology-planner.js';
import { rememberUnlock, rememberedUnlock } from '../view-models/technology-planner.js';

(function () {
  'use strict';

  const SELECTORS = Object.freeze({
    root: 'engineering-root',
  });

  const GOAL_KIND_OPTIONS = Object.freeze([
    ['module_engineering', 'Module engineering'],
    ['ship_unlock', 'Ship unlock'],
    ['engineer_unlock', 'Engineer unlock'],
    ['guardian_tech', 'Guardian tech'],
    ['tech_broker_unlock', 'Tech broker unlock'],
    ['suit_engineering', 'Suit engineering'],
    ['general_progression', 'General progression'],
    ['commander_defined_other', 'Commander defined'],
  ]);

  const PRIORITY_OPTIONS = Object.freeze([
    ['normal', 'Normal'],
    ['high', 'High'],
    ['low', 'Low'],
    ['unsorted', 'Unsorted'],
  ]);

  const READINESS_OPTIONS = Object.freeze([
    ['blueprint_progress', 'Blueprint'],
    ['engineer_unlock_state', 'Engineer'],
    ['guardian_tech_progress', 'Guardian tech'],
    ['suit_engineering_state', 'Suit engineering'],
  ]);

  function safeText(value, fallback = 'Not checked') {
    if (value === null || value === undefined || value === '') return fallback;
    return String(value);
  }

  function el(tagName, className = '', text = null) {
    const node = document.createElement(tagName);
    if (className) node.className = className;
    if (text !== null && text !== undefined) node.textContent = String(text);
    return node;
  }

  function field(label, value) {
    const row = el('div', 'engineering-field');
    row.append(el('span', 'engineering-field-label', label));
    row.append(el('span', 'engineering-field-value', value));
    return row;
  }

  function badge(text, variant = '') {
    const node = el('span', variant ? `engineering-badge ${variant}` : 'engineering-badge');
    node.textContent = safeText(text, 'Not checked');
    return node;
  }

  function option(value, label, selected = false) {
    const node = document.createElement('option');
    node.value = value;
    node.textContent = label;
    node.selected = selected;
    return node;
  }

  function labeledInput(labelText, input) {
    const label = el('label', 'engineering-form-field');
    label.append(el('span', 'engineering-form-label', labelText), input);
    return label;
  }

  function textInput(name, placeholder = '', options = {}) {
    const input = document.createElement('input');
    input.name = name;
    input.type = options.type || 'text';
    input.placeholder = placeholder;
    if (options.required) input.required = true;
    if (options.min !== undefined) input.min = String(options.min);
    if (options.max !== undefined) input.max = String(options.max);
    if (options.maxLength !== undefined) input.maxLength = options.maxLength;
    return input;
  }

  function textArea(name, placeholder = '') {
    const area = document.createElement('textarea');
    area.name = name;
    area.rows = 3;
    area.placeholder = placeholder;
    return area;
  }

  function selectInput(name, options, initial = '') {
    const select = document.createElement('select');
    select.name = name;
    options.forEach(([value, label]) => select.append(option(value, label, value === initial)));
    return select;
  }

  function formValue(form, name) {
    const value = new FormData(form).get(name);
    return typeof value === 'string' ? value.trim() : '';
  }

  function optionalNumber(form, name) {
    const raw = formValue(form, name);
    if (!raw) return null;
    const value = Number(raw);
    return Number.isFinite(value) ? value : null;
  }

  function appendIfPresent(target, key, value) {
    if (value !== null && value !== undefined && value !== '') {
      target[key] = value;
    }
  }

  function emptyState(message) {
    return el('p', 'engineering-empty', message);
  }

  class EngineeringController {
    constructor(rootOverride = null) {
      this.root = rootOverride || document.getElementById(SELECTORS.root);
      this.overview = null;
      this.localContext = null;
      this.statusNode = null;
      this._activeStage = 'builds';
      /* GKI-01 Technology planner: bundled knowledge plus the selected unlock's
         plan. Held here so leaving and re-entering a stage or route keeps it. */
      this.knowledge = null;
      this._technologyState = { unlockId: null, selected: null, quantity: null, recipe: null };
      this._technologyReturn = null;
      /* GKI-03: the Galactic Atlas (Intel) can open Materials on a documented
         material. Engineering only re-renders on load, so the handoff is
         applied from the transfer event itself. */
      window.OmniEvents?.addEventListener('route-transfer-started', (event) => {
        const intent = event?.detail?.intent;
        if (intent?.targetRoute !== '/engineering' || intent.targetSectionId !== 'engineering-stage-materials'
          || !intent.targetEntityId) return;
        // From the Atlas, a return from Navigation to the material Materials
        // handed off (GKI-05), or an expedition stop's material (GKI-06); other
        // Navigation handoffs are not Materials returns.
        const fromExpedition = intent.originRoute === '/navigation' && intent.originPackage === 'Expeditions';
        if (intent.originRoute !== '/intel' && !fromExpedition
          && !(intent.originRoute === '/navigation' && this._materialsReturn)) return;
        if (fromExpedition) {
          this._materialsReturn = {
            perspective: 'acquisition',
            material: String(intent.targetEntityId).toLowerCase(),
            scope: intent.targetPurpose?.scope || null,
          };
        }
        // The shell may already have shown, and cleared, the arrival against the
        // previous DOM; restore it so this render shows the arrival and way back.
        if (window.Shell && !window.Shell.routeTransferIntent) window.Shell.routeTransferIntent = intent;
        this.openFromAtlas(intent);
      });
      this.init();
    }

    /* Show a material the Atlas documented a source for, in the Materials
       inventory view. A material not in the observed inventory is searched for
       so Materials says so plainly instead of selecting another. */
    openFromAtlas(intent) {
      const symbol = String(intent.targetEntityId).toLowerCase();
      const materials = this._materialsState ||= { search: '', category: 'all', availability: 'all', selected: null };
      const observed = (this.overview?.progression?.inventory?.materials || [])
        .some((row) => row.material_id === symbol);
      // GKI-05: a return from Navigation or the Atlas to the material the
      // commander left from restores that perspective (usually Acquisition).
      const back = this._materialsReturn?.material === symbol ? this._materialsReturn : null;
      this._materialsReturn = null;
      if (back && back.perspective !== 'inventory') {
        Object.assign(materials, { perspective: back.perspective, detail: false, acquisitionFocus: symbol });
        // GKI-08: the build the expedition stop was planned for, while it is still
        // an active build; otherwise the scope the commander last used stands.
        const builds = this.overview?.progression?.builds || [];
        if (back.scope === 'all' || builds.some((b) => b.build_plan_id === back.scope)) materials.buildId = back.scope;
        this._technologyReturn = null;
        this._activeStage = 'materials';
        if (this.overview) this.render(this.overview);
        return;
      }
      Object.assign(materials, {
        category: 'all', availability: 'all', detail: true, inventorySelectedByUser: true,
        perspective: 'inventory', selected: symbol, search: observed ? '' : intent.targetLabel || '',
      });
      this._technologyReturn = null;
      this._activeStage = 'materials';
      if (this.overview) this.render(this.overview);
    }

    get apiBase() {
      if (window.Shell?.httpBase) return window.Shell.httpBase;
      return null;
    }

    apiUrl(path) {
      const base = this.apiBase;
      return base ? `${base}${path}` : null;
    }

    init() {
      if (!this.root) return;
      this.renderWaiting();
      if (this.apiBase) {
        this.fetchAndRender();
        return;
      }
      window.OmniEvents?.addEventListener('bridge-connected', () => this.fetchAndRender(), {
        once: true,
      });
    }

    async fetchJson(path, options = {}) {
      const url = this.apiUrl(path);
      if (!url) return null;
      const response = await window.fetch(url, options);
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        const message = body?.detail || `Request failed: ${response.status}`;
        throw new Error(String(message));
      }
      return body;
    }

    async fetchAndRender() {
      if (!this.root) return;
      try {
        /* Local inventory snapshots (Backpack/ShipLocker/FCMaterials) ride the
           local-context backplane. A failed snapshot fetch never blocks the
           Engineering overview — the inventory section falls back honestly. */
        const [overview, localContext, catalog] = await Promise.all([
          this.fetchJson('/engineering/overview'),
          this.fetchJson('/intel/local-context/snapshot').catch(() => null),
          /* Bundled, offline knowledge. A failure only degrades the
             Technology stage; the rest of Engineering is unaffected. */
          this.fetchJson('/knowledge/catalog').catch((error) => ({ error })),
        ]);
        await this.fetchTechnologyPlan(catalog?.error ? null : catalog, catalog?.error);
        /* LNA-022 ship profile, from the one readiness service that also
           answers Operations and the Dashboard. A failed fetch degrades the
           card honestly and never blocks the Engineering overview. */
        this.shipProfile = await this.fetchJson('/readiness/ship-profile')
          .catch(() => null);
        if (!overview) {
          this.renderWaiting();
          return;
        }
        this.overview = overview;
        this.localContext = localContext;
        this.render(overview);
      } catch (error) {
        this.renderUnavailable(error);
      }
    }

    async postJson(path, payload = {}) {
      const body = await this.fetchJson(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      await this.fetchAndRender();
      return body;
    }

    renderWaiting() {
      if (!this.root) return;
      const shell = el('section', 'engineering-shell');
      shell.classList.add('engineering-outfitting-page');
      shell.append(
        this.createHeader({
          status: 'Bridge not ready',
          counts: {},
          dashboard_pin: { inventory: 'No Verified Source' },
        }),
        emptyState('Waiting for OmniCOVAS bridge.'),
      );
      this.root.replaceChildren(shell);
    }

    renderUnavailable(error) {
      if (!this.root) return;
      const shell = el('section', 'engineering-shell');
      shell.append(
        this.createHeader({
          status: 'not_checked',
          counts: {},
          dashboard_pin: { inventory: 'No Verified Source' },
        }),
        this.createErrorMessage(error),
      );
      this.root.replaceChildren(shell);
    }

    createErrorMessage(error) {
      const model = commanderError(error, {
        task: 'Engineering',
        impact: 'Your saved plans were not changed.',
        recovery: 'Try again or open connection details.',
      });
      const state = el('section', 'engineering-empty engineering-error');
      state.setAttribute('role', 'alert');
      state.append(
        el('strong', '', model.title),
        el('span', '', ` ${model.impact} ${model.recovery}`),
      );
      if (model.technicalDetail) {
        const details = el('details', 'engineering-source-why');
        details.append(
          el('summary', 'engineering-source-why-summary', 'Technical details'),
          el('p', 'engineering-card-note', model.technicalDetail),
        );
        state.appendChild(details);
      }
      return state;
    }

    /* LNA-022: current ship, role fit from observed modules, and the facts
       that have not been observed. Role fit is evidence, never a verdict —
       a capability not listed was not seen locally, which is not proof the
       ship lacks it. */
    createShipProfileCard() {
      const card = el('section', 'engineering-card engineering-ship-profile');
      card.setAttribute('aria-label', 'Current ship profile');
      card.appendChild(el('h3', 'engineering-card-title', 'Your current ship'));

      const profile = this.shipProfile;
      if (!profile) {
        card.appendChild(el('p', 'engineering-note',
          'Ship profile unavailable — the local readiness service did not answer.'));
        return card;
      }

      const facts = profile.facts || {};
      const shipName = normalizeShipName(facts.ship_name || facts.ship_type).display;
      const identity = [shipName === 'Unknown ship' ? null : shipName, facts.ship_ident]
        .filter(Boolean).join(' — ') || 'Current ship not checked yet';
      card.appendChild(el('p', 'engineering-ship-identity', identity));

      const fit = profile.role_fit || {};
      const roles = Array.isArray(fit.roles) ? fit.roles : [];
      if (!fit.loadout_observed) {
        card.appendChild(el('p', 'engineering-note',
          'Loadout not checked yet. Enter this ship in Elite Dangerous to update it.'));
      } else {
        card.appendChild(el('p', 'engineering-note', 'Possible roles from this loadout'));
        const list = el('ul', 'engineering-role-list');
        roles.forEach((role) => {
          const item = el('li', 'engineering-role-row');
          const fitted = (role.fitted || []).map((module) => normalizeModuleName(module).display).join(', ');
          item.append(
            el('span', 'engineering-role-name', safeText(role.role).replace(/fitted$/i, '')),
            el('span', 'engineering-role-value',
              fitted || 'No matching modules seen'),
          );
          list.appendChild(item);
        });
        const clues = el('details', 'engineering-source-why');
        clues.append(
          el('summary', 'engineering-source-why-summary', 'See modules used for these suggestions'),
          list,
          el('p', 'engineering-card-note', 'Only modules OmniCOVAS has seen in the latest loadout are included.'),
        );
        card.appendChild(clues);
      }

      const missing = Array.isArray(profile.missing_facts) ? profile.missing_facts : [];
      if (missing.length > 0) {
        /* Naming what is unobserved is the point: a Commander can see why an
           answer is unavailable instead of meeting a blank. */
        const missingDetails = el('details', 'engineering-source-why');
        missingDetails.append(
          el('summary', 'engineering-source-why-summary', 'Details not checked yet'),
          el('p', 'engineering-card-note', missing.map((item) => safeText(item)).join(', ')),
        );
        card.appendChild(missingDetails);
      }
      return card;
    }

    render(overview) {
      this.overview = overview;
      this._designSource ||= 'observed';
      const shell = el('section', 'engineering-shell');
      shell.classList.add('engineering-outfitting-page');

      const heading = el('div', 'engineering-route-heading');
      heading.append(this.createHeader(overview), this.createStageNav());
      shell.append(heading, this.createOutfittingReturn(), this.createTechnologyReturn());

      const library = el('details', 'engineering-build-library');
      library.append(el('summary', '', 'Saved plans, reservations & handoffs'),
        this.createProgressionCockpit(overview), this.createBuildsSection(overview),
        this.createGoalsSection(overview));

      const workspace = el('div', 'engineering-stage-workspace');
      workspace.append(
        this.createStagePanel('builds', [
          this.createActiveBuildDesigner(overview),
          library,
        ]),
        this.createStagePanel('materials', [
          createMaterialsWorkspace(this, overview),
          this.createAcquisitionSection(overview),
          this.createMaterialsManualArea(overview),
        ]),
        this.createStagePanel('engineers', [this.createEngineersMode(overview)]),
        this.createStagePanel('technology', [this.createTechnologyMode(overview)]),
      );
      shell.appendChild(workspace);

      shell.appendChild(this.createSecondaryDetail(overview));

      this.root.replaceChildren(shell);
      this._setStage(this._activeStage || 'builds');
      this.applyRouteTransferArrival();
    }

    createAdvancedGameDataDisclosure(overview) {
      const details = el('details', 'engineering-secondary engineering-advanced-data');
      details.append(
        el('summary', 'engineering-secondary-summary', 'Advanced game data'),
        this.createReferenceCatalogSection(overview),
      );
      return details;
    }

    createActiveBuildDesigner(overview) {
      if (this._designSource === 'reference' && !(overview.progression?.reference_catalog?.hulls || []).some(h=>Object.keys(h.stock_modules || {}).length))
        return this.createReferenceBuildDesigner(overview);
      return this.createBuildDesigner(overview);
    }

    createReferenceCatalogSection(overview) {
      const catalog = overview.progression?.reference_catalog || {};
      const active = catalog.state === 'commander_supplied_validated';
      const localPlants = catalog.catalog_id === 'edsy-local-power-plants';
      const fullOutfitting = catalog.catalog_id === 'edsy-local-outfitting' && !catalog.private_reference_update_available;
      const section = this.createSection(
        'engineering-reference-catalog',
        'Add ship and module data',
        active ? (fullOutfitting ? `${safeText(catalog.module_count)} modules · ${safeText(catalog.coverage?.module_families)} families` : localPlants ? 'Power plant subset ready · upgrade available' : `${safeText(catalog.hull_count, 0)} ships available`) : 'Reference needed for replacements',
      );
      section.appendChild(el('p', 'engineering-card-note', fullOutfitting
        ? 'Catalogue-backed core, optional, military, hardpoint and utility selection. Slot, hull, mass-support, module-count and operating-power checks apply. Source gaps remain explicit.'
        : localPlants
        ? 'Standard power plants, sizes 2–8 and ratings A–E; Armoured, Low Emissions and Overcharged G1–G5; four experimentals. Other module records supply baseline calculations only. This is a supported subset.'
        : active ? 'Compatible ship and module data is available from your local pack.'
          : 'Enable the local outfitting catalogue once to choose compatible modules you have never owned. It stays on this PC and works offline afterward.'));
      if (!fullOutfitting) {
        const consent = document.createElement('input');
        consent.type = 'checkbox';
        consent.name = 'private_reference_use';
        const consentLabel = el('label', 'engineering-catalog-attestation');
        consentLabel.append(consent, el('span', '', 'I confirm private non-commercial reference use. Download one pinned public EDSY file from GitHub; no commander data is sent. Frontier retains game data rights; redistribution permission is unverified.'));
        const download = el('button', 'ocv-btn engineering-action cmd-btn cmd-btn--secondary', 'Enable local outfitting catalogue');
        download.type = 'button';
        download.disabled = true;
        consent.addEventListener('change', () => { download.disabled = !consent.checked; });
        const result = el('p', 'engineering-action-status');
        download.addEventListener('click', async () => {
          download.disabled = true;
          result.textContent = 'Downloading and checking the reference…';
          try {
            this._designSource = 'observed';
            await this.postJson('/engineering/catalog/local-outfitting', { private_use_confirmed: consent.checked });
          } catch (error) {
            result.textContent = error?.message || 'The reference could not be downloaded. Your existing data is preserved.';
            download.disabled = !consent.checked;
          }
        });
        section.append(consentLabel, download, result);
      }
      if (active) {
        const modes = el('div', 'engineering-form-actions engineering-design-source-actions');
        const referenceButton = el('button', 'ocv-btn-ghost engineering-action cmd-btn cmd-btn--quiet', 'Plan another ship');
        referenceButton.type = 'button';
        referenceButton.disabled = this._designSource !== 'observed';
        const observedButton = el('button', 'ocv-btn-ghost engineering-action cmd-btn cmd-btn--quiet', 'Plan current ship');
        observedButton.type = 'button';
        observedButton.disabled = this._designSource === 'observed';
        referenceButton.addEventListener('click', () => {
          if ((catalog.hulls || []).some(h => Object.keys(h.stock_modules || {}).length)) {
            const chooser = this.root.querySelector('[name=ship], [name=new_hull]');
            chooser?.scrollIntoView({ block: 'center' });
            chooser?.focus({ preventScroll: true });
            return;
          }
          this._designSource = 'reference';
          this.render(this.overview);
        });
        observedButton.addEventListener('click', () => {
          this._selectedBuildId = null;
          this._selectedObservationId = null;
          this._observedWorkbench = null;
          this._designSource = 'observed';
          this.render(this.overview);
        });
        modes.append(referenceButton, observedButton);
        section.appendChild(modes);
        const proof = el('details', 'engineering-source-why');
        proof.append(
          el('summary', 'engineering-source-why-summary', 'Coverage and provenance'),
          field('Source', safeText(catalog.provenance?.source_name)),
          field('Licence', safeText(catalog.provenance?.license)),
          field('Digest', safeText(catalog.sha256)),
          el('p', 'engineering-card-note', safeText(catalog.verification_boundary)),
        );
        section.appendChild(proof);
      }

      const disclosure = el('details', 'engineering-source-why');
      disclosure.appendChild(el('summary', 'engineering-source-why-summary', active
        ? 'Replace data file' : 'Choose data file…'));
      const form = el('form', 'engineering-form engineering-catalog-import-form');
      const file = document.createElement('input');
      file.type = 'file';
      file.name = 'catalog_file';
      file.accept = 'application/json,.json';
      file.required = true;
      const attestation = document.createElement('input');
      attestation.type = 'checkbox';
      attestation.name = 'rights_attested';
      const attestationLabel = el('label', 'engineering-catalog-attestation');
      attestationLabel.append(
        attestation,
        el('span', '', 'I may use this local pack and its provenance and licence fields are accurate.'),
      );
      const action = el('button', 'ocv-btn engineering-action cmd-btn cmd-btn--secondary', 'Check and add data');
      action.type = 'submit';
      const status = el('p', 'engineering-action-status');
      form.append(labeledInput('Compatible JSON data file', file), attestationLabel, action, status);
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const selected = file.files?.[0];
        if (!selected) {
          status.textContent = 'Choose a compatible JSON data file.';
          return;
        }
        if (!attestation.checked) {
          status.textContent = 'Confirm the local-use and provenance statement first.';
          return;
        }
        try {
          const catalogPayload = JSON.parse(await selected.text());
          this._designSource = 'reference';
          await this.postJson('/engineering/catalog/import', {
            catalog: catalogPayload,
            rights_attested: true,
          });
          status.textContent = 'Ship and module data added on this PC.';
        } catch (error) {
          this._designSource = 'observed';
          status.textContent = 'That data file could not be added. Review its format and origin, then try again.';
        }
      });
      disclosure.appendChild(form);
      section.appendChild(disclosure);
      return section;
    }

    createReferenceBuildDesigner(overview) {
      const catalog = overview.progression?.reference_catalog || {};
      const section = this.createSection(
        'engineering-reference-build-designer',
        'Plan another ship',
        catalog.state === 'commander_supplied_validated' ? 'Your plan' : 'Ship data needed',
      );
      if (catalog.state !== 'commander_supplied_validated') {
        section.appendChild(emptyState('Add compatible ship data in Advanced game data to plan a ship you do not own.'));
        return section;
      }
      const hulls = Array.isArray(catalog.hulls) ? catalog.hulls : [];
      const modules = Array.isArray(catalog.modules) ? catalog.modules : [];
      const blueprints = Array.isArray(catalog.blueprints) ? catalog.blueprints : [];
      const form = el('form', 'engineering-reference-build-form');
      const hullSelect = selectInput('hull_id', hulls.map((hull) => [hull.id, hull.name]), hulls[0]?.id || '');
      const summary = el('div', 'engineering-form engineering-build-summary');
      summary.append(
        labeledInput('Hull', hullSelect),
        labeledInput('Build name', textInput('title', 'e.g. Future explorer', { required: true })),
        labeledInput('Priority', selectInput('priority', PRIORITY_OPTIONS, 'normal')),
        labeledInput('Acquisition destination', textInput('acquisition_destination', 'Optional system, station, or site')),
      );
      form.appendChild(summary);
      const moduleList = el('div', 'engineering-build-module-list');
      form.appendChild(moduleList);

      const compatibleModules = (slot, hullId) => modules.filter((module) => (
        (module.slot_types || []).includes(slot.slot_type)
        && Number(module.class) <= Number(slot.size)
        && (!(slot.exact_size || module.rules?.no_undersize) || Number(module.class) === Number(slot.size))
        && (!(module.rules?.required_slot_prefixes || []).length || module.rules.required_slot_prefixes.some((prefix) => slot.id.toLowerCase().startsWith(prefix.toLowerCase())))
        && !(module.rules?.forbidden_slot_prefixes || []).some((prefix) => slot.id.toLowerCase().startsWith(prefix.toLowerCase()))
        && (!module.rules?.hull_slot_restrictions?.[hullId] || module.rules.hull_slot_restrictions[hullId].includes(slot.id))
        && (slot.allowed_categories || []).includes(module.category)
        && (!(module.hull_restrictions || []).length || module.hull_restrictions.includes(hullId))
      ));
      const renderBlueprintControls = (row, module) => {
        const blueprintSelect = row.querySelector('[name="blueprint_id"]');
        const gradeSelect = row.querySelector('[name="target_grade"]');
        const experimentalSelect = row.querySelector('[name="experimental_effect"]');
        const supported = blueprints.filter((bp) => (bp.module_categories || []).includes(module.category) && (!Array.isArray(module.blueprint_ids) || module.blueprint_ids.includes(bp.id)));
        const include = row.querySelector('[name="include_module"]');
        const mode = row.querySelector('[name="target_state"]');
        mode.replaceChildren(option('stock', 'Fit stock module', true), ...(supported.length ? [option('engineered', 'Fit and engineer module')] : []));
        const setMode = () => [blueprintSelect, gradeSelect, experimentalSelect].forEach((control) => { control.disabled = mode.value !== 'engineered'; });
        mode.onchange = setMode;
        setMode();
        blueprintSelect.replaceChildren(...supported.map((bp, index) => option(bp.id, bp.name, index === 0)));
        const selected = supported[0];
        gradeSelect.replaceChildren(...Object.keys(selected?.grades || {}).map((grade, index) => option(grade, `Grade ${grade}`, index === 0)));
        experimentalSelect.replaceChildren(option('', 'None', true), ...(selected?.experimentals || []).filter((effect) => !Array.isArray(module.experimental_ids) || module.experimental_ids.includes(effect.id)).map((effect) => option(effect.id, effect.name)));
        const refreshEffect = () => {
          const blueprint = blueprints.find((bp) => bp.id === blueprintSelect.value);
          gradeSelect.replaceChildren(...Object.keys(blueprint?.grades || {}).map((grade, index) => option(grade, `Grade ${grade}`, index === 0)));
          experimentalSelect.replaceChildren(option('', 'None', true), ...(blueprint?.experimentals || []).filter((effect) => !Array.isArray(module.experimental_ids) || module.experimental_ids.includes(effect.id)).map((effect) => option(effect.id, effect.name)));
        };
        blueprintSelect.onchange = refreshEffect;
      };
      const renderSlots = () => {
        moduleList.replaceChildren();
        const hull = hulls.find((item) => item.id === hullSelect.value);
        (hull?.slots || []).forEach((slot) => {
          const choices = compatibleModules(slot, hull.id);
          const row = el('fieldset', 'engineering-build-module-row');
          row.dataset.slot = slot.id;
          const legend = el('legend', 'engineering-build-module-legend');
          const enabled = document.createElement('input');
          enabled.type = 'checkbox';
          enabled.name = 'include_module';
          enabled.checked = !!slot.required || !!hull.stock_modules?.[slot.id];
          enabled.disabled = !!slot.required;
          legend.append(enabled, el('span', '', `${slot.label} · class ${slot.size}`));
          row.appendChild(legend);
          if (choices.length === 0) {
            row.appendChild(el('p', 'engineering-card-note', 'No compatible module is present in the added data file.'));
            moduleList.appendChild(row);
            return;
          }
          const defaultModule = choices.find((item) => item.id === hull.stock_modules?.[slot.id]) || choices[0];
          const moduleSelect = selectInput('module_id', choices.map((item) => [item.id, item.name]), defaultModule.id);
          const mode = selectInput('target_state', [['stock', 'Fit stock module']], 'stock');
          const blueprintSelect = selectInput('blueprint_id', [], '');
          const gradeSelect = selectInput('target_grade', [], '');
          const experimentalSelect = selectInput('experimental_effect', [['', 'None']], '');
          const controls = el('div', 'engineering-build-module-controls');
          controls.append(
            labeledInput('Module', moduleSelect),
            labeledInput('Plan', mode),
            labeledInput('Blueprint', blueprintSelect),
            labeledInput('Grade', gradeSelect),
            labeledInput('Experimental', experimentalSelect),
          );
          row.append(controls, el('p', 'engineering-compatibility-note',
            'Choices are filtered by this pack’s slot type, size, category, and hull restrictions; the backend revalidates them when saved.'));
          moduleSelect.addEventListener('change', () => {
            const selected = modules.find((item) => item.id === moduleSelect.value);
            renderBlueprintControls(row, selected);
          });
          renderBlueprintControls(row, defaultModule);
          moduleList.appendChild(row);
        });
      };
      hullSelect.addEventListener('change', renderSlots);
      renderSlots();

      const actions = el('div', 'engineering-form-actions');
      const submit = el('button', 'ocv-btn engineering-action cmd-btn cmd-btn--secondary', 'Save unowned-ship plan');
      submit.type = 'submit';
      const status = el('p', 'engineering-action-status');
      actions.append(submit, status);
      form.appendChild(actions);
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const targets = Array.from(form.querySelectorAll('.engineering-build-module-row'))
          .filter((row) => row.querySelector('[name="include_module"]')?.checked)
          .map((row) => ({
            slot: row.dataset.slot,
            module_id: row.querySelector('[name="module_id"]').value,
            target_state: row.querySelector('[name="target_state"]').value,
            blueprint_id: row.querySelector('[name="target_state"]').value === 'engineered' ? row.querySelector('[name="blueprint_id"]').value : null,
            target_grade: row.querySelector('[name="target_state"]').value === 'engineered' ? Number(row.querySelector('[name="target_grade"]').value) : null,
            experimental_effect: row.querySelector('[name="target_state"]').value === 'engineered' ? row.querySelector('[name="experimental_effect"]').value || null : null,
          }));
        if (targets.length === 0) {
          status.textContent = 'Choose at least one physical slot.';
          return;
        }
        try {
          await this.postJson('/engineering/workbench/builds', {
            title: formValue(form, 'title'),
            hull_id: hullSelect.value,
            priority: formValue(form, 'priority') || 'normal',
            acquisition_destination: formValue(form, 'acquisition_destination') || null,
            module_targets: targets,
          });
          status.textContent = 'Unowned-ship plan saved locally.';
        } catch (error) {
          status.textContent = error?.message || 'Could not save the ship plan.';
        }
      });
      section.append(form);
      (catalog.limitations || []).forEach((message) => section.appendChild(el('p', 'engineering-card-note', message)));
      return section;
    }

    createBuildDesigner(overview) {
      return createEngineeringWorkbench(this, overview);
    }

    createProgressionCockpit(overview) {
      const progression = overview.progression || {};
      const builds = Array.isArray(progression.builds) ? progression.builds : [];
      const recipes = Array.isArray(progression.observed_recipes) ? progression.observed_recipes : [];
      const lead = builds[0] || null;
      const section = this.createSection(
        'engineering-progression-cockpit',
        'Build readiness',
        progression.inventory?.state === 'verified_local' ? 'Inventory updated' : 'Materials not checked',
      );
      section.classList.add('engineering-progression-cockpit');

      const brief = el('div', 'engineering-progression-brief');
      brief.append(
        field('Your plan', lead ? safeText(lead.title) : 'No module selected'),
        field('Blocking', lead
          ? (lead.unknown_inputs?.[0] || lead.materials?.find((row) => row.deficit)?.display_name || 'No verified blocker')
          : 'Choose a blueprint and grade'),
        field('Next action', lead ? safeText(lead.next_action) : 'Choose module'),
      );
      section.appendChild(brief);

      if (lead) {
        const modules = el('div', 'engineering-progression-modules');
        (lead.modules || []).forEach((module) => {
          const row = el('article', 'engineering-readiness-item');
          row.append(
            el('h3', 'engineering-card-title', safeText(module.module_label, module.slot)),
            field('Desired', `${module.blueprint_id} G${module.target_grade}${module.experimental_effect ? ` · ${module.experimental_effect}` : ''}`),
            field(module.compatibility_state === 'catalog_validated' ? 'Fit' : 'Observed', module.compatibility_state === 'catalog_validated'
              ? 'Compatible with the added ship data'
              : module.actual_grade == null
              ? 'Target slot not checked in the latest loadout'
              : `${module.actual_blueprint || 'Unengineered'} G${module.actual_grade}`),
            field('Readiness', module.state),
          );
          modules.appendChild(row);
        });
        section.appendChild(modules);

        const materialList = el('ul', 'engineering-inventory-list engineering-allocation-list');
        (lead.materials || []).forEach((material) => {
          const value = material.deficit == null
            ? `${material.display_name}: inventory unknown; ${material.required} required`
            : `${material.display_name}: ${material.reserved}/${material.required} reserved · ${material.deficit} short`;
          materialList.appendChild(el('li', 'engineering-inventory-row', value));
        });
        if (lead.materials?.length) section.appendChild(materialList);
        if (lead.trade_alternatives?.length) {
          const alternatives = el('div', 'engineering-trade-alternatives');
          alternatives.appendChild(el('h3', 'engineering-card-title', 'Material Trader alternatives'));
          lead.trade_alternatives.forEach((trade) => {
            alternatives.appendChild(el('p', 'engineering-card-note',
              `Proposal only: trade ${trade.pay} ${trade.from_display_name} for ${trade.receive} ${trade.to_display_name}; up to ${trade.useful_receive} would help after current reservations.`));
          });
          section.appendChild(alternatives);
        }
        (lead.unknown_inputs || []).forEach((message) => {
          section.appendChild(el('p', 'engineering-card-note engineering-unknown-input', message));
        });

        if (lead.readiness !== 'verified_ready') {
          const acknowledge = el('button', 'ocv-btn-ghost engineering-action cmd-btn cmd-btn--quiet', 'Acknowledge ready manually');
          acknowledge.type = 'button';
          acknowledge.addEventListener('click', async () => {
            const accepted = await window.OmniConfirmationGate?.confirmLocalAction?.({
              title: 'Acknowledge engineering readiness?',
              message: 'This closes the local goal by Commander acknowledgement. It does not claim the game reported completion.',
              confirmLabel: 'Acknowledge ready',
              cancelLabel: 'Keep tracking',
            });
            if (accepted) {
              await this.handleAction(() => this.postJson(
                `/engineering/progression/${encodeURIComponent(lead.build_plan_id)}/acknowledge-ready`, {},
              ), 'Readiness acknowledged locally.');
            }
          });
          section.appendChild(acknowledge);
        }
      }

      const details = el('details', 'engineering-commission-details');
      details.appendChild(el('summary', 'engineering-source-why-summary', 'About material costing'));
      details.appendChild(el('p', 'engineering-card-note', recipes.length === 0
        ? 'Exact material totals appear after the corresponding EngineerCraft grade records its ingredient bill in your Journal.'
        : 'The ship builder is the single place to choose modules and engineering. Saved changes feed this material assessment automatically.'));
      section.appendChild(details);

      const proof = el('details', 'engineering-source-why');
      proof.append(
        el('summary', 'engineering-source-why-summary', 'How totals were calculated'),
        el('p', 'engineering-card-note', progression.fixed_roll_policy || 'Costs that have not been observed are not estimated.'),
        el('p', 'engineering-card-note', progression.allocation_policy || 'One local inventory pool is shared across active goals.'),
        el('p', 'engineering-card-note', progression.inventory?.state === 'verified_local'
          ? `Reconciled from the local Materials baseline at ${safeText(progression.inventory.observed_at)} and ${safeText(progression.inventory.event_count, 1)} supported event(s).`
          : 'Materials have not been checked from a complete Journal baseline. Missing counts are never treated as zero.'),
      );
      section.appendChild(proof);
      return section;
    }

    createProgressionCommissionForm(recipes) {
      const form = el('form', 'engineering-form engineering-form--commission');
      const recipeOptions = [];
      const seen = new Set();
      recipes.forEach((recipe) => {
        if (seen.has(recipe.blueprint_id)) return;
        seen.add(recipe.blueprint_id);
        recipeOptions.push([recipe.blueprint_id, recipe.blueprint_label || recipe.blueprint_id]);
      });
      form.append(
        labeledInput('Goal', textInput('title', 'e.g. Exploration FSD', { required: true })),
        labeledInput('Module slot', textInput('slot', 'Journal slot, e.g. FrameShiftDrive', { required: true })),
        labeledInput('Module label', textInput('module_label', 'e.g. 5A Frame Shift Drive')),
        labeledInput('Observed blueprint', selectInput('blueprint_id', recipeOptions, recipeOptions[0]?.[0] || '')),
        labeledInput('Target grade', textInput('target_grade', '1–5', { type: 'number', min: 1 })),
        labeledInput('Experimental effect', textInput('experimental_effect', 'Optional; cost remains unknown unless observed')),
        labeledInput('Priority', selectInput('priority', PRIORITY_OPTIONS, 'normal')),
        labeledInput('Acquisition destination', textInput('acquisition_destination', 'Optional system, station, or site')),
      );
      const actions = el('div', 'engineering-form-actions');
      const submit = el('button', 'ocv-btn engineering-action cmd-btn cmd-btn--secondary', 'Add blueprint');
      submit.type = 'submit';
      actions.appendChild(submit);
      form.appendChild(actions);
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const payload = {
          title: formValue(form, 'title'),
          slot: formValue(form, 'slot'),
          blueprint_id: formValue(form, 'blueprint_id'),
          target_grade: optionalNumber(form, 'target_grade'),
          priority: formValue(form, 'priority') || 'normal',
        };
        appendIfPresent(payload, 'module_label', formValue(form, 'module_label'));
        appendIfPresent(payload, 'experimental_effect', formValue(form, 'experimental_effect'));
        appendIfPresent(payload, 'acquisition_destination', formValue(form, 'acquisition_destination'));
        await this.handleAction(() => this.postJson('/engineering/progression/commission', payload), 'Target commissioned locally.');
      });
      return form;
    }

    /* One stage workspace panel. All panels live in the DOM; only the active
       one is visible (the others carry the hidden attribute) so the stage
       selector swaps the visible workspace rather than scrolling a long page. */
    createStagePanel(stageId, sections) {
      const panel = el('div', 'engineering-stage-panel');
      panel.id = `engineering-stage-${stageId}`;
      panel.setAttribute('data-stage-panel', stageId);
      panel.setAttribute('role', 'tabpanel');
      panel.setAttribute('aria-labelledby', `engineering-stage-tab-${stageId}`);
      sections.forEach((section) => panel.appendChild(section));
      return panel;
    }

    /* Collapsed secondary: readiness, source gates, and proof are real but
       subordinate — folded below the working surface, not competing with it. */
    createSecondaryDetail(overview) {
      const details = el('details', 'engineering-secondary');
      const summary = el('summary', 'engineering-secondary-summary', 'Details');
      details.appendChild(summary);
      const body = el('div', 'engineering-secondary-body');
      body.append(
        this.createReferenceCatalogSection(overview),
        this.createShipProfileCard(),
        this.createSourceGatesSection(overview),
        this.createProofSection(),
      );
      details.appendChild(body);
      return details;
    }

    /* Blueprints & Engineers workstation (Milestone 01). It presents the same
       overview data: observed recipes, the optional reference catalogue, saved
       builds and the Commander's manual readiness records. */
    createEngineersMode(overview) {
      const workspace = createEngineeringBlueprints(this, overview);
      workspace.id = 'engineering-engineers';
      return workspace;
    }

    /* Public hook so other surfaces (e.g. a planned module in Outfitting) can open
       a blueprint's inspector without knowing the workstation's internals. */
    openBlueprint(blueprintId, options = {}) {
      const workspace = this.root?.querySelector('.blueprints-workspace');
      const opened = workspace?.api?.goToBlueprint(String(blueprintId).toLowerCase(), options) === true;
      if (!opened) return false;
      /* Opened from a planned module in Outfitting: remember which ship, build
         and slot, so the Commander can return to exactly that context from any
         other stage. */
      if (options.returnTo) {
        this._outfittingReturn = {
          ...options.returnTo,
          buildId: this._selectedBuildId ?? null,
          observationId: this._selectedObservationId ?? null,
          observedWorkbench: this._observedWorkbench ?? null,
        };
      }
      this._setStage('engineers');
      return true;
    }

    createOutfittingReturn() {
      const bar = el('div', 'engineering-outfitting-return');
      bar.setAttribute('role', 'region');
      bar.setAttribute('aria-label', 'Return to Outfitting');
      const context = this._outfittingReturn;
      if (!context) {
        bar.hidden = true;
        return bar;
      }
      const back = el('button', 'ocv-btn-ghost engineering-action cmd-btn cmd-btn--quiet', 'Back to Outfitting');
      back.type = 'button';
      back.name = 'back_to_outfitting';
      back.addEventListener('click', () => this.returnToOutfitting());
      bar.append(
        el('p', 'engineering-outfitting-return-context',
          `Planning ${[context.buildTitle, context.slotLabel].filter(Boolean).join(' · ')}`),
        back,
      );
      return bar;
    }

    /* Back to the ship, build and module the blueprint was opened from. When
       nothing else changed the selection, Outfitting is simply shown again with
       its unsaved draft intact; otherwise that selection is restored first. */
    returnToOutfitting() {
      const context = this._outfittingReturn;
      if (!context) {
        this._setStage('builds');
        return;
      }
      const changed = (this._selectedBuildId ?? null) !== context.buildId
        || (this._selectedObservationId ?? null) !== context.observationId
        || (this._observedWorkbench ?? null) !== context.observedWorkbench;
      if (changed) {
        this._selectedBuildId = context.buildId;
        this._selectedObservationId = context.observationId;
        this._observedWorkbench = context.observedWorkbench;
        this._activeStage = 'builds';
        this.render(this.overview);
      } else {
        this._setStage('builds');
      }
      const row = this.root?.querySelector(
        `.engineering-module-button[data-slot="${CSS.escape(context.slot)}"]`,
      );
      if (row) {
        if (row.getAttribute('aria-pressed') !== 'true') row.click();
        row.focus({ preventScroll: false });
      }
    }

    createTechnologyMode(overview) {
      const section = this.createSection('engineering-technology', 'Technology / Special Acquisition', 'Offline reference');
      section.appendChild(createTechnologyPlanner(this));
      /* Commander-entered records for unlocks the knowledge snapshot does not
         cover yet (other Guardian tech, suits, special modules). */
      const manual = el('details', 'engineering-secondary tech-manual-records');
      manual.appendChild(el('summary', 'engineering-secondary-summary', 'Other special unlocks (your own records)'));
      const readiness = overview.readiness || {};
      const items = [...(readiness.guardian_tech || []), ...(readiness.suit_engineering || [])];
      if (!items.length) manual.appendChild(emptyState('No local special-acquisition records yet.'));
      items.forEach((item) => manual.appendChild(this.createReadinessItem(item)));
      manual.appendChild(this.createReadinessForm());
      section.appendChild(manual);
      return section;
    }

    /* Load the selected unlock's plan. The selection survives re-renders and
       route changes on this controller, and across launches via local storage. */
    async fetchTechnologyPlan(catalog = this.knowledge?.catalog, catalogError = null) {
      const state = this._technologyState;
      const unlocks = catalog?.state === 'available' ? catalog.unlocks || [] : [];
      if (!unlocks.some((unlock) => unlock.id === state.unlockId)) {
        const remembered = rememberedUnlock();
        state.unlockId = unlocks.some((unlock) => unlock.id === remembered) ? remembered : unlocks[0]?.id || null;
      }
      let plan = null;
      let error = catalogError || null;
      const planPath = () => {
        const query = new URLSearchParams();
        if (state.quantity > 1) query.set('quantity', String(state.quantity));
        if (state.recipe) query.set('recipe', state.recipe);
        const suffix = query.toString() ? `?${query}` : '';
        return `/knowledge/unlocks/${encodeURIComponent(state.unlockId)}/plan${suffix}`;
      };
      if (state.unlockId) {
        try {
          plan = await this.fetchJson(planPath());
          // A tracked per-item purchase or recipe choice comes back as it was saved.
          const saved = plan?.tracking?.target_reference || {};
          if (state.quantity == null && state.recipe == null
            && ((saved.quantity || 1) !== (plan.quantity || 1) || (saved.recipe && saved.recipe !== plan.recipe))) {
            state.quantity = saved.quantity || 1;
            state.recipe = saved.recipe || null;
            plan = await this.fetchJson(planPath());
          }
        } catch (planError) {
          error = planError;
        }
      }
      this.knowledge = { catalog: catalog || null, plan, error };
    }

    async loadTechnologyPlan() {
      this.knowledge = { ...(this.knowledge || {}), plan: null, error: null };
      this.rerenderTechnology();
      await this.fetchTechnologyPlan();
      this.rerenderTechnology();
    }

    /* Pick a catalogue entry. Quantity and recipe belong to one entry, so they
       reset; the choice is remembered for the next launch. */
    async selectTechnology(unlockId) {
      const state = this._technologyState;
      if (state.unlockId === unlockId && this.knowledge?.plan) return;
      Object.assign(state, { unlockId, selected: null, quantity: null, recipe: null });
      rememberUnlock(unlockId);
      await this.loadTechnologyPlan();
      this.root?.querySelector(`.tech-variant[data-unlock-id="${CSS.escape(unlockId)}"]`)?.focus();
    }

    async setTechnologyOptions({ quantity, recipe } = {}) {
      const state = this._technologyState;
      if (quantity !== undefined) state.quantity = quantity;
      if (recipe !== undefined) state.recipe = recipe;
      await this.loadTechnologyPlan();
    }

    rerenderTechnology() {
      this.root?.querySelector('.tech-planner')?.replaceWith(createTechnologyPlanner(this));
    }

    async trackTechnologyUnlock(plan) {
      try {
        await this.fetchJson('/engineering/goal', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            title: plan.transaction === 'per_item_purchase'
              ? `Buy ${plan.quantity} × ${plan.module?.name || plan.unlock.name}`
              : `Unlock ${plan.module?.name || plan.unlock.name}`,
            description: 'Tracked from the Guardian technology workstation.',
            target_kind: 'guardian_tech',
            /* The exact catalogue entry (size, mount, purchase type) is the key, so
               each variant keeps its own goal and checklist. */
            target_reference: {
              knowledge_unlock_id: plan.unlock.id,
              knowledge_pack: plan.pack?.pack_id,
              transaction: plan.transaction,
              quantity: plan.quantity || 1,
              recipe: plan.recipe || null,
              checklist: {},
            },
            state: 'active',
            priority: 'normal',
          }),
        });
      } catch (_error) {
        return false;
      }
      await this.fetchAndRender();
      this.root?.querySelector('.tech-tracking .tech-badge')?.scrollIntoView?.({ block: 'nearest' });
      return true;
    }

    /* A checklist tick is Commander-entered progress on the tracked goal. It is
       saved in place and never re-reads or alters observed inventory. */
    async saveTechnologyChecklist(plan, itemId, checked) {
      const tracking = plan?.tracking;
      if (!tracking) return false;
      const checklist = { ...(tracking.checklist || {}), [itemId]: checked };
      const reference = { ...(tracking.target_reference || {}), checklist };
      try {
        await this.fetchJson(`/engineering/goals/${encodeURIComponent(tracking.goal_id)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ target_reference: reference }),
        });
      } catch (_error) {
        return false;
      }
      tracking.checklist = checklist;
      tracking.target_reference = reference;
      return true;
    }

    /* Open a related Engineering workspace from the planner and offer a way
       back to the same unlock and requirement. */
    openFromTechnology(target, options = {}) {
      const plan = this.knowledge?.plan;
      this._technologyReturn = {
        unlockName: plan?.module?.name || plan?.unlock?.name || 'Technology unlock',
        selected: this._technologyState.selected,
        label: options.label || '',
      };
      if (target === 'builds') {
        this._setStage('builds');
        return;
      }
      const materials = this._materialsState ||= { search: '', category: 'all', availability: 'all', selected: null };
      const observed = (this.overview?.progression?.inventory?.materials || [])
        .some((row) => row.material_id === options.materialId);
      Object.assign(materials, { category: 'all', availability: 'all', detail: true, inventorySelectedByUser: true });
      if (target === 'trader') {
        const known = (this.overview?.progression?.material_trader?.materials || [])
          .find((row) => row.id === options.materialId);
        materials.trader ||= { type: 'raw', search: '', filter: 'all', take: null, give: null, pick: 'take', mode: 'receive', amount: 1, basket: [] };
        if (known) Object.assign(materials.trader, { type: known.type, take: known.id, give: null, pick: 'take' });
        materials.perspective = 'trader';
      } else {
        materials.perspective = 'inventory';
        materials.selected = options.materialId;
        // Not in the observed list: search for it so Materials shows that
        // plainly instead of selecting some other material.
        materials.search = observed ? '' : options.label || '';
      }
      this._activeStage = 'materials';
      this.render(this.overview);
      const focusTarget = target === 'trader'
        ? this.root?.querySelector('#materials-tab-trader')
        : this.root?.querySelector('#materials-inspector h3') || this.root?.querySelector('[name=material_search]');
      focusTarget?.focus?.({ preventScroll: false });
    }

    createTechnologyReturn() {
      const bar = el('div', 'engineering-technology-return');
      bar.setAttribute('role', 'region');
      bar.setAttribute('aria-label', 'Return to technology planner');
      const context = this._technologyReturn;
      if (!context || this._activeStage === 'technology') {
        bar.hidden = true;
        return bar;
      }
      const back = el('button', 'ocv-btn-ghost engineering-action cmd-btn cmd-btn--quiet', 'Back to Guardian planner');
      back.type = 'button';
      back.name = 'back_to_technology';
      back.addEventListener('click', () => this.returnToTechnology());
      bar.append(
        el('p', 'engineering-technology-return-context',
          `Planning ${[context.unlockName, context.label].filter(Boolean).join(' · ')}`),
        back,
      );
      return bar;
    }

    returnToTechnology() {
      const selected = this._technologyReturn?.selected;
      if (selected) this._technologyState.selected = selected;
      this._setStage('technology');
      this.rerenderTechnology();
      const row = this.root?.querySelector(`.tech-requirement[data-entity-id="${CSS.escape(selected || '')}"]`);
      (row || this.root?.querySelector('#tech-unlock-title'))?.focus();
    }

    /* PB-UIV3-HARMONY §4·5 — Current Engineering Focus / readiness lead card.
       Goal-oriented, material-gap-oriented, task-oriented: it names the active
       focus, summarizes local planning counts, and gives ONE state-backed next
       action (the single command-orange element on the route). All values are
       local counts — no invented inventory or readiness percentage. */
    createFocusCard(overview) {
      const counts = overview.counts || {};
      const goals = Array.isArray(overview.goals) ? overview.goals : [];
      const buildPlans = Array.isArray(overview.build_plans) ? overview.build_plans : [];
      const gaps = Array.isArray(overview.material_gaps) ? overview.material_gaps : [];
      const acquisitions = Array.isArray(overview.acquisition_plans) ? overview.acquisition_plans : [];

      const activeGoals = counts.active_goals ?? goals.filter((g) => g.state === 'active').length;
      const buildCount = counts.build_plans ?? buildPlans.length;
      const gapCount = counts.material_gap_rows ?? counts.material_gaps ?? gaps.length;
      const acqCount = counts.acquisition_plans ?? counts.pending_acquisition_plans ?? acquisitions.length;
      const leadGoal = goals.find((g) => g.state === 'active') || goals[0] || null;

      const card = el('section', 'engineering-focus-card');
      card.setAttribute('aria-label', 'Current engineering focus');
      card.append(
        el('p', 'engineering-focus-eyebrow', 'Current plan'),
        el('h2', 'engineering-focus-title', leadGoal ? safeText(leadGoal.title, 'Active goal') : 'No saved build selected'),
      );

      const sub = el('p', 'engineering-focus-sub');
      sub.textContent = leadGoal
        ? `${safeText(leadGoal.target_kind, 'Commander defined')} · ${safeText(leadGoal.priority, 'normal')} priority`
        : 'Plan this ship to compare upgrades, materials, and blockers.';
      card.appendChild(sub);

      /* Local planning metric strip. */
      if ([activeGoals, buildCount, gapCount, acqCount].some((count) => Number(count) > 0)) {
        const metrics = el('div', 'engineering-focus-metrics');
        metrics.append(
          this.createSummaryMetric('Active goals', activeGoals),
          this.createSummaryMetric('Build plans', buildCount),
          this.createSummaryMetric('Material gaps', gapCount),
          this.createSummaryMetric('Acquisitions', acqCount),
        );
        card.appendChild(metrics);
      }

      /* One state-backed next action. */
      let action;
      if (activeGoals === 0) {
        action = { label: 'Plan this ship', stage: 'builds',
          hint: 'Choose a fitted module, then add a blueprint and grade.' };
      } else if (buildCount === 0) {
        action = { label: 'Plan this ship', stage: 'builds',
          hint: `Capture the target recipe for ${leadGoal ? safeText(leadGoal.title, 'this goal') : 'this goal'}.` };
      } else if (gapCount === 0) {
        action = { label: 'Track a material gap', stage: 'materials',
          hint: 'Add the materials this build needs to measure readiness.' };
      } else {
        action = { label: `Work ${gapCount} material gap${gapCount === 1 ? '' : 's'}`, stage: 'materials',
          hint: 'Drive the gap board and acquisition plans toward readiness.' };
      }

      const banner = el('div', 'engineering-next-action');
      banner.append(el('p', 'engineering-next-action-kicker', 'Next action'));
      const btn = el('button', 'engineering-next-action-btn cmd-btn cmd-btn--primary', action.label);
      btn.type = 'button';
      btn.addEventListener('click', () => this._setStage(action.stage));
      banner.appendChild(btn);
      banner.appendChild(el('p', 'engineering-next-action-hint', action.hint));
      card.appendChild(banner);

      const inventoryState = overview.progression?.inventory?.state;
      card.appendChild(el('p', 'engineering-focus-note', inventoryState === 'verified_local'
        ? 'Materials on hand were updated from your Journal.'
        : 'Materials on hand have not been checked. Missing values are not treated as zero.'));
      return card;
    }

    createPlanningGuideDisclosure() {
      const details = el('details', 'engineering-guide-disclosure');
      details.appendChild(el('summary', 'engineering-guide-summary', 'How this works'));
      details.appendChild(this.createPlanningGuide());
      return details;
    }

    createPlanningGuide() {
      const guide = el('section', 'engineering-guide');
      guide.setAttribute('aria-labelledby', 'engineering-guide-title');
      guide.append(
        el('p', 'engineering-kicker', 'Ship engineering workflow'),
        el('h2', 'engineering-guide-title', 'Turn an observed ship into an actionable build plan'),
        el('p', 'engineering-guide-copy', 'The workbench uses only local Loadout and Journal evidence. Unsupported catalogue facts, recipes, compatibility, and unlock requirements stay explicit instead of being guessed.'),
      );
      guide.querySelector('.engineering-guide-title').id = 'engineering-guide-title';

      const steps = el('ol', 'engineering-guide-steps');
      [
        ['1', 'Choose fitted modules', 'Start from the current ship and slots observed in the local Loadout.'],
        ['2', 'Set engineering targets', 'Select locally observed blueprints, grades, and optional experimental effects.'],
        ['3', 'Act on the material plan', 'Review shared reservations, shortages, unknowns, and hand remaining acquisition needs onward.'],
      ].forEach(([number, title, copy]) => {
        const item = el('li', 'engineering-guide-step');
        item.append(
          el('span', 'engineering-guide-number', number),
          el('strong', 'engineering-guide-step-title', title),
          el('span', 'engineering-guide-step-copy', copy),
        );
        steps.appendChild(item);
      });
      guide.appendChild(steps);
      return guide;
    }

    /* PB-UIV3-HARMONY §4·5: guided-planning stage control. The planning surface
       reads as staged work (Goals -> Plans -> Materials), not a flat form stack.
       Cyan/neutral navigation grammar (§5), consistent with the other route
       tab strips; command-orange stays on actions. */
    createStageNav() {
      const nav = el('nav', 'engineering-stage-nav route-subnav');
      nav.setAttribute('role', 'tablist');
      nav.setAttribute('aria-label', 'Engineering planning stages');
      const STAGES = [
        { id: 'builds', label: 'Outfitting' },
        { id: 'materials', label: 'Materials' },
        { id: 'engineers', label: 'Blueprints & Engineers' },
        { id: 'technology', label: 'Special unlocks' },
      ];
      const active = this._activeStage || 'builds';
      STAGES.forEach((stage) => {
        const tab = el('button', 'engineering-stage-tab', stage.label);
        tab.setAttribute('type', 'button');
        tab.setAttribute('role', 'tab');
        tab.setAttribute('data-stage', stage.id);
        tab.id = `engineering-stage-tab-${stage.id}`;
        tab.setAttribute('aria-controls', `engineering-stage-${stage.id}`);
        nav.appendChild(tab);
      });
      window.Uiv3Frame.bindUiv3TabList(nav, {
        selector: '.engineering-stage-tab',
        valueAttribute: 'data-stage',
        activeValue: active,
        onActivate: (stageId) => this._setStage(stageId),
      });
      return nav;
    }

    /* Switch the visible workspace: show the selected stage panel, hide the
       others, and move the active indicator. This is a real workspace swap
       (not an anchor scroll), so domain selection changes what the route
       shows — the Commander-required behavior. */
    _setStage(stageId) {
      this._activeStage = stageId;
      // Back in Outfitting by any route: the return offer has done its job.
      if (stageId === 'builds') this._outfittingReturn = null;
      if (stageId === 'technology') this._technologyReturn = null;
      if (!this.root) return;
      this.root.querySelector('.engineering-outfitting-return')
        ?.replaceWith(this.createOutfittingReturn());
      this.root.querySelector('.engineering-technology-return')
        ?.replaceWith(this.createTechnologyReturn());
      const panels = this.root.querySelectorAll('.engineering-stage-panel');
      panels.forEach((panel) => {
        const match = panel.getAttribute('data-stage-panel') === stageId;
        panel.hidden = !match;
        panel.classList.toggle('is-active', match);
      });
      const nav = this.root.querySelector('.engineering-stage-nav');
      window.Uiv3Frame.setUiv3TabSelection(nav, stageId, {
        selector: '.engineering-stage-tab',
        valueAttribute: 'data-stage',
      });
    }

    createHeader(overview) {
      const header = el('header', 'engineering-header');
      const copy = el('div', 'engineering-header-copy');
      const title = el('h1', 'engineering-title', 'Engineering');
      title.id = 'engineering-title';
      copy.append(title);

      header.append(copy);
      return header;
    }

    createSummaryMetric(label, value) {
      const metric = el('div', 'engineering-metric');
      metric.append(el('span', 'engineering-metric-label', label));
      const display = safeText(value, '0');
      const valueNode = el('strong', 'engineering-metric-value', display);
      /* A zero/empty count should read as honest "none" — dim it so populated
         counts stand out and the empty planning state does not look broken
         (PB-UIV3-HARMONY Engineering guided-planning direction). */
      if (!display || display === '0' || Number(value) === 0) {
        valueNode.classList.add('is-zero');
      }
      metric.append(valueNode);
      return metric;
    }

    createSection(id, title, statusText = '') {
      const section = el('section', 'engineering-section');
      section.id = id;
      const header = el('div', 'engineering-section-header');
      header.append(el('h2', 'engineering-section-title', title));
      if (statusText) header.append(badge(statusText, 'muted'));
      section.appendChild(header);
      return section;
    }

    createGoalsSection(overview) {
      const section = this.createSection('engineering-goals', 'Goals', 'Manual');
      section.appendChild(this.createGoalForm());
      const list = el('div', 'engineering-list');
      const goals = Array.isArray(overview.goals) ? overview.goals : [];
      if (goals.length === 0) {
        list.appendChild(emptyState('Define an engineering goal — name the module, unlock, or progression outcome you want to track.'));
      } else {
        goals.forEach((goal) => list.appendChild(this.createGoalCard(goal)));
      }
      section.appendChild(list);
      return section;
    }

    createGoalForm() {
      const form = el('form', 'engineering-form engineering-form--goal');
      form.append(
        labeledInput('Goal', textInput('title', 'Goal title', { required: true })),
        labeledInput('Target', selectInput('target_kind', GOAL_KIND_OPTIONS, 'module_engineering')),
        labeledInput('Priority', selectInput('priority', PRIORITY_OPTIONS, 'normal')),
        labeledInput('Notes', textArea('notes', 'Commander note')),
      );
      const actions = el('div', 'engineering-form-actions');
      const submit = el('button', 'ocv-btn engineering-action cmd-btn cmd-btn--secondary', 'Add goal');
      submit.type = 'submit';
      actions.appendChild(submit);
      form.appendChild(actions);
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const payload = {
          title: formValue(form, 'title'),
          target_kind: formValue(form, 'target_kind') || 'commander_defined_other',
          priority: formValue(form, 'priority') || 'normal',
          state: 'active',
        };
        appendIfPresent(payload, 'notes', formValue(form, 'notes'));
        await this.handleAction(() => this.postJson('/engineering/goal', payload));
      });
      return form;
    }

    createGoalCard(goal) {
      const card = el('article', 'engineering-card');
      card.append(
        el('h3', 'engineering-card-title', safeText(goal.title, 'Untitled goal')),
        field('State', safeText(goal.state, 'Not checked')),
        field('Target', safeText(goal.target_kind, 'Commander defined')),
        field('Priority', safeText(goal.priority, 'Unsorted')),
      );
      return card;
    }

    createBuildsSection(overview) {
      const section = this.createSection('engineering-builds', 'Saved builds');
      section.appendChild(this.createBuildForm());
      const list = el('div', 'engineering-list');
      const builds = Array.isArray(overview.build_plans) ? overview.build_plans : [];
      if (builds.length === 0) {
        list.appendChild(emptyState('No saved builds yet. Plan this ship to compare materials and readiness.'));
      } else {
        builds.forEach((build) => list.appendChild(this.createBuildCard(build)));
      }
      section.appendChild(list);
      return section;
    }

    createBuildForm() {
      const form = el('form', 'engineering-form engineering-form--build');
      form.append(
        labeledInput('Plan', textInput('title', 'Build plan title', { required: true })),
        labeledInput('Source', selectInput('source', [
          ['commander_defined', 'Commander defined'],
          ['intel_current_loadout_reference', 'Intel current-loadout reference'],
        ], 'commander_defined')),
        labeledInput('Summary', textArea('summary', 'Target summary')),
      );
      const actions = el('div', 'engineering-form-actions');
      const submit = el('button', 'ocv-btn engineering-action cmd-btn cmd-btn--secondary', 'Add build');
      submit.type = 'submit';
      actions.appendChild(submit);
      form.appendChild(actions);
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const payload = {
          title: formValue(form, 'title'),
          source: formValue(form, 'source') || 'commander_defined',
          target_loadout_summary: {},
        };
        const summary = formValue(form, 'summary');
        if (summary) payload.target_loadout_summary = { commander_summary: summary };
        await this.handleAction(() => this.postJson('/engineering/builds', payload));
      });
      return form;
    }

    createBuildCard(build) {
      const card = el('article', 'engineering-card');
      card.dataset.buildPlanId = build.build_plan_id;
      card.append(
        el('h3', 'engineering-card-title', safeText(build.title, 'Untitled build')),
        field('Source', safeText(build.source, 'commander_defined')),
        field('Format', safeText(build.format_verification_state, 'not_applicable')),
        field('Truth boundary', safeText(build.separation_from_current_loadout, 'Target plan only.')),
      );
      const assessment = this.overview?.progression?.builds?.find((row) => row.build_plan_id === build.build_plan_id);
      if (assessment) {
        (assessment.unknown_inputs || []).forEach((message) => card.appendChild(el('p', 'engineering-card-note', message)));
        const bill = el('ul', 'engineering-saved-materials');
        (assessment.materials || []).forEach((row) => bill.appendChild(el('li', '', `${row.display_name}: required ${row.required}, reserved ${row.reserved ?? 'unknown'}, deficit ${row.deficit ?? 'unknown'}`)));
        card.appendChild(bill);
      }
      return card;
    }

    createMaterialsManualArea(overview) {
      const manual = el('details', 'materials-secondary');
      manual.append(el('summary', '', 'Advanced / manual planning'), this.createMaterialGapsSection(overview));
      const snapshots = el('details', 'materials-secondary');
      snapshots.append(el('summary', '', 'Other inventory snapshots'), this.createInventorySnapshotsSection());
      const area = el('div');
      area.append(manual, snapshots);
      return area;
    }

    createMaterialGapsSection(overview) {
      const section = this.createSection('engineering-materials', 'Material Gaps', 'Planning');
      section.appendChild(this.createMaterialGapForm());
      const postureLine = el('p', 'engineering-source-note');
      postureLine.textContent = 'Manual counts are Commander-entered planning values. Journal inventory is shown above.';
      section.appendChild(postureLine);

      const list = el('div', 'engineering-list');
      const gaps = Array.isArray(overview.material_gaps) ? overview.material_gaps : [];
      if (gaps.length === 0) {
        list.appendChild(emptyState('No material gap selected — add a material to measure readiness.'));
      } else {
        gaps.forEach((gap) => list.appendChild(this.createGapCard(gap)));
      }
      section.appendChild(list);
      return section;
    }

    createMaterialGapForm() {
      const form = el('form', 'engineering-form engineering-form--gap');
      form.append(
        labeledInput('Material', textInput('material_id', 'Material name or id', { required: true })),
        labeledInput('Required', textInput('required_count', 'Required', { type: 'number', min: 0 })),
        labeledInput('Current', textInput('current_count', 'Leave blank if not checked', { type: 'number', min: 0 })),
      );
      const actions = el('div', 'engineering-form-actions');
      const submit = el('button', 'ocv-btn engineering-action cmd-btn cmd-btn--secondary', 'Compute gap');
      submit.type = 'submit';
      actions.appendChild(submit);
      form.appendChild(actions);
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const payload = {
          material_id: formValue(form, 'material_id'),
          material_display_name: formValue(form, 'material_id'),
        };
        const required = optionalNumber(form, 'required_count');
        const current = optionalNumber(form, 'current_count');
        if (required !== null) payload.commander_override_required = required;
        if (current !== null) payload.commander_override_current = current;
        await this.handleAction(() => this.postJson('/engineering/material-overrides', payload));
      });
      return form;
    }

    createGapCard(gap) {
      const card = el('article', 'engineering-card engineering-gap-card');
      card.append(el('h3', 'engineering-card-title', safeText(gap.material_display_name, 'Material')));

      /* Readiness progress (§4·5 "material gaps with progress") — honest: a bar
         only when both required and current counts are real numbers. When the
         current inventory is unknown (no verified source) the card states that
         plainly instead of drawing a fake progress bar. */
      const required = gap.required_count == null ? NaN : Number(gap.required_count);
      const current = gap.current_count == null ? NaN : Number(gap.current_count);
      const hasProgress = Number.isFinite(required) && required > 0 && Number.isFinite(current);
      if (hasProgress) {
        const pct = Math.max(0, Math.min(100, Math.round((current / required) * 100)));
        const track = el('div', 'engineering-gap-progress');
        track.setAttribute('role', 'progressbar');
        track.setAttribute('aria-valuemin', '0');
        track.setAttribute('aria-valuemax', String(required));
        track.setAttribute('aria-valuenow', String(Math.min(current, required)));
        const fill = el('span', 'engineering-gap-progress-fill');
        fill.style.width = `${pct}%`;
        if (pct >= 100) fill.classList.add('is-ready');
        track.appendChild(fill);
        card.appendChild(track);
        card.appendChild(el('p', 'engineering-gap-progress-label', `${current} / ${required} held · ${pct}% ready`));
      } else {
        card.appendChild(el('p', 'engineering-gap-progress-label engineering-gap-progress-label--unknown',
          'Inventory not verified — enter the current count to measure readiness.'));
      }

      card.append(
        field('Required', safeText(gap.required_count, 'Unsupported')),
        field('Current', safeText(gap.current_count, 'Not checked')),
        field('Gap', safeText(gap.gap, 'Not known yet')),
        field('State', safeText(gap.state, 'Not checked')),
        el('p', 'engineering-card-note', safeText(gap.fallback, 'Material count not known.')),
      );
      return card;
    }

    /* Local inventory snapshots (LNA-032 surfacing). Backpack.json /
       ShipLocker.json / FCMaterials.json are write-triggered local screen
       snapshots — never continuous live inventory, and a missing file is
       never proof of empty inventory. Entries render verbatim from the
       local file via textContent only (ADR 0003 Tier 1). */
    createInventorySnapshotsSection() {
      const section = this.createSection(
        'engineering-inventory', 'Inventory Snapshots', 'Local snapshots',
      );
      section.appendChild(el(
        'p', 'engineering-source-note',
        'Write-triggered local snapshots from Backpack.json, ShipLocker.json, '
        + 'and FCMaterials.json. Missing files are not proof of empty inventory.',
      ));
      const grid = el('div', 'engineering-inventory-grid');
      const ctx = this.localContext;
      grid.append(
        this.createOdysseyInventoryCard('Odyssey Backpack', ctx?.backpack_snapshot),
        this.createOdysseyInventoryCard('Ship Locker', ctx?.ship_locker_snapshot),
        this.createFcMaterialsCard(ctx?.fc_materials_snapshot),
      );
      section.appendChild(grid);
      return section;
    }

    createInventoryFallbackCard(title, snap, defaultFallback) {
      const card = el('article', 'engineering-card engineering-inventory-card');
      card.appendChild(el('h3', 'engineering-card-title', title));
      card.appendChild(badge(safeText(snap?.fallback, defaultFallback), 'unknown'));
      card.appendChild(el(
        'p', 'engineering-card-note',
        safeText(
          snap?.caveat,
          'No verified local snapshot has been loaded. Missing companion '
          + 'files are not proof of empty inventory.',
        ),
      ));
      return card;
    }

    createOdysseyInventoryCard(title, snap) {
      if (!snap || snap.freshness === 'not_loaded') {
        return this.createInventoryFallbackCard(
          title, snap, 'No verified local snapshot',
        );
      }
      const card = el('article', 'engineering-card engineering-inventory-card');
      card.appendChild(el('h3', 'engineering-card-title', title));
      card.append(
        field('Items', snap.items_count == null ? 'Not checked' : String(snap.items_count)),
        field('Components', snap.components_count == null ? 'Not checked' : String(snap.components_count)),
        field('Consumables', snap.consumables_count == null ? 'Not checked' : String(snap.consumables_count)),
        field('Data', snap.data_count == null ? 'Not checked' : String(snap.data_count)),
        field('Last updated', safeText(snap.observed_at, 'Not checked')),
        field('Freshness', freshnessLabel(snap)),
      );
      card.appendChild(this.createOdysseyEntriesDetail(snap));
      card.appendChild(el('p', 'engineering-card-note', safeText(snap.caveat, 'Snapshot details not available.')));
      return card;
    }

    createOdysseyEntriesDetail(snap) {
      const details = el('details', 'engineering-inventory-entries');
      details.appendChild(el('summary', 'engineering-inventory-entries-summary',
        'Entries (commander-observed)'));
      const categories = [
        ['Items', snap.items],
        ['Components', snap.components],
        ['Consumables', snap.consumables],
        ['Data', snap.data],
      ];
      let any = false;
      categories.forEach(([label, entries]) => {
        if (!Array.isArray(entries) || entries.length === 0) return;
        any = true;
        details.appendChild(el('h4', 'engineering-inventory-category', label));
        details.appendChild(this.createInventoryEntryList(entries, (entry) => {
          const name = safeText(entry?.Name_Localised || entry?.Name, 'Unlabelled item');
          return entry?.Count != null ? `${name} ×${entry.Count}` : name;
        }));
      });
      if (!any) {
        details.appendChild(el('p', 'engineering-card-note',
          'No entries recorded in this local snapshot.'));
      }
      return details;
    }

    createFcMaterialsCard(snap) {
      if (!snap || snap.freshness === 'not_loaded') {
        return this.createInventoryFallbackCard(
          'Carrier Materials Trader', snap, 'No verified local FC materials snapshot',
        );
      }
      const card = el('article', 'engineering-card engineering-inventory-card');
      card.appendChild(el('h3', 'engineering-card-title', 'Carrier Materials Trader'));
      card.append(
        field('Carrier', safeText(snap.carrier_name, 'Carrier not checked')),
        field('Listings', snap.item_count == null ? 'Not checked' : String(snap.item_count)),
        field('Last updated', safeText(snap.observed_at, 'Not checked')),
        field('Freshness', freshnessLabel(snap)),
      );
      const details = el('details', 'engineering-inventory-entries');
      details.appendChild(el('summary', 'engineering-inventory-entries-summary',
        'Listings (commander-observed)'));
      const entries = Array.isArray(snap.items) ? snap.items : [];
      if (entries.length === 0) {
        details.appendChild(el('p', 'engineering-card-note',
          'No listings recorded in this local snapshot.'));
      } else {
        details.appendChild(this.createInventoryEntryList(entries, (entry) => {
          const bits = [safeText(entry?.Name_Localised || entry?.Name, 'Unlabelled item')];
          if (entry?.Stock != null) bits.push(`stock ${entry.Stock}`);
          if (entry?.Price != null) bits.push(`price ${entry.Price}`);
          return bits.join(' · ');
        }));
      }
      card.appendChild(details);
      card.appendChild(el('p', 'engineering-card-note', safeText(snap.caveat, 'Snapshot details not available.')));
      return card;
    }

    createInventoryEntryList(entries, toLabel) {
      const MAX_ROWS = 25;
      const list = el('ul', 'engineering-inventory-list');
      entries.slice(0, MAX_ROWS).forEach((entry) => {
        list.appendChild(el('li', 'engineering-inventory-row', toLabel(entry)));
      });
      if (entries.length > MAX_ROWS) {
        list.appendChild(el('li', 'engineering-inventory-row engineering-inventory-more',
          `+${entries.length - MAX_ROWS} more entries in the local snapshot`));
      }
      return list;
    }

    createAcquisitionSection(overview) {
      const section = this.createSection('engineering-acquisition', 'Acquisition Plans', 'Handoffs');
      section.appendChild(this.createAcquisitionForm());
      const list = el('div', 'engineering-list');
      const plans = Array.isArray(overview.acquisition_plans) ? overview.acquisition_plans : [];
      if (plans.length === 0) {
        list.appendChild(emptyState('No acquisition plan yet — plan where to gather the materials this build needs.'));
      } else {
        plans.forEach((plan) => list.appendChild(this.createAcquisitionCard(plan)));
      }
      section.appendChild(list);
      return section;
    }

    createAcquisitionForm() {
      const form = el('form', 'engineering-form engineering-form--acquisition');
      form.append(
        labeledInput('Plan', textInput('title', 'Acquisition plan title', { required: true })),
        labeledInput('Material', textInput('material_id', 'Material name or id', { required: true })),
        labeledInput('Needed', textInput('quantity_needed', 'Needed', { type: 'number', min: 0 })),
        labeledInput('Notes', textArea('notes', 'Commander note')),
      );
      const actions = el('div', 'engineering-form-actions');
      const submit = el('button', 'ocv-btn engineering-action cmd-btn cmd-btn--secondary', 'Add plan');
      submit.type = 'submit';
      actions.appendChild(submit);
      form.appendChild(actions);
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const materialId = formValue(form, 'material_id');
        const material = {
          material_id: materialId,
          display_name: materialId,
        };
        const qty = optionalNumber(form, 'quantity_needed');
        if (qty !== null) material.quantity_needed = qty;
        const payload = {
          title: formValue(form, 'title'),
          target_materials: [material],
        };
        appendIfPresent(payload, 'notes', formValue(form, 'notes'));
        await this.handleAction(() => this.postJson('/engineering/acquisition-plan', payload));
      });
      return form;
    }

    createAcquisitionCard(plan) {
      const card = el('article', 'engineering-card engineering-acquisition-card');
      card.id = `acquisition_plan:${plan.acquisition_plan_id}`;
      card.append(
        el('h3', 'engineering-card-title', safeText(plan.title, 'Acquisition plan')),
        field('State', safeText(plan.state, 'draft')),
        field('Materials', String(Array.isArray(plan.target_materials) ? plan.target_materials.length : 0)),
      );

      const materials = el('ul', 'engineering-mini-list');
      (Array.isArray(plan.target_materials) ? plan.target_materials : []).forEach((material) => {
        const item = el('li', '', `${safeText(material.display_name || material.material_id, 'Material')} - ${safeText(material.quantity_needed, 'Quantity not known')}`);
        materials.appendChild(item);
      });
      card.appendChild(materials);

      const actions = el('div', 'engineering-card-actions');
      const nav = el('button', 'ocv-btn engineering-action cmd-btn cmd-btn--quiet', 'Send to Navigation');
      nav.type = 'button';
      nav.addEventListener('click', () => this.sendHandoff(plan.acquisition_plan_id, 'navigation'));
      const ops = el('button', 'ocv-btn-ghost engineering-action cmd-btn cmd-btn--quiet', 'Send to Operations');
      ops.type = 'button';
      ops.addEventListener('click', () => this.sendHandoff(plan.acquisition_plan_id, 'operations'));
      actions.append(nav, ops);
      card.appendChild(actions);
      return card;
    }

    createReadinessSection(overview) {
      const section = this.createSection('engineering-readiness', 'Readiness', 'Manual');
      section.appendChild(this.createReadinessForm());
      const readiness = overview.readiness || {};
      const groups = [
        ['Blueprints', readiness.blueprints || []],
        ['Engineers', readiness.engineers || []],
        ['Guardian tech', readiness.guardian_tech || []],
        ['Suit engineering', readiness.suit_engineering || []],
      ];
      groups.forEach(([label, items]) => {
        const group = el('div', 'engineering-readiness-group');
        group.append(el('h3', 'engineering-subsection-title', label));
        if (!items.length) {
          group.appendChild(emptyState('No local records.'));
        } else {
          items.slice(0, 4).forEach((item) => group.appendChild(this.createReadinessItem(item)));
        }
        section.appendChild(group);
      });
      return section;
    }

    createReadinessForm() {
      const form = el('form', 'engineering-form engineering-form--readiness');
      form.append(
        labeledInput('Type', selectInput('readiness_type', READINESS_OPTIONS, 'blueprint')),
        labeledInput('Label', textInput('label', 'Commander-entered label', { required: true })),
        labeledInput('State', textInput('state', 'State')),
        labeledInput('Requirements', textArea('requirements_text', 'Commander-entered requirements')),
      );
      const actions = el('div', 'engineering-form-actions');
      const submit = el('button', 'ocv-btn engineering-action cmd-btn cmd-btn--secondary', 'Add readiness');
      submit.type = 'submit';
      actions.appendChild(submit);
      form.appendChild(actions);
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        await this.submitReadiness(form);
      });
      return form;
    }

    async submitReadiness(form) {
      const type = formValue(form, 'readiness_type') || 'blueprint_progress';
      const label = formValue(form, 'label');
      const state = formValue(form, 'state');
      const requirementsText = formValue(form, 'requirements_text');
      const path = '/engineering/readiness-states';
      const payload = { kind: type, label };

      if (state) payload.state = state;
      if (requirementsText) {
        payload.requirements_known = 'manual';
        payload.requirements_text = requirementsText;
      }
      await this.handleAction(() => this.postJson(path, payload));
    }

    createReadinessItem(item) {
      const node = el('article', 'engineering-readiness-item');
      const label = item.blueprint_label
        || item.engineer_label
        || item.guardian_tech_label
        || item.suit_engineering_label
        || 'Readiness item';
      node.append(
        el('h4', 'engineering-readiness-title', label),
        field('State', safeText(item.state, 'unknown')),
      );
      if (item.requirements_known) {
        node.appendChild(field('Requirements', safeText(item.requirements_known, 'unknown')));
      }
      return node;
    }

    createSourceGatesSection(overview) {
      const section = this.createSection('engineering-source-gates', 'Connection details', 'Off');
      const posture = overview.source_posture || {};
      section.append(
        this.createGateLine('CAPI', posture.capi_material_inventory || 'Source-gated'),
        this.createGateLine('EDSY', posture.edsy || 'Format unverified'),
        this.createGateLine('Coriolis', posture.coriolis || 'Format unverified'),
        this.createGateLine('Ardent', posture.ardent || 'Off'),
      );
      const why = el('details', 'engineering-source-why');
      why.append(
        el('summary', 'engineering-source-why-summary', 'Why?'),
        el('p', 'engineering-source-why-copy',
          'Imports remain disabled until an approved source workflow exists; blocked attempts are recorded locally.'),
      );
      section.appendChild(why);

      const actions = el('div', 'engineering-gate-actions');
      [
        ['CAPI inventory', '/engineering/source-attempts/capi'],
        ['EDSY import', '/engineering/import-sources/edsy/attempt-import'],
        ['EDSY export', '/engineering/import-sources/edsy/attempt-export'],
        ['Coriolis import', '/engineering/import-sources/coriolis/attempt-import'],
        ['Coriolis export', '/engineering/import-sources/coriolis/attempt-export'],
        ['Ardent material truth', '/engineering/source-attempts/ardent'],
      ].forEach(([label, path]) => {
        const button = el('button', 'ocv-btn-ghost engineering-action cmd-btn cmd-btn--quiet', label);
        button.type = 'button';
        button.addEventListener('click', () => this.recordBlockedAttempt(path));
        actions.appendChild(button);
      });
      section.appendChild(actions);
      this.statusNode = el('p', 'engineering-action-status');
      section.appendChild(this.statusNode);
      return section;
    }

    createGateLine(label, state) {
      const line = el('div', 'engineering-gate-line');
      line.append(el('span', 'engineering-gate-label', label), badge(state, 'off'));
      return line;
    }

    createProofSection() {
      const section = this.createSection('engineering-proof', 'Proof', 'Activity Log');
      const button = el('button', 'ocv-btn-ghost engineering-action cmd-btn cmd-btn--quiet', 'View in Log');
      button.type = 'button';
      button.addEventListener('click', () => {
        const intent = window.Shell?.createRouteTransferIntent?.({
          originRoute: '/engineering',
          originPackage: 'engineering',
          originSectionId: 'engineering-proof',
          targetRoute: '/activity-log',
          targetSectionId: 'log-section-sources',
          targetLabel: 'Engineering proof records',
          reason: 'Inspect Engineering source-chain and blocked-source records.',
          returnLabel: 'Back to Engineering',
          returnTarget: { route: '/engineering', sectionId: 'engineering-proof' },
        });
        if (intent && window.Shell?.startRouteTransfer) {
          window.Shell.startRouteTransfer(intent);
        } else {
          window.location.hash = '#/activity-log';
        }
      });
      section.append(
        emptyState('Engineering proof records are written to the local Activity Log.'),
        button,
      );
      return section;
    }

    async sendHandoff(acquisitionPlanId, target) {
      const path = `/engineering/acquisition-plans/${encodeURIComponent(acquisitionPlanId)}/handoff/${target}`;
      await this.handleAction(async () => {
        const result = await this.postJson(path, {});
        const intent = result?.route_transfer_intent || result?.route_intent;
        if (intent && window.Shell?.startRouteTransfer) {
          window.Shell.startRouteTransfer(intent);
        }
        return result;
      });
    }

    async recordBlockedAttempt(path) {
      await this.handleAction(() => this.postJson(path, {}), 'Blocked attempt recorded.');
    }

    async handleAction(action, successMessage = 'Saved locally.') {
      try {
        const result = await action();
        this.setStatus(successMessage);
        return result;
      } catch (error) {
        this.setStatus(error?.message || 'Request failed.');
        return null;
      }
    }

    setStatus(message) {
      if (this.statusNode) {
        this.statusNode.textContent = message;
      }
    }

    applyRouteTransferArrival() {
      if (window.Shell?.applyRouteTransferArrival && this.root) {
        window.Shell.applyRouteTransferArrival('/engineering', this.root);
      }
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    new EngineeringController();
  });

  if (typeof globalThis.__engineeringExports === 'undefined') {
    globalThis.__engineeringExports = {
      EngineeringController,
      safeText,
    };
  }
})();
