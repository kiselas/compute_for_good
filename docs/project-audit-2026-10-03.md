# Аудит ComputeForGood перед публичным запуском

Обновление при подготовке первого серверного релиза: A02, A04, A05, A06 и A08 исправлены и покрыты девятью новыми HTTP/PostgreSQL regression-тестами. Полный прогон — 87 тестов без пропусков, отдельно 7 проверок авторизации; frontend и 874 ключа трёх языков проходят сборку. A03 исправлен heartbeat healthchecks работников и проверкой `/api/ready` при деплое; остановка QA worker дала отказ health probe и HTTP 503, перезапуск вернул 200. A01 был исправлен ранее и сохранён. Живой GitHub lifecycle, публичный TLS и оставшиеся пункты этого аудита требуют отдельных проверок; это обновление не означает готовность рекламы без них.

Проверена версия `a913824` от 3 октября 2026 года: FastAPI, PostgreSQL, Redis, React, Socket.IO, MCP, GitHub reconciliation, production Compose и скрипты эксплуатации. В аудите участвовали три независимых агента и основной агент. CodeGraph не использовался по выбору владельца.

Выявлены 12 основных ошибок и эксплуатационных рисков, из них 3 имеют приоритет P1. Их следует закрыть до рекламы полного contribution loop. Дополнительно выявлены два пробела защиты OAuth и небольшие проблемы интерфейса. Исправления в этом аудите не внесены: ниже зафиксированы причины, воспроизведения и критерии исправления.

P1 означает нарушение операторского запрета, блокировку основного рабочего процесса или ложное подтверждение готовности запуска. P2 означает существенный дефект при определённых условиях. P0 и подтверждённого обхода базовой авторизации не обнаружено; это не доказательство отсутствия других ошибок.

### Статус после реализации кабинета владельца — 3 октября 2026

Исходные выводы ниже относятся к `a913824`. В следующей реализации A01 исправлен: webhook прекращает обработку terminal `INVALID`, `CLOSED`, `MERGED`, не открывая работу заново. Regression invalidate → подписанный synchronize проверен через HTTP и PostgreSQL. В A07 исправлена загрузка задач страницы проекта: `project_id` передаётся на сервер до ограничения выдачи. Остальные проявления A07 и отсутствие pagination остаются открытыми. Переведена подпись `Confirming…`.

Добавлен самостоятельный флоу владельца: цели, улучшения, приватные черновики, утверждение, публикация и приёмка. Его 19 проверок вошли в общий прогон: 78 integration + 7 authorization passed, без skips; сборка и 874 ключа × 3 языка проходят. Эти результаты не закрывают A02–A12 и дополнительные замечания OAuth. Критерии публичного запуска и остальные исправления остаются в roadmap. Подробности: [maintainer-flow.md](maintainer-flow.md).

## Результаты повторной проверки

| Проверка | Результат |
|---|---|
| `scripts/verify.ps1`, отдельный QA стек PostgreSQL и Redis | 53 passed, 6 skipped, 82.57 s |
| Дополнительный прогон авторизации из того же скрипта | 7 passed, 8.85 s |
| Отдельный production-mode HTTP/OAuth и WebSocket через Caddy/nginx на 5380 | 6 passed, 1.90 s |
| `npm run build` | i18n 747 ключей × 3 языка, TypeScript и Vite проходят |
| Основной и production-mode preview `/api/ready` | 200; PostgreSQL, Redis и оба workers готовы |

Таким образом, все 66 существующих уникальных тестов прошли при явном включении production-прогона. Сам стандартный скрипт пропускает шесть из них. XML: `tests/artifacts/verification.xml`, `tests/artifacts/audit-production.xml`. Существующие тесты не покрывают обнаруженные ниже сценарии.

Проверки с изменением данных выполнялись в отдельном QA или локальном production-smoke окружении. Воспроизведения бизнес-ошибок использовали реальные функции и контролируемые in-memory объекты с подменой SQL/GitHub; это проверка ветвления кода, а не полноценный PostgreSQL regression test. Секреты не выводились. Основная демонстрационная база не изменялась.

## Ошибки высокого приоритета

### A01 P1 Webhook отменяет операторскую инвалидацию

Источник: [services.py:401](D:/Projects/compute_for_good/backend/computeforgood/services.py:401), операторская инвалидация — [governance.py:120](D:/Projects/compute_for_good/backend/computeforgood/governance.py:120).

Оператор признаёт задачу небезопасной и переводит task/submission в `INVALID`. Автор пушит новый commit. Обработка `synchronize` без проверки terminal state устанавливает `REVIEWING` и открывает review work. Обычный push тем самым отменяет операторский запрет.

