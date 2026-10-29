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

"""Tests for horizon_pure.overrides (the Horizon customization module)."""

import builtins
import importlib
import sys
import unittest
from unittest import mock

from openstack_dashboard.dashboards.project.volumes import tabs as vol_tabs
from openstack_dashboard.test import helpers as test

import horizon_pure
from horizon_pure.api import pure_flash_array
from horizon_pure.api import registry
from horizon_pure import overrides

try:
    from manila_ui.dashboards.admin.shares import tabs as admin_tabs
    from manila_ui.dashboards.project.shares import tabs as project_tabs
except ImportError:  # manila-ui not installed
    admin_tabs = project_tabs = None


class OverridesTests(test.TestCase):

    def setUp(self):
        super().setUp()
        registry.reset()
        self.addCleanup(registry.reset)
        self.addCleanup(setattr, overrides, '_array_api',
                        overrides._array_api)
        overrides._array_api = None

    def test_overview_tab_is_patched(self):
        self.assertEqual('project/volumes/pure_detail_view.html',
                         vol_tabs.OverviewTab.template_name)
        self.assertIs(overrides.get_purified_volume_context_data,
                      vol_tabs.OverviewTab.get_context_data)

    def test_api_is_lazy_and_shared(self):
        with mock.patch.object(registry, '_build_client') as build, \
                mock.patch.object(pure_flash_array,
                                  'FlashArrayAPI') as api_cls:
            self.assertIsNone(overrides._array_api)
            first = overrides._api()
            second = overrides._api()
        api_cls.assert_called_once_with()
        self.assertIs(api_cls.return_value, first)
        self.assertIs(first, second)
        build.assert_not_called()

    def test_context_data_uses_shared_api(self):
        volume = mock.Mock(name='volume')
        tab = mock.Mock(name='tab')
        tab.tab_group.kwargs = {'volume': volume}
        with mock.patch.object(pure_flash_array,
                               'FlashArrayAPI') as api_cls:
            api = api_cls.return_value
            api.get_volume_info.return_value = 'purified'
            context = vol_tabs.OverviewTab.get_context_data(tab, self.request)
            vol_tabs.OverviewTab.get_context_data(tab, self.request)

        api.get_volume_info.assert_has_calls([mock.call(volume),
                                              mock.call(volume)])
        api_cls.assert_called_once_with()
        self.assertEqual({'volume': 'purified', 'group': volume.group},
                         context)

    def _tab_groups(self):
        if admin_tabs is None:
            return None
        return (admin_tabs.ShareDetailTabs.tabs,
                project_tabs.ShareDetailTabs.tabs)

    def test_manila_hook_absence_is_tolerated(self):
        # Re-import the customization module with manila-ui "missing":
        # every import of manila_ui fails, so horizon_pure.manila_hook
        # raises ImportError and overrides.py must log and carry on with
        # the Cinder override in place.
        real_import = builtins.__import__

        def without_manila_ui(name, *args, **kwargs):
            if name == 'manila_ui' or name.startswith('manila_ui.'):
                raise ImportError('No module named %r' % name)
            return real_import(name, *args, **kwargs)

        before = self._tab_groups()
        # Cleanups run LIFO: the cached hook (if any) is put back first,
        # then overrides is reloaded so later tests see the hook bound.
        self.addCleanup(importlib.reload, overrides)
        cached = sys.modules.get('horizon_pure.manila_hook')
        if cached is not None:  # manila-ui is installed in this venv
            self.addCleanup(sys.modules.__setitem__,
                            'horizon_pure.manila_hook', cached)
            self.addCleanup(setattr, horizon_pure, 'manila_hook', cached)
            # Force a fresh execution of manila_hook.py: drop the cached
            # module, the package attribute that `from ... import`
            # short-cuts through, and the stale name in overrides (reload
            # keeps a module's dict).
            del sys.modules['horizon_pure.manila_hook']
            del horizon_pure.manila_hook
            del overrides.manila_hook

        with mock.patch('builtins.__import__', new=without_manila_ui), \
                self.assertLogs('horizon_pure.overrides',
                                level='INFO') as logs:
            importlib.reload(overrides)

        self.assertEqual(['INFO:horizon_pure.overrides:manila-ui not '
                          'installed; Everpure share tab disabled'],
                         logs.output)
        self.assertFalse(hasattr(overrides, 'manila_hook'))
        self.assertNotIn('horizon_pure.manila_hook', sys.modules)
        # The Cinder override from the same import is still in place.
        self.assertEqual('project/volumes/pure_detail_view.html',
                         vol_tabs.OverviewTab.template_name)
        self.assertIs(overrides.get_purified_volume_context_data,
                      vol_tabs.OverviewTab.get_context_data)
        # The failed import never reached install(): groups untouched.
        self.assertEqual(before, self._tab_groups())

    @unittest.skipIf(admin_tabs is None, 'manila-ui is not installed')
    def test_hook_failure_does_not_break_the_customization_module(self):
        # A manila-ui release that renames ShareDetailTabs makes
        # manila_hook.py raise AttributeError (not ImportError) while it
        # executes. Horizon re-raises whatever the customization module
        # lets through out of its URLconf, which 500s every page, so
        # overrides.py must contain the failure to the share tab.
        from horizon_pure import manila_hook as hook
        original_tab = hook.EverpureShareTab
        admin_group = admin_tabs.ShareDetailTabs
        self.addCleanup(importlib.reload, overrides)
        self.addCleanup(setattr, horizon_pure, 'manila_hook', hook)
        self.addCleanup(setattr, admin_tabs, 'ShareDetailTabs', admin_group)
        with mock.patch.dict(sys.modules):
            del sys.modules['horizon_pure.manila_hook']
            del horizon_pure.manila_hook
            del admin_tabs.ShareDetailTabs
            with self.assertLogs('horizon_pure.overrides',
                                 level='ERROR') as logs:
                importlib.reload(overrides)  # returns instead of raising
        admin_tabs.ShareDetailTabs = admin_group

        self.assertEqual(1, len(logs.output))
        self.assertIn('could not be installed', logs.output[0])
        self.assertIn('AttributeError', logs.output[0])
        self.assertIn('ShareDetailTabs', logs.output[0])
        self.assertIn('horizon_pure.overrides', sys.modules)
        self.assertEqual('project/volumes/pure_detail_view.html',
                         vol_tabs.OverviewTab.template_name)
        self.assertIs(overrides.get_purified_volume_context_data,
                      vol_tabs.OverviewTab.get_context_data)
        # The failure came before install(): neither group was touched.
        for group in (admin_group, project_tabs.ShareDetailTabs):
            self.assertIs(original_tab, group.tabs[-1])
