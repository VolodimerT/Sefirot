/* SEFIROT December Quest V5 — deterministic analysis kernel. No odds scraping or real bets. */
(function(root,factory){const api=factory();if(typeof module!=='undefined'&&module.exports)module.exports=api;if(root)root.QuestV5Core=api;})(typeof window!=='undefined'?window:null,function(){
'use strict';
const finite=x=>typeof x==='number'&&Number.isFinite(x);
const percent=x=>finite(x)&&x>0&&x<=100?x:null;
const positive=x=>finite(x)&&x>1?x:null;
const round=x=>Math.round((x+Number.EPSILON)*100)/100;
const localKickoff=x=>typeof x==='string'&&/^2026-12-(0[1-9]|[12]\d|3[01])T([01]\d|2[0-3]):[0-5]\d/.test(x)?Date.parse(x.slice(0,16)+':00+02:00'):null;
function normalizeTeam(s){return String(s||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^\p{L}\p{N}]+/gu,' ').replace(/\b(fc|cf|sc|afc)\b/g,'').replace(/\s+/g,' ').trim();}
function matchAlias(l){
 const h=normalizeTeam(l?.home),a=normalizeTeam(l?.away),dt=String(l?.kickoff||'').slice(0,10);
 return h&&a&&h!==a&&/^2026-12-\d\d$/.test(dt)?[h,a].sort().join('|')+'|'+dt:null;
}
function fixtureIdentity(l){return matchAlias(l)||String(l?.fixtureId||'').trim().toLowerCase();}
function independent(legs){
 if(!Array.isArray(legs)||!legs.length)return false;
 const aliases=legs.map(matchAlias),ids=legs.map(x=>String(x?.fixtureId||'').trim().toLowerCase()).filter(Boolean);
 return aliases.every(Boolean)&&new Set(aliases).size===aliases.length&&new Set(ids).size===ids.length;
}
function scenario(t,settings){
 const price=t?.purchased?Number(settings?.price)||0:0;
 if(t?.mode==='pass')return {odds:null,implied:null,model:null,ev:-price,reason:'PASS: ставка 0'};
 const legs=(t?.legs||[]).filter(x=>x.enabled);
 if(!legs.length||legs.length>3)return {odds:null,implied:null,model:null,ev:null,reason:'Нет 1–3 активных событий'};
 const odds=legs.reduce((v,l)=>positive(l.odds)===null?NaN:v*l.odds,1);
 if(!finite(odds))return {odds:null,implied:null,model:null,ev:null,reason:'Не указаны коэффициенты'};
 const totalOdds=round(odds),implied=1/odds;
 if(legs.length>1&&!t.independenceReviewed)return {odds:totalOdds,implied,model:null,ev:null,reason:'Независимость не подтверждена'};
 if(!independent(legs))return {odds:totalOdds,implied,model:null,ev:null,reason:'Дублирование или отсутствие идентификатора матча'};
 const model=legs.reduce((v,l)=>percent(l.prob)===null?NaN:v*l.prob/100,1);
 if(!finite(model))return {odds:totalOdds,implied:1/odds,model:null,ev:null,reason:'Н/Д: отсутствует независимая модельная вероятность'};
 const stake=finite(settings?.stake)?settings.stake:1000;
 return {odds:totalOdds,implied:1/odds,model,ev:round(model*odds*stake-stake-price),reason:'Условный EV по введённым P; не гарантия'};
}
function feeGate(t,settings){
 const x=scenario(t,settings);
 const ok=x.model!==null&&x.ev!==null&&x.ev>0;
 const red=(t?.legs||[]).filter(l=>l.enabled).length>1&&!independent((t?.legs||[]).filter(l=>l.enabled));
 return {ok,code:red?'RED':ok?'C':'D',verdict:ok?'Предварительный value, неиграбельно без верифицированной P':'PASS',ev:x.ev,reason:red?'Повтор того же матча или неполные названия/дата':x.reason};
}
function sensitivity(p,odds,settings={stake:1000,price:350},delta=5){
 if(percent(p)===null||positive(odds)===null)return null;
 const stake=finite(settings.stake)&&settings.stake>0?settings.stake:1000;
 const fee=finite(settings.price)&&settings.price>=0?settings.price:0;
 const breakEven=(stake+fee)/(stake*odds)*100;
 const calc=z=>round(z/100*odds*stake-stake-fee);
 return {lowP:Math.max(0,p-delta),highP:Math.min(100,p+delta),lowEV:calc(Math.max(0,p-delta)),highEV:calc(Math.min(100,p+delta)),breakEvenP:breakEven,marginPP:p-breakEven,robust:calc(Math.max(0,p-delta))>0};
}
function marketCompare(quotes,settings){
 if(!Array.isArray(quotes))return [];
 return quotes.slice(0,12).map(q=>{
  const p=percent(q?.prob),odds=positive(q?.odds);
  const stake=finite(settings?.stake)?settings.stake:1000;
  const fee=finite(settings?.price)?settings.price:0;
  const x=p===null||odds===null?null:sensitivity(p,odds,{stake,price:fee});
  return {market:String(q?.market||'').slice(0,80),pick:String(q?.pick||'').slice(0,100),odds,prob:p,implied:odds===null?null:100/odds,ev:x?round(p/100*odds*stake-stake-fee):null,
   breakEven:x?.breakEvenP??null,robust:x?.robust??false,source:String(q?.source||'').slice(0,500)};
 });
}
function legAudit(t,settings){
 const legs=(t?.legs||[]).filter(l=>l.enabled);
 return legs.map(l=>{
  const p=percent(l.prob),o=positive(l.odds);
  const issues=[];
  if(o===null)issues.push('Коэффициент отсутствует');
  if(p===null)issues.push('Нет модельной вероятности');
  if(p!==null&&o!==null&&p/100<=1/o)issues.push('Нет подтверждённого положительного value');
  if(l.market==='ЖК'&&!(l.referee&&finite(l.ycGame)&&finite(l.ycFoul)&&l.lowCardRisk&&l.rulesConfirmed&&l.noCleanerMarket))issues.push('Referee Gate не пройден');
  if(o!==null&&o<=1.25)issues.push('Низкий коэффициент — не добивать экспресс');
  if(!matchAlias(l))issues.push('Нет однозначных команд и даты матча');
  if(settings&&scenario(t,settings).ev!==null&&scenario(t,settings).ev<=0)issues.push('Экспресс: чистый EV с оплатой прогноза неположителен');
  return {id:l.id,home:l.home,away:l.away,market:l.market,odds:o,prob:p,implied:o?1/o:null,delta:o&&p!==null?p/100-1/o:null,issues,pass:issues.length===0};
 });
}
function checkedUrl(s){return typeof s==='string'&&s.length<500&&/^https:\/\/(?:[a-z0-9-]+\.)+[a-z]{2,}(?::443)?(?:[\/?#][^\s<>"']*)?$/i.test(s);}
function cardReadiness(x,fixture){
 const signals=[
 ['Источник исследования',checkedUrl(x?.ownSource)],
 ['Карточка обновлена за 7 дней (не гарантия свежести источника)',Number.isFinite(Date.parse(x?.updatedAt))&&Date.now()-Date.parse(x.updatedAt)<=7*86400000&&Date.parse(x.updatedAt)<=Date.now()+60000],
 ['xG обеих команд',finite(x?.homeXgf)&&finite(x?.homeXga)&&finite(x?.awayXgf)&&finite(x?.awayXga)],
 ['Составы и травмы',x?.lineupStatus==='confirmed'&&!!x?.injuriesChecked],
 ['Тактический fit',String(x?.tactical||'').trim().length>=20],
 ['Контраргумент и death-test',String(x?.deathTest||'').trim().length>=20],
 ['Обоснование public trap',String(x?.publicTrap||'').trim().length>=20]
 ];
 if(fixture?.timing_status!=='confirmed')signals.push(['Время начала подтверждено',false]);
 return {total:signals.length,complete:signals.filter(x=>x[1]).length,signals,grade:signals.every(x=>x[1])?'достаточно для аудита, но не для автоматического EV':'требуются данные'};
}
function compareProb(p,odd,stake=1000,fee=350){
 if(percent(p)===null||positive(odd)===null)return null;
 const implied=1/odd,edge=p/100-implied,ev=round(p/100*odd*stake-stake-fee);
 return {implied,edge,ev,breakeven:(stake+fee)/(stake*odd)};
}
function sealedBrier(data){
 let n=0,total=0,hidden=0;const days={};
 for(const [date,t] of Object.entries(data?.tours||{})){
  if(t?.state!=='closed'||typeof t.sealedSnapshot!=='string')continue;
  let s;try{s=JSON.parse(t.sealedSnapshot);}catch{continue;}
  if(!Array.isArray(s.legs)||!t.sealedAt)continue;
  const sealed=Date.parse(t.sealedAt);if(!Number.isFinite(sealed))continue;
  let used=0;
  for(const l of s.legs){
   if(!l.enabled||percent(l.prob)===null)continue;
   const actual=(t.legs||[]).find(x=>x.id===l.id);
   if(!actual||!['win','lose'].includes(actual.status))continue;
   const kickoff=localKickoff(l.kickoff);
   if(!Number.isFinite(kickoff)||sealed>=kickoff){hidden++;continue;}
   const p=l.prob/100,y=actual.status==='win'?1:0;
   total+=(p-y)**2;n++;used++;
  }
  if(used)days[date]=used;
 }
 return {n,brier:n?round(total/n):null,excludedLate:hidden,days};
}
function hypothesis(data,counts,threshold=5){
 const groups={busy:{days:0,wins:0,pnl:0},quiet:{days:0,wins:0,pnl:0}};
 for(const [day,t] of Object.entries(data?.tours||{})){
  if(t?.state!=='closed')continue;
  const key=(Number(counts?.[day])||0)>=threshold?'busy':'quiet',g=groups[key];
  g.days++;if(t.mode!=='pass'&&t.legs?.filter(l=>l.enabled).length&&t.legs.filter(l=>l.enabled).every(l=>l.status==='win'))g.wins++;
  // P&L must be computed by the existing engine; do not derive a guess here.
 }
 return {groups,threshold,usable:Math.min(groups.busy.days,groups.quiet.days)>=20};
}
return {percent,positive,scenario,legAudit,feeGate,sensitivity,marketCompare,checkedUrl,cardReadiness,compareProb,sealedBrier,hypothesis,fixtureIdentity,matchAlias,independent,localKickoff,round};
});