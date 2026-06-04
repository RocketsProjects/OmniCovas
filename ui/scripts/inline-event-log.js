'use strict';

let logEntries = [];
const MAX_LOG = 500;

function formatTime(ts) {
  if (!ts) return '—';
  try { return new Date(ts).toLocaleTimeString(); } catch (e) { return ts; }
}

function isCritical(t) {
  return ['HULL_CRITICAL_10', 'HULL_CRITICAL_25', 'SHIELDS_DOWN',
          'FUEL_CRITICAL', 'MODULE_CRITICAL'].includes(t);
}

function isWarn(t) {
  return ['HULL_DAMAGE', 'FUEL_LOW', 'HEAT_WARNING', 'MODULE_DAMAGED'].includes(t);
}

// Returns one of: 'critical', 'extended', 'ai', 'telemetry', or 'warn' (legacy fallback).
// Uses entry.category if provided (aligned with table's resolveCategory), then falls back
// to isCritical/isWarn for entries that arrive without a category field.
function getEntryCategory(entry) {
  var validCategories = { critical: true, extended: true, ai: true, telemetry: true };
  if (entry.category && validCategories[entry.category]) return entry.category;
  if (isCritical(entry.event_type)) return 'critical';
  if (isWarn(entry.event_type)) return 'warn';
  var t = (entry.event_type || '').toUpperCase();
  // ai checked before CRITICAL to avoid misclassifying PROPOSAL events
  if (t.indexOf('TIER_3') !== -1 || t.indexOf('CONFIRMATION') !== -1 || t.indexOf('PROPOSAL') !== -1) return 'ai';
  if (t.indexOf('CRITICAL') !== -1 || t.indexOf('DESTROYED') !== -1) return 'critical';
  if (t.indexOf('DOCKED') !== -1 || t.indexOf('WANTED') !== -1 || t.indexOf('FSD') !== -1) return 'extended';
  return 'telemetry';
}

function renderLog(filter) {
  var container = document.getElementById('log-entries');
  if (!container) return;
  var items = filter
    ? logEntries.filter(function(e) {
        return (e.event_type || '').toLowerCase().indexOf(filter) !== -1 ||
               (e.summary || '').toLowerCase().indexOf(filter) !== -1;
      })
    : logEntries;

  container.replaceChildren();

  if (items.length === 0) {
    var p = document.createElement('p');
    p.className = 'field-value unknown';
    p.style.padding = 'var(--space-3)';
    p.textContent = 'No events yet.';
    container.appendChild(p);
    return;
  }

  items.slice(0, MAX_LOG).forEach(function(e) {
    var category = getEntryCategory(e);
    var cls = category !== 'telemetry' ? category : '';
    var div = document.createElement('div');
    div.className = 'log-entry' + (cls ? ' ' + cls : '');
    div.setAttribute('role', 'listitem');

    var timeSpan = document.createElement('span');
    timeSpan.className = 'log-time';
    timeSpan.textContent = formatTime(e.timestamp);

    var typeSpan = document.createElement('span');
    typeSpan.className = 'log-type';
    typeSpan.textContent = e.event_type || '—';

    var msgSpan = document.createElement('span');
    msgSpan.className = 'log-msg';
    msgSpan.textContent = e.summary || '';

    div.appendChild(timeSpan);
    div.appendChild(typeSpan);
    div.appendChild(msgSpan);
    container.appendChild(div);
  });
}

function addLogEntry(entry) {
  logEntries.unshift(entry);
  if (logEntries.length > MAX_LOG) logEntries.length = MAX_LOG;
  var searchEl = document.getElementById('log-search');
  renderLog(searchEl ? searchEl.value.toLowerCase().trim() : '');
}

async function fetchLog() {
  if (!window.OMNICOVAS_PORT) return;
  try {
    var r = await fetch('http://127.0.0.1:' + window.OMNICOVAS_PORT + '/activity-log');
    if (!r.ok) return;
    var data = await r.json();
    logEntries = (data.entries || []).reverse();
    renderLog('');
  } catch (e) { /* silent */ }
}

function hydrateLogForCurrentRoute(attempt) {
  if (attempt === undefined) attempt = 0;
  if (window.location.hash !== '#/activity-log') return;
  if (window.OMNICOVAS_PORT) { fetchLog(); return; }
  if (attempt >= 20) return;
  setTimeout(function () { hydrateLogForCurrentRoute(attempt + 1); }, 100);
}

// Module runs after DOM is parsed — wire search and clear at top-level
var searchEl = document.getElementById('log-search');
if (searchEl) {
  searchEl.addEventListener('input', function () {
    renderLog(searchEl.value.toLowerCase().trim());
  });
}
var clearBtn = document.getElementById('log-clear-btn');
if (clearBtn) {
  clearBtn.addEventListener('click', function () {
    if (confirm('Clear the activity log display? (Does not affect stored history.)')) {
      logEntries = [];
      renderLog('');
    }
  });
}

window.addEventListener('hashchange', function () {
  if (window.location.hash === '#/activity-log') fetchLog();
});

if (window.OmniEvents && typeof window.OmniEvents.addEventListener === 'function') {
  window.OmniEvents.addEventListener('bridge-connected', function () {
    hydrateLogForCurrentRoute();
  });
}

window._addLogEntry = addLogEntry;

hydrateLogForCurrentRoute();

export { renderLog, addLogEntry, fetchLog, hydrateLogForCurrentRoute, getEntryCategory };
