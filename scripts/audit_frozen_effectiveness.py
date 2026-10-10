"""Recompute quality of frozen historical forecasts; no refit, API or promotion."""
from pathlib import Path
import argparse
from datetime import datetime,timezone
import hashlib
import json
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sefirot.evaluation import metrics
from sefirot.identity import code_hash,model_code_hash
from restore_p0_trace import restore


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists():parser.error('output already exists')
    archive=ROOT/'reports/P0_UPGRADE_HOLDOUT.json.gz';summary=ROOT/'reports/P0_UPGRADE_HOLDOUT.json'
    frozen,_,archive_sha=restore(archive,summary);rows=frozen['predictions']
    if len({r['id'] for r in rows})!=len(rows):raise ValueError('duplicate fixtures in frozen evaluation')
    compared={};reproduced=True
    for key in frozen['market_metrics']:
        outcomes=[{'WIN':0,'PUSH':1,'LOSS':2}[r['markets'][key]['outcome']] for r in rows]
        compared[key]={}
        for model in ('baseline','candidate'):
            measured=metrics([r['markets'][key][model]['probabilities'] for r in rows],outcomes)
            stored=frozen['market_metrics'][key][model]
            equal=all(abs(measured[k]-stored[k])<1e-12 for k in ('brier','log_loss','ece_macro'))
            reproduced &= equal
            compared[key][model]={k:measured[k] for k in ('n','brier','log_loss','ece_macro')}
            compared[key][model]['archived_metrics_reproduced']=equal
        compared[key]['delta_brier']=compared[key]['candidate']['brier']-compared[key]['baseline']['brier']
        compared[key]['descriptive_interval']=frozen['market_metrics'][key]['paired']['descriptive_interval']
    old_path=ROOT/'reports/REAL_DATA_BENCHMARK.json';legacy=json.loads(old_path.read_text())
    old=metrics([r['p'] for r in legacy['predictions']],[r['y'] for r in legacy['predictions']])
    output={'schema':'frozen-effectiveness-audit-v1','generated_at':datetime.now(timezone.utc).isoformat(),
        'scope':'HISTORICAL_ALREADY_VIEWED_NOT_NEW_HOLDOUT','fixtures':len(rows),
        'sources':{'restored_p0_sha256':archive_sha,'archive_code_hash':frozen['code_hash'],
                   'legacy_file_sha256':hashlib.sha256(old_path.read_bytes()).hexdigest()},
        'auditing_code_hash':code_hash(),'auditing_model_hash':model_code_hash(),
        'markets':compared,'all_archived_p0_metrics_reproduced':reproduced,
        'legacy_frozen_forecasts':{k:old[k] for k in ('n','brier','log_loss','ece_macro')},
        'primary_market':frozen['primary_market'],
        'candidate_brier_improved_markets':sum(m['delta_brier']<0 for m in compared.values()),
        'candidate_brier_worsened_markets':sum(m['delta_brier']>0 for m in compared.values()),
        'promotion':'KEEP_SHADOW','new_forecasts_created':0,'models_fitted':0,
        'statistical_profitability_proven':False,'monetary_permission':False,
        'limitations':['Archived TEST has already been inspected; it cannot become unseen HOLDOUT.',
            'Same historical fixture reused across markets is one observation, not seven.',
            'Descriptive intervals do not adjust fixture dependence or multiple comparisons.',
            'Legacy forecasts are a different model, not performance of the current default.',
            'No new prematch prices, price baselines or current executable returns are supplied.']}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as f:json.dump(output,f,ensure_ascii=False,indent=2,allow_nan=False)
    print(json.dumps({'file':str(args.output.resolve()),'fixtures':len(rows),'archived_metrics_reproduced':reproduced,
                      'improved_markets':output['candidate_brier_improved_markets'],'worsened_markets':output['candidate_brier_worsened_markets'],
                      'primary':compared[frozen['primary_market']],'promotion':'KEEP_SHADOW'},ensure_ascii=False))
    return 0 if reproduced else 2


if __name__=='__main__':raise SystemExit(main())
