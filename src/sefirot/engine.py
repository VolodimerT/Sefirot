"""Nine responsibilities in a deterministic directed pipeline; no autonomous agents."""
from __future__ import annotations
from dataclasses import asdict
from .contracts import VERSION,MODEL,Policy,digest,time,number,finding,strict
from .evidence import inspect
from .probability import estimate,calibrate,ev_bounds,grade_stress,worst_case_probabilities
from .decision_card import build_card,candidate_rank
from .markets import pool,probabilities,settle,market_of,validate_quote,payoff_ev,implied,fair_odds,complete_overround,market_reference
from .risk import size_risk
from .identity import code_hash,model_code_hash
from .probability_review import scoring_ceiling,under_ceiling,divergence_level


def selection_constraints(sports,witness,policy):
    """Explicit sports-only denials; no threshold inferred from prices or scores."""
    ids=[];issues=[];premises=set();eligible=set(witness['eligible_fact_ids'])
    facts={e['id']:e for e in sports['evidence']}
    for e in sports['evidence']:
        if e['key']!='matchup_signal' or 'selection_constraint' not in e['value']:continue
        constraint=e['value']['selection_constraint']
        strict(constraint,('avoid_result',))
        if constraint['avoid_result'] is not True:raise ValueError('avoid_result must be true; removal requires a new sports seal')
        ids.append(e['id'])
        premises.update(digest({'key':facts[ref]['key'],'value':facts[ref]['value']}) for ref in e['supports'])
        source=witness['sources'][e['source_id']]
        if (not source['enabled'] or source['reliability']<policy.min_source_reliability
            or (time(sports['as_of'])-time(e['observed_at'])).total_seconds()>policy.fact_max_age_minutes*60
            or not e['supports'] or not set(e['supports'])<=eligible):
            issues.append(finding('scenario','SCENARIO_CONSTRAINT_UNVERIFIED','BLOCK',[e['id']],
                                  'Explicit denial remains active; refresh reliable, resolved FACT support'))
    return {'avoid_result':bool(ids),'evidence_ids':sorted(ids),'premise_hash':digest(sorted(premises))},issues


def market_constraint_issues(market,constraints):
    if constraints['avoid_result'] and market.kind in ('1X2','DOUBLE_CHANCE','DNB','HANDICAP'):
        return [finding('scenario','SCENARIO_MARKET_CONFLICT','BLOCK',constraints['evidence_ids'],
                        'Result-dependent contract conflicts with the sealed avoid_result directive')]
    return []