Воспроизведено реальным `process_delivery`: входные `INVALID` и новый SHA дали `REVIEWING`. Исправление должно отделить обновление наблюдаемого GitHub head от права открыть работу. Regression: invalidate → подписанный synchronize → состояния остаются INVALID, новых доступных review slots нет. Аналогично защитить остальные terminal states.

### A02 P1 Блокировка проверяющего оставляет PR без замены ревью

Источники: [services.py:103](D:/Projects/compute_for_good/backend/computeforgood/services.py:103), [review_workflow.py:45](D:/Projects/compute_for_good/backend/computeforgood/review_workflow.py:45), [governance.py:167](D:/Projects/compute_for_good/backend/computeforgood/governance.py:167).

Завершённый approval заблокированного участника исключается из quorum. Его slot остаётся `COMPLETED`, а число slots ограничено размером quorum. У LOW-задачи единственный approval перестаёт считаться, но новый reviewer не получает доступного слота. Требуется разблокировать прежнего участника либо искусственно менять SHA.

Воспроизведено: approved=0, passed=false, replacement slots не создаются. Исправление: пересчитывать пригодность завершённых slots при suspension, сохранять историю и давать замену независимому reviewer. Regression: завершить единственный review → suspend reviewer → другой участник может claim и восстановить quorum на том же SHA.

### A03 P1 Deploy сообщает о готовности при неисправных workers

Источники: [compose.production.yaml:55](D:/Projects/compute_for_good/compose.production.yaml:55), [deploy.ps1:6](D:/Projects/compute_for_good/scripts/deploy.ps1:6), [worker.py:93](D:/Projects/compute_for_good/backend/computeforgood/worker.py:93).

Backend healthcheck проверяет `/api/health`, который не проверяет workers. У обоих workers нет healthcheck. Их цикл ловит ошибки операций и продолжает процесс, поэтому `Running` и успешный `compose up --wait` совместимы с неработающими expiry, outbox или webhook reconciliation. Финальное сообщение deploy преувеличивает проверенную готовность.

Подтверждено по коду и `docker inspect`: Healthcheck/State.Health у workers отсутствуют. Отключение работников на действующих preview не проводилось; сейчас они исправны. Исправление: ждать `/api/ready` через публичный proxy после запуска и добавить независимые heartbeat healthchecks. Regression: worker остаётся Running, но перестаёт публиковать heartbeat → deploy обязан завершиться ошибкой.

## Остальные существенные ошибки

### A04 P2 CI до регистрации PR теряется

Источники: [services.py:325](D:/Projects/compute_for_good/backend/computeforgood/services.py:325), [github_checks.py:84](D:/Projects/compute_for_good/backend/computeforgood/github_checks.py:84).

PR создан, CI завершился, webhook обработан до `register_submission`. Canonical submission ещё нет, delivery становится DONE. Поздняя регистрация создаёт `checks_passed=False` и не запускает первичное reconciliation. Даже после успешного review PR остаётся REVIEWING до следующего GitHub события или ручного operator refresh. Аналогичный порядок возможен при resubmit.

Воспроизведена последовательность delivery → register: reconciliation calls=0. Нужна durable reconciliation job при регистрации и смене head с повторными попытками. Regression: успешный CI перед регистрацией → без новых webhook checks подтверждаются для текущего SHA. Ручной обход уже существует: [refresh-checks](D:/Projects/compute_for_good/backend/computeforgood/github_checks.py:117).

### A05 P2 Merge записывается с предыдущим SHA

Источник: [services.py:399](D:/Projects/compute_for_good/backend/computeforgood/services.py:399).

Authoritative `current_pr` возвращает новый head, однако локальный SHA меняется только для action synchronize. Если closed/merged приходит раньше synchronize либо synchronize не обработан, submission становится MERGED с предыдущим SHA и привязанной к нему историей проверок. Решение maintainer на GitHub сохраняется; локальные provenance и аудит результата ошибочны.

Воспроизведено: GitHub head B, локальный A, action closed → вызов merge с A. Исправление: сверять head по authoritative состоянию при всех значимых PR событиях, отдельно соблюдая A01. Regression: перестановки synchronize/closed должны давать один credit и правильный финальный SHA.

### A06 P2 Фильтр задач раскрывает скрытый результат review

Источники: [app.py:162](D:/Projects/compute_for_good/backend/computeforgood/app.py:162), [services.py:79](D:/Projects/compute_for_good/backend/computeforgood/services.py:79).

SQL фильтрует настоящий `Task.status` до применения blind masking в DTO. Неавторизованный посетитель запрашивает `?status=CHANGES_NEEDED` или `?status=AWAITING_MAINTAINER` и узнаёт скрытое состояние по присутствию task_id, хотя ответ показывает REVIEWING.

