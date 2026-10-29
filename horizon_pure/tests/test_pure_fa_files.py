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

"""Tests for horizon_pure.api.pure_fa_files."""

import datetime
import types
from unittest import mock

from django.test import override_settings

from openstack_dashboard.api import base
from openstack_dashboard.test import helpers as test

from horizon_pure.api import pure_fa_files
from horizon_pure.api import registry


MIB = 1024 ** 2
SHARE_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
SHARE_ID2 = '11111111-2222-3333-4444-555555555555'
SHARE_ID3 = '66666666-7777-8888-9999-000000000000'
SNAP1 = 'f0000000-0000-0000-0000-000000000001'
SNAP2 = 'f0000000-0000-0000-0000-000000000002'
SNAP3 = 'f0000000-0000-0000-0000-000000000003'
SHORT = 'share-%s-manila' % SHARE_ID
DIR = 'openstack:' + SHORT
CREATED_MS = 1700000000000
CREATED = datetime.datetime(2023, 11, 14, 22, 13, 20,
                            tzinfo=datetime.timezone.utc)
FILES = [
    {'san_ip': '192.0.2.10', 'api_token': 'tok',
     'backend_name': 'flasharray-files'},
]


def _resp(items=None, status=200, total=None, errors=None):
    """A fake py-pure-client response; ``items`` is a one-shot iterator."""
    resp = types.SimpleNamespace(status_code=status)
    if status == 200:
        resp.items = iter(items or [])
        if total is not None:
            resp.total_item_count = total
    else:
        resp.errors = errors or [types.SimpleNamespace(
            message='Managed directory does not exist.', context=None)]
    return resp


def _fresh(method, *args, **kwargs):
    """Make ``method`` return a new response (new iterator) per call."""
    method.side_effect = lambda *a, **k: _resp(*args, **kwargs)


def _space(**overrides):
    values = {'data_reduction': 3.0, 'thin_provisioning': 4.0,
              'total_reduction': 12.0, 'snapshots': 1 * MIB,
              'total_physical': 10 * MIB, 'unique': 9 * MIB,
              'virtual': 100 * MIB, 'total_used': 10 * MIB}
    values.update(overrides)
    return types.SimpleNamespace(**values)


def _dir(short_name, parent='openstack', destroyed=False, **space):
    return types.SimpleNamespace(
        name='%s:%s' % (parent, short_name), directory_name=short_name,
        path='/' + short_name, created=CREATED_MS, destroyed=destroyed,
        space=_space(**space))


def _snap(suffix, client_name='openstack', destroyed=False, created=1,
          name=None):
    return types.SimpleNamespace(
        name=name or '%s.%s.%s' % (DIR, client_name, suffix),
        client_name=client_name, suffix=suffix, destroyed=destroyed,
        created=created)


def _perf():
    return types.SimpleNamespace(
        reads_per_sec=100, writes_per_sec=50,
        read_bytes_per_sec=2 * MIB, write_bytes_per_sec=512 * 1024,
        usec_per_read_op=300, usec_per_write_op=400)


def all_directories(parent='openstack'):
    return [
        _dir('root', parent),
        _dir('manila-zero-baseline', parent),
        _dir(SHORT, parent),
        _dir('share-%s-manila' % SHARE_ID2, parent, total_used=5 * MIB),
        _dir('custom-dir', parent),
        _dir('share-%s-manila' % SHARE_ID3, parent, destroyed=True),
    ]


#: the server-side count get_array_info asks for (one item, total only)
COUNT_FILTER = ("directory_name!='root' and "
                "directory_name!='manila-zero-baseline'")


def count_call(parent='openstack'):
    return mock.call(file_system_names=[parent], destroyed=False, limit=1,
                     total_item_count=True, filter=COUNT_FILTER)


