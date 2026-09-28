"""Dependency-free CLI; default workflows operate on local, user-supplied sources."""
import argparse
from datetime import datetime,timezone
from dataclasses import asdict
import json
from pathlib import Path
import sys
import sqlite3
from .contracts import Policy,VERSION,time
from .repository import Repository
from .service import Service
from .fixtures import example
from .markets import DEFAULT_POOL


def load(path):return json.loads(Path(path).read_text(encoding='utf-8'))

def main(argv=None):
    parser=argparse.ArgumentParser(description='SEFIROT CORE '+VERSION+' — prematch analysis and audit')
    parser.add_argument('--db',default='data/sefirot.sqlite')
    parser.add_argument('--policy',help='versioned experimental JSON policy')
    sub=parser.add_subparsers(dest='command',required=True)
    worker=sub.add_parser('work');worker.add_argument('directory');worker.add_argument('--watch',action='store_true')
    demo=sub.add_parser('demo',help='complete synthetic workflow in a temporary database')
    fixture=sub.add_parser('fixture',help='write synthetic JSON input files');fixture.add_argument('directory')
    capture=sub.add_parser('capture',help='seal sports-only probability before reading any prices');capture.add_argument('sports');capture.add_argument('--markets');capture.add_argument('--calibrator');capture.add_argument('--parent');capture.add_argument('--reason')
    decision=sub.add_parser('decide');decision.add_argument('prediction_id');decision.add_argument('quotes');decision.add_argument('recheck');decision.add_argument('--bankroll',type=float,default=1000);decision.add_argument('--peak',type=float,default=1000)
    result=sub.add_parser('result');result.add_argument('file')
    closing=sub.add_parser('closing');closing.add_argument('match_id');closing.add_argument('file')
    replay=sub.add_parser('replay');replay.add_argument('decision_id')
    reserve=sub.add_parser('reserve');reserve.add_argument('role',choices=['CALIBRATION','HOLDOUT','MONITOR']);reserve.add_argument('match_ids',nargs='+')
    sub.add_parser('calibrate')
    validate=sub.add_parser('validate');validate.add_argument('model_id')
    backtest=sub.add_parser('backtest');backtest.add_argument('file')
    research=sub.add_parser('research');research.add_argument('csv',nargs='+');research.add_argument('--output',required=True)
    diagnostic=sub.add_parser('diagnose-p0');diagnostic.add_argument('--csv',nargs='+',required=True);diagnostic.add_argument('--source-run',required=True);diagnostic.add_argument('--design',required=True);diagnostic.add_argument('--output-dir',required=True)
    recovery=sub.add_parser('recover');recovery.add_argument('context_key');recovery.add_argument('validation_id');recovery.add_argument('--fix',required=True)
    comparison=sub.add_parser('compare');comparison.add_argument('old_model');comparison.add_argument('new_model');comparison.add_argument('--apply-rollback',action='store_true')
    activate=sub.add_parser('activate');activate.add_argument('model_id')
    sub.add_parser('report');sub.add_parser('accounting');sub.add_parser('verify')
    review=sub.add_parser('postmortem');review.add_argument('decision_id');review.add_argument('file')
    execution=sub.add_parser('execution');execution.add_argument('decision_id');execution.add_argument('file')
    approval=sub.add_parser('approve-policy');approval.add_argument('--operator',required=True);approval.add_argument('--statement',required=True)
    args=parser.parse_args(argv)
    policy=Policy(**load(args.policy)) if args.policy else Policy()
    repo=None
    try:
        if args.command=='diagnose-p0':
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
                     'feedback_rows':len(service.report()['performance']),'integrity':repo.verify(),'monetary_stake':dec['risk']['stake']}
                repo.close();repo=None
        else:
            path=Path(args.db);path.parent.mkdir(parents=True,exist_ok=True);repo=Repository(path);service=Service(repo,policy);now=service.now()
            cmd=args.command
            if cmd=='work':
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
        print(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False));return 0
    except (ValueError,KeyError,TypeError,OSError,sqlite3.Error,json.JSONDecodeError) as exc:
        print(json.dumps({'status':'ERROR','decision':'PASS','error':str(exc)},ensure_ascii=False),file=sys.stderr);return 2
    finally:
        if repo:repo.close()
