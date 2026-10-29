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

"""Cinder-facing FlashArray queries.

Clients come from ``horizon_pure.api.registry`` and are built on first use,
never at import or construction time. All sizes returned are MiB (the
templates render them with ``mb_float_format``); array-level reduction
ratios are "x.xx to 1" strings, volume-level ones stay numeric because
``pure_detail_view.html`` applies ``floatformat`` to them.
"""

import logging
import re

from openstack_dashboard.api import base

from horizon_pure.api import cinder as pure_cinder_api
from horizon_pure.api import registry


LOG = logging.getLogger(__name__)

# Keys whose raw value is bytes and is reported in MiB.
SIZE_KEYS = [
    'capacity',
    'snapshots',
    'volumes',
    'unique',
    'total',
    'input_per_sec',
    'output_per_sec',
]
# Keys reported as "x.xx to 1" strings in array-level dicts.
RATIO_KEYS = [
    'data_reduction',
    'thin_provisioning',
    'total_reduction',
]

_STAT_KEYS = (
    'total_used',
    'total_available',
    'total_volume_count',
    'available_volume_count',
    'total_snapshot_count',
    'available_snapshot_count',
    'total_host_count',
    'available_host_count',
    'total_pgroup_count',
    'available_pgroup_count',
)

# Object limits as (volumes, snapshots, hosts, protection groups).
_MIN_VERSION = (6, 1, 0)
_LEGACY_LIMITS = (5000, 50000, 500, 100)
_DEFAULT_LIMITS = (5000, 25000, 500, 250)
# (model families, ((minimum Purity version, limits), ...) newest first).
_CAPACITY_LIMITS = (
    (('XL130', 'XL170'),
     (((6, 3, 0), (20000, 100000, 2000, 250)),)),
    (('X70', 'X90'),
     (((6, 3, 0), (20000, 100000, 1000, 250)),)),
    (('X20', 'X50'),
     (((6, 3, 0), (10000, 50000, 500, 250)),)),
    (('X10',),
     (((6, 3, 0), (500, 5000, 500, 250)),)),
    (('C70', 'C90'),
     (((6, 4, 7), (20000, 100000, 2000, 250)),
      ((6, 3, 0), (10000, 50000, 1000, 250)))),
    (('C50', 'C60'),
     (((6, 3, 0), (10000, 50000, 1000, 250)),)),
    (('C40',),
     (((6, 3, 0), (5000, 25000, 1000, 250)),)),
    (('C20', 'RC20'),
     (((6, 8, 2), (5000, 25000, 500, 250)),
      ((6, 3, 0), (5000, 25000, 1000, 250)))),
    (('E',),
     (((6, 6, 0), (5000, 25000, 1000, 250)),)),
)


def adjust_purity_size(nbytes):
    """Bytes -> MiB."""
    return registry.to_mib(nbytes)


def parse_version(version):
    """'6.8.5' -> (6, 8, 5); missing parts are 0; None when unparseable."""
    try:
        parts = [int(part) for part in str(version).split('.')[:3]]
    except ValueError:
        return None
    return tuple(parts + [0] * (3 - len(parts)))


def _empty_stats():
    return dict.fromkeys(_STAT_KEYS, 0)


def _error_info(message):
    info = {
        'id': '1',
        'status': 'Error: %s' % message,
        'array_name': 'Unknown',
        'version': 'Unknown',
        'model': 'Unknown',
        'capacity': 0,
        'total': 0,
        'snapshots': 0,
        'volumes': 0,
        'unique': 0,
        'data_reduction': registry.ratio(None),
        'thin_provisioning': registry.ratio(None),
        'total_reduction': registry.ratio(None),
    }
    info.update(_empty_stats())
    return info


def _format(info):
    """Convert SIZE_KEYS to MiB and RATIO_KEYS to strings, in place."""
    for key in SIZE_KEYS:
        if key in info:
            info[key] = adjust_purity_size(info[key])
    for key in RATIO_KEYS:
        if key in info:
            info[key] = registry.ratio(info[key])
    return info


