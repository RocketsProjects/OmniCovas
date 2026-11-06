// Reusable public-news projection. No commander dependency, transport or timer.
export const galnetArticleUrl=value=>typeof value==='string'&&/^https:\/\/www\.elitedangerous\.com\/news\/galnet\/[a-z0-9-]{1,220}$/.test(value)?value:null;
export function galaxyTodayModel(data={}) {
  const seen=new Set();
  const items=Array.isArray(data.items)?data.items.filter(item=>{
    if(!item||!galnetArticleUrl(item.url)||typeof item.title!=='string'||!item.title.trim()||typeof item.id!=='string'||seen.has(item.id))return false;
    seen.add(item.id);return true;
  }).slice(0,16).map(item=>{
    const text=typeof item.excerpt==='string'?item.excerpt:'',short=text.split(/\s+/).slice(0,40).join(' ').slice(0,280);
    return {...item,excerpt:short.length<text.length?short.replace(/\s+\S*$/,'')+'…':short};
  }):[];
  const date=value=>{
    if(!/^\d{4}-\d{2}-\d{2}$/.test(value||''))return 'Publication date unavailable';
    const parsed=new Date(value+'T12:00:00Z');
    return Number.isFinite(parsed.getTime())?parsed.toLocaleDateString(undefined,{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}):'Publication date unavailable';
  };
  const fetched=Date.parse(data.fetched_at||'');
  const updated=Number.isFinite(fetched)?new Date(fetched).toLocaleString(undefined,{dateStyle:'short',timeStyle:'short'}):'Not updated yet';
  const saved=data.state!=='fresh'||data.enabled!==true;
  const status=data.error==='bridge_unavailable'?'Bridge offline · saved copy':data.error==='cache_unavailable'?'Local cache unavailable':data.error?'Update unavailable · saved copy'
    :data.updating?'Updating GalNet…':!data.enabled?'Updates off':saved?'Saved copy':'Latest feed';
  return {items,date,updated,status,saved,enabled:data.enabled===true,updating:data.updating===true,
    canUpdate:data.can_update===true,nextUpdate:Date.parse(data.next_update_at||''),
    attribution:'GalNet © Frontier Developments',data};
}
export async function openGalnetArticle(url) {
  if(!galnetArticleUrl(url))throw new Error('This article link is not valid.');
  const invoke=window.__TAURI__?.core?.invoke;
  if(invoke)return invoke('open_galnet_article',{url});
  window.open(url,'_blank','noopener,noreferrer');return url;
}
