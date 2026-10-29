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

"""Tests for horizon_pure.api.pure_flash_blade."""

import datetime
import types
from unittest import mock

from django.test import override_settings

from openstack_dashboard.api import base
from openstack_dashboard.test import helpers as test
from urllib3 import exceptions as urllib3_exceptions

from horizon_pure.api import pure_flash_blade
from horizon_pure.api import registry


MIB = 1024 ** 2
IID1 = '11111111-2222-3333-4444-555555555555'
IID2 = '66666666-7777-8888-9999-000000000000'
IID3 = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
FS1 = 'share-%s-manila' % IID1
FS2 = 'share-%s-manila' % IID2
CREATED_MS = 1700000000000
CREATED = datetime.datetime(2023, 11, 14, 22, 13, 20,
                            tzinfo=datetime.timezone.utc)
BLADES = [
    {'mgmt_ip': '192.0.2.20', 'api_token': 'tok',
     'backend_name': 'flashblade'},
]


def _resp(items=None, status=200, total=None, token=None, errors=None):
    """A fake py-pure-client response; ``items`` is a one-shot iterator."""
    resp = types.SimpleNamespace(status_code=status)
    if status == 200:
        resp.items = iter(items or [])
        resp.total_item_count = total
        resp.continuation_token = token
    else:
        resp.errors = errors or [types.SimpleNamespace(
            message='File system does not exist.', context=None)]
    return resp


def _fresh(method, *args, **kwargs):
    """Make ``method`` return a new response (new iterator) per call."""
    method.side_effect = lambda *a, **k: _resp(*args, **kwargs)


def _space(**overrides):
    values = {'data_reduction': 2.5, 'snapshots': 3 * MIB,
              'total_physical': 40 * MIB, 'total_provisioned': 500 * MIB,
              'total_used': 40 * MIB, 'unique': 37 * MIB,
              'virtual': 100 * MIB}
    values.update(overrides)
    return types.SimpleNamespace(**values)


def _fs(name, destroyed=False, **space):
    return types.SimpleNamespace(
        name=name, created=CREATED_MS, destroyed=destroyed,
        provisioned=200 * MIB, hard_limit_enabled=True,
        snapshot_directory_enabled=True,
        nfs=types.SimpleNamespace(rules='10.0.0.0/24(rw,no_root_squash)',
                                  v3_enabled=False, v4_1_enabled=True),
        smb=types.SimpleNamespace(enabled=False),
        space=_space(**space))


def _perf():
    return types.SimpleNamespace(
        reads_per_sec=100, writes_per_sec=50,
        read_bytes_per_sec=2 * MIB, write_bytes_per_sec=512 * 1024,
        usec_per_read_op=300, usec_per_write_op=400)


def set_file_systems(client, pages=(), total=0, by_name=None):
    """Make get_file_systems answer counts, name lookups and paging.

    ``pages`` is [(items, next_token), ...]; a continuation token
    'page-N' selects pages[N]. Unknown names answer HTTP 400.
    """
    by_name = by_name or {}

    def respond(**kwargs):
        if kwargs.get('total_only'):
            return _resp([], total=total)
        if 'names' in kwargs:
            found = [by_name[n] for n in kwargs['names'] if n in by_name]
            return _resp(found) if found else _resp(status=400)
        token = kwargs.get('continuation_token')
        index = 0 if token is None else int(token.rsplit('-', 1)[1])
        items, next_token = pages[index]
        return _resp(items, token=next_token)

    client.get_file_systems.side_effect = respond


def set_snapshots(client, array_total=11, fs_total=2, names_fail=False):
    def respond(**kwargs):
        if kwargs.get('names_or_owner_names') is not None:
            if names_fail:
                return _resp(status=400)
            return _resp([], total=fs_total)
        if kwargs.get('filter'):
            return _resp([], total=fs_total)
        return _resp([], total=array_total)

    client.get_file_system_snapshots.side_effect = respond


def make_client(name='fb-lab'):
    """A Mock FlashBlade client with lab-shaped responses."""
    client = mock.Mock(name='client-%s' % name)
    _fresh(client.get_arrays, [types.SimpleNamespace(
        id='fb-uuid', name=name, version='4.5.3', os='Purity//FB',
        product_type='FlashBlade//S200')])
    _fresh(client.get_arrays_space, [types.SimpleNamespace(
        capacity=2000 * MIB, space=_space())])
    _fresh(client.get_arrays_performance, [_perf()])
    set_file_systems(client, pages=[([_fs(FS1)], None)], total=3,
                     by_name={FS1: _fs(FS1)})
    set_snapshots(client)
    _fresh(client.get_file_systems_performance, [_perf()])
    return client


