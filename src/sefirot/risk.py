"""Arbiter portfolio controls: bounded flat stake; Kelly is diagnostic only, no loss-chasing state."""
from decimal import Decimal, ROUND_DOWN
from .contracts import number,time


def groups(match,model,scenario,factors):
    return sorted({'match:'+match['id'],'team:'+match['home'],'team:'+match['away'],
                   'league:'+match['league'],'model:'+model,'scenario:'+scenario} | {'factor:'+x for x in factors})


def size_risk(*,win,push,odds,bankroll,peak,quality,exposures,match,model,scenario,factors,at,policy):
    for key,val in (('win',win),('push',push),('quality',quality)): number(val,key,0,1)
    number(odds,'odds',1.00000001);number(bankroll,'bankroll',0);number(peak,'peak',0)
    if win+push>1+1e-9 or peak<bankroll: raise ValueError('invalid portfolio/probability')
    drawdown=0 if peak==0 else 1-bankroll/peak
    why=[];tags=groups(match,model,scenario,factors)
    if bankroll<=0 or drawdown>=policy.max_drawdown: return {'stake':0.,'reasons':['BANKROLL_OR_DRAWDOWN'],'groups':tags,'drawdown':drawdown}
    loss=max(0.,1-win-push)
    kelly=max(0.,((odds-1)*win-loss)/((odds-1)*(1-push))) if push<1 else 0.
    fraction=policy.max_stake_fraction*quality*(1-drawdown/policy.max_drawdown) if kelly>0 else 0.
    cap=bankroll*fraction
    day=time(at).date();daily=0.;same_match=0.;related={tag:0. for tag in tags}
    for e in exposures:
        stake=number(e['stake'],'exposure stake',0)
        if time(e['at'])>time(at): raise ValueError('future exposure')
        if time(e['at']).date()==day: daily+=stake
        if e.get('settled_at') and time(e['settled_at'])<=time(at): continue
        if 'match:'+match['id'] in e['groups']: same_match+=stake
        for tag in set(tags)&set(e['groups']): related[tag]+=stake
    caps=[bankroll*policy.max_day_fraction-daily,bankroll*policy.max_match_fraction-same_match]
    caps.extend(bankroll*policy.max_group_fraction-x for x in related.values())
    if same_match>0: why.append('EVENT_ALREADY_EXPOSED');cap=0.
    cap=max(0.,min([cap]+caps))
    if cap<policy.min_stake: cap=0.;why.append('RISK_BELOW_MINIMUM')
    stake=float(Decimal(str(cap)).quantize(Decimal('.01'),rounding=ROUND_DOWN))
    return {'stake':stake,'reasons':why,'groups':tags,'drawdown':drawdown,'kelly_diagnostic':kelly,'staking_method':'FLAT_CAPPED','fraction':fraction,'remaining_day':max(0.,caps[0])}
