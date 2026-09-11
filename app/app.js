'use strict';
(() => {
const $=id=>document.getElementById(id),clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const names=['C','C♯','D','D♯','E','F','F♯','G','G♯','A','A♯','B'];
const words=['До','До-дієз','Ре','Ре-дієз','Мі','Фа','Фа-дієз','Соль','Соль-дієз','Ля','Ля-дієз','Сі'];
const BLACK=new Set([1,3,6,8,10]);
const GRID=.02;// scoring frame, seconds of song time
let song=window.LUMA_SONG,assets=window.LUMA_ASSETS,baseNotes=structuredClone(song.notes);
// Difficulty presets: corridor width, how far in time a sung frame may sit from the grid frame, share of a note's frames needed for ✓, and whether octave errors are forgiven.
const LEVELS={easy:{tolerance:80,slack:.12,ratio:.35,octaveFree:true,label:'легко'},normal:{tolerance:50,slack:.06,ratio:.5,octaveFree:false,label:'звично'},strict:{tolerance:35,slack:.05,ratio:.65,octaveFree:false,label:'точно'}};
const prefs={gate:-48,octave:0,tolerance:50,level:'normal',latency:0,back:.75,fore:.45,vocal:true,view:'contour',speed:1,loop:false,mic:'',lyrics:true,takesOpen:true,viewDefault:2};
try{const p=JSON.parse(localStorage.getItem('luma.trainer.settings')||'{}');for(const [k,a,b]of[['gate',-70,-25],['octave',-12,12],['tolerance',10,100],['latency',-500,1000],['back',0,1],['fore',0,1]])if(Number.isFinite(p[k]))prefs[k]=clamp(p[k],a,b);if(![-12,0,12].includes(prefs.octave))prefs.octave=0;if(typeof p.lyrics==='boolean')prefs.lyrics=p.lyrics;if(typeof p.takesOpen==='boolean')prefs.takesOpen=p.takesOpen;if(typeof p.vocal==='boolean')prefs.vocal=p.vocal;if(p.level in LEVELS||p.level==='custom')prefs.level=p.level;if(prefs.level!=='custom')prefs.tolerance=LEVELS[prefs.level].tolerance;
 // contour became the default on 2026-09-11; older saved settings keep their explicit choice only after that migration
 if(p.viewDefault===2&&(p.view==='notes'||p.view==='contour'))prefs.view=p.view;}catch(_){}
function levelOpt(){const L=LEVELS[prefs.level]||LEVELS.normal;return{tolerance:prefs.level==='custom'?prefs.tolerance:L.tolerance,slack:L.slack,ratio:L.ratio,octaveFree:L.octaveFree,level:prefs.level};}
function levelLabel(opt){return opt.level==='custom'?'свій коридор':(LEVELS[opt.level]||LEVELS.normal).label;}
// Signed distance in cents; on the easy level the octave is forgiven (distance folds into ±6 semitones).
function centsOff(m,refM,opt){let d=m-refM;if(opt.octaveFree){d=((d%12)+12)%12;if(d>6)d-=12;}return d*100;}
const LOOP_LANE=24;
const s={ctx:null,stream:null,capture:null,micSource:null,worker:null,micGeneration:0,busy:false,cancel:0,mode:'idle',transport:null,sources:[],endTimer:null,nextTimer:null,bufs:new Map(),gains:null,pos:song.initialTime||0,range:{a:0,b:song.duration},rangeId:0,history:[],current:null,takes:[],takeCounter:0,pending:new Map(),awaitFinish:false,trace:null,live:null,verified:[],dirty:true,raf:0,lastDraw:0,lastUI:0,rangeLo:48,rangeHi:76,liveSmooth:null,lastSmoothT:0,toastTimer:0,edit:null,computeMs:0,windowMs:0,unsaved:false,undoPunch:null,busyFor:'',scrub:null,lyricKey:'',resumeAt:null,tlDrag:null,seekTimer:0};
const canvas=$('chart'),g=canvas.getContext('2d',{alpha:false}),tl=$('timeline'),tg=tl.getContext('2d',{alpha:false});let W=1,H=1,DPR=1,TW=1,TH=1;
const reduced=matchMedia('(prefers-reduced-motion: reduce)');
function fmt(t){t=Math.max(0,Number.isFinite(t)?t:0);return String(Math.floor(t/60)).padStart(2,'0')+':'+String(Math.floor(t%60)).padStart(2,'0');}
function name(m){if(!Number.isFinite(m))return '—';const n=Math.round(m);return names[(n%12+12)%12]+(Math.floor(n/12)-1);}
function noteHTML(m){if(!Number.isFinite(m))return '—';const n=Math.round(m);return names[(n%12+12)%12]+'<small>'+String(Math.floor(n/12)-1)+'</small>';}
function icon(id){return '<svg><use href="#i-'+id+'"/></svg>';}
function say(text){$('srStatus').textContent=text;}
function toast(text){$('toast').textContent=text;$('toast').classList.add('show');clearTimeout(s.toastTimer);s.toastTimer=setTimeout(()=>$('toast').classList.remove('show'),5000);}
// kind 'mic': microphone trouble, so the banner offers the microphone settings (or the Studio link on file://). Other errors get no action.
function error(text,kind=''){$('errorText').textContent=text;$('errorBanner').hidden=false;const file=location.protocol==='file:';$('studioLink').hidden=!(kind==='mic'&&file);$('errorSettings').hidden=!(kind==='mic'&&!file);if($('settingsDialog').open)$('settingsDialog').close();updateStatus();say(text);}
function savePrefs(){try{localStorage.setItem('luma.trainer.settings',JSON.stringify(prefs));}catch(_){}}
function saveEdits(){try{localStorage.setItem('luma.target.'+song.id,JSON.stringify({notes:song.notes,verified:s.verified}));}catch(_){toast('Не вдалося зберегти правки у браузері. Завантаж JSON цілі.');}}
function loadEdits(){s.verified=[];try{const d=JSON.parse(localStorage.getItem('luma.target.'+song.id)||'null');if(d&&validNotes(d.notes,song.duration)){song.notes=d.notes;s.verified=(d.verified||[]).filter(r=>Number.isFinite(r.a)&&Number.isFinite(r.b)&&r.a>=0&&r.b<=song.duration&&r.b>r.a);}}catch(_){}}
function validNotes(a,d){return Array.isArray(a)&&a.length<=20000&&a.every(n=>Number.isFinite(n.id)&&Number.isFinite(n.a)&&Number.isFinite(n.b)&&Number.isFinite(n.m)&&n.a>=0&&n.b>n.a&&n.b<=d+.05&&n.m>=24&&n.m<=108);}
function validLyrics(a){return Array.isArray(a)&&a.length<=5000&&a.every(l=>Number.isFinite(l.a)&&Number.isFinite(l.b)&&Array.isArray(l.words)&&l.words.every(w=>Number.isFinite(w.a)&&Number.isFinite(w.b)&&typeof w.w==='string'));}
function verifiedAt(t){return s.verified.some(r=>t>=r.a&&t<=r.b);}
function rangeVerified(){return s.verified.some(r=>r.a<=s.range.a+.02&&r.b>=s.range.b-.02);}
// While a recorded trace is on screen its own octave/view/tolerance stay in force, so notes align with what was scored.
function traceShown(){return s.mode!=='singing'&&!!s.trace;}
function effective(){if(s.mode==='singing'&&s.live)return s.live.opt;if(traceShown())return s.trace.score.opt;return{octave:prefs.octave,view:prefs.view,...levelOpt()};}
function customRange(){return s.rangeId!==0&&(s.range.a>.01||s.range.b<song.duration-.01);}
function noteAt(t){const ns=song.notes;let a=0,b=ns.length;while(a<b){const m=(a+b)>>1;if(ns[m].a<=t)a=m+1;else b=m;}const n=ns[a-1];return n&&t<n.b?n:null;}
function pointAt(t){const a=song.points;let lo=0,hi=a.length;while(lo<hi){const mid=(lo+hi)>>1;if(a[mid][0]<t)lo=mid+1;else hi=mid;}let p=a[Math.min(lo,a.length-1)];const prev=a[lo-1];if(prev&&(!p||Math.abs(prev[0]-t)<Math.abs(p[0]-t)))p=prev;return p&&Math.abs(p[0]-t)<song.hop*.75?p:null;}
function targetAt(t,opt=effective()){
 if(t<0||t>song.duration)return null;const n=noteAt(t),p=pointAt(t);if(n?.ignored)return null;
 if(opt.view==='notes')return n?{m:n.m+opt.octave,ok:!!n.ok||!!n.manual,verified:verifiedAt(t),id:n.id}:null;
 if(!p||p[1]===null)return null;let m=p[1];if(n?.manual)m+=n.m-(n.originalM??n.m);
 return {m:m+opt.octave,ok:!!p[3]||!!n?.manual,verified:verifiedAt(t),id:n?.id};
}
// ── Target-match score: one pass over a fixed 20 ms grid, each frame counted once. ──
// 0 = no target (excluded), 1 = hit, 2 = sung outside the corridor, 3 = target but no confident voice (silence = miss).
function newScore(meta){return{a:meta.a,opt:{octave:meta.octave,view:meta.view,tolerance:meta.tolerance,slack:meta.slack??.05,ratio:meta.ratio??.5,octaveFree:!!meta.octaveFree,level:meta.level||'custom'},next:0,cursor:0,target:0,hit:0,sung:0,frames:[],notes:new Map()};}
function scoreAdvance(sc,points,upTo){
 const tol=sc.opt.tolerance,slack=sc.opt.slack;
 for(;;){const t=sc.a+sc.next*GRID;if(t>upTo||t>song.duration+GRID)break;
  const ref=targetAt(t,sc.opt);let state=0;
  if(ref){sc.target++;
   while(sc.cursor+1<points.length&&points[sc.cursor+1].songT<=t)sc.cursor++;
   // nearest confident voice frame within the level's time slack (a silent frame next to a voiced one is forgiven on easy)
   let m=null;for(let i=sc.cursor+2;i>=sc.cursor-4;i--){const p=points[i];if(!p||Math.abs(p.songT-t)>slack||p.confidence<.8)continue;const v=p.raw??p.m;if(v===null||v===undefined||!Number.isFinite(v))continue;if(m===null||Math.abs(p.songT-t)<m.d)m={v,d:Math.abs(p.songT-t)};}
   if(m){sc.sung++;state=Math.abs(centsOff(m.v,ref.m,sc.opt))<=tol?1:2;if(state===1)sc.hit++;}else state=3;
   if(ref.id!==undefined&&ref.id!==null){let n=sc.notes.get(ref.id);if(!n){n={frames:0,hit:0,sung:0};sc.notes.set(ref.id,n);}n.frames++;if(state===1)n.hit++;if(state!==3)n.sung++;}
  }
  sc.frames.push(state);sc.next++;
 }
}
function scorePct(sc){return sc&&sc.target>0?Math.round(100*sc.hit/sc.target):null;}
function frameState(sc,t){if(!sc)return 0;const i=Math.round((t-sc.a)/GRID);return i>=0&&i<sc.frames.length?sc.frames[i]:0;}
function noteKind(sc,id){const n=sc?.notes.get(id);if(!n||n.frames<3)return null;if(n.hit/n.frames>=sc.opt.ratio)return 'hit';return n.sung>0?'miss':'silent';}
function missRuns(sc){const runs=[];if(!sc)return runs;let start=-1;for(let i=0;i<=sc.frames.length;i++){const miss=i<sc.frames.length&&sc.frames[i]>=2;if(miss&&start<0)start=i;else if(!miss&&start>=0){if(i-start>=6)runs.push({a:sc.a+start*GRID,b:sc.a+i*GRID});start=-1;}}return runs;}
function activeScore(){return s.mode==='singing'?s.live:traceShown()?s.trace.score:null;}
function activePoints(){return s.mode==='singing'?s.history:traceShown()?s.trace.points:[];}
function audioClock(){const c=s.ctx;if(!c)return 0;try{const t=c.getOutputTimestamp?.();if(t&&t.contextTime>0&&performance.now()-t.performanceTime<300)return Math.min(c.currentTime,t.contextTime+(performance.now()-t.performanceTime)/1000);}catch(_){}return c.currentTime;}
function now(){const tr=s.transport;if(!tr||!s.ctx)return s.pos;let t=tr.offset+(audioClock()-tr.when)*tr.speed;if(tr.loop&&t>=tr.loop.b){const len=tr.loop.b-tr.loop.a;t=tr.loop.a+((t-tr.loop.a)%len);}return clamp(t,tr.loop?Math.min(tr.offset,tr.loop.a):tr.offset,tr.end);}
function chooseRange(id){
 if(s.mode!=='idle'||s.busy||s.awaitFinish)return;clearTimeout(s.nextTimer);s.cancel++;s.rangeId=Number(id);
 if(s.rangeId===-1)return;
 const p=song.phrases.find(p=>p.id===s.rangeId);s.range=p?{a:p.a,b:p.b}:{a:0,b:song.duration};s.pos=s.range.a;s.history=[];s.current=null;setRangeScale();sync();
}
function setRange(a,b,id=-1){a=clamp(a,0,song.duration);b=clamp(b,0,song.duration);if(b-a<.5)return false;s.range={a,b};s.rangeId=id;if(s.transport?.loop){s.transport.loop={a,b};}sync();return true;}
function clearRange(){s.range={a:0,b:song.duration};s.rangeId=0;if(s.transport?.loop)s.transport.loop=null;sync();}
// ── Vertical scale: predictive, hysteretic, eased. ──
// The band comes from the target notes in the visible window plus a look-ahead, so the plot is already right before the
// notes arrive. The goal moves only when upcoming notes would leave an inner margin (grow, never shrink), or when the band
// could shrink by SCALE.shrinkMin semitones for SCALE.shrinkHold seconds; a change is then eased over SCALE.ease seconds and
// the next one waits SCALE.dwell seconds, except after an explicit seek. Voice enters through a percentile band of confident
// frames, so single glitches never drive the scale.
const SCALE={lookahead:4,dwell:2.5,shrinkHold:2,shrinkMin:3,ease:1,inner:.5,pad:1.5,minSpan:8,voiceMin:25,voiceTrail:2};
const sc={goalLo:48,goalHi:76,fromLo:48,fromHi:76,changedAt:-1e9,shrinkSince:null,lastEase:0};
function scaleZoom(){return Number($('scaleSelect').value)||1;}
function pointIndex(t){const a=song.points;let lo=0,hi=a.length;while(lo<hi){const m=(lo+hi)>>1;if(a[m][0]<t)lo=m+1;else hi=m;}return lo;}
// Pitch extremes of the drawn target between a and b: notes always; in contour view the contour too, but only where it stays
// near the notes (glitches at note edges are not a reason to rescale). Returns {vis, plan} for the visible window and the look-ahead.
function targetBands(v,opt){
 const o=opt.octave,plan=v.b+SCALE.lookahead;const acc=(band,m)=>{if(m<band.lo)band.lo=m;if(m>band.hi)band.hi=m;};
 const vis={lo:Infinity,hi:-Infinity},all={lo:Infinity,hi:-Infinity};
 for(const n of song.notes){if(n.ignored||n.b<v.a)continue;if(n.a>plan)break;const m=n.m+o;acc(all,m);if(n.a<=v.b)acc(vis,m);}
 if(opt.view==='contour'){const pts=song.points,near=2.5;for(let i=pointIndex(v.a);i<pts.length&&pts[i][0]<=plan;i++){const p=pts[i];if(p[1]===null)continue;const n=noteAt(p[0]);if(n?.ignored)continue;let m=p[1];if(n?.manual)m+=n.m-(n.originalM??n.m);m+=o;
   const band=p[0]<=v.b?vis:all;if(!(all.lo<=all.hi)||(m>=all.lo-near&&m<=all.hi+near)){acc(all,m);if(band===vis)acc(vis,m);}}}
 return{vis:vis.lo<=vis.hi?vis:null,plan:all.lo<=all.hi?all:null};
}
// Robust band of the singer's voice: 3rd–97th percentile of confident, loud enough frames. While singing only the trailing
// SCALE.voiceTrail seconds exist; in review the whole visible window counts.
function voiceBand(v,t){
 const pts=activePoints();if(!pts.length)return null;const a=s.mode==='singing'?t-SCALE.voiceTrail:v.a,b=s.mode==='singing'?t:v.b,vals=[];
 let lo=0,hi=pts.length;while(lo<hi){const m=(lo+hi)>>1;if(pts[m].songT<a)lo=m+1;else hi=m;}
 for(let i=lo;i<pts.length;i++){const p=pts[i];if(p.songT>b)break;if(Number.isFinite(p.m)&&p.confidence>=.8&&p.db>=prefs.gate)vals.push(p.m);}
 if(vals.length<SCALE.voiceMin)return null;vals.sort((x,y)=>x-y);return{lo:vals[Math.floor((vals.length-1)*.03)],hi:vals[Math.ceil((vals.length-1)*.97)]};
}
function mergeBand(x,y){return !x?y:!y?x:{lo:Math.min(x.lo,y.lo),hi:Math.max(x.hi,y.hi)};}
function goalFor(need){const z=scaleZoom(),pad=SCALE.pad/z,minSpan=SCALE.minSpan/z;const lo=need.lo-pad,hi=need.hi+pad,span=Math.max(minSpan,hi-lo),mid=(lo+hi)/2;return{lo:mid-span/2,hi:mid+span/2};}
function fitsGoal(band){return band.lo>=sc.goalLo+SCALE.inner&&band.hi<=sc.goalHi-SCALE.inner;}
// First look-ahead note outside the goal: does it reach the visible window before an eased change could finish?
function entrySoon(v,opt){const o=opt.octave;for(const n of song.notes){if(n.ignored||n.b<v.b)continue;if(n.a>v.b+SCALE.lookahead)break;const m=n.m+o;if(m<sc.goalLo+SCALE.inner||m>sc.goalHi-SCALE.inner)return n.a-v.b<=SCALE.ease+.25;}return false;}
function setGoal(g,wall,instant){sc.fromLo=instant?g.lo:s.rangeLo;sc.fromHi=instant?g.hi:s.rangeHi;sc.goalLo=g.lo;sc.goalHi=g.hi;sc.changedAt=instant?-1e9:wall;sc.shrinkSince=null;if(instant){s.rangeLo=g.lo;s.rangeHi=g.hi;}s.dirty=true;}
function planScale(v,t,wall,instant){
 const opt=effective(),tb=targetBands(v,opt),voice=voiceBand(v,t),plan=mergeBand(tb.plan,voice),vis=mergeBand(tb.vis,voice);
 if(!plan)return;// nothing to frame here: keep what is on screen
 if(instant){setGoal(goalFor(plan),wall,true);return;}
 if(!fitsGoal(plan)){// grow to cover the upcoming notes; a note already in the visible window cannot wait for the dwell
  const pad=SCALE.pad/scaleZoom(),need={lo:Math.min(plan.lo,sc.goalLo+pad),hi:Math.max(plan.hi,sc.goalHi-pad)};
  if((vis&&!fitsGoal(vis))||wall-sc.changedAt>=SCALE.dwell||entrySoon(v,opt))setGoal(goalFor(need),wall,false);return;}
 const cand=goalFor(plan);
 if((sc.goalHi-sc.goalLo)-(cand.hi-cand.lo)>=SCALE.shrinkMin){if(sc.shrinkSince===null)sc.shrinkSince=wall;else if(wall-sc.shrinkSince>=SCALE.shrinkHold&&wall-sc.changedAt>=SCALE.dwell)setGoal(cand,wall,false);}
 else sc.shrinkSince=null;
}
function easeScale(wall){if(s.rangeLo===sc.goalLo&&s.rangeHi===sc.goalHi){sc.lastEase=wall;return;}
 if(wall-(sc.lastEase||0)>.25&&!reduced.matches){sc.fromLo=s.rangeLo;sc.fromHi=s.rangeHi;sc.changedAt=wall;}// frames were not running: resume the glide from the current plot
 sc.lastEase=wall;const p=reduced.matches?1:clamp((wall-sc.changedAt)/SCALE.ease,0,1),e=p*p*(3-2*p);
 if(p>=1){s.rangeLo=sc.goalLo;s.rangeHi=sc.goalHi;}else{s.rangeLo=sc.fromLo+(sc.goalLo-sc.fromLo)*e;s.rangeHi=sc.fromHi+(sc.goalHi-sc.fromHi)*e;}s.dirty=true;}
// Explicit seek or a new selection: frame the new place at once.
function setRangeScale(){planScale(view(s.pos),s.pos,performance.now()/1000,true);}
// Every frame during playback: plan ahead, then glide.
function followRange(v,t){const wall=performance.now()/1000;planScale(v,t,wall,false);easeScale(wall);}
function populateSong(){
 $('songTitle').textContent=song.title;$('artistName').textContent=song.artist||'';$('songMeta').textContent=fmt(song.duration)+(prefs.speed!==1?' · '+prefs.speed+'×':'');document.title='Luma · '+song.title;$('timeEnd').textContent=fmt(song.duration);$('timelineWrap').setAttribute('aria-valuemax',song.duration.toFixed(1));
 $('qualityCoverage').textContent=(song.metrics?.comparablePercentOfTrack??0)+'% надійної розмітки';
 const supplied=String(song.method).includes('User-supplied stems');
 $('stemWarning').textContent=supplied?'Готові stems надано користувачем. Мелодія визначена автоматично і потребує перевірки.':song.neuralSeparation?'Доріжки розділено Demucs. Це оцінені stems: залишковий голос і інструменти можливі.':'Наближене DSP-розділення, не нейромодель. Передній план може містити інструменти; «мінус» може містити голос.';
 $('qualityDetails').textContent='Метод: '+song.method+'. '+(supplied?'Використано готові stems. ':song.neuralSeparation?'Нейророзділення виконане локально. ':'Ваги нейромоделі в середовищі підготовки завантажити не вдалося. ')+(song.metrics?.candidateSeconds??0)+' с із '+Math.round(song.duration)+' с мають кандидата мелодії; '+(song.metrics?.comparableSeconds??0)+' с пройшли суворіші евристики. Автоматична розмітка не пройшла ручної музичної перевірки.';
 const sel=$('phraseSelect');sel.replaceChildren(new Option('Вся пісня · '+fmt(song.duration),'0'));for(const p of song.phrases)sel.add(new Option(p.label+' · '+fmt(p.a)+'–'+fmt(p.b),String(p.id)));sel.add(new Option('Власний фрагмент','-1'));
 // Whole song by default; the user draws a loop region on the timeline when a fragment is wanted.
 s.rangeId=0;s.range={a:0,b:song.duration};s.pos=clamp(song.initialTime||0,0,song.duration);
 if(!validLyrics(song.lyrics))song.lyrics=[];$('lyricsBtn').hidden=!song.lyrics.length;
 baseNotes=structuredClone(song.notes);loadEdits();setRangeScale();sync();
}
function sync(){
 s.dirty=true;const active=s.mode!=='idle',singing=s.mode==='singing';$('singBtn').disabled=s.awaitFinish||(s.busy&&s.busyFor!=='sing');$('singBtn').classList.toggle('recording',singing);$('singLabel').textContent=s.busy?(s.busyFor==='sing'?'Скасувати':'Співати'):singing?'Завершити':'Співати';$('singBtn').querySelector('use').setAttribute('href',singing?'#i-stop':'#i-mic');
 $('listenBtn').disabled=s.busy||s.awaitFinish;$('listenLabel').textContent=s.busy&&s.busyFor==='listen'?'Готую…':singing?'Стоп':active?'Пауза':'Слухати';$('listenBtn').setAttribute('aria-label',singing?'Зупинити запис':active?'Пауза':'Слухати пісню');$('listenIcon').setAttribute('href',singing?'#i-stop':active?'#i-pause':'#i-play');$('stopBtn').disabled=!active&&!s.busy&&!s.awaitFinish;
 for(const id of ['phraseSelect','prevPhrase','nextPhrase','octave','latency','tolerance','rangeA','rangeB','applyRange','editBtn','applyEdit','importBtn','exportTarget','saveVerify','resetEdits','revokeVerify'])$(id).disabled=active||s.busy||s.awaitFinish;
 $('speedSelect').disabled=s.busy||s.awaitFinish||s.mode==='singing'||s.mode==='review';
 $('phraseSelect').value=String(s.rangeId);$('speedSelect').value=String(prefs.speed);$('loopBtn').setAttribute('aria-pressed',String(prefs.loop));$('octave').value=String(prefs.octave);$('gate').value=prefs.gate;$('gateOut').textContent=prefs.gate+' dBFS';$('latency').value=prefs.latency;$('tolerance').value=prefs.tolerance;$('rangeA').value=s.range.a.toFixed(2);$('rangeB').value=s.range.b.toFixed(2);
 $('backGain').value=Math.round(prefs.back*100);$('foreGain').value=Math.round(prefs.fore*100);$('backGainOut').textContent=Math.round(prefs.back*100)+'%';$('foreGainOut').textContent=Math.round(prefs.fore*100)+'%';
 const cr=customRange();$('rangeText').textContent=cr?(s.rangeId>0?'Фрагмент '+String(s.rangeId).padStart(2,'0'):'Повтор')+' '+fmt(s.range.a)+'–'+fmt(s.range.b):'Вся пісня · тягни під хвилею, щоб виділити повтор';$('clearRange').hidden=!cr;$('rangeText').classList.toggle('on',cr);
 for(const b of document.querySelectorAll('[data-level]')){b.classList.toggle('active',b.dataset.level===prefs.level);b.setAttribute('aria-pressed',String(b.dataset.level===prefs.level));b.disabled=s.mode==='singing'||s.busy||s.awaitFinish;}$('levelSeg').title='Коридор ±'+levelOpt().tolerance+'¢ · '+levelLabel(levelOpt());
 $('vocalBtn').setAttribute('aria-pressed',String(prefs.vocal));$('vocalLabel').textContent=prefs.vocal?'Вокал':'Мінус';$('vocalBtn').title=prefs.vocal?'Оригінальний вокал звучить · натисни, щоб лишити тільки мінус (V)':'Тільки мінус: чуєш лише себе · натисни, щоб повернути вокал (V)';
 const pt=punchTarget();if(!singing&&!s.busy)$('singLabel').textContent=pt?'Перезаписати з '+fmt(s.pos):'Співати';$('singBtn').title=pt?'Перезаписати спробу '+String(pt.id).padStart(2,'0')+' від '+fmt(s.pos)+' (R)':'Записати нову спробу (R)';
 $('newTakeBtn').hidden=!traceShown();$('newTakeBtn').disabled=active||s.busy||s.awaitFinish;
 $('onboarding').hidden=s.takes.length>0||active;
 $('undoPunchBtn').hidden=!s.undoPunch;$('undoPunchBtn').disabled=active||s.busy||s.awaitFinish;
 $('repeatMissBtn').hidden=!traceShown()||!missRuns(s.trace.score).length;$('repeatMissBtn').disabled=active||s.busy||s.awaitFinish;
 $('levelContext').textContent=traceShown()?'Наступна спроба':'Рівень';
 const ver=rangeVerified();$('qualityPill').textContent=ver?'Фрагмент підтверджений':'Чернетка мелодії';$('qualityBtn').classList.toggle('ok',ver);$('confirmTarget').checked=ver;
 $('micToggle').textContent=s.stream?'Вимкнути мікрофон':'Увімкнути лише мікрофон';$('micToggle').disabled=active||s.busy||s.awaitFinish;$('takesPanel').hidden=!s.takes.length;$('takesPanel').dataset.open=prefs.takesOpen?'1':'0';$('takesToggle').setAttribute('aria-expanded',String(prefs.takesOpen));$('takesCount').textContent=s.takes.length;
 $('lyricsBtn').setAttribute('aria-pressed',String(prefs.lyrics));
 for(const b of document.querySelectorAll('[data-view]')){b.classList.toggle('active',b.dataset.view===prefs.view);b.setAttribute('aria-pressed',String(b.dataset.view===prefs.view));b.disabled=active||s.busy||s.awaitFinish;}
 const rv=traceShown();$('reviewBar').hidden=!rv;if(rv){const t=s.trace.take,runs=missRuns(s.trace.score);$('reviewLabel').textContent='Спроба '+String(t.id).padStart(2,'0');const pct=scorePct(s.trace.score);$('reviewPct').textContent=pct===null?'—':pct+'%';$('missCount').textContent=runs.length?runs.length+' '+plural(runs.length,'промах','промахи','промахів'):'без промахів';$('prevMiss').disabled=$('nextMiss').disabled=!runs.length||s.mode!=='idle';}
 $('chartWrap').classList.toggle('scrub',s.mode!=='singing');
 updateStatus();requestDraw();
}
function plural(n,a,b,c){const m=n%10,h=n%100;return m===1&&h!==11?a:m>=2&&m<=4&&(h<10||h>=20)?b:c;}
function activeErrorMode(){return s.mode!=='idle'||s.busy||s.awaitFinish;}
function updateStatus(){const el=$('status');el.className='status';let t='ГОТОВО ДО СПІВУ';if(s.busy)t='ПІДГОТОВКА';else if(s.awaitFinish)t='ЗБЕРЕЖЕННЯ';else if(s.mode==='singing'){t='ЗАПИС';el.classList.add('rec');}else if(s.mode==='listen'){t='СЛУХАЄМО ЦІЛЬ';el.classList.add('live');}else if(s.mode==='review'){t='ТВІЙ ЗАПИС';el.classList.add('live');}else if(s.stream){t='МІКРОФОН УВІМКНЕНО';el.classList.add('live');}if(!activeErrorMode()&&!$('errorBanner').hidden)t='ПОТРІБНА УВАГА';$('statusText').textContent=t;}
async function ensureContext(){
 if(s.ctx&&s.ctx.state!=='closed'){await s.ctx.resume();return s.ctx;}
 const C=window.AudioContext||window.webkitAudioContext;if(!C)throw Error('Потрібен браузер із Web Audio.');s.ctx=new C({latencyHint:'interactive'});await s.ctx.resume();
 const master=s.ctx.createGain();master.gain.value=.85;master.connect(s.ctx.destination);const back=s.ctx.createGain(),fore=s.ctx.createGain(),voice=s.ctx.createGain();back.connect(master);fore.connect(master);voice.connect(master);voice.gain.value=.9;s.gains={master,back,fore,voice};applyMix();
 s.ctx.onstatechange=()=>{if(s.ctx?.state!=='running'&&s.mode!=='idle'){stopTransport('context');error('Аудіопотік призупинився. Спробу завершено; продовж із цієї позиції.');}};return s.ctx;
}
// "Голос" off = pure backing (мінус): the original vocal stem is muted while listening and while singing
function applyMix(){if(s.gains){s.gains.back.gain.setTargetAtTime(prefs.back,s.ctx.currentTime,.02);s.gains.fore.gain.setTargetAtTime(prefs.vocal?prefs.fore:0,s.ctx.currentTime,.02);}savePrefs();}
async function decodeBase64(data){if(typeof data!=='string'||data.length<40)throw Error('У пакеті бракує аудіодоріжки.');const raw=atob(data),a=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)a[i]=raw.charCodeAt(i);return s.ctx.decodeAudioData(a.buffer);}
async function buffers(speed){const key=String(speed);if(s.bufs.has(key))return s.bufs.get(key);const a=assets[key];if(!a)throw Error('Цю швидкість не підготовлено.');const [back,fore]=await Promise.all([decodeBase64(a.backing),decodeBase64(a.foreground)]);if(Math.abs(back.duration-fore.duration)>.1)throw Error('Доріжки мають різну довжину: пакет потребує повторної підготовки.');const b={back,fore};s.bufs.set(key,b);return b;}
const MIC_ERRORS={NotAllowedError:'Доступ до мікрофона заборонено. Дозволь його для цієї сторінки через значок налаштувань біля адреси, потім натисни «Співати» знову. Прослуховування доступне.',NotFoundError:'Мікрофон не знайдено. Підключи пристрій, вибери його в налаштуваннях і спробуй знову. Поки можна слухати пісню.',NotReadableError:'Мікрофон зайнятий або недоступний. Перевір пристрій у системі та закрий програму, яка використовує його, потім спробуй знову.',OverconstrainedError:'Обраний мікрофон недоступний. У налаштуваннях вибери системний або інший підключений пристрій.'};
function micError(e){return MIC_ERRORS[e.name]||e.message||'Не вдалося підключити мікрофон.';}
function errorKind(e){return e&&(e.name in MIC_ERRORS||e.mic)?'mic':'';}
async function releaseMic(){s.micGeneration++;const w=s.worker,c=s.capture,m=s.micSource,stream=s.stream;s.worker=null;s.capture=null;s.micSource=null;s.stream=null;try{c?.disconnect();c?.port.close();m?.disconnect();}catch(_){}stream?.getTracks().forEach(t=>{t.onended=null;t.stop();});w?.terminate();s.current=null;s.liveSmooth=null;$('micState').textContent='Мікрофон вимкнено';sync();}
async function ensureMic(token){
 if(location.protocol==='file:')throw Object.assign(Error('Запис голосу працює через Luma Studio. Відкрий цю пісню з бібліотеки Studio та натисни «Співати».'),{mic:true});
 if(s.stream&&s.worker)return true;
 if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia)throw Object.assign(Error('Мікрофон потребує окремої вкладки і localhost / HTTPS. Вбудований перегляд може його блокувати.'),{mic:true});
 const ctx=await ensureContext();const stream=await navigator.mediaDevices.getUserMedia({audio:{deviceId:prefs.mic?{exact:prefs.mic}:undefined,channelCount:1,echoCancellation:false,noiseSuppression:false,autoGainControl:false},video:false});
 if(token!==s.cancel){stream.getTracks().forEach(t=>t.stop());return false;}const gen=++s.micGeneration;s.stream=stream;
 const wu=URL.createObjectURL(new Blob([$('worker-source').textContent],{type:'text/javascript'})),cu=URL.createObjectURL(new Blob([$('capture-source').textContent],{type:'text/javascript'}));
 try{
  s.worker=new Worker(wu);await ctx.audioWorklet.addModule(cu);if(token!==s.cancel){await releaseMic();return false;}
  const worker=s.worker;const ready=new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Аудіоаналізатор не відповідає.')),6000);worker.onmessage=e=>{if(gen!==s.micGeneration)return;if(e.data.type==='ready'){clearTimeout(timer);resolve();}handleWorker(e.data);};worker.onerror=e=>{clearTimeout(timer);reject(Error(e.message||'Помилка аналізатора'));if(s.mode==='singing'){stopTransport('worker');error('Аудіоаналізатор зупинився. Незавершений запис може бути втрачений.');}};});
  const node=new AudioWorkletNode(ctx,'luma-capture',{numberOfInputs:1,numberOfOutputs:1,outputChannelCount:[1]}),src=ctx.createMediaStreamSource(stream),channel=new MessageChannel();s.capture=node;s.micSource=src;
  worker.postMessage({type:'connect',sampleRate:ctx.sampleRate,port:channel.port1},[channel.port1]);node.port.postMessage({type:'connect',port:channel.port2},[channel.port2]);worker.postMessage({type:'settings',gate:prefs.gate});src.connect(node);node.connect(ctx.destination);await ready;
  stream.getTracks().forEach(t=>t.onended=()=>{stopTransport('device');error('Мікрофон від’єднався. Поточну спробу завершено.','mic');setTimeout(()=>releaseMic(),500);});
  $('micState').textContent=stream.getAudioTracks()[0]?.label||'Мікрофон увімкнено';populateMics();requestDraw();return true;
 }catch(e){await releaseMic();throw e;}finally{URL.revokeObjectURL(wu);URL.revokeObjectURL(cu);}
}
async function populateMics(){try{const ds=await navigator.mediaDevices.enumerateDevices(),el=$('micSelect');el.replaceChildren(new Option('Системний мікрофон',''));for(const d of ds)if(d.kind==='audioinput'&&d.deviceId&&!['default','communications'].includes(d.deviceId))el.add(new Option(d.label||'Мікрофон',d.deviceId));if([...el.options].some(o=>o.value===prefs.mic))el.value=prefs.mic;}catch(_){}}
function handleWorker(m){
 if(m.type==='pitch'){
  s.computeMs=m.computeMs;s.windowMs=m.windowMs;const raw=m.f?69+12*Math.log2(m.f/440):null;let smooth=raw;
  if(raw!==null&&s.liveSmooth!==null&&m.t-s.lastSmoothT<.12&&Math.abs(raw-s.liveSmooth)<4.5)smooth=s.liveSmooth+.65*(raw-s.liveSmooth);
  s.liveSmooth=smooth;s.lastSmoothT=m.t;const tr=s.transport;const st=tr?tr.offset+(m.t-tr.when-prefs.latency/1000)*tr.speed:s.pos;
  s.current={...m,raw,m:smooth,songT:st};
  if(s.mode==='singing'&&tr&&st>=tr.offset&&st<=tr.end)s.history.push({...s.current});s.dirty=true;requestDraw();
 }else if(m.type==='finished')onFinished(m);
 else if(m.type==='error'){error(m.message);stopTransport('worker');}
}
function clearSources(){clearTimeout(s.endTimer);s.endTimer=null;for(const n of s.sources){n.onended=null;try{n.stop();n.disconnect();}catch(_){}}s.sources=[];}
function addSource(buffer,gain,when,offset,duration,onended){const n=s.ctx.createBufferSource();n.buffer=buffer;n.connect(gain);n.onended=onended||null;const len=Math.min(duration,buffer.duration-offset);if(len>0){n.start(when,Math.max(0,offset),len);s.sources.push(n);}return n;}
function capacity(){
 const size=s.takes.reduce((a,t)=>a+t.blob.size,0)+(s.undoPunch?.before.blob.size||0),seg=nextSegment(true),punch=seg.punch;
 // Undo retains the old full WAV. Reserve the full merged replacement, even for a short selected punch region.
 const duration=punch?Math.max(punch.duration,(seg.end-punch.a)/punch.speed):Math.max(0,(seg.end-seg.start)/seg.speed);
 const bytes=44+Math.ceil(duration*(punch?.sampleRate||s.ctx?.sampleRate||48000))*2;
 return (punch||s.takes.length<10)&&size+bytes<100*1024*1024;
}
// Punch-in: with a take on screen and the playhead inside it (same speed), "Співати" re-records that take from here instead of starting a new one.
function punchTarget(){if(!traceShown()||s.mode!=='idle')return null;const t=s.trace.take;return t.speed===prefs.speed&&s.pos>=t.a-.01&&s.pos<t.endSong-.15?t:null;}
function wavHeaderBuf(count,rate){const b=new ArrayBuffer(44),v=new DataView(b);const text=(o,t)=>{for(let i=0;i<t.length;i++)v.setUint8(o+i,t.charCodeAt(i));};text(0,'RIFF');v.setUint32(4,36+count*2,true);text(8,'WAVE');text(12,'fmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);v.setUint32(24,rate,true);v.setUint32(28,rate*2,true);v.setUint16(32,2,true);v.setUint16(34,16,true);text(36,'data');v.setUint32(40,count*2,true);return b;}
// Splice a freshly recorded segment into an existing take: old audio before the punch point, new audio, then whatever old audio lies beyond the new end.
function mergeTake(old,meta,m){
 const sr=m.sampleRate;if(sr!==old.sampleRate)return null;const speed=old.speed;const oldCount=Math.floor((old.blob.size-44)/2);
 const cut=clamp(Math.round((meta.a-old.a)/speed*sr),0,oldCount);const newCount=Math.floor((m.blob.size-44)/2);const newEndSong=meta.a+newCount/sr*speed;
 const parts=[old.blob.slice(44,44+cut*2),m.blob.slice(44,44+newCount*2)];let total=cut+newCount;let tailStart=null;
 if(old.endSong>newEndSong+.02){tailStart=clamp(Math.round((newEndSong-old.a)/speed*sr),0,oldCount);parts.push(old.blob.slice(44+tailStart*2));total+=oldCount-tailStart;}
 const blob=new Blob([wavHeaderBuf(total,sr),...parts],{type:'audio/wav'});const offT=(meta.a-old.a)/speed;
 const strip=p=>({t:p.t,f:p.f,confidence:p.confidence,db:p.db,rms:p.rms,peak:p.peak});
 const points=[...old.points.filter(p=>p.songT<meta.a).map(strip),...m.points.map(p=>({...strip(p),t:p.t+offT}))];
 if(tailStart!==null)points.push(...old.points.filter(p=>p.songT>=newEndSong).map(strip));
 const duration=total/sr;const meta2={...meta,id:old.id,a:old.a,b:Math.max(old.b,meta.b),speed,startedAt:old.startedAt,punches:(old.punches||0)+1,lastPunchAt:meta.a};
 return {meta:meta2,m:{...m,id:old.id,blob,duration,start:0,end:duration,points,gap:0}};
}
// Where the next Listen or Sing pass runs, without touching state. The A–B fragment applies from inside it and from its
// end (a finished pass parks the playhead there); with the loop on, from anywhere; otherwise the song plays on to its end.
// A punch-in re-records the shown take from the playhead. capacity() reads this, startTransport() applies it.
function nextSegment(sing){
 const speed=prefs.speed,punch=sing?punchTarget():null;let pos=s.pos>=song.duration-.1?0:s.pos;
 if(punch)return{start:pos,end:Math.max(s.range.b,punch.endSong),speed,loop:null,punch};
 const cr=customRange(),atEnd=cr&&pos>=s.range.b-.1&&pos<=s.range.b+.25;
 if(cr&&(atEnd||prefs.loop&&(pos<s.range.a||pos>=s.range.b-.1)))pos=s.range.a;
 const inside=pos>=s.range.a-.01&&pos<s.range.b-.1;
 return inside?{start:Math.max(pos,s.range.a),end:s.range.b,speed,loop:!sing&&prefs.loop&&cr?{a:s.range.a,b:s.range.b}:null,punch:null}:{start:pos,end:song.duration,speed,loop:null,punch:null};
}
function takeMeta(offset,end,speed){const L=levelOpt();return{id:++s.takeCounter,a:offset,b:end,speed,octave:prefs.octave,view:prefs.view,tolerance:L.tolerance,slack:L.slack,ratio:L.ratio,octaveFree:L.octaveFree,level:L.level,latency:prefs.latency,referenceId:song.id,rangeId:s.rangeId,verified:structuredClone(s.verified),startedAt:new Date().toISOString()};}
function scheduleSources(b,when,offset,end,speed,loop,token){
 const duration=(end-offset)/speed;
 const back=addSource(b.back,s.gains.back,when,offset/speed,loop?b.back.duration-offset/speed:duration,loop?null:()=>naturalEnd(token)),fore=addSource(b.fore,s.gains.fore,when,offset/speed,loop?b.fore.duration-offset/speed:duration);
 if(loop)for(const n of [back,fore]){n.loop=true;n.loopStart=loop.a/speed;n.loopEnd=loop.b/speed;}
 return duration;}
async function startTransport(sing,quick=false){
 if(s.awaitFinish)return;if(s.busy){s.cancel++;s.busy=false;await releaseMic();sync();return;}
 if(s.mode!=='idle'){stopTransport('user');return;}
 clearTimeout(s.nextTimer);const token=++s.cancel;s.busy=true;s.busyFor=sing?'sing':'listen';$('errorBanner').hidden=true;sync();
 try{
  await ensureContext();if(sing&&!capacity())throw Error('Ліміт пам’яті: 10 спроб або 100 МіБ. Збережи й видали стару спробу перед новою.');
  if(sing&&!await ensureMic(token))return;
  const b=await buffers(prefs.speed);if(token!==s.cancel)return;await s.ctx.resume();
  const seg=nextSegment(sing),punch=seg.punch;if(sing&&!punch)s.trace=null;if(seg.start!==s.pos){s.pos=seg.start;setRangeScale();}// only a moved playhead is framed at once; otherwise the eased planner takes over
  const speed=seg.speed,when=s.ctx.currentTime+(sing?(quick?.6:2.1):.12),offset=seg.start,end=seg.end,loop=seg.loop;
  s.transport={token,when,offset,end,speed,loop};s.mode=sing?'singing':'listen';s.history=punch?punch.points.filter(p=>p.songT<offset).map(p=>({...p,raw:p.m})):[];s.current=null;s.liveSmooth=null;s.busy=false;s.live=null;
  const duration=scheduleSources(b,when,offset,end,speed,loop,token);
  if(sing){const lag=prefs.latency/1000,meta=takeMeta(offset,end,speed);if(punch){meta.punchInto=punch.id;s.trace=null;}s.pending.set(meta.id,meta);s.live=newScore(meta);s.worker.postMessage({type:'record',id:meta.id,start:when+lag,end:when+duration+lag});if(punch)say('Перезапис спроби '+punch.id+' від '+fmt(offset));}
  if(!loop)s.endTimer=setTimeout(()=>{if(s.transport?.token===token){if(s.mode==='singing'){s.worker?.postMessage({type:'stop',time:when+duration+prefs.latency/1000,reason:'end'});}else naturalEnd(token);}},(when-s.ctx.currentTime+duration+1.1)*1000);
  sync();say(sing?'Запис почнеться після відліку.':loop?'Повтор фрагмента без пауз.':'Відтворення.');
 }catch(e){if(token===s.cancel){error(micError(e),errorKind(e));await releaseMic();}}
 finally{if(token===s.cancel){s.busy=false;sync();}}
}
// Live seek while listening or reviewing: rebuild the sources at the new position on the same transport token.
function seekLive(t){
 const tr=s.transport;if(!tr||!s.ctx||s.mode==='singing')return;const speed=tr.speed;let end=tr.end,loop=tr.loop;
 if(s.mode==='review'){const tk=s.trace.take;t=clamp(t,tk.a,tk.endSong-.05);}else{t=clamp(t,0,song.duration-.05);const inside=t>=s.range.a-.01&&t<s.range.b-.1;if(!inside&&prefs.loop&&customRange()){prefs.loop=false;toast('Повтор вимкнено: позиція поза вибраним фрагментом.');}end=inside?s.range.b:song.duration;loop=inside&&prefs.loop&&customRange()?{a:s.range.a,b:s.range.b}:null;}
 clearSources();const b=s.bufs.get(String(speed));if(!b)return;const when=s.ctx.currentTime+.04;const token=tr.token;
 s.transport={token,when,offset:t,end,speed,loop};s.pos=t;
 if(s.mode==='review'){const tk=s.trace.take,off=t-tk.a,dur=tk.duration-off/speed;addSource(b.back,s.gains.back,when,t/speed,dur);addSource(b.fore,s.gains.fore,when,t/speed,dur);addSource(tk.buffer,s.gains.voice,when,off/speed,dur,()=>naturalEnd(token));}
 else{const duration=scheduleSources(b,when,t,end,speed,loop,token);if(!loop)s.endTimer=setTimeout(()=>{if(s.transport?.token===token)naturalEnd(token);},(when-s.ctx.currentTime+duration+1.1)*1000);}
 s.dirty=true;sync();
}
function naturalEnd(token){if(!s.transport||s.transport.token!==token)return;if(s.mode==='singing')return;const wasReview=s.mode==='review';s.pos=s.transport.end;clearSources();s.transport=null;s.mode='idle';sync();renderTakes();if(!wasReview&&prefs.loop&&customRange()&&s.pos>=s.range.b-.05)scheduleLoop(false);}
function scheduleLoop(sing){clearTimeout(s.nextTimer);const token=s.cancel;s.nextTimer=setTimeout(()=>{if(s.cancel!==token||!prefs.loop||s.mode!=='idle'||s.awaitFinish)return;s.pos=s.range.a;startTransport(sing,true);},60);}
function stopTransport(reason='user'){
 clearTimeout(s.nextTimer);s.cancel++;
 if(s.busy){s.busy=false;releaseMic();sync();return;}
 const active=s.transport,wasSing=s.mode==='singing';if(active)s.pos=now();clearSources();s.transport=null;s.mode='idle';$('countdown').hidden=true;
 if(wasSing&&s.worker){s.awaitFinish=true;s.worker.postMessage({type:'stop',time:s.ctx.currentTime,reason});setTimeout(()=>{if(s.awaitFinish){s.awaitFinish=false;s.pending.clear();s.live=null;error('Запис не відповів на завершення. Незавершена спроба могла не зберегтися.');releaseMic();sync();}},2500);}
 else if(reason==='worker')releaseMic();renderTakes();sync();
}
function analyzeTake(meta,points,duration){
 const opt={octave:meta.octave,view:meta.view,tolerance:meta.tolerance},out=[],errors=[];let targetTime=0,compared=0,inside=0;
 for(const p of points){const songT=meta.a+p.t*meta.speed,ref=targetAt(songT,opt),m=p.f?69+12*Math.log2(p.f/440):null;const cents=m!==null&&ref?(m-ref.m)*100:null;out.push({...p,songT,m,ref:ref?.m??null,eligible:!!ref?.ok&&!!ref?.verified,cents});}
 // Strict stats (verified target only): fixed-time-grid denominator keeps missing microphone frames visible in coverage.
 let cursor=0;const dt=.02;
 for(let t=0;t<duration;t+=dt){const ref=targetAt(meta.a+t*meta.speed,opt);if(!ref?.ok||!meta.verified.some(r=>meta.a+t*meta.speed>=r.a&&meta.a+t*meta.speed<=r.b))continue;targetTime+=dt;
  while(cursor+1<out.length&&out[cursor+1].t<=t)cursor++;let p=out[cursor];if(cursor+1<out.length&&Math.abs(out[cursor+1].t-t)<Math.abs(p.t-t))p=out[cursor+1];
  if(p&&Math.abs(p.t-t)<.05&&p.m!==null&&p.confidence>=.8){const e=Math.abs((p.m-ref.m)*100);errors.push(e);compared+=dt;if(e<=meta.tolerance)inside+=dt;}}
 errors.sort((a,b)=>a-b);
 // Target-match score over every drawn note (draft included): same engine as the live counter.
 const score=newScore(meta);scoreAdvance(score,out,meta.a+duration*meta.speed);
 return {points:out,score,stats:{targetTime,compared,coverage:targetTime?100*compared/targetTime:null,accuracy:compared?100*inside/compared:null,median:errors.length?errors[Math.floor(errors.length/2)]:null}};
}
function storeTake(meta,m){
 let replaced=null;
 if(meta.punchInto!==undefined){const old=s.takes.find(t=>t.id===meta.punchInto);const merged=old?mergeTake(old,meta,m):null;if(merged){meta=merged.meta;m=merged.m;replaced=old;}else{s.takeCounter++;meta={...meta,id:s.takeCounter};m={...m,id:meta.id};}}
 const a=analyzeTake(meta,m.points,m.duration);const take={...meta,...m,...a,saved:false,url:URL.createObjectURL(m.blob),endSong:meta.a+m.duration*meta.speed};
 if(replaced){clearUndoPunch();s.undoPunch={before:replaced,after:take};s.takes[s.takes.indexOf(replaced)]=take;}else s.takes.unshift(take);
 s.unsaved=true;s.trace={take,points:take.points,score:take.score};s.current=null;renderTakes();say(replaced?'Спробу '+String(take.id)+' перезаписано від '+fmt(meta.lastPunchAt)+'.':'Спробу '+String(take.id)+' збережено в пам’яті вкладки.');return take;
}
function clearUndoPunch(){if(s.undoPunch){URL.revokeObjectURL(s.undoPunch.before.url);s.undoPunch=null;}}
function undoPunch(){
 if(!s.undoPunch||s.mode!=='idle'||s.busy||s.awaitFinish)return;
 const {before,after}=s.undoPunch,index=s.takes.indexOf(after);if(index<0){clearUndoPunch();sync();return;}
 URL.revokeObjectURL(after.url);s.takes[index]=before;s.undoPunch=null;s.unsaved=s.takes.some(t=>!t.saved);
 s.trace={take:before,points:before.points,score:before.score};s.pos=clamp(s.pos,before.a,before.endSong);setRangeScale();renderTakes();sync();toast('Попередню версію спроби відновлено.');
}
function onFinished(m){
 const meta=s.pending.get(m.id);if(!meta)return;
 if(s.mode==='singing'&&m.reason==='end'&&s.transport&&s.ctx){const end=s.transport.when+(s.transport.end-s.transport.offset)/s.transport.speed;if(s.ctx.currentTime<end-.01){setTimeout(()=>onFinished(m),(end-s.ctx.currentTime)*1000+20);return;}}
 s.pending.delete(m.id);const auto=s.mode==='singing'&&m.reason==='end'&&prefs.loop;s.awaitFinish=false;
 if(s.transport)s.pos=Math.min(s.transport.end,meta.a+m.duration*meta.speed);clearSources();s.transport=null;s.mode='idle';s.live=null;
 if(m.duration>.15&&m.blob.size>44)storeTake(meta,m);
 if(['discontinuity','late-start'].includes(m.reason))error('Розрив аудіопотоку: запис завершено, щоб не зсувати його відносно пісні.');
 if(s.resumeAt!==null){const t=s.resumeAt;s.resumeAt=null;s.pos=t;sync();startTransport(true,true);return;}// seek during singing: new take from the new spot
 const canLoop=auto&&customRange();if(canLoop&&capacity())scheduleLoop(true);else{if(canLoop)toast('Повтор зупинено: досягнуто ліміт пам’яті. Збережи WAV.');releaseMic();}sync();
}
function download(blob,filename){const u=URL.createObjectURL(blob),a=document.createElement('a');a.href=u;a.download=filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),15000);}
function takeFilename(t,ext){return 'Luma_'+song.title.replace(/[^\p{L}\p{N}_-]+/gu,'_')+'_take_'+String(t.id).padStart(2,'0')+'.'+ext;}
function saveWav(t){download(t.blob,takeFilename(t,'wav'));t.saved=true;s.unsaved=s.takes.some(t=>!t.saved);renderTakes();}
function saveCSV(t){const header='take_seconds,song_seconds,frequency_hz,midi,target_midi,cents_from_target,eligible_target,match_state,yin_periodicity,dbfs,speed,target_octave,mic_shift_ms\n';const rows=t.points.map(p=>[p.t.toFixed(5),p.songT.toFixed(5),p.f??'',p.m??'',p.ref??'',p.cents??'',p.eligible?1:0,frameState(t.score,p.songT),p.confidence,p.db,t.speed,t.octave,t.latency].join(','));download(new Blob([header+rows.join('\n')],{type:'text/csv;charset=utf-8'}),takeFilename(t,'csv'));}
function selectTrace(t){if(s.mode!=='idle'||s.busy||s.awaitFinish)return;s.trace={take:t,points:t.points,score:t.score};s.pos=clamp(s.pos,t.a,t.endSong);if(s.pos<=t.a||s.pos>=t.endSong)s.pos=t.a;setRangeScale();renderTakes();sync();}
function closeTrace(){s.trace=null;setRangeScale();renderTakes();sync();}
// Re-score a take under a new view or octave: audio and pitch points stay, only the comparison rules change.
function rescoreTake(t,patch){Object.assign(t,patch,analyzeTake({...t,...patch},t.points,t.duration));if(s.trace?.take===t)s.trace={take:t,points:t.points,score:t.score};renderTakes();}
function renderTakes(){const root=$('takesList');root.replaceChildren();for(const t of s.takes){
 const el=document.createElement('div');el.className='take'+(s.trace?.take===t?' current':'');const playing=s.trace?.take===t&&s.mode==='review';const play=document.createElement('button');play.className='play';play.innerHTML=icon(playing?'pause':'play');play.ariaLabel=(playing?'Зупинити':'Прослухати')+' спробу '+t.id;play.title=playing?'Зупинити':'Прослухати свій голос поверх мінусу';play.onclick=()=>playTake(t);
 const title=document.createElement('button');title.className='take-title';title.title='Показати слід цієї спроби на графіку · перемотай усередину і натисни «Дописати», щоб перезаписати з цього місця';title.innerHTML='Спроба '+String(t.id).padStart(2,'0')+' · '+fmt(t.a)+'–'+fmt(t.endSong)+'<small>'+t.speed+'× · '+levelLabel(t.score.opt)+' · '+(t.octave?(t.octave>0?'+':'')+t.octave+' пт · ':'')+(t.sampleRate/1000).toFixed(1)+' kHz'+(t.punches?' · перезаписів: '+t.punches:'')+(t.saved?' · збережено':'')+'</small>';title.onclick=()=>selectTrace(t);
 const st=document.createElement('div');st.className='take-stats';const pct=scorePct(t.score);const vals=[['Збіг',pct===null?'—':pct+'%',pct===null?'у фрагменті немає намальованих нот':'влучання '+(t.score.hit*GRID).toFixed(1)+' с із '+(t.score.target*GRID).toFixed(1)+' с цілі · ±'+t.tolerance+'¢ '+levelLabel(t.score.opt)+' · тиша = промах']];
 if(t.stats.targetTime>.1)vals.push(['У коридорі',t.stats.accuracy===null?'—':Math.round(t.stats.accuracy)+'%','підтверджена ціль · серед порівняних точок'],['Покриття',Math.round(t.stats.coverage||0)+'%','порівняно '+t.stats.compared.toFixed(1)+' с із '+t.stats.targetTime.toFixed(1)+' с підтвердженої цілі'],['Медіана |Δ|',t.stats.median===null?'—':Math.round(t.stats.median)+'¢','']);
 for(const [label,value,tip]of vals){const span=document.createElement('span'),b=document.createElement('strong');b.textContent=value;span.append(b,document.createTextNode(label));span.title=tip;st.append(span);}
 if(t.stats.targetTime<=.1){const n=document.createElement('span');n.className='none';n.textContent='Попередня оцінка за чернеткою';n.title='Прослухай накладання та перевір мелодію-ціль. Сам факт знайденої ноти не доводить, що це головний вокал.';st.append(n);}
 const actions=document.createElement('div');actions.className='take-actions';for(const [label,fn,tip]of[['WAV',()=>saveWav(t),'Зберегти WAV'],['CSV',()=>saveCSV(t),'Зберегти CSV зі слідом нот і станом кожної точки'],['×',()=>removeTake(t),'Видалити спробу']]){const b=document.createElement('button');b.textContent=label;b.title=tip;b.setAttribute('aria-label',tip);b.onclick=fn;actions.append(b);}
 el.append(play,title,st,actions);root.append(el);
 }$('takesPanel').hidden=!s.takes.length;$('takesCount').textContent=s.takes.length;}
