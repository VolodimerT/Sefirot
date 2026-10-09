"""Isolated sports-only candidates. Never imported by CORE or money gates.

DC_DYNAMIC uses a time-weighted ridge Poisson fit followed by conditional rho
fitting, NOT joint Dixon-Coles maximum likelihood or a latent-state filter.
"""
from collections import Counter
from datetime import timedelta
from dataclasses import asdict, dataclass
from math import exp, log, fsum
from pathlib import Path

from sefirot.contracts import digest, integer, number, strict, text, time
from sefirot.identity import model_code_hash
from sefirot.probability import estimate

MODELS = ('BASELINE_V1', 'DC_DYNAMIC_V1', 'SOS_LITE_V1')


@dataclass(frozen=True)
class Config:
    half_life_days: float = 180.
    prior_games: float = 8.
    ridge: float = 4.
    previous_season_weight: float = .5
    history_days: int = 730
    min_matches: int = 60
    min_team_matches: int = 6
    iterations: int = 400
    tolerance: float = 1e-7

    def __post_init__(self):
        for key in ('half_life_days', 'prior_games', 'ridge', 'tolerance'):
            number(getattr(self, key), key, 1e-10)
        number(self.previous_season_weight, 'season shrinkage', .01, 1)
        for key in ('history_days', 'min_matches', 'min_team_matches', 'iterations'):
            integer(getattr(self, key), key, 1)


def research_hash():
    return digest({'core': model_code_hash(), 'files': {
        p.name: p.read_text(encoding='utf-8') for p in sorted(Path(__file__).parent.glob('*.py'))}})


def checked_rows(rows, cutoff, league, profile, season, config):
    """Reject contamination; don't silently filter a submitted training cohort.

    receipt_sha is a declared binding, not external authentication. A trusted
    archive adapter must independently verify bytes before prospective use.
    """
    text(league, 'league'); integer(season, 'season', 1900, 2200)
    if profile not in ('MEN', 'WOMEN', 'RESERVE', 'LOWER'):
        raise ValueError('known competition profile required')
    seen = set()
    for r in rows:
        strict(r, ('id', 'home', 'away', 'league', 'competition_profile', 'season',
                   'kickoff', 'finished_at', 'received_at', 'home_goals', 'away_goals',
                   'source_id', 'receipt_sha', 'synthetic'))
        for key in ('id', 'home', 'away', 'source_id'):
            text(r[key], key)
        if r['id'] in seen or r['home'] == r['away']:
            raise ValueError('duplicate/revised fixture or identical teams')
        seen.add(r['id'])
        integer(r['season'], 'season', 1900, 2200)
        if r['league'] != league or r['competition_profile'] != profile or not 0 <= season-r['season'] <= 2:
            raise ValueError('league/profile/season mismatch')
        if not time(r['kickoff'])+timedelta(minutes=90) <= time(r['finished_at']) <= time(r['received_at']) <= time(cutoff):
            raise ValueError('future result/receipt or impossible chronology')
        if (time(cutoff)-time(r['kickoff'])).total_seconds()/86400 > config.history_days:
            raise ValueError('stale history')
        for key in ('home_goals', 'away_goals'):
            integer(r[key], key, 0, 50)
        if type(r['synthetic']) is not bool:
            raise ValueError('explicit provenance required')
        sha = r['receipt_sha']
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
            raise ValueError('receipt sha256 required')
    return sorted(rows, key=lambda r: (time(r['kickoff']), r['id']))


def weight(row, cutoff, season, config):
    age = (time(cutoff)-time(row['kickoff'])).total_seconds()/86400
    return exp(-log(2)*age/config.half_life_days)*config.previous_season_weight**(season-row['season'])


def tau(h, a, lh, la, rho):
    return {(0, 0): 1-lh*la*rho, (0, 1): 1+lh*rho,
            (1, 0): 1+la*rho, (1, 1): 1-rho}.get((h, a), 1.)


def score_mass(lh, la, rho=0.):
    """Zero-rate support; bounded finite tail; invalid DC parameters fail closed."""
    for rate in (lh, la):
        number(rate, 'rate', 0, 12)
    number(rho, 'rho', -1, 1)
    if min(tau(h, a, lh, la, rho) for h in (0, 1) for a in (0, 1)) <= 0:
        raise ValueError('negative/zero DC correction')
    def marginal(rate):
        values = [exp(-rate)]
        for g in range(1, 51):
            values.append(values[-1]*rate/g)
        return values
    hp, ap = marginal(lh), marginal(la)
    mass = {(h, a): p*q*tau(h, a, lh, la, rho)
            for h, p in enumerate(hp) for a, q in enumerate(ap)}
    total = fsum(mass.values())
    return {s: p/total for s, p in mass.items()}, max(0., 1-total)


