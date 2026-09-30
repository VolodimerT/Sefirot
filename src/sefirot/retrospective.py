"""Reported audit cases exercise contracts; they never become holdout evidence."""
from datetime import date
from .contracts import strict,text,number,integer,digest,PROFILES
from .markets import market_of,settle
from .probability import grade_stress


def audit_cases(dataset,policy):
    strict(dataset,('version','status','holdout_eligible','sources','cases'))
    if dataset['status']!='RETROSPECTIVE_REPORTED_UNVERIFIED' or dataset['holdout_eligible'] is not False:
        raise ValueError('audit narratives are retrospective and cannot certify holdout')
    if not isinstance(dataset['cases'],list) or not dataset['cases']:raise ValueError('nonempty audit cases required')
    if not isinstance(dataset['sources'],dict):raise ValueError('audit source manifest required')
    rows=[];seen=set()
    for case in dataset['cases']:
        strict(case,('id','date','match','source','score','reported_decision'),
               ('market','unsupported_market','odds','reported_base_ev','reported_stress_min','reported_flags','competition_profile','reported_other_result'))
        text(case['id'],'case id');text(case['match'],'match');date.fromisoformat(case['date'])
        if case['id'] in seen:raise ValueError('duplicate audit case')
        seen.add(case['id'])
        if case['source'] not in dataset['sources']:raise ValueError('audit source missing')
        if case.get('competition_profile','UNKNOWN') not in PROFILES:raise ValueError('invalid audit profile')
        if case['score'] is not None:
            if not isinstance(case['score'],list) or len(case['score'])!=2:raise ValueError('audit score must have two goals')
            for goal in case['score']:integer(goal,'score',0,50)
        if ('market' in case)==('unsupported_market' in case):raise ValueError('one supported or unsupported market description required')
        if 'market' in case:
            if case['score'] is None:raise ValueError('supported market requires a reported score')
            market=market_of(case['market']);outcome=settle(market,*case['score'])
        else:
            text(case['unsupported_market'],'unsupported market');outcome='UNSUPPORTED'
        odds=number(case['odds'],'odds',1.00000001) if case.get('odds') is not None else None
        ev=case.get('reported_base_ev');stress=case.get('reported_stress_min')
        if ev is not None:number(ev,'reported base EV')
        if stress is not None:number(stress,'reported stress EV')
        grade=grade_stress(ev,stress,policy.min_ev) if ev is not None and stress is not None else None
        pnl=None if odds is None or outcome=='UNSUPPORTED' else odds-1 if outcome=='WIN' else 0. if outcome=='PUSH' else -1.
        rows.append({'id':case['id'],'match':case['match'],'market':case.get('market',case.get('unsupported_market')),
                     'source':case['source'],'outcome':outcome,'reported_decision':case['reported_decision'],
                     'reported_base_ev':ev,'reported_stress_min':stress,'stress_grade':grade,
                     'reported_flags':case.get('reported_flags',[]),'competition_profile':case.get('competition_profile','UNKNOWN'),
                     'decision_quality':'UNDETERMINED','cause':'UNKNOWN','closing_odds':None,'clv':None,
                     'sealed_prediction_available':False,'holdout_eligible':False,'monetary_permission':False,
                     'hypothetical_unit_pnl':pnl})
    return {'version':dataset['version'],'status':dataset['status'],'dataset_hash':digest(dataset),
            'cases':len(rows),'source_documents':len(dataset['sources']),'holdout_eligible':False,
            'monetary_permission':False,'reconstructed_predictions':False,
            'outcomes':{key:sum(r['outcome']==key for r in rows) for key in ('WIN','PUSH','LOSS','UNSUPPORTED')},
            'limitations':['reported results not independently verified','no original sealed inputs or closing prices',
                           'known outcomes cannot prove missed value','hypothetical unit returns are not user accounting'],
            'rows':rows}
