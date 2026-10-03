"""Declared chronological baseline/SoS/count comparison; never a release token.

CSV receipt times are unknown. We assume previous-day availability and exclude
all same-day results. Both model parameters and calibrators freeze before TEST.
Previously viewed TEST outcomes remain exploratory even after a new split.
"""
from collections import Counter
from dataclasses import replace, asdict
from datetime import datetime, timedelta, timezone
from itertools import groupby
from math import log, sqrt
from pathlib import Path
import json

from .contracts import digest, strict, time
from .engine import code_hash,model_code_hash
from .evaluation import metrics
from .goal_model import fit_goal_model, frozen_schedule, estimate as estimate_sos
from .markets import DEFAULT_POOL, market_of, probabilities, settle, payoff_ev
from .probability import estimate as estimate_baseline, fit_calibrator, calibrate, grade_stress, ev_bounds
from .research import load_csvs


def _history(row, profile):
    return {'id': row['id'], 'home': row['home'], 'away': row['away'], 'league': row['league'],
            'competition_profile': profile, 'kickoff': row['date']+'T12:00:00+00:00',
            'finished_at': row['date']+'T22:00:00+00:00',
            'received_at': row['date']+'T23:00:00+00:00', 'home_goals': row['home_goals'],
            'away_goals': row['away_goals'], 'source_id': 'historical-csv'}


def _sports(row, history, profile):
    return {'match': {'id': row['id'], 'home': row['home'], 'away': row['away'],
                      'league': row['league'], 'competition_profile': profile,
                      'kickoff': row['date']+'T12:00:00+00:00', 'sport': 'football', 'format': 'REGULATION_90'},
            'as_of': row['date']+'T00:00:00+00:00', 'synthetic': False, 'evidence': [],
            'history': history, 'sources': [{'id': 'historical-csv', 'independence_group': 'csv',
                                          'reliability': .9, 'enabled': True}]}


