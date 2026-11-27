"""Audit an export of existing guarded archive records. Never reconstruct a ledger."""
import argparse
from collections import Counter, defaultdict
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
import re

from research import football_pipeline as pipeline
from scripts.chat_sports_probe import _safe_source
from sefirot.contracts import digest, time
from sefirot.football_provider import fixture_identity, validate_prematch_state
from sefirot.provider_transport import strict_json_payload
from .data import FIELDS, _lineup_sources, _stat_fields
from .tactical import profile

READY = 'ARCHIVE_OBSERVED_ONLY'
SCOPES = (39, 140, 135, 78, 61, 2, 3, 848, 137, 45, 143, 66, 81)
SCOPE_SET = frozenset(SCOPES)
MISSING_FIELDS = ('SUBSTITUTIONS', 'INJURIES', 'SUSPENSIONS', 'MINUTE_EVENTS')


def _accepted(row, raw, cutoff):
    if (sha256(raw).hexdigest() != row['raw_sha256'] or len(raw) != row['bytes']
            or len(raw.decode('utf-8')) != row['characters']):
        raise ValueError('ARCHIVE_RAW_INTEGRITY')
    packet = strict_json_payload(raw)
    if not isinstance(packet, dict):
        raise ValueError('ARCHIVE_PACKET_SHAPE')
    if set(packet) == {'data', 'receipt', 'schema', 'projection_hash'}:
        if (packet['schema'] != 'guarded-probe-evidence-v2'
                or not isinstance(packet['projection_hash'], str)
                or not re.fullmatch(r'[0-9a-f]{64}', packet['projection_hash'])):
            raise ValueError('ARCHIVE_PACKET_SHAPE')
        # Validate original data and receipt with the existing QC. The
        # archived projection is not used for sports facts.
        packet = {k: packet[k] for k in ('data', 'receipt')}
    elif set(packet) != {'data', 'receipt'}:
        raise ValueError('ARCHIVE_PACKET_SHAPE')
    receipt, data = packet['receipt'], packet['data']
    if (receipt['endpoint'] != row['endpoint'] or receipt['received_at'] != row['received_at']
            or receipt['payload_hash'] != row['payload_sha256']):
        raise ValueError('ARCHIVE_INDEX_BINDING')
    imported = time(row['imported_at'])
    if not time(receipt['received_at']) <= imported <= cutoff:
        raise ValueError('ARCHIVE_CUTOFF')
    links = row['links']
    if (not isinstance(links, list) or not links or any(
            not isinstance(link['job_id'], str) or not re.fullmatch(
                r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', link['job_id'])
            or type(link['attempt']) is not int or not 1 <= link['attempt'] <= 3
            or not imported <= time(link['linked_at']) <= cutoff for link in links)):
        raise ValueError('ARCHIVE_LINK_UNBOUND')
    endpoint = receipt['endpoint'].removeprefix('/')
    if not _safe_source(data, endpoint) or not _safe_source({'response': receipt}, 'fixtures'):
        raise ValueError('ARCHIVE_SOURCE_SAFETY')
    try:
        pipeline._qc(packet, row['imported_at'])
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise ValueError('ARCHIVE_SOURCE_QC') from None
    linked = min((link['linked_at'] for link in links), key=time)
    return {'id': 'football-source:' + row['raw_sha256'],
            'available_at': max(row['imported_at'], linked, key=time)}, packet


def _fixture_rows(ledger, cutoff, season):
    observations, stats, lineups = (defaultdict(list) for _ in range(3))
    issues = Counter()
    for rec, p in ledger:
        receipt = p['receipt']
        endpoint = receipt['endpoint']
        if endpoint == '/fixtures':
            for f in p['data']['response']:
                try:
                    fixture_identity(f)
                    observations[f['fixture']['id']].append((rec, receipt, f))
                except (ValueError, KeyError, TypeError, AttributeError):
                    issues['MALFORMED_FIXTURE_OBSERVATION'] += 1
        elif endpoint in ('/fixtures/statistics', '/fixtures/lineups'):
            value = str(receipt['parameters'].get('fixture', ''))
            if value.isascii() and value.isdigit():
                (stats if endpoint.endswith('/statistics') else lineups)[int(value)].append((rec, p))

    out = []
    for fid, versions in sorted(observations.items()):
        identities = {(v['league']['id'], v['league']['season'], v['teams']['home']['id'],
                       v['teams']['away']['id'], time(v['fixture']['date'])) for _, _, v in versions}
        if len(identities) != 1:
            issues['FIXTURE_IDENTITY_OR_KICKOFF_CONFLICT'] += 1
            continue
        league, year, home, away, kickoff = identities.pop()
        if year != season:
            continue
        latest = max(time(receipt['received_at']) for _, receipt, _ in versions)
        latest_versions = [(rec, v) for rec, receipt, v in versions if time(receipt['received_at']) == latest]
        if len({digest(v) for _, v in latest_versions}) != 1:
            issues['SIMULTANEOUS_FIXTURE_CONFLICT'] += 1
            continue
        fixture = latest_versions[0][1]
        teams = {'home': home, 'away': away}
        state = fixture['fixture']['status']['short']
        finals = []
        for rec, receipt, v in versions:
            if v['fixture']['status']['short'] != 'FT':
                continue
            ft = v['score']['fulltime']
            if time(receipt['received_at']) < kickoff + timedelta(minutes=90):
                issues['FT_BEFORE_REGULATION'] += 1
            elif all(type(ft.get(side)) is int and ft[side] >= 0 for side in teams):
                finals.append((rec, receipt, v))
        if len({digest(v['score']['fulltime']) for _, _, v in finals}) > 1:
            issues['RESULT_REVISION_CONFLICT'] += 1
            continue
        if state == 'NS':
            try:
                validate_prematch_state(fixture)
            except ValueError:
                issues['MALFORMED_PREMATCH_STATE'] += 1
                state = 'INVALID_NS'
        confirmed = state == 'FT' and bool(finals)
        fields, stat_issue = {}, None
        ht, referee, result = None, None, None
        if confirmed:
            first_ft = min(time(r['received_at']) for _, r, _ in finals)
            fields, stat_issue = _stat_fields(stats[fid], teams, first_ft)
            result = fixture['score']['fulltime']
            candidates = {tuple(score[s] for s in teams)
                          for _, _, v in finals
                          if isinstance(score := v['score'].get('halftime'), dict)
                          and all(type(score.get(s)) is int and 0 <= score[s] <= result[s] for s in teams)}
            if len(candidates) == 1:
                ht = dict(zip(teams, next(iter(candidates))))
            elif candidates:
                issues['HALFTIME_REVISION_CONFLICT'] += 1
        if stat_issue:
            issues[stat_issue] += 1
        # Only a prematch-received and linked name is assignment evidence.
        referee_rows = [(rec, v['fixture'].get('referee')) for rec, receipt, v in versions
                        if v['fixture']['status']['short'] == 'NS'
                        and time(receipt['received_at']) <= time(rec['available_at']) < kickoff
                        and isinstance(v['fixture'].get('referee'), str)
                        and v['fixture']['referee'].strip()]
        if len({name for _, name in referee_rows}) == 1:
            referee = {'assignment_only': True, 'source_ids': sorted(rec['id'] for rec, _ in referee_rows)}
        lineup_ids = _lineup_sources(lineups[fid], teams, kickoff)
        paired = {f: all((side, f) in fields for side in teams) for f in FIELDS}
        out.append({'fixture_id': fid, 'league': league, 'season': year, 'teams': teams,
                    'kickoff': fixture['fixture']['date'], 'state': state,
                    'team_names': {s: fixture['teams'][s]['name'] for s in teams},
                    'ft_receipted': confirmed, 'goals': result, 'halftime': ht,
                    'lineups': lineup_ids, 'referee': referee, 'paired_fields': paired,
                    'fields': {s: {f: fields.get((s, f)) for f in FIELDS} for s in teams},
                    'calendar_fresh': cutoff - latest <= timedelta(hours=24),
                    'last_received_at': latest.isoformat(),
                    'fixture_sources': sorted(rec['id'] for rec, _ in latest_versions)})
    return out, issues, len(observations)


def _coverage(rows, cutoff):
    leagues, teams = [], defaultdict(Counter)
    scopes = sorted(SCOPE_SET | {r['league'] for r in rows})
    fields = ('GOALS', 'HALFTIME', 'SECOND_HALF_DERIVED', *FIELDS, 'XGA_DERIVED',
              'PREMATCH_LINEUPS', 'PREMATCH_REFEREE_ASSIGNMENT', *MISSING_FIELDS)
    for code in scopes:
        cohort = [r for r in rows if r['league'] == code]
        finals = [r for r in cohort if r['ft_receipted']]
        upcoming = [r for r in cohort if r['state'] == 'NS' and time(r['kickoff']) > cutoff]
        coverage = Counter(dict.fromkeys(fields, 0))
        for row in cohort:
            if row['ft_receipted']:
                coverage['GOALS'] += 1
                coverage['HALFTIME'] += int(row['halftime'] is not None)
                coverage['SECOND_HALF_DERIVED'] += int(row['halftime'] is not None)
                coverage.update(f for f, pair in row['paired_fields'].items() if pair)
                coverage['XGA_DERIVED'] += int(row['paired_fields']['XG'])
            coverage['PREMATCH_LINEUPS'] += int(bool(row['lineups']))
            coverage['PREMATCH_REFEREE_ASSIGNMENT'] += int(bool(row['referee']))
            for side, team in row['teams'].items():
                c = teams[(code, team)]
                c['observed'] += 1
                if row['ft_receipted']:
                    c['ft'] += 1
                    c['ft_' + side] += 1
                    c.update(f for f, val in row['fields'][side].items() if val is not None)
        leagues.append({'league': code, 'matches': len(cohort), 'ft': len(finals),
                        'upcoming': len(upcoming), 'priority_scope': code in SCOPE_SET,
                        'fresh_upcoming': sum(r['calendar_fresh'] for r in upcoming),
                        'paired_expanded_statistics': sum(any(r['paired_fields'].values()) for r in finals),
                        'field_coverage': dict(coverage)})
    return leagues, [{'league': l, 'team_id': t, **c} for (l, t), c in sorted(teams.items())]


def verify_archive(directory, manifest, *, as_of, season=2026, only=None):
    cutoff = time(as_of)
    if cutoff > time(pipeline.utcnow()):
        raise ValueError('FUTURE_ARCHIVE_CUTOFF')
    ledger, rejected, seen = [], Counter(), set()
    duplicates, selected = 0, 0
    for row in manifest['packets']:
        key = row.get('raw_sha256')
        if not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{64}', key):
            raise ValueError('INVALID_ARCHIVE_INDEX_HASH')
        if only is not None and key not in only:
            continue
        selected += 1
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        try:
            with (directory / (key + '.json')).open('rb') as source:
                raw = source.read(pipeline.MAX_BYTES + 1)
            if len(raw) > pipeline.MAX_BYTES:
                raise ValueError('ARCHIVE_PACKET_TOO_LARGE')
            ledger.append(_accepted(row, raw, cutoff))
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
            allowed = {'ARCHIVE_RAW_INTEGRITY','ARCHIVE_PACKET_SHAPE','ARCHIVE_INDEX_BINDING',
                       'ARCHIVE_CUTOFF','ARCHIVE_LINK_UNBOUND','ARCHIVE_SOURCE_SAFETY',
                       'ARCHIVE_SOURCE_QC','ARCHIVE_PACKET_TOO_LARGE'}
            # Stable diagnostic only; malformed input cannot inject exception text.
            rejected[str(exc) if type(exc) is ValueError and str(exc) in allowed else 'ARCHIVE_PACKET_UNREADABLE'] += 1

    repeated = Counter((p['receipt']['endpoint'], tuple(sorted(
                        (k, str(v)) for k, v in p['receipt']['parameters'].items())),
                        p['receipt']['payload_hash']) for _, p in ledger)
    rows, issues, observed_ids = _fixture_rows(ledger, cutoff, season)
    leagues, teams = _coverage(rows, cutoff)
    upcoming = [r for r in rows if r['league'] in SCOPE_SET and r['state'] == 'NS'
                and time(r['kickoff']) > cutoff + timedelta(minutes=20)]
    target = next(iter(sorted(upcoming, key=lambda r: (time(r['kickoff']), SCOPES.index(r['league']),
                                                    r['fixture_id']))), None)
    result = {'as_of': as_of, 'season': season, 'evidence_status': READY,
              'provider_calls': 0, 'observed_packets': selected, 'accepted_packets': len(ledger),
              'duplicate_raw_records': duplicates,
              'repeat_payload_observations': sum(n - 1 for n in repeated.values()),
              'packets_by_endpoint': dict(Counter(p['receipt']['endpoint'] for _, p in ledger)),
              'packet_rejections': dict(rejected), 'fixture_observation_issues': dict(issues),
              'unique_fixture_ids_all_seasons': observed_ids,
              'unique_reconciled_matches': len(rows), 'leagues': leagues, 'teams': teams, 'fixtures': rows,
              'qualified_research_seals': 0, 'tactical_fit_verified': 0, 'fit_allowed': False}
    if target:
        kickoff = time(target['kickoff'])
        def offset(minutes):
            return (kickoff + timedelta(minutes=minutes)).isoformat()
        schedule = {'history_calendar': [offset(-2880), offset(-1440)],
                    'context': [offset(-360), offset(-180)],
                    'lineups_referee': [offset(-65), offset(-30)],
                    'prematch_last_allowed': offset(-20),
                    'first_ft_recheck': offset(180), 'schedule_installed': False}
        result['pilot'] = {'fixture': target, 'offline_schedule': schedule, 'tactical_profile': profile(result, target['fixture_id']),
                           'decision': 'PASS', 'prematch_seal': None,
                           'blocking_evidence': ['SHARED_BUDGET_WINDOW_NOT_CONFIRMED', 'CURRENT_KICKOFF_RECHECK_REQUIRED',
                               'CONFIRMED_LINEUPS_AND_REFEREE_GATE_REQUIRED', 'TACTICAL_CONTEXT_UNVERIFIED',
                               'TIMESTAMPED_ODDS_UNAVAILABLE', 'PROSPECTIVE_REGISTRY_NOT_ATTESTED']}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--season', type=int, default=2026)
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--only', type=Path, help='JSON array of manifest hashes defining a frozen subset')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_bytes())
    only = set(json.loads(args.only.read_bytes())) if args.only else None
    report = verify_archive(args.archive, manifest, as_of=args.as_of, season=args.season, only=only)
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, separators=(',', ':')))


if __name__ == '__main__':
    main()
