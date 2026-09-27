"""Simple Windows/Linux entry point. Research only, no wager execution."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from sefirot_core.system import analyze
from sefirot_core.storage import ResearchStore

def main(argv=None):
    cli=argparse.ArgumentParser(description='SEFIROT CORE local prematch research')
    cli.add_argument('case',type=Path,help='JSON case with timestamps, sports evidence, history, quotes')
    cli.add_argument('--db',type=Path,help='SQLite journal (new match id required)')
    args=cli.parse_args(argv)
    event=json.loads(args.case.read_text(encoding='utf-8'))
    report=analyze(event)
    if args.db:
        args.db.parent.mkdir(parents=True,exist_ok=True)
        with ResearchStore(args.db) as store:
            store.record(event,report)
    print(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))
    return 0
if __name__=='__main__': raise SystemExit(main())
