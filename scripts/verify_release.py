"""Release gate: tests + end-to-end demo + deterministic synthetic backtest."""
from pathlib import Path
from datetime import datetime,timezone
import json
import platform
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sefirot.backtesting import walk_forward
from sefirot.contracts import VERSION

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
    result={'version':VERSION,'python':platform.python_version(),'platform':platform.system(),'elapsed_seconds':round(time.monotonic()-started,3),
            'test_exit':test.returncode,'demo':demo_result,'backtest_fixtures':backtest['fixtures'],'backtest_scored_markets':backtest['metrics']['n'],
            'statistical_profitability_proven':False,'generated_at':datetime.now(timezone.utc).isoformat()}
    (report_dir/'RELEASE_CHECK.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    (report_dir/'TEST_REPORT.md').write_text(f'''# SEFIROT CORE {VERSION}: проверка сборки

- Среда: Python {result['python']}, {result['platform']}.
- Автоматические тесты: код завершения **0**, полный список в TEST_OUTPUT.txt.
- Сквозной demo: захват → решение → replay → результат → семь рынков feedback; целостность и replay подтверждены.
- Хронологический backtest: **{backtest['fixtures']} синтетических матчей / {backtest['metrics']['n']} оценённых рынков**. Все решения и отказы учтены; результат не сертифицирует модель.
- Время прогона: {result['elapsed_seconds']} сек.
- Реальных проспективных матчей для эмпирического допуска: **0**.
- Windows BAT и CI подготовлены. Локально проверена указанная среда, фактический запуск Windows в этой среде не выполнялся.
- Независимого внешнего аудитора не было. Проведена отдельная проверка контрпримеров и сверка правил; см. docs/FINAL_AUDIT.md.

Дата UTC: {result['generated_at']}.
''',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