def validate_design(rows, data, design, policy):
    strict(design, ('version','profile','warmup_seasons','train_seasons','count_calibration_season',
                   'count_calibration_fraction','test_seasons','test_already_viewed','primary_market',
                   'policy_hash','sources','monetary_permission'))
    if design['version'] != 'p0-upgrade-design-v1' or design['monetary_permission'] is not False:
        raise ValueError('research-only declared design required')
    if policy.goal_model != 'SOS_THRESHOLD_V2' or policy.stress_mode != 'GRADED' or design['policy_hash'] != policy.fingerprint:
        raise ValueError('declared model/policy fingerprint mismatch')
    if design['profile'] not in ('MEN','WOMEN','RESERVE','LOWER') or type(design['test_already_viewed']) is not bool:
        raise ValueError('explicit known profile and TEST visibility required')
    if design['primary_market'] not in {market_of(m).key for m in DEFAULT_POOL}:
        raise ValueError('primary market must belong to predeclared main pool')
    if design['count_calibration_fraction'] != .5:
        raise ValueError('count/calibration day split fixed at one half')
    roles = (design['warmup_seasons'], design['train_seasons'],
             [design['count_calibration_season']], design['test_seasons'])
    if any(not role for role in roles) or any(max(a)>=min(b) for a,b in zip(roles,roles[1:])):
        raise ValueError('ordered disjoint seasons required')
    if {s for role in roles for s in role} != set(data['seasons']):
        raise ValueError('all dataset seasons must be assigned in advance')
    actual = {s['file']:s['sha256'] for s in data['sources']}
    expected = {s['file']:s['sha256'] for s in design['sources']}
    if actual != expected or len(expected)!=len(design['sources']):
        raise ValueError('source hash manifest mismatch')
    cal_days = sorted({r['date'] for r in rows if r['season']==design['count_calibration_season']})
    if len(cal_days)<2:
        raise ValueError('distinct count-fit and market-calibration dates required')
    boundary = cal_days[len(cal_days)//2]
    return {r['id']: ('WARMUP' if r['season'] in roles[0] else 'TRAIN' if r['season'] in roles[1]
                      else 'COUNT_CALIBRATION' if r['season'] in roles[2] and r['date']<boundary
                      else 'MARKET_CALIBRATION' if r['season'] in roles[2] else 'TEST') for r in rows}


def _fit_sports(rows, design):
    end = max(r['date'] for r in rows)
    cutoff = (datetime.fromisoformat(end).replace(tzinfo=timezone.utc)+timedelta(days=1)).isoformat()
    sport = _sports(rows[-1], [_history(r,design['profile']) for r in rows],design['profile'])
    sport['as_of'] = cutoff
    sport['match']['id'] = 'PROFILE_FIT_NOT_A_FIXTURE'
    return sport


def _count_scores(vectors, outcomes):
    n = len(vectors)
    return {'n':n, 'brier':sum(sum((p-int(i==y))**2 for i,p in enumerate(vector))/2
                             for vector,y in zip(vectors,outcomes))/n,
            'log_loss':-sum(log(max(vector[y],1e-15)) for vector,y in zip(vectors,outcomes))/n}


def _comparison(rows, key, new_field='probabilities', old_field='probabilities'):
    deltas=[]
    for r in rows:
        y=('WIN','PUSH','LOSS').index(r['markets'][key]['outcome'])
        new=r['markets'][key]['candidate'][new_field];old=r['markets'][key]['baseline'][old_field]
        deltas.append(sum((p-int(i==y))**2 for i,p in enumerate(new))/2
                      -sum((p-int(i==y))**2 for i,p in enumerate(old))/2)
    n=len(deltas);mean=sum(deltas)/n
    se=sqrt(sum((d-mean)**2 for d in deltas)/(n-1)/n) if n>1 else 1.
    return {'n':n,'candidate_minus_baseline_brier':mean,'descriptive_interval':[mean-1.96*se,mean+1.96*se],
            'interval_note':'Normal approximation, fixture dependence not corrected; not release proof.'}


def benchmark_upgrade(paths, design, output_dir, policy):
    destination=Path(output_dir)
    if destination.exists():
        raise ValueError('preserve prior benchmark; output directory already exists')
    rows,data=load_csvs(paths);split=validate_design(rows,data,design,policy)
    profile=design['profile'];baseline_policy=replace(policy,goal_model='BASELINE_V1',stress_mode='STRICT')
    training=[r for r in rows if split[r['id']]=='TRAIN'];training_sports=_fit_sports(training,design)
    training_artifact=fit_goal_model(training_sports,[],policy,training_sports['as_of'],model_code_hash())
    schedule=frozen_schedule([_history(r,profile) for r in rows],policy)
    history=[];count_records=[];market_records={'baseline':[],'candidate':[]}
    count_artifact=None;calibrators={};test_rows=[];last_count_receipt=None;last_cal_receipt=None
    for _, day in groupby(rows,key=lambda r:r['date']):
        batch=list(day)
        role=split[batch[0]['id']]
        if any(split[r['id']]!=role for r in batch):
            raise ValueError('same-day fixtures cannot cross dataset splits')
        if role=='MARKET_CALIBRATION' and count_artifact is None:
            count_artifact=fit_goal_model(training_sports,count_records,policy,last_count_receipt,model_code_hash())
        if role=='TEST' and not calibrators:
            if count_artifact is None or not all(market_records.values()):
                raise ValueError('count and market calibration must precede TEST')
            calibrators={name:fit_calibrator(records,model_code_hash(),
                         baseline_policy.fingerprint if name=='baseline' else policy.fingerprint,last_cal_receipt)
                         for name,records in market_records.items()}
        for r in batch:
            if role in ('WARMUP','TRAIN'):
                continue
            sport=_sports(r,history,profile)
            if role=='COUNT_CALIBRATION':
                _,_,info=estimate_sos(sport,policy,training_artifact,schedule=schedule)
                for side in ('home','away'):
                    count_records.append({'match_id':r['id'],'league':r['league'],'competition_profile':profile,
                        'side':side,'rate':info['rates'][side],'goals':r[side+'_goals'],'predicted_at':sport['as_of'],
                        'kickoff':sport['match']['kickoff'],'received_at':r['date']+'T23:00:00+00:00',
                        'synthetic':False,'reconstructed':True})
                last_count_receipt=r['date']+'T23:00:00+00:00'
                continue
            base_mass,base_variants,base_info=estimate_baseline(sport,baseline_policy)
            new_mass,new_variants,new_info=estimate_sos(sport,policy,count_artifact,schedule=schedule)
            models={'baseline':(base_mass,base_variants,base_info,baseline_policy),
                    'candidate':(new_mass,new_variants,new_info,policy)}
            markets={}
            for contract in DEFAULT_POOL:
                m=market_of(contract);outcome=settle(m,r['home_goals'],r['away_goals']);values={}
                for name,(mass,variants,info,model_policy) in models.items():
                    raw=list(probabilities(m,mass))
                    if role=='MARKET_CALIBRATION':
                        market_records[name].append({'match_id':r['id'],'market':m.key,'kind':m.kind,
                            'competition_profile':profile,'raw_win':raw[0],'outcome':outcome,
                            'received_at':r['date']+'T23:00:00+00:00','synthetic':False,
                            'goal_model_hash':count_artifact['hash'] if name=='candidate' else None})
                    cal=calibrate(m,raw,calibrators.get(name),model_policy,profile)
                    values[name]={'raw':raw,'probabilities':cal['base'],'calibration_status':cal['status'],'calibration_n':cal['n']}
                    if role=='TEST' and m.kind=='1X2' and 'B365' in r['prices']:
                        odds=r['prices']['B365'][0];ev=payoff_ev(cal['base'][0],cal['base'][1],odds)
                        stress_raw=[probabilities(m,v) for v in variants]
                        stress_cal=[calibrate(m,p,calibrators[name],model_policy,profile) for p in stress_raw]
                        stress_probs=[p['base'] for p in stress_cal] if model_policy.stress_mode=='GRADED' else stress_raw
                        stress=min(payoff_ev(p[0],p[1],odds) for p in stress_probs)
                        stress_fitted=all(p['status']=='CALIBRATED_BIN' for p in stress_cal)
                        low_ev,_=ev_bounds(cal['low'],cal['high'],odds)
                        values[name]['quote_diagnostic']={'odds':odds,'base_ev':ev,'stress_min':stress,
                            'stress_class':grade_stress(ev,stress,model_policy.min_ev)['class'],
                            'epistemic_low_ev':low_ev,'strict_stress_candidate':ev>=policy.min_ev and stress>=0,
                            'graded_stress_candidate':ev>=policy.min_ev and stress>=policy.aggressive_stress_floor and low_ev>=policy.min_low_ev and stress_fitted,
                            'stress_calibration_fitted':stress_fitted,
                            'unit_payoff':odds-1 if outcome=='WIN' else 0 if outcome=='PUSH' else -1,
                            'monetary_permission':False}
                markets[m.key]={'outcome':outcome,**values}
            if role=='MARKET_CALIBRATION':
                last_cal_receipt=r['date']+'T23:00:00+00:00'
            else:
                test_rows.append({'id':r['id'],'date':r['date'],'home_goals':r['home_goals'],'away_goals':r['away_goals'],
                                  'rates':{name:info['rates'] for name,(_,_,info,_) in models.items()},
                                  'thresholds':{name:info['goal_thresholds'] for name,(_,_,info,_) in models.items()},
                                  'used_history':new_info['used_history'],'markets':markets})
        # No result from this batch can enter any prediction in the same batch.
        history.extend(_history(r,profile) for r in batch)
    if not test_rows:
        raise ValueError('nonempty held-out TEST required')
    by_market={}
    for key in test_rows[0]['markets']:
        outcomes=[('WIN','PUSH','LOSS').index(r['markets'][key]['outcome']) for r in test_rows]
        by_market[key]={name:metrics([r['markets'][key][name]['probabilities'] for r in test_rows],outcomes)
                       for name in ('baseline','candidate')}
        by_market[key]['paired']=_comparison(test_rows,key)
    counts={}
    for side in ('home','away'):
        ys=[min(3,r[side+'_goals']) for r in test_rows]
        counts[side]={}
        for name in ('baseline','candidate'):
            ts=[r['thresholds'][name][side] for r in test_rows]
            vectors=[[t['p0'],t['p1'],t['p2_plus']-t['p3_plus'],t['p3_plus']] for t in ts]
            counts[side][name]=_count_scores(vectors,ys)
    groups={}
    for name in ('baseline','candidate'):
        observations=[r['markets']['1X2:HOME'][name].get('quote_diagnostic') for r in test_rows]
        observations=[o for o in observations if o]
        groups[name]={}
        for label in sorted({o['stress_class'] for o in observations}):
            cohort=[o for o in observations if o['stress_class']==label]
            groups[name][label]={'n':len(cohort),'mean_base_ev':sum(o['base_ev'] for o in cohort)/len(cohort),
                                'mean_quote_payoff':sum(o['unit_payoff'] for o in cohort)/len(cohort),
                                'strict_candidate_n':sum(o['strict_stress_candidate'] for o in cohort),
                                'graded_candidate_n':sum(o['graded_stress_candidate'] for o in cohort),
                                'record_kind':'QUOTED_1X2_HOME_DIAGNOSTIC_NOT_EXECUTION'}
    result={'status':'HISTORICAL_HOLDOUT_ALREADY_VIEWED' if design['test_already_viewed'] else 'RECONSTRUCTED_HISTORICAL_HOLDOUT',
            'can_certify_release':False,'monetary_permission':False,'promotion':'KEEP_SHADOW',
            'code_hash':code_hash(),'model_hash':model_code_hash(),'policy':asdict(policy),'policy_hash':policy.fingerprint,'design_hash':digest(design),
            'dataset':data,'split_counts':dict(Counter(split.values())),
            'artifact_hash':count_artifact['hash'],'calibrator_hashes':{k:a['hash'] for k,a in calibrators.items()},
            'comparison':_comparison(test_rows,design['primary_market']),
            'primary_market':design['primary_market'],'market_metrics':by_market,'count_metrics':counts,
            'stress_cohorts':groups,'predictions':test_rows,
            'limitations':['Receipt and kickoff times above are labelled research assumptions, not captured provenance.',
                'No same-day target outcome enters sporting features; prior TEST results can enter subsequent dates.',
                'TRAIN priors, count bins, policy and market calibrators freeze before TEST; no TEST-based tuning.',
                'Already viewed outcomes and reconstructed prices cannot establish prospective efficacy.',
                'No verified lineups, tactics, injuries or executable team-total prices; admissions are not simulated BETs.',
                'Count 3+ retains conditional Poisson tail; overdispersion and player effects remain P1.']}
    result['run_id']=digest(result)
    destination.mkdir(parents=True)
    for name,value in (('BENCHMARK.json',result),('GOAL_MODEL.json',count_artifact),('CALIBRATORS.json',calibrators),('DESIGN.json',design)):
        with (destination/name).open('x',encoding='utf-8') as file:
            json.dump(value,file,ensure_ascii=False,indent=2,allow_nan=False)
    return result