def _read_array(client, detailed=False):
    """Fetch the array-level items: (array, controller, space_item, perf).

    ``perf`` is None unless ``detailed``. Raises registry.ArrayUnavailable
    when the array itself cannot be read; the other items are None when
    their call fails or returns nothing. ``get_array_info`` reads these
    once and feeds both the summary and the statistics with them.
    """
    resp = client.get_arrays()
    array = registry.first(resp)
    if array is None:
        raise registry.ArrayUnavailable(
            'Unable to read array properties (%s)'
            % registry.error_message(resp))
    controller = registry.first(client.get_controllers())
    space_item = registry.first(client.get_arrays_space())
    perf = None
    if detailed:
        perf = registry.first(client.get_arrays_performance())
    return array, controller, space_item, perf


def get_array_summary(client, detailed=False):
    """Array-level summary for a FlashArray client.

    Returns a dict with ``id``, ``array_name``, ``version``, ``model``,
    ``status`` ('Connected'), ``capacity``, ``total`` (physical used),
    ``snapshots``, ``unique`` and ``volumes`` (both unique space) in MiB
    and the RATIO_KEYS as "x.xx to 1" strings. With ``detailed`` it adds
    ``reads_per_sec``, ``writes_per_sec`` (IOPS), ``output_per_sec`` and
    ``input_per_sec`` (read/write MiB per second), ``usec_per_read_op``,
    ``usec_per_write_op`` and ``queue_depth``.

    Raises registry.ArrayUnavailable when the array itself cannot be
    read; controller, space and performance failures degrade to
    'Unknown' / zeros. Shared with the FlashArray Files API.
    """
    return _summary_from(*_read_array(client, detailed), detailed=detailed)


def _summary_from(array, controller, space_item, perf, detailed=False):
    """The ``get_array_summary`` dict from the items ``_read_array`` gave."""
    info = {
        'id': registry.attr(array, 'id', '1'),
        'array_name': registry.attr(array, 'name', 'Unknown'),
        'version': registry.attr(array, 'version', 'Unknown'),
        'model': 'Unknown',
        'status': 'Connected',
        'capacity': 0,
        'total': 0,
        'snapshots': 0,
        'volumes': 0,
        'unique': 0,
        'data_reduction': None,
        'thin_provisioning': None,
        'total_reduction': None,
    }

    if controller is not None:
        info['model'] = registry.attr(controller, 'model', 'Unknown')

    if space_item is None:
        LOG.warning('Unable to read space for array %s', info['array_name'])
    else:
        space = registry.attr(space_item, 'space')
        info.update({
            'capacity': registry.attr(space_item, 'capacity', 0),
            'total': registry.attr(space, 'total_physical', 0),
            'snapshots': registry.attr(space, 'snapshots', 0),
            'unique': registry.attr(space, 'unique', 0),
            # Space consumed by volume data, as the REST 1.x 'volumes' was.
            'volumes': registry.attr(space, 'unique', 0),
            'data_reduction': registry.attr(space, 'data_reduction'),
            'thin_provisioning': registry.attr(space, 'thin_provisioning'),
            'total_reduction': registry.attr(space, 'total_reduction'),
        })

    if detailed:
        info.update({
            'reads_per_sec': registry.attr(perf, 'reads_per_sec', 0),
            'writes_per_sec': registry.attr(perf, 'writes_per_sec', 0),
            'output_per_sec': registry.attr(perf, 'read_bytes_per_sec', 0),
            'input_per_sec': registry.attr(perf, 'write_bytes_per_sec', 0),
            'usec_per_read_op': registry.attr(perf, 'usec_per_read_op', 0),
            'usec_per_write_op': registry.attr(perf, 'usec_per_write_op', 0),
            'queue_depth': registry.attr(perf, 'queue_depth', 0),
        })

    return _format(info)


class ErrorStateArray(object):
    """Stands in for a client when a backend cannot be used."""

    def __init__(self, array_id, error, target=None):
        self.array_id = array_id
        self.error = error
        self.target = target or array_id
        self._target = self.target

    def __repr__(self):
        return '<ErrorStateArray %s: %s>' % (self.array_id, self.error)


