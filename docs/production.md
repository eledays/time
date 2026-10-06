# Production-развёртывание

Ниже описан поддерживаемый вариант для одного небольшого инстанса: Debian/Ubuntu,
nginx с TLS, Gunicorn, systemd и SQLite. Gunicorn слушает только loopback, а nginx —
публичные порты. Для горизонтального масштабирования замените SQLite на PostgreSQL,
укажите общее хранилище Flask-Limiter (например Redis), установите соответствующие
драйверы и увеличьте число workers. Этот вариант выходит за рамки данного runbook.

## 1. Подготовка сервера

Установите Python 3.12+, nginx, sqlite3, Git и средство получения TLS-сертификата.
Создайте отдельного непривилегированного пользователя и каталоги:

```bash
sudo useradd --system --user-group --home-dir /var/lib/time --create-home timeapp
sudo install -d -o root -g root -m 0755 /opt/time
sudo install -d -o timeapp -g timeapp -m 0700 /var/lib/time
```

Разместите проверенную версию репозитория в `/opt/time`. Код должен принадлежать
`root:root`; сервисному пользователю нужна запись только в `/var/lib/time`.

```bash
cd /opt/time
sudo python3 -m venv .venv
sudo .venv/bin/python -m pip install --upgrade pip
sudo .venv/bin/python -m pip install -r requirements.txt
```

## 2. Production-окружение

Создайте `/opt/time/.env`, заменив домен и реквизиты реальными значениями:

```dotenv
APP_ENV=production
SECRET_KEY=СЛУЧАЙНАЯ_СТРОКА_НЕ_КОРОЧЕ_32_СИМВОЛОВ
DATABASE_URL=sqlite:////var/lib/time/time.sqlite3
INSTANCE_PATH=/var/lib/time/instance

YANDEX_CLIENT_ID=идентификатор
YANDEX_CLIENT_SECRET=секрет
PUBLIC_URL=https://time.example.ru
TRUSTED_HOSTS=time.example.ru
TRUSTED_PROXY_COUNT=1

SESSION_COOKIE_SECURE=true
SESSION_LIFETIME_HOURS=168
MAX_CONTENT_LENGTH=1048576
MAX_ROUTE_POINTS=20
MAX_ROUTE_INTERMEDIATE_POINTS=4
MAX_ROUTE_VARIANTS=12
MAX_TEXT_LENGTH=200
RATE_LIMIT_STORAGE_URI=memory://
LOG_LEVEL=INFO

GUNICORN_BIND=127.0.0.1:8000
GUNICORN_WORKERS=1
GUNICORN_THREADS=4
GUNICORN_TIMEOUT=30

LEGAL_OPERATOR_NAME=ФИО или наименование организации
LEGAL_OPERATOR_EMAIL=privacy@example.ru
LEGAL_OPERATOR_ADDRESS=почтовый адрес оператора
LEGAL_OPERATOR_ID=ИНН / ОГРН / ОГРНИП при наличии
LEGAL_DATA_STORAGE_LOCATION=город и страна фактического размещения базы
LEGAL_DOCUMENT_VERSION=1.1
LEGAL_EFFECTIVE_DATE=2026-09-14
LEGAL_BACKUP_RETENTION_DAYS=30
LEGAL_LOG_RETENTION_DAYS=30

# Необязательно, если применимо к фактическому развёртыванию:
LEGAL_HOSTING_PROVIDER_NAME=
LEGAL_HOSTING_PROVIDER_LOCATION=
LEGAL_RKN_NOTICE_DATE=
LEGAL_CROSS_BORDER_TRANSFER=
LEGAL_CROSS_BORDER_NOTICE_DATE=
LEGAL_CROSS_BORDER_COUNTRIES=
```

Сгенерировать секрет можно командой `python3 -c 'import secrets;
print(secrets.token_urlsafe(48))'`. Защитите файл и создайте instance-каталог:

```bash
sudo chown timeapp:timeapp /opt/time/.env
sudo chmod 600 /opt/time/.env
sudo -u timeapp mkdir -p /var/lib/time/instance
```

В приложении Яндекс OAuth разрешите только право `login:info` и добавьте точный callback:
`https://time.example.ru/auth/callback`.

До первого запуска оцените, требуется ли основное уведомление об обработке
персональных данных. Браузер обращается к OpenStreetMap Foundation, jsDelivr и
Google Fonts, поэтому
также проверьте фактические страны, получателей и применимость правил
трансграничной передачи. Если уведомления поданы, заполните необязательные поля —
даты и страны в `.env` должны совпадать с ними. Заключите с провайдером
инфраструктуры договор с применимыми условиями обработки и защиты данных.
При существенном изменении документов увеличьте `LEGAL_DOCUMENT_VERSION`, иначе
ранее вошедшие пользователи не увидят экран принятия новой редакции.

