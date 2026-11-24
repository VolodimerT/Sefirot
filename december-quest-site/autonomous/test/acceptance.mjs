import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { PGlite } from '@electric-sql/pglite';
import Core from '../core.js';
import { execute } from '../run.js';

export const tablePrefix = 'sefirot_december_quest_';
export const fixture = {
  fixture_key: 'QA-EPL-001', competition: 'EPL', home_team: 'Coventry', away_team: 'Ipswich',
  source_quality: 'official', timing_status: 'confirmed', source_url: 'https://example.invalid/calendar',
  checked_at: '2026-11-23T17:00:00Z', kickoff: '2026-12-01T20:00:00Z'
};
const delayed = { ...fixture, fixture_key:'QA-EPL-002', home_team:'Leeds', away_team:'Arsenal' };
const missing = { ...fixture, fixture_key:'QA-COPPA-001', home_team:'Genoa', away_team:'Inter',
  competition:'COPPA', checked_at:'2026-12-01T16:00:00Z' };
export const columns = 'Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HxG,AxG';
export const form = Array.from({ length: 12 }, (_, i) =>
  ['E0,' + String(11 + i).padStart(2,'0') + '/11/2026,19:00,Coventry,Arsenal,2,1,H,1.9,0.8',
    'E0,' + String(11 + i).padStart(2,'0') + '/11/2026,21:00,Leeds,Ipswich,1,1,D,1,1.2']).flat();
export const weekly = 'Div,Date,Time,HomeTeam,AwayTeam,B365H,B365D,B365A\n'
  + 'E0,01/12/2026,20:00,Coventry City,Ipswich Town,4.20,3.40,2.05\n'
  + 'E0,01/12/2026,19:45,Leeds,Arsenal,4,3.5,2\n';
const finish = time => 'E0,01/12/2026,' + time + ',Coventry,Ipswich,2,1,H,2.1,1.0';
const pathSuffix = path => path.split('?')[0];
export const freeze = text => text.replaceAll('statement_timestamp()', 'public.dq_test_clock()');

