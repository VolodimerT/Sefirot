"""Predeclared paired diagnostics; never a model promotion or money approval.

JSON hashes detect corruption, not forged timestamps. External original receipt
verification and immutable cohort registration remain an integration gate.
"""
from collections import defaultdict
from datetime import timedelta
from math import fsum, log
from random import Random

from sefirot.contracts import digest, integer, number, strict, text, time
from sefirot.markets import Market, market_from_key, probabilities, settle
from .models import MODELS

CONTRACTS = ('1X2', 'DOUBLE_CHANCE:1X', 'DNB:HOME', 'HANDICAP:HOME:-1',
             'TOTAL:OVER:2.5', 'BTTS:YES', 'TEAM_TOTAL:HOME_OVER:1.5')


def simplex(p, length):
    if not isinstance(p, (list, tuple)) or len(p) != length:
        raise ValueError('probability vector shape')
    for v in p: number(v,'probability',0,1)
    if abs(fsum(p)-1) > 1e-9: raise ValueError('probabilities must sum to one')
    return p


def project(mass):
    if not mass: raise ValueError('empty score mass')
    for score,p in mass.items():
        if not isinstance(score,tuple) or len(score)!=2: raise ValueError('score pair required')
        for g in score: integer(g,'goals',0,50)
        number(p,'score probability',0,1)
    if abs(fsum(mass.values())-1)>1e-9: raise ValueError('invalid mass')
    return {'1X2':[fsum(p for (h,a),p in mass.items() if condition(h,a))
                   for condition in (lambda h,a:h>a,lambda h,a:h==a,lambda h,a:h<a)],
            **{key:list(probabilities(market_from_key(key),mass)) for key in CONTRACTS[1:]}}


def outcome(key, goals):
    h,a = goals
    for g in goals: integer(g,'result goals',0,50)
    return (0 if h>a else 1 if h==a else 2) if key=='1X2' else ('WIN','PUSH','LOSS').index(settle(market_from_key(key),h,a))


def proper_scores(p, y):
    simplex(p,3); integer(y,'category',0,2)
    return {'brier':fsum((v-float(i==y))**2 for i,v in enumerate(p)),
            'log_loss':-log(max(p[y],1e-15))}


def reliability(pairs):
    """One-vs-rest class reliability; bins are diagnostics, not fitted models."""
    output = []
    for category in range(3):
        bins = []
        for b in range(5):
            members = [(p[category],int(y==category)) for p,y in pairs
                       if min(4,int(p[category]*5)) == b]
            n = len(members)
            bins.append({'bin':b,'n':n,'mean_p':fsum(p for p,_ in members)/n if n else None,
                         'frequency':fsum(y for _,y in members)/n if n else None})
        ece = fsum(b['n']*abs(b['mean_p']-b['frequency']) for b in bins if b['n'])/len(pairs) if pairs else None
        output.append({'class':category,'ece':ece,'bins':bins})
    return output


def paired_interval(values, *, resamples=1000, seed=212):
    """values = [(UTC kickoff date, candidate loss - baseline loss), ...]."""
    integer(resamples,'resamples',100)
    groups = defaultdict(list)
    for day,delta in values: number(delta,'delta'); groups[day].append(delta)
    if len(groups)<2: return None
    rng = Random(seed); days = sorted(groups); samples=[]
    for _ in range(resamples):
        sample=[v for day in rng.choices(days,k=len(days)) for v in groups[day]]
        samples.append(fsum(sample)/len(sample))
    samples.sort()
    return [samples[int(.025*resamples)],samples[min(resamples-1,int(.975*resamples))]]


def validate_manifest(m):
    strict(m,('schema','registered_at','training_ids','calibration_ids','viewed_test_ids',
              'members','models','contracts','primary','research_hash','policy_hash'))
    if m['schema']!='edge-v3-manifest-v1' or m['models']!=list(MODELS) or m['contracts']!=list(CONTRACTS):
        raise ValueError('fixed experiment schema/models/contracts required')
    if m['primary'] != '1X2:raw:log_loss': raise ValueError('primary metric changed')
    text(m['research_hash'],'research hash'); text(m['policy_hash'],'policy hash')
    sets=[]
    for key in ('training_ids','calibration_ids','viewed_test_ids'):
        ids=m[key]
        if not isinstance(ids,list) or any(not isinstance(i,str) or not i for i in ids) or len(set(ids))!=len(ids):
            raise ValueError('invalid split IDs')
        sets.append(set(ids))
    if any(sets[i]&sets[j] for i in range(3) for j in range(i)): raise ValueError('split overlap')
    ids=set()
    for member in m['members']:
        strict(member,('id','kickoff','league','profile'))
        for key in ('id','league'): text(member[key],key)
        if member['profile'] not in ('MEN','WOMEN','LOWER','RESERVE','UNKNOWN'): raise ValueError('profile')
        if member['id'] in ids or any(member['id'] in s for s in sets): raise ValueError('holdout overlap/duplicate')
        if time(member['kickoff'])<=time(m['registered_at']): raise ValueError('retroactive holdout')
        ids.add(member['id'])
    return {member['id']:member for member in m['members']}


