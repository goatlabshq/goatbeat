from typing import override

from django.apps import AppConfig

from goatbeat.django.conf import DjangoSettings


class GoatbeatConfig(AppConfig):
    name = "goatbeat.django"
    label = "goatbeat"
    verbose_name = "Goatbeat"
    default_auto_field = "django.db.models.BigAutoField"

    @override
    def ready(self) -> None:
        DjangoSettings.from_django()
