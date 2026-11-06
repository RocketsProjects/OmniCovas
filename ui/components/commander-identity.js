// Commander identity presentation only. All facts arrive from the shared home
// model; this component owns no transport, source inference or saved profile.
import {deckNode as node} from './widget-host.js';
import {formatCredits} from './command-primitives.js';
import {knownFinancialAmount as knownAmount,recordedFinances} from '../view-models/commander-finances.js';

const knownText=value=>typeof value==='string'&&value.trim()?value.trim():null;
const identityState=model=>!knownText(model.snapshot.publicState?.commander_name)
  && !knownText(model.ship.ship_name) && !model.location.systemName
  ? model.snapshot.connected?'Waiting for commander':'Offline · no record':model.qualifier;

function personalMark(name) {
  const mark=node('span','commander-mark');mark.setAttribute('aria-hidden','true');
  // An original compass monogram, not a rank, faction badge or game portrait.
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('viewBox','0 0 80 80');svg.setAttribute('fill','none');
  for(const [tag,attributes] of [
    ['path',{d:'M40 3 68 19 68 60 40 77 12 60 12 19Z',class:'commander-mark-frame'}],
    ['circle',{cx:'40',cy:'40',r:'25',class:'commander-mark-orbit'}],
    ['path',{d:'M40 7v10M40 63v10M7 40h10M63 40h10M22 22l5 5M53 53l5 5',class:'commander-mark-ticks'}],
    ['path',{d:'m36 15 4-7 4 7M36 65l4 7 4-7',class:'commander-mark-accent'}],
  ]) {
    const part=document.createElementNS(svg.namespaceURI,tag);
    for(const [key,value] of Object.entries(attributes))part.setAttribute(key,value);
    svg.append(part);
  }
  const initials=node('span','commander-monogram');
  const update=value=>{
    const parts=knownText(value)?.split(/\s+/u)||[];
    initials.textContent=parts.length?Array.from(parts[0])[0]+(parts.length>1?Array.from(parts.at(-1))[0]:''):'—';
  };
  update(name);mark.append(svg,initials);
  return{root:mark,update};
}

export function createCommanderCredential() {
  const root=node('article','home-identity commander-credential');root.setAttribute('aria-label','Commander and location');
  const commander=node('button','home-profile home-control');commander.type='button';commander.dataset.homeAction='commander';
  const mark=personalMark(null), copy=node('span','home-identity-copy');
  const title=node('h1','home-name');title.id='dashboard-title';
  const vessel=node('span','home-ship'), registration=node('span','commander-registration');
  const vesselLine=node('span','commander-vessel-line');vesselLine.append(vessel);
  const markColumn=node('span','commander-mark-column');markColumn.append(mark.root,registration);
  copy.append(node('span','commander-kicker','Commander'),title,vesselLine,node('span','home-action-label','Open personal file →'));
  commander.append(markColumn,copy);
  const location=node('button','home-location home-control');location.type='button';location.dataset.homeAction='location';location.dataset.dashboardZone='current-location';
  const placeLabel=node('span','home-eyebrow'), place=node('span','home-system'), station=node('span','home-station'), state=node('span','home-flight');
  location.append(placeLabel,place,station,state,node('span','home-action-label','Location details ↗'));
  const qualifier=node('span','home-qualifier');root.append(commander,location,qualifier);
  function update(model) {
    title.textContent=model.name;mark.update(knownText(model.snapshot.publicState?.commander_name));
    vessel.textContent=[model.shipName,model.shipType&&model.shipType!==model.shipName?model.shipType:null].filter(Boolean).join(' · ');
    registration.textContent=model.ship.ship_ident || '';registration.hidden=!knownText(model.ship.ship_ident);
    registration.setAttribute('aria-label',`Ship registration ${model.ship.ship_ident || 'not recorded'}`);
    qualifier.textContent=identityState(model);
    placeLabel.textContent=model.session&&!model.location.isStale?'Current location':'Last known location';
    place.textContent=model.location.systemName || 'Location not recorded';
    station.textContent=model.location.stationName||'';station.hidden=!model.location.stationName;
    state.textContent=model.location.flightValue==='Unknown'?'Flight state not recorded':model.location.flightValue;
    location.dataset.locationFreshness=model.location.systemName?model.session&&!model.location.isStale?'live_now':'last_seen':'not_checked';
  }
  return{root,commander,location,update};
}

