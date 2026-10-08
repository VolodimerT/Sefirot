"""Versioned evidence review over frozen Core probabilities, never admission."""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

from sefirot.contracts import Policy,digest,strict,time
from sefirot.evidence import inspect,eligible_history
from sefirot.identity import code_hash,model_code_hash
from sefirot.probability import ev_bounds
from sefirot.repository import Repository
from scripts.arena_shadow import ROLE_SPECS,_preflight,_candidate_rows

SCHEMA='sefirot-arena-control-v0.2'
FINDING_SCHEMA='arena-finding-v0.2'
SAFE_ID=re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$')
STATES={'SUPPORTED','DISPUTED','UNKNOWN','HARD_BLOCK'}
FIELDS=('schema','role','phase','market_key','premise_id','state','severity',
        'mechanism','evidence_ids','independence_groups','effective_at',
        'confidence_label','unknowns','action','impact_on_probability','monetary_permission')


def stamp_hash(doc):return {**doc,'hash':digest(doc)}


def check_hash(doc):
    if not isinstance(doc,dict) or doc.get('hash')!=digest({k:v for k,v in doc.items() if k!='hash'}):
        raise ValueError('document hash mismatch')


def safe_id(value):
    if not isinstance(value,str) or not SAFE_ID.fullmatch(value):raise ValueError('unsafe evidence identity')
    return value


def sports_view(prediction,policy):
    """No raw text/nested payloads. Only usable facts and eligible past results."""
    sports=prediction['sports'];check=inspect(sports,policy);match=sports['match']
    active=set(check['eligible_fact_ids']);sources=check['sources'];facts=[]
    for e in sports['evidence']:
        if e['id'] not in active or e['kind']!='FACT':continue
        safe_id(e['id']);safe_id(e['source_id']);source=sources[e['source_id']]
        safe_id(source['independence_group']);key=e['key'];v=e['value']
        # Controlled summaries replace names, arbitrary narratives and instructions.
        if key in ('home_team','away_team'):value='HOME' if key=='home_team' else 'AWAY'
        elif key=='format':value='REGULATION_90' if v=='REGULATION_90' else 'UNKNOWN'
        elif key=='lineup':
            value={'confirmed':isinstance(v,dict) and v.get('status')=='CONFIRMED',
                   'home_count':len(v.get('home',[])) if isinstance(v,dict) and isinstance(v.get('home'),list) else None,
                   'away_count':len(v.get('away',[])) if isinstance(v,dict) and isinstance(v.get('away'),list) else None}
        elif key=='injuries':
            value={side:len(v[side]) if isinstance(v,dict) and isinstance(v.get(side),list) else None for side in ('home','away')}
        elif key in ('coach','rotation'):value=v if v in ('STABLE','NORMAL') else 'OTHER_UNQUANTIFIED'
        elif key=='tactics':
            styles={'BALANCED','ATTACKING','DEFENSIVE','HIGH_PRESS','LOW_BLOCK','COUNTER'}
            value={'fit':'SUPPORTED' if isinstance(v,dict) and v.get('fit')=='SUPPORTED' else 'UNKNOWN',
                   **{side+'_style':v.get(side+'_style') if isinstance(v,dict) and v.get(side+'_style') in styles else 'UNKNOWN' for side in ('home','away')}}
        else:continue
        facts.append({'id':e['id'],'key':key,'value':value,'source_id':e['source_id'],
                      'independence_group':source['independence_group'],
                      **{k:e[k] for k in ('observed_at','published_at','received_at')}})
    history,_=eligible_history(sports,policy)
    allowed=set(prediction['model'].get('used_history',[r['id'] for r in history]))
    history_rows=[]
    for r in history:
        if r['id'] not in allowed or r['id']==match['id']:continue
        if any(time(r[k])>time(sports['as_of']) for k in ('observed_at','available_at') if k in r):continue
        history_rows.append({k:r[k] for k in ('id','kickoff','finished_at','received_at','home_goals','away_goals')})
    return {'as_of':sports['as_of'],'match':{'id':safe_id(match['id']),'home':'HOME','away':'AWAY',
            'kickoff':match['kickoff'],'format':match['format'],'competition_profile':match.get('competition_profile','UNKNOWN')},
            'evidence':facts,'history':history_rows,'free_text':'WITHHELD_UNVERIFIED_NARRATIVE'}


