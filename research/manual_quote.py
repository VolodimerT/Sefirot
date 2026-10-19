"""Manual main-market price preview. No writes, network, decisions or bets."""
from sefirot.contracts import Policy, strict, time
from sefirot.markets import market_of, validate_quote, payoff_ev
from sefirot.readiness import inspect_readiness
from sefirot.service import Service


def preview(repo, payload, at):
    strict(payload,('prediction_id','fixture_id','market','period','bookmaker','odds',
                    'observed_at','rules_confirmed'))
    if payload['period']!='FT_REGULATION_90' or payload['rules_confirmed'] is not True:
        raise ValueError('EXACT_REGULATION_RULES_REQUIRED')
    if not repo.verify():raise ValueError('JOURNAL_INTEGRITY_FAILED')
    p=repo.get('predictions',payload['prediction_id'])
    if time(at)>=time(p['sports']['match']['kickoff']):raise ValueError('PREMATCH_CLOSED')
    if p['sports']['match']['id']!=payload['fixture_id']:
        raise ValueError('QUOTE_FIXTURE_MISMATCH')
    key=market_of(payload['market']).key
    quote={'market':payload['market'],'bookmaker':payload['bookmaker'],'odds':payload['odds'],
           'observed_at':payload['observed_at'],'received_at':at,'phase':'FINAL','rules':'REGULATION_90'}
    validate_quote(quote,p['sports']['match']['kickoff'],at,p['sealed_at'])
    if time(payload['observed_at'])<time(p['sealed_at']):raise ValueError('QUOTE_PRECEDES_PROBABILITY_SEAL')
    policy=Policy()
    if not 0 <= (time(at)-time(payload['observed_at'])).total_seconds() <= policy.quote_max_age_seconds:
        raise ValueError('QUOTE_STALE_OR_FUTURE')
    rows=[r for r in p['candidates'] if r['key']==key]
    if len(rows)!=1:raise ValueError('QUOTE_NOT_IN_SEALED_MARKET_POOL')
    gate=inspect_readiness(Service(repo,policy),p['id'],at)
    market=next((r for r in gate['markets'] if r['market']==key),None)
    c=rows[0]
    verified=(p.get('calibrator') is not None and not p['synthetic']
              and c['calibration']=='CALIBRATED_BIN' and c['calibration_n']>=20
              and market is not None and market['ready_for_price_recheck'] is True)
    # This is an arithmetic preview only. A fresh independent recheck and the
    # existing Service.decide are still required; preview never promotes PASS.
    return {'schema':'manual-quote-preview-v1','quote':quote,'quote_origin':'OPERATOR_ASSERTION',
            'source_attested':False,'probability_status':'CALIBRATED' if verified else 'NOT_VERIFIED',
            'probability':c['base'][0] if verified else None,
            'ev':payoff_ev(c['base'][0],c['base'][1],quote['odds']) if verified else None,
            'blockers':[] if verified else ['CALIBRATION_OR_CORE_READINESS_NOT_VERIFIED'],
            'decision':'PASS','stake':0,'monetary_permission':False,'execution_enabled':False,
            'decision_created':False,'requires_original_service_decide':True}
