"""Reproducible retrospective football benchmark, isolated from monetary admission.

CSV dates are dates, not fabricated receipt timestamps. All same-day fixtures are
predicted before updating any of their results. Historical availability is an
explicit assumption, so even a strong benchmark NEVER creates a release token.
"""
from collections import Counter
from datetime import datetime
from itertools import groupby,product
from pathlib import Path
from math import sqrt,log,exp
import csv
import hashlib
import json
from .contracts import digest,number
from .evaluation import metrics,devig,log_loss


def load_csvs(paths):
    rows=[];sources=[];seen=set()
    for path in paths:
        path=Path(path);raw=path.read_bytes();source_hash=hashlib.sha256(raw).hexdigest()
        sources.append({'file':path.name,'sha256':source_hash,'bytes':len(raw)})
        for r in csv.DictReader(raw.decode('utf-8-sig').splitlines()):
            if not r.get('Date'):continue
            required=('Div','HomeTeam','AwayTeam','FTHG','FTAG','FTR')
            if any(not r.get(k) for k in required):raise ValueError('missing match fields')
            try:day=datetime.strptime(r['Date'],'%d/%m/%Y').date()
            except ValueError:day=datetime.strptime(r['Date'],'%d/%m/%y').date()
            h,a=int(r['FTHG']),int(r['FTAG']);outcome=0 if h>a else 1 if h==a else 2
            if min(h,a)<0 or r['FTR']!='HDA'[outcome] or r['HomeTeam']==r['AwayTeam']:raise ValueError('invalid result/teams')
            key=(r['Div'],day.isoformat(),r['HomeTeam'],r['AwayTeam'])
            if key in seen:raise ValueError('duplicate fixture')
            seen.add(key)
            season=day.year if day.month>=7 else day.year-1
            prices={}
            for prefix in ('B365','B365C','Avg','AvgC'):
                values=[r.get(prefix+s,'') for s in 'HDA']
                if all(values):prices[prefix]=[number(float(v),'odds',1.00000001) for v in values]
            rows.append({'id':digest(key),'league':r['Div'],'date':day.isoformat(),'season':season,
                         'home':r['HomeTeam'],'away':r['AwayTeam'],'home_goals':h,'away_goals':a,'y':outcome,
                         'prices':prices,'result_available_at':None,'odds_observed_at':None})
    if not rows or len({r['league'] for r in rows})!=1:raise ValueError('exactly one nonempty league required')
    rows.sort(key=lambda r:(r['date'],r['id']))
    return rows,{'sources':sorted(sources,key=lambda s:s['file']),'dataset_hash':digest(rows),'n':len(rows),
        'league':rows[0]['league'],'seasons':sorted({r['season'] for r in rows}),
        'availability':'UNKNOWN_HISTORICAL_TIMESTAMPS','promotable':False}


def elo_predictions(rows,k=20.,home=55.,draw=.8,regression=1.,legacy=False):
    ratings={};counts=[0,0,0];predictions={};current=None
    for date,day_rows in groupby(rows,key=lambda r:r['date']):
        batch=list(day_rows);season=batch[0]['season']
        if season!=current:
            ratings={t:1500+(v-1500)*regression for t,v in ratings.items()};current=season
        changes=Counter()
        for r in batch:
            rh=ratings.get(r['home'],1500.);ra=ratings.get(r['away'],1500.)
            strength=10**(max(-1600.,min(1600.,rh+home-ra))/400)
            conditional=strength/(1+strength)
            if legacy:
                pd=(20*.27+counts[1])/(20+sum(counts))*(1-.45*abs(2*conditional-1))
                p=[(1-pd)*conditional,pd,(1-pd)*(1-conditional)]
            else:
                tie=draw*sqrt(strength);den=strength+1+tie;p=[strength/den,tie/den,1/den]
            predictions[r['id']]=p
            expected=conditional if legacy else p[0]+.5*p[1]
            delta=k*((1.,.5,0.)[r['y']]-expected)
            changes[r['home']]+=delta;changes[r['away']]-=delta
        for team,delta in changes.items():ratings[team]=ratings.get(team,1500.)+delta
        for r in batch:counts[r['y']]+=1
    return predictions


def frequency_predictions(rows):
    counts=[1,1,1];output={}
    for _,batch in groupby(rows,key=lambda r:r['date']):
        batch=list(batch)
        for r in batch:output[r['id']]=[c/sum(counts) for c in counts]
        for r in batch:counts[r['y']]+=1
    return output


def temperature(p,t):
    number(t,'temperature',.01,100)
    x=[log(max(v,1e-15))/t for v in p];top=max(x);q=[exp(v-top) for v in x]
    return [v/sum(q) for v in q]


def _scores(rows,ps):return metrics([ps[r['id']] for r in rows],[r['y'] for r in rows])


