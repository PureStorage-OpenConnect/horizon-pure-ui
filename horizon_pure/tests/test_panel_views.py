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

"""Tests for the Everpure admin panel: index, detail views, tabs, tables.

The three API classes are patched where the views and tabs look them up,
the registry never builds a client, and the array settings are overridden
so the registry parses real entries.
"""

import datetime
from unittest import mock

from django.test import override_settings
from django.urls import NoReverseMatch
from django.urls import reverse

from openstack_dashboard.api import base
from openstack_dashboard.test import helpers as test

from horizon_pure.api import pure_fa_files
from horizon_pure.api import pure_flash_array
from horizon_pure.api import pure_flash_blade
from horizon_pure.api import registry
from horizon_pure.pure_panel.fafiles import tables as fafiles_tables
from horizon_pure.pure_panel.flashblades import tables as fb_tables
from horizon_pure.pure_panel import tables as pure_tables
from horizon_pure.pure_panel import tabs as pure_tabs


ARRAYS = [
    {'san_ip': '192.0.2.10', 'api_token': 'tok', 'backend_name': 'pure-iscsi'},
]
BLADES = [
    {'mgmt_ip': '192.0.2.20', 'api_token': 'tok',
     'backend_name': 'flashblade'},
]
FILES = [
    {'san_ip': '192.0.2.10', 'api_token': 'tok',
     'backend_name': 'flasharray-files', 'parent_fs': 'tenant-fs'},
]

INDEX_URL = '/admin/pure_panel/'
FB_TAB_URL = INDEX_URL + '?tab=pure_panel_tabs__flashblade_tab'
FAFILES_TAB_URL = INDEX_URL + '?tab=pure_panel_tabs__fafiles_tab'
FA_DETAIL_URL = '/admin/pure_panel/flasharrays/pure-iscsi/'
FB_DETAIL_URL = '/admin/pure_panel/flashblades/flashblade/'
FAFILES_DETAIL_URL = '/admin/pure_panel/fafiles/flasharray-files/'

IID = '11111111-2222-3333-4444-555555555555'
SHARE_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
FS_NAME = 'share-%s-manila' % IID
DIR_SHORT = 'share-%s-manila' % SHARE_ID
DIR_NAME = 'tenant-fs:' + DIR_SHORT
CREATED = datetime.datetime(2023, 11, 14, 22, 13, 20,
                            tzinfo=datetime.timezone.utc)

FA_STATS = {
    'total_used': 10.0, 'total_available': 1000.0,
    'total_volume_count': 7, 'available_volume_count': 10000,
    'total_snapshot_count': 11, 'available_snapshot_count': 50000,
    'total_host_count': 5, 'available_host_count': 500,
    'total_pgroup_count': 2, 'available_pgroup_count': 250,
}
FB_STATS = {
    'total_used': 40.0, 'total_available': 2000.0,
    'total_file_system_count': 3, 'total_snapshot_count': 11,
}
FAFILES_STATS = {
    'total_used': 10.0, 'total_available': 1000.0,
    'total_directory_count': 3,
}
PERF = {
    'reads_per_sec': 100, 'writes_per_sec': 50,
    'output_per_sec': 2.0, 'input_per_sec': 0.5,
    'usec_per_read_op': 300, 'usec_per_write_op': 400,
}


def fa_info(**overrides):
    info = {
        'id': 'array-uuid', 'status': 'Connected', 'array_name': 'fa-lab',
        'version': '6.8.5', 'model': 'FA-X50R2', 'capacity': 1000.0,
        'total': 10.0, 'snapshots': 1.0, 'unique': 9.0, 'volumes': 9.0,
        'data_reduction': '3.00 to 1', 'thin_provisioning': '4.00 to 1',
        'total_reduction': '12.00 to 1', 'cinder_id': 'pure-iscsi',
        'cinder_name': 'pure-iscsi', 'target': '192.0.2.10',
    }
    info.update(FA_STATS)
    info.update(PERF)
    info.update(overrides)
    return base.APIDictWrapper(info)


