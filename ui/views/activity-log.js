/**
 * Phase 3 Week 13 — Activity Log Controller
 *
 * Full-featured activity log with:
 *  - Filtering by category
 *  - Free-text search
 *  - Pagination (50 rows per page)
 *  - Export to JSON
 *  - Clear with confirmation
 */

const LOG_VIEWS = Object.freeze([
  { id: 'events', label: 'Events', sectionId: 'log-section-events' },
  { id: 'sources', label: 'Sources', sectionId: 'log-section-sources' },
  { id: 'known-data', label: 'Known Data', sectionId: 'log-section-known-data' },
  { id: 'proof', label: 'Proof', sectionId: 'log-section-proof' },
  { id: 'diagnostics', label: 'Diagnostics', sectionId: 'log-section-diagnostics' }
]);

const SECONDARY_FILTERS = Object.freeze([
  { value: 'recent', label: 'Recent' },
  { value: 'source', label: 'Source events' },
  { value: 'blocked', label: 'Blocked requests' },
  { value: 'gate', label: 'Confirmation gate' },
  { value: 'operations', label: 'Operations' },
  { value: 'engineering', label: 'Engineering' },
  { value: 'phase9-bgs', label: 'Phase 9 BGS' },
  { value: 'phase9-powerplay', label: 'Phase 9 Powerplay' },
  { value: 'phase9-campaign', label: 'Phase 9 Campaign' },
  { value: 'phase9-navigation', label: 'Phase 9 Navigation' },
  { value: 'phase9-squadron', label: 'Phase 9 Squadron' },
  { value: 'phase9-source-attempts', label: 'Phase 9 Source attempts' },
  { value: 'phase9-ai-drafts', label: 'Phase 9 AI drafts' },
  { value: 'handoffs', label: 'Route handoffs' },
  { value: 'errors', label: 'Errors / warnings' },
  { value: 'raw', label: 'Raw/proof only' }
]);

const SENSITIVE_TEXT_EVENTS = Object.freeze(new Set([
  'RECEIVETEXT',
  'SENDTEXT'
]));

const SENSITIVE_IDENTITY_EVENTS = Object.freeze([
  'LOADGAME',
  'NEWCOMMANDER',
  'CLEARSAVEDGAME',
  'FRIENDS',
  'WING',
  'SQUADRON',
  'PVP',
  'CREW'
]);

const SENSITIVE_PAYLOAD_KEYS = Object.freeze(new Set([
  'message',
  'message_localised',
  'text',
  'from',
  'to',
  'sender',
  'recipient',
  'commander',
  'commandername',
  'commander_name',
  'cmdr',
  'fid',
  'frontierid',
  'frontier_id',
  'account',
  'accountid',
  'account_id'
]));

const IDENTITY_PAYLOAD_KEYS = Object.freeze(new Set([
  'name',
  'localisedname',
  'localised_name',
  'shipname',
  'ship_name',
  'squadronname',
  'squadron_name'
]));

const PHASE_9_ALLOWED_PAYLOAD_KEYS = Object.freeze(new Set([
  'ai_provider_name',
  'blocked_reason',
  'bookmark_id',
  'campaign_id',
  'candidate_sources',
  'changed_fields',
  'circuit_id',
  'confidence_label',
  'exported',
  'fallback_wording_shown',
  'fact_id',
  'field_count',
  'is_fact',
  'is_fact_source',
  'kb_excerpt_count',
  'kb_reference_count',
  'linked_campaign_id',
  'linked_count',
  'linked_intel_fact_count',
  'linked_intel_fact_id',
  'linked_navigation_circuit_count',
  'needs_review_count',
  'note_id',
  'order_index',
  'previous_state',
  'projected_fields',
  'redacted',
  'redaction_state',
  'rejection_reason',
  'requested_fact',
  'source_chain',
  'source_count',
  'source_label',
  'source_type',
  'state',
  'stop_count',
  'stop_id',
  'tag',
  'title_length',
  'workflow_type'
]));

const PHASE_9_ALLOWED_SOURCE_CHAIN_KEYS = Object.freeze([
  'source',
  'source_type',
  'source_event',
  'truth_class',
  'freshness',
  'workflow_type',
  'blocked_reason',
  'kind',
  'fact_id',
  'kb_file',
  'entry_id',
  'needs_review'
]);

function normalizeText(value) {
  return String(value || '').trim().toLowerCase();
}

function normalizeEventType(entry) {
  return String(entry?.event_type || entry?.event || '').trim().toUpperCase();
}

function rawEventType(entry) {
  return String(entry?.event_type || entry?.event || '').trim();
}

class ActivityLogController {
  constructor() {
    this.allEntries = [];
    this.filteredEntries = [];
    this.currentPage = 0;
    this.pageSize = 50;
    this.activeView = 'events';
    this._primitivesPromise = Promise.all([
      import('../components/command-primitives.js').catch(e => {
        console.error('[ActivityLog] Failed to load command primitives:', e);
        return null;
      }),
      import('../components/source-proof.js').catch(e => {
        console.error('[ActivityLog] Failed to load source proof:', e);
        return null;
      }),
      import('../utils/display-names.js').catch(e => {
        console.error('[ActivityLog] Failed to load display names:', e);
        return null;
      })
    ]).then(([cp, sp, displayNames]) => {
      this._primitives = cp;
      this._sourceProof = sp;
      this._displayNames = displayNames;
      return cp;
    });
    this.init();
  }

