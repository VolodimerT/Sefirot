"""UTF-8 CLI; default workflows operate on local, user-supplied sources."""
import argparse
from datetime import datetime,timezone
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import sqlite3
import tempfile
from .contracts import Policy,VERSION,time
from .repository import Repository
from .service import Service
from .fixtures import example
from .markets import DEFAULT_POOL


def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))

def write_quotes(path, payload):
    """Write a validated quote file and its provenance receipt without overwrites."""
    destination=Path(path);receipt=Path(str(destination)+'.receipt.json')
    if destination.exists() or receipt.exists():raise ValueError('odds output already exists; choose a fresh filename')
    destination.parent.mkdir(parents=True,exist_ok=True)
    staged=[]
    try:
        for target,value in ((receipt,payload['receipt']),(destination,payload['quotes'])):
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=destination.parent,
                                             prefix='.sefirot-',suffix='.staged',delete=False) as file:
                json.dump(value,file,ensure_ascii=False,indent=2,allow_nan=False)
                file.write('\n');staged.append((file.name,target))
        for temporary,target in staged:os.replace(temporary,target)
    finally:
        for temporary,_ in staged:
            if os.path.exists(temporary):os.unlink(temporary)
    return {'quotes_file':str(destination.resolve()),'receipt_file':str(receipt.resolve()),
            'quotes':len(payload['quotes']),'overround':payload['receipt']['overround'],
            'execution_price_verified':False}

