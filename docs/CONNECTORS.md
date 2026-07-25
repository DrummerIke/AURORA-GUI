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
