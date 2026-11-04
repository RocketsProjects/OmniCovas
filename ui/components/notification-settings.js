// NHI-03/04 Settings: notification attention choices for the current
// Commander, plus this device's text and motion choices. Lives inside the
// existing Settings "Notifications & Overlay" tab; storage is the existing
// configuration vault behind /notifications/preferences. Critical alert
// switches, opacity and position stay with the existing overlay settings.
// ADR 0003: every value is rendered with textContent.

const node = (tag, cls = '', text) => {
  const element = document.createElement(tag);
  if (cls) element.className = cls;
  if (text != null) element.textContent = String(text);
  return element;
};

export const PROFILES = Object.freeze({
  Minimal: {
    label: 'Minimal',
    help: 'Critical ship alerts only. Nothing else interrupts you. Recommended.',
  },
  Flightdeck: {
    label: 'Flightdeck',
    help: 'Also brief notices for meaningful exploration, engineering and mining milestones, in this window.',
  },
  Explorer: {
    label: 'Explorer',
    help: 'Also brief notices for exploration discoveries and engineering milestones, in this window.',
  },
  Custom: {
    label: 'Custom',
    help: 'Choose which kinds of milestones may show a brief notice.',
  },
});

export const CATEGORIES = Object.freeze({
  exploration: 'Exploration discoveries (body mapped, biology sample complete)',
  engineering: 'Engineering and objective milestones',
  mining: 'Mining and cargo milestones',
  navigation: 'Navigation milestones',
});

export const DURATIONS = [4, 8, 15, 30];
export const TEXT_SCALES = [100, 125, 150, 200];

