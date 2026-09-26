"""Synthetic fixtures are prominently marked and can never certify a release."""
from datetime import datetime,timedelta,timezone
from .markets import DEFAULT_POOL


def example(at=None,match_id='synthetic-001'):
    now=at or datetime.now(timezone.utc);now=now.replace(microsecond=0)
    ts=lambda delta:(now+timedelta(minutes=delta)).isoformat()
    sources=[{'id':'official','independence_group':'club','reliability':.95,'enabled':True},
             {'id':'statistics','independence_group':'league','reliability':.95,'enabled':True}]
    values={'home_team':'A','away_team':'B','format':'REGULATION_90','lineup':{'status':'CONFIRMED','home':[f'A-{i}' for i in range(11)],'away':[f'B-{i}' for i in range(11)]},'injuries':{'home':[],'away':[]},
            'coach':'STABLE','rotation':'NORMAL','tactics':{'home_style':'BALANCED','away_style':'BALANCED','fit':'SUPPORTED','key_factor':'historical squad continuity'}}
    facts=[{'id':'fact-'+key,'key':key,'value':value,'kind':'FACT','source_id':'official','published_at':ts(-3),
            'received_at':ts(-2),'observed_at':ts(-4),'critical':True,'supports':[]} for key,value in values.items()]
    history=[]
    for i in range(40):
        day=now-timedelta(days=80-i)
        history.append({'id':f'history-{i}','home':'A' if i%2 else 'B','away':'B' if i%2 else 'A','league':'SYNTHETIC',
                        'kickoff':day.isoformat(),'finished_at':(day+timedelta(hours=2)).isoformat(),
                        'received_at':(day+timedelta(hours=3)).isoformat(),'home_goals':i%4,'away_goals':i%2,'source_id':'statistics'})
    sports={'match':{'id':match_id,'home':'A','away':'B','league':'SYNTHETIC','kickoff':ts(120),'sport':'football','format':'REGULATION_90'},
            'as_of':ts(-1),'sources':sources,'evidence':facts,'history':history,'synthetic':True}
    quotes=[{'market':m,'bookmaker':'SYNTHETIC_BOOK','odds':2.1,'observed_at':ts(1),'received_at':ts(1),
             'phase':'FINAL','rules':'REGULATION_90'} for m in DEFAULT_POOL]
    recheck={'checked_at':ts(1),'evidence':[{**e,'id':'recheck-'+e['key'],'published_at':ts(0),'observed_at':ts(0),'received_at':ts(1)} for e in facts]}
    return {'sports':sports,'markets':DEFAULT_POOL,'quotes':quotes,'recheck':recheck,'decision_at':ts(2),
            'result':{'match_id':match_id,'status':'FINISHED','home_goals':2,'away_goals':1,'finished_at':ts(230),'received_at':ts(231),'source':'SYNTHETIC'}}
