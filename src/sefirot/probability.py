"""Price-blind goals distribution and frozen multiclass reliability calibration."""
from __future__ import annotations
from math import exp, sqrt, log
from .contracts import number,integer,time,digest,MODEL,PROFILES
from .evidence import eligible_history,profile_of
from .markets import Market,market_from_key

CALIBRATION_SCHEMA='contract-reliability-v4'


def wilson(successes,n,z=1.96):
    integer(n,'sample size',1);number(successes,'success count',0,n)
    p=successes/n;den=1+z*z/n
    mid=(p+z*z/(2*n))/den;half=z*sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return max(0.,mid-half), min(1.,mid+half)


def poisson(rate,cap=35):
    number(rate,'goal rate',.01,12)
    out=[exp(-rate)]
    for i in range(1,cap+1): out.append(out[-1]*rate/i)
    tail=max(0.,1-sum(out))
    # Explicit residual bound, never silently fold extreme scores into a normal outcome.
    total=sum(out)
    return [p/total for p in out],tail


def distribution(home,away):
    hp,ht=poisson(home);ap,at=poisson(away)
    return {(h,a):p*q for h,p in enumerate(hp) for a,q in enumerate(ap)}, min(1.,ht+at)


def goal_thresholds(mass):
    """Coherent projections of the sealed score model; not a new calibrated model."""
    for score in mass:
        if not isinstance(score,tuple) or len(score)!=2:raise ValueError('two-goal score tuple required')
        for goal in score:integer(goal,'score',0,50)
    total=sum(number(p,'score mass',0,1) for p in mass.values())
    if abs(total-1)>1e-8: raise ValueError('score mass must sum to one')
    output={}
    for side,index in (('home',0),('away',1)):
        output[side]={'p0':sum(p for score,p in mass.items() if score[index]==0),
                      'p1':sum(p for score,p in mass.items() if score[index]==1),
                      'p2_plus':sum(p for score,p in mass.items() if score[index]>=2),
                      'p3_plus':sum(p for score,p in mass.items() if score[index]>=3)}
    return output


def grade_stress(base_ev,stress_min,min_ev=.02):
    """Unvalidated audit thresholds. A label never grants monetary permission."""
    number(base_ev,'base EV');number(stress_min,'stress EV');number(min_ev,'minimum EV',0,1)
    label=('NO_VALUE' if base_ev<min_ev else 'AGGRESSIVE_VALUE' if stress_min<-.10 else
           'FRAGILE_VALUE' if stress_min<0 else 'ROBUST_VALUE')
    return {'class':label,'status':'RESEARCH_UNVALIDATED','base_ev':base_ev,'stress_min':stress_min,
            'candidate':label!='NO_VALUE','monetary_permission':False,
            'sensitivity_is_confidence_interval':False}


def schedule_trace(sports,policy):
    """Opponent context frozen at each historic kickoff, excluding late results.

    This supplies testable SoS features; weights are diagnostic until a separate
    fitted model beats the baseline on unseen data. They do not change lambda.
    """
    rows,_=eligible_history(sports,policy);targets={sports['match']['home'],sports['match']['away']};out=[]
    prior=1.225
    for row in rows:
        for side in ('home','away'):
            team=row[side]
            if team not in targets: continue
            opponent=row['away' if side=='home' else 'home'];cutoff=time(row['kickoff'])
            earlier=[r for r in rows if r['id']!=row['id'] and time(r['received_at'])<=cutoff and opponent in (r['home'],r['away'])]
            n=len(earlier)
            attack=(sum(r['home_goals'] if r['home']==opponent else r['away_goals'] for r in earlier)+policy.prior_games*prior)/(n+policy.prior_games)
            defense=(sum(r['away_goals'] if r['home']==opponent else r['home_goals'] for r in earlier)+policy.prior_games*prior)/(n+policy.prior_games)
            out.append({'history_id':row['id'],'team':team,'opponent':opponent,'frozen_at':row['kickoff'],
                        'opponent_games':n,'opponent_attack':attack,'opponent_defense':defense,
                        'schedule_weight':min(1.25,max(.75,1+.1*(attack-defense))),
                        'used_ids':[r['id'] for r in earlier],'used_in_probability':False,
                        'status':'RESEARCH_DIAGNOSTIC' if n else 'INSUFFICIENT_OPPONENT_HISTORY'})
    return out


