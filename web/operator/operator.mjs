export const unavailable="UNAVAILABLE";
export function scalar(v){return typeof v==="number"&&Number.isFinite(v)?String(v):unavailable;}
export function view(data,matchFilter="",marketFilter=""){
  const match=matchFilter.toLowerCase(),market=marketFilter.toLowerCase();
  const originals=(data?.verified_market_views??[]).filter(r=>
    r.source==="ORIGINAL_VERIFIED_DECISION_CARD"&&r.archive_only===true&&["PASS","BET"].includes(r.core_decision));
  const records=originals.filter(r=>JSON.stringify([r.match,r.fixture_id]).toLowerCase().includes(match))
    .map(r=>({...r,markets:r.markets.filter(m=>String(m.market).toLowerCase().includes(market))}));
  return {build:data?.build??null,provenance:data?.runtime_provenance??null,sources:data?.sources??{},
    readiness:data?.readiness??[],records,research:records.filter(r=>r.research_candidate),
    audit:data?.ledger_status?.startsWith("VERIFIED")?data.audit_events:unavailable,
    originalDecisions:data?.original_decisions??[],
    unavailableOriginalDecisions:data?.unavailable_original_decisions??[],
    readOnly:true,monetaryPermission:false};
}
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function section(id,title){const e=document.getElementById(id);e.replaceChildren(node("h2",title));return e;}
function metric(label,value){const e=node("div",undefined,"metric");e.append(node("strong",label),node("span",value??unavailable));return e;}
function detail(label,value){const e=node("details");e.append(node("summary",label),node("pre",value===null||value===undefined?unavailable:JSON.stringify(value,null,2)));return e;}
export function render(data,matchFilter="",marketFilter=""){
  const v=view(data,matchFilter,marketFilter);
  let e=section("build","Сборка и CI");
  if(!v.build)e.append(node("p",unavailable));
  else {for(const k of ["version","code_hash","model_hash","policy_hash"])e.append(node("p",k+": "+(v.build[k]??unavailable),"hash"));
    e.append(node("p","Ветка: "+(v.provenance?.branch??unavailable)),node("p","HEAD: "+(v.provenance?.head_sha??unavailable),"hash"),
    node("p","CI: "+(v.provenance?.ci_status??"NOT_VERIFIED")));}
  e=section("sources","Источники");
  for(const [name,s] of Object.entries(v.sources)){
    const a=node("article");a.append(node("h3",name),node("span",s.status??"NOT_VERIFIED","badge"),
      node("p","Проверено: "+(s.checked_at??unavailable)),node("p","Квота: "+(s.quota_verified===true?JSON.stringify(s.quota):unavailable)));
    if(s.last_documented_status)a.append(node("p","Исторически: "+s.last_documented_status+" · "+s.last_documented_at));
    e.append(a);
  }
  e=section("fixtures","Готовность PREMATCH");
  if(!v.readiness.length)e.append(node("p","Нет исходных данных. Прогнозы не созданы."));
  for(const r of v.readiness){const a=node("article");a.append(node("h3",r.match.home+" — "+r.match.away),
    node("p",r.status),node("p",r.next_action),detail("Блокеры",r.markets));e.append(a);}
  e=section("decisions","Исходные решения");
  if(!v.records.length)e.append(node("p","Нет проверенных записей CORE."));
  if(v.unavailableOriginalDecisions.length)e.append(node("p",
    "Не все архивные решения можно отобразить. Оригинальные записи сохранены."));
  for(const r of v.records){const a=node("article");a.append(node("h3",r.match.home+" — "+r.match.away),
    node("span","CORE "+r.core_decision+" · "+r.core_class,"badge"),node("p",r.data_origin+" · "+r.at),
    node("p","Архив: свежая цена НЕ ПОДТВЕРЖДЕНА."),
    node("p",r.build_matches?"Исходная сборка совпадает.":"Сборка изменилась: только чтение исходного архива."));
    for(const m of r.markets){const b=node("article");b.append(node("h3",m.market));const grid=node("div",undefined,"metrics");
      grid.append(metric("P · модель (исходная)",scalar(m.model_probability)),metric("P · implied (исходная)",scalar(m.implied_probability)),
        metric("EV (исходный)",scalar(m.ev)),metric("Оценка / stress",m.stress_class));
      b.append(grid,detail("Tactical fit · исходный",m.tactical_fit),detail("Public trap · исходный",m.public_trap),
        detail("Death test · исходный",m.death_test),detail("Исходные блокеры",m.effective_blockers));a.append(b);}
    e.append(a);}
  for(const r of v.unavailableOriginalDecisions){const a=node("article");
    a.append(node("h3","Архивная запись недоступна"),
      node("p","Формат архивного ID не поддерживается. Решение не отображается."),
      detail("Ссылки на исходный архив",{decision_id:r.decision_id,forecast_seal_id:r.forecast_seal_id}));
    e.append(a);}
  e=section("research","Исследовательские варианты");
  if(!v.research.length)e.append(node("p",unavailable));
  for(const r of v.research){const a=node("article");a.append(node("span","RESEARCH_ONLY · не меняет CORE "+r.core_decision,"badge"),
    detail("Исходный research candidate",r.research_candidate));e.append(a);}
  e=section("history","Журнал");e.append(node("p","Audit events: "+v.audit),detail("Исходные ID и решения",v.originalDecisions));
}
if(typeof document!=="undefined"){
  let current=null,generation=0;const error=document.getElementById("error");
  function clear(message){current=null;render(null);error.textContent=message;
    document.getElementById("connection").textContent="Нет подтверждённого подключения. Данные недоступны.";}
  async function refresh(){const request=++generation;try{
      const r=await fetch("/api/operator",{credentials:"same-origin",cache:"no-store"});
      if(request!==generation)return;
      if(r.status===401){clear("Войдите для просмотра.");return;}
      if(!r.ok){clear(r.status===403?"Разрешён только просмотр.":"Данные недоступны.");return;}
      const packet=await r.json();if(request!==generation)return;
      if(packet?.ok!==true||!packet.data||typeof packet.data!=="object"||Array.isArray(packet.data))throw Error("OPERATOR_RESPONSE_INVALID");
      current=packet.data;error.textContent="";document.getElementById("connection").textContent="Частный read-only прототип. Cloud runtime не подключён.";
      render(current,document.getElementById("match").value,document.getElementById("market").value);
    }catch{if(request===generation)clear("Сервер не подключён. Показатели недоступны.");}}
  document.getElementById("login").addEventListener("submit",async e=>{e.preventDefault();const input=document.getElementById("access");const token=input.value;input.value="";
    const request=++generation;clear("");
    try{const r=await fetch("/session",{method:"POST",headers:{"Content-Type":"application/json"},
      credentials:"same-origin",body:JSON.stringify({token})});if(request!==generation)return;
      if(!r.ok){clear("Не удалось войти.");return;}await refresh();}
    catch{if(request===generation)clear("Сервер не подключён.");}});
  document.getElementById("refresh").addEventListener("click",refresh);
  for(const id of ["match","market"])document.getElementById(id).addEventListener("input",()=>{
    if(current)render(current,document.getElementById("match").value,document.getElementById("market").value);});
}
