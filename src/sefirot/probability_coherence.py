"""Price-blind necessary probability constraints; never a calibrated joint fit.

Cache settlement relations only, not probabilities or an admission verdict.
All supported outcomes have a representative in the derived integer grid:
if min(h,a) >= L, replace it by L and clamp the difference beyond +/-L;
otherwise keep the smaller score and cap the larger at 2*L+1. With L above
every absolute line, this preserves every supported settlement category.
"""
from functools import lru_cache
from itertools import combinations
from math import ceil, fsum

from .contracts import number, finding
from .markets import market_of, settle

OUTCOMES=('WIN','PUSH','LOSS')
TOLERANCE=1e-10
MAX_GRID_CELLS=16384
MAX_MARKETS=7
MAX_STRESS_SCENARIOS=16


@lru_cache(maxsize=32)
def _relations(markets):
    level=ceil(max(abs(m.line or 0) for m in markets))+1
    cap=2*level+1
    cells=(cap+1)**2
    if cells>MAX_GRID_CELLS:
        return cells,cap,None
    masks=[0]*(3*len(markets))
    for h in range(cap+1):
        for a in range(cap+1):
            bit=1<<(h*(cap+1)+a)
            for i,m in enumerate(markets):
                masks[3*i+OUTCOMES.index(settle(m,h,a))]|=bit
    full=(1<<cells)-1
    constraints=[]
    for i,mask in enumerate(masks):
        lower=int(mask==full);upper=int(bool(mask))
        if lower or not upper:constraints.append(((i,),(1,),lower,upper))
    for i,j in combinations(range(len(masks)),2):
        left,right=masks[i],masks[j]
        if left==right:
            constraints.append(((i,j),(1,-1),0,0))
        else:
            if not left & ~right:constraints.append(((i,j),(1,-1),-1,0))
            if not right & ~left:constraints.append(((j,i),(1,-1),-1,0))
    # Min/max multiplicity of 2 or 3 events supplies disjoint, exhaustive
    # partition and overlapping-cover constraints without independence.
    for size in (2,3):
        for indexes in combinations(range(len(masks)),size):
            chosen=[masks[i] for i in indexes]
            union=0
            for mask in chosen:union|=mask
            intersections=[x&y for x,y in combinations(chosen,2)]
            pair_union=0
            for mask in intersections:pair_union|=mask
            triple=chosen[0]&chosen[1]&chosen[2] if size==3 else 0
            lower=(3 if triple==full else 2 if pair_union==full else 1 if union==full else 0)
            upper=(3 if triple else 2 if pair_union else 1 if union else 0)
            if lower or upper<size:
                constraints.append((indexes,(1,)*size,lower,upper))
    return cells,cap,tuple(constraints)


def check_coherence(contracts,vectors):
    """Necessary subset/equality/2-3 event constraints on one fixture.

    A PASS here is not full marginal-polytope feasibility, interval coverage,
    source attestation, a coherent joint distribution or a money permission.
    """
    if not isinstance(contracts,list) or not 1<=len(contracts)<=MAX_MARKETS or len(vectors)!=len(contracts):
        raise ValueError('bounded matched coherence contracts required')
    markets=tuple(market_of(c) for c in contracts)
    if len({m.key for m in markets})!=len(markets):raise ValueError('duplicate coherence contract')
    values=[]
    for vector in vectors:
        if not isinstance(vector,(list,tuple)) or len(vector)!=3:raise ValueError('three coherence probabilities required')
        checked=[number(p,'coherence probability',0,1) for p in vector]
        if abs(fsum(checked)-1)>1e-8:raise ValueError('normalized coherence probabilities required')
        values.extend(checked)
    cells,cap,constraints=_relations(markets)
    base={'grid_cells':cells,'representative_max_score':cap,'markets':[m.key for m in markets],
          'joint_distribution_verified':False,'monetary_permission':False}
    if constraints is None:
        return {**base,'status':'UNSUPPORTED','reason':'COHERENCE_GRID_LIMIT','constraints_checked':0,'violations':[]}
    violations=[];count=0
    for indexes,weights,lower,upper in constraints:
        value=fsum(values[i]*w for i,w in zip(indexes,weights))
        if value<lower-TOLERANCE or value>upper+TOLERANCE:
            count+=1
            if len(violations)<16:
                violations.append({'events':[markets[i//3].key+':'+OUTCOMES[i%3] for i in indexes],
                                   'coefficients':list(weights),'value':value,'minimum':lower,'maximum':upper})
    return {**base,'status':'CONFLICT' if count else 'NECESSARY_CONDITIONS_PASS',
            'constraints_checked':len(constraints),'violation_count':count,'violations':violations,
            'violations_truncated':count>len(violations),'tolerance':TOLERANCE}


def audit_candidates(candidates):
    if not isinstance(candidates,list) or not 1<=len(candidates)<=MAX_MARKETS:raise ValueError('bounded coherence candidates required')
    contracts=[c['market'] for c in candidates]
    checks=[{'scenario':'BASE',**check_coherence(contracts,[c['base'] for c in candidates])}]
    sizes=[len(c.get('stress_probabilities',[])) for c in candidates]
    if len(set(sizes))!=1 or not 1<=sizes[0]<=MAX_STRESS_SCENARIOS:
        status='UNSUPPORTED';reason='STRESS_SCENARIO_ALIGNMENT'
    else:
        checks += [{'scenario':'STRESS_'+str(i),**check_coherence(contracts,[c['stress_probabilities'][i] for c in candidates])}
                   for i in range(sizes[0])]
        status=('CONFLICT' if any(c['status']=='CONFLICT' for c in checks) else
                'UNSUPPORTED' if any(c['status']=='UNSUPPORTED' for c in checks) else 'NECESSARY_CONDITIONS_PASS')
        reason=None
    return {'schema':'main-probability-coherence-v1','status':status,'reason':reason,'checks':checks,
            'scope':'SINGLE_FIXTURE_MAIN_WIN_PUSH_LOSS_NECESSARY_CONDITIONS',
            'joint_distribution_verified':False,'monetary_permission':False}


def admission_findings(report):
    if report['status']=='NECESSARY_CONDITIONS_PASS':return []
    code='CALIBRATION_COHERENCE_CONFLICT' if report['status']=='CONFLICT' else 'CALIBRATION_COHERENCE_UNVERIFIED'
    return [finding('probability',code,'BLOCK',detail='Shared settlement constraints fail or cannot be checked; keep probabilities unchanged and obtain a newly validated coherent model')]
