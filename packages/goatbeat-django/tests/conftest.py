import sys
from pathlib import Path

import pytest
from django.conf import settings
from psycopg.conninfo import conninfo_to_dict

from goatbeat.postgres.testing import database_url_from_env

sys.path.insert(0, str(Path(__file__).parent))

URL = database_url_from_env()
if URL is None:
    collect_ignore_glob = ["test_*.py"]


def django_settings(url: str) -> dict[str, object]:
    params = conninfo_to_dict(url)
    return {
        "SECRET_KEY": "goatbeat-tests",
        "USE_TZ": True,
        "DATABASES": {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": params.get("dbname"),
                "USER": params.get("user"),
                "PASSWORD": params.get("password"),
                "HOST": params.get("host"),
                "PORT": params.get("port"),
            }
        },
        "INSTALLED_APPS": [
            "django.contrib.admin",
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django.contrib.messages",
            "django.contrib.sessions",
            "goatbeat.django",
            "sampleapp",
        ],
        "MIDDLEWARE": [
            "django.contrib.sessions.middleware.SessionMiddleware",
            "django.contrib.auth.middleware.AuthenticationMiddleware",
            "django.contrib.messages.middleware.MessageMiddleware",
        ],
        "TEMPLATES": [
            {
                "BACKEND": "django.template.backends.django.DjangoTemplates",
                "APP_DIRS": True,
                "OPTIONS": {
                    "context_processors": [
                        "django.template.context_processors.request",
                        "django.contrib.auth.context_processors.auth",
                        "django.contrib.messages.context_processors.messages",
                    ]
                },
            }
        ],
        "ROOT_URLCONF": "sampleapp.urls",
        "TASKS": {"default": {"BACKEND": "django.tasks.backends.immediate.ImmediateBackend"}},
        "GOATBEAT": {"lease_ttl": "5s", "lease_renew_interval": "1s", "scheduler_id": "tests"},
    }


def pytest_configure(config: pytest.Config) -> None:
    del config
    if URL is not None and not settings.configured:
        settings.configure(**django_settings(URL))
