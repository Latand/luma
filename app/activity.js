'use strict';
// Activity log: what the operator clicks, switches, changes and sings, so an agent can later tune the UX to how Luma is
// really used and follow the singing over time. Luma Studio appends the events to songs/logs/activity/<day>.jsonl.
// Only pages Studio serves log: Studio itself (/), its trainers (/song/…) and /demo. A trainer opened from a file or from
// another server stays silent. No entry point here may disturb the page: each one swallows its own failures.
// Event schema and the off switch: docs/ACTIVITY_LOG.md.
(() => {
const OFF_KEY='luma.activity',ENDPOINT='/activity',MAX_EVENT=16384,MAX_BATCH=48*1024,MAX_QUEUE=400,FLUSH_MS=10000;
const path=location.pathname;
const page=path==='/'?'studio':path==='/demo'?'demo':/^\/song\/[^/]+\.html$/.test(path)?decodeURIComponent(path.slice(6,-5)):null;
const served=/^https?:$/.test(location.protocol)&&page!==null;
const enc=new TextEncoder(),size=t=>enc.encode(t).length;
const session=(()=>{try{return crypto.randomUUID();}catch(_){return Date.now().toString(36)+Math.random().toString(36).slice(2,10);}})();
const opened=performance.now();
let off=false,seq=0,queue=[],bytes=0,timer=0,last={},visibleMs=0,visibleSince=document.visibilityState==='visible'?opened:null;
try{off=localStorage.getItem(OFF_KEY)==='off';}catch(_){}
function clip(v,n=60){v=String(v??'').replace(/\s+/g,' ').trim();return v.length>n?v.slice(0,n-1)+'…':v;}
function log(type,data){
 try{if(!served||off)return;
  const line=JSON.stringify({v:1,ts:new Date().toISOString(),session,page,seq:++seq,type,data:data||{}}),n=size(line);
  if(n>MAX_EVENT)return;
  if(queue.length>=MAX_QUEUE){bytes-=queue[0].n;queue.shift();}   // a server that is gone must not grow the tab without end
  queue.push({line,n});bytes+=n;
  if(bytes>=MAX_BATCH/2||queue.length>=40)flush();else if(!timer)timer=setTimeout(flush,FLUSH_MS);
 }catch(_){}
}
// sendBeacon outlives the page and never answers; keepalive fetch is the fallback. A refused batch is dropped.
function flush(){
 try{clearTimeout(timer);timer=0;
  while(queue.length){let k=0,n=16;while(k<queue.length&&n+queue[k].n+1<=MAX_BATCH){n+=queue[k].n+1;k++;}
   const batch=queue.splice(0,Math.max(1,k)),body='{"events":['+batch.map(e=>e.line).join(',')+']}';
   let sent=false;try{sent=!!navigator.sendBeacon&&navigator.sendBeacon(ENDPOINT,body);}catch(_){}
   if(!sent)try{fetch(ENDPOINT,{method:'POST',body,keepalive:true,headers:{'Content-Type':'text/plain'}}).catch(()=>{});}catch(_){}}
  bytes=0;
 }catch(_){}
}
// Only what changed since the previous call; the first call is the starting state.
function state(cur){
 try{if(!served)return;const changed={};let any=false;
  for(const k of Object.keys(cur)){const v=JSON.stringify(cur[k]);if(last[k]!==v){last[k]=v;changed[k]=cur[k];any=true;}}
  if(any)log('state',changed);
 }catch(_){}
}
function setEnabled(on){
 try{if(!on&&!off){log('logging_off');flush();}
  off=!on;try{localStorage.setItem(OFF_KEY,on?'on':'off');}catch(_){}
  if(on)log('logging_on');
 }catch(_){}
}
// A control by what it is: its id, else its first data-* attribute, else its tag and class inside the nearest id.
function control(el){
 if(el.id)return el.id;
 const d=Object.entries(el.dataset||{})[0];if(d)return clip(d[0]+':'+d[1],40);
 const area=el.parentElement&&el.parentElement.closest('[id]'),cls=typeof el.className==='string'?el.className.trim().split(/\s+/)[0]:'';
 return (area?area.id+' ':'')+el.tagName.toLowerCase()+(cls?'.'+cls:'');
}
function label(el){return clip(el.getAttribute('aria-label')||(el.labels&&el.labels[0]&&el.labels[0].textContent)||el.title||el.textContent);}
function area(el){const a=el.parentElement&&el.parentElement.closest('dialog[id],section[id],[role=tabpanel][id],details[id],header,main,aside');return a?(a.id||a.tagName.toLowerCase()):null;}
function visible(){return Math.round(visibleMs+(visibleSince===null?0:performance.now()-visibleSince));}
function songInfo(){const g=window.LUMA_SONG;if(!g||typeof g!=='object')return {};
 return {songHash:g.sourceId||g.id||null,songId:g.id||null,lessonId:g.lesson&&g.lesson.id||null,duration:Number.isFinite(g.duration)?+g.duration.toFixed(1):null,notes:Array.isArray(g.notes)?g.notes.length:null};}
function opening(restored){
 let from=null;try{const r=document.referrer?new URL(document.referrer):null;if(r&&r.origin===location.origin)from=r.pathname==='/'?'studio':r.pathname;}catch(_){}
 log('page_open',{kind:page==='studio'?'studio':'trainer',...songInfo(),from,restored:!!restored,viewport:[innerWidth,innerHeight],coarse:matchMedia('(pointer: coarse)').matches});
}
if(served){
 const on=(type,fn,target=document)=>target.addEventListener(type,e=>{try{fn(e);}catch(_){}},true);
 on('click',e=>{const el=e.target instanceof Element&&e.target.closest('button,a[href],summary,[role=button],[role=tab],canvas,input[type=button],input[type=submit]');if(!el)return;
  const data={id:control(el),label:label(el),area:area(el)};
  if(el.tagName==='A'){const u=new URL(el.href,location.href);data.href=u.origin===location.origin?u.pathname.replace(/^\/song\//,'song:').replace(/\.html$/,''):'external';}
  if(e.detail===0)data.noPointer=true;   // Enter/Space on a focused control, or a click made by script
  log('click',data);});
 on('change',e=>{const el=e.target;if(!(el instanceof HTMLInputElement||el instanceof HTMLSelectElement||el instanceof HTMLTextAreaElement))return;
  const data={id:control(el),label:label(el),area:area(el),kind:el.type};
  if(el.type==='checkbox'||el.type==='radio')data.value=el.checked;
  else if(el.type==='file'){const f=el.files&&el.files[0];data.files=el.files?el.files.length:0;if(f){data.ext=(f.name.match(/\.([a-z0-9]{1,5})$/i)||[,''])[1].toLowerCase();data.mb=+(f.size/1048576).toFixed(1);}}
  else if(el.type==='range'||el.type==='number')data.value=Number(el.value);
  else if(el instanceof HTMLSelectElement)data.value=el.value.length<=24?el.value:'#'+el.selectedIndex;
  else data.filled=!!el.value;   // typed text (a title, an artist) stays out of the log
  log('change',data);});
 on('keydown',e=>{const t=e.target;if(e.repeat||['Shift','Control','Alt','Meta'].includes(e.key))return;
  if(t instanceof Element&&(t.closest('input,textarea,select,[contenteditable=""],[contenteditable=true]')))return;
  const mods=['ctrl','alt','shift','meta'].filter(m=>e[m+'Key']).join('+');log('key',mods?{key:e.code||e.key,mods}:{key:e.code||e.key});});
 on('toggle',e=>{const d=e.target;if(!(d instanceof HTMLDetailsElement))return;const s=d.querySelector('summary');log('details',{id:d.id||(s?label(s):control(d)),open:d.open});});
 on('close',e=>{const d=e.target;if(d instanceof HTMLDialogElement)log('dialog',{id:d.id||control(d),open:false});});
 on('visibilitychange',()=>{const now=performance.now();if(document.visibilityState==='visible'){if(visibleSince===null)visibleSince=now;}else if(visibleSince!==null){visibleMs+=now-visibleSince;visibleSince=null;}
  log('visibility',{state:document.visibilityState,visibleMs:visible()});if(document.visibilityState==='hidden')flush();});
 on('pagehide',e=>{log('page_close',{openMs:Math.round(performance.now()-opened),visibleMs:visible(),persisted:!!e.persisted});flush();},window);
 on('pageshow',e=>{if(e.persisted)opening(true);},window);
 on('error',e=>{if(e instanceof ErrorEvent)log('js_error',{message:clip(e.message,200),source:clip(String(e.filename||'').split('/').pop(),60),line:e.lineno||null});},window);
 on('unhandledrejection',e=>{const r=e.reason;log('js_error',{message:clip(r&&r.message||r,200),rejection:true});},window);
 on('storage',e=>{if(e.key===OFF_KEY)off=e.newValue==='off';},window);
 opening(false);
}
window.LumaActivity={log,state,flush,setEnabled,clip,available:served,enabled:()=>served&&!off,session,page};
})();
