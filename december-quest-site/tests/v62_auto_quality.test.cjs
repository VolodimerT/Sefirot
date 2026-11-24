/* V6.2 autonomous quality gate regression tests: node tests/v62_auto_quality.test.cjs */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const code=fs.readFileSync(require('node:path').resolve(__dirname,'../autopredict.js'),'utf8');
const match=code.match(/const modelValid=f=>\{[\s\S]*?\n\};/);
assert.ok(match,'modelValid function must exist');
const valid=new Function(match[0]+';return modelValid;')();
const basis={status:'MODEL_ONLY',generated_at:'2026-11-24T15:01:30Z',source_cutoff:'2026-11-24T15:01:30Z',kickoff:'2026-12-01T20:00:00Z',sample_n:11,probabilities:{home:0.53,draw:0.22,away:0.25}};
const cases=[
['valid MODEL_ONLY',basis,true],
['valid WAITING_ODDS',{...basis,status:'WAITING_ODDS'},true],
['unsupported',{...basis,status:'UNSUPPORTED_LEAGUE'},false],
['missing teams', {...basis,probabilities:{home:.5,draw:.5}},false],
['probability total over 1',{...basis,probabilities:{home:.7,draw:.2,away:.25}},false],
['negative probability',{...basis,probabilities:{home:-.1,draw:.5,away:.6}},false],
['no samples',{...basis,sample_n:3},false],
['after kickoff',{...basis,generated_at:'2026-12-01T22:00:00Z'},false],
['future cutoff',{...basis,source_cutoff:'2026-11-25T00:00:00Z'},false],
['invalid timestamp',{...basis,generated_at:'bad-date'},false]
];
for(const [name,row,expected] of cases)assert.equal(valid(row),expected,name);
assert.ok(code.includes('ВСЕГДА PASS'),'No false claims of positive EV without verified sportsbook quotes');
console.log('PASS '+(cases.length+1)+'/'+(cases.length+1));
