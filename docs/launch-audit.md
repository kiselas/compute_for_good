# ComputeForGood — аудит готовности к запуску

Дата: 3 октября 2026. Локальная реализация и проверка выполнены ведущим и тремя параллельными агентами. Исходная спецификация использовалась как требования продукта. GitHub remote, публичное размещение и внешние аккаунты не подключались.

## Текущее состояние

| Область | Реализовано и проверено локально | До публичного запуска |
|---|---|---|
| Дизайн | Новая бело-синяя главная, отдельный кабинет, каталоги, формы, адаптация 390/1280 px | Проверить на публичном origin и физических устройствах |
| Аккаунты | Registration/login/logout, scrypt, HttpOnly cookie, CSRF, rate limits, scoped/expiring/revocable credentials | Настроить GitHub OAuth; определить канал поддержки восстановления аккаунтов |
| MCP | Streamable HTTP, 19 tools, PAT, OAuth PKCE/consent, public и confidential clients | Подключить внешние MCP hosts на HTTPS-домене |
| Работа | Atomic claim, heartbeat, expiry, checkpoint, permit, canonical PR, eligibility | Загрузить реальные разрешённые maintainer задачи |
| Review | Review leases, blind review, quorum, текущий SHA, revisions, независимое разрешение findings | Пройти реальный PR → review → maintainer merge |
| GitHub | HMAC/dedup, очереди, bounded retry/dead letter, автор/время/provenance, current-SHA CI | Credentials, webhook installation, required checks и live verification |
| Операторы | Проверка проектов, создание/редактирование/отзыв задач, force release, suspension, приватный аудит | Bootstrap оператора на сервере и проверить доступ |
| Проекты и профили | Candidate application, собственный и публичный профиль, наблюдаемые contributions | Получить maintainer opt-in и проверить хотя бы один настоящий проект |
| Эксплуатация | Production Compose, Caddy, private DB/Redis, отдельные workers, readiness, backup/restore | Сервер/DNS/HTTPS, внешнее наблюдение и encrypted off-host backup |

Основная локальная версия: http://127.0.0.1:5180. Это явно обозначенная demo среда. Отдельная production-mode сборка на loopback 5380 использовалась для проверки без demo identities и fixtures; она не является публичным HTTPS-размещением.

## Закрытые проблемы аудита