def set_directories(client, listing=None, by_name=None):
    """get_directories answers names=, listings and server-side counts.

    A ``total_item_count=True`` call answers like the array does: at most
    ``limit`` items plus the number of directories left after
    ``destroyed=False`` and the hidden-directory filter.
    """
    by_name = {DIR: _dir(SHORT)} if by_name is None else by_name

    def respond(**kwargs):
        if 'names' in kwargs:
            found = [by_name[n] for n in kwargs['names'] if n in by_name]
            return _resp(found) if found else _resp(status=400)
        items = list(listing if listing is not None else all_directories())
        if kwargs.get('total_item_count'):
            live = [d for d in items if not d.destroyed and d.directory_name
                    not in pure_fa_files.HIDDEN_DIRECTORIES]
            return _resp(live[:kwargs.get('limit')], total=len(live))
        return _resp(items)

    client.get_directories.side_effect = respond


def make_client(name='fa-lab'):
    """A Mock FlashArray client with lab-shaped responses."""
    client = mock.Mock(name='client-%s' % name)
    _fresh(client.get_arrays, [types.SimpleNamespace(
        id='array-uuid', name=name, version='6.10.6',
        capacity=1000 * MIB, space=_space())])
    _fresh(client.get_arrays_space, [types.SimpleNamespace(
        capacity=1000 * MIB, space=_space())])
    _fresh(client.get_controllers, [
        types.SimpleNamespace(name='CT0', model='FA-X50R2', version='6.10.6'),
        types.SimpleNamespace(name='CT1', model='FA-X50R2', version='6.10.6'),
    ])
    _fresh(client.get_arrays_performance, [types.SimpleNamespace(
        reads_per_sec=100, writes_per_sec=50,
        read_bytes_per_sec=2 * MIB, write_bytes_per_sec=1 * MIB,
        usec_per_read_op=300, usec_per_write_op=400, queue_depth=3)])
    set_directories(client)
    _fresh(client.get_directory_quotas, [types.SimpleNamespace(
        usage=6 * MIB, quota_limit=50 * MIB, enforced=True,
        percentage_used=12,
        policy=types.SimpleNamespace(name=SHORT + '-quota'),
        rule_name='rule-1')])
    _fresh(client.get_policies_nfs_client_rules, [
        types.SimpleNamespace(client='10.0.0.5', permission='rw',
                              access='no-root-squash',
                              nfs_version=['nfsv3', 'nfsv4']),
        types.SimpleNamespace(client='10.0.0.0/24', permission='ro',
                              access='root-squash', nfs_version=None),
    ])
    _fresh(client.get_directory_exports, [types.SimpleNamespace(
        export_name=SHORT, enabled=True,
        policy=types.SimpleNamespace(name=SHORT + '-nfs'))])
    _fresh(client.get_directory_snapshots, [
        _snap(SNAP1, created=100),
        _snap('private'),
        _snap(SNAP2, created=200),
        _snap('x', client_name='other'),
        _snap(SNAP3, destroyed=True),
        _snap('1', name='%s.openstack.%s.copy.1' % (DIR, SNAP1)),
    ])
    _fresh(client.get_directories_performance, [_perf()])
    return client


