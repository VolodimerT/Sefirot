"""Cross-version counterexamples; controlled admission is not model validation."""
import copy
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.contracts import Policy, digest
from sefirot.engine import prepare,decide
from sefirot.repository import Repository
from sefirot.service import Service
from test_audit_upgrade import controlled, decision, NOW


class CurrentEvidenceTests(unittest.TestCase):
    def test_fresh_independent_confirmation_still_works(self):
        p, case, quotes, context = controlled()
        self.assertEqual(decision(p, case, quotes, context)['decision'], 'BET')

    def test_old_independent_facts_do_not_confirm_current_divergence(self):
        for age in (timedelta(days=3), timedelta(minutes=61)):
            with self.subTest(age=age):
                p, case, quotes, context = controlled()
                old = (NOW-age).isoformat()
                for fact in case['recheck']['evidence']:
                    if fact['source_id']=='statistics':
                        fact.update(observed_at=old, published_at=old, received_at=old, critical=False)
                out = decision(p, case, quotes, context)
                self.assertEqual(out['decision'], 'PASS')
                self.assertIn('DIVERGENCE_NEEDS_CORROBORATION',
                              [i['code'] for i in out['candidates'][0]['issues']])

    def movement_case(self):
        p, case, quotes, context = controlled(win=.75, odds=1.5)
        news = {'id':'news', 'key':'market_news', 'value':'current sporting news',
                'kind':'FACT', 'source_id':'official', 'critical':False, 'supports':[],
                **{key:case['recheck']['checked_at'] for key in ('observed_at','published_at','received_at')}}
        case['recheck']['evidence'].append(news)
        quotes[0]['movement_evidence']=['news']
        opening={**quotes[0], 'phase':'OPEN', 'odds':1.2, 'movement_evidence':[]}
        return p, case, [opening, quotes[0]], context, news

    def assert_unexplained(self, p, case, quotes, context):
        out=decision(p, case, quotes, context)
        self.assertEqual(out['decision'], 'PASS')
        self.assertIn('UNEXPLAINED_LINE_MOVEMENT', [i['code'] for i in out['candidates'][0]['issues']])

    def test_valid_current_news_can_explain_movement(self):
        p,case,quotes,ctx,_=self.movement_case()
        self.assertEqual(decision(p,case,quotes,ctx)['decision'], 'BET')

    def test_disabled_and_weak_sources_cannot_explain_movement(self):
        for enabled, reliability in ((False,.95),(True,.7)):
            with self.subTest(enabled=enabled,reliability=reliability):
                p,case,quotes,ctx,news=self.movement_case()
                p['sports']['sources'].append({'id':'unusable','independence_group':'unusable',
                                              'enabled':enabled,'reliability':reliability})
                news['source_id']='unusable'
                self.assert_unexplained(p,case,quotes,ctx)

    def test_stale_news_cannot_explain_current_movement(self):
        for age in (timedelta(days=3),timedelta(minutes=61)):
            with self.subTest(age=age):
                p,case,quotes,ctx,news=self.movement_case()
                old=(NOW-age).isoformat()
                news.update(observed_at=old,published_at=old,received_at=old)
                self.assert_unexplained(p,case,quotes,ctx)

    def test_superseded_news_cannot_explain_movement(self):
        p,case,quotes,ctx,news=self.movement_case()
        newer={**news,'id':'new-news','value':'corrected news','supersedes':['news']}
        newer['received_at']=case['decision_at'];newer['published_at']=case['decision_at']
        newer['observed_at']=case['decision_at']
        case['recheck']['checked_at']=case['decision_at']
        case['recheck']['evidence'].append(newer)
        self.assert_unexplained(p,case,quotes,ctx)


