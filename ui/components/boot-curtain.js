/**
 * OmniCOVAS boot curtain — PB11-01 startup readiness surface.
 *
 * A visible local-first initialization curtain that paints immediately on
 * load (static markup in index.html) and reports four discrete, honest
 * checks while the shell boots: runtime shell, backend bridge, local Elite
 * sources, and cached session state. Stage vocabulary follows the complete
 * Phase 11 startup state model (starting → local_sources_locating →
 * hydrating_local_state → ready_live / ready_limited / blocked_local_setup).
 *
 * Doctrine:
 *  - No fake progress: discrete real checks only, no percentages, no bars.
 *  - No indefinite spinner: a hard timeout resolves every unresolved check
 *    to an honest limited state and dismisses the curtain.
 *  - Limited mode keeps a diagnostics path (Open Diagnostics link).
 *  - Local-only language; no provider or network claims.
 *  - ADR 0003 Tier 1: textContent only; no dynamic HTML.
 *  - Never traps the commander: Escape or click dismisses after a short
 *    grace period; any route navigation dismisses instantly.
 *  - This is presentation over existing shell/bridge/state signals — no
 *    parallel bridge, state manager, or hydration service.
 */
(function () {
  'use strict';

  const DISMISS_TIMEOUT_MS = 8000;
  const MIN_VISIBLE_MS = 600;
  const LIMITED_HOLD_MS = 1200;
  const INTERACT_GRACE_MS = 1500;

  const STARTUP_STAGES = Object.freeze({
    STARTING: 'starting',
    LOCATING: 'local_sources_locating',
    HYDRATING: 'hydrating_local_state',
    READY_LIVE: 'ready_live',
    READY_LIMITED: 'ready_limited',
    BLOCKED: 'blocked_local_setup',
  });

  /* Elite session state arrives here in the backend's raw vocabulary
     (`active`, `last_known`, `waiting`, `unknown`) but the checks below were
     written against the shell's display vocabulary (`Active`, `Last known`).
     Normalising with the shell's own rule — shell.js normalizeEliteSessionState
     — lets one matcher accept either form. Matching the raw value literally
     meant `last_known` fell through to "check unavailable", reporting a failed
     check for a check that had in fact succeeded and found local data. */
  function normalizeSessionState(value) {
    return String(value || '').trim().toLowerCase().replace(/[-\s]+/g, '_');
  }

  /* The backend already decides whether startup restored anything: a
     `startup_hydration` source with a `last_known` state means local files
     supplied the state the app came up holding. Deriving the session-state
     check from that answer replaces a hardcoded `true` that claimed
     "Last-known state restored" on every launch, including a first run with
     an empty Elite folder where nothing was restored at all. */
  function deriveSessionRestore(sessionActivity) {
    switch (normalizeSessionState(
      sessionActivity?.elite_session_state ?? sessionActivity?.state,
    )) {
      case 'active': return 'live';
      case 'last_known': return true;
      case 'waiting':
      case 'no_local_path': return false;
      /* `unknown` means files were present but yielded no usable signal.
         That is not a fresh start; it is an unresolved one. */
      default: return 'unavailable';
    }
  }

  const state = {
    started: false,
    dismissed: false,
    shownAt: 0,
    timeoutId: null,
    bridgeOutcome: 'pending',
    sessionOutcome: 'pending',
    localSourcesOutcome: 'pending',
    finalized: false,
  };

  function rootEl() {
    return document.getElementById('uiv3-boot-curtain');
  }

  function stageEl() {
    return document.getElementById('uiv3-boot-stage');
  }

  function setStage(stage, text) {
    const el = stageEl();
    if (el) {
      el.dataset.bootStage = stage;
      el.textContent = text;
    }
    const root = rootEl();
    if (root) root.dataset.bootStage = stage;
  }

  function setCheck(id, status, detail) {
    const node = document.querySelector(`[data-boot-check="${id}"]`);
    if (!node) return;
    node.setAttribute('data-boot-status', status);
    const statusEl = node.querySelector('.uiv3-boot-check-status');
    if (statusEl) statusEl.textContent = detail;
  }

  function hideNow(reason) {
    const el = rootEl();
    if (!el) return;
    el.setAttribute('data-boot-dismissed', reason);
    el.classList.add('is-dismissed');
    el.setAttribute('aria-hidden', 'true');
    /* pointer-events are disabled by .is-dismissed immediately; the hidden
       attribute lands after the short fade so reduced-motion users see an
       instant hide (CSS removes the transition) and nobody can interact
       with a ghost surface. */
    window.setTimeout(() => {
      el.setAttribute('hidden', '');
    }, 300);
  }

  function dismiss(reason) {
    if (state.dismissed) return;
    state.dismissed = true;
    if (state.timeoutId !== null) {
      window.clearTimeout(state.timeoutId);
      state.timeoutId = null;
    }
    const elapsed = Date.now() - state.shownAt;
    const wait = reason === 'navigation' || reason === 'commander'
      ? 0
      : Math.max(0, MIN_VISIBLE_MS - elapsed);
    window.setTimeout(() => hideNow(reason), wait);
  }

  function allOutcomesKnown() {
    return state.bridgeOutcome !== 'pending'
      && state.sessionOutcome !== 'pending'
      && state.localSourcesOutcome !== 'pending';
  }

  function outcomeDetail() {
    return Object.freeze({
      stage: rootEl()?.dataset.bootStage || STARTUP_STAGES.STARTING,
      bridge: state.bridgeOutcome,
      local_sources: state.localSourcesOutcome,
      session_state: state.sessionOutcome,
    });
  }

  function announceOutcome(stage) {
    const root = rootEl();
    if (root) root.dataset.bootOutcome = stage;
    window.dispatchEvent(new CustomEvent('omnicovas:startup-outcome', {
      detail: outcomeDetail(),
    }));
  }

  function finish(stage, text, dismissReason) {
    if (state.dismissed || state.finalized) return;
    state.finalized = true;
    setStage(stage, text);
    announceOutcome(stage);
    if (stage === STARTUP_STAGES.READY_LIVE) {
      dismiss(dismissReason);
      return;
    }
    window.setTimeout(() => dismiss(dismissReason), LIMITED_HOLD_MS);
  }

  function markPendingChecksLimited() {
    if (state.bridgeOutcome === 'pending') {
      state.bridgeOutcome = 'unavailable';
      setCheck('bridge', 'limited', 'Not connected — limited mode');
    }
    if (state.localSourcesOutcome === 'pending') {
      state.localSourcesOutcome = 'unavailable';
      setCheck('local-files', 'limited', 'Not Loaded');
    }
    if (state.sessionOutcome === 'pending') {
      state.sessionOutcome = 'unavailable';
      setCheck('session-state', 'limited', 'Not Loaded');
    }
  }

  function evaluateReadiness() {
    if (state.dismissed || state.finalized) return;

    if (state.bridgeOutcome === 'unavailable') {
      markPendingChecksLimited();
      finish(
        STARTUP_STAGES.BLOCKED,
        'Local setup blocked · Open Diagnostics',
        'blocked',
      );
      return;
    }

    if (state.bridgeOutcome === 'pending') {
      setStage(STARTUP_STAGES.STARTING, 'Starting');
      return;
    }

    if (state.localSourcesOutcome === 'pending') {
      setStage(STARTUP_STAGES.LOCATING, 'Locating local sources');
      return;
    }

    if (state.sessionOutcome === 'pending') {
      setStage(STARTUP_STAGES.HYDRATING, 'Hydrating local state');
      return;
    }

    if (!allOutcomesKnown()) return;

    /* Authority §C: blocked_local_setup covers a "required local path OR
       bridge condition". Only the bridge half was implemented; a missing
       Elite folder resolved to ready_limited, which claims the app can run
       usefully on local context it will never receive. */
    if (state.localSourcesOutcome === 'no_local_path') {
      finish(
        STARTUP_STAGES.BLOCKED,
        'Elite folder not found · Open Diagnostics',
        'blocked',
      );
      return;
    }

    if (state.localSourcesOutcome === 'live') {
      finish(STARTUP_STAGES.READY_LIVE, 'Ready — live local data', 'ready');
      return;
    }

    finish(
      STARTUP_STAGES.READY_LIMITED,
      'Ready — limited mode · Diagnostics available',
      'limited',
    );
  }

  function resolveTimeout() {
    if (state.dismissed || state.finalized) return;
    const bridgeWasPending = state.bridgeOutcome === 'pending';
    markPendingChecksLimited();
    if (bridgeWasPending || state.bridgeOutcome === 'unavailable') {
      finish(
        STARTUP_STAGES.BLOCKED,
        'Local setup blocked · Open Diagnostics',
        'timeout-blocked',
      );
      return;
    }
    finish(
      STARTUP_STAGES.READY_LIMITED,
      'Ready — limited mode · Diagnostics available',
      'timeout-limited',
    );
  }

  function onKeyDown(event) {
    if (event.key !== 'Escape') return;
    if (Date.now() - state.shownAt < INTERACT_GRACE_MS) return;
    dismiss('commander');
  }

  function onClick() {
    if (Date.now() - state.shownAt < INTERACT_GRACE_MS) return;
    dismiss('commander');
  }

  const BootCurtain = {
    start() {
      const el = rootEl();
      if (!el || state.started) return;
      state.started = true;
      state.shownAt = Date.now();
      setCheck('shell', 'ok', 'Ready');
      setStage(STARTUP_STAGES.LOCATING, 'Locating local sources');
      state.timeoutId = window.setTimeout(resolveTimeout, DISMISS_TIMEOUT_MS);
      document.addEventListener('keydown', onKeyDown);
      el.addEventListener('click', onClick);
      window.addEventListener('hashchange', () => dismiss('navigation'), { once: true });
    },

    markBridge(connected) {
      if (state.finalized || state.bridgeOutcome !== 'pending') return;
      if (connected) {
        state.bridgeOutcome = 'connected';
        setCheck('bridge', 'ok', 'Connected');
      } else {
        state.bridgeOutcome = 'unavailable';
        setCheck('bridge', 'limited', 'Local bridge unavailable');
      }
      evaluateReadiness();
    },

    /* Wording mirrors the shell's Elite session state derivation — the
       curtain repeats existing source-backed vocabulary, never invents. */
    markLocalFiles(eliteSessionState) {
      if (state.finalized || state.localSourcesOutcome !== 'pending') return;
      const value = normalizeSessionState(eliteSessionState);
      if (value === 'active' || value === 'live') {
        state.localSourcesOutcome = 'live';
        setCheck('local-files', 'ok', 'Live journal activity');
      } else if (value === 'no_local_path') {
        /* Startup exit criterion 3: the Elite folder is not there. Reporting
           "no current journal activity" told the Commander to wait for data
           that can never arrive, because nothing writes to a path that does
           not exist. This is the local-path half of blocked_local_setup. */
        state.localSourcesOutcome = 'no_local_path';
        setCheck('local-files', 'limited', 'Elite folder not found');
      } else if (value === 'last_known') {
        state.localSourcesOutcome = 'last_known';
        setCheck('local-files', 'limited', 'Last-known local context found');
      } else if (value === 'waiting') {
        state.localSourcesOutcome = 'waiting';
        setCheck('local-files', 'limited', 'No current journal activity');
      } else {
        state.localSourcesOutcome = 'unavailable';
        setCheck('local-files', 'limited', 'Local source check unavailable');
      }
      evaluateReadiness();
    },

    /* The single local-context attempt answers both the local-source check and
       the cached-state check, so it drives both. They are different questions
       about the same evidence: "could the sources be read?" and "did that
       leave the app holding state?" */
    markLocalSources(snapshot) {
      if (state.finalized) return;
      if (!snapshot || typeof snapshot !== 'object') {
        this.markLocalFiles('unavailable');
        this.markSessionState('unavailable');
        return;
      }
      const sessionActivity = snapshot.session_activity || {};
      const sessionState = sessionActivity.elite_session_state
        || sessionActivity.state
        || snapshot.elite_session_state
        || 'Unknown';
      this.markLocalFiles(sessionState);
      this.markSessionState(deriveSessionRestore(
        Object.keys(sessionActivity).length ? sessionActivity : snapshot,
      ));
    },

    markSessionState(restored) {
      if (state.finalized || state.sessionOutcome !== 'pending') return;
      if (restored === 'unavailable' || restored === null) {
        state.sessionOutcome = 'unavailable';
        setCheck('session-state', 'limited', 'State hydration unavailable');
      } else if (restored === 'live') {
        /* A live session is holding live state, not a restored cache. Saying
           "restored" here would trade one false claim for another. */
        state.sessionOutcome = 'live';
        setCheck('session-state', 'ok', 'Live session state');
      } else {
        state.sessionOutcome = restored ? 'restored' : 'fresh';
        setCheck(
          'session-state',
          'ok',
          restored ? 'Last-known state restored' : 'No cached state — fresh start',
        );
      }
      evaluateReadiness();
    },

    dismiss,

    /* Test hook: reset module state between unit tests. */
    __resetForTests() {
      if (state.timeoutId !== null) window.clearTimeout(state.timeoutId);
      state.started = false;
      state.dismissed = false;
      state.shownAt = 0;
      state.timeoutId = null;
      state.bridgeOutcome = 'pending';
      state.sessionOutcome = 'pending';
      state.localSourcesOutcome = 'pending';
      state.finalized = false;
      document.removeEventListener('keydown', onKeyDown);
    },

    __snapshotForTests() {
      return { ...state, stage: rootEl()?.dataset.bootStage || null };
    },
  };

  window.BootCurtain = BootCurtain;
})();
