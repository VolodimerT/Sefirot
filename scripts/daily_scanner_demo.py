"""Create an owned SYNTHETIC offline example; never use an existing ledger."""
from pathlib import Path
import argparse
import json
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from sefirot.contracts import digest
from sefirot.sports_archive import archive_packets
from research.prematch_scenario import run_scenario, _frozen, FIXTURES
from research.daily_scanner import scan_day, render_report


def build_demo(output):
    output = Path(output)
    # Exclusive creation: no historical files or user ledgers can be overwritten.
    output.mkdir(parents=True, exist_ok=False)
    source = _frozen(FIXTURES / 'source.json', 'prematch-synthetic-source-v1')
    scenario = output / 'scenario'
    run_scenario(work_directory=scenario)
    calendar = json.loads(json.dumps(source['packets'][0]))
    calendar['receipt']['parameters'] = {'date': '2030-01-01', 'timezone': 'UTC'}
    calendar['data']['parameters'] = dict(calendar['receipt']['parameters'])
    calendar['receipt']['payload_hash'] = digest(calendar['data'])
    archive_packets([calendar], scenario / 'archive', source['capture_at'])
    event = {'id': 'synthetic-event-900001', 'sport_key': 'soccer_test',
        'home_team': 'Team A', 'away_team': 'Team B',
        'commence_time': '2030-01-01T12:00:00+00:00',
        'bookmakers': [{'key': 'synthetic_book', 'markets': [{'key': 'h2h',
            'last_update': source['quote_at'], 'outcomes': [
                {'name': 'Team A', 'price': 2.1}, {'name': 'Draw', 'price': 3.2},
                {'name': 'Team B', 'price': 3.5}]}]}]}
    prices = {'900001': {'event': event, 'sport': 'soccer_test', 'event_id': event['id'],
        'bookmaker': 'synthetic_book', 'received_at': source['quote_at'],
        'rules_confirmed': True, 'market_keys': ['h2h']}}
    report = scan_day(calendar=calendar, archive=scenario / 'archive', day='2030-01-01',
        at=source['decision_at'], profile=source['profile'], database=scenario / 'scenario.sqlite',
        prices=prices, synthetic=True)
    for name, value in [('calendar.json', calendar), ('prices.json', prices), ('DAILY_REPORT.json', report)]:
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (output / 'DAILY_REPORT.md').write_text(render_report(report), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='New owned directory; must not exist')
    args = parser.parse_args()
    print(json.dumps(build_demo(args.output), ensure_ascii=False, indent=2))
