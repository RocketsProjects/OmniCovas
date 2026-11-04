// Material acquisition intelligence (GKI-05). Renders the backend's shortage →
// method → place guidance inside the existing Materials workspace. ADR 0003:
// every value goes through textContent. No strategy is decided here.
import {
  STRATEGY_TONE, activityLine, evidenceText, hereText, servesText, shortText,
} from '../view-models/material-intelligence.js';

const node = (tag, cls = '', text) => {
  const element = document.createElement(tag);
  if (cls) element.className = cls;
  if (text != null) element.textContent = String(text);
  return element;
};

const button = (text, cls, onClick) => {
  const element = node('button', cls, text);
  element.type = 'button';
  element.addEventListener('click', onClick);
  return element;
};

function placeRow(place, material, method, handlers) {
  const item = node('li', 'mi-place');
  const label = [place.name, place.coordinates ? `(${place.coordinates})` : null].filter(Boolean).join(' ');
  item.append(node('span', 'mi-place-name', label));
  if (place.evidence === 'community_reference') item.append(node('span', 'mi-tag', 'Commander-reported'));
  if (place.evidence === 'community_corroborated') item.append(node('span', 'mi-tag', 'Reported by several sources'));
  if (place.system && handlers.onNavigate) {
    const go = button('Open in Navigation', 'mi-action', () => handlers.onNavigate(place, material, method));
    go.setAttribute('aria-label', `Open ${place.name} in Navigation`);
    item.append(go);
  }
  if (place.atlas && handlers.onAtlas) {
    const read = button('Read its history', 'mi-action mi-action--quiet', () => handlers.onAtlas(place, material));
    read.setAttribute('aria-label', `Read the history of ${place.name} in the Galactic Atlas`);
    item.append(read);
  }
  return item;
}

export function renderMethod(method, material, handlers = {}, open = false) {
  const details = node('details', 'mi-method');
  details.dataset.methodId = method.id;
  if (open) details.open = true;
  const summary = node('summary', 'mi-method-summary');
  summary.append(node('span', 'mi-method-name', method.name));
  if (method.serves?.length) summary.append(node('span', 'mi-tag mi-tag--serves', `+${method.serves.length} other shortage${method.serves.length === 1 ? '' : 's'}`));
  if (method.certainty === 'disputed') summary.append(node('span', 'mi-tag mi-tag--disputed', 'Sources disagree'));
  if (!method.plannable) summary.append(node('span', 'mi-tag', 'Not plannable'));
  details.append(summary);
  details.append(node('p', 'mi-method-lead', method.summary));
  if (method.note) details.append(node('p', 'mi-method-note', method.note));
  const here = hereText(method.here);
  if (here) {
    const line = node('p', `mi-method-here mi-here--${method.here.state}`, here);
    details.append(line);
  }
  const serves = servesText(method);
  if (serves) details.append(node('p', 'mi-method-serves', serves));
  if (method.equipment?.length) {
    details.append(node('p', 'mi-method-equipment', `Needs: ${method.equipment.map((e) => e.name).join(', ')}`));
  }
  if (method.steps?.length) {
    const steps = node('ol', 'mi-steps');
    method.steps.forEach((text) => steps.append(node('li', '', text)));
    details.append(steps);
  }
  if (method.places?.length) {
    const places = node('ul', 'mi-places');
    places.setAttribute('aria-label', `Documented places for ${method.name}`);
    method.places.forEach((place) => places.append(placeRow(place, material, method, handlers)));
    details.append(places);
  }
  const claims = (method.claims || []).map((c) => c.text);
  if (claims.length) {
    const facts = node('ul', 'mi-claims');
    claims.forEach((text) => facts.append(node('li', '', text)));
    details.append(facts);
  }
  const evidence = [...new Set((method.claims || []).map((c) => evidenceText(c.evidence)))];
  details.append(node('p', 'mi-provenance', `${evidence.join(' · ') || 'Community reference'} · ${method.sources?.length || 0} cited source${method.sources?.length === 1 ? '' : 's'}`));
  return details;
}

/* The per-material strategy shown in the Acquisition inspector. The trades
   themselves stay in the inspector's Trading section, which is the Material
   Trader's own plan; this states the decision and the ways to collect. */
