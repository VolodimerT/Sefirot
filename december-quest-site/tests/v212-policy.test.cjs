const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
const start = html.indexOf('(function (root, factory)');
const api={exports:{}};
new Function('module',html.slice(start,html.indexOf('</script>',start)))(api);
const E=api.exports, now=new Date('2026-12-01T17:00:00Z'), ko='2026-12-01T20:00:00Z';
const leg=i=>({...E.emptyLeg(),fixtureId:'fixture'+i,home:'home'+i,away:'away'+i,kickoff:ko,
  market:'Фолы',pick:'ТБ 20.5',odds:2.1,prob:60});
function trusted(l,i){
  return {fixture_key:l.fixtureId,kickoff:ko,source_cutoff:now.toISOString(),generated_at:now.toISOString(),
    sample_n:30,risk_class:'B',verdict:'играбельно',best_candidate:{
      market:l.market,pick:l.pick,odds:l.odds,probability:.6,ev:.26,value_verified:true,
      observed_at:now.toISOString(),quote_updated_at:'2026-12-01T16:59:00Z',quote_timestamp_verified:true,
      price_verified:true,sensitivity:{'-0.05':.155},death_test:'PASS_CONDITIONAL',
      settlement:{win:.6,loss:.4,push:0,half_win:0,half_loss:0},alternative:{market:'1X2',ev:.03}},
    evidence:{home_name:l.home,away_name:l.away,fixture_timing_status:'confirmed',kickoff_gate:'CONFIRMED',
      public_trap_gate:'VERIFIED',fit_gate:'VERIFIED',death_test_gate:'VERIFIED',lineups_gate:'CONFIRMED',
      alternative_market_gate:'VERIFIED',market_rationale:'Fouls supported over the reviewed 1X2 alternative.',
      latest_training_date:'2026-11-28',calibration_gate:'VERIFIED',selection_basis:'SPORTING_EDGE',
      independent_fixture_keys:['fixture'+(1-i)],pass_reasons:[]}};
}
function sample(){
  const t={...E.emptyTour('2026-12-01'),mode:'original',verdict:'играбельно',riskClass:'B',
    independenceReviewed:true,legs:[leg(0),leg(1)]};
  return {t,rows:t.legs.map(trusted)};
}
test.before(async()=>{globalThis.QuestPrematchReview=(await import('../autonomous/markets.js')).prematchReview;});
test('manual gate requires separate source evidence even when every editable field claims approval',()=>{
  const {t,rows}=sample();
  assert.deepEqual(E.validateSeal(t,now,rows),[]);
  assert.ok(E.validateSeal({...t,approved:true,evidence:rows},now,[]).length);
  for(const [key,bad] of Object.entries({fit_gate:'UNVERIFIED',public_trap_gate:true,death_test_gate:'PASS_CONDITIONAL',
    alternative_market_gate:null,market_rationale:' ',calibration_gate:'A',lineups_gate:'expected',
    fixture_timing_status:'estimated',kickoff_gate:'KICKOFF_CONFLICT',latest_training_date:'2026-12-02',
    independent_fixture_keys:['fixture0'],selection_basis:'ODDS_TARGET',pass_reasons:['NO_EDGE']})){
    for(const value of [undefined,bad]){
      const copy=structuredClone(rows);copy[0].evidence[key]=value;
      assert.ok(E.validateSeal(t,now,copy).length,key);
    }
  }
});
test('each price, line, time, confidence and class is bound to the source',()=>{
  const {t,rows}=sample();
  for(const [key,bad] of Object.entries({value_verified:'true',ev:0,odds:2.11,probability:.61,
    pick:'different',market:'ЖК',death_test:'FAIL_CONDITIONAL',sensitivity:{'-0.05':0},
    price_verified:1,quote_timestamp_verified:0,quote_updated_at:'2026-12-01T15:00:00Z',
    observed_at:'2026-12-01T17:01:00Z',alternative:{market:'Фолы',ev:.5}})){
    for(const value of [undefined,bad]){
      const copy=structuredClone(rows);copy[0].best_candidate[key]=value;
      assert.ok(E.validateSeal(t,now,copy).length,key);
    }
  }
  for(const change of [r=>r.fixture_key='unknown',r=>r.evidence.home_name='wrong',r=>r.sample_n=5,
    r=>r.kickoff=now.toISOString(),r=>r.generated_at='2026-12-01T17:02:00Z',
    r=>r.source_cutoff='2026-12-01T17:01:00Z',r=>r.verdict='пропуск']){
    const copy=structuredClone(rows);change(copy[0]);assert.ok(E.validateSeal(t,now,copy).length);
  }
  for(const label of ['A','C','D','RED'])assert.ok(E.validateSeal({...t,riskClass:label},now,rows).length);
  for(const r of rows)r.risk_class='A';
  assert.deepEqual(E.validateSeal({...t,riskClass:'A'},now,rows),[]);
  const review=r=>globalThis.QuestPrematchReview(r,now.getTime()).riskClass;
  assert.equal(review(rows[0]),'A');rows[0].sample_n=0;assert.equal(review(rows[0]),'C');
  rows[0].best_candidate.ev=0;assert.equal(review(rows[0]),'D');
  rows[0].risk_class='RED';assert.equal(review(rows[0]),'RED');
});
test('cards require independent referee evidence; express cardinality, duplicate, filler, PASS',()=>{
  const {t,rows}=sample(),l=t.legs[0],r=rows[0];
  l.market=r.best_candidate.market='ЖК';
  Object.assign(l,{referee:'test',ycGame:4,ycFoul:.2,lowCardRisk:true,rulesConfirmed:true,noCleanerMarket:true});
  assert.ok(E.validateSeal(t,now,rows).length);
  const fields={referee_gate:'VERIFIED',referee:'test',yc_game:4,yc_foul:.2,low_card_risk:true,rules_confirmed:true,no_cleaner_market:true};
  Object.assign(r.evidence,fields);assert.deepEqual(E.validateSeal(t,now,rows),[]);
  for(const key of Object.keys(fields)){
    const copy=structuredClone(rows);delete copy[0].evidence[key];assert.ok(E.validateSeal(t,now,copy).length,key);
  }
  for(const legs of [[l],[l,l],[...t.legs,l,l]])assert.ok(E.validateSeal({...t,legs},now,rows).length);
  assert.ok(E.validateSeal({...t,independenceReviewed:false},now,rows).length);
  const pass={...t,mode:'pass',verdict:'пропуск',riskClass:'C',decisionNote:'Missing evidence'};
  assert.deepEqual(E.validateSeal(pass,now,[]),[]);
  assert.ok(E.validateSeal({...pass,verdict:'играбельно'},now,[]).length);
});
test('three independently reviewed legs may pass and malformed imported legs fail closed',()=>{
  const {t}=sample();
  t.legs.push(leg(2));
  const rows=t.legs.map(trusted);
  for(const row of rows)row.evidence.independent_fixture_keys=rows.filter(other=>other!==row).map(other=>other.fixture_key);
  assert.deepEqual(E.validateSeal(t,now,rows),[]);
  for(const broken of [null,{...leg(1),pick:4}])assert.ok(E.validateSeal({...t,legs:[leg(0),broken]},now,rows).length);
});
