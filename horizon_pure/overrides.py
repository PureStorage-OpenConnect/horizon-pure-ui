# Copyright (c) 2016 Pure Storage, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import logging

from django.utils.translation import gettext_lazy as _
from horizon import tables
from openstack_dashboard.dashboards.project.volumes import tables \
    as volumes_tables
from openstack_dashboard.dashboards.project.volumes import tabs


from horizon_pure.api import pure_flash_array


LOG = logging.getLogger(__name__)


array_api = pure_flash_array.FlashArrayAPI()


class PureVolumeTable(volumes_tables.VolumesTable):
    used_space = tables.Column('used_space', verbose_name=_("Used"))

    class Meta(volumes_tables.VolumesTable.Meta):
        pass


class PureVolumeTab(tabs.VolumeDetailTabs):
    table_classes = (PureVolumeTable,)

    def get_volumes_data(self):
        volumes = super(PureVolumeTab, self).get_volumes_data()

        purified_volumes = array_api.get_volumes_data(volumes)
        return purified_volumes


def get_purified_volume_context_data(self, request):
    vol = self.tab_group.kwargs['volume']
    purified_vol = array_api.get_volume_info(vol)
    LOG.debug("Patched volume: " + str(purified_vol.to_dict()))
    return {"volume": purified_vol}


LOG.debug("Setting overrides for Project VolumeAndSnapshotTabs.")
# Patch our updated versions of the volume tab into the TabGroup
#vol_tabs = tabs.VolumeAndSnapshotTabs.tabs
#purified_tabs = [PureVolumeTab]
# for tab in vol_tabs:
#     if tab != tabs.VolumeTab:
#         purified_tabs.append(tab)

#tabs.VolumeAndSnapshotTabs.tabs = tuple(vol_tabs)

tabs.OverviewTab.template_name = "project/volumes/pure_detail_view.html"

# TODO: Maybe hook in at the tab group step and see if we can avoid requerying
# so much from the array.
tabs.OverviewTab.get_context_data = get_purified_volume_context_data

LOG.debug("Completed overrides for Project VolumeAndSnapshotTabs.")
