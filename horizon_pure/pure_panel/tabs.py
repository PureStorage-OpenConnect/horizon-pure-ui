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

from django.utils.translation import gettext_lazy as _

from horizon import exceptions
from horizon import tabs
import re

from horizon_pure.api import pure_flash_array
from horizon_pure.pure_panel import tables


class FlashArrayTab(tabs.TableTab):
    name = _("FlashArrays")
    slug = "flasharray_tab"
    table_classes = (tables.PureFlashArrayTable,)
    template_name = "horizon/common/_detail_table.html"
    preload = False
    array_api = None

    def has_more_data(self, table):
        return self._has_more

    def get_flasharrays_data(self):
        import logging
        LOG = logging.getLogger(__name__)

        try:
            # TODO: Add pagination
            self._has_more = False

            if not self.array_api:
                LOG.debug('Initializing FlashArrayAPI')
                self.array_api = pure_flash_array.FlashArrayAPI()

            arrays = []
            backends = self.array_api.get_array_list()
            LOG.debug('Found %d backends: %s' % (len(backends), backends))

            for be in backends:
                LOG.debug('Getting array info for backend: %s' % be)
                try:
                    array_info = self.array_api.get_array_info(be)
                    LOG.debug('Array info for %s: %s' % (be, str(array_info)))
                    arrays.append(array_info)
                except Exception as e:
                    LOG.exception('Failed to get array info for %s: %s' % (be, str(e)))
                    # Continue to next array instead of failing completely
                    continue

            LOG.debug('Returning %d arrays' % len(arrays))
            return arrays

        except Exception as e:
            LOG.exception('Exception in get_flasharrays_data: %s' % str(e))
            error_message = _('Unable to get arrays: %s') % str(e)
            exceptions.handle(self.request, error_message)
            return []


class PurePanelTabs(tabs.TabGroup):
    slug = "pure_panel_tabs"
    tabs = (FlashArrayTab,)
    sticky = True
