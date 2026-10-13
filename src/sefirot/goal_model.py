"""Sports-only SoS features and a frozen, profile-specific four-count model.

This is part of Probability, not a second voting model. A fitted threshold
distribution rescales the coherent score mass used by every main market.
Artifacts never contain prices and never confer monetary admission.
"""
from __future__ import annotations

from dataclasses import replace
from math import exp, log

from .contracts import digest, integer, number, strict, text, time, PROFILES
from .evidence import eligible_history, profile_of
from .identity import code_hash,MODEL_IDENTITY_SCHEMA

MODEL = 'goals-sos-threshold-v2'
RATE_BANDS = (.75, 1.25, 1.75, 2.5)


def rate_band(rate):
    number(rate, 'goal rate', .01, 12)
    return str(sum(rate >= boundary for boundary in RATE_BANDS))


def _weight(row, cutoff, policy):
    return exp(-log(2) * (time(cutoff)-time(row['kickoff'])).total_seconds()
               / 86400 / policy.half_life_days)


def league_rates(rows, cutoff, policy):
    weighted = [(row, _weight(row, cutoff, policy)) for row in rows]
    total = sum(w for _, w in weighted)
    return tuple((sum(w*r[side+'_goals'] for r, w in weighted)
                  + policy.prior_games*prior) / (total+policy.prior_games)
                 for side, prior in (('home', 1.35), ('away', 1.10)))


def frozen_schedule(rows, policy, targets=None):
    """Freeze each opponent before historic kickoff, including receipt cutoff.

    The normalization is frozen too: later league averages cannot change an
    earlier game's weights. Separate weights adjust goals for and against.
    """
    prepared = [(r, time(r['kickoff']), time(r['received_at'])) for r in rows]
    output = []
    for row, kickoff, _ in prepared:
        if targets is not None and not targets.intersection((row['home'],row['away'])):
            continue
        prior_rows = [r for r, start, received in prepared
                      if start < kickoff and received <= kickoff and r['id'] != row['id']
                      and (kickoff-start).days <= policy.history_days]
        lh, la = league_rates(prior_rows, row['kickoff'], policy)
        prior = (lh+la)/2
        for side in ('home', 'away'):
            team = row[side]
            if targets is not None and team not in targets:
                continue
            opponent = row['away' if side == 'home' else 'home']
            earlier = [r for r in prior_rows if opponent in (r['home'], r['away'])]
            weighted = [(r, _weight(r, row['kickoff'], policy)) for r in earlier]
            total = sum(w for _, w in weighted)
            attack = (sum(w*(r['home_goals'] if r['home'] == opponent else r['away_goals'])
                          for r, w in weighted)+policy.prior_games*prior)/(total+policy.prior_games)
            defense = (sum(w*(r['away_goals'] if r['home'] == opponent else r['home_goals'])
                           for r, w in weighted)+policy.prior_games*prior)/(total+policy.prior_games)
            bound = lambda value: min(policy.sos_weight_max, max(policy.sos_weight_min, value))
            attack_weight = bound(prior/max(.05, defense))
            defense_weight = bound(prior/max(.05, attack))
            output.append({'history_id': row['id'], 'team': team, 'opponent': opponent,
                           'frozen_at': row['kickoff'], 'opponent_games': len(earlier),
                           'opponent_attack': attack, 'opponent_defense': defense,
                           'league_prior_at_kickoff': prior,
                           'attack_weight': attack_weight, 'defense_weight': defense_weight,
                           'schedule_weight': (attack_weight+defense_weight)/2,
                           'used_ids': [r['id'] for r in earlier],
                           'normalization_ids': [r['id'] for r in prior_rows],
                           'used_in_probability': True,
                           'status': 'FROZEN_SPORTS_FEATURE' if earlier else 'PRIOR_ONLY'})
    return output