export function createStrategy(material, handlers = {}, ranking = '') {
  const section = node('section', 'mi-strategy');
  section.setAttribute('aria-label', `How to get ${material.name}`);
  section.append(node('h4', '', 'How to get it'));
  const verdict = node('div', `mi-verdict mi-verdict--${STRATEGY_TONE[material.recommendation.strategy] || 'unknown'}`);
  verdict.append(node('strong', '', material.recommendation.headline), node('span', 'mi-verdict-short', shortText(material)));
  section.append(verdict);
  const reasons = node('ul', 'mi-reasons');
  material.recommendation.reasons.forEach((text) => reasons.append(node('li', '', text)));
  section.append(reasons);
  if (['trade', 'trade_then_collect'].includes(material.recommendation.strategy)) {
    section.append(node('p', 'mi-muted', `The trades at a ${material.trade?.trader || 'Material Trader'} are listed under Trading, below.`));
  }

  const collect = node('div', 'mi-collect');
  collect.append(node('h5', '', material.methods.length ? `Collect · ${material.methods.length} documented method${material.methods.length === 1 ? '' : 's'}` : 'Collect'));
  if (!material.methods.length) collect.append(node('p', 'mi-muted', 'No documented source for this material.'));
  material.methods.forEach((method, index) => collect.append(renderMethod(method, material, handlers, index === 0 && method.plannable)));
  if (ranking) collect.append(node('p', 'mi-muted mi-ranking', ranking));
  section.append(collect);
  return section;
}

/* Activities that serve the most of the commander's current shortages. */
export function createActivitySummary(intel, { onMaterial, limit = 5 } = {}) {
  if (!intel) return null;
  const section = node('section', 'mi-activities');
  section.setAttribute('aria-labelledby', 'mi-activities-title');
  const heading = node('h3', 'mi-activities-title', 'Best activities for these shortages');
  heading.id = 'mi-activities-title';
  section.append(heading);
  if (intel.state === 'knowledge_unavailable') {
    section.append(node('p', 'mi-muted', 'Acquisition knowledge is not available in this build, so only shortages and trades are shown.'));
    return section;
  }
  if (intel.state === 'no_shortages') {
    section.append(node('p', 'mi-muted', 'Nothing is short for these builds.'));
    return section;
  }
  const plannable = (intel.activities || []).filter((a) => a.plannable).slice(0, limit);
  const list = node('ol', 'mi-activity-list');
  plannable.forEach((activity) => {
    const item = node('li', 'mi-activity');
    item.dataset.activityId = activity.id;
    item.append(node('strong', 'mi-activity-name', activity.name));
    item.append(node('span', 'mi-activity-count', `${activity.materials.length} shortage${activity.materials.length === 1 ? '' : 's'}`));
    const materials = node('p', 'mi-activity-materials');
    activity.materials.forEach((m, index) => {
      if (index) materials.append(document.createTextNode(' · '));
      const pick = button(m.short == null ? m.name : `${m.name} (${m.short})`, 'mi-link', () => onMaterial?.(m.material_id));
      materials.append(pick);
    });
    item.append(materials);
    const extras = [];
    if (activity.equipment?.length) extras.push(`Needs ${activity.equipment.map((e) => e.name).join(', ')}`);
    const possible = activity.materials.filter((m) => m.here?.state === 'possible');
    if (possible.length) extras.push(`${possible.length} possible in ${possible[0].here.system}`);
    if (activity.places?.length) extras.push(`${activity.places.length} documented place${activity.places.length === 1 ? '' : 's'}`);
    if (extras.length) item.append(node('p', 'mi-muted', extras.join(' · ')));
    item.setAttribute('aria-label', `${activity.name}: ${activityLine(activity)}`);
    list.append(item);
  });
  section.append(list);
  section.append(node('p', 'mi-muted mi-ranking', intel.ranking));
  return section;
}

/* Any material's documented sources, for the inventory inspector. */
export function createGuide(guide, handlers = {}) {
  const section = node('section', 'mi-guide');
  section.setAttribute('aria-label', 'How to get it');
  section.append(node('h4', '', 'How to get it'));
  if (!guide || guide.state === 'knowledge_unavailable') {
    section.append(node('p', 'mi-muted', 'Acquisition knowledge is not available in this build.'));
    return section;
  }
  if (!guide.methods.length) {
    section.append(node('p', 'mi-muted', 'No documented source for this material.'));
  }
  guide.methods.forEach((method, index) => section.append(renderMethod(method, { ...guide.material }, handlers, index === 0 && method.plannable)));
  section.append(node('p', 'mi-muted', `Also exchangeable at a ${guide.trader}.`));
  if (guide.ranking) section.append(node('p', 'mi-muted mi-ranking', guide.ranking));
  return section;
}