def _dc_fit(rows, cutoff, season, config):
    teams = sorted({r[k] for r in rows for k in ('home', 'away')})
    idx = {t: i for i, t in enumerate(teams)}; n = len(teams)
    data = [(idx[r['home']], idx[r['away']], r['home_goals'], r['away_goals'],
             weight(r, cutoff, season, config)) for r in rows]
    total = sum(d[4] for d in data)
    # Separate log intercepts encode league home advantage; team effects are
    # ridge-identified around zero, without an unidentifiable free offset.
    initial = [log((sum(d[j]*d[4] for d in data)+config.prior_games*prior)/(total+config.prior_games))
               for j, prior in ((2, 1.35), (3, 1.10))]
    x = initial + [0.]*(2*n)
    def objective(v, gradient=False):
        loss = 0.; g = [0.]*len(v)
        for hi, ai, hg, ag, w in data:
            for side, scorer, defender, goals in ((0, hi, ai, hg), (1, ai, hi, ag)):
                z = v[side]+v[2+scorer]+v[2+n+defender]
                if abs(z) > 20:
                    return (float('inf'), g)
                rate = exp(z); loss += w*(rate-goals*z)
                delta = w*(rate-goals)
                for k in (side, 2+scorer, 2+n+defender):
                    g[k] += delta
        for i in range(len(v)):
            prior = initial[i] if i < 2 else 0.
            loss += .5*config.ridge*(v[i]-prior)**2
            g[i] += config.ridge*(v[i]-prior)
        return loss, g
    converged = False
    for iteration in range(config.iterations):
        loss, grad = objective(x)
        if max(abs(g) for g in grad)/max(1., total) < config.tolerance:
            converged = True; break
        step = 1/max(1., total)
        for _ in range(40):
            candidate = [v-step*g for v, g in zip(x, grad)]
            new_loss, _ = objective(candidate)
            if new_loss <= loss - 1e-4*step*sum(g*g for g in grad):
                break
            step /= 2
        else:
            break
        x = candidate
    _, final_grad = objective(x)
    converged = converged or max(abs(g) for g in final_grad)/max(1., total) < config.tolerance
    rates = [(exp(x[0]+x[2+hi]+x[2+n+ai]), exp(x[1]+x[2+ai]+x[2+n+hi]), hg, ag, w)
             for hi, ai, hg, ag, w in data]
    # Predeclared grid, TRAIN only. Reject candidates invalid for ANY fitted
    # fixture. Prediction can abstain if future rates violate rho support.
    def rho_loss(rho):
        if any(min(tau(h,a,lh,la,rho) for h in (0,1) for a in (0,1)) <= 0
               for lh,la,*_ in rates):
            return float('inf')
        return -sum(w*log(tau(hg,ag,lh,la,rho)) for lh,la,hg,ag,w in rates)+config.ridge*rho*rho
    rho = min((i/100 for i in range(-20, 21)), key=lambda r: (rho_loss(r), abs(r), r))
    return {'intercepts': x[:2], 'attack': dict(zip(teams, x[2:2+n])),
            'defense': dict(zip(teams, x[2+n:])), 'rho': rho,
            'converged': converged, 'iterations': iteration+1,
            'gradient_per_weight': max(abs(g) for g in final_grad)/max(1.,total)}


def fit(model, rows, *, cutoff, league, profile, season, config=Config()):
    if model not in MODELS[1:]:
        raise ValueError('baseline is replayed, never refitted')
    rows = checked_rows(rows, cutoff, league, profile, season, config)
    counts = Counter(t for r in rows for t in (r['home'], r['away']))
    artifact = {'schema': 'prediction-edge-fit-v1', 'model': model, 'cutoff': cutoff,
                'league': league, 'profile': profile, 'season': season,
                'config': asdict(config), 'training_ids': sorted(counts_id['id'] for counts_id in rows),
                'training_digest': digest(rows), 'research_hash': research_hash(),
                'synthetic': any(r['synthetic'] for r in rows),
                'team_counts': dict(counts), 'rows': rows, 'parameters': None,
                'monetary_permission': False, 'status': 'UNTRAINABLE'}
    if len(rows) >= config.min_matches and len(counts) >= 4:
        if model == 'DC_DYNAMIC_V1':
            artifact['parameters'] = _dc_fit(rows, cutoff, season, config)
            artifact['status'] = 'FITTED_SHADOW' if artifact['parameters']['converged'] else 'UNTRAINABLE_NONCONVERGED'
        else:
            artifact['status'] = 'FITTED_SHADOW'
    artifact['hash'] = digest(artifact)
    return artifact


