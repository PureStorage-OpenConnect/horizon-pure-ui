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

"""Tests for horizon_pure.api.pure_manila."""

import datetime
import sys
import types
from unittest import mock

from django.test import override_settings

from openstack_dashboard.test import helpers as test
from urllib3 import exceptions as urllib3_exceptions

from horizon_pure.api import pure_manila
from horizon_pure.api import registry
from horizon_pure.tests import test_pure_fa_files as fa_fixtures
from horizon_pure.tests import test_pure_flash_blade as fb_fixtures


SHARE_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
IID = '11111111-2222-3333-4444-555555555555'
IID2 = '66666666-7777-8888-9999-000000000000'
FB_FS = 'share-%s-manila' % IID
FA_DIR = 'tenant-fs:share-%s-manila' % SHARE_ID
FB_CONF = {'mgmt_ip': '192.0.2.20', 'api_token': 'tok',
           'backend_name': 'flashblade'}
FA_CONF = {'san_ip': '192.0.2.10', 'api_token': 'tok',
           'backend_name': 'flasharray-files', 'parent_fs': 'tenant-fs'}


def _request(admin=False):
    return types.SimpleNamespace(
        user=types.SimpleNamespace(is_superuser=admin))


def _share(share_id=SHARE_ID, host=None, export_locations=None):
    share = types.SimpleNamespace(id=share_id, name='my-share')
    if host is not None:
        share.host = host
    if export_locations is not None:
        share.export_locations = export_locations
    return share


def _location(path):
    return types.SimpleNamespace(path=path, preferred=False)


def _raise(exc):
    raise exc


# Captured before any test patches it.
_real_manila_api = pure_manila._manila_api


class NamingTests(test.TestCase):

    def test_names_from_export_paths(self):
        names = pure_manila.fb_file_system_names(_share(), export_paths=[
            '10.0.0.1:/share-abc-manila',
            '[fd00::1]:/share-abc-manila',
            '10.0.0.2:/share-def-manila',
            'host:/exports/nested-name',
            '',
            None,
        ])
        self.assertEqual(['share-abc-manila', 'share-def-manila',
                          'nested-name'], names)

    def test_name_from_export_path(self):
        cases = (
            ('10.0.0.1:/share-abc-manila', 'share-abc-manila'),
            ('[fd00::1]:/share-abc-manila', 'share-abc-manila'),
            ('fd00::1:/share-abc-manila', 'share-abc-manila'),
            ('/share-abc-manila', 'share-abc-manila'),
            ('share-abc-manila', 'share-abc-manila'),
            ('10.0.0.1:/share-abc-manila/', 'share-abc-manila'),
            ('10.0.0.1:/', None),
            ('', None),
            (None, None),
            (42, None),
        )
        for path, expected in cases:
            with self.subTest(path=path):
                self.assertEqual(expected,
                                 pure_manila.name_from_export_path(path))

    def test_names_from_instance_ids(self):
        names = pure_manila.fb_file_system_names(_share(),
                                                 instance_ids=[IID, IID2, IID,
                                                               None])
        self.assertEqual(['share-%s-manila' % IID, 'share-%s-manila' % IID2],
                         names)
        with override_settings(PURE_MANILA_SHARE_NAME_TEMPLATE='manila-%s'):
            self.assertEqual(['manila-%s-manila' % IID],
                             pure_manila.fb_file_system_names(
                                 _share(), instance_ids=[IID]))
        self.assertEqual(['custom-%s-manila' % IID],
                         pure_manila.fb_file_system_names(
                             _share(), instance_ids=[IID],
                             template='custom-%s'))

    def test_names_combined_and_deduplicated(self):
        names = pure_manila.fb_file_system_names(
            _share(), export_paths=['10.0.0.1:/' + FB_FS],
            instance_ids=[IID, IID2])
        self.assertEqual([FB_FS, 'share-%s-manila' % IID2], names)

    def test_names_fall_back_to_share_export_locations(self):
        share = _share(export_locations=[{'path': '10.0.0.1:/' + FB_FS},
                                         _location('10.0.0.2:/' + FB_FS),
                                         '10.0.0.3:/other'])
        self.assertEqual([FB_FS, 'other'],
                         pure_manila.fb_file_system_names(share))
        # Explicit paths win over the attribute.
        self.assertEqual(['x'], pure_manila.fb_file_system_names(
            share, export_paths=['h:/x']))
        self.assertEqual([], pure_manila.fb_file_system_names(_share()))

    def test_manila_fs_name_re(self):
        pattern = pure_manila.manila_fs_name_re()
        self.assertEqual(IID, pattern.match(FB_FS).group('id'))
        self.assertIsNone(pattern.match('share-%s' % IID))
        self.assertIsNone(pattern.match('share-notauuid-manila'))
        self.assertIsNone(pattern.match('xshare-%s-manila' % IID))
        self.assertIsNone(pattern.match('share-%s-manila-x' % IID))
        self.assertIsNone(pattern.match('manila-%s-manila' % IID))
        self.assertEqual(IID, pure_manila.id_from_name(FB_FS))
        self.assertIsNone(pure_manila.id_from_name(None))

        with override_settings(PURE_MANILA_SHARE_NAME_TEMPLATE='manila-%s'):
            pattern = pure_manila.manila_fs_name_re()
            match = pattern.match('manila-%s-manila' % IID)
            self.assertEqual(IID, match.group('id'))
            self.assertIsNone(pattern.match(FB_FS))
            self.assertEqual('manila-%s', pure_manila.share_name_template())

        with override_settings(PURE_MANILA_SHARE_NAME_TEMPLATE='%s-%s'):
            self.assertEqual('share-%s', pure_manila.share_name_template())
            self.assertIsNotNone(pure_manila.manila_fs_name_re().match(FB_FS))
        with override_settings(PURE_MANILA_SHARE_NAME_TEMPLATE=None):
            self.assertEqual('share-%s', pure_manila.share_name_template())

        # The FlashArray driver ignores the template.
        self.assertEqual(IID, pure_manila.FA_DIRECTORY_RE.match(
            FB_FS).group('id'))

    def test_fa_directory_short_name(self):
        self.assertEqual('share-%s-manila' % SHARE_ID,
                         pure_manila.fa_directory_short_name(SHARE_ID))
        with override_settings(PURE_MANILA_SHARE_NAME_TEMPLATE='manila-%s'):
            self.assertEqual('share-%s-manila' % SHARE_ID,
                             pure_manila.fa_directory_short_name(SHARE_ID))

    def test_to_datetime(self):
        self.assertEqual(
            datetime.datetime(2023, 11, 14, 22, 13, 20,
                              tzinfo=datetime.timezone.utc),
            pure_manila.to_datetime(1700000000000))
        self.assertIsNone(pure_manila.to_datetime(None))
        self.assertIsNone(pure_manila.to_datetime('soon'))


