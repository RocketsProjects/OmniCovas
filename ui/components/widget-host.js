import { widgetRegistry, validateManifest } from './widget-registry.js';
import { packDeck } from './deck-layout.js';
import { selectWidget, subjectKey } from '../view-models/widget-snapshot.js';

export const deckNode = (tag, cls = '', text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
};
let activeDialog = null;

export function openDeckDetail({ title, content, trigger, onClose = () => {} }) {
  if (activeDialog) { activeDialog.dataset.replaced = 'true'; activeDialog.close(); }
  const dialog = deckNode('dialog', 'rcd-dialog rcd-widget-detail');
  dialog.setAttribute('aria-label', title);
  const header = deckNode('header', 'rcd-dialog-header');
  const close = deckNode('button', 'rcd-button', 'Close');
  close.type = 'button';
  close.addEventListener('click', () => dialog.close());
  header.append(deckNode('h2', '', title), close);
  const body = deckNode('div', 'rcd-dialog-body');
  if (content) body.append(content);
  dialog.append(header, body);
  // Keep the *same* Director-owned alert node inside the modal top layer.
  // No mirrored alerts, second subscriptions or replacement acknowledgement.
  const attention = document.querySelector('.ocv-attention');
  const attentionParent = attention?.parentNode;
  if (attention) dialog.append(attention);
  (trigger?.closest('[data-route]') || trigger?.closest('.view') || document.body).append(dialog);
  let restoreFocus = true;
  const routeChanged = () => { restoreFocus = false; dialog.close(); };
  // A route link must dismiss the native modal before the destination opens.
  // Leaving it in the top layer makes a working destination appear inert.
  dialog.addEventListener('click', event => {
    if (event.target.closest('a[href^="#/"]')) routeChanged();
  });
  window.OmniEvents?.addEventListener('route-changed', routeChanged);
  let cleaned=false;
  const cleanup = () => {
    if(cleaned)return;cleaned=true;
    window.OmniEvents?.removeEventListener('route-changed', routeChanged);
    if (attention?.parentNode === dialog) (attentionParent?.isConnected ? attentionParent : document.body).append(attention);
    dialog.remove();
    if (activeDialog === dialog) activeDialog = null;
    if (restoreFocus && !dialog.dataset.replaced && trigger?.isConnected && !trigger.hidden) trigger.focus({ preventScroll: true });
    onClose();
  };
  dialog.addEventListener('close', cleanup, { once: true });
  // Explicit disposal must return the Director node before a route/manifest
  // removes this modal's parent. The browser's close event is asynchronous.
  const closeNative=dialog.close.bind(dialog);
  dialog.close=(...args)=>{closeNative(...args);cleanup();};
  activeDialog = dialog;
  dialog.showModal();
  close.focus({ preventScroll: true });
  return dialog;
}

export function widgetDetail(payload) {
  const content = deckNode('div', 'rcd-widget-detail-content');
  content.append(deckNode('p', 'rcd-detail-value', payload.display.headline));
  if (payload.display.secondary) content.append(deckNode('p', '', payload.display.secondary));
  payload.detail.lines.forEach(line => content.append(deckNode('p', '', line)));
  if (payload.detail.inventory.length) {
    const table = deckNode('table', 'rcd-manifest');
    const caption = deckNode('caption', '', 'Observed ship cargo');
    table.append(caption);
    const tbody = deckNode('tbody');
    payload.detail.inventory.forEach(item => {
      const row = deckNode('tr');
      row.append(deckNode('th', '', `${item.name}${item.mission ? ' · mission cargo' : ''}${item.stolen ? ' · stolen' : ''}`), deckNode('td', '', `${item.count} t`));
      tbody.append(row);
    });
    table.append(tbody); content.append(table);
  }
  if (payload.display.state === 'stale' && payload.observation.observed_at) {
    content.append(deckNode('p', 'rcd-reading-age', `Last recorded ${new Date(payload.observation.observed_at).toLocaleString()}. Reconnect Elite for an updated reading.`));
  }
  return content;
}

