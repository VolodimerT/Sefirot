"""Counterexamples from the October 2 system audit; no API calls or bets."""
import copy
import io
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.contracts import Policy, digest, integer
from sefirot.football_provider import HOST, fixture_identity, normalize_sports, select_prematch
from sefirot.markets import market_of, payoff_ev, settle
from sefirot.probability import calibrate, fit_calibrator
from sefirot.engine import prepare
from sefirot.fixtures import example
from sefirot.identity import code_hash,model_code_hash
from sefirot.repository import Repository
from sefirot.service import Service

STAMP = '2026-10-02T12:00:00+00:00'
POLICY = replace(Policy(), min_calibration=20)


def records(key, outcomes):
    return [{'match_id':str(i), 'market':key, 'kind':key.split(':')[0],
             'competition_profile':'MEN', 'raw_win':.6, 'outcome':outcome,
             'received_at':STAMP, 'synthetic':True} for i, outcome in enumerate(outcomes)]


class CalibrationContractTests(unittest.TestCase):
    def test_integer_line_cannot_calibrate_half_line_or_inflate_ev(self):
        artifact=fit_calibrator(records('TEAM_TOTAL:HOME_OVER:1',
                               ['WIN']*12+['PUSH']*4+['LOSS']*4), 'm','p',STAMP)
        m=market_of({'kind':'TEAM_TOTAL','side':'HOME_OVER','line':1.5})
        cal=calibrate(m,[.6,0.,.4],artifact,POLICY,'MEN')
        self.assertEqual(cal['status'],'INSUFFICIENT_BIN')
        self.assertEqual(cal['base'],[.6,0.,.4])
        self.assertEqual(cal['high'][1],0.)
        self.assertAlmostEqual(payoff_ev(cal['base'][0],cal['base'][1],1.7),.02)

    def test_binary_empirical_fit_has_no_push_in_base_or_bounds(self):
        key='TEAM_TOTAL:HOME_OVER:1.5'
        artifact=fit_calibrator(records(key,['WIN']*12+['LOSS']*8),'m','p',STAMP)
        m=market_of({'kind':'TEAM_TOTAL','side':'HOME_OVER','line':1.5})
        cal=calibrate(m,[.6,0.,.4],artifact,POLICY,'MEN')
        self.assertEqual(cal['status'],'CALIBRATED_BIN')
        self.assertAlmostEqual(sum(cal['base']),1.)
        for field in ('base','low','high'):self.assertEqual(cal[field][1],0.)

    def test_integer_contract_preserves_real_refunds(self):
        artifact=fit_calibrator(records('TOTAL:OVER:2',['WIN']*12+['PUSH']*4+['LOSS']*4),'m','p',STAMP)
        m=market_of({'kind':'TOTAL','side':'OVER','line':2})
        cal=calibrate(m,[.6,.2,.2],artifact,POLICY,'MEN')
        self.assertEqual(cal['status'],'CALIBRATED_BIN')
        self.assertAlmostEqual(cal['base'][1],.2)
        self.assertEqual(settle(m,1,1),'PUSH')

    def test_impossible_push_training_result_is_rejected(self):
        for key in ('1X2:HOME','BTTS:YES','TOTAL:OVER:2.5','HANDICAP:HOME:-1.5'):
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'PUSH'):
                fit_calibrator(records(key,['PUSH']),'m','p',STAMP)

    def test_opposite_sides_and_thresholds_do_not_share_calibration(self):
        artifact=fit_calibrator(records('TOTAL:OVER:2.5',['WIN']*12+['LOSS']*8),'m','p',STAMP)
        for contract in ({'kind':'TOTAL','side':'UNDER','line':2.5},
                         {'kind':'TOTAL','side':'OVER','line':3.5}):
            with self.subTest(contract=contract):
                cal=calibrate(market_of(contract),[.6,0.,.4],artifact,POLICY,'MEN')
                self.assertEqual(cal['status'],'INSUFFICIENT_BIN')

    def test_legacy_family_only_artifact_is_not_reinterpreted(self):
        artifact=fit_calibrator(records('1X2:HOME',['WIN']*12+['LOSS']*8),'m','p',STAMP)
        artifact['version']='profile-reliability-v3'
        with self.assertRaisesRegex(ValueError,'schema'):
            calibrate(market_of({'kind':'1X2','side':'HOME'}),[.6,0,.4],artifact,POLICY,'MEN')

    def test_unfitted_binary_contracts_never_get_push_uncertainty(self):
        for contract in ({'kind':'1X2','side':'HOME'}, {'kind':'DOUBLE_CHANCE','side':'1X'},
                         {'kind':'BTTS','side':'YES'}, {'kind':'HANDICAP','side':'HOME','line':-1.5}):
            with self.subTest(contract=contract):
                cal=calibrate(market_of(contract),[.6,0.,.4],None,POLICY,'MEN')
                for field in ('base','low','high'):self.assertEqual(cal[field][1],0.)
                self.assertEqual(cal['status'],'UNCALIBRATED')

    def test_bad_contract_and_probabilities_cannot_enter_fit(self):
        bad=records('TOTAL:OVER:2.5',['WIN']);bad[0]['kind']='TEAM_TOTAL'
        with self.assertRaisesRegex(ValueError,'kind'):fit_calibrator(bad,'m','p',STAMP)
        m=market_of({'kind':'TOTAL','side':'OVER','line':2.5})
        for raw in ([],[.6,0.],[.6,.1,.3],[.6,0,.6],[True,0,0]):
            with self.subTest(raw=raw),self.assertRaises(ValueError):calibrate(m,raw,None,POLICY,'MEN')


