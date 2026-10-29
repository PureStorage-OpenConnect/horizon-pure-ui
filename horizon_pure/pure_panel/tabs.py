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

"""Tabs of the Everpure admin panel: one table of backends per array kind.

A tab is shown only when its kind is configured (``allowed`` asks the
registry). The API objects are created inside the data methods, never at
import time, because building an array client performs network I/O.
"""

import logging

from django.utils.translation import gettext_lazy as _

from horizon import exceptions
from horizon import tabs

from horizon_pure.api import pure_fa_files
from horizon_pure.api import pure_flash_array
from horizon_pure.api import pure_flash_blade
from horizon_pure.api import registry
from horizon_pure.pure_panel import tables


LOG = logging.getLogger(__name__)


def array_rows(api, backends):
    """``api.get_array_info`` for each backend name; failures are skipped.

    The APIs report an unusable array as an 'Error: ...' row themselves,
    so an exception here is logged in full and must not lose the other
    rows.
    """
    rows = []
    for backend in backends:
        try:
            rows.append(api.get_array_info(backend))
        except Exception:
            LOG.exception('Failed to get array info for %s', backend)
    LOG.debug('Returning %d of %d arrays', len(rows), len(backends))
    return rows


class FlashArrayTab(tabs.TableTab):
    name = _("FlashArrays")
    slug = "flasharray_tab"
    table_classes = (tables.PureFlashArrayTable,)
    template_name = "horizon/common/_detail_table.html"
    preload = False

    def allowed(self, request):
        return bool(registry.entries(service='cinder', kind='fa'))

    def get_flasharrays_data(self):
        try:
            api = pure_flash_array.FlashArrayAPI()
            return array_rows(api, api.get_array_list())
        except Exception as exc:
            exceptions.handle(self.request,
                              _('Unable to retrieve FlashArrays: %s') % exc)
            return []


class FlashBladeTab(tabs.TableTab):
    name = _("FlashBlades")
    slug = "flashblade_tab"
    table_classes = (tables.PureFlashBladeTable,)
    template_name = "horizon/common/_detail_table.html"
    preload = False

    def allowed(self, request):
        return bool(registry.entries(service='manila', kind='fb'))

    def get_flashblades_data(self):
        try:
            api = pure_flash_blade.FlashBladeAPI()
            return array_rows(api, api.get_backend_list())
        except Exception as exc:
            exceptions.handle(self.request,
                              _('Unable to retrieve FlashBlades: %s') % exc)
            return []


class FlashArrayFilesTab(tabs.TableTab):
    name = _("FlashArray Files")
    slug = "fafiles_tab"
    table_classes = (tables.PureFlashArrayFilesTable,)
    template_name = "horizon/common/_detail_table.html"
    preload = False

    def allowed(self, request):
        return bool(registry.entries(service='manila', kind='fa'))

    def get_fafiles_data(self):
        try:
            api = pure_fa_files.FlashArrayFilesAPI()
            return array_rows(api, api.get_backend_list())
        except Exception as exc:
            exceptions.handle(
                self.request,
                _('Unable to retrieve FlashArray Files backends: %s') % exc)
            return []


class PurePanelTabs(tabs.TabGroup):
    slug = "pure_panel_tabs"
    tabs = (FlashArrayTab, FlashBladeTab, FlashArrayFilesTab)
    sticky = True
