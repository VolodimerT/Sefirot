"""Render an offline mobile HTML preview of the daily report."""
import json
from html import escape
from pathlib import Path
import sys


def render(report):
    parts = ['<!doctype html><html lang="ru"><meta charset=utf-8><meta name="viewport" content="width=device-width,initial-scale=1">',
             '<title>SEFIROT · Исследовательский обзор</title><style>body{font:17px system-ui;background:#102321;color:#edf3e9;max-width:44rem;margin:auto;padding:1rem}article{border-top:1px solid #657c74;padding:1rem 0}small{color:#c2d7ca}li{margin:.45rem 0}summary{cursor:pointer}</style>',
             '<h1>Исследовательский обзор</h1><small>'+escape(report['as_of'])+' UTC</small>']
    for r in report['matches']:
        teams = ' — '.join(escape(r['teams'][s]) for s in ('home','away'))
        parts.extend([f'<article><h2>{teams}</h2><p>{escape(r["kickoff"])} · PASS</p>',
                      '<p>Модель Poisson · П1 / Х / П2<br><b>'+
                      ' / '.join(f'{v:.1%}' for v in r['probabilities']['Poisson'])+'</b></p><ul>'])
        for k,v in r['scores'].items():
            if k == 'checks':
                continue
            label = escape(k.replace('_',' '))
            value = ('нет оценки' if v is None else
                     'выборка команд '+str(v['model_home_away_games']) if isinstance(v,dict) else f'{v:.0f} / 100')
            parts.append(f'<li>{label} · {escape(value)}</li>')
        parts.append('</ul><details><summary>Основания PASS</summary><ul>'+
                     ''.join('<li>'+escape(reason)+'</li>' for reason in r['reasons'])+'</ul></details></article>')
    return ''.join(parts)+'</html>'


if __name__ == '__main__':
    print(render(json.loads(Path(sys.argv[1]).read_bytes())))