class ExecutionConsistencyTests(unittest.TestCase):
    def setup_execution(self, root, push=True, graded=False):
        p,case,quotes,ctx=controlled([{'kind':'DNB','side':'HOME'}] if push else [{'kind':'1X2','side':'HOME'}],odds=1.6 if push else 1.5)
        policy=replace(Policy(),stress_mode='GRADED') if graded else Policy()
        if graded:
            p=prepare(case['sports'],[p['candidates'][0]['market']],policy)
            p['sealed_at']=NOW.isoformat();p['model_id']='controlled-model'
        c=p['candidates'][0]
        if push:
            c.update(base=[.45,.4,.15],low=[.4,.3,.1],high=[.5,.5,.2],
                     calibration_low=[.4,.3,.1],calibration_high=[.5,.5,.2],
                     stress_probabilities=[[.4,.4,.2]])
        if graded:
            c.update(calibration='CALIBRATED_BIN',stress_calibration_statuses=['CALIBRATED_BIN'],
                     low=[.1,.1,.1],high=[.8,.8,.8])
            ctx['releases'][c['key']]['stress_classes']={'ROBUST_VALUE':{'passed':True}}
        d=decide(p,quotes,case['recheck'],case['decision_at'],ctx,{'bankroll':1000.,'peak':1000.},policy)
        self.assertEqual(d['decision'],'BET')
        at=case['decision_at']
        repo=Repository(root/'audit.sqlite')
        self.addCleanup(repo.close)
        svc=Service(repo,policy,clock=lambda:datetime.fromisoformat(at))
        saved=svc.capture(case['sports'],[c['market']])
        d['prediction_id']=saved['id'];d['id']=digest(d)
        repo.insert('decisions',d['id'],d,prediction_id=saved['id'],at=at)
        repo.record_log('decisions',d['id'],at,d)
        entry={'id':'controlled-execution','market':c['key'],'odds':quotes[0]['odds'],'stake':d['risk']['stake'],
               'bookmaker':quotes[0]['bookmaker'],'origin':'SYSTEM_RECOMMENDATION'}
        return svc,repo,d,entry,at,ctx,saved

    def test_allowed_push_stake_can_be_recorded_and_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            svc,repo,d,entry,at,ctx,_=self.setup_execution(Path(tmp))
            with patch.object(svc,'context',return_value=ctx):
                result=svc.execution(d['id'],entry,at)
                retry=svc.execution(d['id'],entry,at)
            self.assertEqual(result['flags'],[])
            self.assertEqual(result,retry)
            self.assertEqual(len(repo.all('bets')),1)
            self.assertTrue(repo.verify())

    def test_graded_execution_uses_calibration_bounds_and_stake_caps(self):
        with tempfile.TemporaryDirectory() as tmp:
            svc,repo,d,entry,at,ctx,_=self.setup_execution(Path(tmp),graded=True)
            self.assertEqual(d['risk']['probability_bound_basis'],'CALIBRATION_ONLY')
            self.assertEqual(d['risk']['stake'],5.)
            with patch.object(svc,'context',return_value=ctx):
                result=svc.execution(d['id'],entry,at)
            self.assertEqual(result['flags'],[])
            self.assertTrue(repo.verify())

    def test_real_exposure_change_remains_a_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            svc,repo,d,entry,at,ctx,p=self.setup_execution(Path(tmp))
            ctx['exposures']=[{'at':at,'stake':1.,'groups':['match:'+p['sports']['match']['id']]}]
            with patch.object(svc,'context',return_value=ctx), self.assertRaisesRegex(ValueError,'PORTFOLIO_LIMIT_CHANGED'):
                svc.execution(d['id'],entry,at)
            self.assertEqual(repo.all('bets'),[])

    def test_different_policy_cannot_reuse_old_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            svc,repo,d,entry,at,ctx,_=self.setup_execution(Path(tmp),push=False)
            svc.policy=replace(Policy(),max_stake_fraction=.01)
            with patch.object(svc,'context',return_value=ctx),self.assertRaisesRegex(ValueError,'EXECUTION_VERSION_MISMATCH'):
                svc.execution(d['id'],entry,at)
            self.assertEqual(repo.all('bets'),[])

    def test_different_build_cannot_reuse_old_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            svc,repo,d,entry,at,ctx,_=self.setup_execution(Path(tmp),push=False)
            with patch.object(svc,'context',return_value=ctx),patch('sefirot.service.code_hash',return_value='another-build'),self.assertRaisesRegex(ValueError,'EXECUTION_VERSION_MISMATCH'):
                svc.execution(d['id'],entry,at)
            self.assertEqual(repo.all('bets'),[])


if __name__=='__main__':unittest.main()
