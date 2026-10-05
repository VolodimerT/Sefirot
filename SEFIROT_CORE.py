"""Simple Windows/Linux entry point. Research only, no wager execution."""
import argparse
# DEPRECATED: use sefirot.py. Planned removal: CORE 3.0, not before 2027-01-01.
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))

def _legacy_main(argv=None):
    from sefirot_core.system import analyze
    from sefirot_core.storage import ResearchStore
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
def main(argv=None):
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')
    arguments=list(sys.argv[1:] if argv is None else argv)
    print("DEPRECATED wrapper: use sefirot.py; --legacy selects the historical prototype only.",file=sys.stderr)
    if arguments[:1]==['--legacy']:
        return _legacy_main(arguments[1:])
    from sefirot.cli import main as canonical_main
    return canonical_main(arguments)


if __name__=='__main__':
    raise SystemExit(main())