def fb_info(**overrides):
    info = {
        'id': 'fb-uuid', 'status': 'Connected', 'array_name': 'fb-lab',
        'version': '4.5.3', 'model': 'FlashBlade//S200',
        'capacity': 2000.0, 'total': 40.0, 'unique': 37.0,
        'snapshots': 3.0, 'virtual': 100.0, 'total_provisioned': 500.0,
        'data_reduction': '2.50 to 1', 'file_system_count': 3,
        'snapshot_count': 11, 'backend_id': 'flashblade',
        'backend_name': 'flashblade', 'target': '192.0.2.20',
    }
    info.update(PERF)
    info.update(overrides)
    return base.APIDictWrapper(info)


def fafiles_info(**overrides):
    info = {
        'id': 'array-uuid', 'status': 'Connected', 'array_name': 'fa-lab',
        'version': '6.10.6', 'model': 'FA-X50R2', 'capacity': 1000.0,
        'total': 10.0, 'snapshots': 1.0, 'unique': 9.0, 'volumes': 9.0,
        'data_reduction': '3.00 to 1', 'thin_provisioning': '4.00 to 1',
        'total_reduction': '12.00 to 1', 'directory_count': 3,
        'parent_fs': 'tenant-fs', 'backend_id': 'flasharray-files',
        'backend_name': 'flasharray-files', 'target': '192.0.2.10',
    }
    info.update(PERF)
    info.update(overrides)
    return base.APIDictWrapper(info)


def fb_row(**overrides):
    row = {
        'name': FS_NAME, 'share_instance_id': IID, 'provisioned': 200.0,
        'used': 100.0, 'total_physical': 40.0, 'unique': 37.0,
        'snapshots': 3.0, 'data_reduction': '2.50 to 1',
        'nfs_rules': '10.0.0.0/24(rw,no_root_squash)', 'nfs_v3': False,
        'nfs_v41': True, 'smb_enabled': False, 'hard_limit': True,
        'created': CREATED, 'destroyed': False,
    }
    row.update(overrides)
    return row


def fa_row(**overrides):
    row = {
        'name': DIR_NAME, 'directory_name': DIR_SHORT,
        'path': '/' + DIR_SHORT, 'share_id': SHARE_ID, 'used': 10.0,
        'unique': 9.0, 'snapshots': 1.0, 'virtual': 100.0,
        'total_physical': 10.0, 'data_reduction': '3.00 to 1',
        'created': CREATED, 'destroyed': False,
    }
    row.update(overrides)
    return row


def _share_url(share_id):
    """The manila-ui admin share detail URL, or None when not installed."""
    try:
        return reverse('horizon:admin:shares:detail',
                       kwargs={'share_id': share_id})
    except NoReverseMatch:
        return None


def _share_instance_url(instance_id):
    """The manila-ui admin share instance detail URL, or None."""
    try:
        return reverse('horizon:admin:share_instances:share_instance_detail',
                       kwargs={'share_instance_id': instance_id})
    except NoReverseMatch:
        return None


@override_settings(PURE_FLASHARRAYS=ARRAYS, PURE_FLASHBLADES=BLADES,
                   PURE_FLASHARRAY_FILES=FILES)
