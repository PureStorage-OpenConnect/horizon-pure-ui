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

"""Manila-facing FlashBlade queries (PURE_FLASH_BLADES backends).

Clients come from ``horizon_pure.api.registry`` and are built on first
use. All sizes are MiB (templates render them with ``mb_float_format``),
reduction ratios are "x.xx to 1" strings and ``created`` values are aware
datetimes. An unusable backend yields ``status='Error: ...'`` rows and
listings return []; only ``get_file_system_info`` raises, and only
``registry.ArrayUnavailable``, so that "the array failed" is never
reported as "the file system does not exist".
"""

import logging

from openstack_dashboard.api import base

from horizon_pure.api import pure_manila
from horizon_pure.api import registry


LOG = logging.getLogger(__name__)

#: file systems fetched per page while listing (FlashBlade paginates with a
#: continuation token; the SDK does not auto-paginate get_file_systems)
PAGE_LIMIT = 500
#: safety net against a continuation token that never ends
MAX_PAGES = 200

_STAT_KEYS = (
    'total_used',
    'total_available',
    'total_file_system_count',
    'total_snapshot_count',
)


def _empty_stats():
    return dict.fromkeys(_STAT_KEYS, 0)


def _error_info(message):
    return {
        'id': '1',
        'status': 'Error: %s' % message,
        'array_name': 'Unknown',
        'version': 'Unknown',
        'model': 'Unknown',
        'capacity': 0,
        'total': 0,
        'unique': 0,
        'snapshots': 0,
        'virtual': 0,
        'total_provisioned': 0,
        'data_reduction': registry.ratio(None),
        'file_system_count': 0,
        'snapshot_count': 0,
    }


def _perf_dict(perf):
    """Performance keys from a FlashBlade performance item (None -> 0)."""
    return {
        'reads_per_sec': registry.attr(perf, 'reads_per_sec', 0),
        'writes_per_sec': registry.attr(perf, 'writes_per_sec', 0),
        'output_per_sec': registry.to_mib(
            registry.attr(perf, 'read_bytes_per_sec', 0)),
        'input_per_sec': registry.to_mib(
            registry.attr(perf, 'write_bytes_per_sec', 0)),
        'usec_per_read_op': registry.attr(perf, 'usec_per_read_op', 0),
        'usec_per_write_op': registry.attr(perf, 'usec_per_write_op', 0),
    }


def _count(resp):
    """Object count from a total_only=True response; None on error."""
    if not registry.ok(resp):
        return None
    count = getattr(resp, 'total_item_count', None)
    if count is None:
        count = len(registry.items(resp))
    return count


def array_identity(client):
    """``array_name``, ``version`` and ``model`` from get_arrays().

    Raises registry.ArrayUnavailable when the array cannot be read.
    """
    resp = client.get_arrays()
    array = registry.first(resp)
    if array is None:
        raise registry.ArrayUnavailable(
            'Unable to read array properties (%s)'
            % registry.error_message(resp))
    return {
        'id': registry.attr(array, 'id', '1'),
        'array_name': registry.attr(array, 'name', 'Unknown'),
        'version': registry.attr(array, 'version', 'Unknown'),
        'model': registry.attr(array, 'product_type', 'Unknown'),
    }


def get_array_summary(client, detailed=False):
    """Array-level summary for a FlashBlade client.

    Keys: ``id``, ``array_name``, ``version``, ``model`` (product type),
    ``status`` ('Connected'), ``capacity``, ``total`` (physical used),
    ``unique``, ``snapshots``, ``virtual``, ``total_provisioned`` (MiB),
    ``data_reduction`` ("x.xx to 1"); with ``detailed`` also
    ``reads_per_sec``, ``writes_per_sec`` (IOPS), ``output_per_sec``,
    ``input_per_sec`` (read/write MiB per second), ``usec_per_read_op``
    and ``usec_per_write_op``.

    Raises registry.ArrayUnavailable when get_arrays fails; space and
    performance failures degrade to zeros.
    """
    info = array_identity(client)
    info.update({
        'status': 'Connected',
        'capacity': 0,
        'total': 0,
        'unique': 0,
        'snapshots': 0,
        'virtual': 0,
        'total_provisioned': 0,
        'data_reduction': registry.ratio(None),
    })

    space_item = registry.first(client.get_arrays_space())
    if space_item is None:
        LOG.warning('Unable to read space for FlashBlade %s',
                    info['array_name'])
    else:
        space = registry.attr(space_item, 'space')
        info.update({
            'capacity': registry.to_mib(
                registry.attr(space_item, 'capacity', 0)),
            'total': registry.to_mib(
                registry.attr(space, 'total_physical', 0)),
            'unique': registry.to_mib(registry.attr(space, 'unique', 0)),
            'snapshots': registry.to_mib(
                registry.attr(space, 'snapshots', 0)),
            'virtual': registry.to_mib(registry.attr(space, 'virtual', 0)),
            'total_provisioned': registry.to_mib(
                registry.attr(space, 'total_provisioned', 0)),
            'data_reduction': registry.ratio(
                registry.attr(space, 'data_reduction')),
        })

    if detailed:
        perf = registry.first(client.get_arrays_performance())
        info.update(_perf_dict(perf))
    return info


