# Установка и обновление AURORA в Termux

Телефон в этом варианте является локальным сервером. Интерфейс открывается браузером самого телефона по адресу `http://127.0.0.1:8080`. GitHub Pages может разместить только статическую страницу и не может выполнить Python, Flask, CLI-коннекторы или безопасно хранить API-ключи.

## Первичная установка

Установите Termux из F-Droid или GitHub Releases проекта Termux, затем выполните:

```bash
pkg update -y
pkg install -y python git clang libxml2 libxslt rust
termux-wake-lock
git clone https://github.com/DrummerIke/AURORA-GUI.git ~/AURORA-GUI
cd ~/AURORA-GUI
bash scripts/install_termux.sh
./run.sh
```

Откройте `http://127.0.0.1:8080`.

## Обновление существующей ветки

Сначала сохраните локальные изменения:

```bash
cd ~/AURORA-GUI
git status
git branch --show-current
git fetch origin
```

После merge PR в `main`:

```bash
git checkout main
git pull --ff-only origin main
bash scripts/install_termux.sh
python scripts/doctor.py
./run.sh
```

Если обновление ещё находится в отдельной ветке, замените `BRANCH_NAME` на имя ветки PR:

```bash
git fetch origin BRANCH_NAME
git checkout BRANCH_NAME
git pull --ff-only origin BRANCH_NAME
bash scripts/install_termux.sh
./run.sh
```

## Ограничения Termux

- Docker Compose, PostgreSQL и Redis на телефоне для базового однопользовательского режима не требуются.
- Некоторые Python-пакеты Sherlock/Maigret/Holehe могут не собраться под конкретную версию Android; установщик пометит их как optional, а AURORA продолжит работу.
- PhoneInfoga и dnsx — Go-бинарники; скрипт показывает понятный статус, но не подменяет отсутствующий бинарник заглушкой.
- Для доступа с другого устройства нельзя просто выставлять порт в интернет. Нужны аутентификация, TLS и firewall; текущий сервер намеренно слушает только loopback.

## После обновления сводного отчёта

После слияния текущего PR достаточно обновить ветку и повторно запустить установщик зависимостей:

```bash
cd ~/AURORA-GUI
git checkout main
git pull --ff-only origin main
bash scripts/install_termux.sh
python scripts/doctor.py
./run.sh
```

Старые кейсы останутся в `~/AURORA-GUI/cases/`. Новый формат применяется к новым проверкам; для старого кейса нужно повторно запустить поиск с законным основанием и, при наличии, заявленным кандидатом ФИО.

## Новые переменные после Search/Security обновления

Скопируйте `.env.example` в локальный `.env` и заполните минимум Search Provider:

```bash
cd ~/AURORA-GUI
cp -n .env.example .env
nano .env
```

Минимально:

```dotenv
AURORA_SEARCH_PROVIDER=brave
BRAVE_SEARCH_API_KEY=полученный_ключ
```

Для защищённого браузерного доступа задайте HTTP Basic:

```dotenv
AURORA_AUTH_USERNAME=aurora
AURORA_AUTH_PASSWORD=длинный_уникальный_пароль
AURORA_AUDIT_HMAC_KEY=случайная_строка_не_короче_32_байт
```

Опционально: `ALEPH_API_KEY`, `OPENSANCTIONS_API_KEY`. Полную загрузку страниц включайте только после обновления кода: `AURORA_FETCH_CONTENT=true`.

`run.sh` автоматически загружает локальный `.env`. Запуск:

```bash
./run.sh
```