def evaluate(manifest, forecasts, results, *, as_of):
    members=validate_manifest(manifest); predictions={}; resolved={}
    if time(as_of)<time(manifest['registered_at']): raise ValueError('evaluation before registration')
    manifest_hash=digest(manifest)
    for f in forecasts:
        strict(f,('fixture_id','sealed_at','manifest_hash','research_hash','policy_hash','models','synthetic','hash'))
        body=dict(f); signature=body.pop('hash')
        if signature!=digest(body): raise ValueError('forecast seal mismatch')
        mid=f['fixture_id']
        if mid not in members or mid in predictions: raise ValueError('unassigned/duplicate forecast')
        if f['manifest_hash']!=manifest_hash or f['research_hash']!=manifest['research_hash'] or f['policy_hash']!=manifest['policy_hash']:
            raise ValueError('manifest/code/policy mismatch')
        if not time(manifest['registered_at'])<=time(f['sealed_at'])<time(members[mid]['kickoff']) or time(f['sealed_at'])>time(as_of): raise ValueError('forecast chronology')
        if type(f['synthetic']) is not bool or set(f['models'])!=set(MODELS): raise ValueError('model/provenance mismatch')
        for model,versions in f['models'].items():
            if versions is None: continue  # explicit abstention
            strict(versions,('raw','calibrated'))
            for variant,contracts in versions.items():
                if contracts is None: continue
                if set(contracts)!=set(CONTRACTS): raise ValueError('partial contract universe')
                for key,p in contracts.items():
                    simplex(p,3)
                    if key!='1X2' and not market_from_key(key).push_possible and p[1]!=0:
                        raise ValueError('impossible PUSH')
        predictions[mid]=f
    for r in results:
        strict(r,('fixture_id','finished_at','received_at','goals','status','receipt_sha'))
        mid=r['fixture_id']
        if mid not in members or mid in resolved: raise ValueError('unassigned/duplicate/revised result')
        if not time(members[mid]['kickoff'])<time(r['finished_at'])<=time(r['received_at'])<=time(as_of): raise ValueError('result chronology')
        if r['status'] not in ('FT','VOID'): raise ValueError('nonfinal regulation result')
        if not isinstance(r['receipt_sha'],str) or len(r['receipt_sha'])!=64 or any(c not in '0123456789abcdef' for c in r['receipt_sha']): raise ValueError('result receipt missing')
        if r['status']=='FT':
            if time(r['finished_at']) < time(members[mid]['kickoff'])+timedelta(minutes=90):
                raise ValueError('premature regulation FT result')
            if not isinstance(r['goals'],list) or len(r['goals'])!=2: raise ValueError('FT score missing')
            outcome('1X2',r['goals'])
        elif r['goals'] is not None: raise ValueError('VOID cannot have scored goals')
        resolved[mid]=r
    scorecards=[]
    # Also emit every observed league/profile context without pooling them.
    contexts=[None]+sorted({(v['league'],v['profile']) for v in members.values()})
    for context in contexts:
        assigned=[mid for mid,m in members.items() if context is None or (m['league'],m['profile'])==context]
        for variant in ('raw','calibrated'):
            for key in CONTRACTS:
                by_model={model:{} for model in MODELS}
                for mid in assigned:
                    if mid not in predictions or mid not in resolved or resolved[mid]['status']!='FT': continue
                    y=outcome(key,resolved[mid]['goals'])
                    for model,versions in predictions[mid]['models'].items():
                        if versions is not None and versions[variant] is not None:
                            p=versions[variant][key]; by_model[model][mid]=(proper_scores(p,y),p,y)
                paired=set.intersection(*(set(v) for v in by_model.values()))
                for model,items in by_model.items():
                    metrics={metric:fsum(v[0][metric] for v in items.values())/len(items) if items else None for metric in ('brier','log_loss')}
                    paired_metrics={metric:fsum(items[mid][0][metric] for mid in paired)/len(paired) if paired else None for metric in metrics}
                    delta={}
                    for metric in metrics:
                        differences=[(time(members[mid]['kickoff']).date().isoformat(),items[mid][0][metric]-by_model['BASELINE_V1'][mid][0][metric]) for mid in sorted(paired)]
                        delta[metric]={'mean':fsum(d for _,d in differences)/len(differences) if differences else None,
                                       'date_cluster_95_interval':paired_interval(differences)}
                    scorecards.append({'context':context,'variant':variant,'contract':key,'model':model,
                                       'assigned':len(assigned),'scored':len(items),'paired_n':len(paired),
                                       'coverage':len(items)/len(assigned) if assigned else None,
                                       'metrics':metrics,'paired_metrics':paired_metrics,
                                       'paired_date_clusters':len({time(members[mid]['kickoff']).date() for mid in paired}),
                                       'unscored':len(assigned)-len(items), 'paired_delta':delta,
                                       'reliability':reliability([(p,y) for _,p,y in items.values()])})
    return {'schema':'edge-v3-benchmark-v1','status':'KEEP_SHADOW','manifest_hash':manifest_hash,
            'assigned':len(members),'forecasts':len(predictions),'results':len(resolved),
            'void':sum(r['status']=='VOID' for r in resolved.values()),
            'synthetic':any(f['synthetic'] for f in predictions.values()),
            'source_authentication':'NOT_VERIFIED_BY_THIS_MODULE',
            'proven_superiority':False,'monetary_permission':False,'scorecards':scorecards}
