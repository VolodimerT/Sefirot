(() => {
'use strict';
const B = window.questBridge;
const API = 'https://kxqpwgwihtjmqlcxgfxp.supabase.co/rest/v1/sefirot_december_quest_fixtures';
const KEY = 'sb_publishable_ue9huxLpXqo4iJxRGfd3yw_WRM0sHBO';
const TXT = {
  UCL:'Лига чемпионов', UEL:'Лига Европы', UECL:'Лига конференций',
  EPL:'АПЛ', LALIGA:'Ла Лига', SERIEA:'Серия А', BUNDES:'Бундеслига',
  LIGUE1:'Лига 1', COPPA:'Кубок Италии'
};
let games=[], loaded=false, loading=false, error='', day='all', comp='all', confirmedOnly=false;
const safe = B.escape;
const dayFormat = new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Kyiv',year:'numeric',month:'2-digit',day:'2-digit'});
const timeFormat = new Intl.DateTimeFormat('ru-RU',{timeZone:'Europe/Kyiv',hour:'2-digit',minute:'2-digit',hour12:false});
function localDay(x){return dayFormat.format(new Date(x.kickoff));}
function localTime(x){return timeFormat.format(new Date(x.kickoff));}
function refreshIfActive(){if(window.location.hash.slice(1).split('?')[0]==='fixtures')B.refresh();}
function normalize(list){
 if(!Array.isArray(list))throw Error('Некорректный формат расписания');
 return list.filter(x=>{
  if(!x||typeof x.kickoff!=='string'||!Number.isFinite(Date.parse(x.kickoff)))return false;
  const d=localDay(x), tm=localTime(x);
  return d>='2026-12-01'&&d<='2026-12-31'&&tm>='21:00'&&tm<='23:00'
   && typeof x.home_team==='string'&&typeof x.away_team==='string';
 }).sort((a,b)=>Date.parse(a.kickoff)-Date.parse(b.kickoff)||a.fixture_key.localeCompare(b.fixture_key));
}
async function load(){
 if(loading)return;loading=true;error='';
 try{
  const url=API+'?select=fixture_key,competition,home_team,away_team,kickoff,source_name,source_url,source_quality,timing_status,note&order=kickoff.asc&limit=500';
  const r=await fetch(url,{headers:{'apikey':KEY,'Accept':'application/json'},cache:'no-store'});
  if(!r.ok)throw Error('Ошибка API '+r.status);
  games=normalize(await r.json());loaded=true;
 }catch(e){error=String(e.message||e);loaded=true;}
 finally{loading=false;refreshIfActive();}
}
function view(){
 if(!loaded&&!loading)Promise.resolve().then(load);
 const n=games.length;
 const days=Array.from({length:31},(_,i)=>'2026-12-'+String(i+1).padStart(2,'0'));
 const counts=Object.create(null);
 for(const x of games){const k=localDay(x);counts[k]=(counts[k]||0)+1;}
 const leagues=[...new Set(games.map(x=>x.competition))].sort();
 const records=games.filter(x=>(day==='all'||localDay(x)===day)&&(comp==='all'||x.competition===comp)&&(!confirmedOnly||x.source_quality==='official'&&x.timing_status==='confirmed'));
 const daysWithGames=Object.keys(counts).length;
 let out='<div class="eyebrow">SEASON 01 / РАСПИСАНИЕ</div><h1 class="page-title">Матчи декабря</h1>';
 out+='<p class="page-intro">Календарь футбола на 1–31 декабря 2026. Начало 21:00–23:00 по Киеву. Редактирование купонов и ставки здесь не выполняются.</p>';
 out+='<div class="fq-metrics"><div><strong>'+n+'</strong><span>матчей в каталоге</span></div><div><strong>'+daysWithGames+'</strong><span>дней с матчами</span></div><div><strong>21–23</strong><span>часов по Киеву</span></div></div>';
 if(error)out+='<div class="notice error">Не удалось загрузить расписание: '+safe(error)+' <button type="button" class="button secondary" data-fq="retry">Повторить</button></div>';
 if(loading&&!loaded)out+='<div class="notice">Загрузка официального календаря…</div>';
 out+='<div class="panel fq-panel"><div class="section-head"><h2 class="section-heading">Выбор дня</h2><button class="button secondary" type="button" data-fq="retry">Обновить</button></div><div class="fq-days">';
 out+='<button type="button" class="fq-day '+(day==='all'?'active':'')+'" data-fq-day="all">Все <small>'+n+'</small></button>';
 for(const d of days)out+='<button type="button" class="fq-day '+(d===day?'active':'')+'" data-fq-day="'+d+'" title="'+safe(d)+'">'+Number(d.slice(-2))+'<small>'+(counts[d]||'—')+'</small></button>';
 out+='</div><div class="fq-filters"><label>Турнир <select id="fq-competition"><option value="all">Все турниры</option>';
 for(const l of leagues)out+='<option value="'+safe(l)+'" '+(l===comp?'selected':'')+'>'+safe(TXT[l]||l)+'</option>';
 out+='</select></label><label class="fq-check"><input type="checkbox" id="fq-official" '+(confirmedOnly?'checked':'')+'> Только подтверждённые</label></div>';
 out+='<p class="fq-note">Официальные матчи отмечены отдельно. Вторичные источники и условные даты требуют перепроверки ближе к началу.</p></div>';
 out+='<div class="section-head fq-top"><h2 class="section-heading">Найдено: '+records.length+'</h2><span class="fq-note">Данные расписания — не прогноз и не оценка EV</span></div>';
 if(!records.length)out+='<div class="panel fq-empty">По выбранным условиям матчей пока нет. Это не значит, что футбол в этот день отсутствует во всех мировых лигах.</div>';
 let last='';
 for(const g of records){
  const d=localDay(g);
  if(d!==last){last=d;out+='<h3 class="fq-group">'+Number(d.slice(-2))+' декабря 2026</h3>';}
  const official=g.source_quality==='official'&&g.timing_status==='confirmed';
  const badge=g.timing_status==='conditional'?'ВОЗМОЖЕН ПЕРЕНОС':official?'ПОДТВЕРЖДЕНО':'ПРЕДВАРИТЕЛЬНО';
  const validSource=/^https:\/\/(www\.)?(uefa\.com|premierleague\.com|laliga\.com|legaseriea\.it|ligue1\.com|datencenter\.dfb\.de|footprospects\.com)(\/|$)/.test(String(g.source_url||''));
  out+='<article class="fq-match"><div class="fq-kickoff">'+safe(localTime(g))+'</div><div class="fq-details"><div class="fq-comp">'+safe(TXT[g.competition]||g.competition)+'</div><strong>'+safe(g.home_team)+' <span class="fq-sep">—</span> '+safe(g.away_team)+'</strong><div class="fq-bottom"><span class="'+(official?'fq-good':'fq-warn')+'">'+badge+'</span>';
  if(g.note)out+='<span>'+safe(g.note)+'</span>';
  out+='</div></div><div class="fq-actions">';
  if(validSource)out+='<a href="'+safe(g.source_url)+'" target="_blank" rel="noopener noreferrer">Источник</a>';
  out+='<button type="button" data-fq-tour="'+safe(d)+'">Открыть тур</button></div></article>';
 }
 out+='<div class="notice mt-2">Открыть тур — перейти к аналитике этого дня. Матчи не становятся ногами экспресса автоматически. Коэффициенты, модельные вероятности и реальные исходы не заполняются без проверки.</div>';
 return out;
}
document.addEventListener('click',e=>{
 const button=e.target.closest('[data-fq-day],[data-fq],[data-fq-tour]');if(!button)return;
 if(button.hasAttribute('data-fq-day')){day=button.dataset.fqDay;B.refresh();}
 else if(button.dataset.fq==='retry'){load();}
 else if(button.hasAttribute('data-fq-tour')){B.go('tour',button.dataset.fqTour);}
});
document.addEventListener('change',e=>{
 if(e.target.id==='fq-competition'){comp=e.target.value;B.refresh();}
 if(e.target.id==='fq-official'){confirmedOnly=e.target.checked;B.refresh();}
});
const css=document.createElement('style');
css.textContent=String.raw`.fq-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:24px 0}.fq-metrics>div{background:#111b2c;border:1px solid #26334b;border-radius:15px;padding:16px;display:flex;flex-direction:column;gap:4px}.fq-metrics strong{font-size:28px;color:#66f0b7}.fq-metrics span{color:#9ca9bb;font-size:11px}.fq-panel{margin-top:18px}.fq-days{display:flex;gap:7px;overflow-x:auto;padding:7px 0 16px;scroll-snap-type:x mandatory}.fq-day{scroll-snap-align:start;flex:0 0 45px;border:1px solid #34465b;border-radius:10px;background:#152238;color:#f5f8fc;padding:9px 3px;min-height:60px;font-weight:800}.fq-day:first-child{flex-basis:70px}.fq-day.active{background:#1b514c;border-color:#66f0b7}.fq-day small{display:block;color:#93a9b9;font-size:10px;margin-top:4px}.fq-filters{display:flex;flex-wrap:wrap;align-items:end;gap:15px}.fq-filters label{color:#98acc0;display:flex;flex-direction:column;gap:5px;font-size:12px}.fq-filters select{min-width:195px;background:#172337;color:#fff;border:1px solid #344359;padding:10px;border-radius:10px}.fq-filters .fq-check{flex-direction:row;align-items:center;gap:8px}.fq-note{color:#8797ac;font-size:12px;line-height:1.4;margin:11px 0}.fq-top{margin-top:23px}.fq-group{color:#66f0b7;font-size:14px;margin:18px 0 8px}.fq-match{display:flex;align-items:center;gap:15px;border:1px solid #26334b;border-radius:14px;background:#111b2c;padding:14px;margin:9px 0}.fq-kickoff{font-size:20px;font-weight:850;min-width:62px;color:#f5c875;font-variant-numeric:tabular-nums}.fq-details{min-width:0;flex:1}.fq-details strong{font-size:14px;overflow-wrap:anywhere}.fq-comp{font-size:11px;color:#7f91af;margin-bottom:3px}.fq-sep{color:#63718e}.fq-bottom{display:flex;gap:8px;flex-wrap:wrap;color:#b6a38e;font-size:10px;margin-top:6px}.fq-good{color:#66f0b7}.fq-warn{color:#f5c875}.fq-actions{display:flex;gap:7px;flex-direction:column}.fq-actions a,.fq-actions button{border:1px solid #344359;padding:8px 10px;border-radius:8px;color:#c7f6e5;font-size:11px;background:#1c2a40;white-space:nowrap;text-decoration:none;text-align:center}.fq-empty{padding:28px;text-align:center;color:#9eaec1}@media(max-width:660px){.fq-metrics{gap:6px}.fq-metrics>div{padding:9px}.fq-metrics strong{font-size:22px}.fq-metrics span{font-size:9px}.fq-match{gap:9px;padding:10px}.fq-kickoff{font-size:15px;min-width:42px}.fq-details strong{font-size:12px}.fq-actions a,.fq-actions button{font-size:10px;padding:6px}.fq-days{gap:5px}.fq-day{flex-basis:42px}}`;
document.head.appendChild(css);
window.QuestSchedule={view,load,stats:()=>({total:games.length,days:new Set(games.map(localDay)).size}),get:()=>games.slice()};
Promise.resolve().then(load);
})();