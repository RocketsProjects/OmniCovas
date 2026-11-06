import { deckNode as node } from './widget-host.js';

// This edits the existing structured objective, not a second tracking owner.
// Only the ore is required. An existing authored note is preserved verbatim.
export function createMiningTracking({ record, available, pending, observed = [], capacity = null, busy = false, onSave, onAction, onCancel }) {
  const panel = node('section', 'rcd-mining-tracking');
  if (pending || !available) {
    panel.append(node('p', '', pending ? 'Reading your saved ore selection…' : 'Your saved selection is unavailable. Reconnect before changing it.'));
    return panel;
  }
  const form = node('form', 'rcd-tracking-form');
  form.dataset.miningTrackingForm = '';
  const label = node('label', '', 'Ore to track');
  const ore = node('input'); ore.id = 'mining-tracking-ore'; ore.type = 'text';
  ore.required = true; ore.maxLength = 64; ore.autocomplete = 'off'; ore.value = record?.target_commodity || '';
  ore.dataset.objectiveTargetCommodity = 'mining'; label.htmlFor = ore.id;
  form.append(label, ore, node('p', '', 'Prospector reports check for this ore. You do not need a quantity goal.'));
  const status = node('p', 'rcd-tracking-status'); status.setAttribute('role', 'status');
  const optional = node('details', 'rcd-tracking-goal');
  optional.open = record?.target_quantity > 0;
  optional.append(node('summary', '', 'Quantity goal (optional)'));
  const quantityLabel = node('label', '', 'Tonnes to have aboard');
  const quantity = node('input'); quantity.id = 'mining-tracking-tonnes'; quantity.type = 'number';
  quantity.min = '1'; quantity.max = '100000'; quantity.step = '1'; quantity.placeholder = 'No quantity goal';
  quantity.value = record?.target_quantity ?? ''; quantity.dataset.objectiveTargetQuantity = 'mining'; quantityLabel.htmlFor = quantity.id;
  const remove = node('button', 'rcd-button', 'No quantity goal'); remove.type = 'button';
  remove.addEventListener('click', () => { quantity.value = ''; optional.open = false; });
  optional.append(quantityLabel, quantity, remove, node('p', '', 'This compares sellable ore in your hold with your goal. It does not count cargo already sold.'));
  const limit = node('p', 'rcd-tracking-status');
  const explainLimit = () => { limit.textContent = Number.isFinite(capacity) && capacity > 0 && Number(quantity.value) > capacity
    ? `This exceeds your last recorded ${capacity.toLocaleString()} t hold. The goal counts ore aboard, not the total across multiple trips.` : ''; };
  quantity.addEventListener('input', explainLimit); remove.addEventListener('click', explainLimit); explainLimit(); optional.append(limit);
  const actions = node('div', 'rcd-task-actions');
  const save = node('button', 'rcd-button rcd-button-primary', record ? 'Review tracking change' : 'Track ore'); save.type = 'submit';
  const cancel = node('button', 'rcd-button', 'Cancel'); cancel.type = 'button'; cancel.addEventListener('click', onCancel);
  actions.append(save, cancel); form.append(optional, status, actions);
  const commit = async (commodity, tonnes) => {
    if (busy) return;
    if (!commodity || (tonnes !== null && (!Number.isInteger(tonnes) || tonnes < 1 || tonnes > 100000))) {
      status.textContent = 'Choose an ore. An optional goal must be a whole number from 1 to 100,000 tonnes.'; return;
    }
    busy = true;
    panel.querySelectorAll('button,input').forEach(control => { control.disabled = true; });
    try { await onSave({ commodity, quantity: tonnes, text: record?.text || `Mine ${commodity}` }); }
    catch (error) { status.textContent = error.message || 'Your selection was not saved. Try again.'; }
    finally { busy = false; panel.querySelectorAll('button,input').forEach(control => { control.disabled = false; }); }
  };
  form.addEventListener('submit', event => {
    event.preventDefault();
    if (!form.checkValidity()) { form.reportValidity(); return; }
    commit(ore.value.trim(), quantity.value.trim() ? Number(quantity.value) : null);
  });
  // Names are choices, never observations fabricated from a catalogue. One tap
  // on a reported mineral can enable tracking without copying or typing it.
  const names = [...new Set(observed.filter(Boolean))].slice(0, 8);
  if (names.length) {
    const choices = node('section', 'rcd-tracking-choices');
    choices.append(node('h3', '', 'From your recent readings'));
    const buttons = node('div', 'rcd-task-actions');
    for (const name of names) {
      const choose = node('button', 'rcd-button', `Track ${name}`); choose.type = 'button';
      choose.addEventListener('click', () => commit(name, record?.target_quantity ?? null)); buttons.append(choose);
    }
    choices.append(buttons); panel.append(choices);
  }
  panel.append(form);
  if (record) {
    const saved = node('details', 'rcd-saved-mining-plan');
    saved.append(node('summary', '', 'Saved plan'));
    saved.append(node('p', '', record.text));
    if (record.state === 'completed') saved.append(node('p', '', 'Marked complete. Choose a new ore to resume tracking.'));
    const lifecycle = node('div', 'rcd-task-actions');
    for (const [action, title] of [['complete', 'Mark plan complete'], ['clear', 'Clear saved plan']]) {
      if (action === 'complete' && record.state === 'completed') continue;
      const button = node('button', 'rcd-button', title); button.type = 'button'; button.dataset.objectiveAction = action;
      button.addEventListener('click', () => onAction(action)); lifecycle.append(button);
    }
    saved.append(lifecycle); panel.append(saved);
  }
  return panel;
}
