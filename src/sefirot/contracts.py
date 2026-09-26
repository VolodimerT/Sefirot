"""Versioned, JSON-compatible contracts and strict boundary validation."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import math

VERSION = '2.0.0'
MODEL = 'goals-gamma-v1'
SEPHIROT = ('threshold','witness','scenario','probability','competence','market','opponent','arbiter','chronicler')
REASONS = ('NEW_INFORMATION','DATA_ERROR','BROKEN_SOURCE','WRONG_LINEUP','TECHNICAL_ERROR')


def canonical(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(x):
    return sha256(canonical(x).encode('utf-8')).hexdigest()


def time(value):
    if not isinstance(value,str): raise ValueError('timestamp must be an ISO string')
    try: result = datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError as exc: raise ValueError('invalid ISO timestamp') from exc
    if result.tzinfo is None or result.utcoffset() is None: raise ValueError('timezone required')
    return result.astimezone(timezone.utc)


def iso(value): return time(value).isoformat()


def number(x, name, low=None, high=None):
    if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x): raise ValueError(f'{name}: finite number required')
    if low is not None and x<low or high is not None and x>high: raise ValueError(f'{name}: outside range')
    return float(x)


def integer(x,name,low=0,high=1000000):
    if isinstance(x,bool) or not isinstance(x,int) or not low<=x<=high: raise ValueError(f'{name}: invalid integer')
    return x


def text(x,name):
    if not isinstance(x,str) or not x.strip(): raise ValueError(f'{name}: nonempty string required')
    return x


def strict(obj, required, optional=()):
    if not isinstance(obj,dict): raise ValueError('object required')
    missing=set(required)-obj.keys(); unknown=obj.keys()-set(required)-set(optional)
    if missing or unknown: raise ValueError(f'fields missing={sorted(missing)} unknown={sorted(unknown)}')


@dataclass(frozen=True)
class Policy:
    """Research defaults are explicit proposals, never labelled empirically certified."""
    version: str = 'research-policy-v1'
    min_team_games: int = 8
    history_days: int = 730
    half_life_days: float = 180.
    prior_games: float = 4.
    min_source_reliability: float = .8
    fact_max_age_minutes: int = 1440
    recheck_max_age_minutes: int = 60
    quote_max_age_seconds: int = 120
    max_candidates: int = 7
    min_calibration: int = 20
    min_holdout: int = 60
    min_context: int = 30
    max_calibration_error: float = .10
    min_ev: float = .02
    min_low_ev: float = 0.
    max_probability_width: float = .25
    divergence: float = .10
    line_move: float = .10
    max_tail: float = 1e-7
    stress_rate_fraction: float = .15
    max_revisions: int = 3
    max_stake_fraction: float = .005
    max_match_fraction: float = .01
    max_day_fraction: float = .02
    max_group_fraction: float = .015
    kelly_fraction: float = .1
    max_drawdown: float = .2
    min_stake: float = 1.
    health_window: int = 30
    health_delta: float = .03
    max_severe_errors: int = 2

    def __post_init__(self):
        text(self.version,'policy version')
        for k,v in asdict(self).items():
            if k=='version': continue
            if k in ('min_team_games','history_days','fact_max_age_minutes','recheck_max_age_minutes','quote_max_age_seconds','max_candidates','min_calibration','min_holdout','min_context','max_revisions','health_window','max_severe_errors'):
                integer(v,k,1)
            else: number(v,k,0)
        for k in ('max_calibration_error','min_source_reliability','min_ev','min_low_ev','max_probability_width','divergence','line_move','max_tail','stress_rate_fraction','max_stake_fraction','max_match_fraction','max_day_fraction','max_group_fraction','kelly_fraction','max_drawdown','health_delta'):
            number(getattr(self,k),k,0,1)
        if self.max_candidates>7: raise ValueError('main market pool limited to seven candidates')
        if min(self.half_life_days,self.prior_games,self.max_tail)<=0: raise ValueError('positive numerical scales required')

    @property
    def fingerprint(self): return digest(asdict(self))


def finding(owner, code, severity='BLOCK', evidence=(), detail=''):
    if owner not in SEPHIROT or severity not in ('BLOCK','WARN','INFO'): raise ValueError('invalid finding')
    return {'owner':owner,'code':code,'severity':severity,'evidence':list(evidence),'detail':detail}
