"""Operator-invoked answer check; existing local ledger opened mode=ro only."""
from pathlib import Path
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from sefirot.repository import Repository
from sefirot.contracts import time
from research.chat_answer_contract import strict_json,validate_answer,render_answer


def main():
    sys.stdout.reconfigure(encoding='utf-8',errors='strict')
    p=argparse.ArgumentParser(description='Verify a structured chat answer; no CORE run or write')
    p.add_argument('--answer',type=Path,required=True)
    p.add_argument('--fixture',action='append',required=True)
    p.add_argument('--db',type=Path)
    p.add_argument('--at',help='Operator evaluation clock for archived/reproducible review')
    p.add_argument('--archive',action='store_true')
    args=p.parse_args();repo=None
    try:
        if args.db:
            if not args.db.is_file() or args.db.is_symlink():raise ValueError('ORIGINAL_LEDGER_NOT_AVAILABLE')
            repo=Repository(str(args.db),read_only=True)
        with args.answer.open('rb') as stream: raw=stream.read(65537)
        if len(raw)>65536:raise ValueError('ANSWER_TOO_LARGE')
        answer=validate_answer(strict_json(raw),expected_fixtures=args.fixture,
            at=time(args.at) if args.at else datetime.now(timezone.utc),repo=repo,archive=args.archive)
        print(json.dumps({'valid':True,'answer':answer.to_dict(),'summary':render_answer(answer)},
                         ensure_ascii=False,allow_nan=False))
        return 0
    except (ValueError,TypeError,KeyError,OSError,sqlite3.Error) as exc:
        print(json.dumps({'valid':False,'error':str(exc)},ensure_ascii=False,allow_nan=False))
        return 2
    finally:
        if repo:repo.close()


if __name__=='__main__':raise SystemExit(main())
