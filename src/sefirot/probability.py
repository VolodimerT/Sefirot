"""Price-blind goals distribution and frozen multiclass reliability calibration."""
from __future__ import annotations
from math import exp, sqrt, log
from .contracts import number,integer,time,digest,MODEL
from .evidence import eligible_history


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


def estimate(sports,policy):
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
    summary={'model_version':MODEL,'rates':{'home':lh,'away':la},'team_games':[hn,an],'effective_games':[he,ae],
             'used_history':[r['id'] for r in rows],'excluded_history':excluded,'history_digest':digest(rows),
             'tail_bound':tail,'score_scenarios':[{'home':h,'away':a,'probability':p} for (h,a),p in top],
             'uncertainty_method':'frozen reliability bins plus rate sensitivity; raw sensitivity is not coverage',
             'training_prior':f'{policy.prior_games:g} equivalent games; research policy; not empirically certified'}
    return mass,variants,summary


def bin_key(kind,p): return kind+':'+str(min(4,int(number(p,'probability',0,1)*5)))


def fit_calibrator(records,model_hash,policy_hash,fit_at):
    """Calibration records are produced by settled sealed predictions, not prices."""
    if not records: raise ValueError('no calibration records')
    groups={}; ids=set(); synthetic=False; latest=None
    for r in records:
        key=(r['match_id'],r['market'])
        if key in ids: raise ValueError('duplicate calibration event-market')
        ids.add(key)
        if time(r['received_at'])>time(fit_at): raise ValueError('calibrator cannot see future result')
        if r['outcome'] not in ('WIN','PUSH','LOSS'): raise ValueError('invalid outcome')
        bucket=bin_key(r['kind'],r['raw_win'])
        groups.setdefault(bucket,[0,0,0])[('WIN','PUSH','LOSS').index(r['outcome'])]+=1
        synthetic=synthetic or bool(r['synthetic'])
        latest=max(latest or r['received_at'],r['received_at'],key=time)
    out={'version':'reliability-v1','model_hash':model_hash,'policy_hash':policy_hash,'fit_at':fit_at,
         'fit_ids':sorted({r['match_id'] for r in records}),'buckets':groups,'synthetic':synthetic,
         'last_result_at':latest,'training_digest':digest(records)}
    out['hash']=digest(out)
    return out


def calibrate(kind,raw,artifact,policy):
    if artifact is None:
        return {'base':list(raw),'low':[0.,0.,0.],'high':[1.,1.,1.],'status':'UNCALIBRATED','n':0}
    counts=artifact['buckets'].get(bin_key(kind,raw[0]))
    if not counts or sum(counts)<policy.min_calibration:
        return {'base':list(raw),'low':[0.,0.,0.],'high':[1.,1.,1.],'status':'INSUFFICIENT_BIN','n':sum(counts or [])}
    n=sum(counts)
    # Laplace shrinkage toward raw distribution preserves the simplex; observed
    # bin frequencies drive the posterior as the sample grows.
    base=[(count+2*p)/(n+2) for count,p in zip(counts,raw)]
    bounds=[wilson(c,n) for c in counts]
    low=[min(p,b[0]) for p,b in zip(base,bounds)];high=[max(p,b[1]) for p,b in zip(base,bounds)]
    return {'base':base,'low':low,'high':high,'status':'CALIBRATED_BIN','n':n}


def ev_bounds(low,high,odds):
    """Exact extrema of linear WIN/PUSH/LOSS payoff over interval-simplex polytope."""
    number(odds,'odds',1.00000001)
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
                    vertices.append(point[0]*(odds-1)-point[2])
    if not vertices: raise ValueError('infeasible probability bounds')
    return min(vertices),max(vertices)
