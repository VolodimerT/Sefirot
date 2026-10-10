"""Proof and search disclosures, not a fitted trust score or admission rule."""
from .action_plan import MODEL_CODES, DATA_CODES
from .contracts import time
from .markets import market_of, probabilities
from math import ulp


def probability_trust(prediction, candidate, decision):
    codes={i['code'] for i in decision['issues']+candidate['issues'] if i['severity']=='BLOCK'}
    proof_codes=sorted(codes & (MODEL_CODES | DATA_CODES | {
        'SYNTHETIC_DATA_RESEARCH_ONLY','GOAL_ARTIFACT_SYNTHETIC_RESEARCH_ONLY',
        'RETROSPECTIVE_CAPTURE','JOURNAL_INTEGRITY','LIVE_FORBIDDEN','UNSUPPORTED_FORMAT'}))
    proof_codes+=sorted(c for c in codes if c.startswith('MISSING_') and c!='MISSING_CURRENT_PRICE')
    release=decision['inputs']['context']['releases'].get(candidate['key'])
    health=candidate['competence'];model=prediction['model']
    traces=model.get('schedule_trace',[])
    return {'schema':'probability-trust-v1',
        'status':'BLOCKED' if proof_codes else 'EXISTING_GATES_PASSED',
        'score':None,'score_status':'NO_VALIDATED_NUMERIC_TRUST_SCORE',
        'blockers':sorted(set(proof_codes)),
        'components':{
            'history':{'team_games':model['team_games'],'effective_games':model.get('effective_games'),
                       'used_history_n':len(model['used_history']),
                       'status':'INSUFFICIENT' if 'INSUFFICIENT_HISTORY' in codes else 'POLICY_MINIMUM_CHECKED'},
            'calibration':{'status':candidate['calibration'],'n':candidate['calibration_n'],
                           'artifact_hash':prediction['calibrator']['hash'] if prediction['calibrator'] else None},
            'holdout':{'status':'PASSED_RECORDED_CONTEXT' if release and release.get('passed') else 'UNVALIDATED',
                       'validation_id':(release or {}).get('id'),'n':(release or {}).get('n')},
            'context':{'competition_profile':model['competition_profile'],'model_id':prediction.get('model_id'),
                       'state':health['state'],'trust':health['trust'],'n':health.get('n')},
            'sources':{'source_ids':sorted(prediction['witness']['sources']),
                       'independence_groups':prediction['witness']['groups'],
                       'reliability_basis':'DECLARED_INPUT_NOT_EXTERNAL_CERTIFICATION',
                       'status':'BLOCKED' if codes & {'CRITICAL_EVIDENCE_UNRELIABLE','UNRESOLVED_CONFLICT'} else 'INPUT_GATES_CHECKED'},
            'lineup':{'status':'BLOCKED' if codes & {'MISSING_LINEUP','LINEUP_NOT_CONFIRMED',
                'RECHECK_STALE','RECHECK_FACT_STALE','SPORTS_CHANGED_RECALCULATE'} else 'INPUT_GATES_CHECKED'},
            'model_stability':{'status':'SENSITIVITY_IS_NOT_FORECAST_ACCURACY',
                               'stress_calibration_statuses':candidate.get('stress_calibration_statuses',[])},
            'opponent_history':{'observations':len(traces),
                'missing_history_observations':sum(t['opponent_games']==0 for t in traces),
                'status':'DESCRIPTIVE_NOT_VALIDATED_COMPETENCE'}},
        'true_probability_accuracy':None,'monetary_permission':False,
        'rule':'EV and stress EV do not substitute for calibration, holdout or evidence.'}


def divergence_level(delta, policy):
    # Probability subtraction can round .6-.5 below .10. The allowance is
    # machine roundoff at unit probability scale, not a tuned business margin.
    if delta is None:return 'NOT_ASSESSED'
    magnitude=abs(delta)+4*ulp(1.)
    return ('EXTREME_RECALCULATE' if magnitude>=policy.extreme_divergence else
            'CORROBORATION_REQUIRED' if magnitude>=policy.divergence else 'WITHIN_POLICY_REVIEW_THRESHOLD')


