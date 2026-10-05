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

def write_new_json(path, value):
    destination=Path(path);destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open('x',encoding='utf-8') as file:
        json.dump(value,file,ensure_ascii=False,indent=2,allow_nan=False);file.write('\n')
    return {'output':str(destination.resolve()),'hash':value.get('hash'),
            'candidates':len(value.get('candidates',[])),'monetary_permission':False}

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
    capture=sub.add_parser('capture',help='seal sports-only probability before reading any prices');capture.add_argument('sports');capture.add_argument('--markets');capture.add_argument('--calibrator');capture.add_argument('--parent');capture.add_argument('--reason');capture.add_argument('--goal-model',help='frozen sports-only SoS/count artifact')
    decision=sub.add_parser('decide');decision.add_argument('prediction_id');decision.add_argument('quotes');decision.add_argument('recheck');decision.add_argument('--bankroll',type=float,default=1000);decision.add_argument('--peak',type=float,default=1000)
    decision.add_argument('--text',action='store_true',help='print the decision card; save the full decision in the ledger')
    result=sub.add_parser('result');result.add_argument('file')
    closing=sub.add_parser('closing');closing.add_argument('match_id');closing.add_argument('file')
    replay=sub.add_parser('replay');replay.add_argument('decision_id')
    explain=sub.add_parser('explain',help='read the recorded decision card; no new prediction or admission')
    explain.add_argument('decision_id');explain.add_argument('--text',action='store_true',help='concise Russian output')
    readiness=sub.add_parser('readiness',help='check existing model/data blockers before requesting prices; no new seal')
    readiness.add_argument('prediction_id');readiness.add_argument('--text',action='store_true',help='concise Russian output')
    session=sub.add_parser('session',help='review existing seals as one price-blind session; no new forecasts')
    session.add_argument('--prediction-id',action='append');session.add_argument('--limit',type=int,default=200)
    session.add_argument('--text',action='store_true');session.add_argument('--output')
    tickets=sub.add_parser('ticket-audit',help='audit reported singles, repeated event exposure and recorded decision mismatches')
    tickets.add_argument('file');tickets.add_argument('--link-ledger',action='store_true');tickets.add_argument('--output')
    grid=sub.add_parser('market-grid',help='freeze fifty price-blind research contracts from an existing seal')
    grid.add_argument('prediction_id');grid.add_argument('--output',required=True)
    compare_grid=sub.add_parser('compare-grid',help='compare fresh API quotes with a frozen research grid; no monetary permission')
    compare_grid.add_argument('grid');compare_grid.add_argument('quotes');compare_grid.add_argument('--output',required=True)
    robustness=sub.add_parser('goal-robustness',help='freeze raw history sensitivity from an existing market grid; no model or admission changes')
    robustness.add_argument('grid');robustness.add_argument('--output',required=True);robustness.add_argument('--text',action='store_true')
    compare_robustness=sub.add_parser('compare-robustness',help='compare fresh API quotes with frozen history perturbations; research only')
    compare_robustness.add_argument('report');compare_robustness.add_argument('quotes');compare_robustness.add_argument('--output',required=True)
    builder=sub.add_parser('builder-grid',help='freeze fourteen joint goal builders before prices; research only')
    builder.add_argument('grid');builder.add_argument('--output',required=True)
    builder_compare=sub.add_parser('compare-builder',help='compare API-priced singles with frozen builders; combined price remains missing')
    builder_compare.add_argument('report');builder_compare.add_argument('quotes');builder_compare.add_argument('--output',required=True)
    small=sub.add_parser('small-market-review',help='check full-time API statistics and disjoint long/recent baselines; no probability model')
    small.add_argument('file');small.add_argument('--output',required=True)
    reserve=sub.add_parser('reserve');reserve.add_argument('role',choices=['CALIBRATION','HOLDOUT','MONITOR']);reserve.add_argument('match_ids',nargs='+')
    forward=sub.add_parser('forward-plan',help='reserve every future API fixture in declared leagues before forecasts')
    forward.add_argument('packet');forward.add_argument('--league-profile',action='append',required=True,help='API_LEAGUE_ID=MEN/WOMEN/RESERVE/LOWER; repeat')
    forward.add_argument('--role',choices=['CALIBRATION','HOLDOUT'],default='CALIBRATION')
    forward.add_argument('--calibrator');forward.add_argument('--source-reliability',type=float,required=True)
    forward.add_argument('--output',required=True)
    forward_capture=sub.add_parser('forward-capture',help='attempt every planned fixture from observed API archive; research only')
    forward_capture.add_argument('plan_id');forward_capture.add_argument('--directory',default='data/sports-archive');forward_capture.add_argument('--output',required=True)
    forward_settle=sub.add_parser('forward-settle',help='settle frozen cohort from exact API regulation FT results')
    forward_settle.add_argument('plan_id');forward_settle.add_argument('packet');forward_settle.add_argument('--output',required=True)
    forward_status=sub.add_parser('forward-status',help='read cohort coverage, invalid seals and missing results without certifying it')
    forward_status.add_argument('plan_id');forward_status.add_argument('--output')
    scorecard=sub.add_parser('forward-scorecard',help='read all planned fixtures and frozen forecast quality; no refit or certification')
    scorecard.add_argument('plan_id');scorecard.add_argument('--as-of');scorecard.add_argument('--output');scorecard.add_argument('--text',action='store_true')
    sub.add_parser('calibrate')
    validate=sub.add_parser('validate');validate.add_argument('model_id')
    backtest=sub.add_parser('backtest');backtest.add_argument('file')
    audit=sub.add_parser('audit-regressions',help='settle reported retrospective audit cases without claiming holdout evidence');audit.add_argument('file')
    research=sub.add_parser('research');research.add_argument('csv',nargs='+');research.add_argument('--output',required=True)
    goal_fit=sub.add_parser('fit-goal-model',help='fit profile priors and four-count bins without prices or monetary permission')
    goal_fit.add_argument('training_sports');goal_fit.add_argument('--samples',required=True);goal_fit.add_argument('--output',required=True)
    upgrade=sub.add_parser('p0-upgrade-benchmark',help='compare frozen baseline and SoS/count model on a declared chronological split')
    upgrade.add_argument('--csv',nargs='+',required=True);upgrade.add_argument('--design',required=True);upgrade.add_argument('--output-dir',required=True)
    diagnostic=sub.add_parser('diagnose-p0');diagnostic.add_argument('--csv',nargs='+',required=True);diagnostic.add_argument('--source-run',required=True);diagnostic.add_argument('--design',required=True);diagnostic.add_argument('--output-dir',required=True)
    stake_snapshot=sub.add_parser('stake-snapshot',help='read raw Stake big/small markets after a prematch probability seal; research only')
    stake_snapshot.add_argument('prediction_id');stake_snapshot.add_argument('--sport',default='soccer')
    stake_snapshot.add_argument('--first',type=int,default=200);stake_snapshot.add_argument('--output',required=True)
    stake_snapshot.add_argument('--normalized-output')
    odds_events=sub.add_parser('odds-events',help='list an exact prematch event for a sealed prediction')
    odds_events.add_argument('prediction_id');odds_events.add_argument('--sport',required=True)
    fetch_odds=sub.add_parser('fetch-odds',help='import fresh bookmaker main markets after probability seal')
    fetch_odds.add_argument('prediction_id');fetch_odds.add_argument('--sport',required=True)
    fetch_odds.add_argument('--event-id',required=True);fetch_odds.add_argument('--bookmaker',required=True)
    fetch_odds.add_argument('--region',default='eu');fetch_odds.add_argument('--output',required=True)
    fetch_odds.add_argument('--rules-confirmed',action='store_true',help='operator checked 90-minute bookmaker settlement rules')
    market_scope=fetch_odds.add_mutually_exclusive_group()
    market_scope.add_argument('--main-markets',action='store_true',help='request supported families in the sealed pool; quota depends on returned markets')
    market_scope.add_argument('--grid',help='frozen market-grid JSON; enables alternate main lines for research only')
    health=sub.add_parser('api-health',help='check both API credentials and quotas without fetching prices')
    health.add_argument('--output',help='save a credential-free connection report')
    football=sub.add_parser('football-fetch',help='save an API-Football sports response and receipt, without odds')
    football.add_argument('--endpoint',required=True,choices=['leagues','teams','fixtures','fixtures/lineups','fixtures/statistics','injuries'])
    football.add_argument('--param',action='append',default=[],help='provider filter NAME=VALUE; repeat as needed')
    football.add_argument('--output',required=True)
    normalize=sub.add_parser('football-normalize',help='convert collected API fixtures to sports input; missing facts stay missing')
    normalize.add_argument('target');normalize.add_argument('--fixture-id',required=True,type=int)
    normalize.add_argument('--history',nargs='*',default=[])
    normalize.add_argument('--profile',required=True,choices=['MEN','WOMEN','RESERVE','LOWER'])
    normalize.add_argument('--source-reliability',required=True,type=float,help='explicit operator assertion, not provider certification')
    normalize.add_argument('--output',required=True)
    archive=sub.add_parser('football-archive',help='archive already received API fixture packets; no HTTP requests')
    archive.add_argument('files',nargs='+');archive.add_argument('--directory',default='data/sports-archive')
    archive.add_argument('--output')
    archived=sub.add_parser('football-from-archive',help='deduplicate observed FT history and explain sports data gaps')
    archived.add_argument('--fixture-id',required=True,type=int);archived.add_argument('--directory',default='data/sports-archive')
    archived.add_argument('--profile',required=True,choices=['MEN','WOMEN','RESERVE','LOWER'])
    archived.add_argument('--source-reliability',required=True,type=float);archived.add_argument('--as-of')
    archived.add_argument('--output',required=True)
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
    repo=None
    try:
        policy=Policy(**load(args.policy)) if args.policy else Policy()
        if args.command=='stake-snapshot':
            from .stake_provider import sports_events,exact_event,fixture_markets,research_snapshot
            from .stake_mapper import normalize_snapshot
            database=Path(args.db).resolve()
            if not database.is_file():raise ValueError('ledger does not exist')
            destination=Path(args.output)
            normalized_destination=Path(args.normalized_output or (args.output+'.normalized.json'))
            if destination.exists() or normalized_destination.exists():raise ValueError('Stake output already exists')
            repo=Repository(database,read_only=True)
            if not repo.verify():raise ValueError('journal integrity failed')
            service=Service(repo,policy);prediction=repo.get('predictions',args.prediction_id)
            received=service.now()
            packet=sports_events(first=args.first,sport_slug=args.sport,match_type='active')
            event=exact_event(packet['events'],prediction,received)
            market_packet=fixture_markets(event['slug'])
            snapshot=research_snapshot(event,prediction,received,market_packet['markets'],
                                       [packet['receipt']]+market_packet['receipts'])
            normalized=normalize_snapshot(snapshot)
            write_new_json(destination,snapshot);write_new_json(normalized_destination,normalized)
            out={'status':'RESEARCH_ONLY','provider':'STAKE_GRAPHQL_EXPERIMENTAL',
                 'event_id':snapshot['stake_event_id'],'market_count':snapshot['market_count'],
                 'main_quote_count':normalized['main_quote_count'],
                 'small_quote_count':normalized['small_quote_count'],
                 'snapshot':str(destination.resolve()),
                 'normalized':str(normalized_destination.resolve()),
                 'monetary_permission':False,'execution_enabled':False}
        elif args.command=='api-health':
            from .api_health import check
            out=check()
            if args.output:
                path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
                with path.open('x',encoding='utf-8') as file:json.dump(out,file,ensure_ascii=False,indent=2,allow_nan=False)
                out['report']=str(path.resolve())
        elif args.command=='football-archive':
            from .sports_archive import archive_packets
            if args.output and Path(args.output).exists():raise ValueError('archive report already exists')
            out=archive_packets([load(p) for p in args.files],args.directory,datetime.now(timezone.utc).isoformat())
            if args.output:write_new_json(args.output,out)
        elif args.command=='football-from-archive':
            from .sports_archive import export_sports
            at=args.as_of or datetime.now(timezone.utc).isoformat()
            if time(at)>datetime.now(timezone.utc):raise ValueError('archive cutoff cannot be in the future')
            outputs=[Path(args.output),Path(args.output+'.receipt.json'),Path(args.output+'.coverage.json')]
            if any(p.exists() for p in outputs):raise ValueError('archive export output already exists')
            imported=export_sports(args.directory,args.fixture_id,at,profile=args.profile,
                                   source_reliability=args.source_reliability,policy=policy)
            for destination,field in zip(outputs,('sports','receipt','coverage')):write_new_json(destination,imported[field])
            out={'status':imported['coverage']['status'],'sports_file':str(outputs[0].resolve()),
                 'receipt_file':str(outputs[1].resolve()),'coverage_file':str(outputs[2].resolve()),
                 'history_rows':imported['coverage']['eligible_history_rows'],'teams':imported['coverage']['teams'],
                 'blockers':imported['coverage']['blockers'],'monetary_permission':False}
        elif args.command=='football-fetch':
            from .football_provider import get
            params={}
            for entry in args.param:
                if '=' not in entry:raise ValueError('sports filter must be NAME=VALUE')
                key,value=entry.split('=',1)
                if key in params:raise ValueError('duplicate sports filter')
                params[key]=value
            path=Path(args.output)
            if path.exists():raise ValueError('sports output already exists')
            packet=get(args.endpoint,params)
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('x',encoding='utf-8') as file:json.dump(packet,file,ensure_ascii=False,indent=2,allow_nan=False)
            out={'status':'SPORTS_API_RECEIVED','results':packet['data']['results'],'receipt':packet['receipt'],'file':str(path.resolve()),'execution_enabled':False}
        elif args.command=='football-normalize':
            from .football_provider import normalize_sports
            packet=normalize_sports(load(args.target),args.fixture_id,[load(p) for p in args.history],
                                    profile=args.profile,source_reliability=args.source_reliability)
            path=Path(args.output);receipt=Path(str(path)+'.receipt.json')
            if path.exists() or receipt.exists():raise ValueError('sports output already exists')
            path.parent.mkdir(parents=True,exist_ok=True)
            for target,value in ((path,packet['sports']),(receipt,packet['receipt'])):
                with target.open('x',encoding='utf-8') as file:json.dump(value,file,ensure_ascii=False,indent=2,allow_nan=False)
            out={'status':packet['receipt']['status'],'history_rows':len(packet['sports']['history']),
                 'missing_facts':packet['receipt']['missing_facts'],'sports_file':str(path.resolve()),'receipt_file':str(receipt.resolve())}
        elif args.command=='fit-goal-model':
            from .goal_model import fit_goal_model
            from .engine import model_code_hash
            out=fit_goal_model(load(args.training_sports),load(args.samples),policy,datetime.now(timezone.utc).isoformat(),model_code_hash())
            path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('x',encoding='utf-8') as file:json.dump(out,file,ensure_ascii=False,indent=2,allow_nan=False)
            out={'hash':out['hash'],'status':out['status'],'monetary_permission':False,'report':str(path.resolve())}
        elif args.command=='p0-upgrade-benchmark':
            from .goal_research import benchmark_upgrade
            report=benchmark_upgrade(args.csv,load(args.design),args.output_dir,policy)
            out={k:report[k] for k in ('run_id','status','can_certify_release','monetary_permission','split_counts')}
            out['comparison']=report['comparison'];out['report_dir']=str(Path(args.output_dir).resolve())
        elif args.command=='audit-regressions':
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
        elif args.command=='small-market-review':
            from .small_market import review_small_market
            out=write_new_json(args.output,review_small_market(load(args.file),datetime.now(timezone.utc).isoformat()))
        elif args.command in ('builder-grid','compare-builder'):
            from .builder_research import create_builder_grid,compare_builder_singles
            database=Path(args.db).resolve()
            if not database.is_file():raise ValueError('ledger does not exist')
            if Path(args.output).exists():raise ValueError('research output already exists')
            repo=Repository(database,read_only=True);service=Service(repo,policy)
            if not repo.verify():raise ValueError('journal integrity failed')
            if args.command=='builder-grid':
                grid=load(args.grid);prediction=repo.get('predictions',grid['prediction_id'])
                out=write_new_json(args.output,create_builder_grid(grid,prediction,policy,service.now()))
            else:
                report=load(args.report);prediction=repo.get('predictions',report['prediction_id'])
                out=write_new_json(args.output,compare_builder_singles(report,prediction,load(args.quotes),policy,service.now(),load(args.quotes+'.receipt.json')))
        elif args.command in ('goal-robustness','compare-robustness'):
            from .goal_robustness import create_robustness,compare_robustness as compare_history,render_robustness
            database=Path(args.db).resolve()
            if not database.is_file():raise ValueError('ledger does not exist')
            if Path(args.output).exists():raise ValueError('research output already exists')
            repo=Repository(database,read_only=True);service=Service(repo,policy)
            if not repo.verify():raise ValueError('journal integrity failed')
            if args.command=='goal-robustness':
                grid=load(args.grid);prediction=repo.get('predictions',grid['prediction_id'])
                report=create_robustness(grid,prediction,policy,service.now())
                out=write_new_json(args.output,report)
                if args.text:
                    print(render_robustness(report));return 0
            else:
                report=load(args.report);prediction=repo.get('predictions',report['prediction_id'])
                out=write_new_json(args.output,compare_history(report,prediction,load(args.quotes),policy,service.now(),load(args.quotes+'.receipt.json')))
        elif args.command in ('market-grid','compare-grid'):
            from .market_grid import create_grid,compare_grid as compare_frozen_grid
            database=Path(args.db).resolve()
            if not database.is_file():raise ValueError('ledger does not exist')
            if Path(args.output).exists():raise ValueError('research output already exists')
            repo=Repository(database,read_only=True);service=Service(repo,policy)
            if not repo.verify():raise ValueError('journal integrity failed')
            if args.command=='market-grid':
                prediction=repo.get('predictions',args.prediction_id)
                out=write_new_json(args.output,create_grid(prediction,policy,service.now()))
            else:
                grid=load(args.grid);prediction=repo.get('predictions',grid['prediction_id'])
                receipt=load(args.quotes+'.receipt.json')
                out=write_new_json(args.output,compare_frozen_grid(grid,prediction,load(args.quotes),policy,service.now(),receipt))
        elif args.command=='session':
            from .session import inspect_session,render_session
            database=Path(args.db).resolve()
            if not database.is_file():raise ValueError('ledger does not exist')
            if args.output and Path(args.output).exists():raise ValueError('session output already exists')
            repo=Repository(database,read_only=True);service=Service(repo,policy)
            out=inspect_session(service,service.now(),args.prediction_id,args.limit)
            if args.output:write_new_json(args.output,out)
            if args.text:
                print(render_session(out));return 0
        elif args.command=='ticket-audit':
            from .ticket_audit import audit_tickets
            if args.output and Path(args.output).exists():raise ValueError('ticket audit output already exists')
            service=None
            if args.link_ledger:
                database=Path(args.db).resolve()
                if not database.is_file():raise ValueError('ledger does not exist')
                repo=Repository(database,read_only=True);service=Service(repo,policy)
            out=audit_tickets(load(args.file),service=service,policy=policy)
            if args.output:write_new_json(args.output,out)
        elif args.command=='forward-scorecard':
            from .forward_scorecard import create_scorecard,render_scorecard
            database=Path(args.db).resolve()
            if not database.is_file():raise ValueError('ledger does not exist')
            if args.output and Path(args.output).exists():raise ValueError('forward scorecard output already exists')
            repo=Repository(database,read_only=True);service=Service(repo,policy)
            out=create_scorecard(service,args.plan_id,args.as_of or service.now())
            if args.output:write_new_json(args.output,out)
            if args.text:
                print(render_scorecard(out));return 0
        elif args.command=='forward-status':
            from .forward import inspect_plan
            database=Path(args.db).resolve()
            if not database.is_file():raise ValueError('ledger does not exist')
            if args.output and Path(args.output).exists():raise ValueError('forward output already exists')
            repo=Repository(database,read_only=True);service=Service(repo,policy)
            out=inspect_plan(service,args.plan_id)
            if args.output:write_new_json(args.output,out)
        elif args.command=='readiness':
            from .readiness import inspect_readiness,render_readiness
            database=Path(args.db).resolve()
            if not database.is_file():raise ValueError('ledger does not exist')
            repo=Repository(database,read_only=True);service=Service(repo,policy)
            out=inspect_readiness(service,args.prediction_id,service.now())
            if args.text:
                print(render_readiness(out));return 0
        elif args.command=='sync-supabase':
            from .cloud_sync import check_local,sync
            out=check_local(args.db) if args.check_local else sync(args.db)
        else:
            path=Path(args.db);path.parent.mkdir(parents=True,exist_ok=True);repo=Repository(path);service=Service(repo,policy);now=service.now()
            cmd=args.command
            if cmd in ('forward-plan','forward-capture','forward-settle'):
                from .forward import create_plan,capture_plan,settle_plan
                if Path(args.output).exists():raise ValueError('forward output already exists')
                if cmd=='forward-plan':
                    profiles={}
                    for entry in args.league_profile:
                        key,value=entry.split('=',1);key=int(key)
                        if key in profiles:raise ValueError('duplicate API league profile')
                        profiles[key]=value
                    out=create_plan(service,load(args.packet),profiles,role=args.role,
                                    source_reliability=args.source_reliability,calibrator_id=args.calibrator)
                elif cmd=='forward-capture':out=capture_plan(service,args.plan_id,args.directory)
                else:out=settle_plan(service,args.plan_id,load(args.packet))
                write_new_json(args.output,out)
            elif cmd in ('odds-events','fetch-odds'):
                from .odds_provider import events,event_candidates,event_odds,quotes_from_event,require_prematch_seal,keys_for_candidates
                from .identity import code_hash
                prediction=repo.get('predictions',args.prediction_id)
                if not repo.verify():raise ValueError('journal integrity failed')
                if prediction['code_hash']!=code_hash() or prediction['policy_hash']!=policy.fingerprint:
                    raise ValueError('odds import requires the original prediction build and policy')
                require_prematch_seal(prediction,service.now())
                if cmd=='odds-events':
                    data=events(args.sport)
                    out=event_candidates(data,prediction,args.sport,service.now())
                else:
                    if not args.rules_confirmed:raise ValueError('confirm 90-minute bookmaker rules before fetching; PASS')
                    grid=None;quote_prediction=prediction
                    if args.grid:
                        from .market_grid import validate_grid
                        grid=validate_grid(load(args.grid),prediction,policy,service.now())
                        quote_prediction={**prediction,'candidates':grid['candidates'],'sealed_at':grid['sealed_at']}
                        market_keys=keys_for_candidates(grid['candidates'],alternate=True)
                    elif args.main_markets:market_keys=keys_for_candidates(prediction['candidates'])
                    else:
                        if not any(c['market']['kind']=='1X2' for c in prediction['candidates']):raise ValueError('1X2 was not in the sealed market pool; PASS')
                        market_keys=('h2h',)
                    if Path(args.output).exists() or Path(args.output+'.receipt.json').exists():raise ValueError('odds output already exists')
                    matched=event_candidates(events(args.sport),prediction,args.sport,service.now())
                    if matched['event_id']!=args.event_id:raise ValueError('selected event id differs from exact fixture; PASS')
                    response=event_odds(args.sport,args.event_id,args.region,market_keys=market_keys,bookmaker_key=args.bookmaker)
                    payload=quotes_from_event(response,quote_prediction,args.sport,args.event_id,args.bookmaker,service.now(),
                                              rules_confirmed=True,max_age_seconds=policy.quote_max_age_seconds,market_keys=market_keys)
                    if grid:payload['receipt'].update(grid_hash=grid['hash'],monetary_permission=False)
                    out=write_quotes(args.output,payload)
            elif cmd=='work':
                from .worker import process_inbox
                import time as timer
                while True:
                    out=process_inbox(service,args.directory)
                    if not args.watch:break
                    print(json.dumps(out,ensure_ascii=False),flush=True)
                    timer.sleep(5)
            elif cmd=='capture':out=service.capture(load(args.sports),load(args.markets) if args.markets else DEFAULT_POOL,args.calibrator,parent=args.parent,reason=args.reason,goal_model=load(args.goal_model) if args.goal_model else None)
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
        return 2 if args.command=='api-health' and out['status']!='API_READY' else 0
    except (ValueError,KeyError,TypeError,OSError,sqlite3.Error,json.JSONDecodeError) as exc:
        print(json.dumps({'status':'ERROR','decision':'PASS','error':str(exc)},ensure_ascii=False),file=sys.stderr);return 2
    finally:
        if repo:repo.close()
