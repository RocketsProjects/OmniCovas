/**
 * Phase 3 Week 14 — Resources Controller
 *
 * Consumes GET /resources and renders four cards:
 *   Memory, CPU, Disk, Budget Limits
 *
 * Constraints:
 *   - Classic script (not ES module)
 *   - No innerHTML/outerHTML with dynamic values — element.textContent only
 *   - null/undefined fields render as —
 *   - enabled:false or snapshot:null → status message + all fields at —
 *   - Fetch failure → non-fatal, shows unavailable state
 *   - No polling; manual refresh via button only
 *   - Auto-fetches on bridge-connected event via window.OmniEvents
 */

'use strict';

class ResourcesController {
  constructor() {
    this._boundBridgeHandler = () => { this.fetchAndRender(); };
    this.init();
  }

  get apiBase() {
    if (window.Shell?.httpBase) return window.Shell.httpBase;
    if (window.OMNICOVAS_PORT) return `http://127.0.0.1:${window.OMNICOVAS_PORT}`;
    return null;
  }

  init() {
    this.bindEvents();
    this.bindBridgeEvents();
    this.fetchWhenBridgeReady();
  }

  bindEvents() {
    document.getElementById('res-refresh-btn')
      ?.addEventListener('click', () => { this.fetchAndRender(); });
  }

  bindBridgeEvents() {
    window.OmniEvents?.addEventListener('bridge-connected', this._boundBridgeHandler);
  }

  fetchWhenBridgeReady() {
    if (!this.apiBase) {
      this.setStatusMsg('Waiting for OmniCOVAS bridge…');
      this.renderSnapshot(null, null);
      this.renderBudget(null);
      return;
    }
    this.fetchAndRender();
  }