class FlashArrayAPI(object):
    """Queries for the Cinder FlashArray backends in PURE_FLASHARRAYS."""

    get_array_summary = staticmethod(get_array_summary)

    def _entries(self):
        return registry.entries(service='cinder', kind='fa')

    def get_array_list(self):
        return [entry.backend_name for entry in self._entries()]

    def _get_array(self, array_id):
        """The client for backend ``array_id``, or an ErrorStateArray."""
        entry = registry.find('cinder', array_id)
        if entry is None:
            LOG.debug('Backend %s is not configured in PURE_FLASHARRAYS',
                      array_id)
            return ErrorStateArray(array_id, 'Not in config')
        try:
            return registry.get_client(entry)
        except registry.ArrayUnavailable as exc:
            return ErrorStateArray(array_id, str(exc), target=entry.target)

    def _get_capacity_limits(self, model, version):
        """Object limits for an array model running a Purity version.

        Returns (volumes, snapshots, hosts, protection groups). Versions
        below 6.1.0, unparseable versions and unknown models get
        conservative defaults.
        """
        ver = parse_version(version)
        if ver is None:
            LOG.warning('Failed to parse Purity version: %s', version)
            return _LEGACY_LIMITS
        if ver < _MIN_VERSION:
            LOG.error('Purity version %s is below the minimum supported '
                      'version 6.1.0', version)
            return _LEGACY_LIMITS

        # "FA-X50R2" -> "X50", "//C60" -> "C60": drop the prefix and the
        # generation suffix (R2, R3, ...).
        family = str(model).replace('FA-', '').replace('//', '')
        family = re.sub(r'R\d+$', '', family)
        for families, rows in _CAPACITY_LIMITS:
            if family in families:
                for min_version, limits in rows:
                    if ver >= min_version:
                        return limits
                break
        LOG.warning('Unknown array model %s or version %s, using '
                    'conservative defaults', model, version)
        return _DEFAULT_LIMITS

    @staticmethod
    def _count(method):
        """Object count via total_item_count=True; 0 on error."""
        resp = method(total_item_count=True)
        if registry.ok(resp):
            count = getattr(resp, 'total_item_count', None)
            if count is not None:
                return count
        return 0

    def get_array_stats(self, array_id):
        """Capacity (MiB) and object counts/limits for one backend."""
        stats = _empty_stats()
        array = self._get_array(array_id)
        if isinstance(array, ErrorStateArray):
            return stats
        try:
            controller = registry.first(array.get_controllers())
            space_item = registry.first(array.get_arrays_space())
        except Exception as exc:
            LOG.warning('Failed to collect statistics from %s: %s',
                        array_id, exc)
            return stats
        return self._collect_stats(array, array_id, controller, space_item)

    def _collect_stats(self, array, array_id, controller, space_item):
        """Counts, limits and capacity (MiB) from already fetched items.

        ``controller`` and ``space_item`` come from ``_read_array`` (or
        ``get_array_stats``); None keeps the defaults. An SDK exception
        degrades to the zeros rather than failing the page.
        """
        stats = _empty_stats()
        try:
            if controller is not None:
                (stats['available_volume_count'],
                 stats['available_snapshot_count'],
                 stats['available_host_count'],
                 stats['available_pgroup_count']) = \
                    self._get_capacity_limits(
                        registry.attr(controller, 'model', ''),
                        registry.attr(controller, 'version', ''))
            stats['total_volume_count'] = self._count(array.get_volumes)
            stats['total_snapshot_count'] = self._count(
                array.get_volume_snapshots)
            stats['total_host_count'] = self._count(array.get_hosts)
            stats['total_pgroup_count'] = self._count(
                array.get_protection_groups)
            if space_item is not None:
                space = registry.attr(space_item, 'space')
                stats['total_used'] = adjust_purity_size(
                    registry.attr(space, 'total_physical', 0))
                stats['total_available'] = adjust_purity_size(
                    registry.attr(space_item, 'capacity', 0))
        except Exception as exc:
            LOG.warning('Failed to collect statistics from %s: %s',
                        array_id, exc)
        return stats

    def get_total_stats(self):
        """Sum of get_array_stats over the configured arrays.

        Several backends may point at one array; each target is counted
        once. An empty configuration yields an empty dict.
        """
        stats = {}
        seen = set()
        for entry in self._entries():
            if entry.target in seen:
                LOG.debug('Skipping %s: array %s already counted',
                          entry.backend_name, entry.target)
                continue
            seen.add(entry.target)
            for key, value in self.get_array_stats(entry.backend_name).items():
                stats[key] = stats.get(key, 0) + value
        LOG.debug('Found total stats for FlashArrays: %s', stats)
        return stats

    def get_array_info(self, array_id, detailed=False):
        """Summary plus stats for one backend as an APIDictWrapper.

        Always carries ``cinder_id``, ``cinder_name``, ``target`` and
        ``status``; an unusable backend yields ``status`` 'Error: ...'
        with zeroed values rather than an exception.
        """
        entry = registry.find('cinder', array_id)
        array = self._get_array(array_id)
        if isinstance(array, ErrorStateArray):
            info = _error_info(array.error)
        else:
            try:
                items = _read_array(array, detailed=detailed)
            except Exception as exc:
                LOG.error('Unable to read array info for %s: %s',
                          array_id, exc)
                info = _error_info(str(exc))
            else:
                # One read of controllers and space serves both parts.
                info = _summary_from(*items, detailed=detailed)
                info.update(self._collect_stats(array, array_id,
                                                items[1], items[2]))

        info['cinder_name'] = array_id
        info['cinder_id'] = array_id
        info['target'] = entry.target if entry is not None else array.target
        LOG.debug('Found FlashArray info for %s: %s', array_id, info)
        return base.APIDictWrapper(info)

    def _get_volume_stats(self, client, vol_id):
        """Space and performance of Cinder volume ``vol_id`` on ``client``.

        Raises LookupError when the volume is not on that array.
        """
        name = 'volume-%s-cinder' % vol_id
        resp = client.get_volumes(names=[name])
        found = registry.items(resp)
        if not found:
            # Volumes in a pod are named 'pod::volume-...'.
            name = '*::' + name
            resp = client.get_volumes(names=[name])
            found = registry.items(resp)
        if not found:
            detail = ('no match' if registry.ok(resp)
                      else registry.error_message(resp))
            raise LookupError('Volume %s not found: %s' % (vol_id, detail))

        space = registry.attr(found[0], 'space')
        perf = registry.first(client.get_volumes_performance(names=[name]))
        stats = {
            'total': adjust_purity_size(
                registry.attr(space, 'total_physical', 0)),
            'snapshots': adjust_purity_size(
                registry.attr(space, 'snapshots', 0)),
            'volumes': adjust_purity_size(registry.attr(space, 'unique', 0)),
            # Numeric: the volume template applies floatformat itself.
            'data_reduction': registry.attr(space, 'data_reduction', 1.0),
            'thin_provisioning': registry.attr(space, 'thin_provisioning',
                                               1.0),
            'total_reduction': registry.attr(space, 'total_reduction', 1.0),
            'reads_per_sec': registry.attr(perf, 'reads_per_sec', 0),
            'writes_per_sec': registry.attr(perf, 'writes_per_sec', 0),
            'output_per_sec': adjust_purity_size(
                registry.attr(perf, 'read_bytes_per_sec', 0)),
            'input_per_sec': adjust_purity_size(
                registry.attr(perf, 'write_bytes_per_sec', 0)),
            'usec_per_read_op': registry.attr(perf, 'usec_per_read_op', 0),
            'usec_per_write_op': registry.attr(perf, 'usec_per_write_op', 0),
        }
        LOG.debug('Volume %s stats: %s', vol_id, stats)
        return stats

    def get_volume_info(self, volume):
        """Wrap a Cinder volume as a PureVolume carrying array statistics.

        Admins get the backend from the volume's host attribute; project
        users' volumes are looked up on each configured array in turn.
        """
        try:
            host = getattr(volume, 'os-vol-host-attr:host', None)
        except Exception:
            host = None
        backend = registry.backend_from_host(host)
        stats = {}
        if backend:
            array = self._get_array(backend)
            if not isinstance(array, ErrorStateArray):
                try:
                    stats = self._get_volume_stats(array, volume.id)
                except Exception as exc:
                    LOG.warning('Failed to get Everpure volume info for %s '
                                'from %s: %s', volume.id, backend, exc)
        else:
            seen = set()
            for entry in self._entries():
                if entry.target in seen:
                    continue
                seen.add(entry.target)
                array = self._get_array(entry.backend_name)
                if isinstance(array, ErrorStateArray):
                    continue
                try:
                    stats = self._get_volume_stats(array, volume.id)
                    break
                except Exception as exc:
                    LOG.debug('Volume %s not on %s: %s',
                              volume.id, entry.backend_name, exc)
            if not stats:
                LOG.debug('Volume %s not found on any configured array',
                          volume.id)

        stats.update(volume.to_dict())
        return pure_cinder_api.PureVolume(base.APIDictWrapper(stats))

    def get_volumes_data(self, volumes):
        return [self.get_volume_info(volume) for volume in volumes]

    def get_host_stats(self, host):
        """Per-host statistics are not collected yet."""
        return {}
