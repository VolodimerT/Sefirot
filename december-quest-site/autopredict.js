/* SEFIROT Dec Quest V6 — autonomous probabilities, read-only. */
(() => {
'use strict';
const B=window.questBridge,KEY='sb_publishable_ue9huxLpXqo4iJxRGfd3yw_WRM0sHBO';
const API='https://kxqpwgwihtjmqlcxgfxp.supabase.co/rest/v1/';
const H=B.escape;
const latestRun='sefirot_december_quest_auto_runs?select=started_at,completed_at,model_version,run_status,fetch_ok,sources_attempted,scanned,forecasted,insufficient,errors&order=started_at.desc&limit=1';
let data=[],run=null,validation=[],settlements=[],ready=false,loading=false,error='',checkedAt=0,day='all',league='all',modelOnly=false;
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
 const r=await fetch(API+path,{headers:{apikey:KEY,Accept:'application/json'},cache:'no-store',signal:AbortSignal.timeout(12000)});
 if(!r.ok)throw Error('Supabase REST '+r.status);
 const x=await r.json();if(!Array.isArray(x))throw Error('Некорректный формат автономного результата');
 return x;
}
const stat=()=>({total:data.length,ready:data.filter(modelValid).length,
 unsupported:data.filter(x=>x.status==='UNSUPPORTED_LEAGUE').length,validated_leagues:validation.length,settled:settlements.length,last:run?.completed_at||null});
const historyByFixture=new Map();
let marketFixture=null;
const sealByFixture=new Map();
const formattedDate=value=>Number.isFinite(Date.parse(value))
 ? new Intl.DateTimeFormat('ru-RU',{timeZone:'Europe/Kyiv',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(value))
 : 'Н/Д';
const reasons={
 DUPLICATE_FIXTURE:'Обнаружен дубликат матча', KICKOFF_CONFLICT:'Источники расходятся по kickoff',
 KICKOFF_UNVERIFIED:'Нужно свежее подтверждение kickoff', UNSUPPORTED_LEAGUE:'Турнир вне модели',
 HISTORY_DATA_MISSING:'Свежая история недоступна', INSUFFICIENT_TEAM_HISTORY:'Мало матчей команд',
 ODDS_DATA_MISSING:'Нет котировок', QUOTE_TIMESTAMP_UNVERIFIED:'Время публикации котировки неизвестно',
 LINEUPS_DATA_MISSING:'Нет подтверждённых составов', TACTICAL_FIT_UNVERIFIED:'Тактика не проверена',
 PUBLIC_TRAP_UNVERIFIED:'Рыночная ловушка не проверена', DEATH_TEST_UNVERIFIED:'Death-test без подтверждённых котировок',
 NO_EDGE:'EV по доступной строке ≤ 0', DEATH_TEST_FAIL:'При −5 п.п. условный EV ≤ 0'
};
const percentDelta=value=>typeof value==='number'?fmt(value*100,1)+'%':'Н/Д';
function active(){return location.hash.slice(1).split('?')[0]==='autopredict';}
async function load(){
 if(loading)return;loading=true;error='';checkedAt=Date.now();
 try{
  const [forecasts,runs,checks,finished,seals]=await Promise.all([
   request('sefirot_december_quest_auto_forecasts?select=fixture_key,competition,kickoff,generated_at,source_cutoff,model_version,status,verdict,risk_class,probabilities,markets,best_candidate,evidence,sample_n,notes&order=kickoff.asc&limit=200'),
   request(latestRun),
   request('sefirot_december_quest_auto_validation?select=*&order=competition.asc&limit=20'),
   request('sefirot_december_quest_auto_settlements?select=*&order=settled_at.desc&limit=300'),
   request('sefirot_december_quest_auto_snapshots?select=id,fixture_key,kickoff,generated_at,model_version&order=generated_at.desc,id.desc&limit=300').catch(()=>[])

  ]);
  data=forecasts.filter(x=>typeof x.fixture_key==='string'&&Number.isFinite(Date.parse(x.kickoff))&&x.probabilities);
  run=runs[0]||null;validation=checks;settlements=finished;ready=true;
  sealByFixture.clear();
  for(const seal of seals){
   const key=sealKey(seal);
   if(!sealByFixture.has(key))sealByFixture.set(key,seal);
  }
 }catch(e){error=String(e.message||e);ready=true;}
 finally{loading=false;if(active())B.refresh();}
}
async function refreshIfChanged(){
 if(!active()||document.visibilityState!=='visible'||loading||Date.now()-checkedAt<30000)return;
 checkedAt=Date.now();
 if(error||!ready){await load();return;}
 try{
  const [current]=await request(latestRun);
  if(current?.completed_at!==run?.completed_at)await load();
 }catch(e){error=String(e.message||e);if(active())B.refresh();}
}
function emptyState(){
 const text=error?'Невозможно получить прогнозы: '+H(error):'Прогнозы ещё не созданы. Регулярный расчёт работает на сервере, а не в браузере.';
 return '<div class="panel v6-auto-empty">'+text+' <button class="button secondary" data-auto="reload">Повторить чтение</button></div>';
}
function sealKey(f){return [f.fixture_key,f.model_version,Date.parse(f.kickoff)].join('|');}
function showDetail(f){
 const probs=f.probabilities||{},e=f.evidence||{},markets=Array.isArray(f.markets)?f.markets:[];
 const gradeLabel={win:'выигрыш',half_win:'½ выигрыш',push:'возврат',half_loss:'½ проигрыш',loss:'проигрыш'};
 const rows=markets.map(m=>{
  const distribution=m.settlement?Object.entries(gradeLabel).filter(([key])=>m.settlement[key]>0.00001)
   .map(([key,label])=>label+' '+pct(m.settlement[key])).join(' · '):'';
  const conditional=typeof m.conditional_ev_pct==='number'?percentDelta(m.conditional_ev_pct)+' (условно)'
   :typeof m.conditional_ev==='number'?fmt(m.conditional_ev,0)+' ₴ (условно)':'Н/Д';
  const stress=m.sensitivity?[-0.05,-0.03,0.03,0.05].map(shift=>percentDelta(m.sensitivity[String(shift)])).join(' / '):'Н/Д';
  return '<tr><td>'+H(m.market||'')+'</td><td>'+H(m.pick||'')+'</td><td>'+pct(m.probability)+
   (distribution?'<small class="v6-auto-distribution">'+H(distribution)+'</small>':'')+'</td><td>'+fmt(m.odds,2)+
   '</td><td>'+pct(m.implied)+'</td><td>'+percentDelta(m.edge)+'</td><td>'+conditional+
   '</td><td>'+fmt(m.break_even_odds,2)+' / '+fmt(m.odds_margin,2)+'</td><td>'+stress+'</td><td>'+H(m.source||'')+
   (m.observed_at?' · '+H(formattedDate(m.observed_at))+' · время БК Н/Д':'')+
   (m.quotes?.length?'<small class="v6-auto-distribution">'+H(m.quotes.map(q=>q.bookmaker+' '+fmt(q.odds,2)).join(' · '))+'</small>':'')+'</td></tr>';
 }).join('');
 const alternative=f.best_candidate?.alternative;
 const xgDisplay=row=>row?.matches?fmt(row.xg,2)+' / '+fmt(row.xga,2)+' · '+row.matches+'/'+row.total:'Н/Д';
 return '<div class="v6-auto-detail">'+
 '<div class="v6-auto-evidence"><span>Ожидаемые голы модели: '+fmt(probs.expected_goals_home,2)+' : '+fmt(probs.expected_goals_away,2)+'</span>'+
 '<span>Последний завершённый матч в истории: '+H(e.latest_training_date||'Н/Д')+'</span>'+
 '<span>Матчей в обучении: '+H(String(e.training_matches??'Н/Д'))+'</span>'+
 '<span>Домашние / гостевые наблюдения: '+H(String(e.home_at_home??'Н/Д'))+' / '+H(String(e.away_away??'Н/Д'))+'</span>'+
 '<span>Исторические xG/xGA дома: '+xgDisplay(e.xg?.home_at_home)+' · в гостях: '+xgDisplay(e.xg?.away_away)+'</span>'+
 '<span>Составы: '+H(String(e.lineups?.confirmed_teams??'Н/Д'))+' · данные о травмах: '+(e.injuries?.published?e.injuries.count:'Н/Д')+'</span>'+
 (alternative?'<span>Альтернативный рынок: '+H(alternative.market+' '+alternative.pick)+' · '+percentDelta(alternative.conditional_ev_pct)+' (условно)</span>':'')+'</div>'+
 '<div class="table-scroll"><table class="table"><thead><tr><th>Рынок</th><th>Исход</th><th>P выигрыша</th><th>КФ</th><th>Implied P</th><th>Edge</th><th>EV</th><th>Безубыт. КФ / запас</th><th>EV при −5 / −3 / +3 / +5 п.п.</th><th>Источник</th></tr></thead><tbody>'+rows+'</tbody></table></div></div>';
}
function showHistory(f){
 const items=historyByFixture.get(f.fixture_key);
 if(!Array.isArray(items))return items==='error'?'<p class="muted">Не удалось загрузить снимки. Повторите запрос.</p>':'';
 return items.length?'<ul>'+items.map(item=>'<li>'+H(formattedDate(item.generated_at)+' · '+item.model_version+' · '+(item.evidence?.decision?.verdict||'модельный снимок'))+'</li>').join('')+'</ul>'
  :'<p class="muted">Снимков пока нет.</p>';
}
async function loadHistory(key){
 historyByFixture.set(key,'loading');
 if(active())B.refresh();
 try{
  const rows=await request('sefirot_december_quest_auto_snapshots?select=id,fixture_key,model_version,generated_at,evidence&fixture_key=eq.'+
   encodeURIComponent(key)+'&order=generated_at.desc,id.desc&limit=60');
  historyByFixture.set(key,rows);
 }catch(error){historyByFixture.set(key,'error');}
 if(active())B.refresh();
}
function diagnostics(items){
 const leagues=new Map(),markets=new Map(),buckets=Array.from({length:10},()=>({n:0,p:0,y:0}));
 const add=(map,key,model,baseline)=>{
  if(!model||model.brier==null)return;
  const stat=map.get(key)||{n:0,brier:0,logloss:0,base:0,baseCount:0};
  stat.n++;stat.brier+=model.brier;stat.logloss+=model.logloss;
  if(baseline?.brier!=null){stat.base+=baseline.brier;stat.baseCount++;}
  map.set(key,stat);
 };
 for(const item of items){
  const d=item.details;
  if(!d?.probabilities)continue;
  add(leagues,d.competition,{brier:Number(item.model_brier),logloss:Number(item.model_logloss)},d.baseline);
  for(const market of d.markets||[])add(markets,market.market,market.model,market.baseline);
  for(const key of ['home','draw','away']){
   const p=d.probabilities[key];
   if(!Number.isFinite(p)||p<0||p>1)continue;
   const bucket=buckets[Math.min(9,Math.floor(p*10))];
   bucket.n++;bucket.p+=p;bucket.y+=Number(d.observed===key);
  }
 }
 if(!leagues.size)return '';
 const rows=map=>[...map].map(([key,v])=>'<tr><td>'+H(competitionNames[key]||key)+'</td><td>'+v.n+'</td><td>'+fmt(v.brier/v.n,4)+
  '</td><td>'+fmt(v.logloss/v.n,4)+'</td><td>'+fmt(v.baseCount?v.base/v.baseCount:null,4)+'</td></tr>').join('');
 const table=(label,map)=>'<h3>'+label+'</h3><div class="table-scroll"><table class="table"><thead><tr><th>Группа</th><th>N</th><th>Brier модели</th><th>Log Loss</th><th>Brier базы</th></tr></thead><tbody>'+rows(map)+'</tbody></table></div>';
 return '<details class="v6-auto-detail"><summary>Постматчевая оценка и калибровка</summary>'+table('По лигам',leagues)+table('По рынкам',markets)+
  '<h3>Калибровка 1X2</h3><ul>'+buckets.map((b,i)=>b.n?'<li>'+i*10+'–'+(i+1)*10+'% · '+b.n+' наблюдений · средняя P '+pct(b.p/b.n)+' · частота '+pct(b.y/b.n)+'</li>':'').join('')+'</ul></details>';
}
function view(){
 if(!ready&&!loading)Promise.resolve().then(load);
 const counts=stat();
 const candidates=data.filter(f=>day==='all'||localDay(f)===day).filter(f=>league==='all'||f.competition===league).filter(f=>!modelOnly||modelValid(f));
 const fixtureMap=new Map((window.QuestSchedule?.get()||[]).map(g=>[g.fixture_key,g]));
 const leagues=[...new Set(data.map(f=>f.competition))].sort();
 const next=data.find(f=>Date.parse(f.kickoff)>Date.now());
 const byFixture=new Map(settlements.map(row=>[row.fixture_key,row]));
 const latest=run?.completed_at?new Date(run.completed_at).toLocaleString('ru-RU',{timeZone:'Europe/Kyiv',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}):'Нет успешного запуска';
 let out='<div class="eyebrow">AUTO PREDICTOR</div><h1 class="page-title">Автономный прогнозист</h1>';
 out+='<p class="page-intro">Модель самостоятельно получает завершённые матчи из публичных CSV, рассчитывает вероятности исходов, тоталов и ОЗ, сохраняет серверный прематч-снимок. Реальных ставок нет.</p>';
 out+='<div class="v5-metrics">'+
 '<article><small>Всего матчей</small><strong>'+counts.total+'</strong></article>'+
 '<article><small>С модельной P</small><strong>'+counts.ready+'</strong></article>'+
 '<article><small>Нет покрытия</small><strong>'+counts.unsupported+'</strong></article>'+
 '<article><small>PASS</small><strong>'+data.filter(row=>row.verdict==='пропуск').length+'</strong></article></div>';
 out+='<div class="panel v6-auto-intro"><div><b>Последний расчёт:</b> '+H(latest)+' (Киев) · '+H(run?.run_status||'нет')+' · источники '+H(String(run?.fetch_ok??0))+'/'+H(String(run?.sources_attempted??0))+'</div>'+
 '<div><b>Автозапуск:</b> ежедневно в 19:00 по Киеву; версия '+H(run?.model_version||'нет')+'; дата матча и время — отдельный gate.</div>'+
 '<div class="v6-auto-actions"><button class="button secondary" data-auto="reload">Перечитать прогнозы</button><button class="button secondary" data-route="maintenance">Контроль расписания</button></div></div>';
 if(next){
  const fixture=fixtureMap.get(next.fixture_key);
  out+='<p class="panel v6-auto-intro"><b>Следующий матч:</b> '+H((fixture?.home_team||next.evidence?.home_name||next.fixture_key)+
   ' — '+(fixture?.away_team||next.evidence?.away_name||'')+' · '+formattedDate(next.kickoff))+' (Киев)</p>';
 }
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
 const measured=settlements.filter(row=>row.model_brier!=null);
 const avgSettle=measured.length?measured.reduce((a,z)=>a+Number(z.model_brier),0)/measured.length:null;
 out+='<p class="muted small">Проспективно проверенных исходов: <b>'+measured.length+'</b> · средний Brier '+(avgSettle===null?'Н/Д':fmt(avgSettle,4))+'. Исторический результат может отличаться от будущего. Букмекерское преимущество не доказано.</p></section>';
 out+=diagnostics(settlements);
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
  const home=g?.home_team||f.evidence?.home_name||f.evidence?.home_team||f.fixture_key,away=g?.away_team||f.evidence?.away_name||f.evidence?.away_team||'';
  const P=f.probabilities;
  out+='<article class="panel v6-auto-match"><div class="v6-auto-cardhead"><span class="v6-auto-time">'+H(localTime(f))+'</span><span class="v6-auto-league">'+H(competitionNames[f.competition]||f.competition)+'</span><span class="v6-auto-tag">PASS / Класс '+H(f.risk_class||'D')+'</span></div>';
  out+='<h3>'+H(home)+' <span class="muted">—</span> '+H(away)+'</h3>';
  if(!hasModel){out+='<p class="v5-warning">Нет проверяемой модельной вероятности: '+H(f.evidence?.pass_reasons?'DATA_MISSING':f.notes||'Отсутствуют данные')+'</p>'; }
  else{
   out+='<div class="v6-auto-probs"><div>П1 <b>'+pct(P.home)+'</b><small>Честный КФ '+fair(P.home)+'</small></div><div>Х <b>'+pct(P.draw)+'</b><small>Честный КФ '+fair(P.draw)+'</small></div><div>П2 <b>'+pct(P.away)+'</b><small>Честный КФ '+fair(P.away)+'</small></div></div>';
   out+='<div class="v6-auto-bar"><i style="width:'+Math.round(P.home*100)+'%"></i><i style="width:'+Math.round(P.draw*100)+'%"></i><i style="width:'+Math.round(P.away*100)+'%"></i></div>';
   out+='<div class="v6-auto-secondary"><span>ТБ 2.5: <strong>'+pct(P.o25)+'</strong></span><span>ОЗ: <strong>'+pct(P.btts)+'</strong></span><span>Выборка: <strong>'+H(String(f.sample_n))+'</strong></span></div>';
   const expanded=marketFixture===f.fixture_key;
   out+='<div><button class="button secondary" data-auto-markets="'+H(f.fixture_key)+'" aria-expanded="'+expanded+'">Модель и рынки ('+
    (Array.isArray(f.markets)?f.markets.length:0)+')</button>'+(expanded?showDetail(f):'')+'</div>';
  }
  const e=f.evidence||{},seal=sealByFixture.get(sealKey(f)),finished=byFixture.get(f.fixture_key);
  if(e.pass_reasons?.length)out+='<p class="v6-auto-reasons"><b>Причины PASS</b> '+H(e.pass_reasons.map(code=>reasons[code]||code).join(' · '))+'</p>';
  out+='<div class="v6-auto-evidence"><span>Сбор: '+H(f.status)+' · '+H(formattedDate(f.source_cutoff))+'</span>'+
   '<span>Gateway: '+H(e.gateway_status||'Н/Д')+'</span><span>PREMATCH SEAL: '+H(seal?formattedDate(seal.generated_at):'Нет доступной записи')+'</span></div>';
  if(finished)out+='<p><b>FT '+H(String(finished.actual_home_goals)+' : '+String(finished.actual_away_goals))+
   '</b> · Brier '+fmt(finished.model_brier==null?null:Number(finished.model_brier),4)+
   ' · Log Loss '+fmt(finished.model_logloss==null?null:Number(finished.model_logloss),4)+
   ' · база Brier '+fmt(finished.details?.baseline?.brier,4)+'</p>';
  out+='<div><button class="button secondary" data-auto-history="'+H(f.fixture_key)+'"'+
   (historyByFixture.get(f.fixture_key)==='loading'?' disabled':'')+'>История снимков</button>'+showHistory(f)+'</div>';
  out+='<div class="v6-auto-foot"><span>'+(stale?'ДАННЫЕ УСТАРЕЛИ':!prematch?'Матч начался / прогноз архивный':'Автомодель · только прематч')+'</span>';
  if(hasModel&&g)out+='<button class="button secondary" data-auto-match="'+H(f.fixture_key)+'">Проверить вручную</button>';
  out+='</div></article>';
 }
 out+='<div class="notice warn">История содержит завершённые матчи и счёт FT. Честный КФ = 1/P. Пока котировка и фильтры качества не подтверждены, решение ВСЕГДА PASS.</div>';
 return out;
}
document.addEventListener('click',e=>{
 const btn=e.target.closest('[data-auto],[data-auto-match],[data-auto-history],[data-auto-markets]');if(!btn)return;
 if(btn.dataset.auto==='reload')load();
 if(btn.dataset.autoHistory)loadHistory(btn.dataset.autoHistory);
 if(btn.dataset.autoMarkets){
  const key=btn.dataset.autoMarkets;
  marketFixture=marketFixture===key?null:key;
  B.refresh();
  for(const button of document.querySelectorAll('[data-auto-markets]')){
   if(button.dataset.autoMarkets===key){button.focus({preventScroll:true});break;}
  }
 }
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
window.addEventListener('hashchange',refreshIfChanged);
document.addEventListener('visibilitychange',refreshIfChanged);
setInterval(refreshIfChanged,180000);
Promise.resolve().then(load);
})();