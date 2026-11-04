// Material Trader perspective: browse the trader's materials against observed
// stock, quote exact exchanges, build a simulated basket, and follow the
// backend planner's recommendations for planned builds. Nothing here trades in
// the game or changes observed inventory; reserved stock is never offered.
import { buildTraderIndex, lot, quote, simulate, REASON_TEXT } from '../view-models/material-trader.js';

const node = (tag, cls = '', text) => {
  const element = document.createElement(tag);
  element.className = cls;
  if (text != null) element.textContent = String(text);
  return element;
};
const button = (text, onClick, cls = 'materials-build-link') => {
  const b = node('button', cls, text);
  b.type = 'button';
  b.addEventListener('click', onClick);
  return b;
};
const known = Number.isFinite;
const qty = (value) => (known(value) ? String(value) : 'Unknown');
const TYPES = [['raw', 'Raw'], ['manufactured', 'Manufactured'], ['encoded', 'Encoded']];
const REMAINING_REASON = {
  not_tradeable: 'not tradeable at a Material Trader',
  no_unreserved_source: 'no spare stock can be traded for it',
  destination_full: 'storage is full',
};
const CHECK_TEXT = { matches: 'matches the reference rate', differs: 'differs from the reference rate', not_covered: 'not a standard trader exchange' };

