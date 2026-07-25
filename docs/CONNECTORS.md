# Коннекторы AURORA

Все источники настраиваются в `config/connectors.yaml`. Если ключ отсутствует, коннектор возвращает `CONFIGURATION_REQUIRED` и не останавливает поиск.

## Интерфейс
`BaseConnector`: `id`, `name`, `supported_input_types`, `capabilities`, `requires_api_key`, `enabled`, `priority`, `timeout_seconds`, `rate_limit`, `health_check()`, `search()`, `normalize()`, `close()`.

`ConnectorResult`: `connector_id`, `status`, `started_at`, `completed_at`, `duration_ms`, `entities`, `evidence`, `warnings`, `errors`, `raw_reference`, `metadata`.

## Подключено реально
- `phone_metadata` — локальная библиотека `phonenumbers`.
- `public_web_search` — DDGS, только snippet/title как evidence, без превращения заголовков в ФИО.
- `dns_lookup` — системный DNS resolver.
- `rdap_whois` — `https://rdap.org`.
- `certificate_transparency` — `crt.sh` JSON.
- `wayback_cdx` — Internet Archive CDX API.
- `github_public` — GitHub public search API.
- `phoneinfoga`, `sherlock`, `maigret`, `holehe` — реальные CLI-адаптеры при наличии бинарников.
- `virustotal`, `shodan`, `haveibeenpwned`, `twilio_lookup`, `ipqualityscore`, `abstract_phone` — реальные API-адаптеры через environment variables.

> Важно: наличие адаптера означает выполнение HTTP/CLI-вызова, а не гарантированное получение ФИО. PhoneInfoga, `phonenumbers`, Twilio, IPQS и Abstract в первую очередь дают метаданные, тип линии и репутационные признаки. Для связи ФИО с телефоном AURORA требует контекст номера и независимые доказательства.

Официальные проекты, которые должен сверить владелец перед обновлением из сети без proxy: [PhoneInfoga](https://github.com/sundowndev/PhoneInfoga), [Sherlock](https://github.com/sherlock-project/sherlock), [Maigret](https://github.com/soxoj/maigret), [Holehe](https://github.com/megadose/holehe), [dnsx](https://github.com/projectdiscovery/dnsx). Автоматическая проверка GitHub во время аудита была недоступна из-за ограничения сети среды сборки.

## Требуют ключи
См. `.env.example`. Не храните реальные ключи в Git.

Проверить только конфигурацию и доступность коннекторов, не требуя локальных PostgreSQL/Redis:

```bash
bash scripts/check_connectors.sh
```

## Официальный Search Provider и загрузка страниц

По умолчанию используется Brave Search API (`AURORA_SEARCH_PROVIDER=brave`, `BRAVE_SEARCH_API_KEY`). DDGS сохранён только как явно включаемый fallback (`AURORA_SEARCH_PROVIDER=ddgs`) и не выдаётся за официальный API.

`AURORA_FETCH_CONTENT=true` включает `ContentFetcher`: перед соединением проверяются все DNS-адреса, private/special-use IP блокируются, соединение закрепляется на проверенном IP, каждый redirect проверяется заново, разрешены только HTTP(S) и MIME `text/html`, `text/plain`, `application/xhtml+xml`, `application/json`. Размер, timeout и число страниц ограничиваются переменными из `.env.example`.

## Investigative и compliance

- `aleph` выполняет поиск уже известного ФИО или организации через официальный OCCRP Aleph API. Результаты остаются кандидатами до независимого подтверждения. `ALEPH_API_KEY` нужен для закрытых коллекций/ограниченных запросов.
- `opensanctions` требует `OPENSANCTIONS_API_KEY` и не запускает screening только по имени. Нужен хотя бы дополнительный идентификатор: дата рождения, страна либо регистрационный номер. Статус без него — `INSUFFICIENT_INPUT`.
