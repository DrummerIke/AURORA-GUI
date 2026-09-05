# CURRENT STATE AUDIT

## Что уже работает
- Flask/Waitress приложение запускается на `127.0.0.1:8080` через `run.sh`.
- Есть формы Phone/Email/Username Intelligence, локальные кейсы в `cases/`, статус модулей `/modules`.
- Номер нормализуется библиотекой `phonenumbers`; базовый поиск выполнялся через `ddgs`; Sherlock/Maigret/Holehe запускались как опциональные бинарники.

## Почему выдача содержала мусор
- Старый `web_search_engine.py` извлекал ФИО регулярным выражением из title/snippet поисковой выдачи и первых килобайт HTML, не отделяя SEO, меню, формы и отзывы о звонках.
- Кандидаты из телефонных каталогов попадали в итог как сущности.
- Confidence был эвристическим числом без сохраненного breakdown, поэтому несвязанные результаты получали похожие оценки.
- Пользователю показывались технические поисковые запросы и список кандидатов вместо итогового отчета с доказательствами.

## Что заменено
- Добавлен единый OSINT-конвейер `aurora/pipeline.py`: классификация, нормализация, планирование, асинхронный запуск коннекторов, сбор evidence, фильтрация, entity resolution, scoring и summary.
- Phone worker переведен на новый отчет без публикации поисковых запросов.
- Результатная HTML-страница переработана под итоговый отчет, доказательства, статусы коннекторов и закрытый технический блок отброшенных совпадений.

## Отсутствовавшие зависимости
- `PyYAML`, `beautifulsoup4`, `email-validator`, `pytest`, `pytest-asyncio`.

## Реально подключенные источники
- Локально: `phonenumbers`, DNS через системный resolver, опциональные реальные бинарники PhoneInfoga/Sherlock/Maigret/Holehe при наличии.
- HTTP/API без ключа: RDAP, Certificate Transparency `crt.sh`, Wayback CDX, GitHub public search, DDGS web search.
- API с ключами: VirusTotal, Shodan, Have I Been Pwned, Twilio Lookup, IPQualityScore, Abstract Phone Validation.

## Заглушки и ограничения
- Нелегальные базы утечек и скрытые агрегаторы не подключены.
- PostgreSQL/Redis добавлены в Docker Compose и doctor-проверки как инфраструктура для следующего этапа хранения/очередей; текущий совместимый запуск продолжает хранить кейсы файлово.

## Секреты владельца
`VIRUSTOTAL_API_KEY`, `SHODAN_API_KEY`, `CENSYS_API_ID`, `CENSYS_API_SECRET`, `SECURITYTRAILS_API_KEY`, `HIBP_API_KEY`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `IPQUALITYSCORE_API_KEY`, `ABSTRACT_PHONE_API_KEY`, опционально `GITHUB_TOKEN`.
