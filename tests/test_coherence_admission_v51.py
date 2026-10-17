"""Business regressions; controlled approvals are not empirical permissions."""
import copy
from datetime import timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from sefirot.contracts import Policy,digest,time
from sefirot.engine import prepare,decide,model_code_hash
from sefirot.fixtures import example
from sefirot.markets import market_of
from sefirot.probability import CALIBRATION_SCHEMA,bin_key
from test_audit_upgrade import NOW,controlled,decision

MARKETS=[{'kind':'1X2','side':'HOME'},{'kind':'DNB','side':'HOME'}]


class CoherenceAdmissionTests(unittest.TestCase):
    def conflicting(self, *, stress_only=False):
        p,case,quotes,context=controlled(MARKETS,win=.8,odds=1.5)
        dnb=next(c for c in p['candidates'] if c['key']=='DNB:HOME')
        dnb['stress_probabilities']=[[.75,0.,.25]]
        if not stress_only:
            dnb.update(base=[.75,0.,.25],low=[.73,0.,.23],high=[.77,0.,.27])
        return p,case,quotes,context

    def test_incompatible_same_home_win_probabilities_cannot_be_bet(self):
        p,case,quotes,context=self.conflicting()
        before=digest(p['candidates'])
        result=decision(p,case,quotes,context)
        self.assertEqual(result['decision'],'PASS')
        self.assertEqual(result['risk']['stake'],0.)
        self.assertIn('CALIBRATION_COHERENCE_CONFLICT',[i['code'] for i in result['issues']])
        self.assertEqual(digest(p['candidates']),before)
        self.assertTrue(all(not c['eligible'] for c in result['candidates']))
        self.assertEqual(result['class'],'D')

    def test_stress_incompatibility_blocks_even_with_consistent_base(self):
        p,case,quotes,context=self.conflicting(stress_only=True)
        result=decision(p,case,quotes,context)
        self.assertEqual(result['decision'],'PASS')
        self.assertIn('CALIBRATION_COHERENCE_CONFLICT',[i['code'] for i in result['issues']])

    def test_price_or_deleting_stale_diagnostic_cannot_bypass_recheck(self):
        p,case,quotes,context=self.conflicting()
        p['issues']=[]
        for quote in quotes:quote['odds']=1.6
        result=decision(p,case,quotes,context)
        self.assertEqual(result['decision'],'PASS')
        self.assertIn('CALIBRATION_COHERENCE_CONFLICT',[i['code'] for i in result['issues']])

    def test_valid_equal_probabilities_keep_existing_controlled_admission(self):
        p,case,quotes,context=controlled(MARKETS,win=.8,odds=1.5)
        result=decision(p,case,quotes,context)
        self.assertEqual(result['decision'],'BET')
        self.assertGreater(result['risk']['stake'],0.)
        self.assertNotIn('CALIBRATION_COHERENCE_CONFLICT',[i['code'] for i in result['issues']])

    def test_actual_contract_bin_calibration_is_flagged_without_normalizing_it(self):
        case=example(NOW,'calibration-coherence-v51')
        original=prepare(case['sports'],MARKETS,Policy())
        buckets={bin_key(market_of(c['market']),c['raw'][0],'MEN'):
                 ([20,0,0] if c['key']=='1X2:HOME' else [0,0,20]) for c in original['candidates']}
        artifact={'version':CALIBRATION_SCHEMA,'model_hash':model_code_hash(),
                  'policy_hash':Policy().fingerprint,'fit_at':(time(case['sports']['as_of'])-timedelta(seconds=1)).isoformat(),
                  'goal_model_hash':None,'fit_ids':['synthetic-fit'], 'buckets':buckets,'synthetic':True}
        artifact['hash']=digest(artifact);saved=copy.deepcopy(artifact)
        p=prepare(case['sports'],MARKETS,Policy(),artifact)
        self.assertIn('CALIBRATION_COHERENCE_CONFLICT',[i['code'] for i in p['issues']])
        self.assertGreater(p['candidates'][0]['base'][0],p['candidates'][1]['base'][0])
        self.assertEqual(artifact,saved)

    def test_unverified_bounded_scope_blocks_instead_of_claiming_consistency(self):
        # Controlled sealed-candidate fixture, independent of the extreme-line
        # roundoff limitation in the upstream Poisson projection.
        p,case,quotes,context=controlled([{'kind':'TOTAL','side':'OVER','line':2.5}],win=.8,odds=1.5)
        c=p['candidates'][0];old=c['key'];c['market']['line']=1000.;c['key']='TOTAL:OVER:1000'
        p['market_pool']=[copy.deepcopy(c['market'])];quotes[0]['market']=copy.deepcopy(c['market'])
        for field in ('health','releases','sephirot_ratings'):context[field][c['key']]=context[field].pop(old)
        result=decision(p,case,quotes,context)
        self.assertEqual(result['decision'],'PASS')
        self.assertIn('CALIBRATION_COHERENCE_UNVERIFIED',[i['code'] for i in result['issues']])
        self.assertFalse(result['coherence']['joint_distribution_verified'])

    def test_user_action_cannot_replace_model_repair_with_a_new_price(self):
        p,case,quotes,context=self.conflicting()
        result=decision(p,case,quotes,context)
        actions=[a for a in result['decision_card']['action_plan']
                 if 'CALIBRATION_COHERENCE_CONFLICT' in a['codes']]
        self.assertEqual(len(actions),1)
        self.assertEqual(actions[0]['category'],'MODEL_VALIDATION')
        self.assertFalse(actions[0]['price_can_resolve'])


if __name__=='__main__':unittest.main()
