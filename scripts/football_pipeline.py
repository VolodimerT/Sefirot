"""Explicit offline import/coverage/inputs and bounded daily collection entrypoint."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from sefirot.contracts import canonical
from sefirot.repository import Repository
from sefirot.provider_transport import strict_json_payload
from research.football_pipeline import (ingest,ingest_probe,league_view,model_inputs,
                                       collect_day,calibration_report,MAX_BYTES,sync_archive)
from research.football_pipeline import source_only
from scripts.chat_store import DurableStoreError


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-db',required=True,type=Path,help='Dedicated private source Repository, never original prediction DB')
    p.add_argument('--output',required=True,type=Path)
    sub=p.add_subparsers(dest='action',required=True)
    sub.add_parser('sync-archive')
    imp=sub.add_parser('import');imp.add_argument('packets',nargs='+',type=Path)
    probe=sub.add_parser('import-probes');probe.add_argument('file',type=Path)
    for action in ('coverage','daily'):
        s=sub.add_parser(action);s.add_argument('--league',type=int,default=39);s.add_argument('--season',type=int,default=2026)
        if action=='daily':s.add_argument('--execute-permitted-window',action='store_true')
    s=sub.add_parser('inputs');s.add_argument('--fixture',required=True,type=int)
    s.add_argument('--profile',required=True,choices=('MEN','WOMEN','RESERVE','LOWER'))
    s.add_argument('--source-reliability',required=True,type=float)
    s=sub.add_parser('calibration');s.add_argument('--prediction-db',required=True,type=Path)
    a=p.parse_args(argv)
    repo=None
    try:
        # Reports must not clobber source stores or originals; check before any I/O.
        if os.path.lexists(a.output):raise ValueError('OUTPUT_ALREADY_EXISTS')
        if a.output.resolve()==a.source_db.resolve():raise ValueError('OUTPUT_CONFLICTS_SOURCE_DB')
        if a.action=='calibration' and a.source_db.resolve()==a.prediction_db.resolve():
            raise ValueError('DEDICATED_SOURCE_DB_REQUIRED')
        read_only=a.action in ('coverage','inputs','calibration') or a.action=='daily' and not a.execute_permitted_window
        if read_only and not a.source_db.is_file():raise ValueError('SOURCE_DB_REQUIRED')
        if not read_only:
            if a.source_db.exists():
                prior=Repository(a.source_db,read_only=True)
                try:source_only(prior)
                finally:prior.close()
            a.source_db.parent.mkdir(parents=True,exist_ok=True)
            if not a.source_db.exists():
                fd=os.open(a.source_db,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        repo=Repository(a.source_db,read_only=read_only)
        if a.action=='import':
            out={'imports':[]}
            for path in a.packets:
                with path.open('rb') as f:raw=f.read(MAX_BYTES+1)
                out['imports'].append(ingest(repo,raw))
        elif a.action=='import-probes':
            with a.file.open('rb') as f:raw=f.read(8_000_001)
            if len(raw)>8_000_000:raise ValueError('IMPORT_BYTES_LIMIT')
            rows=strict_json_payload(raw)
            if not isinstance(rows,list) or len(rows)>100:raise ValueError('PROBE_LIST_REQUIRED')
            out={'imports':[]}
            for row in rows:
                out['imports']+=ingest_probe(repo,row['response'],origin='CHAT_JOB:'+row['source_job_id'])
        elif a.action=='sync-archive':out=sync_archive(repo)
        elif a.action=='coverage':out=league_view(repo,a.league,a.season)
        elif a.action=='daily':out=collect_day(repo,a.league,a.season,execute=a.execute_permitted_window)
        elif a.action=='inputs':out=model_inputs(repo,a.fixture,profile=a.profile,source_reliability=a.source_reliability)
        else:
            with_repo=Repository(a.prediction_db,read_only=True)
            try:out=calibration_report(repo,with_repo)
            finally:with_repo.close()
        fd=os.open(a.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(canonical(out)+'\n')
        print(json.dumps({'status':'RESEARCH_ONLY','action':a.action,'provider_requests':0 if a.action!='daily' or not a.execute_permitted_window else 'SEE_GATEWAY_RECEIPTS','private_archive_reads':a.action=='sync-archive','monetary_permission':False}))
        return 0
    except (ValueError,OSError,KeyError,TypeError,AttributeError,DurableStoreError):
        print('PIPELINE_STOPPED: SOURCE_STORAGE_OR_VALIDATION_GATE',file=sys.stderr);return 2
    finally:
        if repo is not None:repo.close()


if __name__=='__main__':raise SystemExit(main())
