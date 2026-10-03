# Сервер для ComputeForGood

Целевой домен владельца — `compute-for-good.tech`. Разведка выполнена 3 октября 2026 года, примерно 14:30–14:40 МСК, через существующее SSH-подключение. На сервере выполнялись только операции чтения: состояние процессов, Docker, сеть, активные файлы nginx, публичный сертификат и HTTPS-проверки. Деплой, изменение DNS, остановка сервисов и правка конфигурации не выполнялись. Значения секретов и приватные ключи не читались.

Сервер подходит для совместного размещения по сетевой схеме, но стандартный `compose.production.yaml` нельзя запускать здесь без адаптации: его edge пытается занять уже используемые 80/443. Запас памяти и диска ограничен; текущие замеры не являются нагрузочным испытанием.

## Адрес и ресурсы

| Параметр | Проверенное состояние |
|---|---|
| IPv4 | `185.115.33.169` |
| SSH | `ssh nextdish-intl`, альтернативный alias `nc-nl`; root, порт 22, существующий ключ |
| Hostname | `vpn-nl-01` |
| ОС | Ubuntu 22.04.5 LTS |
| Доступные CPU | 3 по `nproc`; старые документы о 1 vCPU устарели |
| RAM | 3,8 GiB всего; 2,3 GiB used; около 1,1 GiB available |
| Swap | 2 GiB всего; около 958 MiB занято |
| Корневой диск | 40 GiB; 31 GiB занято, 7,3 GiB свободно, 81% использования |
| Inodes | 22% использовано |
| Docker | Engine 29.7.2, Compose 5.4.0 |
| Контейнеры | 27 запущенных; NextDish продолжает работать |

Несколько отдельных SSH-соединений завершились connection timeout, другие успешно выполнили команды. Причина не установлена: стабильность канала потребуется проверить перед переносом образов и переключением маршрутов.

Для сравнения: шесть контейнеров локального ComputeForGood в покое занимают суммарно около 364 MiB без TLS gateway. Это ориентир, а не прогноз использования под рекламной нагрузкой. Образ backend около 362 MB, frontend около 94 MB; backend/workers имеют общие слои. Образы следует собрать на ноутбуке и передать готовыми, избегая сборки на общем сервере.

## Сервисы и пути

| Контур | Путь | Проверенная конфигурация |
|---|---|---|
| VPN | `/opt/next_connect` | Compose из `/opt/next_connect/deploy/docker-compose.yml` и `docker-compose.override.yml` |
| Общий публичный nginx | `/opt/next_connect/deploy/edge/nginx.conf` | bind mount в `next_connect-edge-1:/etc/nginx/nginx.conf` |
| Caddy подписок VPN | `/opt/next_connect/deploy/caddy/Caddyfile` | `next_connect-caddy-1`, Caddy 2.11.4; содержимое и список модулей в этой разведке не получены |
| NextDish intl | `/opt/nextdish` | `docker-compose.yml` + `docker-compose.intl.yml`; application, два workers, frontend, blog, PostgreSQL, Redis, RabbitMQ, MinIO, backup |
| Content Factory | `/opt/content-factory` | `/opt/content-factory/deploy/compose.web.yaml`, project `content-factory-production` |
| Gateway Content Factory | `/opt/content-factory/deploy/nginx.ip.conf` | bind mount в `content-factory-production-gateway-1`; TLS на 9443, API/MCP → web:8080, UI → editorial-web:3030 |

Content Factory сейчас также имеет publisher, collector, collection-scheduler, browser-worker, adaptation-worker и notification-worker. Сентябрьские документы о размещении только четырёх контейнеров уже не описывают текущую конфигурацию.

## Маршрутизация

`next_connect-edge-1` единолично публикует TCP 80/443 на IPv4 и IPv6. HTTPS использует nginx stream с `ssl_preread`, сохраняя сквозной TLS. Внешний listener отправляет PROXY protocol во внутренние hops.

| HTTPS SNI | Внутренний hop | Назначение |
|---|---|---|
| `dl.google.com` | 127.0.0.1:8543 | xray:443, PROXY header снимается |
| `next-metrica.com` | 127.0.0.1:8545 | caddy:2096, PROXY header снимается |
| `cf.nextdish.tech` | 127.0.0.1:8546 | cf-gateway:9443, PROXY header снимается |
| Остальные имена | 127.0.0.1:8544 | frontend:8443 NextDish, PROXY header переиздаётся |