def _sos_rates(rows, home, away, cutoff, season, config):
    def league_rates(history, at):
        weighted = [(r, weight(r,at,season,config)) for r in history]
        total = sum(w for _,w in weighted)
        return tuple((sum(w*r[k] for r,w in weighted)+config.prior_games*prior)/(total+config.prior_games)
                     for k,prior in (('home_goals',1.35),('away_goals',1.10)))
    lh, la = league_rates(rows, cutoff)
    def strength(team, history, at, adjust=False):
        attack = defense = total = 0.
        for r in history:
            if team not in (r['home'],r['away']): continue
            home_side = r['home'] == team; gf,ga = (r['home_goals'],r['away_goals']) if home_side else (r['away_goals'],r['home_goals'])
            prior = [q for q in rows if time(q['received_at']) < time(r['kickoff'])]
            ph,pa = league_rates(prior, r['kickoff'])
            opp = r['away'] if home_side else r['home']
            oa,od = strength(opp,prior,r['kickoff']) if adjust else (1.,1.)
            w = weight(r,at,season,config); total += w
            attack += w*gf/(ph if home_side else pa)/min(2.,max(.5,od))
            defense += w*ga/(pa if home_side else ph)/min(2.,max(.5,oa))
        return ((attack+config.prior_games)/(total+config.prior_games),
                (defense+config.prior_games)/(total+config.prior_games))
    ha,hd = strength(home,rows,cutoff,True); aa,ad = strength(away,rows,cutoff,True)
    return lh*(ha+ad)/2, la*(aa+hd)/2


def predict(artifact, *, match_id, home, away, league, profile, season, as_of, kickoff):
    payload = dict(artifact); signature = payload.pop('hash', None)
    if digest(payload) != signature or artifact['research_hash'] != research_hash():
        raise ValueError('artifact integrity/code mismatch')
    if artifact['monetary_permission'] is not False:
        raise ValueError('research cannot grant money permission')
    if (league,profile,season) != (artifact['league'],artifact['profile'],artifact['season']):
        raise ValueError('prediction context mismatch')
    if not time(artifact['cutoff']) <= time(as_of) < time(kickoff) or match_id in artifact['training_ids']:
        raise ValueError('prediction chronology/target leakage')
    text(match_id, 'match id'); text(home,'home'); text(away,'away')
    if home == away: raise ValueError('distinct teams required')
    config = Config(**artifact['config'])
    checked_rows(artifact['rows'], artifact['cutoff'], league, profile, season, config)
    if artifact['status'] != 'FITTED_SHADOW':
        return {'status': artifact['status'], 'mass': None}
    if (time(as_of)-time(artifact['cutoff'])).total_seconds() > 86400*7:
        return {'status':'STALE_FIT', 'mass':None}
    if min(artifact['team_counts'].get(t,0) for t in (home,away)) < config.min_team_matches:
        return {'status': 'INSUFFICIENT_HISTORY', 'mass': None}
    rho = 0.
    if artifact['model'] == 'DC_DYNAMIC_V1':
        p = artifact['parameters']; rho = p['rho']
        lh = exp(p['intercepts'][0]+p['attack'][home]+p['defense'][away])
        la = exp(p['intercepts'][1]+p['attack'][away]+p['defense'][home])
    else:
        lh,la = _sos_rates(artifact['rows'],home,away,artifact['cutoff'],season,config)
    if not 0 <= lh <= 12 or not 0 <= la <= 12:
        return {'status':'RATE_OUT_OF_DOMAIN','mass':None}
    try:
        mass,tail = score_mass(lh,la,rho)
    except ValueError:
        return {'status':'DC_OUT_OF_DOMAIN','mass':None}
    return {'status':'SHADOW_ONLY','mass':mass,'rates':[lh,la],'rho':rho,
            'tail_bound':tail,'model_hash':artifact['hash'],'monetary_permission':False}


def baseline(sports, policy):
    if policy.goal_model != 'BASELINE_V1':
        raise ValueError('exact baseline policy required')
    return estimate(sports, policy)
