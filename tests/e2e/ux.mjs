// Regression coverage for the audited user flows. Uses the demo, never the preparation pipeline.
import {launch, open, assert, window_, url} from './lib.mjs';
const b = await launch(['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream']);
const {page: p, logs} = await open(b);
const win = await p.evaluate(src => eval(src), window_());
const live=await b.newPage();await live.goto(url);
const jump=await live.evaluate(a=>{
  const t=window.Luma.test;t.seek(a);t.fakeSing({a,b:a+3});
  const before=t.state();t.livePush({t:.5,f:82.4069,confidence:.99,db:-20,rms:.1,peak:.2});
  const after=t.state();return{before:before.rangeHi-before.rangeLo,after:after.rangeHi-after.rangeLo};
},win.a);
assert(jump.after-jump.before<4,'a single octave jump from the microphone cannot instantly flatten the scale '+JSON.stringify(jump));
await live.close();
await p.evaluate(a => window.Luma.test.seek(a), win.a);
let state = await p.evaluate(() => window.Luma.test.state());
assert(state.rangeHi - state.rangeLo < 22, 'fragment scale is tighter than the old two-octave floor');
// No reference at the end of the demo: the scale must follow the recorded low voice there.
await p.setViewportSize({width:390,height:844});
await p.waitForTimeout(100);
const gap = await p.evaluate(() => {
  const end = window.LUMA_SONG.duration, last = window.LUMA_SONG.notes.at(-1).b;
  const a = last + .1, b = end - .05, points = [];
  for (let t = 0; t < b-a; t += .02) points.push({t, f:82.4069, confidence:.99, db:-20, rms:.1, peak:.2});
  window.Luma.test.injectTake({a,b,points});window.Luma.test.seek(end);window.Luma.test.draw();
  return window.Luma.test.state();
});
assert(gap.rangeLo < 40 && gap.rangeHi > 40 && gap.rangeHi-gap.rangeLo <= 14, 'target-free fragment frames the recorded E2 closely '+JSON.stringify({lo:gap.rangeLo,hi:gap.rangeHi,pos:gap.pos}));
await p.locator('[data-view="notes"]').click();state=await p.evaluate(()=>window.Luma.test.state());
assert(state.trace&&!state.reviewHidden,'switching the view keeps the shown attempt on screen');
await p.locator('[data-view="contour"]').click();
await p.setViewportSize({width:1440,height:900});
await p.evaluate(a => {window.Luma.test.closeTrace();window.Luma.test.setRange(a,a+2);window.Luma.test.seek(a+2);}, win.a);
await p.locator('#loopBtn').click();await p.locator('#listenBtn').click();
await p.waitForFunction(() => window.Luma.test.state().mode === 'listen');await p.waitForTimeout(700);
state = await p.evaluate(() => window.Luma.test.state());
assert(state.transportLoop && state.time >= win.a && state.time < win.a+2, 'starting at B honors the enabled A-B repeat');
await p.evaluate(a=>window.Luma.test.applySeek(a+3),win.a);
state=await p.evaluate(()=>window.Luma.test.state());
assert(!state.loop&&!state.transportLoop,'seeking beyond the loop also clears its visible active state');
await p.locator('#loopBtn').click();
state=await p.evaluate(()=>window.Luma.test.state());
assert(state.loop&&state.transportLoop&&state.time<win.a+2,'enabling repeat outside its region returns to A during playback');
await p.locator('#stopBtn').click();
// A fragment that ended by itself starts again from A, for Listen and for Sing, even with the loop off.
await p.evaluate(a=>{const t=window.Luma.test;if(t.state().loop)document.getElementById('loopBtn').click();t.setRange(a,a+1.5);t.seek(a);},win.a);
await p.locator('#listenBtn').click();await p.waitForFunction(()=>window.Luma.test.state().mode==='listen');await p.waitForFunction(()=>window.Luma.test.state().mode==='idle',null,{timeout:8000});
state=await p.evaluate(()=>window.Luma.test.state());assert(!state.loop&&Math.abs(state.pos-(win.a+1.5))<.15,'fragment ended by itself at B '+JSON.stringify({pos:state.pos,loop:state.loop}));
await p.locator('#listenBtn').click();await p.waitForFunction(()=>window.Luma.test.state().mode==='listen');await p.waitForTimeout(300);
state=await p.evaluate(()=>window.Luma.test.state());assert(state.time>=win.a-.05&&state.time<win.a+1.5,'Listen after a natural end restarts the fragment from A '+state.time);
await p.locator('#stopBtn').click();await p.waitForFunction(()=>window.Luma.test.state().mode==='idle');
await p.evaluate(a=>window.Luma.test.seek(a+1.5),win.a);
await p.locator('#singBtn').click();await p.waitForFunction(()=>window.Luma.test.state().mode==='singing',null,{timeout:8000});
assert(await p.locator('#listenLabel').textContent()==='Стоп','the second button says Стоп while recording');
state=await p.evaluate(()=>window.Luma.test.state());assert(state.time>=win.a-.05&&state.time<win.a+1.5,'Sing from the fragment end records the fragment again from A '+state.time);
await p.locator('#stopBtn').click();await p.waitForTimeout(1500);
// the same parked at B with the loop on: Sing records the fragment from A
await p.evaluate(a=>{const t=window.Luma.test;if(!t.state().loop)document.getElementById('loopBtn').click();t.seek(a+1.5);},win.a);
await p.locator('#singBtn').click();await p.waitForFunction(()=>window.Luma.test.state().mode==='singing',null,{timeout:8000});
state=await p.evaluate(()=>window.Luma.test.state());assert(state.loop&&state.time>=win.a-.05&&state.time<win.a+1.5,'Sing from the fragment end with the loop on records from A '+state.time);
await p.locator('#stopBtn').click();await p.waitForTimeout(1500);await p.evaluate(()=>{if(window.Luma.test.state().loop)document.getElementById('loopBtn').click();});
// Moving the playhead by hand must frame the new place before it is played: the review measured 44 frames (0.72 s)
// with a note drawn outside the pitch range after a far A-B region was applied from the number fields.
// Count every animation frame from just before the control is used until a second later.
const watch=async(act,ms=1000)=>{
  await p.evaluate(()=>{const w=window.__watch={bad:0,frames:0,glide:0};
    const step=()=>{const st=window.Luma.test.state(),v=window.Luma.test.viewWindow(st.time),g=window.Luma.test.scale();w.frames++;
      const oct=Number(document.getElementById('octave').value)||0;// the roll draws n.m + the vocal octave, so the range is judged on that
      if(window.LUMA_SONG.notes.some(n=>!n.ignored&&n.b>=v.a&&n.a<=v.b&&(n.m+oct<st.rangeLo||n.m+oct>st.rangeHi)))w.bad++;
      w.glide=Math.max(w.glide,Math.abs(st.rangeLo-g.goalLo),Math.abs(st.rangeHi-g.goalHi));
      w.raf=requestAnimationFrame(step);};w.raf=requestAnimationFrame(step);});
  await act();await p.waitForTimeout(ms);
  return p.evaluate(()=>{const w=window.__watch;cancelAnimationFrame(w.raf);return{bad:w.bad,frames:w.frames,glide:+w.glide.toFixed(2)};});};