class PanelViewTests(test.BaseAdminViewTests):

    def setUp(self):
        super().setUp()
        registry.reset()
        self.addCleanup(registry.reset)
        # No view test may ever build a real client.
        patcher = mock.patch.object(
            registry, '_build_client',
            side_effect=RuntimeError('no network in tests'))
        self.build = patcher.start()
        self.addCleanup(patcher.stop)

        self.fa_api = self._patch_api(pure_flash_array, 'FlashArrayAPI')
        self.fa_api.get_array_list.return_value = ['pure-iscsi']
        self.fa_api.get_array_info.return_value = fa_info()
        self.fa_api.get_total_stats.return_value = dict(FA_STATS)

        self.fb_api = self._patch_api(pure_flash_blade, 'FlashBladeAPI')
        self.fb_api.get_backend_list.return_value = ['flashblade']
        self.fb_api.get_array_info.return_value = fb_info()
        self.fb_api.get_total_stats.return_value = dict(FB_STATS)
        self.fb_api.list_manila_file_systems.return_value = []

        self.fafiles_api = self._patch_api(pure_fa_files,
                                           'FlashArrayFilesAPI')
        self.fafiles_api.get_backend_list.return_value = ['flasharray-files']
        self.fafiles_api.get_array_info.return_value = fafiles_info()
        self.fafiles_api.get_total_stats.return_value = dict(FAFILES_STATS)
        self.fafiles_api.list_manila_directories.return_value = []

    def _patch_api(self, module, class_name):
        """Patch ``module.class_name``; return the instance every call gets."""
        patcher = mock.patch.object(module, class_name)
        api_class = patcher.start()
        self.addCleanup(patcher.stop)
        return api_class.return_value

    @staticmethod
    def _tab_slugs(res):
        return [tab.slug for tab in res.context['tab_group'].get_tabs()]

    # URLs

    def test_urls_reverse(self):
        self.assertEqual(INDEX_URL, reverse('horizon:admin:pure_panel:index'))
        self.assertEqual(FA_DETAIL_URL, reverse(
            'horizon:admin:pure_panel:flasharrays:detail',
            kwargs={'backend_id': 'pure-iscsi'}))
        self.assertEqual(FB_DETAIL_URL, reverse(
            'horizon:admin:pure_panel:flashblades:detail',
            kwargs={'backend_id': 'flashblade'}))
        self.assertEqual(FAFILES_DETAIL_URL, reverse(
            'horizon:admin:pure_panel:fafiles:detail',
            kwargs={'backend_id': 'flasharray-files'}))

    # Index

    def test_index_renders_all_summaries(self):
        res = self.client.get(INDEX_URL)

        self.assertEqual(200, res.status_code)
        self.assertTemplateUsed(res, 'pure_panel/index.html')
        self.assertEqual(FA_STATS, res.context['fa_stats'])
        self.assertEqual(FB_STATS, res.context['fb_stats'])
        self.assertEqual(FAFILES_STATS, res.context['fafiles_stats'])
        self.fa_api.get_total_stats.assert_called_once_with()
        self.fb_api.get_total_stats.assert_called_once_with()
        self.fafiles_api.get_total_stats.assert_called_once_with()
        self.assertEqual(['flasharray_tab', 'flashblade_tab', 'fafiles_tab'],
                         self._tab_slugs(res))

        content = res.content.decode()
        self.assertIn('FlashArray Summary', content)
        self.assertIn('FlashBlade Summary', content)
        self.assertIn('FlashArray Files Summary', content)
        self.assertNotIn('No Everpure backends are configured', content)
        # Only the active (first) tab loads its table on the initial page.
        self.fa_api.get_array_list.assert_called_once_with()
        self.fa_api.get_array_info.assert_called_once_with('pure-iscsi')
        self.assertIn('fa-lab', content)
        self.assertIn(FA_DETAIL_URL, content)
        self.fb_api.get_array_info.assert_not_called()
        self.fafiles_api.get_array_info.assert_not_called()
        self.build.assert_not_called()

    def test_index_flashblade_tab(self):
        res = self.client.get(FB_TAB_URL)

        self.assertEqual(200, res.status_code)
        self.fb_api.get_backend_list.assert_called_once_with()
        self.fb_api.get_array_info.assert_called_once_with('flashblade')
        self.fa_api.get_array_info.assert_not_called()
        content = res.content.decode()
        self.assertIn('fb-lab', content)
        self.assertIn('https://192.0.2.20/', content)
        self.assertIn(FB_DETAIL_URL, content)
        self.assertIn('4.5.3', content)

    def test_index_fafiles_tab(self):
        res = self.client.get(FAFILES_TAB_URL)

        self.assertEqual(200, res.status_code)
        self.fafiles_api.get_backend_list.assert_called_once_with()
        self.fafiles_api.get_array_info.assert_called_once_with(
            'flasharray-files')
        content = res.content.decode()
        self.assertIn('tenant-fs', content)
        self.assertIn(FAFILES_DETAIL_URL, content)
        self.assertIn('6.10.6', content)

    def test_index_tab_skips_failing_backend(self):
        self.fb_api.get_backend_list.return_value = ['flashblade', 'fb-two']
        self.fb_api.get_array_info.side_effect = [
            fb_info(), RuntimeError('boom')]

        res = self.client.get(FB_TAB_URL)

        self.assertEqual(200, res.status_code)
        self.assertEqual([mock.call('flashblade'), mock.call('fb-two')],
                         self.fb_api.get_array_info.call_args_list)
        self.assertIn('fb-lab', res.content.decode())

    def test_index_unconfigured_kinds_are_none(self):
        self.fb_api.get_total_stats.return_value = {}
        self.fafiles_api.get_total_stats.return_value = {}
        with override_settings(PURE_FLASHBLADES=[],
                               PURE_FLASHARRAY_FILES=[]):
            res = self.client.get(INDEX_URL)

        self.assertEqual(200, res.status_code)
        self.assertEqual(FA_STATS, res.context['fa_stats'])
        self.assertIsNone(res.context['fb_stats'])
        self.assertIsNone(res.context['fafiles_stats'])
        self.assertEqual(['flasharray_tab'], self._tab_slugs(res))
        content = res.content.decode()
        self.assertIn('FlashArray Summary', content)
        self.assertNotIn('FlashBlade Summary', content)
        self.assertNotIn('FlashArray Files Summary', content)
        self.fb_api.get_backend_list.assert_not_called()
        self.fafiles_api.get_backend_list.assert_not_called()

    def test_index_nothing_configured(self):
        for api in (self.fa_api, self.fb_api, self.fafiles_api):
            api.get_total_stats.return_value = {}
        with override_settings(PURE_FLASHARRAYS=[], PURE_FLASHBLADES=[],
                               PURE_FLASHARRAY_FILES=[]):
            res = self.client.get(INDEX_URL)

        self.assertEqual(200, res.status_code)
        self.assertIsNone(res.context['fa_stats'])
        self.assertEqual([], self._tab_slugs(res))
        self.assertIn('No Everpure backends are configured',
                      res.content.decode())
        self.fa_api.get_array_list.assert_not_called()

    def test_index_stats_failure_is_handled(self):
        self.fb_api.get_total_stats.side_effect = RuntimeError('boom')

        res = self.client.get(INDEX_URL)

        self.assertEqual(200, res.status_code)
        self.assertIsNone(res.context['fb_stats'])
        self.assertEqual(FA_STATS, res.context['fa_stats'])
        self.assertEqual(FAFILES_STATS, res.context['fafiles_stats'])
        self.assertMessageCount(res, error=1)

    # Tabs

    def test_tab_allowed_gates_on_configuration(self):
        group = pure_tabs.PurePanelTabs(self.request)
        self.assertEqual(['flasharray_tab', 'flashblade_tab', 'fafiles_tab'],
                         [tab.slug for tab in group.get_tabs()])

        with override_settings(PURE_FLASHBLADES=[]):
            tab = pure_tabs.FlashBladeTab(group, self.request)
            self.assertFalse(tab.allowed(self.request))
            self.assertEqual(
                ['flasharray_tab', 'fafiles_tab'],
                [t.slug for t in
                 pure_tabs.PurePanelTabs(self.request).get_tabs()])
        with override_settings(PURE_FLASHARRAY_FILES=[]):
            tab = pure_tabs.FlashArrayFilesTab(group, self.request)
            self.assertFalse(tab.allowed(self.request))
        with override_settings(PURE_FLASHARRAYS=[]):
            tab = pure_tabs.FlashArrayTab(group, self.request)
            self.assertFalse(tab.allowed(self.request))
        # Nothing above touched an API object or a client.
        self.fb_api.get_backend_list.assert_not_called()
        self.build.assert_not_called()

    def test_tab_data_methods_return_api_rows(self):
        group = pure_tabs.PurePanelTabs(self.request)

        rows = group.get_tab('flashblade_tab').get_flashblades_data()
        self.assertEqual(['flashblade'], [row.backend_id for row in rows])
        self.fb_api.get_array_info.assert_called_once_with('flashblade')

        rows = group.get_tab('fafiles_tab').get_fafiles_data()
        self.assertEqual(['flasharray-files'],
                         [row.backend_id for row in rows])
        self.fafiles_api.get_array_info.assert_called_once_with(
            'flasharray-files')

        rows = group.get_tab('flasharray_tab').get_flasharrays_data()
        self.assertEqual(['pure-iscsi'], [row.cinder_id for row in rows])

    # FlashArray detail (moved under flasharrays/)

    def test_flasharray_detail(self):
        res = self.client.get(FA_DETAIL_URL)

        self.assertEqual(200, res.status_code)
        self.assertTemplateUsed(res, 'pure_panel/flasharrays/detail_view.html')
        self.assertEqual('pure-iscsi', res.context['page_title'])
        self.fa_api.get_array_info.assert_called_once_with('pure-iscsi',
                                                           detailed=True)
        content = res.content.decode()
        self.assertIn('fa-lab', content)
        self.assertIn('Read Bandwidth', content)

    # FlashBlade detail

    def test_flashblade_detail_overview(self):
        res = self.client.get(FB_DETAIL_URL)

        self.assertEqual(200, res.status_code)
        self.assertTemplateUsed(res, 'pure_panel/flashblades/detail_view.html')
        self.assertEqual('flashblade', res.context['page_title'])
        self.fb_api.get_array_info.assert_called_once_with('flashblade',
                                                           detailed=True)
        # The Manila Shares tab is not preloaded.
        self.fb_api.list_manila_file_systems.assert_not_called()
        content = res.content.decode()
        self.assertIn('fb-lab', content)
        self.assertIn('https://192.0.2.20/', content)
        self.assertIn('FlashBlade//S200', content)
        self.assertIn('Manila Shares', content)
        self.build.assert_not_called()

    def test_flashblade_detail_error_row_renders(self):
        self.fb_api.get_array_info.return_value = fb_info(
            status='Error: Unable to connect to flashblade (192.0.2.20)',
            array_name='Unknown', version='Unknown', model='Unknown',
            capacity=0, total=0)
        res = self.client.get(FB_DETAIL_URL)
        self.assertEqual(200, res.status_code)
        self.assertIn('Error: Unable to connect', res.content.decode())

    def test_flashblade_detail_manila_shares_tab(self):
        self.fb_api.list_manila_file_systems.return_value = [
            fb_row(), fb_row(name='share-x-manila', share_instance_id=None,
                             created=None)]

        res = self.client.get(
            FB_DETAIL_URL + '?tab=flashblade_details__manila_shares')

        self.assertEqual(200, res.status_code)
        self.fb_api.list_manila_file_systems.assert_called_once_with(
            'flashblade')
        content = res.content.decode()
        self.assertIn(FS_NAME, content)
        self.assertIn(IID, content)
        self.assertIn('2023-11-14 22:13 UTC', content)
        self.assertIn('share-x-manila', content)
        # A FlashBlade file system is named after the share instance, so
        # the id links to manila-ui's share instance page, not a share's.
        self.assertNotIn('/admin/shares/%s/' % IID, content)
        instance_url = _share_instance_url(IID)
        if instance_url is None:
            self.skipTest('manila-ui is not installed')
        self.assertIn('href="%s"' % instance_url, content)

    # FlashArray Files detail

    def test_fafiles_detail_overview(self):
        res = self.client.get(FAFILES_DETAIL_URL)

        self.assertEqual(200, res.status_code)
        self.assertTemplateUsed(res, 'pure_panel/fafiles/detail_view.html')
        self.assertEqual('flasharray-files', res.context['page_title'])
        self.fafiles_api.get_array_info.assert_called_once_with(
            'flasharray-files', detailed=True)
        self.fafiles_api.list_manila_directories.assert_not_called()
        content = res.content.decode()
        self.assertIn('fa-lab', content)
        self.assertIn('https://192.0.2.10/', content)
        self.assertIn('Parent File System', content)
        self.assertIn('tenant-fs', content)
        self.assertIn('Managed Directories', content)

    def test_fafiles_detail_manila_shares_tab(self):
        self.fafiles_api.list_manila_directories.return_value = [
            fa_row(), fa_row(name='tenant-fs:custom', share_id=None)]

        res = self.client.get(
            FAFILES_DETAIL_URL + '?tab=fafiles_details__manila_shares')

        self.assertEqual(200, res.status_code)
        self.fafiles_api.list_manila_directories.assert_called_once_with(
            'flasharray-files')
        content = res.content.decode()
        self.assertIn(DIR_NAME, content)
        self.assertIn(SHARE_ID, content)
        self.assertIn('tenant-fs:custom', content)
        self.assertIn('Used (physical)', content)
        self.assertIn('Used (logical)', content)
        share_url = _share_url(SHARE_ID)
        if share_url is None:
            self.skipTest('manila-ui is not installed')
        self.assertIn('href="%s"' % share_url, content)

    # Tables and helpers

    def test_share_detail_url(self):
        self.assertIsNone(pure_tables.share_detail_url(None))
        self.assertIsNone(pure_tables.share_detail_url(''))
        with mock.patch.object(pure_tables, 'reverse',
                               side_effect=NoReverseMatch('no manila-ui')):
            self.assertIsNone(pure_tables.share_detail_url(SHARE_ID))
        self.assertEqual(_share_url(SHARE_ID),
                         pure_tables.share_detail_url(SHARE_ID))

    def test_share_instance_detail_url(self):
        self.assertIsNone(pure_tables.share_instance_detail_url(None))
        self.assertIsNone(pure_tables.share_instance_detail_url(''))
        with mock.patch.object(pure_tables, 'reverse',
                               side_effect=NoReverseMatch('no manila-ui')):
            self.assertIsNone(pure_tables.share_instance_detail_url(IID))
        self.assertEqual(_share_instance_url(IID),
                         pure_tables.share_instance_detail_url(IID))
        self.assertEqual(_share_instance_url(IID),
                         fb_tables.get_share_instance_url(fb_row()))
        self.assertIsNone(fb_tables.get_share_instance_url(
            fb_row(share_instance_id=None)))
        if _share_instance_url(IID) is None:
            self.skipTest('manila-ui is not installed')
        self.assertEqual('/admin/share_instances/' + IID,
                         _share_instance_url(IID))

    def test_format_created(self):
        self.assertEqual('-', pure_tables.format_created(None))
        self.assertEqual('2023-11-14 22:13 UTC',
                         pure_tables.format_created(CREATED))

    def test_table_row_ids_and_links(self):
        fb_table = pure_tables.PureFlashBladeTable(self.request, [fb_info()])
        self.assertEqual('flashblade', fb_table.get_object_id(fb_info()))
        self.assertEqual('flashblade', fb_table.get_object_display(fb_info()))
        self.assertEqual(FB_DETAIL_URL,
                         pure_tables.get_flashblade_detail_url(fb_info()))

        fa_table = pure_tables.PureFlashArrayFilesTable(self.request,
                                                        [fafiles_info()])
        self.assertEqual('flasharray-files',
                         fa_table.get_object_id(fafiles_info()))
        self.assertEqual(FAFILES_DETAIL_URL,
                         pure_tables.get_fafiles_detail_url(fafiles_info()))
        self.assertEqual('https://192.0.2.10/',
                         pure_tables.get_purity_url(fafiles_info()))

        fs_table = fb_tables.ManilaFileSystemsTable(self.request, [fb_row()])
        self.assertEqual(FS_NAME, fs_table.get_object_id(fb_row()))
        self.assertEqual(FS_NAME, fs_table.get_object_display(fb_row()))

        dir_table = fafiles_tables.ManilaDirectoriesTable(self.request,
                                                          [fa_row()])
        self.assertEqual(DIR_NAME, dir_table.get_object_id(fa_row()))
        self.assertEqual(_share_url(SHARE_ID),
                         fafiles_tables.get_share_url(fa_row()))
        self.assertIsNone(fafiles_tables.get_share_url(fa_row(share_id=None)))