  get apiBase() {
    if (window.Shell?.httpBase) return window.Shell.httpBase;
    if (window.OMNICOVAS_PORT) return `http://127.0.0.1:${window.OMNICOVAS_PORT}`;
    return null;
  }

  apiUrl(path) {
    const base = this.apiBase;
    return base ? `${base}${path}` : null;
  }

  async init() {
    this.rebuildFilters();
    this.bindEvents();
    if (!this.apiBase) {
      this._showWaiting();
      window.OmniEvents?.addEventListener('bridge-connected', () => this._loadAndRender(), { once: true });
      return;
    }
    await this._loadAndRender();
  }

  rebuildFilters() {
    this.rebuildViewControls();
    this.rebuildSecondaryFilters();
  }

  rebuildViewControls() {
    const viewNav = document.querySelector('.log-section-nav');
    if (!viewNav) return;

    viewNav.replaceChildren();
    viewNav.setAttribute('role', 'tablist');
    viewNav.setAttribute('aria-label', 'Activity Log category views');

    LOG_VIEWS.forEach((view, index) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'log-section-link log-view-tab';
      button.dataset.logView = view.id;
      button.setAttribute('role', 'tab');
      button.setAttribute('aria-controls', view.sectionId);
      button.textContent = view.label;
      if (index === 0 && !this.activeView) {
        this.activeView = view.id;
      }
      viewNav.appendChild(button);
    });