def adjusted_rates(sports, policy, profile_parameters=None, schedule=None):
    rows, excluded = eligible_history(sports, policy)
    match = sports['match']
    lh, la = (profile_parameters['home_prior'], profile_parameters['away_prior']) if profile_parameters else league_rates(rows, sports['as_of'], policy)
    avg = (lh+la)/2
    full_rows,_=eligible_history(sports,replace(policy,history_days=1000000))
    active_ids={r['id'] for r in rows}
    all_trace=(frozen_schedule(full_rows, policy, {match['home'], match['away']}) if schedule is None else schedule)
    trace = [t for t in all_trace
                                      if t['team'] in (match['home'], match['away'])
                                      and t['history_id'] in active_ids]
    index = {(t['history_id'], t['team']): t for t in trace}
    if len(index) != sum(int(r['home'] in (match['home'], match['away']))
                         + int(r['away'] in (match['home'], match['away'])) for r in rows):
        raise ValueError('incomplete frozen schedule')

    def team(name):
        subset = [(r, _weight(r, sports['as_of'], policy))
                  for r in rows if name in (r['home'], r['away'])]
        total = sum(w for _, w in subset)
        attack_sum = defense_sum = 0.
        for r, w in subset:
            context = index[(r['id'], name)]
            gf, ga = ((r['home_goals'], r['away_goals']) if r['home'] == name
                      else (r['away_goals'], r['home_goals']))
            attack_sum += w*gf*context['attack_weight']
            defense_sum += w*ga*context['defense_weight']
        attack = (attack_sum+policy.prior_games*avg)/(total+policy.prior_games)
        defense = (defense_sum+policy.prior_games*avg)/(total+policy.prior_games)
        effective = total*total/sum(w*w for _, w in subset) if subset else 0.
        return attack, defense, len(subset), effective

    ha, hd, hn, he = team(match['home'])
    aa, ad, an, ae = team(match['away'])
    bounded = lambda rate: min(12., max(.05, rate))
    rates = (bounded((ha+ad)/2*lh/avg), bounded((aa+hd)/2*la/avg))
    return rates, {'team_games': [hn, an], 'effective_games': [he, ae],
                   'used_history': [r['id'] for r in rows], 'excluded_history': excluded,
                   'history_digest': digest(rows), 'schedule_trace': trace,
                   'schedule_archive_rows':len(full_rows),
                   'schedule_archive_completeness':'CALLER_SUPPLIED; missing older context cannot be recovered'}


def fit_goal_model(training_sports, records, policy, fit_at, model_hash):
    """Profile priors use TRAIN; count buckets use later CALIBRATION only.

    Each count record must have been predicted before its result. The caller
    cannot claim that reconstructed records are prospective merely by fitting.
    """
    if policy.goal_model != 'SOS_THRESHOLD_V2':
        raise ValueError('fit requires SOS_THRESHOLD_V2 policy')
    strict(training_sports,('match','as_of','sources','evidence','history'),('synthetic','thesis_links'))
    if any(e.get('key')=='market_news' for e in training_sports['evidence']):
        raise ValueError('market evidence is forbidden in sports model fit')
    seen_sources=set()
    for source in training_sports['sources']:
        strict(source,('id','independence_group','reliability','enabled'))
        text(source['id'],'source id');text(source['independence_group'],'source group')
        number(source['reliability'],'source reliability',0,1)
        if source['id'] in seen_sources or type(source['enabled']) is not bool:
            raise ValueError('distinct valid training sources required')
        seen_sources.add(source['id'])
    if time(training_sports['as_of']) > time(fit_at):
        raise ValueError('training cutoff follows fit')
    rows, excluded = eligible_history(training_sports, policy)
    if excluded:
        raise ValueError('training data must be explicitly filtered, not silently excluded')
    profile = profile_of(training_sports['match'])
    if profile == 'UNKNOWN' or not rows:
        raise ValueError('known profile and nonempty training history required')
    train_ids = {r['id'] for r in rows}
    lh, la = league_rates(rows, training_sports['as_of'], policy)
    groups = {}
    ids = set()
    synthetic = bool(training_sports.get('synthetic', False))
    reconstructed = False
    for r in records:
        strict(r, ('match_id', 'league', 'competition_profile', 'side', 'rate', 'goals',
                   'predicted_at', 'kickoff', 'received_at', 'synthetic', 'reconstructed'))
        text(r['match_id'], 'threshold match id')
        if r['league'] != training_sports['match']['league'] or r['competition_profile'] != profile:
            raise ValueError('threshold calibration cannot mix leagues or profiles')
        if r['side'] not in ('home', 'away') or any(type(r[k]) is not bool for k in ('synthetic','reconstructed')):
            raise ValueError('invalid threshold calibration metadata')
        if not time(training_sports['as_of']) < time(r['predicted_at']) < time(r['kickoff']) < time(r['received_at']) <= time(fit_at):
            raise ValueError('threshold calibration chronology/leakage')
        if r['match_id'] in train_ids or (r['match_id'], r['side']) in ids:
            raise ValueError('overlapping or duplicate threshold calibration')
        ids.add((r['match_id'], r['side']))
        integer(r['goals'], 'threshold goals', 0, 50)
        key = rate_band(r['rate'])
        counts = groups.setdefault(key, [0, 0, 0, 0])
        counts[min(3, r['goals'])] += 1
        synthetic = synthetic or r['synthetic']
        reconstructed = reconstructed or r['reconstructed']
    artifact = {'version': MODEL, 'fit_at': fit_at, 'code_hash': code_hash(),
                'model_hash':model_hash,'identity_schema':MODEL_IDENTITY_SCHEMA,
                'policy_hash': policy.fingerprint, 'league': training_sports['match']['league'],
                'competition_profile': profile, 'training_as_of': training_sports['as_of'],
                'profile_parameters': {'home_prior': lh, 'away_prior': la, 'n': len(rows)},
                'training_ids': sorted(train_ids), 'calibration_ids': sorted({mid for mid, _ in ids}),
                'fit_ids': sorted(train_ids | {mid for mid, _ in ids}),
                'rate_bands': list(RATE_BANDS), 'buckets': groups,
                'synthetic': synthetic, 'reconstructed': reconstructed,
                'training_digest': digest(rows), 'calibration_digest': digest(records),
                'status': 'FITTED_RESEARCH_ONLY', 'monetary_permission': False}
    artifact['hash'] = digest(artifact)
    return artifact