def main(argv=None):
    # Windows redirected streams can default to an encoding without Cyrillic.
    # The CLI's JSON and Russian cards use UTF-8 in both pipes and terminals.
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='SEFIROT CORE '+VERSION+' — prematch analysis and audit')
    parser.add_argument('--db',default='data/sefirot.sqlite')
    parser.add_argument('--policy',help='versioned experimental JSON policy')
    sub=parser.add_subparsers(dest='command',required=True)
    worker=sub.add_parser('work');worker.add_argument('directory');worker.add_argument('--watch',action='store_true')
    demo=sub.add_parser('demo',help='complete synthetic workflow in a temporary database')
    demo.add_argument('--text',action='store_true',help='concise Russian decision card')
    fixture=sub.add_parser('fixture',help='write synthetic JSON input files');fixture.add_argument('directory')
    capture=sub.add_parser('capture',help='seal sports-only probability before reading any prices');capture.add_argument('sports');capture.add_argument('--markets');capture.add_argument('--calibrator');capture.add_argument('--parent');capture.add_argument('--reason')
    decision=sub.add_parser('decide');decision.add_argument('prediction_id');decision.add_argument('quotes');decision.add_argument('recheck');decision.add_argument('--bankroll',type=float,default=1000);decision.add_argument('--peak',type=float,default=1000)
    decision.add_argument('--text',action='store_true',help='print the decision card; save the full decision in the ledger')
    result=sub.add_parser('result');result.add_argument('file')
    closing=sub.add_parser('closing');closing.add_argument('match_id');closing.add_argument('file')
    replay=sub.add_parser('replay');replay.add_argument('decision_id')
    explain=sub.add_parser('explain',help='read the recorded decision card; no new prediction or admission')
    explain.add_argument('decision_id');explain.add_argument('--text',action='store_true',help='concise Russian output')
    reserve=sub.add_parser('reserve');reserve.add_argument('role',choices=['CALIBRATION','HOLDOUT','MONITOR']);reserve.add_argument('match_ids',nargs='+')
    sub.add_parser('calibrate')
    validate=sub.add_parser('validate');validate.add_argument('model_id')
    backtest=sub.add_parser('backtest');backtest.add_argument('file')
    audit=sub.add_parser('audit-regressions',help='settle reported retrospective audit cases without claiming holdout evidence');audit.add_argument('file')
    research=sub.add_parser('research');research.add_argument('csv',nargs='+');research.add_argument('--output',required=True)
    diagnostic=sub.add_parser('diagnose-p0');diagnostic.add_argument('--csv',nargs='+',required=True);diagnostic.add_argument('--source-run',required=True);diagnostic.add_argument('--design',required=True);diagnostic.add_argument('--output-dir',required=True)
    odds_events=sub.add_parser('odds-events',help='list an exact prematch event for a sealed prediction')
    odds_events.add_argument('prediction_id');odds_events.add_argument('--sport',required=True)
    fetch_odds=sub.add_parser('fetch-odds',help='import fresh bookmaker 1X2 after probability seal')
    fetch_odds.add_argument('prediction_id');fetch_odds.add_argument('--sport',required=True)
    fetch_odds.add_argument('--event-id',required=True);fetch_odds.add_argument('--bookmaker',required=True)
    fetch_odds.add_argument('--region',default='eu');fetch_odds.add_argument('--output',required=True)
    fetch_odds.add_argument('--rules-confirmed',action='store_true',help='operator checked 90-minute bookmaker settlement rules')
    recovery=sub.add_parser('recover');recovery.add_argument('context_key');recovery.add_argument('validation_id');recovery.add_argument('--fix',required=True)
    comparison=sub.add_parser('compare');comparison.add_argument('old_model');comparison.add_argument('new_model');comparison.add_argument('--apply-rollback',action='store_true')
    activate=sub.add_parser('activate');activate.add_argument('model_id')
    sub.add_parser('report');sub.add_parser('accounting');sub.add_parser('verify')
    sync_parser=sub.add_parser('sync-supabase',help='explicit, verified SQLite -> private Supabase ledger mirror')
    sync_parser.add_argument('--check-local',action='store_true',help='validate source ledger without a cloud connection')
    review=sub.add_parser('postmortem');review.add_argument('decision_id');review.add_argument('file')
    execution=sub.add_parser('execution');execution.add_argument('decision_id');execution.add_argument('file')
    approval=sub.add_parser('approve-policy');approval.add_argument('--operator',required=True);approval.add_argument('--statement',required=True)
    args=parser.parse_args(argv)
    policy=Policy(**load(args.policy)) if args.policy else Policy()
    repo=None
    try:
        if args.command=='audit-regressions':
            from .retrospective import audit_cases
            out=audit_cases(load(args.file),policy)
        elif args.command=='diagnose-p0':
            from .diagnostics import diagnostics
            reports=diagnostics(args.csv,args.source_run,args.design,args.output_dir)
            out={'status':'EXPLORATORY','monetary_permission':False,'reports':{k:v['run_id'] for k,v in reports.items()}}
        elif args.command=='research':
            from .research import benchmark
            r=benchmark(args.csv,args.output)
            out={k:r[k] for k in ('run_id','status','monetary_permission','split_counts','selected','temperature')}
            out['report']=str(Path(args.output).resolve())
        elif args.command=='fixture':
            root=Path(args.directory);root.mkdir(parents=True,exist_ok=True);case=example()
            for key in ('sports','markets','quotes','recheck','result'):(root/(key+'.json')).write_text(json.dumps(case[key],ensure_ascii=False,indent=2),encoding='utf-8')
            out={'directory':str(root.resolve()),'synthetic':True,'note':'quotes are timestamped one minute ahead; refresh at observation time for capture/decide'}
        elif args.command=='demo':
            import tempfile
            with tempfile.TemporaryDirectory() as temp:
                repo=Repository(Path(temp)/'demo.sqlite');case=example();clock=[time(case['sports']['as_of'])]
                service=Service(repo,policy,lambda:clock[0]);clock[0]+=__import__('datetime').timedelta(minutes=1)
                pred=service.capture(case['sports'],case['markets']);clock[0]=time(case['decision_at'])
                dec=service.decide(pred['id'],case['quotes'],case['recheck'],{'bankroll':1000.,'peak':1000.},case['decision_at'])
                replay=service.replay(dec['id']);clock[0]=time(case['result']['received_at']);service.result(case['result'])
                out={'version':VERSION,'synthetic':True,'prediction_id':pred['id'],'decision_id':dec['id'],'decision':dec['decision'],'verdict':dec['verdict'],'class':dec['class'],
                     'reasons':dec['limiting_factors'],'markets_evaluated':len(dec['candidates']),'replay_matches':replay['matches'],
                     'feedback_rows':len(service.report()['performance']),'integrity':repo.verify(),'monetary_stake':dec['risk']['stake'],
                     'decision_card':dec['decision_card']}
                repo.close();repo=None
        elif args.command=='explain':
            # Open in read-only mode: explaining an absent ledger must not create
            # it, migrate its schema, or rewrite an archived decision.
            from .decision_card import render_card
            database=Path(args.db).resolve()
            if not database.is_file():raise ValueError('ledger does not exist')
            connection=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)
            try:
                row=connection.execute('SELECT payload FROM decisions WHERE id=?',(args.decision_id,)).fetchone()
                if row is None:raise ValueError('decision not found')
                recorded=json.loads(row[0])
            finally:connection.close()
            if 'decision_card' not in recorded:raise ValueError('archived decision has no card; use its original code for replay, do not reinterpret it')
            out=recorded['decision_card']
            if args.text:
                print(render_card(out));return 0
        elif args.command=='sync-supabase':
            from .cloud_sync import check_local,sync
            out=check_local(args.db) if args.check_local else sync(args.db)
        else:
            path=Path(args.db);path.parent.mkdir(parents=True,exist_ok=True);repo=Repository(path);service=Service(repo,policy);now=service.now()
            cmd=args.command
            if cmd in ('odds-events','fetch-odds'):
                from .odds_provider import events,event_candidates,event_odds,quotes_from_event,require_prematch_seal
                prediction=repo.get('predictions',args.prediction_id)
                require_prematch_seal(prediction,service.now())
                if cmd=='odds-events':
                    data=events(args.sport)
                    out=event_candidates(data,prediction,args.sport,service.now())
                else:
                    if not args.rules_confirmed:raise ValueError('confirm 90-minute bookmaker rules before fetching; PASS')
                    if not any(c['market']['kind']=='1X2' for c in prediction['candidates']):raise ValueError('1X2 was not in the sealed market pool; PASS')
                    if Path(args.output).exists() or Path(args.output+'.receipt.json').exists():raise ValueError('odds output already exists')
                    matched=event_candidates(events(args.sport),prediction,args.sport,service.now())
                    if matched['event_id']!=args.event_id:raise ValueError('selected event id differs from exact fixture; PASS')
                    response=event_odds(args.sport,args.event_id,args.region)
                    payload=quotes_from_event(response,prediction,args.sport,args.event_id,args.bookmaker,service.now(),
                                              rules_confirmed=True,max_age_seconds=policy.quote_max_age_seconds)
                    out=write_quotes(args.output,payload)
            elif cmd=='work':
                from .worker import process_inbox
                import time as timer
                while True:
                    out=process_inbox(service,args.directory)
                    if not args.watch:break
                    print(json.dumps(out,ensure_ascii=False),flush=True)
                    timer.sleep(5)
            elif cmd=='capture':out=service.capture(load(args.sports),load(args.markets) if args.markets else DEFAULT_POOL,args.calibrator,parent=args.parent,reason=args.reason)
            elif cmd=='decide':out=service.decide(args.prediction_id,load(args.quotes),load(args.recheck),{'bankroll':args.bankroll,'peak':args.peak},now)
            elif cmd=='result':out=service.result(load(args.file))
            elif cmd=='closing':out=service.closing(args.match_id,load(args.file))
            elif cmd=='replay':out=service.replay(args.decision_id)
            elif cmd=='reserve':service.reserve(args.match_ids,args.role,now);out={'reserved':args.match_ids,'role':args.role}
            elif cmd=='calibrate':out=service.calibrate(now)
            elif cmd=='validate':out=service.validate(args.model_id,now)
            elif cmd=='backtest':
                from .backtesting import walk_forward
                out=walk_forward(load(args.file),policy)
            elif cmd=='recover':out=service.recover(args.context_key,args.fix,args.validation_id,now)
            elif cmd=='compare':
                from .feedback import compare_versions
                rows=service._records();out=service.compare_and_rollback(args.old_model,args.new_model,now) if args.apply_rollback else compare_versions([r for r in rows if r['model_id']==args.old_model],[r for r in rows if r['model_id']==args.new_model],policy)
            elif cmd=='activate':out=service.activate(args.model_id,now)
            elif cmd=='report':out=service.report()
            elif cmd=='accounting':out=service.accounting()
            elif cmd=='verify':out={'integrity':repo.verify()}
            elif cmd=='postmortem':out=service.postmortem(args.decision_id,load(args.file),now)
            elif cmd=='execution':out=service.execution(args.decision_id,load(args.file),now)
            elif cmd=='approve-policy':out=service.approve_policy(args.operator,args.statement,now)
        if args.command in ('decide','demo') and args.text:
            from .decision_card import render_card
            print(render_card(out['decision_card']))
        else:print(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False))
        return 0
    except (ValueError,KeyError,TypeError,OSError,sqlite3.Error,json.JSONDecodeError) as exc:
        print(json.dumps({'status':'ERROR','decision':'PASS','error':str(exc)},ensure_ascii=False),file=sys.stderr);return 2
    finally:
        if repo:repo.close()
