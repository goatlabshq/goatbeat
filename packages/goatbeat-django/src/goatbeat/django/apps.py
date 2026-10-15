from importlib import import_module
from typing import Final, override

from django.apps import AppConfig, apps
from django.core.exceptions import ImproperlyConfigured
from django.tasks.signals import task_finished
from django.utils.module_loading import module_has_submodule

from goatbeat.django.conf import DjangoSettings
from goatbeat.django.registry import DjangoRegistry
from goatbeat.django.signals import record_task_completion

SCHEDULES_MODULE: Final = "schedules"
REGISTER_FUNCTION: Final = "register"
COMPLETION_RECEIVER: Final = "goatbeat.record_task_completion"


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
        task_finished.connect(record_task_completion, dispatch_uid=COMPLETION_RECEIVER)


def _register_schedules_of(app: AppConfig, beat: DjangoRegistry) -> None:
    if app.module is None or not module_has_submodule(app.module, SCHEDULES_MODULE):
        return
    module = import_module(f"{app.name}.{SCHEDULES_MODULE}")
    register: object = getattr(module, REGISTER_FUNCTION, None)
    if not callable(register):
        raise ImproperlyConfigured(
            f"{app.name}.{SCHEDULES_MODULE} must define {REGISTER_FUNCTION}(beat)"
        )
    register(beat)
