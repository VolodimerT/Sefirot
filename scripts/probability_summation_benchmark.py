"""Compare two local source trees; no network, fitting or ledger access."""
import argparse
from datetime import datetime, timezone
import importlib
import importlib.util
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter_ns

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def baseline_package(root):
    path = root / 'src' / 'sefirot'
    spec = importlib.util.spec_from_file_location('sefirot_baseline', path / '__init__.py',
                                                 submodule_search_locations=[str(path)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return 'sefirot_baseline'


def components(name):
    return {part: importlib.import_module(name+'.'+part)
            for part in ('contracts', 'engine', 'fixtures', 'markets', 'probability', 'identity')}


def paired_timing(before, after, pairs, repeats):
    for _ in range(3): before(); after()
    timings = []
    for i in range(pairs):
        row = {}
        for label, call in ((('after', after), ('before', before)) if i % 2
                            else (('before', before), ('after', after))):
            start = perf_counter_ns()
            for _ in range(repeats): call()
            row[label] = (perf_counter_ns()-start)/repeats/1e6
        timings.append(row)
    return {'pairs': pairs, 'repeats_per_measurement': repeats,
            'before_median_ms': median(r['before'] for r in timings),
            'after_median_ms': median(r['after'] for r in timings),
            'median_paired_delta_ms': median(r['after']-r['before'] for r in timings),
            'measurements': timings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-root', type=Path, required=True)
    parser.add_argument('--pairs', type=int, default=31)
    args = parser.parse_args()
    if not 1 <= args.pairs <= 101: parser.error('pairs must be 1..101')
    before = components(baseline_package(args.baseline_root.resolve()))
    after = components('sefirot')
    case = after['fixtures'].example(datetime(2026, 10, 13, 7, tzinfo=timezone.utc),
                                     'summation-benchmark-synthetic')
    rates = (.01, .1, .3, .5, 1., 1.1, 1.35, 2., 3., 6., 12.)
    failures = {}; error_types = {}
    for label, source in (('before', before), ('after', after)):
        failures[label] = 0
        for home in rates:
            for away in rates:
                mass, _ = source['probability'].distribution(home, away)
                m = source['markets'].Market('TOTAL', 'UNDER', 1000.)
                raw = source['markets'].probabilities(m, mass)
                try: source['probability'].calibrate(m, raw, None, source['contracts'].Policy())
                except ValueError as e:
                    failures[label] += 1
                    error_types[str(e)] = error_types.get(str(e), 0)+1
    prepare = lambda source: source['engine'].prepare(case['sports'], case['markets'],
                                                      source['contracts'].Policy())
    old, new = prepare(before), prepare(after)
    delta = max(abs(x-y) for oc, nc in zip(old['candidates'], new['candidates'])
                for field in ('raw', 'base', 'low', 'high') for x, y in zip(oc[field], nc[field]))
    stress_delta = max(abs(x-y) for oc, nc in zip(old['candidates'], new['candidates'])
                       for ov, nv in zip(oc['stress_probabilities'], nc['stress_probabilities'])
                       for x, y in zip(ov, nv))
    mass, _ = before['probability'].distribution(1.35, 1.1)
    projection = lambda source: source['markets'].probabilities(
        source['markets'].Market('TOTAL', 'OVER', 2.5), mass)
    report = {'schema': 'probability-summation-benchmark-v1', 'synthetic': True,
              'source_attestation': False, 'out_of_sample_validation': False,
              'monetary_permission': False, 'provider_calls': 0, 'ledger_writes': 0,
              'pair_grid_count': len(rates)**2, 'extreme_calibration_failures': failures,
              'failure_messages': error_types,
              'before_model_hash': before['identity'].model_code_hash(),
              'after_model_hash': after['identity'].model_code_hash(),
              'policy_hash_unchanged': old['policy_hash'] == new['policy_hash'],
              'candidate_keys_unchanged': [c['key'] for c in old['candidates']] == [c['key'] for c in new['candidates']],
              'prepare_issue_codes_unchanged': [i['code'] for i in old['issues']] == [i['code'] for i in new['issues']],
              'max_default_probability_or_bound_delta': delta, 'max_default_stress_delta': stress_delta,
              'warm_projection': paired_timing(lambda: projection(before), lambda: projection(after), args.pairs, 50),
              'warm_default_prepare': paired_timing(lambda: prepare(before), lambda: prepare(after), args.pairs, 1),
              'timing_scope': 'local synthetic cached projection and default sports prepare; no API/DB/decision latency'}
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