export function createWidgetDeck({ instances, getSnapshot, subscribe, detailContent, renderDetail, onDetail, context = 'Command deck', onPage = () => {}, initialPage = 0 }) {
  const manifest = validateManifest(instances);
  const root = deckNode('section', 'rcd-deck');
  root.setAttribute('aria-label', context);
  const grid = deckNode('div', 'rcd-deck-grid');
  const pager = deckNode('nav', 'rcd-deck-pager');
  pager.setAttribute('aria-label', `${context} pages`);
  const previous = deckNode('button', 'rcd-button', '← Previous');
  const next = deckNode('button', 'rcd-button', 'Next →');
  previous.type = next.type = 'button';
  const status = deckNode('span', 'rcd-page-status');
  status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  pager.append(previous, status, next); root.append(grid, pager);
  let page = initialPage, layout = null, disposed = false, frame = null, dialog = null, dialogSubject = null, dialogInstanceId = null;
  const cards = new Map();
  let lastSnapshot = getSnapshot();
  const updateCard = (card, payload) => {
    card.title.textContent = payload.display.label;
    card.answer.textContent = payload.display.headline;
    card.secondary.textContent = payload.display.secondary || '';
    card.facts.replaceChildren(...(payload.display.facts || []).map(fact => deckNode('span', '', fact)));
    card.facts.hidden = !payload.display.facts?.length;
    card.button.dataset.state = payload.display.state;
    card.button.dataset.emphasis = payload.display.emphasis;
    card.button.setAttribute('aria-label', `${payload.display.label}: ${payload.display.headline}. ${payload.display.secondary || ''}. Open details`);
    card.progress.hidden = !payload.detail.progress;
    if (payload.detail.progress) {
      card.progress.value = payload.detail.progress.value;
      card.progress.setAttribute('aria-label', `${payload.display.label}: ${payload.detail.progress.text}`);
    }
  };
  manifest.forEach(instance => {
    const button = deckNode('button', 'rcd-widget');
    button.type = 'button'; button.dataset.widgetId = instance.widgetId; button.dataset.instanceId = instance.instanceId;
    const title = deckNode('span', 'rcd-widget-title');
    const answer = deckNode('span', 'rcd-widget-answer');
    const secondary = deckNode('span', 'rcd-widget-secondary');
    const facts = deckNode('span', 'rcd-widget-facts');
    const progress = deckNode('progress', 'rcd-widget-progress'); progress.max = 100;
    const hint = deckNode('span', 'rcd-widget-hint', 'Details ↗'); hint.setAttribute('aria-hidden','true');
    button.append(title, answer, secondary, facts, progress, hint);
    button.hidden = true;
    grid.append(button);
    button.addEventListener('click', () => {
      const payload = selectWidget(instance.widgetId, getSnapshot());
      const content = renderDetail?.(instance, payload) || widgetDetail(payload);
      const extra = detailContent?.(instance, payload);
      if (extra) content.append(extra);
      const opened = openDeckDetail({ title: payload.display.label, content, trigger: button, onClose: () => {
        if(dialog===opened){dialog=null;dialogInstanceId=null;}
      } });
      dialog=opened;
      dialogSubject = subjectKey(payload.subject);
      dialogInstanceId = instance.instanceId;
      onDetail?.(instance, dialog);
    });
    cards.set(instance.instanceId, { button,title,answer,secondary,facts,progress });
  });
  const render = (moveFocus = false) => {
    if (disposed || !layout) return;
    page = Math.max(0, Math.min(page, layout.pages.length-1));
    const focused = document.activeElement?.dataset?.instanceId;
    const placements = layout.pages[page];
    // Reuse the actual buttons so source updates and resizing keep focus.
    const visible = new Set(placements.map(p => p.instanceId));
    for (const [id, card] of cards) card.button.hidden = !visible.has(id);
    grid.style.gridTemplateColumns = `repeat(${layout.columns}, minmax(0,1fr))`;
    grid.style.gridTemplateRows = `repeat(${layout.rows}, minmax(150px,1fr))`;
    for (const placement of placements) {
      const card = cards.get(placement.instanceId);
      card.button.hidden = false;
      card.button.dataset.size = placement.size;
      card.button.style.gridColumn = `${placement.column} / span ${placement.spanX}`;
      card.button.style.gridRow = `${placement.row} / span ${placement.spanY}`;
      if (!card.button.isConnected) grid.append(card.button);
    }
    // Every instance stays in the DOM and can be enumerated by visible pages.
    for (const card of cards.values()) if (!card.button.isConnected) grid.append(card.button);
    previous.disabled = page === 0; next.disabled = page === layout.pages.length-1;
    status.textContent = `Page ${page+1} of ${layout.pages.length}`;
    root.dataset.page = String(page+1); root.dataset.pages = String(layout.pages.length);
    root.dataset.accessibilityScroll = String(layout.exception);
    onPage(page);
    if (moveFocus) cards.get(placements[0]?.instanceId)?.button.focus({preventScroll:true});
    else if (focused && cards.get(focused)?.button.hidden) cards.get(placements[0]?.instanceId)?.button.focus({preventScroll:true});
  };
  const measure = () => {
    frame = null;
    if (disposed || !root.isConnected) return;
    const { width,height } = grid.getBoundingClientRect();
    if (!width || !height) return;
    const focusedId = dialog?.open ? dialogInstanceId : document.activeElement?.dataset?.instanceId;
    layout = packDeck(manifest, { width,height,gap:8 }, widgetRegistry);
    if (focusedId) {
      const found = layout.pages.findIndex(p => p.some(i => i.instanceId === focusedId));
      if (found >= 0) page = found;
    }
    render();
  };
  const schedule = () => { if (!disposed && frame === null) frame = requestAnimationFrame(measure); };
  const update = () => {
    lastSnapshot = getSnapshot();
    if (dialog && subjectKey(lastSnapshot.subject) !== dialogSubject) dialog.close();
    for (const instance of manifest) updateCard(cards.get(instance.instanceId), selectWidget(instance.widgetId, lastSnapshot));
  };
  previous.addEventListener('click', () => { page--; render(true); });
  next.addEventListener('click', () => { page++; render(true); });
  // Optional swipe supplements the labelled page buttons; never a sole input.
  let start = null;
  grid.addEventListener('pointerdown', e => { if (e.pointerType === 'touch') start = {x:e.clientX,y:e.clientY}; });
  grid.addEventListener('pointerup', e => {
    if (!start) return;
    const dx=e.clientX-start.x,dy=e.clientY-start.y; start=null;
    if (Math.abs(dx)>80 && Math.abs(dx)>Math.abs(dy)*2 && layout) {
      page = Math.max(0,Math.min(layout.pages.length-1,page+(dx<0?1:-1))); render();
    }
  });
  const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(schedule) : null;
  observer?.observe(grid);
  const unsubscribe = subscribe?.(update) || (() => {});
  update(); schedule();
  return { root, refresh: update, measure, dispose() {
    disposed = true; observer?.disconnect(); unsubscribe();
    if (frame !== null) cancelAnimationFrame(frame);
    dialog?.close();
  }, get page() { return page; } };
}
