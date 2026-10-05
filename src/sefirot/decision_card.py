"""Arbiter presentation of sealed decisions; no model, veto or betting authority."""
from .probability import price_requirements
from .action_plan import passport, action_plan, PRICE_CODES


RECALCULATE_CODES={'PROBABILITY_RECALCULATION_REQUIRED','SPORTS_CHANGED_RECALCULATE',
                   'MODEL_MATCHUP_CONFLICT','MODEL_MARKET_DIVERGENCE',
                   'DIVERGENCE_NEEDS_CORROBORATION','THESIS_REPLACEMENT_GUARD',
                   'UNRESOLVED_CONFLICT','UNKNOWN_CONTEXT','UNEXPLAINED_LINE_MOVEMENT'}
VERDICTS={'playable':'играбельно','playable with conditions':'только с оговорками',
          'skip':'пропуск','unplayable':'неиграбельно'}
REASON_TEXT={
    'SCENARIO_MARKET_CONFLICT':'рынок нарушает зафиксированный запрет на результатную ставку',
    'SCENARIO_CONSTRAINT_UNVERIFIED':'ограничение сценария требует свежих подтверждённых фактов',
    'ROBUST_EV_INSUFFICIENT':'цена не проходит Base/Low EV',
    'DEATH_TEST_PRICE_FRAGILITY':'цена не выдерживает стресс-сценарий',
    'CALIBRATION_INSUFFICIENT':'недостаточно калибровочных данных',
    'STRESS_CALIBRATION_INSUFFICIENT':'недостаточно калибровки стресс-сценариев',
    'GRADED_DEATH_TEST_UNVALIDATED':'стресс-класс не прошёл независимую проверку',
    'DEATH_TEST_SEVERE_FRAGILITY':'цена не проходит нижний предел стресс-EV',
    'PROFILE_MODEL_UNFITTED':'модель профиля турнира не обучена',
    'THRESHOLD_MODEL_UNFITTED':'не обучены вероятности порогов голов',
    'THRESHOLD_STRESS_BIN_UNFITTED':'не обучены пороги голов для стресс-сценариев',
    'GOAL_ARTIFACT_SYNTHETIC_RESEARCH_ONLY':'модель голов обучена на синтетических данных',
    'UNCERTAINTY_TOO_WIDE':'слишком широкий диапазон вероятности',
    'HOLDOUT_UNVALIDATED':'модель не прошла независимую проверку',
    'CONTEXT_UNKNOWN':'компетенция в этом контексте неизвестна',
    'CONTEXT_WEAK':'модель слаба в этом контексте',
    'CONTEXT_FROZEN':'контекст временно отключён',
    'SEPHIRA_HISTORY_INSUFFICIENT':'не хватает проверенной истории подсистем',
    'POLICY_NOT_APPROVED':'версия политики не утверждена',
    'SYNTHETIC_DATA_RESEARCH_ONLY':'синтетические данные: только исследование',
    'RETROSPECTIVE_CAPTURE':'прогноз зафиксирован после доступного прематч-окна',
    'INSUFFICIENT_HISTORY':'недостаточно истории команд',
    'COMPETITION_PROFILE_UNKNOWN':'не определён профиль турнира',
    'PROBABILITY_RECALCULATION_REQUIRED':'нужен новый прогноз по спортивным данным',
    'SPORTS_CHANGED_RECALCULATE':'изменились спортивные факты',
    'MODEL_MATCHUP_CONFLICT':'модель конфликтует с данными о противостоянии',
    'MODEL_MARKET_DIVERGENCE':'экстремальное расхождение модели и рынка',
    'DIVERGENCE_NEEDS_CORROBORATION':'нужны независимые подтверждения фактов',
    'THESIS_REPLACEMENT_GUARD':'нужно перепроверить общий тезис связанных рынков',
    'UNKNOWN_CONTEXT':'новый или резко изменившийся контекст',
    'UNEXPLAINED_LINE_MOVEMENT':'не объяснено движение линии',
    'UNRESOLVED_CONFLICT':'не разрешён конфликт источников',
    'PRICE_STALE':'коэффициент устарел',
    'MISSING_CURRENT_PRICE':'нет актуального коэффициента',
    'MARKET_REFERENCE_MISSING':'нет корректного рыночного ориентира',
    'JOURNAL_INTEGRITY':'нарушена целостность журнала',
    'RECHECK_STALE':'предматчевая перепроверка устарела',
    'RECHECK_FACT_STALE':'предматчевые факты устарели',
    'RISK_LIMIT':'не пройден лимит риска',
    'MATCHUP_SUPPORT_INSUFFICIENT':'данные о противостоянии недостаточно подтверждены',
    'CRITICAL_EVIDENCE_UNRELIABLE':'критический источник ненадёжен',
    'FIXTURE_IDENTITY_CONFLICT':'данные относятся к другому матчу',
    'LINEUP_NOT_CONFIRMED':'состав не подтверждён',
    'INJURY_REPORT_INCOMPLETE':'сведения о травмах неполные',
    'TACTICAL_FIT_UNSUPPORTED':'тактический сценарий не подтверждён',
    'SCORE_TAIL_TOO_LARGE':'слишком велика неучтённая вероятность крупных счетов',
    'LIVE_FORBIDDEN':'прематч-окно закрыто',
    'UNSUPPORTED_FORMAT':'формат матча не поддерживается',
}