function removeTake(t){if(s.mode!=='idle'||s.awaitFinish||s.busy){toast('Спочатку зупини відтворення або запис.');return;}if(!t.saved&&!confirm('Спробу ще не завантажено. Видалити її з пам’яті?'))return;if(s.undoPunch?.after===t)clearUndoPunch();s.takes=s.takes.filter(x=>x.id!==t.id);URL.revokeObjectURL(t.url);if(s.trace?.take===t)s.trace=null;s.unsaved=s.takes.some(t=>!t.saved);renderTakes();sync();}
async function playTake(t){
 if(s.busy||s.awaitFinish)return;if(s.mode!=='idle'){stopTransport('user');renderTakes();return;}clearTimeout(s.nextTimer);const token=++s.cancel;s.busy=true;s.busyFor='review';sync();
 try{await ensureContext();const b=await buffers(t.speed);if(!t.buffer)t.buffer=await s.ctx.decodeAudioData(await t.blob.arrayBuffer());if(token!==s.cancel)return;
  const changed=s.trace?.take!==t||s.pos<t.a||s.pos>=t.endSong-1;s.trace={take:t,points:t.points,score:t.score};if(s.pos<t.a||s.pos>=t.endSong-1)s.pos=t.a;// under a second left: replay from the start
  const off=s.pos-t.a,when=s.ctx.currentTime+.15,dur=t.duration-off/t.speed;s.transport={token,when,offset:s.pos,end:t.endSong,speed:t.speed,loop:null};s.mode='review';
  addSource(b.back,s.gains.back,when,s.pos/t.speed,dur);addSource(b.fore,s.gains.fore,when,s.pos/t.speed,dur);addSource(t.buffer,s.gains.voice,when,off/t.speed,dur,()=>{naturalEnd(token);});if(changed)setRangeScale();
 }catch(e){error(e.message);}finally{if(token===s.cancel){s.busy=false;sync();renderTakes();}}
}
function resize(){const r=$('chartWrap').getBoundingClientRect(),q=$('timelineWrap').getBoundingClientRect();W=r.width;H=r.height;TW=q.width;TH=q.height;DPR=Math.min(window.devicePixelRatio||1,2);canvas.width=Math.round(W*DPR);canvas.height=Math.round(H*DPR);g.setTransform(DPR,0,0,DPR,0,0);tl.width=Math.round(TW*DPR);tl.height=Math.round(TH*DPR);tg.setTransform(DPR,0,0,DPR,0,0);if(W>0&&H>0){s.dirty=false;draw(now());}else s.dirty=true;requestDraw();}
function lyricLane(){return 0;}// words are drawn on the melody itself (see drawWords); no separate lane
function bounds(){const narrow=W<720,short=!narrow&&H<330;const hud=narrow?180:short?68:136;return{left:narrow?40:48,right:W-14,top:hud+8,bottom:H-(narrow?128:short?52:92),lane:0,laneTop:hud};}
// Words ride the melody: each word sits just above the target pitch at its own moment; colliding labels stack upward, none is dropped.
function drawWords(t,v,x,y,b,opt){
 if(!prefs.lyrics||!song.lyrics.length)return;const font=(W<720?'12px ':'13px ')+getComputedStyle(document.body).getPropertyValue('--sans');g.font=font;g.textAlign='left';g.textBaseline='alphabetic';
 const placed=[];const rowH=17;
 for(const line of song.lyrics){if(line.a>v.b)break;if(line.b<v.a)continue;
  for(const w of line.words){if(w.a>v.b||w.b<v.a-.5)continue;const xx=x(w.a),tw=g.measureText(w.w).width;
   // anchor: median target pitch inside the word, else the nearest target within 0.6 s, else the plot centre line
   const ms=[];for(let q=w.a;q<=w.b+1e-6;q+=.04){const r=targetAt(q,opt);if(r)ms.push(r.m);}
   let m=null;if(ms.length){ms.sort((p,q)=>p-q);m=ms[ms.length>>1];}else{for(let d=.04;d<=.6&&m===null;d+=.04){const r=targetAt(w.a-d,opt)||targetAt(w.b+d,opt);if(r)m=r.m;}}
   let yy=(m===null?(b.top+b.bottom)/2:clamp(y(m),b.top+rowH,b.bottom))-9;
   for(let k=0;k<6;k++){const hit=placed.some(p=>xx<p.x1+6&&xx+tw>p.x0-6&&Math.abs(yy-p.y)<rowH-1);if(!hit)break;yy-=rowH;}
   if(yy<b.top+4)yy=b.top+4;placed.push({x0:xx,x1:xx+tw,y:yy});
   const on=t>=w.a&&t<w.b+.08,past=t>=w.b;g.globalAlpha=(w.c??1)<.5?.7:1;
   g.fillStyle='#0e131cd0';g.fillRect(xx-2,yy-11,tw+4,14);// halo so the word stays legible over lines
   g.fillStyle=on?'#eef6ff':past?'#a0aec3':'#c1cbdc';g.fillText(w.w,xx,yy);if(on){g.fillStyle='#a1eed8';g.fillRect(xx,yy+2,tw,1.5);}
   g.globalAlpha=1;}}
}
function view(t){const span=W<550?7:W<1100?10:12,behind=span*.34;return{a:t-behind,b:t+span-behind,span};}
function tracePaths(points,x,y,frames,upTo){
 const paths={1:new Path2D(),2:new Path2D(),0:new Path2D()};let last=null;
 for(const p of points){if(p.songT>upTo)break;if(p.m===null||p.m===undefined){last=null;continue;}
  if(last&&p.songT-last.songT<=.11&&Math.abs(p.m-last.m)<=3.5){let st=frameState(frames,(p.songT+last.songT)/2);if(st===3)st=2;const pa=paths[st];pa.moveTo(x(last.songT),y(last.m));pa.lineTo(x(p.songT),y(p.m));}
  last=p;}
 return paths;
}
function draw(t){
 if(!g)return;const b=bounds(),v=view(t);followRange(v,t);const x=a=>b.left+(a-v.a)/v.span*(b.right-b.left),y=m=>b.bottom-(m-s.rangeLo)/(s.rangeHi-s.rangeLo)*(b.bottom-b.top);const rowH=(b.bottom-b.top)/(s.rangeHi-s.rangeLo);
 g.fillStyle='#0e131c';g.fillRect(0,0,W,H);const mono=getComputedStyle(document.body).getPropertyValue('--mono'),sans=getComputedStyle(document.body).getPropertyValue('--sans');
 // piano-roll rows: black-key rows darker, C rows outlined, labels every semitone when rows are tall enough
 const labelStep=rowH>=11?1:2;g.textAlign='right';g.textBaseline='middle';g.font='10px '+mono;
 for(let n=Math.ceil(s.rangeLo);n<=s.rangeHi;n++){const yy=y(n),pc=(n%12+12)%12;if(BLACK.has(pc)){g.fillStyle='#ffffff05';g.fillRect(b.left,y(n+.5),b.right-b.left,rowH);}
  g.strokeStyle=pc===0?'#b7c9e02a':'#b7c9e00e';g.lineWidth=1;g.beginPath();g.moveTo(b.left,y(n+.5));g.lineTo(b.right,y(n+.5));g.stroke();
  if(n%labelStep===0){g.fillStyle=pc===0?'#aab8cf':BLACK.has(pc)?'#55627a':'#78869e';g.fillText(name(n),b.left-7,yy);}}
 g.textAlign='center';g.font='9px '+mono;const tstep=v.span>10?2:1;
 for(let a=Math.ceil(v.a);a<v.b;a++){const xx=x(a);g.strokeStyle=a%tstep===0?'#b7c9e010':'#b7c9e007';g.beginPath();g.moveTo(xx,b.top);g.lineTo(xx,b.bottom+4);g.stroke();if(a>=0&&a%tstep===0){g.fillStyle='#64728a';g.fillText(fmt(a),xx,b.bottom+(W<720?12:14));}}
 const nowX=x(t);g.fillStyle='#060b1218';g.fillRect(b.left,b.top,nowX-b.left,b.bottom-b.top);
 // loop region edges on the plot
 if(customRange()){for(const edge of [s.range.a,s.range.b]){const xe=x(edge);if(xe<b.left||xe>b.right)continue;g.strokeStyle='#b4a2eb70';g.lineWidth=1;g.setLineDash([4,4]);g.beginPath();g.moveTo(xe,b.top);g.lineTo(xe,b.bottom);g.stroke();g.setLineDash([]);}
  g.fillStyle='#b4a2eb08';const xa=clamp(x(s.range.a),b.left,b.right),xb=clamp(x(s.range.b),b.left,b.right);if(xb>xa)g.fillRect(xa,b.top,xb-xa,b.bottom-b.top);}
 g.save();g.beginPath();g.rect(b.left,b.top,b.right-b.left,b.bottom-b.top);g.clip();const opt=effective(),sc=activeScore(),pts=activePoints();
 const tolH=Math.max(4,opt.tolerance/100*rowH*2),barH=clamp(rowH*.72,6,24);
 if(opt.view==='notes'){
  for(const n of song.notes){if(n.a>v.b)break;if(n.b<v.a)continue;const xx=x(n.a),ww=Math.max(2,x(n.b)-xx),yy=y(n.m+opt.octave);const ok=(n.ok||n.manual)&&!n.ignored;
   const kind=n.ignored?null:noteKind(sc,n.id);const cur=t>=n.a&&t<n.b,curState=cur?frameState(sc,t-.03):0;
   // tolerance corridor behind the bar
   if(!n.ignored){g.fillStyle=kind==='hit'?'#a1eed80f':kind?'#c9707a0e':ok?'#b4a2eb12':'#9a94b40a';g.fillRect(xx,yy-tolH/2,ww,tolH);}
   let fill,stroke,dash=[],glyph='';
   if(n.ignored){fill='#7f89900a';stroke='#6b768740';dash=[2,3];}
   else if(kind==='hit'){fill=cur&&curState===1?'#a1eed885':'#a1eed848';stroke='#c2f8ea';glyph='✓';}
   else if(kind==='miss'||kind==='silent'){fill='#c9707a22';stroke='#c9707aa8';dash=kind==='silent'?[2,3]:[];glyph='×';}
   else{fill=ok?'#b4a2eb34':'#9a94b418';stroke=ok?'#c6b7f2d0':'#a8a3c088';dash=ok?[]:[3,3];if(cur&&curState===1){fill='#a1eed870';stroke='#d5fff3';}else if(cur&&curState===2){fill='#c9707a40';stroke='#e29aa3';}}
   g.globalAlpha=n.b<t&&!kind?.55:1;g.fillStyle=fill;g.beginPath();g.roundRect(xx,yy-barH/2,ww,barH,Math.min(3,ww/2));g.fill();g.strokeStyle=stroke;g.lineWidth=cur?1.6:1;g.setLineDash(dash);g.stroke();g.setLineDash([]);
   if(cur&&curState===1&&s.mode!=='idle'){g.shadowColor='#a1eed8';g.shadowBlur=14;g.strokeStyle='#d5fff3';g.stroke();g.shadowBlur=0;}
   if(ww>=30&&barH>=9&&!n.ignored){g.font=(barH>=12?'10px ':'9px ')+mono;g.textAlign='left';g.fillStyle=kind==='hit'?'#0d1f1a':kind?'#ffd9dd':ok?'#f1ecff':'#b8b4cc';g.fillText(glyph?glyph+' '+name(n.m+opt.octave):name(n.m+opt.octave),xx+5,yy+.5);}
   else if(glyph&&ww>=12){g.font='9px '+mono;g.textAlign='center';g.fillStyle=kind==='hit'?'#0d1f1a':'#ffd9dd';g.fillText(glyph,xx+ww/2,yy+.5);}
  }g.globalAlpha=1;
 }else{
  let last=null;for(const p of song.points){if(p[0]<v.a-.03)continue;if(p[0]>v.b+.03)break;const r=targetAt(p[0],opt);if(!r){last=null;continue;}const pt={t:p[0],m:r.m,ok:r.ok};if(last&&pt.t-last.t<.05&&Math.abs(pt.m-last.m)<8){const st=frameState(sc,pt.t);g.beginPath();g.moveTo(x(last.t),y(last.m));g.lineTo(x(pt.t),y(pt.m));g.strokeStyle=st===1?'#a1eed8d0':st>=2?'#c9707ab0':pt.ok?'#b4a2ebb0':'#a39dc0a8';g.lineWidth=pt.ok?2.4:1.8;g.setLineDash(pt.ok?[]:[3,3]);g.stroke();g.setLineDash([]);}last=pt;}
  // Keep hit/miss meaning available without colour in contour mode as well.
  let lastMark=-Infinity;g.font='12px '+mono;g.textAlign='center';
  for(const n of song.notes){if(n.a>v.b)break;if(n.b<v.a||n.ignored)continue;const kind=noteKind(sc,n.id),xx=x((n.a+n.b)/2);if(!kind||xx-lastMark<18)continue;lastMark=xx;const yy=y(n.m+opt.octave)+16;g.fillStyle='#0e131c';g.fillRect(xx-7,yy-9,14,15);g.fillStyle=kind==='hit'?'#bff7e8':'#ffd9dd';g.fillText(kind==='hit'?'✓':'×',xx,yy);}
 }
 // sung trace, coloured per 20 ms frame: mint = in corridor, subdued red = off target, dim = no target here
 if(pts.length){const review=s.mode!=='singing';const upTo=review?v.b+.1:t+.03;const paths=tracePaths(pts,x,y,sc,upTo);
  g.lineJoin='round';g.lineCap='round';
  const pass=(alpha)=>{g.globalAlpha=alpha;g.lineWidth=7;g.strokeStyle='#a1eed81c';g.stroke(paths[1]);g.strokeStyle='#c9707a18';g.stroke(paths[2]);g.lineWidth=2.2;g.strokeStyle='#bff7e8';g.stroke(paths[1]);g.strokeStyle='#d47f88';g.stroke(paths[2]);g.lineWidth=1.6;g.strokeStyle='#8fb5ad99';g.stroke(paths[0]);};
  if(review){// dim the part after the playhead so the eye follows the cursor
   g.save();g.beginPath();g.rect(b.left,b.top,nowX-b.left,b.bottom-b.top);g.clip();pass(1);g.restore();g.save();g.beginPath();g.rect(nowX,b.top,b.right-nowX,b.bottom-b.top);g.clip();pass(.45);g.restore();}
  else pass(1);g.globalAlpha=1;
  let p=null;if(!review){p=pts[pts.length-1];if(p&&(p.m===null||t-p.songT>=.2))p=null;}else{p=pointNear(pts,t,.06);}
  if(p&&p.m!==null&&p.m!==undefined){const xx=x(p.songT),yy=y(p.m),st=frameState(sc,p.songT),c=st===1?'#b8f5e8':st>=2?'#e8a1aa':'#9fc7bf';g.fillStyle=(st>=2?'#c9707a':'#a1eed8')+'1c';g.beginPath();g.arc(xx,yy,11,0,Math.PI*2);g.fill();g.strokeStyle=c;g.lineWidth=1.4;g.beginPath();g.arc(xx,yy,5,0,Math.PI*2);g.stroke();g.fillStyle=c;g.beginPath();g.arc(xx,yy,2.5,0,Math.PI*2);g.fill();}
 }
 drawWords(t,v,x,y,b,opt);
 g.restore();
 g.strokeStyle='#e5eee540';g.lineWidth=1;g.setLineDash([2,5]);g.beginPath();g.moveTo(nowX,b.laneTop-8);g.lineTo(nowX,b.bottom);g.stroke();g.setLineDash([]);
 g.fillStyle='#a4bab9';g.font='8px '+sans;g.textAlign='center';g.textBaseline='middle';g.fillText('ЗАРАЗ',nowX,b.laneTop-14);
 drawTimeline(t);
}
function pointNear(a,t,tol){let lo=0,hi=a.length;while(lo<hi){const m=(lo+hi)>>1;if(a[m].songT<t)lo=m+1;else hi=m;}let p=a[Math.min(lo,a.length-1)];const prev=a[lo-1];if(prev&&(!p||Math.abs(prev.songT-t)<Math.abs(p.songT-t)))p=prev;return p&&Math.abs(p.songT-t)<=tol?p:null;}
function drawTimeline(t){tg.fillStyle='#0c1018';tg.fillRect(0,0,TW,TH);const w=song.waveform||[],x=v=>v/song.duration*TW,WH=TH-LOOP_LANE,cr=customRange();
 // loop lane under the wave: drag here (or Shift-drag anywhere) to set the A–B region
 tg.fillStyle='#ffffff05';tg.fillRect(0,WH,TW,LOOP_LANE);
 if(cr){tg.fillStyle='#b4a2eb14';tg.fillRect(x(s.range.a),0,x(s.range.b)-x(s.range.a),WH);tg.fillStyle=prefs.loop?'#b4a2eb':'#b4a2eb80';tg.fillRect(x(s.range.a),WH+3,Math.max(2,x(s.range.b)-x(s.range.a)),LOOP_LANE-6);
  for(const e of [s.range.a,s.range.b]){tg.fillStyle='#e6dcff';tg.fillRect(x(e)-2,WH+1,4,LOOP_LANE-2);}}
 else{tg.fillStyle='#a4b2c8';tg.font='11px '+getComputedStyle(document.body).getPropertyValue('--sans');tg.textAlign='left';tg.textBaseline='middle';tg.fillText('повтор: тягни тут',6,WH+LOOP_LANE/2);}
 if(traceShown()){const tk=s.trace.take;tg.fillStyle='#a1eed81a';tg.fillRect(x(tk.a),WH-3,x(tk.endSong)-x(tk.a),3);for(const r of missRuns(s.trace.score)){tg.fillStyle='#c9707a';tg.fillRect(x(r.a),WH-3,Math.max(1.5,x(r.b)-x(r.a)),3);}}
 for(let i=0;i<w.length;i++){const xx=i/w.length*TW,hh=Math.max(1,w[i]*(WH-7));tg.strokeStyle=i/w.length*song.duration<t?'#92c8bc':'#54637a80';tg.lineWidth=1;tg.beginPath();tg.moveTo(xx,(WH-4-hh)/2);tg.lineTo(xx,(WH-4+hh)/2);tg.stroke();}tg.fillStyle='#c4eeea';tg.fillRect(x(t)-.7,0,1.4,WH);
 $('timelineWrap').setAttribute('aria-valuenow',t.toFixed(1));}
