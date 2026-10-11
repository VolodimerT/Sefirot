"""Read-only original-record answer verifier. No prediction, source fetch or grant."""
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo

from sefirot.contracts import digest, time
from research.small_market_readiness import preview

SCHEMA_PATH = Path(__file__).resolve().parents[1] / 'schema/chat_answer_v1.json'
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
CLOCK = re.compile(r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)$')


class AnswerError(ValueError):
    pass


_VERIFIED = object()


class VerifiedAnswer:
    """Immutable, non-JSON validation result; render cannot accept caller dicts."""
    __slots__ = ('__json', '__label')

    def __init__(self, answer, token, label):
        if token is not _VERIFIED: raise AnswerError('VERIFIER_RESULT_REQUIRED')
        object.__setattr__(self, '_VerifiedAnswer__json', json.dumps(answer, ensure_ascii=False, allow_nan=False))
        object.__setattr__(self, '_VerifiedAnswer__label', str(label).replace('\n',' ').replace('\r',' ')[:256])

    def __setattr__(self, key, value): raise AttributeError('immutable verifier result')

    def to_dict(self): return json.loads(self.__json)

    def __getitem__(self, key): return self.to_dict()[key]

    @property
    def fixture_label(self): return self.__label


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise AnswerError('DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    def nonfinite(_): raise AnswerError('NONFINITE_JSON')
    try: return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    except RecursionError: raise AnswerError('BOUNDED_JSON_DEPTH') from None


def _schema(value, spec, path='$', depth=0):
    """The frozen schema's finite subset; never resolves remote refs or code."""
    if depth > 20: raise AnswerError('BOUNDED_SCHEMA_DEPTH')
    if '$ref' in spec:
        ref = spec['$ref']
        if not ref.startswith('#/$defs/'): raise AnswerError('LOCAL_SCHEMA_REFS_ONLY')
        spec = SCHEMA['$defs'][ref.split('/')[-1]]
    supported={'$schema','$id','$defs','type','const','enum','properties','required',
               'additionalProperties','items','minItems','maxItems','uniqueItems',
               'minLength','maxLength','pattern','format','minimum','maximum'}
    if set(spec)-supported:raise AnswerError('UNSUPPORTED_FROZEN_SCHEMA_KEYWORD')
    kinds = spec.get('type', [])
    if isinstance(kinds, str): kinds = [kinds]
    def istype(kind):
        return {'null': value is None, 'object': type(value) is dict,
                'array': type(value) is list, 'string': type(value) is str,
                'boolean': type(value) is bool, 'integer': type(value) is int,
                'number': type(value) in (int, float)}[kind]
    if kinds and not any(istype(kind) for kind in kinds): raise AnswerError('SCHEMA_TYPE:' + path)
    if type(value) is float and not math.isfinite(value): raise AnswerError('NONFINITE_NUMBER')
    if 'const' in spec and (type(value) is not type(spec['const']) or value != spec['const']):
        raise AnswerError('SCHEMA_CONST:' + path)
    if 'enum' in spec and not any(type(value) is type(v) and value == v for v in spec['enum']):
        raise AnswerError('SCHEMA_ENUM:' + path)
    if value is None: return
    if type(value) is dict:
        properties = spec.get('properties', {})
        if set(spec.get('required', [])) - set(value): raise AnswerError('MISSING_FIELDS:' + path)
        if spec.get('additionalProperties') is False and set(value) - set(properties):
            raise AnswerError('UNKNOWN_FIELDS:' + path)
        for key, child in value.items():
            if key in properties: _schema(child, properties[key], path + '.' + key, depth + 1)
    if type(value) is list:
        if len(value) < spec.get('minItems', 0) or len(value) > spec.get('maxItems', 100):
            raise AnswerError('ARRAY_BOUNDS:' + path)
        if spec.get('uniqueItems') and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            raise AnswerError('DUPLICATE_ITEMS:' + path)
        for i, child in enumerate(value): _schema(child, spec['items'], path + f'[{i}]', depth + 1)
    if type(value) is str:
        if len(value) < spec.get('minLength', 0) or len(value) > spec.get('maxLength', 1024):
            raise AnswerError('STRING_BOUNDS:' + path)
        if 'pattern' in spec and not re.search(spec['pattern'], value): raise AnswerError('STRING_PATTERN:' + path)
        if spec.get('format') == 'date-time':
            if not CLOCK.fullmatch(value): raise AnswerError('AWARE_RFC3339_REQUIRED:' + path)
            try: time(value)
            except (ValueError, TypeError): raise AnswerError('INVALID_CLOCK:' + path) from None
    if type(value) in (int, float):
        if value < spec.get('minimum', -math.inf) or value > spec.get('maximum', math.inf):
            raise AnswerError('NUMBER_BOUNDS:' + path)


def _record(repo, decision_id):
    if repo is None: raise AnswerError('ORIGINAL_REPOSITORY_REQUIRED')
    try:
        if (repo.db.execute('PRAGMA quick_check').fetchone()[0] != 'ok'
                or repo.db.execute('PRAGMA foreign_key_check').fetchall()):
            raise AnswerError('ORIGINAL_SQL_INTEGRITY_FAILED')
        if not repo.verify(): raise AnswerError('ORIGINAL_LEDGER_INTEGRITY_FAILED')
        d = repo.get('decisions', decision_id)
        p = repo.get('predictions', d['prediction_id'])
        for item in (d, p):
            body = dict(item); identifier = body.pop('id')
            if digest(body) != identifier: raise AnswerError('ORIGINAL_RECORD_ID_MISMATCH')
        dr = repo.db.execute('SELECT * FROM decisions WHERE id=?', (decision_id,)).fetchone()
        pr = repo.db.execute('SELECT * FROM predictions WHERE id=?', (d['prediction_id'],)).fetchone()
        if (d['id'] != decision_id or p['id'] != d['prediction_id']
                or d['match_id'] != p['sports']['match']['id']
                or dr['prediction_id'] != p['id'] or time(dr['at']) != time(d['at'])
                or pr['match_id'] != d['match_id'] or pr['model_id'] != p['model_id']
                or time(pr['at']) != time(p['sealed_at'])
                or not time(p['as_of']) <= time(p['sealed_at']) <= time(d['at'])):
            raise AnswerError('ORIGINAL_RECORD_COLUMN_OR_TIME_MISMATCH')
        return d, p
    except (KeyError, TypeError, ValueError, sqlite3.Error): raise AnswerError('ORIGINAL_RECORD_NOT_VERIFIED') from None


def _day(stamp): return time(stamp).astimezone(ZoneInfo('Europe/Kyiv')).date().isoformat()


def validate_answer(answer, *, expected_fixtures, at=None, repo=None, archive=False):
    _schema(answer, SCHEMA)
    if answer['audit_period'] is not None:
        try: date.fromisoformat(answer['audit_period'])
        except ValueError: raise AnswerError('INVALID_AUDIT_DAY') from None
    if 'NO_VERIFIED_ALTERNATIVE' not in answer['missing_data']:
        raise AnswerError('EXPLICIT_ZERO_ALTERNATIVES_REQUIRED')
    label=answer['fixture_id']
    _schema(expected_fixtures, SCHEMA['properties']['requested_scope'])
    if answer['requested_scope'] != list(expected_fixtures) or answer['fixture_id'] not in expected_fixtures:
        raise AnswerError('ORIGINAL_FIXTURE_SCOPE_MISMATCH')
    now = time((at or datetime.now(timezone.utc)).isoformat())
    replied = time(answer['answered_at'])
    if replied > now: raise AnswerError('FUTURE_ANSWER')
    if not archive and (now - replied).total_seconds() > 120: raise AnswerError('STALE_CURRENT_ANSWER')
    obs, recv = answer['observed_at'], answer['received_at']
    if (obs is None) != (recv is None): raise AnswerError('PAIRED_SOURCE_TIMES_REQUIRED')
    if obs and not time(obs) <= time(recv) <= replied: raise AnswerError('SOURCE_TIME_CONFLICT')
    provenance = ['model_build', 'model_hash', 'code_hash', 'policy_hash', 'forecast_seal_id', 'decision_id', 'core_class']
    if answer['runtime_status'] == 'SEFIROT_NOT_EXECUTED':
        if any(answer[k] is not None for k in provenance): raise AnswerError('FAKE_RUNTIME_PROVENANCE')
        if answer['core_decision'] != 'NO_MODEL_DECISION' or answer['evidence_level'] != 'RESEARCH_ONLY':
            raise AnswerError('NO_MODEL_DECISION_REQUIRED')
        if 'SEFIROT_NOT_EXECUTED' not in answer['missing_data']: raise AnswerError('MISSING_RUNTIME_BLOCKER')
        if answer['data_origin'] != 'UNKNOWN': raise AnswerError('UNKNOWN_DATA_ORIGIN_REQUIRED')
    else:
        if any(answer[k] is None for k in provenance): raise AnswerError('ORIGINAL_IDS_REQUIRED')
        d, p = _record(repo, answer['decision_id'])
        m=p['sports']['match'];label=m['home']+' — '+m['away']+' | '+m['league']+' | '+m['kickoff']
        bindings = {'fixture_id': d['match_id'], 'forecast_seal_id': p['id'],
                    'core_decision': d['decision'], 'core_class': d['class'],
                    'model_hash': p['model_hash'], 'code_hash': p['code_hash'], 'policy_hash': p['policy_hash'],
                    'model_build': {'version': d['version'], 'goal_model': p['policy']['goal_model'], 'executed_at': d['at']},
                    'data_origin': 'SYNTHETIC' if p['synthetic'] else 'ORIGIN_NOT_INDEPENDENTLY_ATTESTED',
                    'evidence_level': 'CORE_PASS' if d['decision'] == 'PASS' else 'CORE_BET'}
        if any(answer[k] != v for k, v in bindings.items()): raise AnswerError('ORIGINAL_CORE_BINDING_MISMATCH')
        if not set(d['limiting_factors']) <= set(answer['missing_data']):
            raise AnswerError('ORIGINAL_CORE_BLOCKERS_REMOVED')
        if answer['phase_source'] == 'ORIGINAL_LEDGER_ARCHIVE':
            if not archive: raise AnswerError('OPERATOR_ARCHIVE_MODE_REQUIRED')
            if (answer['audit_period'] != _day(d['at'])
                    or obs != p['as_of'] or recv != d['at']): raise AnswerError('ARCHIVE_TIME_BINDING_MISMATCH')
            if not p['captured_prematch'] or time(d['at']) >= time(p['sports']['match']['kickoff']):
                raise AnswerError('ORIGINAL_PREMATCH_NOT_VERIFIED')
            if answer['mode'] != 'PREMATCH': raise AnswerError('ARCHIVED_MODE_MISMATCH')
    if answer['phase_source'] == 'NOT_ATTESTED':
        if answer['mode'] != 'HOLD': raise AnswerError('CURRENT_PHASE_SOURCE_NOT_ATTESTED')
        if 'CURRENT_STATUS_NOT_ATTESTED' not in answer['missing_data']:
            raise AnswerError('MISSING_PHASE_BLOCKER')
    elif answer['runtime_status'] != 'ORIGINAL_CORE_RECORD_VERIFIED':
        raise AnswerError('NO_ORIGINAL_PHASE_SOURCE')
    if answer['alternatives_ge_2']:
        for a in answer['alternatives_ge_2']:
            if a['fixture_id'] not in expected_fixtures: raise AnswerError('ALTERNATIVE_FOREIGN_FIXTURE')
        keys = [(a['fixture_id'], a['market_key']) for a in answer['alternatives_ge_2']]
        if len(set(keys)) != len(keys): raise AnswerError('AMBIGUOUS_ALTERNATIVE')
        raise AnswerError('EXTERNAL_PRICE_VERIFIER_NOT_CONNECTED_P0')
    if answer['ticket_record'] is not None:
        # A reported ticket remains a claim, separate from original CORE. P0
        # does not authenticate screenshots or add a financial journal entry.
        if answer['ticket_record']['source_class'] != 'OUR_PARIK24_TICKET':
            raise AnswerError('STAKE_PROPOSAL_IS_NOT_OUR_TICKET')
    live = answer['live_state']
    if live:
        if live['fixture_id'] != answer['fixture_id']: raise AnswerError('LIVE_FIXTURE_CONFLICT')
        conflict = ((live['home_score'], live['away_score'], live['period'], live['minute']) !=
                    (live['quote_home_score'], live['quote_away_score'], live['quote_period'], live['quote_minute']))
        stale = (time(live['observed_at']) > replied or time(live['quote_observed_at']) > replied or
                 (replied-time(live['observed_at'])).total_seconds() > 30 or
                 (replied-time(live['quote_observed_at'])).total_seconds() > 30)
        required = {'LIVE_MODEL_UNVALIDATED'} | ({'LIVE_STATE_CONFLICT'} if conflict else set()) | ({'LIVE_DATA_STALE'} if stale else set())
        if answer['mode'] != 'HOLD' or not required <= set(answer['missing_data']):
            raise AnswerError('LIVE_UNVALIDATED_OR_STATE_CONFLICT')
        if conflict and 'LIVE_STATE_CONFLICT' not in answer['source_conflicts']:
            raise AnswerError('LIVE_STATE_CONFLICT')
    if answer['source_conflicts'] and answer['mode'] != 'HOLD': raise AnswerError('CONFLICT_REQUIRES_HOLD')
    for data in answer['research_checks']:
        quality=preview(data)
        if not set(quality['blockers'])<=set(answer['missing_data']):
            raise AnswerError('SMALL_MARKET_BLOCKERS_NOT_DISCLOSED')
    return VerifiedAnswer(answer, _VERIFIED, label)


def build_answer(fixture_id, fixtures, *, at=None, repo=None, decision_id=None, archive=False):
    now = at or datetime.now(timezone.utc)
    a = {'schema':'sefirot-chat-answer-v1','fixture_id':fixture_id,'requested_scope':list(fixtures),
         'mode':'HOLD','phase_source':'NOT_ATTESTED','observed_at':None,'received_at':None,
         'answered_at':now.isoformat(),'runtime_status':'SEFIROT_NOT_EXECUTED',
         'model_build':None,'model_hash':None,'code_hash':None,'policy_hash':None,
         'forecast_seal_id':None,'decision_id':None,'core_decision':'NO_MODEL_DECISION',
         'core_class':None,'evidence_level':'RESEARCH_ONLY','data_origin':'UNKNOWN',
         'source_conflicts':[],'priced_market_count':0,'alternatives_ge_2':[],
         'missing_data':['SEFIROT_NOT_EXECUTED','CURRENT_STATUS_NOT_ATTESTED','NO_VERIFIED_ALTERNATIVE'],
         'next_action':'OBTAIN_ORIGINAL_CORE_DECISION','ticket_record':None,
         'audit_period':None,'monetary_permission':False,'live_state':None,'research_checks':[]}
    if decision_id:
        d,p = _record(repo,decision_id)
        a.update(runtime_status='ORIGINAL_CORE_RECORD_VERIFIED', model_build={
            'version':d['version'],'goal_model':p['policy']['goal_model'],'executed_at':d['at']},
            model_hash=p['model_hash'],code_hash=p['code_hash'],policy_hash=p['policy_hash'],
            forecast_seal_id=p['id'],decision_id=d['id'],core_decision=d['decision'],core_class=d['class'],
            evidence_level='CORE_PASS' if d['decision']=='PASS' else 'CORE_BET',
            data_origin='SYNTHETIC' if p['synthetic'] else 'ORIGIN_NOT_INDEPENDENTLY_ATTESTED',
            missing_data=sorted(set(d['limiting_factors'])|{'CURRENT_STATUS_NOT_ATTESTED','NO_VERIFIED_ALTERNATIVE'}),
            next_action='READ_ORIGINAL_JOURNAL')
        if archive:
            a.update(mode='PREMATCH',phase_source='ORIGINAL_LEDGER_ARCHIVE',observed_at=p['as_of'],
                     received_at=d['at'],audit_period=_day(d['at']))
            a['missing_data'].remove('CURRENT_STATUS_NOT_ATTESTED')
    return validate_answer(a,expected_fixtures=fixtures,at=now,repo=repo,archive=archive).to_dict()


def render_answer(verified):
    """Render only validate_answer's result at the CLI boundary; no user prose."""
    if not isinstance(verified, VerifiedAnswer): raise AnswerError('VALIDATED_ANSWER_REQUIRED')
    a=verified.to_dict()
    original=a['runtime_status']=='ORIGINAL_CORE_RECORD_VERIFIED'
    source=('оригинальная запись CORE '+a['model_build']['version']+' (архив; '+a['decision_id'][:12]+')'
            if original else 'НЕ ЗАПУЩЕН — SEFIROT_NOT_EXECUTED')
    if a['data_origin']=='SYNTHETIC':source+=' | СИНТЕТИЧЕСКИЙ ТЕСТ'
    elif original:source+=' | происхождение входа отдельно не удостоверено'
    verdict=a['core_decision'] if original else 'НЕ ПОЛУЧЕН'
    action={'OBTAIN_ORIGINAL_CORE_DECISION':'получить оригинальную запечатанную запись CORE',
            'READ_ORIGINAL_JOURNAL':'проверить оригинальный журнал и недостающие данные',
            'REQUEST_SMALL_MARKET_DATA':'получить отдельные данные нужного малого рынка',
            'WAIT_FOR_VALIDATED_LIVE_MODEL':'дождаться независимой проверенной LIVE-модели'}[a['next_action']]
    priority=a['source_conflicts']+[c for c in ('SEFIROT_NOT_EXECUTED','LIVE_MODEL_UNVALIDATED','CURRENT_STATUS_NOT_ATTESTED') if c in a['missing_data']]+a['missing_data']
    blockers=list(dict.fromkeys(priority))
    lines=[f"Матч: {verified.fixture_label} | Режим: {a['mode']}",
           f"Источник: {source}; ответ на {a['answered_at']}",
           f"SEFIROT: {verdict} | класс {a['core_class'] or '—'} | текущий денежный допуск: false",
           'Точная линия: НЕ ПОДТВЕРЖДЕНА',
           'Альтернативы >=2.00: НЕТ — NO_VERIFIED_ALTERNATIVE',
           'Блокеры: '+', '.join(blockers[:3]),
           'Следующий шаг: '+action+'.']
    if a['live_state']:
        s=a['live_state'];lines.insert(6,f"LIVE: {s['home_score']}:{s['away_score']}, {s['minute']}' {s['period']}; красные {s['red_home']}:{s['red_away']}; обновление {s['observed_at']}, линия {s['quote_observed_at']} | НЕ ПОДТВЕРЖДЁН; LIVE_MODEL_UNVALIDATED")
    return '\n'.join(lines)
