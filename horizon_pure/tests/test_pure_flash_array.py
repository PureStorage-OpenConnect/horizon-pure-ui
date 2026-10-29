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

"""Tests for horizon_pure.api.pure_flash_array and the admin index view."""

import types
from unittest import mock

from django.test import override_settings
from django.urls import reverse

from openstack_dashboard.api import base
from openstack_dashboard.test import helpers as test
from urllib3 import exceptions as urllib3_exceptions

from horizon_pure.api import cinder as pure_cinder_api
from horizon_pure.api import pure_flash_array
from horizon_pure.api import registry


MIB = 1024 ** 2
VOL_ID = '7f1c0b5e-1111-2222-3333-444455556666'
VOL_NAME = 'volume-%s-cinder' % VOL_ID
ARRAYS = [
    {'san_ip': '192.0.2.10', 'api_token': 'tok', 'backend_name': 'pure-iscsi'},
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
            message='Volume does not exist.', context=None)]
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


def make_client(name='fa-lab'):
    """A Mock FlashArray client with lab-shaped responses."""
    client = mock.Mock(name='client-%s' % name)
    _fresh(client.get_arrays, [types.SimpleNamespace(
        id='array-uuid', name=name, version='6.8.5',
        capacity=1000 * MIB, space=_space())])
    _fresh(client.get_arrays_space, [types.SimpleNamespace(
        capacity=1000 * MIB, space=_space())])
    _fresh(client.get_controllers, [
        types.SimpleNamespace(name='CT0', model='FA-X50R2', version='6.8.5'),
        types.SimpleNamespace(name='CT1', model='FA-X50R2', version='6.8.5'),
    ])
    _fresh(client.get_arrays_performance, [types.SimpleNamespace(
        reads_per_sec=100, writes_per_sec=50,
        read_bytes_per_sec=2 * MIB, write_bytes_per_sec=1 * MIB,
        usec_per_read_op=300, usec_per_write_op=400, queue_depth=3)])
    _fresh(client.get_volumes, [], total=7)
    _fresh(client.get_volume_snapshots, [], total=11)
    _fresh(client.get_hosts, [], total=5)
    _fresh(client.get_protection_groups, [], total=2)
    return client


def _volume_item():
    return types.SimpleNamespace(
        name=VOL_NAME,
        space=_space(total_physical=3 * MIB, unique=2 * MIB,
                     snapshots=1 * MIB, total_provisioned=10240 * MIB))


def _volume_perf():
    return types.SimpleNamespace(
        reads_per_sec=100, writes_per_sec=50,
        read_bytes_per_sec=2 * MIB, write_bytes_per_sec=512 * 1024,
        usec_per_read_op=300, usec_per_write_op=400)


class FakeVolume(object):
    """Minimal stand-in for openstack_dashboard.api.cinder.Volume."""

    def __init__(self, vol_id=VOL_ID, host=None, name='vol'):
        self.id = vol_id
        self.name = name
        if host is not None:
            setattr(self, 'os-vol-host-attr:host', host)

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'size': 10}