def candidate_rows(prediction,quotes,at):
    policy,prices=_preflight(prediction,quotes,at)
    if prediction.get('model_hash')!=model_code_hash() or prediction.get('code_hash')!=code_hash():
        raise ValueError('BUILD_INCOMPATIBLE: use the original compatible build')
    if policy.fingerprint!=Policy().fingerprint:raise ValueError('POLICY_INCOMPATIBLE')
    rows=_candidate_rows(prediction,prices,at,policy)
    global_codes={i['code'] for i in prediction.get('issues',[]) if i.get('severity')=='BLOCK'}
    for c,r in zip(prediction['candidates'],rows):
        # v0 used EV - P(win) for stress and an infeasible low vector.
        # v0.2 delegates bounds to the unchanged canonical Core math.
        blocks=set(r['blockers'])-{'LOW_EV_NEGATIVE','NEGATIVE_STRESS_EV'}
        blocks.update(global_codes)
        if r['odds'] is not None:
            r['low_ev'],r['high_ev']=ev_bounds(c['low'],c['high'],r['odds'])
            stress=[v[0]*(r['odds']-1)-v[2] for v in c.get('stress_probabilities',[])]
            r['stress_ev_min']=min(stress) if stress else None
            if r['low_ev']<policy.min_low_ev:blocks.add('LOW_EV_NEGATIVE')
            if stress and min(stress)<0:blocks.add('NEGATIVE_STRESS_EV')
        r['blockers']=sorted(blocks)
        chosen=max(prices.get(c['key'],[]),key=lambda q:(time(q['observed_at']),time(q['received_at']),q['bookmaker']),default=None)
        r['quote_hash']=digest(chosen) if chosen and r['odds'] is not None else None
    return policy,rows


def ledger_bridge(database,prediction,quotes,at,decision_id=None):
    """One fresh RO snapshot. A local hash chain is not external time proof."""
    empty={'status':'PROVENANCE_UNVERIFIED','external_time_verified':False,
           'original_status':'ORIGINAL_DECISION_MISSING','original':None,'prediction_receipt':None}
    if database is None:return empty
    repo=Repository(database,read_only=True)
    try:
        repo.db.execute('BEGIN')
        if not repo.verify():raise ValueError('journal integrity failed')
        p=repo.get('predictions',prediction['id'])
        if digest(p)!=digest(prediction):raise ValueError('prediction differs from ledger')
        def receipt(table,row):
            matches=[]
            for a in repo.db.execute("SELECT * FROM audit_logs WHERE event='RECORD' ORDER BY id"):
                payload=json.loads(a['payload'])
                if (payload.get('record_table')==table and payload.get('record_id')==row['id']
                    and payload.get('record_hash')==digest(row) and time(a['at'])<=time(at)):
                    matches.append({'audit_hash':a['hash'],'record_hash':payload['record_hash'],'at':a['at']})
            if not matches:raise ValueError('no cutoff-bound original receipt')
            return matches[0]
        out={**empty,'status':'LOCAL_LEDGER_BOUND','prediction_receipt':receipt('predictions',p)}
        if time(out['prediction_receipt']['at'])!=time(p['sealed_at']):raise ValueError('seal/receipt time mismatch')
        decisions=repo.all('decisions',at,prediction_id=p['id'])
        aligned=[d for d in decisions if time(d['at'])==time(at) and digest(d['inputs']['quotes'])==digest(quotes)]
        if decision_id:
            aligned=[d for d in aligned if d['id']==decision_id]
            if not aligned:raise ValueError('original decision does not align with exact cutoff/quotes')
        if not aligned:return out
        d=min(aligned,key=lambda x:x['id'])
        if d['id']!=digest({k:v for k,v in d.items() if k!='id'}) or d['decision'] not in ('BET','PASS'):
            raise ValueError('invalid original decision')
        if not time(p['sealed_at'])<=time(d['at'])<time(p['sports']['match']['kickoff']):raise ValueError('not a prematch decision')
        out.update(original_status='ORIGINAL_DECISION_RECORDED',original={
            'id':d['id'],'decision':d['decision'],'selected_market':d['selected_market'],
            'at':d['at'],'class':d['class'],'quote_hash':digest(d['inputs']['quotes']),
            'receipt':receipt('decisions',d),'global_blockers':sorted(i['code'] for i in d['issues'] if i['severity']=='BLOCK'),
            'market_blockers':{c['key']:sorted(i['code'] for i in c['issues'] if i['severity']=='BLOCK') for c in d['candidates']},
            'selected_odds':next((c.get('odds') for c in d['candidates'] if c['key']==d['selected_market']),None)})
        return out
    finally:repo.close()


def finding(role,phase,market,at,*,state='UNKNOWN',premise=None,ids=(),groups=(),mechanism='No verified premise',unknowns=()):
    return {'schema':FINDING_SCHEMA,'role':role,'phase':phase,'market_key':market,
            'premise_id':premise,'state':state,'severity':'BLOCK' if state=='HARD_BLOCK' else 'WARN' if state in ('UNKNOWN','DISPUTED') else 'INFO',
            'mechanism':mechanism,'evidence_ids':list(ids),'independence_groups':list(groups),
            'effective_at':at,'confidence_label':'EVIDENCE_BOUND' if ids else 'UNVERIFIED',
            'unknowns':list(unknowns),'action':'REVIEW_PREMISE','impact_on_probability':'UNQUANTIFIED','monetary_permission':False}


