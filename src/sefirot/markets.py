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


def market_from_key(key):
    """Read canonical archived contracts without guessing a side or line."""
    text(key,'market key')
    parts=key.split(':')
    if len(parts) not in (2,3):raise ValueError('invalid market key')
    market=Market(parts[0],parts[1],float(parts[2]) if len(parts)==3 else None)
    if market.key!=key:raise ValueError('noncanonical market key')
    return market


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


def market_reference(quotes,quote,win,push,*,reference_bookmakers=(),at=None,max_age_seconds=120):
    """No-vig comparison only for an exhaustive simultaneous bookmaker line.

    Integer lines and DNB compare conditional probabilities given no PUSH.
    A single price remains a labelled break-even proxy, never a sharp consensus.
    """
    number(win,'win probability',0,1);number(push,'push probability',0,1)
    if win+push>1+1e-10:raise ValueError('invalid win/push probabilities')
    market=market_of(quote['market']);line_id=quote.get('line_id')
    if reference_bookmakers and at is not None:
        references={}
        for q in quotes:
            if q['bookmaker'] not in reference_bookmakers or q['phase'] not in ('FINAL','ENTRY') or not q.get('line_id'):
                continue
            if market_of(q['market']).key!=market.key or q['rules']!=quote['rules']:
                continue
            age=(time(at)-time(q['observed_at'])).total_seconds()
            if not 0<=age<=max_age_seconds or time(q['received_at'])>time(at):continue
            ref=market_reference(quotes,q,win,push)
            if ref['method']!='PROPORTIONAL_COMPLETE_BOOKMAKER_LINE':continue
            prior=references.get(q['bookmaker'])
            order=(time(q['observed_at']),q['line_id'])
            if not prior or order>prior[0]:references[q['bookmaker']]=(order,ref,q)
        if references:
            refs=[v for _,v in sorted(references.items())]
            ps=[r[1]['probability'] for r in refs];reference=sum(ps)/len(ps)
            model=refs[0][1]['model_probability']
            return {'method':'DESIGNATED_BOOKMAKER_CONSENSUS' if len(ps)>1 else 'DESIGNATED_BOOKMAKER_LINE',
                    'probability':reference,'model_probability':model,'divergence':model-reference,
                    'conditional_on_no_push':push>0,'overround':None,'sharp_consensus':len(ps)>1,
                    'designation':'configured reference source; quality is not established by its name',
                    'reference_bookmakers':sorted(references),'reference_n':len(ps),
                    'dispersion':max(ps)-min(ps),
                    'sources':[{'bookmaker':r[2]['bookmaker'],'observed_at':r[2]['observed_at'],
                                'line_id':r[2]['line_id'],'overround':r[1]['overround']} for r in refs]}
    group=[q for q in quotes if line_id and q.get('line_id')==line_id and
           (q['bookmaker'],q['observed_at'],q['phase'])==(quote['bookmaker'],quote['observed_at'],quote['phase'])]
    pairs={}
    for q in group:
        m=market_of(q['market'])
        if m.kind!=market.kind: continue
        if m.kind in ('TOTAL','TEAM_TOTAL') and m.line!=market.line: continue
        if m.kind=='TEAM_TOTAL' and m.side.split('_')[0]!=market.side.split('_')[0]: continue
        if m.kind=='HANDICAP' and m.line!=(market.line if m.side==market.side else -market.line): continue
        if m.side in pairs: return {'method':'MISSING','reason':'DUPLICATE_LINE_OUTCOME','probability':None,'divergence':None}
        pairs[m.side]=q
    sides={'1X2':{'HOME','DRAW','AWAY'},'BTTS':{'YES','NO'},'TOTAL':{'OVER','UNDER'},
           'DNB':{'HOME','AWAY'},'HANDICAP':{'HOME','AWAY'},
           'TEAM_TOTAL':{market.side.split('_')[0]+'_OVER',market.side.split('_')[0]+'_UNDER'}}
    model=win/(1-push) if push<1 else None
    if model is None: return {'method':'MISSING','reason':'ALL_PUSH','probability':None,'divergence':None}
    complete=market.kind in sides and set(pairs)==sides[market.kind]
    overround=sum(implied(q['odds']) for q in pairs.values())-1 if complete else None
    reference=implied(quote['odds'])/(1+overround) if complete else implied(quote['odds'])
    return {'method':'PROPORTIONAL_COMPLETE_BOOKMAKER_LINE' if complete else 'SINGLE_PRICE_BREAK_EVEN_PROXY',
            'probability':reference,'model_probability':model,'divergence':model-reference,
            'conditional_on_no_push':push>0,'overround':overround,'sharp_consensus':False}
