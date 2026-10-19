"""Offline API-Football archive -> observation-v2 -> existing coverage QC.

Exact saved packet bytes are bound, NOT authenticated provider HTTP responses.
Caller receipts, license references and expected calendar remain unattested.
No I/O, training, CORE writes, network requests or monetary admission here.
"""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sefirot.contracts import digest, integer
from sefirot.football_provider import MAX_PROVIDER_ID
from sefirot.small_market import validate_statistics_packet
from sefirot.sports_archive import validate_packet
from research.small_observation_v2 import (
    METRICS, PERIODS, audit_dataset, record_hash, stamp, validate_manifest,
    validate_observation,
)

MAX_PACKET_BYTES = 4_000_000
MAX_ARCHIVE_BYTES = 64_000_000
MAX_STAT_PACKETS = 10000
PROVIDER = 'API_FOOTBALL_V3'
# Label bindings only. These are NOT bookmaker settlement definitions.
LABELS = {'CORNERS': 'Corner Kicks', 'SHOTS': 'Total Shots',
          'SOT': 'Shots on Goal', 'YELLOW_CARDS': 'Yellow Cards',
          'RED_CARDS': 'Red Cards'}
STATUS = {s: s for s in ('FT', 'AET', 'PEN', 'PST', 'ABD', 'NS')}
STATUS.update({'CANC': 'VOID', '1H': 'LIVE', 'HT': 'LIVE', '2H': 'LIVE'})


def decode_packet(raw):
    """Return parsed JSON and SHA of the actual saved UTF-8 packet bytes."""
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_PACKET_BYTES:
        raise ValueError('BOUNDED_PACKET_BYTES_REQUIRED')

    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError('DUPLICATE_JSON_KEY')
            out[key] = value
        return out

    def constant(_):
        raise ValueError('NONFINITE_JSON_NUMBER')

    def floating(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('NONFINITE_JSON_NUMBER')
        return number

    try:
        packet = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                            parse_constant=constant, parse_float=floating)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError('INVALID_UTF8_PACKET_JSON') from None
    if not isinstance(packet, dict):
        raise ValueError('PACKET_OBJECT_REQUIRED')
    return packet, hashlib.sha256(raw).hexdigest()


def _query_echo(packet, endpoint, allowed):
    params = packet['receipt']['parameters']
    data = packet['data']
    if (set(params) != set(allowed) or data.get('get') != endpoint
            or not isinstance(data.get('parameters'), dict)
            or {k: str(v) for k, v in data['parameters'].items()}
            != {k: str(v) for k, v in params.items()}):
        raise ValueError('EXACT_UNFILTERED_QUERY_ECHO_REQUIRED')


def _provider_id(value):
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    return integer(value, 'provider id', 1, MAX_PROVIDER_ID)


def _schedule(schedule_raw, expected, imported_at):
    packet, raw_sha = decode_packet(schedule_raw)
    validate_packet(packet, imported_at)
    _query_echo(packet, 'fixtures', ('league', 'season'))
    params = packet['receipt']['parameters']
    league = _provider_id(params['league'])
    season = _provider_id(params['season'])
    if (expected['provider'] != PROVIDER
            or expected['competition_id'] != f'api-football:league:{league}'
            or expected['season'] != str(season)):
        raise ValueError('EXPECTED_PROVIDER_LEAGUE_SEASON_MISMATCH')
    if expected['source_sha256'] != raw_sha:
        raise ValueError('MANIFEST_RAW_SCHEDULE_HASH_MISMATCH')
    if not expected['pagination_complete']:
        raise ValueError('EXPECTED_MANIFEST_PAGINATION_INCOMPLETE')
    if expected['license_ref'] is None:
        raise ValueError('LICENSE_REFERENCE_REQUIRED_NOT_VERIFIED')
    assigned = validate_manifest(expected, stamp(imported_at))
    rows = packet['data']['response']
    if len(rows) > 10000:
        raise ValueError('BOUNDED_LEAGUE_SCHEDULE_REQUIRED')
    mapped = {}
    for index, row in enumerate(rows):
        if (type(row['league'].get('season')) is not int
                or row['league']['season'] != season
                or row['league']['id'] != league):
            raise ValueError('SCHEDULE_FOREIGN_LEAGUE_OR_SEASON')
        if row['league'].get('type', 'League') != 'League':
            raise ValueError('RAW_CUP_NOT_A_LEAGUE')
        fid = f"api-football:fixture:{row['fixture']['id']}"
        if fid not in assigned:
            raise ValueError('RAW_FIXTURE_NOT_IN_EXPECTED_MANIFEST')
        f = assigned[fid]
        raw_status = row['fixture']['status']['short']
        if raw_status not in STATUS:
            raise ValueError('UNSUPPORTED_PROVIDER_STATUS')
        if (f['home_id'] != f"api-football:team:{row['teams']['home']['id']}"
                or f['away_id'] != f"api-football:team:{row['teams']['away']['id']}"
                or stamp(f['kickoff']) != stamp(row['fixture']['date'])
                or f['status'] != STATUS[raw_status]):
            raise ValueError('RAW_MANIFEST_FIXTURE_IDENTITY_MISMATCH')
        mapped[row['fixture']['id']] = (index, fid, f)
    if {fid for _, fid, _ in mapped.values()} != set(assigned):
        raise ValueError('EXPECTED_SCHEDULE_FIXTURES_MISSING')
    return packet, raw_sha, mapped


