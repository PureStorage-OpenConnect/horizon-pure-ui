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

from horizon_pure.api import pure_fa_files
from horizon_pure.api import pure_flash_array
from horizon_pure.api import pure_flash_blade
from horizon_pure.pure_panel import tabs as pure_tabs


class IndexView(tabs.TabbedTableView):
    template_name = 'pure_panel/index.html'
    tab_group_class = pure_tabs.PurePanelTabs
    page_title = _("Everpure")

    def _total_stats(self, api_class, message):
        """``get_total_stats`` of a freshly built API object, or None.

        None when that kind of array is not configured (the APIs return
        {}) and when the call fails; the failure is reported through
        exceptions.handle and the page still renders.
        """
        try:
            return api_class().get_total_stats() or None
        except Exception:
            exceptions.handle(self.request, message)
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['fa_stats'] = self._total_stats(
            pure_flash_array.FlashArrayAPI,
            _('Unable to retrieve FlashArray statistics.'))
        context['fb_stats'] = self._total_stats(
            pure_flash_blade.FlashBladeAPI,
            _('Unable to retrieve FlashBlade statistics.'))
        context['fafiles_stats'] = self._total_stats(
            pure_fa_files.FlashArrayFilesAPI,
            _('Unable to retrieve FlashArray Files statistics.'))
        return context
