"""Reconcile reported singles with recorded decisions; never authorize a bet."""
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .contracts import digest, number, strict, text, time
from .markets import market_of

CENT = Decimal('.01')
OUTCOMES = ('WIN', 'PUSH', 'LOSS', 'VOID', 'PENDING')


def _money(value, name):
    number(value, name, 0, 1e12)
    result = Decimal(str(value))
    if result != result.quantize(CENT):
        raise ValueError(name + ': at most two decimal places required')
    return result


def _recorded_check(ticket, market, service):
    if not ticket.get('decision_id'):
        return 'UNLINKED', ['NO_RECORDED_DECISION_LINK'], []
    if service is None:
        return 'UNVERIFIABLE', ['LEDGER_UNAVAILABLE'], []
    try:
        decision = service.repo.get('decisions', ticket['decision_id'])
        prediction = service.repo.get('predictions', decision['prediction_id'])
    except ValueError:
        return 'UNVERIFIABLE', ['RECORDED_DECISION_NOT_FOUND'], []
    flags = []
    if decision['decision'] != 'BET' or decision['risk']['stake'] <= 0:
        flags.append('RECORDED_NON_BET_ENTRY')
    if ticket['match_id'] != decision['match_id']:
        flags.append('RECORDED_FIXTURE_MISMATCH')
    if market is None:
        flags.append('RECORDED_MARKET_UNMAPPED')
    elif market.key != decision['selected_market']:
        flags.append('RECORDED_MARKET_MISMATCH')
    if Decimal(str(ticket['stake'])) > Decimal(str(decision['risk']['stake'])):
        flags.append('RECORDED_STAKE_LIMIT_EXCEEDED')
    kickoff = prediction['sports']['match']['kickoff']
    if 'kickoff' in ticket and time(ticket['kickoff']) != time(kickoff):
        flags.append('RECORDED_KICKOFF_MISMATCH')
    if 'placed_at' not in ticket:
        flags.append('ENTRY_TIME_UNVERIFIABLE')
    elif time(ticket['placed_at']) < time(decision['at']):
        flags.append('DECISION_RECORDED_AFTER_ENTRY')
    elif time(ticket['placed_at']) >= time(kickoff):
        flags.append('LIVE_ENTRY_FORBIDDEN')
    chosen = next((c for c in decision['candidates'] if c['key'] == decision['selected_market']), None)
    if chosen is not None:
        if Decimal(str(ticket['odds'])) != Decimal(str(chosen['odds'])):
            flags.append('ENTRY_PRICE_CHANGED_NEEDS_RECHECK')
        if 'bookmaker' not in ticket:
            flags.append('ENTRY_BOOKMAKER_UNVERIFIABLE')
        elif ticket['bookmaker'] != chosen['quote']['bookmaker']:
            flags.append('RECORDED_BOOKMAKER_MISMATCH')
    return ('MISMATCH' if flags else 'MATCHES_RECORDED_DECISION'), flags, decision['limiting_factors']


