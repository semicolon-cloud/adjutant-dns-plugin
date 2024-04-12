from adjutant.feature_set import BaseFeatureSet

from semicolon_dns.default_zone import NewDefaultZoneAction
from semicolon_dns.requested_zone import NewZoneAction, RequestNewZone, CreateZoneAPI


class MyFeatureSet(BaseFeatureSet):

    actions = [
        NewDefaultZoneAction,
        NewZoneAction
    ]

    tasks = [
        RequestNewZone,
    ]

    delegate_apis = [
        CreateZoneAPI,
    ]