@override_settings(PURE_FLASHBLADES=[FB_CONF],
                   PURE_FLASHARRAY_FILES=[FA_CONF])
class ShareInfoTests(test.TestCase):

    def setUp(self):
        super().setUp()
        registry.reset()
        self.addCleanup(registry.reset)
        self.fb = fb_fixtures.make_client()
        fb_fixtures.set_file_systems(
            self.fb, by_name={FB_FS: fb_fixtures._fs(FB_FS)})
        self.fa = fa_fixtures.make_client()
        fa_fixtures.set_directories(
            self.fa, by_name={FA_DIR: fa_fixtures._dir(
                'share-%s-manila' % SHARE_ID, parent='tenant-fs')})
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

    def _built_kinds(self):
        return [call[0][0].kind for call in self.build.call_args_list]

    def test_unconfigured(self):
        with override_settings(PURE_FLASHBLADES=[],
                               PURE_FLASHARRAY_FILES=[]):
            info = pure_manila.get_share_info(_request(admin=True),
                                              _share(host='h@flashblade#p'))
        self.assertFalse(info['configured'])
        self.assertFalse(info['found'])
        self.assertIsNone(info['kind'])
        self.assertIsNone(info['error'])
        self.assertTrue(info['is_admin'])
        self.assertEqual(SHARE_ID, info['share_id'])
        self.build.assert_not_called()
        self.manila.share_export_location_list.assert_not_called()

    def test_admin_resolves_backend_from_host_and_instances(self):
        request = _request(admin=True)
        share = _share(host='ctl@flashblade#flashblade')
        self.manila.share_instance_list.return_value = [
            types.SimpleNamespace(id=IID2, share_id='other-share',
                                  host='ctl@flashblade#flashblade'),
            types.SimpleNamespace(id=IID, share_id=SHARE_ID,
                                  host='ctl@flashblade#flashblade'),
        ]

        info = pure_manila.get_share_info(request, share)

        self.manila.share_export_location_list.assert_called_once_with(
            request, SHARE_ID)
        self.manila.share_instance_list.assert_called_once_with(request)
        self.assertEqual(['fb'], self._built_kinds())
        self.fb.get_file_systems.assert_called_once_with(names=[FB_FS])
        self.fa.get_directories.assert_not_called()

        self.assertTrue(info['configured'])
        self.assertTrue(info['found'])
        self.assertTrue(info['is_admin'])
        self.assertEqual('fb', info['kind'])
        self.assertEqual('flashblade', info['backend_name'])
        self.assertEqual(('manila', 'flashblade'), info['entry'].key)
        self.assertIsNone(info['error'])
        self.assertEqual([], info['export_paths'])
        self.assertEqual([FB_FS], info['candidate_names'])
        self.assertEqual(1, len(info['file_systems']))
        self.assertEqual(FB_FS, info['file_systems'][0]['name'])
        self.assertEqual(IID, info['file_systems'][0]['share_instance_id'])
        self.assertEqual(2, info['file_systems'][0]['snapshot_count'])
        self.assertIsNone(info['directory'])

    def test_project_user_resolves_from_export_locations(self):
        request = _request(admin=False)
        self.manila.share_export_location_list.return_value = [
            _location('10.0.0.1:/' + FB_FS),
            _location('[fd00::1]:/' + FB_FS),
        ]

        info = pure_manila.get_share_info(request, _share())

        self.manila.share_export_location_list.assert_called_once_with(
            request, SHARE_ID)
        self.manila.share_instance_list.assert_not_called()
        # Settings order: FlashBlade first, and it hits, so no FA lookup.
        self.assertEqual(['fb'], self._built_kinds())
        self.fb.get_file_systems.assert_called_once_with(names=[FB_FS])
        self.fa.get_directories.assert_not_called()
        self.assertTrue(info['found'])
        self.assertFalse(info['is_admin'])
        self.assertEqual('fb', info['kind'])
        self.assertEqual('flashblade', info['backend_name'])
        self.assertEqual(['10.0.0.1:/' + FB_FS, '[fd00::1]:/' + FB_FS],
                         info['export_paths'])
        self.assertEqual([FB_FS], info['candidate_names'])
        self.assertEqual([FB_FS], [fs['name'] for fs in info['file_systems']])

    def test_flasharray_share_resolved_by_share_id(self):
        request = _request(admin=False)
        # The FA export name may be a tenant mount_point_name.
        self.manila.share_export_location_list.return_value = [
            _location('10.0.0.5:/myshare')]

        info = pure_manila.get_share_info(request, _share())

        self.assertEqual(['fb', 'fa'], self._built_kinds())
        self.fb.get_file_systems.assert_called_once_with(names=['myshare'])
        self.fa.get_directories.assert_called_once_with(names=[FA_DIR])
        self.fa.get_policies_nfs_client_rules.assert_called_once_with(
            policy_names=['share-%s-manila-nfs' % SHARE_ID])
        self.assertTrue(info['found'])
        self.assertEqual('fa', info['kind'])
        self.assertEqual('flasharray-files', info['backend_name'])
        self.assertEqual(FA_CONF['parent_fs'], info['entry'].parent_fs)
        self.assertEqual([], info['file_systems'])
        self.assertEqual(FA_DIR, info['directory']['name'])
        self.assertEqual(SHARE_ID, info['directory']['share_id'])
        self.assertEqual(50.0, info['directory']['quota_limit'])
        self.assertEqual(['myshare'], info['candidate_names'])
        self.assertIsNone(info['error'])

    def test_admin_flasharray_share_via_host_skips_flashblade(self):
        request = _request(admin=True)
        share = _share(host='ctl@flasharray-files#flasharray-files')
        info = pure_manila.get_share_info(request, share)
        self.assertEqual(['fa'], self._built_kinds())
        self.fb.get_file_systems.assert_not_called()
        # No FlashBlade candidate: Manila is not asked for locations.
        self.manila.share_export_location_list.assert_not_called()
        self.manila.share_instance_list.assert_not_called()
        self.assertTrue(info['found'])
        self.assertEqual('fa', info['kind'])
        self.assertEqual([], info['candidate_names'])

    def test_admin_unknown_backend_tries_all(self):
        request = _request(admin=True)
        share = _share(host='ctl@netapp#pool')
        self.manila.share_export_location_list.return_value = [
            _location('10.0.0.1:/' + FB_FS)]
        info = pure_manila.get_share_info(request, share)
        self.assertEqual(['fb'], self._built_kinds())
        self.assertTrue(info['found'])
        self.assertEqual('flashblade', info['backend_name'])

    def test_nothing_found(self):
        request = _request(admin=True)
        self.manila.share_export_location_list.return_value = [
            _location('10.0.0.1:/share-%s-manila' % IID2)]
        info = pure_manila.get_share_info(request, _share(share_id=IID2))

        self.fb.get_file_systems.assert_called_once_with(
            names=['share-%s-manila' % IID2])
        self.fa.get_directories.assert_called_once_with(
            names=['tenant-fs:share-%s-manila' % IID2])
        self.assertTrue(info['configured'])
        self.assertFalse(info['found'])
        self.assertIsNone(info['kind'])
        self.assertIsNone(info['backend_name'])
        self.assertEqual([], info['file_systems'])
        self.assertIsNone(info['directory'])
        self.assertIn('flashblade: no file system named share-%s-manila'
                      % IID2, info['error'])
        self.assertIn('flasharray-files: no managed directory '
                      'tenant-fs:share-%s-manila' % IID2, info['error'])

    def test_no_names_derivable_for_flashblade(self):
        # Project user, no export locations yet: FlashBlade cannot be
        # searched, FlashArray still is.
        info = pure_manila.get_share_info(_request(), _share(share_id=IID2))
        self.fb.get_file_systems.assert_not_called()
        self.fa.get_directories.assert_called_once()
        self.assertFalse(info['found'])
        self.assertIn('flashblade: no file system name could be derived',
                      info['error'])
        self.assertEqual([], info['candidate_names'])

    def test_unavailable_backend_is_reported_and_skipped(self):
        self.build.side_effect = (
            lambda entry: (_raise(RuntimeError('connection refused'))
                           if entry.kind == 'fb' else self.fa))
        info = pure_manila.get_share_info(_request(), _share())
        self.assertTrue(info['found'])
        self.assertEqual('fa', info['kind'])
        self.fb.get_file_systems.assert_not_called()
        # Found elsewhere, so the tab shows the hit, not the error.
        self.assertIsNone(info['error'])

        registry.reset()
        info = pure_manila.get_share_info(_request(), _share(share_id=IID2))
        self.assertFalse(info['found'])
        self.assertIn('connection refused', info['error'])
        self.assertIn('192.0.2.20', info['error'])
        self.assertIn('flasharray-files: no managed directory', info['error'])

    def test_array_errors_are_not_reported_as_missing(self):
        # 503 from the FlashBlade, 401 (rotated token) from the FlashArray:
        # the tab must name the failure, not claim the object is missing.
        self.fb.get_file_systems.side_effect = lambda **k: fb_fixtures._resp(
            status=503, errors=[types.SimpleNamespace(
                message='Service unavailable', context=None)])
        self.fa.get_directories.side_effect = lambda **k: fa_fixtures._resp(
            status=401, errors=[types.SimpleNamespace(
                message='Bad token', context=None)])
        self.manila.share_export_location_list.return_value = [
            _location('10.0.0.1:/' + FB_FS)]

        info = pure_manila.get_share_info(_request(), _share())

        self.fb.get_file_systems.assert_called_once_with(names=[FB_FS])
        self.fa.get_directories.assert_called_once_with(names=[FA_DIR])
        self.assertFalse(info['found'])
        self.assertEqual('flashblade: HTTP 503: Service unavailable; '
                         'flasharray-files: HTTP 401: Bad token',
                         info['error'])

    def test_sdk_exceptions_are_not_reported_as_missing(self):
        self.fa.get_directories.side_effect = RuntimeError('socket closed')
        info = pure_manila.get_share_info(
            _request(admin=True),
            _share(host='ctl@flasharray-files#flasharray-files'))
        self.assertFalse(info['found'])
        self.assertEqual('flasharray-files: socket closed', info['error'])

    def test_array_dying_after_first_contact_is_remembered(self):
        # The client was built fine; the array then stops answering. The
        # error names the array, and the registry drops the client so the
        # next lookup fails at once without another SDK call.
        self.fa.get_directories.side_effect = (
            urllib3_exceptions.MaxRetryError(None, '/api/2.x/directories',
                                             reason='timed out'))
        share = _share(host='ctl@flasharray-files#flasharray-files')

        info = pure_manila.get_share_info(_request(admin=True), share)
        self.assertFalse(info['found'])
        self.assertIn('Unable to contact flasharray-files (192.0.2.10)',
                      info['error'])
        self.assertIn('timed out', info['error'])
        self.assertNotIn('no managed directory', info['error'])

        info = pure_manila.get_share_info(_request(admin=True), share)
        self.assertIn('Unable to contact flasharray-files', info['error'])
        self.assertEqual(1, self.fa.get_directories.call_count)
        self.assertEqual(['fa'], self._built_kinds())

    def test_manila_ui_missing_is_tolerated(self):
        share = _share(export_locations=[{'path': '10.0.0.1:/' + FB_FS}])
        missing = {'manila_ui': None, 'manila_ui.api': None,
                   'manila_ui.api.manila': None}
        # setUp replaced _manila_api; restore the real one so the import
        # inside it really runs and really fails.
        with mock.patch.dict(sys.modules, missing), \
                mock.patch.object(pure_manila, '_manila_api',
                                  _real_manila_api):
            self.assertIsNone(pure_manila._manila_api())
            info = pure_manila.get_share_info(_request(admin=True), share)
        self.assertTrue(info['found'])
        self.assertEqual('fb', info['kind'])
        self.assertEqual(['10.0.0.1:/' + FB_FS], info['export_paths'])
        self.manila.share_export_location_list.assert_not_called()
        self.manila.share_instance_list.assert_not_called()

    def test_manila_api_errors_are_tolerated(self):
        self.manila.share_export_location_list.side_effect = RuntimeError(
            'manila down')
        self.manila.share_instance_list.side_effect = RuntimeError(
            'manila down')
        share = _share(export_locations=[_location('10.0.0.1:/' + FB_FS)])
        info = pure_manila.get_share_info(_request(admin=True), share)
        self.assertTrue(info['found'])
        self.assertEqual([FB_FS], info['candidate_names'])

        # Without any fallback the share is simply not found on FlashBlade.
        info = pure_manila.get_share_info(_request(admin=True),
                                          _share(share_id=IID2))
        self.assertFalse(info['found'])
        self.assertIn('no file system name could be derived', info['error'])

    def test_get_share_info_for_backend_with_names(self):
        entry = registry.find('manila', 'flashblade')
        result = pure_manila.get_share_info_for_backend(
            _request(), _share(), entry, names=['nope', FB_FS])
        self.assertEqual([mock.call(names=['nope']),
                          mock.call(names=[FB_FS])],
                         self.fb.get_file_systems.call_args_list)
        self.assertTrue(result['found'])
        self.assertEqual('fb', result['kind'])
        self.assertEqual([FB_FS],
                         [fs['name'] for fs in result['file_systems']])
        self.manila.share_export_location_list.assert_not_called()

        # names=None derives them from the share itself.
        self.fb.get_file_systems.reset_mock()
        share = _share(export_locations=[_location('h:/' + FB_FS)])
        result = pure_manila.get_share_info_for_backend(_request(), share,
                                                        entry)
        self.fb.get_file_systems.assert_called_once_with(names=[FB_FS])
        self.assertTrue(result['found'])

    def test_get_share_info_for_backend_share_without_id(self):
        entry = registry.find('manila', 'flasharray-files')
        share = types.SimpleNamespace(name='no-id')
        result = pure_manila.get_share_info_for_backend(_request(), share,
                                                        entry)
        self.assertFalse(result['found'])
        self.assertIn('share has no id', result['error'])
        self.fa.get_directories.assert_not_called()

    def test_api_exception_is_swallowed(self):
        with mock.patch.object(pure_manila, '_fa_api',
                               side_effect=RuntimeError('boom')):
            info = pure_manila.get_share_info(
                _request(admin=True),
                _share(host='ctl@flasharray-files#flasharray-files'))
        self.assertFalse(info['found'])
        self.assertEqual('flasharray-files: boom', info['error'])

        with mock.patch.object(registry, 'entries',
                               side_effect=RuntimeError('settings broken')):
            info = pure_manila.get_share_info(_request(), _share())
        self.assertFalse(info['found'])
        self.assertEqual('settings broken', info['error'])
