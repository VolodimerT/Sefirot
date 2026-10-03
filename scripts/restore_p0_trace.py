"""Restore the complete immutable P0 benchmark and verify its original SHA256."""
from pathlib import Path
import argparse
import gzip
import hashlib
import json

ROOT=Path(__file__).resolve().parents[1]


def restore(archive,summary):
    wrapper=json.loads(gzip.decompress(Path(archive).read_bytes()))
    if wrapper['format']!='indexed-history-v1':raise ValueError('unsupported trace format')
    ids=wrapper['history_ids'];report=wrapper['benchmark']
    if len(set(ids))!=len(ids) or any(not isinstance(mid,str) for mid in ids):raise ValueError('invalid history dictionary')
    for record in report['predictions']:
        indices=record['used_history']
        if any(type(i) is not int or not 0<=i<len(ids) for i in indices):raise ValueError('invalid history index')
        record['used_history']=[ids[i] for i in indices]
    content=(json.dumps(report,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
    expected=json.loads(Path(summary).read_text())['forecast_archive']['full_report_sha256']
    actual=hashlib.sha256(content).hexdigest()
    if actual!=expected:raise ValueError('restored report hash mismatch')
    return report,content,actual


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',default=str(ROOT/'reports/P0_UPGRADE_HOLDOUT.json.gz'))
    parser.add_argument('--summary',default=str(ROOT/'reports/P0_UPGRADE_HOLDOUT.json'))
    parser.add_argument('--output',help='optional new file; existing reports are never overwritten')
    args=parser.parse_args()
    report,content,signature=restore(args.archive,args.summary)
    if args.output:
        target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as file:file.write(content)
    print(json.dumps({'validated':True,'fixtures':len(report['predictions']),
                      'run_id':report['run_id'],'sha256':signature,'output':args.output}))


if __name__=='__main__':main()