def audit_tickets(dataset, *, service=None, policy=None):
    from .contracts import Policy
    policy = policy or Policy()
    strict(dataset, ('schema', 'status', 'source', 'currency', 'timezone', 'tickets'), ('starting_bankroll',))
    if dataset['schema'] != 'ticket-audit-input-v1' or dataset['status'] != 'REPORTED_UNVERIFIED':
        raise ValueError('reported ticket audit schema required; this is not a certified ledger import')
    text(dataset['source'], 'reported source')
    if not isinstance(dataset['currency'], str) or not re.fullmatch(r'[A-Z]{3}', dataset['currency']):
        raise ValueError('one explicit three-letter currency required')
    try:
        zone = ZoneInfo(dataset['timezone'])
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise ValueError('IANA timezone data required for ticket audit') from None
    tickets = dataset['tickets']
    if not isinstance(tickets, list) or not 1 <= len(tickets) <= 10000:
        raise ValueError('bounded nonempty reported tickets required')
    if service is not None and not service.repo.verify():
        raise ValueError('journal integrity failed')
    bankroll = _money(dataset['starting_bankroll'], 'starting bankroll') if 'starting_bankroll' in dataset else None
    if bankroll is not None and bankroll <= 0:
        raise ValueError('positive starting bankroll required')
    rows, ids = [], set()
    cluster_members, day_members, decision_members = defaultdict(list), defaultdict(list), defaultdict(list)
    turnover = settled_turnover = returns = Decimal(0)
    for ticket in tickets:
        strict(ticket, ('id', 'match_id', 'day', 'odds', 'stake', 'outcome'),
               ('market', 'reported_market', 'decision_id', 'reported_decision', 'reported_flags',
                'placed_at', 'kickoff', 'settled_at', 'bookmaker', 'category'))
        for key in ('id', 'match_id'):
            text(ticket[key], key)
        day = date.fromisoformat(ticket['day']).isoformat()
        if day != ticket['day']:
            raise ValueError('canonical reported ticket day required')
        if ticket['id'] in ids:
            raise ValueError('duplicate reported ticket id')
        ids.add(ticket['id'])
        if ticket['outcome'] not in OUTCOMES:
            raise ValueError('reported settlement outcome required')
        if ('market' in ticket) == ('reported_market' in ticket):
            raise ValueError('one canonical market or unmapped reported market description required')
        market = market_of(ticket['market']) if 'market' in ticket else None
        if market is None:text(ticket['reported_market'], 'unmapped reported market')
        category = ticket.get('category', 'MAIN' if market is not None else 'UNMAPPED')
        if category not in ('MAIN', 'SMALL', 'BUILDER', 'UNMAPPED'):
            raise ValueError('reported category must be MAIN/SMALL/BUILDER/UNMAPPED')
        if (market is not None) != (category == 'MAIN'):
            raise ValueError('MAIN category requires a supported single market contract')
        if ticket['outcome'] == 'PUSH' and market is not None and not market.push_possible:
            raise ValueError('PUSH impossible for reported market contract')
        odds = Decimal(str(number(ticket['odds'], 'reported odds', 1.00000001, 10000)))
        stake = _money(ticket['stake'], 'reported stake')
        if stake <= 0:
            raise ValueError('positive reported stake required')
        for key in ('placed_at', 'kickoff', 'settled_at'):
            if key in ticket:
                time(ticket[key])
        if 'placed_at' in ticket and time(ticket['placed_at']).astimezone(zone).date().isoformat() != day:
            raise ValueError('ticket day differs from placement in reporting timezone')
        if 'settled_at' in ticket:
            if ticket['outcome'] == 'PENDING' or 'placed_at' not in ticket:
                raise ValueError('settlement time requires a settled ticket and placement time')
            if time(ticket['settled_at']) < time(ticket['placed_at']):
                raise ValueError('ticket settlement precedes placement')
        for key in ('decision_id', 'bookmaker', 'reported_decision'):
            if key in ticket:
                text(ticket[key], key)
        reported_flags = ticket.get('reported_flags', [])
        if not isinstance(reported_flags, list) or any(not isinstance(f, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{1,80}', f) for f in reported_flags):
            raise ValueError('reported flag codes required')
        reconciled, flags, blockers = _recorded_check(ticket, market, service)
        if market is None:
            flags.append('REPORTED_MARKET_CONTRACT_UNMAPPED')
        if ticket.get('reported_decision') and ticket['reported_decision'] != 'BET':
            flags.append('REPORTED_NON_BET_ENTRY')
        if 'placed_at' in ticket and 'kickoff' in ticket and time(ticket['placed_at']) >= time(ticket['kickoff']):
            flags.append('LIVE_ENTRY_FORBIDDEN')
        outcome = ticket['outcome']
        returned = (stake * odds).quantize(CENT, rounding=ROUND_HALF_UP) if outcome == 'WIN' else (
            stake if outcome in ('PUSH', 'VOID') else Decimal(0) if outcome == 'LOSS' else None)
        turnover += stake
        if returned is not None:
            settled_turnover += stake
            returns += returned
        row = {'id': ticket['id'], 'match_id': ticket['match_id'], 'day': day,
               'category': category, 'category_provenance': 'CONTRACT' if market is not None else 'REPORTED_UNVERIFIED',
               'market': market.key if market is not None else ticket['reported_market'],
               'market_contract_supported': market is not None,
               'odds': float(odds), 'stake': float(stake), 'outcome': outcome,
               'return': None if returned is None else float(returned),
               'pnl': None if returned is None else float(returned - stake),
               'recorded_decision_check': reconciled, 'process_flags': sorted(set(flags)),
               'recorded_blockers': blockers, 'reported_flags': sorted(set(reported_flags)),
               'timing_status': 'REPORTED' if 'placed_at' in ticket and 'kickoff' in ticket else 'UNVERIFIABLE',
               'decision_quality': 'UNDETERMINED', 'monetary_permission': False}
        rows.append(row)
        cluster_members[ticket['match_id']].append((row, market, stake))
        day_members[day].append((row, stake))
        if ticket.get('decision_id'):
            decision_members[ticket['decision_id']].append((row, stake))
    # Splitting one authorized cap across several receipts cannot multiply it.
    if service is not None:
        for did, members in decision_members.items():
            try:
                cap = Decimal(str(service.repo.get('decisions', did)['risk']['stake']))
            except ValueError:
                continue
            if sum((stake for _, stake in members), Decimal(0)) > cap:
                for row, _ in members:
                    row['process_flags'] = sorted(set(row['process_flags']) | {'RECORDED_DECISION_TOTAL_STAKE_EXCEEDED'})
                    row['recorded_decision_check'] = 'MISMATCH'
    clusters = []
    for mid, members in sorted(cluster_members.items()):
        total = sum((s for _, _, s in members), Decimal(0))
        by_thesis = defaultdict(list)
        for row, market, _ in members:
            if market is not None:by_thesis[(market.kind, market.side)].append((row, market))
        nested = [sorted(r['id'] for r, _ in group) for group in by_thesis.values()
                  if len({m.line for _, m in group}) > 1]
        flags = ['REPEATED_EVENT_EXPOSURE'] if len(members) > 1 else []
        if nested:
            flags.append('NESTED_LINE_DUPLICATE_THESIS')
        if bankroll is not None and total > bankroll * Decimal(str(policy.max_match_fraction)):
            flags.append('REPORTED_EVENT_TURNOVER_ABOVE_POLICY')
        clusters.append({'match_id': mid, 'tickets': [r['id'] for r, _, _ in members],
                         'turnover': float(total),
                         'pnl': float(sum((Decimal(str(r['pnl'] or 0)) for r, _, _ in members), Decimal(0))),
                         'nested_line_ticket_groups': nested, 'flags': flags,
                         'nested_line_check': 'UNVERIFIABLE' if any(m is None for _, m, _ in members) else 'CONTRACTS_CHECKED',
                         'concurrent_exposure': 'NOT_ESTIMATED', 'independence': 'SAME_EVENT'})
    days = []
    for day, members in sorted(day_members.items()):
        total = sum((s for _, s in members), Decimal(0))
        days.append({'day': day, 'turnover': float(total),
                     'starting_bankroll_fraction': float(total / bankroll) if bankroll else None,
                     'flags': ['REPORTED_DAY_TURNOVER_ABOVE_POLICY'] if bankroll is not None and
                              total > bankroll * Decimal(str(policy.max_day_fraction)) else []})
    pnl = returns - settled_turnover
    categories = []
    for category in sorted({r['category'] for r in rows}):
        group = [r for r in rows if r['category'] == category]
        stake_sum = sum((Decimal(str(r['stake'])) for r in group), Decimal(0))
        settled = sum((Decimal(str(r['stake'])) for r in group if r['return'] is not None), Decimal(0))
        returned = sum((Decimal(str(r['return'])) for r in group if r['return'] is not None), Decimal(0))
        categories.append({'category': category, 'tickets': len(group),
                           'outcomes': dict(Counter(r['outcome'] for r in group)),
                           'turnover': float(stake_sum), 'settled_turnover': float(settled),
                           'pending_stake': float(stake_sum-settled), 'returns': float(returned),
                           'pnl': float(returned-settled),
                           'roi_on_settled_turnover': float((returned-settled)/settled) if settled else None})
    issues = sorted({f for row in rows for f in row['process_flags']} |
                    {f for cluster in clusters for f in cluster['flags']} | {f for day in days for f in day['flags']})
    output = {'schema': 'ticket-audit-v1', 'status': 'REPORTED_UNVERIFIED',
              'source': dataset['source'], 'currency': dataset['currency'], 'timezone': dataset['timezone'],
              'dataset_hash': digest(dataset), 'policy_hash': policy.fingerprint, 'tickets': len(rows),
              'distinct_events': len(clusters), 'outcomes': dict(Counter(r['outcome'] for r in rows)),
              'turnover': float(turnover), 'settled_turnover': float(settled_turnover),
              'pending_stake': float(turnover - settled_turnover), 'returns': float(returns), 'pnl': float(pnl),
              'roi_on_settled_turnover': float(pnl / settled_turnover) if settled_turnover else None,
              'process_issues': issues, 'clusters': clusters, 'days': days, 'rows': rows, 'categories': categories,
              'linked_to_ledger': service is not None, 'monetary_permission': False,
              'execution_enabled': False, 'holdout_eligible': False,
              'cross_match_dependence': 'NOT_ASSESSED', 'decision_quality': 'UNDETERMINED',
              'limitations': ['Reported tickets/outcomes are not independently verified',
                             'Distinct events are not proof of independent theses',
                             'Policy turnover caps are unvalidated research diagnostics',
                             'A matching archived decision does not grant current betting permission',
                             'WIN/LOSS alone cannot establish value or a model error']}
    output['hash'] = digest(output)
    return output
