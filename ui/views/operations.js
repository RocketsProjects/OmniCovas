/**
 * OmniCOVAS Operations — Workspace Surface (UI v3 target rebuild).
 *
 * Authority: authority_files/documents/02_ui_ux_authority/OmniCOVAS_UI_UX_Master_Blueprint_v2_0_Human_Reference.md §9.2, §11
 *
 * PB-UIV3-03: reshapes the Operations workspace into the UI v3 target layout:
 *   compact breadcrumb/hero header → mode selector bar → mode-specific body.
 *
 * Station mode: two-column card layout (Current Station card / right column
 *   with Cargo, Next Actions, Recent Activity cards).
 *
 * Non-station modes: all existing content preserved (watch strip, context
 *   spine, primary action, supports, quick tools, local context, detail,
 *   proof) — wrapped in the new v3 header + mode bar chrome.
 *
 * Operation modes: Mining, Trading, Combat, Exploration, Travel, Station,
 *   Squadron, Idle. No mode defaults to Station unless explicit state says so.
 *
 * Local-first. Reads:
 *   /pillar1/ship-state, /pillar1/cargo, /pillar1/heat, /pillar1/modules/summary
 *   /navigation/snapshot, /combat/snapshot
 *   /intel/local-context/snapshot
 *
 * Safe rendering: createElement + textContent only (ADR 0003).
 * Decision A LOCKED: first tab is Dashboard, never Pilot.
 */

