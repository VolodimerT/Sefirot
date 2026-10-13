"""Deterministic synthetic runtime benchmark; no prices fetched or profit claims."""
from __future__ import annotations

import argparse
import copy
from hashlib import sha256
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import platform
import statistics
import sys
import tempfile
from time import perf_counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--sizes', type=int, nargs='+', default=[0, 200, 1000])
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1 or any(n < 0 for n in args.sizes):
        parser.error('nonnegative sizes and positive repeats required')
    sys.path.insert(0, str(args.source_root.resolve() / 'src'))
    from sefirot.contracts import Policy, digest, time
    from sefirot.engine import prepare
    from sefirot.fixtures import example
    from sefirot.identity import code_hash, model_code_hash
    from sefirot.repository import Repository
    from sefirot.service import Service

    now = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    case = example(now, 'benchmark-target')
    policy = Policy()

    def measure(call):
        samples = []
        value = None
        for _ in range(args.repeats):
            start = perf_counter()
            value = call()
            samples.append(perf_counter() - start)
        return {'median_seconds': statistics.median(samples), 'samples_seconds': samples}, value

    timing, prepared = measure(lambda: prepare(case['sports'], case['markets'], policy))
    with tempfile.TemporaryDirectory() as directory:
        sequence = iter(range(args.repeats))
        def initialize():
            created = Repository(Path(directory) / f'ledger-{next(sequence)}.sqlite')
            created.close()
        initialization, _ = measure(initialize)
    output = {'schema': 'runtime-benchmark-v1', 'synthetic': True,
              'python': platform.python_version(), 'platform': platform.platform(),
              'source_root': str(args.source_root.resolve()), 'code_hash': code_hash(),
              'benchmark_source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'fixture_hash': digest(case),
              'model_hash': model_code_hash(), 'policy_hash': policy.fingerprint,
              'repeats': args.repeats, 'prepare_seven_markets': timing,
              'initialize_empty_ledger': initialization,
              'probabilities_hash': digest([{k: c[k] for k in
                  ('market', 'raw', 'base', 'low', 'high', 'stress_probabilities', 'calibration')}
                  for c in prepared['candidates']]), 'journals': [],
              'statistical_profitability_proven': False}

    for size in args.sizes:
        repo = Repository(':memory:')
        try:
            # Use one real synthetic service cycle as the template. Seeding is
            # outside timed regions; cloned records keep foreign keys and audit
            # content bindings rather than timing an invalid minimal database.
            seed_case = example(now - timedelta(days=1), 'benchmark-seed-template')
            clock = [now - timedelta(days=1)]
            service = Service(repo, policy, lambda: clock[0])
            seed = service.capture(seed_case['sports'], seed_case['markets'])
            clock[0] = time(seed_case['result']['received_at'])
            service.result(seed_case['result'])
            metrics = repo.all('calibration_history')
            with repo.transaction():
                for i in range(size):
                    p = copy.deepcopy(seed)
                    match = p['sports']['match']
                    match['id'] = f'benchmark-history-{i:06d}'
                    p.pop('id')
                    p['id'] = digest(p)
                    repo.insert('matches', match['id'], match, home=match['home'], away=match['away'],
                                league=match['league'], kickoff=match['kickoff'])
                    repo.insert('predictions', p['id'], p, match_id=match['id'],
                                model_id=p['model_id'], at=p['sealed_at'])
                    repo.record_log('predictions', p['id'], p['sealed_at'], p)
                    for original in metrics:
                        record = {**original, 'prediction_id': p['id'], 'match_id': match['id']}
                        repo.insert('calibration_history', digest(record), record,
                                    prediction_id=p['id'], market_id=record['market'], at=record['received_at'])
            clock[0] = now
            target = service.capture(case['sports'], case['markets'])
            capture, recaptured = measure(lambda: service.capture(case['sports'], case['markets']))
            verify, integrity = measure(repo.verify)
            context, ctx = measure(lambda: service.context(target, case['decision_at']))
            cold = Repository(':memory:')
            try:
                repo.db.backup(cold.db)
                cold_service = Service(cold, policy, lambda: now)
                start = perf_counter()
                cold_ctx = cold_service.context(target, case['decision_at'])
                cold_context_seconds = perf_counter() - start
                assert digest(cold_ctx) == digest(ctx)
            finally:
                cold.close()

            def settle_fresh():
                copied = Repository(':memory:')
                try:
                    repo.db.backup(copied.db)
                    svc = Service(copied, policy, lambda: time(case['result']['received_at']))
                    start = perf_counter()
                    result = svc.result(case['result'])
                    elapsed = perf_counter() - start
                    health = copied.all('health_events', case['result']['received_at'])
                    normalized = [{k: v for k, v in h.items() if k not in ('id', 'context_key')} for h in health]
                    normalized.sort(key=digest)
                    return elapsed, result, digest(normalized)
                finally:
                    copied.close()

            settlement = [settle_fresh() for _ in range(args.repeats)]
            assert integrity and digest(recaptured) == digest(target) and ctx['journal_ok']
            output['journals'].append({'unrelated_fixtures': size,
                'feedback_rows': len(repo.all('calibration_history')),
                'recapture': capture, 'verify': verify, 'context': context,
                'cold_context_seconds': cold_context_seconds,
                'settle': {'median_seconds': statistics.median(s[0] for s in settlement),
                           'samples_seconds': [s[0] for s in settlement]},
                'semantic_result': {'integrity': integrity, 'idempotent_capture': digest(recaptured) == digest(target),
                    'policy_approved': ctx['policy_approved'],
                    'context_hash': digest(ctx),
                    'health': {k: {'n': v['n'], 'state': v['state'], 'trust': v['trust']}
                               for k, v in ctx['health'].items()},
                    'settlement': settlement[0][1], 'settlement_health': settlement[0][2]}})
        finally:
            repo.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output.resolve()), 'probabilities_hash': output['probabilities_hash'],
                      'prepare_seconds': timing['median_seconds'],
                      'journals': [{k: row[k] for k in ('unrelated_fixtures', 'recapture', 'verify', 'context', 'settle')}
                                   for row in output['journals']]}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
