# Новый аудит: вероятность и полнота проверки, 07.10.2026

Продолжение локальной системы по аудиту 06.10.2026. API остаётся на паузе.
Главный вывод принят: высокий EV и устойчивость к пробам интенсивностей
не подтверждают правильность исходной вероятности. Нового holdout,
калибратора или денежного допуска это обновление не создаёт.

## Исправленные дефекты

На ровно 10 п.п. прежнее условие `>` пропускало обязательное подтверждение
спортивных фактов. Теперь проверка начинается с существующего порога
`Policy.divergence = .10`; при `.20` сохраняется обязательный новый seal.
Вычитание `.6 - .5` и `.7 - .5` даёт значения чуть ниже десятичных границ:
общая функция учитывает только машинное округление (четыре ulp при 1.0).
Проверены обе границы, отрицательное расхождение и значение ниже порога.
Не изменены пороги Policy, классы, денежные caps или модель.

При совпадении observed_at общий CLV report ранее мог выбрать другую
closing quote, чем postmatch view. Оба отчёта теперь выбирают одну цену
по observed_at, received_at и стабильному digest, с теми же fixture,
контрактом, БК и REGULATION_90. Cutoff исключает будущие записи.

## Новые сведения в существующих командах

`work ... --text`, `decide` и `readiness` используют прежний runtime.
Карточка раскрывает для каждого рынка `probability_trust`: блокирующие
проверки, историю, calibration n/hash, holdout n/id, профиль/компетенцию,
заявленные источники, составы и статус чувствительности модели.
`EXISTING_GATES_PASSED` означает лишь отсутствие перечисленных блоков.
Это не доказанная точность P. Числовой score=null: веса и границы 50/65/80
из аудита ещё не обучены и не проверены независимо. Новые поля разрешений
не дают; единственный итоговый допуск остаётся в существующем engine.

`divergence_review` показывает действительную reference method, разницу,
условность при отсутствии PUSH и независимые группы актуальных FACT
по lineup/injuries/tactics. Два source_id одной группы не считаются двумя
подтверждениями. Предложенный новый порог 15 п.п. не настроен по одному
дню: действуют прежние .10/.20.

`search_review` хранит весь price-blind пул одного seal, число оценённых
и имеющих цену рынков, reference-only контракты и порядковый номер focus
в исходном пуле. Это не EV-rank. Просмотры других матчей/чатов неизвестны,
а не равны нулю. Автоматический penalty 5/15/30 не введён без проверки.
Котировки reference не расширяют запечатанный пул; default остаётся семь.

Из первоначальной raw массы счёта раскрыты P(home/away >=3/4) и для
андеров вероятность проигрыша от голов одной соответствующей команды.
Для integer UNDER 3 порог проигрыша — 4, а 3 остаётся PUSH.
Событие «хотя бы одна» учитывает пересечение один раз. Это проекция той
же модели, не независимо калиброванный ceiling engine и не новый veto.
Loss scores не выдаются за причинный диагноз; влияние narrative/H2H
остаётся NOT_QUANTIFIED при отсутствии доказательства зависимости.

`forward-scorecard` экспортирует flat reliability_table отдельно по
лиге, профилю, полному контракту/линии, raw/base и WIN/PUSH/LOSS bin:
n, predicted_mean, actual_rate, Brier/log loss. Последние два считаются
по полному вектору исходов в соответствующем bin. Пустая выборка не
превращается в нулевую ошибку. Семь рынков — не семь независимых матчей.

В scorecard добавлен registry всех записанных предматчевых PASS/BET на
оригинальных seals cohort: повторные решения сохранены, блокировки
считаются по уникальным матчам, missing decision не считается PASS.
Весь prospective знаменатель, cutoff и original forecast сохранены.
Он не восстанавливает отсутствующие решения и не охватывает чужие чаты.

`report` показывает CLV coverage отдельно для decision quotes и записанных
исполнений: всего, с matching close, без close и долю покрытия; при нуле
записей доля null. Raw odds ratio same-book не считается no-vig sharp edge
или доказательством прибыли. Новый сбор closing API не запускался.

## Матрица десяти задач аудита

| Задача | Результат этого этапа | Что остаётся |
| --- | --- | --- |
| Probability Trust Score | Видимый proof status и компоненты; EV не заменяет existing gates | Проверить веса/score на отдельной выборке; числовой score отсутствует |
| Extreme divergence | Исправлены точные .10/.20 границы; раскрыто corroboration | Новый .15 порог остаётся предложением |
| Search bias | Зафиксирован локальный sealed pool и ordinal | Общий discovery cohort и независимо проверенный penalty |
| Все PASS/BET | Registry оригинальных решений в existing forward cohort | Получить реальную prospective выборку без исключения пропусков |
| Калибровка по рынкам | Flat таблица контракта/линии/profile/bin, existing fitted gates сохранены | Новые реальные calibration и holdout, без refit по просмотренному TEST |
| CLV | Единый выбор close, coverage и разделение quote/execution | Receipt-bound complete sharp reference и price provenance |
| Favorite ceiling | Raw P>=3/4, exact under loss projection | Независимая проверка ceiling и любого нового veto/penalty |
| Causal death test | Existing sports premises/avoid_result; raw loss scores не названы причинами | Предматчевые структурированные causal facts и проверка отдельных гипотез |
| Dixon–Coles shadow | Не внедрён в текущую модель | Заранее назначенный challenger experiment на отдельном frozen cohort |
| Daily queue UI | Existing `work inbox --text`, named job dependencies и более понятная карточка | Отдельная web UI не создана; сначала стабильный file workflow |

Ни LIVE, ни догон, ни автоматическое исполнение, ни новые рынки не добавлены.
Математические тесты проверяют код, а не качество футбольных прогнозов.
Частные исходные аудиты, ставки, API-пакеты и SQLite в Git не включены.
Архивные seals воспроизводить оригинальной сборкой: code_hash изменился,
семь MODEL_MODULES/model_hash и Policy остались прежними.

## Проверка

30 новых контрпримеров проверяют границы и независимость источников,
неподменяемость holdout ценой/EV, price-blind ceiling/PUSH, missing/future
decisions, reliability арифметику, CLV tie и coverage. Полный release и
точный hash — в reports/RELEASE_CHECK.json; удалённый CI проверяется на
опубликованном exact head, его результат не заменяется локальным прогоном.

Для старых положительных graded controls добавлены два независимых
фиктивных FACT groups на точной .10 границе; требования не ослаблены.
Отдельные тесты проверяют PASS без corroboration и BET controlled context
с ним. Такие test inputs не являются реальными release certificates.

Синтетический runtime benchmark (Linux/Python 3.12, три повтора) одной
фиксированной fixture до/после: prepare семи рынков 22.22 / 21.64 ms,
context при 1000 несвязанных historical fixtures 287.02 / 281.06 ms.
Это малый шумный замер, ускорение не заявляется. Вероятностные векторы,
fixture hash и benchmark script hash одинаковы; integrity сохранена.
Новые raw projections валидируют mass через existing public probability
function один раз и суммируют оставшиеся tails без повторного settlement.
См. reports/AUDIT07_BASELINE_RUNTIME.json и reports/AUDIT07_RUNTIME.json.

- code_hash: `c6301d4f8dbaedb62baf1827283d9e72850fed27e72514edffe614a010e29513`;
- model_hash: `46f1c991a2ee93a2d68a0ae9c1b091b866660501980f52c2456a83bf96ba6617`;
- policy_hash: `5d92a9c98c13df0d313b8ef9f59605e93482b2eeb7f31f91f5031969871becd9`.