export function createMaterialTrader({ progression, buildId, state, onBuild, onRequirements }) {
  const trader = progression.material_trader;
  const index = buildTraderIndex(trader);
  const builds = progression.builds || [];
  const t = (state.trader ||= { type: 'raw', search: '', filter: 'all', take: null, give: null, pick: 'take', mode: 'receive', amount: 1, basket: [] });
  const root = node('section', 'materials-trader');
  root.setAttribute('aria-label', 'Material Trader');

  if (!index.available) {
    root.append(
      node('h3', '', 'Material Trader not included in this build'),
      node('p', 'materials-muted', trader?.reason === 'invalid'
        ? 'The built-in Material Trader rules could not be loaded.'
        : 'This build does not ship the Material Trader rules. Inventory, Requirements and Acquisition still work.'),
    );
    return root;
  }

  const owned = index.known ? Object.fromEntries([...index.materials.values()].map((m) => [m.id, m.owned])) : null;
  const reserved = index.known ? Object.fromEntries([...index.materials.values()].map((m) => [m.id, m.reserved])) : {};
  const scopeKey = buildId === 'all' ? 'all' : buildId;
  const plan = trader.plans?.[scopeKey] || null;
  const shortages = new Map();
  (buildId === 'all' ? builds : builds.filter((b) => b.build_plan_id === buildId)).forEach((build) => (build.materials || []).forEach((row) => {
    if (known(row.deficit) && row.deficit > 0) shortages.set(row.material_id, (shortages.get(row.material_id) || 0) + row.deficit);
  }));
  if (t.take && !index.materials.has(t.take)) t.take = null;
  if (t.give && !index.materials.has(t.give)) t.give = null;

  // --- toolbar ---------------------------------------------------------------
  const toolbar = node('div', 'trader-toolbar');
  const types = node('div', 'trader-types');
  types.setAttribute('role', 'radiogroup');
  types.setAttribute('aria-label', 'Trader');
  TYPES.forEach(([id, label]) => {
    const b = button(label, () => { t.type = id; t.take = null; t.give = null; render(); }, 'trader-type');
    b.dataset.traderType = id;
    b.setAttribute('role', 'radio');
    b.setAttribute('aria-checked', String(t.type === id));
    types.append(b);
  });
  const search = node('input');
  search.type = 'search'; search.name = 'trader_search'; search.value = t.search; search.placeholder = 'Material name…';
  search.setAttribute('aria-label', 'Search materials');
  const filter = node('select');
  filter.name = 'trader_filter'; filter.setAttribute('aria-label', 'Show');
  [['all', 'All materials'], ['spare', 'Spare stock to trade'], ['short', 'Short for builds'], ['owned', 'Held']].forEach(([v, label]) => {
    const option = node('option', '', label); option.value = v; option.selected = t.filter === v; filter.append(option);
  });
  const searchLabel = node('label', 'materials-control'); searchLabel.append(node('span', '', 'Search'), search);
  const filterLabel = node('label', 'materials-control'); filterLabel.append(node('span', '', 'Show'), filter);
  toolbar.append(types, searchLabel, filterLabel);
  search.addEventListener('input', () => { t.search = search.value; renderGrid(); });
  filter.addEventListener('change', () => { t.filter = filter.value; renderGrid(); });

  const main = node('div', 'trader-main');
  const grid = node('div', 'trader-grid');
  grid.setAttribute('aria-label', 'Materials');
  const panel = node('div', 'trader-panel');
  main.append(grid, panel);
  root.append(toolbar);
  if (!index.known) root.append(node('p', 'materials-requirement-warning', 'Stock is unknown (no complete Journal Materials baseline), so exchanges show their rates but nothing is called affordable.'));
  root.append(main);

  // --- grid --------------------------------------------------------------------
  function matches(material) {
    const needle = t.search.trim().toLowerCase();
    if (needle && !material.name.toLowerCase().includes(needle) && !material.group_name.toLowerCase().includes(needle)) return false;
    if (t.filter === 'spare') return known(material.available) && material.available > 0;
    if (t.filter === 'short') return shortages.has(material.id);
    if (t.filter === 'owned') return known(material.owned) && material.owned > 0;
    return true;
  }
  function cell(material) {
    const b = button('', () => pick(material.id), 'trader-cell');
    b.dataset.materialId = material.id;
    b.dataset.grade = String(material.grade);
    const role = material.id === t.take ? 'receive' : material.id === t.give ? 'give' : '';
    if (role) b.dataset.selected = role;
    b.setAttribute('aria-pressed', String(Boolean(role)));
    b.append(node('span', 'trader-cell-grade', `G${material.grade}`), node('strong', '', material.name));
    const stock = node('span', 'trader-cell-stock', index.known ? `${material.owned}/${material.cap}` : `?/${material.cap}`);
    b.append(stock);
    const notes = [];
    if (index.known && material.reserved) notes.push(`${material.reserved} reserved`);
    if (index.known && material.available) notes.push(`${material.available} spare`);
    if (shortages.has(material.id)) notes.push(`short ${shortages.get(material.id)}`);
    if (notes.length) b.append(node('span', 'trader-cell-note', notes.join(' · ')));
    if (shortages.has(material.id)) b.classList.add('trader-cell--short');
    b.setAttribute('aria-label', `${material.name}, grade ${material.grade}, ${index.known ? `${material.owned} held of ${material.cap}` : 'stock unknown'}${notes.length ? `, ${notes.join(', ')}` : ''}`);
    return b;
  }
  function renderGrid() {
    grid.replaceChildren();
    const groups = index.groups.filter((g) => g.type === t.type);
    let shown = 0;
    groups.forEach((group) => {
      const members = group.materials.map((id) => index.materials.get(id));
      const visible = members.filter(matches);
      if (!visible.length) return;
      const row = node('div', 'trader-group');
      row.dataset.group = group.id;
      row.append(node('span', 'trader-group-name', group.name));
      const cells = node('div', 'trader-group-cells');
      members.forEach((m) => cells.append(visible.includes(m) ? cell(m) : node('span', 'trader-cell trader-cell--empty')));
      row.append(cells);
      grid.append(row);
      shown += visible.length;
    });
    if (!shown) grid.append(node('p', 'materials-empty', 'No material matches. Clear the search or change what is shown.'));
  }
  grid.addEventListener('keydown', (event) => {
    if (!event.target.matches('button.trader-cell') || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
    const rows = [...grid.querySelectorAll('.trader-group')].map((r) => [...r.querySelectorAll('.trader-cell')]);
    const r = rows.findIndex((cells) => cells.includes(event.target));
    const c = rows[r].indexOf(event.target);
    const at = (rr, cc) => rows[rr]?.[cc]?.matches?.('button') ? rows[rr][cc] : null;
    let next = null;
    if (event.key === 'ArrowRight') for (let x = c + 1; x < rows[r].length && !next; x += 1) next = at(r, x);
    if (event.key === 'ArrowLeft') for (let x = c - 1; x >= 0 && !next; x -= 1) next = at(r, x);
    if (event.key === 'ArrowDown') for (let y = r + 1; y < rows.length && !next; y += 1) next = at(y, Math.min(c, rows[y].length - 1));
    if (event.key === 'ArrowUp') for (let y = r - 1; y >= 0 && !next; y -= 1) next = at(y, Math.min(c, rows[y].length - 1));
    if (event.key === 'Home') next = grid.querySelector('button.trader-cell');
    if (event.key === 'End') next = [...grid.querySelectorAll('button.trader-cell')].pop();
    if (next) { event.preventDefault(); next.focus(); }
  });

  function pick(id) {
    if (t.pick === 'give') { t.give = id; t.pick = 'take'; } else { t.take = id; if (t.give === id || (t.give && !lot(index, t.give, id))) t.give = null; }
    renderGrid(); renderPanel();
    // In a narrow window the calculator sits below the grid: bring it into view.
    if (window.matchMedia?.('(max-width: 760px)').matches) {
      panel.querySelector('.trader-calc')?.scrollIntoView?.({ block: 'start' });
      panel.querySelector('[name=trader_give]')?.focus({ preventScroll: true });
      return;
    }
    grid.querySelector(`[data-material-id="${CSS.escape(id)}"]`)?.focus({ preventScroll: true });
  }

  // --- calculator, basket, plan ---------------------------------------------------
  function giveOptions(take) {
    const target = index.materials.get(take);
    return [...index.materials.values()].filter((m) => m.type === target.type && m.id !== take).map((m) => {
      const [pay, get] = lot(index, m.id, take);
      const loss = (6 ** (m.grade - 1) * pay) / get - 6 ** (target.grade - 1);
      const affordable = index.known ? Math.floor((m.available || 0) / pay) * get : null;
      return { m, pay, get, loss, affordable };
    }).sort((a, b) => ((b.affordable > 0) - (a.affordable > 0)) || a.loss - b.loss || a.m.name.localeCompare(b.m.name));
  }

  function calculator() {
    const box = node('section', 'trader-calc');
    box.append(node('h3', '', 'Exchange'));
    const pickRow = node('div', 'trader-pick');
    pickRow.append(node('span', 'materials-muted', 'Grid selects:'));
    [['take', 'Material to receive'], ['give', 'Material to give']].forEach(([id, label]) => {
      const b = button(label, () => { t.pick = id; renderPanel(); }, 'trader-pick-mode');
      b.setAttribute('aria-pressed', String(t.pick === id));
      pickRow.append(b);
    });
    box.append(pickRow);
    if (!t.take) {
      box.append(node('p', 'materials-muted', 'Choose a material to receive from the grid.'));
      return box;
    }
    const target = index.materials.get(t.take);
    const options = giveOptions(t.take);
    if (!t.give || !options.some((o) => o.m.id === t.give)) t.give = options[0]?.m.id || null;
    const receiveLine = node('p', 'trader-receive');
    receiveLine.append(node('strong', '', target.name), node('span', 'materials-muted', ` G${target.grade} · ${target.group_name} · ${index.known ? `${target.owned} of ${target.cap} held` : `cap ${target.cap}`}`));
    box.append(receiveLine);
    const giveSelect = node('select');
    giveSelect.name = 'trader_give'; giveSelect.setAttribute('aria-label', 'Material to give');
    options.forEach((o) => {
      const option = node('option', '', `${o.m.name} · G${o.m.grade} · ${o.pay}:${o.get}${index.known ? ` · ${o.m.available} spare` : ''}`);
      option.value = o.m.id; option.selected = o.m.id === t.give; giveSelect.append(option);
    });
    giveSelect.addEventListener('change', () => { t.give = giveSelect.value; renderPanel(); });
    const giveLabel = node('label', 'materials-control'); giveLabel.append(node('span', '', 'Give'), giveSelect);
    const modes = node('div', 'trader-modes');
    modes.setAttribute('role', 'radiogroup'); modes.setAttribute('aria-label', 'Amount is');
    [['receive', 'Receive'], ['spend', 'Spend']].forEach(([id, label]) => {
      const b = button(label, () => { t.mode = id; renderPanel(); }, 'trader-mode');
      b.setAttribute('role', 'radio'); b.setAttribute('aria-checked', String(t.mode === id));
      modes.append(b);
    });
    const amount = node('input');
    amount.type = 'number'; amount.min = '1'; amount.name = 'trader_amount'; amount.value = String(t.amount);
    amount.setAttribute('aria-label', t.mode === 'receive' ? 'Quantity to receive' : 'Quantity to spend');
    amount.addEventListener('input', () => { t.amount = Math.max(parseInt(amount.value, 10) || 0, 0); renderResult(); });
    const amountLabel = node('label', 'materials-control'); amountLabel.append(node('span', '', t.mode === 'receive' ? 'Receive' : 'Spend'), amount);
    const inputs = node('div', 'trader-inputs'); inputs.append(giveLabel, modes, amountLabel);
    box.append(inputs);
    const result = node('div', 'trader-result');
    result.setAttribute('aria-live', 'polite');
    box.append(result);
    function renderResult() {
      result.replaceChildren();
      if (!t.give) { result.append(node('p', 'materials-muted', 'No material in this trader can be given for it.')); return; }
      // Quote against the stock the basket leaves, so a trade can spend an earlier trade's output.
      const projected = t.basket.length && owned ? simulate(index, t.basket, owned, reserved).after || owned : owned;
      const q = quote(index, t.give, t.take, { [t.mode === 'receive' ? 'receive' : 'spend']: t.amount, owned: projected, protected: reserved });
      const source = index.materials.get(t.give);
      const facts = node('dl', 'trader-facts');
      const add = (term, value) => { const d = node('div'); d.append(node('dt', '', term), node('dd', '', value)); facts.append(d); };
      add('Rate', `${q.pay} ${source.name} for ${q.receive} ${target.name}`);
      add('Exchanges', String(q.lots));
      add('You give', `${q.payTotal} ${source.name}`);
      add('You receive', `${q.receiveTotal} ${target.name}`);
      if (q.possible !== null) {
        add('Most now', `${q.maxLots} exchange${q.maxLots === 1 ? '' : 's'} (${q.maxLots * q.receive} ${target.name})`);
        add(source.name, `${q.sourceBefore} → ${q.sourceAfter}`);
        add(target.name, `${q.targetBefore} → ${q.targetAfter} of ${q.targetCap}`);
      }
      result.append(facts);
      if (projected !== owned) result.append(node('p', 'materials-muted', `Balances include the ${t.basket.length} trade${t.basket.length === 1 ? '' : 's'} in your basket.`));
      result.dataset.possible = String(q.possible);
      result.append(node('p', q.possible ? 'materials-requirement-outcome' : 'materials-requirement-warning',
        q.possible ? 'This exchange is possible with your spare stock.' : (q.reasons || [q.reason]).map((r) => REASON_TEXT[r] || r).join(' ')));
      const addButton = button('Add to basket', () => { t.basket.push({ give: t.give, take: t.take, lots: q.lots }); renderPanel(); }, 'trader-submit');
      addButton.disabled = !(q.lots >= 1) || q.possible === false;
      result.append(addButton);
    }
    renderResult();
    return box;
  }

  function basket() {
    const box = node('section', 'trader-basket');
    box.append(node('h3', '', `Trade basket · ${t.basket.length}`));
    if (!t.basket.length) {
      box.append(node('p', 'materials-muted', 'Add exchanges to plan a sequence. Each one is checked against the stock the previous ones leave.'));
      return box;
    }
    const sim = simulate(index, t.basket, owned, reserved);
    const list = node('ol', 'trader-steps');
    t.basket.forEach((trade, i) => {
      const step = sim.steps[i];
      const give = index.materials.get(trade.give); const take = index.materials.get(trade.take);
      const pair = lot(index, trade.give, trade.take) || [0, 0];
      const li = node('li', 'trader-step');
      li.dataset.valid = String(step ? step.valid !== false : false);
      li.append(node('strong', '', `Give ${trade.lots * pair[0]} ${give?.name} → receive ${trade.lots * pair[1]} ${take?.name}`));
      if (!step) li.append(node('p', 'materials-muted', 'Not checked: an earlier step cannot be made.'));
      else if (step.possible === null) li.append(node('p', 'materials-muted', 'Stock unknown; not checked.'));
      else if (!step.valid) li.append(node('p', 'materials-requirement-warning', (step.reasons || [step.reason]).map((r) => REASON_TEXT[r] || r).join(' ')));
      else li.append(node('p', 'materials-muted', `${give.name} ${step.sourceBefore} → ${step.sourceAfter} · ${take.name} ${step.targetBefore} → ${step.targetAfter}`));
      li.append(button('Remove', () => { t.basket.splice(i, 1); renderPanel(); }, 'materials-build-link trader-remove'));
      list.append(li);
    });
    box.append(list);
    if (sim.known) {
      const totals = node('div', 'trader-totals');
      totals.append(node('strong', '', sim.valid ? 'After these trades' : 'After the valid steps'));
      Object.entries(sim.changes).sort((a, b) => a[1] - b[1]).forEach(([id, delta]) => {
        const m = index.materials.get(id);
        totals.append(node('p', 'materials-muted', `${m?.name || id}: ${owned[id] || 0} → ${(owned[id] || 0) + delta} (${delta > 0 ? '+' : ''}${delta})`));
      });
      box.append(totals);
    }
    box.append(button('Clear basket', () => { t.basket = []; renderPanel(); }, 'materials-build-link'));
    box.append(node('p', 'materials-muted', 'A plan only: nothing is traded in the game and your observed stock does not change.'));
    return box;
  }

  function recommendations() {
    const box = node('section', 'trader-plan');
    const scopeTitle = buildId === 'all' ? 'all active builds' : builds.find((b) => b.build_plan_id === buildId)?.title || 'this build';
    box.append(node('h3', '', `Recommended trades for ${scopeTitle}`));
    if (!builds.length) { box.append(node('p', 'materials-muted', 'Save a planned build in Outfitting to get trade recommendations.'), button('Open Outfitting', () => onBuild(null))); return box; }
    if (!index.known) { box.append(node('p', 'materials-muted', 'Recommendations need a complete Journal Materials baseline.')); return box; }
    if (!plan) { box.append(node('p', 'materials-muted', 'No plan for this selection.')); return box; }
    const summary = node('p', 'trader-plan-summary');
    summary.textContent = plan.shortage_before === 0 ? 'No material shortage to trade for.'
      : plan.trades.length ? `${plan.trades.length} trade${plan.trades.length === 1 ? ' covers' : 's cover'} ${plan.resolved_by_trades} of ${plan.shortage_before} missing`
        : 'No spare stock can be traded for these shortages.';
    box.append(summary);
    if (plan.trades.length) {
      const list = node('ol', 'trader-steps');
      plan.trades.forEach((trade) => {
        const li = node('li', 'trader-step');
        li.append(node('strong', '', `Give ${trade.pay_total} ${trade.give_name} → receive ${trade.receive_total} ${trade.take_name}`));
        li.append(node('p', 'materials-muted', `${trade.lots} × ${trade.pay}:${trade.receive} · ${trade.why}${trade.chain ? ' · part of a two-step route' : ''} · for ${trade.for_material_name} (${trade.for_build_title})`));
        li.append(node('p', 'materials-muted', `${trade.give_name} ${trade.source_before} → ${trade.source_after} · ${trade.take_name} ${trade.target_before} → ${trade.target_after}`));
        if (trade.alternatives?.length) {
          const alt = node('details', 'materials-proof');
          alt.append(node('summary', '', 'Other ways'));
          trade.alternatives.forEach((a) => alt.append(node('p', 'materials-muted', `${a.give_name}${a.via ? ` via ${a.via}` : ''}${a.rate ? ` at ${a.rate}` : ''} · ${a.why} · ${a.received} received`)));
          li.append(alt);
        }
        list.append(li);
      });
      box.append(list);
      // For one build, units beyond its own shortage went to builds with higher priority.
      const own = plan.builds[0]?.before || {};
      const received = {};
      plan.trades.forEach((trade) => { if (trade.take === trade.for_material) received[trade.take] = (received[trade.take] || 0) + trade.receive_total; });
      const absorbed = buildId !== 'all' && Object.entries(received).some(([id, n]) => n > (own[id] || 0));
      if (absorbed) {
        box.append(node('p', 'materials-muted', 'Builds with higher priority receive new units first, so some trades also cover their shortages.'));
      }
      box.append(button('Add these trades to the basket', () => {
        plan.trades.forEach((trade) => t.basket.push({ give: trade.give, take: trade.take, lots: trade.lots }));
        renderPanel();
      }, 'trader-submit'));
    }
    const remaining = node('div', 'trader-remaining');
    remaining.append(node('h4', '', plan.remaining.length ? 'Still to collect after these trades' : 'Nothing left to collect'));
    plan.remaining.forEach((row) => remaining.append(node('p', 'materials-muted', `${row.name}: ${row.collect} (${REMAINING_REASON[row.reason] || row.reason})`)));
    box.append(remaining);
    const why = node('details', 'materials-proof');
    why.append(node('summary', '', 'How trades are chosen'), node('p', 'materials-muted', plan.objective));
    box.append(why);
    if (onRequirements) box.append(button('See shortages in Requirements', () => onRequirements()));
    return box;
  }

  function journalTrades() {
    const seen = trader.observed_trades || [];
    const box = node('details', 'materials-proof trader-journal');
    box.append(node('summary', '', `Trades in your Journal · ${seen.length}`));
    if (!seen.length) box.append(node('p', 'materials-muted', 'No Material Trader exchanges recorded yet.'));
    seen.forEach((row) => box.append(node('p', 'materials-muted', `${row.observed_at.slice(0, 16).replace('T', ' ')} · ${row.paid} ${row.give_name} → ${row.received} ${row.take_name} · ${CHECK_TEXT[row.check] || row.check}`)));
    return box;
  }

  function about() {
    const box = node('details', 'materials-proof trader-about');
    box.append(node('summary', '', 'About these rules'));
    const ref = trader.reference || {};
    box.append(node('p', 'materials-muted', `Rules version ${trader.version}. ${ref.basis || ''}`));
    box.append(node('p', 'materials-muted', 'Up one grade: 6 for 1. Down one grade: 1 for 3. Another group: 6 for 1, combined with any grade change. Trades are whole exchanges and never cross raw, manufactured and encoded.'));
    (ref.sources || []).forEach((s) => box.append(node('p', 'materials-muted', `${s.name}: ${s.url}`)));
    if ((ref.discrepancies || []).length) {
      box.append(node('strong', '', 'Known differences between references'));
      ref.discrepancies.forEach((d) => box.append(node('p', 'materials-muted', d)));
    }
    return box;
  }

  function renderPanel() {
    panel.replaceChildren(calculator(), basket(), recommendations(), journalTrades(), about());
  }
  function render() {
    types.querySelectorAll('[data-trader-type]').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.traderType === t.type)));
    renderGrid(); renderPanel();
  }
  render();
  return root;
}
