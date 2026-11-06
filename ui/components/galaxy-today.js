import {deckNode as node,openDeckDetail} from './widget-host.js';
import {galaxyTodayModel,openGalnetArticle} from '../view-models/galaxy-today.js';

export function createGalaxyToday({getData,updateNews,setEnabled,openOriginal=openGalnetArticle}) {
  const root=node('button','galaxy-today home-control');root.type='button';root.dataset.homeAction='galaxy';
  const label=node('span','galaxy-brand','Galaxy today'), copy=node('span','galaxy-copy');
  const meta=node('span','galaxy-meta'), title=node('span','galaxy-headline'), arrow=node('span','galaxy-arrow','›');
  arrow.setAttribute('aria-hidden','true');copy.append(meta,title);root.append(label,copy,arrow);
  let dialog=null, body=null, page=0, selected=null, readerData=null, busy=false;
  const action=(text,key,fn)=>{const b=node('button','rcd-button',text);b.type='button';b.dataset.galaxyControl=key;b.addEventListener('click',fn);return b;};
  const status=node('p','galaxy-reader-status');status.setAttribute('role','status');
  async function request(fn) {
    if(busy)return;const focusKey=document.activeElement?.dataset?.galaxyControl;busy=true;status.textContent='Updating the public feed…';
    try{const data=await fn();if(!dialog?.open)return;readerData=data;selected=null;status.textContent='';draw(focusKey);}
    catch(error){status.textContent=error.message||'The update is unavailable. Saved articles are still readable.';}
    finally{busy=false;}
  }
  function draw(focusKey) {
    if(!body)return;
    const m=galaxyTodayModel(readerData||{}), content=node('section','galaxy-reader');
    content.setAttribute('aria-label',selected?'Selected GalNet article':'GalNet headlines');
    if(selected) {
      const item=selected;
      content.append(action('← Headlines','back',()=>{selected=null;readerData=getData();draw(item.id);}),node('p','galaxy-article-date',`GalNet · ${m.date(item.published_date)}`),node('h3','galaxy-article-title',item.title));
      content.append(node('p','galaxy-excerpt',item.excerpt||'This feed item has no excerpt. Read the original article for its published text.'));
      const address=node('p','galaxy-address',item.url);address.hidden=true;
      const open=action('Read original article ↗','original',async()=>{
        try{await openOriginal(item.url);status.textContent='Original article opened in your browser.';}
        catch{address.hidden=false;status.textContent='The browser could not be opened. The original article address is shown below.';}
      });
      content.append(open,node('p','galaxy-attribution',`${m.attribution} · Short feed excerpt`),address);
    }else {
      const controls=node('div','galaxy-reader-controls');
      controls.append(action(m.enabled?'Turn updates off':'Enable GalNet updates','consent',()=>request(()=>setEnabled(!m.enabled))));
      if(m.enabled){const refresh=action(m.updating?'Updating…':'Update news','update',()=>request(updateNews));refresh.disabled=m.updating||!m.canUpdate;controls.append(refresh);}
      content.append(controls);
      if(!m.enabled)content.append(node('p','galaxy-consent','Optional public RSS updates from Frontier, at most every 15 minutes. No commander identity, gameplay data or credentials are sent. A short copy is saved locally.'));
      else if(!m.canUpdate&&!m.updating&&Number.isFinite(m.nextUpdate))content.append(node('p','galaxy-update-budget',`Next check: ${new Date(m.nextUpdate).toLocaleString(undefined,{dateStyle:'short',timeStyle:'short'})}.`));
      content.append(node('p','galaxy-feed-state',`${m.status} · ${m.updated}`));
      const list=node('div','galaxy-news-list'),pages=Math.max(1,Math.ceil(m.items.length/2));page=Math.min(page,pages-1);
      for(const item of m.items.slice(page*2,page*2+2)){
        const button=action('',item.id,()=>{selected={...item};draw('back');});button.classList.add('galaxy-news-item');
        button.append(node('span','galaxy-item-date',m.date(item.published_date)),node('span','galaxy-item-title',item.title));list.append(button);
      }
      if(!m.items.length)list.append(node('p','galaxy-empty',m.data.fetched_at?'No articles in the last successful feed update.':m.enabled?'No saved articles yet. An update may be unavailable; try again when the next check is allowed.':'Enable updates to read published GalNet news here.'));
      content.append(list);
      if(pages>1){
        const pager=node('nav','galaxy-pager');pager.setAttribute('aria-label','Headline pages');
        const prev=action('Previous','previous',()=>{page--;draw('previous');}),next=action('Next','next',()=>{page++;draw('next');});
        prev.disabled=page===0;next.disabled=page===pages-1;pager.append(prev,node('span','',`${page+1} / ${pages}`),next);content.append(pager);
      }
      content.append(node('p','galaxy-attribution',m.attribution));
    }
    const details=node('details','galaxy-reading-details');details.append(node('summary','','Reading details'));
    details.append(node('p','',`Feed checked: ${m.updated}. Publication dates use the GalNet calendar as published; they are not local update times. Saved articles are not evidence that an event is still active. Community Goals are not connected.`));
    content.append(details,status);body.replaceChildren(content);
    if(focusKey)content.querySelectorAll('[data-galaxy-control]').forEach(el=>{if(el.dataset.galaxyControl===focusKey)el.focus();});
  }
  root.addEventListener('click',()=>{
    readerData=getData();selected=null;status.textContent='';body=node('div');
    dialog=openDeckDetail({title:'Galaxy today · GalNet',content:body,trigger:root,onClose:()=>{dialog=null;body=null;}});draw();
  });
  function update() {
    const data=getData(),m=galaxyTodayModel(data||{}),first=m.items[0];
    meta.textContent=first?`${m.saved?'Saved · ':''}GalNet · ${m.date(first.published_date)}`:'GalNet news';
    title.textContent=first?.title||(m.enabled?'News update pending':'Published news · open to enable updates');
    root.setAttribute('aria-label',`${label.textContent}. ${meta.textContent}. ${title.textContent}. Open news`);
    if(dialog?.open&&!selected&&JSON.stringify(data)!==JSON.stringify(readerData)){
      const focused=document.activeElement?.dataset?.galaxyControl;readerData=data;draw(focused);
    }
  }
  update();return {root,update,dispose(){dialog?.close();}};
}
