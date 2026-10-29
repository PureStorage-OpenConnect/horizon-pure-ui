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

"""Tests for horizon_pure.manila_hook (the manila-ui share detail tab).

The whole module is skipped when manila-ui is not installed, which is the
same condition under which ``overrides.py`` skips the hook.
"""

import datetime
import importlib
import types
import unittest
from unittest import mock

from django.test import override_settings
from django.urls import reverse

from openstack_dashboard.test import helpers as test

from horizon_pure.api import pure_manila
from horizon_pure.api import registry

try:
    from manila_ui.api import manila as manila_api
    from manila_ui.dashboards.admin.shares import tabs as admin_tabs
    from manila_ui.dashboards.project.shares import tabs as project_tabs
    from manila_ui.tests.dashboards.project import test_data as manila_data
    # manila-ui's helpers add the 'share' service to the test catalog;
    # without it the share panels answer 403.
    from manila_ui.tests import helpers as manila_test

    from horizon_pure import manila_hook
    from horizon_pure.tests import test_pure_fa_files as fa_fixtures
    from horizon_pure.tests import test_pure_flash_blade as fb_fixtures
except ImportError:  # manila-ui not installed
    manila_hook = None


SLUG = 'everpure_share_tab'
TAB_PARAM = {'tab': 'share_details__' + SLUG}
SHARE_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
IID1 = '11111111-2222-3333-4444-555555555555'
IID2 = '66666666-7777-8888-9999-000000000000'
FS1 = 'share-%s-manila' % IID1
FS2 = 'share-%s-manila' % IID2
FA_DIR = 'openstack:share-%s-manila' % SHARE_ID
FB_TARGET = '192.0.2.20'
FA_TARGET = '192.0.2.10'
FB_CONF = {'mgmt_ip': FB_TARGET, 'api_token': 'tok',
           'backend_name': 'flashblade'}
FA_CONF = {'san_ip': FA_TARGET, 'api_token': 'tok',
           'backend_name': 'flasharray-files'}
CREATED = datetime.datetime(2023, 11, 14, 22, 13, 20,
                            tzinfo=datetime.timezone.utc)
PERF = {
    'reads_per_sec': 100, 'writes_per_sec': 50,
    'output_per_sec': 2.0, 'input_per_sec': 0.5,
    'usec_per_read_op': 300, 'usec_per_write_op': 400,
}


def _share(share_id=SHARE_ID, **attrs):
    return types.SimpleNamespace(id=share_id, name='my-share', **attrs)


def _user(admin):
    """A request user: what horizon.tabs and pure_manila look at."""
    return types.SimpleNamespace(is_superuser=admin,
                                 has_perms=lambda perms: True)


def _fb_fs(name, array_name='fb-lab'):
    """A get_file_system_info() dict as pure_flash_blade builds it."""
    return dict(PERF, **{
        'name': name, 'share_instance_id': pure_manila.id_from_name(name),
        'provisioned': 200.0, 'used': 100.0, 'total_physical': 40.0,
        'unique': 37.0, 'snapshots': 3.0, 'data_reduction': '2.50 to 1',
        'nfs_rules': '10.0.0.0/24(rw,no_root_squash)', 'nfs_v3': False,
        'nfs_v41': True, 'smb_enabled': False, 'hard_limit': True,
        'created': CREATED, 'destroyed': False, 'snapshot_count': 2,
        'id': 'fb-uuid', 'array_name': array_name, 'version': '4.5.3',
        'model': 'FlashBlade//S200', 'target': FB_TARGET,
        'backend_name': 'flashblade',
    })


def _fa_dir(quota=True):
    """A get_directory_info() dict as pure_fa_files builds it."""
    info = dict(PERF, **{
        'name': FA_DIR, 'directory_name': 'share-%s-manila' % SHARE_ID,
        'path': '/share-%s-manila' % SHARE_ID, 'share_id': SHARE_ID,
        'used': 10.0, 'unique': 9.0, 'snapshots': 1.0, 'virtual': 100.0,
        'total_physical': 10.0, 'data_reduction': '3.00 to 1',
        'created': CREATED, 'destroyed': False,
        'quota_limit': 50.0, 'quota_usage': 6.0, 'percentage_used': 12,
        'quota_enforced': True,
        'nfs_rules': [
            {'client': '10.0.0.5', 'permission': 'rw',
             'access': 'no-root-squash', 'nfs_version': ['nfsv3', 'nfsv4']},
            {'client': '10.0.0.0/24', 'permission': 'ro',
             'access': 'root-squash', 'nfs_version': []},
        ],
        'exports': [{'export_name': 'tenant-mount', 'enabled': True,
                     'policy': 'share-%s-manila-nfs' % SHARE_ID},
                    {'export_name': 'old-export', 'enabled': False,
                     'policy': ''}],
        'snapshot_count': 2,
        'snapshot_list': [{'suffix': 'snap-newest', 'created': CREATED},
                          {'suffix': 'snap-oldest', 'created': None}],
        'array_name': 'fa-lab', 'version': '6.10.6', 'model': 'FA-X50R2',
        'target': FA_TARGET, 'parent_fs': 'openstack',
        'backend_name': 'flasharray-files',
    })
    if not quota:
        info.update({'quota_limit': None, 'quota_usage': 0.0,
                     'percentage_used': None, 'quota_enforced': False})
    return info


