"""Frozen-run diagnostics; never promotes a model or changes the original selection."""
import hashlib
import json
import math
import random
import statistics
from collections import defaultdict
from datetime import date,timedelta
from pathlib import Path
from .contracts import digest
from .evaluation import devig,metrics,log_loss
from .research import load_csvs,elo_predictions,temperature

METHODS=('proportional','power','shin')

def mean(xs):return statistics.fmean(xs) if xs else None

def quantile(xs,q):
    if not xs:return None
    xs=sorted(xs);pos=(len(xs)-1)*q;i=int(pos);j=min(i+1,len(xs)-1)
    return xs[i]+(xs[j]-xs[i])*(pos-i)

def distribution(xs):return {'n':len(xs),'mean':mean(xs),'median':quantile(xs,.5),'p05':quantile(xs,.05),'p95':quantile(xs,.95)}

def bucket(x,bounds):return sum(x>=b for b in bounds)

def jaccard(a,b):return len(a&b)/len(a|b) if a|b else None

def drawdown(values):
    equity=peak=worst=0.
    for x in values:equity+=x;peak=max(peak,equity);worst=max(worst,peak-equity)
    return worst

def portfolio(bets):
    n=len(bets);clv=[b['odds_clv'] for b in bets if b['odds_clv'] is not None];daily=defaultdict(float)
    for b in bets:daily[b['date']]+=b['pnl']
    return {'n':n,'stakes':float(n),'wins':sum(b['won'] for b in bets),'losses':sum(not b['won'] for b in bets),
        'pnl':sum(b['pnl'] for b in bets),'yield':mean([b['pnl'] for b in bets]),
        'mean_odds':mean([b['odds'] for b in bets]),'mean_probability':mean([b['p_model'] for b in bets]),
        'observed_win_rate':mean([int(b['won']) for b in bets]),'expected_wins':sum(b['p_model'] for b in bets),
        'mean_ev':mean([b['ev'] for b in bets]),'max_drawdown':drawdown([b['pnl'] for b in bets]),
        'daily_drawdown':drawdown([daily[d] for d in sorted(daily)]),'clv':distribution(clv),
        'positive_clv_fraction':mean([int(c>0) for c in clv]),'small_sample':n<30,
        'undefined_reason':'EMPTY_GROUP' if not n else None,'clv_missing':n-len(clv)}

def brier(p,y):return sum((v-int(i==y))**2 for i,v in enumerate(p))/2

def compare(records):
    if not records:return {'n':0,'reason':'EMPTY_GROUP'}
    ys=[r['y'] for r in records]
    scores={name:metrics([r[name] for r in records],ys) for name in ('davidson','elo','market')}
    return {'n':len(records),'small_sample':len(records)<30,'scores':scores,
        'delta':{name:{metric:scores['davidson'][metric]-scores[name][metric] for metric in ('brier','log_loss')} for name in ('elo','market')}}

def bootstrap_intervals(records,bets,config,calendar=None):
    """Paired moving blocks on a complete calendar, with empty days retained."""
    span=calendar or records
    start=date.fromisoformat(span[0]['date']);end=date.fromisoformat(span[-1]['date']);days=(end-start).days+1
    series=[[0.,0.,0.,0.,0.,0.,0.] for _ in range(days)]
    for r in records:
        x=series[(date.fromisoformat(r['date'])-start).days];x[0]+=1
        for offset,other in ((1,'elo'),(3,'market')):
            x[offset]+=brier(r['davidson'],r['y'])-brier(r[other],r['y'])
            x[offset+1]+=log_loss(r['davidson'],r['y'])-log_loss(r[other],r['y'])
    for b in bets:
        x=series[(date.fromisoformat(b['date'])-start).days];x[5]+=b['pnl'];x[6]+=1
    rng=random.Random(config['bootstrap_seed']);block=min(config['block_days'],days);samples=[[] for _ in range(5)]
    prefix=[[0.]*7]
    for row in series:prefix.append([a+b for a,b in zip(prefix[-1],row)])
    for _ in range(config['bootstrap_repetitions']):
        total=[0.]*7;remaining=days
        while remaining:
            first=rng.randrange(days-block+1);length=min(block,remaining)
            for i in range(7):total[i]+=prefix[first+length][i]-prefix[first][i]
            remaining-=length
        if total[0]:
            for i in range(4):samples[i].append(total[i+1]/total[0])
        if total[6]:samples[4].append(total[5]/total[6])
    return {key:{'low':quantile(v,.025),'high':quantile(v,.975),'valid_replicates':len(v)} for key,v in zip(('brier_vs_elo','logloss_vs_elo','brier_vs_market','logloss_vs_market','yield'),samples)}