Read-only HTTP на QA вернул соответственно 11 и 22 строки со скрытым статусом REVIEWING. Это раскрывает факт запроса изменений или достижения quorum; тексты findings остаются скрыты. Нужен фильтр по доступному пользователю состоянию либо запрет внутренних status filters без соответствующего права. Regression: prospective reviewer не различает скрытые решения ни по DTO, ни по составу выдачи.

### A07 P2 Ограничение выдачи до фильтрации скрывает доступную работу

Источники: [review_workflow.py:325](D:/Projects/compute_for_good/backend/computeforgood/review_workflow.py:325), [mcp_gateway.py:121](D:/Projects/compute_for_good/backend/computeforgood/mcp_gateway.py:121), [mcp_gateway.py:195](D:/Projects/compute_for_good/backend/computeforgood/mcp_gateway.py:195).

Eligibility, уже выполненные reviews и quorum проверяются после LIMIT. Первые 10 review slots неподходящие, 11-й подходит — REST по умолчанию возвращает пусто. При первых 50 неподходящих slots увеличить лимит уже нельзя. MCP find_work/find_review_work имеет похожую границу 100 кандидатов.

Воспроизведён реальный endpoint с контролируемыми rows: limit10 дал 0, limit11 дал 1. Нужна фильтрация в SQL или cursor scan до заполнения результата.

Отдельное проявление в интерфейсе: [ProjectPage:1232](D:/Projects/compute_for_good/frontend/src/App.tsx:1232) загружает глобальные первые 200 tasks и лишь затем фильтрует по проекту ([1282](D:/Projects/compute_for_good/frontend/src/App.tsx:1282)). При росте каталога проект может показать «нет задач», хотя они есть. Это установленный по коду сценарий; подходящих существующих QA данных для HTTP воспроизведения не было. Следует использовать `project_id` на сервере и добавить pagination.

### A08 P2 Неполная выборка commit statuses допускает ложный CI pass

Источник: [github_checks.py:62](D:/Projects/compute_for_good/backend/computeforgood/github_checks.py:62).

Check runs пагинируются, commit statuses читаются только первой страницей. При более 100 contexts успешный check run build засчитывает bare required name build, если failing status build остался за первой страницей. Aggregate state и total_count игнорируются.

