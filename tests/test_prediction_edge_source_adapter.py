"""Fictional original-schema packets/SQLite: engineering checks, never real data."""
import copy
from contextlib import closing, redirect_stderr, redirect_stdout
from hashlib import sha256
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'src'))
from research.source_adapter_v3 import adapt_sources, ORIGIN
from research.prediction_edge_v3.models import research_hash
from scripts.prediction_edge_source_adapter import main
from sefirot.contracts import digest, time
from sefirot.forward import create_plan, capture_plan, settle_plan, _save
from sefirot.identity import code_hash, model_code_hash
from sefirot.probability import fit_calibrator
from sefirot.repository import Repository
from sefirot.service import Service
from sefirot.sports_archive import archive_packets
from test_operations_upgrade import NOW, packet, row, stamp, reseal


def scoped(rows, hours=0, params=None):
    p = packet(rows,hours)
    p['data']['parameters'] = dict(params if params is not None else {'league':9,'season':2030,'status':'FT'})
    p['receipt']['parameters'] = dict(p['data']['parameters'])
    return reseal(p)


class SourceAdapterTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.archive = self.root/'archive'; self.archive.mkdir()
        self.database = self.root/'forward.sqlite'

    def add(self,p,name=None):
        path = self.archive/(name or digest(p)+'.json')
        path.write_text(json.dumps(p,ensure_ascii=False,allow_nan=False),encoding='utf-8')
        return path

    def adapt(self,**changes):
        context = dict(archive=self.archive,cutoff=stamp(8),league_id=9,season=2030,profile='LOWER')
        context.update(changes)
        return adapt_sources(**context)

    def reason(self,report,code):
        self.assertIn(code,[r['status'] for r in report['fixture_reviews']])

    def denied(self,report):
        self.assertEqual(report['source_verification'],ORIGIN)
        self.assertEqual(report['training_rows'],[])
        self.assertEqual(report['externally_verified_matches'],0)
        self.assertFalse(report['training_allowed'])
        self.assertFalse(report['models_fitted'])
        self.assertEqual(report['model_decision'],'KEEP_SHADOW')
        self.assertFalse(report['monetary_permission'])
        self.assertFalse(report['execution_enabled'])
        self.assertEqual(report['network_requests'],0)
        self.assertEqual(report['hash'],digest({k:v for k,v in report.items() if k!='hash'}))

    def ledger(self,*,holdout=False,settled=True,reserved_history=False):
        target = scoped([row(100,status='NS',hours=3,score=(None,None))],params={'id':100})
        history = scoped([row(10+n,hours=-72-n) for n in range(8)],-1)
        with closing(Repository(str(self.database))) as repo:
            clock = [NOW]; service = Service(repo,clock=lambda:clock[0])
            if reserved_history: service.reserve(['api-football:fixture:10'],'HOLDOUT',stamp(-2))
            fit = None
            if holdout:
                records = [{'match_id':'fictional-calibration','market':'1X2:HOME','kind':'1X2',
                            'raw_win':.5,'outcome':'WIN','synthetic':False,
                            'received_at':stamp(-2),'competition_profile':'LOWER'}]
                fit = fit_calibrator(records,model_code_hash(),service.policy.fingerprint,stamp(-1))
                with repo.transaction():
                    repo.insert('calibrators',fit['hash'],fit,at=fit['fit_at'])
                    repo.record_log('calibrators',fit['hash'],fit['fit_at'],fit)
            plan = create_plan(service,target,{9:'LOWER'},source_reliability=.95,
                               role='HOLDOUT' if holdout else 'CALIBRATION',
                               calibrator_id=fit['hash'] if fit else None)
            archive_packets([target,history],self.archive,stamp())
            capture = capture_plan(service,plan['id'],self.archive)
            self.assertEqual(capture['counts'],{'SEALED_RESEARCH':1})
            if settled:
                clock[0] = time(stamp(6))
                final = scoped([row(100,hours=3,score=(2,0))],6,{'id':100})
                archive_packets([final],self.archive,stamp(6))
                settle_plan(service,plan['id'],final)
            self.assertTrue(repo.verify())
            original = repo.all('predictions')[0]
        return plan,original

    def snapshot(self):
        return {str(p.relative_to(self.root)):sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob('*') if p.is_file()}

    def test_consistent_packet_is_typed_but_not_externally_authenticated(self):
        p = scoped([row(10)]); self.add(p)
        report = self.adapt()
        self.assertEqual(report['structurally_valid_matches'],1)
        r = report['candidate_rows'][0]
        self.assertEqual((r['id'],r['home'],r['away']),
                         ('api-football:fixture:10','api-football:team:1','api-football:team:2'))
        self.assertEqual(r['receipt_sha'],digest(p['receipt']))
        self.assertEqual(r['finished_at'],p['receipt']['received_at'])
        self.assertIn('EXACT_WHISTLE_UNKNOWN',report['source_bindings'][0]['finished_at_semantics'])
        self.assertEqual(report['source_bindings'][0]['profile_verification'],'CALLER_OPERATOR_ASSERTION')
        self.denied(report)

    def test_original_forward_plan_capture_and_result_are_replayed_read_only(self):
        plan,prediction = self.ledger(); before = self.snapshot()
        identities = (code_hash(),model_code_hash(),research_hash())
        with (patch.object(Repository,'insert',side_effect=AssertionError('write')),
             patch.object(Repository,'log',side_effect=AssertionError('write')),
             patch('socket.socket',side_effect=AssertionError('network'))):
            report = self.adapt(database=self.database)
        self.assertEqual(report['ledger']['status'],'LOCAL_LEDGER_INTEGRITY_CHECKED')
        self.assertEqual((report['ledger']['plans'],report['ledger']['results'],report['ledger']['captures']),(1,1,1))
        self.assertEqual(report['structurally_valid_matches'],9)
        bridge = next(r for r in report['source_bindings'] if r['fixture_id']=='api-football:fixture:100')
        self.assertTrue(bridge['ledger_result_bound'])
        self.assertEqual(bridge['original_capture_id'],prediction['id'])
        self.assertEqual(bridge['profile_verification'],'ORIGINAL_PLAN_OPERATOR_ASSERTION')
        self.assertEqual(self.snapshot(),before)
        self.assertEqual((code_hash(),model_code_hash(),research_hash()),identities)
        with closing(Repository(str(self.database),read_only=True)) as repo:
            self.assertEqual(repo.get('jobs',plan['id']),plan)
            self.assertEqual(repo.get('predictions',prediction['id']),prediction)
        self.denied(report)

    def test_repeated_ft_receipt_does_not_refresh_first_knowledge(self):
        self.add(scoped([row(10)],0)); self.add(scoped([row(10)],1))
        report = self.adapt()
        self.assertEqual(report['structurally_valid_matches'],1)
        self.assertEqual(report['candidate_rows'][0]['received_at'],stamp())
        self.assertEqual(report['fixture_reviews'][0]['observations'],2)

    def test_team_alias_changes_use_exact_ids(self):
        first = scoped([row(10)],0); changed = scoped([row(10)],1)
        changed['data']['response'][0]['teams']['home']['name']='Team A renamed'; reseal(changed)
        self.add(first); self.add(changed)
        report = self.adapt()
        self.assertEqual(report['candidate_rows'][0]['home'],'api-football:team:1')
        self.assertEqual(report['source_bindings'][0]['names_observed']['home'],['Team A','Team A renamed'])

    def test_changed_team_id_with_same_name_is_rejected(self):
        self.add(scoped([row(10)],0))
        changed = scoped([row(10,home=3)],1)
        changed['data']['response'][0]['teams']['home']['name']='Team A'; self.add(reseal(changed))
        self.reason(self.adapt(),'FIXTURE_IDENTITY_OR_SEASON_CHANGED')

    def test_changed_kickoff_is_rejected(self):
        self.add(scoped([row(10)],0)); self.add(scoped([row(10,hours=-47)],1))
        self.reason(self.adapt(),'FIXTURE_IDENTITY_OR_SEASON_CHANGED')

    def test_changed_season_is_rejected(self):
        self.add(scoped([row(10)],0)); changed = row(10); changed['league']['season']=2029
        self.add(scoped([changed],1,{'league':9,'season':2029,'status':'FT'}))
        self.reason(self.adapt(),'FIXTURE_IDENTITY_OR_SEASON_CHANGED')

    def test_revised_score_is_rejected(self):
        self.add(scoped([row(10)],0)); self.add(scoped([row(10,score=(3,1))],1))
        self.reason(self.adapt(),'RESULT_REVISION_CONFLICT')

    def test_same_instant_conflict_is_not_ordered_by_packet_hash(self):
        self.add(scoped([row(10)],0))
        self.add(scoped([row(10,status='NS',score=(None,None))],0,{'id':10}))
        self.reason(self.adapt(),'SIMULTANEOUS_OBSERVATION_CONFLICT')

    def test_future_receipt_is_visible_but_cannot_supply_history(self):
        self.add(scoped([row(10)],2)); report = self.adapt(cutoff=stamp())
        self.assertEqual(report['candidate_rows'],[])
        self.reason(report,'RECEIPT_AFTER_CUTOFF')
        self.assertEqual(len(report['future_packet_exclusions']),1)

    def test_ft_before_ninety_minutes_is_rejected(self):
        self.add(scoped([row(10,hours=-.5)],0))
        self.reason(self.adapt(),'PREMATURE_FT_RECEIPT')

    def test_non_regulation_aet_result_is_not_used(self):
        self.add(scoped([row(10,status='AET')],params={'id':10}))
        self.reason(self.adapt(),'NOT_CURRENT_REGULATION_FT')

    def test_stale_history_is_explicit(self):
        self.add(scoped([row(10,hours=-24*731)]))
        self.reason(self.adapt(),'STALE_HISTORY')

    def test_wrong_requested_fixture_id_is_rejected(self):
        self.add(scoped([row(10)],params={'id':11}))
        self.reason(self.adapt(),'QUERY_RESPONSE_MISMATCH')

    def test_wrong_requested_league_is_rejected(self):
        self.add(scoped([row(10)],params={'league':10,'season':2030}))
        self.reason(self.adapt(),'QUERY_RESPONSE_MISMATCH')

    def test_wrong_requested_season_is_rejected(self):
        self.add(scoped([row(10)],params={'league':9,'season':2029}))
        self.reason(self.adapt(),'QUERY_RESPONSE_MISMATCH')

    def test_other_context_league_is_explicit(self):
        self.add(scoped([row(10,league=10)],params={'league':10,'season':2030}))
        self.reason(self.adapt(),'OTHER_LEAGUE')

    def test_other_context_season_is_explicit(self):
        changed = row(10); changed['league']['season']=2027
        self.add(scoped([changed],params={'league':9,'season':2027}))
        self.reason(self.adapt(),'OTHER_SEASON')

    def test_unscoped_final_history_is_rejected(self):
        self.add(scoped([row(10)],params={}))
        self.reason(self.adapt(),'HISTORY_QUERY_SCOPE_MISSING')

    def test_parameter_echo_mismatch_is_packet_blocker(self):
        p=scoped([row(10)]); p['data']['parameters']['season']='2029'; self.add(reseal(p))
        self.assertIn('QUERY_ECHO_MISMATCH',self.adapt()['blockers'])

    def test_string_parameter_echo_is_supported(self):
        p=scoped([row(10)]); p['data']['parameters']={k:str(v) for k,v in p['receipt']['parameters'].items()}
        self.add(reseal(p)); self.assertEqual(self.adapt()['structurally_valid_matches'],1)

    def test_date_filter_is_bound_to_utc_kickoff(self):
        self.add(scoped([row(10)],params={'id':10,'date':'2030-01-01'}))
        self.reason(self.adapt(),'QUERY_RESPONSE_MISMATCH')

    def test_unreplayable_selector_is_explicit(self):
        self.add(scoped([row(10)],params={'league':9,'season':2030,'last':10}))
        self.reason(self.adapt(),'QUERY_PARAMETER_SEMANTICS_UNSUPPORTED')

    def test_echo_alone_cannot_hide_wrong_timezone_offset(self):
        self.add(scoped([row(10)],params={'id':10,'timezone':'Europe/Kyiv'}))
        self.reason(self.adapt(),'QUERY_TIMEZONE_RESPONSE_MISMATCH')

    def test_valid_kyiv_query_uses_local_date_and_keeps_training_closed(self):
        item = row(10, hours=-10)  # UTC Dec 31; Kyiv Jan 1.
        item['fixture']['date'] = time(item['fixture']['date']).astimezone(ZoneInfo('Europe/Kyiv')).isoformat()
        item['fixture']['timezone'] = 'Europe/Kyiv'
        self.add(scoped([item], params={'id':10, 'date':'2030-01-01', 'timezone':'Europe/Kyiv'}))
        report = self.adapt()
        self.assertEqual(report['structurally_valid_matches'], 1)
        self.denied(report)

    def test_unknown_iana_query_zone_is_explicit(self):
        self.add(scoped([row(10)], params={'id':10, 'timezone':'Invalid/Zone'}))
        self.reason(self.adapt(), 'QUERY_TIMEZONE_UNSUPPORTED')

    def test_recovered_pattern_stays_rejected_even_if_rows_match_local_day(self):
        p = scoped([row(10)], params={'id':10, 'timezone':'Europe/Kyiv'})
        p['data']['parameters']['timezone'] = 'UTC'
        path = self.add(reseal(p)); before = path.read_bytes()
        report = self.adapt()
        self.assertIn('QUERY_ECHO_MISMATCH', report['blockers'])
        self.assertEqual(path.read_bytes(), before); self.denied(report)

    def test_missing_or_invalid_season_is_fixed_rejection(self):
        for value in (None,True,'2030',[]):
            with self.subTest(value=value):
                p=scoped([row(10)]); p['data']['response'][0]['league']['season']=value
                self.add(reseal(p))
                self.assertIn('SOURCE_SEASON_OR_KICKOFF_UNVERIFIABLE',self.adapt()['blockers'])

    def test_kickoff_timestamp_disagreement_is_rejected(self):
        p=scoped([row(10)]); p['data']['response'][0]['fixture']['timestamp']+=900
        self.add(reseal(p)); self.assertIn('ARCHIVE_SCHEMA_OR_INTEGRITY_FAILED',self.adapt()['blockers'])

    def test_payload_sha_tamper_is_detected(self):
        p=scoped([row(10)]); name=digest(p)+'.json'
        p['data']['response'][0]['score']['fulltime']['home']=4
        self.add(p,name); self.assertIn('ARCHIVE_SCHEMA_OR_INTEGRITY_FAILED',self.adapt()['blockers'])

    def test_rehashed_payload_with_old_archive_name_is_detected(self):
        p=scoped([row(10)]); name=digest(p)+'.json'
        p['data']['response'][0]['score']['fulltime']['home']=4
        self.add(reseal(p),name); self.assertIn('ARCHIVE_HASH_MISMATCH',self.adapt()['blockers'])

    def test_noncanonical_filename_and_corrupt_json_are_all_reported(self):
        self.add(scoped([row(10)]),'input.json')
        (self.archive/('a'*64+'.json')).write_text('{broken',encoding='utf-8')
        report=self.adapt(); self.assertEqual(len(report['packet_reviews']),2)
        self.assertIn('NONCANONICAL_ARCHIVE_FILENAME',report['blockers'])
        self.assertIn('ARCHIVE_SCHEMA_OR_INTEGRITY_FAILED',report['blockers'])

    def test_duplicate_rows_inside_packet_are_rejected(self):
        self.add(scoped([row(10),row(10)]))
        self.assertIn('ARCHIVE_SCHEMA_OR_INTEGRITY_FAILED',self.adapt()['blockers'])

    def test_unknown_provider_is_rejected(self):
        p=scoped([row(10)]); p['receipt']['provider']='UNDECLARED_SOURCE'
        self.add(p); self.assertIn('ARCHIVE_SCHEMA_OR_INTEGRITY_FAILED',self.adapt()['blockers'])

    def test_price_contamination_is_blocked_before_rows_are_emitted(self):
        p=scoped([row(10)]); p['data']['odds']={'home':2.1}; self.add(reseal(p))
        report=self.adapt(); self.assertIn('PRICE_CONTAMINATION',report['blockers'])
        self.assertEqual(report['candidate_rows'],[])

    def test_missing_archive_never_creates_directory(self):
        missing=self.root/'missing'; report=self.adapt(archive=missing)
        self.assertIn('ARCHIVE_MISSING',report['blockers']); self.assertFalse(missing.exists())

    def test_empty_archive_is_explicit(self):
        self.assertIn('ARCHIVE_EMPTY',self.adapt()['blockers'])

    def test_missing_database_never_creates_file(self):
        self.add(scoped([row(10)])); report=self.adapt(database=self.database)
        self.assertIn('LEDGER_MISSING',report['blockers']); self.assertFalse(self.database.exists())
        self.assertEqual(report['candidate_rows'],[])

    def test_corrupt_database_is_fixed_rejection_and_unchanged(self):
        self.database.write_bytes(b'not sqlite'); before=self.snapshot()
        report=self.adapt(database=self.database)
        self.assertEqual(report['ledger']['status'],'LEDGER_SCHEMA_OR_INTEGRITY_FAILED')
        self.assertEqual(self.snapshot(),before)

    def test_empty_valid_ledger_is_not_real_data(self):
        with closing(Repository(str(self.database))): pass
        report=self.adapt(database=self.database)
        self.assertIn('LEDGER_EMPTY',report['blockers']); self.denied(report)

    def test_live_wal_or_journal_requires_offline_snapshot(self):
        with closing(Repository(str(self.database))): pass
        for suffix in ('-wal','-shm','-journal'):
            with self.subTest(suffix=suffix):
                sidecar=Path(str(self.database)+suffix); sidecar.write_bytes(b'pending')
                before=self.snapshot(); report=self.adapt(database=self.database)
                self.assertIn('LEDGER_REQUIRES_OFFLINE_SNAPSHOT',report['blockers'])
                self.assertEqual(self.snapshot(),before); sidecar.unlink()

    def test_changed_ledger_payload_breaks_content_bound_audit(self):
        plan,_=self.ledger()
        with closing(sqlite3.connect(self.database)) as db:
            changed=copy.deepcopy(plan); changed['role']='HOLDOUT'
            db.execute('DROP TRIGGER jobs_no_update')
            db.execute('UPDATE jobs SET payload=? WHERE id=?',(json.dumps(changed),plan['id'])); db.commit()
        self.assertIn('LEDGER_INTEGRITY_FAILED',self.adapt(database=self.database)['blockers'])

    def test_column_timestamp_tamper_cannot_hide_future_payload(self):
        plan,_=self.ledger()
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('DROP TRIGGER jobs_no_update')
            db.execute('UPDATE jobs SET at=? WHERE id=?',(stamp(-1),plan['id'])); db.commit()
        self.assertIn('LEDGER_COLUMN_MISMATCH',self.adapt(database=self.database)['blockers'])

    def test_original_holdout_member_is_never_training_candidate(self):
        self.ledger(holdout=True); report=self.adapt(database=self.database)
        self.assertEqual(report['ledger']['status'],'LOCAL_LEDGER_INTEGRITY_CHECKED')
        self.reason(report,'HOLDOUT_NOT_TRAINABLE')
        self.assertNotIn('api-football:fixture:100',[r['id'] for r in report['candidate_rows']])
        self.denied(report)

    def test_reserved_holdout_history_is_rejected_even_outside_forward_plan(self):
        self.ledger(reserved_history=True); report=self.adapt(database=self.database)
        self.reason(report,'HOLDOUT_NOT_TRAINABLE')
        self.assertNotIn('api-football:fixture:10',[r['id'] for r in report['candidate_rows']])

    def test_profile_assertion_cannot_override_frozen_plan(self):
        self.ledger(); report=self.adapt(database=self.database,profile='MEN')
        self.reason(report,'PROFILE_LEDGER_MISMATCH')
        self.assertEqual(report['candidate_rows'],[])
        self.assertEqual(report['reason_counts']['PROFILE_LEDGER_MISMATCH'],9)

    def test_ledger_result_must_bind_first_ft_receipt(self):
        self.ledger(); self.add(scoped([row(100,hours=3,score=(2,0))],5,{'id':100}))
        self.reason(self.adapt(database=self.database),'RESULT_LEDGER_MISMATCH_OR_NOT_FIRST_RECEIPT')

    def test_locally_rehashed_capture_with_wrong_fixture_is_rejected(self):
        self.ledger()
        with closing(Repository(str(self.database))) as repo:
            service=Service(repo,clock=lambda:time(stamp(7)))
            capture=next(j for j in repo.all('jobs') if j['schema']=='api-forward-capture-v1')
            changed={k:v for k,v in capture.items() if k!='id'}
            changed['at']=stamp(7); changed['attempts'][0]['match_id']='api-football:fixture:101'
            _save(service,changed); self.assertTrue(repo.verify())
        self.assertIn('CAPTURE_FIXTURE_MISMATCH',self.adapt(database=self.database)['blockers'])

    def test_locally_bound_wrong_result_plan_is_rejected(self):
        self.ledger()
        with closing(Repository(str(self.database))) as repo:
            service=Service(repo,clock=lambda:time(stamp(7)))
            source=next(j for j in repo.all('jobs') if j['schema']=='api-forward-result-source-v1')
            changed={k:v for k,v in source.items() if k!='id'}; changed['at']=stamp(7); changed['plan_id']='unknown'
            _save(service,changed); self.assertTrue(repo.verify())
        self.assertIn('RESULT_PLAN_MISSING',self.adapt(database=self.database)['blockers'])

    def test_source_batch_checks_actual_raw_team_ids_despite_valid_local_hashes(self):
        self.ledger(); bad=scoped([row(100,home=3,hours=3,score=(2,0))],7,{'id':100}); self.add(bad)
        with closing(Repository(str(self.database))) as repo:
            service=Service(repo,clock=lambda:time(stamp(7)))
            source=next(j for j in repo.all('jobs') if j['schema']=='api-forward-result-source-v1')
            changed={k:v for k,v in source.items() if k!='id'}
            changed.update(at=stamp(7),packet_hash=digest(bad),receipt=bad['receipt'])
            for r in changed['api_results']:
                r.update(source='API_FOOTBALL_V3:'+digest(bad),finished_at=stamp(7),received_at=stamp(7))
            _save(service,changed); self.assertTrue(repo.verify())
        self.assertIn('RESULT_FIXTURE_MISMATCH',self.adapt(database=self.database)['blockers'])

    def test_missing_selection_packet_preserves_declared_missing_fixture(self):
        plan,_=self.ledger(); (self.archive/(plan['selection_packet_hash']+'.json')).unlink()
        report=self.adapt(database=self.database)
        self.assertIn('SELECTION_PACKET_MISSING_OR_MISMATCHED',report['blockers'])
        self.assertIn('api-football:fixture:100',report['ledger']['declared_fixture_ids'])
        self.assertEqual(report['candidate_rows'],[])

    def test_future_ledger_result_is_excluded_with_explicit_record_table(self):
        self.ledger(); report=self.adapt(database=self.database,cutoff=stamp(1))
        self.assertEqual(report['ledger']['status'],'LOCAL_LEDGER_INTEGRITY_CHECKED')
        self.assertEqual(report['ledger']['results'],0)
        self.assertIn('results',{r['table'] for r in report['ledger']['future_record_exclusions']})
        self.reason(report,'NOT_CURRENT_REGULATION_FT')

    def test_archive_change_during_ledger_read_invalidates_all_candidates(self):
        self.add(scoped([row(10)]))
        from research.source_adapter_v3 import _ledger
        def concurrent(*args,**kwargs):
            self.add(scoped([row(11)])); return _ledger(*args,**kwargs)
        with patch('research.source_adapter_v3._ledger',side_effect=concurrent): report=self.adapt()
        self.assertIn('ARCHIVE_CHANGED_DURING_READ',report['blockers'])
        self.assertEqual(report['candidate_rows'],[])

    def test_cli_no_inputs_is_honest_json_without_model_fit(self):
        output=io.StringIO()
        with redirect_stdout(output):
            result=main(['--cutoff','2020-01-01T00:00:00+00:00','--league-id','9','--season','2020','--profile','LOWER'])
        self.assertEqual(result,0); report=json.loads(output.getvalue())
        self.assertIn('ARCHIVE_NOT_SUPPLIED',report['blockers']); self.denied(report)

    def test_cli_future_cutoff_is_rejected_before_adapter(self):
        with (patch('scripts.prediction_edge_source_adapter.adapt_sources',side_effect=AssertionError('called')),
              redirect_stderr(io.StringIO())):
            with self.assertRaises(SystemExit) as error:
                main(['--cutoff','2199-01-01T00:00:00+00:00','--league-id','9','--season','2199','--profile','LOWER'])
        self.assertEqual(error.exception.code,2)
