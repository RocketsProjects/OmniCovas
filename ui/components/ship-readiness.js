import {deckNode as node,widgetDetail} from './widget-host.js';
import {formatCredits} from './command-primitives.js';
import {shipReadiness} from '../view-models/ship-readiness.js';

const number=v=>typeof v==='number'&&Number.isFinite(v)&&v>=0?v:null;
const amount=v=>v.toLocaleString(undefined,{maximumFractionDigits:1});
const tons=v=>number(v)===null?'Not recorded':`${amount(v)} t`;
const percent=v=>number(v)===null?'Not recorded':`${amount(v*100)}%`;

function shieldText(m) {
  if(m.value('shields')===true)return 'Shields up';
  if(m.value('shield_fitted')===false)return 'No shield generator fitted';
  if(m.value('shields')===false&&m.value('shield_fitted')===true)
    return m.recent('docked')&&m.value('docked')===true?'Shields down · docked':'Shields down';
  return m.value('shields')===false?'Shield fit not recorded':'Shield state not recorded';
}
function field(parent,label,value) {
  const row=node('div','readiness-fact');row.append(node('dt','',label),node('dd','',value));parent.append(row);
}
function timeNotes(content,m,keys) {
  const details=node('details','readiness-observations');details.append(node('summary','','About these readings'));
  details.append(node('p','','These are the readings shown when this detail opened. Dynamic observations older than five minutes are treated as last known. This is not an activity-specific readiness verdict.'));
  for(const [key,label] of keys) {
    const value=m.fields[key];if(value?.value==null)continue;
    const row=node('p','',`${label} · `), at=Date.parse(value.observed_at||'');
    if(Number.isFinite(at)) {const t=node('time','',new Date(at).toLocaleString());t.dateTime=value.observed_at;row.append(t);}
    else row.append(node('span','','Time not recorded'));
    details.append(row);
  }
  content.append(details);
}
export function readinessDetail(id,snapshot) {
  const m=shipReadiness(snapshot), content=node('div','readiness-detail');
  content.append(node('p','readiness-reading',m.active?'Readings captured when opened':'Last-known readings captured when opened · check in Elite before acting'));
  const facts=node('dl','readiness-facts');
  if(id==='cargo') {
    const inventory=m.cargo.detail.inventory.map(item=>({...item,name:item.name.toLowerCase()==='drones'?'Limpets':item.name}));
    content.append(widgetDetail({...m.cargo,detail:{...m.cargo.detail,inventory}}));
    if(m.breakdown)content.append(node('p','',m.breakdown.limpets===m.rawCargo.total_count&&m.rawCargo.total_count>0
      ?'The recorded hold contains only unused limpets. They are supplies, not a load of commodities to sell. A full hold is not automatically a problem.'
      :`${m.breakdown.limpets} unused limpets and ${m.breakdown.goods} t of other cargo were recorded. Mission and stolen cargo stay marked in the manifest.`));
    if(m.breakdown?.limpets>0)content.append(node('p','','This counts unused limpets aboard, not active collectors.'));
    return content;
  }
  if(id==='ship') {
    field(facts,`Hull${m.value('hull')!==null&&!m.recent('hull')?' · last known':''}`,percent(m.value('hull')));
    field(facts,`Shields${m.value('shields')!==null&&!m.recent('shields')?' · last known':''}`,shieldText(m));
    field(facts,`Heat${m.value('heat')!==null&&!m.recent('heat')?' · last known':''}`,percent(m.value('heat')));
    content.append(facts);
    for(const c of m.concerns.filter(c=>['hull','shields','heat'].includes(c.id))) {
      const note=node('section','readiness-advice');note.dataset.severity=c.severity;
      note.append(node('h3','',c.label),node('p','',c.action));content.append(note);
    }
    if(m.value('shields')===false&&m.recent('docked')&&m.value('docked')===true)
      content.append(node('p','','Shields down while docked is not treated as a flight danger.'));
    if(m.value('shields')===false&&m.value('docked')===null)content.append(node('p','','Docking state is not recorded, so a shields-down reading alone is not treated as a flight danger.'));
    if(!m.concerns.some(c=>['hull','shields','heat'].includes(c.id)))content.append(node('p','','No concern flagged in these condition readings. Equipment for a particular activity is not checked here.'));
    timeNotes(content,m,[['hull','Hull'],['shields','Shields'],['heat','Heat']]);
  }else if(id==='fuel') {
    field(facts,'Main tank',tons(m.value('fuel')));field(facts,'Tank capacity',tons(m.value('fuel_capacity')));content.append(facts);
    const concern=m.concerns.find(c=>c.id==='fuel');
    content.append(node('p',concern?'readiness-advice':'',concern?.action||(m.value('fuel')===null?'Fuel quantity has not been recorded for this ship. Check the fuel display in Elite before travelling.':!m.recent('fuel')?'The quantity is last known. Check the fuel display in Elite before planning further travel.':m.value('fuel_capacity')===null?'Tank capacity is not recorded, so a low-fuel percentage cannot be judged.':'No low-fuel concern is flagged in this reading. Fuel needed for a destination and remaining range are not inferred.')));
    timeNotes(content,m,[['fuel','Fuel'],['fuel_capacity','Tank capacity']]);
  }else if(id==='rebuy') {
    const f=m.finance, wallet=f.recorded, credits=wallet.credits?.value, rebuy=wallet.rebuy?.value;
    const estimated=/estimated/i.test(wallet.rebuy?.caveat||'');
    field(facts,'Recorded credits',credits==null?'Not recorded':formatCredits(credits));
    field(facts,estimated?'Estimated ship rebuy':'Recorded ship rebuy',rebuy==null?'Not recorded':formatCredits(rebuy));content.append(facts);
    if(m.coverage==='shortfall')content.append(node('p','readiness-advice',`${formatCredits(f.shortfall)} short. Check the rebuy screen and balance in Elite before risking the ship.`));
    else if(m.coverage==='covered')content.append(node('p','',`The recent recorded balance covers one recorded rebuy of this ship. This does not account for future spending or guarantee a future rebuy price.`));
    else {
      if(f.historicalCoverage!=='unknown')content.append(node('p','',f.historicalCoverage==='covered'
        ?'Recorded comparison: the balance covers one recorded rebuy. This is not a current funds check.'
        :`Recorded comparison: ${formatCredits(f.shortfall)} short. This is not a current funds check.`));
      else content.append(node('p','','No compatible rebuy comparison.'));
      content.append(node('p','',f.explanation));
    }
    timeNotes(content,{fields:Object.fromEntries(Object.entries(wallet).map(([k,v])=>[k,{...v,observed_at:v.event_timestamp||v.observed_at}]))},[['credits','Balance'],['rebuy','Rebuy']]);
  }
  return content;
}