def prepare(sports,markets,policy,calibrator=None,goal_model=None):
    if any(e.get('key')=='market_news' for e in sports.get('evidence',[])):raise ValueError('market evidence enters only after sports probability seal')
    witness=inspect(sports,policy); issues=list(witness['issues']); declared=pool(markets,policy)
    constraints,constraint_issues=selection_constraints(sports,witness,policy);issues.extend(constraint_issues)
    links=sports.get('thesis_links',[])
    if not isinstance(links,list) or len(links)>policy.max_candidates:raise ValueError('bounded thesis links required')
    known={m.key for m in declared};facts={e['id'] for e in witness['resolved'].values()};seen=set()
    for link in links:
        strict(link,('id','markets','premise_ids'))
        if not isinstance(link['id'],str) or not link['id'] or link['id'] in seen:raise ValueError('unique thesis id required')
        seen.add(link['id'])
        if not isinstance(link['markets'],list) or not 2<=len(link['markets'])<=policy.max_candidates or len(set(link['markets']))!=len(link['markets']) or not set(link['markets'])<=known:
            raise ValueError('thesis markets must belong to the sealed pool')
        if not isinstance(link['premise_ids'],list) or not link['premise_ids'] or not set(link['premise_ids'])<=facts:raise ValueError('thesis requires resolved sports fact premises')
    if policy.goal_model=='SOS_THRESHOLD_V2':
        from .goal_model import validate_artifact
        validate_artifact(goal_model,sports,policy,model_code_hash())
    mass,variants,model=estimate(sports,policy,goal_model)
    if policy.goal_model=='SOS_THRESHOLD_V2':
        if not goal_model or goal_model['profile_parameters']['n']<policy.min_profile_games:
            issues.append(finding('probability','PROFILE_MODEL_UNFITTED'))
        if any(t['status']!='FITTED_COUNT_BIN' for t in model['threshold_model'].values()):
            issues.append(finding('probability','THRESHOLD_MODEL_UNFITTED'))
        if any(t['status']!='FITTED_COUNT_BIN' for bins in model['stress_threshold_models'] for t in bins.values()):
            issues.append(finding('probability','THRESHOLD_STRESS_BIN_UNFITTED'))
        if goal_model and goal_model['synthetic']:
            issues.append(finding('competence','GOAL_ARTIFACT_SYNTHETIC_RESEARCH_ONLY'))
    if min(model['team_games'])<policy.min_team_games:issues.append(finding('probability','INSUFFICIENT_HISTORY'))
    if model['tail_bound']>policy.max_tail:issues.append(finding('probability','SCORE_TAIL_TOO_LARGE'))
    if witness['novelty']:issues.append(finding('competence','UNKNOWN_CONTEXT','BLOCK',detail=','.join(witness['novelty'])))
    if calibrator:
        saved=dict(calibrator);signature=saved.pop('hash',None)
        if digest(saved)!=signature or calibrator['model_hash']!=model_code_hash() or calibrator['policy_hash']!=policy.fingerprint:
            raise ValueError('calibrator version/hash mismatch')
        if time(calibrator['fit_at'])>time(sports['as_of']) or sports['match']['id'] in calibrator['fit_ids']:raise ValueError('calibration leakage')
        if calibrator.get('goal_model_hash')!=(goal_model['hash'] if goal_model else None):raise ValueError('calibrator belongs to another fitted goal model')
    candidates=[]
    for m in declared:
        raw=probabilities(m,mass); cal=calibrate(m,raw,calibrator,policy,model['competition_profile'])
        stressed_raw=[probabilities(m,v) for v in variants]
        stress_calibration=[calibrate(m,p,calibrator,policy,model['competition_profile']) for p in stressed_raw]
        stressed=[cal['base'] for cal in stress_calibration] if policy.stress_mode=='GRADED' else stressed_raw
        # Union empirical reliability uncertainty with sporting sensitivity. Never shrink
        # uncertainty because a price looks attractive.
        low=[min([cal['low'][i]]+[p[i] for p in stressed]) for i in range(3)]
        high=[max([cal['high'][i]]+[p[i] for p in stressed]) for i in range(3)]
        losses=[s for s in model['score_scenarios'] if settle(m,s['home'],s['away'])=='LOSS']
        candidates.append({'market':{'kind':m.kind,'side':m.side,**({'line':m.line} if m.line is not None else {})},'key':m.key,
                           'raw':list(raw),'base':cal['base'],'low':low,'high':high,
                           'calibration_low':cal['low'],'calibration_high':cal['high'],
                           'calibration':cal['status'],'calibration_n':cal['n'],
                           'stress_calibration_statuses':[cal['status'] for cal in stress_calibration],
                           'stress_probabilities':[list(p) for p in stressed],'counterexamples':losses,
                           'under_ceiling':under_ceiling(m,mass),
                           'additional_assumptions':int(m.kind in ('HANDICAP','TEAM_TOTAL')),
                           'selection_issues':market_constraint_issues(m,constraints)})
    result={'version':VERSION,'model_version':model['model_version'],'code_hash':code_hash(),'model_hash':model_code_hash(),'policy':asdict(policy),'policy_hash':policy.fingerprint,
            'sports':sports,'market_pool':markets,'witness':witness,'scenario':{**witness['scenario'],'score_scenarios':model['score_scenarios'],'selection_constraints':constraints},
            'model':model,'scoring_ceiling':scoring_ceiling(mass),
            'calibrator':calibrator,'goal_model':goal_model,'candidates':candidates,'issues':issues,'as_of':sports['as_of'],
            'synthetic':bool(sports.get('synthetic',False)) or bool(goal_model and goal_model['synthetic']),'mode':'UNKNOWN' if witness['novelty'] or min(model['team_games'])<policy.min_team_games or any(i['code'] in ('COMPETITION_PROFILE_UNKNOWN','MODEL_MATCHUP_CONFLICT','MATCHUP_SUPPORT_INSUFFICIENT','SCENARIO_CONSTRAINT_UNVERIFIED','PROFILE_MODEL_UNFITTED','THRESHOLD_MODEL_UNFITTED','THRESHOLD_STRESS_BIN_UNFITTED') for i in issues) else 'NORMAL'}
    result['id']=digest(result)
    return result


