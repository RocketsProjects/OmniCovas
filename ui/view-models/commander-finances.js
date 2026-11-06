// Shared recorded-value selection for Commander Profile and Ship Readiness.
// Comparison arithmetic remains in the backend readiness engine.
import {subjectKey} from './widget-snapshot.js';

export const knownFinancialAmount=field=>typeof field?.value==='number'&&Number.isFinite(field.value)&&field.value>=0
  && !['not_loaded','disabled','unsupported','unknown','error','malformed'].includes(field.freshness)?field.value:null;
const at=field=>Date.parse(field?.event_timestamp||field?.observed_at||'');
export function recordedFinances(snapshot={}) {
  const coherent=Boolean(snapshot.subject?.commander_profile_key&&snapshot.factSubject
    &&subjectKey(snapshot.subject)===subjectKey(snapshot.factSubject));
  const watch=snapshot.shipProfile?.watch;
  const comparison=coherent&&subjectKey(watch?.subject)===subjectKey(snapshot.subject)?watch?.rebuy:null;
  const wallet=coherent?snapshot.localContextRaw?.wallet_snapshot||comparison?.recorded||{}:{};
  const commanderAt=Date.parse(comparison?.commander_observed_at||'');
  const result={};
  for(const key of ['credits','rebuy','loan']) {
    const field=wallet[key];
    // A prior commander's amount is not a record for this commander. Missing
    // dates can still be displayed as recorded, but never enable comparison.
    if(knownFinancialAmount(field)===null||(Number.isFinite(commanderAt)&&at(field)<commanderAt))continue;
    result[key]=field;
  }
  return result;
}

export const rebuyReasons={
  missing_credits:'No credit balance has been recorded.',
  missing_rebuy:'No ship rebuy has been recorded.',
  commander_unconfirmed:'The commander for these readings is not confirmed.',
  commander_changed:'These readings predate the current commander.',
  ship_unconfirmed:'The ship for this quote is not confirmed.',
  quote_before_ship:'This quote predates the latest ship record. A quote for this ship is needed.',
  quote_before_loadout:'A newer loadout was recorded after this quote. Its rebuy needs checking.',
  estimated_rebuy:'This rebuy is an estimate, not a recorded insurance quote.',
  times_unconfirmed:'The reading times are missing or invalid, so compatibility cannot be checked.',
  invalid_amount:'A financial reading is invalid.',
  balance_stale:'The balance is more than five minutes old; current funds are not confirmed.',
  balance_before_quote:'The balance predates this ship quote; current funds are not confirmed.',
  offline:'The connection is offline; current funds are not confirmed.',
  inactive:'The game session is not active; current funds are not confirmed.',
  subject_changed:'These comparison readings belong to another commander or ship.',
  wallet_changed:'The financial readings changed. Waiting for a matching comparison.',
  unavailable:'The comparison is not available yet.',
};

export function rebuyComparison(snapshot,watch,recent) {
  const recorded=recordedFinances(snapshot);
  const unknown=reason=>({recorded,coverage:'unknown',historicalCoverage:'unknown',shortfall:null,reason,explanation:rebuyReasons[reason]});
  if(!watch)return unknown(snapshot.shipProfile?.watch?'subject_changed':'unavailable');
  const packet=watch.rebuy||{};
  if(['commander_changed','commander_unconfirmed'].includes(packet.reason))return unknown(packet.reason);
  // Both renderers show the same wallet. A parallel refresh must not attach
  // arithmetic over an older amount/quote to the newer displayed figures.
  const expected=packet.recorded||Object.fromEntries(['credits','rebuy'].map(k=>[k,watch.fields?.[k]]));
  for(const key of ['credits','rebuy']) {
    const source=expected[key], displayed=recorded[key];
    if(knownFinancialAmount(displayed)!==knownFinancialAmount(source))return unknown('wallet_changed');
    if(displayed&&(!Number.isFinite(at(displayed))||!Number.isFinite(at(source))))return unknown('times_unconfirmed');
    if(displayed&&at(displayed)!==at(source))return unknown('wallet_changed');
  }
  const loadoutAt=Date.parse(snapshot.localContextRaw?.module_loadout?.event_timestamp||'');
  if(Number.isFinite(loadoutAt)&&at(recorded.rebuy)<loadoutAt)return unknown('quote_before_loadout');
  let historicalCoverage=packet.historical_coverage||packet.coverage;
  if(!['covered','shortfall'].includes(historicalCoverage))historicalCoverage='unknown';
  const active=snapshot.connected===true&&snapshot.sessionState==='Active';
  const coverage=active&&recent('credits')&&['covered','shortfall'].includes(packet.coverage)?packet.coverage:'unknown';
  const reason=historicalCoverage==='unknown'?packet.reason||(!recorded.credits?'missing_credits':!recorded.rebuy?'missing_rebuy':'unavailable')
    :!snapshot.connected?'offline':!active?'inactive':!recent('credits')?'balance_stale':packet.reason||null;
  return {recorded,coverage,historicalCoverage,shortfall:packet.shortfall,reason,explanation:rebuyReasons[reason]||''};
}