def _info(**overrides):
    """A get_share_info() dict; defaults to 'configured, nothing found'."""
    info = {
        'configured': True, 'kind': None, 'backend_name': None,
        'entry': None, 'found': False, 'error': None, 'is_admin': True,
        'file_systems': [], 'directory': None, 'share_id': SHARE_ID,
        'export_paths': [], 'candidate_names': [],
    }
    info.update(overrides)
    return info


def info_unconfigured(is_admin=True):
    return _info(configured=False, is_admin=is_admin)


def info_not_found(is_admin=True, error='flashblade: no file system named '
                   + FS1, candidate_names=(FS1, FS2)):
    return _info(is_admin=is_admin, error=error,
                 candidate_names=list(candidate_names))


def info_fb(is_admin=True, file_systems=None):
    if file_systems is None:
        file_systems = [_fb_fs(FS1), _fb_fs(FS2, array_name='fb-two')]
    return _info(kind='fb', backend_name='flashblade', found=True,
                 is_admin=is_admin, file_systems=file_systems,
                 candidate_names=[fs['name'] for fs in file_systems])


def info_fa(is_admin=True, quota=True):
    return _info(kind='fa', backend_name='flasharray-files', found=True,
                 is_admin=is_admin, directory=_fa_dir(quota=quota))


def _everpure_slugs(group):
    return [tab.slug for tab in group.tabs if tab.slug == SLUG]


@unittest.skipIf(manila_hook is None, 'manila-ui is not installed')
class InstallTests(test.TestCase):

    def test_tab_is_last_in_both_groups(self):
        for group in (admin_tabs.ShareDetailTabs,
                      project_tabs.ShareDetailTabs):
            with self.subTest(group=group.__module__):
                self.assertIs(manila_hook.EverpureShareTab, group.tabs[-1])
                self.assertEqual([SLUG], _everpure_slugs(group))
        # manila-ui's own tabs are untouched and still come first.
        self.assertEqual(
            (admin_tabs.ShareOverviewTab, manila_hook.EverpureShareTab),
            admin_tabs.ShareDetailTabs.tabs)
        self.assertEqual(
            (project_tabs.OverviewTab, project_tabs.ExportLocationsTab,
             manila_hook.EverpureShareTab),
            project_tabs.ShareDetailTabs.tabs)
        self.assertEqual(manila_hook.TAB_GROUPS,
                         (admin_tabs.ShareDetailTabs,
                          project_tabs.ShareDetailTabs))

    def test_second_import_and_install_do_not_duplicate(self):
        before = (admin_tabs.ShareDetailTabs.tabs,
                  project_tabs.ShareDetailTabs.tabs)
        self.assertIs(manila_hook,
                      importlib.import_module('horizon_pure.manila_hook'))
        manila_hook.install()
        manila_hook.install()
        self.assertEqual(before, (admin_tabs.ShareDetailTabs.tabs,
                                  project_tabs.ShareDetailTabs.tabs))

    def test_reload_replaces_stale_tab_class(self):
        # A reload defines a new EverpureShareTab class; install() must
        # swap it in by slug instead of appending a second Everpure tab.
        stale = manila_hook.EverpureShareTab
        module = importlib.reload(manila_hook)
        fresh = module.EverpureShareTab
        self.assertIsNot(stale, fresh)
        for group in manila_hook.TAB_GROUPS:
            self.assertEqual([SLUG], _everpure_slugs(group))
            self.assertIs(fresh, group.tabs[-1])
            self.assertNotIn(stale, group.tabs)

    def test_tab_attributes(self):
        tab = manila_hook.EverpureShareTab
        self.assertEqual('Everpure', str(tab.name))
        self.assertEqual(SLUG, tab.slug)
        self.assertEqual('pure_panel/shares/_everpure_tab.html',
                         tab.template_name)
        self.assertFalse(tab.preload)

    def test_overrides_imports_the_hook(self):
        from horizon_pure import overrides
        self.assertIs(manila_hook, overrides.manila_hook)


