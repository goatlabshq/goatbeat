"""Django base classes parameterized for type checkers only.

django-stubs makes them generic, but they are not subscriptable at runtime.
"""

from typing import TYPE_CHECKING

from django import forms
from django.contrib import admin

if TYPE_CHECKING:
    from goatbeat.django.models import Execution, Schedule

    ScheduleModelForm = forms.ModelForm[Schedule]
    ScheduleModelAdmin = admin.ModelAdmin[Schedule]
    ExecutionModelAdmin = admin.ModelAdmin[Execution]
    ExecutionInline = admin.TabularInline[Execution, Schedule]
else:
    ScheduleModelForm = forms.ModelForm
    ScheduleModelAdmin = admin.ModelAdmin
    ExecutionModelAdmin = admin.ModelAdmin
    ExecutionInline = admin.TabularInline