Mock response с total_count101/statefailure и успешным check build дал checks_passed=True. Предпосылка редкая, но нарушает заявленную проверку всех одноимённых источников. Нужна bounded pagination с отказом при неполной выборке. Максимум 100 на страницу подтверждён [официальной документацией GitHub](https://docs.github.com/en/rest/commits/statuses#get-the-combined-status-for-a-specific-reference).

### A09 P2 Недоступный browser storage ломает claim и рендер

Источники: [App.tsx:133](D:/Projects/compute_for_good/frontend/src/App.tsx:133), [App.tsx:137](D:/Projects/compute_for_good/frontend/src/App.tsx:137), [App.tsx:330](D:/Projects/compute_for_good/frontend/src/App.tsx:330), [App.tsx:2193](D:/Projects/compute_for_good/frontend/src/App.tsx:2193).

В отличие от языковых настроек, lease storage не защищён try/catch. После успешного серверного claim `rememberLease` может бросить SecurityError/QuotaExceededError. `useAction` показывает ошибку, не обновляет queries и не сохраняет возвращённый token в памяти. Задача уже занята, но продолжить её из этого браузера нельзя. Чтение storage в render также может бросить исключение без ErrorBoundary. Review claim имеет аналогичную последовательность.

Воспроизведено извлечёнными из исходника функциями с mock storage: API success=1, query invalidations=0, restoreLease throws. Локальный diagnostic: `node artifacts/audit-frontend.cjs`. Нужны in-memory fallback, безопасный storage adapter и отдельная обработка ошибки сохранения после успешной серверной операции. Regression: denied storage → claim остаётся управляемым в текущей вкладке.

### A10 P2 CI не выполняет production transport проверки

Источники: [ci.yml:12](D:/Projects/compute_for_good/.github/workflows/ci.yml:12), [verify.ps1:5](D:/Projects/compute_for_good/scripts/verify.ps1:5), [test_production_smoke.py:13](D:/Projects/compute_for_good/tests/test_production_smoke.py:13), [test_transports.py:244](D:/Projects/compute_for_good/tests/test_transports.py:244).

Стандартные runners не создают production-mode stack и не задают `CFG_PRODUCTION_BASE_URL`. Поэтому пять HTTP/OAuth и один WebSocket тест пропускаются. Повторный запуск действительно показал 6 skipped. Отдельный запуск с переменной на локальном 5380 прошёл все шесть. TestClient авторизации не заменяет proxy transport tests.

Нужен изолированный production-mode stack в CI и обязательное выполнение этих тестов. Regression: CI падает, если production stack отсутствует или эти проверки skipped. Проверка настоящего HTTPS и secure cookies на публичном домене остаётся отдельной задачей.

### A11 P2 Параллельные backup используют общий файл

Источник: [backup.ps1:9](D:/Projects/compute_for_good/scripts/backup.ps1:9).

Каждый запуск пишет `/tmp/cfg-backup.dump`; другой запуск может перезаписать его между pg_dump и docker cp. Конечное имя имеет точность только до секунды и тоже может совпасть. Успешный exit code не доказывает, что скопирован целый архив нужного запуска.

Это вывод по конфликтующим путям, деструктивный concurrent experiment не проводился. Нужны уникальные UUID пути или exclusive lock, затем проверка архива и restore в отдельную базу. Regression: два параллельных запуска сохраняют разные целые архивы, каждый восстанавливается.

### A12 P2 Nginx не обновляет адрес пересозданного backend

Источник: [nginx.conf:16](D:/Projects/compute_for_good/frontend/nginx.conf:16), healthcheck — [compose.production.yaml:85](D:/Projects/compute_for_good/compose.production.yaml:85).

Используется статический `proxy_pass http://backend:8000` без resolver/динамического upstream. При пересоздании backend со сменой IP nginx может продолжить запросы по старому адресу до reload/restart. Проверка статической главной страницы при этом остаётся успешной.

Это сценарий отказа по конфигурации, действующий backend не пересоздавался для эксперимента. Настроить динамический Docker DNS upstream или гарантированный reload, проверять API через frontend. Механизм динамического resolve описан в [документации nginx](https://nginx.org/en/docs/http/ngx_http_upstream_module.html#resolve). Regression: backend replacement со сменой IP → API и MCP восстанавливаются без ручного вмешательства.

## Дополнительные слабые места

- **OAuth refresh replay:** [oauth_provider.py:121](D:/Projects/compute_for_good/backend/computeforgood/oauth_provider.py:121) скрывает уже использованный refresh; повтор отвергается, но актуальная family не отзывается. Если украденный public-client refresh первым обменял злоумышленник, повтор легитимного клиента не останавливает полученную им family. Это статически установленный пробел, атака не выполнялась. Нужны распознавание consumed-token replay, отзыв family и regression. Ожидаемая реакция описана в [RFC 9700 section 4.14.2](https://datatracker.ietf.org/doc/html/rfc9700#section-4.14.2).
- **Рост временных auth записей:** [auth.py:293](D:/Projects/compute_for_good/backend/computeforgood/auth.py:293) после настройки GitHub создаёт state на каждый анонимный GET без rate limit. В worker нет очистки истёкших auth/OAuth/session rows. Нужны throttling и retention cleanup; live GitHub и нагрузочная атака не запускались.
- **Просроченный permit в UI:** [App.tsx:1474](D:/Projects/compute_for_good/frontend/src/App.tsx:1474) выбирает форму по наличию permit, не по expires_at. После истечения можно повторно отправлять уже недействующий permit, но кнопка обновления отсутствует; помогает reload. Сервер правильно отвергает запрос. Нужны обновление permit и сохранение draft.
- **Неполная проверка переводов:** [App.tsx:1634](D:/Projects/compute_for_good/frontend/src/App.tsx:1634) содержит непереведённое `Confirming…` в ternary expression. Checker проверяет JSX text и t calls, но не все human strings внутри expressions. Нужен охват подобных состояний.
- **Сопровождение frontend:** App.tsx содержит более 4700 строк, а весь интерфейс и три словаря загружаются единым bundle 639.43 kB / 191.98 kB gzip. Рекомендуется выделить страницы и hooks, затем route-level code splitting. Это риск роста и сопровождения, а не измеренный отказ производительности.

## Порядок исправления

1. Закрыть A01–A03 и добавить PostgreSQL/HTTP regression tests, которые сначала воспроизводят ошибки на текущей версии.
2. Устранить A04/A05 и refresh replay до подключения внешних клиентов; добавить перестановки GitHub событий, CI до регистрации и повторное использование refresh.
3. Устранить A06–A10: blind filtering, полную выборку eligible work и CI, storage fallback, обязательный production runner.
4. Закрыть A11/A12 и проверить отказ workers, смену backend IP, конкурентные backup с восстановлением.
5. Выполнить внешний HTTPS/GitHub/MCP цикл с настоящим проектом, named CI policy, независимым review, maintainer merge и одним credit. Подтвердить мониторинг, off-host backup и восстановление.

Отсутствие email recovery, repository ownership automation и model attestation уже отражено в roadmap. HIGH/CRITICAL real dispatch намеренно закрыт; отсутствие автоматического merge и запуска чужого кода соответствует выбранной модели проекта. Это не новые дефекты. Публичная доступность, нагрузочная вместимость, полный accessibility и живые GitHub/MCP подключения данным аудитом не подтверждены.
