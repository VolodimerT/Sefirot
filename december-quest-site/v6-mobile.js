/* Mobile navigation extension. No account access. */
(function(){
'use strict';
const navs=[
 {id:'hub',icon:'◈',label:'Штаб'},
 {id:'fixtures',icon:'▦',label:'Матчи'},
 {id:'scout',icon:'⌕',label:'AI Scout'},
 {id:'tour',icon:'◆',label:'Тур'}
];
const rest=[
 ['arena','⚔','Арена'],['radar','◎','Рынки'],['weak','◇','Слабая нога'],['duel','◈','Дуэль'],
 ['hypotheses','⌁','Гипотезы'],['calibration','≈','Калибровка'],['career','★','Карьера'],
 ['maintenance','◷','Контроль'],['sync','☁','Облако'],['imports','▤','Купоны'],
 ['analytics','↗','Итоги'],['rules','≡','Правила'],['lab','◉','Тесты']
];
const doc=document;
const quick=doc.createElement('nav');quick.className='v6-mobile-launcher';quick.setAttribute('aria-label','Быстрая навигация SEFIROT');
for(const x of navs){
 const b=doc.createElement('button');b.type='button';b.dataset.route=x.id;b.innerHTML='<span aria-hidden="true">'+x.icon+'</span><small>'+x.label+'</small>';
 quick.appendChild(b);
}
const more=doc.createElement('button');more.type='button';more.dataset.mobileMore='1';more.setAttribute('aria-expanded','false');more.setAttribute('aria-controls','v6-more-panel');
more.innerHTML='<span aria-hidden="true">☷</span><small>Ещё</small>';quick.appendChild(more);
const panel=doc.createElement('div');panel.className='v6-more-panel';panel.id='v6-more-panel';panel.hidden=true;
const heading=doc.createElement('h2');heading.textContent='Инструменты SEFIROT';panel.appendChild(heading);
const container=doc.createElement('div');container.className='v6-more-grid';
for(const [id,icon,label] of rest){
 const b=doc.createElement('button');b.type='button';b.dataset.route=id;
 b.innerHTML='<span aria-hidden="true">'+icon+'</span>'+label;
 container.appendChild(b);
}
panel.appendChild(container);
const badge=doc.createElement('div');badge.className='v6-offline';badge.hidden=true;badge.textContent='ВНЕ СЕТИ · используем локальные черновики, время матчей перепроверить';panel.appendChild(badge);
const install=doc.createElement('button');install.type='button';install.textContent='Установить на Android';install.className='button secondary';install.hidden=true;
panel.appendChild(install);
doc.body.appendChild(panel);doc.body.appendChild(quick);
let installEvent=null;
window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();installEvent=e;install.hidden=false;});
install.addEventListener('click',async()=>{if(!installEvent)return;const p=installEvent;installEvent=null;install.hidden=true;await p.prompt();});
function mark(){
 const route=(location.hash.slice(1).split('?')[0]||'hub');
 for(const el of quick.querySelectorAll('[data-route]'))el.classList.toggle('active',el.dataset.route===route);
 for(const el of panel.querySelectorAll('[data-route]'))el.classList.toggle('active',el.dataset.route===route);
 more.classList.toggle('active',rest.some(x=>x[0]===route));
 badge.hidden=navigator.onLine!==false;
}
function show(v){panel.hidden=!v;more.setAttribute('aria-expanded',String(v));}
more.addEventListener('click',()=>show(panel.hidden));
doc.addEventListener('click',e=>{
 if(e.target.closest('[data-route]')){show(false);mark();}
 else if(!panel.hidden&&!e.target.closest('.v6-more-panel,.v6-mobile-launcher'))show(false);
});
doc.addEventListener('keydown',e=>{if(e.key==='Escape')show(false);});
window.addEventListener('hashchange',()=>{show(false);mark();});
window.addEventListener('online',mark);window.addEventListener('offline',mark);
mark();
})();
