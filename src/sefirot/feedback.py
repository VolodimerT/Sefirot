"""Chronicler metrics and contextual Competence; results never rewrite decisions."""
from __future__ import annotations
from collections import defaultdict
from datetime import timezone
from math import fsum, sqrt
from random import Random
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
    """Exploratory paired comparison; event-market rows are not independent games.

    Keep legacy row counters, but average common markets within each fixture and
    resample whole UTC kickoff days. This reuses the read-only calibration audit's
    2,000 draws/minimum eight days; it never certifies a new holdout or model.
    """
    key=lambda r:(r['match_id'],r['market'])
    a={key(r):r for r in old};b={key(r):r for r in new};common=sorted(set(a)&set(b))
    if len(a)!=len(old) or len(b)!=len(new):raise ValueError('duplicate paired records')
    if any(a[k]['outcome']!=b[k]['outcome'] for k in common):raise ValueError('paired outcomes disagree')
    if any(a[k].get('competition_profile','UNKNOWN')!=b[k].get('competition_profile','UNKNOWN') for k in common):raise ValueError('paired competition profiles disagree')
    per_fixture=defaultdict(list);kickoffs={};missing_dates=set()
    for k in common:
        mid=k[0]
        per_fixture[mid].append(number(a[k]['brier'],'old Brier',0,1)-number(b[k]['brier'],'new Brier',0,1))
        stamps=[time(row['kickoff']) if row.get('kickoff') is not None else None for row in (a[k],b[k])]
        if None in stamps:missing_dates.add(mid)
        if all(stamp is not None for stamp in stamps) and stamps[0]!=stamps[1]:
            raise ValueError('paired kickoffs disagree')
        for stamp in stamps:
            if stamp is not None:
                if mid in kickoffs and kickoffs[mid]!=stamp:raise ValueError('fixture kickoffs disagree')
                kickoffs[mid]=stamp
    means={mid:fsum(values)/len(values) for mid,values in sorted(per_fixture.items())}
    fixtures=len(means);n=len(common);mean=fsum(means.values())/fixtures if fixtures else 0.
    clusters=defaultdict(list)
    for mid,value in means.items():
        if mid not in missing_dates:
            clusters[kickoffs[mid].astimezone(timezone.utc).date().isoformat()].append(value)
    interval=None;limitations=[]
    if fixtures<policy.min_holdout:limitations.append('HOLDOUT_FIXTURES_TOO_SMALL')
    if missing_dates:limitations.append('KICKOFF_DATE_UNAVAILABLE')
    if len(clusters)<8:limitations.append('UTC_DATE_BLOCKS_TOO_SMALL')
    # The existing audit only reports this interval from >=30 fixtures/8 days.
    # Policy.min_holdout is an additional independent FIXTURE threshold below.
    if fixtures>=30 and len(clusters)>=8 and not missing_dates:
        groups=[clusters[k] for k in sorted(clusters)];rng=Random(20261008);samples=[]
        for _ in range(2000):
            drawn=[groups[rng.randrange(len(groups))] for _ in groups]
            samples.append(fsum(fsum(group) for group in drawn)/sum(map(len,drawn)))
        samples.sort();interval=[samples[49],samples[1949]]
    recommendation='KEEP_SHADOW'
    if fixtures>=policy.min_holdout and interval is not None:
        if interval[1]<0:recommendation='ROLLBACK'
        elif interval[0]>0:recommendation='REVIEW_PROMOTION'
    return {'n':n,'paired_market_rows':n,'unpaired_old':len(a)-n,'unpaired_new':len(b)-n,
            'distinct_fixtures':fixtures,'date_blocks':len(clusters),'fixtures_missing_kickoff':len(missing_dates),
            'improvement':mean,'interval':interval,'recommendation':recommendation,
            'interval_method':'exploratory paired UTC-day cluster bootstrap',
            'interval_replicates':2000 if interval is not None else 0,
            'unit':'per-fixture average delta Brier across common markets',
            'minimum_holdout_fixtures':policy.min_holdout,'minimum_interval_fixtures':30,
            'minimum_interval_date_blocks':8,'limitations':limitations,
            'certifies_model':False,'independent_holdout_verified':False}


def validate_stress_classes(records, policy):
    """Independent monetary gate for each grade; includes previously refused quotes.

    Quote returns are diagnostic payoffs, not executed profit. A favourable base
    EV or winning PASS cannot waive chronology, calibration or sample checks.
    """
    output = {}
    for label in ('ROBUST_VALUE', 'FRAGILE_VALUE', 'AGGRESSIVE_VALUE'):
        rows = sorted([r for r in records if r['stress_class'] == label],
                      key=lambda r: (time(r['kickoff']), r['match_id']))
        reasons = []
        n = len(rows)
        if n < policy.min_holdout:
            reasons.append('CLASS_HOLDOUT_TOO_SMALL')
        report = summary(rows)
        returns = [r['unit_return'] for r in rows]
        delta = [r['brier']-r['baseline_brier'] for r in rows]
        interval = lambda values: _mean_interval(values)
        profit_interval = interval(returns)
        score_interval = interval(delta)
        if not rows or profit_interval[0] <= 0:
            reasons.append('CLASS_POSITIVE_RETURN_UNPROVEN')
        if not rows or score_interval[1] >= 0:
            reasons.append('CLASS_BASELINE_IMPROVEMENT_UNPROVEN')
        halves = (rows[:n//2], rows[n//2:])
        if not all(half and sum(r['unit_return'] for r in half)>0
                   and sum(r['brier']-r['baseline_brier'] for r in half)<0 for half in halves):
            reasons.append('CLASS_PERIOD_STABILITY_FAILED')
        if rows and max(report['calibration_error'], report['multiclass']['ece_macro']) > policy.max_calibration_error:
            reasons.append('CLASS_CALIBRATION_ERROR_HIGH')
        if rows and report['multiclass']['log_loss'] >= sum(r['baseline_log_loss'] for r in rows)/n:
            reasons.append('CLASS_LOGLOSS_BASELINE_NOT_BEATEN')
        if any(r['synthetic'] or not r['captured_prematch'] for r in rows):
            reasons.append('CLASS_RECONSTRUCTED_OR_SYNTHETIC')
        if any(r['calibration_status'] != 'CALIBRATED_BIN' for r in rows):
            reasons.append('CLASS_UNCALIBRATED')
        if any(not r['sports_gates_passed'] for r in rows):
            reasons.append('CLASS_SPORTS_GATES_FAILED')
        if any(r['ev_low'] < policy.min_low_ev for r in rows):
            reasons.append('CLASS_EPISTEMIC_VALUE_FAILED')
        output[label] = {'n': n, 'passed': not reasons, 'reasons': reasons,
                         'ids': [r['match_id'] for r in rows],
                         'return_interval': profit_interval, 'brier_delta_interval': score_interval,
                         'mean_ev': sum(r['ev'] for r in rows)/n if n else None,
                         'metrics': report, 'return_kind': 'PREDECLARED_QUOTE_UNIT_PAYOFF_NOT_EXECUTION'}
    return output


def _mean_interval(values):
    if not values:
        return [None, None]
    n = len(values)
    mean = sum(values)/n
    se = sqrt(sum((v-mean)**2 for v in values)/(n-1)/n) if n>1 else 1.
    return [mean-1.96*se, mean+1.96*se]