def recheck(prediction,recheck_data,at,policy):
    strict(recheck_data,('checked_at','evidence'))
    checked=time(recheck_data['checked_at']);decision=time(at);issues=[]
    if checked>decision or (decision-checked).total_seconds()>policy.recheck_max_age_minutes*60 or checked<time(prediction['as_of']):
        issues.append(finding('witness','RECHECK_STALE'))
    merged={**prediction['sports'],'as_of':recheck_data['checked_at'],'evidence':recheck_data['evidence']}
    check=inspect(merged,policy);issues.extend(check['issues'])
    constraints,constraint_issues=selection_constraints(merged,check,policy);issues.extend(constraint_issues)
    frozen=prediction['scenario']['selection_constraints']
    if any(constraints[key]!=frozen[key] for key in ('avoid_result','premise_hash')):
        issues.append(finding('opponent','SPORTS_CHANGED_RECALCULATE','BLOCK',constraints['evidence_ids'],
                              'Explicit selection constraint changed; create a new sports-only seal'))
    if check['novelty']:issues.append(finding('competence','UNKNOWN_CONTEXT','BLOCK',detail=','.join(check['novelty'])))
    old=prediction['witness']['resolved'];new=check['resolved']
    for key in ('lineup','injuries','coach','rotation','tactics','format','home_team','away_team'):
        if key in old and key in new and digest(old[key]['value'])!=digest(new[key]['value']):
            issues.append(finding('opponent','SPORTS_CHANGED_RECALCULATE','BLOCK',[old[key]['id'],new[key]['id']],key))
    for key in ('lineup','injuries','tactics'):
        if key in new and (decision-time(new[key]['observed_at'])).total_seconds()>policy.recheck_max_age_minutes*60:
            issues.append(finding('witness','RECHECK_FACT_STALE','BLOCK',[new[key]['id']],key))
    return issues,check