export function createNotificationSettings({ fetchJson, sendJson, openTab = null }) {
  const root = node('section', 'ns-settings');
  root.setAttribute('aria-labelledby', 'ns-settings-heading');
  let form = null;
  let device = null;
  let meta = {};
  let status = '';

  function radio(name, value, checked, labelText, help, onChange) {
    const wrap = node('div', 'ns-choice');
    const label = node('label', 'ns-choice-label');
    const input = node('input');
    input.type = 'radio';
    input.name = name;
    input.value = value;
    input.checked = checked;
    input.addEventListener('change', () => { if (input.checked) onChange(value); });
    label.append(input, node('span', 'ns-choice-title', labelText));
    wrap.append(label);
    if (help) wrap.append(node('p', 'ns-help', help));
    return wrap;
  }

  function checkbox(name, checked, labelText, help, onChange, { disabled = false } = {}) {
    const wrap = node('div', 'ns-field');
    const label = node('label', 'ns-check');
    const input = node('input');
    input.type = 'checkbox';
    input.name = name;
    input.checked = checked;
    input.disabled = disabled;
    input.addEventListener('change', () => onChange(input.checked));
    label.append(input, node('span', '', labelText));
    wrap.append(label);
    if (help) wrap.append(node('p', 'ns-help', help));
    return wrap;
  }

  function select(id, labelText, options, value, onChange) {
    const wrap = node('div', 'ns-field');
    const label = node('label', 'ns-select-label', labelText);
    label.htmlFor = id;
    const input = node('select');
    input.id = id;
    options.forEach(([optionValue, text]) => {
      const option = node('option', '', text);
      option.value = String(optionValue);
      option.selected = String(optionValue) === String(value);
      input.append(option);
    });
    input.addEventListener('change', () => onChange(input.value));
    wrap.append(label, input);
    return wrap;
  }

  function render() {
    const heading = node('h2', '', 'Notifications');
    heading.id = 'ns-settings-heading';
    root.replaceChildren(heading);
    root.append(node('p', 'ns-lead',
      'OmniCOVAS stays quiet unless something deserves your attention. Critical ship alerts appear in the in-game overlay; everything else is optional.'));
    if (!form) {
      root.append(node('p', 'ns-status', status || 'Loading notification preferences…'));
      return;
    }
    if (meta.forgotten) {
      root.append(node('p', 'ns-scope', 'This commander was forgotten in Privacy, so notification choices cannot be saved for them.'));
    } else {
      root.append(node('p', 'ns-scope', meta.commanderKnown
        ? 'Attention choices apply to the commander OmniCOVAS currently observes. Each commander keeps their own.'
        : 'No commander observed yet. These choices become the starting point for each commander.'));
    }

    const profile = node('fieldset', 'ns-group');
    profile.append(node('legend', '', 'What may interrupt you'));
    Object.entries(PROFILES).forEach(([id, item]) => {
      profile.append(radio('ns-profile', id, form.profile === id, item.label, item.help, (value) => {
        form.profile = value;
        render();
        root.querySelector(`input[name="ns-profile"][value="${value}"]`)?.focus();
      }));
    });
    root.append(profile);

    if (form.profile === 'Custom') {
      const cats = node('fieldset', 'ns-group');
      cats.append(node('legend', '', 'Milestones that may show a brief notice'));
      Object.entries(CATEGORIES).forEach(([id, text]) => {
        cats.append(checkbox(`ns-cat-${id}`, form.categories[id], text, '', (v) => { form.categories[id] = v; }));
      });
      root.append(cats);
    }

    const behaviour = node('fieldset', 'ns-group');
    behaviour.append(node('legend', '', 'Behaviour'));
    behaviour.append(checkbox('ns-quiet', form.quiet, 'Quiet mode',
      'Holds every non-critical notice. Critical ship alerts still appear.', (v) => { form.quiet = v; }));
    behaviour.append(checkbox('ns-overlay-glances', form.overlay_glances,
      'Show non-critical notices in the in-game overlay',
      'Off by default. When off, milestones appear only in this window. Never on during combat or interdiction, and a critical alert always replaces a notice.',
      (v) => { form.overlay_glances = v; }, { disabled: form.profile === 'Minimal' }));
    behaviour.append(select('ns-duration', 'How long a notice stays',
      DURATIONS.map((s) => [s, `${s} seconds`]), form.duration, (v) => { form.duration = Number(v); }));
    behaviour.append(node('p', 'ns-help',
      'Critical alerts stay for their own time and are never shortened by other notices. Dismissing an alert does not mark the problem fixed.'));
    root.append(behaviour);

    const display = node('fieldset', 'ns-group');
    display.append(node('legend', '', 'This device'));
    display.append(checkbox('ns-overlay', device.overlay, 'Use the in-game overlay for critical alerts',
      'When off, critical alerts appear in this window instead.', (v) => { device.overlay = v; }));
    display.append(select('ns-text-scale', 'Overlay text size',
      TEXT_SCALES.map((s) => [s, `${s}%`]), device.text_scale, (v) => { device.text_scale = Number(v); }));
    display.append(select('ns-motion', 'Motion',
      [['system', 'Follow Windows setting'], ['reduce', 'Always reduce motion']], device.reduced_motion,
      (v) => { device.reduced_motion = v; }));
    display.append(node('p', 'ns-help', 'Sound: OmniCOVAS does not play notification sounds.'));
    root.append(display);

    const gki = node('div', 'ns-group ns-gki');
    gki.append(node('p', 'ns-help',
      'Historical briefings, expedition stories, spoiler protection and first-visit behaviour are set in Galactic Intelligence. They appear in this window only and never become ship alerts.'));
    if (openTab) {
      const link = node('button', 'ocv-btn-ghost ns-gki-link', 'Open Galactic Intelligence settings');
      link.type = 'button';
      link.addEventListener('click', () => openTab('galactic-intelligence'));
      gki.append(link);
    }
    root.append(gki);

    const actions = node('div', 'ns-actions');
    const save = node('button', 'primary-button ns-save', 'Save notification settings');
    save.type = 'button';
    save.disabled = Boolean(meta.forgotten);
    save.addEventListener('click', saveForm);
    const reset = node('button', 'secondary-button ns-reset', 'Reset this commander to Minimal');
    reset.type = 'button';
    reset.disabled = Boolean(meta.forgotten);
    reset.addEventListener('click', resetForm);
    actions.append(save, reset);
    root.append(actions);
    const statusEl = node('p', 'ns-status', status);
    statusEl.setAttribute('role', 'status');
    statusEl.setAttribute('aria-live', 'polite');
    root.append(statusEl);
  }

  function adopt(payload) {
    form = structuredClone(payload.preferences);
    device = structuredClone(payload.device);
    meta = { commanderKnown: payload.commander_known, forgotten: payload.forgotten };
  }

  async function load() {
    try {
      adopt(await fetchJson('/notifications/preferences'));
      status = '';
    } catch (error) {
      status = 'Notification preferences are unavailable until the OmniCOVAS core is running.';
      form = null;
    }
    render();
  }

  async function saveForm() {
    try {
      adopt(await sendJson('PUT', '/notifications/preferences', { preferences: form, device }));
      status = 'Saved.';
    } catch (error) {
      status = 'Not saved. Check the values and try again.';
    }
    render();
    root.querySelector('.ns-save')?.focus();
  }

  async function resetForm() {
    try {
      adopt(await sendJson('POST', '/notifications/preferences/reset', { confirm: true }));
      status = 'This commander is back to Minimal. Galactic Intelligence, history and privacy choices were not changed.';
    } catch (error) {
      status = 'Not reset.';
    }
    render();
    root.querySelector('.ns-reset')?.focus();
  }

  render();
  return { element: root, load, get form() { return form; } };
}

