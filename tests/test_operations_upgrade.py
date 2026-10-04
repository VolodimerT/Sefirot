"""Synthetic boundary cases for observed archives, session views and ticket audits."""
import copy
from contextlib import closing, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.cli import main
from sefirot.contracts import Policy, digest
from sefirot.engine import decide
from sefirot.fixtures import example
from sefirot.repository import Repository
from sefirot.service import Service
from sefirot.session import inspect_session
from sefirot.sports_archive import archive_packets, export_sports, read_archive, validate_packet
from sefirot.ticket_audit import audit_tickets
from test_audit_upgrade import controlled

NOW = datetime(2030, 1, 1, 9, tzinfo=timezone.utc)


def stamp(hours=0):
    return (NOW + timedelta(hours=hours)).isoformat()


def row(fid, *, home=1, away=2, league=9, status='FT', hours=-48, score=(2, 1)):
    names = {1: 'Team A', 2: 'Team B'}
    return {'fixture': {'id': fid, 'date': stamp(hours),
                        'timestamp': int((NOW + timedelta(hours=hours)).timestamp()), 'status': {'short': status}},
            'league': {'id': league, 'season': 2030},
            'teams': {side: {'id': tid, 'name': names.get(tid, 'Team ' + str(tid))}
                      for side, tid in (('home', home), ('away', away))},
            'score': {'fulltime': {'home': score[0], 'away': score[1]}}}


def packet(rows, hours=0):
    data = {'get': 'fixtures', 'parameters': {}, 'errors': [], 'results': len(rows),
            'paging': {'current': 1, 'total': 1}, 'response': rows}
    return {'data': data, 'receipt': {'provider_host': 'v3.football.api-sports.io', 'endpoint': '/fixtures',
            'parameters': {}, 'request_started_at': stamp(hours - .001), 'received_at': stamp(hours),
            'payload_hash': digest(data), 'http_status': 200, 'provider': 'API_FOOTBALL_V3', 'sports_only': True}}


def reseal(p):
    p['receipt']['payload_hash'] = digest(p['data'])
    return p


class SportsArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'archive'
        self.target = packet([row(100, status='NS', hours=3)])

    def exported(self, packets, at=None, reliability=.95):
        archive_packets([self.target, *packets], self.root, stamp(10))
        return export_sports(self.root, 100, at or stamp(), profile='LOWER', source_reliability=reliability)

    def test_repeated_snapshots_keep_one_game_and_first_actual_ft_receipt(self):
        first = packet([row(10)], -24)
        later = packet([row(10)], -1)
        exported = self.exported([first, later])
        self.assertEqual(len(exported['sports']['history']), 1)
        self.assertEqual(exported['sports']['history'][0]['received_at'], stamp(-24))
        self.assertEqual(exported['sports']['history'][0]['finished_at'], stamp(-24))
        self.assertEqual(exported['coverage']['teams']['home']['eligible_games'], 1)
        self.assertEqual(exported['coverage']['teams']['home']['games_needed'], 7)
        self.assertFalse(exported['coverage']['monetary_permission'])

    def test_archive_import_is_idempotent_without_rewriting_observation(self):
        one = archive_packets([self.target], self.root, stamp())
        path = next(self.root.glob('*.json')); before = (path.read_bytes(), path.stat().st_mtime_ns)
        two = archive_packets([self.target, self.target], self.root, stamp())
        self.assertEqual(one['added_packets'], 1); self.assertEqual(two['added_packets'], 0)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_invalid_batch_is_rejected_before_any_packet_write(self):
        bad = copy.deepcopy(self.target); bad['data']['results'] = 7
        with self.assertRaises(ValueError):archive_packets([self.target, bad], self.root, stamp())
        self.assertFalse(self.root.exists())

    def test_tampered_packet_detected_even_if_inner_payload_is_rehashed(self):
        archive_packets([self.target], self.root, stamp())
        path = next(self.root.glob('*.json'))
        changed = copy.deepcopy(self.target); changed['data']['response'][0]['league']['season'] = 2029
        path.write_text(json.dumps(reseal(changed)))
        with self.assertRaisesRegex(ValueError, 'archive packet integrity'):read_archive(self.root)

    def test_provider_error_count_pagination_duplicate_and_credentials_fail_closed(self):
        for reason in ('errors', 'count', 'paging', 'duplicate', 'credential', 'bool_paging', 'unknown_host'):
            p = copy.deepcopy(self.target)
            if reason == 'errors':p['data']['errors'] = {'plan': 'not allowed'}
            if reason == 'count':p['data']['results'] = 0
            if reason == 'paging':p['data']['paging']['total'] = 2
            if reason == 'duplicate':p['data']['response'] *= 2;p['data']['results'] = 2
            if reason == 'credential':p['receipt']['parameters']['apiKey'] = 'private'
            if reason == 'bool_paging':p['data']['paging']['current'] = True
            if reason == 'unknown_host':p['receipt']['provider_host'] = 'untrusted.example'
            with self.subTest(reason=reason), self.assertRaises(ValueError):validate_packet(reseal(p), stamp())

    def test_future_observation_is_not_imported_or_seen_at_an_earlier_cutoff(self):
        future = packet([row(10)], 1)
        with self.assertRaisesRegex(ValueError, 'future'):archive_packets([future], self.root, stamp())
        exported = self.exported([future])
        self.assertEqual(exported['sports']['history'], [])
        self.assertEqual(exported['receipt']['future_packets_excluded'], 1)

    def test_ft_score_correction_is_quarantined_instead_of_price_shopped(self):
        first = packet([row(10)], -24); correction = packet([row(10, score=(0, 0))], -1)
        exported = self.exported([first, correction])
        self.assertEqual(exported['sports']['history'], [])
        self.assertEqual(exported['coverage']['exclusion_reasons'], {'RESULT_REVISION_CONFLICT': 1})

    def test_withdrawn_result_aet_and_other_competitions_do_not_fill_history(self):
        exported = self.exported([packet([row(10)], -24), packet([
            row(10, status='CANC'), row(11, status='AET'), row(12, league=10)], -1)])
        self.assertEqual(exported['sports']['history'], [])
        self.assertEqual(exported['coverage']['eligible_history_rows'], 0)

    def test_team_alias_join_uses_exact_api_id_and_name_collision_is_rejected(self):
        renamed = row(10);renamed['teams']['home']['name'] = 'Old A Name'
        collision = row(11, home=99);collision['teams']['home']['name'] = 'Team A'
        exported = self.exported([packet([renamed, collision], -1)])
        self.assertEqual(exported['sports']['history'][0]['home'], 'Team A')
        self.assertEqual(exported['coverage']['teams']['home']['eligible_games'], 1)
        self.assertEqual(exported['coverage']['exclusion_reasons'], {'TEAM_NAME_COLLISION': 1})

    def test_fixture_identity_and_simultaneous_history_conflicts_are_quarantined(self):
        one = packet([row(10)], -24);two = packet([row(10, home=3)], -1)
        three = packet([row(11)], -1);four = packet([row(11, status='CANC')], -1)
        exported = self.exported([one, two, three, four])
        self.assertEqual(exported['sports']['history'], [])
        self.assertEqual(set(exported['coverage']['exclusion_reasons']),
                         {'FIXTURE_IDENTITY_CONFLICT', 'SIMULTANEOUS_OBSERVATION_CONFLICT'})

    def test_target_live_past_unknown_and_simultaneous_conflicts_are_not_exported(self):
        archive_packets([self.target], self.root, stamp())
        for fid, at in ((999, stamp()), (100, stamp(-1)), (100, stamp(4))):
            with self.subTest(fid=fid, at=at), self.assertRaises(ValueError):
                export_sports(self.root, fid, at, profile='LOWER', source_reliability=.95)
        changed = packet([row(100, status='1H', hours=3)])
        archive_packets([changed], self.root, stamp())
        with self.assertRaisesRegex(ValueError, 'simultaneous target'):
            export_sports(self.root, 100, stamp(), profile='LOWER', source_reliability=.95)

    def test_weak_source_and_missing_context_stay_blocked_despite_eight_games(self):
        histories = packet([row(10 + n, hours=-72 - n) for n in range(8)], -1)
        exported = self.exported([histories])
        self.assertTrue(exported['coverage']['history_coverage_ready'])
        self.assertIn('MISSING_LINEUP', exported['coverage']['blockers'])
        self.assertFalse(exported['coverage']['price_recheck_useful'])
        weak = export_sports(self.root, 100, stamp(), profile='LOWER', source_reliability=.1)
        self.assertEqual(weak['coverage']['eligible_history_rows'], 0)

    def test_goal_counts_and_receipt_chronology_are_validated(self):
        for change in ('negative', 'bool_goal', 'future_ft', 'backwards_receipt'):
            p = packet([row(10)])
            if change == 'negative':p['data']['response'][0]['score']['fulltime']['home'] = -1
            if change == 'bool_goal':p['data']['response'][0]['score']['fulltime']['home'] = True
            if change == 'future_ft':p['data']['response'][0] = row(10, hours=2)
            if change == 'backwards_receipt':p['receipt']['request_started_at'] = stamp(1)
            with self.subTest(change=change), self.assertRaises(ValueError):validate_packet(reseal(p), stamp())


