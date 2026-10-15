import assert from "node:assert/strict";

class Element {
  constructor(){this.children=[];this.textContent="";this.value="";this.handlers={};}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.textContent="";this.children=[...items];}
  addEventListener(event,handler){this.handlers[event]=handler;}
  allText(){return this.textContent+" "+this.children.map(c=>c.allText()).join(" ");}
}
const privateMarker="SYNTHETIC_PRIVATE_HOME";
const data={build:{version:"2.4.2"},sources:{API_FOOTBALL:{status:"NOT_VERIFIED"}},
  verified_market_views:[{source:"ORIGINAL_VERIFIED_DECISION_CARD",archive_only:true,
    fixture_id:"synthetic-1",match:{home:privateMarker,away:"B"},core_decision:"PASS",
    core_class:"D",data_origin:"SYNTHETIC",at:"2030-01-01",build_matches:true,
    markets:[{market:"1X2:HOME",model_probability:.4,ev:-.2,stress_class:"D"}],
    research_candidate:{market:"TOTAL:OVER:2.5",status:"RESEARCH_ONLY"}}],
  original_decisions:[{decision_id:"SYNTHETIC_PRIVATE_DECISION"}],
  unavailable_original_decisions:[{decision_id:"SYNTHETIC_PRIVATE_UNAVAILABLE",
    forecast_seal_id:"SYNTHETIC_PRIVATE_SEAL",status:"UNAVAILABLE",
    reason:"ARCHIVE_FIXTURE_ID_UNSUPPORTED"}],
  ledger_status:"VERIFIED_LOCAL_ORIGIN_NOT_ATTESTED",audit_events:3,readiness:[]};
const success=()=>({status:200,ok:true,json:async()=>({ok:true,data})});
let cases=0;
async function setup(){
  const nodes=new Map(["build","sources","fixtures","decisions","research","history",
    "error","connection","login","access","refresh","match","market"].map(k=>[k,new Element()]));
  globalThis.document={createElement:()=>new Element(),getElementById:k=>nodes.get(k)};
  await import(new URL("../web/operator/operator.mjs?session-case="+cases,import.meta.url));
  return nodes;
}
function deferred(){let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};}
const refresh=nodes=>nodes.get("refresh").handlers.click();
async function loaded(nodes){globalThis.fetch=async()=>success();await refresh(nodes);
  assert.match(nodes.get("decisions").allText(),/CORE PASS/);
  assert.match(nodes.get("decisions").allText(),new RegExp(privateMarker));}
function cleared(nodes){
  const text=["build","sources","fixtures","decisions","research","history"]
    .map(k=>nodes.get(k).allText()).join(" ");
  assert.doesNotMatch(text,/SYNTHETIC_PRIVATE|CORE PASS|RESEARCH_ONLY|0\.4/);
  assert.match(nodes.get("decisions").allText(),/Нет проверенных/);
  nodes.get("match").value=privateMarker;nodes.get("match").handlers.input();
  nodes.get("market").value="1X2";nodes.get("market").handlers.input();
  assert.doesNotMatch(nodes.get("decisions").allText(),new RegExp(privateMarker));
}
async function scenario(name,run){const nodes=await setup();await run(nodes);cases++;}

for(const status of [401,403,503])await scenario("HTTP "+status,async nodes=>{
  await loaded(nodes);globalThis.fetch=async()=>({status,ok:false});await refresh(nodes);cleared(nodes);
  assert.ok(nodes.get("error").textContent);});
await scenario("transport failure",async nodes=>{await loaded(nodes);
  globalThis.fetch=async()=>{throw Error("synthetic unavailable");};await refresh(nodes);cleared(nodes);});
await scenario("invalid JSON",async nodes=>{await loaded(nodes);
  globalThis.fetch=async()=>({status:200,ok:true,json:async()=>{throw SyntaxError("synthetic");}});
  await refresh(nodes);cleared(nodes);});
for(const packet of [{ok:false,data},{ok:true}])await scenario("invalid envelope",async nodes=>{
  await loaded(nodes);globalThis.fetch=async()=>({status:200,ok:true,json:async()=>packet});
  await refresh(nodes);cleared(nodes);});
await scenario("older success after current 401",async nodes=>{
  await loaded(nodes);const old=deferred();globalThis.fetch=()=>old.promise;const pending=refresh(nodes);
  globalThis.fetch=async()=>({status:401,ok:false});await refresh(nodes);cleared(nodes);
  old.resolve(success());await pending;cleared(nodes);});
await scenario("older JSON after current 401",async nodes=>{
  await loaded(nodes);const old=deferred(),started=deferred();
  globalThis.fetch=async()=>({status:200,ok:true,json:()=>{started.resolve();return old.promise;}});
  const pending=refresh(nodes);await started.promise;
  globalThis.fetch=async()=>({status:401,ok:false});await refresh(nodes);cleared(nodes);
  old.resolve({ok:true,data});await pending;cleared(nodes);});
await scenario("older 401 cannot hide newer authorized result",async nodes=>{
  const old=deferred();globalThis.fetch=()=>old.promise;const pending=refresh(nodes);
  await loaded(nodes);old.resolve({status:401,ok:false});await pending;
  assert.match(nodes.get("decisions").allText(),/CORE PASS/);assert.equal(nodes.get("error").textContent,"");});
await scenario("failed login clears data and invalidates pending read",async nodes=>{
  await loaded(nodes);const old=deferred();globalThis.fetch=()=>old.promise;const pending=refresh(nodes);
  nodes.get("access").value="SYNTHETIC_WRONG_TOKEN_ONLY";
  globalThis.fetch=async()=>({status:401,ok:false});await nodes.get("login").handlers.submit({preventDefault(){}});
  assert.equal(nodes.get("access").value,"");cleared(nodes);old.resolve(success());await pending;cleared(nodes);});
await scenario("authorized recovery after expiry",async nodes=>{
  await loaded(nodes);globalThis.fetch=async()=>({status:401,ok:false});await refresh(nodes);cleared(nodes);
  nodes.get("match").value="";nodes.get("market").value="";await loaded(nodes);
  assert.equal(nodes.get("error").textContent,"");});
assert.equal(cases,12);
console.log("OPERATOR_SESSION_CASES="+cases);