## 3. Миграции и первый запуск

Миграции выполняются отдельно до старта каждого релиза. Unit-файл также запускает
их через `ExecStartPre`, поэтому несовместимая схема не попадёт в работающий процесс.

```bash
cd /opt/time
sudo -u timeapp .venv/bin/flask --app run.py db upgrade
sudo -u timeapp .venv/bin/flask --app run.py db current
```

Начальная миграция умеет принять базу, созданную старыми версиями приложения.
Перед первой миграцией существующей базы всё равно обязательно сделайте копию.

## 4. systemd и nginx

Проверьте пути в `deploy/time.service`, затем установите unit, отдельную политику
хранения journald и конфигурацию nginx:

```bash
sudo cp deploy/time.service /etc/systemd/system/time.service
sudo cp deploy/journald@time.conf /etc/systemd/journald@time.conf
sudo cp deploy/nginx.conf /etc/nginx/sites-available/time.conf
sudo ln -s /etc/nginx/sites-available/time.conf /etc/nginx/sites-enabled/time.conf
sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable --now time.service
sudo systemctl reload nginx
```

Gunicorn с SQLite обязан работать с `GUNICORN_WORKERS=1`; несколько потоков
обслуживают параллельные запросы. Не открывайте порт 8000 наружу. Если перед nginx
есть ещё один доверенный proxy, соответственно увеличьте `TRUSTED_PROXY_COUNT`.
Неверное значение позволяет подделывать адрес клиента или ломает rate limiting.
Nginx access log отключён, а формат Gunicorn намеренно не записывает query string:
там могут находиться OAuth-коды и введённые пользователем названия мест.
`LogNamespace=time` изолирует журнал приложения, а `journald@time.conf` удаляет
его записи через 30 дней. При изменении `LEGAL_LOG_RETENTION_DAYS` задайте тот же
срок в `MaxRetentionSec` и перезапустите `systemd-journald@time.service`.

## 5. Проверка релиза

```bash
curl --fail https://time.example.ru/healthz
curl --fail https://time.example.ru/readyz
sudo systemctl --no-pager --full status time.service
sudo journalctl --namespace=time -u time.service --since "10 minutes ago"
```

`/healthz` проверяет процесс, `/readyz` — соединение с базой. Затем вручную
проверьте вход через Яндекс, создание и удаление тестовой поездки, карту и удаление
тестового аккаунта. Ответы должны содержать HSTS, CSP и secure session cookie.

## 6. Резервные копии и восстановление

Установите ежедневный timer:

```bash
sudo cp deploy/time-backup.service deploy/time-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now time-backup.timer
sudo systemctl start time-backup.service
sudo systemctl status time-backup.service
sudo ls -l /var/lib/time/backups
```

Копии создаются штатной SQLite-командой `.backup`, проверяются через
`PRAGMA integrity_check`, сжимаются и удаляются через срок из
`LEGAL_BACKUP_RETENTION_DAYS`. Регулярно переносите их в зашифрованное внешнее
хранилище и тестируйте восстановление.

Для восстановления остановите сервис, сохраните повреждённую базу под другим
именем, распакуйте выбранную копию в `/var/lib/time/time.sqlite3`, установите
владельца `timeapp:timeapp` и права `600`, выполните `PRAGMA integrity_check`, затем
`flask db upgrade` и запустите сервис. Никогда не восстанавливайте поверх работающей
базы.

## 7. Обновление и откат

Перед обновлением создайте проверенную резервную копию. Затем установите код
конкретного тега/коммита, обновите зависимости и перезапустите unit:

```bash
cd /opt/time
sudo .venv/bin/python -m pip install -r requirements.txt
sudo systemctl restart time.service
curl --fail https://time.example.ru/readyz
```

Откат кода допустим только если старая версия совместима с уже применённой схемой.
В ином случае восстановите предрелизную копию базы. Не выполняйте `db downgrade`
на production без отдельно проверенного плана.

## 8. Эксплуатационный чек-лист

- TLS-сертификат автоматически обновляется, HTTP перенаправляется на HTTPS.
- `.env`, база и резервные копии имеют права `600` и принадлежат `timeapp`.
- Доступ к `/var/lib/time` и журналам ограничен администраторами.
- Ошибки и рестарты из journald отправляются в систему мониторинга с алертами.
- Journald или внешний сборщик удаляет журналы не позднее срока из
  `LEGAL_LOG_RETENTION_DAYS`; query string в access log не записывается.
- Внешний монитор вызывает `/healthz`, внутренний — `/readyz`.
- Проверена применимость основного и трансграничного уведомлений Роскомнадзору;
  если они нужны, сведения совпадают с политикой, подрядчиками и странами.
- Периодически выполняются `pytest`, `ruff`, `pip-audit` и тест восстановления.