def packet():
    row={'fixture':{'id':1492986,'date':'2026-10-02T18:45:00+00:00',
                    'timestamp':int(datetime(2026,10,2,18,45,tzinfo=timezone.utc).timestamp()),
                    'status':{'short':'NS'}},
         'league':{'id':1_000_003},
         'teams':{'home':{'id':1_000_004,'name':'Home'},'away':{'id':1_000_005,'name':'Away'}}}
    data={'errors':[],'results':1,'paging':{'total':1},'response':[row]}
    return {'data':data,'receipt':{'provider_host':HOST,'endpoint':'/fixtures',
                                   'received_at':STAMP,'payload_hash':digest(data)}}


class ProviderIdentifierTests(unittest.TestCase):
    def test_real_world_fixture_id_over_one_million_is_accepted(self):
        row,match=select_prematch(packet(),1492986)
        self.assertEqual(match['id'],'api-football:fixture:1492986')
        self.assertEqual(match['league'],'api-football:league:1000003')
        out=normalize_sports(packet(),1492986,[],profile='MEN',source_reliability=.8)
        self.assertFalse(out['receipt']['monetary_permission'])
        self.assertEqual(out['receipt']['missing_facts'],['lineup','injuries','coach','rotation','tactics'])

    def test_id_validation_remains_strict(self):
        for value in (True,0,-1,1.5,'1492986',2**63):
            with self.subTest(value=value),self.assertRaises(ValueError):
                row=copy.deepcopy(packet()['data']['response'][0]);row['fixture']['id']=value
                fixture_identity(row)
        with self.assertRaises(ValueError):integer(1_000_001,'sample size')
        row=copy.deepcopy(packet()['data']['response'][0]);row['fixture']['id']=2**63-1
        self.assertEqual(fixture_identity(row)['id'],f'api-football:fixture:{2**63-1}')

    def test_high_id_does_not_bypass_prematch_or_receipt_integrity(self):
        p=packet();p['data']['response'][0]['fixture']['status']['short']='1H'
        p['receipt']['payload_hash']=digest(p['data'])
        with self.assertRaisesRegex(ValueError,'prematch'):select_prematch(p,1492986)
        p=packet();p['data']['response'][0]['teams']['home']['name']='changed'
        with self.assertRaisesRegex(ValueError,'integrity'):select_prematch(p,1492986)

    def test_cli_normalize_uses_fixed_provider_without_api_calls(self):
        from sefirot.cli import main
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);target=root/'target.json';output=root/'sports.json'
            target.write_text(json.dumps(packet()))
            with redirect_stdout(io.StringIO()):
                status=main(['football-normalize',str(target),'--fixture-id','1492986',
                             '--profile','MEN','--source-reliability','.8','--output',str(output)])
            self.assertEqual(status,0)
            self.assertEqual(json.loads(output.read_text())['match']['id'],'api-football:fixture:1492986')
            self.assertFalse(json.loads(Path(str(output)+'.receipt.json').read_text())['monetary_permission'])