/* Developer/Test: which path owns presentation, and what surfaces reported. */
export function createPresentationOwnerControl({ fetchJson, sendJson }) {
  const root = node('section', 'ns-owner');
  root.setAttribute('aria-labelledby', 'ns-owner-heading');
  let info = null;
  let counters = null;
  let status = '';

  function render() {
    const heading = node('h2', '', 'Notification engine');
    heading.id = 'ns-owner-heading';
    root.replaceChildren(heading);
    root.append(node('p', 'ns-help',
      'The Notification Director decides what may interrupt you. The classic overlay is the fallback, used automatically if the Director stops working. Switching keeps all commander data.'));
    if (!info) {
      root.append(node('p', 'ns-status', status || 'Loading…'));
      return;
    }
    const current = info.owner === 'director' ? 'Notification Director' : 'Classic overlay';
    root.append(node('p', 'ns-owner-state', `In use: ${current}${info.reason && info.reason !== 'healthy' ? ` (${info.reason.replace(/_/g, ' ')})` : ''}`));
    const row = node('div', 'ns-actions');
    [['director', 'Use Notification Director'], ['legacy', 'Use classic overlay']].forEach(([value, text]) => {
      const b = node('button', 'secondary-button', text);
      b.type = 'button';
      b.setAttribute('aria-pressed', String(info.configured_owner === value));
      b.addEventListener('click', async () => {
        try {
          info = await sendJson('POST', '/notifications/owner', { owner: value });
          status = 'Saved.';
        } catch {
          status = 'Not changed.';
        }
        render();
      });
      row.append(b);
    });
    root.append(row);
    if (counters) {
      root.append(node('p', 'ns-help',
        `Delivery receipts this run: ${counters.accepted} accepted, ${counters.rendered} rendered, ${counters.acknowledged} acknowledged, ${counters.failed} failed to display.`));
    }
    const statusEl = node('p', 'ns-status', status);
    statusEl.setAttribute('role', 'status');
    root.append(statusEl);
  }

  async function load() {
    try {
      info = await fetchJson('/notifications/owner');
      counters = (await fetchJson('/notifications/receipts?limit=1')).counters;
      status = '';
    } catch {
      info = null;
      status = 'Unavailable until the OmniCOVAS core is running.';
    }
    render();
  }

  render();
  return { element: root, load };
}
