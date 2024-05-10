import nio
import synapse.appservice
from asgiref.sync import async_to_sync
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView
from matrixappservice import models as mas_models
from .. import forms
from .. import mixins
from .. import models


class CreateCompany(
    PermissionRequiredMixin,
    mixins.ContextActionsMixin,
    CreateView,
):
    permission_required = 'alertrix.add_company'
    model = models.Company
    form_class = forms.company.CompanyForm
    template_name = 'alertrix/form.html'
    http_method_names = [
        'get',
        'post',
    ]
    context_actions = [
        {'name': 'comp.list', 'label': _('list')},
    ]

    def get_form_kwargs(self):
        kwargs = {
            'user': self.request.user,
            **super().get_form_kwargs(),
        }
        return kwargs

    def get_success_url(self):
        return reverse('comp.detail', kwargs={'slug': self.object.slug})

    def form_invalid(self, form):
        """
        Return a form response that has all the previous inputs in it (as per default), but also all the
        autogenerated content.
        """
        form.full_clean()
        initial = form.cleaned_data.copy()
        for name in form.fields:
            if name in form.cleaned_data:
                continue
            if hasattr(form, 'clean_%s' % name):
                initial[name] = getattr(form, 'clean_%s' % name)()
            else:
                initial[name] = form.data[name]
        new_form = self.get_form_class()(
            user=self.request.user,
            initial=initial,
        )
        new_form._errors = form._errors
        return self.render_to_response(self.get_context_data(form=new_form))

    def form_valid(self, form):
        response = super().form_valid(form)
        group_name = form.cleaned_data['admin_group_name']
        if self.request.user.groups.filter(
                name=group_name,
        ).exists():
            group = Group.objects.get(
                name=group_name,
            )
        else:
            group = Group.objects.create(
                name=group_name,
            )
            self.request.user.groups.add(
                group,
            )
        self.object.admins = group
        messages.success(
            self.request,
            _('user has been added to group'),
        )
        if not self.object.responsible_user:
            homeserver_name = form.cleaned_data['matrix_user_id'].split(':')[1]
            hs = mas_models.Homeserver.objects.get(
                server_name=homeserver_name,
            )
            mu, is_new = mas_models.User.objects.get_or_create(
                user_id=form.cleaned_data['matrix_user_id'],
                homeserver=hs,
                app_service=self.object.handler.application_service,
            )
            if is_new:
                try:
                    async_to_sync(mu.register)()
                except matrixappservice.exceptions.MUserInUse:
                    logging.error(
                        '%(user_id)s already exists on server, but is not known to the database',
                    )
            mu.save()
            self.object.responsible_user = mu
        if not self.object.matrix_room_id:
            alias_namespaces = mas_models.Namespace.objects.filter(
                app_service=self.object.handler.application_service,
                scope=mas_models.Namespace.ScopeChoices.aliases,
            )
            # Prepare the alias variable
            alias = None
            # Create a synapse instance to check if its application service is interested in the generated user id
            syn: synapse.appservice.ApplicationService = async_to_sync(
                self.object.handler.application_service.get_synapse_application_service
            )()
            for namespace in alias_namespaces:
                if '*' not in namespace.regex:
                    continue
                localpart = namespace.regex.lstrip('@').replace('*', self.object.slug)
                interested_check_against = '@%(localpart)s:%(server_name)s' % {
                    'localpart': localpart,
                    'server_name': self.object.handler.application_service.homeserver.server_name,
                }
                if not syn.is_interested_in_user(
                        user_id=interested_check_against,
                ):
                    continue
                # Overwrite user_id variable
                alias = interested_check_against
                messages.info(
                    self.request,
                    _('the matrix room alias has automatically been set to \"%(alias)s\"') % {
                        'alias': alias,
                    },
                )
                break
            matrix_space_id = async_to_sync(self.create_matrix_room)(
                alias=alias,
                name=form.data['name'],
                topic=form.data['description'],
                federate=form.data['federate'],
                initial_state=[
                    {
                        'type': 'm.room.member',
                        'content': {
                            'membership': 'join',
                            'displayname': form.data['name'],
                        },
                        'state_key': self.object.responsible_user.user_id,
                    },
                ],
                invite=(
                    [
                        str(self.request.user.matrix_id)
                    ]
                    if self.request.user.groups.filter(name=settings.MATRIX_VALIDATED_GROUP_NAME).exists() else None
                ),
                power_level_override=(
                    {
                        'users': {
                            self.object.responsible_user.user_id: 100,
                            str(self.request.user.matrix_id): 100,
                        },
                    }
                    if self.request.user.groups.filter(name=settings.MATRIX_VALIDATED_GROUP_NAME).exists() else None
                ),
                space=True,
            )
            if matrix_space_id:
                if self.request.user.matrix_id:
                    messages.success(
                        self.request,
                        _('%(user_id)s has been invited') % {
                            'user_id': self.request.user.matrix_id,
                        },
                    )
            self.object.matrix_room_id = matrix_space_id
        self.object.save()
        return response

    async def create_matrix_room(
            self,
            **kwargs,
    ):
        client: nio.AsyncClient = await self.object.responsible_user.get_client()
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
            return None
        return response.room_id
