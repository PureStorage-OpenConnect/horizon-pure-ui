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

"""Horizon customization module (HORIZON_CONFIG['customization_module']).

Swaps the project volume Overview tab for the Everpure-aware template and,
when manila-ui is installed, adds the Everpure tab to the share detail
pages. Each hook is optional: a missing dashboard only logs. No array
client is built here; the API object is created on first use.
"""

import logging


LOG = logging.getLogger(__name__)

try:
    from openstack_dashboard.dashboards.project.volumes import tabs

    from horizon_pure.api import pure_flash_array
except ImportError:
    LOG.warning('Cinder volumes dashboard not available; Everpure volume '
                'details disabled')
else:
    _array_api = None

    def _api():
        """The shared FlashArrayAPI, built on first use."""
        global _array_api
        if _array_api is None:
            _array_api = pure_flash_array.FlashArrayAPI()
        return _array_api

    def get_purified_volume_context_data(self, request):
        volume = self.tab_group.kwargs['volume']
        purified_vol = _api().get_volume_info(volume)
        return {'volume': purified_vol,
                'group': getattr(volume, 'group', None)}

    LOG.debug('Setting overrides for the project volume Overview tab.')
    tabs.OverviewTab.template_name = 'project/volumes/pure_detail_view.html'
    tabs.OverviewTab.get_context_data = get_purified_volume_context_data

try:
    from horizon_pure import manila_hook  # noqa: F401
except ImportError:
    LOG.info('manila-ui not installed; Everpure share tab disabled')
except Exception:
    # Horizon re-raises anything this module lets through while building
    # its URLconf, which would take every page down. A broken hook (for
    # example a manila-ui release that renamed its tab groups) must only
    # cost the Everpure share tab.
    LOG.exception('Everpure share tab could not be installed; '
                  'manila-ui share pages are unaffected')
