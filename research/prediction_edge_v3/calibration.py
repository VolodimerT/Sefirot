"""Experimental score-temperature calibration; preserves market coherence.

Fit only on a disjoint CALIBRATION cohort, primary 1X2 log loss. The fixed grid
is deliberately small. This is a hypothesis, not a validated calibration gain.
"""
from math import exp, log, fsum
from datetime import timedelta
from sefirot.contracts import digest, time, strict
from .benchmark import project, proper_scores, outcome
from .models import research_hash

TEMPERATURES=(.8,.9,1.,1.1,1.2)


def transform(mass, temperature):
    project(mass)
    if temperature not in TEMPERATURES: raise ValueError('unregistered temperature')
    logs={score:log(p)/temperature for score,p in mass.items() if p>0}
    peak=max(logs.values()); weights={score:exp(v-peak) for score,v in logs.items()}
    total=fsum(weights.values())
    return {score:weights.get(score,0.)/total for score in mass}


def fit_temperature(records, *, calibration_ids, training_ids, holdout_ids, fit_at, model_hash):
    groups=[set(ids) for ids in (calibration_ids,training_ids,holdout_ids)]
    if any(len(set(ids))!=len(ids) for ids in (calibration_ids,training_ids,holdout_ids)) or any(groups[i]&groups[j] for i in range(3) for j in range(i)):
        raise ValueError('calibration split overlap/duplicate')
    ids=set(); synthetic=False
    for r in records:
        strict(r,('fixture_id','model_hash','sealed_at','kickoff','finished_at','received_at','mass','goals','synthetic'))
        if r['fixture_id'] in ids or r['fixture_id'] not in groups[0]: raise ValueError('noncalibration/duplicate record')
        ids.add(r['fixture_id'])
        if r['model_hash']!=model_hash or not time(r['sealed_at'])<time(r['kickoff'])<time(r['finished_at'])<=time(r['received_at'])<=time(fit_at):
            raise ValueError('calibration model/chronology mismatch')
        if time(r['finished_at'])<time(r['kickoff'])+timedelta(minutes=90): raise ValueError('premature FT calibration result')
        if type(r['synthetic']) is not bool: raise ValueError('provenance required')
        synthetic=synthetic or r['synthetic']; project(r['mass']); outcome('1X2',r['goals'])
    a={'schema':'score-temperature-v1','fit_at':fit_at,'model_hash':model_hash,
       'research_hash':research_hash(),'fit_ids':sorted(ids),'assigned':len(calibration_ids),
       'synthetic':synthetic,'temperature':None,'status':'INSUFFICIENT_CALIBRATION',
       'monetary_permission':False,'input_digest':digest([
           {**r,'mass':[[h,a,p] for (h,a),p in sorted(r['mass'].items())]} for r in records])}
    if len(ids)>=60 and len(ids)/max(1,len(calibration_ids))>=.8:
        losses={t:fsum(proper_scores(project(transform(r['mass'],t))['1X2'],outcome('1X2',r['goals']))['log_loss'] for r in records)/len(records) for t in TEMPERATURES}
        a['temperature']=min(TEMPERATURES,key=lambda t:(losses[t],abs(t-1)))
        a['status']='FITTED_SHADOW'
    a['hash']=digest(a)
    return a


def apply_temperature(artifact, mass, *, fixture_id, as_of, model_hash):
    body=dict(artifact);signature=body.pop('hash',None)
    if signature!=digest(body) or artifact['research_hash']!=research_hash() or artifact['model_hash']!=model_hash:
        raise ValueError('calibrator integrity/model mismatch')
    if fixture_id in artifact['fit_ids'] or time(artifact['fit_at'])>=time(as_of): raise ValueError('calibration leakage')
    if artifact['status']!='FITTED_SHADOW': return None
    return transform(mass,artifact['temperature'])
