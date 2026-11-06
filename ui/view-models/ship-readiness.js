// Presentation and source-join guards over the existing readiness engine.
// Thresholds, contextual concerns and rebuy arithmetic are owned by that engine.
import {selectWidget,subjectKey} from './widget-snapshot.js';
import {rebuyComparison} from './commander-finances.js';

const known=v=>typeof v==='number'&&Number.isFinite(v)&&v>=0?v:null;
export function shipReadiness(snapshot={},now=Date.now()) {
  const watch=snapshot.shipProfile?.watch;
  const bound=Boolean(snapshot.subject?.commander_profile_key&&snapshot.subject?.ship_id!=null
    && subjectKey(snapshot.subject)===subjectKey(snapshot.factSubject)
    && watch?.subject&&subjectKey(watch.subject)===subjectKey(snapshot.subject));
  const active=snapshot.connected===true&&snapshot.sessionState==='Active';
  const fields=bound?watch.fields||{}:{};
  const recent=key=>{
    const field=fields[key], at=Date.parse(field?.observed_at||'');
    return active&&field?.quality==='recent'&&Number.isFinite(at)&&at<=now
      && now-at<=Math.min(300,watch.max_dynamic_age_seconds||300)*1000;
  };
  const value=key=>fields[key]?.quality!=='unknown'?fields[key]?.value??null:null;
  const concerns=bound&&active?(watch.concerns||[]).filter(c=>{
    const key=c.id==='shields'?'shields':c.id;
    return recent(key)&&(c.id!=='shields'||recent('docked'));
  }):[];
  const finance=rebuyComparison(snapshot,bound?watch:null,recent), coverage=finance.coverage;
  if(coverage==='shortfall')concerns.push({id:'rebuy',severity:'warning',label:'Rebuy funds short',action:'Check the figures in Elite before risking this ship. The recorded balance does not cover its recorded rebuy.'});
  const cargo=selectWidget('ship.cargo',snapshot);
  const raw=snapshot.localContextRaw?.cargo_hold;
  const observed=cargo.observation.source_state!=='absent';
  const at=Date.parse(cargo.observation.observed_at||'');
  const cargoRecent=observed&&active&&cargo.display.state!=='stale'&&Number.isFinite(at)&&at<=now&&now-at<=300000;
  const breakdown=bound&&watch.cargo?.observed&&cargo.observation.coverage==='complete'
    &&watch.cargo.observed_at===cargo.observation.observed_at&&watch.cargo.total_count===raw?.total_count
    &&watch.cargo.limpets+watch.cargo.goods===raw.total_count?watch.cargo:null;
  let cargoNote=!observed?'Manifest not recorded':cargo.observation.coverage!=='complete'?'Contents not recorded'
    :raw.total_count===0?'Empty hold':breakdown?.limpets===raw.total_count?'Limpets only'
      :breakdown?.limpets>0?`${breakdown.limpets} limpets · ${breakdown.goods} t other cargo`:'Manifest available';
  if(observed&&known(raw.capacity)!==null&&raw.total_count===raw.capacity&&raw.capacity>0)cargoNote+=' · hold full';
  else if(observed&&known(raw.capacity)!==null&&raw.total_count>raw.capacity)cargoNote+=' · check capacity';
  if(observed&&!cargoRecent)cargoNote=`Last known · ${cargoNote}`;
  const shieldKnown=value('shields')===true||value('shield_fitted')===false
    ||(value('shields')===false&&value('shield_fitted')===true&&recent('docked'));
  const missing=['hull','fuel','heat'].some(key=>value(key)===null)
    ||!(value('fuel_capacity')>0)||!shieldKnown||coverage==='unknown'
    ||!observed||cargo.observation.coverage!=='complete'||known(raw?.capacity)===null;
  const historical=['hull','fuel','shields','heat'].some(key=>value(key)!==null&&!recent(key));
  const warnings=concerns.filter(c=>c.severity==='warning');
  return {bound,active,fields,value,recent,concerns,warnings,coverage,finance,watch:bound?watch:null,
    cargo,cargoNote,breakdown,rawCargo:observed?raw:null,cargoRecent,
    summary:warnings.length?`${warnings[0].label}${warnings.length>1?` +${warnings.length-1}`:''}`:concerns.length?concerns[0].label:!bound&&!observed?'Waiting for ship readings':!active?'Last-known readings':historical?'Some readings last known':missing?'Readings incomplete':'No concerns flagged',
  };
}