@unittest.skipIf(manila_hook is None, 'manila-ui is not installed')
class TabTests(test.TestCase):
    """The tab rendered through a tab group built like manila-ui's views."""

    def setUp(self):
        super().setUp()
        registry.reset()
        self.addCleanup(registry.reset)
        self.share = _share()

    def _request(self, select_tab=True):
        request = self.factory.get('/admin/shares/%s/' % SHARE_ID,
                                   TAB_PARAM if select_tab else {})
        request.user = self.request.user
        return request

    def _group(self, group_class=None, select_tab=True, share=None):
        request = self._request(select_tab)
        group_class = group_class or admin_tabs.ShareDetailTabs
        return group_class(request, share=share or self.share)

    def _render(self, info, group_class=None):
        with mock.patch.object(pure_manila, 'get_share_info',
                               return_value=info) as get_info:
            group = self._group(group_class)
            tab = group.get_tab(SLUG)
            self.assertIsNotNone(tab)
            self.assertTrue(tab.is_active())
            html = tab.render()
        get_info.assert_called_once_with(group.request, self.share)
        return html

    def test_allowed_needs_a_manila_backend(self):
        # The test settings only configure a Cinder FlashArray.
        self.assertEqual([], registry.entries(service='manila'))
        group = self._group()
        self.assertIsNone(group.get_tab(SLUG))
        tab = group._tabs[SLUG]
        self.assertFalse(tab._allowed)
        self.assertFalse(tab.allowed(group.request))
        self.assertEqual([admin_tabs.ShareOverviewTab],
                         [type(t) for t in group.get_tabs()])
        with override_settings(PURE_FLASHBLADES=[FB_CONF]):
            self.assertTrue(tab.allowed(group.request))
        with override_settings(PURE_FLASHARRAY_FILES=[FA_CONF]):
            self.assertTrue(tab.allowed(group.request))

    @override_settings(PURE_FLASHBLADES=42)
    def test_allowed_survives_broken_settings(self):
        # The tab group evaluates allowed() once while it is built.
        with self.assertLogs('horizon_pure.manila_hook',
                             level='ERROR') as logs:
            group = self._group()
            tab = group._tabs[SLUG]
            self.assertFalse(tab.allowed(group.request))
        self.assertEqual(2, len(logs.output))
        self.assertIn("'int' object is not iterable", logs.output[0])
        self.assertIsNone(group.get_tab(SLUG))

    @override_settings(PURE_FLASHBLADES=[FB_CONF])
    def test_tab_is_offered_but_not_preloaded(self):
        with mock.patch.object(pure_manila, 'get_share_info') as get_info:
            group = self._group(select_tab=False)
            tab = group.get_tab(SLUG)
            self.assertIsNotNone(tab)
            self.assertIs(group.get_tabs()[-1], tab)
            self.assertFalse(tab.is_active())
            self.assertFalse(tab.load)
            self.assertEqual('', tab.render())
            group.load_tab_data()
        get_info.assert_not_called()

    @override_settings(PURE_FLASHBLADES=[FB_CONF])
    def test_context_data(self):
        info = info_fb()
        group = self._group(project_tabs.ShareDetailTabs)
        tab = group.get_tab(SLUG)
        with mock.patch.object(pure_manila, 'get_share_info',
                               return_value=info) as get_info:
            context = tab.get_context_data(group.request)
        get_info.assert_called_once_with(group.request, self.share)
        self.assertEqual({'share': self.share, 'info': info}, context)

    @override_settings(PURE_FLASHBLADES=[FB_CONF])
    def test_context_data_wraps_exceptions(self):
        group = self._group()
        group.request.user = _user(True)
        tab = group.get_tab(SLUG)
        with mock.patch.object(pure_manila, 'get_share_info',
                               side_effect=RuntimeError('boom')) as get_info, \
                self.assertLogs('horizon_pure.manila_hook',
                                level='ERROR') as logs:
            html = tab.render()
        get_info.assert_called_once_with(group.request, self.share)
        self.assertEqual({'share': self.share,
                          'info': {'configured': True, 'found': False,
                                   'error': 'boom', 'is_admin': True}},
                         tab.data)
        self.assertEqual(1, len(logs.output))
        self.assertIn(SHARE_ID, logs.output[0])
        self.assertIn('RuntimeError: boom', logs.output[0])
        self.assertIn('No matching object was found', html)
        self.assertIn('boom', html)
        self.assertNotIn('names tried', html)

        # A project user gets the generic notice without the exception.
        group = self._group(project_tabs.ShareDetailTabs)
        self.assertFalse(group.request.user.is_superuser)
        tab = group.get_tab(SLUG)
        with mock.patch.object(pure_manila, 'get_share_info',
                               side_effect=RuntimeError('boom')), \
                self.assertLogs('horizon_pure.manila_hook', level='ERROR'):
            html = tab.render()
        self.assertFalse(tab.data['info']['is_admin'])
        self.assertIn('No matching object was found', html)
        self.assertNotIn('boom', html)

    @override_settings(PURE_FLASHBLADES=[FB_CONF])
    def test_render_unconfigured(self):
        html = self._render(info_unconfigured())
        self.assertIn('alert-info', html)
        self.assertIn('No Everpure Manila backends are configured.', html)
        self.assertNotIn('alert-warning', html)
        self.assertNotIn('Share on Array', html)

    @override_settings(PURE_FLASHBLADES=[FB_CONF])
    def test_render_not_found_admin(self):
        html = self._render(info_not_found())
        self.assertIn('alert-warning', html)
        self.assertIn('No matching object was found for this share', html)
        self.assertIn('flashblade: no file system named ' + FS1, html)
        self.assertIn('File system names tried:', html)
        self.assertIn('%s, %s' % (FS1, FS2), html)
        self.assertNotIn('Share on Array', html)

    @override_settings(PURE_FLASHBLADES=[FB_CONF])
    def test_render_not_found_project_user_hides_error_and_candidates(self):
        # The error text names backends, arrays and objects: admin-only,
        # like the Array section.
        error = ('Unable to connect to flashblade (%s): connection refused; '
                 'flashblade: no file system named %s' % (FB_TARGET, FS1))
        html = self._render(info_not_found(is_admin=False, error=error),
                            project_tabs.ShareDetailTabs)
        self.assertIn('alert-warning', html)
        self.assertIn('No matching object was found', html)
        self.assertNotIn('no file system named', html)
        self.assertNotIn('connection refused', html)
        self.assertNotIn('flashblade', html)
        self.assertNotIn(FB_TARGET, html)
        self.assertNotIn(FS1, html)
        self.assertNotIn('names tried', html)
        self.assertNotIn(FS2, html)

        html = self._render(info_not_found(error=None, candidate_names=()))
        self.assertIn('alert-warning', html)
        self.assertNotIn('names tried', html)

    @override_settings(PURE_FLASHBLADES=[FB_CONF])
    def test_render_flashblade_admin(self):
        html = self._render(info_fb())
        self.assertEqual(2, html.count('Share on Array'))
        self.assertEqual(2, html.count('<h4>Performance</h4>'))
        self.assertEqual(2, html.count('<h4>Array</h4>'))
        # Array identity, linked to the Purity web UI.
        self.assertIn('href="https://%s/"' % FB_TARGET, html)
        self.assertIn('>fb-lab</a>', html)
        self.assertIn('>fb-two</a>', html)
        self.assertIn('<dd>4.5.3</dd>', html)
        self.assertIn('<dd>FlashBlade//S200</dd>', html)
        self.assertIn('<dd>flashblade</dd>', html)
        # Share on array.
        self.assertIn('<dd>%s</dd>' % FS1, html)
        self.assertIn('<dd>%s</dd>' % FS2, html)
        self.assertIn('Provisioned', html)
        self.assertIn('<dd>200MB</dd>', html)
        self.assertIn('Used (logical)', html)
        self.assertIn('<dd>100MB</dd>', html)
        self.assertIn('Used (physical)', html)
        self.assertIn('<dd>40MB</dd>', html)
        self.assertIn('<dd>37MB</dd>', html)
        self.assertIn('Snapshot Space', html)
        self.assertIn('<dd>3MB</dd>', html)
        self.assertIn('<dd>2.50 to 1</dd>', html)
        self.assertIn('Hard Limit', html)
        self.assertIn('NFS v3', html)
        self.assertIn('NFS v4.1', html)
        self.assertIn('<dd>No</dd>', html)
        self.assertIn('<dd>Yes</dd>', html)
        self.assertIn('10.0.0.0/24(rw,no_root_squash)', html)
        self.assertIn('<dd>2</dd>', html)
        self.assertIn('Nov. 14, 2023', html)
        # Performance.
        self.assertIn('Read IOPS', html)
        self.assertIn('<dd>100.00</dd>', html)
        self.assertIn('Write IOPS', html)
        self.assertIn('<dd>50.00</dd>', html)
        self.assertIn('<dd>2MB/s</dd>', html)
        self.assertIn('<dd>512KB/s</dd>', html)
        self.assertIn('<dd>300.00</dd>', html)
        self.assertIn('<dd>400.00</dd>', html)
        self.assertNotIn('alert-', html)
        self.assertNotIn('Managed Directory', html)

    @override_settings(PURE_FLASHBLADES=[FB_CONF])
    def test_render_flashblade_project_user_hides_array(self):
        html = self._render(info_fb(is_admin=False),
                            project_tabs.ShareDetailTabs)
        self.assertEqual(2, html.count('Share on Array'))
        self.assertNotIn('<h4>Array</h4>', html)
        self.assertNotIn(FB_TARGET, html)
        self.assertNotIn('fb-lab', html)
        self.assertNotIn('fb-two', html)
        self.assertNotIn('4.5.3', html)
        self.assertNotIn('FlashBlade//S200', html)
        self.assertNotIn('Backend Name', html)
        self.assertIn('<dd>%s</dd>' % FS1, html)
        self.assertIn('<dd>200MB</dd>', html)
        self.assertIn('Read IOPS', html)

    @override_settings(PURE_FLASHBLADES=[FB_CONF])
    def test_render_flashblade_missing_optional_values(self):
        fs = _fb_fs(FS1)
        fs.update({'created': None, 'nfs_rules': '', 'snapshot_count': 0})
        html = self._render(info_fb(file_systems=[fs]))
        self.assertEqual(1, html.count('Share on Array'))
        self.assertIn('<dd>-</dd>', html)
        self.assertIn('<dd>0</dd>', html)
        self.assertNotIn('Nov. 14, 2023', html)

    @override_settings(PURE_FLASHARRAY_FILES=[FA_CONF])
    def test_render_flasharray_admin(self):
        html = self._render(info_fa())
        self.assertEqual(1, html.count('Share on Array'))
        self.assertEqual(1, html.count('<h4>Performance</h4>'))
        self.assertEqual(1, html.count('<h4>Array</h4>'))
        self.assertIn('href="https://%s/"' % FA_TARGET, html)
        self.assertIn('>fa-lab</a>', html)
        self.assertIn('<dd>6.10.6</dd>', html)
        self.assertIn('<dd>FA-X50R2</dd>', html)
        self.assertIn('<dd>flasharray-files</dd>', html)
        self.assertIn('Parent File System', html)
        self.assertIn('<dd>openstack</dd>', html)
        self.assertIn('Managed Directory', html)
        self.assertIn('<dd>%s</dd>' % FA_DIR, html)
        self.assertIn('Quota Limit', html)
        self.assertIn('<dd>50MB</dd>', html)
        self.assertIn('Quota Usage', html)
        self.assertIn('<dd>6MB</dd>', html)
        self.assertIn('Quota Used (%)', html)
        self.assertIn('<dd>12.0</dd>', html)
        self.assertIn('Quota Enforced', html)
        self.assertIn('<dd>Yes</dd>', html)
        self.assertIn('Used (physical)', html)
        self.assertIn('<dd>10MB</dd>', html)
        self.assertIn('Used (logical)', html)
        self.assertIn('<dd>100MB</dd>', html)
        self.assertIn('<dd>9MB</dd>', html)
        self.assertIn('<dd>1MB</dd>', html)
        self.assertIn('<dd>3.00 to 1</dd>', html)
        self.assertIn('NFS Client Rules', html)
        self.assertIn('10.0.0.5 (rw, no-root-squash): nfsv3, nfsv4', html)
        self.assertIn('10.0.0.0/24 (ro, root-squash)</div>', html)
        self.assertIn('Exports', html)
        self.assertIn('tenant-mount (enabled)', html)
        self.assertIn('old-export (disabled)', html)
        self.assertIn('<dd>2</dd>', html)
        self.assertIn('Snapshot Suffixes', html)
        self.assertLess(html.index('snap-newest'), html.index('snap-oldest'))
        self.assertIn('snap-newest (Nov. 14, 2023', html)
        self.assertIn('snap-oldest</div>', html)
        self.assertIn('<dd>100.00</dd>', html)
        self.assertIn('<dd>2MB/s</dd>', html)
        self.assertIn('<dd>512KB/s</dd>', html)
        self.assertNotIn('No quota', html)
        self.assertNotIn('<dt>File System</dt>', html)
        self.assertNotIn('alert-', html)

    @override_settings(PURE_FLASHARRAY_FILES=[FA_CONF])
    def test_render_flasharray_project_user_hides_array(self):
        html = self._render(info_fa(is_admin=False),
                            project_tabs.ShareDetailTabs)
        self.assertNotIn('<h4>Array</h4>', html)
        self.assertNotIn(FA_TARGET, html)
        self.assertNotIn('fa-lab', html)
        self.assertNotIn('6.10.6', html)
        self.assertNotIn('FA-X50R2', html)
        self.assertNotIn('Parent File System', html)
        self.assertNotIn('flasharray-files', html)
        # The directory is shown without its parent file system.
        self.assertNotIn(FA_DIR, html)
        self.assertIn('<dd>share-%s-manila</dd>' % SHARE_ID, html)
        self.assertIn('<dd>50MB</dd>', html)

    @override_settings(PURE_FLASHARRAY_FILES=[FA_CONF])
    def test_render_flasharray_without_quota_rules_or_snapshots(self):
        info = info_fa(quota=False)
        info['directory'].update({'nfs_rules': [], 'exports': [],
                                  'snapshot_count': 0, 'snapshot_list': []})
        html = self._render(info)
        self.assertIn('No quota', html)
        self.assertIn('<dd>-</dd>', html)
        self.assertIn('<dd>No</dd>', html)
        self.assertEqual(2, html.count('<em>None</em>'))
        self.assertIn('<dd>0</dd>', html)
        self.assertNotIn('Snapshot Suffixes', html)


