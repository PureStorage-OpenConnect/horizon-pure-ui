# Copyright 2026 Everpure, Inc.
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

"""Detail tabs of a Manila FlashBlade backend."""

from django.utils.translation import gettext_lazy as _

from horizon import exceptions
from horizon import tabs

from horizon_pure.api import pure_flash_blade
from horizon_pure.pure_panel.flashblades import tables as fb_tables


class OverviewTab(tabs.Tab):
    name = _("Overview")
    slug = "overview"
    template_name = "pure_panel/flashblades/detail_view.html"

    def get_context_data(self, request):
        context = super().get_context_data(request)
        backend_id = self.tab_group.kwargs['backend_id']
        context['backend_id'] = backend_id
        try:
            api = pure_flash_blade.FlashBladeAPI()
            context['array'] = api.get_array_info(backend_id, detailed=True)
        except Exception:
            exceptions.handle(self.request,
                              _('Unable to retrieve FlashBlade details.'))
        return context


class ManilaSharesTab(tabs.TableTab):
    name = _("Manila Shares")
    slug = "manila_shares"
    table_classes = (fb_tables.ManilaFileSystemsTable,)
    template_name = "horizon/common/_detail_table.html"
    preload = False

    def get_manila_file_systems_data(self):
        backend_id = self.tab_group.kwargs['backend_id']
        try:
            api = pure_flash_blade.FlashBladeAPI()
            return api.list_manila_file_systems(backend_id)
        except Exception:
            exceptions.handle(
                self.request,
                _('Unable to list Manila file systems on %s.') % backend_id)
            return []


class FlashBladeDetailTabs(tabs.TabGroup):
    slug = "flashblade_details"
    tabs = (OverviewTab, ManilaSharesTab)
