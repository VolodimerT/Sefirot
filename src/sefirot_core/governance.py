"""Contextual competence, deterioration, paired comparison; no implicit release approval."""
from __future__ import annotations
from dataclasses import dataclass
from math import sqrt
from .markets import number

@dataclass(frozen=True)
class Competence:
    context: tuple[str, str, str]
    samples: int
    brier: float | None
    baseline_brier: float | None
    trust: str
    zone: str
    rating_uncertainty: float | None


def competence(context, scores, baselines, frozen=False):
    """Illustrative monitoring thresholds; NOT calibrated admission criteria."""
    if len(context)!=3 or len(scores)!=len(baselines):
        raise ValueError('league, market, scenario context and matched score arrays required')
    s=[number(x,'brier') for x in scores]
    b=[number(x,'baseline') for x in baselines]
    if any(not 0<=x<=1 for x in s+b):
        raise ValueError('binary Brier values lie in [0,1]')
    n=len(s)
    avg=sum(s)/n if n else None
    base=sum(b)/n if n else None
    uncertainty=1/sqrt(n) if n else None
    zone='FROZEN' if frozen else 'UNKNOWN' if n<30 else 'WEAK' if avg>=base else 'WORKING'
    trust='INSUFFICIENT' if n<30 or frozen else 'LOW' if zone=='WEAK' else 'MEDIUM' if n<200 else 'HIGH'
    return Competence(tuple(context),n,avg,base,trust,zone,uncertainty)


def paired_version_test(old_scores, new_scores, *, minimum=30):
    """Candidate must beat existing version on identical untouched fixtures; no self-promotion."""
    if len(old_scores)!=len(new_scores):
        raise ValueError('paired scores need identical cases')
    old=[number(x,'old') for x in old_scores]
    new=[number(x,'new') for x in new_scores]
    if any(not 0<=x<=1 for x in old+new):
        raise ValueError('Brier scores outside [0,1]')
    n=len(old)
    delta=sum(a-b for a,b in zip(old,new))/n if n else None
    # Decision remains manually reviewed even if improved; holdout provenance external.
    return {'n':n,'mean_brier_improvement':delta,'candidate_status':
            'EVIDENCE_FOR_REVIEW' if n>=minimum and delta is not None and delta>0 else 'REJECT_OR_INSUFFICIENT',
            'automatic_release':False}


def classify_error(*, outcome, thesis_held, sources_correct, late_information, market_terms_correct):
    """Postmortem tags are diagnostics, not relabeling of sealed pre-match choices."""
    if outcome not in ('WIN','LOSS','PUSH'):
        raise ValueError('invalid outcome')
    causes=[]
    if not sources_correct: causes.append('SOURCE')
    if late_information: causes.append('LATE_INFORMATION')
    if not thesis_held: causes.append('SCENARIO')
    if not market_terms_correct: causes.append('MARKET')
    if not causes: causes.append('RANDOMNESS_OR_PROBABILITY_ERROR_UNRESOLVED')
    return tuple(causes)
