"""SEFIROT CORE: local prematch 1X2 shadow assistant, standard library only."""

from __future__ import annotations

import argparse
# DEPRECATED: use sefirot.py. Planned removal: CORE 3.0, not before 2027-01-01.
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))


def _time(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("time must include a timezone offset")
    return value


def _history(path: Path) -> tuple[HistoricalMatch, ...]:
    from sefirot_core import HistoricalMatch
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("history must be a JSON list")
    return tuple(HistoricalMatch(str(row["match_id"]), _time(row["kickoff"]),
                _time(row["result_received_at"]), row["home_team"], row["away_team"],
                row["home_goals"], row["away_goals"], row["source"]) for row in rows)


def analyze(*, match_id: str, kickoff: datetime, home: str, away: str,
            source: str, published_at: datetime, history_path: Path, journal_path: Path,
            confirmed: bool, reader=input, writer=print,
            clock=lambda: datetime.now(timezone.utc)) -> str:
    """Capture sports data, seal P, *then* ask for the 1X2 line; never authorize bets."""
    from sefirot_core import (CaptureJournal, Fact, InsufficientHistory,
                              SportsOnlySnapshot, ThreeWayQuote, estimate_1x2, seal_estimate)
    if not match_id or not home or not away or home == away or not source:
        raise ValueError("match id, distinct teams and source are required")
    history = _history(history_path)
    now = clock()
    kind = "FACT" if confirmed else "ASSUMPTION"
    snapshot = SportsOnlySnapshot(match_id, kickoff, now, (
        Fact("sports.home_team", home, source, published_at, now, kind),
        Fact("sports.away_team", away, source, published_at, now, kind)))
    journal = CaptureJournal(journal_path, clock=clock)
    journal.capture_snapshot(snapshot)
    writer(f"SEFIROT CORE | {home} — {away} | 1X2 | snapshot {snapshot.digest()[:12]}")
    if not confirmed:
        writer("PASS: источник команд не подтверждён; снимок сохранён как ASSUMPTION.")
        return "PASS"
    try:
        estimate = estimate_1x2(snapshot, history)
    except InsufficientHistory as exc:
        writer(f"PASS: недостаточно проверенной истории ({exc}).")
        return "PASS"
    seal = seal_estimate(snapshot, estimate, clock())
    journal.capture_seal(seal)
    writer("Иллюстративный прогноз запечатан ДО запроса коэффициентов:")
    writer("1 / X / 2: " + " / ".join(f"{p:.1%}" for p in seal.probabilities))
    writer(f"Исторические матчи: {len(estimate.used_matches)}; поздние исключены: {estimate.excluded_future}")
    writer("Интервалы Low/High некалиброваны. Укажите линию 1X2 одного букмекера.")
    bookmaker = reader("Букмекер: ").strip()
    if not bookmaker:
        writer("PASS: букмекер не указан; прогноз остаётся запечатанным.")
        return "PASS"
    try:
        odds = tuple(float(x.replace(",", ".")) for x in reader("Коэффициенты 1 X 2 через пробел: ").split())
        if len(odds) != 3:
            raise ValueError("нужны три коэффициента 1 X 2")
        quote = ThreeWayQuote(bookmaker, clock(), odds)
        quoted = journal.capture_quote(quote)
        assessment = journal.capture_assessment(quoted.hash)
        journal.capture_shadow_decision(assessment.hash, f"shadow-{assessment.hash[:16]}")
    except (ValueError, OverflowError) as exc:
        writer(f"PASS: недопустимая или поздняя линия ({exc}).")
        return "PASS"
    report = assessment.payload["report"]
    if report["overround"] < 0:
        writer("ВНИМАНИЕ: отрицательная маржа набора 1X2; проверьте, что цены взяты одновременно у одного букмекера.")
    writer("Исход | Кэф | Implied P | Model P | EV")
    for name, odd, p in zip(("1", "X", "2"), quote.odds, seal.probabilities):
        key = {"1": "home", "X": "draw", "2": "away"}[name]
        writer(f"{name:>5} | {odd:>4.2f} | {report['implied'][key]:>8.1%} | {p:>7.1%} | {report['ev'][key]:>+7.1%}")
    writer(f"Маржа 1X2: {report['overround']:.1%}; вердикт: PASS — модель не калибрована.")
    writer(f"Журнал: {journal_path}")
    return "PASS"


def _legacy_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SEFIROT CORE: локальный теневой анализ 1X2")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="вымышленный пример без настоящих ставок")
    cmd = sub.add_parser("analyze", help="один реальный матч с вручную проверенным источником")
    for flag in ("match-id", "kickoff", "home", "away", "source", "published-at"):
        cmd.add_argument("--" + flag, required=True)
    cmd.add_argument("--history", type=Path, required=True, help="JSON с историей и временами получения")
    cmd.add_argument("--journal", type=Path, required=True, help="новый JSONL файл одного матча")
    cmd.add_argument("--confirmed", action="store_true", help="вы вручную подтверждаете источник команд")
    args = parser.parse_args(argv)
    if args.command == "demo":
        import runpy
        runpy.run_path(str(Path(__file__).parent / "examples" / "demo.py"), run_name="__main__")
        return 0
    try:
        analyze(match_id=args.match_id, kickoff=_time(args.kickoff), home=args.home,
                away=args.away, source=args.source, published_at=_time(args.published_at),
                history_path=args.history, journal_path=args.journal, confirmed=args.confirmed)
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError, FileExistsError) as exc:
        parser.exit(2, f"SEFIROT PASS: {exc}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    print("DEPRECATED wrapper: use sefirot.py; --legacy selects the historical prototype only.", file=sys.stderr)
    if arguments[:1] == ['--legacy']:
        return _legacy_main(arguments[1:])
    from sefirot.cli import main as canonical_main
    return canonical_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
