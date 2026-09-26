from importlib import import_module
from typing import Final, override

from django.apps import AppConfig, apps
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import module_has_submodule

from goatbeat.django.conf import DjangoSettings
from goatbeat.django.registry import DjangoRegistry

SCHEDULES_MODULE: Final = "schedules"
REGISTER_FUNCTION: Final = "register"


class GoatbeatConfig(AppConfig):
    name = "goatbeat.django"
    label = "goatbeat"
    verbose_name = "Goatbeat"
    default_auto_field = "django.db.models.BigAutoField"
    registry: DjangoRegistry

    @override
    def ready(self) -> None:
        settings = DjangoSettings.from_django()
        self.registry = DjangoRegistry(timezone=settings.config.timezone)
        for app in apps.get_app_configs():
            _register_schedules_of(app, self.registry)


def _register_schedules_of(app: AppConfig, beat: DjangoRegistry) -> None:
    """Call ``register(beat)`` from ``<app>/schedules.py``, the way admin.py is discovered."""
    if app.module is None or not module_has_submodule(app.module, SCHEDULES_MODULE):
        return
    module = import_module(f"{app.name}.{SCHEDULES_MODULE}")
    register: object = getattr(module, REGISTER_FUNCTION, None)
    if not callable(register):
        raise ImproperlyConfigured(
            f"{app.name}.{SCHEDULES_MODULE} must define {REGISTER_FUNCTION}(beat)"
        )
    register(beat)
