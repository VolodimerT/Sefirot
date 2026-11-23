/* V5: scouting screens, no automated betting */
(function(){
'use strict';
const B=window.questBridge,E=window.SEQ,C=window.QuestV5Core;
if(!B||!E||!C)return;
const esc=B.escape,fmt=n=>Number.isFinite(n)?n.toFixed(2):'Н/Д';
const df=new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Kyiv',year:'numeric',month:'2-digit',day:'2-digit'});
const tf=new Intl.DateTimeFormat('ru-RU',{timeZone:'Europe/Kyiv',hour:'2-digit',minute:'2-digit',hour12:false});
let day='2026-12-01',selected='';
const gdate=g=>df.format(new Date(g.kickoff)),gtime=g=>tf.format(new Date(g.kickoff));
const all=()=>window.QuestSchedule?.get()||[];
function context(){const matches=all().filter(g=>gdate(g)===day);const match=matches.find(g=>g.fixture_key===selected)||matches[0]||null;if(match)selected=match.fixture_key;return {matches,match};}
function store(){const d=B.data();if(!d.intel)d.intel={version:1,cards:{}};if(!d.intel.cards)d.intel.cards={};return d.intel.cards;}
function seed(g){return {fixtureKey:g.fixture_key,home:g.home_team,away:g.away_team,competition:g.competition,kickoff:g.kickoff,sourceUrl:g.source_url,sourceCheckedAt:g.checked_at||'',ownSource:'',updatedAt:'',homeXgf:null,homeXga:null,awayXgf:null,awayXga:null,lineupStatus:'unknown',injuriesChecked:false,tactical:'',publicTrap:'',deathTest:'',notes:'',state:'draft',sealedAt:'',snapshot:''};}
function card(g,create=false){if(!g)return null;const db=store();if(create&&!db[g.fixture_key])db[g.fixture_key]=seed(g);return db[g.fixture_key]||seed(g);}
function title(n,sub){return '<div class="eyebrow">V5 / FOOTBALL INTELLIGENCE</div><h1 class="page-title">'+n+'</h1><p class="page-intro">'+sub+'</p>';}
function options(){
 const ctx=context();let s='<div class="panel v5-select"><label>Дата<select id="v5-day">';
 for(const d of E.days)s+='<option value="'+d+'"'+(d===day?' selected':'')+'>'+Number(d.slice(-2))+' декабря</option>';
 s+='</select></label><label>Матч<select id="v5-match">';
 if(!ctx.matches.length)s+='<option value="">Нет матчей</option>';
 for(const g of ctx.matches)s+='<option value="'+esc(g.fixture_key)+'"'+(ctx.match?.fixture_key===g.fixture_key?' selected':'')+'>'+esc(gtime(g)+' '+g.home_team+' — '+g.away_team)+'</option>';
 return s+'</select></label><button class="button secondary" data-v5-act="refresh">Перезагрузить каталог</button></div>';
}
function textField(k,label,v,type='text'){
 return '<label class="v5-field"><span>'+esc(label)+'</span><input data-v5-field="'+k+'" type="'+type+'" value="'+esc(v??'')+'" '+(type==='number'?'min="0" max="10" step="0.01"':'')+'></label>';
}
function noteField(k,label,v){return '<label class="v5-field"><span>'+esc(label)+'</span><textarea data-v5-field="'+k+'" rows="3">'+esc(v||'')+'</textarea></label>';}
function scoutView(){
 const ctx=context(),g=ctx.match;
 let out=title('AI Scout','Автоматически подгружаются матч и источник календаря. xG, травмы и составы вводим только по проверенным данным.')+options();
 if(!g)return out+'<div class="panel">В этот день подходящих матчей пока нет.</div>';
 const x=card(g),r=C.cardReadiness(x,g);
 out+='<div class="panel"><h2>'+esc(g.home_team)+' — '+esc(g.away_team)+'</h2><p>'+esc(gdate(g))+' '+esc(gtime(g))+' (Киев) · '+esc(g.competition)+'</p>';
 if(C.checkedUrl(g.source_url))out+='<a target="_blank" rel="noopener noreferrer" href="'+esc(g.source_url)+'">Расписание / источник</a>';
 out+='<p>Полнота информации: '+r.complete+' / '+r.total+' (не вероятность)</p>';
 for(const sig of r.signals)out+='<div class="v5-check">'+(sig[1]?'✓':'○')+' '+esc(sig[0])+'</div>';
 out+='</div><div class="panel"><h3>Доказательная карточка · '+(x.state==='sealed'?'SEALED':'DRAFT')+'</h3><fieldset'+(x.state==='sealed'?' disabled':'')+'><div class="v5-pair">';
 out+=textField('homeXgf','xG хозяев',x.homeXgf,'number')+textField('homeXga','xGA хозяев',x.homeXga,'number');
 out+=textField('awayXgf','xG гостей',x.awayXgf,'number')+textField('awayXga','xGA гостей',x.awayXga,'number');
 out+=textField('ownSource','Источник статистики (HTTPS)',x.ownSource,'url');
 out+='<label>Составы<select data-v5-field="lineupStatus">';
 for(const [v,l] of [['unknown','Неизвестны'],['expected','Предварительные'],['confirmed','Подтверждены']])out+='<option value="'+v+'"'+(v===x.lineupStatus?' selected':'')+'>'+l+'</option>';
 out+='</select></label></div><label class="v5-check"><input type="checkbox" data-v5-field="injuriesChecked"'+(x.injuriesChecked?' checked':'')+'> Проверены травмы и дисквалификации</label>';
 out+=noteField('tactical','Tactical fit',x.tactical)+noteField('publicTrap','Public trap',x.publicTrap)+noteField('deathTest','Death-test',x.deathTest)+noteField('notes','Примечания, выборка и качество источников',x.notes);
 out+='</fieldset><div class="v5-buttons">';
 if(x.state==='draft')out+='<button class="button" data-v5-act="server-seal">Серверный PREMATCH SEAL</button><button class="button secondary" data-v5-act="seal">Локальная фиксация</button>';
 else out+='<span>'+(x.serverSealId?'SERVER VERIFIED':'ТОЛЬКО ЛОКАЛЬНО')+': '+esc(x.sealedAt||'')+'</span>'+(x.serverSealId?'':' <button class="button secondary" data-v5-act="server-seal">Зафиксировать на сервере сейчас</button>');
 out+='<button class="button secondary" data-v5-act="copy">Добавить в черновик</button><button class="button secondary" data-route="arena">Арена</button></div></div>';
 out+='<div class="notice warn">Рейтинги и статистика не превращаются в модельную вероятность. После начала матча прематч-функции заблокированы.</div>';
 return out;
}
function arenaView(){
 const g=context().match;let out=title('Match Arena 2.0','Сравнение по подтверждённым данным — игровая оценка OVR не равна вероятности победы.')+options();
 if(!g)return out+'<div class="panel">Нет матча на дату.</div>';
 const x=card(g);
 function side(n,forX,againstX){
 const t=B.data().teams.find(a=>a.name.toLowerCase()===n.toLowerCase());
 return '<article class="panel"><h2>'+esc(n)+'</h2><p>xG '+fmt(forX)+'</p><p>xGA '+fmt(againstX)+'</p><p>OVR '+(t?fmt(E.over(t)):'Н/Д')+' (игровой)</p></article>';
 }
 out+='<div class="v5-arena">'+side(g.home_team,x.homeXgf,x.homeXga)+'<div class="v5-vs">VS</div>'+side(g.away_team,x.awayXgf,x.awayXga)+'</div>';
 for(const [n,v] of [['Tactical fit',x.tactical],['Public trap',x.publicTrap],['Death-test',x.deathTest]])out+='<article class="panel"><h3>'+n+'</h3><p>'+esc(v||'Нет данных')+'</p></article>';
 out+='<details class="panel"><summary>Игровая арена V4 с радаром</summary>'+(window.QuestExtra?.arenaView()||'Нет данных')+'</details>';return out;
}
function weakView(){
 const t=B.data().tours[day]||E.emptyTour(day),a=C.legAudit(t),v=C.scenario(t,B.data().settings);
 let out=title('Weak Leg Detector','Сначала главные рынки. Проверка коэффициента, P модели, EV и рисков каждой ноги.')+options();
 out+='<div class="panel"><b>КФ</b> '+fmt(v.odds)+' · <b>Implied P</b> '+(v.implied===null?'Н/Д':fmt(v.implied*100)+'%')+' · <b>Модель P</b> '+(v.model===null?'Н/Д':fmt(v.model*100)+'%')+' · <b>EV</b> '+(v.ev===null?'Н/Д':B.money(v.ev))+'<p class="muted">'+esc(v.reason)+'</p></div>';
 if(!a.length)out+='<div class="panel">Нет ног экспресса: PASS.</div>';
 a.forEach((l,i)=>{out+='<article class="panel"><h3>Нога '+(i+1)+': '+esc(l.home)+' — '+esc(l.away)+'</h3><p>'+esc(l.market)+' · КФ '+fmt(l.odds)+' · implied '+(l.implied===null?'Н/Д':fmt(l.implied*100)+'%')+' · P '+fmt(l.prob)+'%</p>';
 if(l.delta!==null)out+='<p>Разница P − implied: '+fmt(l.delta*100)+' п.п.</p>';
 for(const issue of l.issues)out+='<p class="v5-warning">• '+esc(issue)+'</p>';
 if(!l.issues.length)out+='<p>Численно value возможно, но без проверки источников вероятности класс D / PASS.</p>';
 out+='</article>';});
 out+='<div class="notice">ЖК — только через Referee Gate. Фолы ≠ ЖК. При корреляции или отсутствии P — PASS.</div>';return out;
}
function updateField(el){
 const g=context().match;if(!g)return;
 const x=card(g,true);if(x.state==='sealed'){B.toast('Запечатанный анализ не редактируется.',true);B.refresh();return;}
 const k=el.dataset.v5Field;
 if(!['homeXgf','homeXga','awayXgf','awayXga','ownSource','lineupStatus','injuriesChecked','tactical','publicTrap','deathTest','notes'].includes(k))return;
 let v=el.type==='checkbox'?el.checked:el.value;
 if(['homeXgf','homeXga','awayXgf','awayXga'].includes(k)){if(v==='')v=null;else {v=Number(v);if(!Number.isFinite(v)||v<0||v>10){B.toast('Неверный xG',true);return;}}}
 if(k==='ownSource'&&v&&!C.checkedUrl(v)){B.toast('Требуется HTTPS',true);return;}
 if(typeof v==='string')v=v.slice(0,k==='notes'?5000:3000);
 x[k]=v;x.updatedAt=new Date().toISOString();B.save();B.refresh();
}
function seal(){
 const g=context().match;if(!g||Date.parse(g.kickoff)<=Date.now()){B.toast('Матч начался или отсутствует.',true);return;}
 const x=card(g,true);if(x.state!=='draft')return;
 if(!C.checkedUrl(x.ownSource)||x.tactical.trim().length<20||x.deathTest.trim().length<20){B.toast('Нужны HTTPS-источник, tactical fit и death-test по 20 знаков.',true);return;}
 x.state='sealed';x.sealedAt=new Date().toISOString();x.updatedAt=x.sealedAt;x.snapshot=JSON.stringify({...x,snapshot:''});B.save();B.refresh();B.toast('Разбор локально зафиксирован.');
}
let serverSealBusy=false;
async function serverSealResearch(){
 if(serverSealBusy)return;
 const g=context().match;if(!g){B.toast('Матч не выбран.',true);return;}
 const ko=Date.parse(g.kickoff);if(!Number.isFinite(ko)||ko<=Date.now()){B.toast('Нельзя фиксировать после начала.',true);return;}
 const x=card(g,true);
 if(x.serverSealId){B.toast('Уже есть неизменяемый серверный снимок.',true);return;}
 if(!C.checkedUrl(x.ownSource)||x.tactical.trim().length<20||x.deathTest.trim().length<20){B.toast('Заполни HTTPS-источник, tactical fit и death-test.',true);return;}
 if(!window.QuestExtra?.serverSeal){B.toast('Облачная фиксация недоступна.',true);return;}
 serverSealBusy=true;
 try{
  const snapshot={version:1,fixtureKey:g.fixture_key,competition:g.competition,kickoff:g.kickoff,
   home:g.home_team,away:g.away_team,asOfClaim:new Date().toISOString(),
   research:{...x,snapshot:'',serverSealId:''},calendarSource:g.source_url,timingStatus:g.timing_status};
  const receipt=await window.QuestExtra.serverSeal('research',g.fixture_key,g.kickoff,snapshot);
  x.serverSealId=receipt.id;x.sealedAt=receipt.sealed_at;x.state='sealed';x.updatedAt=x.sealedAt;
  x.snapshot=JSON.stringify({...snapshot,serverSealId:receipt.id,serverTime:receipt.sealed_at});
  B.save();B.refresh();B.toast('Серверный PREMATCH seal подтверждён. Время установлено базой.');
 }catch(err){B.toast('SERVER SEAL НЕ СОСТОЯЛСЯ: '+String(err.message||err).slice(0,170),true);}
 finally{serverSealBusy=false;}
}
function copy(){
 const g=context().match;if(!g||Date.parse(g.kickoff)<=Date.now()){B.toast('Прематч-импорт недоступен.',true);return;}
 const d=gdate(g),data=B.data(),t=data.tours[d]||(data.tours[d]=E.emptyTour(d));
 if(t.state!=='draft'||t.legs.length>=3||t.legs.some(l=>l.fixtureId===g.fixture_key)){B.toast('Тур закрыт, заполнен или матч повторяется.',true);return;}
 const l=E.emptyLeg();l.home=g.home_team;l.away=g.away_team;l.fixtureId=g.fixture_key;l.kickoff=d+'T'+gtime(g);l.notes='Событие из календаря. Коэффициент, рынок и P ещё не проверены.';
 t.legs.push(l);B.save();B.go('tour',d);
}
document.addEventListener('click',e=>{
 const el=e.target.closest('[data-v5-act]');if(!el)return;
 if(el.dataset.v5Act==='refresh')window.QuestSchedule?.load();
 else if(el.dataset.v5Act==='seal')seal();
 else if(el.dataset.v5Act==='server-seal')serverSealResearch();
 else if(el.dataset.v5Act==='copy')copy();
});
document.addEventListener('change',e=>{
 const el=e.target;
 if(el.id==='v5-day'){day=el.value;selected='';B.refresh();}
 else if(el.id==='v5-match'){selected=el.value;B.refresh();}
 else if(el.dataset?.v5Field)updateField(el);
});
window.addEventListener('quest-fixtures-updated',()=>{if(/^#(scout|arena|weak)/.test(location.hash))B.refresh();});
window.QuestV5={scoutView,arenaView,weakView,context,storage:store,day:()=>day,setDay:d=>{if(E.days.includes(d)){day=d;selected='';B.refresh();}},selectMatch:k=>{if(context().matches.some(x=>x.fixture_key===k)){selected=k;B.refresh();}}};
B.refresh();
})();