def decide(prediction,quotes,recheck_data,at,context,portfolio,policy):
    if prediction['policy_hash']!=policy.fingerprint or prediction['code_hash']!=code_hash():raise ValueError('replay requires same policy/code version')
    match=prediction['sports']['match'];issues=list(prediction['issues'])
    constraints,constraint_issues=selection_constraints(prediction['sports'],inspect(prediction['sports'],policy),policy)
    if constraints!=prediction['scenario']['selection_constraints']:raise ValueError('sealed selection constraints do not reproduce')
    issues.extend(constraint_issues)
    if time(at)<time(prediction['as_of']) or time(at)>=time(match['kickoff']):raise ValueError('decision must be prematch after seal')
    checked,check=recheck(prediction,recheck_data,at,policy);issues.extend(checked)
    # Corroboration and movement explanations use the same active, reliable facts
    # as Witness, with the stricter final-recheck freshness window for each source.
    eligible_ids=set(check['eligible_fact_ids'])
    current_facts={e['id']:e for e in recheck_data['evidence'] if e['id'] in eligible_ids
                   and 0<=(time(at)-time(e['observed_at'])).total_seconds()<=policy.recheck_max_age_minutes*60}
    if not context['journal_ok']:issues.append(finding('chronicler','JOURNAL_INTEGRITY'))
    evaluations=[]
    quote_map={}
    for q in quotes:
        m=validate_quote(q,match['kickoff'],at,prediction['sealed_at'])
        if q['phase']=='CLOSE': raise ValueError('closing odds cannot inform admission')
        quote_map.setdefault(m.key,[]).append(q)
    for c in prediction['candidates']:
        local=market_constraint_issues(market_of(c['market']),constraints)
        available=[q for q in quote_map.get(c['key'],[]) if q['phase'] in ('FINAL','ENTRY')]
        admission_low=c['calibration_low'] if policy.stress_mode=='GRADED' else c['low']
        admission_high=c['calibration_high'] if policy.stress_mode=='GRADED' else c['high']
        if c['calibration']!='CALIBRATED_BIN':local.append(finding('probability','CALIBRATION_INSUFFICIENT'))
        if policy.stress_mode=='GRADED' and any(s!='CALIBRATED_BIN' for s in c.get('stress_calibration_statuses',[])):
            local.append(finding('probability','STRESS_CALIBRATION_INSUFFICIENT'))
        width=admission_high[0]-admission_low[0]
        if width>policy.max_probability_width:local.append(finding('probability','UNCERTAINTY_TOO_WIDE'))
        health=context['health'].get(c['key'],{'state':'UNKNOWN','trust':'INSUFFICIENT'})
        if health['state'] in ('UNKNOWN','WEAK','FROZEN'):local.append(finding('competence','CONTEXT_'+health['state']))
        roles=context.get('sephirot_ratings',{}).get(c['key'],{})
        for role in ('witness','probability','opponent'):
            trust=roles.get(role,{}).get('trust','INSUFFICIENT')
            if trust=='INSUFFICIENT':local.append(finding('competence','SEPHIRA_HISTORY_INSUFFICIENT','BLOCK',detail=role))
            elif trust=='LOW':local.append(finding('competence','SEPHIRA_LOW_TRUST','WARN',detail=role))
        release=context['releases'].get(c['key'])
        if not release or not release.get('passed'):local.append(finding('competence','HOLDOUT_UNVALIDATED'))
        if not available:
            local.append(finding('market','MISSING_CURRENT_PRICE'))
            evaluations.append({**c,'eligible':False,'issues':local,'competence':health,'ev':None,
                                'admission_low':admission_low,'admission_high':admission_high,
                                'probability_bound_basis':'CALIBRATION_ONLY' if policy.stress_mode=='GRADED' else 'CALIBRATION_AND_SENSITIVITY'});continue
        q=max(available,key=lambda x:(time(x['observed_at']),time(x['received_at']),x['bookmaker']))
        odd=q['odds'];win,push,loss=c['base'];ev=payoff_ev(win,push,odd);low_ev,high_ev=ev_bounds(admission_low,admission_high,odd)
        if (time(at)-time(q['observed_at'])).total_seconds()>policy.quote_max_age_seconds:local.append(finding('market','PRICE_STALE'))
        if ev<policy.min_ev or low_ev<policy.min_low_ev:local.append(finding('arbiter','ROBUST_EV_INSUFFICIENT'))
        # Wider disagreement needs independent corroboration of each critical premise.
        edge=win-(1-push)/odd
        reference=market_reference(quotes,q,win,push,reference_bookmakers=policy.reference_bookmakers,
                                   at=at,max_age_seconds=policy.quote_max_age_seconds)
        divergence=reference['divergence']
        divergence_status=divergence_level(divergence,policy)
        if divergence is None:local.append(finding('market','MARKET_REFERENCE_MISSING'))
        elif divergence_status=='EXTREME_RECALCULATE':
            local.append(finding('opponent','MODEL_MARKET_DIVERGENCE','BLOCK',detail='Extreme discrepancy requires a new sports-only seal; reference='+reference['method']))
        corroboration={'status':'NOT_REQUIRED','independence_groups':None}
        if divergence_status in ('CORROBORATION_REQUIRED','EXTREME_RECALCULATE'):
            per_key={key:set() for key in ('lineup','injuries','tactics')}
            for e in current_facts.values():
                if e['key'] in per_key and e['kind']=='FACT':
                    src=check['sources'][e['source_id']]
                    if src['enabled'] and src['reliability']>=policy.min_source_reliability:per_key[e['key']].add(src['independence_group'])
            corroborated=all(len(groups)>=2 for groups in per_key.values())
            corroboration={'status':'CURRENT_FACTS_CORROBORATED' if corroborated else 'INSUFFICIENT',
                           'independence_groups':{key:sorted(groups) for key,groups in per_key.items()}}
            if not corroborated:local.append(finding('opponent','DIVERGENCE_NEEDS_CORROBORATION'))
        opening=[x for x in quote_map[c['key']] if x['phase']=='OPEN' and x['bookmaker']==q['bookmaker']]
        movement=None
        if opening:
            o=min(opening,key=lambda x:time(x['observed_at']));movement=odd/o['odds']-1
            if abs(movement)>=policy.line_move:
                cited=q.get('movement_evidence',[])
                facts=current_facts
                if not cited or any(ref not in facts or facts[ref]['key']!='market_news' or facts[ref]['kind']!='FACT' for ref in cited):
                    local.append(finding('competence','UNEXPLAINED_LINE_MOVEMENT'))
        stress_evs=[payoff_ev(p[0],p[1],odd) for p in c['stress_probabilities']]
        stress_grade=grade_stress(ev,min(stress_evs),policy.min_ev)
        multiplier=1.
        if policy.stress_mode=='STRICT':
            if min(stress_evs)<0:local.append(finding('opponent','DEATH_TEST_PRICE_FRAGILITY'))
        else:
            label=stress_grade['class']
            class_release=(release or {}).get('stress_classes',{}).get(label,{})
            if not class_release.get('passed'):
                local.append(finding('competence','GRADED_DEATH_TEST_UNVALIDATED','BLOCK',detail=label))
            if min(stress_evs)<policy.aggressive_stress_floor:
                local.append(finding('opponent','DEATH_TEST_SEVERE_FRAGILITY'))
            if label in ('FRAGILE_VALUE','AGGRESSIVE_VALUE'):
                multiplier=policy.fragile_stake_multiplier if label=='FRAGILE_VALUE' else policy.aggressive_stake_multiplier
                local.append(finding('opponent','GRADED_STRESS_STAKE_CAP','WARN',detail=label))
            stress_grade={**stress_grade,'status':'CLASS_HOLDOUT_PASSED' if class_release.get('passed') else 'RESEARCH_UNVALIDATED',
                          'monetary_permission':False,'stake_multiplier_cap':multiplier}
        # A losing score alone is not a veto: plausible bets always have loss branches.
        public_trap={'status':'CHECKED','rule':'no popularity or market movement may replace sports evidence',
                     'unexplained_movement':any(x['code']=='UNEXPLAINED_LINE_MOVEMENT' for x in local)}
        evaluations.append({**c,'odds':odd,'quote':q,'implied_probability':implied(odd),'market_reference':reference,
                            'corroboration':corroboration,
                            'fair_odds':fair_odds(win,push) if win>0 else None,'edge':edge,'ev':ev,'ev_low':low_ev,'ev_high':high_ev,
                            'uncertainty':width,'admission_low':admission_low,'admission_high':admission_high,
                            'probability_bound_basis':'CALIBRATION_ONLY' if policy.stress_mode=='GRADED' else 'CALIBRATION_AND_SENSITIVITY',
                            'stake_multiplier':multiplier,'stress_ev_min':min(stress_evs),'stress_ev_max':max(stress_evs),'stress_grade':stress_grade,'line_movement':movement,'public_trap':public_trap,
                            'competence':health,'issues':local,'eligible':not any(x['severity']=='BLOCK' for x in local)})
    thesis_reviews=[]
    if any(i['code']=='MODEL_MARKET_DIVERGENCE' for c in evaluations for i in c['issues']):
        issues.append(finding('probability','PROBABILITY_RECALCULATION_REQUIRED','BLOCK',detail='Extreme divergence affects the shared sports distribution; seal new independent data'))
    for link in prediction['sports'].get('thesis_links',[]):
        members=[c for c in evaluations if c['key'] in link['markets']]
        weakened=[c['key'] for c in members if c.get('line_movement') is not None and c['line_movement']>=policy.line_move]
        if weakened:
            thesis_reviews.append({'thesis_id':link['id'],'weakened_markets':weakened,'action':'RECALCULATE','premise_ids':link['premise_ids']})
            for c in members:
                c['issues'].append(finding('opponent','THESIS_REPLACEMENT_GUARD','BLOCK',link['premise_ids'],'Adverse price signal requires sports premise review; not proof the thesis is false'))
                c['eligible']=False
    if not context['policy_approved']:issues.append(finding('arbiter','POLICY_NOT_APPROVED'))
    if prediction['synthetic']:issues.append(finding('arbiter','SYNTHETIC_DATA_RESEARCH_ONLY'))
    if not context['captured_prematch']:issues.append(finding('chronicler','RETROSPECTIVE_CAPTURE'))
    viable=[c for c in evaluations if c['eligible']]
    # Sporting gates precede ranking. Do not put a coarse market-family penalty
    # ahead of measurable conservative value within the already sealed pool.
    viable.sort(key=candidate_rank)
    selected=viable[0] if viable else None
    if selected is None:issues.append(finding('arbiter','NO_ADMISSIBLE_MAIN_MARKET'))
    blocked=any(x['severity']=='BLOCK' for x in issues)
    risk={'stake':0.,'reasons':['ADMISSION_BLOCKED'],'groups':[]}
    conditional=any(x['severity']=='WARN' for x in issues+(selected['issues'] if selected else []))
    if selected and not blocked:
        quality=min(.5 if conditional else 1.,selected['stake_multiplier'])
        adverse=worst_case_probabilities(selected['admission_low'],selected['admission_high'],selected['odds'])
        risk=size_risk(win=adverse[0],push=adverse[1],odds=selected['odds'],bankroll=portfolio['bankroll'],peak=portfolio['peak'],
                       quality=quality,exposures=context['exposures'],match=match,model=prediction['model_version'],scenario=prediction['scenario']['type'],
                       factors=prediction['scenario']['novelty'],at=at,policy=policy)
        risk['probabilities_used']=adverse
        risk.update(stress_class=selected['stress_grade']['class'],stress_stake_multiplier=selected['stake_multiplier'],probability_bound_basis=selected['probability_bound_basis'])
        if risk['stake']==0:issues.append(finding('arbiter','RISK_LIMIT'));blocked=True
    final='BET' if selected and not blocked and risk['stake']>0 else 'PASS'
    verdict='playable with conditions' if final=='BET' and conditional else 'playable' if final=='BET' else 'unplayable' if any(i['code'] in ('UNRESOLVED_CONFLICT','JOURNAL_INTEGRITY','LIVE_FORBIDDEN') for i in issues) else 'skip'
    grade='B' if final=='BET' and conditional else 'A' if final=='BET' and selected['competence']['trust']=='HIGH' else 'B' if final=='BET' else 'RED' if verdict=='unplayable' else 'C' if selected else 'D'
    unknown=bool(thesis_reviews) or any(i['code'] in ('UNKNOWN_CONTEXT','COMPETITION_PROFILE_UNKNOWN','MODEL_MATCHUP_CONFLICT','MATCHUP_SUPPORT_INSUFFICIENT','SCENARIO_CONSTRAINT_UNVERIFIED','SPORTS_CHANGED_RECALCULATE') for i in issues) or any(i['code'] in ('MODEL_MARKET_DIVERGENCE','DIVERGENCE_NEEDS_CORROBORATION','UNEXPLAINED_LINE_MOVEMENT') for c in evaluations for i in c['issues'])
    out={'version':VERSION,'prediction_id':prediction['id'],'match_id':match['id'],'at':at,'mode':'UNKNOWN' if unknown else prediction['mode'],
            'decision':final,'verdict':verdict,'class':grade,'confidence':'INSUFFICIENT' if blocked else 'MEDIUM' if conditional or selected['competence']['trust']!='HIGH' else 'HIGH',
            'selected_market':selected['key'] if final=='BET' else None,
            'screened_market':selected['key'] if selected else None,'candidates':evaluations,'issues':issues,'thesis_reviews':thesis_reviews,
            'conditions':[i for i in issues+(selected['issues'] if selected else []) if i['severity']=='WARN'],'risk':risk,'execution_enabled':False,
            'selection_reason':'all sporting gates, then Low EV, stress EV, Base EV, loss probability, additional assumptions; sealed pool only',
            'overrounds':complete_overround(quotes),'inputs':{'quotes':quotes,'recheck':recheck_data,'context':context,'portfolio':portfolio},
            'limiting_factors':sorted({i['code'] for i in issues+(selected['issues'] if selected else [i for c in evaluations for i in c['issues']]) if i['severity']=='BLOCK'})}
    out['decision_card']=build_card(out,prediction,policy)
    return out