def validate_findings(items,role,view,cutoff):
    if not isinstance(items,list) or len(items)>24:raise ValueError('bounded findings list required')
    facts={e['id']:e for e in view['sports']['evidence']}
    keys={c['market'] for c in view['model_diagnostics']}
    out=[]
    for f in items:
        strict(f,FIELDS)
        if f['schema']!=FINDING_SCHEMA or (f['role'],f['phase'])!=role[:2]:raise ValueError('finding role/schema mismatch')
        if f['state'] not in STATES or f['severity'] not in ('BLOCK','WARN','INFO'):raise ValueError('invalid state/severity')
        if f['market_key'] is not None and f['market_key'] not in keys:raise ValueError('unknown market')
        if f['premise_id'] is not None and f['premise_id'] not in facts and f['premise_id'] not in {'candidate:'+k for k in keys}:
            raise ValueError('unknown premise')
        ids=f['evidence_ids'];groups=f['independence_groups']
        if not isinstance(ids,list) or len(set(ids))!=len(ids) or any(i not in facts for i in ids):raise ValueError('unknown evidence ID')
        expected=sorted({facts[i]['independence_group'] for i in ids})
        if groups!=expected:raise ValueError('source-family independence mismatch')
        if time(f['effective_at'])>time(cutoff) or any(time(facts[i]['received_at'])>time(f['effective_at']) for i in ids):raise ValueError('future finding')
        if f['impact_on_probability']!='UNQUANTIFIED' or f['monetary_permission'] is not False:raise ValueError('review cannot alter probability or money')
        if f['confidence_label']!=('EVIDENCE_BOUND' if ids else 'UNVERIFIED'):raise ValueError('unvalidated confidence')
        if any(not isinstance(f[k],str) or len(f[k])>1000 for k in ('mechanism','action')):raise ValueError('invalid finding text')
        if not isinstance(f['unknowns'],list) or len(f['unknowns'])>12 or any(not isinstance(s,str) or len(s)>120 for s in f['unknowns']):raise ValueError('invalid unknowns')
        if f['state']=='HARD_BLOCK' or f['severity']=='BLOCK':
            if f['state']!='HARD_BLOCK' or f['severity']!='BLOCK' or f['market_key'] is None or not ids or f['premise_id'] not in ids:
                raise ValueError('market veto needs a specific verified fact premise; no reviewer global veto')
        out.append(deepcopy(f))
    return out


def rule_review(role,view):
    name,phase,_=role;cutoff=view['sports']['as_of']
    if name=='probability_critic':
        return [finding(name,phase,c['market'],cutoff,premise='candidate:'+c['market'],
                mechanism='Existing calibration status; no new numeric trust score',
                unknowns=[] if c['calibration']=='CALIBRATED_BIN' else ['independent calibration and holdout'])
                for c in view['model_diagnostics']]
    return [finding(name,phase,None,cutoff,unknowns=[{
        'history':'independent validation','tactics':'falsifiable tactical mechanism',
        'lineups':'fresh decision-time lineup','schedule':'confirmed rest/travel timeline',
        'market_auditor':'external price provenance','risk_correlation':'confirmed portfolio/joint exposure',
        'death_test':'causal falsifier and verified public feed'}[name]])]


def arbitrate(rows,findings,global_hard_stop):
    reviewed=[]
    for r in rows:
        local=[f for f in findings if f['market_key']==r['market']]
        blocks=[f for f in local if f['state']=='HARD_BLOCK']
        state='hard_block' if r['blockers'] or blocks else 'disputed' if any(f['state']=='DISPUTED' for f in local) else 'unknown' if any(f['state']=='UNKNOWN' for f in local) else 'viable'
        reviewed.append({**r,'market_state':state,'market_findings':local,
                         'research_eligible':not r['blockers'] and not blocks and state=='viable'})
    ranked=sorted(reviewed,key=lambda r: (-(r['ev'] if r['ev'] is not None else -1e9),r['market']))
    focus=next((r['market'] for r in ranked if r['research_eligible'] and r['odds'] is not None),None) if not global_hard_stop else None
    return reviewed,focus


