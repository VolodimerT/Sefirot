"""Evidence tasks and build identity; presentation never grants admission."""
from .contracts import digest, time


def passport(prediction):
    return {'version': prediction['version'], 'prediction_id': prediction['id'],
            'code_hash': prediction['code_hash'], 'model_hash': prediction['model_hash'],
            'policy_hash': prediction['policy_hash'], 'policy_version': prediction['policy']['version'],
            'data_hash': digest(prediction['sports']), 'sports_as_of': prediction['as_of'],
            'source_ids': sorted(s['id'] for s in prediction['sports']['sources']),
            'calibrator_hash': prediction['calibrator']['hash'] if prediction['calibrator'] else None,
            'calibration_schema': prediction['calibrator']['version'] if prediction['calibrator'] else None,
            'goal_model_hash': prediction['goal_model']['hash'] if prediction['goal_model'] else None,
            'synthetic': prediction['synthetic']}


MODEL_CODES = {'CALIBRATION_INSUFFICIENT', 'STRESS_CALIBRATION_INSUFFICIENT',
               'HOLDOUT_UNVALIDATED', 'GRADED_DEATH_TEST_UNVALIDATED',
               'CONTEXT_UNKNOWN', 'CONTEXT_WEAK', 'CONTEXT_FROZEN',
               'SEPHIRA_HISTORY_INSUFFICIENT', 'UNCERTAINTY_TOO_WIDE',
               'PROFILE_MODEL_UNFITTED', 'THRESHOLD_MODEL_UNFITTED',
               'THRESHOLD_STRESS_BIN_UNFITTED', 'SCORE_TAIL_TOO_LARGE'}
PRICE_CODES = {'PRICE_STALE', 'MISSING_CURRENT_PRICE', 'MARKET_REFERENCE_MISSING',
               'ROBUST_EV_INSUFFICIENT', 'DEATH_TEST_PRICE_FRAGILITY',
               'DEATH_TEST_SEVERE_FRAGILITY'}
DATA_CODES = {'INSUFFICIENT_HISTORY', 'COMPETITION_PROFILE_UNKNOWN',
              'FIXTURE_IDENTITY_CONFLICT', 'LINEUP_NOT_CONFIRMED',
              'INJURY_REPORT_INCOMPLETE', 'TACTICAL_FIT_UNSUPPORTED',
              'CRITICAL_EVIDENCE_UNRELIABLE', 'MATCHUP_SUPPORT_INSUFFICIENT',
              'PROBABILITY_RECALCULATION_REQUIRED', 'SPORTS_CHANGED_RECALCULATE',
              'MODEL_MATCHUP_CONFLICT', 'MODEL_MARKET_DIVERGENCE',
              'DIVERGENCE_NEEDS_CORROBORATION', 'THESIS_REPLACEMENT_GUARD',
              'UNKNOWN_CONTEXT', 'UNEXPLAINED_LINE_MOVEMENT', 'UNRESOLVED_CONFLICT',
              'RECHECK_STALE', 'RECHECK_FACT_STALE'}