def candidate_rank(candidate):
    """Admitted markets: conservative EV first; protection breaks exact ties.

    All sporting gates run before this ranking. No tolerance or new numeric
    threshold is inferred from the already-seen audit outcomes.
    """
    return (-candidate['ev_low'],-candidate['stress_ev_min'],-candidate['ev'],
            candidate['base'][2],candidate['additional_assumptions'],candidate['key'])


def _codes(issues):
    return sorted({i['code'] for i in issues if i['severity']=='BLOCK'})


def _status(candidate,global_codes,policy):
    codes=set(global_codes)|set(_codes(candidate['issues']))
    if codes&RECALCULATE_CODES:return 'RECALCULATE'
    if codes-PRICE_CODES-{'NO_ADMISSIBLE_MAIN_MARKET','RISK_LIMIT'}:return 'NOT_EVALUABLE'
    if 'RISK_LIMIT' in codes:return 'RISK_LIMIT'
    if candidate.get('ev') is None:return 'PRICE_MISSING'
    if candidate['ev']<policy.min_ev:return 'NO_EDGE'
    if codes&{'ROBUST_EV_INSUFFICIENT','DEATH_TEST_PRICE_FRAGILITY','DEATH_TEST_SEVERE_FRAGILITY'}:return 'PRICE_FRAGILE'
    if codes&PRICE_CODES:return 'PRICE_RECHECK'
    return 'ADMISSIBLE'


def build_card(decision,prediction,policy):
    """Use the recorded prematch inputs only; never look at results or new odds."""
    global_codes=_codes(decision['issues'])
    rows=[]
    for c in decision['candidates']:
        local=_codes(c['issues'])
        low=c.get('admission_low',c['calibration_low'] if policy.stress_mode=='GRADED' else c['low'])
        high=c.get('admission_high',c['calibration_high'] if policy.stress_mode=='GRADED' else c['high'])
        thresholds=price_requirements(c['base'],low,high,c['stress_probabilities'],policy)
        status=_status(c,global_codes,policy)
        rows.append({'market':c['key'],'status':status,'eligible':c['eligible'],
                     'odds':c.get('odds'),'implied_probability':c.get('implied_probability'),
                     'raw_probability':c['raw'][0],'model_probability':c['base'][0],
                     'push_probability':c['base'][1],'loss_probability':c['base'][2],
                     'probability_low':c['low'][0],'probability_high':c['high'][0],
                     'admission_probability_low':low[0],'admission_probability_high':high[0],
                     'probability_bound_basis':c.get('probability_bound_basis','CALIBRATION_ONLY' if policy.stress_mode=='GRADED' else 'CALIBRATION_AND_SENSITIVITY'),
                     'calibration':c['calibration'],'fair_odds':c.get('fair_odds'),
                     'ev':c.get('ev'),'ev_low':c.get('ev_low'),
                     'edge':c.get('edge'),'market_reference':c.get('market_reference'),
                     'stress_ev_min':c.get('stress_ev_min'),
                     'stress_class':c.get('stress_grade',{}).get('class'),
                     'price_requirements':thresholds,
                     'blockers':local,'effective_blockers':sorted(set(global_codes)|set(local)),
                     'price_only_recheck':status in ('PRICE_FRAGILE','PRICE_RECHECK','PRICE_MISSING','NO_EDGE'),
                     'tactical_fit':{'scenario':prediction['scenario']['type'],
                                     'fact_id':prediction['witness']['resolved'].get('tactics',{}).get('id'),
                                     'status':'RECHECK_REQUIRED' if status in ('RECALCULATE','NOT_EVALUABLE') else 'SPORTS_GATES_CHECKED'},
                     'public_trap':c.get('public_trap'),
                     'death_test':{'loss_branches':c['counterexamples'],
                                   'stress_ev_min':c.get('stress_ev_min')},
                     'admission_permission':decision['decision']=='BET' and c['key']==decision['selected_market']})
    ranked=sorted([c for c in decision['candidates'] if c.get('ev') is not None
                   and not any(i['code']=='SCENARIO_MARKET_CONFLICT' for i in c['issues'])],key=candidate_rank)
    actionable={r['market'] for r in rows if r['price_only_recheck'] or r['status']=='ADMISSIBLE'}
    research=next((c for c in ranked if c['ev']>=policy.min_ev and c['key'] in actionable),None)
    if research is None:research=next((c for c in ranked if c['ev']>=policy.min_ev),None)
    screened=decision.get('screened_market',decision['selected_market'])
    selected=next((r for r in rows if r['market']==screened),None)
    # A numerical candidate stays visible even when unvalidated. Its label and
    # admission_permission explicitly prevent it from becoming a recommendation.
    research_row=next((r for r in rows if research and r['market']==research['key']),None)
    if decision['decision']=='BET':status='BET'
    elif set(global_codes)&RECALCULATE_CODES or any(r['status']=='RECALCULATE' for r in rows):status='RECALCULATE'
    elif selected:status=selected['status']
    elif any(r['status']=='PRICE_FRAGILE' for r in rows):status='PRICE_FRAGILE'
    elif any(r['status']=='NO_EDGE' for r in rows):status='NO_EDGE'
    elif any(r['status'] in ('PRICE_MISSING','PRICE_RECHECK') for r in rows):status='PRICE_RECHECK'
    else:status='NOT_EVALUABLE'
    focus=selected or research_row
    relevant=focus['effective_blockers'] if focus else sorted(set(global_codes)|{code for r in rows for code in r['blockers']})
    actions={
        'BET':'Использовать только выбранный рынок и лимит ставки; перед входом проверить цену.',
        'RECALCULATE':'Перепроверить спортивные факты; при подтверждённом изменении создать новую прематч-ревизию.',
        'PRICE_FRAGILE':'Перепроверить цену до начала матча; новый коэффициент требует полного decide.',
        'NO_EDGE':'Пропустить по текущей цене; пересмотр возможен только в запечатанном пуле.',
        'PRICE_RECHECK':'Получить свежую полную котировку и повторить предматчевую перепроверку.',
        'RISK_LIMIT':'Пропустить: текущая экспозиция или просадка не допускают ставку.',
        'NOT_EVALUABLE':'Закрыть пробелы данных, калибровки и валидации; текущий расчёт не даёт допуска.',
    }
    tasks=action_plan(relevant,prediction['sports']['match']['kickoff'],decision['at'])
    return {'schema':'decision-card-v1','version':decision['version'],'decision':decision['decision'],
            'passport':passport(prediction),'action_plan':tasks,
            'stage':'FINAL' if decision['decision']=='BET' else 'PREVIEW' if status in ('RECALCULATE','NOT_EVALUABLE') else 'READY',
            'verdict':decision['verdict'],'verdict_ru':VERDICTS[decision['verdict']],
            'class':decision['class'],'status':status,'at':decision['at'],
            'match':prediction['sports']['match'],
            'selected_market':decision['selected_market'] if decision['decision']=='BET' else None,
            'screened_market':screened,
            'research_candidate':research_row,'stake':decision['risk']['stake'],
            'reasons':[{'code':code,'text':REASON_TEXT.get(code,code)} for code in relevant if code!='NO_ADMISSIBLE_MAIN_MARKET'],
            'next_action':actions[status],'deadline':prediction['sports']['match']['kickoff'],
            'alternatives':rows,'selection_rule':decision['selection_reason'],
            'execution_enabled':False,'price_threshold_is_permission':False,
            'result_data_used':False}


