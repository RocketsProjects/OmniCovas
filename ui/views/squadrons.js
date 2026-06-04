/**
 * ui/views/squadrons.js — PB07-04 Squadrons Route Shell + PB07-07 Write Flows
 *
 * Squadrons owns group coordination (local-only).
 * Reads ten section endpoints from the PB07-03 local backend.
 * PB07-07: adds local-only create/revoke flows with inline proposal/confirm/cancel gate modals.
 * ADR 0003: safe DOM rendering throughout (createElement + textContent only).
 * No AI dependency. No provider dependency. No transport. No outbound calls.
 */
(function () {
  'use strict';

  const OVERVIEW_PATH          = '/squadrons/overview';
  const ROSTER_PATH            = '/squadrons/roster';
  const INVITES_PATH           = '/squadrons/invites';
  const TELEMETRY_SYNC_PATH    = '/squadrons/telemetry-sync';
  const ROLES_PATH             = '/squadrons/roles';
  const SHARED_OPERATIONS_PATH = '/squadrons/shared-operations';
  const SHARED_NAVIGATION_PATH = '/squadrons/shared-navigation';
  const EMERGENCY_PATH         = '/squadrons/emergency-security';
  const LOG_PATH               = '/squadrons/log';
  const INTEGRATIONS_PATH      = '/squadrons/integrations';
  const RESERVED_INTENT_PATH   = '/squadrons/reserved-intent';
  const CAMPAIGN_NOTES_PATH    = '/squadrons/campaign-notes';

  // Write-flow path fragments (PB07-07)
  const ROSTER_CONFIRM_PATH           = '/squadrons/roster/confirm/';
  const ROSTER_CANCEL_PATH            = '/squadrons/roster/cancel/';
  const ROSTER_REVOKE_CONFIRM_PATH    = '/squadrons/roster/revoke-confirm/';
  const ROSTER_REVOKE_CANCEL_PATH     = '/squadrons/roster/revoke-cancel/';
  const INVITES_CONFIRM_PATH          = '/squadrons/invites/confirm/';
  const INVITES_CANCEL_PATH           = '/squadrons/invites/cancel/';
  const INVITES_REVOKE_CONFIRM_PATH   = '/squadrons/invites/revoke-confirm/';
  const INVITES_REVOKE_CANCEL_PATH    = '/squadrons/invites/revoke-cancel/';
  const ROLES_CONFIRM_PATH            = '/squadrons/roles/confirm/';
  const ROLES_CANCEL_PATH             = '/squadrons/roles/cancel/';
  const ROLES_REVOKE_CONFIRM_PATH     = '/squadrons/roles/revoke-confirm/';
  const ROLES_REVOKE_CANCEL_PATH      = '/squadrons/roles/revoke-cancel/';
  const SHARED_OPS_CONFIRM_PATH       = '/squadrons/shared-operations/confirm/';
  const SHARED_OPS_CANCEL_PATH        = '/squadrons/shared-operations/cancel/';
  const SHARED_OPS_REVOKE_CONFIRM_PATH = '/squadrons/shared-operations/revoke-confirm/';
  const SHARED_OPS_REVOKE_CANCEL_PATH  = '/squadrons/shared-operations/revoke-cancel/';
  const SHARED_NAV_CONFIRM_PATH        = '/squadrons/shared-navigation/confirm/';
  const SHARED_NAV_CANCEL_PATH         = '/squadrons/shared-navigation/cancel/';
  const SHARED_NAV_REVOKE_CONFIRM_PATH = '/squadrons/shared-navigation/revoke-confirm/';
  const SHARED_NAV_REVOKE_CANCEL_PATH  = '/squadrons/shared-navigation/revoke-cancel/';
  const EMERG_NOTE_PATH                = '/squadrons/emergency-security/note';
  const EMERG_NOTE_CONFIRM_PATH        = '/squadrons/emergency-security/note/confirm/';
  const EMERG_NOTE_CANCEL_PATH         = '/squadrons/emergency-security/note/cancel/';
  const EMERG_NOTE_REVOKE_CONFIRM_PATH = '/squadrons/emergency-security/note/revoke-confirm/';
  const EMERG_NOTE_REVOKE_CANCEL_PATH  = '/squadrons/emergency-security/note/revoke-cancel/';
  const LOG_CONFIRM_PATH               = '/squadrons/log/confirm/';
  const LOG_CANCEL_PATH                = '/squadrons/log/cancel/';

  const LOCAL_ONLY_NOTE            = 'Local-only — no peer transport active.';
  const LOCAL_ONLY_WRITE_NOTE      = 'Local only — no peer delivery.';
  const NOT_LOADED                 = 'Not Loaded';

  const FALLBACK_WORDING = Object.freeze([
    'Not Loaded',
    'Stale',
    'Unknown',
    'No Verified Source',
    'Unsupported',
    'Disabled',
    'Requires Authorization',
  ]);

  const RESERVED_SURFACES = Object.freeze([
    {
      id: 'stun_p2p',
      section: 'roster',
      feature: 'STUN P2P',
      wording: 'Reserved — requires future security doctrine.',
      reason: 'Reserved — requires future security doctrine',
      authorities: ['UI Blueprint §23', 'Future Squadron Security Doctrine'],
    },
    {
      id: 'peer_relay_fallback',
      section: 'roster',
      feature: 'Peer-Relay Fallback',
      wording: 'Reserved — requires future security doctrine.',
      reason: 'Reserved — requires future security doctrine',
      authorities: ['UI Blueprint §23', 'Future Squadron Security Doctrine'],
    },
    {
      id: 'telemetry_sync',
      section: 'telemetry',
      feature: 'Telemetry Sync',
      wording: 'Reserved — requires future security doctrine. No peer telemetry sync in this baseline.',
      reason: 'Reserved — requires future security doctrine',
      futureRequirements: [
        'STUN P2P',
        'ChaCha20-Poly1305 in-flight encryption',
        'peer-relay fallback',
      ],
      authorities: [
        'UI Blueprint §23',
        'Backend Blueprint §23.5',
        'Future Squadron Security Doctrine',
      ],
    },
    {
      id: 'three_tier_cross_squadron_model',
      section: 'roles',
      feature: 'Three-Tier Cross-Squadron Model',
      wording: 'Reserved — requires future security doctrine.',
      reason: 'Reserved — requires future security doctrine',
      authorities: ['UI Blueprint §23', 'Future Squadron Security Doctrine'],
    },
    {
      id: 'loot_coordination',
      section: 'shared-operations',
      feature: 'Loot Coordination',
      wording: 'Reserved — requires future security doctrine.',
      reason: 'Reserved — requires future security doctrine',
      authorities: ['UI Blueprint §23', 'Future Squadron Security Doctrine'],
    },
    {
      id: 'top_secret_mode',
      section: 'emergency',
      feature: 'Top Secret Mode',
      wording: 'Reserved — requires future security doctrine.',
      reason: 'Reserved — requires future security doctrine',
      authorities: [
        'UI Blueprint §23',
        'Backend Blueprint §23.5',
        'Future Squadron Security Doctrine',
      ],
    },
    {
      id: 'burn_command',
      section: 'emergency',
      feature: 'Burn Command',
      wording: 'Reserved — requires future security doctrine. Burn Command requires Confirmation Gate, full security doctrine, and Activity Log/security review before activation.',
      reason: 'Reserved — requires future security doctrine',
      authorities: [
        'UI Blueprint §23',
        'Backend Blueprint §12',
        'Future Squadron Security Doctrine',
      ],
    },
    {
      id: 'discord_integration',
      section: 'integrations',
      feature: 'Discord',
      wording: 'Reserved — requires separate Commander-approved provider-enablement playbook with Source Verification and Compliance Review evidence.',
      reason: 'Reserved — requires provider enablement playbook',
      authorities: ['UI Blueprint §23', 'Compliance Matrix §7', 'Source Capability §2.19'],
    },
    {
      id: 'capi_commander_profile',
      section: 'integrations',
      feature: 'CAPI commander profile',
      wording: 'Reserved — requires provider enablement playbook.',
      reason: 'Reserved — requires provider enablement playbook',
      authorities: ['Source Capability §2.19', 'Compliance Matrix §4.3'],
    },
    {
      id: 'inara_get_commander_profile',
      section: 'integrations',
      feature: 'Inara getCommanderProfile',
      wording: 'Reserved — requires provider enablement playbook.',
      reason: 'Reserved — requires provider enablement playbook',
      authorities: ['Source Capability §2.19', 'Compliance Matrix §5.3'],
    },
    {
      id: 'edsm_commander_api',
      section: 'integrations',
      feature: 'EDSM commander API',
      wording: 'Reserved — requires provider enablement playbook.',
      reason: 'Reserved — requires provider enablement playbook',
      authorities: ['Source Capability §2.19', 'Compliance Matrix §5.3'],
    },
  ]);

  let commandPrimitivesPromise = null;
  let commandPrimitivesModule = null;

  function getCommandPrimitives() {
    if (commandPrimitivesModule) {
      return Promise.resolve(commandPrimitivesModule);
    }

    if (!commandPrimitivesPromise) {
      commandPrimitivesPromise = import('../components/command-primitives.js')
        .then((module) => {
          commandPrimitivesModule = module;
          return module;
        });
    }

    return commandPrimitivesPromise;
  }

  class SquadronsController {
    constructor(rootOverride = null) {
      this._root = rootOverride || document.getElementById('squadrons-root');
      this.init();
    }

    get _apiBase() {
      return window.Shell && window.Shell.httpBase ? window.Shell.httpBase : null;
    }

    init() {
      if (!this._root) return;
      this._renderWaiting();
      if (this._apiBase) {
        this.fetchAndRender();
        return;
      }
      if (window.OmniEvents) {
        window.OmniEvents.addEventListener('bridge-connected', () => {
          this.fetchAndRender();
        });
      }
    }

    async fetchAndRender() {
      const base = this._apiBase;
      if (!base) {
        this.renderUnavailable('Waiting for OmniCOVAS bridge.', NOT_LOADED);
        return;
      }

      try {
        const [
          overviewResp,
          rosterResp,
          invitesResp,
          telemetrySyncResp,
          rolesResp,
          sharedOpsResp,
          sharedNavResp,
          emergencyResp,
          logResp,
          integrationsResp,
          campaignNotesResp,
        ] = await Promise.all([
          window.fetch(base + OVERVIEW_PATH),
          window.fetch(base + ROSTER_PATH),
          window.fetch(base + INVITES_PATH),
          window.fetch(base + TELEMETRY_SYNC_PATH),
          window.fetch(base + ROLES_PATH),
          window.fetch(base + SHARED_OPERATIONS_PATH),
          window.fetch(base + SHARED_NAVIGATION_PATH),
          window.fetch(base + EMERGENCY_PATH),
          window.fetch(base + LOG_PATH),
          window.fetch(base + INTEGRATIONS_PATH),
          window.fetch(base + CAMPAIGN_NOTES_PATH).catch(() => null),
        ]);

        const safeJson = async (resp) => {
          if (!resp || !resp.ok) return null;
          try { return await resp.json(); } catch { return null; }
        };

        const [
          overview,
          roster,
          invites,
          telemetrySync,
          roles,
          sharedOps,
          sharedNav,
          emergency,
          log,
          integrations,
          campaignNotes,
        ] = await Promise.all([
          safeJson(overviewResp),
          safeJson(rosterResp),
          safeJson(invitesResp),
          safeJson(telemetrySyncResp),
          safeJson(rolesResp),
          safeJson(sharedOpsResp),
          safeJson(sharedNavResp),
          safeJson(emergencyResp),
          safeJson(logResp),
          safeJson(integrationsResp),
          safeJson(campaignNotesResp),
        ]);

        await this.render({
          overview,
          roster,
          invites,
          telemetrySync,
          roles,
          sharedOps,
          sharedNav,
          emergency,
          log,
          integrations,
          campaignNotes,
        });
      } catch (_err) {
        this.renderUnavailable('Squadrons bridge unreachable.', NOT_LOADED);
      }
    }

    render({ overview, roster, invites, telemetrySync, roles, sharedOps, sharedNav, emergency, log, integrations, campaignNotes }) {
      if (!this._root) return;
      const renderArgs = {
        overview,
        roster,
        invites,
        telemetrySync,
        roles,
        sharedOps,
        sharedNav,
        emergency,
        log,
        integrations,
        campaignNotes,
      };

      if (commandPrimitivesModule) {
        return Promise.resolve(this._renderCommandSurface(renderArgs, commandPrimitivesModule));
      }

      this._renderPrimitiveLoadingState();
      return getCommandPrimitives()
        .then((primitives) => this._renderCommandSurface(renderArgs, primitives))
        .catch((_err) => {
          this.renderUnavailable('Squadrons command surface unavailable.', NOT_LOADED);
          return null;
        });
    }

    _createHeader() {
      const header = document.createElement('div');
      header.className = 'squadrons-header';

      const h1 = document.createElement('h1');
      h1.id = 'squadrons-title';
      h1.className = 'squadrons-heading';
      h1.textContent = 'Squadrons';
      header.appendChild(h1);

      const sub = document.createElement('p');
      sub.className = 'squadrons-subheading';
      sub.textContent = 'Local Coordination';
      header.appendChild(sub);

      return header;
    }

    _renderCommandSurface(data, primitives) {
      if (!this._root) return null;

      this._root.replaceChildren(
        this._createRouteHero(primitives),
        this._createLocalCoordinationIntro(),
        this._createAvailableNowSection(data, primitives),
        this._createLocalStatusSection(data, primitives),
        this._createPhase9CampaignCoordinationSection(data.campaignNotes),
        this._createFutureRoadmapSection(primitives),
      );

      this._applyRouteTransferArrival();
      return this._root;
    }

    _createRouteHero(primitives) {
      const hero = primitives.createRouteHero({
        kicker: 'Local Coordination',
        title: 'Squadrons',
        statusText: 'Local coordination available',
        statusVariant: 'available',
        primaryValues: [
          { label: 'Share scope', value: 'Local' },
          { label: 'Local status', value: 'No active group plan' },
          { label: 'Sync', value: 'Not available yet' },
          { label: 'Reserved features', value: `${RESERVED_SURFACES.length} reserved` },
        ],
      });

      const title = hero.querySelector('.route-hero-title');
      if (title) {
        title.id = 'squadrons-title';
      }

      return hero;
    }

    _createLocalCoordinationIntro() {
      const intro = document.createElement('p');
      intro.className = 'squadrons-local-intro';
      intro.textContent = 'Local-only coordination tools are available in this build.';
      return intro;
    }

    _createCommandSection(title, description) {
      const section = document.createElement('section');
      section.className = 'squadrons-command-section';
      section.setAttribute('aria-labelledby', this._sectionIdFromTitle(title));

      const header = document.createElement('header');
      header.className = 'squadrons-command-section-header';

      const h2 = document.createElement('h2');
      h2.id = this._sectionIdFromTitle(title);
      h2.className = 'squadrons-command-section-title';
      h2.textContent = title;
      header.appendChild(h2);

      if (description) {
        const copy = document.createElement('p');
        copy.className = 'squadrons-command-section-copy';
        copy.textContent = description;
        header.appendChild(copy);
      }

      section.appendChild(header);
      return section;
    }

    _sectionIdFromTitle(title) {
      return `squadrons-${String(title).toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
    }

    _routeTransfer(input) {
      return {
        originRoute: '/squadrons',
        originPackage: 'Squadrons',
        originSectionId: input.originSectionId || '',
        targetRoute: input.targetRoute,
        targetSectionId: input.targetSectionId || '',
        targetEntityId: input.targetEntityId || '',
        targetLabel: input.targetLabel || '',
        reason: input.reason || '',
        returnLabel: input.returnLabel || 'Return to Squadrons',
        returnTarget: {
          route: '/squadrons',
          package: 'Squadrons',
          sectionId: input.originSectionId || '',
          entityId: input.originEntityId || '',
        },
      };
    }

    _routeTransferClick(input) {
      return (event) => {
        if (typeof window.Shell?.startRouteTransfer !== 'function') {
          return;
        }

        const href = event.currentTarget?.getAttribute('href') || '';
        event.preventDefault();
        if (!window.Shell.startRouteTransfer(this._routeTransfer(input)) && href) {
          window.location.hash = href;
        }
      };
    }

    _applyRouteTransferArrival() {
      window.Shell?.applyRouteTransferArrival?.('/squadrons', this._root);
    }

    _createAvailableNowSection(data, primitives) {
      const section = this._createCommandSection(
        'Available Now',
        'Current local coordination tools stay on this machine.',
      );
      const grid = document.createElement('div');
      grid.className = 'squadrons-command-grid squadrons-command-grid--available';

      grid.appendChild(primitives.createCommandCard({
        title: 'Local Share Scope',
        primaryValue: 'Share scope local',
        statusBadge: { variant: 'local-only', label: 'Local-only' },
        detail: () => this._createShareScopeDetail(data.overview),
      }));

      grid.appendChild(primitives.createCommandCard({
        title: 'Local Coordination',
        primaryValue: 'No active group plan',
        statusBadge: { variant: 'available', label: 'Available' },
        detail: () => this._createLocalCoordinationDetail(data),
      }));

      grid.appendChild(primitives.createCommandCard({
        title: 'Operations Handoff',
        primaryValue: 'Open Operations',
        statusBadge: { variant: 'available', label: 'Available' },
        action: {
          label: 'Open Operations',
          href: '#/operations',
          onClick: this._routeTransferClick({
            originSectionId: 'squadrons-available-now',
            targetRoute: '/operations',
            targetSectionId: 'operations-package-workspace',
            targetLabel: 'Operations package workspace',
            reason: 'Operations owns active package internals for current work.',
            returnLabel: 'Return to Squadrons local coordination',
          }),
        },
        detail: () => this._createOperationsHandoffDetail(),
      }));

      grid.appendChild(primitives.createCommandCard({
        title: 'Blocked Intent Proof',
        primaryValue: 'Intent recording available',
        statusBadge: { variant: 'reserved', label: 'Reserved' },
        action: {
          label: 'View Activity Log proof',
          href: '#/activity-log',
          onClick: this._routeTransferClick({
            originSectionId: 'squadrons-available-now',
            targetRoute: '/activity-log',
            targetSectionId: 'log-body',
            targetLabel: 'Activity Log proof',
            reason: 'Activity Log owns proof records for reserved blocked intent.',
            returnLabel: 'Return to Squadrons',
          }),
        },
        detail: () => this._createBlockedIntentSummaryDetail(),
      }));

      section.appendChild(grid);
      return section;
    }

    _createShareScopeDetail(overview) {
      const detail = document.createElement('div');
      detail.className = 'squadrons-detail-stack';
      detail.appendChild(this._createFactRow('Share scope', 'Local'));
      detail.appendChild(this._createFactRow('Outbound traffic', 'Off'));
      detail.appendChild(this._createFactRow('Sync', 'Not available yet'));
      detail.appendChild(this._createCaveat('Local-only squadron state. No external profile calls.'));
      detail.appendChild(this._createFallbackWordList());

      if (!overview) {
        detail.appendChild(this._createEmptyState('No local squadron overview data.'));
      }

      return detail;
    }

    _createLocalCoordinationDetail(data) {
      const detail = document.createElement('div');
      detail.className = 'squadrons-detail-stack squadrons-local-tools';
      detail.appendChild(this._createRosterSectionWithWrites(data.roster));
      detail.appendChild(this._createInvitesSectionWithWrites(data.invites));
      detail.appendChild(this._createRolesSectionWithWrites(data.roles));
      detail.appendChild(this._createSharedOpsSectionWithWrites(data.sharedOps));
      detail.appendChild(this._createSharedNavSectionWithWrites(data.sharedNav));
      detail.appendChild(this._createEmergencySectionWithWrites(data.emergency));
      detail.appendChild(this._createLogSectionWithWrites(data.log));
      return detail;
    }

    _createOperationsHandoffDetail() {
      const detail = document.createElement('div');
      detail.className = 'squadrons-detail-stack';
      detail.appendChild(this._createCaveat(
        'Operations owns active package internals. Squadrons keeps local group coordination context.',
      ));
      detail.appendChild(this._createFactRow('Handoff', 'Operations route'));
      return detail;
    }

    _createBlockedIntentSummaryDetail() {
      const detail = document.createElement('div');
      detail.className = 'squadrons-detail-stack';
      detail.appendChild(this._createCaveat(
        'Reserved features can record blocked local intent as proof only. No feature is enabled.',
      ));
      detail.appendChild(this._createProofActionLinks());
      return detail;
    }

    _createProofActionLinks() {
      if (commandPrimitivesModule && typeof commandPrimitivesModule.createActionLinkGroup === 'function') {
        return commandPrimitivesModule.createActionLinkGroup(
          [{
            label: 'View source event',
            href: '#/activity-log',
            onClick: this._routeTransferClick({
              originSectionId: 'squadrons-available-now',
              targetRoute: '/activity-log',
              targetSectionId: 'log-body',
              targetLabel: 'Squadrons proof records',
              reason: 'Activity Log owns proof for blocked local squadron intent.',
              returnLabel: 'Return to Squadrons proof',
            }),
          }],
          { ariaLabel: 'Squadrons proof links' },
        );
      }

      const group = document.createElement('nav');
      group.className = 'action-link-group';
      group.setAttribute('role', 'group');
      group.setAttribute('aria-label', 'Squadrons proof links');

      const link = document.createElement('a');
      link.className = 'action-link';
      link.href = '#/activity-log';
      link.textContent = 'View source event';
      link.addEventListener('click', this._routeTransferClick({
        originSectionId: 'squadrons-available-now',
        targetRoute: '/activity-log',
        targetSectionId: 'log-body',
        targetLabel: 'Squadrons proof records',
        reason: 'Activity Log owns proof for blocked local squadron intent.',
        returnLabel: 'Return to Squadrons proof',
      }));
      group.appendChild(link);
      return group;
    }

    _createLocalStatusSection(data, primitives) {
      const section = this._createCommandSection(
        'Local Status / Privacy',
        'Network and provider posture is summarized here; implementation details stay behind disclosure.',
      );
      const grid = document.createElement('div');
      grid.className = 'squadrons-command-grid squadrons-command-grid--status';

      grid.appendChild(primitives.createCommandCard({
        title: 'Outbound Traffic',
        primaryValue: 'Off',
        statusBadge: { variant: 'off', label: 'Off' },
        detail: () => this._createOutboundStatusDetail(),
      }));

      grid.appendChild(primitives.createCommandCard({
        title: 'Sync',
        primaryValue: 'Not available yet',
        statusBadge: { variant: 'disabled', label: 'Disabled' },
        detail: () => this._createSyncStatusDetail(data.telemetrySync),
      }));

      grid.appendChild(primitives.createCommandCard({
        title: 'External Providers',
        primaryValue: 'Disabled',
        statusBadge: { variant: 'disabled', label: 'Disabled' },
        detail: () => this._createProviderStatusDetail(data.integrations),
      }));

      grid.appendChild(primitives.createCommandCard({
        title: 'Local-only Posture',
        primaryValue: 'Local-only',
        statusBadge: { variant: 'local-only', label: 'Local-only' },
        detail: () => this._createLocalOnlyStatusDetail(),
      }));

      section.appendChild(grid);
      return section;
    }

    _createOutboundStatusDetail() {
      const detail = document.createElement('div');
      detail.className = 'squadrons-detail-stack';
      detail.appendChild(this._createFactRow('Outbound traffic', 'Off'));
      detail.appendChild(this._createFactRow('Local-only baseline', 'true'));
      detail.appendChild(this._createCaveat('No outbound call.'));
      return detail;
    }

    _createSyncStatusDetail(telemetrySync) {
      const detail = document.createElement('div');
      detail.className = 'squadrons-detail-stack';
      detail.appendChild(this._createFactRow('Sync', 'Not available yet'));
      detail.appendChild(this._createFactRow(
        'Active',
        telemetrySync ? String(telemetrySync.active) : 'false',
      ));
      detail.appendChild(this._createFactRow(
        'Last sync',
        telemetrySync && telemetrySync.last_sync_at ? telemetrySync.last_sync_at : null,
      ));
      return detail;
    }

    _createProviderStatusDetail(integrations) {
      const detail = document.createElement('div');
      detail.className = 'squadrons-detail-stack';
      detail.appendChild(this._createFactRow('External providers', 'Disabled'));
      detail.appendChild(this._createIntegrationsSection(integrations));
      return detail;
    }

    _createLocalOnlyStatusDetail() {
      const detail = document.createElement('div');
      detail.className = 'squadrons-detail-stack';
      detail.appendChild(this._createFactRow('Local-only', 'true'));
      detail.appendChild(this._createFactRow('Share scope', 'Local'));
      detail.appendChild(this._createCaveat(LOCAL_ONLY_NOTE));
      return detail;
    }

    _createPhase9CampaignCoordinationSection(campaignNotes) {
      const section = document.createElement('details');
      section.className = 'squadrons-command-section squadrons-phase9-campaign-coordination';
      section.id = 'squadrons-phase9-campaign-coordination';

      const summary = document.createElement('summary');
      summary.className = 'squadrons-future-summary';
      summary.id = 'squadrons-phase9-campaign-summary';
      summary.textContent = 'Phase 9 Campaign Coordination (Local Only)';
      section.appendChild(summary);

      const copy = document.createElement('p');
      copy.className = 'squadrons-command-section-copy';
      copy.textContent =
        'Local-only squadron campaign notes. Shared campaign state is Reserved — Phase 7 squadron backend required.';
      section.appendChild(copy);

      const statusStack = document.createElement('div');
      statusStack.className = 'squadrons-detail-stack';
      statusStack.appendChild(this._createFactRow('Share scope', 'Local — no outbound'));
      statusStack.appendChild(
        this._createFactRow('Shared campaign state', 'Reserved — Phase 7 backend required'),
      );
      statusStack.appendChild(this._createFactRow('External squadron sync', 'Disabled'));
      statusStack.appendChild(
        this._createFactRow('Provider coordination', 'No Verified Source — Unsupported'),
      );
      statusStack.appendChild(this._createFactRow('Local notes', 'Local-only'));
      section.appendChild(statusStack);

      const notes =
        campaignNotes && Array.isArray(campaignNotes.notes) ? campaignNotes.notes : null;

      if (notes === null) {
        const fallback = document.createElement('p');
        fallback.className = 'squadrons-fallback';
        fallback.textContent = 'Not Loaded — campaign notes endpoint unavailable.';
        section.appendChild(fallback);
      } else if (notes.length === 0) {
        section.appendChild(this._createEmptyState('No local campaign notes.'));
      } else {
        const list = document.createElement('ul');
        list.className = 'squadrons-list squadrons-campaign-notes-list';
        list.setAttribute('aria-label', 'Local campaign notes');

        notes.forEach((note) => {
          const item = document.createElement('li');
          item.className = 'squadrons-list-item squadrons-campaign-note-item';

          const typeBadge = document.createElement('span');
          typeBadge.className = 'squadrons-campaign-note-type';
          typeBadge.textContent = note.workflow_type || '—';
          item.appendChild(typeBadge);

          const textEl = document.createElement('span');
          textEl.className = 'squadrons-campaign-note-text';
          textEl.textContent = note.note_text || '—';
          item.appendChild(textEl);

          if (note.linked_campaign_id) {
            const idEl = document.createElement('span');
            idEl.className = 'squadrons-campaign-note-campaign-id';
            idEl.textContent = 'Linked objective: ' + note.linked_campaign_id;
            item.appendChild(idEl);
          }

          /* PB09-08: View Campaign bridge link */
          if (note.linked_campaign_id) {
            const viewCampaignBtn = document.createElement('button');
            viewCampaignBtn.className = 'sq-bridge-btn';
            viewCampaignBtn.setAttribute('type', 'button');
            viewCampaignBtn.setAttribute('aria-label', 'View linked campaign in Operations');
            viewCampaignBtn.textContent = 'View Campaign';
            viewCampaignBtn.addEventListener('click', () => {
              if (typeof window.Shell?.startRouteTransfer !== 'function') {
                window.location.hash = '#/operations';
                return;
              }
              const wsHint = `operations-phase9-${note.workflow_type || 'bgs'}-workspace`;
              window.Shell.startRouteTransfer({
                originRoute: '/squadrons',
                originPackage: 'Squadrons',
                originSectionId: 'squadrons-phase9-campaign-coordination',
                targetRoute: '/operations',
                targetSectionId: wsHint,
                targetEntityId: note.linked_campaign_id,
                targetLabel: 'Operations campaign workspace',
                reason: 'Viewing campaign from local note.',
                returnLabel: 'Return to Squadrons',
                returnTarget: { route: '/squadrons' },
              });
            });
            item.appendChild(viewCampaignBtn);
          }

          /* PB09-08: View Proof bridge link */
          if (note.note_id) {
            const viewProofBtn = document.createElement('button');
            viewProofBtn.className = 'sq-bridge-btn';
            viewProofBtn.setAttribute('type', 'button');
            viewProofBtn.setAttribute('aria-label', 'View note proof in Activity Log');
            viewProofBtn.textContent = 'View Proof';
            viewProofBtn.addEventListener('click', () => {
              if (typeof window.Shell?.startRouteTransfer !== 'function') {
                window.location.hash = '#/activity-log';
                return;
              }
              window.Shell.startRouteTransfer({
                originRoute: '/squadrons',
                originPackage: 'Squadrons',
                originSectionId: 'squadrons-phase9-campaign-coordination',
                targetRoute: '/activity-log',
                targetSectionId: 'log-body',
                targetEntityId: note.note_id,
                targetLabel: 'Activity Log proof',
                reason: 'Viewing note proof.',
                returnLabel: 'Return to Squadrons',
                returnTarget: { route: '/squadrons' },
              });
            });
            item.appendChild(viewProofBtn);
          }

          if (note.note_id) {
            const archiveBtn = document.createElement('button');
            archiveBtn.className = 'sq-revoke-btn';
            archiveBtn.setAttribute('type', 'button');
            archiveBtn.setAttribute('aria-label', 'Archive campaign note');
            archiveBtn.textContent = 'Archive';
            archiveBtn.addEventListener('click', () => {
              this._handleArchiveCampaignNote(note.note_id);
            });
            item.appendChild(archiveBtn);
          }

          list.appendChild(item);
        });
        section.appendChild(list);
      }

      section.appendChild(
        this._createCaveat('Local-only — no outbound. Notes visible to this commander only.'),
      );
      section.appendChild(
        this._createAddButton('Add Campaign Note', LOCAL_ONLY_WRITE_NOTE, () => {
          this._handleAddCampaignNote();
        }),
      );

      return section;
    }

    _createFutureRoadmapSection(primitives) {
      const section = document.createElement('details');
      section.className = 'squadrons-command-section squadrons-future-roadmap';

      const summary = document.createElement('summary');
      summary.className = 'squadrons-future-summary';
      summary.textContent = 'Reserved Features';
      section.appendChild(summary);

      const copy = document.createElement('p');
      copy.className = 'squadrons-command-section-copy';
      copy.textContent = 'Reserved squadron capabilities remain unavailable in this build.';
      section.appendChild(copy);

      const rows = document.createElement('div');
      rows.className = 'squadrons-reserved-row-list';

      RESERVED_SURFACES.forEach((surface) => {
        rows.appendChild(this._createReservedRoadmapRow(surface, primitives));
      });

      section.appendChild(rows);
      return section;
    }

    _createReservedRoadmapRow(surface, primitives) {
      const wrapper = document.createElement('div');
      wrapper.className = 'squadrons-reserved-row-shell';
      wrapper.dataset.reservedFeature = surface.id;

      const detailHost = document.createElement('div');
      detailHost.className = 'squadrons-reserved-detail-host';
      detailHost.id = `squadrons-reserved-detail-${surface.id}`;

      let inspectButton = null;
      const row = primitives.createReservedFeatureRow({
        name: surface.feature,
        badge: 'reserved',
        inspectLabel: 'Details',
        onInspect: () => {
          this._toggleReservedSurfaceDetails(surface, detailHost, inspectButton);
        },
      });
      row.dataset.reservedFeatureRow = surface.id;
      inspectButton = row.querySelector('.reserved-feature-inspect');
      if (inspectButton) {
        inspectButton.setAttribute('aria-expanded', 'false');
        inspectButton.setAttribute('aria-controls', detailHost.id);
      }

      wrapper.appendChild(row);
      wrapper.appendChild(detailHost);
      return wrapper;
    }

    _toggleReservedSurfaceDetails(surface, detailHost, inspectButton) {
      if (!detailHost) return;
      const isOpen = detailHost.dataset.open === 'true';
      if (isOpen) {
        detailHost.replaceChildren();
        detailHost.dataset.open = 'false';
        if (inspectButton) inspectButton.setAttribute('aria-expanded', 'false');
        return;
      }

      detailHost.replaceChildren(this._createReservedSurfaceDetail(surface));
      detailHost.dataset.open = 'true';
      if (inspectButton) inspectButton.setAttribute('aria-expanded', 'true');
    }

    _createReservedSurfaceDetail(surface) {
      const card = document.createElement('article');
      card.className = 'squadrons-reserved-detail';

      const title = document.createElement('h3');
      title.className = 'squadrons-reserved-title';
      title.textContent = surface.feature;

      const wording = document.createElement('p');
      wording.className = 'squadrons-reserved-wording';
      wording.textContent = surface.wording;

      const statusList = document.createElement('ul');
      statusList.className = 'squadrons-reserved-status-list';
      [
        'Not enabled.',
        'Local-only baseline.',
        'No outbound call.',
        'No provider, transport, OAuth, encryption, or relay activation.',
      ].forEach((text) => {
        const item = document.createElement('li');
        item.textContent = text;
        statusList.appendChild(item);
      });

      card.appendChild(title);
      card.appendChild(wording);
      card.appendChild(statusList);

      if (Array.isArray(surface.futureRequirements) && surface.futureRequirements.length > 0) {
        card.appendChild(this._createReservedLabelGroup(
          'Future requirements',
          surface.futureRequirements,
          'squadrons-reserved-requirements',
        ));
      }

      card.appendChild(this._createReservedLabelGroup(
        'Authority',
        surface.authorities || [],
        'squadrons-reserved-authorities',
      ));

      const controls = document.createElement('div');
      controls.className = 'squadrons-reserved-controls';

      const button = document.createElement('button');
      button.className = 'sq-reserved-intent-btn';
      button.setAttribute('type', 'button');
      button.textContent = 'Record blocked local intent';

      const status = document.createElement('p');
      status.className = 'sq-reserved-intent-status';
      status.setAttribute('aria-live', 'polite');
      status.textContent = 'Feature remains reserved.';

      const proof = document.createElement('div');
      proof.className = 'sq-reserved-proof';
      proof.setAttribute('aria-live', 'polite');

      button.addEventListener('click', () => {
        this._handleReservedIntent(surface.id, status, proof);
      });

      controls.appendChild(button);
      controls.appendChild(status);
      card.appendChild(controls);
      card.appendChild(proof);

      return card;
    }

    _createOverviewSection(overview) {
      const section = this._createSection('Overview');

      const localNote = document.createElement('p');
      localNote.className = 'squadrons-caveat';
      localNote.textContent = 'Local-only squadron state. No external profile calls.';
      section.appendChild(localNote);
      section.appendChild(this._createFallbackWordList());

      const peerCount = overview && Array.isArray(overview.peers) ? overview.peers.length : 0;
      section.appendChild(this._createFactRow('Peers', String(peerCount)));

      const syncActive = overview && overview.telemetry_sync
        ? String(overview.telemetry_sync.active)
        : 'false';
      section.appendChild(this._createFactRow('Telemetry sync', syncActive));

      const roleCount = overview && Array.isArray(overview.roles) ? overview.roles.length : 0;
      section.appendChild(this._createFactRow('Roles defined', String(roleCount)));

      if (!overview) {
        section.appendChild(this._createEmptyState('No local squadron overview data.'));
      }

      return section;
    }

    _createRosterSection(roster) {
      const section = this._createSection('Roster / Peers');

      const peers = roster && Array.isArray(roster.peers) ? roster.peers : [];

      if (peers.length === 0) {
        section.appendChild(this._createEmptyState('No local peer data.'));
        section.appendChild(this._createCaveat(LOCAL_ONLY_NOTE));
        return section;
      }

      const list = document.createElement('ul');
      list.className = 'squadrons-list';

      peers.forEach(function (peer) {
        const item = document.createElement('li');
        item.className = 'squadrons-list-item';

        const nameEl = document.createElement('span');
        nameEl.className = 'squadrons-peer-name';
        nameEl.textContent = peer.commander_name || 'Unknown';
        item.appendChild(nameEl);

        if (peer.role) {
          const roleEl = document.createElement('span');
          roleEl.className = 'squadrons-peer-role';
          roleEl.textContent = peer.role;
          item.appendChild(roleEl);
        }

        list.appendChild(item);
      });

      section.appendChild(list);
      return section;
    }

    _createInvitesSection(invites) {
      const section = this._createSection('Invites');

      const codes = invites && Array.isArray(invites.invites) ? invites.invites : [];

      if (codes.length === 0) {
        section.appendChild(this._createEmptyState('No local invite data.'));
        return section;
      }

      const list = document.createElement('ul');
      list.className = 'squadrons-list';

      codes.forEach(function (invite) {
        const item = document.createElement('li');
        item.className = 'squadrons-list-item';

        const codeEl = document.createElement('span');
        codeEl.className = 'squadrons-invite-code';
        codeEl.textContent = invite.code || 'Unknown code';
        item.appendChild(codeEl);

        if (invite.expires_at) {
          const expiryEl = document.createElement('span');
          expiryEl.className = 'squadrons-invite-expiry';
          expiryEl.textContent = 'Expires: ' + invite.expires_at;
          item.appendChild(expiryEl);
        }

        list.appendChild(item);
      });

      section.appendChild(list);
      return section;
    }

    _createTelemetrySyncSection(telemetrySync) {
      const section = this._createSection('Telemetry Sync');

      const active = telemetrySync ? String(telemetrySync.active) : 'false';
      section.appendChild(this._createFactRow('Active', active));

      const lastSync = telemetrySync && telemetrySync.last_sync_at
        ? telemetrySync.last_sync_at
        : null;
      section.appendChild(this._createFactRow('Last sync', lastSync));

      return section;
    }

    _createRolesSection(roles) {
      const section = this._createSection('Roles / Authority');

      const roleList = roles && Array.isArray(roles.roles) ? roles.roles : [];

      if (roleList.length === 0) {
        section.appendChild(this._createEmptyState('No local role data.'));
        return section;
      }

      const list = document.createElement('ul');
      list.className = 'squadrons-list';

      roleList.forEach(function (role) {
        const item = document.createElement('li');
        item.className = 'squadrons-list-item';

        const nameEl = document.createElement('span');
        nameEl.className = 'squadrons-role-name';
        nameEl.textContent = role.role_name || 'Unknown role';
        item.appendChild(nameEl);

        if (Array.isArray(role.permissions) && role.permissions.length > 0) {
          const permEl = document.createElement('span');
          permEl.className = 'squadrons-role-permissions';
          permEl.textContent = role.permissions.join(', ');
          item.appendChild(permEl);
        }

        list.appendChild(item);
      });

      section.appendChild(list);
      return section;
    }

    _createSharedOperationsSection(sharedOps) {
      const section = this._createSection('Shared Operations');

      const links = sharedOps && Array.isArray(sharedOps.shared_operations)
        ? sharedOps.shared_operations
        : [];

      if (links.length === 0) {
        section.appendChild(this._createEmptyState('No local shared operations data.'));
        section.appendChild(this._createCaveat(LOCAL_ONLY_NOTE));
        return section;
      }

      const list = document.createElement('ul');
      list.className = 'squadrons-list';

      links.forEach(function (op) {
        const item = document.createElement('li');
        item.className = 'squadrons-list-item';

        const labelEl = document.createElement('span');
        labelEl.className = 'squadrons-op-label';
        labelEl.textContent = op.label || op.operation_id || 'Unknown operation';
        item.appendChild(labelEl);

        list.appendChild(item);
      });

      section.appendChild(list);
      return section;
    }

    _createSharedNavigationSection(sharedNav) {
      const section = this._createSection('Shared Navigation');

      const links = sharedNav && Array.isArray(sharedNav.shared_navigation)
        ? sharedNav.shared_navigation
        : [];

      if (links.length === 0) {
        section.appendChild(this._createEmptyState('No local shared navigation data.'));
        section.appendChild(this._createCaveat(LOCAL_ONLY_NOTE));
        return section;
      }

      const list = document.createElement('ul');
      list.className = 'squadrons-list';

      links.forEach(function (nav) {
        const item = document.createElement('li');
        item.className = 'squadrons-list-item';

        const sysEl = document.createElement('span');
        sysEl.className = 'squadrons-nav-system';
        sysEl.textContent = nav.system_name || 'Unknown system';
        item.appendChild(sysEl);

        if (nav.objective) {
          const objEl = document.createElement('span');
          objEl.className = 'squadrons-nav-objective';
          objEl.textContent = nav.objective;
          item.appendChild(objEl);
        }

        list.appendChild(item);
      });

      section.appendChild(list);
      return section;
    }

    _createEmergencySecuritySection(emergency) {
      const section = this._createSection('Emergency / Security');

      const active = emergency ? String(emergency.active) : 'false';
      section.appendChild(this._createFactRow('Active', active));

      const reason = emergency && emergency.reason ? emergency.reason : null;
      section.appendChild(this._createFactRow('Reason', reason));

      return section;
    }

    _createSquadronLogSection(log) {
      const section = this._createSection('Squadron Log');

      const entries = log && Array.isArray(log.log) ? log.log : [];

      if (entries.length === 0) {
        section.appendChild(this._createEmptyState('No local squadron log entries.'));
        return section;
      }

      const list = document.createElement('ul');
      list.className = 'squadrons-list';

      entries.forEach(function (entry) {
        const item = document.createElement('li');
        item.className = 'squadrons-list-item';

        const tsEl = document.createElement('span');
        tsEl.className = 'squadrons-log-timestamp';
        tsEl.textContent = entry.timestamp || '—';
        item.appendChild(tsEl);

        const typeEl = document.createElement('span');
        typeEl.className = 'squadrons-log-type';
        typeEl.textContent = entry.event_type || '—';
        item.appendChild(typeEl);

        if (entry.summary) {
          const summaryEl = document.createElement('span');
          summaryEl.className = 'squadrons-log-summary';
          summaryEl.textContent = entry.summary;
          item.appendChild(summaryEl);
        }

        list.appendChild(item);
      });

      section.appendChild(list);
      return section;
    }

    _createIntegrationsSection(integrations) {
      const section = this._createSection('Integrations');

      const integrationList = integrations && Array.isArray(integrations.integrations)
        ? integrations.integrations
        : [];

      if (integrationList.length === 0) {
        section.appendChild(this._createEmptyState('No local integrations enabled.'));
        return section;
      }

      const list = document.createElement('ul');
      list.className = 'squadrons-list';

      integrationList.forEach(function (integration) {
        const item = document.createElement('li');
        item.className = 'squadrons-list-item';

        const providerEl = document.createElement('span');
        providerEl.className = 'squadrons-integration-provider';
        providerEl.textContent = integration.provider || 'Unknown provider';
        item.appendChild(providerEl);

        const statusEl = document.createElement('span');
        statusEl.className = 'squadrons-integration-status';
        statusEl.textContent = integration.status || 'not_shipped';
        item.appendChild(statusEl);

        list.appendChild(item);
      });

      section.appendChild(list);
      return section;
    }

    _appendReservedSurfaces(section, sectionKey) {
      RESERVED_SURFACES
        .filter((surface) => surface.section === sectionKey)
        .forEach((surface) => {
          section.appendChild(this._createReservedSurface(surface));
        });
    }

    _createReservedSurface(surface) {
      const card = document.createElement('article');
      card.className = 'squadrons-reserved-card';
      card.dataset.reservedFeature = surface.id;

      const title = document.createElement('h3');
      title.className = 'squadrons-reserved-title';
      title.textContent = surface.feature;

      const wording = document.createElement('p');
      wording.className = 'squadrons-reserved-wording';
      wording.textContent = surface.wording;

      const statusList = document.createElement('ul');
      statusList.className = 'squadrons-reserved-status-list';
      [
        'Not enabled.',
        'Local-only baseline.',
        'No outbound call.',
        'No provider, transport, OAuth, encryption, or relay activation.',
      ].forEach((text) => {
        const item = document.createElement('li');
        item.textContent = text;
        statusList.appendChild(item);
      });

      card.appendChild(title);
      card.appendChild(wording);
      card.appendChild(statusList);

      if (Array.isArray(surface.futureRequirements) && surface.futureRequirements.length > 0) {
        card.appendChild(this._createReservedLabelGroup(
          'Future requirements',
          surface.futureRequirements,
          'squadrons-reserved-requirements',
        ));
      }

      card.appendChild(this._createReservedLabelGroup(
        'Authority',
        surface.authorities || [],
        'squadrons-reserved-authorities',
      ));

      const controls = document.createElement('div');
      controls.className = 'squadrons-reserved-controls';

      const button = document.createElement('button');
      button.className = 'sq-reserved-intent-btn';
      button.setAttribute('type', 'button');
      button.textContent = 'Record blocked local intent';

      const status = document.createElement('p');
      status.className = 'sq-reserved-intent-status';
      status.setAttribute('aria-live', 'polite');
      status.textContent = 'Feature remains reserved.';

      button.addEventListener('click', () => {
        this._handleReservedIntent(surface.id, status);
      });

      controls.appendChild(button);
      controls.appendChild(status);
      card.appendChild(controls);

      return card;
    }

    _createReservedLabelGroup(label, values, className) {
      const group = document.createElement('div');
      group.className = className;

      const groupLabel = document.createElement('span');
      groupLabel.className = 'squadrons-reserved-label';
      groupLabel.textContent = label;
      group.appendChild(groupLabel);

      values.forEach((value) => {
        const chip = document.createElement('span');
        chip.className = 'squadrons-reserved-chip';
        chip.textContent = value;
        group.appendChild(chip);
      });

      return group;
    }

    _createFallbackWordList() {
      const group = document.createElement('div');
      group.className = 'squadrons-fallback-words';

      const label = document.createElement('span');
      label.className = 'squadrons-fallback-words-label';
      label.textContent = 'Fallback wording';
      group.appendChild(label);

      FALLBACK_WORDING.forEach((word) => {
        const chip = document.createElement('span');
        chip.className = 'squadrons-fallback-word';
        chip.textContent = word;
        group.appendChild(chip);
      });

      return group;
    }

    _createSection(title) {
      const section = document.createElement('div');
      section.className = 'squadrons-section';

      const h2 = document.createElement('h2');
      h2.className = 'squadrons-section-title';
      h2.textContent = title;
      section.appendChild(h2);

      return section;
    }

    _createFactRow(label, value) {
      const row = document.createElement('div');
      row.className = 'squadrons-fact-row';

      const labelEl = document.createElement('span');
      labelEl.className = 'squadrons-fact-label';
      labelEl.textContent = label;

      const valueEl = document.createElement('span');
      if (value !== null && value !== undefined) {
        valueEl.className = 'squadrons-fact-value';
        valueEl.textContent = String(value);
      } else {
        valueEl.className = 'squadrons-fact-value squadrons-fact-value--fallback';
        valueEl.textContent = 'Unknown';
      }

      row.appendChild(labelEl);
      row.appendChild(valueEl);
      return row;
    }

    _createEmptyState(text) {
      const el = document.createElement('p');
      el.className = 'squadrons-fallback';
      el.textContent = text;
      return el;
    }

    _createCaveat(text) {
      const el = document.createElement('p');
      el.className = 'squadrons-caveat';
      el.textContent = text;
      return el;
    }

    _renderWaiting() {
      if (!this._root) return;
      const msg = document.createElement('p');
      msg.className = 'squadrons-waiting';
      msg.textContent = 'Waiting for OmniCOVAS bridge.';
      const fallback = document.createElement('p');
      fallback.className = 'squadrons-fallback';
      fallback.textContent = 'Fallback: ' + NOT_LOADED;
      this._root.replaceChildren(msg, fallback);
    }

    _renderPrimitiveLoadingState() {
      if (!this._root) return;
      const section = document.createElement('section');
      section.className = 'squadrons-loading-state';
      section.setAttribute('role', 'status');
      section.setAttribute('aria-live', 'polite');

      const title = document.createElement('p');
      title.className = 'squadrons-waiting';
      title.textContent = 'Preparing local coordination surface.';
      section.appendChild(title);

      const status = document.createElement('p');
      status.className = 'squadrons-fallback';
      status.textContent = 'Local coordination available.';
      section.appendChild(status);

      this._root.replaceChildren(section);
    }

    renderUnavailable(message, fallbackText) {
      if (!this._root) return;
      const msg = document.createElement('p');
      msg.className = 'squadrons-unavailable-message';
      msg.textContent = message;
      const fallback = document.createElement('p');
      fallback.className = 'squadrons-unavailable-fallback';
      fallback.textContent = 'Fallback: ' + (fallbackText || NOT_LOADED);
      this._root.replaceChildren(this._createHeader(), msg, fallback);
    }

    // ── Write-flow section builders (PB07-07) ────────────────────────────────

    _createRosterSectionWithWrites(roster) {
      const section = this._createSection('Roster / Peers');
      section.appendChild(this._createCaveat(LOCAL_ONLY_NOTE));

      const peers = roster && Array.isArray(roster.peers) ? roster.peers : [];

      if (peers.length === 0) {
        section.appendChild(this._createEmptyState('No local peer data.'));
      } else {
        const list = document.createElement('ul');
        list.className = 'squadrons-list';
        peers.forEach((peer) => {
          const item = document.createElement('li');
          item.className = 'squadrons-list-item';
          const nameEl = document.createElement('span');
          nameEl.className = 'squadrons-peer-name';
          nameEl.textContent = peer.commander_name || 'Unknown';
          item.appendChild(nameEl);
          if (peer.role) {
            const roleEl = document.createElement('span');
            roleEl.className = 'squadrons-peer-role';
            roleEl.textContent = peer.role;
            item.appendChild(roleEl);
          }
          if (peer.id) {
            const revokeBtn = this._createRevokeButton(peer.id, () => {
              this._handleRevokeRoster(peer.id);
            });
            item.appendChild(revokeBtn);
          }
          list.appendChild(item);
        });
        section.appendChild(list);
      }

      section.appendChild(this._createAddButton('Add Roster Member', LOCAL_ONLY_WRITE_NOTE, () => {
        this._handleAddRosterMember();
      }));
      return section;
    }

    _createInvitesSectionWithWrites(invites) {
      const section = this._createSection('Invites');
      const codes = invites && Array.isArray(invites.invites) ? invites.invites : [];
      if (codes.length === 0) {
        section.appendChild(this._createEmptyState('No local invite data.'));
      } else {
        const list = document.createElement('ul');
        list.className = 'squadrons-list';
        codes.forEach((invite) => {
          const item = document.createElement('li');
          item.className = 'squadrons-list-item';
          const codeEl = document.createElement('span');
          codeEl.className = 'squadrons-invite-code';
          codeEl.textContent = invite.code || 'Unknown code';
          item.appendChild(codeEl);
          if (invite.id) {
            const revokeBtn = this._createRevokeButton(invite.id, () => {
              this._handleRevokeInvite(invite.id);
            });
            item.appendChild(revokeBtn);
          }
          list.appendChild(item);
        });
        section.appendChild(list);
      }
      section.appendChild(this._createAddButton('Add Invite Code', LOCAL_ONLY_WRITE_NOTE, () => {
        this._handleAddInviteCode();
      }));
      return section;
    }

    _createRolesSectionWithWrites(roles) {
      const section = this._createSection('Roles / Authority');
      const roleList = roles && Array.isArray(roles.roles) ? roles.roles : [];
      if (roleList.length === 0) {
        section.appendChild(this._createEmptyState('No local role data.'));
      } else {
        const list = document.createElement('ul');
        list.className = 'squadrons-list';
        roleList.forEach((role) => {
          const item = document.createElement('li');
          item.className = 'squadrons-list-item';
          const nameEl = document.createElement('span');
          nameEl.className = 'squadrons-role-name';
          nameEl.textContent = role.role_name || 'Unknown role';
          item.appendChild(nameEl);
          if (Array.isArray(role.permissions) && role.permissions.length > 0) {
            const permEl = document.createElement('span');
            permEl.className = 'squadrons-role-permissions';
            permEl.textContent = role.permissions.join(', ');
            item.appendChild(permEl);
          }
          if (role.id) {
            const revokeBtn = this._createRevokeButton(role.id, () => {
              this._handleRevokeRole(role.id);
            });
            item.appendChild(revokeBtn);
          }
          list.appendChild(item);
        });
        section.appendChild(list);
      }
      section.appendChild(this._createAddButton('Add Role', LOCAL_ONLY_WRITE_NOTE, () => {
        this._handleAddRole();
      }));
      return section;
    }

    _createSharedOpsSectionWithWrites(sharedOps) {
      const section = this._createSection('Shared Operations');
      const links = sharedOps && Array.isArray(sharedOps.shared_operations)
        ? sharedOps.shared_operations : [];
      if (links.length === 0) {
        section.appendChild(this._createEmptyState('No local shared operations data.'));
        section.appendChild(this._createCaveat(LOCAL_ONLY_NOTE));
      } else {
        const list = document.createElement('ul');
        list.className = 'squadrons-list';
        links.forEach((op) => {
          const item = document.createElement('li');
          item.className = 'squadrons-list-item';
          const labelEl = document.createElement('span');
          labelEl.className = 'squadrons-op-label';
          labelEl.textContent = op.label || op.operation_id || 'Unknown operation';
          item.appendChild(labelEl);
          if (op.id) {
            const revokeBtn = this._createRevokeButton(op.id, () => {
              this._handleRevokeSharedOp(op.id);
            });
            item.appendChild(revokeBtn);
          }
          list.appendChild(item);
        });
        section.appendChild(list);
      }
      section.appendChild(this._createAddButton(
        'Add Shared Operation Link', LOCAL_ONLY_WRITE_NOTE, () => {
          this._handleAddSharedOperation();
        }
      ));
      return section;
    }

    _createSharedNavSectionWithWrites(sharedNav) {
      const section = this._createSection('Shared Navigation');
      const links = sharedNav && Array.isArray(sharedNav.shared_navigation)
        ? sharedNav.shared_navigation : [];
      if (links.length === 0) {
        section.appendChild(this._createEmptyState('No local shared navigation data.'));
        section.appendChild(this._createCaveat(LOCAL_ONLY_NOTE));
      } else {
        const list = document.createElement('ul');
        list.className = 'squadrons-list';
        links.forEach((nav) => {
          const item = document.createElement('li');
          item.className = 'squadrons-list-item';
          const sysEl = document.createElement('span');
          sysEl.className = 'squadrons-nav-system';
          sysEl.textContent = nav.system_name || 'Unknown system';
          item.appendChild(sysEl);
          if (nav.objective) {
            const objEl = document.createElement('span');
            objEl.className = 'squadrons-nav-objective';
            objEl.textContent = nav.objective;
            item.appendChild(objEl);
          }
          if (nav.id) {
            const revokeBtn = this._createRevokeButton(nav.id, () => {
              this._handleRevokeSharedNav(nav.id);
            });
            item.appendChild(revokeBtn);
          }
          list.appendChild(item);
        });
        section.appendChild(list);
      }
      section.appendChild(this._createAddButton(
        'Add Shared Navigation Link', LOCAL_ONLY_WRITE_NOTE, () => {
          this._handleAddSharedNavigation();
        }
      ));
      return section;
    }

    _createEmergencySectionWithWrites(emergency) {
      const section = this._createSection('Emergency / Security');

      const active = emergency ? String(emergency.active) : 'false';
      section.appendChild(this._createFactRow('Active', active));
      const reason = emergency && emergency.reason ? emergency.reason : null;
      section.appendChild(this._createFactRow('Reason', reason));

      const notes = emergency && Array.isArray(emergency.notes) ? emergency.notes : [];
      if (notes.length > 0) {
        const h3 = document.createElement('h3');
        h3.className = 'squadrons-section-subtitle';
        h3.textContent = 'Local Notes';
        section.appendChild(h3);
        const list = document.createElement('ul');
        list.className = 'squadrons-list';
        notes.forEach((note) => {
          const item = document.createElement('li');
          item.className = 'squadrons-list-item';
          const textEl = document.createElement('span');
          textEl.className = 'squadrons-emergency-note-text';
          textEl.textContent = note.note_text || '—';
          item.appendChild(textEl);
          if (note.id) {
            const revokeBtn = this._createRevokeButton(note.id, () => {
              this._handleRevokeEmergencyNote(note.id);
            });
            item.appendChild(revokeBtn);
          }
          list.appendChild(item);
        });
        section.appendChild(list);
      }

      section.appendChild(this._createAddButton(
        'Add Local Note', LOCAL_ONLY_WRITE_NOTE, () => {
          this._handleAddEmergencyNote();
        }
      ));
      return section;
    }

    _createLogSectionWithWrites(log) {
      const section = this._createSection('Squadron Log');
      const entries = log && Array.isArray(log.log) ? log.log : [];
      if (entries.length === 0) {
        section.appendChild(this._createEmptyState('No local squadron log entries.'));
      } else {
        const list = document.createElement('ul');
        list.className = 'squadrons-list';
        entries.forEach((entry) => {
          const item = document.createElement('li');
          item.className = 'squadrons-list-item';
          const tsEl = document.createElement('span');
          tsEl.className = 'squadrons-log-timestamp';
          tsEl.textContent = entry.timestamp || '—';
          item.appendChild(tsEl);
          const typeEl = document.createElement('span');
          typeEl.className = 'squadrons-log-type';
          typeEl.textContent = entry.event_type || '—';
          item.appendChild(typeEl);
          if (entry.summary) {
            const summaryEl = document.createElement('span');
            summaryEl.className = 'squadrons-log-summary';
            summaryEl.textContent = entry.summary;
            item.appendChild(summaryEl);
          }
          list.appendChild(item);
        });
        section.appendChild(list);
      }
      section.appendChild(this._createAddButton(
        'Add Log Entry', LOCAL_ONLY_WRITE_NOTE, () => {
          this._handleAddLogEntry();
        }
      ));
      return section;
    }

    // ── Phase 9 campaign note handlers ───────────────────────────────────────

    async _handleAddCampaignNote() {
      const base = this._apiBase;
      if (!base) return;
      const workflowRaw = this._prompt('Workflow type — enter bgs or powerplay:');
      if (!workflowRaw) return;
      const workflowType = workflowRaw.toLowerCase().trim();
      if (workflowType !== 'bgs' && workflowType !== 'powerplay') return;
      const noteText = this._prompt('Campaign note (local only):');
      if (!noteText) return;
      const linkedRaw = this._prompt(
        'Linked campaign objective ID (paste UUID or leave blank):',
      );
      const body = { workflow_type: workflowType, note_text: noteText };
      if (linkedRaw && linkedRaw.trim()) {
        body.linked_campaign_id = linkedRaw.trim();
      }
      try {
        const resp = await window.fetch(base + CAMPAIGN_NOTES_PATH, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        if (!resp.ok) return;
        this.fetchAndRender();
      } catch (_e) { /* bridge unreachable */ }
    }

    async _handleArchiveCampaignNote(noteId) {
      const base = this._apiBase;
      if (!base) return;
      try {
        const resp = await window.fetch(`${base}${CAMPAIGN_NOTES_PATH}/${noteId}`, {
          method: 'DELETE',
        });
        if (!resp.ok) return;
        this.fetchAndRender();
      } catch (_e) { /* bridge unreachable */ }
    }

    // ── Write-flow add/revoke handlers ───────────────────────────────────────

    async _handleAddRosterMember() {
      const base = this._apiBase;
      if (!base) return;
      const commanderName = this._prompt('Commander name (local only):');
      if (!commanderName) return;
      const role = this._prompt('Role (optional):');
      try {
        const resp = await window.fetch(base + ROSTER_PATH, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ commander_name: commanderName, role: role || null }),
        });
        if (!resp.ok) return;
        const data = await resp.json();
        this._showGateModal(
          data.suggestion_text,
          () => this._confirmProposal(base + ROSTER_CONFIRM_PATH + data.proposal_id),
          () => this._cancelProposal(base + ROSTER_CANCEL_PATH + data.proposal_id),
        );
      } catch (_e) { /* bridge unreachable */ }
    }

    async _handleRevokeRoster(memberId) {
      const base = this._apiBase;
      if (!base) return;
      try {
        const resp = await window.fetch(`${base}/squadrons/roster/${memberId}`, {
          method: 'DELETE',
        });
        if (!resp.ok) return;
        const data = await resp.json();
        this._showGateModal(
          data.suggestion_text,
          () => this._confirmProposal(base + ROSTER_REVOKE_CONFIRM_PATH + data.proposal_id),
          () => this._cancelProposal(base + ROSTER_REVOKE_CANCEL_PATH + data.proposal_id),
        );
      } catch (_e) { /* bridge unreachable */ }
    }

    async _handleAddInviteCode() {
      const base = this._apiBase;
      if (!base) return;
      const code = this._prompt('Invite code label (local only — no delivery):');
      if (!code) return;
      try {
        const resp = await window.fetch(base + INVITES_PATH, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code }),
        });
        if (!resp.ok) return;
        const data = await resp.json();
        this._showGateModal(
          data.suggestion_text,
          () => this._confirmProposal(base + INVITES_CONFIRM_PATH + data.proposal_id),
          () => this._cancelProposal(base + INVITES_CANCEL_PATH + data.proposal_id),
        );
      } catch (_e) { /* bridge unreachable */ }
    }

    async _handleRevokeInvite(inviteId) {
      const base = this._apiBase;
      if (!base) return;
      try {
        const resp = await window.fetch(`${base}/squadrons/invites/${inviteId}`, {
          method: 'DELETE',
        });
        if (!resp.ok) return;
        const data = await resp.json();
        this._showGateModal(
          data.suggestion_text,
          () => this._confirmProposal(base + INVITES_REVOKE_CONFIRM_PATH + data.proposal_id),
          () => this._cancelProposal(base + INVITES_REVOKE_CANCEL_PATH + data.proposal_id),
        );
      } catch (_e) { /* bridge unreachable */ }
    }

    async _handleAddRole() {
      const base = this._apiBase;
      if (!base) return;
      const roleName = this._prompt('Role name (local only):');
      if (!roleName) return;
      const permsRaw = this._prompt('Permissions (comma-separated, optional):');
      const permissions = permsRaw
        ? permsRaw.split(',').map((p) => p.trim()).filter(Boolean)
        : [];
      try {
        const resp = await window.fetch(base + ROLES_PATH, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ role_name: roleName, permissions }),
        });
        if (!resp.ok) return;
        const data = await resp.json();
        this._showGateModal(
          data.suggestion_text,
          () => this._confirmProposal(base + ROLES_CONFIRM_PATH + data.proposal_id),
          () => this._cancelProposal(base + ROLES_CANCEL_PATH + data.proposal_id),
        );
      } catch (_e) { /* bridge unreachable */ }
    }

    async _handleRevokeRole(roleId) {
      const base = this._apiBase;
      if (!base) return;
      try {
        const resp = await window.fetch(`${base}/squadrons/roles/${roleId}`, {
          method: 'DELETE',
        });
        if (!resp.ok) return;
        const data = await resp.json();
        this._showGateModal(
          data.suggestion_text,
          () => this._confirmProposal(base + ROLES_REVOKE_CONFIRM_PATH + data.proposal_id),
          () => this._cancelProposal(base + ROLES_REVOKE_CANCEL_PATH + data.proposal_id),
        );
      } catch (_e) { /* bridge unreachable */ }
    }

    async _handleAddSharedOperation() {
      const base = this._apiBase;
      if (!base) return;
      const operationId = this._prompt('Operation reference ID (local only):');
      const label = this._prompt('Label (optional):');
      if (!operationId && !label) return;
      try {
        const resp = await window.fetch(base + SHARED_OPERATIONS_PATH, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ operation_id: operationId || '', label: label || '' }),
        });
        if (!resp.ok) return;
        const data = await resp.json();
        this._showGateModal(
          data.suggestion_text,
          () => this._confirmProposal(base + SHARED_OPS_CONFIRM_PATH + data.proposal_id),
          () => this._cancelProposal(base + SHARED_OPS_CANCEL_PATH + data.proposal_id),
        );
      } catch (_e) { /* bridge unreachable */ }
    }

    async _handleRevokeSharedOp(linkId) {
      const base = this._apiBase;
      if (!base) return;
      try {
        const resp = await window.fetch(`${base}/squadrons/shared-operations/${linkId}`, {
          method: 'DELETE',
        });
        if (!resp.ok) return;
        const data = await resp.json();
        this._showGateModal(
          data.suggestion_text,
          () => this._confirmProposal(
            base + SHARED_OPS_REVOKE_CONFIRM_PATH + data.proposal_id),
          () => this._cancelProposal(
            base + SHARED_OPS_REVOKE_CANCEL_PATH + data.proposal_id),
        );
      } catch (_e) { /* bridge unreachable */ }
    }

    async _handleAddSharedNavigation() {
      const base = this._apiBase;
      if (!base) return;
      const systemName = this._prompt('System name (local only):');
      if (!systemName) return;
      const objective = this._prompt('Objective (optional):');
      try {
        const resp = await window.fetch(base + SHARED_NAVIGATION_PATH, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ system_name: systemName, objective: objective || null }),
        });
        if (!resp.ok) return;
        const data = await resp.json();
        this._showGateModal(
          data.suggestion_text,
          () => this._confirmProposal(base + SHARED_NAV_CONFIRM_PATH + data.proposal_id),
          () => this._cancelProposal(base + SHARED_NAV_CANCEL_PATH + data.proposal_id),
        );
      } catch (_e) { /* bridge unreachable */ }
    }

    async _handleRevokeSharedNav(linkId) {
      const base = this._apiBase;
      if (!base) return;
      try {
        const resp = await window.fetch(`${base}/squadrons/shared-navigation/${linkId}`, {
          method: 'DELETE',
        });
        if (!resp.ok) return;
        const data = await resp.json();
        this._showGateModal(
          data.suggestion_text,
          () => this._confirmProposal(
            base + SHARED_NAV_REVOKE_CONFIRM_PATH + data.proposal_id),
          () => this._cancelProposal(
            base + SHARED_NAV_REVOKE_CANCEL_PATH + data.proposal_id),
        );
      } catch (_e) { /* bridge unreachable */ }
    }

    async _handleAddEmergencyNote() {
      const base = this._apiBase;
      if (!base) return;
      const noteText = this._prompt('Local emergency/security note:');
      if (!noteText) return;
      try {
        const resp = await window.fetch(base + EMERG_NOTE_PATH, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ note_text: noteText }),
        });
        if (!resp.ok) return;
        const data = await resp.json();
        this._showGateModal(
          data.suggestion_text,
          () => this._confirmProposal(base + EMERG_NOTE_CONFIRM_PATH + data.proposal_id),
          () => this._cancelProposal(base + EMERG_NOTE_CANCEL_PATH + data.proposal_id),
        );
      } catch (_e) { /* bridge unreachable */ }
    }

    async _handleRevokeEmergencyNote(noteId) {
      const base = this._apiBase;
      if (!base) return;
      try {
        const resp = await window.fetch(
          `${base}/squadrons/emergency-security/note/${noteId}`, { method: 'DELETE' });
        if (!resp.ok) return;
        const data = await resp.json();
        this._showGateModal(
          data.suggestion_text,
          () => this._confirmProposal(
            base + EMERG_NOTE_REVOKE_CONFIRM_PATH + data.proposal_id),
          () => this._cancelProposal(
            base + EMERG_NOTE_REVOKE_CANCEL_PATH + data.proposal_id),
        );
      } catch (_e) { /* bridge unreachable */ }
    }

    async _handleAddLogEntry() {
      const base = this._apiBase;
      if (!base) return;
      const summary = this._prompt('Log entry summary (local only):');
      if (!summary) return;
      const eventType = this._prompt('Event type (optional):');
      try {
        const resp = await window.fetch(base + LOG_PATH, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ summary, event_type: eventType || '' }),
        });
        if (!resp.ok) return;
        const data = await resp.json();
        this._showGateModal(
          data.suggestion_text,
          () => this._confirmProposal(base + LOG_CONFIRM_PATH + data.proposal_id),
          () => this._cancelProposal(base + LOG_CANCEL_PATH + data.proposal_id),
        );
      } catch (_e) { /* bridge unreachable */ }
    }

    async _handleReservedIntent(featureId, statusEl, proofEl) {
      const setStatus = (text) => {
        if (statusEl) statusEl.textContent = text;
      };
      const clearProof = () => {
        if (proofEl) proofEl.replaceChildren();
      };
      const base = this._apiBase;
      if (!base) {
        setStatus('Not Loaded. Intent not recorded. Feature remains reserved.');
        clearProof();
        return;
      }
      try {
        const resp = await window.fetch(base + RESERVED_INTENT_PATH, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ feature_id: featureId }),
        });
        if (!resp.ok) {
          setStatus('Intent not recorded. Feature remains reserved.');
          clearProof();
          return;
        }
        const data = await resp.json();
        if (data && data.intent_recorded_but_blocked === true) {
          setStatus('Intent recorded — blocked');
          if (proofEl) {
            proofEl.replaceChildren(this._createReservedIntentProof(data));
          }
          return;
        }
        setStatus('Intent blocked. Feature remains reserved.');
        clearProof();
      } catch (_e) {
        setStatus('Intent not recorded. Feature remains reserved.');
        clearProof();
      }
    }

    // ── Gate modal (ADR 0003 safe DOM; role="dialog"; textContent only) ──────

    _createReservedIntentProof(data) {
      const proof = document.createElement('div');
      proof.className = 'sq-reserved-proof-detail';

      proof.appendChild(this._createProofActionLinks());
      proof.appendChild(this._createFactRow('Status', data.status || 'blocked'));
      proof.appendChild(this._createFactRow('Feature', data.feature || data.feature_id || 'Reserved'));
      proof.appendChild(this._createFactRow('Local-only', String(data.local_only === true)));
      proof.appendChild(this._createFactRow('Transport attempted', String(data.transport_attempted === true)));
      proof.appendChild(this._createFactRow('Reason', data.reason || 'Reserved'));

      const note = document.createElement('p');
      note.className = 'squadrons-caveat';
      note.textContent = 'Feature remains reserved. No feature was enabled.';
      proof.appendChild(note);

      return proof;
    }

    _showGateModal(suggestionText, onConfirm, onCancel) {
      this._hideGateModal();

      const overlay = document.createElement('div');
      overlay.className = 'sq-gate-overlay';
      overlay.id = 'sq-gate-overlay';

      const dialog = document.createElement('div');
      dialog.className = 'sq-gate-modal';
      dialog.setAttribute('role', 'dialog');
      dialog.setAttribute('aria-modal', 'true');
      dialog.setAttribute('aria-labelledby', 'sq-gate-title');
      dialog.setAttribute('tabindex', '-1');

      const title = document.createElement('h3');
      title.id = 'sq-gate-title';
      title.className = 'sq-gate-title';
      title.textContent = 'Confirm Action';

      const suggestion = document.createElement('p');
      suggestion.className = 'sq-gate-suggestion';
      suggestion.textContent = suggestionText;

      const localNote = document.createElement('p');
      localNote.className = 'sq-gate-local-note';
      localNote.textContent = 'Local only — no peer delivery.';

      const buttons = document.createElement('div');
      buttons.className = 'sq-gate-buttons';

      const confirmBtn = document.createElement('button');
      confirmBtn.className = 'sq-gate-btn sq-gate-btn--confirm';
      confirmBtn.setAttribute('type', 'button');
      confirmBtn.textContent = 'Confirm';
      confirmBtn.addEventListener('click', () => {
        this._hideGateModal();
        onConfirm();
      });

      const cancelBtn = document.createElement('button');
      cancelBtn.className = 'sq-gate-btn sq-gate-btn--cancel';
      cancelBtn.setAttribute('type', 'button');
      cancelBtn.textContent = 'Cancel';
      cancelBtn.addEventListener('click', () => {
        this._hideGateModal();
        onCancel();
      });

      buttons.appendChild(confirmBtn);
      buttons.appendChild(cancelBtn);

      dialog.appendChild(title);
      dialog.appendChild(suggestion);
      dialog.appendChild(localNote);
      dialog.appendChild(buttons);
      overlay.appendChild(dialog);

      document.body.appendChild(overlay);
      dialog.focus();
    }

    _hideGateModal() {
      const existing = document.getElementById('sq-gate-overlay');
      if (existing) existing.remove();
    }

    async _confirmProposal(url) {
      try {
        await window.fetch(url, { method: 'POST' });
        this.fetchAndRender();
      } catch (_e) { /* bridge unreachable */ }
    }

    async _cancelProposal(url) {
      try {
        await window.fetch(url, { method: 'POST' });
      } catch (_e) { /* bridge unreachable */ }
    }

    // ── Write-flow DOM helpers ───────────────────────────────────────────────

    _createAddButton(label, caveat, onClick) {
      const wrapper = document.createElement('div');
      wrapper.className = 'sq-write-controls';

      const btn = document.createElement('button');
      btn.className = 'sq-add-btn';
      btn.textContent = label;
      btn.setAttribute('type', 'button');
      btn.addEventListener('click', onClick);

      const note = document.createElement('span');
      note.className = 'sq-local-note';
      note.textContent = caveat;

      wrapper.appendChild(btn);
      wrapper.appendChild(note);
      return wrapper;
    }

    _createRevokeButton(id, onClick) {
      const btn = document.createElement('button');
      btn.className = 'sq-revoke-btn';
      btn.textContent = 'Revoke';
      btn.setAttribute('type', 'button');
      btn.dataset.id = id;
      btn.addEventListener('click', onClick);
      return btn;
    }

    _prompt(message) {
      return window.prompt(message) || '';
    }
  }

  globalThis.__squadronsExports = { SquadronsController };
  new SquadronsController();
})();