def validate_artifact(artifact, sports, policy, model_hash):
    if artifact is None:
        return
    strict(artifact, ('version', 'fit_at', 'code_hash', 'model_hash', 'identity_schema', 'policy_hash', 'league',
                     'competition_profile', 'training_as_of', 'profile_parameters',
                     'training_ids', 'calibration_ids', 'fit_ids', 'rate_bands', 'buckets',
                     'synthetic', 'reconstructed', 'training_digest', 'calibration_digest',
                     'status', 'monetary_permission', 'hash'))
    original = dict(artifact)
    signature = original.pop('hash')
    if digest(original) != signature or artifact['model_hash'] != model_hash or artifact['policy_hash'] != policy.fingerprint:
        raise ValueError('goal artifact hash/code/policy mismatch')
    if artifact['version'] != MODEL or artifact['identity_schema'] != MODEL_IDENTITY_SCHEMA or artifact['rate_bands'] != list(RATE_BANDS):
        raise ValueError('goal model schema mismatch')
    if artifact['league'] != sports['match']['league'] or artifact['competition_profile'] != profile_of(sports['match']):
        raise ValueError('goal artifact league/profile mismatch')
    if time(artifact['fit_at']) >= time(sports['as_of']) or sports['match']['id'] in artifact['fit_ids']:
        raise ValueError('goal artifact future fit or target leakage')
    if time(artifact['training_as_of'])>time(artifact['fit_at']):
        raise ValueError('goal artifact training chronology')
    strict(artifact['profile_parameters'], ('home_prior', 'away_prior', 'n'))
    for side in ('home', 'away'):
        number(artifact['profile_parameters'][side+'_prior'], 'profile prior', .01, 12)
    integer(artifact['profile_parameters']['n'], 'profile sample', 1)
    if any(type(artifact[k]) is not bool for k in ('synthetic', 'reconstructed')) or artifact['monetary_permission'] is not False:
        raise ValueError('invalid goal artifact provenance/admission')
    for key in ('training_ids','calibration_ids','fit_ids'):
        if not isinstance(artifact[key],list) or any(not isinstance(mid,str) or not mid for mid in artifact[key]) or len(set(artifact[key]))!=len(artifact[key]):
            raise ValueError('distinct goal artifact match IDs required')
    if set(artifact['training_ids']) & set(artifact['calibration_ids']) or set(artifact['fit_ids']) != set(artifact['training_ids']) | set(artifact['calibration_ids']):
        raise ValueError('goal artifact split overlap')
    for key, counts in artifact['buckets'].items():
        if key not in {str(i) for i in range(len(RATE_BANDS)+1)} or len(counts) != 4:
            raise ValueError('invalid count-model bucket')
        for count in counts:
            integer(count, 'threshold count')