def ticket_input():
    return {'schema': 'ticket-audit-input-v1', 'status': 'REPORTED_UNVERIFIED',
            'source': 'synthetic audit fixture; not actual user tickets', 'currency': 'UAH',
            'timezone': 'Europe/Kyiv', 'tickets': [
                {'id': 't1', 'match_id': 'm1', 'day': '2030-01-01',
                 'market': {'kind': 'TEAM_TOTAL', 'side': 'HOME_OVER', 'line': 1.5},
                 'odds': 2, 'stake': 10, 'outcome': 'WIN'}]}


class TicketAuditTests(unittest.TestCase):
    def test_nine_reported_singles_reconcile_to_six_events_and_three_duplicate_theses(self):
        data = ticket_input()
        specs = [('m1', 1.5, 2, 10, 'WIN'), ('m1', 2, 3, 5, 'PUSH'),
                 ('m2', 2.5, 1.9, 7, 'LOSS'), ('m2', 3, 2.4, 3, 'LOSS'),
                 ('m3', 1.5, 2.3, 8, 'LOSS'), ('m4', 3, 1.8, 9, 'LOSS'),
                 ('m5', 1, 2.2, 4, 'LOSS'), ('m5', 1.5, 3.5, 6, 'LOSS'),
                 ('m6', 1, 4.2, 2, 'LOSS')]
        data['tickets'] = [{**data['tickets'][0], 'id': 't' + str(i), 'match_id': mid,
                            'market': {'kind': 'TOTAL' if mid in ('m2', 'm4') else 'TEAM_TOTAL',
                                       'side': 'OVER' if mid in ('m2', 'm4') else 'HOME_OVER', 'line': line},
                            'odds': odds, 'stake': stake, 'outcome': outcome}
                           for i, (mid, line, odds, stake, outcome) in enumerate(specs)]
        report = audit_tickets(data)
        self.assertEqual((report['turnover'], report['returns'], report['pnl']), (54, 25, -29))
        self.assertAlmostEqual(report['roi_on_settled_turnover'], -29 / 54)
        self.assertEqual(report['distinct_events'], 6)
        self.assertEqual(sum(bool(c['nested_line_ticket_groups']) for c in report['clusters']), 3)
        self.assertFalse(report['holdout_eligible']);self.assertFalse(report['monetary_permission'])
        self.assertEqual(report['decision_quality'], 'UNDETERMINED')

    def test_pending_and_void_are_not_losses_and_roi_uses_only_settled_stakes(self):
        data = ticket_input();base = data['tickets'][0]
        data['tickets'] += [{**base, 'id': 'p', 'match_id': 'm2', 'stake': 7, 'outcome': 'PENDING'},
                            {**base, 'id': 'v', 'match_id': 'm3', 'stake': 5, 'outcome': 'VOID'}]
        report = audit_tickets(data)
        self.assertEqual(report['turnover'], 22);self.assertEqual(report['settled_turnover'], 15)
        self.assertEqual(report['returns'], 25);self.assertEqual(report['pnl'], 10)
        self.assertEqual(report['pending_stake'], 7);self.assertAlmostEqual(report['roi_on_settled_turnover'], 10 / 15)
        data['tickets'] = [data['tickets'][1]]
        self.assertIsNone(audit_tickets(data)['roi_on_settled_turnover'])

    def test_currency_and_exact_money_are_required_and_no_impossible_push(self):
        for change in ('negative', 'fractional_cent', 'nan', 'bool', 'impossible_push', 'currency', 'duplicate'):
            data = ticket_input();t = data['tickets'][0]
            if change == 'negative':t['stake'] = -1
            if change == 'fractional_cent':t['stake'] = 10.001
            if change == 'nan':t['odds'] = float('nan')
            if change == 'bool':t['stake'] = True
            if change == 'impossible_push':t['outcome'] = 'PUSH'
            if change == 'currency':data['currency'] = 'mixed'
            if change == 'duplicate':data['tickets'].append(copy.deepcopy(t))
            with self.subTest(change=change), self.assertRaises(ValueError):audit_tickets(data)

    def test_local_ticket_day_handles_dst_and_rejects_wrong_day(self):
        data = ticket_input();t = data['tickets'][0]
        t.update(day='2024-07-02', placed_at='2024-07-01T21:15:00Z', kickoff='2024-07-02T12:00:00Z')
        self.assertEqual(audit_tickets(data)['days'][0]['day'], '2024-07-02')
        t['day'] = '2024-07-01'
        with self.assertRaisesRegex(ValueError, 'timezone'):audit_tickets(data)

    def test_shadow_win_and_live_entry_are_flagged_without_claiming_model_quality(self):
        data = ticket_input();t = data['tickets'][0]
        t.update(reported_decision='SHADOW', placed_at=stamp(3), kickoff=stamp(2))
        report = audit_tickets(data)
        self.assertIn('REPORTED_NON_BET_ENTRY', report['process_issues'])
        self.assertIn('LIVE_ENTRY_FORBIDDEN', report['process_issues'])
        self.assertEqual(report['rows'][0]['decision_quality'], 'UNDETERMINED')
        self.assertFalse(report['monetary_permission'])

    def test_cap_diagnostics_require_explicit_bankroll(self):
        data = ticket_input();self.assertEqual(audit_tickets(data)['days'][0]['flags'], [])
        data['starting_bankroll'] = 400
        report = audit_tickets(data)
        self.assertIn('REPORTED_DAY_TURNOVER_ABOVE_POLICY', report['process_issues'])
        self.assertIn('REPORTED_EVENT_TURNOVER_ABOVE_POLICY', report['process_issues'])

    def test_unmapped_reported_ticket_does_not_invent_home_away_contract(self):
        data = ticket_input();t = data['tickets'][0]
        t.pop('market');t['reported_market'] = 'Reported team over 1.5; fixture side unknown'
        report = audit_tickets(data)
        self.assertEqual(report['pnl'], 10)
        self.assertIn('REPORTED_MARKET_CONTRACT_UNMAPPED', report['process_issues'])
        self.assertFalse(report['rows'][0]['market_contract_supported'])
        self.assertEqual(report['clusters'][0]['nested_line_check'], 'UNVERIFIABLE')

    def test_missing_ledger_or_decision_cannot_verify_a_reported_bet(self):
        data = ticket_input();data['tickets'][0]['decision_id'] = 'does-not-exist'
        self.assertIn('LEDGER_UNAVAILABLE', audit_tickets(data)['process_issues'])
        with tempfile.TemporaryDirectory() as temp, closing(Repository(Path(temp) / 'ledger.sqlite')) as repo:
            self.assertIn('RECORDED_DECISION_NOT_FOUND', audit_tickets(data, service=Service(repo))['process_issues'])

    def test_recorded_bet_price_stake_market_book_and_entry_time_are_checked(self):
        # Artificial engine admission fixture; not a real release or forecast.
        p, case, quotes, context = controlled()
        decision = decide(p, quotes, case['recheck'], case['decision_at'], context,
                          {'bankroll': 1000, 'peak': 1000}, Policy())
        self.assertEqual(decision['decision'], 'BET');decision['id'] = digest(decision)
        with tempfile.TemporaryDirectory() as temp, closing(Repository(Path(temp) / 'ledger.sqlite')) as repo:
            match = p['sports']['match']
            for name in (match['home'], match['away']):repo.insert('teams', name, {'name': name})
            repo.insert('matches', match['id'], match, home=match['home'], away=match['away'],
                        kickoff=match['kickoff'], league=match['league'])
            model = {'id': p['model_id'], 'code_hash': p['code_hash'], 'model_hash': p['model_hash'],
                     'policy_hash': p['policy_hash'], 'calibrator_id': None, 'goal_model': None}
            repo.insert('model_versions', p['model_id'], model, at=p['sealed_at'])
            repo.insert('predictions', p['id'], p, at=p['sealed_at'], match_id=decision['match_id'], model_id=p['model_id'])
            repo.record_log('predictions', p['id'], p['sealed_at'], p)
            repo.insert('decisions', decision['id'], decision, at=decision['at'], prediction_id=p['id'])
            repo.record_log('decisions', decision['id'], decision['at'], decision)
            service = Service(repo)
            data = ticket_input();t = data['tickets'][0]
            t.update(match_id=decision['match_id'], day=time_day(decision['at']),
                     market=quotes[0]['market'], odds=quotes[0]['odds'], stake=decision['risk']['stake'],
                     decision_id=decision['id'], placed_at=decision['at'],
                     kickoff=p['sports']['match']['kickoff'], bookmaker=quotes[0]['bookmaker'])
            before = repo.db.total_changes
            self.assertEqual(audit_tickets(data, service=service)['rows'][0]['recorded_decision_check'], 'MATCHES_RECORDED_DECISION')
            self.assertEqual(repo.db.total_changes, before)
            duplicated = copy.deepcopy(data)
            duplicated['tickets'].append({**duplicated['tickets'][0], 'id': 'split'})
            audited = audit_tickets(duplicated, service=service)
            self.assertIn('RECORDED_DECISION_TOTAL_STAKE_EXCEEDED', audited['process_issues'])
            self.assertTrue(all(r['recorded_decision_check'] == 'MISMATCH' for r in audited['rows']))
            for key, value, expected in [('odds', 3, 'ENTRY_PRICE_CHANGED_NEEDS_RECHECK'),
                ('stake', 50, 'RECORDED_STAKE_LIMIT_EXCEEDED'),
                ('market', {'kind': 'BTTS', 'side': 'YES'}, 'RECORDED_MARKET_MISMATCH'),
                ('bookmaker', 'OTHER', 'RECORDED_BOOKMAKER_MISMATCH'),
                ('placed_at', p['sealed_at'], 'DECISION_RECORDED_AFTER_ENTRY')]:
                altered = copy.deepcopy(data);altered['tickets'][0][key] = value
                with self.subTest(key=key):self.assertIn(expected, audit_tickets(altered, service=service)['process_issues'])


