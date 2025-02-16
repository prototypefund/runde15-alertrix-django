from typing import Iterable
from typing import List

from django.conf import settings
from django.db.models.query import QuerySet
from matrixappservice.models import *

from . import models


def get_companies_for_unit(
        unit: [
            Iterable,
            List[str],
            QuerySet,
            Room,
            models.Unit,
        ],
):
    return models.Company.objects.filter(
        room_id__in=Event.objects.filter(
            type='%(prefix)s.company.unit' % {
                'prefix': settings.ALERTRIX_STATE_EVENT_PREFIX,
            },
            **(
                dict(
                    state_key=unit.room_id,
                )
                if type(unit) is Room
                else
                dict(
                    state_key__in=unit,
                )
                if '__iter__' in dir(unit)
                else
                dict(
                    state_key__in=unit.values_list(
                        'state_key',
                        flat=True,
                    ),
                )
                if type(unit) is QuerySet
                else
                dict()
            ),
        ).values_list(
            'room__room_id',
            flat=True,
        ),
    )


def get_units_for_company(
        company: Room,
):
    return models.Unit.objects.get_queryset().filter(
        room_id__in=Event.objects.filter(
            type='%(prefix)s.company.unit' % {
                'prefix': settings.ALERTRIX_STATE_EVENT_PREFIX,
            },
            state_key__isnull=False,
            room=company,
        ).values_list(
            'state_key',
            flat=True,
        ),
    )
