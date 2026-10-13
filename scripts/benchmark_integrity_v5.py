"""Paired archived/candidate integrity benchmark on one synthetic ledger.

No network, private data, probabilities retuning, deployment or admission.
The reference is trusted repository Python at an explicit git revision.
"""
import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
from random import Random
import statistics
import subprocess
import sys
from time import perf_counter
from types import MethodType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sefirot.contracts import digest
from sefirot.fixtures import example
from sefirot.identity import code_hash, model_code_hash
from sefirot.repository import Repository
from sefirot.service import Service


def run(reference, size, repeats):
    source = subprocess.check_output(
        ['git', 'show', reference + ':src/sefirot/repository.py'], cwd=ROOT, text=True)
    namespace = {'__name__': 'sefirot.archived_integrity_reference', '__package__': 'sefirot'}
    exec(compile(source, '<explicit archived repository reference>', 'exec'), namespace)
    original = namespace['Repository']
    repo = Repository(':memory:')
    try:
        now = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
        case = example(now, 'integrity-paired')
        template = Service(repo, clock=lambda: now).capture(case['sports'], case['markets'])
        with repo.transaction():
            for i in range(size - 1):
                row = copy.deepcopy(template)
                row['revision'] = i + 1
                row.pop('id')
                row['id'] = digest(row)
                repo.insert('predictions', row['id'], row,
                            match_id=row['sports']['match']['id'],
                            model_id=row['model_id'], at=row['sealed_at'])
                repo.record_log('predictions', row['id'], row['sealed_at'], row)
        repo._record_digest = MethodType(original._record_digest, repo)
        methods = {'reference': original.verify, 'candidate': Repository.verify}
        for method in methods.values():
            if method(repo) is not True:
                raise ValueError('benchmark journal integrity failed')
        query_counts = {}
        for name, method in methods.items():
            queries = []
            repo.db.set_trace_callback(queries.append)
            try:
                if method(repo) is not True:
                    raise ValueError('benchmark journal integrity failed')
            finally:
                repo.db.set_trace_callback(None)
            query_counts[name] = sum(q.lstrip().upper().startswith('SELECT') for q in queries)
        rng = Random(5000)
        rows = []
        for _ in range(repeats):
            order = ['reference', 'candidate']
            rng.shuffle(order)
            sample = {}
            for name in order:
                started = perf_counter()
                if methods[name](repo) is not True:
                    raise ValueError('benchmark journal integrity failed')
                sample[name] = (perf_counter() - started) * 1000
            rows.append(sample)
        delta = [r['candidate'] - r['reference'] for r in rows]
        return {'schema': 'integrity-paired-benchmark-v5', 'synthetic': True,
                'reference_commit': subprocess.check_output(
                    ['git', 'rev-parse', reference], cwd=ROOT, text=True).strip(),
                'reference_source_hash': digest(source), 'candidate_code_hash': code_hash(),
                'model_hash': model_code_hash(), 'predictions': size, 'pairs': repeats,
                'query_counts': query_counts, 'samples_ms': rows,
                'reference_median_ms': statistics.median(r['reference'] for r in rows),
                'candidate_median_ms': statistics.median(r['candidate'] for r in rows),
                'paired_delta_median_ms': statistics.median(delta),
                'scope': 'warm integrity verification only, same database and cache, shuffled pairs',
                'limitations': ['Shared host timing is descriptive, not a production SLO.',
                                'No complete API/source/model/decision latency measured here.'],
                'monetary_permission': False, 'execution_enabled': False}
    finally:
        repo.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref', required=True)
    parser.add_argument('--size', type=int, default=1000)
    parser.add_argument('--pairs', type=int, default=21)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.size <= 10000 or not 3 <= args.pairs <= 101:
        parser.error('size/pairs outside bounded benchmark range')
    if args.output.exists():
        parser.error('output already exists')
    report = run(args.baseline_ref, args.size, args.pairs)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({k: report[k] for k in
          ('predictions', 'pairs', 'query_counts', 'reference_median_ms',
           'candidate_median_ms', 'paired_delta_median_ms')}))


if __name__ == '__main__':
    main()
