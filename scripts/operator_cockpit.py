"""Read-only mobile subset of the existing chat bridge, offline prototype."""
from pathlib import Path
import argparse
import hmac
import json
import secrets
import sys
import subprocess
import threading
from time import monotonic
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"src"),str(ROOT/"scripts")]
from chat_gateway import Handler, ThreadingHTTPServer, configured_token
from chat_situation import strict_json
from research.prematch_readiness import operator_report

ASSETS=ROOT/"web"/"operator"


def snapshot(database=None, *, at=None):
    report=operator_report(database,at=at,include_market_views=True)
    def git(*args):
        try:return subprocess.check_output(["git",*args],cwd=ROOT,text=True,
            stderr=subprocess.DEVNULL,timeout=2).strip()
        except (OSError,subprocess.SubprocessError):return None
    report["runtime_provenance"]={"head_sha":git("rev-parse","HEAD"),
        "branch":git("branch","--show-current"),"ci_status":"NOT_VERIFIED",
        "ci_evidence":None,"mode":"OFFLINE_READ_ONLY_PROTOTYPE","cloud_runtime_connected":False}
    return report


def make_server(*, database=None, token, at=None, port=0):
    if not isinstance(token,str) or not 32<=len(token)<=256 or any(not 33<=ord(c)<=126 for c in token):
        raise ValueError("OPERATOR_TEST_OR_OWNER_TOKEN_REQUIRED")
    class ReadOnlyHandler(Handler):
        def authenticated(self):
            provided=self.headers.get("Authorization","")
            if provided.startswith("Bearer ") and hmac.compare_digest(provided[7:].encode(),token.encode()):
                return True
            cookies={}
            for part in self.headers.get("Cookie","").split(";"):
                if "=" in part:
                    key,value=part.strip().split("=",1);cookies[key]=value
            with self.server.session_lock:
                expires=self.server.sessions.get(cookies.get("sefirot_operator",""),0)
            if monotonic()<expires:return True
            self.respond(401,{"ok":False,"error":"UNAUTHORIZED","message":"Войдите для просмотра."})
            return False

        def do_GET(self):
            parsed=urlsplit(self.path)
            if parsed.query or parsed.fragment:
                self.respond(403,{"ok":False,"error":"READ_ONLY_SCOPE"});return
            assets={"/":"index.html","/operator.css":"operator.css","/operator.mjs":"operator.mjs"}
            if parsed.path in assets:
                raw=(ASSETS/assets[parsed.path]).read_bytes()
                mime="text/html" if parsed.path=="/" else "text/css" if parsed.path.endswith(".css") else "text/javascript"
                self.send_response(200);self.send_header("Content-Type",mime+"; charset=utf-8")
                self.send_header("Cache-Control","no-store")
                self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
                self.send_header("X-Content-Type-Options","nosniff")
                self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw);return
            if not self.authenticated():return
            if parsed.path!="/api/operator":
                self.respond(403,{"ok":False,"error":"READ_ONLY_SCOPE","message":"Доступен только просмотр."});return
            try:self.respond(200,{"ok":True,"data":snapshot(database,at=at)})
            except Exception:self.respond(503,{"ok":False,"error":"UNAVAILABLE","message":"Данные временно недоступны."})

        def do_POST(self):
            if self.path!="/session":
                if not self.authenticated():return
                self.respond(403,{"ok":False,"error":"READ_ONLY_SCOPE","message":"Запись и LIVE недоступны."});return
            origin="http://127.0.0.1:"+str(self.server.server_port)
            if self.headers.get("Host")!=origin.removeprefix("http://") or self.headers.get("Origin")!=origin:
                self.respond(403,{"ok":False,"error":"ORIGIN_REJECTED"});return
            try:
                size=int(self.headers.get("Content-Length","0"))
                if not 1<=size<=1024 or self.headers.get("Content-Type")!="application/json":
                    raise ValueError("BOUNDED_JSON_REQUIRED")
                value=strict_json(self.rfile.read(size))
                if not isinstance(value,dict) or set(value)!={"token"} or not isinstance(value["token"],str):
                    raise ValueError("SESSION_FIELDS")
                if not hmac.compare_digest(value["token"].encode(),token.encode()):
                    self.respond(401,{"ok":False,"error":"UNAUTHORIZED","message":"Неверный код доступа."});return
            except (ValueError,TypeError):
                self.respond(400,{"ok":False,"error":"SESSION_REQUEST_INVALID"});return
            cookie=secrets.token_urlsafe(32)
            with self.server.session_lock:
                self.server.sessions={k:v for k,v in self.server.sessions.items() if v>monotonic()}
                if len(self.server.sessions)>=32:
                    self.respond(429,{"ok":False,"error":"SESSION_LIMIT"});return
                self.server.sessions[cookie]=monotonic()+600
            self.send_response(204);self.send_header("Cache-Control","no-store")
            # HTTP exception is strictly loopback-only, never a deployed endpoint.
            self.send_header("Set-Cookie","sefirot_operator="+cookie+"; HttpOnly; SameSite=Strict; Path=/; Max-Age=600")
            self.send_header("Content-Length","0");self.end_headers()

        def deny_write(self):
            if self.authenticated():self.respond(403,{"ok":False,"error":"READ_ONLY_SCOPE"})
        def do_PUT(self):self.deny_write()
        def do_PATCH(self):self.deny_write()
        def do_DELETE(self):self.deny_write()
    server=ThreadingHTTPServer(("127.0.0.1",port),ReadOnlyHandler)
    server.sessions={};server.session_lock=threading.Lock()
    return server


def main(argv=None):
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,"reconfigure"):stream.reconfigure(encoding="utf-8")
    p=argparse.ArgumentParser(description="SEFIROT read-only operator: loopback offline review only")
    p.add_argument("--db",type=Path);p.add_argument("--port",type=int,default=8787)
    args=p.parse_args(argv)
    if not 0<=args.port<=65535:p.error("--port must be in 0..65535")
    # Owner config is only read when explicitly running the application.
    # Agent tests supply a synthetic token directly; no credential lookup.
    try:token=configured_token()
    except RuntimeError:
        print("SEFIROT: настройте SEFIROT_BRIDGE_TOKEN для частного просмотра (32–256 ASCII-символов без пробелов).",file=sys.stderr)
        return 2
    try:server=make_server(database=args.db,token=token,port=args.port)
    except (OSError,ValueError):
        print("SEFIROT: не удалось открыть локальный порт; выберите свободный --port.",file=sys.stderr)
        return 2
    try:
        print("SEFIROT: http://127.0.0.1:"+str(server.server_port)+" — только просмотр",flush=True)
        server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
    return 0
if __name__=="__main__":raise SystemExit(main())
