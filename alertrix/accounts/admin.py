from django.contrib import admin
from django.contrib.auth import forms as auth
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _

from alertrix.models import User
from . import models


class UserCreationForm(
    auth.UserCreationForm,
):
    class Meta:
        model = User
        fields = (
            'matrix_id',
        )


class UserChangeForm(
    auth.UserChangeForm,
):
    class Meta:
        model = User
        fields = (
            'password',
        )


class AlertrixUserAdmin(UserAdmin):
    add_form = UserCreationForm
    forms = UserChangeForm
    model = User
    list_display = [
        'matrix_id',
    ]
    fieldsets = (
        (None, {"fields": ("matrix_id", "password")}),
        (_("Personal info"), {"fields": ("first_name", "last_name", "email")}),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    ordering = [
        'matrix_id',
    ]


admin.site.register(
    User,
    AlertrixUserAdmin,
)

admin.site.register(
    models.RegistrationToken,
)
