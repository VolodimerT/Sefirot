"""Bounded, research-only rebuild of SEFIROT source model inputs from cloud archive.

This never calls API-Football, mutates CORE predictions or makes wagers.
The local source Repository is ephemeral on Render Free; the SQL source archive
remains authoritative and is immutable. Source QC failures never become forecasts.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Thread

from sefirot.repository import Repository
from research.football_pipeline import league_view, source_only, sync_archive

LOCAL_SOURCE = Path("/tmp/sefirot-research-football-sources.sqlite")
MAX_PAGES = 4
PAGE_LIMIT = 100


def bootstrap(source_path: Path = LOCAL_SOURCE) -> dict:
    if os.environ.get("SEFIROT_SOURCE_RESEARCH_SYNC", "0") != "1":
        return {"status": "DISABLED", "provider_requests": 0}
    if (os.environ.get("SEFIROT_SOURCE_ARCHIVE") != "1"
            or os.environ.get("SEFIROT_BRIDGE_READ_ONLY") != "1"
            or os.environ.get("SEFIROT_CHAT_JOB_WORKER_MODE") != "sports_probe"):
        return {"status": "MODE_GUARD_STOP", "provider_requests": 0}
    path = Path(source_path)
    if path.is_symlink() or path.exists() and not path.is_file():
        return {"status": "SOURCE_STORAGE_UNSAFE", "provider_requests": 0}
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
    elif os.stat(path).st_mode & 0o077:
        return {"status": "SOURCE_STORAGE_PERMISSIONS", "provider_requests": 0}
    repo = None
    try:
        repo = Repository(path)
        source_only(repo)
        cursor = ""
        added = 0
        complete = False
        for _ in range(MAX_PAGES):
            page = sync_archive(repo, after=cursor, limit=PAGE_LIMIT)
            added += page["added_sources"]
            complete = bool(page["complete"])
            if complete:
                break
            cursor = page["next_after"]
        if not repo.verify():
            raise ValueError("SOURCE_REPOSITORY_INVALID")
        coverage = {}
        if complete:
            for league in (39, 135, 140):
                v = league_view(repo, league, 2026)
                coverage[str(league)] = {
                    "expected_matches": v["expected_matches"],
                    "calendar_complete": v["calendar_complete"],
                    "observed_matches": v["observed_matches"],
                    "confirmed_ft": v["confirmed_ft"],
                    "statistics_qc_matches": v["statistics_qc_matches"],
                    "qc_rejected_packets": v["qc_rejected_packets"],
                    "pending_qc_packets": v["pending_qc_packets"],
                }
        return {
            "status": "SOURCE_QC_COMPLETE" if complete else "SOURCE_SYNC_PAGE_CAP",
            "new_local_sources": added,
            "complete": complete,
            "next_after": "" if complete else cursor,
            "league_coverage": coverage,
            "provider_requests": 0,
            "model_probability": None,
            "calibration_fit_allowed": False,
            "monetary_permission": False,
        }
    except (ValueError, TypeError, KeyError, RuntimeError, OSError) as exc:
        return {"status": "SOURCE_QC_STOPPED", "error_class": type(exc).__name__,
                "provider_requests": 0, "monetary_permission": False}
    finally:
        if repo is not None:
            repo.close()


def start() -> bool:
    if os.environ.get("SEFIROT_SOURCE_RESEARCH_SYNC", "0") != "1":
        return False

    def run() -> None:
        result = bootstrap()
        print("SEFIROT_SOURCE_RESEARCH_QC=" + json.dumps(
            result, ensure_ascii=True, separators=(",", ":"), allow_nan=False), flush=True)

    Thread(target=run, name="sefirot-source-research-qc", daemon=True).start()
    return True