@override_settings(PURE_FLASHARRAY_FILES=FILES)
class FlashArrayFilesAPITests(test.TestCase):

    def setUp(self):
        super().setUp()
        registry.reset()
        self.addCleanup(registry.reset)
        self.client = make_client()
        patcher = mock.patch.object(registry, '_build_client',
                                    return_value=self.client)
        self.build = patcher.start()
        self.addCleanup(patcher.stop)
        self.api = pure_fa_files.FlashArrayFilesAPI()

    def test_construction_builds_nothing(self):
        pure_fa_files.FlashArrayFilesAPI()
        self.assertEqual(['flasharray-files'], self.api.get_backend_list())
        self.build.assert_not_called()

    def test_get_array_info_detailed(self):
        info = self.api.get_array_info('flasharray-files', detailed=True)

        self.build.assert_called_once()
        self.assertEqual('flasharray-files',
                         self.build.call_args[0][0].backend_name)
        self.client.get_arrays.assert_called_once_with()
        self.client.get_controllers.assert_called_once_with()
        self.client.get_arrays_space.assert_called_once_with()
        self.client.get_arrays_performance.assert_called_once_with()
        # The count is the array's, not a full listing paged to the end.
        self.assertEqual([count_call()],
                         self.client.get_directories.call_args_list)

        self.assertIsInstance(info, base.APIDictWrapper)
        self.assertEqual('Connected', info.status)
        self.assertEqual('fa-lab', info.array_name)
        self.assertEqual('6.10.6', info.version)
        self.assertEqual('FA-X50R2', info.model)
        self.assertEqual('flasharray-files', info.backend_id)
        self.assertEqual('flasharray-files', info.backend_name)
        self.assertEqual('192.0.2.10', info.target)
        self.assertEqual('openstack', info.parent_fs)
        # root, baseline and the destroyed directory are not counted.
        self.assertEqual(3, info.directory_count)
        self.assertEqual(1000.0, info.capacity)
        self.assertEqual(10.0, info.total)
        self.assertEqual(1.0, info.snapshots)
        self.assertEqual(9.0, info.unique)
        self.assertEqual('3.00 to 1', info.data_reduction)
        self.assertEqual('4.00 to 1', info.thin_provisioning)
        self.assertEqual('12.00 to 1', info.total_reduction)
        self.assertEqual(100, info.reads_per_sec)
        self.assertEqual(2.0, info.output_per_sec)
        self.assertEqual(1.0, info.input_per_sec)
        self.assertEqual(400, info.usec_per_write_op)

    def test_get_array_info_not_detailed_skips_performance(self):
        info = self.api.get_array_info('flasharray-files')
        self.client.get_arrays_performance.assert_not_called()
        self.assertNotIn('reads_per_sec', info.to_dict())
        self.assertEqual(3, info.directory_count)

    def test_get_array_info_error_status_400(self):
        _fresh(self.client.get_arrays, status=400,
               errors=[types.SimpleNamespace(message='Bad request',
                                             context='arrays')])
        info = self.api.get_array_info('flasharray-files', detailed=True)
        self.client.get_directories.assert_not_called()
        self.assertIn('HTTP 400: Bad request (arrays)', info.status)
        self.assertTrue(info.status.startswith('Error: '), info.status)
        self.assertEqual('Unknown', info.array_name)
        self.assertEqual(0, info.capacity)
        self.assertEqual(0, info.directory_count)
        self.assertEqual('1.00 to 1', info.data_reduction)
        self.assertEqual('openstack', info.parent_fs)
        self.assertEqual('192.0.2.10', info.target)

    def test_get_array_info_directory_listing_failure(self):
        _fresh(self.client.get_directories, status=400)
        info = self.api.get_array_info('flasharray-files')
        self.assertEqual('Connected', info.status)
        self.assertEqual(0, info.directory_count)

    def test_get_array_info_directory_count_falls_back_to_listing(self):
        # A REST level that answers without total_item_count: the full
        # listing is fetched and counted client-side instead.
        self.client.get_directories.side_effect = (
            lambda **k: _resp(all_directories()))
        info = self.api.get_array_info('flasharray-files')
        self.assertEqual(
            [count_call(),
             mock.call(file_system_names=['openstack'], destroyed=False)],
            self.client.get_directories.call_args_list)
        self.assertEqual(3, info.directory_count)

    def test_get_array_info_unavailable_array(self):
        self.build.side_effect = RuntimeError('connection refused')
        info = self.api.get_array_info('flasharray-files')
        self.assertTrue(info.status.startswith('Error: '), info.status)
        self.assertIn('connection refused', info.status)
        self.assertEqual('192.0.2.10', info.target)
        self.assertEqual('openstack', info.parent_fs)
        self.api.get_array_info('flasharray-files')
        self.assertEqual(1, self.build.call_count)

    def test_unknown_backend(self):
        info = self.api.get_array_info('nope')
        self.assertEqual('Error: Not in config', info.status)
        self.assertEqual('nope', info.target)
        self.assertEqual('nope', info.backend_id)
        self.assertEqual('openstack', info.parent_fs)
        # Cinder and FlashBlade backends are not FlashArray Files backends.
        with override_settings(PURE_FLASHBLADES=[
                {'mgmt_ip': '192.0.2.20', 'api_token': 'tok',
                 'backend_name': 'flashblade'}]):
            self.assertEqual('Error: Not in config',
                             self.api.get_array_info('flashblade').status)
        self.assertEqual('Error: Not in config',
                         self.api.get_array_info('pure-iscsi').status)
        self.build.assert_not_called()

    def test_get_total_stats_dedupes_by_target(self):
        conf = [
            {'san_ip': '192.0.2.10', 'api_token': 'tok',
             'backend_name': 'flasharray-files'},
            {'san_ip': '192.0.2.10', 'api_token': 'tok',
             'backend_name': 'flasharray-files-two', 'parent_fs': 'other'},
            {'san_ip': '192.0.2.11', 'api_token': 'tok',
             'backend_name': 'flasharray-files-b'},
        ]
        second = make_client('fa-two')
        set_directories(second, listing=[_dir('root'), _dir(SHORT)])
        self.build.side_effect = (
            lambda entry: second if entry.target == '192.0.2.11'
            else self.client)
        with override_settings(PURE_FLASHARRAY_FILES=conf):
            stats = self.api.get_total_stats()

        self.assertEqual({'total_used': 20.0, 'total_available': 2000.0,
                          'total_directory_count': 4}, stats)
        self.assertEqual(1, self.client.get_arrays_space.call_count)
        self.assertEqual(1, second.get_arrays_space.call_count)
        self.assertEqual(2, self.build.call_count)

    def test_get_total_stats_unconfigured(self):
        with override_settings(PURE_FLASHARRAY_FILES=[]):
            self.assertEqual({}, self.api.get_total_stats())
        self.build.assert_not_called()

    def test_list_manila_directories(self):
        result = self.api.list_manila_directories('flasharray-files')

        self.client.get_directories.assert_called_once_with(
            file_system_names=['openstack'], destroyed=False)
        # root, the baseline, custom-dir and the destroyed share are gone.
        self.assertEqual([DIR, 'openstack:share-%s-manila' % SHARE_ID2],
                         [d['name'] for d in result])
        first = result[0]
        self.assertEqual(SHORT, first['directory_name'])
        self.assertEqual('/' + SHORT, first['path'])
        self.assertEqual(SHARE_ID, first['share_id'])
        # 'used' is the physical figure; 'virtual' the logical one.
        self.assertEqual(10.0, first['used'])
        self.assertEqual(100.0, first['virtual'])
        self.assertEqual(9.0, first['unique'])
        self.assertEqual(1.0, first['snapshots'])
        self.assertEqual(10.0, first['total_physical'])
        self.assertEqual('3.00 to 1', first['data_reduction'])
        self.assertEqual(CREATED, first['created'])
        self.assertFalse(first['destroyed'])
        self.assertEqual(SHARE_ID2, result[1]['share_id'])
        self.assertEqual(5.0, result[1]['used'])

    @override_settings(PURE_FLASHARRAY_FILES=[
        dict(FILES[0], parent_fs='tenant-fs')],
        PURE_MANILA_SHARE_NAME_TEMPLATE='manila-%s')
    def test_list_manila_directories_custom_parent_fs_ignores_template(self):
        set_directories(self.client, listing=all_directories('tenant-fs'))
        result = self.api.list_manila_directories('flasharray-files')
        self.client.get_directories.assert_called_once_with(
            file_system_names=['tenant-fs'], destroyed=False)
        # The FA driver always names directories share-<id>-manila.
        self.assertEqual(['tenant-fs:' + SHORT,
                          'tenant-fs:share-%s-manila' % SHARE_ID2],
                         [d['name'] for d in result])

    def test_list_manila_directories_errors_are_empty(self):
        _fresh(self.client.get_directories, status=400)
        self.assertEqual([],
                         self.api.list_manila_directories('flasharray-files'))
        self.client.get_directories.side_effect = RuntimeError('socket')
        self.assertEqual([],
                         self.api.list_manila_directories('flasharray-files'))
        self.assertEqual([], self.api.list_manila_directories('nope'))

    def test_list_manila_directories_unavailable(self):
        self.build.side_effect = RuntimeError('down')
        self.assertEqual([],
                         self.api.list_manila_directories('flasharray-files'))
        self.client.get_directories.assert_not_called()

    def test_get_directory_info(self):
        info = self.api.get_directory_info('flasharray-files', SHARE_ID)

        self.client.get_directories.assert_called_once_with(names=[DIR])
        self.client.get_directory_quotas.assert_called_once_with(
            directory_names=[DIR], policy_names=[SHORT + '-quota'])
        self.client.get_policies_nfs_client_rules.assert_called_once_with(
            policy_names=[SHORT + '-nfs'])
        self.client.get_directory_exports.assert_called_once_with(
            directory_names=[DIR])
        self.client.get_directory_snapshots.assert_called_once_with(
            source_names=[DIR])
        self.client.get_directories_performance.assert_called_once_with(
            names=[DIR])
        self.client.get_arrays.assert_called_once_with()
        self.client.get_controllers.assert_called_once_with()
        self.client.get_arrays_space.assert_not_called()

        self.assertEqual(DIR, info['name'])
        self.assertEqual(SHORT, info['directory_name'])
        self.assertEqual(SHARE_ID, info['share_id'])
        self.assertEqual(10.0, info['used'])
        self.assertEqual(100.0, info['virtual'])
        self.assertEqual(1.0, info['snapshots'])
        self.assertEqual('3.00 to 1', info['data_reduction'])
        self.assertEqual(CREATED, info['created'])
        # Quota in MiB.
        self.assertEqual(50.0, info['quota_limit'])
        self.assertEqual(6.0, info['quota_usage'])
        self.assertEqual(12, info['percentage_used'])
        self.assertTrue(info['quota_enforced'])
        self.assertEqual([
            {'client': '10.0.0.5', 'permission': 'rw',
             'access': 'no-root-squash', 'nfs_version': ['nfsv3', 'nfsv4']},
            {'client': '10.0.0.0/24', 'permission': 'ro',
             'access': 'root-squash', 'nfs_version': []},
        ], info['nfs_rules'])
        self.assertEqual([{'export_name': SHORT, 'enabled': True,
                           'policy': SHORT + '-nfs'}], info['exports'])
        # private, other-client, destroyed and .copy. snapshots excluded.
        self.assertEqual(2, info['snapshot_count'])
        self.assertEqual([SNAP2, SNAP1],
                         [s['suffix'] for s in info['snapshot_list']])
        self.assertEqual(
            datetime.datetime(1970, 1, 1, 0, 0, 0, 200000,
                              tzinfo=datetime.timezone.utc),
            info['snapshot_list'][0]['created'])
        self.assertEqual(100, info['reads_per_sec'])
        self.assertEqual(50, info['writes_per_sec'])
        self.assertEqual(2.0, info['output_per_sec'])
        self.assertEqual(0.5, info['input_per_sec'])
        self.assertEqual(300, info['usec_per_read_op'])
        self.assertEqual(400, info['usec_per_write_op'])
        self.assertEqual('fa-lab', info['array_name'])
        self.assertEqual('6.10.6', info['version'])
        self.assertEqual('FA-X50R2', info['model'])
        self.assertEqual('192.0.2.10', info['target'])
        self.assertEqual('openstack', info['parent_fs'])
        self.assertEqual('flasharray-files', info['backend_name'])

    @override_settings(PURE_FLASHARRAY_FILES=[
        dict(FILES[0], parent_fs='tenant-fs')])
    def test_get_directory_info_custom_parent_fs(self):
        name = 'tenant-fs:' + SHORT
        set_directories(self.client,
                        by_name={name: _dir(SHORT, parent='tenant-fs')})
        info = self.api.get_directory_info('flasharray-files', SHARE_ID,
                                           detailed=False)
        self.client.get_directories.assert_called_once_with(names=[name])
        self.client.get_directory_quotas.assert_called_once_with(
            directory_names=[name], policy_names=[SHORT + '-quota'])
        self.client.get_policies_nfs_client_rules.assert_called_once_with(
            policy_names=[SHORT + '-nfs'])
        self.client.get_directories_performance.assert_not_called()
        self.assertEqual(name, info['name'])
        self.assertEqual('tenant-fs', info['parent_fs'])
        self.assertNotIn('reads_per_sec', info)

    def test_get_directory_info_quota_pinned_to_driver_policy(self):
        # The array lists one quota item per policy attached to the
        # directory; the lookup asks for the driver's policy so another
        # policy's limit (listed first by the array) is never shown.
        foreign = types.SimpleNamespace(
            usage=6 * MIB, quota_limit=900 * MIB, enforced=False,
            percentage_used=1, rule_name='rule-1',
            policy=types.SimpleNamespace(name='ops-quota'))
        driver = types.SimpleNamespace(
            usage=6 * MIB, quota_limit=50 * MIB, enforced=True,
            percentage_used=12, rule_name='rule-1',
            policy=types.SimpleNamespace(name=SHORT + '-quota'))

        def respond(**kwargs):
            if kwargs.get('policy_names') == [SHORT + '-quota']:
                return _resp([driver])
            return _resp([foreign, driver])

        self.client.get_directory_quotas.side_effect = respond
        info = self.api.get_directory_info('flasharray-files', SHARE_ID)
        self.client.get_directory_quotas.assert_called_once_with(
            directory_names=[DIR], policy_names=[SHORT + '-quota'])
        self.assertEqual(50.0, info['quota_limit'])
        self.assertEqual(12, info['percentage_used'])
        self.assertTrue(info['quota_enforced'])

    def test_get_directory_info_without_quota_or_policy(self):
        # Neither policy was ever created: HTTP 400 "Policy does not exist."
        _fresh(self.client.get_directory_quotas, status=400,
               errors=[types.SimpleNamespace(
                   message='Policy does not exist.', context=None)])
        _fresh(self.client.get_policies_nfs_client_rules, status=400,
               errors=[types.SimpleNamespace(
                   message='Policy does not exist.', context=None)])
        _fresh(self.client.get_directory_exports, [])
        _fresh(self.client.get_directory_snapshots, [])
        _fresh(self.client.get_directories_performance, [])

        info = self.api.get_directory_info('flasharray-files', SHARE_ID)

        self.assertIsNone(info['quota_limit'])
        self.assertEqual(0.0, info['quota_usage'])
        self.assertIsNone(info['percentage_used'])
        self.assertFalse(info['quota_enforced'])
        self.assertEqual([], info['nfs_rules'])
        self.assertEqual([], info['exports'])
        self.assertEqual(0, info['snapshot_count'])
        self.assertEqual([], info['snapshot_list'])
        self.assertEqual(0, info['reads_per_sec'])
        self.assertEqual(0.0, info['output_per_sec'])
        self.assertEqual(DIR, info['name'])

    def test_get_directory_info_snapshot_list_is_capped(self):
        snaps = [_snap('f0000000-0000-0000-0000-%012d' % n, created=n)
                 for n in range(60)]
        _fresh(self.client.get_directory_snapshots, snaps)
        info = self.api.get_directory_info('flasharray-files', SHARE_ID)
        self.assertEqual(60, info['snapshot_count'])
        self.assertEqual(pure_fa_files.MAX_SNAPSHOTS,
                         len(info['snapshot_list']))
        self.assertEqual('f0000000-0000-0000-0000-%012d' % 59,
                         info['snapshot_list'][0]['suffix'])

    def test_get_directory_info_not_found(self):
        # HTTP 400 "does not exist" and an empty 200 both mean missing.
        self.assertIsNone(
            self.api.get_directory_info('flasharray-files', SHARE_ID2))
        self.client.get_directories.assert_called_once_with(
            names=['openstack:share-%s-manila' % SHARE_ID2])
        self.client.get_directory_quotas.assert_not_called()
        self.client.get_directory_snapshots.assert_not_called()
        self.client.get_directories_performance.assert_not_called()

        self.client.get_directories.side_effect = lambda **k: _resp([])
        self.assertIsNone(
            self.api.get_directory_info('flasharray-files', SHARE_ID))
        self.client.get_directory_quotas.assert_not_called()

    def test_get_directory_info_destroyed_is_none(self):
        set_directories(self.client,
                        by_name={DIR: _dir(SHORT, destroyed=True)})
        self.assertIsNone(
            self.api.get_directory_info('flasharray-files', SHARE_ID))
        self.client.get_directory_quotas.assert_not_called()

    def test_get_directory_info_array_errors_raise(self):
        # Anything but HTTP 400 is the array failing (bad token, access
        # denied, server error, TLS), not a missing directory.
        for status in (401, 403, 500, 0):
            with self.subTest(status=status):
                self.client.get_directories.side_effect = (
                    lambda status=status, **k: _resp(status=status, errors=[
                        types.SimpleNamespace(message='denied',
                                              context=None)]))
                with self.assertRaises(registry.ArrayUnavailable) as ctx:
                    self.api.get_directory_info('flasharray-files', SHARE_ID)
                self.assertEqual(
                    'flasharray-files: HTTP %s: denied' % status,
                    str(ctx.exception))
        self.client.get_directory_quotas.assert_not_called()
        self.client.get_arrays.assert_not_called()

    def test_get_directory_info_unavailable(self):
        self.build.side_effect = RuntimeError('down')
        with self.assertRaises(registry.ArrayUnavailable) as ctx:
            self.api.get_directory_info('flasharray-files', SHARE_ID)
        self.assertIn('down', str(ctx.exception))
        self.assertIn('192.0.2.10', str(ctx.exception))
        self.client.get_directories.assert_not_called()
        with self.assertRaises(registry.ArrayUnavailable) as ctx:
            self.api.get_directory_info('nope', SHARE_ID)
        self.assertEqual('Not in config', str(ctx.exception))

    def test_get_directory_info_sdk_exception(self):
        # A failure after the directory was found is still an array
        # failure, never "not found".
        self.client.get_directory_quotas.side_effect = RuntimeError('socket')
        with self.assertRaises(registry.ArrayUnavailable) as ctx:
            self.api.get_directory_info('flasharray-files', SHARE_ID)
        self.assertEqual('flasharray-files: socket', str(ctx.exception))
        self.assertIsInstance(ctx.exception.__cause__, RuntimeError)

    def test_is_manila_snapshot(self):
        self.assertTrue(pure_fa_files.is_manila_snapshot(_snap(SNAP1)))
        self.assertFalse(pure_fa_files.is_manila_snapshot(_snap('private')))
        self.assertFalse(pure_fa_files.is_manila_snapshot(
            _snap(SNAP1, client_name='other')))
        self.assertFalse(pure_fa_files.is_manila_snapshot(
            _snap(SNAP1, destroyed=True)))
        self.assertFalse(pure_fa_files.is_manila_snapshot(
            _snap('1', name=DIR + '.openstack.x.copy.1')))
        self.assertFalse(pure_fa_files.is_manila_snapshot(None))

    def test_snapshot_suffix_parsed_from_name(self):
        # Purity//FA 6.10 returns directory snapshots without a ``suffix``
        # field; the baseline must still be recognised from its name.
        private = _snap(None, name=DIR + '.openstack.private')
        user = _snap(None, name=DIR + '.openstack.' + SNAP1)
        self.assertEqual('private', pure_fa_files.snapshot_suffix(private))
        self.assertEqual(SNAP1, pure_fa_files.snapshot_suffix(user))
        self.assertFalse(pure_fa_files.is_manila_snapshot(private))
        self.assertTrue(pure_fa_files.is_manila_snapshot(user))
        # An explicit suffix wins over the name; no marker gives ''.
        self.assertEqual(SNAP2, pure_fa_files.snapshot_suffix(_snap(SNAP2)))
        self.assertEqual('', pure_fa_files.snapshot_suffix(
            _snap(None, name='weird')))
        _fresh(self.client.get_directory_snapshots, [private, user])
        count, listing = self.api._snapshots(self.client, DIR)
        self.assertEqual(1, count)
        self.assertEqual(SNAP1, listing[0]['suffix'])

    def test_directory_name(self):
        self.assertEqual(DIR, pure_fa_files.directory_name('openstack',
                                                           SHARE_ID))
        self.assertEqual('tenant-fs:' + SHORT,
                         pure_fa_files.directory_name('tenant-fs', SHARE_ID))