def count_marginal(rate, artifact, policy):
    """Learn P(0), P(1), P(2), P(3+) rather than just project a Poisson.

    The >=3 conditional tail retains its base shape; fitting overdispersion and
    player effects remains P1. Small/absent bins explicitly remain unvalidated.
    """
    from .probability import poisson
    base, tail = poisson(rate)
    raw = [base[0], base[1], base[2], sum(base[3:])]
    counts = artifact['buckets'].get(rate_band(rate)) if artifact else None
    n = sum(counts or [])
    status = 'FITTED_COUNT_BIN' if n >= policy.min_threshold_bin else 'INSUFFICIENT_COUNT_BIN'
    probs = ([(counts[i]+policy.threshold_prior_games*raw[i])/(n+policy.threshold_prior_games)
              for i in range(4)] if status == 'FITTED_COUNT_BIN' else raw)
    marginal = probs[:3]+[p*probs[3]/raw[3] for p in base[3:]]
    return marginal, min(1.,tail*max(1.,probs[3]/raw[3])), {'status': status, 'n': n, 'band': rate_band(rate),
                            'raw_buckets': raw, 'buckets': probs,
                            'method': 'profile/league count frequencies with Dirichlet shrinkage'}


def score_distribution(home, away, artifact, policy):
    hp, ht, home_info = count_marginal(home, artifact, policy)
    ap, at, away_info = count_marginal(away, artifact, policy)
    mass = {(h, a): p*q for h, p in enumerate(hp) for a, q in enumerate(ap)}
    return mass, min(1., ht+at), {'home': home_info, 'away': away_info}


def estimate(sports, policy, artifact=None, *, schedule=None):
    parameters = artifact['profile_parameters'] if artifact else None
    (lh, la), summary = adjusted_rates(sports, policy, parameters, schedule)
    mass, tail, thresholds = score_distribution(lh, la, artifact, policy)
    variants = [];stress_thresholds=[]
    scale = policy.stress_rate_fraction
    for hm, am in ((1-scale,1-scale), (1-scale,1+scale), (1+scale,1-scale), (1+scale,1+scale)):
        stressed, residual, bins = score_distribution(min(12.,max(.05,lh*hm)), min(12.,max(.05,la*am)), artifact, policy)
        variants.append(stressed)
        stress_thresholds.append(bins)
        tail = max(tail, residual)
    from .probability import goal_thresholds
    top = sorted(mass.items(), key=lambda item: (-item[1], item[0]))[:5]
    summary.update({'model_version': MODEL, 'competition_profile': profile_of(sports['match']),
                    'rates': {'home': lh, 'away': la}, 'tail_bound': tail,
                    'rates_kind':'PRE_COUNT_CALIBRATION_RATE',
                    'expected_goals':{'home':sum(h*p for (h,a),p in mass.items()),'away':sum(a*p for (h,a),p in mass.items())},
                    'goal_thresholds': goal_thresholds(mass), 'threshold_model': thresholds,
                    'stress_threshold_models':stress_thresholds,
                    'goal_model_hash': artifact['hash'] if artifact else None,
                    'profile_parameters_status': 'FITTED_RESEARCH_ONLY' if artifact else 'UNFITTED',
                    'profile_parameters': parameters,
                    'score_scenarios': [{'home': h, 'away': a, 'probability': p} for (h,a),p in top],
                    'uncertainty_method': 'frozen count model, market calibration and rate sensitivity; no claimed confidence coverage',
                    'training_prior': 'sports-only frozen profile prior; shrinkage and SoS weights are research parameters'})
    return mass, variants, summary
