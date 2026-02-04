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
from pypureclient import flasharray
import re

from openstack_dashboard.api import base

from horizon_pure.api import cinder as pure_cinder_api


LOG = logging.getLogger(__name__)

SIZE_KEYS = [
    'capacity',
    'snapshots',
    'volumes',
    'total',
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


class ErrorStateArray(object):
    """Represents an array in error state"""
    def __init__(self, target, e):
        self._target = target
        self.error = e
        self.target = target


class FlashArrayAPI(object):
    def __init__(self):
        self._arrays = {}
        self._array_config = getattr(settings, 'PURE_FLASH_ARRAYS')
        self._array_id_list = []
        self._init_all_arrays()

    def _init_all_arrays(self):
        for array_conf in self._array_config:
            array_id = array_conf['backend_name']
            array = self._get_array_from_conf(array_conf)
            self._arrays[array_id] = array
            self._array_id_list.append(array_id)

    def _get_array_from_conf(self, conf):
        try:
            # Create py-pure-client FlashArray client
            # Note: verify_ssl=False is used because FlashArrays often use self-signed certificates
            client = flasharray.Client(
                target=conf['san_ip'],
                api_token=conf['api_token'],
                user_agent='OpenStack-Horizon-Pure-UI/2.0.0',
                verify_ssl=False
            )
            # Add custom attributes for compatibility
            client.error = None
            client._target = conf['san_ip']
            client.target = conf['san_ip']
            return client
        except Exception as e:
            LOG.warning('Unable to create Pure Storage FlashArray client: %s'
                        % str(e))
            return ErrorStateArray(conf['san_ip'], 'Failed to connect')

    def _get_capacity_limits(self, model, version):
        """
        Get capacity limits based on array model and Purity version.

        Minimum supported version: Purity 6.1.0

        Args:
            model: Array model (e.g., 'FA-X50R2', 'FA-C60')
            version: Purity version (e.g., '6.8.5')

        Returns:
            Tuple of (volume_cap, snapshot_cap, host_cap, pgroup_cap)
        """
        # Parse version to compare
        try:
            version_parts = version.split('.')
            major = int(version_parts[0])
            minor = int(version_parts[1]) if len(version_parts) > 1 else 0
            patch = int(version_parts[2]) if len(version_parts) > 2 else 0
        except (ValueError, IndexError):
            # If version parsing fails, use conservative defaults
            LOG.warning('Failed to parse Purity version: %s' % version)
            return (5000, 50000, 500, 100)

        # Check minimum version requirement
        if major < 6 or (major == 6 and minor < 1):
            LOG.error('Purity version %s is below minimum supported version 6.1.0' % version)
            return (5000, 50000, 500, 100)

        # Extract model family (remove FA- prefix and generation suffix)
        # e.g., "FA-X50R2" -> "X50", "FA-C60" -> "C60"
        model_clean = model.replace('FA-', '').replace('//', '')
        # Remove generation suffix (R2, R3, R4, etc.)
        model_family = re.sub(r'R\d+$', '', model_clean)

        # Capacity lookup based on model family and version
        # Format: (volumes, snapshots, hosts, pgroups)
        # Snapshot limit is typically 10x volume limit for modern arrays
        # Protection groups (pgroups) max is 250 for all arrays

        # XL-class arrays (//XL130, //XL170)
        if model_family in ['XL130', 'XL170']:
            if major >= 6 and minor >= 3:
                return (20000, 100000, 2000, 250)

        # X-class high-end (//X70, //X90)
        elif model_family in ['X70', 'X90']:
            if major >= 6 and minor >= 3:
                return (20000, 100000, 1000, 250)

        # X-class mid-range (//X20, //X50)
        elif model_family in ['X20', 'X50']:
            if major >= 6 and minor >= 3:
                return (10000, 50000, 500, 250)

        # X-class entry (//X10)
        elif model_family in ['X10']:
            if major >= 6 and minor >= 3:
                return (500, 5000, 500, 250)

        # C-class high-end (//C70, //C90)
        elif model_family in ['C70', 'C90']:
            if major >= 6 and minor >= 4 and patch >= 7:
                return (20000, 100000, 2000, 250)
            elif major >= 6 and minor >= 3:
                return (10000, 50000, 1000, 250)

        # C-class mid-range (//C50, //C60)
        elif model_family in ['C50', 'C60']:
            if major >= 6 and minor >= 3:
                return (10000, 50000, 1000, 250)

        # C-class entry (//C40)
        elif model_family in ['C40']:
            if major >= 6 and minor >= 3:
                return (5000, 25000, 1000, 250)

        # C-class small (//C20, //RC20)
        elif model_family in ['C20', 'RC20']:
            if major >= 6 and minor >= 8 and patch >= 2:
                return (5000, 25000, 500, 250)
            elif major >= 6 and minor >= 3:
                return (5000, 25000, 1000, 250)

        # E-class (//E)
        elif model_family in ['E']:
            if major >= 6 and minor >= 6:
                return (5000, 25000, 1000, 250)

        # Default fallback for unknown models or older versions
        LOG.warning('Unknown array model %s or version %s, using conservative defaults' %
                   (model, version))
        return (5000, 25000, 500, 250)

    def _get_array(self, array_id):
        array = self._arrays.get(array_id)
        if array and hasattr(array, 'error') and array.error:
            LOG.debug('Removing FlashArray client for %s that was in error '
                      'state.' % array_id)
            array = None
            self._arrays[array_id] = None
        if not array:
            LOG.debug('Initializing FlashArray client for ' + array_id)
            if self._array_config:
                for array_conf in self._array_config:
                    be_name = array_conf.get('backend_name')
                    if be_name == array_id:
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

    def _get_volume_stats(self, client, vol_id):
        pure_vol_name = 'volume-%s-cinder' % vol_id
        LOG.debug('Getting volume stats for %s from %s' % (vol_id, client.target))

        try:
            # Try to get volume with space stats
            response = client.get_volumes(names=[pure_vol_name])
            if response.status_code != 200 or not list(response.items):
                # Try with pod prefix
                pure_vol_name = "*::" + pure_vol_name
                response = client.get_volumes(names=[pure_vol_name])

            if response.status_code != 200:
                raise Exception(f"Failed to get volume: {response.errors}")

            volume = list(response.items)[0]
            space_stats = {
                'total': volume.space.total_provisioned if volume.space else 0,
                'snapshots': volume.space.snapshots if volume.space else 0,
                'volumes': volume.space.total_physical if volume.space else 0,
                'data_reduction': volume.space.data_reduction if volume.space else 1.0,
                'thin_provisioning': volume.space.thin_provisioning if volume.space else 1.0,
                'total_reduction': volume.space.total_reduction if volume.space else 1.0,
            }

            # Get performance stats
            perf_response = client.get_volumes_performance(names=[pure_vol_name])
            perf_stats = {}
            if perf_response.status_code == 200:
                perf = list(perf_response.items)[0]
                perf_stats = {
                    'reads_per_sec': perf.reads_per_sec if perf.reads_per_sec else 0,
                    'writes_per_sec': perf.writes_per_sec if perf.writes_per_sec else 0,
                    'usec_per_read_op': perf.usec_per_read_op if perf.usec_per_read_op else 0,
                    'usec_per_write_op': perf.usec_per_write_op if perf.usec_per_write_op else 0,
                }

            LOG.debug('raw_stats = %s' % space_stats)
            stats = space_stats.copy()
            stats.update(perf_stats)
            stats.update({
                'total': adjust_purity_size(space_stats['total']),
                'output_per_sec': adjust_purity_size(perf_stats.get('reads_per_sec', 0)),
                'input_per_sec': adjust_purity_size(perf_stats.get('writes_per_sec', 0)),
            })
            LOG.debug('stats = %s' % stats)
            return stats
        except Exception as e:
            LOG.error(f"Error getting volume stats: {e}")
            raise

    def get_volume_info(self, volume):
        stats = {}
        try:
            backend = getattr(volume, 'os-vol-host-attr:host')
            backend = re.split('@', backend)[1]
            backend = re.split('#', backend)[0]
            LOG.debug('Found backend %s' % backend)
        except Exception:
            backend = ''
            LOG.debug('Backend not found. Looping...')
        if backend:
            # Fast path, we are an admin and know what array it belongs to
            array = self._get_array(backend)
            LOG.debug('Got array %s' % array)
            if array and not (hasattr(array, 'error') and array.error):
                try:
                    stats = self._get_volume_stats(array, volume.id)
                except Exception as e:
                    LOG.exception(e)
                    LOG.warning('Failed to get Purity volume info: %s' % e)
        else:
            for array_id in self._array_id_list:
                array = self._get_array(array_id)
                LOG.debug('Trying array %s' % array)
                try:
                    stats = self._get_volume_stats(array, volume.id)
                    break
                except Exception as e:
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
        arrays = self._array_id_list

        for array_id in arrays:
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

        if not (hasattr(array, 'error') and array.error):
            # Get array info using py-pure-client
            # Get controller info to determine array model and version
            controller_response = array.get_controllers()
            if controller_response.status_code == 200:
                controller = list(controller_response.items)[0]
                model = controller.model
                version = controller.version

                # Get capacity limits based on model and version
                # TODO: Implement lookup table from Excel data
                array_volume_cap, array_snapshot_cap, array_host_cap, array_pgroup_cap = \
                    self._get_capacity_limits(model, version)

                available_volume_count += array_volume_cap
                available_snapshot_count += array_snapshot_cap
                available_host_count += array_host_cap
                available_pgroup_count += array_pgroup_cap

                # Get volume counts using total_item_count
                vol_response = array.get_volumes(total_item_count=True)
                if vol_response.status_code == 200 and vol_response.total_item_count is not None:
                    total_volume_count += vol_response.total_item_count

                # Get snapshot counts using total_item_count
                snap_response = array.get_volume_snapshots(total_item_count=True)
                if snap_response.status_code == 200 and snap_response.total_item_count is not None:
                    total_snapshot_count += snap_response.total_item_count

                # Get host counts using total_item_count
                host_response = array.get_hosts(total_item_count=True)
                if host_response.status_code == 200 and host_response.total_item_count is not None:
                    total_host_count += host_response.total_item_count

                # Get protection group counts using total_item_count
                pgroup_response = array.get_protection_groups(total_item_count=True)
                if pgroup_response.status_code == 200 and pgroup_response.total_item_count is not None:
                    total_pgroup_count += pgroup_response.total_item_count

                # Get space info
                space_response = array.get_arrays_space()
                if space_response.status_code == 200:
                    space_info = list(space_response.items)[0]
                    total_used = total_used + space_info.space.total_physical
                    total_available = total_available + space_info.capacity

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
            'available_pgroup_count': available_pgroup_count,
        }
        return stats

    def get_array_list(self):
        return self._array_id_list

    def get_array_info(self, array_id, detailed=False):
        array = self._get_array(array_id)
        if hasattr(array, 'error') and array.error:
            info = {
                'id': '1',
                'status': 'Error: ' + array.error,
                'array_name': 'Unknown',
                'version': 'Unknown',
                'capacity': 0,
                'total': 0,
                'snapshots': 0,
                'volumes': 0,
                'data_reduction': 1.0,
                'thin_provisioning': 1.0,
                'total_reduction': 1.0,
                'total_volume_count': 0,
            }
        else:
            # Get array info using py-pure-client
            try:
                response = array.get_arrays()

                if response is None:
                    LOG.error('get_arrays() returned None for %s' % array_id)
                    raise Exception('get_arrays() returned None')
            except Exception as e:
                LOG.error('Exception calling get_arrays() for %s: %s' % (array_id, str(e)))
                info = {
                    'id': '1',
                    'status': 'Error: ' + str(e),
                    'array_name': 'Unknown',
                    'version': 'Unknown',
                    'capacity': 0,
                    'total': 0,
                    'snapshots': 0,
                    'volumes': 0,
                    'data_reduction': 1.0,
                    'thin_provisioning': 1.0,
                    'total_reduction': 1.0,
                    'total_volume_count': 0,
                }
                info['cinder_name'] = array_id
                info['cinder_id'] = array_id
                info['target'] = array._target if hasattr(array, '_target') else array.target
                return base.APIDictWrapper(info)

            if response.status_code != 200:
                LOG.warning('get_arrays() returned status %d for %s' % (response.status_code, array_id))
                info = {
                    'id': '1',
                    'status': 'Error: Failed to get array info (HTTP %d)' % response.status_code,
                    'array_name': 'Unknown',
                    'version': 'Unknown',
                    'capacity': 0,
                    'total': 0,
                    'snapshots': 0,
                    'volumes': 0,
                    'data_reduction': 1.0,
                    'thin_provisioning': 1.0,
                    'total_reduction': 1.0,
                    'total_volume_count': 0,
                }
            else:
                array_obj = list(response.items)[0]
                info = {
                    'id': array_obj.id if array_obj.id else '1',
                    'version': array_obj.version if array_obj.version else 'Unknown',
                    'array_name': array_obj.name if array_obj.name else 'Unknown',
                }

                # Get space info
                space_response = array.get_arrays_space()
                if space_response.status_code == 200:
                    space_obj = list(space_response.items)[0]

                    # Extract space information with proper field names
                    capacity = space_obj.capacity if hasattr(space_obj, 'capacity') and space_obj.capacity else 0

                    # Get space metrics - check which attributes exist
                    total_physical = 0
                    snapshots = 0
                    volumes = 0
                    data_reduction = 1.0
                    thin_provisioning = 1.0
                    total_reduction = 1.0

                    if hasattr(space_obj, 'space') and space_obj.space:
                        # Try total_provisioned first, fall back to total_physical
                        if hasattr(space_obj.space, 'total_provisioned'):
                            total_physical = space_obj.space.total_provisioned
                        elif hasattr(space_obj.space, 'total_physical'):
                            total_physical = space_obj.space.total_physical

                        if hasattr(space_obj.space, 'snapshots'):
                            snapshots = space_obj.space.snapshots

                        # Try total_physical for volumes, fall back to unique
                        if hasattr(space_obj.space, 'total_physical'):
                            volumes = space_obj.space.total_physical
                        elif hasattr(space_obj.space, 'unique'):
                            volumes = space_obj.space.unique

                        if hasattr(space_obj.space, 'data_reduction') and space_obj.space.data_reduction:
                            data_reduction = space_obj.space.data_reduction

                        if hasattr(space_obj.space, 'thin_provisioning') and space_obj.space.thin_provisioning:
                            thin_provisioning = space_obj.space.thin_provisioning

                        if hasattr(space_obj.space, 'total_reduction') and space_obj.space.total_reduction:
                            total_reduction = space_obj.space.total_reduction

                    space_info = {
                        'capacity': capacity,
                        'total': total_physical,
                        'snapshots': snapshots,
                        'volumes': volumes,
                        'data_reduction': data_reduction,
                        'thin_provisioning': thin_provisioning,
                        'total_reduction': total_reduction,
                    }
                    info.update(space_info)

                info['status'] = 'Connected'

                if detailed:
                    # Get performance info
                    perf_response = array.get_arrays_performance()
                    if perf_response.status_code == 200:
                        perf_obj = list(perf_response.items)[0]
                        perf_info = {
                            'queue_depth': perf_obj.queue_depth if hasattr(perf_obj, 'queue_depth') and perf_obj.queue_depth else 0,
                            'reads_per_sec': perf_obj.reads_per_sec if hasattr(perf_obj, 'reads_per_sec') and perf_obj.reads_per_sec else 0,
                            'writes_per_sec': perf_obj.writes_per_sec if hasattr(perf_obj, 'writes_per_sec') and perf_obj.writes_per_sec else 0,
                            'usec_per_read_op': perf_obj.usec_per_read_op if hasattr(perf_obj, 'usec_per_read_op') and perf_obj.usec_per_read_op else 0,
                            'usec_per_write_op': perf_obj.usec_per_write_op if hasattr(perf_obj, 'usec_per_write_op') and perf_obj.usec_per_write_op else 0,
                        }
                        info.update(perf_info)

                stats = self.get_array_stats(array_id)
                info.update(stats)

        info['cinder_name'] = array_id
        info['cinder_id'] = array_id
        info['target'] = array._target if hasattr(array, '_target') else array.target

        for key in info:
            if key in SIZE_KEYS:
                info[key] = adjust_purity_size(info[key])
            if key in RATIO_KEYS:
                info[key] = "%.2f to 1" % info[key]

        LOG.debug('Found flash array info for %s: %s' % (array_id, str(info)))
        return base.APIDictWrapper(info)
