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

from django.conf import settings
import logging
import purestorage

from openstack_dashboard.api import base

from horizon_pure.api import cinder as pure_cinder_api


LOG = logging.getLogger(__name__)

SIZE_KEYS = [
    'capacity',
    'snapshots',
    'volumes',
    'total',
    'shared_space',
    'input_per_sec',
    'output_per_sec',
]
RATIO_KEYS = [
    'data_reduction',
    'thin_provisioning',
    'total_reduction'
]


def adjust_purity_size(bytes):
    return bytes / (1024 ** 2)


class ErrorStateArray(purestorage.FlashArray):
    def __init__(self, target, e):
        self._target = target
        self.error = e


class FlashArrayAPI(object):
    def __init__(self):
        self._arrays = {}
        self._array_config = getattr(settings, 'PURE_FLASH_ARRAYS')
        self._array_id_list = []
        self._init_all_arrays()

    def _init_all_arrays(self):
        for array_conf in self._array_config:
            array_id = '%s@%s#%s' % (
                array_conf['cinder_host'],
                array_conf['backend_name'],
                array_conf['backend_name']
            )
            array = self._get_array_from_conf(array_conf)
            self._arrays[array_id] = array
            self._array_id_list.append(array_id)

    def _get_array_from_conf(self, conf):
        try:
            array = purestorage.FlashArray(conf['san_ip'],
                                           api_token=conf['api_token'])
            array.error = None
            return array
        except purestorage.PureError as e:
            LOG.warning('Unable to create Pure Storage FlashArray client: %s'
                        % str(e))
            return ErrorStateArray(conf['san_ip'], 'Failed to connect')

    def _get_array(self, array_id):
        cinder_host, backend_name = array_id.split('@')
        backend_name, pool_name = backend_name.split('#')
        array = self._arrays.get(array_id)
        if array and array.error:
            LOG.debug('Removing FlashArray client for %s that was in error '
                      'state.' % array_id)
            array = None
            self._arrays[array_id] = None
        if not array:
            LOG.debug('Initializing FlashArray client for ' + array_id)
            if self._array_config:
                for array_conf in self._array_config:
                    host = array_conf.get('cinder_host')
                    be_name = array_conf.get('backend_name')
                    if (host == cinder_host and
                            be_name == backend_name and
                            be_name == pool_name):
                        array = self._get_array_from_conf(array_conf)
                        self._arrays[array_id] = array
                        break
                if not array:
                    LOG.error('Failed to find array in conf for %s' % array_id)
                    array = ErrorStateArray('array_id', 'Not in config')
        else:
            LOG.debug('Using existing FlashArray client for ' + array_id)
        return array

    def get_volumes_data(self, volumes):
        data = []
        for vol in volumes:
            data.append(self.get_volume_info(vol))
        return data

    def _get_volume_stats(self, array, vol_id):
        pure_vol_name = 'volume-%s-cinder' % vol_id
        LOG.debug('Getting volume stats for %s from %s' % (vol_id, array))
        space_stats = array.get_volume(pure_vol_name, space=True)
        LOG.debug('raw_stats = %s' % space_stats)
        perf_stats = array.get_volume(pure_vol_name, action='monitor')[0]
        stats = space_stats.copy()
        stats.update(perf_stats)
        stats.update({
            'total': adjust_purity_size(space_stats['total']),
            'output_per_sec': adjust_purity_size(perf_stats['reads_per_sec']),
            'input_per_sec': adjust_purity_size(perf_stats['writes_per_sec']),
        })
        LOG.debug('stats = %s' % stats)
        return stats

    def get_volume_info(self, volume):
        stats = {}
        backend = getattr(volume, 'os-vol-host-attr:host')
        LOG.debug('Found backend %s' % backend)
        if backend:
            # Fast path, we are an admin and know what array it belongs to
            array = self._get_array(backend)
            LOG.debug('Got array %s' % array)
            if array and not array.error:
                try:
                    stats = self._get_volume_stats(array, volume.id)
                except purestorage.PureError as e:
                    LOG.exception(e)
                    LOG.warning('Failed to get Purity volume info: %s' % e)
        else:
            for array_id in self._array_id_list:
                array = self._get_array(array_id)
                LOG.debug('Trying array %s' % array)
                try:
                    stats = self._get_volume_stats(array, volume.id)
                    break
                except purestorage.PureError as e:
                    LOG.debug('Unable to get volume stats from %s for vol %s:'
                              ' %s' % (array_id, volume.id, e))
            if not stats:
                LOG.debug('Failed to find volume %s on any configured arrays!'
                          % volume.id)

        stats.update(volume.to_dict())
        return pure_cinder_api.PureVolume(base.APIDictWrapper(stats))

    def get_host_stats(self, host):
        # TODO: Lookup the purity host and return perf info and connected volumes
        return {}

    def get_total_stats(self):
        stats = {}
        for array_id in self._array_id_list:
            array_stats = self.get_array_stats(array_id)
            for key in array_stats:
                if key in stats:
                    stats[key] += array_stats[key]
                else:
                    stats[key] = array_stats[key]

        LOG.debug('Found total stats for flash arrays: %s' % stats)
        return stats

    def get_array_stats(self, array_id):
        array = self._get_array(array_id)

        total_used = 0
        total_available = 0
        total_volume_count = 0
        total_snapshot_count = 0
        total_host_count = 0
        total_pgroup_count = 0
        available_volume_count = 0
        available_snapshot_count = 0
        available_host_count = 0
        available_pgroup_count = 0

        if not array.error:
            info = array.get()
            array_volume_cap = 500
            array_snapshot_cap = 5000
            array_host_cap = 50
            array_pgroup_cap = 50
            version = info['version'].split('.')
            if ((int(version[0]) == 4 and int(version[1]) >= 8) or
                    (int(version[0]) > 4)):
                array_volume_cap = 5000
                array_snapshot_cap = 50000
                array_host_cap = 500

            available_volume_count += array_volume_cap
            available_snapshot_count += array_snapshot_cap
            available_host_count += array_host_cap
            available_pgroup_count += array_pgroup_cap

            total_volume_count += len(array.list_volumes(pending=True))
            total_snapshot_count += len(array.list_volumes(snap=True,
                                                           pending=True))
            total_host_count += len(array.list_hosts())

            total_pgroup_count += len(array.list_pgroups(snap=True,
                                                         pending=True))
            space_info = array.get(space=True)
            if isinstance(space_info, list):
                space_info = space_info[0]
            total_used = total_used + space_info['total']
            total_available = total_available + space_info['capacity']

        total_used = adjust_purity_size(total_used)
        total_available = adjust_purity_size(total_available)

        stats = {
            'total_used': total_used,
            'total_available': total_available,
            'total_volume_count': total_volume_count,
            'available_volume_count': available_volume_count,
            'total_snapshot_count': total_snapshot_count,
            'available_snapshot_count': available_snapshot_count,
            'total_host_count': total_host_count,
            'available_host_count': available_host_count,
            'total_pgroup_count': total_pgroup_count,
            'available_pgroup_count': available_host_count,
        }
        return stats

    def get_array_list(self):
        return self._array_id_list

    def get_array_info(self, array_id, detailed=False):
        array = self._get_array(array_id)
        if array.error:
            info = {
                'id': '1',
                'status': 'Error: ' + array.error,
            }
        else:
            info = array.get()
            space_info = array.get(space=True)
            if isinstance(space_info, list):
                space_info = space_info[0]
            info.update(space_info)
            info['volume_count'] = (len(array.list_volumes()) +
                                    len(array.list_volumes(pending=True)))
            info['status'] = 'Connected'

            if detailed:
                perf_info = array.get(action='monitor')
                if isinstance(perf_info, list):
                    perf_info = perf_info[0]
                info.update(perf_info)

                stats = self.get_array_stats(array_id)
                info.update(stats)

        info['cinder_id'] = array_id
        info['target'] = array._target

        for key in info:
            if key in SIZE_KEYS:
                info[key] = adjust_purity_size(info[key])
            if key in RATIO_KEYS:
                info[key] = "%.2f to 1" % info[key]

        LOG.debug('Found flash array info for %s: %s' % (array_id, str(info)))
        return base.APIDictWrapper(info)