function lyricAt(t){let cur=null,next=null;for(const l of song.lyrics){if(t>=l.a-.25&&t<=l.b+.5){cur=l;break;}if(l.a>t){next=l;break;}}return {cur,next};}
function renderLyric(t){const el=$('lyricNow');if(!prefs.lyrics||!song.lyrics.length){if(s.lyricKey!==''){s.lyricKey='';el.replaceChildren();}return;}
 const {cur,next}=lyricAt(t);let key='',line=cur;if(cur){let on=-1;for(let i=0;i<cur.words.length;i++){const w=cur.words[i];if(t>=w.a&&t<w.b+.08)on=i;}key='c'+cur.a+':'+on+':'+cur.words.filter(w=>t>=w.b).length;}
 else if(next&&next.a-t<4){line=next;key='n'+next.a;}
 if(key===s.lyricKey)return;s.lyricKey=key;el.replaceChildren();if(!line)return;
 for(const w of line.words){const sp=document.createElement('span');sp.textContent=w.w+' ';sp.className=line===next?'soon':t>=w.a&&t<w.b+.08?'on':t>=w.b?'past':'';el.append(sp);}
}
function updateReadout(t){
 let p=s.current;const review=traceShown();if(review)p=pointNear(s.trace.points,t,.06);
 const live=p&&p.m!==null&&p.m!==undefined&&(review||s.ctx&&s.ctx.currentTime-(p.t||0)<.23);
 $('liveNote').innerHTML=noteHTML(live?p.m:null);$('liveNote').classList.toggle('empty',!live);$('liveDesc').textContent=live?words[(Math.round(p.m)%12+12)%12]+(review?' · запис':''):review?'Тут ти мовчав':s.stream?'Заспівай зручну ноту':'Час заспівати';$('liveFreq').textContent=live?(p.f.toFixed(1)+' Гц'):review?'Спроба '+String(s.trace.take.id).padStart(2,'0'):s.stream?'Слухаю мікрофон':'Мікрофон вимкнено';
 const opt=effective(),target=targetAt(t,opt),ref=p?.songT!==undefined?targetAt(p.songT,opt):target;$('targetNote').textContent=target?name(target.m):'—';let text='Тут ціль не визначена',delta=null;if(target)text=target.ok?'Слухай. Потім повтори.':'Невпевнена ціль';if(live&&ref){delta=centsOff(p.raw??p.m,ref.m,opt);text=(ref.ok?'':'≈ ')+(delta>0?'+':'')+Math.round(delta)+' ¢'+(opt.octaveFree&&Math.abs((p.raw??p.m)-ref.m)>=6?' · інша октава':'')+(!ref.verified?' · чернетка':'');}
 const inTol=delta!==null&&Math.abs(delta)<=opt.tolerance;$('deviation').textContent=text;$('deviation').style.color=delta===null?'#94a0b3':inTol?'#a1eed8':'#d99aa2';$('needle').style.opacity=delta===null?0:1;$('needle').style.left=clamp(50+(delta||0)/2,0,100)+'%';$('needle').style.background=delta!==null&&!inTol?'#d47f88':'#a1eed8';$('liveNote').classList.toggle('miss',delta!==null&&!inTol&&!!ref);
 $('level').style.width=p&&!review?clamp((p.db+60)/60*100,0,100)+'%':'0%';$('level').style.background=p?.peak>.99?'#f3a1b5':'#a1eed8';
 // live target-match: hit frames ÷ frames with any drawn target, tolerance from the attempt itself
 const sc=activeScore(),pct=scorePct(sc),pe=$('matchPct'),de=$('matchDetail');$('scoreLabel').textContent=sc?'Попередній збіг із мелодією':'Збіг із мелодією';pe.classList.remove('good','low');
 if(sc&&pct!==null){pe.textContent=pct+'%';if(pct>=70)pe.classList.add('good');else if(pct<40)pe.classList.add('low');de.textContent='Влучання '+(sc.hit*GRID).toFixed(1)+' с із '+(sc.target*GRID).toFixed(1)+' с цілі · ±'+sc.opt.tolerance+'¢ '+levelLabel(sc.opt)+(sc.sung<sc.target?' · тиша = промах':'')+(rangeVerified()?'':' · чернетка');}
 else if(sc){pe.textContent='—';de.textContent=s.mode==='singing'?'Чекаю на першу намальовану ноту…':'У цій спробі не було намальованих нот';}
 else{pe.textContent='—';de.textContent=s.mode==='listen'?'Слухаємо ціль · збіг рахується тільки під час співу':'Заспівай — рахую по намальованих нотах · '+levelLabel(levelOpt())+' ±'+levelOpt().tolerance+'¢';}
 $('timeNow').textContent=fmt(t);if(s.transport&&s.ctx.currentTime<s.transport.when&&s.mode==='singing'){$('countdown').hidden=false;$('countNumber').textContent=Math.ceil(s.transport.when-s.ctx.currentTime);}else $('countdown').hidden=true;
 renderLyric(t);
 if($('settingsDialog').open)$('diagnostics').textContent='YIN · '+(s.ctx?(s.ctx.sampleRate/1000).toFixed(1)+' kHz':'мікрофон вимкнено')+'\nВікно аналізу: '+s.windowMs.toFixed(1)+' мс\nОбчислення останнього кадру: '+s.computeMs.toFixed(2)+' мс\nЦе не вимір повної затримки.\nКалібрування: ручний зсув '+prefs.latency+' мс';
}
function requestDraw(){if(!s.raf&&!document.hidden)s.raf=requestAnimationFrame(tick);}
function tick(wall){s.raf=0;const moving=s.mode!=='idle'||!!s.stream||s.busy;if(wall-s.lastDraw>=(reduced.matches?32:15)){const t=now(),wasDirty=s.dirty;
 if(s.mode==='singing'&&s.live&&s.transport)scoreAdvance(s.live,s.history,Math.min(t-.18*s.transport.speed,s.transport.end));
 if(wasDirty||moving){s.dirty=false;draw(t);s.lastDraw=wall;}if(wall-s.lastUI>55||wasDirty){updateReadout(t);s.lastUI=wall;}}if(moving||s.dirty)requestDraw();}
