from unittest import IsolatedAsyncioTestCase
from urllib.parse import urlencode

import nio
import time
from asgiref.sync import sync_to_async
from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.test import AsyncClient
from django.urls import reverse
from matrixappservice import models as mas_models

from . import callbacks
from . import models
from . import querysets
from .events import v1 as events
from .test import AppserviceSetup


class MatrixRoomTest(
    AppserviceSetup,
    IsolatedAsyncioTestCase
):
    """
    Test managing companies and units
    """

    async def test_create_organisation_and_unit(self):
        # Create a Matrix-Account for the test user in the scope of the application service
        mx_user, new = await mas_models.User.objects.aget_or_create(
            user_id='@alertrix_OrganisationTest_test_create_organisation_and_unit-user:synapse.localhost',
            app_service=self.app_service,
            prevent_automated_responses=True,
        )
        main_app_service_key = await models.MainApplicationServiceKey.objects.aget()
        main_user_key = await models.MainUserKey.objects.aget(
            service=await sync_to_async(getattr)(main_app_service_key, 'service'),
        )
        main_user: mas_models.User = await sync_to_async(getattr)(main_user_key, 'user')

        messages = {}

        def store_messages(c, r, e):
            if c.user_id not in messages:
                messages[c.user_id] = []
            messages[c.user_id].append([r, e])

        mx_client = await mx_user.aget_client()
        mx_client.add_event_callback(
            store_messages,
            nio.Event,
        )
        mx_client.add_event_callback(
            callbacks.encryption.verify_all_devices,
            nio.RoomMessage,
        )
        mx_client.add_event_callback(
            callbacks.encryption.verify_all_devices,
            nio.RoomMemberEvent,
        )
        mx_client.add_event_callback(
            lambda c, r, e: c.join(r.room_id),
            nio.InviteMemberEvent,
        )

        room_create_response = await mx_client.room_create(
            preset=nio.RoomPreset.trusted_private_chat,
            invite=(
                main_user.user_id,
            ),
            is_direct=True,
            initial_state=[
                nio.EnableEncryptionBuilder().as_dict(),
            ],
        )
        await mx_client.sync_n(
            n=1,
        )
        start = time.time()
        end = start + 20
        # waiting for bot to join
        while time.time() < end:
            if await mas_models.Event.objects.filter(
                room__room_id=room_create_response.room_id,
                type='m.room.member',
                content__membership='join',
                state_key=main_user.user_id,
            ).aexists():
                break
            await mx_client.sync_n(
                n=1,
            )
        await sync_to_async(self.assertIn)(
            ('join', mx_client.user_id),
            mas_models.Event.objects.filter(
                room__room_id=room_create_response.room_id,
                type='m.room.member',
            ).values_list(
                'content__membership', 'state_key',
            ),
        )
        await sync_to_async(self.assertIn)(
            ('join', main_user.user_id),
            mas_models.Event.objects.filter(
                room__room_id=room_create_response.room_id,
                type='m.room.member',
            ).values_list(
                'content__membership', 'state_key',
            ),
        )
        await mx_client.sync_n(
            n=1,
        )
        await mx_client.room_send(
            room_create_response.room_id,
            'm.room.message',
            {
                'msgtype': 'm.text',
                'body': 'start',
            },
        )
        await mx_client.sync_n(
            n=1,
        )
        start = time.time()
        end = start + 2
        while time.time() < end:
            if await mas_models.Event.objects.filter(
                    room__room_id=room_create_response.room_id,
                    type='im.vector.modular.widgets',
            ).aexists():
                break
        else:
            self.fail(
                'did not receive widget event in time',
            )
        widget_event = await mas_models.Event.objects.aget(
            room__room_id=room_create_response.room_id,
            type='im.vector.modular.widgets',
        )
        url = widget_event.content['url']
        client = AsyncClient()
        # Do not allow every user to access the company creation form
        resp = await client.get(
            reverse('comp.new'),
        )
        self.assertEqual(
            resp.status_code,
            403,
        )
        user = await get_user_model().objects.aget(
            matrix_id=mx_client.user_id,
        )
        self.assertGreater(
            await user.groups.acount(),
            0,
            'user is not part of any group',
        )
        # Allow access to the company creation form now
        resp = await client.get(
            reverse('comp.new'),
        )
        self.assertEqual(
            resp.status_code,
            200,
        )
        company_initial_data = {
            'name': 'OrganisationTest test create organisation and unit Company',
            'description': 'Hello World!',
            'application_service': self.app_service.pk,
        }
        resp = await client.post(
            reverse('comp.new'),
            data=company_initial_data,
        )
        self.assertEqual(
            resp.status_code,
            302,
        )
        await mx_client.sync_n(
            n=1,
        )
        company = await models.Company.objects.aget(
            room_id__in=mas_models.Event.objects.filter(
                type='m.room.name',
                content__name=company_initial_data['name'],
            ).values_list(
                'room__room_id',
                flat=True,
            ),
        )
        self.assertEqual(
            company.room_id,
            (
                await mas_models.Room.objects.aget(
                    room_id__in=mas_models.Event.objects.filter(
                        type='m.room.member',
                        state_key=mx_client.user_id,
                        content__membership='join',
                    ).values_list(
                        'room__room_id',
                        flat=True,
                    ),
                )
            ).room_id,
            'User has not received an invite to a room with the correct name',
        )
        resp = await client.get(
            reverse('unit.new'),
        )
        self.assertEqual(
            resp.status_code,
            200,
        )
        unit_initial_data = {
            'name': 'OrganisationTest test create organisation and unit Unit',
            'description': 'Hello, World!',
            'companies': [
                company.room_id,
            ],
        }
        resp = await client.post(
            reverse('unit.new'),
            data=unit_initial_data,
        )
        self.assertEqual(
            resp.status_code,
            302,
        )
        await mx_client.sync_n(
            n=1,
        )
        units = models.Unit.objects.filter(
            room_id__in=mas_models.Event.objects.filter(
                type='m.room.name',
                content__name=unit_initial_data['name'],
            ).values_list(
                'room__room_id',
                flat=True,
            ),
        )
        unit = await units.aget()
        self.assertIn(
            unit.room_id,
            await sync_to_async(list)(
                mas_models.Event.objects.filter(
                    type='m.room.member',
                    state_key=mx_client.user_id,
                    content__membership='join',
                ).values_list(
                    'room__room_id',
                    flat=True,
                ).distinct(
                ),
            ),
            'User has not received an invite to a room with the correct name',
        )
        await mx_client.close()
