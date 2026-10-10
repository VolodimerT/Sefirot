"""Frozen, chronological evaluation of corner probabilities: research only.

Training ends strictly before test fixtures. No training on the test partition,
no post-game backdating, no bookmaker profitability or holdout-certification claims.
"""
from __future__ import annotations
from datetime import datetime
from math import log
from typing import Iterable
from .corners_shadow import CornerMatch,Market,fit,utc,_probability

def _observed(row:CornerMatch,market:Market)->tuple[int|None,bool]:
    h,a=(row.home_1h,row.away_1h) if market.period=="1H" else (row.home_ft,row.away_ft)
    if market.kind=="DOUBLE_CHANCE":
        return int(h>=a if market.side=="1X" else a>=h),False
    value=h+a if market.kind=="TOTAL" else h if market.side.startswith("HOME") else a
    if value==market.line:return None,True
    return int(value>market.line if (market.side=="OVER" or market.side.endswith("_OVER"))
               else value<market.line),False

def _wilson(k:int,n:int,z:float=1.96)->tuple[float,float]:
    if n==0:return (0.,1.)
    p=k/n;den=1+z*z/n
    middle=(p+z*z/(2*n))/den
    half=z*((p*(1-p)/n+z*z/(4*n*n))**.5)/den
    return max(0.,middle-half),min(1.,middle+half)

def score_frozen_split(history:Iterable[CornerMatch],*,league:str,market:Market,
                       train_end:datetime,evaluate_at:datetime,min_league:int=80,
                       min_team:int=8,minimum_evaluations:int=100)->dict:
    """Time-locked training followed by untouched chronological fixtures.

    This is an internal temporal split, never an independently attested holdout.
    """
    cut,at=utc(train_end,"train_end"),utc(evaluate_at,"evaluate_at")
    if cut>=at:raise ValueError("train cutoff must precede evaluation date")
    if not league or not isinstance(market,Market):
        raise ValueError("explicit league and market contract required")
    if minimum_evaluations<20 or min_team<1 or min_league<10:
        raise ValueError("invalid sample thresholds")
    rows=list(history)
    if any(not isinstance(r,CornerMatch) or r.league!=league for r in rows):
        raise ValueError("mixed league or invalid history")
    if len({r.fixture_id for r in rows})!=len(rows):
        raise ValueError("duplicate fixture id")
    train=[r for r in rows if utc(r.kickoff,"kickoff")<cut
           and utc(r.available_at,"available_at")<=cut]
    test=sorted((r for r in rows if cut<utc(r.kickoff,"kickoff")<at
                 and utc(r.available_at,"available_at")<=at),
                key=lambda r:(utc(r.kickoff,"kickoff"),r.fixture_id))
    wins=losses=0
    for r in train:
        y,push=_observed(r,market)
        if not push:
            if y:wins+=1
            else:losses+=1
    if wins+losses==0:
        return {"status":"NO_TRAINING_BENCHMARK","training":len(train),"scored":0,
                "independent_holdout_verified":False,"monetary_permission":False}
    baseline=max(1e-9,min(1-1e-9,wins/(wins+losses)))
    scored=[];push_count=skipped=0
    for target in test:
        try:
            forecast=fit(train,league=league,home=target.home,away=target.away,
                         as_of=cut,kickoff=target.kickoff,
                         min_league=min_league,min_team=min_team)
        except ValueError as exc:
            if str(exc).startswith(("INSUFFICIENT_HISTORY","INSUFFICIENT_LEAGUE_COVERAGE")):
                skipped+=1;continue
            raise
        win,push,loss=_probability(forecast,market,(1.,1.))
        outcome,settled_push=_observed(target,market)
        if settled_push:push_count+=1;continue
        if win+loss<1e-12:raise ValueError("zero probability after excluding pushes")
        prob=max(1e-9,min(1-1e-9,win/(win+loss)))
        scored.append((prob,int(outcome),target.fixture_id))
    if not scored:
        return {"status":"INSUFFICIENT_HOLDOUT","training":len(train),
                "test_candidates":len(test),"scored":0,
                "skipped":skipped,"pushes":push_count,
                "independent_holdout_verified":False,"monetary_permission":False}
    n=len(scored)
    brier=sum((p-y)**2 for p,y,_ in scored)/n
    base_brier=sum((baseline-y)**2 for _,y,_ in scored)/n
    log_loss=-sum(y*log(p)+(1-y)*log(1-p) for p,y,_ in scored)/n
    base_loss=-sum(y*log(baseline)+(1-y)*log(1-baseline) for _,y,_ in scored)/n
    success=sum(y for _,y,_ in scored)
    bins=[]
    for i in range(5):
        bucket=[(p,y) for p,y,_ in scored if min(4,int(p*5))==i]
        if bucket:
            bins.append({"bin":i,"n":len(bucket),
                         "predicted":sum(p for p,y in bucket)/len(bucket),
                         "observed":sum(y for p,y in bucket)/len(bucket),
                         "wilson95":_wilson(sum(y for p,y in bucket),len(bucket))})
    return {"status":("RESEARCH_TEMPORAL_SPLIT" if n>=minimum_evaluations
                      else "INSUFFICIENT_HOLDOUT"),
            "market":{"period":market.period,"kind":market.kind,
                      "side":market.side,"line":market.line},
            "training":len(train),"test_candidates":len(test),"scored":n,
            "pushes":push_count,"skipped":skipped,
            "mean_predicted":sum(p for p,y,_ in scored)/n,
            "realized_rate":success/n,"wilson95":_wilson(success,n),
            "brier":brier,"log_loss":log_loss,
            "benchmark_training_base_rate":baseline,
            "benchmark_brier":base_brier,"benchmark_log_loss":base_loss,
            "brier_delta":brier-base_brier,"log_loss_delta":log_loss-base_loss,
            "reliability_bins":bins,"train_end":cut.isoformat(),
            "evaluate_at":at.isoformat(),
            "evaluated_ids":[id for _,_,id in scored],
            "independent_holdout_verified":False,
            "bookmaker_benchmark_available":False,
            "profitability_claim_supported":False,"monetary_permission":False}