function modal(id){$(id).showModal();if(id==='settingsDialog')populateMics();if(id==='qualityDialog')$('confirmTarget').checked=rangeVerified();}
function openEditor(){if(s.mode!=='idle')return;const ns=song.notes.filter(n=>n.b>s.range.a&&n.a<s.range.b);const sel=$('editNoteSelect');sel.replaceChildren();for(const n of ns)sel.add(new Option(fmt(n.a)+' · '+name(n.m)+' · '+(n.b-n.a).toFixed(2)+' с',String(n.id)));if(!ns.length){toast('У цьому фрагменті немає нот для редагування. Обери інший фрагмент або підготуй кращу ціль.');return;}const near=ns.find(n=>n.b>s.pos)||ns[0];selectEdit(near.id);sel.value=String(near.id);modal('editDialog');}
function selectEdit(id){const n=song.notes.find(n=>n.id===+id);if(!n)return;s.edit=structuredClone(n);$('editNoteName').textContent=name(s.edit.m);$('editStart').value=n.a;$('editEnd').value=n.b;$('editIgnore').checked=!!n.ignored;}
function exportTarget(){const data={...song,verified:s.verified};download(new Blob([JSON.stringify(data)],{type:'application/json'}),'Luma_'+song.title+'_target.json');}
function validateSong(d){return d&&d.schema==='luma.song.v1'&&typeof d.title==='string'&&d.title.length<200&&Number.isFinite(d.duration)&&d.duration>0&&d.duration<=600&&Number.isFinite(d.hop)&&d.hop>.001&&d.hop<.25&&Array.isArray(d.points)&&d.points.length<300001&&d.points.length>0&&d.points.every(p=>Array.isArray(p)&&Number.isFinite(p[0])&&(p[1]===null||Number.isFinite(p[1])&&p[1]>=24&&p[1]<=108))&&validNotes(d.notes,d.duration)&&Array.isArray(d.phrases)&&d.phrases.length<1001&&d.phrases.every(p=>Number.isFinite(p.a)&&Number.isFinite(p.b)&&p.a>=0&&p.b<=d.duration&&p.b>p.a);}
async function importFile(file){if(!file)return;if(file.size>100*1024*1024){error('Пакет завеликий: максимум 100 МіБ.');return;}try{const d=JSON.parse(await file.text());const packed=d.schema==='luma.pack.v1',newSong=packed?d.song:d;if(!validateSong(newSong))throw Error('Непідтримуваний формат цілі. Потрібен target.json або готовий .luma.json, не сире аудіо.');if(s.unsaved&&!confirm('Перед заміною пісні збережи WAV. Продовжити й видалити спроби з вкладки?'))return;
 if(!packed){if(Math.abs(newSong.duration-song.duration)>.1||newSong.title!==song.title||(newSong.sourceId&&song.sourceId&&newSong.sourceId!==song.sourceId))throw Error('Ціль належить іншому аудіо. Імпортуй повний підготовлений пакет.');if(!validLyrics(newSong.lyrics))newSong.lyrics=song.lyrics;}
 else{if(!d.assets?.['1']?.backing||!d.assets?.['1']?.foreground)throw Error('У пакеті відсутні аудіодоріжки.');assets=d.assets;s.bufs.clear();}
 stopTransport('import');await releaseMic();s.takes.forEach(t=>URL.revokeObjectURL(t.url));clearUndoPunch();s.takes=[];s.unsaved=false;s.trace=null;s.history=[];song=newSong;song.notes.sort((a,b)=>a.a-b.a);song.points.sort((a,b)=>a[0]-b[0]);populateSong();if(Array.isArray(newSong.verified)){s.verified=newSong.verified.filter(r=>Number.isFinite(r.a)&&Number.isFinite(r.b)&&r.a>=0&&r.b<=song.duration);saveEdits();}renderTakes();sync();toast('Ціль імпортовано. Перевір мелодію перед тренуванням.');
 }catch(e){error(e.message||'Не вдалося прочитати пакет.');}}
