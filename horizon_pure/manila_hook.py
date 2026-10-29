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

"""Everpure tab on the manila-ui share detail pages.

``horizon_pure.overrides`` imports this module inside ``try/except
ImportError``. The manila-ui imports below are deliberately unguarded: when
manila-ui is not installed the ImportError propagates and the customization
module simply skips the hook.

Importing the module appends :class:`EverpureShareTab` to both the admin
and the project ``ShareDetailTabs`` groups of manila-ui 16 (``install()``
is idempotent). The tab is only offered when a Manila backend is configured
(``PURE_FLASH_BLADES`` / ``PURE_FLASH_ARRAY_FILES``) and loads on demand,
so an unreachable array never slows the share detail page itself down.
"""

import logging

from django.utils.translation import gettext_lazy as _
from horizon import tabs
from manila_ui.dashboards.admin.shares import tabs as admin_tabs
from manila_ui.dashboards.project.shares import tabs as project_tabs

from horizon_pure.api import pure_manila
from horizon_pure.api import registry


LOG = logging.getLogger(__name__)

#: the manila-ui tab groups that receive the Everpure tab
TAB_GROUPS = (admin_tabs.ShareDetailTabs, project_tabs.ShareDetailTabs)


class EverpureShareTab(tabs.Tab):
    """Array-side view of a Manila share on an Everpure backend.

    Context: ``share`` (the manila-ui share object) and ``info`` (the dict
    from ``pure_manila.get_share_info``). ``info`` is always a dict: a
    failure inside the lookup becomes ``{'configured': True, 'found':
    False, 'error': <text>, 'is_admin': <bool>}`` so the template can
    show it (the error text to administrators only).
    """
    name = _("Everpure")
    slug = "everpure_share_tab"
    template_name = "pure_panel/shares/_everpure_tab.html"
    preload = False

    def allowed(self, request):
        """Shown only when at least one Manila backend is configured.

        A broken setting must not take the whole share detail page down,
        so an error here hides the tab and is logged instead.
        """
        try:
            return bool(registry.entries(service='manila'))
        except Exception:
            LOG.exception('Unable to read the Everpure Manila settings; '
                          'hiding the Everpure share tab')
            return False

    def get_context_data(self, request):
        share = self.tab_group.kwargs['share']
        try:
            info = pure_manila.get_share_info(request, share)
        except Exception as exc:
            LOG.exception('Everpure share tab failed for share %s',
                          getattr(share, 'id', None))
            # The template gates the error text on is_admin; without the
            # key administrators would lose it too.
            info = {'configured': True, 'found': False, 'error': str(exc),
                    'is_admin': pure_manila.request_is_admin(request)}
        return {'share': share, 'info': info}


def install():
    """Append EverpureShareTab to both manila-ui share detail tab groups.

    Idempotent: a tab carrying the Everpure slug that is already present
    (this class, or a stale one left by a module reload) is replaced, so
    the tab is never duplicated and always comes last.
    """
    for group in TAB_GROUPS:
        kept = tuple(tab for tab in group.tabs
                     if getattr(tab, 'slug', None) != EverpureShareTab.slug)
        group.tabs = kept + (EverpureShareTab,)
        LOG.debug('Everpure share tab installed on %s.%s',
                  group.__module__, group.__name__)


install()