def time_day(value):
    from zoneinfo import ZoneInfo
    return datetime.fromisoformat(value).astimezone(ZoneInfo('Europe/Kyiv')).date().isoformat()


class SessionAndCliTests(unittest.TestCase):
    def test_session_is_read_only_deduplicates_revisions_and_reports_match_blockers_once(self):
        with tempfile.TemporaryDirectory() as temp, closing(Repository(Path(temp) / 'ledger.sqlite')) as repo:
            now = [NOW]
            service = Service(repo, clock=lambda: now[0]);case = example(NOW)
            first = service.capture(case['sports'], case['markets'])
            later = copy.deepcopy(case['sports']);later['as_of'] = stamp(.1)
            later['evidence'][0]['value'] = 'changed'
            now[0] = NOW + timedelta(minutes=7)
            revised = service.capture(later, case['markets'], parent=first['id'], reason='NEW_INFORMATION')
            before = repo.db.total_changes
            report = inspect_session(service, service.now())
            self.assertEqual(repo.db.total_changes, before)
            self.assertEqual(report['shown'], 1);self.assertEqual(report['rows'][0]['prediction_id'], revised['id'])
            self.assertEqual(report['blocker_match_counts']['FIXTURE_IDENTITY_CONFLICT'], 1)
            self.assertEqual(report['price_recheck_prediction_ids'], [])
            self.assertFalse(report['monetary_permission'])

    def test_explicit_session_ids_limits_empty_and_duplicate_selection(self):
        with tempfile.TemporaryDirectory() as temp, closing(Repository(Path(temp) / 'ledger.sqlite')) as repo:
            service = Service(repo, clock=lambda: NOW)
            self.assertEqual(inspect_session(service, stamp())['status'], 'EMPTY')
            ids = [service.capture(example(NOW, 'm' + str(i))['sports'], example(NOW)['markets'])['id'] for i in range(2)]
            self.assertTrue(inspect_session(service, stamp(), limit=1)['truncated'])
            with self.assertRaises(ValueError):inspect_session(service, stamp(), [ids[0], ids[0]])

    def test_session_requires_intact_journal_even_for_closed_or_mismatched_build(self):
        with tempfile.TemporaryDirectory() as temp, closing(Repository(Path(temp) / 'ledger.sqlite')) as repo:
            service = Service(repo, clock=lambda: NOW)
            service.capture(example(NOW)['sports'], example(NOW)['markets'])
            with patch.object(repo, 'verify', return_value=False), self.assertRaisesRegex(ValueError, 'integrity'):
                inspect_session(service, stamp())

    def test_closed_seals_do_not_hide_upcoming_seals_behind_the_default_limit(self):
        with tempfile.TemporaryDirectory() as temp, closing(Repository(Path(temp) / 'ledger.sqlite')) as repo:
            now = [NOW]
            service = Service(repo, clock=lambda: now[0])
            old = service.capture(example(NOW, 'old')['sports'], example(NOW)['markets'])
            now[0] = NOW + timedelta(days=1)
            new = service.capture(example(now[0], 'new')['sports'], example(now[0])['markets'])
            report = inspect_session(service, service.now(), limit=1)
            self.assertEqual(report['closed_fixtures_excluded'], 1)
            self.assertEqual(report['rows'][0]['prediction_id'], new['id'])
            explicit = inspect_session(service, service.now(), [old['id']])
            self.assertEqual(explicit['rows'][0]['status'], 'PREMATCH_CLOSED')

    def test_archive_overwrite_guard_checks_all_three_outputs_before_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);out = root / 'sports.json'
            Path(str(out) + '.coverage.json').write_text('existing coverage')
            with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                status = main(['football-from-archive', '--fixture-id', '100', '--profile', 'LOWER',
                               '--source-reliability', '.95', '--output', str(out)])
            self.assertEqual(status, 2);self.assertFalse(out.exists())
            self.assertFalse(Path(str(out) + '.receipt.json').exists())

    def test_cli_readonly_commands_do_not_create_missing_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / 'missing.sqlite';input_file = Path(temp) / 'tickets.json'
            input_file.write_text(json.dumps(ticket_input()))
            for argv in (['--db', str(missing), 'session'],
                         ['--db', str(missing), 'ticket-audit', str(input_file), '--link-ledger']):
                with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):self.assertEqual(main(argv), 2)
                self.assertFalse(missing.exists())

    def test_cli_archive_and_export_require_no_credentials_and_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp);source = path / 'packet.json';archive = path / 'archive';out = path / 'sports.json'
            target = row(100, status='NS', hours=3)
            # Use an actual past cutoff; the synthetic target still lies ahead.
            source.write_text(json.dumps(packet([target])))
            with patch('sefirot.cli.datetime') as clock:
                clock.now.return_value = NOW
                with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                    self.assertEqual(main(['football-archive', str(source), '--directory', str(archive)]), 0)
                    argv = ['football-from-archive', '--directory', str(archive), '--fixture-id', '100',
                            '--profile', 'LOWER', '--source-reliability', '.95', '--output', str(out)]
                    self.assertEqual(main(argv), 0)
                    before = out.read_bytes();self.assertEqual(main(argv), 2)
                    self.assertEqual(out.read_bytes(), before)
            self.assertTrue(Path(str(out) + '.coverage.json').exists())


if __name__ == '__main__':
    unittest.main()
