"""Error Hunter and falsifiable hypotheses over the existing ARENA v0.2 views.

Reviewers can select reproducible hypotheses, not supply new facts or mechanisms.
All claims concern archived inputs/math; real source/time authenticity is UNKNOWN.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path

from scripts.arena_control import (finding as legacy_finding, run_control, sports_view,
                                   validate_findings as legacy_validate)
from scripts.arena_shadow import ROLE_SPECS
from sefirot.contracts import Policy, canonical, digest, integer, time
from sefirot.engine import selection_constraints
from sefirot.evidence import inspect
from sefirot.markets import market_of, probabilities, settle
from sefirot.probability import distribution
from sefirot.repository import Repository

from .contracts import Finding, ROLES, SCHEMA
from .counterfactual import REVIEW_DELTA, run_lab

REPORT_SCHEMA = 'arena1-diagnostic-registry-v1'


@dataclass(frozen=True, slots=True)
class Context:
    prediction_json: str
    quotes_json: str
    control_json: str
    views_json: str
    lab_json: str
    at: str

    @property
    def prediction(self):
        return json.loads(self.prediction_json)

    @property
    def quotes(self):
        return json.loads(self.quotes_json)

    @property
    def control(self):
        return json.loads(self.control_json)

    @property
    def views(self):
        return json.loads(self.views_json)

    @property
    def lab(self):
        return json.loads(self.lab_json)


def bind(prediction, quotes, at, *, database=None, decision_id=None, legacy_reviews=None):
    if not isinstance(prediction, dict):
        raise ValueError('original prediction object required')
    p = deepcopy(prediction)
    for key in ('captured_prematch', 'reconstructed', 'synthetic'):
        if type(p.get(key)) is not bool:
            raise ValueError('boolean original capture flags required')
    if p.get('parent') is not None or p.get('revision') != 0:
        raise ValueError('original unrevised seal required')
    cutoff = time(p['sports']['as_of'])
    calibrator = p.get('calibrator')
    if calibrator is not None:
        if (calibrator.get('hash') != digest({k: v for k, v in calibrator.items() if k != 'hash'})
                or calibrator['model_hash'] != p['model_hash'] or calibrator['policy_hash'] != p['policy_hash']
                or time(calibrator['fit_at']) > cutoff
                or p['sports']['match']['id'] in calibrator['fit_ids']
                or len(set(calibrator['fit_ids'])) != len(calibrator['fit_ids'])):
            raise ValueError('calibrator fit identity/time leakage')
    for c in p['candidates']:
        integer(c['calibration_n'], 'original calibration count', 0)
        if c['calibration'] not in ('UNCALIBRATED', 'INSUFFICIENT_BIN', 'CALIBRATED_BIN'):
            raise ValueError('unknown original calibration label')
    # A poisoned original input is rejected; it is not silently relabelled a fact.
    for row in p['sports']['history']:
        if row['id'] == p['sports']['match']['id'] or time(row['received_at']) > cutoff:
            raise ValueError('result leakage in original sports input')
    control = run_control(p, deepcopy(quotes), at, database=database, decision_id=decision_id,
                          recorded_reviews=deepcopy(legacy_reviews))
    if database is not None:
        _check_ledger_alignment(database, p, control)
    policy = Policy(**p['policy'])
    sports = sports_view(p, policy)
    for fact in sports['evidence']:
        fact['available_at'] = fact['received_at']
        fact['availability_basis'] = 'LOCAL_RECEIPT_ONLY'
    lab = run_lab(p)
    diagnostics = [{'market': c['key'], 'calibration': c['calibration'],
                    'raw': c['raw'], 'base': c['base']} for c in p['candidates']]
    views = {}
    for name, phase, _ in ROLE_SPECS:
        view = {'role': name, 'phase': phase, 'sports': deepcopy(sports),
                'model_diagnostics': deepcopy(diagnostics)}
        if phase == 'priced':
            # Quote text/bookmaker names do not become instructions or evidence.
            view['market_rows'] = [{k: r[k] for k in ('market', 'odds', 'ev', 'quote_hash')}
                                   for r in control['candidate_rows']]
            view['quote_receipts'] = [{'market_key': market_of(q['market']).key, 'quote_hash': digest(q),
                                       'observed_at': time(q['observed_at']).isoformat(),
                                       'received_at': time(q['received_at']).isoformat(),
                                       'availability_basis': 'LOCAL_RECEIPT_ONLY'} for q in quotes]
        views[name] = view
    return Context(canonical(p), canonical(quotes), canonical(control), canonical(views), canonical(lab), time(at).isoformat())


def _check_ledger_alignment(database, p, control):
    """Also bind SQL columns/FKs; a payload-only hash chain cannot do that."""
    repo = Repository(database, read_only=True)
    try:
        repo.db.execute('BEGIN')
        if (repo.db.execute('PRAGMA quick_check').fetchone()[0] != 'ok'
                or repo.db.execute('PRAGMA foreign_key_check').fetchall() or not repo.verify()):
            raise ValueError('global ledger integrity failure')
        row = repo.db.execute('SELECT * FROM predictions WHERE id=?', (p['id'],)).fetchone()
        if (row is None or canonical(repo.get('predictions', p['id'])) != canonical(p)
                or row['match_id'] != p['sports']['match']['id'] or row['model_id'] != p['model_id']
                or time(row['at']) != time(p['sealed_at'])):
            raise ValueError('original prediction column/payload alignment failure')
        original = control['provenance']['original']
        if original is not None:
            d = repo.get('decisions', original['id'])
            row = repo.db.execute('SELECT * FROM decisions WHERE id=?', (d['id'],)).fetchone()
            if (d['prediction_id'] != p['id'] or d['match_id'] != p['sports']['match']['id']
                    or row['prediction_id'] != p['id'] or time(row['at']) != time(d['at'])
                    or time(d['at']) != time(original['at'])):
                raise ValueError('original decision column/payload alignment failure')
    finally:
        repo.close()


def _make(ctx, role, category, mechanism, test, *, market=None, premise=None,
          ids=(), state='UNKNOWN', unknowns=(), counterexample=None):
    p = ctx.prediction
    facts = {e['id']: e for e in ctx.views[role]['sports']['evidence']}
    groups = tuple(sorted({facts[eid]['independence_group'] for eid in ids}))
    original = ctx.control['provenance']['original']
    phase = ROLES[role]
    cutoff = p['sports']['as_of'] if phase == 'sports' else ctx.at
    return Finding(schema=SCHEMA, fixture_id=p['sports']['match']['id'], prediction_id=p['id'],
                   decision_id=original['id'] if original else None, model_hash=p['model_hash'],
                   code_hash=p['code_hash'], policy_hash=p['policy_hash'], role=role, phase=phase,
                   category=category, market_key=market, premise_id=premise,
                   evidence_ids=tuple(sorted(ids)), independence_groups=groups, state=state,
                   effective_at=time(cutoff).isoformat(), mechanism=mechanism, test_condition=test,
                   expected_direction='UNQUANTIFIED', hypothesis_version='1.0',
                   unknowns=tuple(unknowns), counterexample=canonical(counterexample) if counterexample is not None else None,
                   action='REVIEW_ONLY', monetary_permission=False)


def _builder_probe(p):
    pair = ('1X2:HOME', 'BTTS:YES')  # One fixed model-consistency probe, not a suggested ticket.
    by_key = {c['key']: c for c in p['candidates']}
    if not set(pair) <= by_key.keys() or p['policy']['goal_model'] != 'BASELINE_V1':
        return {'status': 'UNKNOWN', 'reason': 'ORIGINAL_JOINT_MODEL_OR_FIXED_LEGS_MISSING',
                'legs': [], 'joint_win': None, 'product_win': None, 'combined_odds': None, 'ev': None}
    mass, _ = distribution(p['model']['rates']['home'], p['model']['rates']['away'])
    markets = [market_of(by_key[key]['market']) for key in pair]
    marginal = [probabilities(m, mass)[0] for m in markets]
    joint = sum(value for (h, a), value in mass.items()
                if all(settle(m, h, a) == 'WIN' for m in markets))
    return {'status': 'UNPRICED', 'legs': list(pair), 'joint_win': joint,
            'product_win': marginal[0] * marginal[1], 'probability_source': 'SHARED_RAW_SCORE_MASS',
            'combined_odds': None, 'ev': None, 'joint_calibration': 'UNKNOWN',
            'external_quote_time_verified': False, 'monetary_permission': False}


def hunt(ctx):
    """Deterministic proof templates; no freely authored reviewer fact is accepted."""
    p, control, lab = ctx.prediction, ctx.control, ctx.lab
    result = []
    by_key = {c['key']: c for c in p['candidates']}
    facts = ctx.views['history']['sports']['evidence']
    for c in p['candidates']:
        key = c['key']
        if not market_of(c['market']).push_possible and any(c[field][1] > 1e-8 for field in ('raw', 'base')):
            result.append(_make(ctx, 'probability_critic', 'IMPOSSIBLE_PUSH_MASS',
                'A push-free contract assigns positive probability to PUSH.',
                'The exact contract has no push score cells; every raw/calibrated PUSH component must equal zero.',
                market=key, premise='candidate:' + key, state='SUPPORTED',
                counterexample={'raw': c['raw'], 'base': c['base'], 'push_possible': False}))
        result.append(_make(ctx, 'probability_critic', 'CALIBRATION_UNVERIFIED',
            'An original bin label/count does not establish independent profile/contract calibration.',
            'A future separately registered independent cohort must bound calibration error for this exact profile, market, line and period.',
            market=key, premise='candidate:' + key,
            unknowns=('independent cohort and external source/time proof',),
            counterexample={'profile': p['sports']['match']['competition_profile'], 'market': key,
                            'period': 'REGULATION_90', 'original_bin_n': c['calibration_n'],
                            'original_status': c['calibration'], 'externally_verified_n': None}))
        if lab['status'] != 'SENSITIVITY_ONLY':
            continue
        expected = lab['baseline_projection'][key]
        actual = c['raw']
        if max(abs(x - y) for x, y in zip(expected, actual)) > 1e-8:
            result.append(_make(ctx, 'probability_critic', 'SCORE_PROJECTION_MISMATCH',
                'The archived raw win/push/loss vector differs from its declared score distribution.',
                'Replaying the archived distribution and exact contract must reproduce all three raw components within 1e-8.',
                market=key, premise='candidate:' + key, state='SUPPORTED',
                counterexample={'original_raw': actual, 'score_projection': expected,
                                'max_absolute_error': max(abs(x - y) for x, y in zip(expected, actual))}))
        worst = max(lab['scenarios'], key=lambda s: abs(s['probabilities'][key][0] - expected[0]), default=None)
        if worst and abs(worst['probabilities'][key][0] - expected[0]) >= REVIEW_DELTA:
            result.append(_make(ctx, 'probability_critic', 'SENSITIVITY_THRESHOLD_EXCEEDED',
                'A predeclared synthetic input probe changes raw win probability by at least the review threshold; this is sensitivity only.',
                'Repeat the fixed probe on the original archived inputs; no observed injury/event or calibrated probability correction follows.',
                market=key, premise='candidate:' + key, state='SUPPORTED',
                unknowns=('empirical validity of stress range',),
                counterexample={'scenario': worst['name'], 'label': 'SENSITIVITY_ONLY',
                                'original_raw_win': expected[0], 'probe_raw_win': worst['probabilities'][key][0],
                                'review_delta': REVIEW_DELTA}))

    # Count declarations; never treat repeated provider records as independent trials.
    buckets = {}
    for e in facts:
        buckets.setdefault(e['key'], []).append(e)
    for key, copies in sorted(buckets.items()):
        if len(copies) < 2:
            continue
        ids = [e['id'] for e in copies]
        groups = sorted({e['independence_group'] for e in copies})
        result.append(_make(ctx, 'history', 'SOURCE_REPLICATION',
            'Several visible records for one premise are not several verified independent confirmations.',
            'Independent upstream origin and first receipt must be established separately for every claimed source family.',
            premise=ids[0], ids=ids, state='SUPPORTED' if len(groups) == 1 else 'UNKNOWN',
            unknowns=('upstream source-family authenticity',),
            counterexample={'key': key, 'records': len(ids), 'declared_groups': groups,
                            'verified_independent_groups': None}))
    rows = {r['id']: r for r in p['sports']['history']}
    used = [rows[rid] for rid in p['model']['used_history']]
    result.append(_make(ctx, 'history', 'HISTORY_CONCENTRATION',
        'Archived history concentration is observable; generalisation to new teams, leagues or seasons is unmeasured.',
        'A future untouched cohort stratified by team, league and season must test the concentration hypothesis.',
        unknowns=('independent generalisation sample', 'season field unavailable'),
        counterexample={'used_fixtures': len(used), 'leagues': len({r['league'] for r in used}),
                        'teams': len({r[side] for r in used for side in ('home', 'away')})}))

    # A block is a reproducible contradiction of a sealed directive, not a critic's opinion.
    policy = Policy(**p['policy'])
    witness = inspect(p['sports'], policy)
    constraints, issues = selection_constraints(p['sports'], witness, policy)
    if constraints != p['scenario']['selection_constraints']:
        raise ValueError('original selection constraint does not reproduce')
    if constraints['avoid_result'] and not issues:
        supports = sorted({ref for e in p['sports']['evidence']
                           if e['id'] in constraints['evidence_ids'] for ref in e['supports']})
        visible = {e['id'] for e in facts}
        supports = [ref for ref in supports if ref in visible]
        for c in p['candidates']:
            if c['market']['kind'] in ('1X2', 'DOUBLE_CHANCE', 'DNB', 'HANDICAP') and supports:
                bound = control['provenance']['status'] == 'LOCAL_LEDGER_BOUND'
                result.append(_make(ctx, 'death_test', 'RESULT_MARKET_CONSTRAINT',
                    'This exact result contract contradicts the original evidence-bound avoid_result directive.',
                    'A changed or removed premise requires a new sports seal; the current sealed directive excludes this contract.',
                    market=c['key'], premise=supports[0], ids=supports, state='HARD_BLOCK' if bound else 'UNKNOWN',
                    unknowns=() if bound else ('original directive receipt is unbound',),
                    counterexample={'sealed_premise_hash': constraints['premise_hash'],
                                    'market_family': c['market']['kind'], 'avoid_result': True}))

    for role, category, unknown in (
        ('tactics', 'TACTICAL_EFFECT_UNKNOWN', 'validated tactical effect model'),
        ('lineups', 'LINEUP_EFFECT_UNKNOWN', 'validated lineup effect model'),
        ('schedule', 'SCHEDULE_EFFECT_UNKNOWN', 'confirmed rest/travel timeline')):
        result.append(_make(ctx, role, category,
            'The available sports view does not quantify this mechanism; narrative is not a probability adjustment.',
            'A separately confirmed prematch fact and prospective test of this mechanism are required.',
            unknowns=(unknown,)))
    if control['provenance']['original'] is None:
        result.append(_make(ctx, 'market_auditor', 'ORIGINAL_DECISION_MISSING',
            'No aligned original prematch PASS/BET receipt is available; missing is not PASS.',
            'Read an original decision with the same prediction, exact cutoff and quote content; do not backfill it.',
            unknowns=('aligned original decision',)))
    for r in control['candidate_rows']:
        key = r['market']
        local_quotes = [q for q in ctx.quotes if market_of(q['market']).key == key and q['phase'] in ('FINAL', 'ENTRY')]
        newest = max(local_quotes, key=lambda q: (time(q['observed_at']), time(q['received_at'])), default=None)
        if newest is not None:
            age = (time(ctx.at) - time(newest['observed_at'])).total_seconds()
            if age > policy.quote_max_age_seconds:
                result.append(_make(ctx, 'market_auditor', 'STALE_QUOTE_RECEIPT',
                    'The declared local observation time exceeds the archived maximum quote age; external time authenticity is unknown.',
                    'A fresh original exact-contract receipt must replace this stale input before it can be considered current.',
                    market=key, premise='candidate:' + key, state='SUPPORTED',
                    unknowns=('external quote time authenticity',),
                    counterexample={'quote_hash': digest(newest), 'age_seconds': age,
                                    'max_age_seconds': policy.quote_max_age_seconds}))
        if r['odds'] is None:
            result.append(_make(ctx, 'market_auditor', 'CURRENT_QUOTE_MISSING',
                'No fresh exact regulation-time quote is available for this original contract.',
                'An original post-seal quote receipt for this exact contract must be available before the review cutoff.',
                market=key, premise='candidate:' + key, unknowns=('fresh exact quote and external receipt',)))
    result.append(_make(ctx, 'market_auditor', 'QUOTE_ORIGIN_AND_CLV_UNKNOWN',
        'Local quote hashes and same-book prices do not authenticate origin/time or a closing-line comparison.',
        'Independent prematch and closing receipts for the same contract must be authenticated before CLV can be measured.',
        unknowns=('external quote origin/time', 'verified closing receipt')))
    builder = _builder_probe(p)
    if builder['legs'] and abs(builder['joint_win'] - builder['product_win']) > 1e-8:
        result.append(_make(ctx, 'risk_correlation', 'BUILDER_DEPENDENCE',
            'The fixed same-match legs have dependent win events in the shared raw score model; their product is not their joint probability.',
            'The shared score-cell projection must reproduce joint probability; independent prospective joint calibration remains required.',
            market=builder['legs'][0], premise='candidate:' + builder['legs'][0], state='SUPPORTED',
            counterexample={'legs': builder['legs'], 'joint_win': builder['joint_win'],
                            'product_win': builder['product_win'], 'label': 'MODEL_DEPENDENCE_ONLY'}))
    result.append(_make(ctx, 'risk_correlation', 'BUILDER_UNPRICED',
        'Single-leg prices are not a verified combined Builder quote; joint EV is undefined.',
        'An authenticated prematch combined quote with exact legs and settlement rules is required before joint EV.',
        unknowns=('verified combined odds', 'joint calibration', 'portfolio exposure')))
    result.append(_make(ctx, 'death_test', 'CAUSAL_FALSIFIER_UNKNOWN',
        'A stress branch or reviewer vote is not an observed causal sporting premise.',
        'Obtain an original point-in-time fact and a preregistered future condition that can refute the proposed mechanism.',
        unknowns=('independently confirmed causal premise',)))
    legacy_vetoes = [f for group in control['reviews'] for f in group if f['state'] == 'HARD_BLOCK']
    repeated = {}
    legacy_seen = set()
    for f in legacy_vetoes:
        signature = (f['market_key'], f['premise_id'], tuple(sorted(f['evidence_ids'])))
        repeated.setdefault(signature, []).append(f)
        if digest(f) in legacy_seen:
            continue
        legacy_seen.add(digest(f))
        result.append(_make(ctx, f['role'], 'LEGACY_VETO_UNVERIFIED',
            'A v0.2 evidence-ID allowlist does not verify that the cited fact entails the authored market veto.',
            'The original fact must satisfy an implemented market-specific mechanism before a new diagnostic block is accepted.',
            market=f['market_key'], premise=f['premise_id'], ids=f['evidence_ids'],
            unknowns=('reproducible fact-to-market mechanism',),
            counterexample={'legacy_finding_hash': digest(f)}))
    for (market, premise, ids), copies in repeated.items():
        if len(copies) > 1:
            # Use a priced role because repetitions may include the priced phase.
            result.append(_make(ctx, 'death_test', 'DUPLICATE_VETO',
                'Multiple role vetoes reuse the same market, premise and evidence; they are not independent confirmations.',
                'Deduplicate the exact evidence mechanism and measure role correlation only in a prospective cohort.',
                market=market, premise=premise, ids=ids, state='SUPPORTED',
                unknowns=('prospective role correlation',),
                counterexample={'role_vetoes': len(copies), 'unique_evidence_mechanisms': 1}))
    return tuple(result)


def validate_findings(items, ctx):
    return _validate(items, ctx, hunt(ctx))


def _validate(items, ctx, expected):
    if type(items) is not list or len(items) > 160:
        raise ValueError('bounded findings list required')
    allowed = {canonical(f.to_dict()) for f in expected}
    out, seen = [], set()
    for item in items:
        f = Finding.from_dict(item)
        encoded = canonical(f.to_dict())
        if encoded not in allowed:
            raise ValueError('hypothesis is not reproduced by original evidence/time/market mechanism')
        if encoded in seen:
            raise ValueError('duplicate hypothesis is not independent confirmation')
        seen.add(encoded)
        legacy = legacy_finding(f.role, f.phase, f.market_key, f.effective_at,
                                state=f.state, premise=f.premise_id, ids=f.evidence_ids,
                                groups=f.independence_groups, mechanism=f.mechanism, unknowns=f.unknowns)
        role = next(r for r in ROLE_SPECS if r[0] == f.role)
        cutoff = ctx.prediction['sports']['as_of'] if f.phase == 'sports' else ctx.at
        legacy_validate([legacy], role, ctx.views[f.role], cutoff)
        out.append(f)
    return tuple(out)


def diagnostic_hash():
    root = Path(__file__).parent
    return digest({p.name: p.read_text(encoding='utf-8') for p in sorted(root.glob('*.py'))})


def diagnose(prediction, quotes, at, *, database=None, decision_id=None, recorded_findings=None,
             legacy_reviews=None):
    ctx = bind(prediction, quotes, at, database=database, decision_id=decision_id, legacy_reviews=legacy_reviews)
    expected = hunt(ctx)
    findings = _validate([f.to_dict() for f in expected] if recorded_findings is None else recorded_findings,
                         ctx, expected)
    # Replay/selection must not suppress a deterministic error or a missing role.
    if {canonical(f.to_dict()) for f in findings} != {canonical(f.to_dict()) for f in expected}:
        raise ValueError('incomplete diagnostic replay: missing findings are not PASS')
    p, control = ctx.prediction, ctx.control
    local = {key: [f for f in findings if f.market_key == key] for key in ctx.lab.get('baseline_projection', {})}
    registry = []
    for c in p['candidates']:
        fs = local.get(c['key'], [f for f in findings if f.market_key == c['key']])
        registry.append({'market_key': c['key'], 'diagnostic_state':
                         'HARD_BLOCK' if any(f.state == 'HARD_BLOCK' for f in fs) else 'UNKNOWN',
                         'original_raw': c['raw'], 'original_base': c['base'],
                         'original_core_blockers': next(r['blockers'] for r in control['candidate_rows'] if r['market'] == c['key']),
                         'probability_changed': False, 'monetary_permission': False})
    vetoes = [f for group in control['reviews'] for f in group if f['state'] == 'HARD_BLOCK']
    signatures = [(f['market_key'], f['premise_id'], tuple(f['evidence_ids'])) for f in vetoes]
    # Roles/source families are declarations, not independent statistical observations.
    out = {'schema': REPORT_SCHEMA, 'fixture_id': p['sports']['match']['id'], 'prediction_id': p['id'],
           'decision_id': (control['provenance']['original'] or {}).get('id'), 'as_of': ctx.at,
           'sports_as_of': time(p['sports']['as_of']).isoformat(), 'sealed_at': p['sealed_at'],
           'kickoff': p['sports']['match']['kickoff'], 'model_hash': p['model_hash'], 'code_hash': p['code_hash'],
           'policy_hash': p['policy_hash'], 'diagnostic_hash': diagnostic_hash(),
           'synthetic': p['synthetic'], 'mode': 'RULE_REVIEW', 'control_report_hash': control['hash'],
           'legacy_reviews_provenance': 'SELF_ATTESTED_OFFLINE_INPUT' if legacy_reviews is not None else None,
           'registry_chronology': 'OFFLINE_AS_OF_RECONSTRUCTION_NOT_PROSPECTIVE_REGISTRATION',
           'local_provenance': control['provenance'], 'source_time_authenticity': 'UNKNOWN',
           'external_time_verified': False, 'global_hard_stop': control['global_hard_stop'],
           'empirical_hard_stop': True,
           'role_views': ctx.views, 'role_view_hashes': {role: digest(view) for role, view in ctx.views.items()},
           'findings': [f.to_dict() for f in findings], 'markets': registry, 'counterfactual_lab': ctx.lab,
           'builder_probe': _builder_probe(p),
           'critic_independence': {'independent_models_verified': False, 'declared_roles': 8,
                                   'duplicate_legacy_vetoes': len(signatures) - len(set(signatures)),
                                   'aggregation': 'UNIQUE_EVIDENCE_MECHANISMS_NOT_VOTES', 'phi': None},
           'forecast_probability_changed': False, 'real_train': 0, 'new_independent_holdout': 0,
           'arena_incremental_benefit': 'NOT_MEASURED', 'empirical_status': 'INSUFFICIENT_REAL_DATA',
           'model_action': 'KEEP_SHADOW', 'llm_calls': 0, 'llm_cost_usd': None, 'llm_latency_ms': None,
           'stake': 0., 'monetary_permission': False, 'execution_enabled': False}
    out['hash'] = digest(out)
    return out
