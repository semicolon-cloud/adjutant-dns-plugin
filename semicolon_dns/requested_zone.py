from adjutant.actions.utils import validate_steps
from adjutant.actions.v1.base import BaseAction, ProjectMixin
from adjutant.api import models, utils
from adjutant.api.v1.base import BaseDelegateAPI
from adjutant.common import openstack_clients, user_store
from adjutant.tasks.v1.base import BaseTask

from designateclient.v2 import client as designateclient
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response


class NewRequestedZoneSerializer(serializers.Serializer):
    domain_name = serializers.CharField(max_length=256)
    project_id = serializers.CharField(max_length=64)
    region = serializers.CharField(max_length=100)
    email = serializers.EmailField()


class NewZoneAction(BaseAction, ProjectMixin):
    required = [
        "project_id",
        "region",
        "domain_name",
        "email"
    ]

    serializer = NewRequestedZoneSerializer

    def _validate_domain_name(self):
        if not self.domain_name:
            self.add_note("ERROR: No domain name given.")
            return False
        # actually i need smth more but let's keep it like this for now
        return True

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
                self._validate_domainname,
                self._validate_project_id,
            ]
        )
        self.action.save()

    def _pre_validate(self):
        # Note: Don't check project here as it doesn't exist yet.
        self.action.valid = validate_steps(
            [
                self._validate_region,
                self._validate_domainname,
                self._validate_project_id,
            ]
        )
        self.action.save()

    def _prepare(self):
        self._pre_validate()

    def _create_zone(self):
        designate = designateclient.Client(session=openstack_clients.get_auth_session(), region_name=self.region, sudo_project_id=self.project_id)
        if not self.get_cache("zone_id"):
            try:
                zone = designate.zones.create(self.domain_name, email=self.email)
                self.set_cache("zone_id", zone['id'])
            except Exception as e:
                self.add_note(
                    "Error: '%s' while creating zone: %s"
                    % (e, self.domain_name)
                )
                raise
            self.add_note(
                "Zone %s created for project %s"
                % (self.domain_name, self.project_id)
            )
        else:
            self.add_note(
                "Zone %s already created for project %s"
                % (self.domain_name, self.project_id)
            )

    def _approve(self):
        self.project_id = self.action.task.cache.get("project_id", None)
        self._validate()

        if self.valid:
            self._create_zone()

    def _submit(self, token_data, keystone_user=None):
        pass


class RequestNewZone(BaseTask):
    task_type = "create_zone"
    default_actions = [
        "NewZoneAction",
    ]

    email_config = {
        "initial": None,
        "token": None,
        "completed": {
            "template": "update_quota_completed.txt",
            "subject": "Quota Updated",
        },
    }


class CreateZoneAPI(BaseDelegateAPI):
    """
    The OpenStack endpoint to update the quota of a project in
    one or more regions
    """

    url = r"^openstack/domain/?$"

    task_type = "create_zone"

    _number_of_returned_tasks = 5

    def get_active_quota_tasks(self):
        # Get the 5 last quota tasks.
        task_list = models.Task.objects.filter(
            task_type__exact=self.task_type,
            project_id__exact=self.project_id,
            cancelled=0,
        ).order_by("-created_on")[: self._number_of_returned_tasks]

        response_tasks = []

        for task in task_list:
            status = "Awaiting Approval"
            if task.completed:
                status = "Completed"

            task_data = {}
            for action in task.actions:
                task_data.update(action.action_data)
            new_dict = {
                "id": task.uuid,
                "region": task_data["region"],
                "domain": task_data["domain_name"],
                "request_user": task.keystone_user["username"],
                "task_created": task.created_on,
                "valid": all([a.valid for a in task.actions]),
                "status": status,
            }
            response_tasks.append(new_dict)

        return response_tasks

    def check_region_exists(self, region):
        # Check that the region actually exists
        id_manager = user_store.IdentityManager()
        v_region = id_manager.get_region(region)
        if not v_region:
            return False
        return True

    @utils.mod_or_admin
    def get(self, request):
        """
        This endpoint returns data about what sizes are available
        as well as the current status of a specified region's quotas.
        """

        response_tasks = self.get_active_quota_tasks()

        return Response(
            {
                "active_quota_tasks": response_tasks,
            }
        )

    @utils.mod_or_admin
    def post(self, request):
        request.data["project_id"] = request.keystone_user["project_id"]
        self.project_id = request.keystone_user["project_id"]

        regions = request.data.get("region", None)

        if not regions:
            id_manager = user_store.IdentityManager()
            regions = [region.id for region in id_manager.list_regions()]
            request.data["region"] = regions[0]

        self.logger.info("(%s) - New CreateZone request." % timezone.now())

        self.task_manager.create_from_request(self.task_type, request)

        return Response({"notes": ["task created"]}, status=202)
