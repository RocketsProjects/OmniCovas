// Dashboard iteration 1: one shared Shell snapshot, no new transport or facts.
import { deckNode as node, openDeckDetail } from './widget-host.js';
import { selectWidget, subjectKey } from '../view-models/widget-snapshot.js';
import { deriveLocalContext } from '../view-models/local-context.js';
import { deriveCommanderLocationState } from '../view-models/commander-context.js';
import { normalizeShipName } from './command-primitives.js';
import { createCommanderCredential, createCommanderProfile } from './commander-identity.js';
import { createShipReadiness, readinessDetail } from './ship-readiness.js';
import { createGalaxyToday } from './galaxy-today.js';

const text = value => typeof value === 'string' && value.trim() ? value.trim() : null;
const sameSystem = (a,b) => text(a) && text(b) && a.trim().toLowerCase() === b.trim().toLowerCase();

export function commanderHomeModel(snapshot = {}) {
  const publicState = snapshot.publicState || {};
  const coherent = Boolean(snapshot.subject?.commander_profile_key && snapshot.factSubject
    && subjectKey(snapshot.subject) === subjectKey(snapshot.factSubject));
  const ship = coherent ? snapshot.shipState || {} : {};
  const raw = coherent ? snapshot.localContextRaw || {} : {};
  const nav = coherent ? snapshot.navSnap?.active_route : null;
  const session = coherent && snapshot.connected && snapshot.sessionState === 'Active';
  const local = deriveLocalContext(raw);
  const location = deriveCommanderLocationState(local,ship,coherent ? snapshot.navSnap : null,
    {sessionState:session ? 'Active' : 'Last known'});
  const cargo = selectWidget('ship.cargo',snapshot);
  const shipType = normalizeShipName(ship.ship_type || publicState.current_ship_type).display;
  const name = text(publicState.commander_name) || 'Commander unknown';
  const shipName = text(ship.ship_name) || text(publicState.current_ship_name) || shipType || 'Ship not recorded';
  const isRoute = text(nav?.destination) && nav?.route_state === 'active';
  const routeStale = !session || !['live_now','fresh','commander_observed'].includes(nav?.freshness_label);
  return {snapshot,raw,local,ship,name,shipName,shipType,location,cargo,session,
    qualifier: !snapshot.connected ? 'Offline · last known' : session ? 'In game' : coherent ? 'Last known' : 'Waiting for game data',
    route:isRoute ? nav : null,routeStale,
  };
}

function fact(parent,label,value) {
  if (value === null || value === undefined || value === '') return;
  const row=node('div','home-fact');
  row.append(node('dt','',label),node('dd','',value));parent.append(row);
}
function reading(model) {
  const content=node('div','home-detail');
  content.append(node('p','home-reading',`Reading captured when opened · ${model.qualifier}`));
  return content;
}
function locationDetail(model) {
  const content=reading(model), facts=node('dl','home-facts');
  fact(facts,'System',model.location.systemName || 'Not recorded');
  fact(facts,'Station',model.location.stationName);
  fact(facts,'Flight state',model.location.flightValue);
  const system=model.raw.system_context;
  if (sameSystem(system?.star_system,model.location.systemName)) {
    for (const [key,label] of [['system_economy','Economy'],['system_government','Government'],['system_security','Security'],['population','Population']])
      if(system[key]!==null && system[key]!==undefined) fact(facts,label,model.local.systemBrief?.facts?.find(row=>row.label===label)?.value);
    fact(facts,'System recorded at',system.event_timestamp);
  }
  const station=model.raw.station_context;
  if(model.location.stationName && sameSystem(station?.star_system,model.location.systemName)
    && station.station_name === model.location.stationName) {
    fact(facts,'Station type',station.station_type ? model.local.stationBrief?.stationType : null);
    const services=model.local.stationServices?.services;
    fact(facts,'Services',services?.length ? services.map(service=>service.label).join(', ') : null);
    fact(facts,'Station recorded at',station.event_timestamp);
  }
  content.append(facts);return content;
}
function routeDetail(model) {
  const content=reading(model), facts=node('dl','home-facts'), route=model.route;
  fact(facts,'Route reading',model.routeStale ? 'Last known route · check in Elite' : 'Recorded route');
  fact(facts,'Destination',route.destination);fact(facts,'Next hop',route.next_hop);
  fact(facts,'Jumps in recorded route',route.total_hops);fact(facts,'Recorded at',route.observed_at);
  content.append(facts);
  if(Array.isArray(route.hops) && route.hops.length) {
    content.append(node('h3','','Recorded route'));
    const list=node('ol','home-route-hops');
    for(const hop of route.hops) list.append(node('li','',`${hop.star_system}${hop.star_class ? ` · ${hop.star_class}` : ''}`));
    content.append(list);
  }
  return content;
}

export function createCommanderHome({getSnapshot}) {
  const root=node('div','commander-home');
  const identity=createCommanderCredential();
  const {commander,location}=identity;
  const supports=node('section','home-supports');supports.setAttribute('aria-label','Commander context');
  const readiness=createShipReadiness();supports.append(readiness.root);
  const cards={};
  for(const [id,label,hint] of [['route','Destination','View route ↗']]) {
    const button=node('button','home-card home-control');button.type='button';button.dataset.homeAction=id;
    const headline=node('span','home-answer'), summary=node('span','home-summary');
    button.append(node('span','home-eyebrow',label),headline,summary,node('span','home-action-label',hint));
    supports.append(button);cards[id]={button,headline,summary};
  }
  const galaxy=createGalaxyToday({getData:()=>getSnapshot().galaxyToday,
    updateNews:()=>window.Shell.updateGalnet(),setEnabled:enabled=>window.Shell.setGalnetEnabled(enabled)});
  root.append(identity.root,supports,galaxy.root);
  let model,dialog=null,dialogSubject=null;
  const details={commander:createCommanderProfile,location:locationDetail,ship:m=>readinessDetail('ship',m.snapshot),cargo:m=>readinessDetail('cargo',m.snapshot),fuel:m=>readinessDetail('fuel',m.snapshot),rebuy:m=>readinessDetail('rebuy',m.snapshot),route:routeDetail};
  const titles={commander:'Commander profile',location:'Location details',ship:'Ship condition',cargo:'Cargo hold',fuel:'Fuel reserves',rebuy:'Rebuy coverage',route:'Recorded route'};
  for(const button of [commander,location,...Object.values(readiness.controls),...Object.values(cards).map(card=>card.button)]) button.addEventListener('click',()=>{
    update();
    const id=button.dataset.homeAction;
    if(id==='route'&&!model.route)return;
    dialogSubject=subjectKey(model.snapshot.subject);
    dialog=openDeckDetail({title:titles[id],content:details[id](model),trigger:button,onClose:()=>{dialog=null;}});
  });
  function update() {
    model=commanderHomeModel(getSnapshot());
    if(dialog && subjectKey(model.snapshot.subject)!==dialogSubject) dialog.close();
    identity.update(model);
    root.dataset.reading=model.session?'active':'last-known';
    readiness.update(model.snapshot);
    galaxy.update();
    cards.route.button.hidden=!model.route;
    supports.dataset.count=model.route?'3':'2';
    if(model.route) {
      cards.route.headline.textContent=model.route.destination;
      cards.route.summary.textContent=`${model.routeStale ? 'Last known · ' : ''}${model.route.next_hop ? `Next: ${model.route.next_hop}` : 'Next hop not recorded'}`;
    }
  }
  update();
  return {root,update,dispose(){dialog?.close();galaxy.dispose();}};
}