const far=await p.evaluate(()=>{const ns=window.LUMA_SONG.notes.filter(n=>!n.ignored),lo=ns.reduce((a,b)=>a.m<b.m?a:b);
  return{a:+Math.max(0,lo.a-.3).toFixed(2),b:+Math.min(window.LUMA_SONG.duration,lo.b+2).toFixed(2)};});
// Park the plot on a recorded E2 at the target-free end of the song, two octaves under the melody, then type an A-B
// region back up in the melody: the new region has to be framed before its first frame, not glided into.
await p.evaluate(()=>{const T=window.Luma.test,S=window.LUMA_SONG,end=S.duration,last=S.notes.at(-1).b;
  const a=last+.1,b=end-.05,points=[];for(let t=0;t<b-a;t+=.02)points.push({t,f:82.4069,confidence:.99,db:-20,rms:.1,peak:.2});
  T.closeTrace();T.clearRange();T.injectTake({a,b,points});T.seek(end);});
await p.locator('#settingsBtn').click();
await p.evaluate(a=>{document.getElementById('rangeA').value=a;document.getElementById('rangeB').value=a+2;},win.a);
let framed=await watch(()=>p.locator('#applyRange').click());
assert(framed.glide===0,'the A-B number field frames its region at once instead of gliding to it '+JSON.stringify(framed));
assert(framed.bad===0,'the A-B number field frames the region it moved the playhead to '+JSON.stringify(framed));
await p.evaluate(()=>document.getElementById('settingsDialog').close());
// the same for "Повторити складну фразу", which jumps to a miss far from whatever is framed now
await p.evaluate(f=>{const T=window.Luma.test,pts=[];for(let t=0;t<f.b-f.a;t+=.02)pts.push({t,f:82.4069,confidence:.99,db:-20,rms:.1,peak:.2});
  T.clearRange();T.injectTake({a:f.a,b:f.b,points:pts});T.seek(0);},far);
