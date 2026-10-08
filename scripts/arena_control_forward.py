"""Three aligned hypothetical arms; retain every fixture and every missing arm."""
from __future__ import annotations
import argparse
from datetime import timedelta
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from sefirot.contracts import digest,strict,time,number
from sefirot.identity import code_hash,model_code_hash
from sefirot.markets import market_from_key,settle
from sefirot.repository import Repository
from scripts.arena_control import check_hash,stamp_hash,run_control,write_new,safe_id
from scripts.arena_forward import _interval,evaluate as evaluate_legacy,PLAN_SCHEMA as LEGACY_PLAN

PLAN_SCHEMA='sefirot-arena-control-plan-v0.2'
SCORE_SCHEMA='sefirot-arena-control-scorecard-v0.2'
ARMS=('original','naive','arena')


def freeze(fixtures,created_at,*,min_ev=.02):
    number(min_ev,'frozen minimum EV',0,1)
    if not isinstance(fixtures,list) or not fixtures:raise ValueError('nonempty cohort required')
    ids=set();rows=[]
    for f in fixtures:
        strict(f,('match_id','kickoff'))
        safe_id(f['match_id'])
        if f['match_id'] in ids:raise ValueError('duplicate fixture')
        if time(created_at)>=time(f['kickoff']):raise ValueError('plan must precede every kickoff')
        ids.add(f['match_id']);rows.append(dict(f))
    return stamp_hash({'schema':PLAN_SCHEMA,'created_at':created_at,
          'fixtures':sorted(rows,key=lambda f:(time(f['kickoff']),f['match_id'])),
          'min_ev':min_ev,'core_hash':code_hash(),'model_hash':model_code_hash(),
          'provenance':'SELF_ATTESTED_MANIFEST','external_time_verified':False,
          'stake':0.,'monetary_permission':False,'execution_enabled':False})


def _result(result,fixture,as_of,database):
    if result is None:return None,'RESULT_MISSING'
    strict(result,('match_id','status','home_goals','away_goals','finished_at','received_at','source'))
    if result['match_id']!=fixture['match_id'] or result['status']!='FINISHED' or not isinstance(result['source'],str) or not result['source']:
        raise ValueError('result identity/status/source mismatch')
    if any(type(result[k]) is not int or not 0<=result[k]<=50 for k in ('home_goals','away_goals')):raise ValueError('invalid score')
    if not time(fixture['kickoff'])+timedelta(minutes=90)<=time(result['finished_at'])<=time(result['received_at'])<=time(as_of):
        raise ValueError('future or premature result')
    if database is not None:
        repo=Repository(database,read_only=True)
        try:
            repo.db.execute('BEGIN')
            if not repo.verify():raise ValueError('journal integrity failed')
            try:saved=repo.get('results',fixture['match_id'])
            except ValueError:saved=None
            if saved is not None:
                if saved!=result:raise ValueError('result differs from recorded source')
                bound=any(json.loads(a['payload']).get('record_hash')==digest(saved)
                    and json.loads(a['payload']).get('record_table')=='results'
                    and json.loads(a['payload']).get('record_id')==fixture['match_id']
                    and time(a['at'])<=time(as_of)
                    for a in repo.db.execute("SELECT at,payload FROM audit_logs WHERE event='RECORD'"))
                if not bound:raise ValueError('result has no bound receipt')
                return (result['home_goals'],result['away_goals']),'LOCAL_LEDGER_BOUND'
        finally:repo.close()
    return (result['home_goals'],result['away_goals']),'SELF_ATTESTED_RESULT'


def _arm(selection,result):
    if selection is None:return {'market':None,'odds':None,'profit':0.,'outcome':'PASS','available':True}
    if result is None:return {'market':selection['market'],'odds':selection['odds'],'profit':None,'outcome':None,'available':True}
    outcome=settle(market_from_key(selection['market']),*result)
    profit=selection['odds']-1 if outcome=='WIN' else 0. if outcome=='PUSH' else -1.
    return {'market':selection['market'],'odds':selection['odds'],'profit':profit,'outcome':outcome,'available':True}