    this.updateViewControls();
  }

  rebuildSecondaryFilters() {
    const filterGroup = document.querySelector('.log-filter-group');
    if (!filterGroup) return;

    filterGroup.replaceChildren();
    const legend = document.createElement('legend');
    legend.className = 'ocv-sr-only';
    legend.textContent = 'Filter within current Activity Log view';
    filterGroup.appendChild(legend);

    SECONDARY_FILTERS.forEach(f => {
      const id = `log-filter-secondary-${f.value}`;
      const label = document.createElement('label');
      label.className = 'log-filter-label';
      label.setAttribute('for', id);
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.className = 'log-filter';
      input.id = id;
      input.name = id;
      input.value = f.value;
      label.appendChild(input);
      label.appendChild(document.createTextNode(' ' + f.label));
      filterGroup.appendChild(label);
    });
  }

  _showWaiting() {
    const tbody = document.getElementById('log-body');
    if (!tbody) return;
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 5;
    td.className = 'log-waiting';
    td.textContent = 'Waiting for OmniCOVAS bridge…';
    tr.appendChild(td);
    tbody.replaceChildren(tr);
  }

  getActiveView() {
    const view = LOG_VIEWS.find(v => v.id === this.activeView);
    return view ? view.id : 'events';
  }

  activateView(viewId) {
    if (!LOG_VIEWS.some(view => view.id === viewId)) return;
    this.activeView = viewId;
    this.currentPage = 0;
    this.updateViewControls();
    this._computeFilteredEntries();
    this.renderPage();
  }

  updateViewControls() {
    const activeView = this.getActiveView();
    document.querySelectorAll('.log-view-tab').forEach((button) => {
      const isActive = button.dataset.logView === activeView;
      button.classList.toggle('is-active', isActive);
      button.setAttribute('aria-selected', isActive ? 'true' : 'false');
      button.setAttribute('tabindex', isActive ? '0' : '-1');
    });

    LOG_VIEWS.forEach((view) => {
      const section = document.getElementById(view.sectionId);
      if (!section) return;
      const isActive = view.id === activeView;
      section.hidden = !isActive;
      section.dataset.logViewActive = isActive ? 'true' : 'false';
    });
  }

  focusAdjacentView(currentButton, direction) {
    const buttons = Array.from(document.querySelectorAll('.log-view-tab'));
    const index = buttons.indexOf(currentButton);
    if (index === -1 || buttons.length === 0) return;
    const nextIndex = (index + direction + buttons.length) % buttons.length;
    const next = buttons[nextIndex];
    next.focus();
    this.activateView(next.dataset.logView);
  }

  async _loadAndRender() {
    this.renderRouteHero();
    await this.loadActivityLog();
    this.renderRouteHero();
    await this.renderPage();
    this.applyRouteTransferArrival();
  }

  async renderRouteHero() {
    const Primitives = await this._primitivesPromise;
    if (!Primitives) return;

    const container = document.getElementById('view-activity-log');
    if (!container) return;

    container.querySelector('.route-hero')?.remove();

    const hero = Primitives.createRouteHero({
      title: 'Activity Log',
      kicker: 'Proof Ledger',
      statusText: this.allEntries.length > 0 ? 'Events available' : (this.apiBase ? 'No events loaded' : 'Bridge not ready'),
      statusVariant: this.allEntries.length > 0 ? 'available' : (this.apiBase ? 'off' : 'not-loaded'),
      primaryValues: [
        { label: 'Events shown', value: this.filteredEntries.length },
        { label: 'Latest', value: this.allEntries[0]?.event_type || 'None' }
      ]
    });

    container.prepend(hero);
  }

  async loadActivityLog() {
    const url = this.apiUrl('/activity-log');
    if (!url) return;
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      this.allEntries = data.entries || [];
      this.filteredEntries = [...this.allEntries];
    } catch (err) {
      console.error("Failed to load activity log:", err);
      this.allEntries = [];
      this.filteredEntries = [];
    }
  }

  bindEvents() {
    document.querySelectorAll('.log-view-tab').forEach((button) => {
      button.addEventListener('click', () => {
        this.activateView(button.dataset.logView);
      });
      button.addEventListener('keydown', (event) => {
        if (event.key === 'ArrowRight') {
          event.preventDefault();
          this.focusAdjacentView(button, 1);
        }
        if (event.key === 'ArrowLeft') {
          event.preventDefault();
          this.focusAdjacentView(button, -1);
        }
      });
    });

    // Search
    document.getElementById("log-search")?.addEventListener("input", (e) => {
      this.filterAndRender(e.target.value);
    });

    // Filters
    document.querySelectorAll(".log-filter").forEach((checkbox) => {
      checkbox.addEventListener("change", () => {
        this.applyFilters();
      });
    });

    // Actions
    document.getElementById("log-export-btn")?.addEventListener("click", () => {
      this.exportLog();
    });

    document.getElementById("log-clear-btn")?.addEventListener("click", () => {
      this.showClearConfirm();
    });

    // Clear modal
    document.getElementById("log-clear-confirm-btn")?.addEventListener("click", () => {
      this.clearLog();
    });

    document.getElementById("log-clear-cancel-btn")?.addEventListener("click", () => {
      document.getElementById("log-clear-modal").style.display = "none";
    });

    // Pagination
    document.getElementById("log-prev-btn")?.addEventListener("click", () => {
      if (this.currentPage > 0) {
        this.currentPage--;
        this.renderPage();
      }
    });

    document.getElementById("log-next-btn")?.addEventListener("click", () => {
      const maxPage = Math.ceil(this.filteredEntries.length / this.pageSize) - 1;
      if (this.currentPage < maxPage) {
        this.currentPage++;
        this.renderPage();
      }
    });
  }

  _computeFilteredEntries() {
    const searchEl = document.getElementById("log-search");
    const text = (searchEl?.value || "").toLowerCase();
    const activeView = this.getActiveView();

    const selectedCategories = new Set();
    document.querySelectorAll(".log-filter:checked").forEach((cb) => {
      selectedCategories.add(cb.value);
    });

    this.filteredEntries = this.allEntries.filter((entry) => {
      if (text) {
        const searchable = this.getSearchableText(entry);
        if (!searchable.includes(text)) {
           return false;
        }
      }
      const categories = this.getEventCategories(entry);
      if (!categories.includes(activeView)) {
        return false;
      }
      if (selectedCategories.size > 0) {
        let match = false;
        for (const cat of categories) {
           if (selectedCategories.has(cat)) {
              match = true;
              break;
           }
        }
        if (!match) return false;
      }
      return true;
    });

    this.currentPage = 0;
  }

  filterAndRender(_searchText) {
    this._computeFilteredEntries();
    this.renderPage();
  }

  applyFilters() {
    this._computeFilteredEntries();
    this.renderPage();
  }

  getHumanSummary(entry) {
    const type = (entry.event_type || '').toUpperCase();
    if (this.isPhase9Entry(entry)) {
      return this.formatEventLabel(entry);
    }
    if (SENSITIVE_TEXT_EVENTS.has(type)) return 'Text event recorded; private message redacted';
    if (SENSITIVE_IDENTITY_EVENTS.some(marker => type.includes(marker))) {
      return 'Identity or social event recorded; private fields redacted';
    }
    if (type === 'LOCAL_CONFLICT_CONTEXT_UPDATED') return 'Conflict context updated';
    if (type === 'ENGINEERING.SOURCE_ATTEMPT.BLOCKED') return 'Engineering source attempt blocked';
    if (type.startsWith('ENGINEERING.')) {
      if (entry.summary) return entry.summary;
      return 'Engineering planning record updated';
    }
    if (type.includes('BLOCKED')) return 'External request blocked';
    if (type.includes('CONFIRMATION') || type.includes('PROPOSAL')) return 'Confirmation decision recorded';
    if (entry.summary && entry.summary !== '—') return entry.summary;

    if (type.includes('TRANSFER') || type.includes('HANDOFF')) return 'Route handoff initiated';
    if (type.includes('ERROR') || type.includes('WARN') || type.includes('CRITICAL')) return 'Warning / Error recorded';
    if (type.startsWith('SOURCE_')) return 'Source data updated';

    return 'Event recorded';
  }

  getSearchableText(entry) {
    const payload = entry?.payload && typeof entry.payload === 'object' ? entry.payload : {};
    const safePayload = this.isPhase9Entry(entry) ? this.getPhase9DisplayPayload(entry) : payload;
    const payloadKeys = Object.keys(safePayload);
    const parts = [
      entry?.event_type,
      this.formatEventLabel(entry),
      this.getHumanSummary(entry),
      entry?.source,
      entry?.category,
      entry?.matrix_status,
      entry?.classification,
      entry?.home_status,
      ...payloadKeys
    ];

    if (!this.isPrivacySensitiveEntry(entry)) {
      parts.push(entry?.summary);
      parts.push(...Object.values(safePayload).filter(value => typeof value !== 'object').map(value => String(value)));
    }

    return parts.filter(Boolean).join(' ').toLowerCase();
  }

  getEventCategories(entry) {
    const categories = [];
    const type = (entry.event_type || '').toUpperCase();
    const lowerType = rawEventType(entry).toLowerCase();
    const source = (entry.source || '').toLowerCase();

    categories.push('events');
    categories.push('proof');
    categories.push('recent');
    categories.push('raw');

    if (type.startsWith('SOURCE_') || type.startsWith('EXTERNAL_REQUEST_') || source === 'local_telemetry' || source === 'local_event_history') categories.push('source');
    if (this.isSourceEntry(entry)) categories.push('sources');
    if (this.isKnownDataEntry(entry)) categories.push('known-data');
    if (this.isDiagnosticEntry(entry)) categories.push('diagnostics');
    if (type.includes('BLOCKED') || (entry.payload && entry.payload.blocked === true) || source === 'external_disabled') categories.push('blocked');
    if (type.includes('CONFIRMATION') || type.includes('PROPOSAL') || type.includes('GATE')) categories.push('gate');
    if (type.includes('COMBAT') || type.includes('TRADE') || type.includes('MINING') || type.includes('SQUADRON') || type.includes('EXPLORATION') || type.includes('DOCKED') || type.includes('FSD')) categories.push('operations');
    if (type.startsWith('ENGINEERING.') || entry.category === 'engineering') categories.push('engineering');
    if (lowerType.startsWith('phase_9.bgs.')) categories.push('phase9-bgs', 'source', 'known-data');
    if (lowerType.startsWith('phase_9.powerplay.')) categories.push('phase9-powerplay', 'source', 'known-data');
    if (lowerType.startsWith('phase_9.campaign.')) categories.push('phase9-campaign', 'operations');
    if (lowerType.startsWith('phase_9.navigation.')) categories.push('phase9-navigation', 'operations');
    if (lowerType.startsWith('phase_9.squadron.')) categories.push('phase9-squadron', 'operations');
    if (lowerType === 'phase_9.source_attempt_blocked' || lowerType.startsWith('phase_9.source_attempt_') || lowerType.startsWith('phase_9.source_attempt.')) categories.push('phase9-source-attempts', 'source', 'blocked', 'diagnostics');
    if (lowerType.startsWith('phase_9.campaign.ai_draft')) categories.push('phase9-ai-drafts', 'gate');
    if (type.includes('TRANSFER') || type.includes('HANDOFF') || (entry.payload && entry.payload.route_intent)) categories.push('handoffs');
    if (type.includes('ERROR') || type.includes('WARN') || type.includes('CRITICAL')) categories.push('errors');

    return categories;
  }

  isSourceEntry(entry) {
    const type = normalizeEventType(entry);
    const source = normalizeText(entry?.source);
    return (
      type.startsWith('SOURCE_') ||
      type.startsWith('EXTERNAL_REQUEST_') ||
      source.includes('journal') ||
      source.includes('status') ||
      source.includes('local_') ||
      source.endsWith('.json') ||
      source.includes('external') ||
      source.includes('engineering') ||
      Boolean(entry?.source_chain) ||
      Boolean(entry?.payload?.source_id || entry?.payload?.source || entry?.payload?.provider)
    );
  }

  isKnownDataEntry(entry) {
    const type = normalizeEventType(entry);
    const source = normalizeText(entry?.source);
    const text = `${type} ${source} ${normalizeText(entry?.summary)}`;
    return (
      source.endsWith('.json') ||
      source.includes('journal') ||
      source.includes('local_telemetry') ||
      source.includes('local_event_history') ||
      /STATUS|STATE|SNAPSHOT|CARGO|MARKET|SHIPYARD|OUTFITTING|MODULE|MISSION|MATERIAL|POWERPLAY|RANK|LOADOUT|LOCATION/.test(text)
    );
  }

  isDiagnosticEntry(entry) {
    const type = normalizeEventType(entry);
    const text = `${type} ${normalizeText(entry?.summary)} ${normalizeText(entry?.classification)} ${normalizeText(entry?.matrix_status)} ${normalizeText(entry?.home_status)} ${normalizeText(entry?.payload?.classification)} ${normalizeText(entry?.payload?.matrix_status)} ${normalizeText(entry?.payload?.home_status)}`;
    return /DIAGNOSTIC|ERROR|WARN|CRITICAL|BLOCKED|CONFLICT|AMBIGUOUS|DEFERRED|RESERVED|UNSUPPORTED|NO_VERIFIED_SOURCE/.test(text);
  }

  // Retained for backward compatibility with older tests if they spy on it
  resolveCategory(entry) {
    const validCategories = new Set(["critical", "extended", "ai", "telemetry", "source", "engineering"]);
    if (entry && entry.category && validCategories.has(entry.category)) {
      return entry.category;
    }
    return this.getEventCategory(entry ? entry.event_type : "");
  }

  // Retained for backward compatibility with older tests
  getEventCategory(eventType) {
    if (!eventType) return "telemetry";

    const type = eventType.toUpperCase();
    if (
      type.includes("TIER_3") ||
      type.includes("CONFIRMATION") ||
      type.includes("PROPOSAL")
    )
      return "ai";
    if (type.includes("CRITICAL") || type.includes("DESTROYED")) return "critical";
    if (type.includes("DOCKED") || type.includes("WANTED") || type.includes("FSD"))
      return "extended";
    if (type.startsWith("SOURCE_") || type.startsWith("EXTERNAL_REQUEST_"))
      return "source";
    if (type.startsWith("ENGINEERING.")) return "engineering";
    if (type.startsWith("PHASE_9.")) return "source";
    return "telemetry";
  }

  async renderPage() {
    await this._primitivesPromise; // Ensure modules are loaded
    const tbody = document.getElementById("log-body");
    if (!tbody) return;

    if (this.filteredEntries.length === 0) {
      tbody.replaceChildren();
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 5;

      if (this._primitives) {
        const empty = this._primitives.createEmptyState({
          status: this.apiBase ? 'No matching proof records' : 'Bridge not ready',
          reason: this.apiBase ? 'Try adjusting your filters or search text.' : 'Waiting for OmniCOVAS bridge connection.'
        });
        td.appendChild(empty);
      } else {
        td.className = 'log-waiting';
        td.textContent = this.apiBase ? 'No matching proof records' : 'Waiting for OmniCOVAS bridge…';
      }

      tr.appendChild(td);
      tbody.appendChild(tr);
      this.renderViewPanels();
      this.updatePagination();
      this.updateViewControls();
      return;
    }

    const start = this.currentPage * this.pageSize;
    const end = start + this.pageSize;
    const pageEntries = this.filteredEntries.slice(start, end);

    tbody.replaceChildren();
    for (const entry of pageEntries) {
      const row = this.createLogRow(entry);
      tbody.appendChild(row);
    }

    this.renderViewPanels();
    this.updatePagination();
    this.updateViewControls();
  }

  renderViewPanels() {
    this.renderEventsPanel();
    this.renderSourcesPanel();
    this.renderProofPanel();
    this.renderDiagnosticsPanel();
  }

  renderEventsPanel() {
    const timeline = document.getElementById('log-entries');
    if (!timeline) return;
    timeline.replaceChildren();

    if (this.filteredEntries.length === 0) {
      timeline.appendChild(this.createPanelEmpty('No event rows match the current Activity Log view.'));
      return;
    }

    this.filteredEntries.slice(0, this.pageSize).forEach((entry) => {
      const item = document.createElement('article');
      item.className = `log-entry ${this.resolveCategory(entry)}`;
      item.dataset.logEventType = entry.event_type || 'unknown';

      const time = document.createElement('span');
      time.className = 'log-time';
      time.textContent = this.formatTimestamp(entry.timestamp || '');

      const type = document.createElement('span');
      type.className = 'log-type';
      type.textContent = this.formatEventLabel(entry);

      const msg = document.createElement('span');
      msg.className = 'log-msg';
      msg.textContent = this.getHumanSummary(entry);

      item.append(time, type, msg);
      timeline.appendChild(item);
    });
  }

  renderSourcesPanel() {
    const panel = document.getElementById('log-sources-view');
    if (!panel) return;
    panel.replaceChildren();

    if (this.filteredEntries.length === 0) {
      panel.appendChild(this.createPanelEmpty('No source or provenance rows match the current filters.'));
      return;
    }

    const list = document.createElement('ul');
    list.className = 'log-view-list';
    this.filteredEntries.slice(0, this.pageSize).forEach((entry) => {
      const item = document.createElement('li');
      item.className = 'log-view-list-item';
      item.append(
        this.createInlineLabel('Source', entry.source || 'activity_log'),
        this.createInlineLabel('Event', this.formatEventLabel(entry)),
        this.createInlineLabel('Summary', this.getHumanSummary(entry))
      );
      list.appendChild(item);
    });
    panel.appendChild(list);
  }

  renderProofPanel() {
    const panel = document.getElementById('log-proof-view');
    if (!panel) return;
    panel.replaceChildren();

    if (this.filteredEntries.length === 0) {
      panel.appendChild(this.createPanelEmpty('No proof rows match the current filters.'));
      return;
    }

    this.filteredEntries.slice(0, this.pageSize).forEach((entry) => {
      panel.appendChild(this.createProofCard(entry));
    });
  }

  renderDiagnosticsPanel() {
    const panel = document.getElementById('log-diagnostics-view');
    if (!panel) return;
    panel.replaceChildren();

    const stats = document.createElement('dl');
    stats.className = 'log-diagnostics-stats';
    [
      ['Loaded entries', this.allEntries.length],
      ['Visible in view', this.filteredEntries.length],
      ['Deferred/reserved rows', this.allEntries.filter(entry => this.getMatrixStatus(entry) === 'deferred_reserved').length],
      ['Conflict/ambiguous rows', this.allEntries.filter(entry => this.getMatrixStatus(entry) === 'conflict_ambiguous').length],
      ['Blocked/error rows', this.allEntries.filter(entry => this.isDiagnosticEntry(entry)).length]
    ].forEach(([label, value]) => {
      const wrap = document.createElement('div');
      wrap.className = 'log-diagnostics-stat';
      const dt = document.createElement('dt');
      dt.textContent = label;
      const dd = document.createElement('dd');
      dd.textContent = String(value);
      wrap.append(dt, dd);
      stats.appendChild(wrap);
    });
    panel.appendChild(stats);

    const diagnosticEntries = this.filteredEntries.filter(entry => this.isDiagnosticEntry(entry));
    if (diagnosticEntries.length === 0) {
      panel.appendChild(this.createPanelEmpty('No diagnostic, deferred/reserved, conflict, or blocked rows match the current filters.'));
      return;
    }

    const list = document.createElement('ul');
    list.className = 'log-view-list';
    diagnosticEntries.slice(0, this.pageSize).forEach((entry) => {
      const item = document.createElement('li');
      item.className = 'log-view-list-item';
      item.append(
        this.createInlineLabel('Status', this.describeMatrixStatus(entry)),
        this.createInlineLabel('Event', this.formatEventLabel(entry)),
        this.createInlineLabel('Summary', this.getHumanSummary(entry))
      );
      list.appendChild(item);
    });
    panel.appendChild(list);
  }

  applyRouteTransferArrival() {
    const container = document.getElementById('view-activity-log');
    if (!container) return;
    window.Shell?.applyRouteTransferArrival?.('/activity-log', container);
  }

  createPanelEmpty(message) {
    const p = document.createElement('p');
    p.className = 'log-section-hint';
    p.textContent = message;
    return p;
  }

  createInlineLabel(labelText, valueText) {
    const wrap = document.createElement('span');
    wrap.className = 'log-inline-field';
    const label = document.createElement('span');
    label.className = 'log-inline-label';
    label.textContent = labelText;
    const value = document.createElement('span');
    value.className = 'log-inline-value';
    value.textContent = valueText === null || valueText === undefined ? 'Unknown' : String(valueText);
    wrap.append(label, value);
    return wrap;
  }

  createProofCard(entry) {
    const card = document.createElement('article');
    card.className = 'log-proof-card';
    card.dataset.logEventType = entry.event_type || 'unknown';

    const heading = document.createElement('h3');
    heading.className = 'log-proof-card-title';
    heading.textContent = this.formatEventLabel(entry);
    card.appendChild(heading);

    const summary = document.createElement('p');
    summary.className = 'log-proof-card-summary';
    summary.textContent = this.getHumanSummary(entry);
    card.appendChild(summary);

    card.appendChild(this.createProofDetails(entry));
    return card;
  }

  createProofDetails(entry) {
    const details = document.createElement('details');
    details.className = 'log-entry-details';

    const summaryEl = document.createElement('summary');
    summaryEl.textContent = 'Expand audit details / proof';
    details.appendChild(summaryEl);

    const list = document.createElement('dl');
    list.className = 'log-entry-proof-list';
    this.appendProofField(list, 'Event type', entry.event_type || 'Unknown event');
    this.appendProofField(list, 'Event label', this.formatEventLabel(entry));
    this.appendProofField(list, 'Source', entry.source || 'activity_log');
    this.appendProofField(list, 'Timestamp', entry.timestamp || 'Unknown');
    this.appendProofField(list, 'Home status', this.describeMatrixStatus(entry));
    details.appendChild(list);

    const keyInventory = this.createPayloadKeyInventory(entry);
    details.appendChild(keyInventory);

    const sourceChainDetails = this.createSourceChainDetails(entry);
    if (sourceChainDetails) {
      details.appendChild(sourceChainDetails);
    }

    return details;
  }

  appendProofField(list, labelText, valueText) {
    const dt = document.createElement('dt');
    dt.textContent = labelText;
    const dd = document.createElement('dd');
    dd.textContent = valueText === null || valueText === undefined ? 'Unknown' : String(valueText);
    list.append(dt, dd);
  }

  createPayloadKeyInventory(entry) {
    const wrap = document.createElement('section');
    wrap.className = 'log-entry-key-inventory';
    const heading = document.createElement('h4');
    heading.textContent = 'Payload key inventory';
    wrap.appendChild(heading);

    const payload = entry?.payload && typeof entry.payload === 'object' ? entry.payload : null;
    const displayPayload = payload && this.isPhase9Entry(entry) ? this.getPhase9DisplayPayload(entry) : payload;
    const payloadKeys = payload
      ? Object.keys(displayPayload)
      : (Array.isArray(entry?.payload_keys) ? entry.payload_keys.map(key => String(key)) : []);

    if (payloadKeys.length === 0) {
      const empty = document.createElement('p');
      empty.className = 'log-section-hint';
      empty.textContent = 'No payload keys supplied by this activity record.';
      wrap.appendChild(empty);
      return wrap;
    }

    const list = document.createElement('dl');
    list.className = 'log-entry-payload-keys';
    payloadKeys.sort((a, b) => a.localeCompare(b)).forEach((key) => {
      const dt = document.createElement('dt');
      dt.textContent = key;
      const dd = document.createElement('dd');
      dd.textContent = displayPayload ? this.safePayloadValue(entry, key, displayPayload[key]) : 'present';
      list.append(dt, dd);
    });
    wrap.appendChild(list);

    if (this.isPrivacySensitiveEntry(entry)) {
      const note = document.createElement('p');
      note.className = 'log-redaction-note';
      note.textContent = 'Private text and identity fields are redacted by default.';
      wrap.appendChild(note);
    }

    return wrap;
  }

  createSourceChainDetails(entry) {
    const chain = this.getSourceChainForDisplay(entry);
    if (chain.length === 0) return null;

    const details = document.createElement('details');
    details.className = 'log-source-chain-details';

    const summary = document.createElement('summary');
    summary.textContent = 'Source chain / why';
    details.appendChild(summary);

    const list = document.createElement('ol');
    list.className = 'log-source-chain-list';
    chain.forEach((sourceItem) => {
      const item = document.createElement('li');
      const fields = document.createElement('dl');
      fields.className = 'log-entry-proof-list';
      PHASE_9_ALLOWED_SOURCE_CHAIN_KEYS.forEach((key) => {
        if (!Object.prototype.hasOwnProperty.call(sourceItem, key)) return;
        this.appendProofField(fields, key, sourceItem[key]);
      });
      item.appendChild(fields);
      list.appendChild(item);
    });
    details.appendChild(list);
    return details;
  }

  safePayloadValue(entry, key, value) {
    if (this.shouldRedactPayloadKey(entry, key)) return '[redacted by default]';
    if (value === null || value === undefined) return 'not supplied';
    if (Array.isArray(value)) return `array (${value.length} items)`;
    if (typeof value === 'object') return `object (${Object.keys(value).length} keys)`;
    const text = String(value);
    return text.length > 80 ? `${text.slice(0, 77)}...` : text;
  }

  shouldRedactPayloadKey(entry, key) {
    const normalizedKey = this.normalizePayloadKey(key);
    if (SENSITIVE_PAYLOAD_KEYS.has(normalizedKey)) return true;
    return this.isPrivacySensitiveEntry(entry) && IDENTITY_PAYLOAD_KEYS.has(normalizedKey);
  }

  isPrivacySensitiveEntry(entry) {
    const type = normalizeEventType(entry);
    if (SENSITIVE_TEXT_EVENTS.has(type)) return true;
    if (SENSITIVE_IDENTITY_EVENTS.some(marker => type.includes(marker))) return true;
    const payload = entry?.payload && typeof entry.payload === 'object' ? entry.payload : {};
    return Object.keys(payload).some(key => SENSITIVE_PAYLOAD_KEYS.has(this.normalizePayloadKey(key)));
  }

  normalizePayloadKey(key) {
    return normalizeText(key).replace(/[^a-z0-9_]/g, '');
  }

  isPhase9Entry(entry) {
    return rawEventType(entry).toLowerCase().startsWith('phase_9.');
  }

  formatEventLabel(entry) {
    const eventType = rawEventType(entry);
    if (!eventType) return 'Unknown event';
    if (this._displayNames?.formatActivityEventType) {
      return this._displayNames.formatActivityEventType(eventType);
    }
    return eventType;
  }

  getPhase9DisplayPayload(entry) {
    const payload = entry?.payload && typeof entry.payload === 'object' ? entry.payload : {};
    const safePayload = {};
    Object.keys(payload).forEach((key) => {
      const normalized = this.normalizePayloadKey(key);
      if (PHASE_9_ALLOWED_PAYLOAD_KEYS.has(normalized)) {
        safePayload[key] = payload[key];
      }
    });
    return safePayload;
  }

  getSourceChainForDisplay(entry) {
    const payload = entry?.payload && typeof entry.payload === 'object' ? entry.payload : {};
    const sourceChain = Array.isArray(entry?.source_chain)
      ? entry.source_chain
      : Array.isArray(payload.source_chain)
      ? payload.source_chain
      : [];
    return sourceChain
      .filter(item => item && typeof item === 'object' && !Array.isArray(item))
      .map((item) => {
        const safeItem = {};
        PHASE_9_ALLOWED_SOURCE_CHAIN_KEYS.forEach((key) => {
          if (Object.prototype.hasOwnProperty.call(item, key)) {
            safeItem[key] = item[key];
          }
        });
        return safeItem;
      })
      .filter(item => Object.keys(item).length > 0);
  }

  getMatrixStatus(entry) {
    const payload = entry?.payload && typeof entry.payload === 'object' ? entry.payload : {};
    const text = [
      entry?.classification,
      entry?.matrix_status,
      entry?.home_status,
      entry?.status,
      entry?.summary,
      payload.classification,
      payload.matrix_status,
      payload.home_status,
      payload.status
    ].filter(Boolean).join(' ').toLowerCase();

    if (text.includes('conflict') || text.includes('ambiguous')) return 'conflict_ambiguous';
    if (text.includes('deferred') || text.includes('reserved') || text.includes('future')) return 'deferred_reserved';
    if (text.includes('raw') || text.includes('proof')) return 'raw_proof';
    return 'activity_log_home';
  }

  describeMatrixStatus(entry) {
    const status = this.getMatrixStatus(entry);
    if (status === 'conflict_ambiguous') return 'Conflict/ambiguous - review before route implementation';
    if (status === 'deferred_reserved') return 'Deferred/reserved - proof visible here';
    if (status === 'raw_proof') return 'Raw/proof Activity Log home';
    return 'Activity Log fallback home';
  }

  createLogRow(entry) {
    const row = document.createElement("tr");

    const timestamp = entry.timestamp || "";
    const source = entry.source || "system";
    const aiTier = entry.ai_tier || "—";
    const category = this.resolveCategory(entry); // Old category for class name compatibility

    const summary = this.getHumanSummary(entry);

    const timestampCell = document.createElement("td");
    timestampCell.className = "log-timestamp";
    timestampCell.textContent = this.formatTimestamp(timestamp);

    const eventCell = document.createElement("td");
    eventCell.className = `log-event-type ${category}`;
    const eventLabel = document.createElement('span');
    eventLabel.className = 'log-event-label';
    eventLabel.textContent = this.formatEventLabel(entry);
    const summaryText = document.createElement('span');
    summaryText.className = 'log-summary-text';
    summaryText.textContent = summary;
    eventCell.append(eventLabel, summaryText);

    const sourceCell = document.createElement("td");
    sourceCell.className = "log-source";
    if (this._sourceProof) {
       const sourceKey = source.toLowerCase().replace(/-/g, '_');
       if (['available', 'blocked', 'disabled', 'stale', 'no_verified_source', 'future', 'manual'].includes(sourceKey)) {
         try {
           const badge = this._sourceProof.createOmniStateBadge(sourceKey);
           sourceCell.appendChild(badge);
         } catch {
           sourceCell.textContent = source;
         }
       } else if (!['ai', 'ai_provider', 'system', 'unknown'].includes(sourceKey)) {
         try {
           let chipKey = sourceKey;
           if (chipKey === 'journal') chipKey = 'local_event_history';
           if (chipKey === 'status.json' || chipKey === 'system') chipKey = 'local_telemetry';
           if (chipKey === 'external_disabled') chipKey = 'external_disabled';
           const chip = this._sourceProof.createSourceChip(chipKey);
           sourceCell.appendChild(chip);
         } catch {
           sourceCell.textContent = source;
         }
       } else {
         sourceCell.textContent = source;
       }
    } else {
       sourceCell.textContent = source;
    }

    const summaryCell = document.createElement("td");
    summaryCell.className = "log-summary";

    if (entry.payload && entry.payload.route_intent) {
       const link = document.createElement('a');
       link.href = `#${entry.payload.route_intent}`;
       link.className = 'ocv-route-handoff-link';
       link.textContent = `View in ${entry.payload.route_intent.replace('/', '')}`;
       link.onclick = (e) => {
         e.preventDefault();
         if (window.Shell && window.Shell.navigate) {
           window.Shell.navigate(entry.payload.route_intent);
         }
       };
       summaryCell.appendChild(link);
       summaryCell.appendChild(document.createElement('br'));
    }

    const chips = this.createPhase9Chips(entry);
    if (chips) summaryCell.appendChild(chips);

    /* PB09-08: Phase 9 owner-route back-links using allowlisted payload IDs only */
    if (this.isPhase9Entry(entry)) {
      const displayPayload = this.getPhase9DisplayPayload(entry);
      let ownerLink = null;
      if (displayPayload.campaign_id) {
        ownerLink = this._createOwnerRouteLink(
          'View in Operations', '/operations', String(displayPayload.campaign_id),
          'Viewing campaign from Activity Log.',
        );
      } else if (displayPayload.circuit_id) {
        ownerLink = this._createOwnerRouteLink(
          'View in Navigation', '/navigation', String(displayPayload.circuit_id),
          'Viewing circuit from Activity Log.',
        );
      } else if (displayPayload.note_id) {
        ownerLink = this._createOwnerRouteLink(
          'View in Squadrons', '/squadrons', String(displayPayload.note_id),
          'Viewing note from Activity Log.',
        );
      }
      if (ownerLink) summaryCell.appendChild(ownerLink);
    }

    summaryCell.appendChild(this.createProofDetails(entry));

    const tierCell = document.createElement("td");
    tierCell.textContent = aiTier;

    row.append(timestampCell, eventCell, sourceCell, summaryCell, tierCell);

    return row;
  }

  /* PB09-08: creates a button that navigates to an owner route using RouteTransferIntent.
     entityId must be a pre-filtered allowlisted ID (never raw text). */
  _createOwnerRouteLink(label, targetRoute, entityId, reason) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'log-phase9-owner-link';
    btn.textContent = label;
    btn.addEventListener('click', () => {
      if (typeof window.Shell?.startRouteTransfer !== 'function') {
        window.location.hash = `#${targetRoute}`;
        return;
      }
      window.Shell.startRouteTransfer({
        originRoute: '/activity-log',
        originPackage: 'Activity Log',
        originSectionId: 'log-body',
        targetRoute,
        targetSectionId: '',
        targetEntityId: entityId,
        targetLabel: label,
        reason,
        returnLabel: 'Return to Activity Log',
        returnTarget: { route: '/activity-log' },
      });
    });
    return btn;
  }

  createPhase9Chips(entry) {
    if (!this.isPhase9Entry(entry)) return null;
    const payload = this.getPhase9DisplayPayload(entry);
    const chips = [];
    const type = rawEventType(entry).toLowerCase();

    if (type.startsWith('phase_9.campaign.ai_draft') || payload.is_fact === false) {
      chips.push(['is_fact', 'false']);
    }
    if (type.startsWith('phase_9.squadron.') || payload.visibility === 'local_only') {
      chips.push(['visibility', 'local_only']);
    }
    if (payload.source_label) {
      chips.push(['source', payload.source_label]);
    } else if (payload.source_type) {
      chips.push(['source', payload.source_type]);
    } else if (this.getSourceChainForDisplay(entry).length > 0) {
      chips.push(['source', 'source_chain']);
    }

    if (chips.length === 0) return null;
    const wrap = document.createElement('div');
    wrap.className = 'log-phase9-chips';
    chips.forEach(([label, value]) => {
      const chip = document.createElement('span');
      chip.className = 'log-phase9-chip';
      chip.textContent = `${label}=${value}`;
      wrap.appendChild(chip);
    });
    return wrap;
  }

  formatTimestamp(ts) {
    if (!ts) return "";
    try {
      const date = new Date(ts);
      return date.toLocaleString([], {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return ts;
    }
  }

  updatePagination() {
    const maxPage = Math.max(
      1,
      Math.ceil(this.filteredEntries.length / this.pageSize)
    );
    const pageInfo = document.getElementById("log-page-info");
    if (pageInfo) {
      pageInfo.textContent = `Page ${this.currentPage + 1} of ${maxPage}`;
    }

    const prevBtn = document.getElementById("log-prev-btn");
    const nextBtn = document.getElementById("log-next-btn");

    if (prevBtn) prevBtn.disabled = this.currentPage === 0;
    if (nextBtn) nextBtn.disabled = this.currentPage >= maxPage - 1;
  }

  async exportLog() {
    const json = JSON.stringify(
      {
        total: this.filteredEntries.length,
        entries: this.filteredEntries,
        exported_at: new Date().toISOString(),
      },
      null,
      2
    );

    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `omnicovas-activity-log-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  showClearConfirm() {
    document.getElementById("log-clear-modal").style.display = "flex";
  }

  async clearLog() {
    try {
      // In Phase 3, there's no /activity-log/clear endpoint
      this.allEntries = [];
      this.filteredEntries = [];
      this.currentPage = 0;

      document.getElementById("log-clear-modal").style.display = "none";
      this.renderPage();
      alert("Activity log cleared!");
    } catch (err) {
      console.error("Failed to clear log:", err);
      alert("Failed to clear log. See console for details.");
    }
  }
}

globalThis.__activityLogExports = { ActivityLogController };

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    new ActivityLogController();
  });
} else {
  new ActivityLogController();
}
