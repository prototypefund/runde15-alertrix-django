import logging
from typing import Optional

import nio
from asgiref.sync import async_to_sync
from asgiref.sync import sync_to_async
from django import views
from django.conf import settings
from django.contrib import messages
from django.db.models import Q
from django.db.models import QuerySet
from django.http import HttpResponseRedirect
from django.http import JsonResponse
from django.utils.translation import gettext_lazy as _
from matrixappservice import models
from matrixappservice.database.models import Account



class CreateMatrixRoom(
    views.generic.FormView,
):
    """
    Parent CreateView to create MatrixRoom objects.
    """
    template_name = 'alertrix/form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        kwargs['initial'] = {
            **kwargs['initial'],
            **self.request.GET.dict(),
        }
        if self.request.POST:
            kwargs['data'] = self.request.POST
        return kwargs

    def get_matrix_state_events(self, form):
        return []

    async def aget_secondary_matrix_state_events(self, form, room_id):
        """

        :param form: This views form.
        :param room_id: The room_id of the newly created room.
        :return: Yields state events.
        """
        yield

    def get_invites(self, form) -> QuerySet:
        return models.User.objects.none()

    def get_ban_permission_level(self) -> Optional[int]:
        return

    def get_events_permission_level(self) -> Optional[dict[str, int]]:
        return

    def get_events_default_permission_level(self) -> Optional[int]:
        return

    def get_invite_permission_level(self) -> Optional[int]:
        return

    def get_kick_permission_level(self) -> Optional[int]:
        return

    def get_notifications_permission_level(self) -> Optional[dict[str, int]]:
        return

    def get_redact_permission_level(self) -> Optional[int]:
        return

    def get_state_default_permission_level(self) -> Optional[int]:
        return

    def get_users_permission_level(self) -> Optional[dict[str, int]]:
        return {
            user_id: power_level
            for user_id, power_level in {
                **{
                    self.request.user.matrix_id: 100
                    if self.request.user.groups.filter(name=settings.MATRIX_VALIDATED_GROUP_NAME).exists() else None
                },
                str(self.responsible_user.user_id): 100,
            }.items()
            if type(power_level) is int
        }

    def get_users_default_permission_level(self) -> Optional[int]:
        return

    def get_permission_levels(self):
        permission_levels = {
            'ban': self.get_ban_permission_level(),
            'events': self.get_events_permission_level(),
            'events_default': self.get_events_default_permission_level(),
            'invite': self.get_invite_permission_level(),
            'kick': self.get_kick_permission_level(),
            'notifications': self.get_notifications_permission_level(),
            'redact': self.get_redact_permission_level(),
            'state_default': self.get_state_default_permission_level(),
            'users': self.get_users_permission_level(),
            'users_default': self.get_users_default_permission_level(),
        }
        return {
            k: permission_levels[k]
            for k in permission_levels.keys()
            if permission_levels[k] not in [None, {}]
        }

    def get_matrix_room_args(
            self,
            form,
            **kwargs,
    ):
        """
        Return the arguments used to create the room.
        :param form:
        :return:
        """
        return dict(
            name=form.data['name'],
            topic=form.data.get('description'),
            federate=form.data['federate'] == 'on' if 'federate' in form.data else False,
            initial_state=self.get_matrix_state_events(
                form=form,
            ),
            invite=(
                [
                    str(self.request.user.matrix_id)
                ]
                if self.request.user.groups.filter(name=settings.MATRIX_VALIDATED_GROUP_NAME).exists() else list()
            ) + list(
                self.get_invites(
                    form,
                ).filter(
                    ~Q(
                        user_id=self.responsible_user.user_id,
                    ),
                ).values_list(
                    'user_id',
                    flat=True,
                )
            ),
            power_level_override=self.get_permission_levels(),
            space=True,
            **kwargs,
        )

    async def create_matrix_room(
            self,
            **kwargs,
    ):
        client: nio.AsyncClient = await self.responsible_user.aget_client()
        response: nio.RoomCreateResponse = await client.room_create(
            **kwargs
        )
        if type(response) is nio.RoomCreateError:
            messages.warning(
                self.request,
                _('failed to create matrix space: %(errcode)s %(error)s') % {
                    'errcode': response.status_code,
                    'error': response.message,
                },
            )
            await client.close()
            return None
        async for state_event in self.aget_secondary_matrix_state_events(
                self.form,
                room_id=response.room_id,
        ):
            if state_event is None:
                continue
            if state_event.get('room_id') != response.room_id:
                room = models.Room(state_event.get('room_id'))
                try:
                    power_levels = (await room.aget_power_levels()).content.get('users')
                    users = models.User.objects.filter(
                        Q(
                            user_id__in=models.Event.objects.filter(
                                type='m.room.member',
                                room_id=state_event.get('room_id'),
                                content__membership='join',
                            ).values_list(
                                'state_key',
                                flat=True,
                            ),
                        ),
                        Q(
                            user_id__in=power_levels.keys(),
                        ),
                        Q(
                            user_id__in=Account.objects.filter(
                                account__isnull=False,
                            ).values_list(
                                'user_id',
                                flat=True,
                            ),
                        ),
                    )
                    user = sorted(
                        await sync_to_async(list)(users),
                        key=lambda x: power_levels[x.user_id],
                    )[0]
                except models.Event.DoesNotExist:
                    user = await models.User.objects.aget(
                        user_id=await models.Event.objects.aget(
                            type='m.room.create',
                            room=room,
                        ).content.get('creator'),
                    )
                c = await user.aget_client()
            else:
                c = client
            room_put_state_response: nio.RoomPutStateResponse = await c.room_put_state(
                event_type=state_event.pop('type'),
                **state_event,
            )
            if type(room_put_state_response) is nio.RoomPutStateError:
                logging.error(room_put_state_response)
                messages.error(
                    self.request,
                    room_put_state_response,
                )
            if c != client:
                await c.close()
        await client.close()
        return response.room_id

    async def room_put_state(
            self,
            room_id: str,
            event_type: str,
            content,
            state_key: str = "",
    ):
        client: nio.AsyncClient = await self.responsible_user.aget_client()
        if client is not None:
            response: nio.RoomPutStateResponse | nio.RoomPutStateError = await client.room_put_state(
                room_id=room_id,
                event_type=event_type,
                content=content,
                state_key=state_key,
            )
        await client.close()

    async def aafter_room_creation(
            self,
            room_id: str,
    ):
        """
        Child classes can override this method.

        :param room_id: The room_id of the newly created room.
        :return:
        """
        return None

    def after_room_creation(
            self,
            room_id: str,
    ):
        return async_to_sync(self.aafter_room_creation)(
            room_id,
        )

    def form_valid(self, form):
        self.form = form
        self.responsible_user: models.User
        if not form.cleaned_data.get('room_id'):
            room_id = async_to_sync(self.create_matrix_room)(
                **self.get_matrix_room_args(
                    form=form,
                ),
            )
        else:
            room_id = form.cleaned_data.get('room_id')
        self.instance = models.Room(
            room_id=room_id,
        )
        self.after_room_creation(
            room_id,
        )
        client = self.responsible_user.get_client()
        async_to_sync(client.sync_n)(
            n=1,
        )
        if self.request.META.get('HTTP_ACCEPT') == 'application/json':
            return JsonResponse(
                {
                    'room_id': room_id,
                },
            )
        return HttpResponseRedirect(self.get_success_url())
