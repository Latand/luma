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
const prefs={gate:-48,octave:0,tolerance:50,level:'normal',latency:0,back:.75,fore:.45,vocal:true,view:'notes',speed:1,loop:false,mic:'',lyrics:true,takesOpen:true,viewDefault:3,audio:false,shadow:true,tab:'takes',audioNotice:false};
let hadSettings=false;// an empty profile has nothing to be told about a change it did not live through
try{const saved=localStorage.getItem('luma.trainer.settings');hadSettings=!!saved;const p=JSON.parse(saved||'{}');for(const [k,a,b]of[['gate',-70,-25],['octave',-12,12],['tolerance',10,100],['latency',-500,1000],['back',0,1],['fore',0,1]])if(Number.isFinite(p[k]))prefs[k]=clamp(p[k],a,b);if(![-12,0,12].includes(prefs.octave))prefs.octave=0;for(const k of ['lyrics','takesOpen','vocal','audio','shadow','audioNotice'])if(typeof p[k]==='boolean')prefs[k]=p[k];if(p.tab==='takes'||p.tab==='progress')prefs.tab=p.tab;if(p.level in LEVELS||p.level==='custom')prefs.level=p.level;if(prefs.level!=='custom')prefs.tolerance=LEVELS[prefs.level].tolerance;
 // notes became the default on 2026-09-12; a choice saved under an older default is not a choice, so it is not carried over
 if(p.viewDefault===3&&(p.view==='notes'||p.view==='contour'))prefs.view=p.view;}catch(_){}
function levelOpt(){const L=LEVELS[prefs.level]||LEVELS.normal;return{tolerance:prefs.level==='custom'?prefs.tolerance:L.tolerance,slack:L.slack,ratio:L.ratio,octaveFree:L.octaveFree,level:prefs.level};}
function levelLabel(opt){return opt.level==='custom'?'свій коридор':(LEVELS[opt.level]||LEVELS.normal).label;}
// Signed distance in cents; on the easy level the octave is forgiven (distance folds into ±6 semitones).
function centsOff(m,refM,opt){let d=m-refM;if(opt.octaveFree){d=((d%12)+12)%12;if(d>6)d-=12;}return d*100;}
const LOOP_LANE=24;
const s={ctx:null,stream:null,capture:null,micSource:null,worker:null,micGeneration:0,busy:false,cancel:0,mode:'idle',transport:null,sources:[],endTimer:null,nextTimer:null,bufs:new Map(),gains:null,pos:song.initialTime||0,range:{a:0,b:song.duration},rangeId:0,history:[],current:null,takes:[],takeCounter:0,pending:new Map(),awaitFinish:false,trace:null,live:null,verified:[],dirty:true,raf:0,lastDraw:0,lastFrame:0,lastUI:0,rangeLo:48,rangeHi:76,liveSmooth:null,lastSmoothT:0,toastTimer:0,edit:null,computeMs:0,windowMs:0,unsaved:false,undoPunch:null,busyFor:'',scrub:null,lyricKey:'',resumeAt:null,tlDrag:null,seekTimer:0,dense:false,stageH:0,hist:{runs:[],days:[],loaded:false,note:'',persisted:null,stamp:'',stale:false,restored:false},shadow:null,shadowSig:'',progressSig:'',trendScope:'',weakAll:false,roomNotice:false};
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
function saveEdits(){invalidateMap();try{localStorage.setItem('luma.target.'+song.id,JSON.stringify({notes:song.notes,verified:s.verified}));}catch(_){toast('Не вдалося зберегти правки у браузері. Завантаж JSON цілі.');}}
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
const sc={goalLo:48,goalHi:76,fromLo:48,fromHi:76,changedAt:-1e9,shrinkSince:null,p:1};
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
function setGoal(g,wall,instant){sc.fromLo=instant?g.lo:s.rangeLo;sc.fromHi=instant?g.hi:s.rangeHi;sc.goalLo=g.lo;sc.goalHi=g.hi;sc.changedAt=instant?-1e9:wall;sc.shrinkSince=null;sc.p=instant?1:0;if(instant){s.rangeLo=g.lo;s.rangeHi=g.hi;}s.dirty=true;}
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
// Progress runs on rendered frames, not on the wall clock: a paused tab or a slow frame never shortens or stretches the glide.
function easeScale(dt){if(s.rangeLo===sc.goalLo&&s.rangeHi===sc.goalHi){sc.p=1;return;}
 sc.p=reduced.matches?1:clamp(sc.p+dt/SCALE.ease,0,1);const e=sc.p*sc.p*(3-2*sc.p);
 if(sc.p>=1){s.rangeLo=sc.goalLo;s.rangeHi=sc.goalHi;}else{s.rangeLo=sc.fromLo+(sc.goalLo-sc.fromLo)*e;s.rangeHi=sc.fromHi+(sc.goalHi-sc.fromHi)*e;}s.dirty=true;}