def import_api_archive(expected, schedule_raw, statistic_raws, imported_at, evaluated_at):
    """Replayable mechanical import; local knowledge never predates import.

Only unfiltered regulation-FT per-team statistics are supported. Each supplied
snapshot is preserved as a new normalized revision, with no forward-filling.
The expected calendar must be supplied independently of the statistic sample.
"""
    imported = stamp(imported_at)
    cutoff = stamp(evaluated_at)
    if cutoff < imported:
        raise ValueError('CUTOFF_PRECEDES_LOCAL_IMPORT')
    if (not isinstance(statistic_raws, list) or len(statistic_raws) > MAX_STAT_PACKETS
            or any(not isinstance(b, bytes) for b in statistic_raws)
            or not isinstance(schedule_raw, bytes)):
        raise ValueError('BOUNDED_STATISTIC_BYTE_LIST_REQUIRED')
    if len(schedule_raw) + sum(len(b) for b in statistic_raws) > MAX_ARCHIVE_BYTES:
        raise ValueError('ARCHIVE_BYTES_LIMIT')
    validate_manifest(expected, imported)
    schedule, schedule_sha, mapped = _schedule(schedule_raw, expected, imported_at)
    ft_received = stamp(schedule['receipt']['received_at'])
    manifest = deepcopy(expected)
    # The imported calendar is knowledge acquired locally now, never historically.
    manifest['registered_at'] = imported.isoformat()
    definitions = {m: (f'api-football:v3:statistics:FT:{LABELS[m]}:RAW_UNATTESTED'
                       if m in LABELS else None) for m in METRICS}
    snapshots = defaultdict(dict)
    duplicate_packets = 0
    seen = set()
    input_hashes = []
    for raw in statistic_raws:
        packet, raw_sha = decode_packet(raw)
        input_hashes.append(raw_sha)
        fid = validate_statistics_packet(packet)
        _query_echo(packet, 'fixtures/statistics', ('fixture',))
        receipt = packet['receipt']
        received = stamp(receipt['received_at'])
        if received > imported:
            raise ValueError('PACKET_RECEIVED_AFTER_LOCAL_IMPORT')
        if stamp(receipt['request_started_at']) < ft_received:
            raise ValueError('STATISTICS_NOT_REQUESTED_AFTER_FT_RECEIPT')
        if fid not in mapped:
            raise ValueError('STATISTICS_UNASSIGNED_FIXTURE')
        schedule_index, normalized_fid, fixture = mapped[fid]
        if fixture['status'] != 'FT':
            raise ValueError('REGULATION_FT_REQUIRED')
        if raw_sha in seen:
            duplicate_packets += 1
            continue
        seen.add(raw_sha)
        counts = {p: {m: {'home': None, 'away': None} for m in METRICS}
                  for p in PERIODS}
        team_indices = {}
        for index, block in enumerate(packet['data']['response']):
            team_id = f"api-football:team:{block['team']['id']}"
            sides = [s for s in ('home', 'away') if fixture[s + '_id'] == team_id]
            if len(sides) != 1:
                raise ValueError('STATISTICS_FOREIGN_TEAM')
            side = sides[0]
            team_indices[side] = index
            values = {s['type']: s.get('value') for s in block['statistics']}
            for metric, label in LABELS.items():
                value = values.get(label)
                if value is not None:
                    integer(value, 'statistic count', 0, 10000)
                counts['FT'][metric][side] = value
        # Empty response is preserved as explicit missing data. One-sided
        # packets are rejected; no cross-packet assembly or implied zero.
        if team_indices and set(team_indices) != {'home', 'away'}:
            raise ValueError('BOTH_STATISTIC_TEAMS_REQUIRED')
        observation = {'schema': 'small-match-observation-v2',
                       **{k: manifest[k] for k in ('provider', 'competition_id', 'season', 'competition_type')},
                       **fixture, 'revision': 0, 'supersedes_sha256': None,
                       'published_at': received.isoformat(), 'received_at': imported.isoformat(),
                       'available_at': imported.isoformat(), 'raw_sha256': raw_sha,
                       'source_kind': 'RETROSPECTIVE_IMPORT', 'license_ref': manifest['license_ref'],
                       'metric_definitions': dict(definitions), 'counts': counts, 'referee': None}
        validate_observation(observation)
        payload_key = digest(packet['data'])
        old = snapshots[fid].get(received)
        if old is not None:
            if old[0] != payload_key:
                raise ValueError('SIMULTANEOUS_STATISTIC_CONFLICT')
            duplicate_packets += 1
            # Equivalent serialization at one receipt time: select deterministically.
            if old[1]['raw_sha256'] <= raw_sha:
                continue
        snapshots[fid][received] = (payload_key, observation, {
            'fixture_id': normalized_fid, 'schedule_sha256': schedule_sha,
            'schedule_row_pointer': f'/data/response/{schedule_index}',
            'statistic_packet_sha256': raw_sha,
            'statistic_team_pointers': {s: f'/data/response/{i}' for s, i in team_indices.items()},
            'provider_first_observed_at': received.isoformat(),
        })
    observations = []
    bindings = []
    for fid in sorted(snapshots):
        times = sorted(snapshots[fid])
        for index, received in enumerate(times):
            _, observation, binding = snapshots[fid][received]
            binding.update(archive_snapshot_index=index, emitted=(received == times[-1]))
            if binding['emitted']:
                binding['emitted_normalized_sha256'] = record_hash(observation)
                observations.append(observation)
            bindings.append(binding)
    batch = {'schema': 'small-observation-batch-v2', 'manifest': manifest,
             'observations': observations}
    coverage = audit_dataset(batch, cutoff.isoformat())
    report = {'schema': 'small-source-import-v1', 'adapter': 'API_FOOTBALL_FT_ARCHIVE_V1',
              'imported_at': imported.isoformat(), 'evaluated_at': cutoff.isoformat(),
              'status': 'RETROSPECTIVE_RESEARCH_ONLY', 'batch': batch, 'coverage': coverage,
              'binding': {'saved_packet_bytes_bound': True, 'original_http_bytes_bound': False,
                          'source_attested': False, 'license_verified': False,
                          'manifest_completeness_attested': False,
                          'venue_provenance': 'EXPECTED_MANIFEST_OPERATOR_ASSERTION',
                          'competition_type_provenance': 'EXPECTED_MANIFEST_OPERATOR_ASSERTION',
                          'expected_manifest_sha256': record_hash(expected),
                          'schedule_sha256': schedule_sha, 'observations': bindings,
                          'input_statistic_packet_sha256': sorted(input_hashes),
                          'duplicate_packets': duplicate_packets,
                          'archived_statistic_revisions': len(bindings) - len(observations),
                          'definitions': definitions},
              'unsupported': ['1H', '2H', 'FOULS_DIRECTION', 'SECOND_YELLOW',
                              'BOOKING_POINTS', 'REFEREE_PRIORS', 'PLAYER_PROPS', 'ODDS'],
              'network_requests': 0, 'core_writes': 0, 'fit_allowed': False,
              'monetary_permission': False, 'holdout_eligible': False,
              'timestamp_semantics': {
                  'published_at': 'Caller receipt time; true upstream publication unknown.',
                  'available_at': 'Actual local import time; never kickoff or old provider receipt.',
                  'revisions': 'Latest caller-observed snapshot at import; older snapshots bound in provenance only.'},
              'missing_inputs': ['INDEPENDENT_PROVIDER_ORIGIN_ATTESTATION', 'LICENSE_VERIFICATION',
                                 'INDEPENDENT_COMPLETE_LEAGUE_CALENDAR', 'VERIFIED_METRIC_DEFINITIONS',
                                 'BOOKMAKER_SETTLEMENT_RULES', 'INDEPENDENT_NEW_HOLDOUT']}
    report['report_hash'] = record_hash(report)
    return report
