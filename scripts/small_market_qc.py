"""Offline QC only: no provider request, source certification, fit or ledger write."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.small_observation_v2 import audit_dataset, METRICS, PERIODS, stamp


def readiness_without_archive(evaluated_at):
    return {'schema':'small-market-data-readiness-v2',
            'evaluated_at':stamp(evaluated_at).isoformat(),
            'status':'INSUFFICIENT_REAL_DATA','registered_leagues':[],
            'source_attested':False,'archive_audited':False,
            'markets':[{'metric':metric,'period':period,
                        'eligible_denominator':None,'verified_coverage':None,
                        'TRAIN':0,'CALIBRATION':0,'HOLDOUT':0,
                        'probability':None,'ev':None,'fit_allowed':False,
                        'blockers':['LICENSED_FULL_LEAGUE_ARCHIVE_NOT_SUPPLIED',
                                    'RAW_RECEIPTS_NOT_BOUND','SETTLEMENT_NOT_ATTESTED',
                                    'NO_INDEPENDENT_HOLDOUT']}
                       for metric in METRICS for period in PERIODS],
            'scores':{'brier':None,'log_loss':None,'ece':None,'clv':None},
            'monetary_permission':False,
            'next_action':'Supply a licensed league manifest and immutable source archive; do not query suspended providers.'}


def strict_json(path):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('DUPLICATE_JSON_KEY')
            result[key]=value
        return result
    def constant(value):raise ValueError('NONFINITE_JSON_NUMBER')
    return json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=pairs,parse_constant=constant)


def main(argv=None):
    parser=argparse.ArgumentParser(description='SEFIROT offline small-market coverage (research only)')
    parser.add_argument('--input',type=Path,help='Normalized archive batch, never a remote URL')
    parser.add_argument('--as-of',required=True,help='Timezone-aware information cutoff')
    parser.add_argument('--output',type=Path,help='New report file; overwrite rejected')
    args=parser.parse_args(argv)
    try:
        report=(audit_dataset(strict_json(args.input),args.as_of) if args.input
                else readiness_without_archive(args.as_of))
        rendered=json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n'
        if args.output:
            # Operator controls path. Exclusive creation preserves previous reports.
            with args.output.open('x',encoding='utf-8') as handle:handle.write(rendered)
        else:
            sys.stdout.reconfigure(encoding='utf-8',errors='strict')
            print(rendered,end='')
        return 0
    except (ValueError,OSError) as error:
        print('QC_INPUT_REJECTED: '+str(error),file=sys.stderr)
        return 2


if __name__=='__main__':raise SystemExit(main())