@override_settings(PURE_FLASHARRAYS=ARRAYS)
class FlashArrayAPITests(test.TestCase):

    def setUp(self):
        super().setUp()
        registry.reset()
        self.addCleanup(registry.reset)
        self.client = make_client()
        patcher = mock.patch.object(registry, '_build_client',
                                    return_value=self.client)
        self.build = patcher.start()
        self.addCleanup(patcher.stop)
        self.api = pure_flash_array.FlashArrayAPI()

    def test_construction_builds_nothing(self):
        pure_flash_array.FlashArrayAPI()
        self.build.assert_not_called()
        self.assertEqual(['pure-iscsi'], self.api.get_array_list())
        self.build.assert_not_called()

    def test_get_array_info_detailed(self):
        info = self.api.get_array_info('pure-iscsi', detailed=True)

        self.build.assert_called_once()
        self.assertEqual('pure-iscsi', self.build.call_args[0][0].backend_name)
        self.client.get_arrays.assert_called_once_with()
        self.client.get_arrays_performance.assert_called_once_with()
        # Controllers and space are read once and shared with the stats.
        self.client.get_controllers.assert_called_once_with()
        self.client.get_arrays_space.assert_called_once_with()
        for method in (self.client.get_volumes,
                       self.client.get_volume_snapshots,
                       self.client.get_hosts,
                       self.client.get_protection_groups):
            method.assert_called_once_with(total_item_count=True)

        self.assertIsInstance(info, base.APIDictWrapper)
        self.assertEqual('Connected', info.status)
        self.assertEqual('array-uuid', info.id)
        self.assertEqual('fa-lab', info.array_name)
        self.assertEqual('6.8.5', info.version)
        self.assertEqual('FA-X50R2', info.model)
        self.assertEqual('pure-iscsi', info.cinder_id)
        self.assertEqual('pure-iscsi', info.cinder_name)
        self.assertEqual('192.0.2.10', info.target)
        # Sizes are MiB.
        self.assertEqual(1000.0, info.capacity)
        self.assertEqual(10.0, info.total)
        self.assertEqual(1.0, info.snapshots)
        self.assertEqual(9.0, info.unique)
        self.assertEqual(9.0, info.volumes)
        self.assertEqual(10.0, info.total_used)
        self.assertEqual(1000.0, info.total_available)
        # Ratios are strings.
        self.assertEqual('3.00 to 1', info.data_reduction)
        self.assertEqual('4.00 to 1', info.thin_provisioning)
        self.assertEqual('12.00 to 1', info.total_reduction)
        # Performance: IOPS unchanged, bandwidth in MiB/s.
        self.assertEqual(100, info.reads_per_sec)
        self.assertEqual(50, info.writes_per_sec)
        self.assertEqual(2.0, info.output_per_sec)
        self.assertEqual(1.0, info.input_per_sec)
        self.assertEqual(300, info.usec_per_read_op)
        self.assertEqual(400, info.usec_per_write_op)
        self.assertEqual(3, info.queue_depth)
        # Counts and limits (X50 at 6.8.5).
        self.assertEqual(7, info.total_volume_count)
        self.assertEqual(11, info.total_snapshot_count)
        self.assertEqual(5, info.total_host_count)
        self.assertEqual(2, info.total_pgroup_count)
        self.assertEqual(10000, info.available_volume_count)
        self.assertEqual(50000, info.available_snapshot_count)
        self.assertEqual(500, info.available_host_count)
        self.assertEqual(250, info.available_pgroup_count)

    def test_get_array_info_not_detailed_skips_performance(self):
        info = self.api.get_array_info('pure-iscsi')
        self.client.get_arrays_performance.assert_not_called()
        self.client.get_controllers.assert_called_once_with()
        self.client.get_arrays_space.assert_called_once_with()
        self.assertEqual('Connected', info.status)
        self.assertEqual(10.0, info.total_used)
        self.assertEqual(7, info.total_volume_count)
        self.assertNotIn('output_per_sec', info.to_dict())
        self.assertNotIn('reads_per_sec', info.to_dict())

    def test_get_array_info_error_status_400(self):
        _fresh(self.client.get_arrays, status=400,
               errors=[types.SimpleNamespace(message='Bad request',
                                             context='arrays')])
        info = self.api.get_array_info('pure-iscsi', detailed=True)

        self.client.get_arrays.assert_called_once_with()
        self.client.get_arrays_performance.assert_not_called()
        self.assertTrue(info.status.startswith('Error: '), info.status)
        self.assertIn('400', info.status)
        self.assertIn('Bad request', info.status)
        self.assertEqual('Unknown', info.array_name)
        self.assertEqual('Unknown', info.version)
        self.assertEqual(0, info.capacity)
        self.assertEqual(0, info.total)
        self.assertEqual('1.00 to 1', info.data_reduction)
        self.assertEqual(0, info.total_volume_count)
        self.assertEqual(0, info.available_volume_count)
        self.assertEqual('pure-iscsi', info.cinder_id)
        self.assertEqual('192.0.2.10', info.target)

    def test_get_array_info_unavailable_array(self):
        self.build.side_effect = RuntimeError('connection refused')
        info = self.api.get_array_info('pure-iscsi')
        self.assertTrue(info.status.startswith('Error: '), info.status)
        self.assertIn('connection refused', info.status)
        self.assertEqual('192.0.2.10', info.target)
        self.assertEqual('pure-iscsi', info.cinder_id)
        self.assertEqual(0, info.total_volume_count)

        # The failure is cached: no second construction attempt.
        self.api.get_array_info('pure-iscsi')
        self.assertEqual(1, self.build.call_count)
        self.assertEqual(['pure-iscsi'], self.api.get_array_list())

    def test_transport_failure_gives_error_row_and_evicts_client(self):
        # The array stopped answering after its client was built: the row
        # names the failure, and the summary on the same page fails fast
        # from the registry instead of paying the timeout again.
        self.client.get_arrays.side_effect = urllib3_exceptions.MaxRetryError(
            None, '/api/2.x/arrays', reason='hung')
        info = self.api.get_array_info('pure-iscsi')
        self.assertIn('Error: Unable to contact pure-iscsi (192.0.2.10)',
                      info.status)
        self.assertEqual(0, info.total_volume_count)
        self.client.get_controllers.assert_not_called()

        stats = self.api.get_total_stats()
        self.assertEqual(0, stats['total_volume_count'])
        self.client.get_controllers.assert_not_called()
        self.assertEqual(1, self.client.get_arrays.call_count)
        self.assertEqual(1, self.build.call_count)

    def test_unknown_backend_is_error_state_array(self):
        array = self.api._get_array('nope')
        self.assertIsInstance(array, pure_flash_array.ErrorStateArray)
        self.assertEqual('nope', array.array_id)
        self.assertEqual('nope', array.target)
        self.assertEqual('Not in config', array.error)

        info = self.api.get_array_info('nope')
        self.assertEqual('Error: Not in config', info.status)
        self.assertEqual('nope', info.target)
        self.assertEqual('nope', info.cinder_id)
        self.assertEqual(0, info.total_used)
        self.build.assert_not_called()

    def test_get_array_stats_tolerates_sdk_exception(self):
        self.client.get_volumes.side_effect = RuntimeError('socket closed')
        stats = self.api.get_array_stats('pure-iscsi')
        self.assertEqual(10000, stats['available_volume_count'])
        self.assertEqual(0, stats['total_volume_count'])
        self.assertEqual(0, stats['total_used'])

    def test_get_total_stats_dedupes_by_target(self):
        conf = [
            {'san_ip': '192.0.2.10', 'api_token': 'tok',
             'backend_name': 'pure-iscsi'},
            {'san_ip': '192.0.2.10', 'api_token': 'tok',
             'backend_name': 'pure-fc'},
            {'san_ip': '192.0.2.11', 'api_token': 'tok',
             'backend_name': 'pure-nvme'},
        ]
        second = make_client('fa-two')
        self.build.side_effect = (
            lambda entry: second if entry.target == '192.0.2.11'
            else self.client)
        with override_settings(PURE_FLASHARRAYS=conf):
            self.assertEqual(['pure-iscsi', 'pure-fc', 'pure-nvme'],
                             self.api.get_array_list())
            stats = self.api.get_total_stats()

        # Two distinct arrays, not three backends.
        self.assertEqual(14, stats['total_volume_count'])
        self.assertEqual(22, stats['total_snapshot_count'])
        self.assertEqual(20.0, stats['total_used'])
        self.assertEqual(2000.0, stats['total_available'])
        self.assertEqual(20000, stats['available_volume_count'])
        self.assertEqual(1, self.client.get_arrays_space.call_count)
        self.assertEqual(1, second.get_arrays_space.call_count)
        self.assertEqual(2, self.build.call_count)

    def test_get_total_stats_unconfigured(self):
        with override_settings(PURE_FLASHARRAYS=[]):
            self.assertEqual({}, self.api.get_total_stats())
        self.build.assert_not_called()

    def test_volume_stats_units(self):
        _fresh(self.client.get_volumes, [_volume_item()])
        _fresh(self.client.get_volumes_performance, [_volume_perf()])

        stats = self.api._get_volume_stats(self.client, VOL_ID)

        self.client.get_volumes.assert_called_once_with(names=[VOL_NAME])
        self.client.get_volumes_performance.assert_called_once_with(
            names=[VOL_NAME])
        # IOPS stay IOPS; bandwidth comes from *_bytes_per_sec in MiB/s.
        self.assertEqual(100, stats['reads_per_sec'])
        self.assertEqual(50, stats['writes_per_sec'])
        self.assertEqual(2.0, stats['output_per_sec'])
        self.assertEqual(0.5, stats['input_per_sec'])
        self.assertEqual(300, stats['usec_per_read_op'])
        self.assertEqual(400, stats['usec_per_write_op'])
        # Sizes in MiB; 'total' is the physical footprint.
        self.assertEqual(3.0, stats['total'])
        self.assertEqual(1.0, stats['snapshots'])
        self.assertEqual(2.0, stats['volumes'])
        # Volume ratios stay numeric for floatformat.
        self.assertEqual(3.0, stats['data_reduction'])
        self.assertEqual(4.0, stats['thin_provisioning'])
        self.assertEqual(12.0, stats['total_reduction'])

    def test_volume_stats_pod_fallback(self):
        self.client.get_volumes.side_effect = [_resp(status=400),
                                               _resp([_volume_item()])]
        _fresh(self.client.get_volumes_performance, [_volume_perf()])

        stats = self.api._get_volume_stats(self.client, VOL_ID)

        self.assertEqual([mock.call(names=[VOL_NAME]),
                          mock.call(names=['*::' + VOL_NAME])],
                         self.client.get_volumes.call_args_list)
        self.client.get_volumes_performance.assert_called_once_with(
            names=['*::' + VOL_NAME])
        self.assertEqual(3.0, stats['total'])

    def test_volume_stats_missing_performance_is_zero(self):
        _fresh(self.client.get_volumes, [_volume_item()])
        _fresh(self.client.get_volumes_performance, status=400)
        stats = self.api._get_volume_stats(self.client, VOL_ID)
        self.assertEqual(0, stats['reads_per_sec'])
        self.assertEqual(0.0, stats['output_per_sec'])
        self.assertEqual(3.0, stats['total'])

    def test_volume_stats_not_found_raises(self):
        _fresh(self.client.get_volumes, status=400)
        with self.assertRaises(LookupError) as ctx:
            self.api._get_volume_stats(self.client, VOL_ID)
        self.assertIn(VOL_ID, str(ctx.exception))
        self.assertIn('400', str(ctx.exception))
        self.assertEqual(2, self.client.get_volumes.call_count)
        self.client.get_volumes_performance.assert_not_called()

    def test_get_volume_info_admin_fast_path(self):
        _fresh(self.client.get_volumes, [_volume_item()])
        _fresh(self.client.get_volumes_performance, [_volume_perf()])
        volume = FakeVolume(host='host@pure-iscsi#pure-iscsi')

        result = self.api.get_volume_info(volume)

        self.assertIsInstance(result, pure_cinder_api.PureVolume)
        self.client.get_volumes.assert_called_once_with(names=[VOL_NAME])
        self.assertEqual(VOL_ID, result.id)
        self.assertEqual('vol', result.name)
        self.assertEqual(10, result.size)
        self.assertEqual(2.0, result.output_per_sec)
        self.assertEqual(0.5, result.input_per_sec)
        self.assertEqual(100, result.reads_per_sec)
        self.assertEqual(3.0, result.total)

    def test_get_volume_info_foreign_backend(self):
        volume = FakeVolume(host='host@lvm#lvm')
        result = self.api.get_volume_info(volume)
        self.assertEqual(VOL_ID, result.id)
        self.assertIsNone(getattr(result, 'total', None))
        self.build.assert_not_called()

    def test_get_volume_info_scans_arrays_without_host(self):
        conf = [
            {'san_ip': '192.0.2.10', 'api_token': 'tok',
             'backend_name': 'pure-iscsi'},
            {'san_ip': '192.0.2.10', 'api_token': 'tok',
             'backend_name': 'pure-fc'},
            {'san_ip': '192.0.2.11', 'api_token': 'tok',
             'backend_name': 'pure-nvme'},
        ]
        second = make_client('fa-two')
        self.build.side_effect = (
            lambda entry: second if entry.target == '192.0.2.11'
            else self.client)
        _fresh(self.client.get_volumes, status=400)
        _fresh(second.get_volumes, [_volume_item()])
        _fresh(second.get_volumes_performance, [_volume_perf()])

        with override_settings(PURE_FLASHARRAYS=conf):
            result = self.api.get_volume_info(FakeVolume())

        # First array queried once (plain + pod name), not once per backend.
        self.assertEqual(2, self.client.get_volumes.call_count)
        second.get_volumes.assert_called_once_with(names=[VOL_NAME])
        self.assertEqual(3.0, result.total)
        self.assertEqual(VOL_ID, result.id)

    def test_get_volume_info_without_arrays_keeps_cinder_fields(self):
        self.build.side_effect = RuntimeError('down')
        result = self.api.get_volume_info(FakeVolume())
        self.assertEqual(VOL_ID, result.id)
        self.assertEqual('vol', result.name)
        self.assertIsNone(getattr(result, 'total', None))

    def test_get_volumes_data(self):
        _fresh(self.client.get_volumes, [_volume_item()])
        _fresh(self.client.get_volumes_performance, [_volume_perf()])
        volumes = [FakeVolume(host='host@pure-iscsi#pure-iscsi'),
                   FakeVolume(vol_id='other', host='host@lvm#lvm')]
        data = self.api.get_volumes_data(volumes)
        self.assertEqual([VOL_ID, 'other'], [v.id for v in data])
        self.assertEqual(3.0, data[0].total)

    def test_capacity_limits(self):
        cases = (
            ('FA-X50R2', '6.2.0', (5000, 25000, 500, 250)),
            ('FA-X50R2', '6.3.1', (10000, 50000, 500, 250)),
            ('FA-XL170', '7.0.0', (20000, 100000, 2000, 250)),
            ('FA-XL130', '6.3.0', (20000, 100000, 2000, 250)),
            ('FA-X90R3', '6.10.6', (20000, 100000, 1000, 250)),
            ('FA-X10', '6.4.0', (500, 5000, 500, 250)),
            ('FA-C70', '6.4.7', (20000, 100000, 2000, 250)),
            ('FA-C70', '6.5.0', (20000, 100000, 2000, 250)),
            ('FA-C70', '6.4.6', (10000, 50000, 1000, 250)),
            ('FA-C60', '6.8.5', (10000, 50000, 1000, 250)),
            ('FA-C40', '6.3.0', (5000, 25000, 1000, 250)),
            ('FA-C20', '6.8.2', (5000, 25000, 500, 250)),
            ('FA-RC20', '6.8.1', (5000, 25000, 1000, 250)),
            ('FA-E', '6.6.0', (5000, 25000, 1000, 250)),
            ('FA-E', '6.5.9', (5000, 25000, 500, 250)),
            ('FA-M20', '6.8.5', (5000, 25000, 500, 250)),
            ('FA-X50R2', '6.0.9', (5000, 50000, 500, 100)),
            ('FA-X50R2', 'garbage', (5000, 50000, 500, 100)),
            ('FA-X50R2', None, (5000, 50000, 500, 100)),
            # '6' is 6.0.0, below the 6.1.0 minimum.
            ('FA-X50R2', '6', (5000, 50000, 500, 100)),
            ('FA-X50R2', '6.3', (10000, 50000, 500, 250)),
        )
        for model, version, expected in cases:
            with self.subTest(model=model, version=version):
                self.assertEqual(
                    expected, self.api._get_capacity_limits(model, version))

    def test_get_array_summary_is_reusable(self):
        summary = pure_flash_array.FlashArrayAPI.get_array_summary(
            self.client)
        self.assertEqual('fa-lab', summary['array_name'])
        self.assertEqual('FA-X50R2', summary['model'])
        self.assertEqual('6.8.5', summary['version'])
        self.assertEqual('Connected', summary['status'])
        self.assertEqual(1000.0, summary['capacity'])
        self.assertEqual(10.0, summary['total'])
        self.assertEqual('3.00 to 1', summary['data_reduction'])
        self.assertNotIn('reads_per_sec', summary)
        self.client.get_controllers.assert_called_once_with()
        self.client.get_arrays_space.assert_called_once_with()

        detailed = pure_flash_array.get_array_summary(self.client,
                                                      detailed=True)
        self.assertEqual(2.0, detailed['output_per_sec'])
        self.assertEqual(1.0, detailed['input_per_sec'])
        self.assertEqual(3, detailed['queue_depth'])

        _fresh(self.client.get_arrays, status=400)
        self.assertRaises(registry.ArrayUnavailable,
                          pure_flash_array.get_array_summary, self.client)

    def test_get_array_summary_degrades_without_space_or_controllers(self):
        _fresh(self.client.get_controllers, status=400)
        _fresh(self.client.get_arrays_space, [])
        summary = pure_flash_array.get_array_summary(self.client)
        self.assertEqual('Unknown', summary['model'])
        self.assertEqual(0.0, summary['capacity'])
        self.assertEqual('1.00 to 1', summary['data_reduction'])
        self.assertEqual('fa-lab', summary['array_name'])