function profileFact(label,value,className='') {
  const fact=node('div',`commander-profile-fact ${className}`);
  fact.append(node('dt','',label),node('dd','',value));return fact;
}

export function createCommanderProfile(model) {
  const root=node('div','commander-dossier');
  const mast=node('header','commander-dossier-mast'), name=node('div','commander-dossier-name');
  name.append(node('p','commander-kicker','Personal record'),node('h3','',model.name));
  const state=node('span','commander-record-state',identityState(model));
  mast.append(personalMark(knownText(model.snapshot.publicState?.commander_name)).root,name,state);root.append(mast);
  const groups=node('div','commander-profile-groups');
  const vessel=node('section','commander-profile-group commander-vessel');
  vessel.setAttribute('aria-label','Vessel');vessel.append(node('h3','commander-group-label','Vessel'));
  vessel.append(node('p','commander-vessel-name',model.shipName));
  const shipFacts=node('dl','commander-vessel-facts');
  if(model.shipType&&model.shipType!==model.shipName)shipFacts.append(profileFact('Class',model.shipType));
  if(knownText(model.ship.ship_ident))shipFacts.append(profileFact('Registration',model.ship.ship_ident));
  vessel.append(shipFacts);
  const finance=node('section','commander-profile-group commander-finances');finance.setAttribute('aria-label','Recorded finances');
  finance.append(node('h3','commander-group-label','Last recorded finances'));
  const wallet=recordedFinances(model.snapshot), amounts=node('dl','commander-account');
  const observations=[];
  for(const [key,label] of [['credits','Credits'],['rebuy','Rebuy'],['loan','Loan']]) {
    const field=wallet[key], value=knownAmount(field);
    if(value===null)continue;
    const estimated=key==='rebuy'&&/estimated/i.test(field.caveat||'');
    amounts.append(profileFact(estimated?'Estimated rebuy':label,formatCredits(value),`commander-money-${key}`));
    observations.push({label:estimated?'Estimated rebuy':label,timestamp:field.event_timestamp||field.observed_at||null,note:estimated?field.caveat:null});
  }
  if(observations.length)finance.append(amounts);
  else finance.append(node('p','commander-profile-empty','No wallet readings recorded yet.'));
  groups.append(vessel,finance);root.append(groups);
  const position=node('section','commander-position');position.setAttribute('aria-label','Recorded position');
  const positionCopy=node('div');
  positionCopy.append(node('h3','commander-group-label',model.session&&!model.location.isStale?'Position':'Last known position'));
  positionCopy.append(node('p','commander-position-name',[model.location.systemName,model.location.stationName].filter(Boolean).join(' · ')||'Location not recorded'));
  position.append(positionCopy,node('span','commander-position-state',model.location.flightValue==='Unknown'?'Flight state not recorded':model.location.flightValue));root.append(position);
  const records=node('details','commander-records');records.append(node('summary','','Reading times'));
  records.append(node('p','commander-record-note','This file keeps the readings shown when you opened it. Balances are recorded observations, not a live account.'));
  const byTime=new Map();
  for(const observation of observations) {
    const key=observation.timestamp||'';
    if(!byTime.has(key))byTime.set(key,[]);byTime.get(key).push(observation.label);
  }
  for(const [timestamp,labels] of byTime) {
    const line=node('p','commander-record-time');line.append(node('span','',`${labels.join(', ')} · `));
    const date=new Date(timestamp);
    if(timestamp&&Number.isFinite(date.getTime())) {
      const time=node('time','',new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'short'}).format(date));time.dateTime=timestamp;line.append(time);
    }else line.append(node('span','','Time not recorded'));
    records.append(line);
  }
  for(const observation of observations)if(observation.note)records.append(node('p','',observation.note));
  if(observations.length)root.append(records);
  return root;
}