export function createShipReadiness() {
  const root=node('section','ship-readiness');root.setAttribute('aria-label','Ship readiness');
  const header=node('header','readiness-heading'), summary=node('span','readiness-summary');
  header.append(node('h2','','Ship readiness'),summary);
  const grid=node('div','readiness-controls'), controls={}, labels={}, notes={}, bars={};
  for(const id of ['ship','fuel','cargo','rebuy']) {
    const button=node('button','readiness-control home-control');button.type='button';button.dataset.homeAction=id;
    const value=node('span','readiness-value'), note=node('span','readiness-note');
    const bar=node('span','readiness-bar');bar.setAttribute('aria-hidden','true');bar.hidden=true;
    const fill=node('span');bar.append(fill);button.append(value,note,bar);grid.append(button);
    controls[id]=button;labels[id]=value;notes[id]=note;bars[id]={bar,fill};
  }
  root.append(header,grid);
  function update(snapshot) {
    const m=shipReadiness(snapshot);summary.textContent=m.summary;
    root.dataset.concern=m.warnings.length?'warning':m.concerns.length?'note':'quiet';
    labels.ship.textContent=m.value('hull')===null?'Condition unknown':`Hull ${percent(m.value('hull'))}`;
    const condition=m.concerns.find(c=>['hull','shields','heat'].includes(c.id)&&c.severity==='warning')||m.concerns.find(c=>['hull','shields','heat'].includes(c.id));
    const staleCondition=['hull','shields','heat'].some(key=>m.value(key)!==null&&!m.recent(key));
    notes.ship.textContent=condition?.label||(staleCondition?'Last known · condition readings':shieldText(m));
    labels.fuel.textContent=m.value('fuel')===null?'Fuel not recorded':`Fuel ${amount(m.value('fuel'))}${m.value('fuel_capacity')>0?` / ${amount(m.value('fuel_capacity'))}`:''} t`;
    notes.fuel.textContent=m.concerns.find(c=>c.id==='fuel')?.label||(!m.recent('fuel')&&m.value('fuel')!==null?'Last known · main tank':!(m.value('fuel_capacity')>0)?'Tank size not confirmed':'Main tank');
    labels.cargo.textContent=m.rawCargo?`Cargo ${m.cargo.display.headline}`:'Cargo not recorded';notes.cargo.textContent=m.cargoNote;
    const f=m.finance;
    labels.rebuy.textContent=m.coverage==='covered'?'Rebuy covered':m.coverage==='shortfall'?'Rebuy shortfall':f.historicalCoverage!=='unknown'?'Rebuy · recorded':'Rebuy unchecked';
    const reasonNotes={missing_credits:'Balance not recorded',missing_rebuy:'Rebuy not recorded',quote_before_ship:'Quote predates ship',quote_before_loadout:'Earlier loadout quote',estimated_rebuy:'Estimate only',wallet_changed:'Readings updating',subject_changed:'Ship or commander changed',times_unconfirmed:'Reading times unconfirmed'};
    notes.rebuy.textContent=m.coverage==='covered'?'One recorded rebuy':m.coverage==='shortfall'?`${formatCredits(f.shortfall)} short`
      :f.historicalCoverage==='covered'?'Balance covered quote':f.historicalCoverage==='shortfall'?'Recorded balance was short':reasonNotes[f.reason]||'Open for explanation';
    for(const [id,key] of [['ship','hull'],['fuel','fuel'],['cargo','cargo'],['rebuy','rebuy']]) {
      const concerns=m.concerns.filter(c=>id==='ship'?['hull','shields','heat'].includes(c.id):c.id===key);
      controls[id].dataset.severity=concerns.some(c=>c.severity==='warning')?'warning':concerns.length?'note':'quiet';
      controls[id].setAttribute('aria-label',`${labels[id].textContent}. ${notes[id].textContent}. Open ${id==='ship'?'condition':id} details`);
    }
    const ratios={fuel:m.value('fuel')!==null&&m.value('fuel_capacity')>0?m.value('fuel')/m.value('fuel_capacity'):null,
      cargo:m.rawCargo?.capacity>0?m.rawCargo.total_count/m.rawCargo.capacity:null};
    for(const id of ['fuel','cargo']) {bars[id].bar.hidden=ratios[id]===null;bars[id].fill.style.width=`${Math.max(0,Math.min(100,(ratios[id]||0)*100))}%`;}
  }
  return{root,controls,update};
}