class IndexViewTests(test.BaseAdminViewTests):

    def setUp(self):
        super().setUp()
        registry.reset()
        self.addCleanup(registry.reset)
        # No view test may ever build a real client.
        patcher = mock.patch.object(
            registry, '_build_client',
            side_effect=RuntimeError('no network in tests'))
        patcher.start()
        self.addCleanup(patcher.stop)

    @mock.patch.object(pure_flash_array, 'FlashArrayAPI')
    def test_index_renders(self, api_cls):
        api = api_cls.return_value
        api.get_total_stats.return_value = {
            'total_used': 100.0, 'total_available': 1000.0,
            'total_volume_count': 7, 'available_volume_count': 10000,
            'total_snapshot_count': 11, 'available_snapshot_count': 50000,
            'total_host_count': 5, 'available_host_count': 500,
            'total_pgroup_count': 2, 'available_pgroup_count': 250,
        }
        api.get_array_list.return_value = ['pure-iscsi']
        api.get_array_info.return_value = base.APIDictWrapper({
            'id': 'array-uuid', 'status': 'Connected',
            'array_name': 'fa-lab', 'version': '6.8.5', 'model': 'FA-X50R2',
            'capacity': 1000.0, 'total': 100.0, 'snapshots': 1.0,
            'volumes': 9.0, 'unique': 9.0,
            'data_reduction': '3.00 to 1', 'thin_provisioning': '4.00 to 1',
            'total_reduction': '12.00 to 1', 'total_volume_count': 7,
            'cinder_id': 'pure-iscsi', 'cinder_name': 'pure-iscsi',
            'target': '192.0.2.10',
        })

        res = self.client.get(reverse('horizon:admin:pure_panel:index'))

        self.assertEqual(200, res.status_code)
        self.assertTemplateUsed(res, 'pure_panel/index.html')
