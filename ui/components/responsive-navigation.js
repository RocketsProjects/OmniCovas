// Presentation only: original route/mode controls remain the selection owners.
// A single controller observes the mounted content; replaced rows retain no
// observers, timers or global listeners of their own.
const rows = '#uiv3-tab-row, .operation-selector, [role="tablist"]';
const itemSelector = '[data-uiv3-route], [role="tab"]';
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  node.className = cls;
  if (text != null) node.textContent = text;
  return node;
};

export function installResponsiveNavigation({ scope = document, onFit = () => {} } = {}) {
  let frame = null;
  let picker = null;
  let disposed = false;
  const fit = () => {
    frame = null;
    if (disposed) return;
    scope.querySelectorAll(rows).forEach((row) => {
      if (row.querySelector('.operation-selector')) return;
      const items = [...row.querySelectorAll(itemSelector)].filter(n => !n.closest('.rcd-nav-picker'));
      if (!items.length || !row.getBoundingClientRect().width) return;
      row.classList.add('rcd-nav-row');
      items.forEach(item => {
        if (!item.querySelector('svg') && window.Uiv3Frame?.createUiv3Icon) {
          const icon = el('span', 'rcd-nav-icon');
          icon.setAttribute('aria-hidden', 'true');
          icon.appendChild(window.Uiv3Frame.createUiv3Icon('compass-diamond'));
          item.prepend(icon);
        }
      });
      let more = row.querySelector(':scope > .rcd-nav-more');
      if (!more) {
        more = el('button', 'rcd-button rcd-nav-more', 'More ▾');
        more.type = 'button';
        more.setAttribute('aria-haspopup', 'dialog');
        more.setAttribute('aria-label', `More ${row.id === 'uiv3-tab-row' ? 'routes' : 'modes'}`);
        row.appendChild(more);
      }
      items.forEach(item => { item.hidden = false; });
      const width = row.clientWidth - 24 - Math.max(78, more.getBoundingClientRect().width);
      // Read geometry together before changing visibility. Interleaved reads
      // and writes force a fresh browser layout for every tab during startup.
      const widths = new Map(items.map(item => [item, item.getBoundingClientRect().width + 4]));
      const active = items.find(n => n.getAttribute('aria-current') === 'page' || n.getAttribute('aria-selected') === 'true');
      const activeWidth = active ? widths.get(active) : 0;
      let used = activeWidth;
      for (const item of items) {
        if (item === active) continue;
        const size = widths.get(item);
        item.hidden = used + size > width;
        if (!item.hidden) used += size;
      }
      const selectedName = active?.textContent.trim();
      more.title = selectedName ? `All choices · ${selectedName} selected` : 'All choices';
    });
    onFit();
  };
  const schedule = () => {
    if (!disposed && frame === null) frame = requestAnimationFrame(fit);
  };
  const close = () => { if (picker?.open) picker.close(); };
  const click = (event) => {
    const more = event.target.closest('.rcd-nav-more');
    if (!more) return;
    close();
    const row = more.parentElement;
    const items = [...row.querySelectorAll(itemSelector)];
    picker = el('dialog', 'rcd-dialog rcd-nav-picker');
    picker.setAttribute('aria-label', more.getAttribute('aria-label'));
    const header = el('header', 'rcd-dialog-header');
    const title = el('h2', '', row.id === 'uiv3-tab-row' ? 'Go to…' : 'Choose a mode');
    const cancel = el('button', 'rcd-button', 'Close');
    cancel.type = 'button';
    cancel.addEventListener('click', close);
    header.append(title, cancel);
    const list = el('div', 'rcd-dialog-body rcd-nav-options');
    items.forEach((item) => {
      const choice = el('button', 'rcd-button', item.textContent.trim());
      choice.type = 'button';
      const active = item.getAttribute('aria-current') === 'page' || item.getAttribute('aria-selected') === 'true';
      choice.setAttribute('aria-pressed', String(active));
      choice.disabled = item.disabled || item.getAttribute('aria-disabled') === 'true';
      choice.addEventListener('click', () => {
        const key = item.getAttribute('data-operation') || item.getAttribute('data-uiv3-route');
        close();
        item.click();
        schedule();
        requestAnimationFrame(() => {
          const target = key ? [...scope.querySelectorAll('[data-operation], [data-uiv3-route]')]
            .find(n => n.matches('button, a') && !n.hidden && (n.getAttribute('data-operation') === key || n.getAttribute('data-uiv3-route') === key)) : null;
          (target || more).focus({ preventScroll: true });
        });
      });
      list.appendChild(choice);
    });
    picker.append(header, list);
    const currentPicker = picker;
    const attention = document.querySelector('.ocv-attention');
    const attentionParent = attention?.parentNode;
    if (attention) picker.append(attention);
    document.body.appendChild(picker);
    picker.addEventListener('close', () => {
      if(attention?.parentNode===currentPicker)(attentionParent?.isConnected?attentionParent:document.body).append(attention);
      currentPicker.remove(); if(picker===currentPicker)picker = null; if (more.isConnected) more.focus({ preventScroll: true });
    }, { once: true });
    picker.showModal();
  };
  const keydown = (event) => {
    const row = event.target.closest('.rcd-nav-row');
    if (!row || event.target.closest('.rcd-nav-picker')) return;
    const items = [...row.querySelectorAll(`${itemSelector}, .rcd-nav-more`)].filter(n => !n.hidden && !n.disabled);
    const index = items.indexOf(document.activeElement);
    let next;
    if (event.key === 'ArrowRight') next = (index + 1) % items.length;
    if (event.key === 'ArrowLeft') next = (index - 1 + items.length) % items.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = items.length - 1;
    if (next === undefined) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    items[next]?.focus();
    // Manual activation with Enter/Space keeps route-owned selection intact.
  };
  const observer = new MutationObserver(changes => {
    if(changes.some(change => change.target.closest?.(rows) || [...change.addedNodes].some(node => node.matches?.(rows) || node.querySelector?.(rows)))) schedule();
  });
  observer.observe(scope.body || scope, { childList: true, subtree: true });
  const resize = typeof ResizeObserver === 'function' ? new ResizeObserver(schedule) : null;
  resize?.observe(document.documentElement);
  scope.addEventListener('click', click);
  scope.addEventListener('keydown', keydown, true);
  window.addEventListener('resize', schedule);
  window.addEventListener('hashchange', schedule);
  schedule();
  return { refresh: schedule, dispose() {
    disposed = true;
    observer.disconnect(); resize?.disconnect();
    if (frame !== null) cancelAnimationFrame(frame);
    scope.removeEventListener('click', click);
    scope.removeEventListener('keydown', keydown, true);
    window.removeEventListener('resize', schedule);
    window.removeEventListener('hashchange', schedule);
    close();
  } };
}
