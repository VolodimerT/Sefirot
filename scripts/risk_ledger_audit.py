"""Explicit offline audit of original SQLite rows; no model or ledger writes."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sefirot.contracts import Policy, digest, number, time
from sefirot.repository import Repository
from sefirot.service import Service


def audit(path, as_of):
    cutoff = time(as_of)
    report = {'schema': 'risk-ledger-audit-v43', 'as_of': cutoff.isoformat(),
              'status': 'INPUT_REJECTED', 'read_only': True,
              'risk_day_timezone': 'UTC', 'risk_day': cutoff.date().isoformat(),
              'journal_integrity': False, 'counts': {}, 'defects': {},
              'service_contexts_checked': 0, 'settled_exposures_checked': 0,
              'source_attestation': 'NOT_ESTABLISHED',
              'predictive_edge': 'NOT_EVALUATED', 'monetary_permission': False,
              'replay_performed': False}
    repo = Repository(path, read_only=True)
    try:
        # One consistent read snapshot; no BEGIN IMMEDIATE, schema/bootstrap,
        # write connection, forecast replay, original-row updates or network.
        repo.db.execute('BEGIN')
        report['journal_integrity'] = repo.verify()
        tables = ('predictions', 'decisions', 'bets', 'results')
        rows = {t: list(repo.db.execute('SELECT * FROM ' + t + ' ORDER BY id'))
                for t in tables}
        report['counts'] = {t: len(v) for t, v in rows.items()}
        report['snapshot_digest'] = digest({
            t: [dict(row) for row in v] for t, v in rows.items()})
        if not report['journal_integrity']:
            report['status'] = 'JOURNAL_INVALID'
            return report
        defects = Counter()
        def require(condition, code):
            if not condition:
                defects[code] += 1
        payloads = {t: {r['id']: json.loads(r['payload']) for r in v}
                    for t, v in rows.items()}
        for row in rows['predictions']:
            p = payloads['predictions'][row['id']]
            require(row['id'] == p['id'], 'PREDICTION_ID_BINDING')
            require(row['match_id'] == p['sports']['match']['id'], 'PREDICTION_MATCH_BINDING')
            require(time(row['at']) == time(p['sealed_at']), 'PREDICTION_TIME_BINDING')
        for row in rows['decisions']:
            d = payloads['decisions'][row['id']]
            require(row['id'] == d['id'], 'DECISION_ID_BINDING')
            require(row['prediction_id'] == d['prediction_id'], 'DECISION_PARENT_BINDING')
            require(time(row['at']) == time(d['at']), 'DECISION_TIME_BINDING')
            p = payloads['predictions'][row['prediction_id']]
            require(d['match_id'] == p['sports']['match']['id'], 'DECISION_MATCH_BINDING')
            require(time(p['sealed_at']) <= time(d['at']) < time(p['sports']['match']['kickoff']),
                    'DECISION_PREMATCH_CHRONOLOGY')
        for row in rows['bets']:
            b = payloads['bets'][row['id']]
            require(row['id'] == b['id'], 'BET_ID_BINDING')
            require(row['decision_id'] == b['decision_id'], 'BET_PARENT_BINDING')
            require(time(row['at']) == time(b['at']), 'BET_TIME_BINDING')
            number(b['stake'], 'stake', .01)
            require(isinstance(b['groups'], list) and all(isinstance(g, str) for g in b['groups']),
                    'BET_GROUP_SHAPE')
            d = payloads['decisions'][row['decision_id']]
            p = payloads['predictions'][d['prediction_id']]
            require(b['match_id'] == d['match_id'], 'BET_MATCH_BINDING')
            require(time(d['at']) <= time(b['at']) < time(p['sports']['match']['kickoff']),
                    'BET_PREMATCH_CHRONOLOGY')
        for row in rows['results']:
            r = payloads['results'][row['id']]
            match = repo.get('matches', row['id'])
            require(row['id'] == r['match_id'], 'RESULT_MATCH_BINDING')
            require(time(row['at']) == time(r['received_at']), 'RESULT_TIME_BINDING')
            require(time(match['kickoff']) < time(r['finished_at']) <= time(r['received_at']),
                    'RESULT_CHRONOLOGY')
        # Use the actual Service's as-of filtering and exposure reconstruction,
        # with the sealed historical Policy. No replacement repository mocks.
        for p in payloads['predictions'].values():
            if time(p['sealed_at']) > cutoff:
                continue
            svc = Service(repo, Policy(**p['policy']), clock=lambda: cutoff)
            context = svc.context(p, cutoff.isoformat())
            report['service_contexts_checked'] += 1
            require(context['journal_ok'], 'SERVICE_JOURNAL_INVALID')
            for e in context['exposures']:
                b = payloads['bets'][e['id']]
                require(time(e['at']) <= cutoff, 'FUTURE_PLACEMENT_VISIBLE')
                visible = payloads['results'].get(b['match_id'])
                visible = visible if visible and time(visible['received_at']) <= cutoff else None
                require(('settled_at' in e) == (visible is not None), 'SETTLEMENT_VISIBILITY')
                if visible:
                    require(time(e['settled_at']) == time(visible['received_at']), 'SETTLEMENT_SOURCE_BINDING')
                    require(time(e['at']) <= time(e['settled_at']) <= cutoff, 'EXPOSURE_CHRONOLOGY')
            # Exposures repeat per context; denominator is unique bet records.
        report['settled_exposures_checked'] = sum(
            time(b['at']) <= cutoff and b['match_id'] in payloads['results']
            and time(payloads['results'][b['match_id']]['received_at']) <= cutoff
            for b in payloads['bets'].values())
        report['defects'] = dict(sorted(defects.items()))
        report['status'] = ('CHRONOLOGY_INVALID' if defects else
                            'INSUFFICIENT_SETTLEMENT_RECORDS' if not report['settled_exposures_checked']
                            else 'INTERNAL_CHRONOLOGY_CHECKED')
        # Internal hash bindings are not provider/bookmaker attestation.
        report['synthetic_predictions'] = sum(p['sports'].get('synthetic') is True
                                               for p in payloads['predictions'].values())
        return report
    except (ValueError, KeyError, TypeError, sqlite3.Error):
        # Never echo private SQL, identifiers, payloads or exception messages.
        report['status'] = 'RECORD_SHAPE_REJECTED'
        return report
    finally:
        repo.db.rollback()
        repo.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only original risk receipt audit; no provider calls')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--as-of', required=True)
    args = parser.parse_args(argv)
    try:
        report = audit(args.db, args.as_of)
    except (ValueError, OSError, sqlite3.Error):
        print('RISK_LEDGER_INPUT_REJECTED', file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False))
    return 0 if report['status'] in ('INTERNAL_CHRONOLOGY_CHECKED', 'INSUFFICIENT_SETTLEMENT_RECORDS') else 2


if __name__ == '__main__':
    raise SystemExit(main())
