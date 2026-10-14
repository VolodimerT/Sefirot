import assert from "node:assert/strict";
import {view,render,scalar} from "../web/operator/operator.mjs";
class Element{constructor(tag="section"){this.tag=tag;this.children=[];this.textContent="";}
  append(...items){this.children.push(...items);}replaceChildren(...items){this.children=[...items];}
  allText(){return this.textContent+" "+this.children.map(c=>c.allText()).join(" ");}}
const sections=new Map(["build","sources","fixtures","decisions","research","history"].map(k=>[k,new Element()]));
globalThis.document={createElement:t=>new Element(t),getElementById:k=>sections.get(k)};
render(null);assert.match(sections.get("decisions").allText(),/Нет проверенных/);
const row={source:"ORIGINAL_VERIFIED_DECISION_CARD",archive_only:true,fixture_id:"synthetic-1",
  match:{home:"A",away:"B"},core_decision:"PASS",core_class:"D",data_origin:"SYNTHETIC",at:"2030-01-01",
  build_matches:true,markets:[{market:"1X2:HOME",model_probability:.4,implied_probability:.5,ev:-.2,
    stress_class:"D",tactical_fit:null,death_test:null,public_trap:null,effective_blockers:["PRICE_STALE"]}],
  research_candidate:{market:"TOTAL:OVER:2.5",ev:.3,status:"RESEARCH_ONLY"}};
const data={build:{version:"2.4.2"},sources:{API_FOOTBALL:{status:"BLOCKED",checked_at:"2030-01-01",
  quota:null,quota_verified:false}},verified_market_views:[row],original_decisions:[{core_decision:"PASS"}],
  ledger_status:"VERIFIED_LOCAL_ORIGIN_NOT_ATTESTED",audit_events:3,readiness:[]};
render(data);assert.match(sections.get("sources").allText(),/BLOCKED/);
assert.match(sections.get("decisions").allText(),/CORE PASS/);
assert.match(sections.get("research").allText(),/RESEARCH_ONLY/);
assert.equal(view(data,"A","1X2").records[0].markets.length,1);
assert.equal(view(data,"missing").records.length,0);
const changed=structuredClone(data);changed.verified_market_views[0].build_matches=false;
render(changed);assert.match(sections.get("decisions").allText(),/Сборка изменилась/);
assert.equal(scalar(null),"UNAVAILABLE");assert.equal(scalar(0),"0");assert.equal(scalar(NaN),"UNAVAILABLE");
assert.equal(view(data).records[0].core_decision,"PASS");
assert.equal(view(data).monetaryPermission,false);
console.log("OPERATOR_FRONTEND_CASES=8");
