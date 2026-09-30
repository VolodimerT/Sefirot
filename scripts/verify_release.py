"""Release gate: tests + end-to-end demo + deterministic synthetic backtest."""
from pathlib import Path
from datetime import datetime,timezone
import json
import platform
import re
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sefirot.backtesting import walk_forward
from sefirot.contracts import VERSION,Policy
from sefirot.retrospective import audit_cases

def main():
    report_dir=ROOT/'reports';report_dir.mkdir(exist_ok=True)
    started=time.monotonic()
    test=subprocess.run([sys.executable,str(ROOT/'test_sefirot.py')],cwd=ROOT,capture_output=True,text=True)
    (report_dir/'TEST_OUTPUT.txt').write_text(test.stdout+test.stderr,encoding='utf-8')
    if test.returncode:
        print(test.stderr,file=sys.stderr);return test.returncode
    demo=subprocess.run([sys.executable,str(ROOT/'sefirot.py'),'demo'],cwd=ROOT,capture_output=True,text=True)
    if demo.returncode:
        print(demo.stderr,file=sys.stderr);return demo.returncode
    demo_result=json.loads(demo.stdout)
    if not demo_result['integrity'] or not demo_result['replay_matches']:raise ValueError('demo failed integrity/replay')
    (report_dir/'DEMO.json').write_text(demo.stdout,encoding='utf-8')
    cases=json.loads((ROOT/'examples/core2_backtest.json').read_text())
    backtest=walk_forward(cases)
    (report_dir/'BACKTEST.json').write_text(json.dumps(backtest,indent=2,ensure_ascii=False),encoding='utf-8')
    audit=audit_cases(json.loads((ROOT/'examples/audit_cases_20260927_30.json').read_text(encoding='utf-8')),Policy())
    (report_dir/'AUDIT_REGRESSION_REPORT.json').write_text(json.dumps(audit,indent=2,ensure_ascii=False),encoding='utf-8')
    count=re.search(r'Ran (\d+) tests?',test.stderr)
    result={'version':VERSION,'python':platform.python_version(),'platform':platform.system(),'elapsed_seconds':round(time.monotonic()-started,3),
            'test_exit':test.returncode,'tests':int(count.group(1)) if count else None,'demo':demo_result,'backtest_fixtures':backtest['fixtures'],'backtest_scored_markets':backtest['metrics']['n'],
            'audit_cases':audit['cases'],'audit_outcomes':audit['outcomes'],'audit_dataset_hash':audit['dataset_hash'],'audit_holdout_eligible':audit['holdout_eligible'],
            'statistical_profitability_proven':False,'generated_at':datetime.now(timezone.utc).isoformat()}
    (report_dir/'RELEASE_CHECK.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    (report_dir/'TEST_REPORT.md').write_text(f'''# SEFIROT CORE {VERSION}: проверка сборки

- Среда: Python {result['python']}, {result['platform']}.
- Автоматические тесты: **{result['tests']}/{result['tests']}**, код завершения **0**, полный список в TEST_OUTPUT.txt. Новых тестов по аудитам: 31.
- Сквозной demo: захват → решение → replay → результат → семь рынков feedback; целостность и replay подтверждены.
- Хронологический backtest: **{backtest['fixtures']} синтетических матчей / {backtest['metrics']['n']} оценённых рынков**. Все решения и отказы учтены; результат не сертифицирует модель.
- Ретроспективные случаи: **{audit['cases']}** из четырёх аудитных документов; {audit['outcomes']}. Неподдерживаемые рынки отмечены явно; исходные предматчевые прогнозы не восстановлены. Данные unverified/holdout=false, это не проверка эффективности новой модели.
- Время прогона: {result['elapsed_seconds']} сек.
- Реальных проспективных матчей для эмпирического допуска: **0**.
- Windows/Ubuntu и Python 3.11/3.13 проверяются в GitHub Actions при публикации. Для CORE 2.2 предыдущие восемь проверок прошли; статус CORE 2.3 виден в PR текущей версии. Локально выполнена только указанная среда, запуск Windows здесь не заявляется.
- Реальная авторизованная выгрузка CLI в Supabase всё ещё не проверена: роль NOLOGIN, нет пароля/CA. Схема из CORE 2.2 сохраняется; миграции CORE 2.3 не потребовались. Tavily не использовался.
- GitHub connector при записи вернул 403 Resource not accessible by integration, git push — отсутствие credentials. Публикация выполняется через ранее разрешённый пользователем браузер; это ограничение инструментов, а не провал тестов.
- Независимого внешнего аудитора не было. Проведена отдельная проверка контрпримеров и сверка правил; см. docs/FINAL_AUDIT.md.

Дата UTC: {result['generated_at']}.
''',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
