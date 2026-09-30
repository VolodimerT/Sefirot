"""Nine responsibilities in a deterministic directed pipeline; no autonomous agents."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from .contracts import VERSION,MODEL,Policy,digest,time,number,finding,strict
from .evidence import inspect
from .probability import estimate,calibrate,ev_bounds,grade_stress
from .markets import pool,probabilities,settle,market_of,validate_quote,payoff_ev,implied,fair_odds,complete_overround,market_reference
from .risk import size_risk


def code_hash():
    root=Path(__file__).parent
    return digest({p.name:p.read_text(encoding='utf-8') for p in sorted(root.glob('*.py'))})


def prepare(sports,markets,policy,calibrator=None):
    if any(e.get('key')=='market_news' for e in sports.get('evidence',[])):raise ValueError('market evidence enters only after sports probability seal')
    witness=inspect(sports,policy); issues=list(witness['issues']); declared=pool(markets,policy)
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
    mass,variants,model=estimate(sports,policy)
    if min(model['team_games'])<policy.min_team_games:issues.append(finding('probability','INSUFFICIENT_HISTORY'))
    if model['tail_bound']>policy.max_tail:issues.append(finding('probability','SCORE_TAIL_TOO_LARGE'))
    if witness['novelty']:issues.append(finding('competence','UNKNOWN_CONTEXT','BLOCK',detail=','.join(witness['novelty'])))
    if calibrator:
        saved=dict(calibrator);signature=saved.pop('hash',None)
        if digest(saved)!=signature or calibrator['model_hash']!=code_hash() or calibrator['policy_hash']!=policy.fingerprint:
            raise ValueError('calibrator version/hash mismatch')
        if time(calibrator['fit_at'])>time(sports['as_of']) or sports['match']['id'] in calibrator['fit_ids']:raise ValueError('calibration leakage')
    candidates=[]
    for m in declared:
        raw=probabilities(m,mass); cal=calibrate(m.kind,raw,calibrator,policy,model['competition_profile'])
        stressed=[probabilities(m,v) for v in variants]
        # Union empirical reliability uncertainty with sporting sensitivity. Never shrink
        # uncertainty because a price looks attractive.
        low=[min([cal['low'][i]]+[p[i] for p in stressed]) for i in range(3)]
        high=[max([cal['high'][i]]+[p[i] for p in stressed]) for i in range(3)]
        losses=[s for s in model['score_scenarios'] if settle(m,s['home'],s['away'])=='LOSS']
        candidates.append({'market':{'kind':m.kind,'side':m.side,**({'line':m.line} if m.line is not None else {})},'key':m.key,
                           'raw':list(raw),'base':cal['base'],'low':low,'high':high,'calibration':cal['status'],'calibration_n':cal['n'],
                           'stress_probabilities':[list(p) for p in stressed],'counterexamples':losses,
                           'additional_assumptions':int(m.kind in ('HANDICAP','TEAM_TOTAL'))})
    result={'version':VERSION,'model_version':MODEL,'code_hash':code_hash(),'policy':asdict(policy),'policy_hash':policy.fingerprint,
            'sports':sports,'market_pool':markets,'witness':witness,'scenario':{**witness['scenario'],'score_scenarios':model['score_scenarios']},
            'model':model,'calibrator':calibrator,'candidates':candidates,'issues':issues,'as_of':sports['as_of'],
            'synthetic':bool(sports.get('synthetic',False)),'mode':'UNKNOWN' if witness['novelty'] or min(model['team_games'])<policy.min_team_games or any(i['code'] in ('COMPETITION_PROFILE_UNKNOWN','MODEL_MATCHUP_CONFLICT','MATCHUP_SUPPORT_INSUFFICIENT') for i in issues) else 'NORMAL'}
    result['id']=digest(result)
    return result


def recheck(prediction,recheck_data,at,policy):
    strict(recheck_data,('checked_at','evidence'))
    checked=time(recheck_data['checked_at']);decision=time(at);issues=[]
    if checked>decision or (decision-checked).total_seconds()>policy.recheck_max_age_minutes*60 or checked<time(prediction['as_of']):
        issues.append(finding('witness','RECHECK_STALE'))
    merged={**prediction['sports'],'as_of':recheck_data['checked_at'],'evidence':recheck_data['evidence']}
    check=inspect(merged,policy);issues.extend(check['issues'])
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
    if time(at)<time(prediction['as_of']) or time(at)>=time(match['kickoff']):raise ValueError('decision must be prematch after seal')
    checked,check=recheck(prediction,recheck_data,at,policy);issues.extend(checked)
    if not context['journal_ok']:issues.append(finding('chronicler','JOURNAL_INTEGRITY'))
    evaluations=[]
    quote_map={}
    for q in quotes:
        m=validate_quote(q,match['kickoff'],at,prediction['sealed_at'])
        if q['phase']=='CLOSE': raise ValueError('closing odds cannot inform admission')
        quote_map.setdefault(m.key,[]).append(q)
    for c in prediction['candidates']:
        local=[];available=[q for q in quote_map.get(c['key'],[]) if q['phase'] in ('FINAL','ENTRY')]
        if not available:
            evaluations.append({**c,'eligible':False,'issues':[finding('market','MISSING_CURRENT_PRICE')],'ev':None});continue
        q=max(available,key=lambda x:(time(x['observed_at']),time(x['received_at']),x['bookmaker']))
        odd=q['odds'];win,push,loss=c['base'];ev=payoff_ev(win,push,odd);low_ev,high_ev=ev_bounds(c['low'],c['high'],odd)
        if (time(at)-time(q['observed_at'])).total_seconds()>policy.quote_max_age_seconds:local.append(finding('market','PRICE_STALE'))
        if c['calibration']!='CALIBRATED_BIN':local.append(finding('probability','CALIBRATION_INSUFFICIENT'))
        width=c['high'][0]-c['low'][0]
        if width>policy.max_probability_width:local.append(finding('probability','UNCERTAINTY_TOO_WIDE'))
        if ev<policy.min_ev or low_ev<policy.min_low_ev:local.append(finding('arbiter','ROBUST_EV_INSUFFICIENT'))
        health=context['health'].get(c['key'],{'state':'UNKNOWN','trust':'INSUFFICIENT'})
        if health['state'] in ('UNKNOWN','WEAK','FROZEN'):local.append(finding('competence','CONTEXT_'+health['state']))
        roles=context.get('sephirot_ratings',{}).get(c['key'],{})
        for role in ('witness','probability','opponent'):
            trust=roles.get(role,{}).get('trust','INSUFFICIENT')
            if trust=='INSUFFICIENT':local.append(finding('competence','SEPHIRA_HISTORY_INSUFFICIENT','BLOCK',detail=role))
            elif trust=='LOW':local.append(finding('competence','SEPHIRA_LOW_TRUST','WARN',detail=role))
        release=context['releases'].get(c['key'])
        if not release or not release.get('passed'):local.append(finding('competence','HOLDOUT_UNVALIDATED'))
        # Wider disagreement needs independent corroboration of each critical premise.
        edge=win-(1-push)/odd
        reference=market_reference(quotes,q,win,push)
        divergence=reference['divergence']
        if divergence is None:local.append(finding('market','MARKET_REFERENCE_MISSING'))
        elif abs(divergence)>=policy.extreme_divergence:
            local.append(finding('opponent','MODEL_MARKET_DIVERGENCE','BLOCK',detail='Extreme discrepancy requires a new sports-only seal; reference='+reference['method']))
        if divergence is not None and abs(divergence)>policy.divergence:
            per_key={key:set() for key in ('lineup','injuries','tactics')}
            for e in recheck_data['evidence']:
                if e['key'] in per_key and e['kind']=='FACT':
                    src=check['sources'][e['source_id']]
                    if src['enabled'] and src['reliability']>=policy.min_source_reliability:per_key[e['key']].add(src['independence_group'])
            if any(len(groups)<2 for groups in per_key.values()):local.append(finding('opponent','DIVERGENCE_NEEDS_CORROBORATION'))
        opening=[x for x in quote_map[c['key']] if x['phase']=='OPEN' and x['bookmaker']==q['bookmaker']]
        movement=None
        if opening:
            o=min(opening,key=lambda x:time(x['observed_at']));movement=odd/o['odds']-1
            if abs(movement)>=policy.line_move:
                cited=q.get('movement_evidence',[])
                facts={e['id']:e for e in recheck_data['evidence']}
                if not cited or any(ref not in facts or facts[ref]['key']!='market_news' or facts[ref]['kind']!='FACT' for ref in cited):
                    local.append(finding('competence','UNEXPLAINED_LINE_MOVEMENT'))
        stress_evs=[payoff_ev(p[0],p[1],odd) for p in c['stress_probabilities']]
        if min(stress_evs)<0:local.append(finding('opponent','DEATH_TEST_PRICE_FRAGILITY'))
        # A losing score alone is not a veto: plausible bets always have loss branches.
        public_trap={'status':'CHECKED','rule':'no popularity or market movement may replace sports evidence',
                     'unexplained_movement':any(x['code']=='UNEXPLAINED_LINE_MOVEMENT' for x in local)}
        evaluations.append({**c,'odds':odd,'quote':q,'implied_probability':implied(odd),'market_reference':reference,
                            'fair_odds':fair_odds(win,push) if win>0 else None,'edge':edge,'ev':ev,'ev_low':low_ev,'ev_high':high_ev,
                            'uncertainty':width,'stress_ev_min':min(stress_evs),'stress_ev_max':max(stress_evs),'stress_grade':grade_stress(ev,min(stress_evs),policy.min_ev),'line_movement':movement,'public_trap':public_trap,
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
    # Choose fewer assumptions and robust cross-scenario value within the sealed pool.
    viable.sort(key=lambda c:(c['additional_assumptions'],-c['stress_ev_min'],-c['ev_low'],c['key']))
    selected=viable[0] if viable else None
    if selected is None:issues.append(finding('arbiter','NO_ADMISSIBLE_MAIN_MARKET'))
    blocked=any(x['severity']=='BLOCK' for x in issues)
    risk={'stake':0.,'reasons':['ADMISSION_BLOCKED'],'groups':[]}
    conditional=any(x['severity']=='WARN' for x in issues+(selected['issues'] if selected else []))
    if selected and not blocked:
        quality=.5 if conditional else 1.
        risk=size_risk(win=selected['low'][0],push=selected['low'][1],odds=selected['odds'],bankroll=portfolio['bankroll'],peak=portfolio['peak'],
                       quality=quality,exposures=context['exposures'],match=match,model=prediction['model_version'],scenario=prediction['scenario']['type'],
                       factors=prediction['scenario']['novelty'],at=at,policy=policy)
        if risk['stake']==0:issues.append(finding('arbiter','RISK_LIMIT'));blocked=True
    final='BET' if selected and not blocked and risk['stake']>0 else 'PASS'
    verdict='playable with conditions' if final=='BET' and conditional else 'playable' if final=='BET' else 'unplayable' if any(i['code'] in ('UNRESOLVED_CONFLICT','JOURNAL_INTEGRITY','LIVE_FORBIDDEN') for i in issues) else 'skip'
    grade='B' if final=='BET' and conditional else 'A' if final=='BET' and selected['competence']['trust']=='HIGH' else 'B' if final=='BET' else 'RED' if verdict=='unplayable' else 'C' if selected else 'D'
    unknown=bool(thesis_reviews) or any(i['code'] in ('MODEL_MARKET_DIVERGENCE','DIVERGENCE_NEEDS_CORROBORATION','UNEXPLAINED_LINE_MOVEMENT') for c in evaluations for i in c['issues'])
    return {'version':VERSION,'prediction_id':prediction['id'],'match_id':match['id'],'at':at,'mode':'UNKNOWN' if unknown else prediction['mode'],
            'decision':final,'verdict':verdict,'class':grade,'confidence':'INSUFFICIENT' if blocked else 'MEDIUM' if conditional or selected['competence']['trust']!='HIGH' else 'HIGH',
            'selected_market':selected['key'] if selected else None,'candidates':evaluations,'issues':issues,'thesis_reviews':thesis_reviews,
            'conditions':[i for i in issues+(selected['issues'] if selected else []) if i['severity']=='WARN'],'risk':risk,'execution_enabled':False,
            'selection_reason':'fewest additional assumptions, then robust stress EV within sealed pool',
            'overrounds':complete_overround(quotes),'inputs':{'quotes':quotes,'recheck':recheck_data,'context':context,'portfolio':portfolio},
            'limiting_factors':[i['code'] for i in issues if i['severity']=='BLOCK']}