По HTTP отдельный server для IP и `cf.nextdish.tech` обслуживает только ACME challenge через `cf-acme:8080`; `next-metrica.com` отправляется на caddy:80, default — на NextDish frontend:80. Без нового правила домен ComputeForGood попадёт в NextDish.

Общая внешняя Docker-сеть — `edge_net`. NextDish frontend использует в ней alias `frontend`, Content Factory gateway — `cf-gateway`. Внешнюю сеть нужно подключать только к уникально названному CFG gateway; CFG frontend, backend, PostgreSQL и Redis оставить в собственной сети. Иначе общий alias `frontend` создаст неоднозначное DNS-разрешение.

Другие опубликованные порты: SSH 22/tcp; Xray 2053/8443 tcp; VPN Caddy 2096/tcp; Content Factory 9443/tcp; Hysteria 9443/udp. На loopback: control plane 8000/tcp и RabbitMQ management 15672/tcp. UFW включён, разрешает входящие 22/443, остальное по умолчанию deny. Это не полный аудит эффективного firewall для опубликованных Docker-портов; iptables/nftables и доступность каждого порта извне не проверялись.

`nginx -t` для edge и gateway Content Factory успешен. Проверки с самого сервера: `https://cf.nextdish.tech/`, `https://nextdish.tech/`, `https://next-metrica.com/` вернули HTTP 200 с `ssl_verify_result=0`. Это подтверждает веб-маршруты; полноценные VPN туннели и авторизованные пользовательские сценарии не проверялись.

Публичный сертификат Content Factory: Let's Encrypt YE1, SAN `cf.nextdish.tech` и `185.115.33.169`, действителен до 8 октября 2026, 10:09:58 UTC. Есть `content-factory-cert-renew.timer`: последний запуск в таблице timers — 3 октября 00:13 UTC, следующий — 12:04 UTC. Результат renewal service не получен, поэтому успешное продление не подтверждено.

## DNS нового домена

На момент проверки локальный DNS, Cloudflare `1.1.1.1` и Google `8.8.8.8` возвращают NXDOMAIN для `compute-for-good.tech`; запросы NS/SOA через Cloudflare также не дали записи. Это не опровергает покупку домена: текущая делегация пока не видна указанным резолверам.

После появления делегации целевая запись: `A @ → 185.115.33.169`. Если нужен `www`, добавить `CNAME www → compute-for-good.tech` и отдельное перенаправление/сертификат. IPv6 сервера и IPv6-вариант размещения в этой разведке не подтверждены.

## Схема предстоящего размещения

1. Подготовить отдельный каталог `/opt/compute-for-good`, Compose project и приватное окружение. `PUBLIC_URL`, `FRONTEND_URL`, CORS и MCP issuer — `https://compute-for-good.tech`; demo выключен, secure cookies включены. Соседние базы и credentials не использовать.
2. Создать вариант production Compose для общего сервера: уникальный TLS gateway без публикации host 80/443, только gateway подключён к `edge_net`. Добавить лимиты памяти/CPU/processes и ротацию логов; предусмотреть запас на PostgreSQL, импорт образов и резервную копию.
3. Подготовить конкретный HTTPS gateway и ACME-процедуру. Согласовать поддержку PROXY protocol на обоих концах нового hop: сохранение реального IP нужно для корректного login throttling. Простое снятие PROXY header без дальнейшей передачи IP объединит клиентов под адресом proxy. Поддержка PROXY listener текущим stock Caddy здесь не подтверждена.
4. Подготовить точечный SNI-маршрут для нового домена в существующем edge и HTTP-маршрут для redirect/ACME. Сохранить копию исходного nginx и план отката; проверить nginx syntax до reload. Существующие VPN, Content Factory и NextDish маршруты сохраняются.
5. До публичного переключения проверить `/api/ready`, TLS, регистрацию/CSRF, OAuth metadata, внешний MCP transport и Socket.IO. После переключения повторить HTTPS-проверки соседних доменов и проверку VPN.
6. Проверить off-host backup и фактическую нагрузку. При нехватке ресурсов сначала решить с владельцем судьбу всё ещё работающего NextDish либо увеличить RAM/диск; его остановка не входит в эту разведку.

Стандартный публичный Compose не запускается на этом сервере на этапе разведки. Общие prune, изменение UFW/sshd/Docker daemon, остановка соседних сервисов и чтение production `.env` не выполнялись.
