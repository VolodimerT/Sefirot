"""Loopback-only manual inbox UI; all actions go through the existing worker."""
from datetime import datetime, timezone
from html import escape
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import secrets
import sqlite3
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from .contracts import Policy, time
from .decision_card import render_card
from .repository import Repository
from .service import Service
from .worker import _summary, process_inbox


class Panel:
    def __init__(self, database, directory, policy=None, clock=None):
        self.database=Path(database).resolve();self.directory=Path(directory).resolve()
        self.policy=policy or Policy();self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.token=secrets.token_urlsafe(32);self.last_run=[]

    def snapshot(self):
        # Listing filenames does not open pending quote jobs before capture.
        view={'files':sorted(p.name for p in self.directory.glob('*.json') if p.is_file()),
              'directory':str(self.directory),'records':[],'status':'NO_LEDGER',
              'last_run':self.last_run,'at':self.clock().isoformat()}
        if not self.database.exists():return view
        repo=None
        try:
            repo=Repository(self.database,read_only=True)
            repo.db.execute('BEGIN')  # One consistent read-only snapshot.
            if not repo.verify():raise ValueError('journal integrity failed')
            receipts=sorted(repo.all('jobs',view['at']),key=lambda r:(time(r['at']),r['id']),reverse=True)
            view['recorded_jobs']=len(receipts)
            for r in receipts[:30]:
                row={**_summary(r,'ALREADY_PROCESSED'),'at':r['at'],'job_type':r.get('job_type','LEGACY')}
                view['records'].append(row)
            view['status']='OK'
        except (ValueError,KeyError,TypeError,OSError,sqlite3.Error):
            view.update(status='ERROR',records=[],error='Журнал не прошёл проверку. Обработка остановлена.')
        finally:
            if repo:repo.close()
        return view

    def run(self):
        # Opening the page never creates a ledger. Only the explicit POST runs
        # the unchanged, transactional worker; an empty folder stays read-only.
        if not any(p.is_file() for p in self.directory.glob('*.json')):
            self.last_run=[];return
        before=self.snapshot()
        if before['status']=='ERROR':
            self.last_run=[{'status':'ERROR','error':before['error']}];return
        repo=None
        try:
            self.database.parent.mkdir(parents=True,exist_ok=True)
            repo=Repository(self.database)
            self.last_run=process_inbox(Service(repo,self.policy,self.clock),self.directory)
        except (ValueError,KeyError,TypeError,OSError,sqlite3.Error):
            self.last_run=[{'status':'ERROR','error':'Не удалось открыть журнал. Проверьте файл и доступ.'}]
        finally:
            if repo:repo.close()


STYLE='''
:root{color-scheme:dark;--bg:#101713;--surface:#1a241e;--line:#33463a;--text:#edf4ec;--muted:#a9b7aa;--accent:#c5ec85}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,sans-serif}
main{max-width:1160px;margin:auto;padding:34px 24px 60px}header{display:flex;justify-content:space-between;gap:24px;align-items:center}
h1{font-size:clamp(28px,4vw,42px);letter-spacing:-1px;margin:4px 0}h2{font-size:20px;margin:0 0 16px}p{margin:6px 0}
.eyebrow{color:var(--accent);font-size:12px;letter-spacing:2px;text-transform:uppercase}.muted,small{color:var(--muted)}
.pill{border:1px solid var(--line);border-radius:30px;padding:5px 12px;font-size:12px;white-space:nowrap}
.toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:26px 0 20px}
button,a.button{font:inherit;border:0;border-radius:9px;background:var(--accent);color:#162011;padding:12px 18px;cursor:pointer;text-decoration:none;font-weight:650}
button:disabled{opacity:.4;cursor:default}a.secondary{background:transparent;border:1px solid var(--line);color:var(--text)}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:24px 0}.stat,.box,.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:20px}
.stat strong{display:block;font-size:30px}.stat span{font-size:13px;color:var(--muted)}
.grid{display:grid;grid-template-columns:minmax(0,1fr) 310px;gap:20px}.card{margin-bottom:12px}.cardhead{display:flex;justify-content:space-between;gap:12px}.card h3{font-size:19px;margin:0 0 6px}
.reason{margin-top:12px;color:var(--muted)}.error{border-color:#9f625a;background:#33231f;padding:16px;border-radius:12px;margin:14px 0}
.filename{font-family:ui-monospace,monospace;font-size:13px;overflow-wrap:anywhere;border-top:1px solid var(--line);padding:10px 0}
ol{padding-left:20px}li{margin:10px 0}.path{overflow-wrap:anywhere;font-size:12px;color:var(--muted)}
details{border-top:1px solid var(--line);margin-top:14px;padding-top:12px}summary{cursor:pointer;color:var(--accent)}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 ui-monospace,monospace;color:var(--muted)}
footer{margin-top:24px;padding-top:16px;border-top:1px solid var(--line);font-size:13px;color:var(--muted)}
@media(max-width:760px){main{padding:22px 16px}.grid{grid-template-columns:1fr}header{align-items:flex-start}.stats{gap:8px}.stat{padding:14px}.stat strong{font-size:24px}}
'''


