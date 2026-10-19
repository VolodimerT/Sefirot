"""Fail-closed durable snapshots of the original SEFIROT SQLite ledger.

The isolated Supabase bridge acts as a CAS blob store. Restore never relabels
historical predictions or recalculates existing bet probabilities.
"""
from __future__ import annotations
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener
from sefirot.provider_transport import NoRedirect
from sefirot.repository import Repository

MAX_GZIP_BYTES = 2_100_000
MAX_SQLITE_BYTES = 8_000_000
MAX_RESPONSE_BYTES = 4_100_000


class DurableStoreError(RuntimeError):
    """Sanitized transport classification; callers decide whether replay is safe."""
    def __init__(self, message, *, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def _verify_snapshot_bytes(raw):
    """Validate the exact captured bytes in an owned temporary read-only DB."""
    with tempfile.TemporaryDirectory(prefix="sefirot-snapshot-verify-") as directory:
        path = Path(directory) / "snapshot.sqlite"
        path.write_bytes(raw)
        repo = Repository(str(path), read_only=True)
        try:
            if not repo.verify():
                raise ValueError("snapshot journal integrity failed")
        finally:
            repo.close()


def _require_offline_snapshot(path):
    if any(Path(str(path)+suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise RuntimeError("SQLITE_CHECKPOINT_REQUIRES_OFFLINE_SNAPSHOT")


def _read_snapshot_bytes(path):
    with path.open("rb") as handle:
        return handle.read(MAX_SQLITE_BYTES+1)

def configured() -> bool:
    return bool(os.environ.get("SEFIROT_STORE_URL", ""))

def config() -> tuple[str,str]:
    url=os.environ.get("SEFIROT_STORE_URL", "").strip()
    token=os.environ.get("SEFIROT_STORE_TOKEN", "").strip()
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == 'https' and bool(parsed.hostname)
                 and parsed.username is None and parsed.password is None
                 and parsed.port in (None, 443)
                 and parsed.path == '/functions/v1/sefirot-chat-store'
                 and not parsed.query and not parsed.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise RuntimeError("SEFIROT durable store URL unavailable")
    if len(token)<48 or len(token)>128 or not all(c.isascii() and (c.isalnum() or c in "_-") for c in token):
        raise RuntimeError("SEFIROT durable store token unavailable")
    return url,token

def request(payload:dict) -> dict:
    url,token=config()
    message=json.dumps(payload,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode("utf-8")
    if len(message)>2_900_000:raise ValueError("store request exceeds safe size")
    req=Request(url,data=message,method="POST",headers={
        "Content-Type":"application/json",
        "X-Sefirot-Bridge-Store-Token":token,
        "Accept":"application/json"})
    try:
        # Preserve normal proxy/CA settings, but never forward this private
        # header to a redirect destination (including a downgrade to HTTP).
        with build_opener(NoRedirect()).open(req,timeout=20) as response:
            if response.status!=200:raise RuntimeError("durable store refused request")
            raw=response.read(MAX_RESPONSE_BYTES+1)
            if len(raw)>MAX_RESPONSE_BYTES:raise ValueError('store response exceeds safe size')
    except Exception as exc:
        retryable = isinstance(exc, (URLError, OSError, HTTPException))
        if isinstance(exc, HTTPError):
            retryable = exc.code in (500, 502, 503, 504)
            try:
                exc.close()
            except Exception:
                pass
        raise DurableStoreError("SEFIROT_DURABLE_STORE_UNAVAILABLE", retryable=retryable) from None
    try:
        packet=json.loads(raw)
        if not isinstance(packet,dict) or packet.get("ok") is not True or not isinstance(packet.get("data"),dict):
            raise ValueError("missing verified store response")
        return packet["data"]
    except (ValueError,TypeError,KeyError) as exc:
        raise DurableStoreError("SEFIROT_DURABLE_STORE_INVALID_RESPONSE", retryable=True) from None

def restore(path:Path) -> int:
    record=request({"action":"pull"})
    revision=record.get("revision")
    if type(revision) is not int or revision<0:raise RuntimeError("STORE_REVISION_INVALID")
    if revision==0:
        if record.get("snapshot") is not None or record.get("checksum") is not None:
            raise RuntimeError("EMPTY_STORE_CONFLICT")
        return 0
    blob=record.get("snapshot")
    checksum=record.get("checksum")
    if not isinstance(blob,str) or not isinstance(checksum,str) or len(blob)>2_800_000 or len(checksum)!=64:
        raise RuntimeError("STORE_SNAPSHOT_INVALID")
    try:
        packed=base64.b64decode(blob,validate=True)
        if len(packed)>MAX_GZIP_BYTES or hashlib.sha256(packed).hexdigest()!=checksum:
            raise ValueError("checksum mismatch")
        with gzip.GzipFile(fileobj=io.BytesIO(packed),mode="rb") as handle:
            raw=handle.read(MAX_SQLITE_BYTES+1)
        if len(raw)>MAX_SQLITE_BYTES or not raw.startswith(b"SQLite format 3\x00"):
            raise ValueError("SQLite payload invalid")
        _verify_snapshot_bytes(raw)
    except Exception as exc:
        raise RuntimeError("STORE_SNAPSHOT_INTEGRITY_FAILED") from None
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("xb") as stream: stream.write(raw)
    return revision

def checkpoint(path:Path, expected_revision:int) -> int:
    if type(expected_revision) is not int or expected_revision<0:raise ValueError("invalid revision")
    path=Path(path)
    _require_offline_snapshot(path)
    raw=_read_snapshot_bytes(path)
    if len(raw)>MAX_SQLITE_BYTES or not raw.startswith(b"SQLite format 3\x00"):
        raise RuntimeError("SQLITE_CHECKPOINT_TOO_LARGE_OR_INVALID")
    try:
        _verify_snapshot_bytes(raw)
    except Exception:
        raise RuntimeError("SQLITE_CHECKPOINT_INTEGRITY_FAILED") from None
    _require_offline_snapshot(path)
    if _read_snapshot_bytes(path)!=raw:
        raise RuntimeError("SQLITE_CHECKPOINT_CHANGED_DURING_READ")
    packed=gzip.compress(raw,mtime=0)
    if len(packed)>MAX_GZIP_BYTES:raise RuntimeError("SQLITE_COMPRESSED_CHECKPOINT_TOO_LARGE")
    checksum=hashlib.sha256(packed).hexdigest()
    record=request({"action":"save","revision":expected_revision,
                    "snapshot":base64.b64encode(packed).decode("ascii"),
                    "checksum":checksum})
    next_rev=record.get("revision")
    if type(next_rev) is not int or next_rev!=expected_revision+1 or record.get("checksum")!=checksum:
        raise RuntimeError("CHECKPOINT_COMMIT_UNVERIFIED")
    return next_rev