def render_card(card):
    """Concise Russian CLI output; JSON card keeps the full evidence."""
    match=card['match']
    lines=[f"{match['home']} — {match['away']}",
           f"Вердикт: {card['verdict_ru']} | {card['decision']} | класс {card['class']} | {card['status']}"]
    if card.get('passport'):
        identity=card['passport']
        lines.append(f"Сборка {identity['version']} / {identity['code_hash'][:12]}; модель {identity['model_hash'][:12]}; калибратор {identity['calibrator_hash'][:12] if identity['calibrator_hash'] else 'нет'}.")
    focus=next((r for r in card['alternatives'] if r['market']==card['selected_market']),None)
    if focus:lines.append('Выбранный рынок: '+focus['market'])
    elif card['research_candidate']:
        focus=card['research_candidate'];lines.append('Кандидат для проверки (допуска нет): '+focus['market'])
    if focus and focus['odds'] is not None:
        lines.append(f"КФ {focus['odds']:.3f}; implied {focus['implied_probability']:.2%}; модель {focus['model_probability']:.2%}; PUSH {focus['push_probability']:.2%}")
        lines.append(f"Base EV {focus['ev']:+.2%}; Low EV {focus['ev_low']:+.2%}; stress {focus['stress_ev_min']:+.2%}; {focus['stress_class']}")
        if focus['fair_odds'] is not None:lines.append(f"Fair {focus['fair_odds']:.3f}; edge {focus['edge']:+.2%}.")
        floor=focus['price_requirements']['required_odds']
        lines.append(f"Порог только по цене: {floor:.4f}; все проверки допуска сохраняются." if floor is not None else 'Конечного порога цены нет при текущем диапазоне вероятности.')
    if card['reasons']:lines.append('Причины: '+'; '.join(r['text'] for r in card['reasons']))
    for task in card.get('action_plan',[]):
        lines.append(task['category']+': '+task['action'])
    lines.append(f"Лимит ставки: {card['stake']:.2f}. {card['next_action']}")
    return '\n'.join(lines)