def file_system_dict(fs, pattern=None):
    """The listing dict for a FlashBlade file system item.

    ``used`` is ``space.virtual`` (what the driver compares against the
    share size); ``total_physical`` is the footprint on flash.
    """
    space = registry.attr(fs, 'space')
    nfs = registry.attr(fs, 'nfs')
    smb = registry.attr(fs, 'smb')
    name = registry.attr(fs, 'name', '')
    return {
        'name': name,
        'share_instance_id': pure_manila.id_from_name(name, pattern),
        'provisioned': registry.to_mib(registry.attr(fs, 'provisioned', 0)),
        'used': registry.to_mib(registry.attr(space, 'virtual', 0)),
        'total_physical': registry.to_mib(
            registry.attr(space, 'total_physical', 0)),
        'unique': registry.to_mib(registry.attr(space, 'unique', 0)),
        'snapshots': registry.to_mib(registry.attr(space, 'snapshots', 0)),
        'data_reduction': registry.ratio(
            registry.attr(space, 'data_reduction')),
        'nfs_rules': registry.attr(nfs, 'rules', '') or '',
        'nfs_v3': bool(registry.attr(nfs, 'v3_enabled', False)),
        'nfs_v41': bool(registry.attr(nfs, 'v4_1_enabled', False)),
        'smb_enabled': bool(registry.attr(smb, 'enabled', False)),
        'hard_limit': bool(registry.attr(fs, 'hard_limit_enabled', False)),
        'created': pure_manila.to_datetime(registry.attr(fs, 'created')),
        'destroyed': bool(registry.attr(fs, 'destroyed', False)),
    }