function seekTo(t,keepRange){if(s.mode!=='idle'){applySeek(t);return;}clearTimeout(s.nextTimer);s.cancel++;s.pos=clamp(t,0,song.duration);s.history=[];s.current=null;setRangeScale();sync();}
// One entry point for every seek gesture: idle → move the playhead; listen/review → rebuild audio live; singing → close the take and restart from there.
function applySeek(t){t=clamp(t,0,song.duration);if(s.busy||s.awaitFinish)return;
 if(s.mode==='idle'){seekTo(t,true);return;}
 if(s.mode==='singing'){s.resumeAt=t;stopTransport('seek');return;}
 seekLive(t);}
function jumpMiss(dir){if(!traceShown()||s.mode!=='idle')return;const runs=missRuns(s.trace.score);if(!runs.length)return;const pos=s.pos;let r=dir>0?runs.find(r=>r.a>pos+.05):[...runs].reverse().find(r=>r.a<pos-.05);if(!r)r=dir>0?runs[0]:runs[runs.length-1];seekTo(r.a-.35);const i=runs.indexOf(r);$('missCount').textContent='промах '+(i+1)+' / '+runs.length;}
$('singBtn').onclick=()=>startTransport(true);$('listenBtn').onclick=()=>startTransport(false);$('stopBtn').onclick=()=>stopTransport();$('settingsBtn').onclick=()=>modal('settingsDialog');$('mixBtn').onclick=()=>modal('mixDialog');$('helpBtn').onclick=()=>modal('helpDialog');$('qualityBtn').onclick=()=>modal('qualityDialog');$('editBtn').onclick=openEditor;$('dismissError').onclick=()=>{$('errorBanner').hidden=true;updateStatus();};$('errorSettings').onclick=()=>modal('settingsDialog');
$('scaleSelect').onchange=()=>{setRangeScale();requestDraw();};
$('newTakeBtn').onclick=()=>{if(s.mode!=='idle'||s.busy||s.awaitFinish)return;closeTrace();startTransport(true);};$('undoPunchBtn').onclick=undoPunch;
$('repeatMissBtn').onclick=()=>{if(!traceShown()||s.mode!=='idle'||s.busy||s.awaitFinish)return;const runs=missRuns(s.trace.score),r=runs.find(r=>r.b>s.pos)||runs[0];if(!r)return;const a=Math.max(0,r.a-.6),b=Math.min(song.duration,r.b+.8);closeTrace();setRange(a,b);prefs.loop=true;s.pos=a;sync();startTransport(false);};
function markRange(which){if(s.busy||s.awaitFinish)return;const t=now();const ok=which==='a'?setRange(t,Math.max(s.range.b,t+.5)):setRange(Math.min(s.range.a,t-.5),t);if(ok)toast((which==='a'?'Початок':'Кінець')+' фрагмента: '+fmt(t));}
$('markA').onclick=()=>markRange('a');$('markB').onclick=()=>markRange('b');$('rangeSettings').onclick=()=>{modal('settingsDialog');$('rangeA').focus();};$('prevMiss').onclick=()=>jumpMiss(-1);$('nextMiss').onclick=()=>jumpMiss(1);$('closeReview').onclick=closeTrace;$('takesToggle').onclick=()=>{prefs.takesOpen=!prefs.takesOpen;savePrefs();sync();};$('lyricsBtn').onclick=()=>{prefs.lyrics=!prefs.lyrics;savePrefs();s.lyricKey='~';resize();sync();};
for(const b of document.querySelectorAll('[data-close]'))b.onclick=()=>$(b.dataset.close).close();
$('loopBtn').onclick=()=>{prefs.loop=!prefs.loop;if(!prefs.loop)clearTimeout(s.nextTimer);if(prefs.loop&&!customRange())toast('Виділи фрагмент: тягни під хвилею або клавіші A / B під час прослуховування.');
 if(s.mode==='listen'&&s.transport){const t=now();seekLive(prefs.loop&&customRange()&&(t<s.range.a||t>=s.range.b-.1)?s.range.a:t);}sync();};$('speedSelect').onchange=()=>{prefs.speed=Number($('speedSelect').value);$('songMeta').textContent=fmt(song.duration)+(prefs.speed!==1?' · '+prefs.speed+'×':'');if(s.mode==='listen'){const t=now();stopTransport('speed');s.pos=t;startTransport(false);}sync();};
