"""Chronicler metrics and contextual Competence; results never rewrite decisions."""
from __future__ import annotations
from math import sqrt
from .contracts import number,integer,time,digest,SEPHIROT
from .probability import wilson
from .evaluation import metrics


def brier(probabilities,outcome):
    if outcome not in ('WIN','PUSH','LOSS'): raise ValueError('outcome must be WIN/PUSH/LOSS')
    if len(probabilities)!=3: raise ValueError('three probabilities required')
    p=[number(x,'probability',0,1) for x in probabilities]
    if abs(sum(p)-1)>1e-8: raise ValueError('probabilities must sum to 1')
    return sum((x-int(i==('WIN','PUSH','LOSS').index(outcome)))**2 for i,x in enumerate(p))/2


def summary(records):
    if not records: return {'n':0,'brier':None,'baseline_brier':None,'calibration_error':None,'mean_error':None}
    keys=[(r['match_id'],r['market'],r['model_id']) for r in records]
    if len(keys)!=len(set(keys)): raise ValueError('duplicate feedback observation')
    bins={}
    for r in records:
        bucket=min(4,int(r['probabilities'][0]*5));bins.setdefault(bucket,[]).append(r)
    ece=sum(len(rows)*abs(sum(r['probabilities'][0]-int(r['outcome']=='WIN') for r in rows)/len(rows)) for rows in bins.values())/len(records)
    return {'n':len(records),'distinct_matches':len({r['match_id'] for r in records}),
            'brier':sum(r['brier'] for r in records)/len(records),
            'multiclass':metrics([r['probabilities'] for r in records],[('WIN','PUSH','LOSS').index(r['outcome']) for r in records]),
            'baseline_brier':sum(r['baseline_brier'] for r in records)/len(records),
            'calibration_error':ece,'mean_error':sum(r['probabilities'][0]-int(r['outcome']=='WIN') for r in records)/len(records),
            'reliability':[{'bin':k,'n':len(v),'forecast':sum(r['probabilities'][0] for r in v)/len(v),
                            'frequency':sum(r['outcome']=='WIN' for r in v)/len(v),
                            'interval':wilson(sum(r['outcome']=='WIN' for r in v),len(v))} for k,v in sorted(bins.items())]}


def context_key(league,market,scenario,model_id,profile='UNKNOWN'): return digest([league,profile,market,scenario,model_id])


def competence(records,policy,previous='UNKNOWN',severe=0):
    records=sorted(records,key=lambda r:(time(r['received_at']),r['match_id']))
    report=summary(records);n=report['n'];w=policy.health_window
    state='UNKNOWN' if n<policy.min_context else 'WORKING'
    reason='INSUFFICIENT_SAMPLE' if state=='UNKNOWN' else 'NO_DEGRADATION_SIGNAL'
    recent=records[-w:];prior=records[-2*w:-w]
    def worse(rows):
        if len(rows)<w:return False
        diffs=[r['brier']-r['baseline_brier'] for r in rows];mean=sum(diffs)/len(diffs)
        se=sqrt(sum((x-mean)**2 for x in diffs)/(len(diffs)-1)/len(diffs)) if len(diffs)>1 else 1.
        return mean>policy.health_delta+1.96*se
    if worse(recent):state='WEAK';reason='RECENT_BASELINE_UNDERPERFORMANCE'
    if worse(recent) and worse(prior):state='FROZEN';reason='TWO_FAILED_WINDOWS'
    if severe>=policy.max_severe_errors:state='FROZEN';reason='REPEATED_CRITICAL_ERRORS'
    if previous=='FROZEN':state='FROZEN';reason='RECOVERY_REQUIRED'
    trust='INSUFFICIENT' if state in ('UNKNOWN','FROZEN') else 'LOW' if state=='WEAK' else 'MEDIUM' if n<200 else 'HIGH'
    return {**report,'state':state,'trust':trust,'reason':reason,'sample_uncertainty':1/sqrt(n) if n else None}


def ratings(postmortems,league,kind,scenario,policy,model_id=None,profile=None):
    output={}
    relevant=[p for p in postmortems if (p['league'],p['kind'],p['scenario'])==(league,kind,scenario) and (model_id is None or p.get('model_id')==model_id) and (profile is None or p.get('competition_profile','UNKNOWN')==profile)]
    for role in SEPHIROT:
        by_match={}
        for p in sorted(relevant,key=lambda r:time(r['at'])):
            if role in p['roles'] and p['roles'][role]['correct'] is not None:by_match[p['match_id']]=p['roles'][role]
        observations=list(by_match.values())
        n=len(observations);ok=sum(o['correct'] for o in observations);severe=sum(o['severe'] for o in observations)
        output[role]={'n':n,'accuracy':ok/n if n else None,'interval':wilson(ok,n) if n else [0.,1.],
                      'severe_errors':severe,'trust':'INSUFFICIENT' if n<policy.min_context else 'LOW' if severe else 'MEDIUM'}
    return output


def compare_versions(old,new,policy):
    key=lambda r:(r['match_id'],r['market'])
    a={key(r):r for r in old};b={key(r):r for r in new};common=sorted(set(a)&set(b))
    if len(a)!=len(old) or len(b)!=len(new):raise ValueError('duplicate paired records')
    if any(a[k]['outcome']!=b[k]['outcome'] for k in common):raise ValueError('paired outcomes disagree')
    if any(a[k].get('competition_profile','UNKNOWN')!=b[k].get('competition_profile','UNKNOWN') for k in common):raise ValueError('paired competition profiles disagree')
    delta=[a[k]['brier']-b[k]['brier'] for k in common]
    n=len(delta);mean=sum(delta)/n if n else 0.
    se=sqrt(sum((d-mean)**2 for d in delta)/(n-1)/n) if n>1 else 1.
    return {'n':n,'unpaired_old':len(a)-n,'unpaired_new':len(b)-n,'improvement':mean,'interval':[mean-1.96*se,mean+1.96*se],
            'recommendation':'ROLLBACK' if n>=policy.min_holdout and mean+1.96*se<0 else
                             'REVIEW_PROMOTION' if n>=policy.min_holdout and mean-1.96*se>0 else 'KEEP_SHADOW'}