class ModelIdentityTests(unittest.TestCase):
    def test_ui_and_transport_change_build_but_not_fit_identity(self):
        package=Path(__file__).resolve().parents[1]/'src'/'sefirot'
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for path in package.glob('*.py'):shutil.copy2(path,root/path.name)
            build,model=code_hash(root),model_code_hash(root)
            for name in ('cli.py','decision_card.py','football_provider.py','provider_transport.py'):
                with (root/name).open('a') as file:file.write('\n# presentation or transport change\n')
            self.assertNotEqual(code_hash(root),build)
            self.assertEqual(model_code_hash(root),model)
            with (root/'_payoffs.py').open('a') as file:file.write('\n# changed payoff implementation\n')
            self.assertNotEqual(model_code_hash(root),model)

    def test_same_math_can_use_fit_after_ui_change_math_change_is_rejected(self):
        case=example(datetime(2026,10,3,12,tzinfo=timezone.utc));market=case['markets'][0]
        raw=prepare(case['sports'],[market],POLICY)['candidates'][0]['raw']
        rows=records('1X2:HOME',['WIN']*12+['LOSS']*8)
        for row in rows:row['raw_win']=raw[0]
        artifact=fit_calibrator(rows,model_code_hash(),POLICY.fingerprint,STAMP)
        with patch('sefirot.engine.code_hash',return_value='new-ui-build'):
            p=prepare(case['sports'],[market],POLICY,artifact)
        self.assertEqual(p['code_hash'],'new-ui-build')
        self.assertEqual(p['candidates'][0]['calibration'],'CALIBRATED_BIN')
        with patch('sefirot.engine.model_code_hash',return_value='different-math'):
            with self.assertRaisesRegex(ValueError,'hash'):prepare(case['sports'],[market],POLICY,artifact)

    def test_goal_fit_compatibility_uses_math_identity_and_rejects_old_schema(self):
        from test_p0_upgrade import artifact,P0,NOW
        from sefirot.goal_model import validate_artifact
        fitted=artifact();sports=example(NOW)['sports']
        with patch('sefirot.engine.code_hash',return_value='new-ui-build'):
            p=prepare(sports,[{'kind':'TOTAL','side':'OVER','line':2.5}],P0,goal_model=fitted)
        self.assertEqual(p['goal_model']['hash'],fitted['hash'])
        with self.assertRaisesRegex(ValueError,'hash'):
            validate_artifact(fitted,sports,P0,'different-math')
        old=copy.deepcopy(fitted);old.pop('model_hash');old.pop('identity_schema')
        old['hash']=digest({key:value for key,value in old.items() if key!='hash'})
        with self.assertRaises(ValueError):validate_artifact(old,sports,P0,model_code_hash())

    def test_full_build_money_approval_is_not_inherited_after_ui_change(self):
        now=datetime(2026,10,3,12,tzinfo=timezone.utc);case=example(now)
        with tempfile.TemporaryDirectory() as temp:
            repo=Repository(Path(temp)/'test.sqlite');svc=Service(repo,clock=lambda:now)
            try:
                svc.approve_policy('controlled-test','I_APPROVE_THIS_EXPERIMENTAL_POLICY',now.isoformat())
                with patch('sefirot.engine.code_hash',return_value='new-ui-build'):
                    p=svc.capture(case['sports'],[case['markets'][0]])
                self.assertFalse(svc.context(p,now.isoformat())['policy_approved'])
            finally:repo.close()

    def test_old_model_records_cannot_be_relabelled_as_new_math(self):
        now=[datetime(2026,10,3,12,tzinfo=timezone.utc)];case=example(now[0])
        with tempfile.TemporaryDirectory() as temp:
            repo=Repository(Path(temp)/'test.sqlite');svc=Service(repo,clock=lambda:now[0])
            try:
                svc.reserve([case['sports']['match']['id']],'CALIBRATION',(now[0]-timedelta(seconds=1)).isoformat())
                svc.capture(case['sports'],[case['markets'][0]])
                now[0]=datetime.fromisoformat(case['result']['received_at']);svc.result(case['result'])
                with patch('sefirot.service.model_code_hash',return_value='different-math'):
                    with self.assertRaisesRegex(ValueError,'relabelled'):svc.calibrate(now[0].isoformat())
                self.assertEqual(repo.all('calibrators'),[])
            finally:repo.close()


class CombinedVersionTests(unittest.TestCase):
    def test_graded_card_and_sizing_use_actual_admission_bounds(self):
        from test_p0_upgrade import graded_case,run_graded
        from sefirot.probability import ev_bounds
        inputs=graded_case();d=run_graded(inputs);candidate=d['candidates'][0]
        self.assertEqual(d['decision'],'BET')
        row=d['decision_card']['alternatives'][0];requirements=row['price_requirements']
        self.assertEqual(row['probability_bound_basis'],'CALIBRATION_ONLY')
        self.assertLessEqual(requirements['required_odds'],candidate['odds'])
        self.assertEqual(requirements['stress_ev_floor'],inputs[0].aggressive_stress_floor)
        self.assertTrue(requirements['requires_stress_class_validation'])
        self.assertFalse(requirements['monetary_permission'])
        adverse=d['risk']['probabilities_used']
        self.assertAlmostEqual(sum(adverse),1.)
        self.assertAlmostEqual(payoff_ev(adverse[0],adverse[1],candidate['odds']),
                               ev_bounds(candidate['admission_low'],candidate['admission_high'],candidate['odds'])[0])


if __name__=='__main__':unittest.main()