$('phraseSelect').onchange=()=>{if($('phraseSelect').value==='-1'){s.rangeId=-1;modal('settingsDialog');sync();}else chooseRange($('phraseSelect').value);};
function adjacent(dir){const opts=[...$('phraseSelect').options].filter(o=>+o.value>=0),idx=opts.findIndex(o=>+o.value===s.rangeId),j=clamp(idx+dir,0,opts.length-1);chooseRange(opts[j].value);}
$('prevPhrase').onclick=()=>adjacent(-1);$('nextPhrase').onclick=()=>adjacent(1);$('clearRange').onclick=()=>{clearRange();toast('Повтор знято: вся пісня.');};
$('vocalBtn').onclick=()=>{prefs.vocal=!prefs.vocal;applyMix();sync();toast(prefs.vocal?'Оригінальний вокал увімкнено.':'Тільки мінус: оригінальний вокал вимкнено.');};
for(const b of document.querySelectorAll('[data-level]'))b.onclick=()=>{prefs.level=b.dataset.level;prefs.tolerance=LEVELS[prefs.level].tolerance;savePrefs();sync();toast('Рівень: '+LEVELS[prefs.level].label+' · коридор ±'+prefs.tolerance+'¢');};
// timeline: click/drag on the wave seeks (live while playing); drag in the loop lane or Shift-drag sets the A–B region; handles are draggable
const tlw=$('timelineWrap');const tlTime=e=>{const r=tlw.getBoundingClientRect();return clamp((e.clientX-r.left)/r.width,0,1)*song.duration;};
tlw.addEventListener('pointerdown',e=>{if(e.button!==0||s.busy||s.awaitFinish)return;const r=tlw.getBoundingClientRect(),t=tlTime(e),lane=e.clientY-r.top>r.height-LOOP_LANE,px=r.width/song.duration;tlw.setPointerCapture(e.pointerId);
 const nearA=customRange()&&Math.abs((t-s.range.a)*px)<7,nearB=customRange()&&Math.abs((t-s.range.b)*px)<7;
 if(lane&&(nearA||nearB)){s.tlDrag={kind:'handle',which:nearA?'a':'b'};}
 else if(lane||e.shiftKey){s.tlDrag={kind:'range',anchor:t,moved:false};}
 else{s.tlDrag={kind:'seek',last:0};s.pos=t;s.dirty=true;requestDraw();}});
