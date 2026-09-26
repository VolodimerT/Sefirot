"""Bounded main-market universe and bookmaker contracts (regulation time only)."""
from ._payoffs import Market,settle,probabilities,payoff_ev,fair_odds,implied,margin,MAIN_ORDER
from .contracts import strict,time,number,text

DEFAULT_POOL=[{'kind':'1X2','side':'HOME'}, {'kind':'DOUBLE_CHANCE','side':'1X'},
              {'kind':'DNB','side':'HOME'}, {'kind':'HANDICAP','side':'HOME','line':-1.},
              {'kind':'TOTAL','side':'OVER','line':2.5}, {'kind':'BTTS','side':'YES'},
              {'kind':'TEAM_TOTAL','side':'HOME_OVER','line':1.5}]


def market_of(obj):
    strict(obj,('kind','side'),('line',))
    return Market(obj['kind'],obj['side'],obj.get('line'))


def pool(markets,policy):
    if not isinstance(markets,list) or not 1<=len(markets)<=policy.max_candidates: raise ValueError('bounded market pool required')
    parsed=[market_of(m) for m in markets]
    if len({m.key for m in parsed})!=len(parsed): raise ValueError('duplicate market')
    if len({m.kind for m in parsed})!=len(parsed): raise ValueError('one predeclared candidate per family')
    return sorted(parsed,key=lambda m:(MAIN_ORDER.index(m.kind),m.key))


def validate_quote(q,kickoff,at,seal_at):
    strict(q,('market','bookmaker','odds','observed_at','received_at','phase','rules'),('line_id','movement_evidence'))
    m=market_of(q['market']);text(q['bookmaker'],'bookmaker');number(q['odds'],'odds',1.00000001,10000)
    if q['rules']!='REGULATION_90' or q['phase'] not in ('OPEN','FINAL','ENTRY','CLOSE'): raise ValueError('quote settlement/phase unsupported')
    observed,received=time(q['observed_at']),time(q['received_at'])
    if observed>received or received>time(at) or observed>=time(kickoff): raise ValueError('quote chronology')
    if q['phase']!='CLOSE' and received<time(seal_at): raise ValueError('quotes must enter after probability seal')
    return m


def complete_overround(quotes):
    """Only a genuinely simultaneous exhaustive 1X2 partition has a quoted margin."""
    groups={}
    for q in quotes:
        if q['market']['kind']=='1X2' and q.get('line_id'):
            key=(q['bookmaker'],q['observed_at'],q['line_id'],q['phase'])
            groups.setdefault(key,[]).append(q)
    output=[]
    for key,rows in sorted(groups.items()):
        sides=[r['market']['side'] for r in rows]
        if len(rows)==3 and set(sides)=={'HOME','DRAW','AWAY'}:
            output.append({'bookmaker':key[0],'observed_at':key[1],'line_id':key[2],
                           'overround':margin(tuple(r['odds'] for r in rows))})
    return output