@override_settings(PURE_FLASHBLADES=BLADES)
class FlashBladeAPITests(test.TestCase):

    def setUp(self):
        super().setUp()
        registry.reset()
        self.addCleanup(registry.reset)
        self.client = make_client()
        patcher = mock.patch.object(registry, '_build_client',
                                    return_value=self.client)
        self.build = patcher.start()
        self.addCleanup(patcher.stop)
        self.api = pure_flash_blade.FlashBladeAPI()

    def test_construction_builds_nothing(self):
        pure_flash_blade.FlashBladeAPI()
        self.assertEqual(['flashblade'], self.api.get_backend_list())
        self.build.assert_not_called()

    def test_get_array_info_detailed(self):
        info = self.api.get_array_info('flashblade', detailed=True)

        self.build.assert_called_once()
        self.assertEqual('flashblade', self.build.call_args[0][0].backend_name)
        self.client.get_arrays.assert_called_once_with()
        self.client.get_arrays_space.assert_called_once_with()
        self.client.get_arrays_performance.assert_called_once_with()
        # Counts leave out objects pending eradication.
        self.client.get_file_systems.assert_called_once_with(
            destroyed=False, total_only=True)
        self.client.get_file_system_snapshots.assert_called_once_with(
            destroyed=False, total_only=True)

        self.assertIsInstance(info, base.APIDictWrapper)
        self.assertEqual('Connected', info.status)
        self.assertEqual('fb-uuid', info.id)
        self.assertEqual('fb-lab', info.array_name)
        self.assertEqual('4.5.3', info.version)
        self.assertEqual('FlashBlade//S200', info.model)
        self.assertEqual('flashblade', info.backend_id)
        self.assertEqual('flashblade', info.backend_name)
        self.assertEqual('192.0.2.20', info.target)
        # Sizes are MiB.
        self.assertEqual(2000.0, info.capacity)
        self.assertEqual(40.0, info.total)
        self.assertEqual(37.0, info.unique)
        self.assertEqual(3.0, info.snapshots)
        self.assertEqual(100.0, info.virtual)
        self.assertEqual(500.0, info.total_provisioned)
        self.assertEqual('2.50 to 1', info.data_reduction)
        self.assertEqual(3, info.file_system_count)
        self.assertEqual(11, info.snapshot_count)
        # IOPS stay IOPS; bandwidth in MiB/s.
        self.assertEqual(100, info.reads_per_sec)
        self.assertEqual(50, info.writes_per_sec)
        self.assertEqual(2.0, info.output_per_sec)
        self.assertEqual(0.5, info.input_per_sec)
        self.assertEqual(300, info.usec_per_read_op)
        self.assertEqual(400, info.usec_per_write_op)

    def test_get_array_info_not_detailed_skips_performance(self):
        info = self.api.get_array_info('flashblade')
        self.client.get_arrays_performance.assert_not_called()
        self.assertEqual('Connected', info.status)
        self.assertNotIn('reads_per_sec', info.to_dict())
        self.assertEqual(3, info.file_system_count)

    def test_get_array_info_error_status_400(self):
        _fresh(self.client.get_arrays, status=400,
               errors=[types.SimpleNamespace(message='Bad request',
                                             context='arrays')])
        info = self.api.get_array_info('flashblade', detailed=True)

        self.client.get_arrays.assert_called_once_with()
        self.client.get_arrays_space.assert_not_called()
        self.client.get_file_systems.assert_not_called()
        self.assertTrue(info.status.startswith('Error: '), info.status)
        self.assertIn('HTTP 400: Bad request (arrays)', info.status)
        self.assertEqual('Unknown', info.array_name)
        self.assertEqual('Unknown', info.model)
        self.assertEqual(0, info.capacity)
        self.assertEqual(0, info.total)
        self.assertEqual('1.00 to 1', info.data_reduction)
        self.assertEqual(0, info.file_system_count)
        self.assertEqual(0, info.snapshot_count)
        self.assertEqual('flashblade', info.backend_id)
        self.assertEqual('192.0.2.20', info.target)

    def test_get_array_info_space_failure_degrades(self):
        _fresh(self.client.get_arrays_space, status=400)
        self.client.get_file_system_snapshots.side_effect = RuntimeError('x')
        info = self.api.get_array_info('flashblade')
        self.assertEqual('Connected', info.status)
        self.assertEqual('fb-lab', info.array_name)
        self.assertEqual(0, info.capacity)
        self.assertEqual('1.00 to 1', info.data_reduction)
        self.assertEqual(3, info.file_system_count)
        self.assertEqual(0, info.snapshot_count)

    def test_get_array_info_unavailable_array(self):
        self.build.side_effect = RuntimeError('connection refused')
        info = self.api.get_array_info('flashblade')
        self.assertTrue(info.status.startswith('Error: '), info.status)
        self.assertIn('connection refused', info.status)
        self.assertIn('192.0.2.20', info.status)
        self.assertEqual('192.0.2.20', info.target)
        self.assertEqual('flashblade', info.backend_id)
        self.assertEqual(0, info.file_system_count)
        # The failure is cached: no second construction attempt.
        self.api.get_array_info('flashblade')
        self.assertEqual(1, self.build.call_count)

    def test_get_array_info_transport_failure_evicts_client(self):
        # The array stopped answering after its client was built: the
        # row says so and the next call fails fast from the registry.
        self.client.get_arrays.side_effect = (
            urllib3_exceptions.ReadTimeoutError(None, '/api/2.x/arrays',
                                                'Read timed out'))
        info = self.api.get_array_info('flashblade')
        self.assertIn('Error: Unable to contact flashblade (192.0.2.20)',
                      info.status)
        self.assertIn('Read timed out', info.status)
        self.client.get_arrays.assert_called_once_with()
        self.client.get_arrays_space.assert_not_called()

        info = self.api.get_array_info('flashblade')
        self.assertIn('Unable to contact flashblade', info.status)
        self.assertEqual(1, self.client.get_arrays.call_count)
        self.assertEqual(1, self.build.call_count)

    def test_unknown_backend(self):
        info = self.api.get_array_info('nope')
        self.assertEqual('Error: Not in config', info.status)
        self.assertEqual('nope', info.target)
        self.assertEqual('nope', info.backend_id)
        self.build.assert_not_called()
        # A FlashArray Files backend name is not a FlashBlade backend.
        with override_settings(PURE_FLASHARRAY_FILES=[
                {'san_ip': '192.0.2.10', 'api_token': 'tok',
                 'backend_name': 'flasharray-files'}]):
            info = self.api.get_array_info('flasharray-files')
        self.assertEqual('Error: Not in config', info.status)
        self.build.assert_not_called()

    def test_get_total_stats_dedupes_by_target(self):
        conf = [
            {'mgmt_ip': '192.0.2.20', 'api_token': 'tok',
             'backend_name': 'flashblade'},
            {'mgmt_ip': '192.0.2.20', 'api_token': 'tok',
             'backend_name': 'flashblade-two'},
            {'mgmt_ip': '192.0.2.21', 'api_token': 'tok',
             'backend_name': 'flashblade-b'},
        ]
        second = make_client('fb-two')
        set_file_systems(second, total=5)
        set_snapshots(second, array_total=7)
        self.build.side_effect = (
            lambda entry: second if entry.target == '192.0.2.21'
            else self.client)
        with override_settings(PURE_FLASHBLADES=conf):
            self.assertEqual(['flashblade', 'flashblade-two', 'flashblade-b'],
                             self.api.get_backend_list())
            stats = self.api.get_total_stats()

        self.assertEqual({'total_used': 80.0, 'total_available': 4000.0,
                          'total_file_system_count': 8,
                          'total_snapshot_count': 18}, stats)
        self.assertEqual(1, self.client.get_arrays_space.call_count)
        self.assertEqual(1, second.get_arrays_space.call_count)
        self.assertEqual(2, self.build.call_count)

    def test_get_total_stats_unconfigured(self):
        with override_settings(PURE_FLASHBLADES=[]):
            self.assertEqual({}, self.api.get_total_stats())
        self.build.assert_not_called()

    def test_list_manila_file_systems_paginates_and_filters(self):
        page1 = [_fs(FS1), _fs('other-fs'), _fs(FS2, destroyed=True)]
        page2 = [_fs('share-notauuid-manila'),
                 _fs('manila-%s-manila' % IID3),
                 _fs('share-%s' % IID3),
                 _fs('share-%s-manila' % IID3, virtual=7 * MIB)]
        set_file_systems(self.client, pages=[(page1, 'page-1'),
                                             (page2, None)])

        result = self.api.list_manila_file_systems('flashblade')

        self.assertEqual(
            [mock.call(limit=pure_flash_blade.PAGE_LIMIT, destroyed=False),
             mock.call(limit=pure_flash_blade.PAGE_LIMIT, destroyed=False,
                       continuation_token='page-1')],
            self.client.get_file_systems.call_args_list)
        self.assertEqual([FS1, 'share-%s-manila' % IID3],
                         [fs['name'] for fs in result])
        first = result[0]
        self.assertEqual(IID1, first['share_instance_id'])
        self.assertEqual(200.0, first['provisioned'])
        self.assertEqual(100.0, first['used'])
        self.assertEqual(40.0, first['total_physical'])
        self.assertEqual(37.0, first['unique'])
        self.assertEqual(3.0, first['snapshots'])
        self.assertEqual('2.50 to 1', first['data_reduction'])
        self.assertEqual('10.0.0.0/24(rw,no_root_squash)', first['nfs_rules'])
        self.assertTrue(first['hard_limit'])
        self.assertEqual(CREATED, first['created'])
        self.assertFalse(first['destroyed'])
        self.assertEqual(IID3, result[1]['share_instance_id'])
        self.assertEqual(7.0, result[1]['used'])

    @override_settings(PURE_MANILA_SHARE_NAME_TEMPLATE='manila-%s')
    def test_list_manila_file_systems_custom_template(self):
        custom = 'manila-%s-manila' % IID3
        set_file_systems(self.client, pages=[([_fs(FS1), _fs(custom)], None)])
        result = self.api.list_manila_file_systems('flashblade')
        self.assertEqual([custom], [fs['name'] for fs in result])
        self.assertEqual(IID3, result[0]['share_instance_id'])

    def test_list_manila_file_systems_errors_are_empty(self):
        set_file_systems(self.client, pages=[([], None)])
        self.assertEqual([], self.api.list_manila_file_systems('flashblade'))

        self.client.get_file_systems.side_effect = lambda **k: _resp(
            status=400)
        self.assertEqual([], self.api.list_manila_file_systems('flashblade'))

        self.client.get_file_systems.side_effect = RuntimeError('socket')
        self.assertEqual([], self.api.list_manila_file_systems('flashblade'))

        self.assertEqual([], self.api.list_manila_file_systems('nope'))

    def test_list_manila_file_systems_unavailable(self):
        self.build.side_effect = RuntimeError('down')
        self.assertEqual([], self.api.list_manila_file_systems('flashblade'))
        self.client.get_file_systems.assert_not_called()

    def test_get_file_system_info(self):
        info = self.api.get_file_system_info('flashblade', FS1)

        self.client.get_file_systems.assert_called_once_with(names=[FS1])
        self.client.get_file_system_snapshots.assert_called_once_with(
            names_or_owner_names=[FS1], destroyed=False, total_only=True)
        self.client.get_file_systems_performance.assert_called_once_with(
            names=[FS1])
        self.client.get_arrays.assert_called_once_with()
        self.client.get_arrays_space.assert_not_called()

        self.assertEqual(FS1, info['name'])
        self.assertEqual(IID1, info['share_instance_id'])
        self.assertEqual(200.0, info['provisioned'])
        self.assertEqual(100.0, info['used'])
        self.assertEqual(40.0, info['total_physical'])
        self.assertEqual('2.50 to 1', info['data_reduction'])
        self.assertEqual(2, info['snapshot_count'])
        self.assertFalse(info['nfs_v3'])
        self.assertTrue(info['nfs_v41'])
        self.assertFalse(info['smb_enabled'])
        self.assertTrue(info['hard_limit'])
        self.assertEqual(CREATED, info['created'])
        self.assertEqual(100, info['reads_per_sec'])
        self.assertEqual(50, info['writes_per_sec'])
        self.assertEqual(2.0, info['output_per_sec'])
        self.assertEqual(0.5, info['input_per_sec'])
        self.assertEqual(300, info['usec_per_read_op'])
        self.assertEqual(400, info['usec_per_write_op'])
        self.assertEqual('fb-lab', info['array_name'])
        self.assertEqual('4.5.3', info['version'])
        self.assertEqual('FlashBlade//S200', info['model'])
        self.assertEqual('192.0.2.20', info['target'])
        self.assertEqual('flashblade', info['backend_name'])

    def test_get_file_system_info_not_detailed(self):
        info = self.api.get_file_system_info('flashblade', FS1,
                                             detailed=False)
        self.client.get_file_systems_performance.assert_not_called()
        self.assertNotIn('reads_per_sec', info)
        self.assertEqual(2, info['snapshot_count'])

    def test_get_file_system_info_snapshot_count_filter_fallback(self):
        set_snapshots(self.client, fs_total=4, names_fail=True)
        info = self.api.get_file_system_info('flashblade', FS1)
        self.assertEqual(
            [mock.call(names_or_owner_names=[FS1], destroyed=False,
                       total_only=True),
             mock.call(filter="source.name='%s'" % FS1, destroyed=False,
                       total_only=True)],
            self.client.get_file_system_snapshots.call_args_list)
        self.assertEqual(4, info['snapshot_count'])

    def test_get_file_system_info_idle_performance_is_zero(self):
        _fresh(self.client.get_file_systems_performance, [])
        info = self.api.get_file_system_info('flashblade', FS1)
        self.assertEqual(0, info['reads_per_sec'])
        self.assertEqual(0.0, info['output_per_sec'])
        self.assertEqual(0, info['usec_per_write_op'])
        self.assertEqual(FS1, info['name'])

    def test_get_file_system_info_identity_failure_degrades(self):
        # /arrays failing right after the file system was read must not
        # turn an existing file system into "not found".
        _fresh(self.client.get_arrays, status=503,
               errors=[types.SimpleNamespace(message='Service unavailable',
                                             context=None)])
        with self.assertLogs('horizon_pure.api.pure_flash_blade',
                             level='WARNING') as logs:
            info = self.api.get_file_system_info('flashblade', FS1)
        self.client.get_arrays.assert_called_once_with()
        self.assertIn('HTTP 503: Service unavailable', logs.output[0])
        self.assertEqual(FS1, info['name'])
        self.assertEqual(2, info['snapshot_count'])
        self.assertEqual(100, info['reads_per_sec'])
        self.assertEqual('Unknown', info['array_name'])
        self.assertEqual('Unknown', info['version'])
        self.assertEqual('Unknown', info['model'])
        self.assertEqual('192.0.2.20', info['target'])
        self.assertEqual('flashblade', info['backend_name'])

    def test_get_file_system_info_not_found(self):
        # HTTP 400 "does not exist" and an empty 200 both mean missing.
        self.assertIsNone(self.api.get_file_system_info('flashblade', FS2))
        self.client.get_file_systems.assert_called_once_with(names=[FS2])
        self.client.get_file_system_snapshots.assert_not_called()
        self.client.get_file_systems_performance.assert_not_called()

        self.client.get_file_systems.side_effect = lambda **k: _resp([])
        self.assertIsNone(self.api.get_file_system_info('flashblade', FS1))
        self.client.get_file_system_snapshots.assert_not_called()

    def test_get_file_system_info_destroyed_is_none(self):
        set_file_systems(self.client, by_name={FS2: _fs(FS2, destroyed=True)})
        self.assertIsNone(self.api.get_file_system_info('flashblade', FS2))
        self.client.get_file_system_snapshots.assert_not_called()

    def test_get_file_system_info_array_errors_raise(self):
        # Anything but HTTP 400 is the array failing (bad token, access
        # denied, server error, TLS), not a missing file system.
        for status in (401, 403, 500, 0):
            with self.subTest(status=status):
                self.client.get_file_systems.side_effect = (
                    lambda status=status, **k: _resp(status=status, errors=[
                        types.SimpleNamespace(message='denied',
                                              context=None)]))
                with self.assertRaises(registry.ArrayUnavailable) as ctx:
                    self.api.get_file_system_info('flashblade', FS1)
                self.assertEqual('flashblade: HTTP %s: denied' % status,
                                 str(ctx.exception))
        self.client.get_file_system_snapshots.assert_not_called()
        self.client.get_arrays.assert_not_called()

    def test_get_file_system_info_unavailable(self):
        self.build.side_effect = RuntimeError('down')
        with self.assertRaises(registry.ArrayUnavailable) as ctx:
            self.api.get_file_system_info('flashblade', FS1)
        self.assertIn('down', str(ctx.exception))
        self.assertIn('192.0.2.20', str(ctx.exception))
        self.client.get_file_systems.assert_not_called()
        with self.assertRaises(registry.ArrayUnavailable) as ctx:
            self.api.get_file_system_info('nope', FS1)
        self.assertEqual('Not in config', str(ctx.exception))

    def test_get_file_system_info_sdk_exception(self):
        self.client.get_file_systems.side_effect = RuntimeError('socket')
        with self.assertRaises(registry.ArrayUnavailable) as ctx:
            self.api.get_file_system_info('flashblade', FS1)
        self.assertEqual('flashblade: socket', str(ctx.exception))
        self.assertIsInstance(ctx.exception.__cause__, RuntimeError)