def benchmark(paths,output):
    """Five chronological seasons: two train, tune, calibrate, untouched final test.
    Refuses overwriting an existing run. Params/grid/test choice fixed in code.
    """
    output=Path(output)
    if output.exists():raise ValueError('output already exists; preserve original test run')
    rows,data=load_csvs(paths);seasons=data['seasons']
    if len(seasons)!=5 or any(b!=a+1 for a,b in zip(seasons,seasons[1:])):raise ValueError('five consecutive seasons required')
    split={r['id']:('TRAIN' if r['season'] in seasons[:2] else 'TUNE' if r['season']==seasons[2] else 'CALIBRATE' if r['season']==seasons[3] else 'TEST') for r in rows}
    tune=[r for r in rows if split[r['id']]=='TUNE'];cal=[r for r in rows if split[r['id']]=='CALIBRATE'];test=[r for r in rows if split[r['id']]=='TEST']
    before_test=[r for r in rows if split[r['id']]!='TEST'];through_tune=[r for r in rows if split[r['id']] in ('TRAIN','TUNE')]
    trials=[]
    for k,home,draw,regression in product((10.,20.,40.),(40.,80.,120.),(.6,.8,1.),(.5,.8)):
        params={'k':k,'home':home,'draw':draw,'regression':regression}
        ps=elo_predictions(through_tune,**params)
        trials.append({'params':params,'tune_log_loss':sum(log_loss(ps[r['id']],r['y']) for r in tune)/len(tune)})
    selected=min(trials,key=lambda t:t['tune_log_loss']);params=selected['params']
    precal=elo_predictions(before_test,**params)
    temperatures=(.7,.85,1.,1.15,1.3,1.5)
    selected_t=min(temperatures,key=lambda t:sum(log_loss(temperature(precal[r['id']],t),r['y']) for r in cal))
    # Only now evaluate the held-out season; its outcomes never affect model selection.
    raw=elo_predictions(rows,**params);models={'historical_frequency':frequency_predictions(rows),'legacy_elo':elo_predictions(rows,legacy=True),
        'trained_davidson':raw,'calibrated_davidson':{key:temperature(p,selected_t) for key,p in raw.items()}}
    reports={name:_scores(test,ps) for name,ps in models.items()}
    market_rows=[r for r in test if 'Avg' in r['prices']]
    for method in ('proportional','power'):
        if market_rows:reports['market_preclose_'+method]=metrics([devig(r['prices']['Avg'],method) for r in market_rows],[r['y'] for r in market_rows])
    closing_rows=[r for r in test if 'AvgC' in r['prices']]
    if closing_rows:reports['market_closing_reference']=metrics([devig(r['prices']['AvgC']) for r in closing_rows],[r['y'] for r in closing_rows])
    # Paired comparisons always use exactly the same fixtures as available market data.
    paired={name:_scores(market_rows,ps) for name,ps in models.items()} if market_rows else {}
    monthly={month:_scores([r for r in test if r['date'][:7]==month],models['calibrated_davidson']) for month in sorted({r['date'][:7] for r in test})}
    bets=[];equity=0.;peak=0.;max_drawdown=0.
    for r in test:
        if 'B365' not in r['prices']:continue
        p=models['calibrated_davidson'][r['id']];odds=r['prices']['B365'];side=max(range(3),key=lambda i:p[i]*odds[i]-1)
        if p[side]*odds[side]-1<.02:continue
        pnl=odds[side]-1 if r['y']==side else -1.;equity+=pnl;peak=max(peak,equity);max_drawdown=max(max_drawdown,peak-equity)
        close=r['prices'].get('B365C')
        bets.append({'id':r['id'],'side':side,'stake':1.,'pnl':pnl,'ev':p[side]*odds[side]-1,
            'odds_clv':odds[side]/close[side]-1 if close else None,
            'fair_probability_movement':devig(close)[side]-devig(odds)[side] if close else None})
    clvs=[b['odds_clv'] for b in bets if b['odds_clv'] is not None]
    result={'status':'EXPERIMENTAL','monetary_permission':False,'dataset':data,'split_counts':dict(Counter(split.values())),
        'split_seasons':{'TRAIN':seasons[:2],'TUNE':seasons[2],'CALIBRATE':seasons[3],'TEST':seasons[4]},
        'features':['prior results','home advantage','season regression'],'initial_rating':1500,
        'initial_rating_note':'Common rating is an arbitrary origin, not an identifiable fitted parameter.',
        'selected':selected,'temperature':selected_t,'trials':trials,'test_metrics':reports,'paired_market_subset':paired,
        'monthly_calibrated':monthly,'model_selection_metric':'tuning log loss; calibration temperature uses separate season',
        'simulation':{'status':'RETROSPECTIVE_DIAGNOSTIC_ONLY','n':len(bets),'flat_stake':1.,'pnl_units':equity,'yield':equity/len(bets) if bets else None,
            'max_drawdown_units':max_drawdown,'clv_n':len(clvs),'mean_odds_clv':sum(clvs)/len(clvs) if clvs else None,'bets':bets},
        'limitations':['Historical receipt timestamps unknown; previous calendar-day results assumed available.',
            'CSV pre-closing price is not proven first opening or executable entry.',
            'No prospective validation, no transaction costs/limits, no monetary promotion.',
            'Calibration gives point probabilities, no claimed individual probability confidence interval.',
            'Hyperparameters and test season must not be retuned after inspecting this report.',
            'Online ratings update only after each full day; model parameters stay frozen.'],
        'predictions':[{'id':r['id'],'date':r['date'],'y':r['y'],'p':models['calibrated_davidson'][r['id']]} for r in test]}
    result['code_hash']=hashlib.sha256(Path(__file__).read_bytes()+Path(__file__).with_name('evaluation.py').read_bytes()).hexdigest()
    result['run_id']=digest(result)
    # Exclusive create prevents accidental replacement; the report is a reproducible artifact.
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False)
    return result
