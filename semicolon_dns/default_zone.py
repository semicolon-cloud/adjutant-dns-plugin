from adjutant.actions.utils import validate_steps
from adjutant.actions.v1.base import BaseAction, ProjectMixin
from adjutant.common import openstack_clients, user_store

from designateclient.v2 import client as designateclient
from rest_framework import serializers


class NewDefaultZoneSerializer(serializers.Serializer):
    project_id = serializers.CharField(max_length=64)
    region = serializers.CharField(max_length=100)
    email = serializers.EmailField()


class NewDefaultZoneAction(BaseAction, ProjectMixin):
    required = [
        "project_id",
        "region",
        "email"
    ]

    serializer = NewDefaultZoneSerializer

    def _validate_region(self):
        if not self.region:
            self.add_note("ERROR: No region given.")
            return False

        id_manager = user_store.IdentityManager()
        region = id_manager.get_region(self.region)
        if not region:
            self.add_note("ERROR: Region does not exist.")
            return False

        self.add_note("Region: %s exists." % self.region)
        return True

    def _validate(self):
        self.action.valid = validate_steps(
            [
                self._validate_region,
                self._validate_project_id,
            ]
        )
        self.action.save()

    def _pre_validate(self):
        # Note: Don't check project here as it doesn't exist yet.
        self.action.valid = validate_steps(
            [
                self._validate_region,
            ]
        )
        self.action.save()

    def _prepare(self):
        self._pre_validate()

    def _create_zone(self):
        designate = designateclient.Client(session=openstack_clients.get_auth_session(), region_name=self.region, sudo_project_id=self.project_id)
        if not self.get_cache("zone_id"):
            try:
                zone = designate.zones.create(self.project_id + '.scloud.seda.club.', email=self.email)
                self.set_cache("zone_id", zone['id'])
            except Exception as e:
                self.add_note(
                    "Error: '%s' while creating zone: %s"
                    % (e, self.project_id + '.scloud.seda.club.')
                )
                raise
            self.add_note(
                "Zone %s created for project %s"
                % (self.project_id + '.scloud.seda.club.', self.project_id)
            )
        else:
            self.add_note(
                "Zone %s already created for project %s"
                % (self.project_id + '.scloud.seda.club.', self.project_id)
            )

    def _approve(self):
        self._validate()

        if self.valid:
            self._create_zone()

    def _submit(self, token_data, keystone_user=None):
        pass