(function () {
  'use strict';

  const STORAGE_KEY = 'omnicovas.manualOperation';
  const HANDOFF_STORAGE_KEY = 'omnicovas.operationHandoff';

  /* Phase 9 workspace modes are session-only. writeManualOperation is never
     called for these modes; they cannot be auto-reopened from storage.

     R8 makes campaigns selectable (`P14-K07`) and deliberately does NOT touch
     this guard. The two are independent: reachability is whether the Commander
     can FIND the workspace; auto-reopen is whether the app decides to open it
     FOR them. R4 ruled it never may, and `readManualOperation` already returns
     null unconditionally, so this is the second of two locks. */
  const PHASE9_SESSION_ONLY_MODES = new Set(['bgs', 'powerplay']);

  const PRIMITIVES_URL = '../components/command-primitives.js';
  const COMMANDER_VM_URL = '../view-models/commander-context.js';
  const WORKSPACE_VM_URL = '../view-models/operations-workspaces.js';
  const LOCAL_CONTEXT_VM_URL = '../view-models/local-context.js';
  const LOCAL_CONTEXT_SURFACES_URL = '../components/local-context-surfaces.js';

  let _primitives = null;
  let _commanderVM = null;
  let _workspaceVM = null;
  let _localContextVM = null;
  let _localSurfaces = null;

  const primitivesPromise = import(PRIMITIVES_URL)
    .then((m) => { _primitives = m; return m; })
    .catch((err) => { console.error('[operations] Failed to load command primitives:', err); return null; });

  const commanderPromise = import(COMMANDER_VM_URL)
    .then((m) => { _commanderVM = m; return m; })
    .catch((err) => { console.error('[operations] Failed to load commander VM:', err); return null; });

  const workspacePromise = import(WORKSPACE_VM_URL)
    .then((m) => { _workspaceVM = m; return m; })
    .catch((err) => { console.error('[operations] Failed to load workspace VM:', err); return null; });

  const localContextPromise = import(LOCAL_CONTEXT_VM_URL)
    .then((m) => { _localContextVM = m; return m; })
    .catch((err) => { console.error('[operations] Failed to load local context VM:', err); return null; });

  const localSurfacesPromise = import(LOCAL_CONTEXT_SURFACES_URL)
    .then((m) => { _localSurfaces = m; return m; })
    .catch((err) => { console.error('[operations] Failed to load local context surfaces:', err); return null; });

  function getRoot() {
    return document.getElementById('operations-root');
  }

  function apiBase() {
    if (window.Shell?.httpBase) return window.Shell.httpBase;
    if (window.OMNICOVAS_PORT) return `http://127.0.0.1:${window.OMNICOVAS_PORT}`;
    return null;
  }

  async function fetchJson(path) {
    const base = apiBase();
    if (!base) return null;
    try {
      const r = await fetch(`${base}${path}`);
      return r.ok ? await r.json() : null;
    } catch {
      return null;
    }
  }

  /* ────── Cross-route handoff proof (R8-9) ──────────────────────────────────────────────────────
   *
   * R6 left `P14-G08` partial because Trade handoffs carried context but left
   * no proof. R7 met the same question and declined to answer it from inside a
   * Combat slice. R8 answers it once, here, for every Operations handoff.
   *
   * ONE function dispatches every purposeful Operations transfer, so the proof
   * cannot drift out of step with the navigation, and no workflow needs its own
   * logging path. Three rules it enforces by construction:
   *
   *   1. proof only follows a SUCCESSFUL dispatch. `startRouteTransfer`
   *      returns null for an unknown target route, and a handoff that did not
   *      happen must not leave a record saying it did;
   *   2. proof is emitted HERE, at dispatch — never on arrival, render,
   *      highlight or refresh, each of which fires many times per decision;
   *   3. ordinary navigation never reaches this function at all. Tab clicks,
   *      mode selection and browser back go through the shell directly, so the
   *      Activity Log cannot become a clickstream.
   *
   * The request carries structured slugs only. `targetLabel`, `reason` and
   * `targetQuery` are deliberately NOT sent: all three are free text in the
   * intent grammar, and one of them (a campaign title) is Commander-authored.
   */
  /* Mirrors `operations_handoff._SLUG` on the server. Slugs, dotted ids and
     route paths; no whitespace, no markup, no punctuation beyond `._/-`. */
  const HANDOFF_ID = /^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$/;

  function dispatchHandoff(intentInput, proof = {}) {
    if (typeof window.Shell?.startRouteTransfer !== 'function') return null;
    const intent = window.Shell.startRouteTransfer(intentInput);
    /* A refused dispatch is not a handoff. No proof, no claim. */
    if (!intent) return null;
    recordHandoffProof(intent, proof);
    return intent;
  }

  /* Fire-and-forget: a Commander who has already navigated must not be blocked
     on a proof write, and a failed write must not undo the navigation they
     asked for. The endpoint is the only thing that can create the event. */
  function recordHandoffProof(intent, proof) {
    const base = apiBase();
    if (!base) return;
    const body = {
      origin_package: String(proof.originPackage || _manualOperation || 'idle'),
      target_route: String(intent.targetRoute || ''),
    };
    const optional = {
      origin_section_id: intent.originSectionId,
      target_section_id: intent.targetSectionId,
      target_entity_id: proof.entityId ?? intent.targetEntityId,
      target_entity_kind: proof.entityKind,
      handoff_kind: proof.kind,
      workflow_id: proof.workflowId,
    };
    Object.entries(optional).forEach(([key, value]) => {
      const text = value === null || value === undefined ? '' : String(value).trim();
      /* The SAME conservative identifier shape the server enforces, applied
         here so unloggable values never leave the browser at all. A
         whitespace-only check was the first version of this and was not
         enough: `<script>alert("x")</script>` has no whitespace. The server
         still re-checks — this is the outer of two identical guards, not a
         replacement for the inner one. */
      if (text && HANDOFF_ID.test(text)) body[key] = text;
    });
    try {
      fetch(`${base}/operations/handoff`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).catch(() => {});
    } catch { /* proof is best-effort; the handoff already happened */ }
  }

  /* Mutating call. Unlike `fetchJson`, a failure is never flattened to null:
     R3's truth lock requires that a write which did not happen is reported as
     a failure, not silently rendered as an unchanged surface. */
  async function postJson(path, body) {
    const base = apiBase();
    if (!base) {
      const err = new Error('No local backend');
      err.commanderMessage = 'The local backend is unavailable. Nothing changed.';
      throw err;
    }
    const r = await fetch(`${base}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    let payload = null;
    try { payload = await r.json(); } catch { payload = null; }
    if (!r.ok) {
      const err = new Error(`HTTP ${r.status}`);
      err.status = r.status;
      err.commanderMessage = typeof payload?.detail === 'string'
        ? payload.detail
        : 'The objective was not changed.';
      throw err;
    }
    return payload;
  }

  /* Smoke R3: Operations default is selector-only. The Commander explicitly
     directed that legacy localStorage values must NOT reopen old operations
     automatically — only an explicit current-session click opens an
     operation. We never read manualOperation back from storage; on init we
     just clear any stale value so prior sessions cannot influence this one. */
  function readManualOperation() {
    try {
      window.localStorage?.removeItem(STORAGE_KEY);
    } catch { /* localStorage unavailable */ }
    return null;
  }

  function writeManualOperation(op) {
    // Phase 9 modes (bgs, powerplay) are session-only: never write to storage.
    if (PHASE9_SESSION_ONLY_MODES.has(op)) return;
    try {
      if (op === null || op === 'idle') window.sessionStorage?.removeItem(STORAGE_KEY);
      else window.sessionStorage?.setItem(STORAGE_KEY, op);
    } catch { /* ignore */ }
  }

  function isHandoffOperation(value) {
    return value !== 'idle'
      && Array.isArray(_commanderVM?.PRIMARY_OPERATIONS)
      && _commanderVM.PRIMARY_OPERATIONS.includes(value);
  }

  /* Consume only explicit current-session route handoffs. This intentionally
     does not revive the old persistent manualOperation value. */
  function consumeInboundOperation() {
    let operation = null;
    const intent = typeof window.Shell?.getRouteTransferIntent === 'function'
      ? window.Shell.getRouteTransferIntent('/operations')
      : null;
    if (isHandoffOperation(intent?.targetEntityId)) {
      operation = intent.targetEntityId;
    }

    if (!operation) {
      try {
        const staged = window.sessionStorage?.getItem(HANDOFF_STORAGE_KEY);
        window.sessionStorage?.removeItem(HANDOFF_STORAGE_KEY);
        if (isHandoffOperation(staged)) operation = staged;
      } catch { /* sessionStorage unavailable; selector remains available */ }
    }

    if (operation) {
      _manualOperation = operation;
      writeManualOperation(operation);
    }
    return operation;
  }

  const inputs = {
    state: null,
    heat: null,
    cargo: null,
    mods: null,
    navSnap: null,
    combat: null,
    localContext: null,
    localContextRaw: null,
    activityLog: null,
    /* Mode-specific inputs. `readiness` and `explorationSnapshot` are answers
       to a question about ONE operation, so they are invalidated the moment the
       Commander selects another and re-read for the new one (R1-1). The two
       pending flags exist so the surfaces can say "not resolved yet" instead of
       "the service did not answer" while a read is in flight. */
    readiness: null,
    readinessPending: false,
    explorationSnapshot: null,
    explorationPending: false,
    /* R6: the Trade and Mining workflows. Deliberately two inputs rather than
       one "economy" input — they read the same cargo and market but answer
       different questions, and a mode switch is a workflow switch. */
    tradeWorkflow: null,
    tradePending: false,
    miningWorkflow: null,
    miningPending: false,
    /* R7: the Combat workflow. Mode-specific for the same reason the economic
       ones are — it answers a question about Combat, and a mode switch must
       not leave the previous mode's answer on screen. */
    combatWorkflow: null,
    combatPending: false,
    /* R8 (`P14-J01`): Engineering's acquisition plans. Read, never owned —
       Engineering keeps the plan, the material gaps and the build detail; the
       payload's own `ownership` block says `active_task: operations`, and this
       input is how Operations honours that half. */
    engineeringPlans: null,
    /* PB14-R1 (R3): the persisted Commander objective for the selected mode.
       Mode-specific for the same reason readiness is — one mode's stated
       intent is not another's — so it follows the identical invalidate,
       re-read and discard-stale contract. */
    commanderObjective: null,
    commanderObjectivePending: false,
    /* Every mode's current objective, for the default surface only. */
    objectivesIndex: null,
    /* P14-D05: role fit from the one readiness service. Deliberately NOT
       mode-scoped — what is bolted to the ship does not depend on which
       workspace is open — so it is read with the rest of the shared state and
       is not invalidated on mode change. */
    shipProfile: null,
    sessionState: null,
  };

  let _manualOperation = readManualOperation();

  /* PB14-R1 (R3) objective editor state. Session-scoped view state only — the
     objective itself lives in the local database, and nothing here is ever
     treated as the objective. `_objectiveStatus` exists so a refused or failed
     write is visible on the surface that asked for it, rather than only in a
     transient toast: R3's truth lock requires the Commander to be told the
     objective did not change. */
  let _objectiveEditor = null;
  let _objectiveStatus = null;
  let _objectiveBusy = false;

  function setObjectiveStatus(message, kind) {
    _objectiveStatus = message ? { message, kind: kind || 'info' } : null;
    if (message && typeof window.OmniConfirmationGate?.announce === 'function') {
      window.OmniConfirmationGate.announce(message, { kind: kind || 'info' });
    }
  }

  function resetObjectiveEditor() {
    _objectiveEditor = null;
    _objectiveStatus = null;
    _objectiveBusy = false;
  }

  /* Mirrors `operations_objectives.OBJECTIVE_MAX_LENGTH`. An objective is a
     sentence about intent, not a document. */
  const OBJECTIVE_TEXT_MAX = 280;

  const OBJECTIVE_SUCCESS_TEXT = Object.freeze({
    change: 'Objective changed. The change is stored on this machine.',
    complete: 'Objective marked complete. It stays here until you clear it.',
    clear: 'Objective cleared. It is kept as history, not destroyed.',
  });

  function safeEl(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined && text !== null) el.textContent = String(text);
    return el;
  }

  /* PB14-02 first slice (LNA-028): state-backed operation readiness card.
     Every row derives from already-source-backed local state; Unknown rows
     mean the local source has not reported — never a failure. ADR 0003
     Tier 1 rendering only. */
  function buildReadinessCard(model) {
    if (!model) return null;
    const commanderSummary = String(model.summary || '').replace(/\bunknown\b/gi, 'not checked');
    const card = safeEl('section', 'operations-readiness-card');
    card.setAttribute('aria-label', 'Operation readiness');
    const head = safeEl('div', 'operations-readiness-head');
    head.append(
      safeEl('h3', 'operations-readiness-title', 'Readiness'),
      safeEl('span', 'operations-readiness-summary', commanderSummary),
    );
    card.appendChild(head);

    /* An unanswered service is reported, not hidden. Removing the card would
       leave the Commander with no readiness section at all and no reason
       given, which reads as "nothing to report" rather than "not known". */
    if (model.unavailable || !Array.isArray(model.checks) || model.checks.length === 0) {
      if (model.caveat) {
        card.appendChild(safeEl('p', 'operations-readiness-note', model.caveat));
      }
      return card;
    }
    const list = safeEl('ul', 'operations-readiness-list');
    model.checks.forEach((check) => {
      const status = ['ready', 'attention', 'unknown'].includes(check.status)
        ? check.status : 'unknown';
      const item = safeEl('li',
        `operations-readiness-check operations-readiness-check--${status}`);
      item.append(
        safeEl('span', 'operations-readiness-label', check.label || 'Readiness check'),
        safeEl('span', 'operations-readiness-value',
          check.value === null || check.value === undefined ? 'Not checked' : check.value),
      );
      if (check.note) {
        item.appendChild(safeEl('span', 'operations-readiness-note', check.note));
      }
      list.appendChild(item);
    });
    card.appendChild(list);

    /* P14-D05: role fit for the operation being viewed, from the same readiness
       service. It answers a different question from the checks above — "is
       this ship equipped for this job", not "is it in good shape" — so it sits
       in the readiness card rather than becoming a card of its own. */
    const roleRow = buildRoleFitRow(model.operation);
    if (roleRow) card.appendChild(roleRow);

    if (model.caveat) {
      const caveat = safeEl('details', 'operations-readiness-caveat');
      caveat.appendChild(safeEl('summary', 'operations-readiness-caveat-summary', 'Why?'));
      caveat.appendChild(safeEl('p', 'operations-readiness-caveat-copy', model.caveat));
      card.appendChild(caveat);
    }
    return card;
  }

  /* Role fit for one operation (P14-D05 / LNA-022).
   *
   * Absence of evidence is never a verdict: a capability that was not seen in
   * the observed loadout is reported as not observed, not as missing. Modes
   * with no role evidence render nothing rather than an empty row.
   */
  function buildRoleFitRow(operation) {
    const profile = inputs.shipProfile;
    if (!profile || !operation) return null;
    const fit = profile.role_fit || null;
    if (!fit) return null;
    const role = (fit.roles || []).find((entry) => entry.role === operation);
    if (!role) return null;

    const row = safeEl('div', 'operations-role-fit');
    row.setAttribute('data-role-fit', operation);
    row.appendChild(safeEl('span', 'operations-role-fit-label', 'Role fit'));

    if (fit.loadout_observed === false) {
      row.setAttribute('data-role-fit-status', 'unknown');
      row.appendChild(safeEl('span', 'operations-role-fit-value', 'Loadout not checked'));
      row.appendChild(safeEl('span', 'operations-role-fit-note',
        'No loadout has been observed locally, so there is nothing to judge the '
        + 'fitting against.'));
      return row;
    }

    const fitted = Array.isArray(role.fitted) ? role.fitted : [];
    const notObserved = Array.isArray(role.not_observed) ? role.not_observed : [];
    const readable = (tokens) => tokens.map((token) => token.replace(/_/g, ' ')).join(', ');

    row.setAttribute('data-role-fit-status', role.status || 'unknown');
    row.appendChild(safeEl('span', 'operations-role-fit-value',
      fitted.length > 0 ? `${fitted.length} of ${fitted.length + notObserved.length} observed`
        : 'None observed'));
    if (fitted.length > 0) {
      row.appendChild(safeEl('span', 'operations-role-fit-note',
        `Observed: ${readable(fitted)}.`));
    }
    if (notObserved.length > 0) {
      /* "not observed", never "missing". */
      row.appendChild(safeEl('span', 'operations-role-fit-note',
        `Not observed in local data: ${readable(notObserved)}. That is not proof `
        + 'the ship lacks them.'));
    }
    return row;
  }

  /* PB14-02 first slice: Goals & Blockers workflow card. Read-only
     synthesis from the workspace view-model — goals labeled
     commander-entered vs from-local-state, blockers always name the
     missing source/state, next actions say why they are relevant.
     ADR 0003 Tier 1 rendering only. */
  /* ──────────────────────────────────────────────
   * The Commander objective band (R4-1 / P14-T02)
   *
   * R2 created one canonical objective slot; R3 filled it with real persisted
   * state; R4 gives it the rank it was promised. The audit found the objective
   * sitting BELOW the watch strip, context spine, primary action and readiness
   * card — "the thing the cockpit is supposedly organised around is neither
   * present nor prominent".
   *
   * It is now its own band, directly under the current-state strip and above
   * the primary action and readiness. This is a move, not a multiplication:
   * there is still exactly ONE objective slot in Operations. Blockers and next
   * actions stay in the workflow card below readiness, which is what keeps
   * Commander intent, factual readiness and recommendation distinct (R2-6) and
   * keeps safety information unobscured.
   * ────────────────────────────────────────────── */
  function buildObjectiveBand(goal) {
    if (!goal) return null;
    const band = safeEl('section', 'operations-objective-band');
    band.setAttribute('aria-label', 'Commander objective');

    const head = safeEl('div', 'operations-outlook-head');
    head.append(
      /* "Commander Objective" — not "Objective" — so it cannot be read as the
         same domain object as the derived exploration workflow steps (R4-6). */
      safeEl('h3', 'operations-outlook-title', 'Commander Objective'),
      safeEl('span', 'operations-outlook-goal-kind', goal.kindLabel || ''),
    );
    band.appendChild(head);

    const goalLine = safeEl('p', 'operations-outlook-goal', goal.text || 'No objective selected');
    goalLine.setAttribute('data-objective-slot', goal.kind || 'unknown');
    if (goal.isSet === false) goalLine.classList.add('operations-outlook-goal--unset');
    if (goal.objectiveId) {
      goalLine.setAttribute('data-commander-objective-id', String(goal.objectiveId));
    }
    if (goal.state) goalLine.setAttribute('data-objective-state', String(goal.state));
    if (goal.state === 'completed') {
      goalLine.classList.add('operations-outlook-goal--completed');
    }
    band.appendChild(goalLine);

    /* R3: the lifecycle lives on the one objective line, in the one objective
       owner. No second card, no objective sidebar. */
    const controls = buildObjectiveLifecycle(goal);
    if (controls) band.appendChild(controls);
    return band;
  }

  function buildWorkflowOutlookCard(model) {
    if (!model) return null;
    const hasActions = Array.isArray(model.nextActions) && model.nextActions.length > 0;
    const hasBlockers = Array.isArray(model.blockers) && model.blockers.length > 0;
    if (!hasActions && !hasBlockers && !model.caveat) return null;
    const card = safeEl('section', 'operations-outlook-card');
    /* R4-1: the objective moved out of this card and above it. What remains is
       the impediment-and-response pair, which is what this card now says. */
    card.setAttribute('aria-label', 'Blockers and next actions');

    card.appendChild(safeEl('h4', 'operations-outlook-subtitle', 'Blockers'));
    if (!Array.isArray(model.blockers) || model.blockers.length === 0) {
      card.appendChild(safeEl('p', 'operations-outlook-none',
        'Nothing known is blocking this activity. Details that were not checked do not count as blockers.'));
    } else {
      const list = safeEl('ul', 'operations-outlook-blockers');
      model.blockers.forEach((blocker) => {
        const item = safeEl('li', 'operations-outlook-blocker');
        /* R4-2: correlatable with the condition that produced it, so a later
           slice can tie a blocker to the readiness row it came from without
           parsing its label. */
        if (blocker.conditionId) {
          item.setAttribute('data-condition-id', String(blocker.conditionId));
        }
        item.append(
          safeEl('span', 'operations-outlook-blocker-label', blocker.label || 'Blocker'),
          safeEl('span', 'operations-outlook-blocker-detail', blocker.detail || ''),
          safeEl('span', 'operations-outlook-blocker-source', blocker.source || ''),
        );
        list.appendChild(item);
      });
      card.appendChild(list);
    }

    if (Array.isArray(model.nextActions) && model.nextActions.length > 0) {
      card.appendChild(safeEl('h4', 'operations-outlook-subtitle', 'Next actions'));
      const actions = safeEl('ul', 'operations-outlook-actions');
      model.nextActions.forEach((next) => {
        /* R2-3: workflow, handoff and support-tool actions share this one
           surface. `kind` weights them; it is not a taxonomy shown to the
           Commander, who reads a single list. */
        const kind = next.kind || 'workflow';
        const item = safeEl('li', `operations-outlook-action operations-outlook-action--${kind}`);
        item.setAttribute('data-action-kind', kind);
        /* R1-5: the action's own identity, and the blocker it clears when it
           came from one, so later work can correlate the two. */
        if (next.id) item.setAttribute('data-action-id', String(next.id));
        if (next.blockerId) item.setAttribute('data-blocker-id', String(next.blockerId));
        if (next.toolId) item.setAttribute('data-tool', String(next.toolId));
        /* R2-9: an action that switches the Operations mode is a control, not
           a link to the route we are already on. Anchors are reserved for real
           cross-route handoffs so a handoff always reads as a handoff. */
        const isModeSwitch = Boolean(next.operation);
        const link = safeEl(isModeSwitch ? 'button' : 'a',
          'cmd-btn cmd-btn--quiet operations-outlook-action-link', next.label || 'Open');
        if (isModeSwitch) {
          link.type = 'button';
          link.setAttribute('data-operation-target', String(next.operation));
          link.addEventListener('click', () => selectOperation(next.operation));
        } else if (next.route) {
          link.setAttribute('href', next.route);
          /* R5-11: a handoff that knows what the target should show says so,
             through the existing RouteTransferIntent grammar. The href stays as
             the fallback, so an action never becomes unreachable if the Shell
             helper is absent. */
          if (next.handoff) {
            link.addEventListener('click', (event) => {
              if (typeof window.Shell?.startRouteTransfer !== 'function') return;
              event.preventDefault();
              dispatchHandoff({
                originRoute: '/operations',
                originPackage: _manualOperation || 'idle',
                originSectionId: `operations-${_manualOperation || 'idle'}-workspace`,
                targetRoute: next.route.replace(/^#/, ''),
                targetSectionId: next.handoff.sectionId || '',
                targetEntityId: next.handoff.entityId || '',
                targetLabel: next.handoff.targetLabel || next.label || '',
                /* R6: the commodity travels in `targetQuery`, the field R2
                   added so a search term would stop being smuggled through
                   `targetLabel` and running as the wrong query. */
                targetQuery: next.handoff.targetQuery || '',
                reason: next.handoff.reason || '',
                returnLabel: 'Back to Operations',
                returnTarget: { route: '/operations' },
              });
            });
          }
        }
        item.appendChild(link);
        if (next.why) item.appendChild(safeEl('span', 'operations-outlook-action-why', next.why));
        actions.appendChild(item);
      });
      card.appendChild(actions);
    }

    /* R4-2 / R4-8: conditions that need attention but do not block this
       operation. They are kept — losing them would trade one dishonesty for
       another — but rendered subordinately and collapsed, so the Blockers slot
       means what it says and the Commander does not meet four cards shouting
       the same sentence. */
    if (Array.isArray(model.nonBlocking) && model.nonBlocking.length > 0) {
      const aside = safeEl('details', 'operations-outlook-nonblocking');
      aside.setAttribute('data-nonblocking-count', String(model.nonBlocking.length));
      aside.appendChild(safeEl('summary', 'operations-outlook-nonblocking-summary',
        `${model.nonBlocking.length} other condition`
        + `${model.nonBlocking.length === 1 ? '' : 's'} noted, not blocking this operation`));
      const list = safeEl('ul', 'operations-outlook-nonblocking-list');
      model.nonBlocking.forEach((entry) => {
        const item = safeEl('li', 'operations-outlook-nonblocking-item');
        if (entry.conditionId) {
          item.setAttribute('data-condition-id', String(entry.conditionId));
        }
        item.append(
          safeEl('span', 'operations-outlook-blocker-label', entry.label || 'Blocker'),
          safeEl('span', 'operations-outlook-blocker-detail', entry.detail || ''),
        );
        list.appendChild(item);
      });
      aside.appendChild(list);
      card.appendChild(aside);
    }

    const caveat = safeEl('details', 'operations-readiness-caveat');
    caveat.appendChild(safeEl('summary', 'operations-readiness-caveat-summary', 'Why?'));
    caveat.appendChild(safeEl('p', 'operations-readiness-caveat-copy', model.caveat || ''));
    card.appendChild(caveat);
    return card;
  }

  /* ──────────────────────────────────────────────
   * Commander objective lifecycle (PB14-R1 / R3)
   *
   * The objective is Commander intent: it is typed, persisted, and only ever
   * changed by the Commander. It is not derived from telemetry, not the mode
   * name, and not a recommendation — so nothing here reads local state to
   * produce objective text, and completion is never inferred.
   *
   * R2 left exactly one objective slot in the Operations hierarchy. These
   * affordances attach to that slot. Creating a second objective surface here
   * would be a defect against both R2 and PB14-R1 §3.
   *
   * Gate boundary (PB14-R1 §4): setting a FIRST objective where none exists is
   * an ordinary write — it destroys nothing and can be undone by stating
   * another. Change, complete and clear are protected and route through the
   * one shared Week 13 Confirmation Gate; the mutation is held server-side and
   * cannot run without a decision spent exactly once.
   * ────────────────────────────────────────────── */

  function buildObjectiveStatusLine() {
    if (!_objectiveStatus) return null;
    const line = safeEl('p',
      `operations-objective-status operations-objective-status--${_objectiveStatus.kind}`,
      _objectiveStatus.message);
    line.setAttribute('role', _objectiveStatus.kind === 'error' ? 'alert' : 'status');
    line.setAttribute('data-objective-status', _objectiveStatus.kind);
    return line;
  }

  /* Bounded, labelled text entry. `maxLength` mirrors the backend limit so the
     Commander is stopped at the boundary rather than told afterwards; the
     backend still rejects over-length input, because a UI limit is not a
     contract. */
  function buildObjectiveForm(operation, mode, initialText, initialTarget) {
    const form = safeEl('form', 'operations-objective-form');
    form.setAttribute('data-objective-form', mode);
    const inputId = `operations-objective-input-${operation}`;
    const label = safeEl('label', 'operations-objective-label',
      mode === 'change' ? 'Change your objective' : 'What are you trying to accomplish?');
    label.setAttribute('for', inputId);
    const field = document.createElement('input');
    field.type = 'text';
    field.id = inputId;
    field.className = 'operations-objective-input';
    field.maxLength = OBJECTIVE_TEXT_MAX;
    field.value = initialText || '';
    field.setAttribute('autocomplete', 'off');
    field.setAttribute('data-objective-input', operation);

    /* R6 / `P14-H02`: the Commander SELECTS a target commodity and quantity.
       They are separate fields, not something read out of the sentence above:
       parsing "fill 200t with platinum" would be guessing at intent, and a
       guess must never be stored as a Commander choice. Mining only, because
       fill progress is the one thing that needs a denominator; every other
       mode's objective is the sentence alone. */
    const targetFields = operation === 'mining'
      ? buildMiningTargetFields(operation, initialTarget)
      : null;

    const actions = safeEl('div', 'operations-objective-form-actions');
    const save = safeEl('button', 'cmd-btn cmd-btn--primary operations-objective-save',
      mode === 'change' ? 'Review change' : 'Save objective');
    save.type = 'submit';
    save.setAttribute('data-objective-action', mode === 'change' ? 'change-submit' : 'set-submit');
    const cancel = safeEl('button', 'cmd-btn cmd-btn--quiet operations-objective-cancel', 'Cancel');
    cancel.type = 'button';
    cancel.setAttribute('data-objective-action', 'cancel');
    cancel.addEventListener('click', () => {
      resetObjectiveEditor();
      renderWorkspace(operation);
    });
    actions.append(save, cancel);

    if (_objectiveBusy) {
      field.disabled = true;
      save.disabled = true;
      cancel.disabled = true;
      if (targetFields) {
        targetFields.commodity.disabled = true;
        targetFields.quantity.disabled = true;
      }
    }

    form.append(label, field);
    if (targetFields) form.appendChild(targetFields.wrap);
    form.appendChild(actions);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const text = String(field.value || '').trim();
      if (!text) {
        setObjectiveStatus('An objective needs some words. Nothing was saved.', 'error');
        renderWorkspace(operation);
        return;
      }
      /* An empty selection stays empty. A blank field is "I did not choose",
         never a reason to fall back to something derived. */
      const target = targetFields
        ? {
          commodity: String(targetFields.commodity.value || '').trim() || null,
          quantity: Number.parseInt(targetFields.quantity.value, 10) || null,
        }
        : null;
      if (mode === 'change') runProtectedObjectiveAction(operation, 'change', text, target);
      else submitFirstObjective(operation, text, target);
    });
    return form;
  }

  /* The commodity list offered is what this machine has actually observed:
     what is in the hold, and what the last market snapshot listed. It is a
     convenience, not a constraint — the field is free text so a Commander can
     name something OmniCOVAS has never seen, which is the normal case before
     the first run. */
  function observedCommodityOptions() {
    const names = new Set();
    (inputs.miningWorkflow?.cargo?.sellable || []).forEach((entry) => {
      if (entry?.name) names.add(String(entry.name));
    });
    (inputs.miningWorkflow?.sell_matches || []).forEach((entry) => {
      if (entry?.name) names.add(String(entry.name));
    });
    (inputs.tradeWorkflow?.matches || []).forEach((entry) => {
      if (entry?.name) names.add(String(entry.name));
    });
    return Array.from(names).sort();
  }

  function buildMiningTargetFields(operation, initialTarget) {
    const wrap = safeEl('div', 'operations-objective-target');
    wrap.setAttribute('data-objective-target', operation);
    wrap.appendChild(safeEl('p', 'operations-objective-target-note',
      'Optional. Choosing a target is what lets Mining show fill progress; '
      + 'nothing is read from the sentence above.'));

    const commodityId = `operations-objective-commodity-${operation}`;
    const commodityLabel = safeEl('label', 'operations-objective-label',
      'Target commodity');
    commodityLabel.setAttribute('for', commodityId);
    const commodity = document.createElement('input');
    commodity.type = 'text';
    commodity.id = commodityId;
    commodity.className = 'operations-objective-input operations-objective-commodity';
    commodity.maxLength = 64;
    commodity.value = initialTarget?.commodity || '';
    commodity.setAttribute('autocomplete', 'off');
    commodity.setAttribute('data-objective-target-commodity', operation);

    const listId = `operations-objective-commodity-list-${operation}`;
    const options = observedCommodityOptions();
    if (options.length > 0) {
      const datalist = document.createElement('datalist');
      datalist.id = listId;
      options.forEach((name) => {
        const option = document.createElement('option');
        option.value = name;
        datalist.appendChild(option);
      });
      commodity.setAttribute('list', listId);
      wrap.appendChild(datalist);
    }

    const quantityId = `operations-objective-quantity-${operation}`;
    const quantityLabel = safeEl('label', 'operations-objective-label',
      'Target tonnes');
    quantityLabel.setAttribute('for', quantityId);
    const quantity = document.createElement('input');
    quantity.type = 'number';
    quantity.id = quantityId;
    quantity.className = 'operations-objective-input operations-objective-quantity';
    quantity.min = '1';
    quantity.max = '100000';
    quantity.value = initialTarget?.quantity != null ? String(initialTarget.quantity) : '';
    quantity.setAttribute('data-objective-target-quantity', operation);

    wrap.append(commodityLabel, commodity, quantityLabel, quantity);
    return { wrap, commodity, quantity };
  }

  function buildObjectiveLifecycle(goal) {
    const operation = _manualOperation;
    if (!operation || !goal) return null;
    const wrap = safeEl('div', 'operations-objective-lifecycle');
    wrap.setAttribute('data-objective-lifecycle', goal.kind || 'unknown');

    /* Loading and Unknown offer nothing to press. Offering "Set objective"
       against an unread store would invite the Commander to overwrite an
       objective the app simply failed to read. */
    if (goal.pending) {
      wrap.appendChild(safeEl('p', 'operations-objective-note',
        'Reading your objective for this operation from local state.'));
      return wrap;
    }
    if (goal.available === false) {
      wrap.appendChild(safeEl('p', 'operations-objective-note',
        'The local objective store did not answer, so whether you have set an '
        + 'objective here is unknown. No change is offered against an unknown '
        + 'state.'));
      return wrap;
    }

    const status = buildObjectiveStatusLine();
    if (status) wrap.appendChild(status);

    const editing = _objectiveEditor && _objectiveEditor.operation === operation
      ? _objectiveEditor.mode : null;

    if (editing) {
      /* Changing keeps the selection the Commander already made, so a
         reworded objective does not silently drop its target. */
      const record = inputs.commanderObjective?.objective || null;
      wrap.appendChild(buildObjectiveForm(
        operation,
        editing,
        editing === 'change' ? goal.text : '',
        editing === 'change' && record
          ? { commodity: record.target_commodity, quantity: record.target_quantity }
          : null,
      ));
      return wrap;
    }

    const actions = safeEl('div', 'operations-objective-actions');
    const addButton = (label, action, handler, variant) => {
      const button = safeEl('button',
        `cmd-btn ${variant || 'cmd-btn--quiet'} operations-objective-button`, label);
      button.type = 'button';
      button.setAttribute('data-objective-action', action);
      button.disabled = Boolean(_objectiveBusy);
      button.addEventListener('click', handler);
      actions.appendChild(button);
    };

    if (!goal.commanderObjectiveSet) {
      /* Not set is absence, not a prompt dressed as a fact: the line above
         reads "Not set" (or the labelled derived stand-in) and this is simply
         the way to state one. */
      addButton('Set objective', 'set', () => {
        _objectiveStatus = null;
        _objectiveEditor = { operation, mode: 'set' };
        renderWorkspace(operation);
      }, 'cmd-btn--primary');
    } else if (goal.state === 'completed') {
      wrap.appendChild(safeEl('p', 'operations-objective-note',
        'You marked this objective complete. It stays here until you clear it.'));
      addButton('Clear objective', 'clear',
        () => runProtectedObjectiveAction(operation, 'clear'));
    } else {
      addButton('Change objective', 'change', () => {
        _objectiveStatus = null;
        _objectiveEditor = { operation, mode: 'change' };
        renderWorkspace(operation);
      });
      addButton('Mark complete', 'complete',
        () => runProtectedObjectiveAction(operation, 'complete'));
      addButton('Clear objective', 'clear',
        () => runProtectedObjectiveAction(operation, 'clear'));
    }

    wrap.appendChild(actions);
    return wrap;
  }

  /* Re-read the mode's objective and redraw. Never optimistic: the surface
     shows what the store returned, so a write that did not land cannot be
     rendered as though it had. */
  async function reloadObjective(operation) {
    const payload = await fetchJson(`/operations/objectives/${encodeURIComponent(operation)}`);
    if (_manualOperation !== operation) return;
    inputs.commanderObjective = payload;
    inputs.commanderObjectivePending = false;
    if (getRoot() !== null) renderWorkspace(operation);
  }

  async function submitFirstObjective(operation, text, target) {
    if (_objectiveBusy) return;
    _objectiveBusy = true;
    renderWorkspace(operation);
    try {
      const body = { text };
      if (target?.commodity) body.target_commodity = target.commodity;
      if (target?.quantity) body.target_quantity = target.quantity;
      await postJson(`/operations/objectives/${encodeURIComponent(operation)}`, body);
      _objectiveEditor = null;
      setObjectiveStatus('Objective set. It is stored on this machine and will be '
        + 'here when you come back.', 'success');
    } catch (err) {
      setObjectiveStatus(err?.commanderMessage
        || 'The objective was not saved. Nothing changed.', 'error');
    } finally {
      _objectiveBusy = false;
      await reloadObjective(operation);
      if (_manualOperation === operation && getRoot() !== null) renderWorkspace(operation);
    }
  }

  /* Protected transitions. The proposal is held server-side; this only asks
     for it and then waits for a decision the Commander makes in the shared
     gate. Cancelling changes nothing, and the wait is bounded. */
  /* Campaign lifecycle, through the SAME Week 13 queue objectives use (R8-16).
     Deliberately a near-copy of `runProtectedObjectiveAction` in shape rather
     than a second gate mechanism: one queue, one policy, two callers.

     Only `complete` and `archive` are offered. Reversible progression between
     proposed / active / blocked is not protected, and putting a confirmation on
     it would be the modal-on-every-button the R8 ruling forbids. */
  let _campaignBusy = false;
  let _campaignStatus = null;

  const CAMPAIGN_SUCCESS_TEXT = {
    complete: 'Campaign marked complete. Your Commander Objective is unchanged.',
    archive: 'Campaign archived. The record is kept, not deleted.',
  };

  function setCampaignStatus(message, tone) {
    _campaignStatus = message ? { message, tone: tone || 'info' } : null;
  }

  async function runProtectedCampaignAction(operation, action, campaignId) {
    if (_campaignBusy) return;
    const gate = window.OmniConfirmationGate;
    if (!gate?.delay) {
      setCampaignStatus('The shared Confirmation Gate is unavailable, so this '
        + 'change cannot be confirmed. Nothing changed.', 'error');
      renderWorkspace(operation);
      return;
    }
    _campaignBusy = true;
    renderWorkspace(operation);
    try {
      const proposal = await postJson(
        '/operations/phase9/campaigns/actions/propose',
        { action, campaign_id: campaignId },
      );
      const confirmationId = proposal?.confirmation_id || null;
      if (!confirmationId) throw new Error('No confirmation id was returned.');
      setCampaignStatus('Awaiting your decision in the Confirmation Gate. '
        + 'Nothing has changed yet.', 'warning');
      renderWorkspace(operation);

      let authorized = null;
      for (let attempt = 0; attempt < 300 && authorized === null; attempt += 1) {
        const result = await postJson(
          '/operations/phase9/campaigns/actions/authorize',
          { confirmation_id: confirmationId },
        );
        if (result?.authorized) authorized = result;
        else await gate.delay(1000);
      }
      if (authorized === null) throw new Error('Confirmation wait timed out.');
      setCampaignStatus(CAMPAIGN_SUCCESS_TEXT[action] || 'Campaign updated.', 'success');
    } catch (err) {
      /* R3's truth lock: a write that did not happen is reported as a failure,
         never rendered as an unchanged surface pretending nothing was asked. */
      setCampaignStatus(err?.commanderMessage
        || 'The campaign was not changed. It is unchanged on this machine.', 'error');
    } finally {
      _campaignBusy = false;
      if (_manualOperation === operation && getRoot() !== null) {
        renderWorkspace(operation);
      }
    }
  }

  async function runProtectedObjectiveAction(operation, action, text, target) {
    if (_objectiveBusy) return;
    const gate = window.OmniConfirmationGate;
    if (!gate?.delay) {
      setObjectiveStatus('The shared Confirmation Gate is unavailable, so this '
        + 'change cannot be confirmed. Nothing changed.', 'error');
      renderWorkspace(operation);
      return;
    }
    _objectiveBusy = true;
    renderWorkspace(operation);
    try {
      const body = { action, operation };
      if (action === 'change') {
        body.text = text;
        /* The selection goes through the same gate as the sentence. Changing a
           stated target is a Commander decision, not a side effect. */
        if (target?.commodity) body.target_commodity = target.commodity;
        if (target?.quantity) body.target_quantity = target.quantity;
      }
      const proposal = await postJson('/operations/objectives/actions/propose', body);
      const confirmationId = proposal?.confirmation_id || null;
      if (!confirmationId) throw new Error('No confirmation id was returned.');
      setObjectiveStatus('Awaiting your decision in the Confirmation Gate. '
        + 'Nothing has changed yet.', 'warning');
      renderWorkspace(operation);

      let authorized = null;
      for (let attempt = 0; attempt < 300 && authorized === null; attempt += 1) {
        const result = await postJson('/operations/objectives/actions/authorize',
          { confirmation_id: confirmationId });
        if (result?.authorized) authorized = result;
        else await gate.delay(1000);
      }
      if (authorized === null) throw new Error('Confirmation wait timed out.');
      _objectiveEditor = null;
      setObjectiveStatus(OBJECTIVE_SUCCESS_TEXT[action] || 'Objective updated.', 'success');
    } catch (err) {
      setObjectiveStatus(err?.commanderMessage
        || 'The objective was not changed. It is unchanged on this machine.', 'error');
    } finally {
      _objectiveBusy = false;
      await reloadObjective(operation);
      if (_manualOperation === operation && getRoot() !== null) renderWorkspace(operation);
    }
  }

  /* ──────────────────────────────────────────────
   * Exploration workflow card (R1-2, deepened in R5)
   *
   * `/operations/exploration/snapshot` is a real PB05-08 backend that no UI
   * file fetched, so the Exploration workspace rendered only the generic
   * skeleton and the Commander could not reach a single exploration objective.
   * R1 made this card the missing consumer. R5 gives it something worth
   * consuming: a stage, semantic progress, work remaining, a concrete derived
   * step, value split by truth class, and a completion-readiness claim.
   *
   * Boundaries held deliberately: Operations owns the workflow — what stage am
   * I at, what work remains, what should I do next, is this effectively done.
   * Intel keeps the system/body/biology facts and Navigation keeps the hop
   * table; this card shows counts and one-line summaries and hands off for
   * anything deeper. No Intel fact browser and no route planner is rebuilt.
   *
   * Two things this card no longer does. It does not render a Blockers list of
   * its own — R2 made the outlook card the one owner of that slot and R5-9
   * routes exploration blockers through it, so a Commander meets one Blockers
   * heading per screen. And it does not present candidate genera beside
   * observed ones: a prediction and an observation are shown apart, always.
   * ────────────────────────────────────────────── */

  /* R5-1: the smallest stage vocabulary local data can prove. Each label is a
     reading of the journal, not a state machine the app advances on its own. */
  const EXPLORATION_STAGE_LABELS = Object.freeze({
    unknown: 'Not checked',
    transit: 'In transit',
    arrived: 'Arrived',
    system_survey: 'System survey',
    surface_survey: 'Surface survey',
    biology: 'Biology',
    departure_ready: 'Departure ready',
  });

  /* The route-session reading PB05-08 owned. It is not the workflow stage —
     "Route loaded" says something about NavRoute.json, "System survey" says
     something about where the Commander is in this exploration — so both are
     shown, each on its own row, and neither is collapsed into the other. */
  const EXPLORATION_SESSION_LABELS = Object.freeze({
    route_loaded: 'Route loaded',
    no_route_plotted: 'No route plotted',
    no_route: 'NavRoute not loaded',
    unknown: 'Not checked',
  });

  const EXPLORATION_WORK_KIND_LABELS = Object.freeze({
    work: 'Work',
    opportunity: 'Opportunity',
    unknown: 'Not checked',
  });

  const EXPLORATION_ITEM_STATE_SET = new Set(['complete', 'active', 'blocked', 'unknown']);

  function explorationItemChip(state, blockClass) {
    const raw = String(state || 'unknown').toLowerCase();
    const known = EXPLORATION_ITEM_STATE_SET.has(raw) ? raw : 'unknown';
    return safeEl('span', `${blockClass} ${blockClass}--${known}`, known);
  }

  function explorationFactRow(label, value, modifier) {
    const row = safeEl('p', 'operations-exploration-fact');
    if (modifier) row.classList.add(`operations-exploration-fact--${modifier}`);
    row.append(
      safeEl('span', 'operations-exploration-fact-label', label),
      safeEl('span', 'operations-exploration-fact-value', value),
    );
    return row;
  }

  /* Credits received and an estimate of what unsold scans might fetch are two
     different kinds of number. They are rendered as separate rows with their
     own labels and never summed: an estimate added to an earning reads as an
     account balance, which is exactly the claim the data cannot support. */
  function buildExplorationValueBlock(value) {
    if (!value) return null;
    const wrap = safeEl('div', 'operations-exploration-value');
    const earned = value.actual_earnings || {};
    const estimate = value.estimated_scan_value || {};
    const bio = value.estimated_biology_value || {};

    const credits = [];
    if (typeof earned.exploration_credits === 'number') {
      credits.push(`${earned.exploration_credits.toLocaleString()} Cr exploration`);
    }
    if (typeof earned.exobiology_credits === 'number') {
      credits.push(`${earned.exobiology_credits.toLocaleString()} Cr exobiology`);
    }
    wrap.appendChild(explorationFactRow(
      'Credits received',
      credits.length > 0 ? credits.join(' · ') : 'No sale recorded',
      'earned',
    ));

    const low = estimate.estimated_low;
    const high = estimate.estimated_high;
    wrap.appendChild(explorationFactRow(
      'Estimated scan value',
      (typeof low === 'number' && typeof high === 'number')
        ? `${low.toLocaleString()}–${high.toLocaleString()} Cr (estimate, not earned)`
        : 'Not checked',
      'estimate',
    ));
    if (Number(estimate.bodies_unvalued) > 0) {
      wrap.appendChild(explorationFactRow(
        'Bodies with no estimate',
        `${estimate.bodies_unvalued} (class never recorded)`,
        'estimate',
      ));
    }
    wrap.appendChild(explorationFactRow(
      'Estimated exobiology value',
      'Not checked',
      'estimate',
    ));
    return wrap;
  }

  /* R5-7: observed genera are fact, candidates are prediction, and the two are
     never rendered in the same list or with the same weight. */
  function buildExplorationBiologyBlock(biology) {
    if (!biology) return null;
    const wrap = safeEl('div', 'operations-exploration-biology');
    wrap.appendChild(explorationFactRow(
      'Observed genera',
      biology.genera_observed > 0
        ? `${biology.genera_observed} observed on ${biology.bodies_with_observed_genera} `
          + `bod${biology.bodies_with_observed_genera === 1 ? 'y' : 'ies'}`
        : 'None recorded',
      'observed',
    ));
    wrap.appendChild(explorationFactRow(
      'Samples',
      biology.species_sampled > 0
        ? `${biology.species_analysed} of ${biology.species_sampled} species analysed`
        : 'None recorded',
      'observed',
    ));
    if (biology.candidate_genera > 0) {
      wrap.appendChild(explorationFactRow(
        'Candidate genera',
        `${biology.candidate_genera} predicted — not observed`,
        'candidate',
      ));
    }
    /* A predicate the Sentinel has falsified must not be presented as an
       authority. R5 consumes that verdict; it never changes the ruleset. */
    if (biology.sentinel_predicate_state) {
      wrap.appendChild(explorationFactRow(
        'Prediction rules',
        `${biology.sentinel_predicate_state} — candidates shown with reduced confidence`,
        'candidate',
      ));
    }
    return wrap;
  }

  function buildExplorationWorkList(workRemaining) {
    const list = safeEl('ul', 'operations-exploration-work');
    (workRemaining || []).forEach((entry) => {
      const kind = String(entry.kind || 'unknown');
      const item = safeEl('li', `operations-exploration-work-item operations-exploration-work-item--${kind}`);
      item.setAttribute('data-work-kind', kind);
      if (entry.id) item.setAttribute('data-work-id', String(entry.id));
      item.append(
        safeEl('span', 'operations-exploration-work-kind',
          EXPLORATION_WORK_KIND_LABELS[kind] || 'Activity'),
        safeEl('span', 'operations-exploration-work-label', entry.label || 'Work item'),
        safeEl('span', 'operations-exploration-work-detail', entry.detail || ''),
      );
      list.appendChild(item);
    });
    return list;
  }

  /* R5-11: a handoff carries the context the target needs to land on the right
     thing — the section that owns the detail and the entity in question — via
     the existing RouteTransferIntent grammar. Nothing Commander-authored is
     ever placed in that payload, and nothing leaves this machine. */
  /* API paths as the snapshot states them, mapped to the UI routes that own
     them. The legacy PB05-08 `handoffs` map is still honoured so a snapshot
     built without workflow facts keeps its three destinations. */
  const EXPLORATION_HANDOFF_HASH = Object.freeze({
    '/intel': '#/intel',
    '/intel/snapshot': '#/intel',
    '/navigation': '#/navigation',
    '/navigation/snapshot': '#/navigation',
    '/activity-log': '#/activity-log',
  });

  const EXPLORATION_LEGACY_HANDOFF_LABELS = Object.freeze({
    intel: 'Open Intel',
    navigation: 'Open Navigation',
    activity_log: 'Open Activity Log',
  });

  function explorationHandoffList(workflow, snap) {
    const fromWorkflow = Array.isArray(workflow?.handoffs) ? workflow.handoffs : [];
    if (fromWorkflow.length > 0) {
      return fromWorkflow
        .map((handoff) => ({
          ...handoff,
          hash: EXPLORATION_HANDOFF_HASH[String(handoff.route || '')] || null,
        }))
        .filter((handoff) => handoff.hash);
    }
    const legacy = snap?.handoffs || {};
    return Object.keys(EXPLORATION_LEGACY_HANDOFF_LABELS)
      .filter((key) => legacy[key])
      .map((key) => ({
        id: key,
        label: EXPLORATION_LEGACY_HANDOFF_LABELS[key],
        route: legacy[key],
        section_id: null,
        entity_id: null,
        reason: '',
        hash: EXPLORATION_HANDOFF_HASH[String(legacy[key])] || null,
      }))
      .filter((handoff) => handoff.hash);
  }

  function startExplorationHandoff(handoff, fallbackRoute) {
    if (typeof window.Shell?.startRouteTransfer === 'function') {
      const intent = dispatchHandoff({
        originRoute: '/operations',
        originPackage: 'exploration',
        originSectionId: 'operations-exploration-workspace',
        targetRoute: String(handoff.route || '').replace('/snapshot', ''),
        targetSectionId: handoff.section_id || '',
        targetEntityId: handoff.entity_id || '',
        targetLabel: handoff.label || '',
        reason: handoff.reason || '',
        returnLabel: 'Back to Operations',
        returnTarget: { route: '/operations' },
      });
      if (intent) return;
    }
    if (fallbackRoute) window.location.hash = fallbackRoute;
  }

  function buildOpsV3ExplorationCard(inputsObj) {
    const card = safeEl('section', 'operations-exploration-card');
    card.setAttribute('aria-label', 'Exploration workflow');
    const head = safeEl('div', 'operations-exploration-head');
    head.appendChild(safeEl('h3', 'operations-exploration-title', 'Exploration workflow'));
    card.appendChild(head);

    const snap = inputsObj?.explorationSnapshot || null;
    if (!snap) {
      /* A read still in flight is not an empty workflow, and neither is a
         service that did not answer. Both are said plainly. */
      card.appendChild(safeEl('p', 'operations-exploration-note',
        inputsObj?.explorationPending === true
          ? 'Reading the exploration snapshot from local state…'
          : 'Exploration snapshot not loaded. The local exploration service did '
            + 'not answer, so no objectives are shown rather than none claimed.'));
      return card;
    }

    const workflow = snap.workflow || null;
    const available = workflow?.available === true;

    /* R5-1: the stage, in the head, because it is the answer to "where am I in
       this?" and everything below it is detail. */
    head.appendChild(safeEl('span', 'operations-exploration-status',
      EXPLORATION_STAGE_LABELS[String(workflow?.stage || 'unknown')]
        || EXPLORATION_STAGE_LABELS.unknown));

    if (workflow?.stage_detail) {
      card.appendChild(safeEl('p', 'operations-exploration-stage-detail',
        workflow.stage_detail));
    }

    if (!available) {
      card.appendChild(safeEl('p', 'operations-exploration-note',
        workflow?.caveat
          || 'The local exploration history could not be read, so no progress '
            + 'is claimed. Progress has not been checked; this is not an empty system.'));
    }

    card.appendChild(explorationFactRow(
      'Session',
      EXPLORATION_SESSION_LABELS[String(snap.session_status || 'unknown')]
        || EXPLORATION_SESSION_LABELS.unknown,
    ));

    const routeRef = snap.active_route_ref || null;
    if (routeRef) {
      const hops = routeRef.total_hops;
      const routeLine = routeRef.destination
        ? `${routeRef.destination}${hops === null || hops === undefined ? '' : ` · ${hops} hops`}`
        : (routeRef.fallback || 'Route not checked');
      card.appendChild(explorationFactRow('Route', routeLine));
    }

    /* R5-3: the derived step. It is labelled as derived and kept visually and
       semantically apart from the Commander objective band above — different
       heading, different identity, different owner. */
    /* The workflow owns the step where it can read one. Where it cannot, the
       route-derived snapshot objective still answers "what am I doing", so the
       R1 contract survives a workflow that could not be built. */
    const objectives = Array.isArray(snap.objectives) ? snap.objectives : [];
    const step = workflow?.step || objectives[0] || null;
    card.appendChild(safeEl('h4', 'operations-exploration-subtitle',
      'Current exploration step'));
    if (step) {
      const stepRow = safeEl('div', 'operations-exploration-step');
      stepRow.setAttribute('data-objective-id', String(step.objective_id || ''));
      stepRow.setAttribute('data-objective-owner', String(step.owner || 'derived'));
      stepRow.append(
        safeEl('p', 'operations-exploration-step-label', step.label || 'Next step not checked'),
        safeEl('p', 'operations-exploration-step-owner',
          'Derived from local exploration facts — not a Commander objective.'),
      );
      card.appendChild(stepRow);
    } else {
      card.appendChild(safeEl('p', 'operations-exploration-none',
        snap.fallback
          ? `No exploration workflow steps derived from local state (${snap.fallback}).`
          : 'No exploration workflow steps derived from local state.'));
    }

    /* R5-2 / R5-5: semantic progress and what is left, in that order. No body
       table: Intel owns that, and the handoffs below go there. */
    if (available && workflow.progress) {
      const system = workflow.progress.system || {};
      const mapping = workflow.progress.mapping || {};
      card.appendChild(safeEl('h4', 'operations-exploration-subtitle', 'Progress'));
      const progress = safeEl('div', 'operations-exploration-progress');
      progress.appendChild(explorationFactRow(
        'Bodies scanned',
        system.body_count_known
          ? `${system.bodies_scanned} of ${system.bodies_in_system}`
          : `${system.bodies_scanned} scanned · system total not checked`,
      ));
      progress.appendChild(explorationFactRow(
        'Surface mapped', String(mapping.bodies_surface_mapped ?? 0),
      ));
      progress.appendChild(explorationFactRow(
        'First discoveries',
        String(workflow.progress.footfall?.first_discoveries ?? 0),
      ));
      /* R5-6: first DISCOVERY is a local fact; first FOOTFALL is not, and the
         two are never allowed to read as one claim. */
      progress.appendChild(explorationFactRow('First footfall', 'Not checked'));
      card.appendChild(progress);

      const biology = buildExplorationBiologyBlock(workflow.progress.biology);
      if (biology) card.appendChild(biology);
    }

    /* Only claimed when a workflow actually answered. A snapshot carrying no
       workflow block has not told us there is nothing left — it has told us
       nothing, and "No additional work detected" would be a fabricated all-clear
       of exactly the kind R0 was written to remove. */
    if (workflow) {
      const workRemaining = Array.isArray(workflow.work_remaining)
        ? workflow.work_remaining : [];
      card.appendChild(safeEl('h4', 'operations-exploration-subtitle', 'Work remaining'));
      if (workRemaining.length > 0) {
        card.appendChild(buildExplorationWorkList(workRemaining));
      } else if (available) {
        card.appendChild(safeEl('p', 'operations-exploration-none',
          'No additional locally-known exploration work detected.'));
      } else {
        /* The all-clear is available ONLY to a workflow that could read the
           facts. A workflow that could not has nothing to clear. */
        card.appendChild(safeEl('p', 'operations-exploration-none',
          'Work remaining is not known — the local exploration history could '
          + 'not be read.'));
      }
    }

    /* R5-13: completion readiness, stated as the claim it actually is. */
    const completion = workflow?.completion || null;
    if (completion) {
      const row = safeEl('p',
        `operations-exploration-completion operations-exploration-completion--${completion.state}`);
      row.setAttribute('data-completion-state', String(completion.state));
      row.append(
        safeEl('span', 'operations-exploration-completion-label', completion.label || 'Completion not checked'),
        safeEl('span', 'operations-exploration-completion-reason', completion.reason || ''),
      );
      card.appendChild(row);
    }

    const value = buildExplorationValueBlock(workflow?.value);
    if (value) {
      card.appendChild(safeEl('h4', 'operations-exploration-subtitle', 'Value'));
      card.appendChild(value);
    }

    /* R5-4: the checklist, collapsed. It is detail behind the workflow, not the
       workflow itself, and every row names the event that advances it. */
    const checklist = Array.isArray(snap.checklist) ? snap.checklist : [];
    if (checklist.length > 0) {
      const advanced = checklist.filter((entry) => entry.state === 'complete').length;
      const details = safeEl('details', 'operations-exploration-checklist-details');
      details.appendChild(safeEl('summary', 'operations-exploration-checklist-summary',
        `Exploration checklist — ${advanced} of ${checklist.length} recorded`));
      const list = safeEl('ul', 'operations-exploration-checklist');
      checklist.forEach((entry) => {
        const item = safeEl('li', 'operations-exploration-checklist-item');
        item.setAttribute('data-item-id', String(entry.item_id || ''));
        item.setAttribute('data-item-state', String(entry.state || 'unknown'));
        item.append(
          safeEl('span', 'operations-exploration-checklist-label', entry.label || 'Checklist item'),
          explorationItemChip(entry.state, 'operations-exploration-checklist-state'),
          safeEl('span', 'operations-exploration-checklist-evidence',
            entry.evidence || entry.caveat || ''),
        );
        list.appendChild(item);
      });
      details.appendChild(list);
      card.appendChild(details);
    }

    /* Handoffs: Operations answers "where do I go for more detail" by naming
       the route that owns the detail, never by rendering it here. R5-11 gives
       each one the context the target needs to land on the right thing. */
    const handoffs = explorationHandoffList(workflow, snap);
    if (handoffs.length > 0) {
      const strip = safeEl('nav', 'operations-exploration-handoffs');
      strip.setAttribute('aria-label', 'Exploration handoffs');
      handoffs.forEach((handoff) => {
        /* R2-9: a real cross-route handoff reads as a link and keeps its href,
           so it works whether or not the Shell transfer helper is present. */
        const link = safeEl('a',
          'cmd-btn cmd-btn--quiet operations-exploration-handoff', handoff.label || 'Open');
        link.setAttribute('href', handoff.hash);
        link.setAttribute('data-handoff-id', String(handoff.id || ''));
        if (handoff.section_id) {
          link.setAttribute('data-handoff-section', String(handoff.section_id));
        }
        if (handoff.entity_id) {
          link.setAttribute('data-handoff-entity', String(handoff.entity_id));
        }
        if (handoff.section_id) {
          link.addEventListener('click', (event) => {
            if (typeof window.Shell?.startRouteTransfer !== 'function') return;
            event.preventDefault();
            startExplorationHandoff(handoff, handoff.hash);
          });
        }
        strip.appendChild(link);
      });
      card.appendChild(strip);
    }

    /* Every caveat the snapshot carries, collapsed. The default surface stays
       a workflow surface, not a proof wall. */
    const caveats = [];
    if (workflow?.caveat) caveats.push(workflow.caveat);
    (Array.isArray(snap.unsupported_notes) ? snap.unsupported_notes : [])
      .forEach((note) => { if (note && !caveats.includes(note)) caveats.push(note); });
    if (caveats.length > 0) {
      const details = safeEl('details', 'operations-readiness-caveat');
      details.appendChild(safeEl('summary', 'operations-readiness-caveat-summary',
        'Why some details are missing'));
      caveats.forEach((note) => {
        details.appendChild(safeEl('p', 'operations-readiness-caveat-copy', note));
      });
      card.appendChild(details);
    }

    return card;
  }

  /* ──────────────────────────────────────────────
   * Trade and Mining workflow cards (R6)
   *
   * The audit found Trade's sell matcher living entirely in button labels:
   * "Search sell prices", "Open Market Search" and "Compare current station"
   * were three names for one handler that set `window.location.hash`. Mining
   * ended at a readiness card and never reached the sale.
   *
   * These two cards render the workflows that replace them. They share the
   * exploration card's shape — stage, step, progress, work remaining,
   * completion, collapsed detail, handoffs — because a Commander switching
   * modes should meet the same grammar, not a new one. They do NOT share a
   * card: Trade asks about cargo, market and sale; Mining asks about
   * equipment, extraction and return. Merging them would produce one surface
   * where half the rows are inert whichever mode you are in.
   *
   * Neither renders a Blockers list. R2 made the outlook card the one owner of
   * that slot and R6 routes both workflows' blockers through it.
   *
   * Three visual distinctions carry the honesty, and they are the reason these
   * classes exist rather than a generic row: a current market snapshot never
   * looks like a historical one, a potential value never looks like credits
   * received, and fitted equipment never looks like equipment that was merely
   * not seen.
   * ────────────────────────────────────────────── */

  const TRADE_STAGE_LABELS = Object.freeze({
    unknown: 'Not checked',
    no_cargo: 'No sale workflow active',
    cargo_aboard: 'Cargo aboard',
    market_review: 'Market review required',
    no_local_demand: 'No local demand',
    sell_opportunity: 'Local sell opportunity known',
  });

  const MINING_STAGE_LABELS = Object.freeze({
    unknown: 'Not checked',
    prepare: 'Prepare',
    extract: 'Extract',
    return: 'Return',
    sell: 'Sell',
    complete_ready: 'Session complete',
  });

  /* A snapshot's scope is the single most misreadable fact on these surfaces:
     the same 356 rows mean something completely different depending on whether
     the Commander is standing in that station. The modifier drives the
     treatment so the two can never look alike. */
  const MARKET_SCOPE_MODIFIER = Object.freeze({
    current_station: 'current',
    same_station_historical: 'historical',
    foreign_station: 'historical',
    unknown_identity: 'historical',
    not_loaded: 'absent',
  });

  const FIT_STATE_LABELS = Object.freeze({
    fitted: 'Fitted',
    not_observed: 'Not observed',
    unknown: 'Not checked',
  });

  const COMBAT_STAGE_LABELS = Object.freeze({
    unknown: 'Combat status not checked',
    idle: 'Idle',
    preparation: 'Preparation',
    interdicted: 'Interdiction',
    engaged: 'Engaged',
    recovery: 'Recovery',
    post_engagement: 'Post-engagement',
    review_ready: 'Review ready',
  });

  /* Readiness meaning must survive without colour (R7-22): every state carries
     a word, and the modifier only changes the treatment. */
  const COMBAT_FACT_STATE_LABELS = Object.freeze({
    good: 'OK',
    problem: 'Attention',
    unknown: 'Not checked',
  });

  /* Factual descriptions of what the journal observed. Deliberately not
     characterisations of the other Commander — there is no vocabulary here
     for 'ganker', 'griefer' or any risk score, and none may be added. */
  const PVP_ENCOUNTER_LABELS = Object.freeze({
    interdicted_by: 'Interdicted by',
    killed_by: 'Ship lost to',
    killed: 'Ship destroyed',
    witnessed: 'Witnessed',
    commander_entered: 'Commander note',
    unknown: 'Recorded encounter',
  });

  function economyFactRow(label, value, modifier) {
    const row = safeEl('p', 'operations-economy-fact');
    if (modifier) row.classList.add(`operations-economy-fact--${modifier}`);
    row.append(
      safeEl('span', 'operations-economy-fact-label', label),
      safeEl('span', 'operations-economy-fact-value', value),
    );
    return row;
  }

  function creditText(value) {
    return typeof value === 'number' ? `${value.toLocaleString()} Cr` : 'Value not checked';
  }

  function buildEconomyStep(step, ownerNote) {
    const wrap = safeEl('div', 'operations-economy-step');
    wrap.setAttribute('data-objective-id', String(step.objective_id || ''));
    wrap.setAttribute('data-objective-owner', String(step.owner || 'derived'));
    wrap.append(
      safeEl('p', 'operations-economy-step-label', step.label || 'Next step not checked'),
      safeEl('p', 'operations-economy-step-owner', ownerNote),
    );
    return wrap;
  }

  function buildEconomyWorkList(workRemaining) {
    const list = safeEl('ul', 'operations-economy-work');
    (workRemaining || []).forEach((entry) => {
      const kind = String(entry.kind || 'unknown');
      const item = safeEl('li',
        `operations-economy-work-item operations-economy-work-item--${kind}`);
      item.setAttribute('data-work-kind', kind);
      if (entry.id) item.setAttribute('data-work-id', String(entry.id));
      item.append(
        safeEl('span', 'operations-economy-work-kind',
          EXPLORATION_WORK_KIND_LABELS[kind] || 'Activity'),
        safeEl('span', 'operations-economy-work-label', entry.label || 'Work item'),
        safeEl('span', 'operations-economy-work-detail', entry.detail || ''),
      );
      list.appendChild(item);
    });
    return list;
  }

  function buildEconomyCompletion(completion) {
    if (!completion) return null;
    const row = safeEl('p',
      `operations-economy-completion operations-economy-completion--${completion.state}`);
    row.setAttribute('data-completion-state', String(completion.state));
    row.append(
      safeEl('span', 'operations-economy-completion-label', completion.label || 'Completion not checked'),
      safeEl('span', 'operations-economy-completion-reason', completion.reason || ''),
    );
    return row;
  }

  /* Handoffs reuse the R5 contract: real anchors that keep their href, upgraded
     on click to a typed RouteTransferIntent so the target lands on the right
     thing. `targetQuery` carries the commodity — the field R2 added precisely
     so a commodity would stop being smuggled through `targetLabel`. */
  function buildEconomyHandoffs(handoffs, originSectionId) {
    const list = Array.isArray(handoffs) ? handoffs : [];
    if (list.length === 0) return null;
    const strip = safeEl('nav', 'operations-economy-handoffs');
    strip.setAttribute('aria-label', 'Workflow handoffs');
    list.forEach((handoff) => {
      const hash = EXPLORATION_HANDOFF_HASH[String(handoff.route || '')] || null;
      if (!hash) return;
      const link = safeEl('a',
        'cmd-btn cmd-btn--quiet operations-economy-handoff', handoff.label || 'Open');
      link.setAttribute('href', hash);
      link.setAttribute('data-handoff-id', String(handoff.id || ''));
      if (handoff.section_id) {
        link.setAttribute('data-handoff-section', String(handoff.section_id));
      }
      if (handoff.query) link.setAttribute('data-handoff-query', String(handoff.query));
      if (handoff.section_id) {
        link.addEventListener('click', (event) => {
          if (typeof window.Shell?.startRouteTransfer !== 'function') return;
          event.preventDefault();
          dispatchHandoff({
            originRoute: '/operations',
            originPackage: _manualOperation || 'idle',
            originSectionId: originSectionId,
            targetRoute: String(handoff.route || ''),
            targetSectionId: handoff.section_id || '',
            targetEntityId: handoff.entity_id || '',
            targetLabel: handoff.label || '',
            targetQuery: handoff.query || '',
            reason: handoff.reason || '',
            returnLabel: 'Back to Operations',
            returnTarget: { route: '/operations' },
          });
        });
      }
      strip.appendChild(link);
    });
    return strip;
  }

  function buildEconomyCaveat(workflow) {
    const caveats = [];
    if (workflow?.caveat) caveats.push(workflow.caveat);
    if (workflow?.location_coverage) caveats.push(workflow.location_coverage);
    (workflow?.value?.unknown || []).forEach((note) => {
      if (note && !caveats.includes(note)) caveats.push(note);
    });
    if (caveats.length === 0) return null;
    const details = safeEl('details', 'operations-readiness-caveat');
    details.appendChild(safeEl('summary', 'operations-readiness-caveat-summary',
      'What is not known'));
    caveats.forEach((note) => {
      details.appendChild(safeEl('p', 'operations-readiness-caveat-copy', note));
    });
    return details;
  }

  function buildEconomyShell(inputsObj, options) {
    const card = safeEl('section', options.cardClass);
    card.setAttribute('aria-label', options.ariaLabel);
    const head = safeEl('div', 'operations-economy-head');
    head.appendChild(safeEl('h3', 'operations-economy-title', options.title));
    card.appendChild(head);

    const workflow = options.workflow;
    if (!workflow) {
      /* A read in flight is not an empty workflow, and a service that did not
         answer is not an empty hold. Both are said plainly. */
      card.appendChild(safeEl('p', 'operations-economy-note',
        options.pending
          ? `Reading the ${options.noun} workflow from local state…`
          : `${options.title} not loaded. The local workflow service did not `
            + 'answer, so nothing is claimed about cargo or markets.'));
      return { card, head, workflow: null };
    }

    head.appendChild(safeEl('span', 'operations-economy-status',
      options.stageLabels[String(workflow.stage || 'unknown')]
        || options.stageLabels.unknown));
    if (workflow.stage_detail) {
      card.appendChild(safeEl('p', 'operations-economy-stage-detail',
        workflow.stage_detail));
    }
    return { card, head, workflow };
  }

  /* Market provenance, in one row that can never be mistaken for another. */
  function buildMarketRow(market) {
    if (!market) return null;
    const modifier = MARKET_SCOPE_MODIFIER[String(market.scope)] || 'absent';
    const value = market.available
      ? `${market.station_name || 'Station not checked'} · ${market.item_count} rows`
      : 'No local market snapshot loaded';
    const row = economyFactRow('Market', value, modifier);
    row.setAttribute('data-market-scope', String(market.scope || 'not_loaded'));
    return row;
  }

  function buildOpsV3TradeCard(inputsObj) {
    const { card, workflow } = buildEconomyShell(inputsObj, {
      cardClass: 'operations-trade-card operations-economy-card',
      ariaLabel: 'Trade workflow',
      title: 'Trade workflow',
      noun: 'trade',
      workflow: inputsObj?.tradeWorkflow || null,
      pending: inputsObj?.tradePending === true,
      stageLabels: TRADE_STAGE_LABELS,
    });
    if (!workflow) return card;

    const cargo = workflow.cargo || {};
    const market = workflow.market || {};

    /* Known local cargo as a workflow summary, never a manifest dump. */
    card.appendChild(economyFactRow(
      'Sellable cargo',
      cargo.observed
        ? `${cargo.sellable_tonnes} t`
        : 'Not checked',
      cargo.observed ? 'observed' : 'unknown',
    ));
    if (cargo.observed && cargo.limpets) {
      /* Limpets occupy the hold and are not freight. Saying so once here stops
         a 250-limpet hold reading as 250 t of cargo two rows down. */
      card.appendChild(economyFactRow('Limpets', `${cargo.limpets} (not cargo to sell)`));
    }
    const marketRow = buildMarketRow(market);
    if (marketRow) card.appendChild(marketRow);
    card.appendChild(economyFactRow('Snapshot scope', market.scope_label || 'Not checked',
      MARKET_SCOPE_MODIFIER[String(market.scope)] || 'absent'));

    card.appendChild(safeEl('h4', 'operations-economy-subtitle', 'Current trade step'));
    if (workflow.step) {
      card.appendChild(buildEconomyStep(workflow.step,
        'Derived from known cargo and the last observed market — not a Commander objective.'));
    } else {
      card.appendChild(safeEl('p', 'operations-economy-none',
        'No trade step derived from local state.'));
    }

    /* The sell matcher itself: at most a handful of rows, each naming whether
       the observed snapshot buys it. Intel keeps the full commodity table. */
    const matches = (workflow.matches || []).slice(0, 4);
    if (matches.length > 0) {
      card.appendChild(safeEl('h4', 'operations-economy-subtitle',
        'Cargo against the observed market'));
      const list = safeEl('ul', 'operations-economy-matches');
      matches.forEach((entry) => {
        const item = safeEl('li', 'operations-economy-match');
        item.setAttribute('data-commodity', String(entry.key || ''));
        item.setAttribute('data-buys-here', String(entry.buys_here));
        let verdict;
        if (!entry.in_snapshot) verdict = 'Not in this snapshot';
        else if (!entry.buys_here) verdict = 'Not bought here';
        else verdict = `${Number(entry.sell_price).toLocaleString()} Cr/t observed`;
        item.append(
          safeEl('span', 'operations-economy-match-name',
            `${entry.count} t ${entry.name}`),
          safeEl('span', 'operations-economy-match-verdict', verdict),
        );
        list.appendChild(item);
      });
      card.appendChild(list);
    }

    card.appendChild(safeEl('h4', 'operations-economy-subtitle', 'Work remaining'));
    const work = workflow.work_remaining || [];
    if (work.length === 0) {
      card.appendChild(safeEl('p', 'operations-economy-none',
        'No additional locally-known trade step.'));
    } else {
      card.appendChild(buildEconomyWorkList(work));
    }

    const completion = buildEconomyCompletion(workflow.completion);
    if (completion) card.appendChild(completion);

    /* Value, in three rows that must never be summed. */
    const value = workflow.value || {};
    card.appendChild(safeEl('h4', 'operations-economy-subtitle', 'Value'));
    const potential = value.potential_sale_value || {};
    card.appendChild(economyFactRow(
      'Potential at snapshot',
      typeof potential.total === 'number'
        ? `${potential.total.toLocaleString()} Cr (estimate, not earned)`
        : 'Not checked',
      'estimate',
    ));
    card.appendChild(economyFactRow(
      'Credits received',
      creditText(value.recorded_sales?.revenue),
      'earned',
    ));
    const profit = value.realised_profit || {};
    card.appendChild(economyFactRow(
      'Realised profit',
      typeof profit.value === 'number' ? `${profit.value.toLocaleString()} Cr` : 'Profit not checked',
      'earned',
    ));

    const observedStations = workflow.observed_stations || {};
    if (typeof observedStations.count === 'number') {
      card.appendChild(economyFactRow(
        'Markets you have opened',
        `${observedStations.count} station${observedStations.count === 1 ? '' : 's'}`,
      ));
    }

    const handoffs = buildEconomyHandoffs(workflow.handoffs,
      'operations-trading-workspace');
    if (handoffs) card.appendChild(handoffs);
    const caveat = buildEconomyCaveat(workflow);
    if (caveat) card.appendChild(caveat);
    return card;
  }

  function buildOpsV3MiningCard(inputsObj) {
    const { card, workflow } = buildEconomyShell(inputsObj, {
      cardClass: 'operations-mining-card operations-economy-card',
      ariaLabel: 'Mining workflow',
      title: 'Mining workflow',
      noun: 'mining',
      workflow: inputsObj?.miningWorkflow || null,
      pending: inputsObj?.miningPending === true,
      stageLabels: MINING_STAGE_LABELS,
    });
    if (!workflow) return card;

    const equipment = workflow.equipment || {};
    const limpets = workflow.limpets || {};
    const target = workflow.target || {};
    const cargo = workflow.cargo || {};

    card.appendChild(safeEl('h4', 'operations-economy-subtitle', 'Current mining step'));
    if (workflow.step) {
      card.appendChild(buildEconomyStep(workflow.step,
        'Derived from the observed loadout and known cargo — not a Commander objective.'));
    } else {
      card.appendChild(safeEl('p', 'operations-economy-none',
        'No mining step derived from local state.'));
    }

    /* Target and fill progress. The denominator is the Commander's own
       selection; without one this says so rather than inventing a target from
       whatever is largest in the hold. */
    card.appendChild(safeEl('h4', 'operations-economy-subtitle', 'Target'));
    if (target.selected) {
      const row = safeEl('div', 'operations-mining-target');
      row.setAttribute('data-target-commodity', String(target.commodity || ''));
      row.appendChild(economyFactRow(
        target.commodity,
        target.percent === null || target.percent === undefined
          ? 'Progress not checked'
          : `${target.held} of ${target.quantity} t (${target.percent}%)`,
        'observed',
      ));
      if (target.percent !== null && target.percent !== undefined) {
        const bar = safeEl('div', 'operations-mining-fill');
        bar.setAttribute('role', 'progressbar');
        bar.setAttribute('aria-valuenow', String(target.percent));
        bar.setAttribute('aria-valuemin', '0');
        bar.setAttribute('aria-valuemax', '100');
        bar.setAttribute('aria-label', `${target.commodity} fill progress`);
        const fill = safeEl('div', 'operations-mining-fill-bar');
        fill.style.width = `${target.percent}%`;
        bar.appendChild(fill);
        row.appendChild(bar);
      }
      card.appendChild(row);
    } else {
      card.appendChild(safeEl('p', 'operations-economy-none',
        target.reason || 'No target commodity selected.'));
    }

    /* Equipment, in the three states R0's shield doctrine established. A
       capability not seen in a partial loadout is Unknown, and it is rendered
       so it cannot be misread as absent. */
    card.appendChild(safeEl('h4', 'operations-economy-subtitle', 'Equipment'));
    const equipList = safeEl('ul', 'operations-mining-equipment');
    Object.entries(equipment.capabilities || {}).forEach(([name, cap]) => {
      const item = safeEl('li',
        `operations-mining-capability operations-mining-capability--${cap.state}`);
      item.setAttribute('data-capability', name);
      item.setAttribute('data-capability-state', String(cap.state));
      item.append(
        safeEl('span', 'operations-mining-capability-label', cap.label || name),
        safeEl('span', 'operations-mining-capability-state',
          FIT_STATE_LABELS[cap.state] || 'Not checked'),
      );
      equipList.appendChild(item);
    });
    card.appendChild(equipList);

    card.appendChild(economyFactRow(
      'Limpets',
      limpets.count === null || limpets.count === undefined
        ? 'Not checked'
        : String(limpets.count),
      limpets.state === 'unknown' ? 'unknown' : 'observed',
    ));
    card.appendChild(economyFactRow(
      'Hold',
      cargo.observed && cargo.capacity != null
        ? `${cargo.total_count} / ${cargo.capacity} t`
        : 'Not checked',
      cargo.observed ? 'observed' : 'unknown',
    ));

    /* Session yield: refined tonnes, and only refined tonnes. */
    const session = workflow.session || {};
    card.appendChild(economyFactRow(
      'Refined this history',
      typeof session.refined_tonnes === 'number'
        ? `${session.refined_tonnes} t`
        : 'Not checked',
      'observed',
    ));

    /* The return/sell half. Rendered only once there is something to sell, so
       Mining does not carry an inert market row through the whole run. */
    const sellMatches = (workflow.sell_matches || []).slice(0, 3);
    if (sellMatches.length > 0) {
      card.appendChild(safeEl('h4', 'operations-economy-subtitle', 'Return and sell'));
      const marketRow = buildMarketRow(workflow.market);
      if (marketRow) card.appendChild(marketRow);
      const list = safeEl('ul', 'operations-economy-matches');
      sellMatches.forEach((entry) => {
        const item = safeEl('li', 'operations-economy-match');
        item.setAttribute('data-commodity', String(entry.key || ''));
        item.append(
          safeEl('span', 'operations-economy-match-name',
            `${entry.count} t ${entry.name}`),
          safeEl('span', 'operations-economy-match-verdict',
            entry.buys_here
              ? `${Number(entry.sell_price).toLocaleString()} Cr/t observed`
              : 'Not bought here'),
        );
        list.appendChild(item);
      });
      card.appendChild(list);
    }

    card.appendChild(safeEl('h4', 'operations-economy-subtitle', 'Work remaining'));
    const work = workflow.work_remaining || [];
    if (work.length === 0) {
      card.appendChild(safeEl('p', 'operations-economy-none',
        'No additional locally-known mining step.'));
    } else {
      card.appendChild(buildEconomyWorkList(work));
    }

    const completion = buildEconomyCompletion(workflow.completion);
    if (completion) card.appendChild(completion);

    const handoffs = buildEconomyHandoffs(workflow.handoffs,
      'operations-mining-workspace');
    if (handoffs) card.appendChild(handoffs);
    const caveat = buildEconomyCaveat(workflow);
    if (caveat) card.appendChild(caveat);
    return card;
  }

  /* Combat workflow card (R7).

     Phase 4 built seven Combat cards; the Phase 7.5 v2 rebuild removed them and
     left the backend unread. They are NOT restored as seven cards — R2
     established one cockpit hierarchy, so the same facts arrive as one workflow
     card with detail disclosure beneath it.

     Three separations are held visually, because collapsing them is what made
     the old surface untrustworthy:

       * THREAT is what local detection observed. It sits in its own row and
         never appears in the blocker list;
       * READINESS is ship posture, three-state, and an Unknown row reads
         'Unknown', never a zero or a failure;
       * BLOCKERS do not render here at all. They reach the Commander through
         the one outlook card, so a fight and a broken hull are not one red
         list. */
  function buildOpsV3CombatCard(inputsObj) {
    const { card, workflow } = buildEconomyShell(inputsObj, {
      cardClass: 'operations-combat-workflow-card operations-economy-card',
      ariaLabel: 'Combat workflow',
      title: 'Combat workflow',
      noun: 'combat',
      workflow: inputsObj?.combatWorkflow || null,
      pending: inputsObj?.combatPending === true,
      stageLabels: COMBAT_STAGE_LABELS,
    });
    if (!workflow) return card;

    const threat = workflow.threat || {};
    const interdiction = workflow.interdiction || {};
    const readinessBlock = workflow.readiness || {};
    const pvp = workflow.pvp || {};

    card.appendChild(safeEl('h4', 'operations-economy-subtitle', 'Current combat step'));
    if (workflow.step) {
      card.appendChild(buildEconomyStep(workflow.step,
        'Derived from observed combat telemetry and the local loadout — not a '
        + 'Commander objective.'));
    } else {
      card.appendChild(safeEl('p', 'operations-economy-none',
        'No combat step derived from local state.'));
    }

    /* Threat, as a fact about local detection. The wording is the same one
       `deriveHostileContact` uses on the watch strip, so the two surfaces
       cannot disagree about the same reading. */
    card.appendChild(safeEl('h4', 'operations-economy-subtitle', 'Threat'));
    const threatRow = economyFactRow(
      'Hostile contact',
      threat.label || 'Hostile contact not checked',
      threat.state === 'hostile' ? 'problem'
        : (threat.state === 'clear' ? 'observed' : 'unknown'),
    );
    threatRow.setAttribute('data-threat-state', String(threat.state || 'unknown'));
    card.appendChild(threatRow);
    if (threat.detail) {
      card.appendChild(safeEl('p', 'operations-economy-note', threat.detail));
    }

    const interdictionRow = economyFactRow(
      'Interdiction',
      interdiction.label || 'Interdiction status not checked',
      interdiction.active === true ? 'problem'
        : (interdiction.observed ? 'observed' : 'unknown'),
    );
    interdictionRow.setAttribute('data-interdiction-state',
      interdiction.active === true ? 'active'
        : (interdiction.observed ? 'observed' : 'unknown'));
    card.appendChild(interdictionRow);

    /* Readiness, three-state, straight from the one readiness engine. */
    card.appendChild(safeEl('h4', 'operations-economy-subtitle', 'Ship readiness'));
    if (!readinessBlock.observed) {
      card.appendChild(safeEl('p', 'operations-economy-none',
        readinessBlock.reason || 'Ship readiness has not been checked.'));
    } else {
      const list = safeEl('ul', 'operations-combat-readiness');
      (readinessBlock.facts || []).forEach((fact) => {
        const item = safeEl('li',
          `operations-combat-fact operations-combat-fact--${fact.state}`);
        item.setAttribute('data-fact', String(fact.id));
        item.setAttribute('data-fact-state', String(fact.state));
        item.append(
          safeEl('span', 'operations-combat-fact-label', fact.label),
          safeEl('span', 'operations-combat-fact-value', fact.value),
          safeEl('span', 'operations-combat-fact-state',
            COMBAT_FACT_STATE_LABELS[fact.state] || 'Not checked'),
        );
        list.appendChild(item);
      });
      card.appendChild(list);

      /* Loadout evidence: what was SEEN fitted. A capability not listed is
         Unknown, never 'missing' — an observed loadout may still be partial. */
      const role = readinessBlock.role;
      if (role) {
        const fitted = (role.fitted || []).length;
        card.appendChild(economyFactRow(
          'Combat loadout',
          role.loadout_observed
            ? `${fitted} capability(s) observed fitted`
            : 'Not checked — no loadout observed',
          role.loadout_observed ? 'observed' : 'unknown',
        ));
      }
    }

    /* PvP, bounded to a workflow summary and stated factually. */
    card.appendChild(safeEl('h4', 'operations-economy-subtitle', 'Local PvP record'));
    if (!pvp.observed) {
      card.appendChild(safeEl('p', 'operations-economy-none',
        pvp.reason || 'Local PvP records have not been checked.'));
    } else if (!pvp.total) {
      card.appendChild(safeEl('p', 'operations-economy-none',
        'No local PvP encounters recorded.'));
    } else {
      const list = safeEl('ul', 'operations-combat-pvp');
      list.setAttribute('data-pvp-total', String(pvp.total));
      (pvp.entries || []).forEach((entry) => {
        const item = safeEl('li', 'operations-combat-pvp-entry');
        item.setAttribute('data-encounter-id', String(entry.id));
        item.append(
          safeEl('span', 'operations-combat-pvp-kind',
            PVP_ENCOUNTER_LABELS[entry.encounter_type] || PVP_ENCOUNTER_LABELS.unknown),
          safeEl('span', 'operations-combat-pvp-name',
            entry.commander_name || 'Commander not recorded'),
          safeEl('span', 'operations-combat-pvp-where', entry.system || 'System not checked'),
        );
        list.appendChild(item);
      });
      card.appendChild(list);
      if (pvp.total > (pvp.entries || []).length) {
        card.appendChild(safeEl('p', 'operations-economy-note',
          `${pvp.total} recorded in total. Open the Activity Log for the full record.`));
      }
    }

    /* Session facts — the inputs a debrief will need. Behind disclosure so
       the workflow stays a cockpit rather than a proof wall. */
    const debrief = workflow.debrief_facts;
    if (debrief) {
      const details = safeEl('details', 'operations-combat-session');
      details.appendChild(safeEl('summary', 'operations-readiness-caveat-summary',
        'This session’s combat record'));
      const rows = [
        ['Hostile events', debrief.hostile_events],
        ['Interdiction events', debrief.interdiction_events],
        ['Ship losses', debrief.ship_losses],
        ['Bounty credits redeemed', debrief.bounty_credits],
        ['Combat bond credits redeemed', debrief.bond_credits],
        ['Active missions', debrief.active_missions],
      ];
      rows.forEach(([label, value]) => {
        details.appendChild(economyFactRow(
          label,
          typeof value === 'number' ? value.toLocaleString() : 'Not checked',
          typeof value === 'number' ? 'observed' : 'unknown',
        ));
      });
      details.appendChild(safeEl('p', 'operations-readiness-caveat-copy',
        debrief.caveat || ''));
      card.appendChild(details);
    }

    card.appendChild(safeEl('h4', 'operations-economy-subtitle', 'Work remaining'));
    const work = workflow.work_remaining || [];
    if (work.length === 0) {
      card.appendChild(safeEl('p', 'operations-economy-none',
        'No additional locally-known combat step.'));
    } else {
      card.appendChild(buildEconomyWorkList(work));
    }

    const completion = buildEconomyCompletion(workflow.completion);
    if (completion) card.appendChild(completion);

    const handoffs = buildEconomyHandoffs(workflow.handoffs,
      'operations-combat-workspace');
    if (handoffs) card.appendChild(handoffs);

    /* The source boundaries, in one disclosure. Munitions, combat zones and
       AX/Odyssey are stated as unsupported here rather than rendered as empty
       rows that could be mistaken for zeros. */
    const notKnown = safeEl('details', 'operations-readiness-caveat');
    notKnown.appendChild(safeEl('summary', 'operations-readiness-caveat-summary',
      'What is not known'));
    [
      workflow.caveat,
      workflow.munitions?.detail,
      workflow.combat_zone?.detail,
      workflow.ax_odyssey,
      pvp.caveat,
    ].forEach((note) => {
      if (note) {
        notKnown.appendChild(safeEl('p', 'operations-readiness-caveat-copy', note));
      }
    });
    card.appendChild(notKnown);
    return card;
  }


  /* Active engineering task (R8 / `P14-J01`).
   *
   * The audit called the Engineering bridge "one-directional and asymmetric":
   * Engineering modelled and proved its handoff to Operations while Operations
   * offered only a bare link, in one mode, "via the card slated for deletion".
   * That card was duly deleted by R2, so by R8 the bridge was broken in BOTH
   * directions — Engineering aimed its arrival at a section id that no
   * longer existed anywhere in Operations.
   *
   * This is the missing half, and deliberately no more than that. Operations
   * shows WHICH task is active and hands back for the detail. It renders no
   * material gaps, no blueprint maths and no plan editor: Engineering owns the
   * plan, and duplicating its persistence here is an explicit STOP condition.
   */
  function buildOpsV3EngineeringTaskCard(inputsObj) {
    const payload = inputsObj?.engineeringPlans || null;
    const plans = Array.isArray(payload?.acquisition_plans)
      ? payload.acquisition_plans
      : (Array.isArray(payload) ? payload : []);
    const active = plans.filter(
      (plan) => String(plan?.state || '') === 'handoff_sent_to_operations',
    );
    if (active.length === 0) return null;

    const card = safeEl('section', 'operations-engineering-task-card');
    /* The exact section id Engineering's RouteTransferIntent targets. Without
       it the arrival banner reports the target as unavailable. */
    card.id = 'active_engineering_task';
    card.setAttribute('aria-label', 'Active engineering task');
    card.appendChild(safeEl('h3', 'operations-economy-title', 'Active engineering task'));

    const list = safeEl('ul', 'operations-engineering-task-list');
    active.slice(0, 3).forEach((plan) => {
      const item = safeEl('li', 'operations-engineering-task');
      item.setAttribute('data-plan-id', String(plan.acquisition_plan_id || ''));
      item.append(
        safeEl('span', 'operations-engineering-task-title', plan.title || 'Untitled plan'),
        safeEl('span', 'operations-engineering-task-materials',
          `${(plan.target_materials || []).length} target material(s)`),
      );
      list.appendChild(item);
    });
    card.appendChild(list);

    card.appendChild(safeEl('p', 'operations-economy-note',
      'Engineering owns the plan, its material gaps and its build detail. '
      + 'Operations tracks only which task is currently active.'));

    const strip = safeEl('nav', 'operations-economy-handoffs');
    strip.setAttribute('aria-label', 'Engineering handoffs');
    const link = safeEl('a', 'cmd-btn cmd-btn--quiet operations-economy-handoff',
      'Open the plan in Engineering');
    link.setAttribute('href', '#/engineering');
    link.setAttribute('data-handoff-id', 'engineering_plan');
    const first = active[0];
    link.addEventListener('click', (event) => {
      if (typeof window.Shell?.startRouteTransfer !== 'function') return;
      event.preventDefault();
      dispatchHandoff({
        originRoute: '/operations',
        originPackage: _manualOperation || 'idle',
        originSectionId: 'active_engineering_task',
        targetRoute: '/engineering',
        targetSectionId: 'engineering-acquisition-plans',
        targetEntityId: first?.acquisition_plan_id || '',
        targetLabel: 'Engineering acquisition plan',
        reason: 'Engineering owns the plan detail.',
        returnLabel: 'Back to Operations',
        returnTarget: { route: '/operations', sectionId: 'active_engineering_task' },
      }, {
        kind: 'engineering_plan',
        entityKind: 'acquisition_plan',
        entityId: first?.acquisition_plan_id || '',
      });
    });
    strip.appendChild(link);
    card.appendChild(strip);
    return card;
  }


  /* ──────────────────────────────────────────────
   * UI v3 Operations header helpers
   * ────────────────────────────────────────────── */

  /* Returns H1 text for the operation based on real local state only.
     Amendment 5: no auto-selection of Station; honest fallback per mode. */
  function deriveV3HeroTitle(operation, inputsObj, operationConfidence = 'unknown') {
    const st = inputsObj?.state || null;
    const lc = inputsObj?.localContext || null;
    const nav = inputsObj?.navSnap || null;
    const cargo = inputsObj?.cargo || null;

    const stationName = lc?.stationBrief?.stationName || st?.current_station || null;
    const isDocked = st?.is_docked === true || lc?.stationBrief?.isDocked === true;
    const destination = nav?.active_route?.destination || null;
    const currentSystem = st?.current_system || lc?.systemBrief?.systemName || null;
    const cargoItems = Array.isArray(cargo?.inventory) ? cargo.inventory : [];
    const topItem = cargoItems[0]?.display || cargoItems[0]?.name_localised || cargoItems[0]?.name || null;
    const operationName = _commanderVM?.operationLabel?.(operation) || 'Operations';

    if (operationConfidence === 'manual') return `${operationName} workspace.`;
    if (operationConfidence === 'suggested') return `${operationName} workspace suggested.`;

    switch (operation) {
      case 'station':
        if (isDocked && stationName) return `Docked at ${stationName}.`;
        if (isDocked) return 'Docked.';
        return 'Awaiting dock.';
      case 'mining':
        if (topItem) return `Mining ${topItem}.`;
        return 'Mining underway.';
      case 'trading':
        if (isDocked && stationName) return `Trading from ${stationName}.`;
        return 'Trading underway.';
      case 'combat':
        return 'Combat operations.';
      case 'exploration':
        if (currentSystem) return `Exploration in ${currentSystem}.`;
        if (destination) return `Plotted to ${destination}.`;
        return 'Exploration underway.';
      case 'travel':
        if (destination) return `Travelling to ${destination}.`;
        return 'Travelling.';
      case 'squadron':
        return 'Squadron coordination.';
      case 'bgs':
        return 'BGS campaign.';
      case 'powerplay':
        return 'Powerplay campaign.';
      default:
        return 'Operations';
    }
  }

  /* Returns compact one-line subtitle for the given operation.
     Amendment 3: no large hero slab — station card is the visual anchor. */
  function deriveV3Subtitle(operation, inputsObj) {
    const lc = inputsObj?.localContext || null;

    switch (operation) {
      case 'station': {
        const parts = [];
        const stationType = lc?.stationBrief?.stationType;
        const economy = lc?.stationBrief?.economySummary;
        if (stationType && stationType !== 'Unknown') parts.push(`${stationType} station`);
        if (economy && economy !== 'Unknown') parts.push(`${economy} economy`);
        const prefix = parts.join(', ');
        return prefix
          ? `${prefix}. Switch operation below, or use the quick links to dive deeper.`
          : 'Switch operation below, or use the quick links to dive deeper.';
      }
      case 'mining':
        return 'Track cargo, threat status, and market access from local state.';
      case 'trading':
        return 'Track cargo and market access from local state.';
      case 'combat':
        return 'Monitor threat status and ship readiness from local state.';
      case 'exploration':
        return 'Track discovery context and route from local state.';
      case 'travel':
        return 'Monitor route and safety from local state.';
      case 'squadron':
        return 'Local coordination only. No outbound transport in this build.';
      case 'bgs':
        return 'Local BGS campaign objectives. Intel owns facts. No outbound calls.';
      case 'powerplay':
        return 'Local Powerplay campaign objectives. Intel owns facts. No outbound calls.';
      default:
        return 'Manage active tasks, readiness, and next actions from local state.';
    }
  }

  /* Compact v3 header zone: breadcrumb + h1#operations-title + subtitle.
     Amendment 3: the header stays compact; the station card is the visual anchor. */
  function buildOpsV3Header(operation, ctx, inputsObj) {
    const header = safeEl('div', 'ops-v3-header route-header');
    const operationConfidence = ctx?.operationConfidence || 'unknown';
    header.setAttribute('data-operation-confidence', operationConfidence);

    /* Compact breadcrumb (mono, small, dim) */
    const breadcrumb = safeEl('p', 'ops-v3-breadcrumb');
    breadcrumb.appendChild(safeEl('span', 'ops-v3-breadcrumb-root', 'OPERATIONS'));
    const opName = _commanderVM?.operationLabel?.(operation);
    if (opName) {
      const sep = safeEl('span', 'ops-v3-breadcrumb-sep', '›');
      sep.setAttribute('aria-hidden', 'true');
      breadcrumb.appendChild(sep);
      breadcrumb.appendChild(safeEl('span', 'ops-v3-breadcrumb-leaf', opName.toUpperCase()));
    }
    header.appendChild(breadcrumb);

    /* Hero row: title left. Interrupts are owned by createInterruptBanner. */
    const heroRow = safeEl('div', 'ops-v3-hero-row');

    const heroLeft = safeEl('div', 'ops-v3-hero-left');
    const h1 = safeEl('h1', 'ops-v3-title',
      deriveV3HeroTitle(operation, inputsObj, operationConfidence));
    h1.id = 'operations-title';
    heroLeft.appendChild(h1);
    heroLeft.appendChild(safeEl('p', 'ops-v3-subtitle', deriveV3Subtitle(operation, inputsObj)));
    heroRow.appendChild(heroLeft);
    heroRow.appendChild(safeEl(
      'span',
      'ops-v3-confidence-pill',
      `MODE · ${operationConfidence.toUpperCase()}`,
    ));

    header.appendChild(heroRow);
    return header;
  }

  function deriveSinceLabel(operation) {
    const labels = {
      station: 'SINCE LAST DOCK EVENT',
      mining: 'SINCE LAST CARGO EVENT',
      trading: 'SINCE LAST CARGO EVENT',
      combat: 'SINCE LAST COMBAT EVENT',
      exploration: 'SINCE LAST SCAN EVENT',
      travel: 'SINCE LAST JUMP EVENT',
      squadron: 'SINCE LAST SESSION EVENT',
    };
    return labels[operation] || '— SINCE LAST EVENT';
  }

  /* Mode selector bar: OPERATION label + 8 chips (reused createOperationSelector) + since label. */
  function buildOpsV3ModeBar(currentOperation, onSelect) {
    const bar = safeEl('div', 'ops-v3-mode-bar route-subnav');
    bar.appendChild(safeEl('span', 'ops-v3-mode-label', 'OPERATION'));

    if (_primitives && _commanderVM) {
      const { createOperationSelector } = _primitives;
      const { SELECTABLE_OPERATIONS, operationLabel } = _commanderVM;
      bar.appendChild(createOperationSelector({
        operations: SELECTABLE_OPERATIONS.map(op => ({ id: op, label: operationLabel(op) })),
        current: currentOperation,
        onSelect,
      }));
    }

    bar.appendChild(safeEl('span', 'ops-v3-mode-since', deriveSinceLabel(currentOperation)));
    return bar;
  }

  /* ──────────────────────────────────────────────
   * Station mode body helpers
   * ────────────────────────────────────────────── */

  /* Supporting context band (R2-8). Rendered after the workflow band in every
     mode, never before it. Returns null when the mode has none, so no empty
     scaffolding is drawn. */
  function buildOpsV3SupportingContext(operation, inputsObj) {
    if (operation !== 'station') return null;

    const wrap = safeEl('section', 'ops-v3-supporting-context');
    wrap.setAttribute('aria-label', 'Supporting context');

    /* PB-PHASE10-SUPER-03 #5: Station is not a true operation. It is shown here
       as a temporary docked-context surface; full station / local intelligence
       is planned to move to Intel (which already owns a Station briefing). This
       note demotes it honestly until that migration lands. */
    wrap.appendChild(safeEl('p', 'ops-v3-station-demote-note',
      'Temporary docked context. Station and local intelligence will move to Intel in a future update.'));

    const grid = safeEl('div', 'ops-v3-body-grid');
    grid.setAttribute('aria-label', 'Docked context detail');
    grid.appendChild(buildOpsV3StationCard(inputsObj));

    const rightCol = safeEl('div', 'ops-v3-right-col');
    /* R2-5: the private Cargo card is gone. Cargo is answered once at a glance
       by the watch strip and once in workflow context by the Cargo support
       card; a third card repeating "0 / 400 t" served no separate decision.
       R2-3: the static NEXT ACTIONS card is gone; its four links live in the
       one canonical action surface above. */
    rightCol.appendChild(buildOpsV3RecentActivityCard(inputsObj));
    grid.appendChild(rightCol);

    wrap.appendChild(grid);
    return wrap;
  }

  /* Current Station card (~60% width). All fields from real local state or honest fallback. */
  function buildOpsV3StationCard(inputsObj) {
    const sb = inputsObj.localContext?.stationBrief || null;
    const st = inputsObj.state || null;

    const card = safeEl('article', 'ops-v3-station-card');
    card.setAttribute('aria-label', 'Current station');

    /* Eyebrow row */
    const eyebrowRow = safeEl('div', 'ops-v3-card-eyebrow-row');
    eyebrowRow.appendChild(safeEl('span', 'ops-v3-card-eyebrow', 'CURRENT STATION'));
    const rawTs = sb?.proof?.timestamp || null;
    let displayTs = '—';
    if (rawTs) {
      const timePart = rawTs.replace(/^[^T]+T/, '').replace(/\.\d+Z?$/, '');
      displayTs = timePart.slice(0, 5) + 'Z';
    }
    eyebrowRow.appendChild(safeEl('span', 'ops-v3-card-timestamp', `SNAPSHOT \xB7 ${displayTs}`));
    card.appendChild(eyebrowRow);

    /* Station name */
    const stationName = sb?.stationName || st?.current_station || 'Station not checked';
    card.appendChild(safeEl('h2', 'ops-v3-station-name', stationName));

    /* Description composed from real fields only — never hardcoded screenshot values */
    const descParts = [];
    if (sb?.stationType && sb.stationType !== 'Unknown') descParts.push(sb.stationType);
    if (sb?.economySummary && sb.economySummary !== 'Unknown') descParts.push(`${sb.economySummary} economy`);
    if (sb?.factionSummary && sb.factionSummary !== 'Unknown') descParts.push(sb.factionSummary);
    card.appendChild(safeEl('p', 'ops-v3-station-desc',
      descParts.length ? descParts.join(', ') + '.' : 'Station context not yet loaded.'));

    /* Fact grid — 6 self-contained visual units per RUNTIME_UI_REPAIR_DOCTRINE */
    const factGrid = safeEl('div', 'ops-v3-fact-grid');
    factGrid.setAttribute('role', 'list');

    function detailVal(rowLabel) {
      return sb?.detailRows?.find(r => r.label === rowLabel)?.value || '—';
    }

    const isDocked = st?.is_docked === true || sb?.isDocked === true;
    const dockingText = sb?.dockedLabel || (isDocked ? 'Docked' : '—');

    const facts = [
      { label: 'TYPE',              value: (sb?.stationType && sb.stationType !== 'Unknown') ? sb.stationType : '—' },
      { label: 'DISTANCE FROM STAR', value: detailVal('Distance from star') },
      { label: 'ECONOMY',           value: (sb?.economySummary && sb.economySummary !== 'Unknown') ? sb.economySummary : '—' },
      { label: 'DOCKING',           value: dockingText, ok: isDocked },
      { label: 'GOVERNMENT',        value: detailVal('Government') },
      { label: 'FACTION',           value: (sb?.factionSummary && sb.factionSummary !== 'Unknown') ? sb.factionSummary : '—' },
    ];

    facts.forEach(f => {
      const unit = safeEl('div', 'ops-v3-fact-unit');
      unit.setAttribute('role', 'listitem');
      unit.appendChild(safeEl('span', 'ops-v3-fact-label', f.label));
      unit.appendChild(safeEl('span', `ops-v3-fact-value${f.ok ? ' ops-v3-fact-value--ok' : ''}`, f.value));
      factGrid.appendChild(unit);
    });
    card.appendChild(factGrid);

    /* Services chip cloud */
    const services = Array.isArray(sb?.services) ? sb.services : [];
    if (services.length > 0) {
      card.appendChild(safeEl('p', 'ops-v3-services-head', 'SERVICES'));
      const cloud = safeEl('div', 'ops-v3-services-cloud');

      const CHIP_LIMIT = 11;
      services.slice(0, CHIP_LIMIT).forEach(svc => {
        cloud.appendChild(safeEl('span', 'ops-v3-service-chip', svc.label));
      });

      const overflow = services.slice(CHIP_LIMIT);
      if (overflow.length > 0) {
        const overflowWrap = safeEl('div', 'ops-v3-services-overflow');
        overflow.forEach(svc => {
          overflowWrap.appendChild(safeEl('span', 'ops-v3-service-chip', svc.label));
        });
        const moreChip = safeEl('button', 'ops-v3-service-chip ops-v3-service-chip--more',
          `+${overflow.length} more`);
        moreChip.setAttribute('type', 'button');
        moreChip.addEventListener('click', () => overflowWrap.classList.toggle('is-open'));
        cloud.appendChild(moreChip);
        cloud.appendChild(overflowWrap);
      }
      card.appendChild(cloud);
    }

    /* Footer: freshness summary | DETAILS | Open station brief (→ Intel) */
    const footer = safeEl('div', 'ops-v3-card-footer');

    const raw = inputs.localContextRaw || {};
    const freshnessItems = [
      ['Market', raw.market_snapshot],
      ['Outfitting', raw.outfitting_snapshot],
      ['Shipyard', raw.shipyard_snapshot],
    ].map(([label, source]) => `${label}: ${_primitives.freshnessLabel(source || 'not_loaded')}`);
    footer.appendChild(safeEl('div', 'ops-v3-freshness',
      freshnessItems.join(' \xB7 ')));

    const detailsBtn = safeEl('button', 'ops-v3-details-link', 'DETAILS');
    detailsBtn.setAttribute('type', 'button');
    detailsBtn.addEventListener('click', () => {
      const proofEl = card.closest('.operations-workspace')?.querySelector('.proof-toggle');
      if (proofEl) proofEl.setAttribute('open', '');
    });
    footer.appendChild(detailsBtn);

    /* Intel owns Station Brief — this is a link, not an embedded panel */
    const briefLink = safeEl('a', 'ops-v3-station-brief-btn', 'Open station brief ›');
    briefLink.setAttribute('href', '#/intel');
    footer.appendChild(briefLink);

    card.appendChild(footer);
    return card;
  }

  /* Recent Activity card (right column, bottom). Activity Log remains the proof
     owner; this is a bounded read of it, never a second event store.

     R0-2: this card previously asserted "No recent activity." unconditionally,
     while the same backend reported 250 entries. Absence of a query is not
     evidence of absence, so the card now distinguishes three states: entries
     read, a verified empty log, and a log that could not be read. */
  function buildOpsV3RecentActivityCard(inputsObj) {
    const card = safeEl('article', 'ops-v3-recent-activity-card');
    card.setAttribute('aria-label', 'Recent activity');
    card.appendChild(safeEl('p', 'ops-v3-card-title', 'RECENT ACTIVITY'));

    const log = inputsObj?.activityLog || null;

    if (!log || !Array.isArray(log.entries)) {
      card.appendChild(safeEl('p', 'ops-v3-card-body', 'Activity not loaded.'));
      card.appendChild(safeEl('p', 'ops-v3-card-sub',
        'The Activity Log could not be read here. Open the Activity Log for proof.'));
    } else if (log.entries.length === 0) {
      card.appendChild(safeEl('p', 'ops-v3-card-body', 'No recent activity.'));
      card.appendChild(safeEl('p', 'ops-v3-card-sub',
        'The Activity Log reported no entries.'));
    } else {
      /* Concise by design: the cockpit shows the most recent few, never an
         audit table. Activity Log owns the full proof surface. */
      const list = safeEl('ul', 'ops-v3-recent-activity-list');
      log.entries.slice(0, 3).forEach((entry) => {
        const item = safeEl('li', 'ops-v3-recent-activity-item');
        item.append(
          safeEl('span', 'ops-v3-recent-activity-type',
            entry?.event_type || 'Event type not recorded'),
          safeEl('span', 'ops-v3-recent-activity-time',
            entry?.timestamp || 'Time not recorded'),
        );
        list.appendChild(item);
      });
      card.appendChild(list);
      const total = typeof log.total === 'number' ? log.total : log.entries.length;
      card.appendChild(safeEl('p', 'ops-v3-card-sub',
        `${total} entr${total === 1 ? 'y' : 'ies'} in the Activity Log.`));
    }

    const logLink = safeEl('a', 'ops-v3-card-footer-link', 'OPEN LOG ›');
    logLink.setAttribute('href', '#/activity-log');
    card.appendChild(logLink);

    return card;
  }

  /* ──────────────────────────────────────────────
   * Idle selector (Correction #7 — preserved exactly, now uses v3 chrome)
   * ────────────────────────────────────────────── */
  function renderIdleSelector() {
    const root = getRoot();
    if (!root || !_primitives || !_commanderVM) return;
    const { createOperationSelector } = _primitives;
    const { SELECTABLE_OPERATIONS, operationLabel } = _commanderVM;

    const wrap = safeEl('section', 'operations-workspace operations-workspace--idle');
    wrap.setAttribute('aria-labelledby', 'operations-title');
    wrap.setAttribute('data-operation', 'idle');

    /* Compact v3 header — no hero slab (Amendment 3), honest idle copy (Amendment 5) */
    const hdr = safeEl('div', 'ops-v3-header');

    const breadcrumb = safeEl('p', 'ops-v3-breadcrumb');
    breadcrumb.appendChild(safeEl('span', 'ops-v3-breadcrumb-root', 'OPERATIONS'));
    hdr.appendChild(breadcrumb);

    const h1 = safeEl('h1', 'ops-v3-title', 'Operations');
    h1.id = 'operations-title';
    hdr.appendChild(h1);

    hdr.appendChild(safeEl('p', 'ops-v3-subtitle',
      'No active operation. Select an operation to focus the command deck.'));
    wrap.appendChild(hdr);

    /* Mode bar — wraps the operation selector (no watch-strip, no support-card, no quick-tools) */
    const bar = safeEl('div', 'ops-v3-mode-bar');
    bar.appendChild(safeEl('span', 'ops-v3-mode-label', 'OPERATION'));
    bar.appendChild(createOperationSelector({
      operations: SELECTABLE_OPERATIONS.map(op => ({ id: op, label: operationLabel(op) })),
      current: 'idle',
      onSelect: selectOperation,
    }));
    wrap.appendChild(bar);

    /* R2-2: the default route was a bare mode picker, which is not a cockpit.
       It now answers "where am I, what needs attention, what can I do" from
       state Operations already holds — no new fetch, and nothing mode-specific,
       because no mode is selected. It deliberately stays short: one status
       band, attention only when there is some, and the entry points. */
    wrap.appendChild(buildOpsV3DefaultBriefing());

    root.replaceChildren(wrap);
    /* PB09-08: apply route-transfer arrival banner */
    if (typeof window.Shell?.applyRouteTransferArrival === 'function') {
      window.Shell.applyRouteTransferArrival('/operations', root);
    }
  }

  /* Default-surface briefing (R2-2).
   *
   * PB14-00 obliges the Operations default to prioritise state, attention and
   * next actions; it was a bare mode picker (`P14-A05` MISSING, `P14-T01`
   * "the first screen is a menu"). This makes it answer the cockpit questions
   * that are answerable with no operation selected — where am I, what needs
   * attention, what can I do — using the same primitives every mode uses.
   *
   * Three things it deliberately does NOT do: it does not fabricate an
   * objective — R3 gives it real ones to show, and it shows only those the
   * Commander actually typed; it does not suggest or reopen an operation,
   * which the Commander explicitly forbade (Smoke R3, selector-first), so the
   * objectives below are stated, not offered as controls; and it does not
   * become a dashboard — no support cards, no readiness fetch, no proof wall. */
  function buildOpsV3DefaultBriefing() {
    const section = safeEl('section', 'ops-v3-default-briefing');
    section.setAttribute('aria-label', 'Current state');
    if (!_commanderVM || !_primitives) return section;

    const { deriveCommanderContext } = _commanderVM;
    const { createCommandContextSpine, createInterruptBanner } = _primitives;
    /* Null operation: the derived *suggestion* is deliberately not read here. */
    const ctx = deriveCommanderContext(inputs, null);

    /* Attention first, and only when local state actually reports some. */
    const banner = createInterruptBanner(ctx.interrupts, {
      onResolveAction: { label: 'Open Activity Log', href: '#/activity-log' },
    });
    if (banner) section.appendChild(banner);

    section.appendChild(safeEl('h2', 'ops-v3-default-heading', 'Current state'));
    section.appendChild(createCommandContextSpine(ctx.contextSpine, {
      ariaLabel: 'Current commander state',
    }));

    const objectives = buildOpsV3DefaultObjectives();
    if (objectives) section.appendChild(objectives);

    /* One concise empty-state explanation — not a wall of "No objective / no
       blockers / no actions". */
    section.appendChild(safeEl('p', 'ops-v3-default-note',
      ctx.interrupts.length > 0
        ? 'No operation is selected, so no workflow state is shown. The attention above is '
          + 'shared local state. Choose an operation to focus the deck.'
        : 'No operation is selected, so no workflow state is shown. Choose an operation '
          + 'above to focus the deck on it.'));

    return section;
  }

  /* Standing Commander objectives on the default surface (R3).
   *
   * PB14-R1 scopes an objective to one operation mode, so there is no single
   * global objective to show here. What is honest, and what a Commander opening
   * the cockpit actually wants, is the set of intentions they have already
   * stated — so this lists exactly those and nothing else.
   *
   * It renders no control. R2 preserved the Commander's selector-first
   * instruction that Operations must never reopen a mode for them, and a row
   * that jumps into a workspace would be a second selector wearing an
   * objective's clothes. The mode is named; the selector is directly above.
   *
   * Absence stays absence: with no objectives set this renders nothing rather
   * than a "No objective" wall. */
  function buildOpsV3DefaultObjectives() {
    const index = inputs.objectivesIndex;
    if (!index) return null;

    if (index.available === false) {
      const unknown = safeEl('section', 'ops-v3-default-objectives');
      unknown.setAttribute('aria-label', 'Standing objectives');
      unknown.appendChild(safeEl('h3', 'ops-v3-default-subheading', 'Your objectives'));
      unknown.appendChild(safeEl('p', 'ops-v3-default-note',
        'The local objective store did not answer, so whether you have set any '
        + 'objectives is unknown. This is not the same as having none.'));
      return unknown;
    }

    const entries = Object.entries(index.objectives || {})
      .filter(([operation, record]) => operation && record && record.text);
    if (entries.length === 0) return null;

    const section = safeEl('section', 'ops-v3-default-objectives');
    section.setAttribute('aria-label', 'Standing objectives');
    section.appendChild(safeEl('h3', 'ops-v3-default-subheading', 'Your objectives'));
    const list = safeEl('ul', 'ops-v3-default-objective-list');
    entries.forEach(([operation, record]) => {
      const item = safeEl('li', 'ops-v3-default-objective');
      item.setAttribute('data-objective-operation', operation);
      if (record.objective_id) {
        item.setAttribute('data-commander-objective-id', String(record.objective_id));
      }
      if (record.state) item.setAttribute('data-objective-state', String(record.state));
      item.append(
        safeEl('span', 'ops-v3-default-objective-mode',
          _commanderVM?.operationLabel?.(operation) || operation),
        safeEl('span', 'ops-v3-default-objective-text', record.text),
      );
      if (record.state === 'completed') {
        item.classList.add('ops-v3-default-objective--completed');
        item.appendChild(safeEl('span', 'ops-v3-default-objective-state', 'Completed'));
      }
      list.appendChild(item);
    });
    section.appendChild(list);
    section.appendChild(safeEl('p', 'ops-v3-default-note',
      'You entered these. OmniCOVAS did not verify them, and they are held on '
      + 'this machine only.'));
    return section;
  }

  /* ──────────────────────────────────────────────
   * Mode-specific state resolution (R1-1)
   *
   * Readiness and the exploration snapshot answer a question about ONE
   * operation. They were previously read once, for `idle`, and never read
   * again: selecting Trading re-rendered the deck around the idle readiness
   * profile, and the blockers and next actions derived from it, with nothing
   * to say the answer belonged to another operation.
   *
   * The contract now is: selecting a mode invalidates every mode-specific
   * input before the first frame of that mode is drawn, re-reads only what the
   * new mode actually needs, and discards any answer that arrives after the
   * Commander has moved on. Shared state (ship, cargo, navigation, combat,
   * local context, activity log) is not re-fetched — it is not mode-specific,
   * and the event bindings already refresh it.
   * ────────────────────────────────────────────── */

  /* Modes that render a readiness card. The selector-only idle surface and the
     Phase 9 campaign surfaces render none, so neither is asked for one. */
  function needsModeInputs(operation) {
    return !!operation
      && operation !== 'idle'
      && !PHASE9_SESSION_ONLY_MODES.has(operation);
  }

  function invalidateModeInputs(operation) {
    const pending = needsModeInputs(operation);
    inputs.readiness = null;
    inputs.readinessPending = pending;
    inputs.explorationSnapshot = null;
    inputs.explorationPending = pending && operation === 'exploration';
    inputs.tradeWorkflow = null;
    inputs.tradePending = pending && operation === 'trading';
    inputs.miningWorkflow = null;
    inputs.miningPending = pending && operation === 'mining';
    inputs.combatWorkflow = null;
    inputs.combatPending = pending && operation === 'combat';
    /* R3: the objective is mode-specific state, so the previous mode's stated
       intent must not survive the switch. It is invalidated here and re-read
       for the new mode; until it answers the slot reads Loading, never the
       objective that belonged to the mode the Commander just left. */
    inputs.commanderObjective = null;
    inputs.commanderObjectivePending = pending;
  }

  async function loadOperationInputs(operation) {
    const [
      readiness, explorationSnapshot, commanderObjective, tradeWorkflow, miningWorkflow,
      combatWorkflow,
    ] = await Promise.all([
      fetchJson(`/readiness?operation=${encodeURIComponent(operation)}`),
      /* PB05-08's exploration snapshot is Exploration-only; no other mode
         renders it, so no other mode asks for it. */
      operation === 'exploration'
        ? fetchJson('/operations/exploration/snapshot')
        : Promise.resolve(null),
      /* R3: the mode's persisted Commander objective, read in the same round
         trip as readiness so one selection resolves one coherent frame. */
      fetchJson(`/operations/objectives/${encodeURIComponent(operation)}`),
      /* R6: each economic workflow is read only by the mode that renders it. */
      operation === 'trading'
        ? fetchJson('/operations/trade/workflow')
        : Promise.resolve(null),
      operation === 'mining'
        ? fetchJson('/operations/mining/workflow')
        : Promise.resolve(null),
      /* R7: Combat reads its workflow in the same round trip, so one selection
         resolves one coherent frame rather than a card that fills in late. */
      operation === 'combat'
        ? fetchJson('/operations/combat/workflow')
        : Promise.resolve(null),
    ]);
    return {
      readiness, explorationSnapshot, commanderObjective, tradeWorkflow, miningWorkflow,
      combatWorkflow,
    };
  }

  /* Resolves mode-specific inputs for `operation`. Returns true only when the
     answers were applied — a caller re-renders on true, and a late answer for
     an abandoned mode returns false rather than being drawn under the mode the
     Commander has since selected. */
  async function refreshOperationInputs(operation) {
    if (!needsModeInputs(operation)) return false;
    const resolved = await loadOperationInputs(operation);
    if (_manualOperation !== operation) return false;
    inputs.readiness = resolved.readiness;
    inputs.readinessPending = false;
    inputs.explorationSnapshot = resolved.explorationSnapshot;
    inputs.explorationPending = false;
    inputs.tradeWorkflow = resolved.tradeWorkflow;
    inputs.tradePending = false;
    inputs.miningWorkflow = resolved.miningWorkflow;
    inputs.miningPending = false;
    inputs.combatWorkflow = resolved.combatWorkflow;
    inputs.combatPending = false;
    inputs.commanderObjective = resolved.commanderObjective;
    inputs.commanderObjectivePending = false;
    return true;
  }

  function selectOperation(id) {
    _manualOperation = id;
    writeManualOperation(id);
    /* Invalidate first: no readiness, blocker or next action from the previous
       mode may survive into this render. */
    invalidateModeInputs(id);
    /* A half-typed objective belongs to the mode it was being typed for. */
    resetObjectiveEditor();
    renderWorkspace(id);
    /* The promise is returned so tests can await the resolved render instead of
       guessing at timing; the selector itself ignores it. */
    return refreshOperationInputs(id).then((applied) => {
      if (applied && getRoot() !== null) renderWorkspace(id);
      return applied;
    });
  }

  /* ──────────────────────────────────────────────
   * Main workspace renderer (UI v3 restructured)
   * ────────────────────────────────────────────── */
  function renderWorkspace(operation) {
    if (operation === null || operation === undefined || operation === 'idle') {
      renderIdleSelector();
      return;
    }

    const root = getRoot();
    if (!root || !_primitives || !_commanderVM || !_workspaceVM) return;

    /* Phase 9 campaign modes: async fetch then render. No localStorage persistence.
       Selector-first idle contract preserved — renders only on explicit selection. */
    if (PHASE9_SESSION_ONLY_MODES.has(operation)) {
      // Show loading placeholder immediately (synchronous)
      const placeholder = safeEl('section', 'operations-workspace operations-workspace--phase9-loading');
      placeholder.setAttribute('aria-labelledby', 'operations-title');
      const ph1 = safeEl('h1', 'ops-v3-title', operation === 'bgs' ? 'BGS Campaign' : 'Powerplay Campaign');
      ph1.id = 'operations-title';
      placeholder.appendChild(ph1);
      placeholder.appendChild(safeEl('p', 'ops-phase9-loading', 'Loading campaign…'));
      root.replaceChildren(placeholder);
      // PB09-08: read inbound route-transfer intent to optionally fetch a specific campaign by id
      const _inboundIntent = typeof window.Shell?.getRouteTransferIntent === 'function'
        ? window.Shell.getRouteTransferIntent('/operations')
        : null;
      const _requestedCampaignId = _inboundIntent?.targetEntityId || null;
      // Async: fetch and render
      fetchActivePhase9Campaign(operation, _requestedCampaignId).then(campaign => {
        if (getRoot() !== null && _manualOperation === operation) {
          renderPhase9CampaignWorkspace(getRoot(), operation, campaign);
        }
      });
      return;
    }

    const {
      createCommandContextSpine,
      createWatchStrip,
      createInterruptBanner,
      createSupportCard,
      createPrimaryActionBlock,
      createDetailDrawer,
      createProofToggle,
    } = _primitives;

    const { deriveCommanderContext } = _commanderVM;
    const { deriveWorkspace } = _workspaceVM;

    inputs.sessionState = window.Shell?.eliteSessionState || inputs.sessionState;
    const ctx = deriveCommanderContext(inputs, operation);
    const ws  = deriveWorkspace(ctx.primaryOperation, inputs);

    const wrap = safeEl('section', 'operations-workspace');
    wrap.setAttribute('aria-labelledby', 'operations-title');
    wrap.setAttribute('data-operation', ctx.primaryOperation);
    wrap.setAttribute('data-operation-confidence', ctx.operationConfidence);
    wrap.id = `operations-${ctx.primaryOperation}-workspace`;

    /* 1. Interrupt banner (elevated over all content).
       ALERT_OWNERSHIP_01: critical alerts (e.g. fuel critical) are shared
       attention state, not owned by Operations. The banner shows them but no
       longer changes the selected operation; its detail affordance routes to
       the Activity Log (the proof layer), never a fabricated remediation. */
    const banner = createInterruptBanner(ctx.interrupts, {
      onResolveAction: { label: 'Open Activity Log', href: '#/activity-log' },
    });
    if (banner) wrap.appendChild(banner);

    /* 2. Compact v3 header (breadcrumb + h1#operations-title + subtitle + alert pill) */
    wrap.appendChild(buildOpsV3Header(ctx.primaryOperation, ctx, inputs));

    /* 3. Mode selector bar (OPERATION label + 8 chips + since label) */
    const onSelect = selectOperation;
    wrap.appendChild(buildOpsV3ModeBar(ctx.primaryOperation, onSelect));

    /* 4. Body — ONE skeleton for every mode (R2-1, R2-8).
       Docked Context used to diverge into a private two-column layout with its
       own Cargo, Next Actions and Recent Activity cards, so the Commander met a
       different cockpit grammar there and two answers to "what next?". Every
       mode now reads in the same order:

         state at a glance  →  workflow (objective, readiness, blockers,
         next actions)  →  supporting context  →  detail / proof

       Supporting context is rendered AFTER the workflow band in every mode, so
       station detail, market context and history can never outrank the thing
       the Commander is being asked to decide. */
    wrap.appendChild(createWatchStrip(ctx.watch));
    if (ctx.primaryOperation !== 'station') {
      wrap.appendChild(createCommandContextSpine(ctx.contextSpine));
    }

    /* R4-1: Commander intent, directly beneath the factual state strip and
       above the primary action and readiness. Attention (the watch strip) stays
       first, because a safety interrupt must never sit below a goal. */
    const objectiveBand = buildObjectiveBand(ws.outlook?.goal);
    if (objectiveBand) wrap.appendChild(objectiveBand);

    const primaryAction = createPrimaryActionBlock(ws.action
      ? {
        label: ws.action.label,
        route: ws.action.route,
        onClick: ws.action.operation ? () => selectOperation(ws.action.operation) : undefined,
      }
      : null);
    if (primaryAction) wrap.appendChild(primaryAction);

    /* PB14-02 first slice: state-backed readiness card (LNA-028). */
    const readinessCard = buildReadinessCard(ws.readiness);
    if (readinessCard) wrap.appendChild(readinessCard);

    /* PB14-02: the one objective / blockers / next-actions surface. */
    const outlookCard = buildWorkflowOutlookCard(ws.outlook);
    if (outlookCard) wrap.appendChild(outlookCard);

    /* R1-2: the PB05-08 exploration snapshot, finally rendered. */
    if (ctx.primaryOperation === 'exploration') {
      wrap.appendChild(buildOpsV3ExplorationCard(inputs));
    }

    /* R6: the economic workflows sit in the same slot the exploration workflow
       occupies — after the one blockers/next-actions card, before supporting
       context. One card per mode, never both. */
    if (ctx.primaryOperation === 'trading') {
      wrap.appendChild(buildOpsV3TradeCard(inputs));
    }
    if (ctx.primaryOperation === 'mining') {
      wrap.appendChild(buildOpsV3MiningCard(inputs));
    }

    /* R7: Combat occupies the same slot. It sits AFTER the outlook card on
       purpose — blockers and next actions are the outlook card's to own, so a
       threat row inside this card can never be mistaken for one of them. */
    if (ctx.primaryOperation === 'combat') {
      wrap.appendChild(buildOpsV3CombatCard(inputs));
    }

    /* R8: cross-cutting, so it is not gated on a mode — an engineering task
       handed to Operations is active whatever the Commander is doing. */
    const engineeringTask = buildOpsV3EngineeringTaskCard(inputs);
    if (engineeringTask) wrap.appendChild(engineeringTask);

    const supportsRegion = safeEl('section', 'operations-supports');
    supportsRegion.setAttribute('role', 'region');
    supportsRegion.setAttribute('aria-label', 'Support systems');
    ws.supports.forEach(s => supportsRegion.appendChild(createSupportCard(
      /* R2-9: a support whose target is another Operations mode opens as a
         control; only real cross-route targets keep an href. */
      s.operation ? { ...s, route: null, onOpen: () => selectOperation(s.operation) } : s,
    )));
    wrap.appendChild(supportsRegion);

    /* Supporting context, subordinate by position and by weight. */
    const supporting = buildOpsV3SupportingContext(ctx.primaryOperation, inputs);
    if (supporting) wrap.appendChild(supporting);

    const localWorkspace = buildLocalContextWorkspace(ctx.primaryOperation);
    if (localWorkspace) wrap.appendChild(localWorkspace);

    /* 5. Detail drawer (collapsed by default) */
    wrap.appendChild(createDetailDrawer({
      summary: 'Details',
      content: buildOperationDetail(ctx.primaryOperation),
    }));

    /* 6. Proof toggle (source posture, collapsed by default, never a default wall) */
    wrap.appendChild(createProofToggle(buildProofContent(ctx.primaryOperation), 'Proof'));

    /* 7. Back to selector */
    const footer = safeEl('footer', 'operations-workspace-footer');
    const back = safeEl('button', 'operations-selector-back', 'Back to Operations selector');
    back.type = 'button';
    back.addEventListener('click', () => {
      _manualOperation = null;
      writeManualOperation(null);
      renderIdleSelector();
    });
    footer.appendChild(back);
    wrap.appendChild(footer);

    root.replaceChildren(wrap);
    /* PB09-08: apply route-transfer arrival banner */
    if (typeof window.Shell?.applyRouteTransferArrival === 'function') {
      window.Shell.applyRouteTransferArrival('/operations', root);
    }
  }

  /* ──────────────────────────────────────────────
   * Phase 9 campaign workspace renderers (PB09-03)
   * ADR 0003: createElement + textContent only. No innerHTML.
   * No localStorage auto-reopen (PHASE9_SESSION_ONLY_MODES guard above).
   * Selector-first idle contract: these render only when mode is explicitly selected.
   * ────────────────────────────────────────────── */

  /* Fetch a Phase 9 campaign for a workflow type from the local API.
     If campaignId is provided, fetches that specific campaign (PB09-08 arrival handling).
     Falls back to first active campaign for the workflowType if not found or omitted.
     Returns a single campaign record or null. */
  async function fetchActivePhase9Campaign(workflowType, campaignId) {
    const base = apiBase();
    if (!base) return null;
    try {
      if (campaignId) {
        const r = await fetch(`${base}/operations/phase9/campaigns/${encodeURIComponent(String(campaignId))}`);
        if (r.ok) return await r.json();
      }
      /* R8: this asked for `state=active&limit=1`, so a BLOCKED campaign was
         invisible — the Commander could not see the thing that was blocking
         them, which is most of what `P14-K02` asks the workspace to answer.
         Live states are fetched instead, and `active` still wins when both
         exist: a campaign in motion outranks one waiting on something. */
      const r = await fetch(
        `${base}/operations/phase9/campaigns?workflow_type=${workflowType}&limit=25`
      );
      if (!r.ok) return null;
      const data = await r.json();
      const campaigns = Array.isArray(data?.campaigns) ? data.campaigns : [];
      const live = campaigns.filter(
        (c) => c?.state === 'active' || c?.state === 'blocked' || c?.state === 'proposed',
      );
      return live.find((c) => c.state === 'active')
        || live.find((c) => c.state === 'blocked')
        || live[0]
        || null;
    } catch {
      return null;
    }
  }

  /* Render a Phase 9 campaign workspace body into root.
     campaign: single campaign record from API, or null if none active.
     All text rendered via textContent — no innerHTML anywhere.
     State pills use className only (no state text in innerHTML). */
  function renderPhase9CampaignWorkspace(root, workflowType, campaign) {
    const operation = workflowType;

    if (!root) return;

    const onSelect = selectOperation;

    const wrap = safeEl('section', 'operations-workspace operations-workspace--phase9');
    wrap.setAttribute('aria-labelledby', 'operations-title');
    wrap.setAttribute('data-operation', operation);
    wrap.id = `operations-phase9-${operation}-workspace`;

    /* v3 header */
    wrap.appendChild(buildOpsV3Header(operation, {}, inputs));

    /* Mode bar */
    wrap.appendChild(buildOpsV3ModeBar(operation, onSelect));

    /* Campaign body section */
    const body = safeEl('section', 'ops-phase9-campaign-body');
    body.setAttribute('aria-label', `${operation} campaign workspace`);

    /* Workspace question */
    const questionText = _workspaceVM?.workspaceQuestion(operation) || '';
    body.appendChild(safeEl('p', 'ops-phase9-question', questionText));

    if (campaign) {
      /* Campaign title — textContent prevents XSS */
      body.appendChild(safeEl('h2', 'ops-phase9-campaign-title', campaign.title));

      /* State pill — class-based styling only, no innerHTML state value in class */
      const validStates = new Set(['proposed', 'active', 'blocked', 'completed', 'archived']);
      const safeState = validStates.has(campaign.state) ? campaign.state : 'unknown';
      const statePill = safeEl('span', `ops-phase9-state-pill ops-phase9-state-pill--${safeState}`);
      statePill.textContent = campaign.state;
      body.appendChild(statePill);

      /* Target subject / system */
      if (campaign.target_subject) {
        body.appendChild(safeEl('p', 'ops-phase9-target-subject', campaign.target_subject));
      }
      if (campaign.target_system) {
        body.appendChild(safeEl('p', 'ops-phase9-target-system', campaign.target_system));
      }

      /* Blockers */
      const blockers = Array.isArray(campaign.blockers) ? campaign.blockers : [];
      if (blockers.length > 0) {
        body.appendChild(safeEl('h3', 'ops-phase9-section-head', 'Blockers'));
        const bList = safeEl('ul', 'ops-phase9-blockers-list');
        blockers.forEach(b => bList.appendChild(safeEl('li', 'ops-phase9-blocker-item', b)));
        body.appendChild(bList);
      }

      /* Next actions */
      const nextActions = Array.isArray(campaign.next_actions) ? campaign.next_actions : [];
      if (nextActions.length > 0) {
        body.appendChild(safeEl('h3', 'ops-phase9-section-head', 'Next actions'));
        const nList = safeEl('ul', 'ops-phase9-next-actions-list');
        nextActions.forEach(a => nList.appendChild(safeEl('li', 'ops-phase9-action-item', a)));
        body.appendChild(nList);
      }

      /* Linked Intel facts (weak refs — IDs only, textContent each) */
      const linkedFacts = Array.isArray(campaign.linked_intel_facts) ? campaign.linked_intel_facts : [];
      const factsHead = safeEl('h3', 'ops-phase9-section-head');
      factsHead.textContent = `Linked Intel facts (${linkedFacts.length})`;
      body.appendChild(factsHead);
      const factList = safeEl('ul', 'ops-phase9-linked-facts-list');
      linkedFacts.forEach(fid => factList.appendChild(safeEl('li', 'ops-phase9-fact-id', fid)));
      body.appendChild(factList);

      /* Linked Navigation circuits (weak refs — IDs only, textContent each) */
      const linkedCircuits = Array.isArray(campaign.linked_navigation_circuits) ? campaign.linked_navigation_circuits : [];
      const circuitsHead = safeEl('h3', 'ops-phase9-section-head');
      circuitsHead.textContent = `Linked Navigation circuits (${linkedCircuits.length})`;
      body.appendChild(circuitsHead);
      const circuitList = safeEl('ul', 'ops-phase9-linked-circuits-list');
      linkedCircuits.forEach(cid => circuitList.appendChild(safeEl('li', 'ops-phase9-circuit-id', cid)));
      body.appendChild(circuitList);

      /* Campaign lifecycle (R8-16). The only two protected transitions the
         Commander can reach, each of which goes through the Confirmation Gate
         and says so before it is pressed. */
      const terminal = campaign.state === 'archived' || campaign.state === 'completed';
      if (!terminal) {
        const lifecycle = safeEl('div', 'ops-phase9-lifecycle');
        lifecycle.setAttribute('aria-label', 'Campaign lifecycle');
        [
          { action: 'complete', label: 'Mark complete', allowed: campaign.state === 'active' },
          { action: 'archive', label: 'Archive campaign', allowed: true },
        ].forEach(({ action, label, allowed }) => {
          if (!allowed) return;
          const btn = safeEl('button', 'ops-phase9-lifecycle-btn cmd-btn', label);
          btn.setAttribute('type', 'button');
          /* Announced BEFORE the press, so a confirmation is never a surprise. */
          btn.setAttribute('data-requires-confirmation', 'true');
          if (_campaignBusy) btn.setAttribute('disabled', 'disabled');
          btn.addEventListener('click', () => {
            runProtectedCampaignAction(operation, action, campaign.campaign_id);
          });
          lifecycle.appendChild(btn);
        });
        lifecycle.appendChild(safeEl('p', 'ops-phase9-lifecycle-note',
          'Both need your confirmation. Archiving is terminal.'));
        body.appendChild(lifecycle);
      }

      if (_campaignStatus) {
        const status = safeEl('p',
          `ops-phase9-campaign-status ops-phase9-campaign-status--${_campaignStatus.tone}`,
          _campaignStatus.message);
        status.setAttribute('role', 'status');
        status.setAttribute('data-status-tone', _campaignStatus.tone);
        body.appendChild(status);
      }

      /* PB09-08 bridge affordances — route-transfer navigation only, no mutation */
      const bridgeNav = safeEl('nav', 'ops-phase9-bridge-links');
      bridgeNav.setAttribute('aria-label', 'Campaign bridge links');

      if (linkedFacts.length > 0) {
        const viewIntelBtn = safeEl('button', 'ops-phase9-bridge-btn ops-phase9-bridge-btn--intel', 'View Intel facts');
        viewIntelBtn.setAttribute('type', 'button');
        viewIntelBtn.addEventListener('click', () => {
          if (typeof window.Shell?.startRouteTransfer !== 'function') { window.location.hash = '#/intel'; return; }
          dispatchHandoff({
            originRoute: '/operations',
            originPackage: 'Operations',
            originSectionId: `operations-phase9-${operation}-workspace`,
            targetRoute: '/intel',
            targetSectionId: `intel-phase9-${operation}`,
            targetEntityId: linkedFacts[0] || '',
            targetLabel: `Intel ${operation === 'bgs' ? 'BGS' : 'Powerplay'} facts`,
            reason: 'Viewing linked Intel facts.',
            returnLabel: 'Return to Operations',
            returnTarget: { route: '/operations' },
          });
        });
        bridgeNav.appendChild(viewIntelBtn);
      }

      if (linkedCircuits.length > 0) {
        const viewCircuitBtn = safeEl('button', 'ops-phase9-bridge-btn ops-phase9-bridge-btn--navigation', 'View Navigation circuit');
        viewCircuitBtn.setAttribute('type', 'button');
        viewCircuitBtn.addEventListener('click', () => {
          if (typeof window.Shell?.startRouteTransfer !== 'function') { window.location.hash = '#/navigation'; return; }
          dispatchHandoff({
            originRoute: '/operations',
            originPackage: 'Operations',
            originSectionId: `operations-phase9-${operation}-workspace`,
            targetRoute: '/navigation',
            targetSectionId: 'navigation-campaign-circuits',
            targetEntityId: linkedCircuits[0] || '',
            targetLabel: 'Navigation campaign circuits',
            reason: 'Viewing linked Navigation circuit.',
            returnLabel: 'Return to Operations',
            returnTarget: { route: '/operations' },
          });
        });
        bridgeNav.appendChild(viewCircuitBtn);
      }

      const attachNoteBtn = safeEl('button', 'ops-phase9-bridge-btn ops-phase9-bridge-btn--squadrons', 'Attach Squadron note');
      attachNoteBtn.setAttribute('type', 'button');
      attachNoteBtn.addEventListener('click', () => {
        if (typeof window.Shell?.startRouteTransfer !== 'function') { window.location.hash = '#/squadrons'; return; }
        dispatchHandoff({
          originRoute: '/operations',
          originPackage: 'Operations',
          originSectionId: `operations-phase9-${operation}-workspace`,
          targetRoute: '/squadrons',
          targetSectionId: 'squadrons-phase9-campaign-coordination',
          targetEntityId: campaign.campaign_id || '',
          targetLabel: 'Squadron campaign coordination',
          reason: 'Attaching local-only squadron note.',
          returnLabel: 'Return to Operations',
          returnTarget: { route: '/operations' },
        });
      });
      bridgeNav.appendChild(attachNoteBtn);
      body.appendChild(bridgeNav);

      /* AI draft history cards */
      const draftHistory = Array.isArray(campaign.ai_draft_history) ? campaign.ai_draft_history : [];
      if (draftHistory.length > 0) {
        body.appendChild(safeEl('h3', 'ops-phase9-section-head', 'AI draft history'));
        draftHistory.forEach(entry => {
          body.appendChild(buildAiDraftHistoryCard(entry));
        });
      }
    } else {
      /* No active campaign — idle copy */
      const idleCopy = operation === 'bgs'
        ? 'No active BGS objective. Add one to focus the deck.'
        : 'No active Powerplay objective. Add one to focus the deck.';
      body.appendChild(safeEl('p', 'ops-phase9-idle-copy', idleCopy));
    }

    wrap.appendChild(body);

    /* Quick tools row */
    const quickTools = _workspaceVM?.workspaceQuickTools(operation) || [];
    if (quickTools.length > 0 && _primitives?.createQuickToolStrip) {
      wrap.appendChild(_primitives.createQuickToolStrip(quickTools));
    }

    /* PB09-08: Activity Log proof link (PB09-08 bridge) */
    const logLink = safeEl('a', 'ops-phase9-activity-log-link cmd-btn cmd-btn--quiet', 'View in Log');
    logLink.setAttribute('href', '#/activity-log');
    if (campaign?.campaign_id) {
      logLink.addEventListener('click', (e) => {
        if (typeof window.Shell?.startRouteTransfer !== 'function') return;
        e.preventDefault();
        dispatchHandoff({
          originRoute: '/operations',
          originPackage: 'Operations',
          originSectionId: `operations-phase9-${operation}-workspace`,
          targetRoute: '/activity-log',
          targetSectionId: 'log-body',
          targetEntityId: campaign.campaign_id,
          targetLabel: 'Activity Log proof',
          reason: 'Viewing campaign proof.',
          returnLabel: 'Return to Operations',
          returnTarget: { route: '/operations' },
        });
      });
    }
    wrap.appendChild(logLink);

    /* Back to selector */
    const footer = safeEl('footer', 'operations-workspace-footer');
    const back = safeEl('button', 'operations-selector-back', 'Back to Operations selector');
    back.type = 'button';
    back.addEventListener('click', () => {
      _manualOperation = null;
      writeManualOperation(null);
      renderIdleSelector();
    });
    footer.appendChild(back);
    wrap.appendChild(footer);

    root.replaceChildren(wrap);
    /* PB09-08: apply route-transfer arrival banner for inbound bridge handoffs */
    if (typeof window.Shell?.applyRouteTransferArrival === 'function') {
      window.Shell.applyRouteTransferArrival('/operations', root);
    }
  }

  /* ──────────────────────────────────────────────
   * PB09-06 AI draft rendering helpers
   * ADR 0003: createElement + textContent only. No innerHTML.
   * ────────────────────────────────────────────── */

  /* Build a single AI draft history card from a history entry dict.
     Renders: is_fact chip, confidence, timestamp, draft_text (non-fact label),
     source_chain (fact IDs), KB references with needs_review warning. */
  function buildAiDraftHistoryCard(entry) {
    const card = safeEl('article', 'ops-phase9-ai-draft-card');

    /* is_fact chip — always present, always "not a fact" per AI draft contract */
    card.appendChild(safeEl('span', 'ops-phase9-is-fact-chip', 'AI DRAFT — not a fact'));

    if (entry.confidence_label) {
      card.appendChild(safeEl('span', 'ops-phase9-confidence', entry.confidence_label));
    }
    if (entry.timestamp) {
      const ts = safeEl('time', 'ops-phase9-draft-timestamp');
      ts.setAttribute('datetime', entry.timestamp);
      ts.textContent = entry.timestamp;
      card.appendChild(ts);
    }

    /* draft_text — rendered as explicitly labeled non-fact text via textContent */
    if (entry.draft_text) {
      card.appendChild(safeEl('p', 'ops-phase9-draft-text', entry.draft_text));
    }

    /* source_chain — fact IDs only, textContent */
    const chain = Array.isArray(entry.source_chain) ? entry.source_chain : [];
    if (chain.length > 0) {
      const scHead = safeEl('p', 'ops-phase9-draft-sc-head', 'Sources');
      card.appendChild(scHead);
      const scList = safeEl('ul', 'ops-phase9-draft-source-chain');
      chain.forEach(sc => {
        scList.appendChild(safeEl('li', 'ops-phase9-draft-sc-item', sc.fact_id || sc.source || ''));
      });
      card.appendChild(scList);
    }

    /* KB references — metadata with needs_review warning (PB09-06) */
    const kbRefs = Array.isArray(entry.kb_references) ? entry.kb_references : [];
    if (kbRefs.length > 0) {
      card.appendChild(safeEl('p', 'ops-phase9-draft-kb-refs-head', 'KB References'));
      const kbList = safeEl('ul', 'ops-phase9-draft-kb-refs');
      kbRefs.forEach(ref => {
        const refItem = safeEl('li', 'ops-phase9-draft-kb-ref');
        refItem.appendChild(safeEl('span', 'ops-phase9-draft-kb-file', ref.kb_file || ''));
        refItem.appendChild(safeEl('span', 'ops-phase9-draft-kb-entry', ref.entry_id || ''));
        if (ref.needs_review) {
          refItem.appendChild(safeEl('span', 'ops-phase9-draft-kb-needs-review',
            'Under review — do not treat as fact'));
        }
        kbList.appendChild(refItem);
      });
      card.appendChild(kbList);
    }

    return card;
  }

  /* Render an AI draft response section (nullprovider or validation_failed) into
     the given container element. Safe DOM only — no innerHTML.
     Called by tests directly via __operationsExports.buildAiDraftResponseSection.
     In production, would be called after a fresh POST /ai-draft response.

     result shape expected:
       { status, nullprovider_message?, kb_references?, is_fact, draft_text? }
  */
  function buildAiDraftResponseSection(container, result) {
    if (!result || !container) return;

    const section = safeEl('div', 'ops-phase9-draft-response');

    if (result.status === 'nullprovider') {
      const msg = result.nullprovider_message ||
        'AI drafting disabled. Use the commander-entered notes and the linked Intel facts to plan your next step.';
      section.appendChild(safeEl('span', 'ops-phase9-is-fact-chip', 'AI DRAFT — not a fact'));
      section.appendChild(safeEl('p', 'ops-phase9-nullprovider-msg', msg));

      /* KB references disclosed on NullProvider path */
      const kbRefs = Array.isArray(result.kb_references) ? result.kb_references : [];
      if (kbRefs.length > 0) {
        section.appendChild(safeEl('p', 'ops-phase9-draft-kb-refs-head', 'KB References'));
        const kbList = safeEl('ul', 'ops-phase9-draft-kb-refs');
        kbRefs.forEach(ref => {
          const refItem = safeEl('li', 'ops-phase9-draft-kb-ref');
          refItem.appendChild(safeEl('span', 'ops-phase9-draft-kb-file', ref.kb_file || ''));
          refItem.appendChild(safeEl('span', 'ops-phase9-draft-kb-entry', ref.entry_id || ''));
          if (ref.needs_review) {
            refItem.appendChild(safeEl('span', 'ops-phase9-draft-kb-needs-review',
              'Under review — do not treat as fact'));
          }
          kbList.appendChild(refItem);
        });
        section.appendChild(kbList);
      }
    } else if (result.status === 'validation_failed') {
      section.appendChild(safeEl('span', 'ops-phase9-is-fact-chip', 'AI DRAFT — not a fact'));
      section.appendChild(safeEl('p', 'ops-phase9-validation-failed',
        'Draft validation failed. Refine the inputs and try again.'));
    }

    container.appendChild(section);
  }

  /* Public-facing renderer for BGS campaign workspace. Accepts a campaign record or null.
     Used by tests directly and by renderWorkspace async dispatch. */
  function renderBgsWorkspace(root, campaign) {
    renderPhase9CampaignWorkspace(root, 'bgs', campaign);
  }

  /* Public-facing renderer for Powerplay campaign workspace. */
  function renderPowerplayWorkspace(root, campaign) {
    renderPhase9CampaignWorkspace(root, 'powerplay', campaign);
  }

  function buildLocalContextWorkspace(operation) {
    if (!_localSurfaces || !inputs.localContext) return null;
    const {
      createCargoHoldSurface,
      createMarketContextSurface,
      createStationBriefSurface,
    } = _localSurfaces;

    const handlers = {
      'search-sell-prices': () => stageIntelMarketFromCargo(),
      'open-market-search': () => stageIntelMarketFromCargo(),
      'compare-current-station': () => stageIntelMarketFromCargo(),
      'open-market-intel': () => stageIntelMarketFromCargo(),
      'open-cargo': () => selectOperation('trading'),
      'open-station': () => selectOperation('station'),
    };

    /* R2-4: Operations shows market CONTEXT and hands search to Intel, which
       owns it. `createMarketSearchSurface` is Intel's; Operations no longer
       calls it. */
    const marketContext = () => createMarketContextSurface(inputs.localContext.marketSearch, {
      onSearchHandoff: (query) => stageIntelMarketFromCargo(query),
      onOpenSearch: () => stageIntelMarketFromCargo(),
    });

    const grid = safeEl('section', 'operations-local-context-grid');
    grid.setAttribute('aria-label', 'Local context workspace');

    if (operation === 'station') {
      grid.appendChild(createStationBriefSurface(inputs.localContext.stationBrief, { handlers }));
      grid.appendChild(marketContext());
      return grid;
    }

    if (operation === 'mining' || operation === 'trading') {
      grid.appendChild(createCargoHoldSurface(inputs.localContext.cargoHold, { handlers }));
      grid.appendChild(marketContext());
      grid.appendChild(createStationBriefSurface(inputs.localContext.stationBrief, { handlers }));
      return grid;
    }

    return null;
  }

  /* Hand commodity lookup to Intel, the accepted owner. Uses the existing
     RouteTransferIntent grammar so the arrival banner and the return path work
     — `targetSectionId` names Intel's search domain, `targetEntityId` its
     commodity mode, and `targetLabel` carries the commodity itself when the
     Commander asked about one. No new field is added to the contract, and no
     Dashboard fallback is used (FU-022). */
  function stageIntelMarketFromCargo(commodity) {
    const query = String(commodity || '').trim();
    if (typeof window.Shell?.startRouteTransfer === 'function') {
      const intent = dispatchHandoff({
        originRoute: '/operations',
        originPackage: _manualOperation || 'idle',
        targetRoute: '/intel',
        targetSectionId: 'intel-domain-search',
        targetEntityId: 'commodity',
        targetLabel: query ? `Commodity: ${query}` : 'Commodity search',
        targetQuery: query,
        reason: query
          ? `Commodity lookup from Operations: ${query}`
          : 'Commodity lookup from Operations',
        returnLabel: 'Back to Operations',
      });
      if (intent) return;
    }
    /* Shell unavailable (e.g. a bare test harness): still reach Intel. */
    window.location.hash = '#/intel';
  }

  function buildOperationDetail(operation) {
    const container = safeEl('div', 'operations-detail');

    const cargoItems = Array.isArray(inputs.cargo?.inventory) ? inputs.cargo.inventory : [];
    const cargoCount = inputs.state?.cargo_count;
    const cargoCap   = inputs.state?.cargo_capacity;
    const route      = inputs.navSnap?.active_route?.destination || null;
    const station    = inputs.state?.current_station || inputs.localContext?.stationBrief?.stationName || null;
    const market     = inputs.localContext?.marketSearch || null;

    const dl = document.createElement('dl');
    dl.className = 'operations-detail-dl';

    function row(label, value) {
      const dt = safeEl('dt', 'operations-detail-dt', label);
      const dd = safeEl('dd', 'operations-detail-dd', value);
      dl.appendChild(dt);
      dl.appendChild(dd);
    }

    row('Operation', operation);
    if (cargoCount != null && cargoCap != null) row('Cargo', `${cargoCount} / ${cargoCap} t`);
    else if (cargoItems.length > 0) row('Cargo types', `${cargoItems.length}`);
    else row('Cargo', 'No cargo detected');
    row('Route', route ? route : 'No route plotted');
    /* Smoke R1: derive station/docking via unified location state so
       Operations never says "Undocked" when station_context knows a station. */
    const sessionState = window.Shell?.eliteSessionState || null;
    const loc = _commanderVM?.deriveCommanderLocationState?.(
      inputs.localContext, inputs.state, inputs.navSnap, { sessionState }) || null;
    if (loc) {
      row('Station', loc.stationName || (loc.dockingState === 'in_space' ? 'In space' : 'Station not checked'));
      row('Docking', `${loc.flightLabel}: ${loc.flightValue}`);
    } else {
      row('Station', station || 'Station not checked');
    }
    row('Local market', market?.available ? market.rowsPhrase : 'No local market snapshot loaded');

    container.appendChild(dl);

    if (cargoItems.length > 0) {
      const heading = safeEl('h4', 'operations-detail-subheading', 'Top cargo');
      const list = safeEl('ul', 'operations-detail-cargo-list');
      cargoItems.slice(0, 6).forEach((item) => {
        const li = safeEl('li', 'operations-detail-cargo-item');
        li.appendChild(safeEl('span', 'operations-detail-cargo-name', item?.name || 'Unlabelled cargo'));
        li.appendChild(safeEl('span', 'operations-detail-cargo-count', String(item?.count ?? '—')));
        list.appendChild(li);
      });
      container.appendChild(heading);
      container.appendChild(list);
    }

    return container;
  }

  function buildProofContent(operation) {
    const container = safeEl('div', 'operations-proof');

    const lines = [
      'Operations reads only local Status, Loadout, Cargo, NavRoute, and combat session data.',
      'No outbound provider lookups happen by default; external integrations remain gated.',
      'See Activity Log for raw event history and Systems route for source posture detail.',
    ];

    lines.forEach((text) => {
      container.appendChild(safeEl('p', 'operations-proof-line', text));
    });

    container.appendChild(safeEl('p', 'operations-proof-note',
      `Activity context: ${operation}. Details that were not checked remain unset; no inferred facts are presented as game-observed.`));

    return container;
  }

  async function loadAndRender() {
    await Promise.all([primitivesPromise, commanderPromise, workspacePromise, localContextPromise, localSurfacesPromise]);
    if (!_primitives || !_commanderVM || !_workspaceVM) {
      const missing = [
        !_primitives && 'shared controls',
        !_commanderVM && 'Commander context',
        !_workspaceVM && 'activity workspaces',
      ].filter(Boolean).join(', ');
      renderUnavailable(new Error(`Operations modules unavailable: ${missing}`));
      return;
    }
    consumeInboundOperation();

    const [ship, cargo, heat, mods, navSnap, combat, localContextSnap, activityLog,
      objectivesIndex, shipProfile, engineeringPlans] = await Promise.all([
      fetchJson('/pillar1/ship-state'),
      fetchJson('/pillar1/cargo'),
      fetchJson('/pillar1/heat'),
      fetchJson('/pillar1/modules/summary'),
      fetchJson('/navigation/snapshot'),
      fetchJson('/combat/snapshot'),
      fetchJson('/intel/local-context/snapshot'),
      /* R0-2: bounded read of the Activity Log, the existing proof owner.
         No second event store is created. A null result means "could not
         read", which the card reports as such rather than as "none". */
      fetchJson('/activity-log'),
      /* R3: every mode's current objective, for the default surface only. A
         mode that is selected re-reads its own objective through the
         mode-specific path; this answers "what am I trying to accomplish"
         when no mode is selected at all. */
      fetchJson('/operations/objectives'),
      /* P14-D05: the role-fit capability has existed and been served since
         LNA-022, consumed only by Engineering. Operations — the surface that
         most needs "is this ship right for this job" — never called it. */
      fetchJson('/readiness/ship-profile'),
      /* R8: Engineering already models the handoff INTO Operations and aims it
         at a section id `active_engineering_task`. Operations rendered no such
         element, so the arrival landed nowhere. This read is what finally
         gives that intent something to land on. */
      fetchJson('/engineering/acquisition-plans'),
    ]);

    inputs.engineeringPlans = engineeringPlans;
    inputs.state = ship;
    inputs.cargo = cargo;
    inputs.heat  = heat;
    inputs.mods  = mods;
    inputs.navSnap = navSnap;
    inputs.combat  = combat;
    inputs.localContext = _localContextVM?.deriveLocalContext(localContextSnap) || null;
    inputs.localContextRaw = localContextSnap || null;
    inputs.activityLog = activityLog || null;
    inputs.objectivesIndex = objectivesIndex || null;
    inputs.shipProfile = shipProfile || null;
    /* Readiness is computed once, by the backend service that also answers
       Dashboard and Engineering. Read per operation so the served answer
       matches the operation being shown — consumeInboundOperation() above may
       already have selected one from a route handoff. */
    invalidateModeInputs(_manualOperation);
    await refreshOperationInputs(_manualOperation);

    renderWorkspace(_manualOperation);
  }

  function renderUnavailable(error) {
    const root = getRoot();
    if (!root) return;
    root.replaceChildren();
    const h1 = safeEl('h1', 'operations-unavailable-title', 'Operations');
    h1.id = 'operations-title';
    root.appendChild(h1);
    if (_primitives?.createErrorState) {
      root.appendChild(_primitives.createErrorState({
        error,
        task: 'Operations',
        impact: 'Your saved plans were not changed.',
        recovery: 'Try again. If the problem continues, open connection details.',
        retry: loadAndRender,
        detailsHref: '#/sources',
      }));
      return;
    }
    const note = safeEl('section', 'operations-unavailable');
    note.setAttribute('role', 'alert');
    note.append(
      safeEl('p', 'operations-unavailable-message', 'Operations could not open.'),
      safeEl('p', 'operations-unavailable-message', 'Your saved plans were not changed. Try again or open connection details.'),
    );
    root.appendChild(note);
  }

  function renderOperations() {
    const root = getRoot();
    if (!root) return;
    if (!_primitives || !_commanderVM || !_workspaceVM) {
      const interim = safeEl('section', 'operations-loading');
      const h1 = safeEl('h1', 'operations-loading-title', 'Operations');
      h1.id = 'operations-title';
      const p = safeEl('p', 'operations-loading-message', 'Loading workspace…');
      interim.appendChild(h1);
      interim.appendChild(p);
      root.replaceChildren(interim);
      Promise.all([primitivesPromise, commanderPromise, workspacePromise, localContextPromise, localSurfacesPromise]).then(() => {
        if (_primitives && _commanderVM && _workspaceVM) renderWorkspace(_manualOperation);
        else renderUnavailable(new Error('Operations modules did not load.'));
      });
      return;
    }
    consumeInboundOperation();
    renderWorkspace(_manualOperation);
  }

  /* ──────────────────────────────────────────────
   * Event wiring
   * ────────────────────────────────────────────── */
  function bindEvents() {
    if (window.OmniEvents) {
      window.OmniEvents.addEventListener('bridge-connected', loadAndRender);
      window.OmniEvents.addEventListener('event', (ev) => {
        const detail = ev.detail || {};
        const type = detail.event_type || detail.event;
        if (!type) return;
        if (type === 'INTERDICTION_STARTED' || type === 'INTERDICTION_ENDED'
            || type === 'COMBAT_STATE_CHANGED' || type === 'COMBAT_SESSION_STATE_CHANGED') {
          fetchJson('/combat/snapshot').then((c) => { inputs.combat = c; renderWorkspace(_manualOperation); });
        }
        if (type === 'CARGO_CHANGED') {
          Promise.all([
            fetchJson('/pillar1/cargo'),
            fetchJson('/intel/local-context/snapshot'),
          ]).then(([c, localContextSnap]) => {
            inputs.cargo = c;
            inputs.localContext = _localContextVM?.deriveLocalContext(localContextSnap) || inputs.localContext;
            renderWorkspace(_manualOperation);
          });
        }
        if (type === 'SHIP_STATE_CHANGED' || type === 'LOADOUT_CHANGED') {
          loadAndRender();
        }
      });
    }
    window.addEventListener('hashchange', () => {
      if (window.location.hash === '#/operations') loadAndRender();
    });
  }

  function init() {
    bindEvents();
    if (apiBase()) {
      loadAndRender();
    } else {
      renderUnavailable(new Error('OmniCOVAS bridge is not connected.'));
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  /* Test hooks — expose synchronous render entry points for vitest/JSDOM */
  globalThis.__operationsExports = {
    renderOperations,
    renderWorkspace,
    consumeInboundOperation,
    /* Phase 9 campaign workspace renderers — called directly in tests with mock data */
    renderBgsWorkspace,
    renderPowerplayWorkspace,
    /* PB09-06 AI draft rendering helpers */
    buildAiDraftHistoryCard,
    buildAiDraftResponseSection,
    /* R0 truth-integrity card — asserted directly against fixture inputs so
       the regression proves rendered behaviour, not helper output. */
    buildOpsV3RecentActivityCard,
    /* R2 supporting-context band (Docked Context detail + history). */
    buildOpsV3SupportingContext,
    /* R1-2 exploration workflow card — asserted directly against snapshot
       fixtures so the regression proves rendered behaviour. */
    buildOpsV3ExplorationCard,
    /* R1-1 mode selection, including the async mode-input refresh. Returns the
       promise so tests await the resolved render rather than guessing at
       timing. */
    selectOperation,
    refreshOperationInputs,
    /* R3 objective lifecycle. Exposed so regressions drive the real flows —
       the gate round trip included — instead of asserting helper output. */
    buildObjectiveLifecycle,
    /* P14-A03: the Commander decided Operations must never reopen the last
       package after restart. This is the function that enforces it, exported
       so the decision has a regression that actually exercises it — the
       module-init call cannot be re-run from a test. */
    readManualOperation,
    /* R4-1 objective band, asserted directly for rank and uniqueness. */
    buildObjectiveBand,
    buildWorkflowOutlookCard,
    /* P14-D05 role fit, asserted against served ship-profile fixtures. */
    buildRoleFitRow,
    /* R8: the active engineering task card (`P14-J01`) and the ONE function
       every purposeful Operations handoff dispatches through, exported so the
       proof contract is asserted against real behaviour rather than a stub. */
    buildOpsV3EngineeringTaskCard,
    dispatchHandoff,
    /* R8-16: the campaign half of the one gate policy. */
    runProtectedCampaignAction,
    campaignStatusForTests() {
      return _campaignStatus ? { ..._campaignStatus } : null;
    },
    resetCampaignStatusForTests() {
      _campaignStatus = null;
      _campaignBusy = false;
    },
    buildOpsV3DefaultObjectives,
    submitFirstObjective,
    runProtectedObjectiveAction,
    resetObjectiveEditor,
    openObjectiveEditorForTests(operation, mode) {
      _objectiveEditor = { operation, mode };
    },
    objectiveStatusForTests() {
      return _objectiveStatus ? { ..._objectiveStatus } : null;
    },
    setOperation(op) {
      _manualOperation = op;
      writeManualOperation(op);
    },
    setInputs(next) {
      Object.assign(inputs, next || {});
      if (next?.localContextSnap && _localContextVM) {
        inputs.localContext = _localContextVM.deriveLocalContext(next.localContextSnap);
      }
    },
    resetState() {
      Object.keys(inputs).forEach((k) => { inputs[k] = null; });
      _manualOperation = null;
      writeManualOperation(null);
      resetObjectiveEditor();
    },
    async getCommandPrimitives() {
      const p = await primitivesPromise;
      await commanderPromise;
      await workspacePromise;
      await localContextPromise;
      await localSurfacesPromise;
      return p;
    },
    /* Compatibility shims for older tests. */
    openOperationsPackage() { renderOperations(); },
    resetTargetThreatForTests() { /* no-op in v2/v3 workspace model */ },
  };
})();
