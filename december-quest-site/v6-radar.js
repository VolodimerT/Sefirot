/* V5.2 market radar; all probabilities and odds are manual, not market feed */
(function(){
'use strict';
const B=window.questBridge,E=window.SEQ,C=window.QuestV5Core,V=window.QuestV5;
if(!B||!E||!C||!V)return;
const H=B.escape;
function quote(){
 return {id:E.id(),market:"1X2",pick:"",odds:null,prob:null,source:"",observedAt:""};
}
const money=v=>Number.isFinite(v)?B.money(v):"Н/Д",n=v=>Number.isFinite(v)?v.toFixed(2):"Н/Д";
function radarView(){
 const ctx=V.context(),g=ctx.match,day=V.day();
 let html='<div class="eyebrow">SEFIROT / V5.2</div><h1 class="page-title">Market Radar</h1><p class="page-intro">Сравнение главных и малых рынков ОДНОГО матча. Коэффициенты и P вручную; автоматических ставок или выдуманных прогнозов нет.</p>';
 html+='<div class="panel v5-select"><label>Дата<select id="radar-day">'+E.days.map(d=>'<option value="'+d+'"'+(day===d?' selected':'')+'>'+Number(d.slice(-2))+' декабря</option>').join('')+'</select></label><label>Матч<select id="radar-match">'+(ctx.matches.length?ctx.matches.map(x=>'<option value="'+H(x.fixture_key)+'"'+(g?.fixture_key===x.fixture_key?' selected':'')+'>'+H(x.home_team)+' — '+H(x.away_team)+'</option>').join(''):'<option value="">Нет событий</option>')+'</select></label></div>';
 if(!g)return html+'<div class="panel">Матчи пока не подтверждены для этой даты.</div>';
 const card=V.storage()[g.fixture_key]||null;
 const quotes=card?.marketQuotes||[];
 const t=B.data().tours[day],fee=t?.purchased?B.data().settings.price:0;
 const settings={stake:B.data().settings.stake,price:fee};
 const frozen=card?.state==='sealed';
 html+='<div class="v5-metrics"><article><small>Матч</small><strong>'+H(g.competition)+'</strong></article><article><small>Начало (Киев)</small><strong>'+H(new Intl.DateTimeFormat('ru-RU',{timeZone:"Europe/Kyiv",hour:"2-digit",minute:"2-digit"}).format(new Date(g.kickoff)))+'</strong></article><article><small>Флет</small><strong>'+H(String(settings.stake))+' ₴</strong></article><article><small>Цена прогноза</small><strong>'+H(String(fee))+' ₴</strong></article></div>';
 html+='<div class="notice warn">Рынки сравниваются по одному, НЕ как экспресс. Сначала исход, двойной шанс, DNB, форы, тоталы, ОЗ и индивидуальные тоталы. Small markets — только если данные чище. Класс A по ручным P не присваивается.</div>';
 if(!frozen)html+='<div class="v5-buttons"><button class="button" data-radar="add">+ Добавить рынок</button><button class="button secondary" data-route="scout">Заполнить AI Scout</button></div>';
 else html+='<div class="notice">SEALED: этот набор рынков уже не редактируется. Для нового варианта требуется другой матч/исследование.</div>';
 if(!quotes.length)html+='<div class="panel v5-empty">Коэффициентов нет. Market Radar не придумывает линию: нет котировки или вероятности — PASS.</div>';
 const calc=C.marketCompare(quotes,settings);
 for(let i=0;i<quotes.length;i++){
  const q=quotes[i],a=calc[i],disabled=frozen?' disabled':'';
  const input=(k,type,v,extra='')=>'<input type="'+type+'" data-radar-field="'+k+'" data-radar-i="'+i+'" '+extra+' value="'+H(v??'')+'" '+disabled+'>';
  html+='<article class="panel v5-market"><div class="section-head"><h3 class="panel-title">Рынок '+(i+1)+'</h3>'+(frozen?'SEALED':'<button data-radar="delete" data-i="'+i+'" class="button secondary">Удалить</button>')+'</div>';
  html+='<div class="v5-pair"><label class="v5-field">Маркет<select data-radar-field="market" data-radar-i="'+i+'" '+disabled+'>'+E.markets.map(z=>'<option value="'+H(z)+'"'+(z===q.market?' selected':'')+'>'+H(z)+'</option>').join('')+'</select></label>';
  html+='<label class="v5-field">Исход / линия'+input('pick','text',q.pick,'maxlength="120"')+'</label>';
  html+='<label class="v5-field">Коэффициент'+input('odds','number',q.odds,'step="0.01" min="1.01" max="10000"')+'</label>';
  html+='<label class="v5-field">P модели (%) — только с проверенным источником'+input('prob','number',q.prob,'step="0.1" min="0.1" max="100"')+'</label></div>';
  html+='<label class="v5-field">Источник данных / расчёта P (HTTPS)'+input('source','url',q.source,'maxlength="500"')+'</label>';
  const source=C.checkedUrl(q.source);const low=a?.prob!==null&&a?.odds?C.sensitivity(a.prob,a.odds,settings):null;
  const status=source&&a?.ev!==null&&a?.ev>0&&a.robust?'УСЛОВНО ПОЛОЖИТЕЛЬНО, P НЕ ВЕРИФИЦИРОВАНА':'PASS / НЕТ ДОКАЗАННОГО VALUE';
  html+='<div class="v5-market-result"><b>'+status+'</b><div class="v5-metrics">'+
  '<article><small>Implied P</small><strong>'+(a?.implied===null?'Н/Д':n(a.implied)+'%')+'</strong></article>'+
  '<article><small>Безубыточная P с расходами</small><strong>'+(a?.breakEven===null?'Н/Д':n(a.breakEven)+'%')+'</strong></article>'+
  '<article><small>EV netto</small><strong>'+money(a?.ev)+'</strong></article>'+
  '<article><small>EV при P−5 п.п.</small><strong>'+money(low?.lowEV)+'</strong></article></div></div>';
  if(q.market==='ЖК')html+='<p class="v5-warning">Referee Gate обязателен. Отдельной формы строгой проверки ЖК здесь нет — PASS.</p>';
  html+='</article>';
 }
 html+='<div class="notice">Показатели условные: математический EV не доказывает качество P. Корреляционные рынки одного матча запрещено объединять в экспресс. Для фиксации результатов используй прематч-снимок.</div>';
 return html;
}
function canEdit(){
 const g=V.context().match;if(!g)return null;
 let cards=V.storage(),x=cards[g.fixture_key];
 if(!x){x={fixtureKey:g.fixture_key,home:g.home_team,away:g.away_team,competition:g.competition,kickoff:g.kickoff,
  ownSource:'',sourceUrl:g.source_url,sourceCheckedAt:g.checked_at,homeXgf:null,homeXga:null,awayXgf:null,awayXga:null,
  lineupStatus:'unknown',injuriesChecked:false,tactical:'',publicTrap:'',deathTest:'',notes:'',state:'draft',sealedAt:'',snapshot:'',marketQuotes:[],updatedAt:''};
  cards[g.fixture_key]=x;
 }
 if(x.state==='sealed'||Date.parse(g.kickoff)<=Date.now()){B.toast('Запечатанный или начавшийся матч изменять нельзя.',true);return null;}
 if(!Array.isArray(x.marketQuotes))x.marketQuotes=[];
 return x;
}
document.addEventListener('click',e=>{
 const b=e.target.closest('[data-radar]');if(!b)return;
 const x=canEdit();if(!x)return;
 if(b.dataset.radar==='add'){if(x.marketQuotes.length>=12){B.toast('Максимум 12 рынков на матч.',true);return;}x.marketQuotes.push(quote());}
 else if(b.dataset.radar==='delete'){const i=Number(b.dataset.i);if(Number.isInteger(i)&&i>=0&&i<x.marketQuotes.length)x.marketQuotes.splice(i,1);}
 x.updatedAt=new Date().toISOString();B.save();B.refresh();
});
document.addEventListener('change',e=>{
 const el=e.target;
 if(el.id==='radar-day'){V.setDay(el.value);return;}
 if(el.id==='radar-match'){const sel=document.getElementById('v5-match');if(sel){sel.value=el.value;sel.dispatchEvent(new Event('change',{bubbles:true}));} else {window.QuestV5?.selectMatch?.(el.value);B.refresh();}return;}
 if(!el.dataset?.radarField)return;
 const x=canEdit();if(!x)return;
 const i=Number(el.dataset.radarI),q=x.marketQuotes[i];if(!q)return;
 const k=el.dataset.radarField;let val=el.value;
 if(k==='odds'||k==='prob'){if(val==='')val=null;else{val=Number(val);if(!Number.isFinite(val)||val<=(k==='odds'?1:0)||val>(k==='odds'?10000:100)){B.toast('Неверная цена или вероятность.',true);return;}}}
 else if(k==='market'){if(!E.markets.includes(val))return;}
 else if(k==='source'){if(val&&!C.checkedUrl(val)){B.toast('Нужна ссылка HTTPS.',true);return;}val=val.slice(0,500);}
 else if(k==='pick')val=val.slice(0,120);else return;
 q[k]=val;q.observedAt=new Date().toISOString();x.updatedAt=q.observedAt;B.save();B.refresh();
});
window.addEventListener('quest-fixtures-updated',()=>{if(window.location.hash.startsWith('#radar'))B.refresh();});
Object.assign(V,{radarView});
B.refresh();
})();