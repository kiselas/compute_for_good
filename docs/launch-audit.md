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
| Frontend production build | TypeScript и Vite: exit 0; финальный bundle index-D08znBrJ.js | Docker build |
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

После проверки QA контейнеры остановлены с сохранением volumes. Основной demo stack 5180 и отдельный demo-free preview 5380 оставлены работающими. Повторный запуск QA выполняет scripts/verify.ps1. Screenshot сохраняет финальную визуальную сборку; последняя правка nginx не меняет frontend bundle.
