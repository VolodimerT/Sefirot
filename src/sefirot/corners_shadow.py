"""Research-only corner projection, separate from the canonical SEFIROT goal CORE.

No method in this module grants monetary permission. Match-level league history,
timestamp provenance, independent holdout and live settlement need validation.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from json import dumps
from math import exp, isfinite, log
from typing import Iterable

STATUS = "RESEARCH_UNVALIDATED"

def utc(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)

def count(value: int, name: str) -> int:
    if type(value) is not int or not 0 <= value <= 40:
        raise ValueError(f"{name} must be a verified corner count 0..40")
    return value

@dataclass(frozen=True)
class CornerMatch:
    fixture_id: str
    league: str
    home: str
    away: str
    kickoff: datetime
    available_at: datetime
    home_ft: int
    away_ft: int
    home_1h: int
    away_1h: int
    source_id: str

    def __post_init__(self) -> None:
        for key in ("fixture_id", "league", "home", "away", "source_id"):
            if not isinstance(getattr(self, key), str) or not getattr(self, key).strip():
                raise ValueError(f"missing {key}")
        if self.home == self.away:
            raise ValueError("same home and away team")
        if utc(self.available_at, "available_at") < utc(self.kickoff, "kickoff") + timedelta(minutes=90):
            raise ValueError("result availability predates full time")
        for label in ("home_ft", "away_ft", "home_1h", "away_1h"):
            count(getattr(self, label), label)
        if self.home_1h > self.home_ft or self.away_1h > self.away_ft:
            raise ValueError("first-half corners exceed full-time corners")

@dataclass(frozen=True)
class CornerForecast:
    league: str
    home: str
    away: str
    as_of: datetime
    full_home: float
    full_away: float
    half_home: float
    half_away: float
    dispersion_full: float | None
    dispersion_half: float | None
    matches: int
    home_games: int
    away_games: int
    source_ids: tuple[str, ...]
    history_sha256: str
    status: str = STATUS
    monetary_permission: bool = False

@dataclass(frozen=True)
class Market:
    period: str
    kind: str
    side: str
    line: float | None = None

    def __post_init__(self) -> None:
        if self.period not in ("FT", "1H"):
            raise ValueError("unsupported corner period")
        valid = {"TOTAL": {"OVER", "UNDER"},
                 "TEAM": {"HOME_OVER", "HOME_UNDER", "AWAY_OVER", "AWAY_UNDER"},
                 "DOUBLE_CHANCE": {"1X", "X2"}}
        if self.kind not in valid or self.side not in valid[self.kind]:
            raise ValueError("unsupported corner market contract")
        if self.kind == "DOUBLE_CHANCE":
            if self.line is not None:
                raise ValueError("double chance has no line")
            return
        if self.line is None or type(self.line) not in (float, int) or not isfinite(self.line):
            raise ValueError("finite line required")
        if not 0 <= self.line <= 35 or self.line * 2 != int(self.line * 2):
            raise ValueError("only integer and half-integer lines supported")

def _mean(values: list[float], weights: list[float]) -> float:
    return sum(v * w for v, w in zip(values, weights)) / sum(weights)

def _dispersion(values: list[int], weights: list[float]) -> float | None:
    mu = _mean(values, weights)
    variance = _mean([(x-mu)**2 for x in values], weights)
    if variance <= mu * 1.01:
        return None
    return max(2., min(40., mu*mu/(variance-mu) + 8.))

def fit(history: Iterable[CornerMatch], *, league: str, home: str, away: str,
        as_of: datetime, kickoff: datetime, max_age_days: int = 730, min_league: int = 80,
        min_team: int = 8, prior_games: float = 8.) -> CornerForecast:
    """The input MUST cover the league, not only the two teams."""
    at = utc(as_of, "as_of")
    if at >= utc(kickoff, "target kickoff"):
        raise ValueError("target fixture is not prematch")
    if not league or not home or not away or home == away:
        raise ValueError("bad fixture")
    if not 1 <= max_age_days <= 3650 or not 10 <= min_league <= 10000 or not 1 <= min_team <= 200:
        raise ValueError("bad sampling policy")
    if not 0 < prior_games <= 100:
        raise ValueError("invalid shrinkage")
    rows = list(history)
    if any(not isinstance(r, CornerMatch) for r in rows):
        raise ValueError("expected independently verified CornerMatch rows")
    ids = [r.fixture_id for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate fixture IDs")
    if any(r.league != league for r in rows):
        raise ValueError("mixed competitions in corner history")
    if any(utc(r.available_at, "available_at") > at for r in rows):
        raise ValueError("future/unavailable result would leak into forecast")
    rows = [r for r in rows if 0 <= (at-utc(r.kickoff,"kickoff")).total_seconds() <= max_age_days*86400]
    rows.sort(key=lambda r: (utc(r.kickoff,"kickoff"),r.fixture_id))
    h = [r for r in rows if r.home == home]
    a = [r for r in rows if r.away == away]
    if len({t for r in rows for t in (r.home,r.away)}) < 12:
        raise ValueError("INSUFFICIENT_LEAGUE_COVERAGE: at least 12 distinct teams")
    if len(rows) < min_league or len(h) < min_team or len(a) < min_team:
        raise ValueError(f"INSUFFICIENT_HISTORY: league={len(rows)} home_venue={len(h)} away_venue={len(a)}")
    def weights(rs):
        return [exp(-log(2)*(at-utc(r.kickoff,"kickoff")).total_seconds()/(180*86400)) for r in rs]
    wl, wh, wa = weights(rows), weights(h), weights(a)
    def period(half: bool) -> tuple[float,float]:
        hc, ac = ("home_1h","away_1h") if half else ("home_ft","away_ft")
        league_h = _mean([getattr(r,hc) for r in rows],wl)
        league_a = _mean([getattr(r,ac) for r in rows],wl)
        def shrink(rs,ws,field,base):
            return (sum(w*getattr(r,field) for r,w in zip(rs,ws))+prior_games*base)/(sum(ws)+prior_games)
        hf = shrink(h,wh,hc,league_h)
        ha = shrink(h,wh,ac,league_a)
        af = shrink(a,wa,ac,league_a)
        aa = shrink(a,wa,hc,league_h)
        return (hf+aa)/2, (af+ha)/2
    full_h,full_a = period(False)
    half_h,half_a = period(True)
    kf=_dispersion([r.home_ft+r.away_ft for r in rows],wl)
    kh=_dispersion([r.home_1h+r.away_1h for r in rows],wl)
    trail=[{"id":r.fixture_id,"ko":utc(r.kickoff,"kickoff").isoformat(),
            "known":utc(r.available_at,"available_at").isoformat(),
            "h":r.home,"a":r.away,"ft":[r.home_ft,r.away_ft],
            "half":[r.home_1h,r.away_1h],"source":r.source_id} for r in rows]
    digest=sha256(dumps(trail,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return CornerForecast(league,home,away,at,full_h,full_a,half_h,half_a,
                          kf,kh,len(rows),len(h),len(a),
                          tuple(sorted({r.source_id for r in rows})),digest)

def _pmf(mu: float, size: float | None, cap: int = 180) -> list[float]:
    if not isfinite(mu) or not 0 <= mu < 80:
        raise ValueError("invalid corner rate")
    if mu == 0:
        return [1.] + [0.] * cap
    if size is None:
        out=[exp(-mu)]
        for i in range(1,cap+1):
            out.append(out[-1]*mu/i)
    else:
        if not isfinite(size) or size < 1:
            raise ValueError("invalid NB size")
        p=size/(size+mu)
        out=[p**size]
        for i in range(1,cap+1):
            out.append(out[-1]*(i-1+size)*(1-p)/i)
    if 1-sum(out)>1e-8:
        raise ValueError("probability tail not bounded")
    return out

def _probability(f: CornerForecast, m: Market,
                 rate_multiplier: tuple[float,float], family: str = "POISSON") -> tuple[float,float,float]:
    if family not in ("POISSON","NEGATIVE_BINOMIAL"):
        raise ValueError("unsupported family")
    if any(not .5 <= x <= 1.5 for x in rate_multiplier):
        raise ValueError("invalid rate multiplier")
    if m.period == "FT":
        h,a,k=f.full_home,f.full_away,f.dispersion_full
    else:
        h,a,k=f.half_home,f.half_away,f.dispersion_half
    h*=rate_multiplier[0];a*=rate_multiplier[1]
    # NB with matching p requires side sizes proportional to their means.
    if family == "NEGATIVE_BINOMIAL" and k is not None:
        kh=max(1.,k*h/(h+a))
        ka=max(1.,k*a/(h+a))
    else:
        kh=ka=None
    hp,ap=_pmf(h,kh),_pmf(a,ka)
    win=push=loss=0.
    for ih,p1 in enumerate(hp):
        if p1<1e-17:continue
        for ia,p2 in enumerate(ap):
            mass=p1*p2
            if mass<1e-17:continue
            if m.kind == "DOUBLE_CHANCE":
                won=ih>=ia if m.side=="1X" else ia>=ih
                tied=False
            else:
                v=(ih+ia if m.kind=="TOTAL" else ih if m.side.startswith("HOME") else ia)
                over=m.side.endswith("OVER") or m.side=="OVER"
                won=v>m.line if over else v<m.line
                tied=(v==m.line)
            if won:win+=mass
            elif tied:push+=mass
            else:loss+=mass
    if abs(win+push+loss-1)>1e-7:
        raise ValueError("corner probabilities not normalized")
    return win,push,loss

def price(forecast: CornerForecast, market: Market, odds: float,
          *, stress_fraction: float = .15) -> dict:
    if forecast.status!=STATUS or forecast.monetary_permission:
        raise ValueError("only shadow forecasts allowed")
    if type(odds) not in (float,int) or not isfinite(odds) or not 1<odds<1000:
        raise ValueError("invalid price")
    if not 0<=stress_fraction<=.4:
        raise ValueError("invalid stress")
    win,push,loss=_probability(forecast,market,(1.,1.))
    families=["POISSON"]
    k=forecast.dispersion_full if market.period=="FT" else forecast.dispersion_half
    if k is not None:
        families.append("NEGATIVE_BINOMIAL")
    evs=[]
    for family in families:
        for hm in (1-stress_fraction,1+stress_fraction):
            for am in (1-stress_fraction,1+stress_fraction):
                w,p,l=_probability(forecast,market,(hm,am),family)
                evs.append(w*(odds-1)-l)
    return {"market":{"period":market.period,"kind":market.kind,"side":market.side,"line":market.line},
            "odds":odds,"win":win,"push":push,"loss":loss,
            "fair_odds":(1-push)/win if win else None,
            "raw_ev":win*(odds-1)-loss,
            "stress_ev_min":min(evs),"stress_ev_max":max(evs),
            "stress_families":families,"status":STATUS,"monetary_permission":False,
            "assumptions":["INDEPENDENT_SIDE_CORNER_COUNTS","UNCALIBRATED",
                           "RATE_STRESS_NOT_COVERAGE","NO_GOALS_CORNERS_JOINT_MODEL"]}

def walk_forward(history: Iterable[CornerMatch],market: Market,
                 *, league: str,min_league: int = 80,min_team: int = 8) -> dict:
    """Walk-forward scorecard is research only, NOT an untouched HOLDOUT."""
    rows=sorted((r for r in history if r.league==league),
                key=lambda r:(utc(r.kickoff,"kickoff"),r.fixture_id))
    scored=[]
    for i,target in enumerate(rows):
        if i<min_league:continue
        at=utc(target.kickoff,"kickoff")-timedelta(seconds=1)
        train=[r for r in rows[:i] if utc(r.available_at,"available_at")<=at]
        try:
            f=fit(train,league=league,home=target.home,away=target.away,
                  as_of=at,kickoff=target.kickoff,min_league=min_league,min_team=min_team)
        except ValueError as exc:
            if str(exc).startswith("INSUFFICIENT_HISTORY"):
                continue
            raise
        if market.kind=="DOUBLE_CHANCE":
            actual=(target.home_ft>=target.away_ft if market.side=="1X"
                    else target.away_ft>=target.home_ft)
            is_push=False
        else:
            if market.kind=="TOTAL":
                v=(target.home_ft+target.away_ft if market.period=="FT"
                   else target.home_1h+target.away_1h)
            elif market.side.startswith("HOME"):
                v=target.home_ft if market.period=="FT" else target.home_1h
            else:
                v=target.away_ft if market.period=="FT" else target.away_1h
            actual=(v>market.line if market.side.endswith("OVER") or market.side=="OVER"
                    else v<market.line)
            is_push=(v==market.line)
        if is_push:continue
        p,push,_=_probability(f,market,(1.,1.))
        p=min(1-1e-10,max(1e-10,p/(1-push)))
        scored.append((p,int(actual),f.history_sha256,target.fixture_id))
    if not scored:
        return {"status":"INSUFFICIENT_HOLDOUT","scored":0,"monetary_permission":False}
    brier=sum((p-y)**2 for p,y,_,_ in scored)/len(scored)
    logloss=-sum(y*log(p)+(1-y)*log(1-p) for p,y,_,_ in scored)/len(scored)
    return {"status":"RESEARCH_WALK_FORWARD_ONLY","scored":len(scored),
            "brier":brier,"logloss":logloss,
            "realized_rate":sum(y for _,y,_,_ in scored)/len(scored),
            "mean_predicted":sum(p for p,_,_,_ in scored)/len(scored),
            "evaluated_ids":[id for _,_,_,id in scored],
            "history_digests":[v for _,_,v,_ in scored],
            "independent_holdout_complete":False,"monetary_permission":False}