def _missing():return {'market':None,'odds':None,'profit':None,'outcome':None,'available':False}


def evaluate(plan,records,*,as_of,database=None):
    if plan.get('schema')==LEGACY_PLAN:return evaluate_legacy(plan,records)
    check_hash(plan)
    if plan!=freeze(plan['fixtures'],plan['created_at'],min_ev=plan['min_ev']):raise ValueError('plan/build incompatible')
    if time(as_of)<time(plan['created_at']):raise ValueError('evaluation precedes plan')
    if not isinstance(records,list):raise ValueError('records list required')
    fixtures={f['match_id']:f for f in plan['fixtures']};assigned={}
    for rec in records:
        strict(rec,('match_id','prediction','quotes','arena','result'))
        if rec['match_id'] not in fixtures:raise ValueError('unplanned fixture')
        if rec['match_id'] in assigned:raise ValueError('duplicate capture')
        assigned[rec['match_id']]=rec
    rows=[]
    for f in plan['fixtures']:
        row={'match_id':f['match_id'],'kickoff':f['kickoff'],'capture_status':'CAPTURE_MISSING',
             'original_status':'ORIGINAL_DECISION_MISSING','result_status':'RESULT_MISSING',
             'synthetic':None,'quote_coverage':False,'paired_eligible':False,
             **{a:_missing() for a in ARMS}}
        if f['match_id'] not in assigned:rows.append(row);continue
        rec=assigned[f['match_id']];p=rec['prediction'];report=rec['arena'];check_hash(report)
        if report.get('schema')!='sefirot-arena-control-v0.2':raise ValueError('use separate legacy evaluator for old reports')
        if p['sports']['match']['id']!=f['match_id'] or time(p['sports']['match']['kickoff'])!=time(f['kickoff']):
            raise ValueError('capture differs from planned fixture')
        if not time(plan['created_at'])<=time(p['sealed_at'])<=time(report['as_of'])<=time(as_of):
            raise ValueError('capture/report chronology differs from plan')
        expected=run_control(p,rec['quotes'],report['as_of'],database=database,
                             decision_id=(report['provenance']['original'] or {}).get('id'),
                             recorded_reviews=report['reviews'])
        for k in ('prediction_id','match','as_of','synthetic','build','reviews','review_views_hashes',
                  'candidate_rows','research_focus','provenance','global_hard_stop','global_blockers','evidence_graph','ranked_alternatives'):
            if expected[k]!=report[k]:raise ValueError('arena report does not reproduce: '+k)
        if report.get('stake')!=0 or report.get('monetary_permission') is not False or report.get('execution_enabled') is not False:
            raise ValueError('money permission forbidden')
        candidates=report['candidate_rows'];priced=[r for r in candidates if r['odds'] is not None and r['ev']>=plan['min_ev']]
        naive=min(priced,key=lambda r:(-r['ev'],r['market'])) if priced else None
        screened=next((r for r in priced if r['market']==report['research_focus']),None)
        result,result_status=_result(rec['result'],f,as_of,database)
        original=report['provenance']['original'];original_arm=_missing()
        if original:
            choice=None
            if original['decision']=='BET':
                choice=next((r for r in candidates if r['market']==original['selected_market']),None)
                if choice is None or choice['odds']!=original['selected_odds']:raise ValueError('original selected price not aligned')
            original_arm=_arm(choice,result)
        row.update(capture_status='CAPTURED',synthetic=report['synthetic'],
                   original_status=report['provenance']['original_status'],result_status=result_status,
                   quote_coverage=any(r['odds'] is not None for r in candidates),original=original_arm,naive=_arm(naive,result),arena=_arm(screened,result),
                   paired_eligible=bool(original and result is not None and result_status=='LOCAL_LEDGER_BOUND'
                                        and not report['synthetic'] and report['provenance']['status']=='LOCAL_LEDGER_BOUND'))
        rows.append(row)
    def summary(a):
        available=[r[a] for r in rows if r[a]['available']]
        selected=[r for r in available if r['market'] is not None]
        settled=[r for r in selected if r['profit'] is not None]
        known=sum(r['profit'] for r in available if r['profit'] is not None)
        complete=len(available)==len(rows) and all(r['profit'] is not None for r in available)
        return {'available':len(available),'missing_arm':len(rows)-len(available),'selected':len(selected),
                'settled_selected':len(settled),'known_unit_pnl':known,
                'unit_pnl_per_planned_fixture':known/len(rows) if complete else None,
                'roi_per_settled_selection':sum(r['profit'] for r in settled)/len(settled) if settled else None,
                'coverage':len(available)/len(rows)}
    paired=[r for r in rows if r['paired_eligible']]
    rejected=[r for r in rows if r['naive']['market'] is not None and r['naive']['market']!=r['arena']['market'] and r['naive']['profit'] is not None]
    exploratory=[{'status':'SETTLED','kickoff':r['kickoff'],'arena_profit':r['arena']['profit'],
                  'naive_profit':r['original']['profit']} for r in paired]
    out={'schema':SCORE_SCHEMA,'plan_hash':plan['hash'],'as_of':as_of,'planned':len(rows),
         'captured':len(assigned),'missing_capture':len(rows)-len(assigned),
         'missing_original_decisions':sum(not r['original']['available'] for r in rows),
         'missing_results':sum(r['result_status']=='RESULT_MISSING' for r in rows),
         'quote_coverage':sum(r['quote_coverage'] for r in rows)/len(rows),
         'paired_eligible':len(paired),'paired_coverage':len(paired)/len(rows),
         'arms':{a:summary(a) for a in ARMS},'no_bet_baseline':{'hypothetical_pnl':0},
         'rejected_profitable':sum(r['naive']['profit']>0 for r in rejected),
         'rejected_unprofitable':sum(r['naive']['profit']<0 for r in rejected),'rejection_metric':'HINDSIGHT_NOT_TRUE_VALUE',
         'paired_arena_minus_original':sum(r['arena']['profit']-r['original']['profit'] for r in paired) if paired else None,
         'exploratory_interval':_interval(exploratory),'rows':rows,
         'status':'EXPLORATORY_LOCAL_RECEIPTS' if paired else 'INSUFFICIENT_DATA',
         'provenance':'PROVENANCE_UNVERIFIED_MANIFEST_TIME','prospective_validated':False,
         'external_time_verified':False,'forecast_probability_changed':False,'llm_cost_usd':None,
         'stake':0.,'monetary_permission':False,'execution_enabled':False,'edge_certified':False}
    return stamp_hash(out)


def main(argv=None):
    parser=argparse.ArgumentParser(description='ARENA v0.2 three-arm offline scorecard')
    sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('freeze');p.add_argument('fixtures');p.add_argument('--created-at',required=True)
    p.add_argument('--min-ev',type=float,default=.02);p.add_argument('--output',required=True)
    p=sub.add_parser('score');p.add_argument('plan');p.add_argument('records')
    p.add_argument('--as-of',required=True);p.add_argument('--db');p.add_argument('--output',required=True)
    args=parser.parse_args(argv);load=lambda f:json.loads(Path(f).read_text(encoding='utf-8'))
    try:
        out=freeze(load(args.fixtures),args.created_at,min_ev=args.min_ev) if args.action=='freeze' else evaluate(
            load(args.plan),load(args.records),as_of=args.as_of,database=args.db)
        write_new(args.output,out);print(json.dumps({'schema':out['schema'],'stake':0,'output':args.output}));return 0
    except (ValueError,KeyError,TypeError,OSError) as e:parser.exit(2,str(e)+'\n')


if __name__=='__main__':raise SystemExit(main())