// Explicit seek or a new selection: frame the new place at once.
function setRangeScale(){planScale(view(s.pos),s.pos,performance.now()/1000,true);}
// Every frame during playback: plan ahead, then glide.
function followRange(v,t){const wall=performance.now()/1000,dt=clamp(wall-(s.lastFrame||wall),0,.25);s.lastFrame=wall;planScale(v,t,wall,false);easeScale(dt);}
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
 baseNotes=structuredClone(song.notes);loadEdits();invalidateMap();setRangeScale();sync();
}
function sync(){
 s.dirty=true;$('lyricBand').hidden=!prefs.lyrics||!song.lyrics.length;
 // nothing recorded and nothing running: one invitation instead of a readout with no reading and a meter with no level
 const intro=!s.takes.length&&s.mode!=='singing'&&!s.stream&&!s.trace;$('invite').hidden=!intro;$('chartWrap').dataset.intro=intro?'1':'0';
 const active=s.mode!=='idle',singing=s.mode==='singing';$('singBtn').disabled=s.awaitFinish||(s.busy&&s.busyFor!=='sing');$('singBtn').classList.toggle('recording',singing);$('singLabel').textContent=s.busy?(s.busyFor==='sing'?'Скасувати':'Співати'):singing?'Завершити':'Співати';$('singBtn').querySelector('use').setAttribute('href',singing?'#i-stop':'#i-mic');
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
 $('undoPunchBtn').hidden=!s.undoPunch;$('undoPunchBtn').disabled=active||s.busy||s.awaitFinish;
 $('repeatMissBtn').hidden=!traceShown()||!missRuns(s.trace.score).length;$('repeatMissBtn').disabled=active||s.busy||s.awaitFinish;
 $('levelContext').textContent=traceShown()?'Наступна спроба':'Рівень';
 const ver=rangeVerified();$('qualityPill').textContent=ver?'Фрагмент підтверджений':'Чернетка мелодії';$('qualityBtn').classList.toggle('ok',ver);$('confirmTarget').checked=ver;
 $('micToggle').textContent=s.stream?'Вимкнути мікрофон':'Увімкнути лише мікрофон';$('micToggle').disabled=active||s.busy||s.awaitFinish;$('takesPanel').dataset.open=prefs.takesOpen?'1':'0';$('takesToggle').setAttribute('aria-expanded',String(prefs.takesOpen));$('takesCount').textContent=s.takes.length;
 $('lyricsBtn').setAttribute('aria-pressed',String(prefs.lyrics));$('shadowBtn').setAttribute('aria-pressed',String(prefs.shadow));$('recordAudio').checked=prefs.audio;
 refreshShadow();renderProgress();
 for(const b of document.querySelectorAll('[data-view]')){b.classList.toggle('active',b.dataset.view===prefs.view);b.setAttribute('aria-pressed',String(b.dataset.view===prefs.view));b.disabled=active||s.busy||s.awaitFinish;}
 const rv=traceShown();$('reviewBar').hidden=$('reviewDivider').hidden=!rv;if(rv){const t=s.trace.take,runs=missRuns(s.trace.score);$('reviewLabel').textContent='Спроба '+String(t.id).padStart(2,'0');const pct=scorePct(s.trace.score);$('reviewPct').textContent=pct===null?'—':pct+'%';$('missCount').textContent=runs.length?runs.length+' '+plural(runs.length,'промах','промахи','промахів'):'без промахів';$('prevMiss').disabled=$('nextMiss').disabled=!runs.length||s.mode!=='idle';}
 $('chartWrap').classList.toggle('scrub',s.mode!=='singing');
 // measured last, once everything above has shown or hidden what it will: a review bar that wraps the transport onto
 // a second row moves the stage, and a measure taken before it would fold the head for a height the stage no longer has
 fitStage();measureStage();updateStatus();requestDraw();
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
// Two budgets, counted at once, and neither one asks the singer to do anything. Traces are ~4 bytes a frame and every
// attempt is already in the history, so when a new attempt needs room the oldest attempt that is safe to drop leaves the
// tab by itself. WAV is 96 KB/s and lives only in the tab, so its limit stands when the user asked for audio — and a
// recording that needs room frees the oldest voices by itself; their attempts stay, lines and scores untouched.
const TRACE_TAKES=20,TRACE_POINTS=400000,AUDIO_TAKES=10,AUDIO_BYTES=100*1024*1024;
// Safe to drop: its row is in the history (or the singer cleared that row himself), it holds no WAV, it is not on
// screen and undo does not lean on it.
function evictable(t,stored){return !t.hasAudio&&!t.historyError&&s.trace?.take!==t&&s.undoPunch?.after!==t&&(stored.has(t.runId)||t.cleared);}
// The attempts, oldest first, that leave so one more fits the trace budget; null when too few of them may go.
function traceRoom(){
 let count=s.takes.length,points=s.takes.reduce((a,t)=>a+t.points.length,0);const out=[];
 if(count<TRACE_TAKES&&points<TRACE_POINTS)return out;
 const stored=new Set(s.hist.runs.map(r=>r.id));
 for(let i=s.takes.length-1;i>=0&&(count>=TRACE_TAKES||points>=TRACE_POINTS);i--){const t=s.takes[i];if(!evictable(t,stored))continue;out.push(t);count--;points-=t.points.length;}
 return count<TRACE_TAKES&&points<TRACE_POINTS?out:null;
}
// fresh: a pass of the A–B auto-repeat, which is a new attempt even while the pass before it is still on screen.
// Only the trace budget can still refuse, and only when the store itself refused: an attempt missing from the history
// has its line nowhere else, so the tab will not drop it to make room.
function capacity(fresh=false){
 const seg=nextSegment(true,fresh),punch=seg.punch;
 if(!punch&&!traceRoom())return{ok:false,kind:'trace',message:'Ліміт слідів: '+(s.takes.length>=TRACE_TAKES?TRACE_TAKES+' спроб':'400 000 точок голосу')+' у вкладці, і жодну з них вкладка не прибере сама: '
  +(s.takes.some(t=>t.historyError)?'сховище браузера не прийняло їх в історію, тож їхні лінії є лише тут.':'їхніх ліній ще немає в історії.')};
 return{ok:true};
}
// What the voice budget frees so the next recording fits: the oldest WAVs of other attempts first, then the copy undo
// holds. Undo retains the old full WAV, so a punch reserves its full merged replacement even for a short region; a punch
// that still cannot fit beside its own undo copy keeps no undo.
function audioRoom(seg){
 const punch=seg.punch,out={drop:[],undo:false,keepUndo:true};if(!prefs.audio&&!punch?.hasAudio)return out;
 const duration=punch?Math.max(punch.duration,(seg.end-punch.a)/punch.speed):Math.max(0,(seg.end-seg.start)/seg.speed);
 let size=44+Math.ceil(duration*(punch?.sampleRate||s.ctx?.sampleRate||48000))*2+s.takes.reduce((a,t)=>a+(t.blob?.size||0),0)+(s.undoPunch?.before.blob?.size||0),
  count=s.takes.filter(t=>t.hasAudio).length+(punch?0:1);const over=()=>count>AUDIO_TAKES||size>=AUDIO_BYTES;
 for(let i=s.takes.length-1;i>=0&&over();i--){const t=s.takes[i];if(!t.hasAudio||t===punch)continue;out.drop.push(t);count--;size-=t.blob?.size||0;}
 if(over()&&s.undoPunch){out.undo=true;size-=s.undoPunch.before.blob?.size||0;}
 if(over()&&punch)out.keepUndo=false;
 return out;
}
// A voice leaves memory, the attempt stays: its line, its score and its place in the list are untouched.
function dropVoice(t){if(t.url)URL.revokeObjectURL(t.url);t.blob=null;t.url=null;t.buffer=null;t.hasAudio=false;}
function freeVoices(room){for(const t of room.drop)dropVoice(t);if(room.undo)clearUndoPunch();if(room.drop.length||room.undo)renderTakes();}
// A new attempt is starting: what traceRoom() picked leaves the tab, and its row stays in the history.
function makeRoom(){
 const room=traceRoom();if(!room?.length)return;
 for(const t of room){s.takes.splice(s.takes.indexOf(t),1);if(t.url)URL.revokeObjectURL(t.url);}
 renderTakes();
 if(!s.roomNotice){s.roomNotice=true;toast('У вкладці лишаються '+TRACE_TAKES+' останніх спроб. Старіші — в історії, вкладка «Прогрес».');}
}
// Punch-in: with a take on screen and the playhead inside it (same speed), "Співати" re-records that take from here instead of starting a new one.
function punchTarget(){if(!traceShown()||s.mode!=='idle')return null;const t=s.trace.take;return t.speed===prefs.speed&&!!t.hasAudio===!!prefs.audio&&s.pos>=t.a-.01&&s.pos<t.endSong-.15?t:null;}
function wavHeaderBuf(count,rate){const b=new ArrayBuffer(44),v=new DataView(b);const text=(o,t)=>{for(let i=0;i<t.length;i++)v.setUint8(o+i,t.charCodeAt(i));};text(0,'RIFF');v.setUint32(4,36+count*2,true);text(8,'WAVE');text(12,'fmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);v.setUint32(24,rate,true);v.setUint32(28,rate*2,true);v.setUint16(32,2,true);v.setUint16(34,16,true);text(36,'data');v.setUint32(40,count*2,true);return b;}
// Splice a freshly recorded segment into an existing take: old audio before the punch point, new audio, then whatever old audio lies beyond the new end.
function mergeTake(old,meta,m){
 if(!!old.hasAudio!==!!m.hasAudio)return null;
 const speed=old.speed,offT=(meta.a-old.a)/speed,newEndSong=meta.a+m.duration*speed,tail=old.endSong>newEndSong+.02;
 let blob=null,duration=tail?old.duration:offT+m.duration;
 if(old.hasAudio){
  const sr=m.sampleRate;if(sr!==old.sampleRate)return null;const oldCount=Math.floor((old.blob.size-44)/2);
  const cut=clamp(Math.round(offT*sr),0,oldCount),newCount=Math.floor((m.blob.size-44)/2);
  const parts=[old.blob.slice(44,44+cut*2),m.blob.slice(44,44+newCount*2)];let total=cut+newCount;
  if(tail){const tailStart=clamp(Math.round((newEndSong-old.a)/speed*sr),0,oldCount);parts.push(old.blob.slice(44+tailStart*2));total+=oldCount-tailStart;}
  blob=new Blob([wavHeaderBuf(total,sr),...parts],{type:'audio/wav'});duration=total/sr;
 }
 const strip=p=>({t:p.t,f:p.f,confidence:p.confidence,db:p.db});
 const points=[...old.points.filter(p=>p.songT<meta.a).map(strip),...m.points.map(p=>({...strip(p),t:p.t+offT}))];
 if(tail)points.push(...old.points.filter(p=>p.songT>=newEndSong).map(strip));
 const meta2={...meta,id:old.id,a:old.a,b:Math.max(old.b,meta.b),speed,startedAt:old.startedAt,punches:(old.punches||0)+1,lastPunchAt:meta.a};
 return {meta:meta2,m:{...m,id:old.id,blob,duration,start:0,end:duration,points,gap:0,clipped:!!old.clipped||!!m.clipped}};
}
// Where the next Listen or Sing pass runs, without touching state. The A–B fragment applies from inside it and from its
// end (a finished pass parks the playhead there); with the loop on, from anywhere; otherwise the song plays on to its end.
// A punch-in re-records the shown take from the playhead, except on a fresh pass of the auto-repeat. capacity() reads
// this, startTransport() applies it.
function nextSegment(sing,fresh=false){
 const speed=prefs.speed,punch=sing&&!fresh?punchTarget():null;let pos=s.pos>=song.duration-.1?0:s.pos;
 if(punch)return{start:pos,end:Math.max(s.range.b,punch.endSong),speed,loop:null,punch};
 const cr=customRange(),atEnd=cr&&pos>=s.range.b-.1&&pos<=s.range.b+.25;
 if(cr&&(atEnd||prefs.loop&&(pos<s.range.a||pos>=s.range.b-.1)))pos=s.range.a;
 const inside=pos>=s.range.a-.01&&pos<s.range.b-.1;
 return inside?{start:Math.max(pos,s.range.a),end:s.range.b,speed,loop:!sing&&prefs.loop&&cr?{a:s.range.a,b:s.range.b}:null,punch:null}:{start:pos,end:song.duration,speed,loop:null,punch:null};
}
function takeMeta(offset,end,speed){const L=levelOpt();return{id:++s.takeCounter,a:offset,b:end,speed,octave:prefs.octave,view:prefs.view,tolerance:L.tolerance,slack:L.slack,ratio:L.ratio,octaveFree:L.octaveFree,level:L.level,latency:prefs.latency,referenceId:song.id,rangeId:s.rangeId,verified:structuredClone(s.verified),startedAt:new Date().toISOString(),hasAudio:!!prefs.audio,mapVersion:mapVersion()};}
function scheduleSources(b,when,offset,end,speed,loop,token){
 const duration=(end-offset)/speed;
 const back=addSource(b.back,s.gains.back,when,offset/speed,loop?b.back.duration-offset/speed:duration,loop?null:()=>naturalEnd(token)),fore=addSource(b.fore,s.gains.fore,when,offset/speed,loop?b.fore.duration-offset/speed:duration);
 if(loop)for(const n of [back,fore]){n.loop=true;n.loopStart=loop.a/speed;n.loopEnd=loop.b/speed;}
 return duration;}
async function startTransport(sing,quick=false,fresh=false){
 if(s.awaitFinish)return;if(s.busy){s.cancel++;s.busy=false;await releaseMic();sync();return;}
 if(s.mode!=='idle'){stopTransport('user');return;}
 clearTimeout(s.nextTimer);const token=++s.cancel;s.busy=true;s.busyFor=sing?'sing':'listen';$('errorBanner').hidden=true;sync();
 try{
  await ensureContext();const cap=capacity(fresh);if(sing&&!cap.ok){retryRefused();throw Error(cap.message);}
  if(sing&&!await ensureMic(token))return;
  const b=await buffers(prefs.speed);if(token!==s.cancel)return;await s.ctx.resume();
  const seg=nextSegment(sing,fresh),punch=seg.punch,room=sing?audioRoom(seg):null;if(room)freeVoices(room);if(sing&&!punch){makeRoom();s.trace=null;}if(seg.start!==s.pos){s.pos=seg.start;setRangeScale();}// only a moved playhead is framed at once; otherwise the eased planner takes over
  const speed=seg.speed,when=s.ctx.currentTime+(sing?(quick?.6:2.1):.12),offset=seg.start,end=seg.end,loop=seg.loop;
  s.transport={token,when,offset,end,speed,loop};s.mode=sing?'singing':'listen';s.history=punch?punch.points.filter(p=>p.songT<offset).map(p=>({...p,raw:p.m})):[];s.current=null;s.liveSmooth=null;s.busy=false;s.live=null;
  const duration=scheduleSources(b,when,offset,end,speed,loop,token);
  if(sing){const lag=prefs.latency/1000,meta=takeMeta(offset,end,speed);if(punch){meta.punchInto=punch.id;meta.keepUndo=room.keepUndo;s.trace=null;}s.pending.set(meta.id,meta);s.live=newScore(meta);s.worker.postMessage({type:'record',id:meta.id,start:when+lag,end:when+duration+lag,audio:meta.hasAudio});if(punch)say('Перезапис спроби '+punch.id+' від '+fmt(offset));}
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
 if(s.mode==='review'){const tk=s.trace.take,off=t-tk.a,dur=tk.duration-off/speed;const lead=addSource(b.back,s.gains.back,when,t/speed,dur);addSource(b.fore,s.gains.fore,when,t/speed,dur);
  if(tk.hasAudio)addSource(tk.buffer,s.gains.voice,when,off/speed,dur,()=>naturalEnd(token));else lead.onended=()=>naturalEnd(token);}
 else{const duration=scheduleSources(b,when,t,end,speed,loop,token);if(!loop)s.endTimer=setTimeout(()=>{if(s.transport?.token===token)naturalEnd(token);},(when-s.ctx.currentTime+duration+1.1)*1000);}
 s.dirty=true;sync();
}
function naturalEnd(token){if(!s.transport||s.transport.token!==token)return;if(s.mode==='singing')return;const wasReview=s.mode==='review';s.pos=s.transport.end;clearSources();s.transport=null;s.mode='idle';sync();renderTakes();if(!wasReview&&prefs.loop&&customRange()&&s.pos>=s.range.b-.05)scheduleLoop(false);}
// Every sung pass is an attempt of its own: as a punch-in it would overwrite the pass before it, in the tab and in the history.
function scheduleLoop(sing){clearTimeout(s.nextTimer);const token=s.cancel;s.nextTimer=setTimeout(()=>{if(s.cancel!==token||!prefs.loop||s.mode!=='idle'||s.awaitFinish)return;s.pos=s.range.a;startTransport(sing,true,true);},60);}
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
// ── Practice history ──────────────────────────────────────────────────────────────────────────────────────────────
// Every finished attempt lands in IndexedDB in this page's origin, automatically: no accounts, no network, nothing
// leaves this computer. Studio serves its own page and the trainers from the same origin, so a progress panel there
// can read the very same base. Schema, retention and the export format: docs/HISTORY_SCHEMA.md.
const HIST={name:'luma',version:1,dayEdge:4,keepTraces:20,minPhraseFrames:75,minSongFrames:200,songCover:.95,phraseCover:.8,lamp:85,trendRuns:30,sessionGap:45*60*1000,streakFrames:6000,noPitch:-32768};
function historyAvailable(){return location.protocol!=='file:'&&typeof indexedDB!=='undefined'&&!!indexedDB;}
function newRunId(){try{if(crypto.randomUUID)return crypto.randomUUID();}catch(_){}return 'r-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,10);}
// The song, not the file: re-preparing the same audio gives a new song.id but the same sourceId, so the history stays.
function songHash(){return song.sourceId||song.id;}
// Two FNV-1a accumulators over the drawn target: a short stable fingerprint. Editing a note opens a new comparison
// group; confirming a fragment by ear does not, because targetAt().m never reads `verified`.
function hash16(text){let a=0x811c9dc5,b=0x1b873593;for(let i=0;i<text.length;i++){const c=text.charCodeAt(i);a=Math.imul(a^c,16777619)>>>0;b=Math.imul(b^(c+i),2246822519)>>>0;}return (a>>>0).toString(16).padStart(8,'0')+(b>>>0).toString(16).padStart(8,'0');}
let mapVersionCache='',totalsCache=new Map();
function invalidateMap(){mapVersionCache='';totalsCache=new Map();s.shadowSig='';s.progressSig='';}
function mapVersion(){return mapVersionCache||(mapVersionCache=song.id+':'+hash16(JSON.stringify(song.notes.map(n=>[n.id,Math.round(n.a*1000),Math.round(n.b*1000),Math.round(n.m*100),n.ignored?1:0]))));}
function levelKey(meta){return meta.level==='custom'?'custom:'+meta.tolerance:meta.level;}
// The ruler a score was measured with. Two numbers may stand side by side only when all five agree. The vocal octave
// is not in it: it moves the target and leaves the difficulty alone.
function cmpKeyOf(meta){return [songHash(),meta.mapVersion||mapVersion(),levelKey(meta),meta.view,meta.speed].join('|');}
function currentKey(){const L=levelOpt();return cmpKeyOf({mapVersion:mapVersion(),level:L.level,tolerance:L.tolerance,view:prefs.view,speed:prefs.speed});}
// Local day with its edge at 04:00, so singing at half past midnight counts towards the evening that just passed.
function localDay(ms){const d=new Date(ms-HIST.dayEdge*3600e3);return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');}
function dayShift(day,delta){const [y,m,d]=String(day).split('-').map(Number),z=new Date(y,m-1,d+delta);return z.getFullYear()+'-'+String(z.getMonth()+1).padStart(2,'0')+'-'+String(z.getDate()).padStart(2,'0');}
function median(a){if(!a.length)return -1;const z=[...a].sort((x,y)=>x-y);return Math.round(z[z.length>>1]);}

// ── the compact trace: four bytes a frame instead of 96 000 a second ─────────────────────────────────────────────
// cents = round(midi × 100); -32768 means "no pitch here". Time is not stored per frame: a segment carries its own t0
// and the shared hop, and a new segment opens wherever the reconstructed time would drift by a quarter of a hop.
function traceHop(points){
 if(points.length<2)return .021333;const d=[];
 for(let i=1;i<points.length;i++){const z=points[i].t-points[i-1].t;if(z>1e-6&&z<.5)d.push(z);}
 if(!d.length)return .021333;d.sort((a,b)=>a-b);return d[d.length>>1];
}
function packTrace(points){
 const hop=traceHop(points),segs=[];let cur=null;
 for(const p of points){
  if(!cur||Math.abs(p.t-(cur.t0+cur.cents.length*hop))>hop*.25){cur={t0:p.t,cents:[],conf:[],db:[]};segs.push(cur);}
  cur.cents.push(p.f>0?clamp(Math.round((69+12*Math.log2(p.f/440))*100),-32767,32767):HIST.noPitch);
  cur.conf.push(clamp(Math.round((p.confidence||0)*255),0,255));
  cur.db.push(clamp(Math.round(Number.isFinite(p.db)?p.db:-120),-120,0));
 }
 return {hop,segments:segs.map(sg=>({t0:sg.t0,cents:Int16Array.from(sg.cents),conf:Uint8Array.from(sg.conf),db:Int8Array.from(sg.db)}))};
}
function unpackTrace(tr){
 const out=[];
 for(const sg of tr.segments)for(let i=0;i<sg.cents.length;i++){const c=sg.cents[i];
  out.push({t:sg.t0+i*tr.hop,f:c===HIST.noPitch?null:440*Math.pow(2,(c/100-69)/12),confidence:sg.conf[i]/255,db:sg.db[i]});}
 return out;
}
function b64(arr){const u=new Uint8Array(arr.buffer,arr.byteOffset,arr.byteLength);let out='';for(let i=0;i<u.length;i+=8192)out+=String.fromCharCode.apply(null,u.subarray(i,i+8192));return btoa(out);}
function unb64(text,Type){
 let raw;try{raw=atob(text);}catch(_){throw Error('Слід у файлі історії закодовано неправильно.');}
 const u=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)u[i]=raw.charCodeAt(i);
 if(u.byteLength%Type.BYTES_PER_ELEMENT)throw Error('Пошкоджений слід у файлі історії.');return new Type(u.buffer);}
function encodeTrace(tr){return {runId:tr.runId,songHash:tr.songHash,hop:tr.hop,segments:tr.segments.map(sg=>({t0:sg.t0,cents:b64(sg.cents),conf:b64(sg.conf),db:b64(sg.db)}))};}
function decodeTrace(tr){return {runId:tr.runId,songHash:tr.songHash,hop:tr.hop,segments:tr.segments.map(sg=>{
 const cents=unb64(sg.cents,Int16Array),conf=unb64(sg.conf,Uint8Array),db=unb64(sg.db,Int8Array);
 if(conf.length!==cents.length||db.length!==cents.length)throw Error('Канали сліду мають різну довжину.');
 return {t0:sg.t0,cents,conf,db};})};}
function encodeRun(r){return {...r,phraseIds:[...(r.phraseIds||[])],phraseStats:[...(r.phraseStats||[])]};}
function decodeRun(r){return {...r,phraseIds:Int32Array.from(r.phraseIds||[]),phraseStats:Int32Array.from(r.phraseStats||[])};}

// ── denominators: how many frames of target a phrase and the whole song hold under one view, and how many are draft ─
function targetTotals(view){
 const hit=totalsCache.get(view);if(hit)return hit;
 const opt={octave:0,view},phr=song.phrases||[],per=new Map(),perDraft=new Map();let songFrames=0,draft=0;
 for(const p of phr){per.set(p.id,0);perDraft.set(p.id,0);}
 for(let i=0;;i++){const t=i*GRID;if(t>song.duration)break;const ref=targetAt(t,opt);if(!ref)continue;songFrames++;if(!ref.ok)draft++;
  for(let j=0;j<phr.length;j++){const p=phr[j];if(p.a>t)break;if(p.b>=t){per.set(p.id,(per.get(p.id)||0)+1);if(!ref.ok)perDraft.set(p.id,(perDraft.get(p.id)||0)+1);}}}
 const out={song:songFrames,draft,phrase:per,phraseDraft:perDraft};totalsCache.set(view,out);return out;
}
// One walk of an attempt's own scoring grid. A phrase enters the record only when the attempt covered at least 80 %
// of its frames with a target: a pass that clipped the edge of a phrase must not spoil the weak-phrase map.
function summarizeRun(t){
 const opt=t.score.opt,frames=t.score.frames,phr=song.phrases||[],per=new Map(),perErrs=new Map(),errs=[];
 for(const p of phr){per.set(p.id,{target:0,hit:0,sung:0});perErrs.set(p.id,[]);}
 let target=0,hit=0,sung=0,draft=0,pi=0;
 for(let i=0;i<frames.length;i++){const st=frames[i];if(!st)continue;const tt=t.score.a+i*GRID,ref=targetAt(tt,opt);
  target++;if(st===1)hit++;if(st!==3)sung++;if(!ref||!ref.ok)draft++;
  for(let j=pi;j<phr.length;j++){const p=phr[j];if(p.a>tt)break;if(p.b<tt){if(j===pi)pi++;continue;}
   const q=per.get(p.id);q.target++;if(st===1)q.hit++;if(st!==3)q.sung++;}}
 for(const p of t.points){if(p.m===null||p.m===undefined||p.ref===null||p.ref===undefined||p.confidence<.8)continue;
  const e=Math.abs(centsOff(p.m,p.ref,opt));errs.push(e);
  for(let j=0;j<phr.length;j++){const q=phr[j];if(q.a>p.songT)break;if(q.b>=p.songT)perErrs.get(q.id).push(e);}}
 const totals=targetTotals(opt.view),phrases=[];
 for(const p of phr){const q=per.get(p.id),whole=totals.phrase.get(p.id)||0;
  if(!q.target||!whole||q.target<whole*HIST.phraseCover)continue;
  phrases.push({id:p.id,target:q.target,hit:q.hit,sung:q.sung,median:median(perErrs.get(p.id))});}
 return {target,hit,sung,draft,median:median(errs),phrases,songTarget:totals.song};
}
// match is stored as an integer in hundredths of a percent, so ties break on the median and not on rounding.
function runRecord(t,sum){
 const stat=[];for(const p of sum.phrases)stat.push(p.target,p.hit,p.sung,p.median);
 const started=Date.parse(t.startedAt)||Date.now();
 return {id:t.runId,songHash:songHash(),mapVersion:t.mapVersion||mapVersion(),cmpKey:cmpKeyOf(t),startedAt:t.startedAt,endedAt:new Date().toISOString(),localDay:localDay(started),
  a:+t.a.toFixed(3),b:+t.endSong.toFixed(3),speed:t.speed,level:t.level,tolerance:t.tolerance,view:t.view,octave:t.octave,latency:t.latency,
  hasAudio:!!t.hasAudio,clipped:!!t.clipped,punches:t.punches||0,
  target:sum.target,hit:sum.hit,sung:sum.sung,draftFrames:sum.draft,medianCents:sum.median,match:sum.target?Math.round(10000*sum.hit/sum.target):null,songTarget:sum.songTarget,
  strict:{targetTime:+(t.stats.targetTime||0).toFixed(3),compared:+(t.stats.compared||0).toFixed(3),inside:+((t.stats.compared||0)*(t.stats.accuracy||0)/100).toFixed(3),median:t.stats.median===null?-1:Math.round(t.stats.median)},
  phraseIds:Int32Array.from(sum.phrases.map(p=>p.id)),phraseStats:Int32Array.from(stat),hasTrace:true};
}
function songEntry(runs){
 const maps=new Map();
 for(const r of runs)if(!maps.has(r.mapVersion))maps.set(r.mapVersion,{mapVersion:r.mapVersion,firstSeen:r.startedAt,notes:null,draftShare:null});
 const cur=mapVersion(),totals=targetTotals(prefs.view);
 if(!maps.has(cur))maps.set(cur,{mapVersion:cur,firstSeen:new Date().toISOString(),notes:null,draftShare:null});
 Object.assign(maps.get(cur),{notes:song.notes.length,draftShare:totals.song?+(totals.draft/totals.song).toFixed(4):0});
 const times=runs.map(r=>r.startedAt).sort();
 return {songHash:songHash(),title:song.title,artist:song.artist||'',duration:song.duration,lessonId:song.lesson?.id||null,maps:[...maps.values()],
  firstRunAt:times[0]||new Date().toISOString(),lastRunAt:times[times.length-1]||new Date().toISOString(),runCount:runs.length};
}

// ── IndexedDB ───────────────────────────────────────────────────────────────────────────────────────────────────
let dbHandle=null;
function openDB(){
 if(dbHandle)return dbHandle;
 const opened=new Promise((resolve,reject)=>{
  if(!historyAvailable())return reject(Error('Історія працює лише зі сторінки, відкритої через Studio.'));
  const req=indexedDB.open(HIST.name,HIST.version);
  req.onupgradeneeded=()=>{const db=req.result;
   if(!db.objectStoreNames.contains('songs'))db.createObjectStore('songs',{keyPath:'songHash'});
   if(!db.objectStoreNames.contains('runs')){const runs=db.createObjectStore('runs',{keyPath:'id'});
    runs.createIndex('bySong',['songHash','startedAt']);runs.createIndex('byKey',['cmpKey','match']);runs.createIndex('byDay','localDay');}
   if(!db.objectStoreNames.contains('traces'))db.createObjectStore('traces',{keyPath:'runId'});};
  req.onsuccess=()=>resolve(req.result);
  req.onerror=()=>reject(req.error||Error('Не вдалося відкрити сховище історії.'));
  req.onblocked=()=>reject(Error('Сховище зайняте іншою вкладкою Luma.'));
 });
 opened.catch(()=>{dbHandle=null;});dbHandle=opened;return opened;
}
function idbAll(store,index,range){
 return openDB().then(db=>new Promise((resolve,reject)=>{
  const t=db.transaction(store,'readonly'),src=index?t.objectStore(store).index(index):t.objectStore(store);
  const r=range===undefined?src.getAll():src.getAll(range);
  r.onsuccess=()=>resolve(r.result||[]);t.onerror=()=>reject(t.error);t.onabort=()=>reject(t.error||Error('Читання перервано.'));
 }));
}
function idbGet(store,key){
 return openDB().then(db=>new Promise((resolve,reject)=>{
  const t=db.transaction(store,'readonly'),r=t.objectStore(store).get(key);
  r.onsuccess=()=>resolve(r.result);t.onerror=()=>reject(t.error);t.onabort=()=>reject(t.error||Error('Читання перервано.'));
 }));
}
// ops: [store, 'put'|'delete', value|key]. One transaction, so an attempt and its trace never land half-written.
function idbWrite(ops){
 if(!ops.length)return Promise.resolve(true);
 return openDB().then(db=>new Promise((resolve,reject)=>{
  const t=db.transaction([...new Set(ops.map(o=>o[0]))],'readwrite');
  t.oncomplete=()=>resolve(true);t.onerror=()=>reject(t.error);t.onabort=()=>reject(t.error||Error('Запис перервано.'));
  try{for(const [store,op,arg]of ops)t.objectStore(store)[op](arg);}catch(e){try{t.abort();}catch(_){}reject(e);}
 }));
}
function readable(e,fallback){
 const m=e&&e.message?String(e.message):'';
 return /[\u0400-\u04FF]/.test(m)?m:fallback+(e&&e.name?' ('+e.name+')':'');
}
function storeNote(e){return e&&e.name==='QuotaExceededError'?'Сховище браузера переповнене: нові спроби не лягають в історію, доки на диску не звільниться місце.':readable(e,'Історію не записано.');}
function askPersist(){
 if(s.hist.persisted!==null||!navigator.storage||!navigator.storage.persist)return;
 s.hist.persisted=false;
 navigator.storage.persist().then(ok=>{s.hist.persisted=!!ok;s.progressSig='';renderProgress();}).catch(()=>{});
}
// The whole in-memory view of the history, so importing another song cannot leave the previous song's runs behind it:
// songHash() would then have moved while s.hist.runs had not, and the next attempt would write the mixed list back.
function resetHistory(){s.hist={runs:[],days:[],loaded:false,note:'',persisted:s.hist.persisted,stamp:'',stale:false,restored:false};s.shadow=null;s.shadowSig='';s.progressSig='';}
// A caption is a statement about the history; when the history moves under the cards, every caption is recounted, and
// an attempt whose row is no longer stored loses it altogether.
function refreshCaptions(){
 for(const t of s.takes){
  const row=t.runId?s.hist.runs.find(r=>r.id===t.runId):null;
  if(!row||!historyAvailable()){t.record=null;continue;}
  // an attempt brought back from the history has no summary of its own: its stored row is the pass it was sung as
  try{t.record=recordCaption(t.summary?runRecord(t,t.summary):row);}catch(_){t.record=null;}
 }
 renderTakes();
}
async function loadHistory(){
 s.hist.loaded=true;
 if(!historyAvailable()){s.hist.note='Історія не ведеться: відкрий пісню з бібліотеки Studio (file:// не має сховища).';refreshCaptions();renderProgress();sync();return;}
 try{
  const key=songHash();
  s.hist.runs=(await idbAll('runs','bySong',IDBKeyRange.bound([key,''],[key,'￿']))).sort(byNewest);
  const recent=await idbAll('runs','byDay',IDBKeyRange.lowerBound(dayShift(localDay(Date.now()),-180)));
  s.hist.days=recent.map(r=>({id:r.id,localDay:r.localDay,target:r.target}));
  s.hist.note='';s.hist.stale=false;
  if(!s.hist.restored)restoreTakes();
 }catch(e){s.hist.note=storeNote(e);s.hist.stale=true;}
 s.hist.stamp=newRunId();refreshShadow();refreshCaptions();renderProgress();sync();
}
// A reopened trainer opens on the lines already sung: the newest attempts whose trace the history keeps come back into
// the list, up to the same budget the tab keeps while singing. They come back as the tab would score them now, and
// without audio, which never was in the history. Once per song, and again after a history file comes in; nothing is
// shown on the stage until one is picked. One attempt per task, so a page of long passes still paints meanwhile.
let wipes=0;// «Очистити пісню» so far: a restore that outlives a clear would bring back lines whose rows are gone
async function restoreTakes(){
 s.hist.restored=true;const key=songHash(),wipe=wipes,have=new Set(s.takes.map(t=>t.runId)),stale=()=>songHash()!==key||wipes!==wipe;
 const runs=s.hist.runs.filter(r=>r.hasTrace&&!have.has(r.id)).slice(0,Math.max(0,TRACE_TAKES-s.takes.length));if(!runs.length)return;
 const traces=await Promise.all(runs.map(r=>idbGet('traces',r.id).catch(()=>null))),back=[];
 for(let i=0;i<runs.length;i++){const r=runs[i],tr=traces[i];if(!tr)continue;
  if(back.length)await new Promise(ok=>setTimeout(ok));if(stale())return;// another song opened, or this one cleared, meanwhile
  try{const pts=unpackTrace(tr),L=LEVELS[r.level]||LEVELS.normal,duration=(r.b-r.a)/r.speed;
   const meta={a:r.a,b:r.b,speed:r.speed,octave:r.octave||0,view:r.view,tolerance:r.tolerance,slack:L.slack,ratio:L.ratio,octaveFree:L.octaveFree,level:r.level,latency:r.latency||0,referenceId:song.id,rangeId:0,verified:structuredClone(s.verified),startedAt:r.startedAt,hasAudio:false,mapVersion:mapVersion(),punches:r.punches||0};
   back.push({...meta,...analyzeTake(meta,pts,duration),duration,clipped:!!r.clipped,url:null,blob:null,endSong:r.b,runId:r.id,restored:true});}
  catch(_){}// a trace that no longer decodes stays in the history, out of the list
 }
 if(stale())return;
 // counted now, so what the tab took in meanwhile keeps its place; newest first, stopping at the first that does not fit
 let room=TRACE_TAKES-s.takes.length,points=TRACE_POINTS-s.takes.reduce((a,t)=>a+t.points.length,0);const fit=[];
 for(const t of back){if(room<=0||t.points.length>points)break;fit.push(t);room--;points-=t.points.length;}
 if(!fit.length)return;
 for(let i=fit.length-1;i>=0;i--)fit[i].id=++s.takeCounter;// numbered oldest first, as they were sung
 s.takes.push(...fit);refreshCaptions();sync();
}
function byNewest(a,b){return a.startedAt<b.startedAt?1:a.startedAt>b.startedAt?-1:0;}
// A record belongs to the day it was first reached: equal scores go to the smaller median |Δ|, then to the earlier date.
function better(a,b){
 if(!b)return true;if(a.match!==b.match)return a.match>b.match;
 const am=a.medianCents<0?1e9:a.medianCents,bm=b.medianCents<0?1e9:b.medianCents;
 if(am!==bm)return am<bm;return a.startedAt<b.startedAt;
}
function phraseCandidates(r){
 const ids=r.phraseIds||[],st=r.phraseStats||[],out=[];
 for(let i=0;i<ids.length;i++){const target=st[i*4];if(!target)continue;
  out.push({id:ids[i],target,hit:st[i*4+1],sung:st[i*4+2],medianCents:st[i*4+3],match:clamp(Math.round(10000*st[i*4+1]/target),0,10000),startedAt:r.startedAt,run:r});}
 return out;
}
// Records inside one ruler: a song record needs a full pass (95 % of the song's target frames, at least 4 s of it);
// a phrase record needs the 80 % coverage that put the phrase in the attempt at all, plus 1.5 s of target.
function records(list){
 let song_=null;const phrases=new Map();
 for(const r of list){
  if(r.match!==null&&r.target>=HIST.minSongFrames&&r.songTarget&&r.target>=r.songTarget*HIST.songCover&&better(r,song_))song_=r;
  for(const c of phraseCandidates(r)){if(c.target<HIST.minPhraseFrames)continue;const cur=phrases.get(c.id);if(better(c,cur))phrases.set(c.id,c);}}
 return {song:song_,phrases};
}
function recordHolders(runs){
 const out=new Set(),byKey=new Map();
 for(const r of runs){if(!byKey.has(r.cmpKey))byKey.set(r.cmpKey,[]);byKey.get(r.cmpKey).push(r);}
 for(const list of byKey.values()){const rec=records(list);if(rec.song)out.add(rec.song.id);for(const c of rec.phrases.values())out.add(c.run.id);}
 return out;
}
// Retention: the trace of every standing record, plus the last 20 attempts of the song. Summaries are never deleted.
function staleTraces(runs){
 const keep=recordHolders(runs);for(const r of runs.slice(0,HIST.keepTraces))keep.add(r.id);
 return runs.filter(r=>r.hasTrace&&!keep.has(r.id));
}
function runScope(run){
 if(run.match===null)return null;
 if(run.target>=HIST.minSongFrames&&run.songTarget&&run.target>=run.songTarget*HIST.songCover)return {kind:'song'};
 const big=phraseCandidates(run).filter(c=>c.target>=HIST.minPhraseFrames);
 return big.length===1?{kind:'phrase',id:big[0].id,match:big[0].match}:null;
}
// One calm line under the attempt: «+4 до рекорду», «рекорд», «−7 від рекорду». No animation, no badge, no sound.
function recordCaption(run){
 const scope=runScope(run);if(!scope)return null;
 const prev=s.hist.runs.filter(r=>r.id!==run.id&&r.cmpKey===run.cmpKey),rec=records(prev);
 const mine=scope.kind==='song'?run.match:scope.match;
 const best=scope.kind==='song'?rec.song:rec.phrases.get(scope.id);
 const what=scope.kind==='song'?'рекорд пісні':'рекорд фрази «'+phraseLabel(scope.id)+'»';
 if(!best)return {delta:0,text:'перший зарахований прохід',title:what+' · порівнювати поки нема з чим'};
 const d=Math.round(mine/100)-Math.round(best.match/100);
 const tail=' · попередній '+Math.round(best.match/100)+'% від '+String(best.startedAt).slice(0,10);
 return d>0?{delta:d,text:'+'+d+' до рекорду',title:what+tail}:d<0?{delta:d,text:'−'+(-d)+' від рекорду',title:what+tail}:{delta:0,text:'рекорд',title:what+tail};
}
function phraseLabel(id){const p=(song.phrases||[]).find(p=>p.id===id);return p?(p.label||'Фрагмент '+id):'Фрагмент '+id;}
function exerciseOf(p){return p.exercise||String(p.label||'').split(' · ')[0]||'Вправа';}
let saveQueue=Promise.resolve();
function saveRun(take){
 if(!take)return Promise.resolve(false);
 let run,trace;
 try{const sum=summarizeRun(take);take.summary=sum;run=runRecord(take,sum);trace=packTrace(take.points);
  // No caption before the history is on hand: «перший зарахований прохід» would be a guess, not a fact.
  take.record=historyAvailable()&&s.hist.loaded?recordCaption(run):null;}
 catch(e){take.historyError=true;markUnsaved();s.hist.note=readable(e,'Не вдалося підсумувати спробу.');return Promise.resolve(false);}
 if(!historyAvailable()){take.historyError=false;markUnsaved();return Promise.resolve(false);}
 // One write at a time: each one counts its summary row and its retention from the list the write before it left, so
 // attempts saved back to back never write a list that is missing the others.
 take.writing=true;
 const step=saveQueue.then(()=>{
  const runs=[run,...s.hist.runs.filter(r=>r.id!==run.id)].sort(byNewest);
  // s.hist.runs is what songEntry() counts; when the last read failed it is empty, and a summary row built from it
  // would claim this attempt is the song's first. The attempt itself is written either way.
  const ops=[['runs','put',run],['traces','put',{runId:run.id,songHash:run.songHash,hop:trace.hop,segments:trace.segments}]];
  if(!s.hist.stale)ops.unshift(['songs','put',songEntry(runs)]);
  for(const r of staleTraces(runs)){r.hasTrace=false;ops.push(['runs','put',r],['traces','delete',r.id]);}
  return idbWrite(ops).then(()=>{
   s.hist.runs=runs;s.hist.stamp=run.id+':'+run.endedAt;take.writing=false;take.historyError=false;markUnsaved();s.hist.note='';
   s.hist.days=[...s.hist.days.filter(d=>d.id!==run.id),{id:run.id,localDay:run.localDay,target:run.target}];
   askPersist();refreshShadow();s.progressSig='';renderProgress();renderTakes();
   retryRefused();return true;
  });
 }).catch(e=>{take.writing=false;take.historyError=true;markUnsaved();s.hist.note=storeNote(e);s.progressSig='';renderTakes();renderProgress();return false;});
 saveQueue=step;return step;
}
// Whatever the store refused is tried again whenever it may take writes: after any write it accepted, and on every
// «Співати» the refused ones hold back. Nobody is asked to do it.
function retryRefused(){for(const t of s.takes)if(t.historyError&&!t.writing)saveRun(t);}
// The shadow of the personal best for what is framed now: one dim line under the live trace, so «how am I moving»
// has an answer while singing and not only afterwards.
function refreshShadow(){
 const sig=prefs.shadow?[currentKey(),s.trendScope||'',s.range.a.toFixed(2),s.range.b.toFixed(2),s.hist.stamp||'',s.trace?.take?.runId||''].join('|'):'off';
 if(sig===s.shadowSig)return;s.shadowSig=sig;
 if(!prefs.shadow){s.shadow=null;s.dirty=true;requestDraw();return;}
 const key=currentKey(),skip=s.trace?.take?.runId;
 // Same population as the numbers above the graph: under a fragment the best line is the best pass of that fragment,
 // never a whole-song pass that happened to cover it.
 let entry=null;
 for(const e of scopeEntries(s.hist.runs.filter(r=>r.cmpKey===key&&r.hasTrace&&r.id!==skip)))if(better(e,entry))entry=e;
 if(!entry){s.shadow=null;s.dirty=true;requestDraw();return;}
 const best=entry.run;
 if(s.shadow?.id===best.id)return;
 idbGet('traces',best.id).then(tr=>{
  if(s.shadowSig!==sig||!tr)return;
  // The octave is out of the comparison key because it moves the target and leaves the difficulty alone; the shadow
  // has to move with it, or a record sung an octave away silently falls off the plot.
  s.shadow={id:best.id,match:entry.match,octave:best.octave||0,points:unpackTrace(tr).map(p=>({songT:best.a+p.t*best.speed,m:p.f?69+12*Math.log2(p.f/440):null,confidence:p.confidence}))};
  s.dirty=true;requestDraw();
 }).catch(()=>{});
}
function optOfRun(r){const L=LEVELS[r.level]||LEVELS.normal;return {a:r.a,octave:r.octave,view:r.view,tolerance:r.tolerance,slack:L.slack,ratio:L.ratio,octaveFree:L.octaveFree,level:r.level};}

// ── export, import, clearing ────────────────────────────────────────────────────────────────────────────────────
async function exportPayload(all){
 const songs=await idbAll('songs'),runs=await idbAll('runs'),traces=await idbAll('traces');
 const key=songHash(),keep=r=>all||r.songHash===key;
 return {schema:'luma.history.v1',exportedAt:new Date().toISOString(),app:'luma',
  songs:songs.filter(x=>all||x.songHash===key),runs:runs.filter(keep).map(encodeRun),traces:traces.filter(keep).map(encodeTrace)};
}
function validHistory(d){
 if(!d||d.schema!=='luma.history.v1')return 'Потрібен файл історії Luma (схема luma.history.v1).';
 if(!Array.isArray(d.songs)||!Array.isArray(d.runs)||!Array.isArray(d.traces))return 'У файлі бракує розділів songs / runs / traces.';
 if(d.songs.length>1000||d.runs.length>50000||d.traces.length>50000)return 'Файл завеликий: більше 50 000 спроб.';
 for(const x of d.songs){
  if(!x||typeof x.songHash!=='string'||!x.songHash||x.songHash.length>100)return 'У записі пісні немає ключа songHash.';
  if(x.title!==undefined&&(typeof x.title!=='string'||x.title.length>300))return 'Невірна назва пісні у файлі.';
  if(x.artist!==undefined&&(typeof x.artist!=='string'||x.artist.length>300))return 'Невірний виконавець у файлі.';
  if(x.duration!==undefined&&(!Number.isFinite(x.duration)||x.duration<0||x.duration>36000))return 'Невірна тривалість пісні у файлі.';
  if(x.maps!==undefined&&(!Array.isArray(x.maps)||x.maps.length>500))return 'Невірний перелік версій карти у файлі.';
 }
 for(const r of d.runs){
  if(typeof r.id!=='string'||!r.id||r.id.length>100||typeof r.songHash!=='string'||!r.songHash||r.songHash.length>100)return 'Невірний ідентифікатор спроби.';
  if(typeof r.startedAt!=='string'||r.startedAt.length>40||typeof r.cmpKey!=='string'||r.cmpKey.length>400)return 'Невірні метадані спроби.';
  for(const k of ['target','hit','sung'])if(!Number.isFinite(r[k])||r[k]<0||r[k]>5e6)return 'Невірні лічильники кадрів у спробі.';
  if(r.hit>r.target||r.sung>r.target)return 'У спробі більше влучань, ніж кадрів із ціллю.';
  if(r.match!==null&&(!Number.isFinite(r.match)||r.match<0||r.match>10000))return 'Невірний збіг у спробі.';
  if(!Array.isArray(r.phraseIds)||!Array.isArray(r.phraseStats)||r.phraseIds.length>5000||r.phraseStats.length!==r.phraseIds.length*4)return 'Невірна розбивка по фразах.';
  if(!r.phraseIds.every(Number.isFinite)||!r.phraseStats.every(Number.isFinite))return 'Невірні числа в розбивці по фразах.';
 }
 let frames=0;
 for(const tr of d.traces){
  if(typeof tr.runId!=='string'||!Array.isArray(tr.segments)||tr.segments.length>20000)return 'Невірний слід у файлі.';
  if(!Number.isFinite(tr.hop)||tr.hop<=0||tr.hop>1)return 'Невірний крок сліду.';
  for(const sg of tr.segments){if(typeof sg.cents!=='string'||typeof sg.conf!=='string'||typeof sg.db!=='string')return 'Невірний слід у файлі.';
   if(!Number.isFinite(sg.t0)||sg.t0<0||sg.t0>36000)return 'Невірний час у сліді.';frames+=sg.cents.length;}}
 if(frames>6e7)return 'Сліди у файлі завеликі.';
 return '';
}
// Merging is by attempt id, so the same file may be imported twice with no effect.
async function importHistory(d){
 const bad=validHistory(d);if(bad)throw Error(bad);
 try{return await mergeHistory(d);}catch(e){throw Error(readable(e,'Файл історії не прийнято.'));}
}
async function mergeHistory(d){
 const have=new Set((await idbAll('runs')).map(r=>r.id));
 const songs=new Map((await idbAll('songs')).map(x=>[x.songHash,x]));
 const fresh=d.runs.filter(r=>!have.has(r.id)),ids=new Set(fresh.map(r=>r.id));
 const ops=[];
 for(const r of fresh)ops.push(['runs','put',decodeRun(r)]);
 for(const tr of d.traces)if(ids.has(tr.runId))ops.push(['traces','put',decodeTrace(tr)]);
 // The row this browser already has stays in charge: a file adds its attempts, the map versions it knows and a wider
 // span of dates, and a file with nothing new for a song leaves that song's row as it is, byte for byte.
 for(const x of d.songs){const cur=songs.get(x.songHash),added=fresh.filter(r=>r.songHash===x.songHash);
  if(!cur){ops.push(['songs','put',x]);continue;}
  if(!added.length)continue;
  const maps=new Map([...(x.maps||[]),...(cur.maps||[])].map(m=>[m.mapVersion,m]));
  const times=[cur.firstRunAt,cur.lastRunAt,...added.map(r=>r.startedAt)].filter(Boolean).sort();
  ops.push(['songs','put',{...x,...cur,maps:[...maps.values()],firstRunAt:times[0],lastRunAt:times[times.length-1],runCount:(cur.runCount||0)+added.length}]);}
 await idbWrite(ops);
 s.hist.restored=false;await loadHistory();// the lines a file brought fill the list the way a reopen does
 return {imported:fresh.length,skipped:d.runs.length-fresh.length};
}
async function clearSongHistory(){
 wipes++;const key=songHash(),runs=await idbAll('runs','bySong',IDBKeyRange.bound([key,''],[key,'￿']));
 const ops=[['songs','delete',key]];
 for(const r of runs)ops.push(['runs','delete',r.id],['traces','delete',r.id]);
 await idbWrite(ops);
 // The singer deleted these rows himself, so an attempt still in the tab is his to lose: the tab may drop it to make
 // room, and × stops promising that the history keeps it.
 const gone=new Set(runs.map(r=>r.id));for(const t of s.takes)if(gone.has(t.runId))t.cleared=true;
 s.shadow=null;s.shadowSig='';await loadHistory();// loadHistory ends in refreshCaptions(), which drops the caption of an attempt whose row is gone
 // Clearing is what the quota message asks for, so an attempt the full store refused gets its write now that there is room.
 await Promise.all(s.takes.filter(t=>t.historyError).map(saveRun));
 return runs.length;
}
function takePayload(t){
 const sum=t.summary||(t.summary=summarizeRun(t)),run=runRecord(t,sum),trace=packTrace(t.points);
 return {schema:'luma.history.v1',exportedAt:new Date().toISOString(),app:'luma',
  songs:[songEntry([run])],runs:[encodeRun(run)],traces:[encodeTrace({runId:run.id,songHash:run.songHash,hop:trace.hop,segments:trace.segments})]};
}
function saveTakeJSON(t){download(new Blob([JSON.stringify(takePayload(t))],{type:'application/json'}),takeFilename(t,'json'));}
// What closing the tab would lose for good: an attempt the history refused to take, whose line exists nowhere else.
// A WAV is a listen-back copy of a line the history already holds, so it never holds the tab open.
function markUnsaved(){s.unsaved=s.takes.some(t=>t.historyError);}
function storeTake(meta,m){
 let replaced=null;
 if(meta.punchInto!==undefined){const old=s.takes.find(t=>t.id===meta.punchInto);const merged=old?mergeTake(old,meta,m):null;if(merged){meta=merged.meta;m=merged.m;replaced=old;}else{s.takeCounter++;meta={...meta,id:s.takeCounter};m={...m,id:meta.id};}}
 const a=analyzeTake(meta,m.points,m.duration);
 const take={...meta,...m,...a,hasAudio:!!m.blob,clipped:!!m.clipped,url:m.blob?URL.createObjectURL(m.blob):null,endSong:meta.a+m.duration*meta.speed,runId:replaced?.runId||newRunId()};
 if(replaced){clearUndoPunch();if(meta.keepUndo!==false)s.undoPunch={before:replaced,after:take};else if(replaced.url)URL.revokeObjectURL(replaced.url);s.takes[s.takes.indexOf(replaced)]=take;}else s.takes.unshift(take);
 s.trace={take,points:take.points,score:take.score};s.current=null;saveRun(take);markUnsaved();renderTakes();
 say(replaced?'Спробу '+String(take.id)+' перезаписано від '+fmt(meta.lastPunchAt)+'.':'Спробу '+String(take.id)+' записано: лінія й оцінка зберігаються самі.');return take;
}
function clearUndoPunch(){if(s.undoPunch){if(s.undoPunch.before.url)URL.revokeObjectURL(s.undoPunch.before.url);s.undoPunch=null;}}
function undoPunch(){
 if(!s.undoPunch||s.mode!=='idle'||s.busy||s.awaitFinish)return;
 const {before,after}=s.undoPunch,index=s.takes.indexOf(after);if(index<0){clearUndoPunch();sync();return;}
 if(after.url)URL.revokeObjectURL(after.url);s.takes[index]=before;s.undoPunch=null;saveRun(before);markUnsaved();
 s.trace={take:before,points:before.points,score:before.score};s.pos=clamp(s.pos,before.a,before.endSong);setRangeScale();renderTakes();sync();toast('Попередню версію спроби відновлено.');
}
function onFinished(m){
 const meta=s.pending.get(m.id);if(!meta)return;
 if(s.mode==='singing'&&m.reason==='end'&&s.transport&&s.ctx){const end=s.transport.when+(s.transport.end-s.transport.offset)/s.transport.speed;if(s.ctx.currentTime<end-.01){setTimeout(()=>onFinished(m),(end-s.ctx.currentTime)*1000+20);return;}}
 s.pending.delete(m.id);const auto=s.mode==='singing'&&m.reason==='end'&&prefs.loop;s.awaitFinish=false;
 if(s.transport)s.pos=Math.min(s.transport.end,meta.a+m.duration*meta.speed);clearSources();s.transport=null;s.mode='idle';s.live=null;
 if(m.duration>.15&&(!m.hasAudio||m.blob?.size>44))storeTake(meta,m);
 if(['discontinuity','late-start'].includes(m.reason))error('Розрив аудіопотоку: запис завершено, щоб не зсувати його відносно пісні.');
 if(s.resumeAt!==null){const t=s.resumeAt;s.resumeAt=null;s.pos=t;sync();startTransport(true,true);return;}// seek during singing: new take from the new spot
 const canLoop=auto&&customRange(),cap=capacity(true);if(canLoop&&cap.ok)scheduleLoop(true);
 else{if(canLoop)toast('Повтор зупинено: '+cap.message);releaseMic();}sync();
}
function download(blob,filename){const u=URL.createObjectURL(blob),a=document.createElement('a');a.href=u;a.download=filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),15000);}
function takeFilename(t,ext){return 'Luma_'+song.title.replace(/[^\p{L}\p{N}_-]+/gu,'_')+'_take_'+String(t.id).padStart(2,'0')+'.'+ext;}
function saveWav(t){download(t.blob,takeFilename(t,'wav'));}
function saveCSV(t){const header='take_seconds,song_seconds,frequency_hz,midi,target_midi,cents_from_target,eligible_target,match_state,yin_periodicity,dbfs,speed,target_octave,mic_shift_ms\n';const rows=t.points.map(p=>[p.t.toFixed(5),p.songT.toFixed(5),p.f??'',p.m??'',p.ref??'',p.cents??'',p.eligible?1:0,frameState(t.score,p.songT),p.confidence,p.db,t.speed,t.octave,t.latency].join(','));download(new Blob([header+rows.join('\n')],{type:'text/csv;charset=utf-8'}),takeFilename(t,'csv'));}
function selectTrace(t){if(s.mode!=='idle'||s.busy||s.awaitFinish)return;s.trace={take:t,points:t.points,score:t.score};s.pos=clamp(s.pos,t.a,t.endSong);if(s.pos<=t.a||s.pos>=t.endSong)s.pos=t.a;setRangeScale();renderTakes();sync();}
function closeTrace(){s.trace=null;setRangeScale();renderTakes();sync();}
// Re-score a take under a new view or octave: audio and pitch points stay, only the comparison rules change. The
// history keeps the attempt as it was measured when it finished — the view is part of the comparison key, so a
// re-scored take belongs to a different ruler and does not overwrite the one it was sung under.
function rescoreTake(t,patch){
 Object.assign(t,patch,analyzeTake({...t,...patch},t.points,t.duration));
 // The summary and the record line were counted from the score that just went away. Both are recounted against the
 // ruler the attempt now carries — including the target map they are counted from, so the JSON the card exports
 // cannot stamp new frame counts with the map version the attempt happened to be sung under.
 t.mapVersion=mapVersion();
 try{const sum=summarizeRun(t);t.summary=sum;t.record=historyAvailable()&&s.hist.loaded?recordCaption(runRecord(t,sum)):null;}
 catch(_){t.summary=null;t.record=null;}
 if(s.trace?.take===t)s.trace={take:t,points:t.points,score:t.score};renderTakes();
}
function renderTakes(){const root=$('takesList');root.replaceChildren();for(const t of s.takes){
 const el=document.createElement('div');el.className='take'+(s.trace?.take===t?' current':'');const playing=s.trace?.take===t&&s.mode==='review';const play=document.createElement('button');play.className='play';play.innerHTML=icon(playing?'pause':'play');play.ariaLabel=(playing?'Зупинити':t.hasAudio?'Прослухати':'Слухати з мінусом')+' спробу '+t.id;play.title=playing?'Зупинити':t.hasAudio?'Прослухати свій голос поверх мінусу':'Слухати з мінусом: голосу в цій спробі немає, лінія йде синхронно';play.onclick=()=>playTake(t);
 // an attempt brought back from the history says when it was sung: the proof that the line outlived the tab
 const d=new Date(t.startedAt),two=n=>String(n).padStart(2,'0'),when=t.restored&&!isNaN(d)?two(d.getDate())+'.'+two(d.getMonth()+1)+' '+two(d.getHours())+':'+two(d.getMinutes())+' · ':'';
 const title=document.createElement('button');title.className='take-title';title.title='Показати слід цієї спроби на графіку · перемотай усередину і натисни «Дописати», щоб перезаписати з цього місця';title.innerHTML='Спроба '+String(t.id).padStart(2,'0')+' · '+fmt(t.a)+'–'+fmt(t.endSong)+'<small>'+when+t.speed+'× · '+levelLabel(t.score.opt)+' · '+(t.octave?(t.octave>0?'+':'')+t.octave+' пт · ':'')+(t.hasAudio?(t.sampleRate/1000).toFixed(1)+' kHz':'без аудіо')+(t.clipped?' · перевантаження':'')+(t.punches?' · перезаписів: '+t.punches:'')+(t.historyError?' · не записано в історію':'')+'</small>';title.onclick=()=>selectTrace(t);
 const st=document.createElement('div');st.className='take-stats';const pct=scorePct(t.score);const vals=[['Збіг',pct===null?'—':pct+'%',pct===null?'у фрагменті немає намальованих нот':'влучання '+(t.score.hit*GRID).toFixed(1)+' с із '+(t.score.target*GRID).toFixed(1)+' с цілі · ±'+t.tolerance+'¢ '+levelLabel(t.score.opt)+' · тиша = промах']];
 if(t.stats.targetTime>.1)vals.push(['У коридорі',t.stats.accuracy===null?'—':Math.round(t.stats.accuracy)+'%','підтверджена ціль · серед порівняних точок'],['Покриття',Math.round(t.stats.coverage||0)+'%','порівняно '+t.stats.compared.toFixed(1)+' с із '+t.stats.targetTime.toFixed(1)+' с підтвердженої цілі'],['Медіана |Δ|',t.stats.median===null?'—':Math.round(t.stats.median)+'¢','']);
 for(const [label,value,tip]of vals){const span=document.createElement('span'),b=document.createElement('strong');b.textContent=value;span.append(b,document.createTextNode(label));span.title=tip;st.append(span);}
 if(t.record){const n=document.createElement('span');n.className='rec-delta'+(t.record.delta>0?' up':t.record.delta<0?' down':'');n.textContent=t.record.text;n.title=t.record.title;st.append(n);}
 if(t.stats.targetTime<=.1){const n=document.createElement('span');n.className='none';n.textContent='Попередня оцінка за чернеткою';n.title='Прослухай накладання та перевір мелодію-ціль. Сам факт знайденої ноти не доводить, що це головний вокал.';st.append(n);}
 // Export is a download on request, never a condition of keeping: one quiet ↓ per card, the formats folded behind it.
 const actions=document.createElement('div');actions.className='take-actions';const files=document.createElement('span');files.className='take-files';files.id='takeFiles'+t.id;files.hidden=!t.filesOpen;
 const button=(label,fn,tip)=>{const b=document.createElement('button');b.textContent=label;b.title=tip;b.setAttribute('aria-label',tip);b.onclick=fn;return b;};
 for(const [label,fn,tip]of [...(t.hasAudio?[['WAV',()=>saveWav(t),'Завантажити голос цієї спроби у WAV']]:[]),['CSV',()=>saveCSV(t),'Завантажити CSV: лінія голосу і стан кожної точки'],['JSON',()=>saveTakeJSON(t),'Завантажити спробу файлом історії Luma: метадані, оцінка і стиснута лінія']])files.append(button(label,fn,tip));
 const exp=button('',()=>{t.filesOpen=!t.filesOpen;files.hidden=!t.filesOpen;exp.setAttribute('aria-expanded',String(!!t.filesOpen));},'Завантажити спробу '+String(t.id).padStart(2,'0')+' файлом');
 exp.className='take-export';exp.innerHTML=icon('download');exp.setAttribute('aria-expanded',String(!!t.filesOpen));exp.setAttribute('aria-controls',files.id);
 const cleared=t.cleared&&!s.hist.runs.some(r=>r.id===t.runId);
 actions.append(files,exp,button('×',()=>removeTake(t),t.historyError?'Видалити спробу з вкладки · в історії її немає':cleared?'Видалити спробу з вкладки · історію пісні очищено':'Видалити спробу з вкладки · в історії вона лишається'));
 el.append(play,title,st,actions);root.append(el);
 }
 if(!s.takes.length&&s.hist.runs.length){const p=document.createElement('p');p.className='takes-empty';
  p.textContent='У цій вкладці спроб ще немає. Те, що ти співав раніше, — у вкладці «Прогрес».';root.append(p);}
 $('takesCount').textContent=s.takes.length;$('takesPanel').dataset.empty=s.takes.length?'0':'1';renderProgress();}
// ── Progress tab ────────────────────────────────────────────────────────────────────────────────────────────────
// The attempt panel gets two tabs instead of one heading; nothing is added inside .stage, so the geometry the stage
// redesign made reliable stays untouched. Mint means better, muted rose means worse, and every bar carries its number.
const WEAK_SHOWN=12;let trendWatch=null;
function pct100(v){return v===null||v===undefined?null:clamp(Math.round(v/100),0,100);}
function pctText(v){const p=pct100(v);return p===null?'—':p+'%';}
function underTarget(frames){const sec=frames*GRID;return sec<60?Math.round(sec)+' с':Math.round(sec/60)+' хв';}
function streakDays(){
 const byDay=new Map();for(const d of s.hist.days)byDay.set(d.localDay,(byDay.get(d.localDay)||0)+d.target);
 let day=localDay(Date.now()),n=0;
 if((byDay.get(day)||0)<HIST.streakFrames)day=dayShift(day,-1);// today may simply not have happened yet
 while((byDay.get(day)||0)>=HIST.streakFrames){n++;day=dayShift(day,-1);}
 return n;
}
// A session is attempts less than 45 minutes apart. The newest one is what the footer reports.
function lastSession(runs,eligible){
 if(!runs.length)return null;
 const out=[runs[0]];
 for(let i=1;i<runs.length;i++){const gap=Date.parse(out[out.length-1].startedAt)-Date.parse(runs[i].startedAt);if(gap>HIST.sessionGap)break;out.push(runs[i]);}
 // Attempts and minutes count everything sung in the session; the best number obeys the same coverage floors as the
 // record above it, so a three-second fragment can never sit under «найкраще» next to a record over the whole song.
 const best=out.reduce((a,r)=>eligible.has(r.id)&&(a===null||eligible.get(r.id)>a)?eligible.get(r.id):a,null);
 return {count:out.length,frames:out.reduce((a,r)=>a+r.target,0),best};
}
function trendScope(){return s.trendScope==='song'||!customRange()?'song':'range';}
// The phrase the A–B region is currently sitting on, if it is sitting on one at all.
function scopePhrase(){
 if(trendScope()==='song')return null;
 const p=(song.phrases||[]).find(p=>Math.abs(p.a-s.range.a)<=.25&&Math.abs(p.b-s.range.b)<=.25);
 return p?p.id:null;
}
// What every number on the panel is counted over, as {id, match, medianCents, startedAt, localDay, target}. A full pass
// of the song carries a whole-song percentage, which says nothing about one phrase — so when the fragment lines up with
// a phrase, that phrase's own frames are read out of the attempt instead, the way docs/PROGRESS_DESIGN.md §4.2 has it:
// an arbitrary A–B has no entity of its own and decomposes into the phrases it covered. An A–B that is not a phrase can
// only be spoken for by an attempt recorded at that very fragment.
function scopeEntries(runs){
 const of=(r,match,medianCents,target)=>({id:r.id,run:r,match,medianCents,target,startedAt:r.startedAt,localDay:r.localDay});
 if(trendScope()==='song')
  return runs.filter(r=>r.match!==null&&r.songTarget&&r.target>=r.songTarget*HIST.songCover&&r.target>=HIST.minSongFrames)
   .map(r=>of(r,r.match,r.medianCents,r.target));
 const id=scopePhrase();
 if(id!==null){
  const out=[];
  for(const r of runs)for(const c of phraseCandidates(r))if(c.id===id&&c.target>=HIST.minPhraseFrames)out.push(of(r,c.match,c.medianCents,c.target));
  return out;
 }
 return runs.filter(r=>r.match!==null&&Math.abs(r.a-s.range.a)<=.25&&Math.abs(r.b-s.range.b)<=.25&&r.target>=HIST.minPhraseFrames)
  .map(r=>of(r,r.match,r.medianCents,r.target));
}
function trendRuns(runs){return scopeEntries(runs).slice(0,HIST.trendRuns).reverse();}
// Draft frames over frames with a target, for what the panel is about: the song, the phrase, or the A–B on screen.
function scopeDraft(view){
 const totals=targetTotals(view);
 if(trendScope()==='song')return {frames:totals.song,draft:totals.draft};
 const id=scopePhrase();
 if(id!==null)return {frames:totals.phrase.get(id)||0,draft:totals.phraseDraft.get(id)||0};
 const opt={octave:0,view};let frames=0,draft=0;
 for(let i=Math.ceil(s.range.a/GRID);i*GRID<=s.range.b;i++){const ref=targetAt(i*GRID,opt);if(!ref)continue;frames++;if(!ref.ok)draft++;}
 return {frames,draft};
}
function drawTrend(cv,list){
 const w=cv.clientWidth,h=cv.clientHeight,dpr=Math.min(window.devicePixelRatio||1,2);
 if(!w||!h)return;// a folded panel has no size to draw into; the observer draws once it has one
 cv.width=Math.round(w*dpr);cv.height=Math.round(h*dpr);const c=cv.getContext('2d');c.setTransform(dpr,0,0,dpr,0,0);c.clearRect(0,0,w,h);
 const pad=6,x=i=>list.length<2?w/2:pad+i/(list.length-1)*(w-2*pad),y=v=>h-pad-v/100*(h-2*pad);
 c.strokeStyle='#ffffff12';c.lineWidth=1;
 for(const line of [0,50,100]){c.beginPath();c.moveTo(0,Math.round(y(line))+.5);c.lineTo(w,Math.round(y(line))+.5);c.stroke();}
 if(!list.length)return;
 const vals=list.map(r=>pct100(r.match)??0);
 c.strokeStyle='#a1eed8a8';c.lineWidth=1.6;c.beginPath();// moving average over five attempts
 for(let i=0;i<vals.length;i++){const from=Math.max(0,i-4),avg=vals.slice(from,i+1).reduce((a,b)=>a+b,0)/(i-from+1);
  const xx=x(i),yy=y(avg);if(i)c.lineTo(xx,yy);else c.moveTo(xx,yy);}
 c.stroke();
 for(let i=0;i<vals.length;i++){c.beginPath();c.arc(x(i),y(vals[i]),2.4,0,Math.PI*2);c.fillStyle=i===vals.length-1?'#d9fdf4':'#9fb0c8';c.fill();}
}
// value is the number on the bar and in the column; mark is a second, named number drawn as a notch on the same track.
function barRow(label,value,mark,markLabel,onclick,note){
 const row=document.createElement('button');row.className='prog-bar';row.type='button';
 if(onclick)row.onclick=onclick;else row.disabled=true;
 const name=document.createElement('span');name.className='nm';name.textContent=label;
 const track=document.createElement('span');track.className='track';
 if(value===null){const em=document.createElement('em');em.className='none';em.textContent=note||'не співано';track.append(em);}
 else{const fill=document.createElement('span');fill.className='fill'+(value>=70?' good':value<40?' low':'');fill.style.width=clamp(value,0,100)+'%';track.append(fill);}
 if(value!==null&&mark!==null&&mark!==undefined){const i=document.createElement('i');i.className='mark';i.style.left=clamp(mark,0,100)+'%';i.title=markLabel+' '+mark+'%';track.append(i);}
 const num=document.createElement('span');num.className='num';num.textContent=value===null?'—':value+'%';
 row.append(name,track,num);
 row.title=label+' · '+(value===null?(note||'ще не зараховано жодної спроби')
  :'найкраще '+value+'%'+(mark!==null&&mark!==undefined?' · '+markLabel.toLowerCase()+' '+mark+'%':''));
 return row;
}
function weakRows(runs){
 const rec=records(runs),totals=targetTotals(prefs.view),out=[];
 for(const p of song.phrases||[]){
  const best=rec.phrases.get(p.id);
  // under 1.5 s of target in the whole phrase no attempt can ever count it: the phrase is short, not unsung
  const short=(totals.phrase.get(p.id)||0)<HIST.minPhraseFrames;
  // the same 1.5 s floor the record uses, so the notch can never mark an attempt too short to be counted
  let last=null;for(const r of runs){const c=phraseCandidates(r).find(c=>c.id===p.id&&c.target>=HIST.minPhraseFrames);if(c){last=c.match;break;}}
  out.push({id:p.id,label:p.label||('Фрагмент '+p.id),best:pct100(best?best.match:null),last:pct100(last),short});
 }
 // Worst first by the personal best: one bad take must not reshuffle the practice list, a phrase nobody has sung yet
 // stands at the bottom rather than pretending to be the weakest, and a phrase too short to count stands under it.
 out.sort((a,b)=>(a.best===null)-(b.best===null)||a.short-b.short||(a.best-b.best)||a.id-b.id);
 return out;
}
// A lesson trains a skill, not nine separate keys: rows are exercises, and each carries one lamp per level.
function exerciseRows(){
 const groups=new Map();
 for(const p of song.phrases||[]){const ex=exerciseOf(p);if(!groups.has(ex))groups.set(ex,[]);groups.get(ex).push(p.id);}
 const rows=[];
 for(const [ex,ids]of groups){
  const lamps=[];
  for(const level of ['easy','normal','strict']){
   const key=cmpKeyOf({mapVersion:mapVersion(),level,tolerance:LEVELS[level].tolerance,view:prefs.view,speed:prefs.speed});
   const list=s.hist.runs.filter(r=>r.cmpKey===key),rec=records(list);
   let best=null,count=0;
   for(const r of list)if(phraseCandidates(r).some(c=>ids.includes(c.id)))count++;
   for(const id of ids){const c=rec.phrases.get(id);if(c&&(best===null||c.match>best))best=c.match;}
   lamps.push({level,label:LEVELS[level].label,best:pct100(best),count});
  }
  rows.push({ex,ids,lamps});
 }
 return rows;
}
function progressSignature(){
 return [prefs.tab,prefs.shadow,currentKey(),s.trendScope||'',s.rangeId,s.range.a.toFixed(2),s.range.b.toFixed(2),
  s.hist.runs.length,s.hist.stamp||'',s.hist.note,s.hist.persisted,s.takes.length,s.weakAll].join('|');
}
function renderProgress(){
 const panel=$('takesPanel'),box=$('progressPanel');
 const has=s.takes.length||s.hist.runs.length;
 panel.hidden=!has;panel.dataset.tab=prefs.tab;
 $('tabTakes').setAttribute('aria-selected',String(prefs.tab==='takes'));
 $('tabProgress').setAttribute('aria-selected',String(prefs.tab==='progress'));
 $('takesList').hidden=prefs.tab!=='takes';box.hidden=prefs.tab!=='progress';
 // A statement of what happens by itself, never an instruction: the only other lines are the store's own failures.
 const refused=s.takes.filter(t=>t.historyError).length;
 $('takesHint').textContent=!historyAvailable()?'Історія не ведеться: відкрий пісню з бібліотеки Studio'
  :refused?'Не записано в історію: '+refused+' '+plural(refused,'спроба','спроби','спроб')+' · лишаються тут і запишуться, щойно сховище прийме запис'
  :s.hist.note?s.hist.note
  :'Лінія кожної спроби зберігається сама';
 $('takesHint').title=historyAvailable()&&!refused?'Натискати нічого не треба: коли знову відкриєш пісню, '+TRACE_TAKES+' останніх спроб з їхніми лініями будуть у цьому списку':'';
 if(panel.hidden||prefs.tab!=='progress')return;
 const sig=progressSignature();if(sig===s.progressSig)return;s.progressSig=sig;
 buildProgress(box);
}
function buildProgress(box){
 box.replaceChildren();
 const key=currentKey(),runs=s.hist.runs.filter(r=>r.cmpKey===key),today=localDay(Date.now());
 const whole=trendScope()==='song',phraseId=scopePhrase(),scored=scopeEntries(runs);
 let best=null;for(const e of scored)if(better(e,best))best=e;
 const last5=scored.slice(0,5),bestToday=scored.filter(e=>e.localDay===today).reduce((a,e)=>a===null||e.match>a?e.match:a,null);
 const of=whole?'повних проходів пісні':phraseId!==null?'зарахованих проходів цієї фрази':'спроб цього фрагмента';
 // 1 · the numbers, all counted over the same attempts as the trend below
 // A record over draft targets is a preliminary one, and says so the way the attempt card does.
 const share=scopeDraft(prefs.view),soft=!!best&&share.draft>0;
 const draftPct=!share.draft?'0%':share.draft*200<share.frames?'<1%':Math.round(100*share.draft/share.frames)+'%';
 const row=document.createElement('div');row.className='prog-nums';
 const cells=[[soft?'Рекорд · за чернеткою':'Рекорд',best?pctText(best.match):'—',best?(whole?'найкращий повний прохід':'найкраща спроба цього фрагмента')+' · '+String(best.startedAt).slice(0,10)+(soft?' · попередній: '+draftPct+' цілей тут — чернетка мелодії':''):whole?'Ще немає повного проходу цієї пісні':'Ще немає зарахованої спроби цього фрагмента'],
  ['Останні 5',last5.length?Math.round(last5.reduce((a,e)=>a+e.match,0)/last5.length/100)+'%':'—','середній збіг останніх '+last5.length+' '+of],
  ['Сьогодні',pctText(bestToday),'найкраще за цю добу серед '+of],
  ['Серія днів',String(streakDays()),'дні поспіль, у кожному щонайменше 2 хв кадрів із ціллю']];
 for(const [label,value,tip]of cells){const cell=document.createElement('div');cell.className='prog-num';cell.title=tip;
  const v=document.createElement('b');v.textContent=value;const l=document.createElement('span');l.textContent=label;cell.append(v,l);row.append(cell);}
 const ruler=document.createElement('p');ruler.className='prog-ruler';
 ruler.textContent='Лінійка: '+levelLabel(levelOpt())+' · '+(prefs.view==='notes'?'Ноти':'Контур')+' · '+prefs.speed+'× · карта '+mapVersion().slice(-8)
  +' · чернеткових цілей '+draftPct+' · область: '+(whole?'вся пісня':phraseId!==null?phraseLabel(phraseId):'фрагмент '+fmt(s.range.a)+'–'+fmt(s.range.b));
 box.append(row,ruler);
 // 2 · trend
 const head=document.createElement('div');head.className='prog-head';
 const title=document.createElement('h3');title.textContent='Тренд';head.append(title);
 const seg=document.createElement('div');seg.className='segmented';seg.setAttribute('aria-label','Область тренду');
 for(const [id,label]of [['song','Вся пісня'],['range','Поточний фрагмент']]){
  const b=document.createElement('button');b.textContent=label;b.className=trendScope()===id?'active':'';b.setAttribute('aria-pressed',String(trendScope()===id));
  b.disabled=id==='range'&&!customRange();b.onclick=()=>{s.trendScope=id;s.progressSig='';renderProgress();};seg.append(b);}
 head.append(seg);box.append(head);
 const list=trendRuns(runs);
 const cv=document.createElement('canvas');cv.className='prog-trend';cv.setAttribute('role','img');
 cv.setAttribute('aria-label','Збіг останніх '+list.length+' спроб: '+(list.map(e=>pctText(e.match)).join(', ')||'спроб ще немає'));
 box.append(cv);
 const note=document.createElement('p');note.className='prog-note';
 const octaves=new Set(list.map(e=>e.run.octave));
 note.textContent=list.length?(list.length+' '+plural(list.length,'спроба','спроби','спроб')+' · точки в часі, лінія — середнє по п’яти'
  +(octaves.size>1?' · спроби співано в різних вокальних октавах':'')):'Тут з’явиться крива збігу, коли буде хоча б одна зарахована спроба цієї лінійки.';
 box.append(note);
 // drawn whenever the canvas takes a size: now, when a folded panel opens, when the window narrows
 trendWatch?.disconnect();trendWatch=new ResizeObserver(()=>drawTrend(cv,list));trendWatch.observe(cv);
 // 3 · weak places, or the lesson's exercises
 const h2=document.createElement('h3');h2.textContent=song.lesson?'Вправи':'Слабкі місця';box.append(h2);
 const rows=document.createElement('div');rows.className='prog-rows';
 if(song.lesson){
  for(const r of exerciseRows()){
   const line=document.createElement('div');line.className='prog-ex';
   const nm=document.createElement('span');nm.className='nm';nm.textContent=r.ex;line.append(nm);
   for(const lamp of r.lamps){
    const el=document.createElement('span');const on=lamp.best!==null&&lamp.best>=HIST.lamp;
    el.className='lamp'+(on?' on':lamp.best===null?' empty':'');
    el.textContent=lamp.label+' '+(lamp.best===null?'—':lamp.best+'%');
    el.title=lamp.label+' · найкраще '+(lamp.best===null?'ще не співано':lamp.best+'%')+' · спроб: '+lamp.count+' · лампа світиться від '+HIST.lamp+'%';
    line.append(el);}
   rows.append(line);}
 }else if(!(song.phrases||[]).length){
  const empty=document.createElement('p');empty.className='prog-note';empty.textContent='У цій пісні немає готових фраз, тож карта слабких місць порожня. Виділи фрагмент — тренд рахуватиметься по ньому.';rows.append(empty);
 }else{
  // A four-minute song has dozens of phrases and most of them are still unsung: the worst twelve are the map, the rest
  // are one line until you ask for them.
  const all=weakRows(runs),shown=s.weakAll?all:all.slice(0,WEAK_SHOWN);
  for(const w of shown){const bar=barRow(w.label,w.best,w.last,'Остання спроба',()=>{
   const p=(song.phrases||[]).find(p=>p.id===w.id);if(!p||s.mode!=='idle'||s.busy||s.awaitFinish)return;
   closeTrace();setRange(p.a,p.b,p.id);s.pos=p.a;setRangeScale();sync();toast('Фрагмент: '+(p.label||('Фрагмент '+p.id)));},w.short?'закоротка для рекорду':'');
   if(w.short)bar.title+=': у фразі менше 1.5 с нот';
   rows.append(bar);}
  if(all.length>shown.length){const more=document.createElement('button');more.className='ghost sm prog-more';
   const rest=all.length-shown.length,unsung=all.slice(shown.length).filter(w=>w.best===null&&!w.short).length;
   more.textContent='Показати решту '+rest+' '+plural(rest,'фразу','фрази','фраз')+(unsung?' · без зарахованої спроби: '+unsung:'');
   more.onclick=()=>{s.weakAll=true;s.progressSig='';renderProgress();};rows.append(more);}
 }
 box.append(rows);
 // 4 · footer: where the history lives and what you can do with it
 const foot=document.createElement('div');foot.className='prog-foot';
 const state=document.createElement('p');state.className='prog-note';
 const session=lastSession(runs,new Map(scored.map(e=>[e.id,e.match])));
 state.textContent=(s.hist.note?s.hist.note+' ':'')
  +(session?'Остання сесія: '+session.count+' '+plural(session.count,'спроба','спроби','спроб')+' · '+underTarget(session.frames)+' під ціллю'
   +(session.best===null?' · '+(whole?'без повного проходу':'без зарахованої спроби цього фрагмента'):' · найкраще '+pctText(session.best))+'. ':'')
  +(historyAvailable()?'Історія лежить у цьому браузері, на цьому комп’ютері.':'');
 foot.append(state);
 const acts=document.createElement('div');acts.className='prog-actions';
 for(const [label,tip,fn]of [
  ['Експорт пісні','Завантажити історію цієї пісні файлом',()=>doExport(false)],
  ['Експорт усього','Завантажити історію всіх пісень файлом',()=>doExport(true)],
  ['Імпорт','Прочитати файл історії; повтори пропускаються',()=>$('historyFile').click()],
  ['Очистити пісню','Видалити історію цієї пісні з цього браузера',doClear]]){
  const b=document.createElement('button');b.className='ghost sm';b.textContent=label;b.title=tip;b.setAttribute('aria-label',tip);b.onclick=fn;b.disabled=!historyAvailable();acts.append(b);}
 foot.append(acts);box.append(foot);
}
function doExport(all){
 exportPayload(all).then(payload=>{
  const name='Luma_'+(all?'history':song.title.replace(/[^\p{L}\p{N}_-]+/gu,'_')+'_history')+'.json';
  download(new Blob([JSON.stringify(payload)],{type:'application/json'}),name);
  toast('Експортовано '+payload.runs.length+' '+plural(payload.runs.length,'спробу','спроби','спроб')+'.');
 }).catch(e=>error(readable(e,'Не вдалося експортувати історію.')));
}
function doClear(){
 if(!confirm('Видалити історію цієї пісні з цього браузера? Лінії й оцінки всіх її спроб зникнуть з історії.'))return;
 clearSongHistory().then(n=>toast('Видалено '+n+' '+plural(n,'спробу','спроби','спроб')+' з історії.')).catch(e=>error(readable(e,'Не вдалося очистити історію.')));
}
async function importHistoryFile(file){
 if(!file)return;
 if(file.size>200*1024*1024){error('Файл історії завеликий: максимум 200 МіБ.');return;}
 try{const d=JSON.parse(await file.text());const r=await importHistory(d);
  toast(r.imported?'Імпортовано '+r.imported+' '+plural(r.imported,'спробу','спроби','спроб')+(r.skipped?', пропущено повторів: '+r.skipped:'')+'.':'Нових спроб у файлі не було: усі вже в історії.');
 }catch(e){error(readable(e,'Не вдалося прочитати файл історії.'));}
}
function removeTake(t){if(s.mode!=='idle'||s.awaitFinish||s.busy){toast('Спочатку зупини відтворення або запис.');return;}
 // Only a line that exists nowhere else is worth a question; anything the history holds just leaves the tab.
 if(t.historyError&&!confirm('Цієї спроби немає в історії: сховище браузера її не прийняло, тож з вкладки вона зникне назавжди. Видалити?'))return;if(s.undoPunch?.after===t)clearUndoPunch();s.takes=s.takes.filter(x=>x.id!==t.id);if(t.url)URL.revokeObjectURL(t.url);if(s.trace?.take===t)s.trace=null;markUnsaved();renderTakes();sync();}
async function playTake(t){
 if(s.busy||s.awaitFinish)return;if(s.mode!=='idle'){stopTransport('user');renderTakes();return;}clearTimeout(s.nextTimer);const token=++s.cancel;s.busy=true;s.busyFor='review';sync();
 try{await ensureContext();const b=await buffers(t.speed);if(t.hasAudio&&!t.buffer)t.buffer=await s.ctx.decodeAudioData(await t.blob.arrayBuffer());if(token!==s.cancel)return;
  const changed=s.trace?.take!==t||s.pos<t.a||s.pos>=t.endSong-1;s.trace={take:t,points:t.points,score:t.score};if(s.pos<t.a||s.pos>=t.endSong-1)s.pos=t.a;// under a second left: replay from the start
  const off=s.pos-t.a,when=s.ctx.currentTime+.15,dur=t.duration-off/t.speed;s.transport={token,when,offset:s.pos,end:t.endSong,speed:t.speed,loop:null};s.mode='review';
  const lead=addSource(b.back,s.gains.back,when,s.pos/t.speed,dur);addSource(b.fore,s.gains.fore,when,s.pos/t.speed,dur);
  if(t.hasAudio)addSource(t.buffer,s.gains.voice,when,off/t.speed,dur,()=>{naturalEnd(token);});else lead.onended=()=>naturalEnd(token);if(changed)setRangeScale();
 }catch(e){error(e.message);}finally{if(token===s.cancel){s.busy=false;sync();renderTakes();}}
}
function resize(){const r=$('chartWrap').getBoundingClientRect(),q=$('timelineWrap').getBoundingClientRect();W=r.width;H=r.height;TW=q.width;TH=q.height;DPR=Math.min(window.devicePixelRatio||1,2);canvas.width=Math.round(W*DPR);canvas.height=Math.round(H*DPR);g.setTransform(DPR,0,0,DPR,0,0);tl.width=Math.round(TW*DPR);tl.height=Math.round(TH*DPR);tg.setTransform(DPR,0,0,DPR,0,0);measureStage();if(W>0&&H>0){s.dirty=false;draw(now());}else s.dirty=true;requestDraw();}
// The readout, the lyric band and the rail are flow items inside the stage; the plot takes what is left between them.
// Measured on layout changes only (resize and sync), never per frame, so the piano roll can never be drawn under them.
function measureStage(){const box=$('chartWrap').getBoundingClientRect();const below=el=>el&&!el.hidden?el.getBoundingClientRect().bottom-box.top:0;
 const dense=box.height<520||innerWidth<=720;if(dense!==s.dense){s.dense=dense;$('chartWrap').dataset.dense=dense?'1':'0';}
 s.headH=Math.max(below($('stageHead')),below($('lyricBand')));const rail=$('stageRail');s.railH=rail?box.bottom-rail.getBoundingClientRect().top:0;}
// Phones, and phones held sideways: the page scrolls, so the stage takes exactly the height that leaves «Співати» on the first
// screen — measured, not guessed, because the title, the hint banner and the browser chrome all move the space above it.
// Never called from the resize observer: it writes a length, and the observer only reads.
function fitStage(){const app=document.querySelector('.app');
 if(!matchMedia('(max-width:720px),(max-height:560px)').matches){if(s.stageH){s.stageH=0;app.style.removeProperty('--stage-h');}return;}
 const box=$('chartWrap').getBoundingClientRect(),btn=$('singBtn').getBoundingClientRect();
 const h=Math.round(clamp(innerHeight-(box.top+scrollY)-(btn.bottom-box.bottom)-6,200,760));
 if(Math.abs(h-(s.stageH||0))>1){s.stageH=h;app.style.setProperty('--stage-h',h+'px');}}
function bounds(){const narrow=W<720||s.dense,axis=narrow?22:26,left=narrow?42:56;
 // a folded head gets a thin lane instead of the 26 px the ЗАРАЗ caption needs
 const top=Math.min((s.headH||0)+(s.dense?12:26),H*.55),bottom=Math.max(top+40,H-(s.railH||0)-axis);
 return{left,right:W-16,top,bottom,laneTop:top-6};}
// Words ride the melody: each word sits just above the target pitch at its own moment; colliding labels stack upward, none is dropped.
function drawWords(t,v,x,y,b,opt){
 if(!prefs.lyrics||!song.lyrics.length)return;const font=(W<720?'600 14px ':'600 16px ')+getComputedStyle(document.body).getPropertyValue('--sans');g.font=font;g.textAlign='left';g.textBaseline='alphabetic';
 const placed=[];const rowH=W<720?19:22;
 for(const line of song.lyrics){if(line.a>v.b)break;if(line.b<v.a)continue;
  for(const w of line.words){if(w.a>v.b||w.b<v.a-.5)continue;const xx=x(w.a),tw=g.measureText(w.w).width;
   // anchor: median target pitch inside the word, else the nearest target within 0.6 s, else the plot centre line
   const ms=[];for(let q=w.a;q<=w.b+1e-6;q+=.04){const r=targetAt(q,opt);if(r)ms.push(r.m);}
   let m=null;if(ms.length){ms.sort((p,q)=>p-q);m=ms[ms.length>>1];}else{for(let d=.04;d<=.6&&m===null;d+=.04){const r=targetAt(w.a-d,opt)||targetAt(w.b+d,opt);if(r)m=r.m;}}
   let yy=(m===null?(b.top+b.bottom)/2:clamp(y(m),b.top+rowH,b.bottom))-11;
   for(let k=0;k<6;k++){const hit=placed.some(p=>xx<p.x1+6&&xx+tw>p.x0-6&&Math.abs(yy-p.y)<rowH-1);if(!hit)break;yy-=rowH;}
   if(yy<b.top+4)yy=b.top+4;placed.push({x0:xx,x1:xx+tw,y:yy});
   const on=t>=w.a&&t<w.b+.08,past=t>=w.b;g.globalAlpha=(w.c??1)<.5?.72:1;
   g.fillStyle='#0c111aec';g.beginPath();g.roundRect(xx-5,yy-(W<720?13:15),tw+10,W<720?18:21,5);g.fill();// halo so the word stays legible over the lines
   g.fillStyle=on?'#f2f8ff':past?'#a6b3c8':'#c6d0e0';g.fillText(w.w,xx,yy);if(on){g.fillStyle='#a1eed8';g.fillRect(xx,yy+3.5,tw,1.8);}
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
// A hit is the only solid bar on the roll, so the ✓ and the note name on it are dark ink on mint, the same pairing as the
// contour marker. At the old 33 % wash the dark label measured 2.2:1 against its own bar.
const HIT_FILL='#a1eed899',HIT_CUR='#a1eed8d6',HIT_INK='#0d2620';
// Diagonal hatch behind a missed note: hit and miss stay apart for an eye that does not read the colours.
let missPat=null,probe=null;
function missHatch(){if(missPat)return missPat;const c=document.createElement('canvas');c.width=c.height=7;const h=c.getContext('2d');
 h.strokeStyle='#dd8f9759';h.lineWidth=1.2;h.beginPath();h.moveTo(-2,7);h.lineTo(7,-2);h.moveTo(1,10);h.lineTo(10,1);h.stroke();missPat=g.createPattern(c,'repeat');return missPat;}
function draw(t){
 if(!g)return;const b=bounds(),v=view(t);followRange(v,t);const x=a=>b.left+(a-v.a)/v.span*(b.right-b.left),y=m=>b.bottom-(m-s.rangeLo)/(s.rangeHi-s.rangeLo)*(b.bottom-b.top);const rowH=(b.bottom-b.top)/(s.rangeHi-s.rangeLo);
 const mono=getComputedStyle(document.body).getPropertyValue('--mono'),sans=getComputedStyle(document.body).getPropertyValue('--sans');
 // stage light: the roll sits on a lit surface that falls off downwards instead of a flat field
 const lit=g.createLinearGradient(0,0,0,H);lit.addColorStop(0,'#121a27');lit.addColorStop(.5,'#0e131d');lit.addColorStop(1,'#0a0e16');
 g.fillStyle=lit;g.fillRect(0,0,W,H);
 g.fillStyle='#090d15';g.fillRect(0,0,b.left-7,H);// pitch rail: note names keep their own strip, off the roll
 g.strokeStyle='#ffffff0a';g.lineWidth=1;g.beginPath();g.moveTo(b.left-6.5,0);g.lineTo(b.left-6.5,H);g.stroke();
 // piano-roll rows: black keys in a darker band, C lines drawn and named clearly, every other semitone a whisper
 const named=n=>{const pc=(n%12+12)%12;return pc===0||(rowH>=16||(rowH>=11?!BLACK.has(pc):rowH>=7&&(pc===4||pc===7)));};
 g.textAlign='right';g.textBaseline='middle';
 for(let n=Math.ceil(s.rangeLo);n<=s.rangeHi;n++){const yy=y(n),pc=(n%12+12)%12,isC=pc===0;
  if(BLACK.has(pc)){g.fillStyle='#ffffff05';g.fillRect(b.left,y(n+.5),b.right-b.left,rowH);}
  g.strokeStyle=isC?'#9fb4d133':'#93a8c40f';g.lineWidth=1;g.beginPath();g.moveTo(b.left,y(n+.5));g.lineTo(b.right,y(n+.5));g.stroke();
  if(!named(n))continue;g.font=(isC?'600 ':'')+'11px '+mono;g.fillStyle=isC?'#d3deee':BLACK.has(pc)?'#93a2b8':'#b3c1d6';g.fillText(name(n),b.left-11,yy);}
 g.textAlign='center';g.font='11px '+mono;const tstep=v.span>10?2:1;
 for(let a=Math.ceil(v.a);a<v.b;a++){const xx=x(a),major=a%tstep===0;
  g.strokeStyle=major?'#93a8c414':'#93a8c407';g.beginPath();g.moveTo(xx,b.top);g.lineTo(xx,b.bottom+(major?6:3));g.stroke();
  if(a>=0&&major){g.fillStyle='#93a2b8';g.fillText(fmt(a),xx,b.bottom+(W<720?15:17));}}
 const nowX=x(t);g.fillStyle='#05080e2b';g.fillRect(b.left,b.top,nowX-b.left,b.bottom-b.top);
 // loop region edges on the plot
 if(customRange()){for(const edge of [s.range.a,s.range.b]){const xe=x(edge);if(xe<b.left||xe>b.right)continue;g.strokeStyle='#b4a2eb82';g.lineWidth=1;g.setLineDash([5,4]);g.beginPath();g.moveTo(xe,b.top);g.lineTo(xe,b.bottom);g.stroke();g.setLineDash([]);}
  g.fillStyle='#b4a2eb0c';const xa=clamp(x(s.range.a),b.left,b.right),xb=clamp(x(s.range.b),b.left,b.right);if(xb>xa)g.fillRect(xa,b.top,xb-xa,b.bottom-b.top);}
 g.save();g.beginPath();g.rect(b.left,b.top,b.right-b.left,b.bottom-b.top);g.clip();const opt=effective(),sc=activeScore(),pts=activePoints();
 const tolH=Math.max(4,opt.tolerance/100*rowH*2),barH=clamp(rowH*.74,7,26);
 if(opt.view==='notes'){
  for(const n of song.notes){if(n.a>v.b)break;if(n.b<v.a)continue;const xx=x(n.a),ww=Math.max(2,x(n.b)-xx),yy=y(n.m+opt.octave);const ok=(n.ok||n.manual)&&!n.ignored;
   const kind=n.ignored?null:noteKind(sc,n.id),missed=kind==='miss'||kind==='silent';const cur=t>=n.a&&t<n.b,curState=cur?frameState(sc,t-.03):0;
   // tolerance corridor behind the bar
   if(!n.ignored){g.fillStyle=kind==='hit'?'#a1eed812':kind?'#c9707a10':ok?'#b4a2eb14':'#9a94b40c';g.fillRect(xx,yy-tolH/2,ww,tolH);}
   // outline and fill carry the state on their own: solid + filled = hit, solid + hatched = miss, dashed = draft or ignored
   let fill,stroke,dash=[],glyph='',ink;
   if(n.ignored){fill='#7f89900c';stroke='#6b768747';dash=[2,3];ink='#aab4c5';}
   else if(kind==='hit'){fill=cur&&curState===1?HIT_CUR:HIT_FILL;stroke='#c8fbee';glyph='✓';ink=HIT_INK;}
   else if(missed){fill='#c9707a14';stroke='#dd8f97';dash=kind==='silent'?[2,3]:[];glyph='×';ink='#ffdbdf';}
   else{fill=ok?'#b4a2eb3a':'#9a94b41c';stroke=ok?'#c9baf4':'#aaa4c4';dash=ok?[]:[4,3];ink=ok?'#f2edff':'#dcd8ea';
    if(cur&&curState===1){fill=HIT_CUR;stroke='#d8fff4';ink=HIT_INK;}else if(cur&&curState===2){fill='#c9707a45';stroke='#e6a0a8';ink='#ffdbdf';}}
   g.globalAlpha=n.b<t&&!kind?.75:1;
   g.beginPath();g.roundRect(xx,yy-barH/2,ww,barH,Math.min(4,ww/2,barH/2));g.fillStyle=fill;g.fill();
   if(missed){g.fillStyle=missHatch();g.fill();}
   g.strokeStyle=stroke;g.lineWidth=cur?1.7:1.1;g.setLineDash(dash);g.stroke();g.setLineDash([]);
   if(cur&&curState===1&&s.mode!=='idle'){g.shadowColor='#a1eed8';g.shadowBlur=16;g.strokeStyle='#d8fff4';g.stroke();g.shadowBlur=0;}
   if(ww>=32&&barH>=10&&!n.ignored){const label=glyph?glyph+' '+name(n.m+opt.octave):name(n.m+opt.octave);g.font='11px '+mono;g.textAlign='left';g.textBaseline='middle';g.fillStyle=ink;g.fillText(label,xx+6,yy);
    if(probe)probe.push({id:n.id,kind:kind||(ok?'target':'draft'),cur:cur&&curState>0,x:xx,y:yy,w:ww,h:barH,label,ink,tx:xx+6,tw:g.measureText(label).width,alpha:g.globalAlpha});}
   else if(glyph&&ww>=12){g.font='600 11px '+sans;g.textAlign='center';g.textBaseline='middle';g.fillStyle=ink;g.fillText(glyph,xx+ww/2,yy);
    if(probe)probe.push({id:n.id,kind,cur:cur&&curState>0,x:xx,y:yy,w:ww,h:barH,label:glyph,ink,tx:xx+ww/2-g.measureText(glyph).width/2,tw:g.measureText(glyph).width,alpha:g.globalAlpha});}
  }g.globalAlpha=1;
 }else{
  g.lineCap='round';g.lineJoin='round';
  let last=null;for(const p of song.points){if(p[0]<v.a-.03)continue;if(p[0]>v.b+.03)break;const r=targetAt(p[0],opt);if(!r){last=null;continue;}const pt={t:p[0],m:r.m,ok:r.ok};
   if(last&&pt.t-last.t<.05&&Math.abs(pt.m-last.m)<8){const st=frameState(sc,pt.t);g.beginPath();g.moveTo(x(last.t),y(last.m));g.lineTo(x(pt.t),y(pt.m));
    g.strokeStyle=st===1?'#a1eed8d8':st>=2?'#c9707ac0':pt.ok?'#b4a2ebc4':'#aaa4c4b0';g.lineWidth=pt.ok?2.6:1.9;g.setLineDash(pt.ok?[]:[3,3]);g.stroke();g.setLineDash([]);}
   last=pt;}
  // Hit and miss stay readable in contour mode too: a filled disc against a dashed ring, each with its own glyph.
  let lastMark=-Infinity;g.textAlign='center';g.textBaseline='middle';
  for(const n of song.notes){if(n.a>v.b)break;if(n.b<v.a||n.ignored)continue;const kind=noteKind(sc,n.id),xx=x((n.a+n.b)/2);if(!kind||xx-lastMark<21)continue;lastMark=xx;
   const yv=y(n.m+opt.octave),yy=yv+19<=b.bottom-10?yv+19:yv-19>=b.top+10?yv-19:clamp(yv,b.top+10,b.bottom-10),hit=kind==='hit';
   g.beginPath();g.arc(xx,yy,8,0,Math.PI*2);
   if(hit){g.fillStyle='#a1eed8';g.fill();}
   else{g.fillStyle='#0d121b';g.fill();g.strokeStyle='#dd8f97';g.lineWidth=1.3;g.setLineDash([3,2.4]);g.stroke();g.setLineDash([]);}
   g.font='600 11px '+sans;g.fillStyle=hit?'#0d2620':'#f0b5bb';g.fillText(hit?'✓':'×',xx,yy+.5);}
 }
 // shadow of the personal best for this fragment: 1 px, no halo, under everything the current attempt draws
 if(prefs.shadow&&s.shadow&&s.shadow.points.length){const path=new Path2D();let last=null;const shift=opt.octave-s.shadow.octave;
  for(const p of s.shadow.points){if(p.songT>v.b)break;
   if(p.m===null||p.confidence<.8){last=null;continue;}
   if(last&&p.songT>=v.a-.3&&p.songT-last.songT<=.11&&Math.abs(p.m-last.m)<=3.5){path.moveTo(x(last.songT),y(last.m+shift));path.lineTo(x(p.songT),y(p.m+shift));}
   last=p;}
  g.lineWidth=1;g.lineJoin='round';g.lineCap='round';g.strokeStyle='#95a3b899';g.stroke(path);}
 // sung trace: a soft halo around the voice, crisp core on top; mint inside the corridor, subdued red outside, dim with no target
 if(pts.length){const review=s.mode!=='singing';const upTo=review?v.b+.1:t+.03;const paths=tracePaths(pts,x,y,sc,upTo);
  g.lineJoin='round';g.lineCap='round';
  const pass=(alpha)=>{g.globalAlpha=alpha;
   g.lineWidth=12;g.strokeStyle='#a1eed80f';g.stroke(paths[1]);g.lineWidth=6.5;g.strokeStyle='#a1eed826';g.stroke(paths[1]);
   g.lineWidth=6.5;g.strokeStyle='#c9707a1c';g.stroke(paths[2]);
   g.lineWidth=2.6;g.strokeStyle='#d9fdf4';g.stroke(paths[1]);g.lineWidth=2.2;g.strokeStyle='#dd8f97';g.stroke(paths[2]);
   g.lineWidth=1.7;g.strokeStyle='#93b8b0aa';g.stroke(paths[0]);};
  if(review){// dim the part after the playhead so the eye follows the cursor
   g.save();g.beginPath();g.rect(b.left,b.top,nowX-b.left,b.bottom-b.top);g.clip();pass(1);g.restore();g.save();g.beginPath();g.rect(nowX,b.top,b.right-nowX,b.bottom-b.top);g.clip();pass(.42);g.restore();}
  else pass(1);g.globalAlpha=1;
  let p=null;if(!review){p=pts[pts.length-1];if(p&&(p.m===null||t-p.songT>=.2))p=null;}else{p=pointNear(pts,t,.06);}
  if(p&&p.m!==null&&p.m!==undefined){const xx=x(p.songT),yy=y(p.m),st=frameState(sc,p.songT),c=st===1?'#d9fdf4':st>=2?'#f0b5bb':'#a7cdc4';
   g.fillStyle=(st>=2?'#c9707a':'#a1eed8')+'1f';g.beginPath();g.arc(xx,yy,12,0,Math.PI*2);g.fill();
   g.strokeStyle=c;g.lineWidth=1.4;g.beginPath();g.arc(xx,yy,5.5,0,Math.PI*2);g.stroke();g.fillStyle=c;g.beginPath();g.arc(xx,yy,2.6,0,Math.PI*2);g.fill();}
 }
 drawWords(t,v,x,y,b,opt);
 g.restore();
 g.strokeStyle='#dff0ea52';g.lineWidth=1;g.setLineDash([2,5]);g.beginPath();g.moveTo(nowX,b.laneTop-(s.dense?0:8));g.lineTo(nowX,b.bottom);g.stroke();g.setLineDash([]);
 // the caption above the playhead is the first thing a short stage gives up: the dashed line already says where now is
 if(!s.dense){g.fillStyle='#a9c8c1';g.font='600 11px '+sans;g.letterSpacing='1.4px';g.textAlign='center';g.textBaseline='middle';g.fillText('ЗАРАЗ',nowX,b.laneTop-15);g.letterSpacing='0px';}
 drawTimeline(t);
}
function pointNear(a,t,tol){let lo=0,hi=a.length;while(lo<hi){const m=(lo+hi)>>1;if(a[m].songT<t)lo=m+1;else hi=m;}let p=a[Math.min(lo,a.length-1)];const prev=a[lo-1];if(prev&&(!p||Math.abs(prev.songT-t)<Math.abs(p.songT-t)))p=prev;return p&&Math.abs(p.songT-t)<=tol?p:null;}
function drawTimeline(t){tg.fillStyle='#0a0e16';tg.fillRect(0,0,TW,TH);const w=song.waveform||[],x=v=>v/song.duration*TW,WH=TH-LOOP_LANE,cr=customRange();
 // loop lane under the wave: drag here (or Shift-drag anywhere) to set the A–B region
 tg.fillStyle='#ffffff07';tg.fillRect(0,WH,TW,LOOP_LANE);tg.fillStyle='#ffffff0d';tg.fillRect(0,WH,TW,1);
 if(cr){tg.fillStyle='#b4a2eb16';tg.fillRect(x(s.range.a),0,x(s.range.b)-x(s.range.a),WH);tg.fillStyle=prefs.loop?'#b4a2eb':'#b4a2eb85';tg.beginPath();tg.roundRect(x(s.range.a),WH+4,Math.max(3,x(s.range.b)-x(s.range.a)),LOOP_LANE-8,3);tg.fill();
  for(const e of [s.range.a,s.range.b]){tg.fillStyle='#ece4ff';tg.beginPath();tg.roundRect(x(e)-2.5,WH+2,5,LOOP_LANE-4,2.5);tg.fill();}}
 else{tg.fillStyle='#a3b1c6';tg.font='11px '+getComputedStyle(document.body).getPropertyValue('--sans');tg.textAlign='left';tg.textBaseline='middle';tg.fillText('повтор: тягни тут',8,WH+LOOP_LANE/2);}
 if(traceShown()){const tk=s.trace.take;tg.fillStyle='#a1eed826';tg.fillRect(x(tk.a),WH-4,x(tk.endSong)-x(tk.a),3);for(const r of missRuns(s.trace.score)){tg.fillStyle='#dd8f97';tg.fillRect(x(r.a),WH-4,Math.max(1.5,x(r.b)-x(r.a)),3);}}
 for(let i=0;i<w.length;i++){const xx=i/w.length*TW,hh=Math.max(1,w[i]*(WH-8));tg.strokeStyle=i/w.length*song.duration<t?'#8fcdbf':'#5a6b85a0';tg.lineWidth=1;tg.beginPath();tg.moveTo(xx,(WH-5-hh)/2);tg.lineTo(xx,(WH-5+hh)/2);tg.stroke();}
 tg.fillStyle='#d2f4f0';tg.fillRect(x(t)-.8,0,1.6,WH);tg.beginPath();tg.roundRect(x(t)-3,0,6,4,2);tg.fill();
 $('timelineWrap').setAttribute('aria-valuenow',t.toFixed(1));}
function lyricAt(t){const L=song.lyrics;for(let i=0;i<L.length;i++){const l=L[i];if(t>=l.a-.25&&t<=l.b+.5)return{cur:l,next:null,i};if(l.a>t)return{cur:null,next:l,i};}return{cur:null,next:null,i:L.length};}
function renderLyric(t){const el=$('lyricNow'),ahead=$('lyricNext');if(!prefs.lyrics||!song.lyrics.length){if(s.lyricKey!==''){s.lyricKey='';el.replaceChildren();ahead.textContent='';}return;}
 const {cur,next,i}=lyricAt(t);let key='',line=cur;if(cur){let on=-1;for(let i=0;i<cur.words.length;i++){const w=cur.words[i];if(t>=w.a&&t<w.b+.08)on=i;}key='c'+cur.a+':'+on+':'+cur.words.filter(w=>t>=w.b).length;}
 else if(next&&next.a-t<4){line=next;key='n'+next.a;}
 // the line after the one on screen: the singer sees where the phrase goes next
 const after=line?song.lyrics[i+1]:null;key+='|'+(after?after.a:'');
 if(key===s.lyricKey)return;s.lyricKey=key;el.replaceChildren();ahead.textContent=after?after.words.map(w=>w.w).join(' '):'';if(!line)return;
 for(const w of line.words){const sp=document.createElement('span');sp.textContent=w.w+' ';sp.className=line===next?'soon':t>=w.a&&t<w.b+.08?'on':t>=w.b?'past':'';el.append(sp);}
}
function updateReadout(t){
 let p=s.current;const review=traceShown();if(review)p=pointNear(s.trace.points,t,.12);
 const live=p&&p.m!==null&&p.m!==undefined&&(review||s.ctx&&s.ctx.currentTime-(p.t||0)<.23);
 $('liveNote').innerHTML=noteHTML(live?p.m:null);$('liveNote').classList.toggle('empty',!live);$('liveDesc').textContent=live?words[(Math.round(p.m)%12+12)%12]+(review?' · запис':''):review?'У цю мить у записі тиша':s.stream?'Заспівай зручну ноту':'Час заспівати';$('liveFreq').textContent=live?(p.f.toFixed(1)+' Гц'):review?'Спроба '+String(s.trace.take.id).padStart(2,'0'):s.stream?'Слухаю мікрофон':'Мікрофон вимкнено';
 const opt=effective(),target=targetAt(t,opt),ref=p?.songT!==undefined?targetAt(p.songT,opt):target;$('targetNote').textContent=target?name(target.m):'—';let text='Тут ціль не визначена',delta=null;if(target)text=target.ok?'Слухай. Потім повтори.':'Невпевнена ціль';if(live&&ref){delta=centsOff(p.raw??p.m,ref.m,opt);text=(ref.ok?'':'≈ ')+(delta>0?'+':'')+Math.round(delta)+' ¢'+(opt.octaveFree&&Math.abs((p.raw??p.m)-ref.m)>=6?' · інша октава':'')+(!ref.verified?' · чернетка':'');}
 const inTol=delta!==null&&Math.abs(delta)<=opt.tolerance;$('deviation').textContent=text;$('deviation').style.color=delta===null?'#94a0b3':inTol?'#a1eed8':'#d99aa2';$('needle').style.opacity=delta===null?0:1;$('needle').style.setProperty('--n',clamp(.5+(delta||0)/200,0,1));$('needle').style.background=delta!==null&&!inTol?'#d47f88':'#a1eed8';$('liveNote').classList.toggle('miss',delta!==null&&!inTol&&!!ref);
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
async function importFile(file){if(!file)return;if(file.size>100*1024*1024){error('Пакет завеликий: максимум 100 МіБ.');return;}try{const d=JSON.parse(await file.text());const packed=d.schema==='luma.pack.v1',newSong=packed?d.song:d;if(!validateSong(newSong))throw Error('Непідтримуваний формат цілі. Потрібен target.json або готовий .luma.json, не сире аудіо.');if(s.unsaved&&!confirm('Сховище браузера не прийняло частину спроб, і їхні лінії є лише в цій вкладці. Відкрити іншу пісню й прибрати їх?'))return;
 if(!packed){if(Math.abs(newSong.duration-song.duration)>.1||newSong.title!==song.title||(newSong.sourceId&&song.sourceId&&newSong.sourceId!==song.sourceId))throw Error('Ціль належить іншому аудіо. Імпортуй повний підготовлений пакет.');if(!validLyrics(newSong.lyrics))newSong.lyrics=song.lyrics;}
 else{if(!d.assets?.['1']?.backing||!d.assets?.['1']?.foreground)throw Error('У пакеті відсутні аудіодоріжки.');assets=d.assets;s.bufs.clear();}
 stopTransport('import');await releaseMic();s.takes.forEach(t=>{if(t.url)URL.revokeObjectURL(t.url);});clearUndoPunch();s.takes=[];s.unsaved=false;s.trace=null;s.history=[];song=newSong;song.notes.sort((a,b)=>a.a-b.a);song.points.sort((a,b)=>a[0]-b[0]);resetHistory();populateSong();if(Array.isArray(newSong.verified)){s.verified=newSong.verified.filter(r=>Number.isFinite(r.a)&&Number.isFinite(r.b)&&r.a>=0&&r.b<=song.duration);saveEdits();}renderTakes();sync();await loadHistory();toast('Ціль імпортовано. Перевір мелодію перед тренуванням.');
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
$('repeatMissBtn').onclick=()=>{if(!traceShown()||s.mode!=='idle'||s.busy||s.awaitFinish)return;const runs=missRuns(s.trace.score),r=runs.find(r=>r.b>s.pos)||runs[0];if(!r)return;const a=Math.max(0,r.a-.6),b=Math.min(song.duration,r.b+.8);closeTrace();setRange(a,b);prefs.loop=true;s.pos=a;setRangeScale();sync();startTransport(false);};
function markRange(which){if(s.busy||s.awaitFinish)return;const t=now();const ok=which==='a'?setRange(t,Math.max(s.range.b,t+.5)):setRange(Math.min(s.range.a,t-.5),t);if(ok)toast((which==='a'?'Фрагмент від':'Фрагмент до')+' '+fmt(t));}
$('markA').onclick=()=>markRange('a');$('markB').onclick=()=>markRange('b');$('rangeSettings').onclick=()=>{modal('settingsDialog');$('rangeA').focus();};$('prevMiss').onclick=()=>jumpMiss(-1);$('nextMiss').onclick=()=>jumpMiss(1);$('closeReview').onclick=closeTrace;$('takesToggle').onclick=()=>{prefs.takesOpen=!prefs.takesOpen;savePrefs();sync();};
for(const [id,tab]of [['tabTakes','takes'],['tabProgress','progress']])$(id).onclick=()=>{prefs.tab=tab;savePrefs();s.progressSig='';renderProgress();};
$('shadowBtn').onclick=()=>{prefs.shadow=!prefs.shadow;savePrefs();s.shadowSig='';refreshShadow();sync();toast(prefs.shadow?'Тінь особистого рекорду увімкнена.':'Тінь особистого рекорду вимкнена.');};
$('recordAudio').onchange=()=>{prefs.audio=$('recordAudio').checked;savePrefs();sync();toast(prefs.audio?'Голос записується у WAV: спробу можна буде переслухати.':'Запис голосу вимкнено. Лінія й оцінка зберігаються як завжди.');};
$('historyFile').onchange=()=>{importHistoryFile($('historyFile').files[0]);$('historyFile').value='';};$('lyricsBtn').onclick=()=>{prefs.lyrics=!prefs.lyrics;savePrefs();s.lyricKey='~';resize();sync();};
for(const b of document.querySelectorAll('[data-close]'))b.onclick=()=>$(b.dataset.close).close();
$('loopBtn').onclick=()=>{prefs.loop=!prefs.loop;if(!prefs.loop)clearTimeout(s.nextTimer);if(prefs.loop&&!customRange())toast('Виділи фрагмент: тягни під хвилею або клавіші A / B під час прослуховування.');
 if(s.mode==='listen'&&s.transport){const t=now();seekLive(prefs.loop&&customRange()&&(t<s.range.a||t>=s.range.b-.1)?s.range.a:t);}sync();};$('speedSelect').onchange=()=>{prefs.speed=Number($('speedSelect').value);$('songMeta').textContent=fmt(song.duration)+(prefs.speed!==1?' · '+prefs.speed+'×':'');if(s.mode==='listen'){const t=now();stopTransport('speed');s.pos=t;startTransport(false);}sync();};
$('phraseSelect').onchange=()=>{if($('phraseSelect').value==='-1'){s.rangeId=-1;modal('settingsDialog');sync();}else chooseRange($('phraseSelect').value);};
function adjacent(dir){const opts=[...$('phraseSelect').options].filter(o=>+o.value>=0),idx=opts.findIndex(o=>+o.value===s.rangeId),j=clamp(idx+dir,0,opts.length-1);chooseRange(opts[j].value);}
$('prevPhrase').onclick=()=>adjacent(-1);$('nextPhrase').onclick=()=>adjacent(1);$('clearRange').onclick=()=>{clearRange();toast('Повтор знято: вся пісня.');};
$('vocalBtn').onclick=()=>{prefs.vocal=!prefs.vocal;applyMix();sync();toast(prefs.vocal?'Оригінальний вокал увімкнено.':'Тільки мінус: оригінальний вокал вимкнено.');};
for(const b of document.querySelectorAll('[data-level]'))b.onclick=()=>{prefs.level=b.dataset.level;prefs.tolerance=LEVELS[prefs.level].tolerance;savePrefs();s.progressSig='';sync();toast('Рівень: '+LEVELS[prefs.level].label+' · коридор ±'+prefs.tolerance+'¢');};
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
$('applyRange').onclick=()=>{const a=+$('rangeA').value,b=+$('rangeB').value;if(!Number.isFinite(a)||!Number.isFinite(b)||a<0||b>song.duration||b-a<.5){toast('Початок і кінець мають бути в межах пісні; довжина — від 0.5 с.');return;}setRange(a,b);s.pos=a;s.history=[];setRangeScale();sync();toast('Фрагмент встановлено.');};
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
addEventListener('resize',fitStage);
new ResizeObserver(resize).observe($('chartWrap'));new ResizeObserver(resize).observe($('timelineWrap'));
function silentWav(seconds,rate=48000){const n=Math.round(seconds*rate),b=new ArrayBuffer(44+n*2),v=new DataView(b);const text=(o,t)=>{for(let i=0;i<t.length;i++)v.setUint8(o+i,t.charCodeAt(i));};text(0,'RIFF');v.setUint32(4,36+n*2,true);text(8,'WAVE');text(12,'fmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,1,true);v.setUint32(24,rate,true);v.setUint32(28,rate*2,true);v.setUint16(32,2,true);v.setUint16(34,16,true);text(36,'data');v.setUint32(40,n*2,true);return new Blob([b],{type:'audio/wav'});}
// Test hooks for the history: everything below is read-only except seedRun, which exists so a suite can build a
// week of practice without a microphone and without waiting for real time to pass.
const historyHooks={
 available:historyAvailable,key:currentKey,mapVersion,songHash,note:()=>s.hist.note,persisted:()=>s.hist.persisted,
 runs:()=>s.hist.runs.map(r=>({id:r.id,cmpKey:r.cmpKey,level:r.level,view:r.view,speed:r.speed,match:r.match,target:r.target,hit:r.hit,sung:r.sung,draftFrames:r.draftFrames,
  medianCents:r.medianCents,localDay:r.localDay,startedAt:r.startedAt,hasAudio:r.hasAudio,hasTrace:r.hasTrace,a:r.a,b:r.b,songTarget:r.songTarget,
  phrases:phraseCandidates(r).map(c=>({id:c.id,target:c.target,hit:c.hit,match:c.match,median:c.medianCents}))})),
 records:()=>{const rec=records(s.hist.runs.filter(r=>r.cmpKey===currentKey()));
  return {song:rec.song?{id:rec.song.id,match:rec.song.match}:null,phrases:[...rec.phrases].map(([id,c])=>({id,match:c.match,run:c.run.id}))};},
 recordsFor:level=>{const key=cmpKeyOf({mapVersion:mapVersion(),level,tolerance:(LEVELS[level]||LEVELS.normal).tolerance,view:prefs.view,speed:prefs.speed});
  const rec=records(s.hist.runs.filter(r=>r.cmpKey===key));return {key,song:rec.song?{id:rec.song.id,match:rec.song.match}:null,phrases:[...rec.phrases].map(([id,c])=>({id,match:c.match}))};},
 reload:()=>loadHistory(),
 // Re-score a stored trace: proof that the packed frames rebuild the same numbers the attempt was saved with.
 rescore:async id=>{const run=s.hist.runs.find(r=>r.id===id),tr=await idbGet('traces',id);if(!run||!tr)return null;
  const meta=optOfRun(run),pts=unpackTrace(tr).map(p=>{const songT=run.a+p.t*run.speed,ref=targetAt(songT,meta);
   return {...p,songT,m:p.f?69+12*Math.log2(p.f/440):null,ref:ref?ref.m:null};});
  const sc=newScore(meta);scoreAdvance(sc,pts,run.b);
  return {points:pts.length,target:sc.target,hit:sc.hit,stored:{target:run.target,hit:run.hit}};},
 exportPayload:all=>exportPayload(all),importPayload:d=>importHistory(d),clearSong:()=>clearSongHistory(),draft:()=>scopeDraft(prefs.view),
 takeJSON:id=>{const t=s.takes.find(x=>x.id===id);return t?takePayload(t):null;},
 shadow:()=>s.shadow?{id:s.shadow.id,match:s.shadow.match,points:s.shadow.points.length}:null,
 streak:streakDays,trend:()=>trendRuns(s.hist.runs.filter(r=>r.cmpKey===currentKey())).map(r=>r.match),
 totals:()=>({song:targetTotals(prefs.view).song,draft:targetTotals(prefs.view).draft}),
 weak:()=>weakRows(s.hist.runs.filter(r=>r.cmpKey===currentKey())),exercises:exerciseRows,
 // Write attempts straight into the store, dated freely: the seed a progress test needs.
 seedRun:async spec=>{const ids=await historyHooks.seedMany([spec]);return ids[0];},
 seedMany:async list=>{
  const make=({match=8000,target=600,startedAt,level=prefs.level,view=prefs.view,speed=prefs.speed,a=0,b=song.duration,phrases=[],songTarget,medianCents=20,id})=>{
   const started=startedAt||new Date().toISOString(),hit=Math.round(target*match/10000),L=LEVELS[level]||LEVELS.normal;
   const stat=[];for(const p of phrases)stat.push(p.target,p.hit,p.sung??p.hit,p.median??-1);
   return {id:id||newRunId(),songHash:songHash(),mapVersion:mapVersion(),cmpKey:cmpKeyOf({mapVersion:mapVersion(),level,tolerance:level==='custom'?prefs.tolerance:L.tolerance,view,speed}),
    startedAt:started,endedAt:started,localDay:localDay(Date.parse(started)),a,b,speed,level,tolerance:L.tolerance,view,octave:0,latency:0,
    hasAudio:false,clipped:false,punches:0,target,hit,sung:hit,draftFrames:0,medianCents,match:Math.round(10000*hit/target),
    songTarget:songTarget??targetTotals(view).song,strict:{targetTime:0,compared:0,inside:0,median:-1},
    phraseIds:Int32Array.from(phrases.map(p=>p.id)),phraseStats:Int32Array.from(stat),hasTrace:false};};
  const runs=list.map(make),ops=runs.map(r=>['runs','put',r]);
  ops.push(['songs','put',songEntry([...s.hist.runs,...runs].sort(byNewest))]);
  await idbWrite(ops);await loadHistory();return runs.map(r=>r.id);},
 reloadMs:async()=>{const t0=performance.now();await loadHistory();return +(performance.now()-t0).toFixed(1);}
};
window.Luma={diagnostics:()=>({mode:s.mode,busy:s.busy,pending:s.awaitFinish,time:now(),range:{...s.range},takeCount:s.takes.length,takes:s.takes.map(t=>({id:t.id,duration:t.duration,samples:t.duration*t.sampleRate,sampleRate:t.sampleRate,points:t.points.length,stats:t.stats,match:scorePct(t.score),frames:t.score.frames.length})),mic:!!s.stream,frequency:s.current?.f??null,computeMs:s.computeMs,windowMs:s.windowMs,contextState:s.ctx?.state,bufferDurations:[...s.bufs].map(([k,b])=>({speed:k,back:b.back.duration,fore:b.fore.duration}))}),targetAt:t=>targetAt(t),song:()=>({title:song.title,duration:song.duration,metrics:song.metrics,notes:song.notes.length,phrases:song.phrases.length,lyrics:song.lyrics.length}),
 // Test hooks: pure scoring and synthetic takes (silent WAV) so the review path can be exercised without a microphone.
 test:{GRID,score:(points,meta,upTo)=>{const sc=newScore(meta);scoreAdvance(sc,points,upTo??Infinity);return {target:sc.target,hit:sc.hit,sung:sc.sung,pct:scorePct(sc),frames:sc.frames,notes:[...sc.notes]};},
  injectTake:({a,b,speed=1,points,tolerance,octave=prefs.octave,view=prefs.view,audio=prefs.audio,startedAt})=>{const duration=(b-a)/speed,meta={...takeMeta(a,b,speed),octave,view,hasAudio:!!audio};if(tolerance!==undefined){meta.tolerance=tolerance;meta.level='custom';}if(startedAt)meta.startedAt=startedAt;const id=meta.id;const m={id,blob:audio?silentWav(duration):null,hasAudio:!!audio,clipped:false,sampleRate:48000,duration,start:0,end:duration,reason:'end',points:points.filter(p=>p.t>=0&&p.t<duration),gap:0};const t=storeTake(meta,m);s.pos=a;sync();return {id:t.id,runId:t.runId,pct:scorePct(t.score),frames:t.score.frames.length,points:t.points.length,hasAudio:!!t.hasAudio};},
  livePush:(p)=>{handleWorker({type:'pitch',computeMs:0,windowMs:64,...p});},
  seek:t=>seekTo(t,true),applySeek,selectTake:id=>{const t=s.takes.find(t=>t.id===id);if(t)selectTrace(t);},closeTrace,jumpMiss,draw:()=>{draw(now());updateReadout(now());},
  setLevel:l=>{document.querySelector('[data-level="'+l+'"]').click();return levelOpt();},viewWindow:t=>view(t),plot:()=>({...bounds()}),dpr:()=>DPR,// one frame drawn with the label rectangles recorded, so a test can read the real canvas pixels behind the type
  noteBoxes:()=>{probe=[];draw(now());const r=probe;probe=null;return r;},scale:()=>({...SCALE,goalLo:sc.goalLo,goalHi:sc.goalHi}),setRange,clearRange,levelOpt,centsOff,now,punchTarget:()=>punchTarget()?.id??null,gains:()=>s.gains?{back:s.gains.back.gain.value,fore:s.gains.fore.gain.value,vocal:prefs.vocal}:null,takes:()=>s.takes.map(t=>({id:t.id,runId:t.runId,a:t.a,endSong:t.endSong,duration:t.duration,bytes:t.blob?.size||0,hasAudio:!!t.hasAudio,clipped:!!t.clipped,points:t.points.length,punches:t.punches||0,pct:scorePct(t.score),record:t.record?.text||null,historyError:!!t.historyError,restored:!!t.restored})),
  state:()=>({mode:s.mode,pos:s.pos,time:now(),trace:s.trace?{id:s.trace.take.id,points:s.trace.points.length,frames:s.trace.score.frames.length,pct:scorePct(s.trace.score),missRuns:missRuns(s.trace.score)}:null,liveScore:s.live?{target:s.live.target,hit:s.live.hit,sung:s.live.sung,pct:scorePct(s.live)}:null,history:s.history.length,matchText:$('matchPct').textContent,matchDetail:$('matchDetail').textContent,reviewHidden:$('reviewBar').hidden,missCount:$('missCount').textContent,lyric:$('lyricNow').textContent,liveNote:$('liveNote').textContent,deviation:$('deviation').textContent,range:{...s.range},rangeId:s.rangeId,rangeText:$('rangeText').textContent,loop:prefs.loop,transportLoop:s.transport?.loop??null,level:prefs.level,tolerance:prefs.tolerance,rangeLo:s.rangeLo,rangeHi:s.rangeHi}),
  fakeSing:({a,b,speed=1})=>{// enter singing mode without audio: transport clock driven by a fake context
   if(s.mode!=='idle')return false;const meta=takeMeta(a,b,speed),id=meta.id;if(!s.ctx)s.ctx={currentTime:0,state:'running',sampleRate:48000,resume(){},get _fake(){return true;}};const when=s.ctx.currentTime;s.transport={token:++s.cancel,when,offset:a,end:b,speed,loop:null};s.mode='singing';s.history=[];s.live=newScore(meta);s.pending.set(id,meta);sync();return {id,when};},
  fakeTick:(ctxTime)=>{if(s.ctx&&'_fake' in s.ctx)s.ctx.currentTime=ctxTime;const t=now();if(s.mode==='singing'&&s.live&&s.transport)scoreAdvance(s.live,s.history,Math.min(t-.18*s.transport.speed,s.transport.end));draw(t);updateReadout(t);return t;},
  fakeFinish:()=>{const id=s.takeCounter,meta=s.pending.get(id);if(!meta)return null;const pts=s.history.map(p=>({t:(p.songT-meta.a)/meta.speed,f:p.f,confidence:p.confidence,db:p.db}));s.pending.delete(id);const duration=(s.pos=now())-meta.a;s.transport=null;s.mode='idle';s.live=null;const m={id,blob:meta.hasAudio?silentWav(duration/meta.speed):null,hasAudio:!!meta.hasAudio,clipped:false,sampleRate:48000,duration:duration/meta.speed,start:0,end:duration/meta.speed,reason:'end',points:pts,gap:0};const t=storeTake(meta,m);sync();return {id:t.id,pct:scorePct(t.score)};},
  history:historyHooks}};
populateSong();fitStage();resize();setRangeScale();updateReadout(s.pos);loadHistory();
// A profile that has never opened Luma before did not live through the change, so it is told nothing; the flag is set
// either way, so the notice can never surface later.
if(!prefs.audioNotice){const upgrade=hadSettings;prefs.audioNotice=true;savePrefs();
 if(upgrade)setTimeout(()=>toast('Запис голосу у WAV тепер вимикається і типово вимкнений. Слід і оцінка кожної спроби зберігаються завжди — вкладка «Прогрес». WAV вмикається в налаштуваннях.'),900);}
})();
