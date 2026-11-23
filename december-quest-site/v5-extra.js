/* December Quest V5: duels, research hypotheses, career & schedule operations */
(function(){
'use strict';
const B=window.questBridge,E=window.SEQ,C=window.QuestV5Core,V=window.QuestV5;
if(!B||!E||!C||!V)return;
const h=B.escape,f=n=>Number.isFinite(n)?n.toFixed(2):'Н/Д';
const currency=n=>Number.isFinite(n)?B.money(n):'Н/Д';
const localDay=g=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Kyiv',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(g.kickoff));
const games=()=>window.QuestSchedule?.get()||[];
function heading(t,s){return '<div class="eyebrow">SEFIROT / FOOTBALL INTELLIGENCE V5</div><h1 class="page-title">'+t+'</h1><p class="page-intro">'+s+'</p>';}
function metric(label,value){return '<article><small>'+h(label)+'</small><strong>'+h(String(value))+'</strong></article>';}
function duelView(){
 const day=V.day(),d=B.data(),t=d.tours[day]||E.emptyTour(day),b=C.sealedBrier(d),q=C.scenario(t,d.settings);
 let out=heading('CAP vs SEFIROT','Дуэль исходного прогноза и нашего решения. Исходы считаем отдельно; три стратегии не складываем в одну прибыль.');
 out+='<div class="panel v5-select"><label>Игровой день<select id="v5-duel-day">'+E.days.map(x=>'<option value="'+x+'"'+(x===day?' selected':'')+'>'+Number(x.slice(-2))+' декабря</option>').join('')+'</select></label><button class="button secondary" data-route="tour">Открыть купон</button></div>';
 out+='<div class="v5-metrics">'+metric('День',day.slice(-2)+' декабря')+metric('EV нашей модели',currency(q.ev))+metric('Brier',b.brier===null?'Н/Д':f(b.brier))+metric('Учтено вероятностей',b.n)+'</div>';
 out+='<div class="notice warn">Brier из клиентского журнала — предварительная метрика, НЕ независимая верификация. Для доказательства prospective нужны серверные снимки до kickoff и сверка исходов. Возвраты и половинные расчёты исключены. Маленькая выборка не показывает преимущества.</div>';
 out+='<div class="panel"><h3>Сценарии</h3><div class="v5-duel"><div><strong>CAP</strong><p>Оригинал купона</p><small>'+h(t.baseline?.label||'Нет прематч-снимка')+'</small></div><div><strong>SEFIROT</strong><p>'+h(t.verdict||'PASS')+'</p><small>Только проверенное EV</small></div><div><strong>PASS</strong><p>Контроль риска</p><small>Без дополнительной ставки</small></div></div></div>';
 out+='<details class="panel"><summary>Исходная дуэль V4 и сравнительная статистика</summary>'+(window.QuestExtra?.duelView()||'Данные недоступны')+'</details>';
 return out;
}
function hypothesisView(){
 const d=B.data(),counts={};for(const g of games()){const k=localDay(g);counts[k]=(counts[k]||0)+1;}
 const g={busy:{days:0,wins:0,pnl:0},quiet:{days:0,wins:0,pnl:0}},threshold=5;
 for(const [day,t] of Object.entries(d.tours||{})){
  if(t.state!=='closed')continue;
  const bucket=(counts[day]||0)>=threshold?g.busy:g.quiet;
  bucket.days++;if(t.mode!=='pass'&&E.active(t).length&&E.active(t).every(l=>l.status==='win'))bucket.wins++;
  const pnl=E.realized(t,d.settings);if(Number.isFinite(pnl))bucket.pnl+=pnl;
 }
 const enough=Math.min(g.busy.days,g.quiet.days)>=8;
 let out=heading('Лаборатория гипотез','Фиксированный тест: больше ли полных побед в вечера с пятью и более известными матчами? Порог нельзя менять под результаты.');
 out+='<section class="v5-arena"><article class="panel"><h3>Насыщенные вечера (≥5)</h3><p>Закрытых туров: <b>'+g.busy.days+'</b></p><p>Полных проходов: <b>'+g.busy.wins+'</b></p><p>Виртуальный P&L: '+currency(g.busy.pnl)+'</p></article><div class="v5-vs">VS</div><article class="panel"><h3>Спокойные (0–4)</h3><p>Закрытых туров: <b>'+g.quiet.days+'</b></p><p>Полных проходов: <b>'+g.quiet.wins+'</b></p><p>Виртуальный P&L: '+currency(g.quiet.pnl)+'</p></article></section>';
 out+='<div class="panel"><h3>'+(enough?'Предварительный объём достигнут — статистическая значимость не доказана':'Предварительный порог: 8 закрытых дней каждой группы пока не достигнут')+'</h3><p>«Интересность» здесь измеряется только количеством матчей с 21:00 до 23:00 в нашей неполной подборке из девяти турниров. Связь с проходимостью ещё не доказана.</p><p>Правила: прематч-класс дня определяется до игр; сравниваются только закрытые туры; PASS и возвраты учитываются отдельно. Корреляция не означает причинность. В сезоне максимум 31 день: для надёжного вывода нужно продолжение на следующие сезоны.</p></div>';
 return out;
}
function careerView(){
 const d=B.data(),x=E.analytics(d),c=V.storage(),snaps=Object.values(c).filter(v=>v.state==='sealed'),b=C.sealedBrier(d);
 const missions=[['Первая разведка',snaps.length>=1],['5 исследованных матчей',snaps.length>=5],['5 закрытых туров',x.closed.length>=5],['30 проверенных прогнозов',b.n>=30]];
 let out=heading('Карьера аналитика','Опыт за дисциплину и качество разбора, не за увеличение ставок и не за высокий КФ.');
 out+='<div class="v5-metrics">'+metric('XP',x.xp)+metric('Туры',x.closed.length+'/31')+metric('SEALED исследования',snaps.length)+metric('Brier N',b.n)+'</div><article class="panel"><h3>Испытания</h3>';
 for(const [name,done] of missions)out+='<div class="v5-achieve">'+(done?'✓':'○')+' '+h(name)+'</div>';
 out+='</article><div class="notice">Даже высокий уровень игрока не доказывает преимущество над линией. Без value — PASS.</div>';return out;
}
function maintenanceView(){
 const a=games(),now=Date.now(),stale=a.filter(g=>g.checked_at&&now-Date.parse(g.checked_at)>7*86400000);
 const unconfirmed=a.filter(g=>g.timing_status!=='confirmed');
 let out=heading('Контроль расписания','Проверка свежести нашей базы. Обновление каталога не равно повторной проверке официального сайта лиги.');
 out+='<div class="v5-metrics">'+metric('В каталоге',a.length)+metric('Устаревшие записи',stale.length)+metric('Требуют подтверждения',unconfirmed.length)+metric('Дней сезона',31)+'</div>';
 out+='<article class="panel"><h3>За 48 часов до начала</h3><p>Перепроверить kickoff, составы, травмы, линию и независимость ног. Источник старше 7 дней — предупредить о необходимости повторной проверки; нет модельной P — PASS.</p><button class="button secondary" data-v5-extra="reload">Обновить из нашей базы</button><button class="button secondary" data-route="fixtures">Открыть матчи</button><p class="muted">Полная сверка внешних сайтов требует отдельного процесса. Фоновая проверка не активирована.</p></article>';return out;
}
document.addEventListener('change',e=>{if(e.target?.id==='v5-duel-day'){V.setDay(e.target.value);}});
document.addEventListener('click',e=>{const t=e.target.closest('[data-v5-extra]');if(t?.dataset.v5Extra==='reload')window.QuestSchedule?.load();});
window.addEventListener('quest-fixtures-updated',()=>{if(/^#(maintenance|hypotheses|career|duel)(?:$|\?)/.test(window.location.hash))B.refresh();});
Object.assign(V,{duelView,hypothesisView,careerView,maintenanceView});
B.refresh();
})();