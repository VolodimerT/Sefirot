"""Fail-closed external corner feed adapter; retrospective match dates are not seal times."""
from __future__ import annotations
import csv
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo
from .corners_shadow import CornerMatch, utc

REQUIRED_FIELDS=frozenset({"id","matchDate","Season","homeTeam","awayTeam",
                           "HCFT","ACFT","HC1H","AC1H","HC2H","AC2H"})

@dataclass(frozen=True)
class ImportResult:
    rows: tuple[CornerMatch,...]
    source: str
    acquired_at: datetime
    content_sha256: str
    statuses: tuple[str,...]
    dropped: tuple[tuple[int,str],...]
    monetary_permission: bool = False

def load_footiqo_csv(path: str|Path, *, acquired_at: datetime,
                     fixture_timezone: str, league: str,
                     source_id: str="footiqo-user-export",
                     allow_partial: bool=False) -> ImportResult:
    """Load an explicitly acquired full CSV. Never invent historic available_at.

    Source matchDate timezone is ambiguous. Require independently documented timezone.
    Archive rows become known at acquired_at, not at their historic kickoff.
    """
    at=utc(acquired_at,"acquired_at")
    if at>datetime.now(timezone.utc)+timedelta(minutes=3):
        raise ValueError("acquisition timestamp cannot be future")
    if not fixture_timezone or not league or not source_id:
        raise ValueError("explicit timezone, league and source ID required")
    try: tz=ZoneInfo(fixture_timezone)
    except (KeyError,ValueError) as exc: raise ValueError("unknown fixture timezone") from exc
    raw=Path(path).read_bytes()
    if len(raw)>100_000_000: raise ValueError("unbounded input file")
    try: decoded=raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc: raise ValueError("CSV must be UTF-8") from exc
    reader=csv.DictReader(decoded.splitlines(),strict=True)
    if not reader.fieldnames or not REQUIRED_FIELDS.issubset(reader.fieldnames):
        raise ValueError("missing required full-time / first-half / second-half corner fields")
    if len(reader.fieldnames)!=len(set(reader.fieldnames)):
        raise ValueError("duplicate column names")
    data,dropped,seen=[],[],set()
    for line_no,r in enumerate(reader,start=2):
        try:
            if r.get(None) is not None: raise ValueError("excess columns")
            if not all(r.get(k) is not None and str(r[k]).strip() for k in REQUIRED_FIELDS):
                raise ValueError("missing corner or fixture value")
            fid=str(r["id"]).strip()
            if fid in seen: raise ValueError("duplicate fixture ID")
            seen.add(fid)
            year=int(str(r["Season"]).strip())
            naive=datetime.strptime(r["matchDate"].strip(),"%d-%m-%y %H:%M")
            if naive.year!=year: raise ValueError("season and kickoff year conflict")
            local=naive.replace(tzinfo=tz)
            ko=utc(local,"kickoff")
            if local.astimezone(tz).replace(tzinfo=None)!=naive:
                raise ValueError("invalid local timestamp")
            if ko+timedelta(hours=2)>at:
                raise ValueError("future or unfinished match in dataset")
            hft,aft,h1,a1,h2,a2=(int(r[k]) for k in
                         ("HCFT","ACFT","HC1H","AC1H","HC2H","AC2H"))
            if h1+h2!=hft or a1+a2!=aft:
                raise ValueError("FT != 1H + 2H corners")
            data.append(CornerMatch(f"{source_id}:{fid}",league,
                        r["homeTeam"].strip(),r["awayTeam"].strip(),ko,at,
                        hft,aft,h1,a1,source_id))
        except (ValueError,TypeError,OverflowError) as exc:
            if not allow_partial or "duplicate fixture ID" in str(exc):
                raise ValueError(f"CSV line {line_no}: {exc}") from exc
            dropped.append((line_no,str(exc)))
    if len(data)!=len(set(x.fixture_id for x in data)):
        raise ValueError("duplicate ID in imported sample")
    return ImportResult(tuple(sorted(data,key=lambda x:(x.kickoff,x.fixture_id))),
                        source_id,at,sha256(raw).hexdigest(),
                        ("ARCHIVED_NOT_HISTORICALLY_SEALED",
                         "NO_INDEPENDENT_FIXTURE_COVERAGE_CHECK",
                         "RESEARCH_UNVALIDATED"),tuple(dropped))

def coverage_report(rows: tuple[CornerMatch,...], *, expected: set[str]|None,
                    source_accepted: bool=False, min_fraction: float=.98) -> dict:
    """Expected fixture IDs must be independently verified and harmonized."""
    if not 0<min_fraction<=1: raise ValueError("bad minimum coverage")
    actual=[r.fixture_id for r in rows]
    if len(actual)!=len(set(actual)): raise ValueError("duplicate rows")
    if expected is None:
        return {"status":"COVERAGE_UNKNOWN","n":len(rows),"expected":None,
                "coverage_fraction":None,"monetary_permission":False}
    if not expected: raise ValueError("empty independent fixture manifest")
    if not all(isinstance(x,str) and x for x in expected):
        raise ValueError("invalid fixture IDs")
    missing=sorted(expected-set(actual))
    unexpected=sorted(set(actual)-expected)
    ratio=(len(expected)-len(missing))/len(expected)
    status=("RESEARCH_DATA_READY" if source_accepted and
            ratio>=min_fraction and not unexpected else "INCOMPLETE_OR_UNLICENSED")
    return {"status":status,"n":len(actual),"expected":len(expected),
            "coverage_fraction":ratio,"missing_ids":missing,"extra_ids":unexpected,
            "provenance_accepted":source_accepted,"monetary_permission":False}