def monte_carlo(bets,config,probability):
    bets=[b for b in bets if b.get(probability) is not None]
    if not bets:return {'n':0,'reason':'NO_AVAILABLE_PROBABILITIES','expected_pnl':None,'percentile_le_observed':None}
    rng=random.Random(config['monte_carlo_seed']);sims=[]
    for _ in range(config['monte_carlo_repetitions']):sims.append(sum(b['odds']*(rng.random()<b[probability])-1 for b in bets))
    observed=sum(b['pnl'] for b in bets)
    return {'n':len(bets),'observed_pnl':observed,'expected_pnl':sum(b['odds']*b[probability]-1 for b in bets),
        'simulated':distribution(sims),'percentile_le_observed':mean([int(v<=observed) for v in sims]),
        'assumption':'independent Bernoulli matches; conditional, not causal attribution'}

def verify_source(paths,source,config):
    raw=Path(source).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=config['source_report_sha256']:raise ValueError('source report hash mismatch')
    original=json.loads(raw);rows,manifest=load_csvs(paths)
    if manifest['dataset_hash']!=config['dataset_hash'] or manifest['sources']!=original['dataset']['sources']:raise ValueError('dataset hash mismatch')
    if original['run_id']!=config['source_run_id']:raise ValueError('source run mismatch')
    return rows,manifest,original