  async fetchAndRender() {
    const base = this.apiBase;
    if (!base) {
      this.setStatusMsg('Waiting for OmniCOVAS bridge…');
      this.renderSnapshot(null, null);
      this.renderBudget(null);
      return;
    }

    let data;
    try {
      const res = await fetch(`${base}/resources`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      data = await res.json();
    } catch (err) {
      console.error('Resources fetch failed:', err);
      this.renderUnavailable();
      return;
    }
    this.render(data);
  }

  render(data) {
    if (!data.enabled) {
      this.setStatusMsg('Resource monitoring disabled.');
      this.renderSnapshot(null, null);
      this.renderBudget(data.budget ?? null);
      return;
    }
    if (data.snapshot == null) {
      this.setStatusMsg('Resource monitor initializing…');
      this.renderSnapshot(null, null);
      this.renderBudget(data.budget ?? null);
      return;
    }
    this.setStatusMsg('');
    this.renderSnapshot(data.snapshot, data.budget?.max_cache_size_mb ?? null);
    this.renderBudget(data.budget ?? null);
    this.stampLastUpdated();
  }

  renderUnavailable() {
    this.setStatusMsg('Resource data unavailable.');
    this.renderSnapshot(null, null);
    this.renderBudget(null);
  }

  // ── Status banner ────────────────────────────────────────────────────────

  setStatusMsg(text) {
    const el = document.getElementById('res-status-msg');
    if (!el) return;
    el.textContent = text;
    el.style.display = text ? '' : 'none';
  }

  // ── Snapshot cards ───────────────────────────────────────────────────────

  renderSnapshot(snap, budgetCacheMb) {
    this.renderMemory(snap, budgetCacheMb);
    this.renderCpu(snap);
    this.renderDisk(snap);
  }

  renderMemory(snap, budgetCacheMb) {
    const usedMb  = snap?.memory_used_mb  ?? null;
    const totalMb = snap?.memory_total_mb ?? null;
    const pct = (usedMb != null && totalMb != null && totalMb > 0)
                  ? (usedMb / totalMb) * 100
                  : null;
    const cls = this.memClass(usedMb, budgetCacheMb);

    this.setText('res-mem-used',  usedMb  != null ? usedMb.toFixed(1)  + ' MB' : '—');
    this.setText('res-mem-total', totalMb != null ? totalMb.toFixed(1) + ' MB' : '—');
    this.setText('res-mem-pct',   pct     != null ? pct.toFixed(1)     + '%'   : '—');

    const barEl = document.getElementById('res-mem-bar');
    if (barEl) {
      barEl.style.width = pct != null ? Math.min(pct, 100).toFixed(1) + '%' : '0%';
      barEl.className = 'progress-bar-fill' + (cls ? ' ' + cls : '');
    }
  }

  renderCpu(snap) {
    const cpuPct = snap?.cpu_percent ?? null;
    const cls    = this.cpuClass(cpuPct);

    const pctEl = document.getElementById('res-cpu-pct');
    if (pctEl) {
      pctEl.textContent = cpuPct != null ? cpuPct.toFixed(1) + '%' : '—';
      pctEl.className = 'field-value' + (cls ? ' ' + cls : '');
    }

    const badgeEl = document.getElementById('res-cpu-badge');
    if (badgeEl) {
      if (cpuPct == null) {
        badgeEl.textContent = '—';
        badgeEl.className = 'badge muted';
      } else if (cls === 'critical') {
        badgeEl.textContent = 'HIGH';
        badgeEl.className = 'badge critical';
      } else if (cls === 'warn') {
        badgeEl.textContent = 'ELEVATED';
        badgeEl.className = 'badge warn';
      } else {
        badgeEl.textContent = 'OK';
        badgeEl.className = 'badge ok';
      }
    }

    const barEl = document.getElementById('res-cpu-bar');
    if (barEl) {
      barEl.style.width = cpuPct != null ? Math.min(cpuPct, 100).toFixed(1) + '%' : '0%';
      barEl.className = 'progress-bar-fill' + (cls ? ' ' + cls : '');
    }

    this.setCardState('card-res-cpu', cls || null);
  }

  renderDisk(snap) {
    const freeGb  = snap?.disk_free_gb  ?? null;
    const totalGb = snap?.disk_total_gb ?? null;
    const usedGb  = (freeGb != null && totalGb != null) ? (totalGb - freeGb) : null;
    const pct     = (usedGb != null && totalGb != null && totalGb > 0)
                      ? (usedGb / totalGb) * 100
                      : null;
    const cls     = this.diskClass(pct);

    this.setText('res-disk-used',  usedGb  != null ? usedGb.toFixed(1)  + ' GB' : '—');
    this.setText('res-disk-total', totalGb != null ? totalGb.toFixed(1) + ' GB' : '—');

    const pctEl = document.getElementById('res-disk-pct');
    if (pctEl) {
      pctEl.textContent = pct != null ? pct.toFixed(1) + '%' : '—';
      pctEl.className = 'field-value' + (cls ? ' ' + cls : '');
    }

    const barEl = document.getElementById('res-disk-bar');
    if (barEl) {
      barEl.style.width = pct != null ? Math.min(pct, 100).toFixed(1) + '%' : '0%';
      barEl.className = 'progress-bar-fill' + (cls ? ' ' + cls : '');
    }

    this.setCardState('card-res-disk', cls || null);
  }

  // ── Budget card ──────────────────────────────────────────────────────────

  renderBudget(budget) {
    this.setText('res-budget-cache',
      budget?.max_cache_size_mb               != null ? budget.max_cache_size_mb               + ' MB'     : '—');
    this.setText('res-budget-disk',
      budget?.max_galaxy_dump_size_gb         != null ? budget.max_galaxy_dump_size_gb         + ' GB'     : '—');
    this.setText('res-budget-cpu',
      budget?.max_background_task_cpu_percent != null ? budget.max_background_task_cpu_percent + '%'       : '—');
    this.setText('res-budget-api',
      budget?.max_api_calls_per_minute_total  != null ? budget.max_api_calls_per_minute_total  + '/min'  : '—');
  }

  // ── Pure helpers ─────────────────────────────────────────────────────────

  setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = (value == null) ? '—' : value;
  }

  setCardState(cardId, state) {
    const card = document.getElementById(cardId);
    if (!card) return;
    card.classList.remove('ok', 'warn', 'critical');
    if (state) card.classList.add(state);
  }

  stampLastUpdated() {
    const el = document.getElementById('res-last-updated');
    if (el) el.textContent = 'Updated ' + new Date().toLocaleTimeString();
  }

  // ── Classification — UI display severity only, not ResourceMonitor policy ─

  cpuClass(pct) {
    if (pct == null) return '';
    if (pct >= 80) return 'critical';
    if (pct >= 50) return 'warn';
    return '';
  }

  diskClass(pct) {
    if (pct == null) return '';
    if (pct >= 90) return 'critical';
    if (pct >= 75) return 'warn';
    return '';
  }

  memClass(usedMb, budgetCacheMb) {
    if (usedMb == null || budgetCacheMb == null) return '';
    if (usedMb > budgetCacheMb) return 'warn';
    return '';
  }
}

// Initialize on page load
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => { new ResourcesController(); });
} else {
  new ResourcesController();
}

// Test hook for Vitest; keeps this browser-compatible without changing production module/script loading.
globalThis.__resourcesExports = { ResourcesController };