@unittest.skipIf(manila_hook is None, 'manila-ui is not installed')
@override_settings(PURE_FLASHBLADES=[FB_CONF],
                   PURE_FLASHARRAY_FILES=[FA_CONF])
class TabWithRealApiTests(test.TestCase):
    """The tab fed by the real API modules over mocked SDK clients.

    Guards the template against key renames in pure_flash_blade /
    pure_fa_files: every value asserted here comes from the fixture
    clients of those modules' own tests.
    """

    def setUp(self):
        super().setUp()
        registry.reset()
        self.addCleanup(registry.reset)
        self.fb = fb_fixtures.make_client()
        self.fa = fa_fixtures.make_client()
        patcher = mock.patch.object(
            registry, '_build_client',
            side_effect=lambda entry: self.fb if entry.kind == 'fb'
            else self.fa)
        self.build = patcher.start()
        self.addCleanup(patcher.stop)
        self.manila = mock.Mock(name='manila_ui.api.manila')
        self.manila.share_export_location_list.return_value = []
        self.manila.share_instance_list.return_value = []
        patcher = mock.patch.object(pure_manila, '_manila_api',
                                    return_value=self.manila)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _render(self, share, group_class=admin_tabs.ShareDetailTabs,
                admin=True):
        request = self.factory.get('/shares/%s/' % share.id, TAB_PARAM)
        request.user = _user(admin)
        group = group_class(request, share=share)
        tab = group.get_tab(SLUG)
        self.assertIsNotNone(tab)
        html = tab.render()
        self.assertIs(share, tab.data['share'])
        return html, tab.data['info'], request

    def test_flashblade_share(self):
        share = _share(share_id=fb_fixtures.IID3,
                       host='ctl@flashblade#flashblade')
        self.manila.share_export_location_list.return_value = [
            types.SimpleNamespace(path='10.0.0.1:/' + fb_fixtures.FS1)]

        html, info, request = self._render(share)

        self.manila.share_export_location_list.assert_called_once_with(
            request, fb_fixtures.IID3)
        self.manila.share_instance_list.assert_not_called()
        self.assertEqual(['fb'],
                         [c[0][0].kind for c in self.build.call_args_list])
        self.fb.get_file_systems.assert_called_once_with(
            names=[fb_fixtures.FS1])
        self.fb.get_file_systems_performance.assert_called_once_with(
            names=[fb_fixtures.FS1])
        self.fa.get_directories.assert_not_called()
        self.assertTrue(info['found'])
        self.assertTrue(info['is_admin'])
        self.assertEqual('fb', info['kind'])
        self.assertIn('<dd>%s</dd>' % fb_fixtures.FS1, html)
        self.assertIn('href="https://%s/"' % FB_TARGET, html)
        self.assertIn('>fb-lab</a>', html)
        self.assertIn('<dd>4.5.3</dd>', html)
        self.assertIn('<dd>FlashBlade//S200</dd>', html)
        self.assertIn('<dd>flashblade</dd>', html)
        self.assertIn('<dd>200MB</dd>', html)     # provisioned
        self.assertIn('<dd>100MB</dd>', html)     # used (virtual)
        self.assertIn('<dd>40MB</dd>', html)      # total_physical
        self.assertIn('<dd>37MB</dd>', html)      # unique
        self.assertIn('<dd>3MB</dd>', html)       # snapshots
        self.assertIn('<dd>2.50 to 1</dd>', html)
        self.assertIn('10.0.0.0/24(rw,no_root_squash)', html)
        self.assertIn('<dd>2</dd>', html)         # snapshot_count
        self.assertIn('Nov. 14, 2023', html)
        self.assertIn('<dd>100.00</dd>', html)    # read IOPS
        self.assertIn('<dd>2MB/s</dd>', html)     # read bandwidth
        self.assertIn('<dd>512KB/s</dd>', html)   # write bandwidth
        self.assertNotIn('alert-', html)

    def test_flasharray_share_for_project_user(self):
        share = _share(share_id=fa_fixtures.SHARE_ID)
        self.manila.share_export_location_list.return_value = [
            types.SimpleNamespace(path='10.0.0.5:/tenant-mount')]

        html, info, request = self._render(share,
                                           project_tabs.ShareDetailTabs,
                                           admin=False)

        # Settings order: FlashBlade is tried (and misses) first.
        self.assertEqual(['fb', 'fa'],
                         [c[0][0].kind for c in self.build.call_args_list])
        self.fb.get_file_systems.assert_called_once_with(
            names=['tenant-mount'])
        self.fa.get_directories.assert_called_once_with(
            names=[fa_fixtures.DIR])
        self.fa.get_directory_quotas.assert_called_once_with(
            directory_names=[fa_fixtures.DIR],
            policy_names=[fa_fixtures.SHORT + '-quota'])
        self.fa.get_policies_nfs_client_rules.assert_called_once_with(
            policy_names=[fa_fixtures.SHORT + '-nfs'])
        self.fa.get_directory_exports.assert_called_once_with(
            directory_names=[fa_fixtures.DIR])
        self.fa.get_directory_snapshots.assert_called_once_with(
            source_names=[fa_fixtures.DIR])
        self.fa.get_directories_performance.assert_called_once_with(
            names=[fa_fixtures.DIR])
        self.assertTrue(info['found'])
        self.assertEqual('fa', info['kind'])
        self.assertFalse(info['is_admin'])
        self.assertIn('<dd>%s</dd>' % fa_fixtures.SHORT, html)
        self.assertNotIn(fa_fixtures.DIR, html)   # parent fs is admin-only
        self.assertIn('<dd>50MB</dd>', html)      # quota_limit
        self.assertIn('<dd>6MB</dd>', html)       # quota_usage
        self.assertIn('<dd>12.0</dd>', html)      # percentage_used
        self.assertIn('<dd>10MB</dd>', html)      # used (physical)
        self.assertIn('<dd>100MB</dd>', html)     # virtual (logical)
        self.assertIn('<dd>3.00 to 1</dd>', html)
        self.assertIn('10.0.0.5 (rw, no-root-squash): nfsv3, nfsv4', html)
        self.assertIn('10.0.0.0/24 (ro, root-squash)</div>', html)
        self.assertIn('%s (enabled)' % fa_fixtures.SHORT, html)
        self.assertIn('<dd>2</dd>', html)         # snapshot_count
        self.assertLess(html.index(fa_fixtures.SNAP2),
                        html.index(fa_fixtures.SNAP1))
        self.assertNotIn(fa_fixtures.SNAP3, html)
        self.assertNotIn('private', html)
        # Project users do not see the array identity.
        self.assertNotIn('<h4>Array</h4>', html)
        self.assertNotIn('fa-lab', html)
        self.assertNotIn(FA_TARGET, html)
        self.assertNotIn('FA-X50R2', html)
        self.assertNotIn('alert-', html)

    def test_unreachable_arrays_render_the_reason(self):
        self.build.side_effect = RuntimeError('connection refused')
        share = _share(host='ctl@flashblade#flashblade')
        html, info, request = self._render(share)
        self.assertFalse(info['found'])
        self.assertIn('alert-warning', html)
        self.assertIn('connection refused', html)
        self.assertIn(FB_TARGET, html)

    def test_unreachable_arrays_hidden_from_project_user(self):
        # Both arrays down; the tenant sees the notice, not the targets.
        self.build.side_effect = RuntimeError('connection refused')
        html, info, request = self._render(_share(),
                                           project_tabs.ShareDetailTabs,
                                           admin=False)
        self.assertFalse(info['found'])
        self.assertFalse(info['is_admin'])
        # The data is still collected (logs, admins), only not rendered.
        self.assertIn(FB_TARGET, info['error'])
        self.assertIn(FA_TARGET, info['error'])
        self.assertIn('connection refused', info['error'])
        self.assertIn('alert-warning', html)
        self.assertIn('No matching object was found', html)
        for secret in (FB_TARGET, FA_TARGET, 'connection refused',
                       'flashblade', 'flasharray-files', 'Unable to'):
            self.assertNotIn(secret, html)

    def test_foreign_backend_share_hidden_from_project_user(self):
        # Steady state in a mixed cloud: the share lives on another
        # vendor's backend and both Everpure arrays answer "no such
        # object". The miss must not tell the tenant what was asked.
        self.manila.share_export_location_list.return_value = [
            types.SimpleNamespace(path='10.0.0.9:/netapp-export')]
        html, info, request = self._render(_share(share_id=IID2),
                                           project_tabs.ShareDetailTabs,
                                           admin=False)
        self.fb.get_file_systems.assert_called_once_with(
            names=['netapp-export'])
        self.fa.get_directories.assert_called_once_with(
            names=['openstack:share-%s-manila' % IID2])
        self.assertFalse(info['found'])
        self.assertIn('flashblade: no file system named netapp-export',
                      info['error'])
        self.assertIn('flasharray-files: no managed directory openstack:',
                      info['error'])
        self.assertIn('alert-warning', html)
        self.assertIn('No matching object was found', html)
        for secret in ('no file system named', 'no managed directory',
                       'netapp-export', 'flashblade', 'flasharray-files',
                       'openstack', IID2):
            self.assertNotIn(secret, html)

        # The same miss shows its detail to an administrator.
        html, info, request = self._render(_share(share_id=IID2))
        self.assertIn('flashblade: no file system named netapp-export',
                      html)
        self.assertIn('File system names tried:', html)
        self.assertIn('netapp-export', html)


