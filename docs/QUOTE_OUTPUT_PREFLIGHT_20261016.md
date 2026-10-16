# Занятое имя файла котировок: отказ до сети

База `eb17d04c6376149daee588f8c32971439ebe855f`, existing draft #56.
Проверяется существующий fetch-odds/write_quotes путь, новый importer не создаётся.

## Воспроизведение

Path.exists следует за symbolic link. Когда ссылка указывает на отсутствующий
файл, exists=false, хотя само имя уже занято. Проверка CLI пропускала такое имя
quotes или receipt. На принадлежащих тесту synthetic fixtures оба provider stub
вызывались по одному разу (catalogue и price), затем публикация отказывала EEXIST.
Настоящего provider/платного запроса в воспроизведении не было.

Это подтверждённый лишний запрос при заранее известной невозможности сохранить
результат. Старый hardlink no-clobber сохранял существующую ссылку и не переписывал
чужой файл; обхода его защиты не обнаружено. Нет оснований утверждать потерю
исходного ledger или нарушение всей публикации при обычном конкурентном запуске.

## Исправление и проверки

Две существующие проверки используют os.path.lexists: наличие самой directory
entry, без следования за конечной ссылкой. CLI отказывает до catalogue/price/
credential lookup; direct publisher — до создания временных файлов. Существующие
сообщения отказа, hardlink publication/rollback и валидные output bytes сохранены.
Против возникновения конфликта уже после preflight по-прежнему действует
существующая exclusive hardlink публикация; preflight не объявляется lock.

Два новых метода, каждый проверяет quotes и receipt. CLI работает с настоящим
owned synthetic ledger; проверяются ноль catalogue/price/credential calls,
byte equality ledger, отсутствие output/staging/target и сохранность исходной
ссылки. Direct publisher не доходит до NamedTemporaryFile.

Тест создаёт настоящую dangling symlink. Только на Windows при WinError1314
(не хватает права создания symlink) выполняется явно маркированная модель
occupied directory entry; тест не пропускается. Другие OS errors не маскируются.
Итоговый CI log отдельно фиксирует NATIVE_DANGLING_SYMLINK либо
WINDOWS_MODELED_OCCUPIED_NAME. Модель preflight не доказывает создание Windows
symlink при отсутствующем праве. Linux проверяет реальные filesystem entries.

Начальный 5043cc01 прошёл16/20 CI. Четыре Windows jobs показали ошибку нового
test helper: raw readlink() сравнивался с исходной записью пути. Assertions
отказа до сети/staging и сохранности ledger прошли; native symlinks созданы.
Теперь helper сравнивает dev/inode и raw readlink snapshot до/после операции:
проверяется идентичность самой ссылки и неизменность её значения без догадки
о Windows представлении пути. Ошибки не подавляются, assertions не удалены,
новых skips нет. Код приложения/hash прежний; новый commit проходит полный CI.
Неуспешный SHA/логи сохранены без rerun.

```sh
python -m unittest discover -s tests -p test_quote_output_preflight.py -v
python -m unittest discover -s tests -p test_quote_publication_v5.py -v
python -m unittest discover -s tests -p test_odds_provider.py -v
python -m unittest discover -s tests -p test_odds_confirmation_contract.py -v
```

Полный release — в отдельной tracked-tree копии; точный head/результаты и полный
20-job OS/Python/native PostgreSQL CI записываются в stage report и PR #56.
Изменяется только non-model cli.py, новые test/doc и AGENTS header. Другие src,
MODEL_MODULES/Policy, SQL/worker/relay, frozen protocol и originals прежние.
Code hash меняется явно, valid quote/receipt hashes не переписываются.

Официальный Stake contract/access не подтверждён. Раскрытый account token не
используется; настоящие provider/платные вызовы, budget activation, hosted writes,
deploy/main merge, fit/HOLDOUT и денежные разрешения не добавляются.
**RESEARCH_ONLY / PASS / stake=0.**
