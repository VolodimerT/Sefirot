/* SEFIROT Dec Quest V6 — autonomous probabilities, read-only. */
(() => {
'use strict';
const B=window.questBridge,KEY='sb_publishable_ue9huxLpXqo4iJxRGfd3yw_WRM0sHBO';
const API='https://kxqpwgwihtjmqlcxgfxp.supabase.co/rest/v1/';
const H=B.escape;let data=[],run=null,validation=[],settlements=[],ready=false,loading=false,error='',lastLoaded=0,day='all',league='all',modelOnly=false;
const dateFmt=new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Kyiv',year:'numeric',month:'2-digit',day:'2-digit'});
const timeFmt=new Intl.DateTimeFormat('ru-RU',{timeZone:'Europe/Kyiv',hour:'2-digit',minute:'2-digit',hour12:false});
const fmt=(v,d=1)=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('ru-RU',{minimumFractionDigits:d,maximumFractionDigits:d}):'Н/Д';
const pct=v=>typeof v==='number'&&Number.isFinite(v)&&v>=0&&v<=1?fmt(v*100,1)+'%':'Н/Д';
const fair=v=>typeof v==='number'&&Number.isFinite(v)&&v>0&&v<=1?fmt(1/v,2):'Н/Д';
const modelValid=f=>{
 const p=f?.probabilities||{},generated=Date.parse(f?.generated_at),kickoff=Date.parse(f?.kickoff),cutoff=Date.parse(f?.source_cutoff);
 return ['MODEL_ONLY','WAITING_ODDS'].includes(f?.status)&&Number.isFinite(generated)&&Number.isFinite(kickoff)&&generated<kickoff&&Number.isFinite(cutoff)&&cutoff<=generated+1000
 &&Number.isFinite(f?.sample_n)&&f.sample_n>=6
 &&['home','draw','away'].every(k=>typeof p[k]==='number'&&Number.isFinite(p[k])&&p[k]>0&&p[k]<1)
 &&Math.abs(p.home+p.draw+p.away-1)<0.02;
};
const localDay=x=>dateFmt.format(new Date(x.kickoff)),localTime=x=>timeFmt.format(new Date(x.kickoff));
const competitionNames={EPL:'АПЛ',LALIGA:'Ла Лига',SERIEA:'Серия А',BUNDES:'Бундеслига',LIGUE1:'Лига 1',UCL:'Лига чемпионов',UEL:'Лига Европы',UECL:'Лига конференций',COPPA:'Кубок Италии'};
async function request(path){
 const r=await fetch(API+path,{headers:{apikey:KEY,Accept:'application/json'},cache:'no-store'});
 if(!r.ok)throw Error('Supabase REST '+r.status);
 const x=await r.json();if(!Array.isArray(x))throw Error('Некорректный формат автономного результата');
 return x;
}
const stat=()=>({total:data.length,ready:data.filter(modelValid).length,
 unsupported:data.filter(x=>x.status==='UNSUPPORTED_LEAGUE').length,validated_leagues:validation.length,settled:settlements.length,last:run?.completed_at||null});
function active(){return location.hash.slice(1).split('?')[0]==='autopredict';}
async function load(){
 if(loading)return;loading=true;error='';
 try{
  const [forecasts,runs,checks,finished]=await Promise.all([
   request('sefirot_december_quest_auto_forecasts?select=fixture_key,competition,kickoff,generated_at,source_cutoff,model_version,status,verdict,risk_class,probabilities,markets,best_candidate,evidence,sample_n,notes&order=kickoff.asc&limit=200'),
   request('sefirot_december_quest_auto_runs?select=started_at,completed_at,model_version,run_status,fetch_ok,sources_attempted,scanned,forecasted,insufficient,errors&order=started_at.desc&limit=1'),
   request('sefirot_december_quest_auto_validation?select=competition,model_version,sample_n,model_brier,baseline_brier,model_logloss,baseline_logloss,relative_skill,status,generated_at&order=competition.asc&limit=20'),
   request('sefirot_december_quest_auto_settlements?select=fixture_key,model_brier,model_logloss,result,settled_at,source_quality&order=settled_at.desc&limit=200')
  ]);
  data=forecasts.filter(x=>typeof x.fixture_key==='string'&&Number.isFinite(Date.parse(x.kickoff))&&x.probabilities);
  run=runs[0]||null;validation=checks;settlements=finished;lastLoaded=Date.now();ready=true;
 }catch(e){error=String(e.message||e);ready=true;}
 finally{loading=false;if(active())B.refresh();}
}
function emptyState(){
 const text=error?'Невозможно получить прогнозы: '+H(error):'Прогнозы ещё не созданы. Регулярный расчёт работает на сервере, а не в браузере.';
 return '<div class="panel v6-auto-empty">'+text+' <button class="button secondary" data-auto="reload">Повторить чтение</button></div>';
}
function showDetail(f,index){
 const probs=f.probabilities||{},e=f.evidence||{},markets=Array.isArray(f.markets)?f.markets:[];
 const rows=markets.map(m=>'<tr><td>'+H(m.market||'')+'</td><td>'+H(m.pick||'')+'</td><td>'+pct(m.probability)+'</td><td>'+(typeof m.odds==='number'?fmt(m.odds,2):'Н/Д')+'</td><td>'+(typeof m.conditional_ev==='number'?fmt(m.conditional_ev,0)+' ₴ (условно)':'Н/Д')+'</td></tr>').join('');
 return '<details class="v6-auto-detail"><summary>Модель и рынки ('+markets.length+')</summary>'+
 '<div class="v6-auto-evidence"><span>Голы модели: '+fmt(probs.expected_goals_home,2)+' : '+fmt(probs.expected_goals_away,2)+'</span>'+
 '<span>Последний исходный матч: '+H(e.latest_training_date||'нет данных')+'</span>'+
 '<span>Лига, матчей в обучении: '+H(String(e.training_matches??'Н/Д'))+'</span>'+
 '<span>Домашние/гостевые наблюдения: '+H(String(e.home_at_home??'Н/Д'))+'/'+H(String(e.away_away??'Н/Д'))+'</span>'+
 '<span>Составы и tactical fit: не проверены · исторические голы ≠ xG</span></div>'+
 '<div class="table-scroll"><table class="table"><thead><tr><th>Рынок</th><th>Исход</th><th>P модели</th><th>КФ</th><th>Условный EV</th></tr></thead><tbody>'+rows+'</tbody></table></div>'+
 '<p class="muted small">Вероятности из результатов команд. Ни одна P не является подтверждённым value. Введите проверенную котировку в Market Radar, затем проведите независимый аудит.</p>'+
 '</details>';
}
function view(){
 if(!ready&&!loading)Promise.resolve().then(load);
 const counts=stat();
 const candidates=data.filter(f=>day==='all'||localDay(f)===day).filter(f=>league==='all'||f.competition===league).filter(f=>!modelOnly||modelValid(f));
 const fixtureMap=new Map((window.QuestSchedule?.get()||[]).map(g=>[g.fixture_key,g]));
 const leagues=[...new Set(data.map(f=>f.competition))].sort();
 const latest=run?.completed_at?new Date(run.completed_at).toLocaleString('ru-RU',{timeZone:'Europe/Kyiv',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'Нет успешного запуска';
 let out='<div class="eyebrow">SEFIROT / PROSPECTIVE SHADOW MODEL</div><h1 class="page-title">Автономный прогнозист</h1>';
 out+='<p class="page-intro">Модель самостоятельно получает завершённые матчи из публичных CSV, рассчитывает вероятности исходов, тоталов и ОЗ, сохраняет серверный прематч-снимок. Реальных ставок нет.</p>';
 out+='<div class="v5-metrics">'+
 '<article><small>Всего матчей</small><strong>'+counts.total+'</strong></article>'+
 '<article><small>С модельной P</small><strong>'+counts.ready+'</strong></article>'+
 '<article><small>Нет покрытия</small><strong>'+counts.unsupported+'</strong></article>'+
 '<article><small>Проверенных value</small><strong>0</strong></article></div>';
 out+='<div class="panel v6-auto-intro"><div><b>Последний расчёт:</b> '+H(latest)+' (Киев) · '+H(run?.run_status||'нет')+' · источники '+H(String(run?.fetch_ok??0))+'/'+H(String(run?.sources_attempted??0))+'</div>'+
 '<div><b>Автозапуск:</b> ежедневно в 19:00 по Киеву; версия '+H(run?.model_version||'нет')+'; дата матча и время — отдельный gate.</div>'+
 '<div class="v6-auto-actions"><button class="button secondary" data-auto="reload">Перечитать прогнозы</button><button class="button secondary" data-route="maintenance">Контроль расписания</button></div></div>';
 if(error)out+='<div class="notice warn">Доступность модели временно не подтверждена: '+H(error)+'. Сохранённые старые P могут устареть. PASS.</div>';
 if(loading&&!ready)out+='<div class="notice">Получаю автоматические прогнозы из Supabase…</div>';
 const audit=validation.filter(v=>v.sample_n>0);
 out+='<section class="panel v6-auto-audit"><div class="section-head"><h2 class="section-heading">Проверка модели</h2><span class="muted small">Walk-forward, только матчи до прогноза</span></div>';
 if(!audit.length)out+='<p class="muted">Историческая проверка пока отсутствует. Не считай P подтверждённой.</p>';
 else {
  out+='<div class="table-scroll"><table class="table"><thead><tr><th>Лига</th><th>Тестов</th><th>Brier модели</th><th>Brier базы</th><th>Результат</th></tr></thead><tbody>';
  for(const v of audit)out+='<tr><td>'+H(competitionNames[v.competition]||v.competition)+'</td><td>'+H(String(v.sample_n))+'</td><td>'+fmt(Number(v.model_brier),4)+'</td><td>'+fmt(Number(v.baseline_brier),4)+'</td><td>'+H(v.status==='PROMISING'?'Ниже базы (пока SHADOW)':v.status==='NO_EDGE'?'Нет преимущества над базой':'Недостаточно')+'</td></tr>';
  out+='</tbody></table></div>';
 }
 const avgSettle=settlements.length?settlements.reduce((a,z)=>a+Number(z.model_brier||0),0)/settlements.length:null;
 out+='<p class="muted small">Проспективно проверенных исходов: <b>'+settlements.length+'</b> · средний Brier '+(avgSettle===null?'Н/Д':fmt(avgSettle,4))+'. Исторический результат может отличаться от будущего. Букмекерское преимущество не доказано.</p></section>';
 if(!data.length)return out+emptyState();
 out+='<div class="panel v6-auto-filter"><label>День<select id="v6-auto-day"><option value="all"'+(day==='all'?' selected':'')+'>Все 31 дня</option>';
 for(let d=1;d<=31;d++){const val='2026-12-'+String(d).padStart(2,'0');out+='<option value="'+val+'"'+(day===val?' selected':'')+'>'+d+' декабря</option>';}
 out+='</select></label><label>Турнир<select id="v6-auto-league"><option value="all">Все турниры</option>';
 for(const l of leagues)out+='<option value="'+H(l)+'"'+(league===l?' selected':'')+'>'+H(competitionNames[l]||l)+'</option>';
 out+='</select></label><label class="v6-auto-check"><input type="checkbox" id="v6-auto-covered"'+(modelOnly?' checked':'')+'> Только с вероятностями</label></div>';
 out+='<div class="section-head"><h2 class="section-heading">Матчей: '+candidates.length+'</h2><span class="muted small">Все решения — PASS до доказанного value</span></div>';
 if(!candidates.length)out+='<div class="panel">На эту дату нет доступных прогнозов или матчей.</div>';
 let lastDay='';
 for(const f of candidates){
  const g=fixtureMap.get(f.fixture_key),hasModel=modelValid(f);
  const age=Date.now()-Date.parse(f.generated_at),stale=!Number.isFinite(age)||age>36*3600000;
  const prematch=Date.now()<Date.parse(f.kickoff);const d=localDay(f);
  if(d!==lastDay){lastDay=d;out+='<h3 class="v6-auto-daytitle">'+Number(d.slice(-2))+' декабря 2026</h3>';}
  const home=g?.home_team||f.evidence?.home_team||f.fixture_key,away=g?.away_team||f.evidence?.away_team||'';
  const P=f.probabilities;
  out+='<article class="panel v6-auto-match"><div class="v6-auto-cardhead"><span class="v6-auto-time">'+H(localTime(f))+'</span><span class="v6-auto-league">'+H(competitionNames[f.competition]||f.competition)+'</span><span class="v6-auto-tag">PASS / Класс D</span></div>';
  out+='<h3>'+H(home)+' <span class="muted">—</span> '+H(away)+'</h3>';
  if(!hasModel){out+='<p class="v5-warning">Нет проверяемой модельной вероятности: '+H(f.notes||'Отсутствуют данные либо нарушен временной/вероятностный gate')+'</p>'; }
  else{
   out+='<div class="v6-auto-probs"><div>П1 <b>'+pct(P.home)+'</b><small>Честный КФ '+fair(P.home)+'</small></div><div>Х <b>'+pct(P.draw)+'</b><small>Честный КФ '+fair(P.draw)+'</small></div><div>П2 <b>'+pct(P.away)+'</b><small>Честный КФ '+fair(P.away)+'</small></div></div>';
   out+='<div class="v6-auto-bar"><i style="width:'+Math.round(P.home*100)+'%"></i><i style="width:'+Math.round(P.draw*100)+'%"></i><i style="width:'+Math.round(P.away*100)+'%"></i></div>';
   out+='<div class="v6-auto-secondary"><span>ТБ 2.5: <strong>'+pct(P.o25)+'</strong></span><span>ОЗ: <strong>'+pct(P.btts)+'</strong></span><span>Выборка: <strong>'+H(String(f.sample_n))+'</strong></span></div>';
   out+=showDetail(f);
  }
  out+='<div class="v6-auto-foot"><span>'+(stale?'ДАННЫЕ УСТАРЕЛИ':!prematch?'Матч начался / прогноз архивный':'Автомодель · только прематч')+'</span>';
  if(hasModel&&g)out+='<button class="button secondary" data-auto-match="'+H(f.fixture_key)+'">Проверить вручную</button>';
  out+='</div></article>';
 }
 out+='<div class="notice warn">Внимание: DQ-POISSON-0.2 прошла предварительную внутреннюю walk-forward проверку на 5 лигах, но преимущество над букмекерской линией НЕ доказано. Честный КФ = 1/P без маржи — это расчёт, а не предложение букмекера. Используются голы итоговых матчей, не xG; нет подтверждённых составов, tactical fit и реальных прематч-котировок. Поэтому ВСЕГДА PASS. Live, догон и реальные ставки запрещены.</div>';
 return out;
}
document.addEventListener('click',e=>{
 const btn=e.target.closest('[data-auto],[data-auto-match]');if(!btn)return;
 if(btn.dataset.auto==='reload')load();
 if(btn.dataset.autoMatch){
  const f=data.find(x=>x.fixture_key===btn.dataset.autoMatch);
  if(f?.kickoff&&window.QuestV5){
   const date=localDay(f);
   window.QuestV5.setDay(date);window.QuestV5.selectMatch(f.fixture_key);B.go('radar');
  }
 }
});
document.addEventListener('change',e=>{
 if(e.target?.id==='v6-auto-day'){day=e.target.value;B.refresh();}
 if(e.target?.id==='v6-auto-league'){league=e.target.value;B.refresh();}
 if(e.target?.id==='v6-auto-covered'){modelOnly=e.target.checked;B.refresh();}
});
window.QuestAutoPredict={view,load,stat,get:()=>data.slice()};
Promise.resolve().then(load);
})();