@unittest.skipIf(manila_hook is None, 'manila-ui is not installed')
class AdminShareDetailViewTests(manila_test.BaseAdminViewTests):
    """GET the manila-ui admin share detail page with the hook installed."""

    def setUp(self):
        super().setUp()
        registry.reset()
        self.addCleanup(registry.reset)
        self.share = manila_data.share
        self.url = reverse('horizon:admin:shares:detail',
                           args=[self.share.id])
        for name in ('share_get', 'share_rules_list'):
            patcher = mock.patch.object(manila_api, name)
            patcher.start()
            self.addCleanup(patcher.stop)
        manila_api.share_get.return_value = self.share
        manila_api.share_rules_list.return_value = []

    def _get(self, info, **extra):
        with mock.patch.object(pure_manila, 'get_share_info',
                               return_value=info) as get_info:
            res = self.client.get(self.url, TAB_PARAM, **extra)
        return res, get_info

    @override_settings(PURE_FLASHBLADES=[FB_CONF])
    def test_detail_page_has_the_everpure_tab(self):
        info = info_fb(file_systems=[_fb_fs(FS1)])
        res, get_info = self._get(info)

        self.assertEqual(200, res.status_code)
        self.assertTemplateUsed(res, 'admin/shares/detail.html')
        self.assertTemplateUsed(res, 'pure_panel/shares/_everpure_tab.html')
        manila_api.share_get.assert_called_once_with(mock.ANY, self.share.id)
        manila_api.share_rules_list.assert_called_once_with(
            mock.ANY, self.share.id)
        get_info.assert_called_once_with(mock.ANY, self.share)
        self.assertContains(res, 'Everpure')
        self.assertContains(res, 'share_details__' + SLUG)
        self.assertContains(res, 'Share on Array')
        self.assertContains(res, '<dd>%s</dd>' % FS1)
        self.assertContains(res, '>fb-lab</a>')
        self.assertContains(res, 'Share Overview')

    @override_settings(PURE_FLASHBLADES=[FB_CONF])
    def test_ajax_tab_load_returns_only_the_tab(self):
        res, get_info = self._get(info_fa(),
                                  HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(200, res.status_code)
        get_info.assert_called_once_with(mock.ANY, self.share)
        self.assertContains(res, '<dd>%s</dd>' % FA_DIR)
        self.assertContains(res, 'Managed Directory')
        self.assertNotContains(res, '<html')
        self.assertNotContains(res, 'Share Overview')

    def test_tab_absent_without_manila_backends(self):
        with mock.patch.object(pure_manila, 'get_share_info') as get_info:
            res = self.client.get(self.url)
        self.assertEqual(200, res.status_code)
        self.assertTemplateUsed(res, 'admin/shares/detail.html')
        self.assertTemplateNotUsed(res,
                                   'pure_panel/shares/_everpure_tab.html')
        self.assertNotContains(res, 'share_details__' + SLUG)
        get_info.assert_not_called()


@unittest.skipIf(manila_hook is None, 'manila-ui is not installed')
class ProjectShareDetailViewTests(manila_test.TestCase):
    """GET the manila-ui project share detail page as a plain user."""

    def setUp(self):
        super().setUp()
        registry.reset()
        self.addCleanup(registry.reset)
        self.share = manila_data.share
        self.url = reverse('horizon:project:shares:detail',
                           args=[self.share.id])
        for name in ('share_get', 'share_rules_list',
                     'share_export_location_list'):
            patcher = mock.patch.object(manila_api, name)
            patcher.start()
            self.addCleanup(patcher.stop)
        manila_api.share_get.return_value = self.share
        manila_api.share_rules_list.return_value = []
        manila_api.share_export_location_list.return_value = []

    @override_settings(PURE_FLASHARRAY_FILES=[FA_CONF])
    def test_detail_page_hides_array_identity(self):
        with mock.patch.object(pure_manila, 'get_share_info',
                               return_value=info_fa(is_admin=False)) as g:
            res = self.client.get(self.url, TAB_PARAM)
        self.assertEqual(200, res.status_code)
        self.assertTemplateUsed(res, 'project/shares/detail.html')
        self.assertTemplateUsed(res, 'pure_panel/shares/_everpure_tab.html')
        g.assert_called_once_with(mock.ANY, self.share)
        self.assertContains(res, 'Everpure')
        self.assertContains(res, 'Export Locations')
        self.assertContains(res, '<dd>share-%s-manila</dd>' % SHARE_ID)
        self.assertNotContains(res, FA_DIR)
        self.assertNotContains(res, 'fa-lab')
        self.assertNotContains(res, FA_TARGET)