framed=await watch(()=>p.locator('#repeatMissBtn').click());
assert(framed.bad===0,'repeating a hard phrase frames it before it plays '+JSON.stringify(framed));
await p.locator('#stopBtn').click();await p.waitForFunction(()=>window.Luma.test.state().mode==='idle');
for(const oct of [-12,12]){
  await p.evaluate(o=>{const sel=document.getElementById('octave');sel.value=String(o);sel.dispatchEvent(new Event('change'));},oct);
  await p.evaluate(()=>{const T=window.Luma.test;T.closeTrace();T.clearRange();T.seek(0);});
  await p.locator('#settingsBtn').click();
  await p.evaluate(a=>{document.getElementById('rangeA').value=a;document.getElementById('rangeB').value=a+2;},win.a);
  const shifted=await watch(()=>p.locator('#applyRange').click(),700);
  assert(shifted.bad===0&&shifted.glide===0,'the A-B number field frames its region with the vocal octave at '+oct+' '+JSON.stringify(shifted));
  await p.evaluate(()=>document.getElementById('settingsDialog').close());
}
await p.evaluate(()=>{const sel=document.getElementById('octave');sel.value='0';sel.dispatchEvent(new Event('change'));});
await p.evaluate(()=>{const T=window.Luma.test;if(T.state().loop)document.getElementById('loopBtn').click();T.closeTrace();T.clearRange();});
// ── item 6: the plot rectangle never reaches under the head, the lyric band or the rail ──
for(const [width,height] of [[1440,900],[1024,700],[844,390],[390,844]]){
  await p.setViewportSize({width,height});await p.waitForTimeout(220);
  const geo=await p.evaluate(()=>{const r=id=>{const e=document.getElementById(id);return e&&!e.hidden&&e.offsetParent!==null?e.getBoundingClientRect():null;};
    const box=document.getElementById('chartWrap').getBoundingClientRect(),pl=window.Luma.test.plot();
    const below=el=>el?el.bottom-box.top:0;
    return {head:Math.max(below(r('stageHead')),below(r('lyricBand'))),rail:r('stageRail')?r('stageRail').top-box.top:box.height,
      top:pl.top,bottom:pl.bottom,height:box.height};});
  assert(geo.top>=geo.head&&geo.bottom<=geo.rail&&geo.bottom>geo.top,
    'the plot keeps clear of the head and the rail at '+width+'x'+height+' '+JSON.stringify(geo));
}
// ── item 2: the glyph and the note name on a bar are read off the canvas and compared with the bar under them ──
// Sing .7 semitone sharp on a 90 cent corridor: still a hit, and the voice trace runs clear of the type it would otherwise cross.
await p.evaluate(()=>{const T=window.Luma.test,S=window.LUMA_SONG,ns=S.notes.filter(n=>!n.ignored);
  ns.at(-1).ok=false;// one drawn-but-unverified note, so the draft bar is measured too
  const scored=ns.slice(0,ns.length-3),a=Math.max(0,scored[0].a-.2),b=scored.at(-1).b+.2,points=[];
  for(let t=a;t<b;t+=.02){const i=scored.findIndex(n=>n.a<=t&&n.b>t),n=scored[i];
    const f=!n||i%3===2?null:440*Math.pow(2,(n.m+(i%3?3:.7)-69)/12);// hit · miss · silence, in turn
    points.push({t:t-a,f,confidence:f?.99:.1,db:f?-20:-70,rms:.1,peak:.2});}
  T.closeTrace();T.clearRange();T.setLevel('strict');T.injectTake({a,b,points,tolerance:90});
  window.__stops=[a+.4,b+.6,...scored.slice(0,9).map(n=>(n.a+n.b)/2)];});
