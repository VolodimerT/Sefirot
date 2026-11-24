/* Read-only source audit. Supply the archived Football-Data inputs and calendar.json. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import Core from '../core.js';
import { execute } from '../run.js';
import { backupStatus, fetchResultBackup, resultKey } from '../result-backups.js';

const [directory,stamp]=process.argv.slice(2);
const cutoff=Date.parse(stamp);
if(!directory||!Number.isFinite(cutoff)||!stamp.endsWith('Z'))throw Error('Supply CSV directory and explicit UTC cutoff');
const read=name=>readFileSync(resolve(directory,name),'utf8');
const calendar=JSON.parse(read('calendar.json'));
const now=()=>cutoff;
const get=(code,season)=>fetchResultBackup(code,season,cutoff,fetch,now);
const compare=await Promise.all(Object.entries(Core.LEAGUE_FILES).flatMap(([competition,div])=>['2627','2526'].map(async season=>{
  const [backup,rows]=await Promise.all([get(competition,season),Core.resultsFromCsv(read(season+'-'+div+'.csv'),competition,cutoff)]);
  assert.equal(backup.ok,true,competition+' '+season+' '+backup.error);
  const index=new Map(rows.map(row=>[resultKey(row),row]));
  const matching=backup.rows.filter(row=>{
    const primary=index.get(resultKey(row));
    return primary&&primary.hg===row.hg&&primary.ag===row.ag;
  });
  const conflicts=backup.rows.filter(row=>index.has(resultKey(row))).length-matching.length;
  const status=backupStatus(backup,rows,cutoff);
  assert.equal(conflicts,0);
  const latest=backup.rows.map(row=>row.date).sort().at(-1);
  return {competition,season,source:backup.url,primary:rows.length,backup:backup.rows.length,matching,latest,status};
})));
async function stage(outage){
  let stored;
  const rest=async (path,options)=>{
    if(path==='rpc/dq_predictor_run_state')return {checked_at:stamp};
    if(path.startsWith('sefirot_december_quest_fixtures?'))return calendar;
    assert.equal(path,'rpc/dq_commit_predictor_run');
    stored=JSON.parse(options.body);
    return {saved:stored.p_forecasts.length};
  };
  const csv=async url=>{
    if(url.endsWith('/fixtures.csv'))return {text:read('weekly.csv'),publishedAt:cutoff-60_000};
    const [,season,div]=url.match(/(\d+)\/(\w+)\.csv$/);
    if(outage(season,div))throw Error('STAGED_PRIMARY_OUTAGE');
    return read(season+'-'+div+'.csv');
  };
  const run=await execute({rest,csv,backup:get,clock:now});
  return {run,forecasts:stored.p_forecasts};
}
const healthy=await stage(()=>false);
const archiveUnavailable=await stage(season=>season==='2526');
const currentUnavailable=await stage(season=>season==='2627');
const modeled=rows=>rows.filter(row=>row.markets.length);
assert.equal(healthy.forecasts.length,114);
assert.equal(modeled(healthy.forecasts).length,60);
assert.equal(healthy.run.fixtures_using_history_backup,0);
assert.equal(healthy.run.odds_eligible_fixtures,0);
assert.equal(modeled(archiveUnavailable.forecasts).length,60);
assert.equal(archiveUnavailable.run.fixtures_using_history_backup,60);
assert.equal(modeled(currentUnavailable.forecasts).length,3);
assert.equal(currentUnavailable.run.fixtures_using_history_backup,3);
for(const row of modeled(currentUnavailable.forecasts)){
  const original=healthy.forecasts.find(item=>item.fixture_key===row.fixture_key);
  assert.equal(row.competition,'BUNDES');
  assert.deepEqual(row.probabilities,original.probabilities);
}
for(const result of [healthy,archiveUnavailable,currentUnavailable]) {
  assert.ok(result.forecasts.every(row=>row.verdict==='пропуск'&&!row.evidence.quote_price_verified));
}
console.log(JSON.stringify({comparison:compare.map(({matching,...row})=>({...row,matching:matching.length})),
  healthy:healthy.run,archive_outage:archiveUnavailable.run,current_outage:currentUnavailable.run},null,2));
