"""Offline V3 report runner. No credentials, providers, ledgers or CORE writes.

--input accepts {manifest, forecasts, results, as_of}; report content remains
self-attested until original receipt/ledger integration has been verified.
With no input produce an honest empty readiness/benchmark, never demo scores.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from sefirot.contracts import Policy, digest, time
from sefirot.credentials import credential_status
from sefirot.identity import model_code_hash, code_hash
from research.prediction_edge_v3.benchmark import CONTRACTS, evaluate
from research.prediction_edge_v3.models import MODELS, research_hash


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    now=datetime.now(timezone.utc).isoformat()
    if args.input:
        data=json.loads(args.input.read_text(encoding='utf-8'))
        if time(data['as_of'])>time(now):raise ValueError('evaluation cutoff in future')
        manifest=data['manifest']
        benchmark=evaluate(manifest,data['forecasts'],data['results'],as_of=data['as_of'])
    else:
        manifest={'schema':'edge-v3-manifest-v1','registered_at':now,'training_ids':[],
                  'calibration_ids':[],'viewed_test_ids':[],'members':[],
                  'models':list(MODELS),'contracts':list(CONTRACTS),'primary':'1X2:raw:log_loss',
                  'research_hash':research_hash(),'policy_hash':Policy().fingerprint}
        benchmark=evaluate(manifest,[],[],as_of=now)
        benchmark['manifest_status']='TEMPLATE_ONLY_NO_HOLDOUT_REGISTERED'
    benchmark.update(generated_at=now,core_code_hash=code_hash(),core_model_hash=model_code_hash(),research_hash=research_hash(),
                     market_comparator={'status':'NO_DATA','verified_quotes':0,'clv':None},
                     arena={'status':'NO_DATA','paired_records':0,'benefit':None})
    readiness={'schema':'edge-v3-data-readiness-v1','generated_at':now,
               'status':'INSUFFICIENT_REAL_DATA','provider_status':'NOT_PROBED',
               'credential_presence':credential_status(),'network_requests':0,
               'verified_archive_packets':0,'verified_training_matches':0,
               'externally_verified_holdout_matches':0,
               'submitted_cohort_matches':benchmark['assigned'],
               'verified_quote_partitions':0,'combined_quotes':0,
               'history_coverage':None,'missing_seasons':'UNKNOWN_NO_ARCHIVE_SUPPLIED',
               'lineup_coverage':None,'xg_coverage':None,'receipt_age':None,'achieved_calibration_bins':0,
               'receipt_authentication':'NO_ORIGINAL_ARCHIVE_OR_LEDGER_SUPPLIED',
               'historical_context':{'viewed_test_matches':380,'previous_calibration_assigned':17,'previous_calibration_scored':0,
                                     'source':'docs/FORWARD_SCORECARD.md; reports/FROZEN_EFFECTIVENESS_AUDIT_20261006.json; not a new run'},
               'blockers':['Original timestamped training archive missing','New predeclared HOLDOUT not registered',
                           'Research-to-original-ledger adapter not implemented','Verified prematch/closing/combined quotes missing'],
               'monetary_permission':False}
    args.output_dir.mkdir(parents=True,exist_ok=True)
    for name,value in [('MANIFEST',manifest),('DATA_READINESS',readiness),('BENCHMARK',benchmark)]:
        (args.output_dir/f'PREDICTION_EDGE_V3_{name}.json').write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    text=f'''# PREDICTION EDGE V3: evidence status\n\nKEEP_SHADOW / INSUFFICIENT_REAL_DATA.\n\nAssigned input fixtures: {benchmark['assigned']}; submitted forecasts: {benchmark['forecasts']}.\nExternally verified new HOLDOUT fixtures: 0. Accuracy gain: not established.\nRaw and calibrated scorecards are separate; missing values remain null.\nSynthetic unit tests are excluded from this report. Historical 380-match TEST is not reused.\nMarket edge/CLV, ARENA benefit and Builder EV: no verified data.\nResearch hash: `{research_hash()}`. CORE model hash: `{model_code_hash()}`.\n\nRun: `python scripts/prediction_edge_v3.py --output-dir reports`\nOptional self-attested diagnostics: `--input PATH`; this cannot promote models.\n'''
    (args.output_dir/'PREDICTION_EDGE_V3_BENCHMARK.md').write_text(text,encoding='utf-8')
    print(json.dumps({'status':readiness['status'],'report_status':benchmark['status'],'assigned':benchmark['assigned']}))

if __name__=='__main__':main()
