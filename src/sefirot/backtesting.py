"""Chronological replay of captured inputs. Reconstructed tests cannot certify release."""
from .contracts import time,Policy,digest
from .engine import prepare,decide
from .markets import market_of,settle
from .feedback import brier,summary


def walk_forward(cases,policy=None):
    policy=policy or Policy();seen=set();records=[];decisions=[]
    for case in sorted(cases,key=lambda c:(time(c['sports']['as_of']),c['sports']['match']['id'])):
        sports=case['sports'];mid=sports['match']['id'];result=case['result']
        if mid in seen:raise ValueError('duplicate backtest fixture')
        seen.add(mid)
        if result['match_id']!=mid or time(result['finished_at'])<=time(sports['match']['kickoff']) or time(result['received_at'])<time(result['finished_at']):raise ValueError('backtest result mismatch/chronology')
        if result['status'] not in ('VOID','FINISHED'):raise ValueError('unsupported result')
        p=prepare(sports,case['markets'],policy,case.get('calibrator'),case.get('goal_model'));p['sealed_at']=sports['as_of'];p['model_id']=digest([p['code_hash'],p['policy_hash'],case.get('calibrator',{}).get('hash'),case.get('goal_model',{}).get('hash')])
        context={'journal_ok':True,'health':{},'releases':{},'policy_approved':False,'captured_prematch':False,'exposures':[]}
        d=decide(p,case['quotes'],case['recheck'],case['decision_at'],context,{'bankroll':1000.,'peak':1000.},policy);decisions.append(d)
        if result['status']=='VOID':continue
        for c in p['candidates']:
            m=market_of(c['market']);outcome=settle(m,result['home_goals'],result['away_goals']);push=c['raw'][1]
            records.append({'match_id':mid,'market':m.key,'model_id':p['model_id'],'probabilities':c['base'],'outcome':outcome,
                            'brier':brier(c['base'],outcome),'baseline_brier':brier([(1-push)/2,push,(1-push)/2],outcome),
                            'received_at':result['received_at'],'used_history':p['model']['used_history']})
    return {'mode':'RECONSTRUCTED_BACKTEST','can_certify_release':False,'fixtures':len(cases),'decisions':len(decisions),
            'BET':sum(d['decision']=='BET' for d in decisions),'PASS':sum(d['decision']=='PASS' for d in decisions),
            'metrics':summary(records),'by_market':{m:summary([r for r in records if r['market']==m]) for m in sorted({r['market'] for r in records})},
            'records':records}