tlw.addEventListener('pointermove',e=>{const d=s.tlDrag;if(!d)return;const t=tlTime(e);
 if(d.kind==='seek'){s.pos=t;s.dirty=true;requestDraw();if(s.mode!=='idle'&&performance.now()-d.last>150){d.last=performance.now();applySeek(t);}}
 else if(d.kind==='handle'){const a=d.which==='a'?Math.min(t,s.range.b-.5):s.range.a,b=d.which==='b'?Math.max(t,s.range.a+.5):s.range.b;setRange(a,b);}
 else{d.moved=true;setRange(Math.min(d.anchor,t),Math.max(d.anchor,t));}});
const tlUp=e=>{const d=s.tlDrag;if(!d)return;s.tlDrag=null;const t=tlTime(e);
 if(d.kind==='seek')applySeek(t);else if(d.kind==='range'&&!d.moved){applySeek(t);}else{if(s.mode==='idle'&&(s.pos<s.range.a||s.pos>s.range.b))seekTo(s.range.a,true);sync();say('Повтор '+fmt(s.range.a)+'–'+fmt(s.range.b));}};
tlw.addEventListener('pointerup',tlUp);tlw.addEventListener('pointercancel',tlUp);
// drag / wheel on the stage scrubs time (live while listening), so a recorded trace can be inspected note by note
const stage=$('chartWrap');stage.addEventListener('pointerdown',e=>{if(s.mode==='singing'||s.busy||e.button!==0||e.target.closest('button,select'))return;s.scrub={x:e.clientX,pos:now(),moved:false,last:0};stage.setPointerCapture(e.pointerId);});
stage.addEventListener('pointermove',e=>{if(!s.scrub)return;const b=bounds(),v=view(0),pxPerSec=(b.right-b.left)/v.span,dx=e.clientX-s.scrub.x;if(Math.abs(dx)>2)s.scrub.moved=true;if(s.scrub.moved){const t=clamp(s.scrub.pos-dx/pxPerSec,0,song.duration);if(s.mode==='idle'){s.pos=t;s.dirty=true;requestDraw();}else if(performance.now()-s.scrub.last>150){s.scrub.last=performance.now();applySeek(t);}s.scrub.target=t;}});
const endScrub=e=>{if(!s.scrub)return;const {moved,target}=s.scrub;s.scrub=null;if(moved)applySeek(target??s.pos);};stage.addEventListener('pointerup',endScrub);stage.addEventListener('pointercancel',endScrub);
stage.addEventListener('wheel',e=>{if(s.mode==='singing')return;e.preventDefault();const d=(Math.abs(e.deltaX)>Math.abs(e.deltaY)?e.deltaX:e.deltaY)/120;const t=clamp((s.wheelPos??now())+d*.5,0,song.duration);s.wheelPos=t;if(s.mode==='idle'){s.pos=t;s.dirty=true;requestDraw();}clearTimeout(s.wheelTimer);s.wheelTimer=setTimeout(()=>{const p=s.wheelPos;s.wheelPos=null;applySeek(p);},120);},{passive:false});
$('gate').oninput=()=>{prefs.gate=+$('gate').value;s.worker?.postMessage({type:'settings',gate:prefs.gate});savePrefs();sync();};$('octave').onchange=()=>{prefs.octave=+$('octave').value;if(traceShown())rescoreTake(s.trace.take,{octave:prefs.octave});savePrefs();setRangeScale();sync();};
$('latency').onchange=()=>{const v=+$('latency').value;if(!Number.isFinite(v))return;prefs.latency=clamp(v,-500,1000);savePrefs();sync();};
$('tolerance').onchange=()=>{const v=+$('tolerance').value;if(!Number.isFinite(v))return;prefs.tolerance=clamp(v,10,100);prefs.level=Object.keys(LEVELS).find(k=>LEVELS[k].tolerance===prefs.tolerance)||'custom';savePrefs();sync();};
$('micSelect').onchange=()=>{prefs.mic=$('micSelect').value;if(s.stream)releaseMic();};$('micToggle').onclick=async()=>{if(s.stream){await releaseMic();return;}if(s.busy)return;const token=++s.cancel;s.busy=true;s.busyFor='mic';sync();try{await ensureMic(token);}catch(e){error(micError(e),errorKind(e));}finally{if(token===s.cancel){s.busy=false;sync();}}};
$('applyRange').onclick=()=>{const a=+$('rangeA').value,b=+$('rangeB').value;if(!Number.isFinite(a)||!Number.isFinite(b)||a<0||b>song.duration||b-a<.5){toast('Початок і кінець мають бути в межах пісні; довжина — від 0.5 с.');return;}setRange(a,b);s.pos=a;s.history=[];sync();toast('Фрагмент встановлено.');};
for(const [id,key]of[['backGain','back'],['foreGain','fore']])$(id).oninput=()=>{prefs[key]=+$(id).value/100;$(id+'Out').textContent=Math.round(prefs[key]*100)+'%';applyMix();};$('originalMix').onclick=()=>{prefs.back=.75;prefs.fore=.75;applyMix();sync();};
for(const b of document.querySelectorAll('[data-view]'))b.onclick=()=>{prefs.view=b.dataset.view;if(traceShown())rescoreTake(s.trace.take,{view:prefs.view});savePrefs();s.dirty=true;sync();};
$('saveVerify').onclick=()=>{if($('confirmTarget').checked){s.verified.push({...s.range});toast('Підтверджено тільки вибраний фрагмент.');}else s.verified=s.verified.filter(r=>r.b<s.range.a||r.a>s.range.b);saveEdits();$('qualityDialog').close();sync();};$('revokeVerify').onclick=()=>{s.verified=s.verified.filter(r=>r.b<s.range.a||r.a>s.range.b);saveEdits();$('qualityDialog').close();sync();};
$('editNoteSelect').onchange=()=>selectEdit($('editNoteSelect').value);for(const b of document.querySelectorAll('[data-delta]'))b.onclick=()=>{if(!s.edit)return;s.edit.m=clamp(s.edit.m+Number(b.dataset.delta),24,108);$('editNoteName').textContent=name(s.edit.m);};
$('applyEdit').onclick=()=>{if(!s.edit)return;const a=+$('editStart').value,b=+$('editEnd').value;if(!Number.isFinite(a)||!Number.isFinite(b)||a<0||b>song.duration||b-a<.04){toast('Перевір межі ноти: мінімум 0.04 с, у межах пісні.');return;}if(song.notes.some(n=>n.id!==s.edit.id&&n.a<b-.001&&n.b>a+.001)){toast('Ця нота перекриває сусідню. Спочатку зміни її межі.');return;}const original=song.notes.find(n=>n.id===s.edit.id);s.edit.originalM=original.originalM??original.m;Object.assign(original,s.edit,{a,b,manual:true,ok:true,n:Math.round(s.edit.m),ignored:$('editIgnore').checked});song.notes.sort((a,b)=>a.a-b.a);s.verified=[];saveEdits();setRangeScale();$('editDialog').close();sync();};
$('resetEdits').onclick=()=>{if(!confirm('Скинути всі правки до автоматичної чернетки?'))return;song.notes=structuredClone(baseNotes);s.verified=[];saveEdits();$('editDialog').close();setRangeScale();sync();};$('exportTarget').onclick=exportTarget;$('importBtn').onclick=()=>$('importFile').click();$('importFile').onchange=()=>{importFile($('importFile').files[0]);$('importFile').value='';};
window.addEventListener('keydown',e=>{if(e.ctrlKey||e.metaKey||e.altKey||e.repeat&&!['ArrowLeft','ArrowRight'].includes(e.code)||e.target.closest('input,select,textarea')||document.querySelector('dialog[open]'))return;
 if(e.code==='Space'&&!e.target.closest('button')){e.preventDefault();startTransport(false);}else if(e.code==='KeyR'){e.preventDefault();startTransport(true);}else if(e.code==='Escape')stopTransport();else if(e.key==='[')adjacent(-1);else if(e.key===']')adjacent(1);
 else if(e.code==='ArrowLeft'||e.code==='ArrowRight'){if(s.mode==='singing')return;e.preventDefault();applySeek(now()+(e.code==='ArrowRight'?1:-1)*(e.shiftKey?5:1));}else if(e.key===',')jumpMiss(-1);else if(e.key==='.')jumpMiss(1);
 else if(e.code==='KeyA')markRange('a');else if(e.code==='KeyB')markRange('b');else if(e.code==='KeyL'){$('loopBtn').click();}else if(e.code==='KeyV'){$('vocalBtn').click();}});
