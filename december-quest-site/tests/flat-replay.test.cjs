const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const test = require('node:test');

const html=readFileSync(join(__dirname,'../index.html'),'utf8');
const start=html.indexOf('(function (root, factory)');
const end=html.indexOf('</script>',start);
const testModule={exports:{}};
new Function('module',html.slice(start,end))(testModule);
const E=testModule.exports;

test('flat replay grades partial returns and excludes PASS, late and correlated records',()=>{
  const leg=(id,status,odds=2)=>({fixtureId:id,home:id+' A',away:id+' B',kickoff:'2026-12-08T20:00:00Z',status,odds,enabled:true});
  const tour=(d,legs)=>({date:'2026-12-0'+d,sealedAt:'2026-12-07T15:00:00Z',state:'closed',
    mode:legs.length===1?'single':'original',verdict:'играбельно',independenceReviewed:true,legs});
  const x=E.flatReplay({
    a:tour(1,[leg('a','win')]),
    b:tour(2,[leg('b','half-win'),leg('c','return')]),
    c:tour(3,[leg('d','half-loss'),leg('e','win'),leg('f','return')]),
    d:tour(4,[leg('g','lose')]),
    e:tour(5,[leg('h','lose')]),
    f:tour(6,[leg('i','win'),leg('i','return')]),
    g:{...tour(7,[leg('j','win')]),verdict:'пропуск'},
    h:{...tour(7,[leg('k','win')]),sealedAt:'2026-12-08T20:00:00Z'},
    i:{...tour(7,[leg('l','win'),leg('m','win')]),independenceReviewed:false},
    j:tour(7,[leg('n','win',1.20)])
  });
  assert.equal(x.n,5);
  assert.equal(x.bank,99.5);
  assert.equal(x.hit_rate,40);
  assert.equal(x.yield,-10);
  assert.equal(x.best_win_streak,2);
  assert.equal(x.worst_loss_streak,2);
  assert.equal(x.drawdown,200/101.5);
  assert.deepEqual(x.summary[2],{n:1,pnl:.5});
  assert.deepEqual(x.summary[3],{n:1,pnl:0});
  assert.equal(E.flatReplay({}).yield,null);
  assert.equal(E.payout({...tour(1,[leg('o','half-win'),leg('p','return')]),manualPayout:null},{stake:1000}),1500);
});