await p.locator('[data-view="notes"]').click();
for(const [width,height] of [[1440,900],[390,844]]){
  await p.setViewportSize({width,height});await p.waitForTimeout(220);
  const ink=await p.evaluate(()=>{
    const T=window.Luma.test,DPR=T.dpr(),chart=document.getElementById('chart');
    // read back from a copy, not from the live canvas: repeated getImageData on the GPU-backed one warns in the console
    const copy=document.createElement('canvas');copy.width=chart.width;copy.height=chart.height;
    const g=copy.getContext('2d',{willReadFrequently:true});
    const lin=v=>{v/=255;return v<=.04045?v/12.92:Math.pow((v+.055)/1.055,2.4);};
    const L=(r,b,l)=>.2126*lin(r)+.7152*lin(b)+.0722*lin(l);
    const worst={},kinds={};
    for(const stop of window.__stops){T.seek(stop);const pl=T.plot(),boxes=T.noteBoxes();g.drawImage(chart,0,0);
      for(const bx of boxes){
        kinds[bx.kind]=(kinds[bx.kind]||0)+1;
        if(bx.x<pl.left+1||bx.tx+bx.tw>pl.right-1)continue;
        const hh=Math.min(6,bx.h/2-1.2);if(hh<3)continue;// the strip the type sits in, clear of the bar outline
        const dw=Math.round((bx.tw+2)*DPR),dh=Math.round(2*hh*DPR);if(dw<6||dh<6)continue;
        const px=g.getImageData(Math.round((bx.tx-1)*DPR),Math.round((bx.y-hh)*DPR),dw,dh).data;
        const hist=new Map();let body=null,best=0;
        for(let i=0;i<px.length;i+=4){const k=px[i]+','+px[i+1]+','+px[i+2];const n=(hist.get(k)||0)+1;hist.set(k,n);if(n>best){best=n;body=k;}}
        if(best<dw*dh*.12)continue;// no flat ground behind the type here: nothing to compare against
        const Lb=L(...body.split(',').map(Number));
        const c=bx.ink.slice(1),up=L(...[0,2,4].map(i=>parseInt(c.slice(i,i+2),16)))>Lb;// look for the glyph the way the app inked it
        let Li=Lb;for(let i=0;i<px.length;i+=4){const l=L(px[i],px[i+1],px[i+2]);if(up?l>Li:l<Li)Li=l;}
        const key=bx.kind+(bx.cur?' (current)':'');const ratio=(Math.max(Lb,Li)+.05)/(Math.min(Lb,Li)+.05);
        if(!(key in worst)||ratio<worst[key])worst[key]=+ratio.toFixed(2);}}
    return {worst,kinds};});
  for(const k of ['hit','miss','silent','draft'])
    assert(ink.kinds[k]>0,'the '+k+' bar is on screen to be measured at '+width+'x'+height+' '+JSON.stringify(ink.kinds));
  const bad=Object.entries(ink.worst).filter(([,c])=>c<4.5);
  assert(bad.length===0,'every label on a bar clears 4.5:1 against its own bar at '+width+'x'+height+' '+JSON.stringify(ink.worst));
}
// ── item 4: with an attempt on screen no line of the interface is cut off on a desktop ──
for(const [width,height] of [[1024,700],[1440,900],[1920,1080]]){
  await p.setViewportSize({width,height});await p.waitForTimeout(220);
  const cut=await p.evaluate(()=>[...document.querySelectorAll('body *')]
    .filter(e=>!e.closest('dialog')&&!e.classList.contains('sr-only')&&!e.hidden&&e.offsetParent!==null&&e.scrollWidth-e.clientWidth>1)
    .map(e=>(e.id||e.className.toString()).slice(0,24)+' +'+(e.scrollWidth-e.clientWidth)));
  assert(cut.length===0,'nothing outside the dialogs is ellipsised at '+width+'x'+height+' '+JSON.stringify(cut));
}
await p.evaluate(()=>{window.LUMA_SONG.notes.filter(n=>!n.ignored).at(-1).ok=true;window.Luma.test.setLevel('normal');window.Luma.test.closeTrace();});
await p.setViewportSize({width:390,height:844});
assert(await p.locator('#listenBtn').getAttribute('aria-label') === 'Слухати пісню', 'mobile listen has an accessible name');
const dimensions = await p.evaluate(() => ({page:document.documentElement.scrollWidth,view:innerWidth}));
assert(dimensions.page === dimensions.view, 'trainer fits the narrow viewport');
// ── two budgets: the WAV limit only when the voice is being recorded, the trace limit always ──
const setAudio=on=>p.evaluate(v=>{const c=document.getElementById('recordAudio');c.checked=v;c.dispatchEvent(new Event('change'));},on);
await setAudio(true);
await p.evaluate(()=>{
  window.Luma.test.closeTrace();window.LUMA_SONG.duration=600;
  window.Luma.test.injectTake({a:0,b:600,points:[],audio:true});
  window.Luma.test.setRange(1,3);window.Luma.test.seek(1);
});
await p.locator('#singBtn').click();await p.waitForFunction(()=>!document.querySelector('#errorBanner').hidden);
assert((await p.locator('#errorText').textContent()).includes('Ліміт пам’яті'), 'short punch reserves its full replacement plus the undo WAV');
await p.evaluate(()=>{window.Luma.test.closeTrace();window.Luma.test.clearRange();window.Luma.test.seek(600);});
await p.locator('#singBtn').click();await p.waitForFunction(()=>!document.querySelector('#errorBanner').hidden);
assert((await p.locator('#errorText').textContent()).includes('Ліміт пам’яті'), 'starting at song end reserves the restarted full song');
// with the switch off there is no WAV to budget, so the very same attempt is allowed
await setAudio(false);
await p.evaluate(()=>{window.Luma.test.closeTrace();window.Luma.test.seek(600);document.getElementById('errorBanner').hidden=true;});
await p.locator('#singBtn').click();await p.waitForFunction(()=>window.Luma.test.state().mode==='singing',null,{timeout:9000});
assert(await p.locator('#errorBanner').isHidden(),'with the recording switch off the WAV budget no longer stops a new attempt');
await p.locator('#stopBtn').click();await p.waitForFunction(()=>window.Luma.test.state().mode==='idle',null,{timeout:9000});await p.waitForTimeout(600);
// the trace budget is what stops singing now, and it says the history keeps what the tab drops
const filled=await p.evaluate(()=>{const T=window.Luma.test;T.clearRange();
  while(T.takes().length<20)T.injectTake({a:0,b:1,points:[],audio:false});
  T.closeTrace();T.seek(0);return T.takes().length;});// no attempt on screen, so this is a new one and not a punch-in
assert(filled===20,'twenty traces fit in the tab '+filled);
await p.locator('#singBtn').click();await p.waitForFunction(()=>!document.querySelector('#errorBanner').hidden,null,{timeout:9000});
const limit=await p.locator('#errorText').textContent();
assert(limit.includes('Ліміт слідів')&&limit.includes('історія її не втратить'),'the 21st attempt reports the trace limit and says the history keeps the deleted one: '+limit);
assert(logs.length === 0, 'trainer console clean: '+JSON.stringify(logs));
await b.close();