export async function runAcceptance() {
  const [schema, migration] = await Promise.all([
    readFile(new URL('./schema.sql', import.meta.url), 'utf8'),
    readFile(new URL('../persist.sql', import.meta.url), 'utf8')
  ]);
  const db = new PGlite();
  const rows = async (text, params) => JSON.parse(JSON.stringify((await db.query(text, params)).rows));
  const read = suffix => rows('select * from ' + tablePrefix + suffix + ' order by 1');
  let timestamp;
  const setTime = async value => {
    await db.query("select set_config('dq_test.clock',$1,false)", [value]);
    timestamp = Date.parse(value);
  };
  const clock = () => timestamp;
  const csv = async (url, resultTime = null) => {
    if (url.endsWith('/fixtures.csv')) return weekly;
    const complete = (url.includes('/2627/') ? form : form.map(row => row.replace('/2026,','/2025,')));
    return [columns, ...complete, ...(url.includes('/2627/') && resultTime ? [finish(resultTime)] : [])].join('\n');
  };
  const rest = async (path, options) => {
    const resource = pathSuffix(path);
    if (resource === tablePrefix + 'fixtures') {
      return rows('select * from ' + resource + ' order by kickoff,fixture_key');
    }
    if (resource === tablePrefix + 'auto_runs') {
      return rows('select * from ' + resource + ' order by started_at desc limit 1');
    }
    const params = JSON.parse(options.body);
    await db.exec('set role service_role');
    try {
      if (resource === 'rpc/dq_pending_predictor_snapshots') {
        return rows('select * from public.dq_pending_predictor_snapshots($1,$2)',
          [params.p_fixture_keys, params.p_model_version]);
      }
      assert.equal(resource,'rpc/dq_commit_predictor_run');
      return (await rows('select public.dq_commit_predictor_run($1,$2,$3,$4) as result',
        [params.p_run,params.p_forecasts,params.p_validation,params.p_settlements].map(value=>JSON.stringify(value))))[0].result;
    } finally {
      await db.exec('reset role');
    }
  };

  try {
    await db.exec("create function public.dq_test_clock() returns timestamptz language sql stable "
      + "as $$select current_setting('dq_test.clock')::timestamptz$$");
    await setTime('2026-12-01T17:00:00Z');
    await db.exec(freeze(schema));
    await db.exec(freeze(migration));
    await db.exec('alter table '+tablePrefix+'auto_snapshots enable row level security; '
      +'grant select on '+tablePrefix+'auto_snapshots to anon,authenticated; '
      +'create policy snapshots_read on '+tablePrefix+'auto_snapshots for select to anon,authenticated using (true)');
    for (const source of [fixture,delayed,missing]) {
      await db.query('insert into '+tablePrefix+'fixtures '
        +'(fixture_key,competition,home_team,away_team,kickoff,source_name,source_url,source_quality,timing_status,checked_at) '
        +'values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)',
        [source.fixture_key,source.competition,source.home_team,source.away_team,source.kickoff,
          'synthetic',source.source_url,source.source_quality,source.timing_status,source.checked_at]);
    }
    const first = await execute({ rest, csv, clock });
    assert.equal(first.saved, 3);
    assert.equal(first.modeled, 1);
    assert.equal(first.sealed, 2);
    assert.equal(first.settled, 0);
    const forecasts = await read('auto_forecasts');
    const conflict = forecasts.find(row=>row.fixture_key===delayed.fixture_key);
    assert.equal(conflict.risk_class,'RED');
    assert.deepEqual(conflict.probabilities,{});
    assert.equal(conflict.evidence.kickoff_gate,'KICKOFF_CONFLICT');
    const seals = await read('auto_snapshots');
    const locked = seals.find(row=>row.fixture_key===fixture.fixture_key);
    assert.equal(locked.evidence.kickoff_confirmation,'OFFICIAL_CALENDAR_AND_WEEKLY_CSV');
    assert.ok(locked.generated_at < locked.kickoff);
    assert.equal(locked.evidence.decision.verdict,'пропуск');
    assert.equal(locked.evidence.pass_reasons.includes('QUOTE_TIMESTAMP_UNVERIFIED'),true);
    assert.equal(locked.markets.find(row=>row.pick==='П1').ev,null);
    assert.ok(seals.some(row=>row.fixture_key===missing.fixture_key&&row.status==='UNSUPPORTED_LEAGUE'));

    assert.equal((await execute({rest,csv,clock})).skipped,'RUN_WITHIN_SIX_HOURS');
    for (const role of ['anon','authenticated','service_role']) {
      await db.exec('set role '+role);
      try {
        assert.equal((await read('auto_snapshots')).length,2);
        await assert.rejects(db.exec('delete from '+tablePrefix+'auto_snapshots'),/permission denied/);
        if (role !== 'service_role') {
          await assert.rejects(db.exec("select public.dq_commit_predictor_run('{}','[]','[]','[]')"),/permission denied/);
        }
      } finally { await db.exec('reset role'); }
    }
    await assert.rejects(db.exec("update "+tablePrefix+"auto_snapshots set status='SOURCE_ERROR'"),/PREMATCH_SEAL_IMMUTABLE/);

    await setTime('2026-12-02T02:00:00Z');
    const failure = await execute({ rest, csv:async()=>{ throw Error('synthetic timeout'); }, clock });
    assert.equal(failure.status,'SOURCE_ERROR');
    assert.equal(failure.settled,0);
    await setTime('2026-12-02T02:05:00Z');
    const wrongTime = await execute({rest, csv:url=>csv(url,'19:45'),clock});
    assert.equal(wrongTime.settled,0);
    await setTime('2026-12-02T08:06:00Z');
    const correct = await execute({rest,csv:url=>csv(url,'20:00'),clock});
    assert.equal(correct.status,'OK');
    assert.equal(correct.settled,1);
    const [result] = await read('auto_settlements');
    assert.equal(result.snapshot_id,locked.id);
    assert.equal(result.result,'H');
    assert.ok(Number(result.model_brier)>0&&Number(result.model_logloss)>0);
    assert.equal(result.details.markets.length,68);
    assert.ok(result.details.baseline.brier>0);
    assert.deepEqual(await read('auto_snapshots'),seals);
    await assert.rejects(db.query('insert into '+tablePrefix+'auto_snapshots '
      +'(fixture_key,kickoff,generated_at,model_version,status) values ($1,$2,$3,$4,$5)',
      [fixture.fixture_key,fixture.kickoff,locked.generated_at,Core.MODEL_VERSION,'MODEL_ONLY']),
    /FORECAST_CANNOT_BE_WRITTEN_AFTER_KICKOFF/);

    return { outcome:'PASS', source:'SYNTHETIC', model:Core.MODEL_VERSION,
      saved:first.saved, sealed:first.sealed, timed_conflict:'RED', same_slot_retry:'SKIPPED',
      source_failure:failure.status, mismatched_ft:wrongTime.settled, correct_ft:correct.settled,
      market_scores:result.details.markets.length, rls:'PASS', snapshots_immutable:'PASS' };
  } finally { await db.close(); }
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) {
  try { console.log(JSON.stringify(await runAcceptance())); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