def diagnostics(paths,source,design,output):
    output=Path(output)
    if output.exists():raise ValueError('output directory already exists; do not overwrite diagnostics')
    config=json.loads(Path(design).read_text(encoding='utf-8'))
    if config['cash_ev_threshold']!=.02 or config['monetary_permission'] is not False:raise ValueError('frozen research policy required')
    rows,manifest,original=verify_source(paths,source,config)
    trace={};raw=elo_predictions(rows,**original['selected']['params']);pd={k:temperature(p,original['temperature']) for k,p in raw.items()}
    pe=elo_predictions(rows,legacy=True,trace=trace);test=[r for r in rows if r['season']==original['split_seasons']['TEST']]
    saved=original['predictions']
    if [r['id'] for r in test]!=[r['id'] for r in saved]:raise ValueError('prediction IDs/order mismatch')
    for r,s in zip(test,saved):
        if r['y']!=s['y'] or any(abs(a-b)>1e-12 for a,b in zip(pd[r['id']],s['p'])):raise ValueError('frozen prediction mismatch')
    rosters={season:sorted({r[k] for r in rows if r['season']==season for k in ('home','away')}) for season in manifest['seasons']}
    season=test[0]['season'];promoted=set(rosters[season])-set(rosters[season-1]);first={}
    for r in test:
        for i,t in enumerate((r['home'],r['away'])):first.setdefault(t,trace[r['id']]['ratings'][i])
    # Preseason ratings are reconstructed using only rows before TEST, including
    # teams whose first fixture is later. Do not use their opponents' later ratings.
    prefix=[r for r in rows if r['season']<season]
    fictitious=[dict(test[0],id='preseason-'+t,home=t,away='__RATING_REFERENCE__',y=1) for t in rosters[season]]
    pretrace={};elo_predictions(prefix+fictitious,legacy=True,trace=pretrace)
    ordered=sorted(rosters[season],key=lambda t:(-pretrace['preseason-'+t]['ratings'][0],t))
    bands={t:('top' if i<6 else 'middle' if i<14 else 'bottom') for i,t in enumerate(ordered)}
    records=[];bets=[];excluded=[]
    for r in test:
        mid=r['id'];p=pd[mid];prices=r['prices'];q={};reason=None
        try:q={method:devig(prices['Avg'],method) for method in METHODS}
        except (KeyError,ValueError) as exc:reason=str(exc);excluded.append({'id':mid,'reason':reason})
        t=trace[mid];counts=t['season_counts'];early=max(counts)<6;u=sum(counts)/2
        labels={'market':'1X2','season_phase':'early' if u<13 else 'middle' if u<26 else 'late',
            'early_six_proxy':str(early),'season_change':str(min(counts)==0),'month':r['date'][:7],
            'promotion':'any_promoted' if promoted&{r['home'],r['away']} else 'both_established',
            'short_history':str(min(t['history_counts'])<20),'short_current_history':str(min(counts)<6),
            'home_strength':bands[r['home']],'away_strength':bands[r['away']],
            'strength_pair':bands[r['home']]+'/'+bands[r['away']]}
        entropy=-sum(v*math.log(v) for v in p if v)/math.log(3);labels['entropy']='low' if entropy<=.8 else 'high' if entropy>=.95 else 'middle'
        if q:
            market=q['proportional'];dis=max(abs(a-b) for a,b in zip(p,market));labels.update({
                'strong_home_favourite':str(market[0]>=.6),'strong_away_favourite':str(market[2]>=.6),
                'near_even':str(abs(market[0]-market[2])<=.1 and max(market[0],market[2])<.5),
                'draw_heavy':str(market[1]>=.28),'disagreement':'low' if dis<=.05 else 'high' if dis>=.1 else 'middle'})
            records.append({'id':mid,'date':r['date'],'y':r['y'],'davidson':p,'elo':pe[mid],'market':market,'q':q,'labels':dict(labels),'pre_match_trace':t})
        if 'B365' not in prices:continue
        odds=prices['B365'];side=max(range(3),key=lambda i:p[i]*odds[i]-1);ev=p[side]*odds[side]-1
        if ev<.02:continue
        close=prices.get('B365C');won=r['y']==side;clv=odds[side]/close[side]-1 if close else None
        delta={m:p[side]-q[m][side] for m in q};qm=q.get('proportional',[None]*3)[side]
        labels.update({'selection':'HDA'[side],'odds_bin':str(bucket(odds[side],config['odds_boundaries'])),
            'ev_bin':str(bucket(ev,config['ev_boundaries'])),
            'divergence_bin':str(bucket(delta['proportional'],config['divergence_boundaries'])) if delta else 'UNKNOWN',
            'side_strength':'UNKNOWN' if qm is None else 'strong' if qm>=.6 else 'moderate' if qm>=.45 else 'near_even' if qm>=.3 else 'underdog',
            'selected_promotion':'N/A' if side==1 else str(r['home' if side==0 else 'away'] in promoted)})
        closing_q={};movement={}
        for method in METHODS:
            try:
                if close:closing_q[method]=devig(close,method)[side];movement[method]=closing_q[method]-devig(odds,method)[side]
            except ValueError:pass
        bets.append({'id':mid,'date':r['date'],'side':side,'market_family':'1X2','odds':odds[side],'p_model':p[side],
            'stake':1.,'won':won,'pnl':odds[side]-1 if won else -1.,'ev':ev,'odds_clv':clv,
            'fair_probability_movement':movement.get('proportional'),'divergence':delta,'labels':labels,
            'closing_q':closing_q,'closing_movement':movement,'p_close':closing_q.get('proportional')})
    if not records:raise ValueError('no common market subset for all devig methods')
    old=original['simulation']['bets']
    if len(bets)!=len(old):raise ValueError('original bet count mismatch')
    for b,s in zip(bets,old):
        if b['id']!=s['id'] or b['side']!=s['side']:raise ValueError('bet identity/order mismatch')
        for k in ('stake','pnl','ev','odds_clv','fair_probability_movement'):
            if (b[k] is None)!=(s[k] is None) or (b[k] is not None and abs(b[k]-s[k])>1e-12):raise ValueError('bet field mismatch: '+k)
    paired_ids={r['id'] for r in records};paired_bets=[b for b in bets if b['id'] in paired_ids]
    cohorts={}
    for axis in sorted({k for b in bets for k in b['labels']}):
        cohorts[axis]={label:portfolio([b for b in bets if b['labels'].get(axis)==label]) for label in sorted({b['labels'].get(axis,'UNKNOWN') for b in bets})}
    segments={}
    for axis in sorted({k for r in records for k in r['labels']}):
        segments[axis]={label:compare([r for r in records if r['labels'][axis]==label]) for label in sorted({r['labels'][axis] for r in records})}
    for axis,groups in segments.items():
        for label,value in groups.items():
            subset=[r for r in records if r['labels'][axis]==label];ids={r['id'] for r in subset}
            value['paired_intervals']=bootstrap_intervals(subset,[b for b in paired_bets if b['id'] in ids],config,records)
    for axis,groups in cohorts.items():
        for label,value in groups.items():
            subset=[b for b in paired_bets if b['labels'].get(axis)==label];ids={b['id'] for b in subset}
            value['yield_interval']=bootstrap_intervals([r for r in records if r['id'] in ids],subset,config,records)['yield']
    devig_report={m:{'cash_ev_portfolio':portfolio(paired_bets),'market_scores':metrics([r['q'][m] for r in records],[r['y'] for r in records]),
        'sports_scores':metrics([r['davidson'] for r in records],[r['y'] for r in records]),
        'divergence_all_sides':distribution([p-q for r in records for p,q in zip(r['davidson'],r['q'][m])]),
        'divergence_selected':distribution([b['divergence'][m] for b in paired_bets])} for m in METHODS}
    flags={}
    for name,threshold in (('positive',0.),('at_least_2pp',.02)):
        sets={m:{b['id'] for b in paired_bets if (b['divergence'][m]>0 if threshold==0 else b['divergence'][m]>=threshold)} for m in METHODS}
        groups={'intersection':set.intersection(*sets.values())}
        groups.update({m+'_only':sets[m]-set.union(*(sets[n] for n in METHODS if n!=m)) for m in METHODS})
        groups.update(sets)
        flags[name]={'jaccard':{a+'/'+b:jaccard(sets[a],sets[b]) for i,a in enumerate(METHODS) for b in METHODS[i+1:]},
            'groups':{k:{'ids':sorted(v),'portfolio':portfolio([b for b in paired_bets if b['id'] in v])} for k,v in groups.items()}}
    decomposition={}
    for m in METHODS:
        bs=[b for b in bets if m in b['closing_q']]
        expected=sum(b['ev'] for b in bs);disagreement=sum(b['odds']*(b['closing_q'][m]-b['p_model']) for b in bs)
        residual=sum(b['odds']*(int(b['won'])-b['closing_q'][m]) for b in bs)
        decomposition[m]={'n':len(bs),'model_expected_pnl':expected,'closing_minus_model':disagreement,
            'outcome_minus_closing':residual,'actual_pnl':sum(b['pnl'] for b in bs),
            'closing_expected_pnl':expected+disagreement,'identity_residual':sum(b['pnl'] for b in bs)-expected-disagreement-residual,
            'same_method_probability_movement':distribution([b['closing_movement'][m] for b in bs])}
    common={'schema_version':1,'status':'EXPLORATORY','monetary_permission':False,'source_run_id':original['run_id'],
        'source_report_sha256':config['source_report_sha256'],'dataset_hash':manifest['dataset_hash'],'source_files':manifest['sources'],
        'config':config,'config_hash':digest(config),'split':original['split_counts'],'subset_ids':sorted(paired_ids),'exclusions':excluded,
        'limitations':['Historical timestamps unknown; not prospective validation','All 2024/25 is now seen; no retuning',
        'Avg is a market reference, not an executable price','B365 historical quotes do not establish execution feasibility',
        'Cohorts exploratory; no automatic freeze','True individual probability coverage not identifiable',
        'Exact rounds unavailable; early-six uses previous games proxy','Bootstrap and Monte Carlo rely on dependence assumptions']}
    root=Path(__file__).parent
    common['code_hash']=digest({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.glob('*.py'))})
    common['design_hash']=config['design_sha256']
    uncertainty={'individual_probability_coverage':None,'reason':'NO_INTERVALS_IN_SOURCE_RUN; true probabilities unobserved',
        'interval_design':'See docs/P0_EXPERIMENT_DESIGN.md section 7; no retrospective interval fabrication'}
    results={'P0_DEVIG_SENSITIVITY':{'methods':devig_report,'cash_selection_jaccard':1. if paired_bets else None,
        'diagnostic_flags':flags,'cash_selection_rule':'Original max cash EV side; >=0.02; devig-independent'},
        'P0_COHORT_ANALYSIS':{'original_portfolio':portfolio(bets),'replay_verified':True,'bets':bets,'cohorts':cohorts,
            'rolling50':[{'first_id':bets[i]['id'],'last_id':bets[i+49]['id'],'portfolio':portfolio(bets[i:i+50])} for i in range(max(0,len(bets)-49))],
            'decomposition':decomposition,'monte_carlo':{p:monte_carlo(bets,config,p) for p in ('p_model','p_close')}},
        'P0_DAVIDSON_VS_ELO':{'overall':compare(records),'segments':segments,'paired_block_bootstrap':bootstrap_intervals(records,paired_bets,config),
            'records':records,'uncertainty':uncertainty,'tune_regression_trials':original['trials'],
            'decay_sensitivity':decay_sensitivity(rows,original)}}
    for name,result in results.items():
        result.update(common);result['report_kind']=name;result['run_id']=digest(result)
    output.mkdir(parents=True,exist_ok=False)
    for name,result in results.items():(output/(name+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    (output/'P0_DIAGNOSTIC_REPORT.md').write_text(render_report(results),encoding='utf-8')
    return results


def decay_sensitivity(rows,original):
    """Separate goals-only TRAIN/TUNE experiment; never uses CALIBRATE or TEST."""
    tune=original['split_seasons']['TUNE'];trials=[]
    eligible=[r for r in rows if r['season']<=tune]
    # Goals model's evidence contract is handled explicitly by its historical
    # research adapter, not by fabricating provider provenance.
    from math import exp,log
    from .probability import distribution as scores
    for half in (90.,180.,360.):
        for prior in (2.,4.,8.):
            ps=[];ys=[]
            for r in eligible:
                if r['season']!=tune:continue
                past=[a for a in eligible if a['date']<r['date']]
                weights=[exp(-log(2)*(date.fromisoformat(r['date'])-date.fromisoformat(a['date'])).days/half) for a in past]
                total=sum(weights);lh=(sum(w*a['home_goals'] for a,w in zip(past,weights))+prior*1.35)/(total+prior)
                la=(sum(w*a['away_goals'] for a,w in zip(past,weights))+prior*1.10)/(total+prior);avg=(lh+la)/2
                def team(name):
                    sub=[(a,w) for a,w in zip(past,weights) if name in (a['home'],a['away'])];den=sum(w for a,w in sub)+prior
                    return [(sum(w*a['home_goals' if (a['home']==name)==attack else 'away_goals'] for a,w in sub)+prior*avg)/den for attack in (True,False)]
                ha,hd=team(r['home']);aa,ad=team(r['away']);mass,_=scores(min(12.,max(.05,(ha+ad)/2*lh/avg)),min(12.,max(.05,(aa+hd)/2*la/avg)))
                p=[0.,0.,0.]
                for (h,a),v in mass.items():p[0 if h>a else 1 if h==a else 2]+=v
                ps.append(p);ys.append(r['y'])
            trials.append({'half_life_days':half,'prior_games':prior,'scores':metrics(ps,ys)})
    return {'status':'TRAIN_TUNE_ONLY_OTHER_MODEL','trials':trials,'note':'Research date-based reconstruction; does not alter Davidson or CORE policy'}


def render_report(results):
    c=results['P0_COHORT_ANALYSIS'];d=results['P0_DAVIDSON_VS_ELO'];v=results['P0_DEVIG_SENSITIVITY'];p=c['original_portfolio']
    lines=['# P0 — диагностика исходного benchmark','',
        '**EXPLORATORY; денежного допуска нет. Правила исходного TEST не менялись.**','',
        f"Восстановлено {p['n']} ставок; PnL {p['pnl']:.2f}; yield {p['yield']:.2%}; mean EV {p['mean_ev']:.2%}.",
        f"Модель ожидала {p['expected_wins']:.2f} побед, получено {p['wins']}. Raw CLV mean {p['clv']['mean'] if p['clv']['mean'] is not None else 'N/A'}, median {p['clv']['median']}; positive fraction {p['positive_clv_fraction']}.",'',
        '## 1. Слабая модель?', '',
        'Парные ошибки на одинаковом subset. Положительная delta означает, что Davidson хуже. Bootstrap: 14 календарных дней, 2000 повторов в полном прогоне. Интервалы условны; сегменты exploratory.','',
        '| Сравнение | Δ Brier | Δ LogLoss | 95% Brier interval | 95% LogLoss interval |','|---|---:|---:|---|---|']
    for other in ('elo','market'):
        delta=d['overall']['delta'][other];ci=d['paired_block_bootstrap']
        lines.append(f"| Davidson − {other} | {delta['brier']:.6f} | {delta['log_loss']:.6f} | {ci['brier_vs_'+other]['low']:.6f}…{ci['brier_vs_'+other]['high']:.6f} | {ci['logloss_vs_'+other]['low']:.6f}…{ci['logloss_vs_'+other]['high']:.6f} |")
    lines+=['','## 2. Нестабильный devig?','',
        'Cash EV не зависит от devig: те же исходные ставки. Диагностические группы divergence не являются новой стратегией.','',
        '| Метод | N | Market Brier | Market LogLoss | Closing-implied PnL |','|---|---:|---:|---:|---:|']
    for method in METHODS:
        m=v['methods'][method]['market_scores'];dec=c['decomposition'][method]
        lines.append(f"| {method} | {m['n']} | {m['brier']:.6f} | {m['log_loss']:.6f} | {dec['closing_expected_pnl']:.2f} |")
    lines+=['', 'Jaccard при divergence ≥2 pp: '+json.dumps(v['diagnostic_flags']['at_least_2pp']['jaccard']), '',
        '## 3. Плохой EV threshold?','',
        'Проверяется достоверность заявленного EV, не выбирается новый порог. Положительный исход отдельных bins не разрешает торговать ими.','',
        '| EV bin (0=2–4%, 1=4–8%, 2=8–15%, 3=15%+) | N | Mean EV | PnL | Yield |','|---|---:|---:|---:|---:|']
    for label,g in c['cohorts']['ev_bin'].items():lines.append(f"| {label} | {g['n']} | {g['mean_ev']:.2%} | {g['pnl']:.2f} | {g['yield']:.2%} |")
    lines+=['','## 4. Плохие cohorts?','','Разрезы пересекаются: нельзя складывать их убытки. Отбор плохих групп после просмотра не даёт права вводить production veto.','',
        '| Разрез | Группа | N | PnL | Yield |','|---|---|---:|---:|---:|']
    for axis in ('selection','promotion','season_phase','odds_bin','side_strength','divergence_bin'):
        for label,g in c['cohorts'][axis].items():lines.append(f"| {axis} | {label} | {g['n']} | {g['pnl']:.2f} | {g['yield']:.2%} |")
    lines+=['','## 5. Калибровка и uncertainty?','']
    for model,m in d['overall']['scores'].items():lines.append(f"- {model}: macro ECE={m['ece_macro']:.6f}; mean confidence={m['sharpness_mean_max']:.6f}.")
    lines+=['','ECE зависит от размера bins. Все classwise reliability bins опубликованы в JSON. Temperature=1 не исправила исходные прогнозы. Истинная индивидуальная P неизвестна: coverage=null. Wilson и ±15% rate stress другой CORE-модели не приписываются Davidson.','',
        '## 6. Смесь причин и CLV','',
        'Точное разложение: фактический PnL = модельное ожидание + расхождение closing с моделью + остаток исходов относительно closing. Это бухгалтерское тождество, не доказанная причинная декомпозиция.','',
        '| Devig | Model expectation | Closing − model | Outcome − closing | Actual |','|---|---:|---:|---:|---:|']
    for method,r in c['decomposition'].items():lines.append(f"| {method} | {r['model_expected_pnl']:.2f} | {r['closing_minus_model']:.2f} | {r['outcome_minus_closing']:.2f} | {r['actual_pnl']:.2f} |")
    lines+=['','Условный Monte Carlo (независимость матчей):']
    for model,r in c['monte_carlo'].items():lines.append(f"- {model}: N={r['n']}, доля симуляций не выше фактического PnL={r.get('percentile_le_observed')}; expected PnL={r.get('expected_pnl')}.")
    lines+=['','Closing-implied EV уже учитывает маржу через q_close и не равен raw odds CLV. Положительный mean raw CLV сам по себе не доказывает положительного EV. Execution timestamps отсутствуют: невозможно доказать доступность цены или точно выделить потери исполнения.','',
        '## Decay, regression и следующий эксперимент','',
        'Сохранены все 54 прежних TUNE trials Davidson; отдельная 3×3 чувствительность goals-модели использует только TRAIN/TUNE. Текущие defaults не объявляются обученными и не меняются. JSON содержит все результаты, а не только победителя.','',
        'Рекомендуемая ветка P1 после рассмотрения отчёта: сохранить Davidson baseline и проверить xG/xGA challenger с отдельными данными и новым независимым периодом. Наблюдаемые promoted/early-season ошибки задают гипотезы priors/context; отключение этих групп на просмотренном TEST не является улучшением, подтверждённым вне выборки. Новый P1 здесь не реализован.','',
        '## Воспроизводимость и ограничения','',f"Dataset hash: `{c['dataset_hash']}`",f"Code hash: `{c['code_hash']}`",f"Config hash: `{c['config_hash']}`",f"Design hash: `{c['design_hash']}`",'']
    for name,r in results.items():lines.append(f"- {name}: run_id `{r['run_id']}`")
    lines+=['']+['- '+x for x in c['limitations']]
    lines+=['','Shin numerical reference: https://github.com/mberk/shin ; methodology: https://www.sciencepg.com/article/10.11648/10026106 .',
        'Исходные CSV перечислены с SHA256 в каждом JSON и DATA_MANIFEST.json. Команда: см. README и P0_EXPERIMENT_DESIGN.md.','']
    return '\n'.join(lines)
