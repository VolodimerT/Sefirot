"""Diagnostic veto ablation on identical predeclared fixtures, not betting ROI."""
from math import sqrt
from sefirot.contracts import strict, time, text
from .benchmark import simplex


def ablation(members, records, roles):
    if len(roles)!=8 or len(set(roles))!=8: raise ValueError('eight distinct registered roles required')
    fixtures={m['id']:m for m in members}
    if len(fixtures)!=len(members): raise ValueError('duplicate cohort')
    rows=[]; seen=set()
    for r in records:
        strict(r,('fixture_id','sealed_at','reviewed_at','result_received_at','core','candidate','outcome','vetoes'))
        mid=r['fixture_id']
        if mid not in fixtures or mid in seen: raise ValueError('unassigned/duplicate fixture')
        seen.add(mid)
        if not time(r['sealed_at'])<=time(r['reviewed_at'])<time(fixtures[mid]['kickoff'])<time(r['result_received_at']):
            raise ValueError('arena chronology')
        if type(r['outcome']) is not int or r['outcome'] not in (0,1,2): raise ValueError('result class')
        simplex(r['core'],3)
        if r['candidate'] is not None: simplex(r['candidate'],3)
        if set(r['vetoes'])!=set(roles) or any(type(v) is not bool for v in r['vetoes'].values()): raise ValueError('missing role is not PASS')
        rows.append(r)
    def arm(model, active):
        available=[r for r in rows if r[model] is not None]
        kept=[r for r in available if not any(r['vetoes'][role] for role in active)]
        return {'available':len(available),'retained':len(kept),
                'coverage':len(kept)/len(members) if members else None,
                'top_class_errors':sum(max(range(3),key=lambda i:r[model][i])!=r['outcome'] for r in kept)}
    per_role={}
    for role in roles:
        vetoed=[r for r in rows if r['vetoes'][role]]
        errors=sum(max(range(3),key=lambda i:r['core'][i])!=r['outcome'] for r in vetoed)
        per_role[role]={'vetoes':len(vetoed),'error_precision':errors/len(vetoed) if vetoed else None,
                        'false_veto_fraction':(len(vetoed)-errors)/len(vetoed) if vetoed else None,
                        'missed_errors':sum(not r['vetoes'][role] and max(range(3),key=lambda i:r['core'][i])!=r['outcome'] for r in rows),
                        'without_role':arm('core',[x for x in roles if x!=role])}
    correlations=[]
    for i,a in enumerate(roles):
        for b in roles[i+1:]:
            n=len(rows); sx=sum(r['vetoes'][a] for r in rows); sy=sum(r['vetoes'][b] for r in rows)
            sxy=sum(r['vetoes'][a] and r['vetoes'][b] for r in rows)
            den=sqrt(sx*(n-sx)*sy*(n-sy))
            correlations.append({'roles':[a,b],'phi':(n*sxy-sx*sy)/den if den else None})
    return {'assigned':len(members),'complete_records':len(rows),'roles':per_role,'correlations':correlations,
            'arms':{'CORE':arm('core',[]),'CORE_ARENA':arm('core',roles),
                    'CANDIDATE':arm('candidate',[]),'CANDIDATE_ARENA':arm('candidate',roles)},
            'label':'TOP_CLASS_ERROR_DIAGNOSTIC_NOT_BET_QUALITY','proven_benefit':False,
            'monetary_permission':False}