window.addEventListener('beforeunload',e=>{if(s.unsaved||s.mode==='singing'){e.preventDefault();e.returnValue='';}});
document.addEventListener('visibilitychange',()=>{if(document.hidden){if(s.raf)cancelAnimationFrame(s.raf);s.raf=0;if(s.mode!=='idle'){prefs.loop=false;stopTransport('hidden');toast('Вкладку приховано — відтворення зупинено.');}}else{s.dirty=true;requestDraw();}});
new ResizeObserver(resize).observe($('chartWrap'));new ResizeObserver(resize).observe($('timelineWrap'));
function silentWav(seconds,rate=48000){const n=Math.round(seconds*rate),b=new ArrayBuffer(44+n*2),v=new DataView(b);const text=(o,t)=>{for(let i=0;i<t.length;i++)v.setUint8(o+i,t.charCodeAt(i));};text(0,'RIFF');v.setUint32(4,36+n*2,true);text(8,'WAVE');text(12,'fmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);v.setUint32(24,rate,true);v.setUint32(28,rate*2,true);v.setUint16(32,2,true);v.setUint16(34,16,true);text(36,'data');v.setUint32(40,n*2,true);return new Blob([b],{type:'audio/wav'});}
window.Luma={diagnostics:()=>({mode:s.mode,busy:s.busy,pending:s.awaitFinish,time:now(),range:{...s.range},takeCount:s.takes.length,takes:s.takes.map(t=>({id:t.id,duration:t.duration,samples:t.duration*t.sampleRate,sampleRate:t.sampleRate,points:t.points.length,stats:t.stats,match:scorePct(t.score),frames:t.score.frames.length})),mic:!!s.stream,frequency:s.current?.f??null,computeMs:s.computeMs,windowMs:s.windowMs,contextState:s.ctx?.state,bufferDurations:[...s.bufs].map(([k,b])=>({speed:k,back:b.back.duration,fore:b.fore.duration}))}),targetAt:t=>targetAt(t),song:()=>({title:song.title,duration:song.duration,metrics:song.metrics,notes:song.notes.length,phrases:song.phrases.length,lyrics:song.lyrics.length}),
 // Test hooks: pure scoring and synthetic takes (silent WAV) so the review path can be exercised without a microphone.
 test:{GRID,score:(points,meta,upTo)=>{const sc=newScore(meta);scoreAdvance(sc,points,upTo??Infinity);return {target:sc.target,hit:sc.hit,sung:sc.sung,pct:scorePct(sc),frames:sc.frames,notes:[...sc.notes]};},
  injectTake:({a,b,speed=1,points,tolerance,octave=prefs.octave,view=prefs.view})=>{const duration=(b-a)/speed,meta={...takeMeta(a,b,speed),octave,view};if(tolerance!==undefined){meta.tolerance=tolerance;meta.level='custom';}const id=meta.id;const m={id,blob:silentWav(duration),sampleRate:48000,duration,start:0,end:duration,reason:'end',points:points.filter(p=>p.t>=0&&p.t<duration),gap:0};const t=storeTake(meta,m);s.pos=a;sync();return {id:t.id,pct:scorePct(t.score),frames:t.score.frames.length,points:t.points.length};},
  livePush:(p)=>{handleWorker({type:'pitch',computeMs:0,windowMs:64,...p});},
  seek:t=>seekTo(t,true),applySeek,selectTake:id=>{const t=s.takes.find(t=>t.id===id);if(t)selectTrace(t);},closeTrace,jumpMiss,draw:()=>{draw(now());updateReadout(now());},
  setLevel:l=>{document.querySelector('[data-level="'+l+'"]').click();return levelOpt();},viewWindow:t=>view(t),scale:()=>({...SCALE,goalLo:sc.goalLo,goalHi:sc.goalHi}),setRange,clearRange,levelOpt,centsOff,now,punchTarget:()=>punchTarget()?.id??null,gains:()=>s.gains?{back:s.gains.back.gain.value,fore:s.gains.fore.gain.value,vocal:prefs.vocal}:null,takes:()=>s.takes.map(t=>({id:t.id,a:t.a,endSong:t.endSong,duration:t.duration,bytes:t.blob.size,points:t.points.length,punches:t.punches||0,pct:scorePct(t.score)})),
  state:()=>({mode:s.mode,pos:s.pos,time:now(),trace:s.trace?{id:s.trace.take.id,points:s.trace.points.length,frames:s.trace.score.frames.length,pct:scorePct(s.trace.score),missRuns:missRuns(s.trace.score)}:null,liveScore:s.live?{target:s.live.target,hit:s.live.hit,sung:s.live.sung,pct:scorePct(s.live)}:null,history:s.history.length,matchText:$('matchPct').textContent,matchDetail:$('matchDetail').textContent,reviewHidden:$('reviewBar').hidden,missCount:$('missCount').textContent,lyric:$('lyricNow').textContent,liveNote:$('liveNote').textContent,deviation:$('deviation').textContent,range:{...s.range},rangeId:s.rangeId,rangeText:$('rangeText').textContent,loop:prefs.loop,transportLoop:s.transport?.loop??null,level:prefs.level,tolerance:prefs.tolerance,rangeLo:s.rangeLo,rangeHi:s.rangeHi}),
  fakeSing:({a,b,speed=1})=>{// enter singing mode without audio: transport clock driven by a fake context
   if(s.mode!=='idle')return false;const meta=takeMeta(a,b,speed),id=meta.id;if(!s.ctx)s.ctx={currentTime:0,state:'running',sampleRate:48000,resume(){},get _fake(){return true;}};const when=s.ctx.currentTime;s.transport={token:++s.cancel,when,offset:a,end:b,speed,loop:null};s.mode='singing';s.history=[];s.live=newScore(meta);s.pending.set(id,meta);sync();return {id,when};},
  fakeTick:(ctxTime)=>{if(s.ctx&&'_fake' in s.ctx)s.ctx.currentTime=ctxTime;const t=now();if(s.mode==='singing'&&s.live&&s.transport)scoreAdvance(s.live,s.history,Math.min(t-.18*s.transport.speed,s.transport.end));draw(t);updateReadout(t);return t;},
  fakeFinish:()=>{const id=s.takeCounter,meta=s.pending.get(id);if(!meta)return null;const pts=s.history.map(p=>({t:(p.songT-meta.a)/meta.speed,f:p.f,confidence:p.confidence,db:p.db,rms:p.rms??0,peak:p.peak??0}));s.pending.delete(id);const duration=(s.pos=now())-meta.a;s.transport=null;s.mode='idle';s.live=null;const m={id,blob:silentWav(duration/meta.speed),sampleRate:48000,duration:duration/meta.speed,start:0,end:duration/meta.speed,reason:'end',points:pts,gap:0};const t=storeTake(meta,m);sync();return {id:t.id,pct:scorePct(t.score)};}}};
populateSong();resize();setRangeScale();updateReadout(s.pos);
})();