def render_panel(view,token):
    def safe(value):return escape(str(value),quote=True)
    def stamp(value):return time(value).astimezone(ZoneInfo('Europe/Kyiv')).strftime('%d.%m.%Y %H:%M')+' Киев'
    records=[]
    for row in view['records']:
        card=row.get('decision_card');match=card['match'] if card else row.get('match')
        title=f"{match['home']} — {match['away']}" if match else row['id']
        label={'CAPTURE':'Прогноз сохранён','RESULT':'Результат записан','CLOSING':'Цена закрытия записана','LEGACY':'Запись журнала'}.get(row['job_type'],'Решение записано')
        body=f'<p class="muted">{safe(label)} · {safe(stamp(row["at"]))}</p>'
        if card:
            label=card.get('verdict_ru',card['decision'])+' · '+card['class']
            market=card.get('selected_market') or card.get('screened_market')
            body+=f'<p>{safe(market or "Рынок не допущен")}</p>'
            body+='<p class="reason">Сохранённое решение. Для нового входа нужна новая перепроверка.</p>'
            body+=f'<details><summary>Почему такое решение</summary><pre>{safe(render_card(card))}</pre></details>'
        elif 'prediction_id' in row:
            body+='<p>Вероятность зафиксирована до цены. Следующий шаг — цена и перепроверка.</p>'
            if row.get('synthetic'):body+='<p class="reason">Синтетический пример. Денежного допуска нет.</p>'
        records.append(f'<article class="card"><div class="cardhead"><h3>{safe(title)}</h3><span class="pill">{safe(label)}</span></div>{body}<small>Задание: {safe(row["id"])}</small></article>')
    errors=''.join(f'<div class="error">{safe(r.get("file",r.get("id","Очередь")))}: {safe(r["error"])}</div>' for r in view['last_run'] if r['status']=='ERROR')
    if view['status']=='ERROR':errors+=f'<div class="error">{safe(view["error"])}</div>'
    files=''.join(f'<div class="filename">{safe(name)}</div>' for name in view['files']) or '<p class="muted">В папке пока нет JSON-заданий.</p>'
    content=''.join(records) or '<div class="box"><h2>Начните с прогноза</h2><p>Добавьте 01-capture.json со спортивными данными в папку заданий. Затем нажмите «Обработать очередь».</p><p class="reason">Цену и перепроверку добавляйте после сохранения прогноза.</p></div>'
    disabled=' disabled' if not view['files'] or view['status']=='ERROR' else ''
    last=view['last_run'];done=sum(r['status']!='ERROR' for r in last);failed=sum(r['status']=='ERROR' for r in last)
    notice=f'<p class="muted">Последний запуск: обработано или уже сохранено {done}; ошибок {failed}.</p>' if last else '<p class="muted">Обработка запускается только кнопкой. Просмотр страницы ничего не записывает.</p>'
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Сефирот — рабочая очередь</title><style>{STYLE}</style></head><body><main>
<header><div><div class="eyebrow">SEFIROT / PREMATCH</div><h1>Рабочая очередь</h1><p class="muted">Спортивные данные → прогноз → решение → результат</p></div><span class="pill">Локальный режим</span></header>
<div class="toolbar"><form method="post" action="/run"><input type="hidden" name="token" value="{safe(token)}"><button type="submit"{disabled}>Обработать очередь</button></form><a class="button secondary" href="/">Обновить обзор</a></div>{notice}<small>Обзор: {safe(stamp(view['at']))}</small>{errors}
<section class="stats"><div class="stat"><strong>{len(view['files'])}</strong><span>Файлов в папке</span></div><div class="stat"><strong>{view.get('recorded_jobs',0)}</strong><span>Записанных заданий</span></div><div class="stat"><strong>{failed}</strong><span>Ошибок последнего запуска</span></div></section>
<div class="grid"><section><h2>Последние сохранённые записи</h2>{content}</section><aside><section class="box"><h2>Порядок работы</h2><ol><li><b>Спорт.</b> Добавьте CAPTURE без цены.</li><li><b>Seal.</b> Обработайте и сохраните прогноз.</li><li><b>Перепроверка.</b> Добавьте DECIDE с новой ценой и актуальными фактами.</li><li><b>Итог.</b> После матча добавьте RESULT и CLOSING.</li></ol><p class="path">Папка: {safe(view['directory'])}</p></section><section class="box" style="margin-top:16px"><h2>Файлы очереди</h2><p class="muted">Список имён, не проверка содержимого. Обработанные файлы тоже могут остаться здесь.</p>{files}</section></aside></div>
<footer>PASS — нормальный результат анализа. Ошибка задания показана отдельно. Здесь нет исполнителя ставок, LIVE или запросов к API.<br>Показаны последние 30 записей журнала. Сохранённая карточка не подтверждает текущую цену или готовность нового входа.</footer>
</main></body></html>'''


def handler_for(panel):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass

        def setup(self):
            super().setup();self.connection.settimeout(5)

        def send(self,status,body='',*,location=None):
            data=body.encode('utf-8');self.send_response(status)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
            self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
            # A normal form POST under no-referrer has Origin:null (Fetch).
            # same-origin preserves the local Origin required by our CSRF gate.
            self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','same-origin')
            if location:self.send_header('Location',location)
            self.end_headers();self.wfile.write(data)

        def local(self):
            expected=f'127.0.0.1:{self.server.server_port}'
            return self.client_address[0]=='127.0.0.1' and self.headers.get_all('Host')==[expected]

        def do_GET(self):
            if not self.local():self.send(403);return
            if self.path!='/':self.send(404);return
            self.send(200,render_panel(panel.snapshot(),panel.token))

        def do_POST(self):
            if not self.local():self.send(403);return
            origin=f'http://127.0.0.1:{self.server.server_port}'
            if self.headers.get_all('Origin')!=[origin]:self.send(403);return
            if self.path!='/run':self.send(404);return
            if self.headers.get_all('Content-Type')!=['application/x-www-form-urlencoded']:self.send(415);return
            lengths=self.headers.get_all('Content-Length') or []
            if len(lengths)!=1 or self.headers.get('Transfer-Encoding'):
                self.send(400);return
            try:
                size=int(lengths[0])
                if not 0<size<=512:self.send(413);return
                self.connection.settimeout(3)
                data=self.rfile.read(size)
                if len(data)!=size:raise ValueError('incomplete body')
                fields=parse_qs(data.decode('utf-8'),strict_parsing=True,max_num_fields=1,keep_blank_values=True)
                if set(fields)!={'token'} or len(fields['token'])!=1 or not secrets.compare_digest(fields['token'][0].encode('utf-8'),panel.token.encode('ascii')):
                    self.send(403);return
            except (ValueError,UnicodeError,TimeoutError):self.send(400);return
            panel.run();self.send(303,location='/')

        def do_HEAD(self):self.send(405)
        def do_OPTIONS(self):self.send(405)
    return Handler


def make_server(panel,port=8765):
    if type(port) is not int or not 0<=port<=65535:raise ValueError('panel port must be an integer from 0 to 65535')
    server=HTTPServer(('127.0.0.1',port),handler_for(panel))
    server.timeout=1
    return server


def serve(database,directory,policy,port=8765):
    panel=Panel(database,directory,policy)
    with make_server(panel,port) as server:
        print(f'Сефирот: http://127.0.0.1:{server.server_port}/\nОткройте адрес в браузере. Обработка — кнопкой; остановка — Ctrl+C.',flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt:pass
    return 0