def divergence_review(candidate, policy):
    reference=candidate.get('market_reference') or {};delta=reference.get('divergence')
    status=divergence_level(delta,policy)
    return {'status':status,'difference':delta,'reference_method':reference.get('method'),
            'reference_probability':reference.get('probability'),
            'conditional_on_no_push':reference.get('conditional_on_no_push',False),
            'corroboration':candidate.get('corroboration'),
            'review_threshold':policy.divergence,'extreme_threshold':policy.extreme_divergence,
            'threshold_basis':'EXISTING_RESEARCH_POLICY_NOT_NEW_EMPIRICAL_VALIDATION',
            'monetary_permission':False}


def search_review(decision, prediction, research_key=None):
    candidates=decision['candidates'];sealed=[market_of(m).key for m in prediction['market_pool']]
    quoted={market_of(q['market']).key for q in decision['inputs']['quotes']}
    focus=decision['selected_market'] or decision.get('screened_market') or research_key
    return {'schema':'sealed-search-review-v1','scope':'ONE_LOCAL_SEALED_FIXTURE',
            'match_id':decision['match_id'],'sealed_markets':sealed,
            'sealed_market_count':len(sealed),'evaluated_market_count':len(candidates),
            'priced_market_count':sum(c.get('ev') is not None for c in candidates),
            'quoted_contract_count':len(quoted),'reference_only_contract_count':len(quoted-set(sealed)),
            'eligible_before_global_gates':sum(c['eligible'] for c in candidates),
            'focus_market':focus,'focus_sealed_ordinal':sealed.index(focus)+1 if focus in sealed else None,
            'other_screened_fixtures':None,'global_search_status':'NOT_RECORDED_BY_THIS_DECISION',
            'search_bias_penalty':None,'penalty_status':'NO_VALIDATED_MULTIPLE_TESTING_PENALTY',
            'rule':'The fixed pool is auditable; external searches are unknown, not zero.',
            'monetary_permission':False}


def scoring_ceiling(mass):
    # One existing public projection validates all score keys and mass values.
    # The remaining tails need no repeated settlement/validation of that mass.
    home3=probabilities(market_of({'kind':'TEAM_TOTAL','side':'HOME_OVER','line':2.5}),mass)[0]
    sides={'home':{'p3_plus':home3,'p4_plus':0.},'away':{'p3_plus':0.,'p4_plus':0.}}
    for (home,away),p in mass.items():
        if home>=4:sides['home']['p4_plus']+=p
        if away>=3:sides['away']['p3_plus']+=p
        if away>=4:sides['away']['p4_plus']+=p
    return {'schema':'raw-scoring-ceiling-v1','teams':sides,
            'basis':'ORIGINAL_RAW_SCORE_MASS','calibration':'NOT_A_CALIBRATED_CEILING_FORECAST',
            'automatic_veto':False,'monetary_permission':False}


def under_ceiling(market, mass):
    if market.kind not in ('TOTAL','TEAM_TOTAL') or not market.side.endswith('UNDER'):return None
    threshold=int(market.line)+1
    sides=('home','away') if market.kind=='TOTAL' else (market.side.split('_')[0].lower(),)
    first=sides[0]
    risk=probabilities(market_of({'kind':'TEAM_TOTAL','side':first.upper()+'_OVER',
                                'line':threshold-.5}),mass)[0]
    risks={first:risk};union=risk
    if len(sides)>1:
        risks['away']=0.;union=0.
        for (home,away),p in mass.items():
            if away>=threshold:risks['away']+=p
            if home>=threshold or away>=threshold:union+=p
    return {'loss_goal_threshold':threshold,'one_team_alone_loss_probability':risks,
            'either_relevant_team_alone_loss_probability':union,
            'basis':'ORIGINAL_RAW_SCORE_MASS_NOT_CALIBRATED_MARKET_BASE',
            'automatic_veto':False,'monetary_permission':False}


def closing_quote(closes, match_id, market, bookmaker, observed):
    from .contracts import digest
    matches=[q for q in closes if q['match_id']==match_id and market_of(q['market']).key==market
             and q['bookmaker']==bookmaker and q['rules']=='REGULATION_90'
             and time(q['observed_at'])>=time(observed)]
    return max(matches,key=lambda q:(time(q['observed_at']),time(q['received_at']),digest(q))) if matches else None