def estimate(sports,policy,goal_model=None):
    if policy.goal_model=='SOS_THRESHOLD_V2':
        from .goal_model import estimate as estimate_sos
        return estimate_sos(sports,policy,goal_model)
    if goal_model is not None:raise ValueError('goal artifact requires SOS_THRESHOLD_V2')
    rows,excluded=eligible_history(sports,policy)
    now=time(sports['as_of']);match=sports['match']
    weights=[exp(-log(2)*(now-time(r['kickoff'])).total_seconds()/86400/policy.half_life_days) for r in rows]
    weight=sum(weights)
    league_home=(sum(w*r['home_goals'] for r,w in zip(rows,weights))+policy.prior_games*1.35)/(weight+policy.prior_games)
    league_away=(sum(w*r['away_goals'] for r,w in zip(rows,weights))+policy.prior_games*1.10)/(weight+policy.prior_games)
    def team(name):
        subset=[(r,w) for r,w in zip(rows,weights) if name in (r['home'],r['away'])]
        total=sum(w for _,w in subset); prior=(league_home+league_away)/2
        attack=(sum(w*(r['home_goals'] if r['home']==name else r['away_goals']) for r,w in subset)+policy.prior_games*prior)/(total+policy.prior_games)
        defense=(sum(w*(r['away_goals'] if r['home']==name else r['home_goals']) for r,w in subset)+policy.prior_games*prior)/(total+policy.prior_games)
        effective=total*total/sum(w*w for _,w in subset) if subset else 0.
        return attack,defense,len(subset),effective
    ha,hd,hn,he=team(match['home']); aa,ad,an,ae=team(match['away'])
    avg=(league_home+league_away)/2
    lh=min(12.,max(.05,(ha+ad)/2*league_home/avg));la=min(12.,max(.05,(aa+hd)/2*league_away/avg))
    mass,tail=distribution(lh,la)
    scale=policy.stress_rate_fraction
    variants=[]
    for hmult,amult in ((1-scale,1-scale),(1-scale,1+scale),(1+scale,1-scale),(1+scale,1+scale)):
        m,t=distribution(min(12.,max(.05,lh*hmult)),min(12.,max(.05,la*amult)))
        variants.append(m);tail=max(tail,t)
    top=sorted(mass.items(),key=lambda item:(-item[1],item[0]))[:5]
    summary={'model_version':MODEL,'competition_profile':profile_of(match),'rates':{'home':lh,'away':la},'team_games':[hn,an],'effective_games':[he,ae],
             'used_history':[r['id'] for r in rows],'excluded_history':excluded,'history_digest':digest(rows),
             'tail_bound':tail,'goal_thresholds':goal_thresholds(mass),'schedule_trace':schedule_trace(sports,policy),
             'profile_parameters_status':'UNVALIDATED; history and calibration isolated; no fitted profile coefficients',
             'score_scenarios':[{'home':h,'away':a,'probability':p} for (h,a),p in top],
             'uncertainty_method':'frozen reliability bins plus rate sensitivity; raw sensitivity is not coverage',
             'training_prior':f'{policy.prior_games:g} equivalent games; research policy; not empirically certified'}
    return mass,variants,summary


def bin_key(market,p,profile='UNKNOWN'):
    if profile not in PROFILES: raise ValueError('invalid calibration profile')
    if not isinstance(market,Market):raise ValueError('full market contract required for calibration')
    return profile+':'+market.key+':'+str(min(4,int(number(p,'probability',0,1)*5)))


def fit_calibrator(records,model_hash,policy_hash,fit_at):
    """Calibration records are produced by settled sealed predictions, not prices."""
    if not records: raise ValueError('no calibration records')
    groups={}; ids=set(); synthetic=False; latest=None
    goal_hashes={r.get('goal_model_hash') for r in records}
    if len(goal_hashes)!=1:raise ValueError('calibration cannot mix fitted goal models')
    for r in records:
        key=(r['match_id'],r['market'])
        if key in ids: raise ValueError('duplicate calibration event-market')
        ids.add(key)
        if time(r['received_at'])>time(fit_at): raise ValueError('calibrator cannot see future result')
        if r['outcome'] not in ('WIN','PUSH','LOSS'): raise ValueError('invalid outcome')
        market=market_from_key(r['market'])
        if market.kind!=r['kind']:raise ValueError('calibration market/kind mismatch')
        if r['outcome']=='PUSH' and not market.push_possible:raise ValueError('PUSH impossible for calibration contract')
        if r.get('model_hash',model_hash)!=model_hash:raise ValueError('calibration record model hash mismatch')
        bucket=bin_key(market,r['raw_win'],r.get('competition_profile','UNKNOWN'))
        groups.setdefault(bucket,[0,0,0])[('WIN','PUSH','LOSS').index(r['outcome'])]+=1
        synthetic=synthetic or bool(r['synthetic'])
        latest=max(latest or r['received_at'],r['received_at'],key=time)
    out={'version':CALIBRATION_SCHEMA,'model_hash':model_hash,'policy_hash':policy_hash,'fit_at':fit_at,
         'goal_model_hash':next(iter(goal_hashes)),
         'fit_ids':sorted({r['match_id'] for r in records}),'buckets':groups,'synthetic':synthetic,
         'last_result_at':latest,'training_digest':digest(records)}
    out['hash']=digest(out)
    return out


