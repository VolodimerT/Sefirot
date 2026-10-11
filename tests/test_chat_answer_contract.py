"""Synthetic adversarial replies; original Service decisions remain authoritative."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from sefirot.contracts import digest
from sefirot.fixtures import example
from sefirot.repository import Repository
from sefirot.service import Service
from research.chat_answer_contract import AnswerError, build_answer, validate_answer, render_answer
from research.small_market_readiness import preview

NOW = datetime(2030, 1, 1, 12, tzinfo=timezone.utc)


class ChatAnswerContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'original.sqlite'
        repo = Repository(str(self.path))
        case = example(NOW, 'synthetic:contract:original')
        service = Service(repo, clock=lambda: NOW)
        self.prediction = service.capture(case['sports'], case['markets'])
        service.clock = lambda: NOW + timedelta(minutes=2)
        self.decision = service.decide(self.prediction['id'], case['quotes'], case['recheck'],
                                      {'bankroll': 1000., 'peak': 1000.}, case['decision_at'])
        self.assertEqual(self.decision['decision'], 'PASS')
        repo.close()
        self.before = self.path.read_bytes()
        self.repo = Repository(str(self.path), read_only=True)
        self.fixtures = [self.decision['match_id']]
        self.at = NOW + timedelta(minutes=3)
        self.answer = build_answer(self.fixtures[0], self.fixtures, at=self.at,
                                   repo=self.repo, decision_id=self.decision['id'])

    def tearDown(self):
        self.repo.close()
        self.assertEqual(self.path.read_bytes(), self.before)
        self.temp.cleanup()

    def check(self, answer=None, **kw):
        return validate_answer(answer or self.answer, expected_fixtures=self.fixtures,
                               at=self.at, repo=self.repo, **kw)

    def reject(self, change, code=None):
        answer = copy.deepcopy(self.answer)
        change(answer)
        with self.assertRaises(AnswerError) as caught: self.check(answer)
        if code: self.assertIn(code, str(caught.exception))

    def test_actual_original_pass_and_renderer(self):
        out = self.check()
        self.assertEqual(out['core_decision'], 'PASS')
        self.assertEqual(out['evidence_level'], 'CORE_PASS')
        text = render_answer(out)
        self.assertEqual(len(text.splitlines()), 7)
        self.assertIn('PASS', text)
        self.assertIn('НЕТ', text)
        self.assertNotIn('играем', text)
        self.assertIn('СИНТЕТИЧЕСКИЙ ТЕСТ',text)

    def test_pass_cannot_become_bet(self):
        self.reject(lambda a: a.update(core_decision='BET', evidence_level='CORE_BET'))

    def test_renderer_refuses_unverified_dict_and_result_is_immutable(self):
        with self.assertRaises(AnswerError): render_answer(self.answer)
        verified=self.check();copy=verified.to_dict();copy['core_decision']='BET'
        self.assertIn('SEFIROT: PASS',render_answer(verified))
        with self.assertRaises(AttributeError):verified.fake='BET'

    def test_raw_ev_cannot_override_pass(self):
        for field, value in [('raw_ev', .35), ('probability', .99), ('recommendation', 'BET')]:
            with self.subTest(field=field): self.reject(lambda a: a.update({field: value}))

    def test_monetary_permission_cannot_be_client_grant(self):
        self.reject(lambda a: a.update(monetary_permission=True))

    def test_fake_decision_id(self):
        self.reject(lambda a: a.update(decision_id='f' * 64))

    def test_forged_build_hashes(self):
        for key in ['model_hash', 'code_hash', 'policy_hash', 'forecast_seal_id']:
            with self.subTest(key=key): self.reject(lambda a: a.update({key: 'f' * 64}))

    def test_forged_version(self):
        self.reject(lambda a: a['model_build'].update(version='999.0'))

    def test_class_cannot_be_improved(self):
        self.reject(lambda a: a.update(core_class='A'))

    def test_original_blockers_cannot_be_removed(self):
        self.reject(lambda a: a.update(missing_data=[]))

    def test_tampered_record_and_ledger_rejected(self):
        self.repo.close()
        db=sqlite3.connect(self.path)
        try:
            db.execute('DROP TRIGGER decisions_no_update')
            d=copy.deepcopy(self.decision);d['decision']='BET'
            db.execute('UPDATE decisions SET payload=? WHERE id=?',(json.dumps(d),d['id']));db.commit()
        finally:db.close()
        self.repo=Repository(str(self.path),read_only=True)
        try:
            with self.assertRaises(AnswerError):self.check()
        finally:
            self.repo.close();self.path.write_bytes(self.before)
            self.repo=Repository(str(self.path),read_only=True)

    def test_sealed_result_requires_server_repository(self):
        with self.assertRaises(AnswerError):
            validate_answer(self.answer, expected_fixtures=self.fixtures, at=self.at)

    def test_screenshot_without_core_is_not_executed(self):
        a = build_answer(self.fixtures[0], self.fixtures, at=self.at)
        out = validate_answer(a, expected_fixtures=self.fixtures, at=self.at)
        self.assertEqual(out['runtime_status'], 'SEFIROT_NOT_EXECUTED')
        self.assertEqual(out['core_decision'], 'NO_MODEL_DECISION')
        self.assertIsNone(out['model_hash'])
        self.assertIn('НЕ ЗАПУЩЕН', render_answer(out))

    def test_fake_executed_core_without_ids(self):
        a = build_answer(self.fixtures[0], self.fixtures, at=self.at)
        a.update(runtime_status='ORIGINAL_CORE_RECORD_VERIFIED', core_decision='BET')
        with self.assertRaises(AnswerError): validate_answer(a, expected_fixtures=self.fixtures, at=self.at)

    def test_missing_identity_or_clock_rejected(self):
        for key in ['fixture_id', 'answered_at', 'requested_scope', 'runtime_status']:
            with self.subTest(key=key): self.reject(lambda a: a.pop(key))

    def test_naive_clock_rejected(self):
        self.reject(lambda a: a.update(answered_at='2030-01-01T12:03:00'))

    def test_future_answer_rejected(self):
        self.reject(lambda a: a.update(answered_at=(self.at + timedelta(seconds=1)).isoformat()))

    def test_stale_current_answer_rejected(self):
        self.reject(lambda a: a.update(answered_at=(self.at - timedelta(seconds=121)).isoformat()))

    def test_fixture_and_original_scope_are_bound(self):
        self.reject(lambda a: a.update(fixture_id='synthetic:other'))
        self.reject(lambda a: a.update(requested_scope=['synthetic:other']))

    def test_duplicate_scope_rejected(self):
        self.reject(lambda a: a.update(requested_scope=self.fixtures * 2))

    def test_unknown_source_cannot_claim_prematch(self):
        self.reject(lambda a: a.update(mode='PREMATCH'))

    def test_archived_phase_requires_operator_archive_mode(self):
        a = build_answer(self.fixtures[0], self.fixtures, at=self.at, repo=self.repo,
                         decision_id=self.decision['id'], archive=True)
        with self.assertRaises(AnswerError): self.check(a)
        self.assertEqual(self.check(a, archive=True)['mode'], 'PREMATCH')

    def test_observation_after_receipt_rejected(self):
        self.reject(lambda a: a.update(observed_at=self.at.isoformat(),
                    received_at=(self.at - timedelta(seconds=1)).isoformat()))

    def test_fake_priced_count_rejected(self):
        self.reject(lambda a: a.update(priced_market_count=1))

    def test_zero_alternative_blocker_cannot_be_hidden(self):
        self.reject(lambda a: a['missing_data'].remove('NO_VERIFIED_ALTERNATIVE'))

    def test_invalid_audit_calendar_day_rejected(self):
        self.reject(lambda a: a.update(audit_period='2026-02-30'))

    def test_truths_not_equivalent(self):
        for level in ['CORE_BET', 'BOOKMAKER_QUOTE_OBSERVED', 'REAL_TICKET_SETTLED', 'RESEARCH_ONLY']:
            with self.subTest(level=level): self.reject(lambda a: a.update(evidence_level=level))

    def alternative(self, odds=2.):
        return {'fixture_id': self.fixtures[0], 'market_key': 'TOTAL:OVER:2.5',
                'bookmaker': 'SYNTHETIC_TEST_ONLY', 'period': 'REGULATION_90',
                'line_id': 'synthetic-line', 'decimal_odds': odds,
                'observed_at': self.at.isoformat(), 'received_at': self.at.isoformat(),
                'source_receipt_hash': 'a' * 64, 'evidence_level': 'RESEARCH_ONLY',
                'monetary_permission': False}

    def test_floor_199_rejected_and_200_needs_real_attestation(self):
        for odds in [1.99, 2., 2.01]:
            with self.subTest(odds=odds):
                self.reject(lambda a: a.update(alternatives_ge_2=[self.alternative(odds)]))

    def test_foreign_match_alternative_not_substituted(self):
        alt = self.alternative(); alt['fixture_id'] = 'synthetic:foreign'
        self.reject(lambda a: a.update(alternatives_ge_2=[alt]))

    def test_more_than_three_and_duplicate_alternatives_rejected(self):
        self.reject(lambda a: a.update(alternatives_ge_2=[self.alternative()] * 4))
        self.reject(lambda a: a.update(alternatives_ge_2=[self.alternative()] * 2))

    def test_nan_and_bool_odds_rejected(self):
        for odds in [float('nan'), True, 0]:
            with self.subTest(odds=odds): self.reject(lambda a: a.update(alternatives_ge_2=[self.alternative(odds)]))

    def test_three_chat_requests_keep_same_pass_snapshot(self):
        # Simulates JSON pipelines, not three actually connected GPT chats.
        for request_label in ['как Ярый', 'коэффициент 2.5', 'я сыграл']:
            with self.subTest(request=request_label):
                a = build_answer(self.fixtures[0], self.fixtures, at=self.at,
                                 repo=self.repo, decision_id=self.decision['id'])
                self.assertEqual(a, self.answer)

    def test_live_stale_score_3046_conflict_cannot_get_bet(self):
        a = copy.deepcopy(self.answer)
        a['live_state'] = {'fixture_id': self.fixtures[0], 'period': '1H', 'minute': 13,
                          'home_score': 0, 'away_score': 0, 'red_home': 0, 'red_away': 0,
                          'observed_at': self.at.isoformat(), 'quote_home_score': 1,
                          'quote_away_score': 0, 'quote_period': '1H', 'quote_minute': 13,
                          'quote_observed_at': self.at.isoformat()}
        with self.assertRaises(AnswerError): self.check(a)
        a['source_conflicts'] = ['LIVE_STATE_CONFLICT']
        a['missing_data'] += ['LIVE_STATE_CONFLICT', 'LIVE_MODEL_UNVALIDATED']
        out = self.check(a)
        self.assertEqual(out['mode'], 'HOLD'); self.assertFalse(out['monetary_permission'])
        self.assertIn('НЕ ПОДТВЕРЖДЁН', render_answer(out))

    def test_live_unvalidated_even_if_score_matches(self):
        a = copy.deepcopy(self.answer)
        a['mode'] = 'LIVE_RESEARCH'
        with self.assertRaises(AnswerError): self.check(a)

    def test_small_market_qc_blockers_are_required_and_preserved(self):
        a=copy.deepcopy(self.answer)
        counts={k:None for k in ('shots','sot','corners_ft','corners_1h','fouls_committed','yellow_cards','red_cards','booking_points')}
        counts.update(shots=4,sot=5)
        data={'metric':'SOT','period':'FT','counts':counts}
        a['research_checks']=[data]
        with self.assertRaises(AnswerError):self.check(a)
        a['missing_data']=sorted(set(a['missing_data'])|set(preview(data)['blockers']))
        out=self.check(a)
        self.assertIn('SOT_EXCEEDS_SHOTS',out['missing_data'])
        self.assertEqual(out['core_decision'],'PASS')

    def test_ticket_does_not_become_model(self):
        self.reject(lambda a: a.update(evidence_level='REAL_TICKET_SETTLED',
                   ticket_record={'source_class':'OUR_PARIK24_TICKET','ticket_id':'3045',
                                  'status':'CASHOUT','verification':'USER_REPORTED_NOT_ATTESTED'}))

    def test_stake_proposal_cannot_be_our_ticket(self):
        self.reject(lambda a: a.update(ticket_record={'source_class':'EXTERNAL_STAKE_YARYI_PROPOSAL',
                   'ticket_id':'3045','status':'WON','verification':'USER_REPORTED_NOT_ATTESTED'}))

    def test_cli_missing_db_does_not_create_it(self):
        answer = build_answer(self.fixtures[0], self.fixtures, at=self.at)
        f = Path(self.temp.name) / 'answer.json'; f.write_text(json.dumps(answer))
        missing = Path(self.temp.name) / 'missing.sqlite'
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/verify_chat_answer.py'),
                    '--answer', str(f), '--fixture', self.fixtures[0], '--db', str(missing),
                    '--at', self.at.isoformat()], capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 2)
        self.assertFalse(missing.exists())

    def test_cli_utf8_and_duplicate_json_rejected(self):
        f = Path(self.temp.name) / 'answer.json'; f.write_text(json.dumps(self.answer), encoding='utf-8')
        cmd = [sys.executable, str(ROOT / 'scripts/verify_chat_answer.py'), '--answer', str(f),
               '--fixture', self.fixtures[0], '--db', str(self.path), '--at', self.at.isoformat()]
        result = subprocess.run(cmd, capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PASS', json.loads(result.stdout)['summary'])
        f.write_text('{"fixture_id":"a","fixture_id":"b"}', encoding='utf-8')
        self.assertEqual(subprocess.run(cmd, capture_output=True, encoding='utf-8').returncode, 2)

    def test_cli_bounded_input_and_malformed_db_fail_closed(self):
        f=Path(self.temp.name)/'bounded.json'
        cmd=[sys.executable,str(ROOT/'scripts/verify_chat_answer.py'),'--answer',str(f),
             '--fixture',self.fixtures[0],'--at',self.at.isoformat()]
        for raw in ['['*2000+'0'+']'*2000, ' '*65537]:
            with self.subTest(size=len(raw)):
                f.write_text(raw,encoding='utf-8')
                result=subprocess.run(cmd,capture_output=True,encoding='utf-8')
                self.assertEqual(result.returncode,2)
                self.assertFalse(json.loads(result.stdout)['valid'])
        bad=Path(self.temp.name)/'not-sqlite';bad.write_bytes(b'not a database')
        f.write_text(json.dumps(self.answer),encoding='utf-8')
        result=subprocess.run(cmd+['--db',str(bad)],capture_output=True,encoding='utf-8')
        self.assertEqual(result.returncode,2)
        self.assertFalse(json.loads(result.stdout)['valid'])
        self.assertEqual(bad.read_bytes(),b'not a database')


class SmallMarketReadinessTests(unittest.TestCase):
    def data(self, metric='CORNERS'):
        return {'metric':metric,'period':'FT','counts':{'shots':None,'sot':None,
            'corners_ft':None,'corners_1h':None,'fouls_committed':None,
            'yellow_cards':None,'red_cards':None,'booking_points':None}}

    def test_missing_is_not_zero(self):
        a=self.data(); missing=preview(a);a['counts']['corners_ft']=0
        zero=preview(a);self.assertNotEqual(missing['missing_counts'],zero['missing_counts'])
        self.assertFalse(zero['fit_allowed']);self.assertIsNone(zero['probability'])

    def test_sot_larger_than_shots_quarantined(self):
        a=self.data('SOT');a['counts'].update(shots=4,sot=5)
        self.assertEqual(preview(a)['status'],'QUARANTINED')

    def test_half_corners_larger_than_ft_quarantined(self):
        a=self.data();a['counts'].update(corners_ft=4,corners_1h=5)
        self.assertEqual(preview(a)['status'],'QUARANTINED')

    def test_cards_without_referee_and_rules_have_no_probability(self):
        for metric in ['YELLOW_CARDS','RED_CARDS','BOOKING_POINTS']:
            with self.subTest(metric=metric):
                r=preview(self.data(metric));self.assertIn('REFEREE_NOT_ATTESTED',r['blockers'])
                self.assertIn('SETTLEMENT_NOT_ATTESTED',r['blockers']);self.assertIsNone(r['ev'])

    def test_fouls_cannot_be_cards_proxy(self):
        a=self.data('YELLOW_CARDS');a['counts']['fouls_committed']=30
        r=preview(a);self.assertIn('yellow_cards',r['missing_counts'])

    def test_goals_lambda_and_fake_full_league_claim_rejected(self):
        for field,value in [('goal_lambda',2.),('full_league_verified',True)]:
            with self.subTest(field=field):
                a=self.data();a[field]=value
                with self.assertRaises(ValueError):preview(a)

    def test_bool_negative_or_float_counts_rejected(self):
        for value in [True,-1,1.5]:
            with self.subTest(value=value):
                a=self.data();a['counts']['corners_ft']=value
                with self.assertRaises(ValueError):preview(a)

    def test_every_supported_period_is_unfit_not_green(self):
        for period in ['FT','1H','2H']:
            a=self.data();a['period']=period
            self.assertEqual(preview(a)['status'],'INSUFFICIENT_REAL_DATA')


if __name__ == '__main__': unittest.main()
