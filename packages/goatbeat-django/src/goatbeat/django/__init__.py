from typing import TYPE_CHECKING, cast

# Aliased: importing the goatbeat.django.apps submodule rebinds ``apps`` in this namespace.
from django.apps import apps as django_apps

from goatbeat.django.registry import DjangoRegistry, call

if TYPE_CHECKING:
    from goatbeat.django.apps import GoatbeatConfig

__all__ = ["DjangoRegistry", "call", "registry"]


def registry() -> DjangoRegistry:
    return cast("GoatbeatConfig", django_apps.get_app_config("goatbeat")).registry