- Проверка linked GitHub ID и времени создания PR исключает выдачу старой или чужой работы за результат нового lease.
- Смена head SHA отменяет применимость старых approvals, но не стирает нерешённые HIGH/CRITICAL findings. Возврат к исходному плохому SHA снова блокируется.
- Review требует независимого reservation proof; автор не может review или разрешить собственную проблему. Operator adjudication требует browser authority.
- При ожидании domain lock сервер повторно проверяет suspension, чтобы уже прочитанная identity не давала доступ после блокировки.
- Poison webhook больше не откатывает соседние deliveries; retries и terminal failure наблюдаемы. Отдельный integration worker не останавливает expiry/outbox из-за сетевого запроса GitHub.
- Socket.IO объединяет до 100 outbox metadata changes в один пакет. Проверенная проблема 39 packets при decoder limit 16 устранена; burst из 40 событий проходит с обычным polling decoder.
- Повторный merge не создаёт второй impact credit. Приостановка проекта отзывает reservations, а повторная верификация восстанавливает только незавершённые review slots текущего SHA.
- Реальные browser sessions и MCP credentials заменили demo-only авторизацию. Refresh/revoke, scopes, audience, PKCE, CSRF и одноразовые authorization codes проверены отрицательными сценариями.
- nginx runtime обновлён с 1.27 до 1.30.5, образ закреплён digest. Причина: [официальные security advisories](https://nginx.org/en/security_advisories.html), включая исправления rewrite и proxy модулей. Forwarding headers явно заданы в OAuth/MCP/Socket.IO locations; production доверяет им за приватным proxy. Повторная proxy-проверка записана ниже.

Подробные review invariants и независимый разбор: [audit-review.md](audit-review.md).

## Доказательства проверки

| Проверка | Результат | Артефакт |
|---|---|---|
| Общая интеграция с настоящими PostgreSQL/Redis, REST/MCP/Socket.IO и demo-free proxy | **59 passed**, 81.04 s, errors/failures/skips = 0 | tests/artifacts/launch-final.xml |
| Авторизация с настоящими PostgreSQL/Redis, demo mode off | **7 passed**, 6.35 s, errors/failures/skips = 0 | tests/artifacts/auth-verification.xml |
| Финальный nginx 1.30.5 и forwarding configuration: production HTTP/OAuth + WebSocket | **6 passed**, 1.19 s, errors/failures/skips = 0 | tests/artifacts/proxy-final.xml |
| Frontend production build, включая мультиязычность | 747 ключей в каждом из 3 словарей; проверки i18n, TypeScript и Vite: exit 0; финальный bundle index-CEfjZZ_v.js | Docker build demo и production-mode |
| npm production dependency audit | 0 известных vulnerabilities на момент проверки | npm audit --omit=dev --json |
| Python pinned dependency audit | No known vulnerabilities found на момент проверки | pip-audit по backend/requirements.lock.txt |
| Backup restore | Успешно восстановлена отдельная cfg_restore_launch_final, Alembic 5c4267c97e04, 2 projects / 5 tasks / 1 submission | artifacts/backups/cfg-20261003-015913.dump |
| Browser | Главная и регистрация mobile без горизонтального скролла; login/logout; masked token; MCP handshake 19 tools; отказ после revoke; operator integrations; публичный профиль | artifacts/launch-desktop.jpg, launch-mobile.jpg, launch-production.jpg, launch-registration-mobile.jpg |

**66 уникальных тестов прошли.** Основной прогон включает 5 настоящих HTTP production identity/OAuth проверок и WebSocket через Caddy/nginx. GitHub API в проверках provenance/CI заменён контролируемыми upstream responses; это доказательство policy, а не live GitHub integration. npm/pip audit не является полным аудитом ОС, контейнеров или доказательством отсутствия неизвестных уязвимостей.

Тесты используют отдельный QA стек 8110/55472/56382. Showcase база не заполнялась новыми fixtures. Резервные копии, screenshots, XML, пароли и encryption keys исключены из Git. Операторский пароль находится в приватном файле вне репозитория; в отчёте его нет.

## Границы запуска

**Рекламу, обещающую полный contribution loop, запускать после внешней проверки**, описанной в [roadmap](launch-roadmap.md) и [runbook](production-runbook.md): публичный HTTPS, реальные credentials, verified project с LOW-risk задачей, внешний MCP client и настоящий PR/review/merge с одним credit. Сейчас production каталог пуст: имитация impact не используется.

В beta остаются ограничения: нет email recovery/verification, автоматического ownership proof/GitHub App installation, подтверждённой model attestation, выплат, автоматического merge или server-side запуска пользовательского кода. Реальный HIGH/CRITICAL dispatch закрыт. Нагрузочная вместимость выбранного сервера и full accessibility ещё не измерены.

CI workflow подготовлен в .github/workflows/ci.yml; hosted GitHub Actions не запускался. GitHub подключается завтра по запросу владельца.

После проверки QA контейнеры остановлены с сохранением volumes. Основной demo stack 5180 и отдельный demo-free preview 5380 оставлены работающими. Повторный запуск QA выполняет scripts/verify.ps1.

Последующее обновление интерфейса добавило русский, английский и упрощённый китайский языки. Оба frontend пересобраны и запущены; readiness обоих стеков подтверждён. Сохранение языка, текста формы и активного экрана проверено в браузере; русская и китайская мобильные версии не имеют горизонтального скролла при ширине 390 px. Новые screenshots и подробности: [i18n.md](i18n.md). Backend не изменялся; 66 интеграционных тестов выше относятся к предыдущей проверке запуска.

## Цикл стабилизации — 13 октября 2026

Исходный revision: `82fa8db02d588d598e9a91688e00982db52e9e89`. Изменения подготовлены в ветке `codex/stabilize-browser-requests`. CodeGraph инициализирован с согласия владельца; локальные материалы посева, публикаций и ранее изменённый roadmap сохранены.

| Гипотеза / сбой | Проверяемый результат | Доказательства и решение |
|---|---|---|
| Поздний ответ проверки сессии перезаписывает успешный вход или выход | Ни один отменённый ответ не возвращает предыдущую сессию; смена аккаунта очищает кеш данных | На прежнем порядке записи обе гонки воспроизвелись. Три регрессии с настоящим QueryClient проходят после отмены запросов перед сменой сессии. Реализовано, принято по локальным проверкам. |
| Зависшее соединение удерживает запрос и форму в ожидании | HTTP-запрос завершается ошибкой по истечении 30 секунд, включая чтение тела; записи автоматически не повторяются | Семь проверок реального API-адаптера: зависшие заголовки и оба вида тела, отмена, cleanup, CSRF/bearer и локализованный proxy error. Реализовано, принято по локальным проверкам. |
| Кеш черновиков спринтов не учитывает аккаунт | Черновик одного пользователя не отображается другому для того же проекта | SSR настоящего SprintBuilder с кешем другого владельца; query key включает user ID. Реализовано, принято по локальным проверкам. |

Проверки: исходный backend прошёл 180 интеграционных тестов за 170.33 секунды, включая шесть production transport checks без пропусков, динамическую смену IP backend без reload proxy и 25 authentication tests за 42.43 секунды. Backend этой итерацией не менялся. Финальный frontend прошёл 36 тестов, 1039 ключей на RU/EN/zh-CN, TypeScript и production build. QA браузер загрузил именно `index-Dj6E1nSH.js`: проверены вход, выход, кабинет, переключение на alice и возврат к своему аккаунту. Гонки и deadline проверены управляемыми задержками в тестах; сетевые сбои на production не вводились.

Доказательства сохранены локально: `artifacts/stabilization-baseline-20261013.log`, `artifacts/stabilization-frontend-20261013.log`, `artifacts/stabilization-browser-build-20261013.log`, `artifacts/stabilization-account-20261013.png` и манифест с хэшами исходников. После смены QA-сборки обнаружен ожидаемый отказ старой вкладки при загрузке удалённого lazy asset; reload загрузил новый bundle. На проверенных действиях нового bundle ошибок консоли не зафиксировано.

Границы: отмена fetch не отменяет уже выполненную сервером запись — сообщение о timeout предлагает сначала проверить рабочую область. Главный JS остаётся крупным: 732.50 kB, gzip 219.04 kB; этот цикл не улучшает его размер и не измеряет рекламную вместимость. Выпуск на production и hosted CI для новых изменений ещё не выполнялись.

Из предложенного владельцем playbook применены гипотезы с критериями, лестница проверок и запись решения с отдельными статусами реализации/доказательств. Практический порядок закреплён в [tests/README.md](../tests/README.md). Повторять полную backend-проверку без изменения её поверхности не требуется; для принятия следующего выпуска нужны обычные CI и release gates. Рекомендации BlueSec о моделях, количестве ревью и соревнованиях не используются как доказательство для изменения независимой приёмки PR.

## Оптимизация тестовых прогонов — 13 октября 2026

Цель: ускорить обратную связь в итерациях и убрать повторную работу, сохранив полный release gate. Быстрый профиль стал режимом по умолчанию; frontend, выбранные backend-тесты и полный прогон вызываются явно. Команды и границы профилей описаны в [tests/README.md](../tests/README.md).

| Проверка | До | После | Область сравнения |
|---|---|---|---|
| Frontend: тесты, i18n, TypeScript, bundle | 31.49 s | 14.31 s | Те же 36 тестов и 1039 ключей; ограниченный параллелизм вместо последовательных npm-процессов |
| Два настоящих polling-теста | 62.71 s | 7.20 s | Те же события и default decoder limit 16; async HTTP позволяет отменить pending GET при teardown |
| Основная Python suite | 180 passed / 170.33 s | 196 passed / 88.66 s | Добавлены 16 проверок управления прогоном; отражение неизменной PostgreSQL-схемы переиспользуется внутри run |
| Быстрый профиль | Отдельной команды не было | 10.49 s | 36 frontend и 67 offline Python tests; 129 integration cases осознанно не выбираются, пропусков нет |
| Один выбранный polling-кейс с подготовкой текущих образов | Отдельного профиля не было | 17.35 s | Backend-профиль, один node selector, реальная PostgreSQL/Redis/API инфраструктура |
| Полный новый профиль | Сопоставимый total не записан | 189.39 s | Frontend checks, однократная сборка двух образов, оба стека, 196 + 25 Python tests, 6 transports и DNS recovery |

Это локальные замеры на данном компьютере, а не обещание одинакового времени на другой машине. Время полного прогона включает 22.13 s на образы, 14.11 s на запуск двух стеков и 35.58 s на отдельную авторизацию. Новый полный прогон прошёл без failures/errors/skips; auth и DNS проверки сохранены. После контролируемой TypeScript-ошибки повторный quick подтвердил корректное восстановление. Проверен также отказ test runner на отсутствующем файле и запрет запуска bundle при упавшем typecheck.

Убраны повторные state/render tests из упаковки Docker, образы переиспользуются между demo/production и тремя backend-ролями. CI использует общие Docker layer caches с deploy workflow; feature-branch push больше не дублирует PR-run, main push сохраняет точную проверку release revision. Hosted CI для этих изменений ещё не запускался; структура workflow и состав обязательных gates проверены локально.

Один полный запуск был прерван после остановки локальной Docker VM: ошибки инфраструктуры не зачтены как успех. Прогоны теперь останавливаются на первой ошибке и имеют deadlines с завершением только своего дерева процессов. Частичный профиль не помечается полной проверкой; full не принимает selectors. Параллелятся frontend и offline проверки, а операции с реальным общим хранилищем остаются последовательными. Успешные результаты тестов не кешируются.

Доказательства: `artifacts/test-flow-frontend-before.log`, `test-flow-frontend-after.log`, `polling-before.xml`, `polling-after.xml`; отчёты `artifacts/verification-quick-20261013T080349Z-f479f8/report.json`, `artifacts/verification-full-20261013T075948Z-5ae072/report.json` и `artifacts/verification-backend-20261013T080524Z-c1dd23/report.json`. Логи, XML, временные fixture-файлы и Docker settings остаются вне Git. Не повторять полную suite на каждом небольшом UI-изменении: использовать quick/целевой набор, а полный профиль — для завершённого пакета и выпуска.

## Восстановление черновика PR — 13 октября 2026

Гипотеза: потерю введённых URL/SHA/описания при reload можно устранить хранением только текста формы в пределах вкладки, сохранив отдельную серверную проверку отправки. Реализована sessionStorage-запись по account/task/lease с ограниченной областью и expiry; серверные credentials и permits не сохраняются. После reload форма получает новый permit через уже существующий FINALIZING recovery. Поля ограничены контрактом backend, есть явная очистка. Logout/смена аккаунта удаляют записи этой функции; отказ хранилища оставляет форму в памяти с честным предупреждением.

Девять новых регрессий проверяют перезагрузку, отсутствие credentials в записи, изоляцию аккаунта/задачи/lease, expiry/24-hour bound, отказ/quota, повреждённые и большие записи, очистку настоящим session transition и невозможность отправить восстановленный текст без permit. В QA-браузере обычный cookie-аккаунт ввёл три поля, перезагрузил страницу, получил новый permit и увидел точные исходные значения. Очистка сохранилась после следующего reload; отдельная QA-регистрация работы завершилась успешно. Production fixtures для этого не создавались.

Локальные проверки: quick 12.63 s; full 178.01 s, 196 integration/runner + 25 auth tests без пропусков, шесть production transports и DNS recovery. Frontend: 45 тестов и 1043 ключа в трёх локалях, TypeScript и Docker production build. Доказательства: `artifacts/draft-browser-proof.json`, `draft-browser-recovered.png`, `draft-full.log` и `artifacts/verification-full-20261013T112857Z-d609b8/report.json`. Это восстановление текста для того же lease, не сохранение полномочий или обход проверки срока. При недоступном sessionStorage reload recovery невозможен; plain-memory fallback обозначен в интерфейсе. Backend и схема этой итерацией не менялись.
