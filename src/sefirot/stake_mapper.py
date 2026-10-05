"""Conservative normalization for experimental Stake sportsbook snapshots.

Only explicitly recognized, regulation-time-like main markets are mapped to
SEFIROT canonical contracts. Small markets are normalized descriptively for
research only; no probability, EV, settlement or monetary permission is
inferred here.
"""
from __future__ import annotations

import re

from .contracts import digest, number
from .markets import market_of


def _specifiers(value):
    if not value:
        return {}
    if not isinstance(value, str):
        return {}
    out = {}
    for part in value.replace("&", "|").split("|"):
        if "=" in part:
            key, val = part.split("=", 1)
            out[key.strip()] = val.strip()
    return out


def _line(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError("invalid Stake line") from None


def _supported_contract(contract):
    try:
        market_of(contract)
    except ValueError:
        return None
    return contract


def _main_market_rows(market, home, away):
    template = market.get("template")
    name = market.get("name")
    outcomes = market.get("outcomes") or []
    specs = _specifiers(market.get("specifiers"))
    rows = []
    rejected = []

    def emit(contract, outcome):
        contract = _supported_contract(contract)
        if contract is None:
            rejected.append({"reason": "UNSUPPORTED_CORE_LINE", "outcome": outcome.get("name")})
            return
        rows.append({
            "market": contract,
            "odds": number(outcome.get("odds"), "Stake decimal odds", 1.00000001, 10000),
            "stake_market_id": market.get("id"),
            "stake_outcome_id": outcome.get("id"),
            "raw_group": market.get("group"),
            "raw_template": template,
            "raw_name": name,
            "raw_specifiers": market.get("specifiers"),
            "custom_bet_available": outcome.get("customBetAvailable"),
        })

    if template == "1x2" and name == "1x2":
        sides = {home: "HOME", "Draw": "DRAW", away: "AWAY"}
        if len(outcomes) != 3 or any(o.get("name") not in sides for o in outcomes):
            return [], [{"reason": "INVALID_1X2_PARTITION"}]
        for outcome in outcomes:
            emit({"kind": "1X2", "side": sides[outcome["name"]]}, outcome)
    elif template == "Draw No Bet" and name == "Draw No Bet":
        sides = {home: "HOME", away: "AWAY"}
        if len(outcomes) != 2 or any(o.get("name") not in sides for o in outcomes):
            return [], [{"reason": "INVALID_DNB_PARTITION"}]
        for outcome in outcomes:
            emit({"kind": "DNB", "side": sides[outcome["name"]]}, outcome)
    elif template == "Both Teams to Score" and name == "Both Teams to Score":
        sides = {"Yes": "YES", "No": "NO"}
        if len(outcomes) != 2 or any(o.get("name") not in sides for o in outcomes):
            return [], [{"reason": "INVALID_BTTS_PARTITION"}]
        for outcome in outcomes:
            emit({"kind": "BTTS", "side": sides[outcome["name"]]}, outcome)
    elif template == "Double Chance" and name == "Double Chance":
        aliases = {
            frozenset((home, "Draw")): "1X",
            frozenset(("Draw", away)): "X2",
            frozenset((home, away)): "12",
        }
        if len(outcomes) != 3:
            return [], [{"reason": "INVALID_DOUBLE_CHANCE_PARTITION"}]
        for outcome in outcomes:
            parts = [part.strip() for part in str(outcome.get("name", "")).split(" or ")]
            side = aliases.get(frozenset(parts)) if len(parts) == 2 else None
            if side is None:
                return [], [{"reason": "UNKNOWN_DOUBLE_CHANCE_OUTCOME", "outcome": outcome.get("name")}]
            emit({"kind": "DOUBLE_CHANCE", "side": side}, outcome)
    elif template == "Asian Total" and name == "Asian Total":
        total = _line(specs.get("total"))
        if len(outcomes) != 2:
            return [], [{"reason": "INVALID_TOTAL_PARTITION"}]
        for outcome in outcomes:
            raw = str(outcome.get("name", ""))
            side = "OVER" if raw.startswith("Over ") else "UNDER" if raw.startswith("Under ") else None
            if side is None:
                return [], [{"reason": "UNKNOWN_TOTAL_OUTCOME", "outcome": raw}]
            emit({"kind": "TOTAL", "side": side, "line": total}, outcome)
    elif template == "Asian Handicap" and name == "Asian Handicap":
        home_line = _line(specs.get("hcp"))
        if len(outcomes) != 2:
            return [], [{"reason": "INVALID_HANDICAP_PARTITION"}]
        for outcome in outcomes:
            raw = str(outcome.get("name", ""))
            if raw.startswith(home + " "):
                emit({"kind": "HANDICAP", "side": "HOME", "line": home_line}, outcome)
            elif raw.startswith(away + " "):
                emit({"kind": "HANDICAP", "side": "AWAY", "line": -home_line}, outcome)
            else:
                return [], [{"reason": "UNKNOWN_HANDICAP_OUTCOME", "outcome": raw}]
    return rows, rejected


def _small_market_rows(market, home, away):
    name = str(market.get("name", ""))
    template = str(market.get("template", ""))
    specs = _specifiers(market.get("specifiers"))
    outcomes = market.get("outcomes") or []
    rows = []

    def add(metric, scope, period, operator, threshold, outcome, *, category="THRESHOLD"):
        rows.append({
            "metric": metric,
            "scope": scope,
            "period": period,
            "category": category,
            "operator": operator,
            "threshold": threshold,
            "odds": number(outcome.get("odds"), "Stake decimal odds", 1.00000001, 10000),
            "stake_market_id": market.get("id"),
            "stake_outcome_id": outcome.get("id"),
            "raw_group": market.get("group"),
            "raw_template": template,
            "raw_name": name,
            "raw_specifiers": market.get("specifiers"),
            "custom_bet_available": outcome.get("customBetAvailable"),
        })

    shot = re.fullmatch(r"Match (\d+)\+ shots", name, re.I)
    if shot and len(outcomes) == 1 and outcomes[0].get("name") == "Yes":
        add("SHOTS", "MATCH", "REGULATION_90", "GTE", int(shot.group(1)), outcomes[0])
        return rows

    def total_pair(metric, period):
        try:
            line = _line(specs.get("total"))
        except ValueError:
            return
        for outcome in outcomes:
            raw = str(outcome.get("name", ""))
            side = "OVER" if raw.startswith("Over ") else "UNDER" if raw.startswith("Under ") else None
            if side:
                add(metric, "MATCH", period, side, line, outcome)

    if template == "Total Corners" and name == "Total Corners":
        total_pair("CORNERS", "REGULATION_90")
    elif template == "1st Half - Total Corners" and name == "1st Half - Total Corners":
        total_pair("CORNERS", "FIRST_HALF")
    elif template == "Total Cards" and name == "Total Cards":
        total_pair("CARDS", "REGULATION_90")
    elif template == "1st Half - Total Cards" and name == "1st Half - Total Cards":
        total_pair("CARDS", "FIRST_HALF")

    # Preserve team corner ranges as categorical research data; do not pretend
    # the middle buckets are ordinary over/under lines.
    for team, scope in ((home, "HOME"), (away, "AWAY")):
        if template == "{$competitor1} Corner Range" and scope == "HOME" or \
           template == "{$competitor2} Corner Range" and scope == "AWAY":
            if name == f"{team} Corner Range":
                for outcome in outcomes:
                    rows.append({
                        "metric": "CORNERS", "scope": scope, "period": "REGULATION_90",
                        "category": "RANGE", "operator": "RANGE", "threshold": outcome.get("name"),
                        "odds": number(outcome.get("odds"), "Stake decimal odds", 1.00000001, 10000),
                        "stake_market_id": market.get("id"), "stake_outcome_id": outcome.get("id"),
                        "raw_group": market.get("group"), "raw_template": template,
                        "raw_name": name, "raw_specifiers": market.get("specifiers"),
                        "custom_bet_available": outcome.get("customBetAvailable"),
                    })
                break
    return rows


def normalize_snapshot(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get("provider") != "STAKE_GRAPHQL_EXPERIMENTAL":
        raise ValueError("Stake research snapshot required")
    if snapshot.get("status") != "RESEARCH_ONLY" or snapshot.get("monetary_permission") is not False:
        raise ValueError("Stake snapshot safety flags missing")
    home = snapshot.get("home"); away = snapshot.get("away")
    if not isinstance(home, str) or not isinstance(away, str) or home == away:
        raise ValueError("invalid Stake fixture teams")
    markets = snapshot.get("markets")
    if not isinstance(markets, list) or len(markets) > 5000:
        raise ValueError("invalid Stake market list")

    main = []
    small = []
    rejected = []
    seen_main = set()
    for market in markets:
        if not isinstance(market, dict):
            continue
        rows, reasons = _main_market_rows(market, home, away)
        for row in rows:
            key = market_of(row["market"]).key
            fingerprint = (key, row["stake_market_id"], row["stake_outcome_id"])
            if fingerprint in seen_main:
                rejected.append({"reason": "DUPLICATE_MAIN_OUTCOME", "key": key})
                continue
            seen_main.add(fingerprint)
            row["key"] = key
            main.append(row)
        for reason in reasons:
            rejected.append({**reason, "raw_template": market.get("template"),
                             "raw_name": market.get("name"),
                             "raw_specifiers": market.get("specifiers")})
        small.extend(_small_market_rows(market, home, away))

    report = {
        "schema": "stake-normalized-research-v1",
        "provider": "STAKE_GRAPHQL_EXPERIMENTAL",
        "fixture_id": snapshot.get("fixture_id"),
        "stake_event_id": snapshot.get("stake_event_id"),
        "home": home, "away": away, "kickoff": snapshot.get("kickoff"),
        "received_at": snapshot.get("received_at"),
        "freshness": "RECEIPT_TIME_ONLY",
        "settlement_rules": "UNVERIFIED_PROVIDER_WEB_CONTRACT",
        "main_quotes": main,
        "small_quotes": small,
        "rejected": rejected,
        "main_quote_count": len(main),
        "small_quote_count": len(small),
        "monetary_permission": False,
        "execution_enabled": False,
    }
    report["hash"] = digest(report)
    return report