def calibrate(market,raw,artifact,policy,profile='UNKNOWN'):
    if len(raw)!=3 or abs(sum(number(p,'probability',0,1) for p in raw)-1)>1e-8:
        raise ValueError('three normalized calibration probabilities required')
    bucket=bin_key(market,raw[0],profile)
    if not market.push_possible and raw[1]!=0:raise ValueError('PUSH impossible for raw contract')
    fallback={'base':list(raw),'low':[0.,0.,0.],'high':[1.,1. if market.push_possible else 0.,1.], 'n':0}
    if artifact is None:
        return {**fallback,'status':'UNCALIBRATED'}
    if artifact['version']!=CALIBRATION_SCHEMA:raise ValueError('calibration schema mismatch; refit from archived contracts')
    counts=artifact['buckets'].get(bucket)
    if counts is not None:
        if not isinstance(counts,list) or len(counts)!=3:raise ValueError('three calibration counts required')
        for count in counts:integer(count,'calibration count')
        if not market.push_possible and counts[1]:raise ValueError('PUSH impossible for calibrated contract')
    if not counts or sum(counts)<policy.min_calibration:
        return {**fallback,'status':'INSUFFICIENT_BIN','n':sum(counts or [])}
    n=sum(counts)
    # Laplace shrinkage toward raw distribution preserves the simplex; observed
    # bin frequencies drive the posterior as the sample grows.
    base=[(count+2*p)/(n+2) for count,p in zip(counts,raw)]
    bounds=[wilson(c,n) for c in counts]
    low=[min(p,b[0]) for p,b in zip(base,bounds)];high=[max(p,b[1]) for p,b in zip(base,bounds)]
    if not market.push_possible:base[1]=low[1]=high[1]=0.
    return {'base':base,'low':low,'high':high,'status':'CALIBRATED_BIN','n':n}


def _bound_vertices(low,high):
    """Feasible vertices, shared by EV extrema and price thresholds."""
    if len(low)!=3 or len(high)!=3: raise ValueError('three category bounds required')
    for l,h in zip(low,high):
        number(l,'low',0,1);number(h,'high',l,1)
    vertices=[]
    for free in range(3):
        fixed=[i for i in range(3) if i!=free]
        for a in (low[fixed[0]],high[fixed[0]]):
            for b in (low[fixed[1]],high[fixed[1]]):
                point=[0.,0.,0.];point[fixed[0]]=a;point[fixed[1]]=b;point[free]=1-a-b
                if low[free]-1e-10<=point[free]<=high[free]+1e-10:
                    vertices.append([max(0.,min(1.,p)) for p in point])
    if not vertices: raise ValueError('infeasible probability bounds')
    return vertices


def ev_bounds(low,high,odds):
    """Exact extrema of linear WIN/PUSH/LOSS payoff over interval-simplex polytope."""
    number(odds,'odds',1.00000001)
    vertices=[p[0]*(odds-1)-p[2] for p in _bound_vertices(low,high)]
    return min(vertices),max(vertices)


def worst_case_probabilities(low,high,odds):
    """A feasible adverse distribution for sizing; component lows need not sum to one."""
    number(odds,'odds',1.00000001)
    return min(_bound_vertices(low,high),key=lambda p:(p[0]*(odds-1)-p[2],p))


def price_requirements(base,low,high,stress,policy):
    """Price-only floors for the existing gates; never an admission permission.

    EV = p_win * (odds - 1) - p_loss. PUSH is neither a win nor
    a loss. Low/High are category bounds, not a standalone probability
    vector: every feasible simplex vertex must clear the Low-EV gate.
    """
    def floor(vectors,target):
        floors=[]
        for p in vectors:
            if len(p)!=3:raise ValueError('three probabilities required')
            win,push,loss=[number(x,'probability',0,1) for x in p]
            if abs(win+push+loss-1)>1e-8:raise ValueError('probabilities must sum to one')
            if win==0:
                if loss+target>0:return None
                floors.append(1.)
            else:floors.append(max(1.,1+(loss+target)/win))
        if not floors:raise ValueError('nonempty stress scenarios required')
        return max(floors)
    base_floor=floor([base],policy.min_ev)
    low_floor=floor(_bound_vertices(low,high),policy.min_low_ev)
    stress_target=0. if policy.stress_mode=='STRICT' else policy.aggressive_stress_floor
    stress_floor=floor(stress,stress_target)
    values=[base_floor,low_floor,stress_floor]
    return {'base_min_odds':base_floor,'low_min_odds':low_floor,'stress_min_odds':stress_floor,
            'required_odds':max(values) if all(v is not None for v in values) else None,
            'scope':'PRICE_GATES_ONLY','monetary_permission':False,
            'stress_mode':policy.stress_mode,'stress_ev_floor':stress_target,
            'requires_stress_class_validation':policy.stress_mode=='GRADED',
            'requires_fresh_quote_and_full_recheck':True}