def run_control(prediction,quotes,at,*,database=None,decision_id=None,reviewer=None,recorded_reviews=None):
    policy,rows=candidate_rows(prediction,quotes,at);sports=sports_view(prediction,policy)
    provenance=ledger_bridge(database,prediction,quotes,at,decision_id)
    if provenance['original']:
        original=provenance['original']
        for r in rows:r['blockers']=sorted(set(r['blockers'])|set(original['global_blockers'])|set(original['market_blockers'].get(r['market'],[])))
    else:
        for r in rows:r['blockers']=sorted(set(r['blockers'])|{'CANONICAL_RECHECK_NOT_RECORDED'})
    diagnostics=[{'market':r['market'],'calibration':r['calibration']} for r in rows]
    views=[];reviews=[]
    if reviewer is not None and recorded_reviews is not None:raise ValueError('choose fresh reviews or replay')
    if recorded_reviews is not None and len(recorded_reviews)!=len(ROLE_SPECS):raise ValueError('eight recorded reviews required')
    for idx,role in enumerate(ROLE_SPECS):
        view={'role':role[0],'phase':role[1],'sports':deepcopy(sports),'model_diagnostics':deepcopy(diagnostics)}
        if role[1]=='priced':view['market_rows']=deepcopy(rows)
        items=recorded_reviews[idx] if recorded_reviews is not None else (reviewer or rule_review)(role,deepcopy(view))
        reviews.append(validate_findings(items,role,view,sports['as_of'] if role[1]=='sports' else at));views.append(digest(view))
    findings=[f for group in reviews for f in group]
    stop=provenance['status']=='PROVENANCE_UNVERIFIED'
    rows,focus=arbitrate(rows,findings,stop)
    out={'schema':SCHEMA,'prediction_id':prediction['id'],'match':prediction['sports']['match'],'as_of':at,
         'synthetic':bool(prediction['synthetic']),'profile':'REPLAY' if recorded_reviews is not None else 'CUSTOM_SHADOW' if reviewer is not None else 'RULE_ONLY',
         'prompt_version':'evidence-allowlist-v0.2','review_views_hashes':views,'reviews':reviews,
         'evidence_graph':{'facts':sports['evidence'],'edges':[
             {'role':f['role'],'market':f['market_key'],'premise':f['premise_id'],'fact_id':eid,
              'relation':'CONTRADICTS' if f['state'] in ('HARD_BLOCK','DISPUTED') else 'SUPPORTS' if f['state']=='SUPPORTED' else 'UNKNOWN',
              'impact':'UNQUANTIFIED'} for f in findings for eid in f['evidence_ids']],
              'independent_source_families':sorted({e['independence_group'] for e in sports['evidence']})},
         'candidate_rows':rows,'research_focus':focus,'global_hard_stop':stop,
         'ranked_alternatives':[r['market'] for r in sorted(rows,key=lambda r:(-(r['ev'] if r['ev'] is not None else -1e9),r['market']))],
         'global_blockers':['PROVENANCE_UNVERIFIED'] if stop else [],'provenance':provenance,
         'build':{'core_hash':code_hash(),'model_hash':model_code_hash(),'policy_hash':policy.fingerprint,
                  'control_hash':digest(Path(__file__).read_text(encoding='utf-8'))},
         'review_invocations':8,'gpt_calls':0 if reviewer is None else None,
         'cost_usd':0 if reviewer is None else None,'latency_ms':None,
         'research_status':'UNVALIDATED_SHADOW','verdict':'ПРОПУСК','class':'D',
         'stake':0.,'monetary_permission':False,'execution_enabled':False,'edge_certified':False}
    return stamp_hash(out)


def write_new(path,document):
    """Serialize first; partial write rolls back only our exclusively-created file."""
    payload=json.dumps(document,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    target=Path(path);created=False
    try:
        with target.open('x',encoding='utf-8') as f:
            created=True;f.write(payload);f.flush()
            import os
            os.fsync(f.fileno())
    except BaseException:
        if created:target.unlink(missing_ok=True)
        raise


def main(argv=None):
    p=argparse.ArgumentParser(description='ARENA v0.2 evidence review; offline research only')
    p.add_argument('--prediction',required=True);p.add_argument('--quotes',required=True);p.add_argument('--at',required=True)
    p.add_argument('--db');p.add_argument('--decision-id');p.add_argument('--reviews',help='replay validated structured findings')
    p.add_argument('--output',required=True);args=p.parse_args(argv)
    load=lambda x:json.loads(Path(x).read_text(encoding='utf-8'))
    try:
        out=run_control(load(args.prediction),load(args.quotes),args.at,database=args.db,decision_id=args.decision_id,
                        recorded_reviews=load(args.reviews) if args.reviews else None)
        write_new(args.output,out);print(json.dumps({'schema':out['schema'],'research_status':out['research_status'],
              'provenance':out['provenance']['status'],'original':out['provenance']['original_status'],'stake':0}))
        return 0
    except (ValueError,KeyError,TypeError,OSError) as e:p.exit(2,str(e)+'\n')


if __name__=='__main__':raise SystemExit(main())
