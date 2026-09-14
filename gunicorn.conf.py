"""Безопасные значения Gunicorn по умолчанию для этого приложения."""

import os

from sqlalchemy.engine import make_url

bind = os.getenv("GUNICORN_BIND", "127.0.0.1:8000")
workers = int(os.getenv("GUNICORN_WORKERS", "1"))
threads = int(os.getenv("GUNICORN_THREADS", "4"))
timeout = int(os.getenv("GUNICORN_TIMEOUT", "30"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "5"))
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "2000"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "200"))
accesslog = "-"
errorlog = "-"
capture_output = True
access_log_format = (
    '%(t)s client="%({x-real-ip}i)s" method=%(m)s path="%(U)s" '
    "protocol=%(H)s status=%(s)s bytes=%(b)s duration_us=%(D)s"
)

database_url = make_url(os.getenv("DATABASE_URL", "sqlite:///time.sqlite3"))
rate_limit_storage = os.getenv("RATE_LIMIT_STORAGE_URI", "memory://")
if database_url.get_backend_name() == "sqlite" and workers != 1:
    raise RuntimeError(
        "SQLite требует GUNICORN_WORKERS=1; для масштабирования используйте PostgreSQL"
    )
if rate_limit_storage == "memory://" and workers != 1:
    raise RuntimeError(
        "Несколько workers требуют общего RATE_LIMIT_STORAGE_URI, например Redis"
    )