class FlashBladeAPI(object):
    """Queries for the Manila FlashBlade backends in PURE_FLASH_BLADES."""

    get_array_summary = staticmethod(get_array_summary)

    def _entries(self):
        return registry.entries(service='manila', kind='fb')

    def get_backend_list(self):
        return [entry.backend_name for entry in self._entries()]

    def _resolve(self, backend_name):
        """(entry, client, error) for a backend; client is None on error."""
        entry = registry.find('manila', backend_name)
        if entry is None or entry.kind != 'fb':
            LOG.debug('Backend %s is not configured in PURE_FLASH_BLADES',
                      backend_name)
            return None, None, 'Not in config'
        try:
            return entry, registry.get_client(entry), None
        except registry.ArrayUnavailable as exc:
            return entry, None, str(exc)

    @staticmethod
    def _counts(client):
        """Non-destroyed ``file_system_count`` and ``snapshot_count``.

        Without ``destroyed=False`` FlashBlade counts objects pending
        eradication too, which the listings here never show.
        """
        counts = {'file_system_count': 0, 'snapshot_count': 0}
        try:
            count = _count(client.get_file_systems(destroyed=False,
                                                   total_only=True))
            if count is not None:
                counts['file_system_count'] = count
            count = _count(client.get_file_system_snapshots(
                destroyed=False, total_only=True))
            if count is not None:
                counts['snapshot_count'] = count
        except Exception as exc:
            LOG.warning('Failed to count FlashBlade objects: %s', exc)
        return counts

    def get_array_info(self, backend_name, detailed=False):
        """Array summary for one backend as an APIDictWrapper.

        Always carries ``backend_id``, ``backend_name``, ``target`` and
        ``status``; an unusable backend yields ``status`` 'Error: ...'
        with zeroed values.
        """
        entry, client, error = self._resolve(backend_name)
        if client is None:
            info = _error_info(error)
        else:
            try:
                info = get_array_summary(client, detailed=detailed)
                info.update(self._counts(client))
            except Exception as exc:
                LOG.warning('Unable to read FlashBlade info for %s: %s',
                            backend_name, exc)
                info = _error_info(str(exc))
        info['backend_id'] = backend_name
        info['backend_name'] = backend_name
        info['target'] = entry.target if entry is not None else backend_name
        LOG.debug('Found FlashBlade info for %s: %s', backend_name, info)
        return base.APIDictWrapper(info)

    def get_total_stats(self):
        """Capacity (MiB) and counts summed over the distinct arrays.

        Several backends may point at one array; each target is counted
        once. An empty configuration yields an empty dict.
        """
        stats = {}
        seen = set()
        for entry in self._entries():
            if entry.target in seen:
                LOG.debug('Skipping %s: FlashBlade %s already counted',
                          entry.backend_name, entry.target)
                continue
            seen.add(entry.target)
            if not stats:
                stats = _empty_stats()
            info = self.get_array_info(entry.backend_name)
            stats['total_used'] += info['total']
            stats['total_available'] += info['capacity']
            stats['total_file_system_count'] += info['file_system_count']
            stats['total_snapshot_count'] += info['snapshot_count']
        LOG.debug('Found total stats for FlashBlades: %s', stats)
        return stats

    @staticmethod
    def _iter_file_systems(client):
        """Yield every non-destroyed file system, following the token."""
        kwargs = {'limit': PAGE_LIMIT, 'destroyed': False}
        for _page in range(MAX_PAGES):
            resp = client.get_file_systems(**kwargs)
            if not registry.ok(resp):
                LOG.warning('Unable to list FlashBlade file systems: %s',
                            registry.error_message(resp))
                return
            for fs in registry.items(resp):
                yield fs
            token = getattr(resp, 'continuation_token', None)
            if not token:
                return
            kwargs = dict(kwargs, continuation_token=token)
        LOG.warning('FlashBlade file system listing stopped after %d pages',
                    MAX_PAGES)

    def list_manila_file_systems(self, backend_name):
        """Manila-created file systems on a backend (newest template form).

        A file system counts when its name is ``share_name_template %
        <uuid> + '-manila'`` and it is not destroyed. [] on any error.
        """
        entry, client, error = self._resolve(backend_name)
        if client is None:
            LOG.warning('Cannot list file systems on %s: %s',
                        backend_name, error)
            return []
        pattern = pure_manila.manila_fs_name_re()
        result = []
        try:
            for fs in self._iter_file_systems(client):
                name = registry.attr(fs, 'name', '')
                if not pattern.match(name):
                    continue
                if registry.attr(fs, 'destroyed', False):
                    continue
                result.append(file_system_dict(fs, pattern))
        except Exception as exc:
            LOG.warning('Failed to list file systems on %s: %s',
                        backend_name, exc)
        return result

    @staticmethod
    def _snapshot_count(client, fs_name):
        """Non-destroyed snapshots of ``fs_name``; falls back to a filter."""
        count = _count(client.get_file_system_snapshots(
            names_or_owner_names=[fs_name], destroyed=False,
            total_only=True))
        if count is None:
            count = _count(client.get_file_system_snapshots(
                filter="source.name='%s'" % fs_name, destroyed=False,
                total_only=True))
        return count or 0

    def get_file_system_info(self, backend_name, fs_name, detailed=True):
        """Everything about one file system, or None when it is missing.

        Listing keys plus ``snapshot_count``, ``nfs_v3``, ``nfs_v41``,
        ``smb_enabled``, the performance keys (zeros when the array has
        no sample), ``array_name``, ``version``, ``model``, ``target`` and
        ``backend_name``. None on a missing or destroyed file system.
        Raises registry.ArrayUnavailable when the backend is not configured
        or the array cannot be read, so a failure is never reported as
        "not found"; an unreadable array identity alone degrades to
        'Unknown' and the file-system data is still returned.
        """
        entry, client, error = self._resolve(backend_name)
        if client is None:
            LOG.warning('Cannot read file system %s on %s: %s',
                        fs_name, backend_name, error)
            raise registry.ArrayUnavailable(error)
        try:
            resp = client.get_file_systems(names=[fs_name])
            if not registry.ok(resp) and not registry.not_found(resp):
                raise registry.ArrayUnavailable('%s: %s' % (
                    backend_name, registry.error_message(resp)))
            fs = registry.first(resp)
            if fs is None:
                LOG.debug('File system %s not on %s: %s', fs_name,
                          backend_name, 'no match' if registry.ok(resp)
                          else registry.error_message(resp))
                return None
            if registry.attr(fs, 'destroyed', False):
                LOG.debug('File system %s on %s is destroyed', fs_name,
                          backend_name)
                return None
            info = file_system_dict(fs)
            info['snapshot_count'] = self._snapshot_count(client, fs_name)
            if detailed:
                info.update(_perf_dict(registry.first(
                    client.get_file_systems_performance(names=[fs_name]))))
            try:
                info.update(array_identity(client))
            except registry.ArrayUnavailable as exc:
                # The file system was read; do not turn it into "not found"
                # because /arrays failed right after it.
                LOG.warning('Unable to read array identity for %s on %s: %s',
                            fs_name, backend_name, exc)
                info.update({'id': '1', 'array_name': 'Unknown',
                             'version': 'Unknown', 'model': 'Unknown'})
            info['target'] = entry.target
            info['backend_name'] = backend_name
            return info
        except registry.ArrayUnavailable:
            raise
        except Exception as exc:
            LOG.warning('Failed to read file system %s on %s: %s',
                        fs_name, backend_name, exc)
            raise registry.ArrayUnavailable(
                '%s: %s' % (backend_name, exc)) from exc
