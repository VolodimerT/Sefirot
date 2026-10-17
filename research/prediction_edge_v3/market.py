"""Verified-input research comparator. No quote fetch, staking or admission."""
from sefirot.contracts import number, strict, text, time
from sefirot.markets import payoff_ev, settle
from .benchmark import simplex


def compare_1x2(*, fixture_id, probabilities, lower_bounds, sealed_at, kickoff, at, quotes):
    simplex(probabilities,3)
    if lower_bounds is not None:
        if len(lower_bounds)!=3: raise ValueError('three lower bounds required')
        for low,p in zip(lower_bounds,probabilities): number(low,'lower bound',0,p)
    if not time(sealed_at)<time(kickoff) or time(at)>=time(kickoff): raise ValueError('prematch only')
    groups={}
    for q in quotes:
        strict(q,('fixture_id','bookmaker','line_id','side','odds','observed_at','received_at','rules','verified'))
        text(q['bookmaker'],'bookmaker'); text(q['line_id'],'line')
        number(q['odds'],'odds',1.00000001,10000)
        if q['fixture_id']!=fixture_id or q['rules']!='REGULATION_90' or q['verified'] is not True:
            raise ValueError('quote fixture/rules/provenance mismatch')
        if not time(sealed_at)<=time(q['received_at'])<=time(at)<time(kickoff) or not time(q['observed_at'])<=time(q['received_at']):
            raise ValueError('quote chronology')
        if not 0<=(time(at)-time(q['observed_at'])).total_seconds()<=120: raise ValueError('stale quote')
        if q['side'] not in ('HOME','DRAW','AWAY'): raise ValueError('invalid 1X2 side')
        group=groups.setdefault((q['bookmaker'],q['line_id'],q['observed_at']),{})
        if q['side'] in group: raise ValueError('duplicate partition outcome')
        group[q['side']]=q
    complete=[]
    for (book,line,observed),g in groups.items():
        if set(g)!=set(('HOME','DRAW','AWAY')): continue
        prices=[g[s]['odds'] for s in ('HOME','DRAW','AWAY')]; implied=[1/o for o in prices]; total=sum(implied)
        complete.append({'bookmaker':book,'line_id':line,'observed_at':observed,'overround':total-1,
                         'no_vig':[p/total for p in implied], 'prices':prices})
    # At most one latest partition per bookmaker, avoiding pseudo-consensus.
    latest={}
    for line in complete:
        prior=latest.get(line['bookmaker'])
        if prior is None or (time(line['observed_at']),line['line_id'])>(time(prior['observed_at']),prior['line_id']): latest[line['bookmaker']]=line
    complete=list(latest.values())
    if not complete: return {'status':'NO_DATA','lines':[],'monetary_permission':False}
    reference=[sum(q['no_vig'][i] for q in complete)/len(complete) for i in range(3)]
    for line in complete:
        line['ev']=[payoff_ev(p,0,o) for p,o in zip(probabilities,line['prices'])]
        line['ev_lower']=[payoff_ev(p,0,o) for p,o in zip(lower_bounds,line['prices'])] if lower_bounds is not None else None
    edge=[p-q for p,q in zip(probabilities,reference)]
    status='NO_DATA' if lower_bounds is None else ('RESEARCH_EDGE' if any(low>ref and any(line['ev_lower'][i]>0 for line in complete) for i,(low,ref) in enumerate(zip(lower_bounds,reference))) else 'NO_EDGE')
    return {'status':status,'method':'PROPORTIONAL_NO_VIG','reference':reference,'edge':edge,
            'bookmakers':len(complete),'lines':complete,'monetary_permission':False,
            'uncertainty_verified':False}


def clv(entry, close, *, kickoff):
    for key in ('fixture_id','bookmaker','contract','rules'):
        if entry[key]!=close[key]: raise ValueError('CLV contract mismatch')
    if entry['rules']!='REGULATION_90' or any(q['verified'] is not True for q in (entry,close)):
        raise ValueError('unverified CLV')
    if not time(entry['observed_at'])<=time(entry['received_at'])<time(close['observed_at'])<=time(close['received_at'])<time(kickoff):
        raise ValueError('CLV chronology')
    for q in (entry,close): number(q['odds'],'odds',1.00000001,10000)
    return {'raw_price_ratio':entry['odds']/close['odds']-1,'no_vig_clv':None,
            'status':'RAW_SAME_BOOK_ONLY','profitability_proven':False}


def builder(legs,mass):
    """Shared score-cell intersection; unsupported push combinations abstain."""
    from .benchmark import project
    project(mass)
    if not 2<=len(legs)<=3 or len({m.key for m in legs})!=len(legs): raise ValueError('2-3 distinct legs required')
    if any(m.push_possible for m in legs): raise ValueError('builder PUSH rules not verified')
    p=sum(v for (h,a),v in mass.items() if all(settle(m,h,a)=='WIN' for m in legs))
    return {'joint_probability':p,'builder_ev':None,'status':'UNPRICED','monetary_permission':False}