def action_plan(codes, kickoff, at):
    """Unknown blockers require review; they never become price-only tasks."""
    codes = set(codes) - {'NO_ADMISSIBLE_MAIN_MARKET'}
    expired = time(at) >= time(kickoff) or bool(codes & {'LIVE_FORBIDDEN', 'PREMATCH_CLOSED'})
    if expired:
        return [{'category': 'CLOSED', 'codes': sorted(codes), 'priority': 0,
                 'action': 'Прематч закрыт; сохранить результат и аудит, не создавать новый вход.',
                 'source': 'официальный результат и исходный журнал', 'deadline': None,
                 'price_can_resolve': False, 'requires_new_sports_seal': False}]
    groups = {}
    for code in codes:
        if code in {'BUILD_MISMATCH', 'JOURNAL_INTEGRITY'}: category = 'INTEGRITY'
        elif code in {'SYNTHETIC_DATA_RESEARCH_ONLY', 'RETROSPECTIVE_CAPTURE', 'GOAL_ARTIFACT_SYNTHETIC_RESEARCH_ONLY'}: category = 'RESEARCH_ONLY'
        elif code == 'UNSUPPORTED_FORMAT': category = 'CONTRACT'
        elif code in DATA_CODES or code.startswith('MISSING_') and code != 'MISSING_CURRENT_PRICE': category = 'SPORTS_DATA'
        elif code in MODEL_CODES: category = 'MODEL_VALIDATION'
        elif code == 'POLICY_NOT_APPROVED': category = 'POLICY'
        elif code == 'RISK_LIMIT': category = 'RISK'
        elif code in PRICE_CODES: category = 'PRICE'
        else: category = 'REVIEW'
        groups.setdefault(category, []).append(code)
    descriptions = {
        'INTEGRITY': (0, 'Проверить целостность и открыть исходную сборку/политику; не переносить разрешения.', 'архивная сборка и исходный журнал'),
        'RESEARCH_ONLY': (1, 'Сохранить исследовательский результат; для допуска нужны новые реальные предматчевые наблюдения.', 'реальные API-наблюдения и новый независимый период'),
        'CONTRACT': (2, 'Выбрать поддержанный контракт до цены либо оставить пропуск.', 'правила расчёта и контракт рынка'),
        'REVIEW': (3, 'Разобрать неизвестную блокировку; обновление цены не считается исправлением.', 'код причины и доказательства исходного решения'),
        'SPORTS_DATA': (10, 'Получить недостающие спортивные сведения через API; проверить ID, профиль, источники и время. Изменение фактов требует нового seal.', 'API спортивных данных; подтверждённые предматчевые факты'),
        'MODEL_VALIDATION': (20, 'Накопить отдельные калибровочные данные и пройти заранее назначенный будущий holdout нужного контракта и контекста.', 'CALIBRATION/HOLDOUT и проверенная история подсистем'),
        'POLICY': (30, 'Проверить утверждение точной версии политики после эмпирической проверки; высокий EV его не заменяет.', 'реестр политики и результаты независимой проверки'),
        'RISK': (40, 'Проверить банк, просадку и суммарную открытую экспозицию; при превышении лимита пропустить.', 'записанные исполнения и текущий банк'),
        'PRICE': (50, 'Получить свежую полную API-котировку, перепроверить спортивные факты и выполнить новый decide до kickoff.', 'API котировок, точная БК и правила расчёта'),
    }
    price_only = not (codes - PRICE_CODES)
    rows = []
    for category, group in groups.items():
        priority, action, source = descriptions[category]
        deferred = category == 'PRICE' and not price_only
        if deferred: action = 'Отложить запрос цены: сначала закрыть остальные блокировки; коэффициент их не устраняет.'
        rows.append({'category': category, 'codes': sorted(group), 'priority': priority,
                     'action': action, 'source': source,
                     'deadline': None if category in ('MODEL_VALIDATION', 'POLICY', 'RESEARCH_ONLY') else kickoff,
                     'price_can_resolve': category == 'PRICE' and price_only,
                     'deferred': deferred, 'requires_new_sports_seal': category == 'SPORTS_DATA'})
    return sorted(rows, key=lambda r: (r['priority'], r['category']))


def enrich_readiness(view, prediction):
    codes = {b['code'] for row in view['markets'] for b in row['blockers']}
    if view['status'] in ('PREMATCH_CLOSED', 'BUILD_MISMATCH'): codes.add(view['status'])
    plan = action_plan(codes, view['match']['kickoff'], view['at'])
    stage = ('EXPIRED' if view['status'] == 'PREMATCH_CLOSED' else
             'ARCHIVED' if view['status'] == 'BUILD_MISMATCH' else
             'READY' if view['quote_recheck_useful'] else 'PREVIEW')
    return {**view, 'passport': passport(prediction), 'stage': stage, 'action_plan': plan}
