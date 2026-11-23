"""Cadenced, offline orchestration of the existing SHADOW commands."""
from datetime import timedelta
import sqlite3

from research.prospective_shadow import BASE, plan_next, report, run
from sefirot.contracts import time
from sefirot.forward import _save

SCHEMA = 'prospective-shadow-tick-v1'


def tick(service, source, *, league, profile, reliability, synthetic_test_only=False):
    repo = service.repo
    with repo.transaction():
        if not repo.verify():
            raise ValueError('shadow ledger verification failed')
        prior = [j for j in repo.all('jobs') if j.get('schema') == SCHEMA]
        last = max(prior, key=lambda j: time(j['at'])) if prior else None
        at = service.now()
        if last and time(at) < time(last['next_attempt_at']):
            return {**last, 'ran': False}
        try:
            with repo.transaction():
                if source is None:
                    raise OSError('missing source ledger')
                planned = plan_next(service, source, league, profile, reliability,
                                    synthetic_test_only=synthetic_test_only)
                capture = run(service, source, 'capture')
                settlement = run(service, source, 'settle')
                dashboard = report(service, source)
        except (OSError, sqlite3.OperationalError):
            failures = (last['consecutive_failures'] if last else 0) + 1
            status, reason = 'BLOCKED', 'SOURCE_UNAVAILABLE'
            planned = capture = settlement = None
            dashboard = None
        except ValueError:
            failures = (last['consecutive_failures'] if last else 0) + 1
            status, reason = 'BLOCKED', 'SHADOW_INPUT_OR_INTEGRITY_REJECTED'
            planned = capture = settlement = None
            dashboard = None
        else:
            failures = 0
            status, reason = 'OK', None
        delay = min(60, 15 * 2 ** min(failures - 1, 2)) if failures else 30
        result = _save(service, {'schema': SCHEMA, 'at': at, 'status': status, 'reason': reason,
                                'next_attempt_at': (time(at) + timedelta(minutes=delay)).isoformat(),
                                'consecutive_failures': failures,
                                'synthetic_test_only': synthetic_test_only, 'network_requests': 0, **BASE})
    return {**result, 'ran': True, 'planning': planned, 'capture': capture,
            'settle': settlement, 'report': dashboard}
