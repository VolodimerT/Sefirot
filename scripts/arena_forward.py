"""SEFIROT ARENA forward shadow scorecard: paired, fixture-level and research only.

Workflow: declare a complete fixture cohort BEFORE kickoff; later score *every*
fixture with original sealed prediction, arena report, and optionally result.
No network, LLM, bookmaker execution, SQLite writes or money permission.
The comparator is explicitly a naive max-EV screen, NOT canonical SEFIROT.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import timezone
import json
from pathlib import Path
from random import Random
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from sefirot.contracts import digest, number, strict, text, time
from sefirot.markets import market_from_key, settle
from scripts.arena_shadow import _candidate_rows, _preflight

PLAN_SCHEMA = 'sefirot-arena-forward-plan-v1'
SCORE_SCHEMA = 'sefirot-arena-forward-scorecard-v1'
MIN_FIXTURES_CI = 30
MIN_DATES_CI = 8


def _check_hash(document):
    if not isinstance(document, dict): raise ValueError('JSON object required')
    actual = document.get('hash')
    if not isinstance(actual, str) or digest({k:v for k,v in document.items() if k != 'hash'}) != actual:
        raise ValueError('document hash mismatch')


def freeze(fixtures, created_at):
    """Lock exact fixture IDs and prediction IDs, no results or price inputs."""
    stamped = time(created_at)
    if not isinstance(fixtures, list) or not fixtures: raise ValueError('nonempty planned cohort required')
    ids, rows = set(), []
    for f in fixtures:
        strict(f, ('match_id', 'prediction_id', 'kickoff'))
        text(f['match_id'], 'match id');text(f['prediction_id'], 'prediction id')
        kickoff = time(f['kickoff'])
        if stamped >= kickoff: raise ValueError('plan must be declared before every kickoff')
        if f['match_id'] in ids: raise ValueError('duplicate planned match')
        ids.add(f['match_id']);rows.append(dict(f))
    rows.sort(key=lambda r:(time(r['kickoff']),r['match_id']))
    out = {'schema': PLAN_SCHEMA, 'created_at': created_at, 'fixtures': rows,
           'research_only': True, 'monetary_permission': False, 'execution_enabled': False}
    out['hash'] = digest(out)
    return out


def _moneyless(row, score):
    if row is None: return 0., 'PASS'
    outcome = settle(market_from_key(row['market']), score[0], score[1])
    if outcome not in ('WIN','PUSH','LOSS'): raise ValueError('unknown market settlement')
    return (row['odds']-1 if outcome=='WIN' else 0. if outcome=='PUSH' else -1.), outcome


def _select(row_map, key, min_ev):
    if key is None: return None
    row = row_map.get(key)
    if row is None:raise ValueError('arena selected missing market')
    if row['ev'] is None or row['odds'] is None or row['ev'] < min_ev: return None
    return row


def _entry(plan_item, record, min_ev):
    strict(record, ('match_id', 'prediction', 'quotes', 'arena', 'result'))
    if record['match_id'] != plan_item['match_id']: raise ValueError('record match id mismatch')
    pred = record['prediction'];arena = record['arena'];quotes = record['quotes']
    if not isinstance(pred,dict) or not isinstance(arena,dict):raise ValueError('prediction/arena objects required')
    _check_hash(arena)
    if arena.get('schema')!='sefirot-arena-shadow-v0': raise ValueError('unsupported arena schema')
    if arena.get('prediction_id') != plan_item['prediction_id'] or pred.get('id') != plan_item['prediction_id']:
        raise ValueError('prediction is not in original plan')
    match = pred['sports']['match']
    if match['id'] != record['match_id'] or time(match['kickoff'])!=time(plan_item['kickoff']):
        raise ValueError('fixture kickoff or identity mismatch')
    if arena['match']!=match:raise ValueError('arena match differs from original')
    cutoff = arena['as_of']
    policy, book = _preflight(pred, quotes, cutoff)
    expected = _candidate_rows(pred,book,cutoff,policy)
    if digest(expected)!=digest(arena.get('candidate_rows')):
        raise ValueError('arena candidate math/quotes do not reproduce')
    if arena.get('betting_allowed') is not False or arena.get('monetary_permission') is not False or arena.get('stake')!=0:
        raise ValueError('arena must never grant monetary permission')
    if arena.get('verdict')!='ПРОПУСК' or arena.get('execution_enabled') is not False:
        raise ValueError('arena cannot be a betting decision')
    if len(arena.get('agents',[])) != 8:raise ValueError('all eight reviews required')
    if [a.get('role') for a in arena['agents']] != [
        'history','tactics','lineups','schedule','probability_critic',
        'market_auditor','risk_correlation','death_test']:
        raise ValueError('role order missing/forged')
    focus = arena.get('research_focus')
    if any(a.get('status') not in ('OK','CAUTION','UNKNOWN','BLOCK') for a in arena['agents']):
        raise ValueError('invalid arena review status')
    blockers = any(a.get('status')=='BLOCK' for a in arena['agents'])
    bykey={r['market']:r for r in expected}
    top = arena.get('top_ev_market_diagnostic_only')
    # Avoid trusting an arbitrary user-edited ranking: derive it exactly.
    ordered=sorted([r for r in expected if r['odds'] is not None and r['ev'] is not None],key=lambda r:(-r['ev'],r['market']))
    if top != (ordered[0]['market'] if ordered else None):raise ValueError('top EV ranking differs from original')
    verified_focus=(next((r['market'] for r in ordered if not r['blockers']),None) if not blockers else None)
    if focus != verified_focus:raise ValueError('arena focus not reproducible')
    naive = _select(bykey,top,min_ev)
    screened = _select(bykey,focus,min_ev)
    result=record['result']
    if result is None:
        return {'match_id':record['match_id'],'kickoff':plan_item['kickoff'],'status':'RESULT_MISSING',
                'synthetic':bool(pred.get('synthetic')),'naive_market':naive['market'] if naive else None,
                'arena_market':screened['market'] if screened else None,
                'naive_profit':None,'arena_profit':None,'naive_outcome':None,'arena_outcome':None}
    if not isinstance(result,dict):raise ValueError('result object or null required')
    strict(result, ('match_id','home_goals','away_goals','received_at','status','source'))
    if result['match_id'] != record['match_id'] or result['status']!='FINISHED' or not result['source']:
        raise ValueError('unverified result identity/status')
    if time(result['received_at']) <= time(plan_item['kickoff']):raise ValueError('future/early result leakage')
    hg=result['home_goals'];ag=result['away_goals']
    if any(isinstance(g,bool) or not isinstance(g,int) or not 0<=g<=60 for g in (hg,ag)):
        raise ValueError('invalid final score')
    if match.get('format')!='REGULATION_90':raise ValueError('unsupported match settlement format')
    a_profit,a_state = _moneyless(naive,(hg,ag))
    b_profit,b_state = _moneyless(screened,(hg,ag))
    return {'match_id':record['match_id'],'kickoff':plan_item['kickoff'],'status':'SETTLED',
            'synthetic':bool(pred.get('synthetic')),'naive_market':naive['market'] if naive else None,
            'arena_market':screened['market'] if screened else None,
            'naive_profit':a_profit,'arena_profit':b_profit,'naive_outcome':a_state,'arena_outcome':b_state}


def _summary(rows, method):
    selected=[r for r in rows if r[method+'_market'] is not None]
    settled=[r for r in selected if r['status']=='SETTLED']
    pnl=sum(r[method+'_profit'] for r in settled)
    return {'selected':len(selected), 'settled_selected':len(settled),
            'unsettled_selected':len(selected)-len(settled),
            'win':sum(r[method+'_outcome']=='WIN' for r in settled),
            'push':sum(r[method+'_outcome']=='PUSH' for r in settled),
            'loss':sum(r[method+'_outcome']=='LOSS' for r in settled),
            'unit_stake_pnl':pnl,
            'roi_per_settled_selection':(pnl/len(settled) if settled else None)}


def _interval(rows):
    """Date-clustered, paired bootstrap of per-fixture profit delta; exploratory."""
    settled=[r for r in rows if r['status']=='SETTLED']
    dates=defaultdict(list)
    for row in settled:
        dates[time(row['kickoff']).date().isoformat()].append(row['arena_profit']-row['naive_profit'])
    if len(settled)<MIN_FIXTURES_CI or len(dates)<MIN_DATES_CI:return None
    clusters=list(dates.values());random=Random(20261008);values=[]
    for _ in range(2000):
        picked=[clusters[random.randrange(len(clusters))] for __ in clusters]
        values.append(sum(sum(g) for g in picked)/sum(len(g) for g in picked))
    values.sort()
    return {'low': values[49], 'high': values[1949], 'method':'exploratory paired game-date cluster bootstrap',
            'iterations':2000,'seed':20261008,'certifies_edge':False}


def evaluate(plan, records, *, min_ev=0.02):
    number(min_ev,'minimum EV',0,1)
    _check_hash(plan)
    if plan.get('schema')!=PLAN_SCHEMA or plan.get('monetary_permission') is not False:
        raise ValueError('not a research plan')
    freeze_check=freeze(plan['fixtures'],plan['created_at'])
    if freeze_check!=plan:raise ValueError('plan fields are not canonical')
    if not isinstance(records,list):raise ValueError('records list required')
    assigned={p['match_id']:p for p in plan['fixtures']};byid={}
    for rec in records:
        if not isinstance(rec,dict):raise ValueError('record object required')
        mid=rec.get('match_id')
        if mid not in assigned:raise ValueError('unplanned fixture (cherry-picking)')
        if mid in byid:raise ValueError('duplicate fixture results')
        byid[mid]=rec
    rows=[]
    for f in plan['fixtures']:
        rows.append(_entry(f,byid[f['match_id']],min_ev) if f['match_id'] in byid else
                    {'match_id':f['match_id'],'kickoff':f['kickoff'],'status':'CAPTURE_MISSING',
                     'synthetic':None,'naive_market':None,'arena_market':None,
                     'naive_profit':None,'arena_profit':None,'naive_outcome':None,'arena_outcome':None})
    settled=[r for r in rows if r['status']=='SETTLED']
    pnl_delta=sum(r['arena_profit']-r['naive_profit'] for r in settled)
    out={'schema':SCORE_SCHEMA,'plan_hash':plan['hash'],'planned':len(rows),
         'reported':len(byid),'captured':sum(r['status']!='CAPTURE_MISSING' for r in rows),
         'settled':len(settled),'missing_results':sum(r['status']=='RESULT_MISSING' for r in rows),
         'missing_capture':sum(r['status']=='CAPTURE_MISSING' for r in rows),
         'coverage':len(settled)/len(rows),
         'synthetic':any(r['synthetic'] is not False for r in rows),
         'comparator':'NAIVE_TOP_EV_THRESHOLD_NOT_SEFIROT_BASELINE',
         'min_ev':min_ev, 'naive':_summary(rows,'naive'),'arena':_summary(rows,'arena'),
         'paired_unit_profit_delta':pnl_delta,
         'paired_delta_per_settled_fixture':pnl_delta/len(settled) if settled else None,
         'exploratory_95pct_interval':_interval(rows),
         'rows':rows, 'monetary_permission':False,'execution_enabled':False,'stake':0.,
         'edge_certified':False,'research_status':'INCONCLUSIVE_NO_PROSPECTIVE_HOLDOUT',
         'limitations':['Plan created_at and hashes are self-attested, not authenticated external timestamps.',
                        'No independent model forecasts: agents review, not estimate probabilities.',
                        'Unsettled and unreported planned games stay in coverage.',
                        'A comparison against the actual original SEFIROT decisions requires a separate baseline registry.',
                        'Performance is exploratory and subject to selection bias; unit profits are hypothetical.']}
    out['hash']=digest(out)
    return out


def main(argv=None):
    parser=argparse.ArgumentParser(description='SEFIROT ARENA shadow forward audit: no monetary permission')
    subs=parser.add_subparsers(dest='action',required=True)
    fr=subs.add_parser('freeze',help='create immutable-ish pre-kickoff manifest (self-attested timestamp)')
    fr.add_argument('fixtures',help='JSON list with match_id, prediction_id, kickoff')
    fr.add_argument('--created-at',required=True);fr.add_argument('--output',required=True)
    sc=subs.add_parser('score',help='evaluate complete declared cohort including missing entries')
    sc.add_argument('plan');sc.add_argument('records');sc.add_argument('--output',required=True)
    args=parser.parse_args(argv)
    try:
        load=lambda f:json.loads(Path(f).read_text(encoding='utf-8'))
        if args.action=='freeze':out=freeze(load(args.fixtures),args.created_at)
        else:out=evaluate(load(args.plan),load(args.records))
        target=Path(args.output)
        with target.open('x',encoding='utf-8') as f:
            json.dump(out,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
        print(json.dumps({'schema':out['schema'],'output':str(target),'planned':len(out['fixtures']) if args.action=='freeze' else out['planned'],
                          'research_only':True,'monetary_permission':False},ensure_ascii=False))
        return 0
    except (OSError,ValueError,TypeError,KeyError) as exc:
        parser.exit(2,f'ARENA forward error: {exc}\n')


if __name__=='__main__':raise SystemExit(main())
