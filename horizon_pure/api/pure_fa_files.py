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

"""Manila-facing FlashArray Files queries (PURE_FLASH_ARRAY_FILES backends).

A Manila share is the managed directory ``<parent_fs>:share-<share id>-
manila`` with an NFS policy ``share-<id>-manila-nfs`` and a quota policy
``share-<id>-manila-quota``. Array-level data is shared with the Cinder
module through ``pure_flash_array.get_array_summary``.

All sizes are MiB, ratios are "x.xx to 1" strings, ``created`` values are
aware datetimes. An unusable backend yields ``status='Error: ...'`` rows
and listings return []; only ``get_directory_info`` raises, and only
``registry.ArrayUnavailable``, so that "the array failed" is never
reported as "the directory does not exist".
"""

import logging

from openstack_dashboard.api import base

from horizon_pure.api import pure_flash_array
from horizon_pure.api import pure_manila
from horizon_pure.api import registry


LOG = logging.getLogger(__name__)

#: directories in the parent file system that are never Manila shares
HIDDEN_DIRECTORIES = ('root', 'manila-zero-baseline')
#: client_name the Manila driver stamps on its directory snapshots
SNAPSHOT_CLIENT = 'openstack'
#: suffix of the driver's baseline snapshot (never a user snapshot)
PRIVATE_SUFFIX = 'private'
#: marker of the undo snapshots Purity creates for overwrite copies
COPY_MARKER = '.copy.'
#: most recent snapshots returned in ``snapshot_list``
MAX_SNAPSHOTS = 50

_STAT_KEYS = (
    'total_used',
    'total_available',
    'total_directory_count',
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
        'snapshots': 0,
        'unique': 0,
        'volumes': 0,
        'data_reduction': registry.ratio(None),
        'thin_provisioning': registry.ratio(None),
        'total_reduction': registry.ratio(None),
        'directory_count': 0,
    }


def _perf_dict(perf):
    """Performance keys from a directory performance item (None -> 0)."""
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


def directory_name(parent_fs, share_id):
    """'<parent_fs>:share-<share_id>-manila'."""
    return '%s:%s' % (parent_fs, pure_manila.fa_directory_short_name(share_id))


def directory_dict(item):
    """The listing dict for a managed directory item.

    ``used`` is ``space.total_used`` (physical); ``virtual`` is the
    logical size the share tab shows alongside it.
    """
    space = registry.attr(item, 'space')
    short_name = registry.attr(item, 'directory_name', '')
    return {
        'name': registry.attr(item, 'name', ''),
        'directory_name': short_name,
        'path': registry.attr(item, 'path', ''),
        'share_id': pure_manila.id_from_name(short_name,
                                             pure_manila.FA_DIRECTORY_RE),
        'used': registry.to_mib(registry.attr(space, 'total_used', 0)),
        'unique': registry.to_mib(registry.attr(space, 'unique', 0)),
        'snapshots': registry.to_mib(registry.attr(space, 'snapshots', 0)),
        'virtual': registry.to_mib(registry.attr(space, 'virtual', 0)),
        'total_physical': registry.to_mib(
            registry.attr(space, 'total_physical', 0)),
        'data_reduction': registry.ratio(
            registry.attr(space, 'data_reduction')),
        'created': pure_manila.to_datetime(registry.attr(item, 'created')),
        'destroyed': bool(registry.attr(item, 'destroyed', False)),
    }


def snapshot_suffix(snap):
    """The snapshot suffix, parsed from the name when the model lacks it.

    Purity//FA 6.10 answers ``directory-snapshots`` without a ``suffix``
    field (seen on the lab array); the name is always
    ``<fs>:<dir>.<client_name>.<suffix>``, so fall back to that.
    """
    suffix = registry.attr(snap, 'suffix')
    if suffix:
        return suffix
    name = registry.attr(snap, 'name', '') or ''
    marker = '.%s.' % SNAPSHOT_CLIENT
    if marker in name:
        return name.rsplit(marker, 1)[1]
    return ''


def is_manila_snapshot(snap):
    """True for a live snapshot the Manila driver made for a user.

    Excludes the driver's ``.private`` baseline, Purity's ``.copy.`` undo
    snapshots, snapshots of other clients and destroyed ones.
    """
    if registry.attr(snap, 'client_name') != SNAPSHOT_CLIENT:
        return False
    if snapshot_suffix(snap) == PRIVATE_SUFFIX:
        return False
    if COPY_MARKER in (registry.attr(snap, 'name', '') or ''):
        return False
    return not registry.attr(snap, 'destroyed', False)


class FlashArrayFilesAPI(object):
    """Queries for the Manila FlashArray Files backends."""

    get_array_summary = staticmethod(pure_flash_array.get_array_summary)

    def _entries(self):
        return registry.entries(service='manila', kind='fa')

    def get_backend_list(self):
        return [entry.backend_name for entry in self._entries()]

    def _resolve(self, backend_name):
        """(entry, client, error) for a backend; client is None on error."""
        entry = registry.find('manila', backend_name)
        if entry is None or entry.kind != 'fa':
            LOG.debug('Backend %s is not configured in '
                      'PURE_FLASH_ARRAY_FILES', backend_name)
            return None, None, 'Not in config'
        try:
            return entry, registry.get_client(entry), None
        except registry.ArrayUnavailable as exc:
            return entry, None, str(exc)

    @staticmethod
    def _list_directories(client, parent_fs):
        """Live directories of ``parent_fs`` minus root and the baseline.

        The FlashArray SDK paginates for us; limit/offset are not passed.
        """
        resp = client.get_directories(file_system_names=[parent_fs],
                                      destroyed=False)
        if not registry.ok(resp):
            LOG.warning('Unable to list directories of %s: %s', parent_fs,
                        registry.error_message(resp))
            return []
        result = []
        for item in registry.items(resp):
            if registry.attr(item, 'directory_name') in HIDDEN_DIRECTORIES:
                continue
            if registry.attr(item, 'destroyed', False):
                continue
            result.append(item)
        return result

    @staticmethod
    def _count_directories(client, parent_fs):
        """Live, non-hidden directories of ``parent_fs``, array-counted.

        One call with ``limit=1`` and ``total_item_count=True`` instead
        of paging through every directory on each index load; an array
        without the count field falls back to the listing. Never
        ``names=[root, baseline]``: a FlashArray ``names=`` lookup fails
        as a whole when any name is missing, and the baseline only exists
        once the Manila driver has started.
        """
        hidden = ' and '.join("directory_name!='%s'" % name
                              for name in HIDDEN_DIRECTORIES)
        resp = client.get_directories(file_system_names=[parent_fs],
                                      destroyed=False, limit=1,
                                      total_item_count=True, filter=hidden)
        if not registry.ok(resp):
            LOG.warning('Unable to count directories of %s: %s', parent_fs,
                        registry.error_message(resp))
            return 0
        count = getattr(resp, 'total_item_count', None)
        if count is None:
            return len(FlashArrayFilesAPI._list_directories(client,
                                                            parent_fs))
        return count

    def get_array_info(self, backend_name, detailed=False):
        """Array summary for one backend as an APIDictWrapper.

        The FlashArray summary keys (see pure_flash_array) plus
        ``parent_fs`` and ``directory_count``; always carries
        ``backend_id``, ``backend_name``, ``target`` and ``status``.
        """
        entry, client, error = self._resolve(backend_name)
        if client is None:
            info = _error_info(error)
        else:
            try:
                info = pure_flash_array.get_array_summary(client,
                                                          detailed=detailed)
                info['directory_count'] = self._count_directories(
                    client, entry.parent_fs)
            except Exception as exc:
                LOG.warning('Unable to read FlashArray Files info for %s: %s',
                            backend_name, exc)
                info = _error_info(str(exc))
        info['backend_id'] = backend_name
        info['backend_name'] = backend_name
        info['target'] = entry.target if entry is not None else backend_name
        info['parent_fs'] = (entry.parent_fs if entry is not None
                             else registry.DEFAULT_PARENT_FS)
        LOG.debug('Found FlashArray Files info for %s: %s', backend_name,
                  info)
        return base.APIDictWrapper(info)

    def get_total_stats(self):
        """Capacity (MiB) and directory count over the distinct arrays.

        Each target is counted once. An empty configuration yields an
        empty dict.
        """
        stats = {}
        seen = set()
        for entry in self._entries():
            if entry.target in seen:
                LOG.debug('Skipping %s: FlashArray %s already counted',
                          entry.backend_name, entry.target)
                continue
            seen.add(entry.target)
            if not stats:
                stats = _empty_stats()
            info = self.get_array_info(entry.backend_name)
            stats['total_used'] += info['total']
            stats['total_available'] += info['capacity']
            stats['total_directory_count'] += info['directory_count']
        LOG.debug('Found total stats for FlashArray Files: %s', stats)
        return stats

    def list_manila_directories(self, backend_name):
        """Manila share directories in the backend's parent file system.

        A directory counts when its name is ``share-<uuid>-manila`` and it
        is not destroyed; ``root`` and the zero baseline are hidden. [] on
        any error.
        """
        entry, client, error = self._resolve(backend_name)
        if client is None:
            LOG.warning('Cannot list directories on %s: %s', backend_name,
                        error)
            return []
        result = []
        try:
            for item in self._list_directories(client, entry.parent_fs):
                short_name = registry.attr(item, 'directory_name', '')
                if pure_manila.FA_DIRECTORY_RE.match(short_name):
                    result.append(directory_dict(item))
        except Exception as exc:
            LOG.warning('Failed to list directories on %s: %s',
                        backend_name, exc)
        return result

    @staticmethod
    def _quota(client, name, short_name):
        """The driver's quota rule for the directory (policy <dir>-quota).

        A directory may carry several quota policies and the array lists
        one item per policy, so the lookup is pinned to the driver's own
        policy rather than taking whichever item comes first. A missing
        policy is HTTP 400 and shows as "No quota".
        """
        policy = short_name + '-quota'
        resp = client.get_directory_quotas(directory_names=[name],
                                           policy_names=[policy])
        quota = registry.first(resp)
        if quota is None:
            if not registry.ok(resp):
                LOG.debug('No quota for %s: %s', name,
                          registry.error_message(resp))
            return {'quota_limit': None, 'quota_usage': 0.0,
                    'percentage_used': None, 'quota_enforced': False}
        limit = registry.attr(quota, 'quota_limit')
        return {
            'quota_limit': (registry.to_mib(limit) if limit is not None
                            else None),
            'quota_usage': registry.to_mib(registry.attr(quota, 'usage', 0)),
            'percentage_used': registry.attr(quota, 'percentage_used'),
            'quota_enforced': bool(registry.attr(quota, 'enforced', False)),
        }

    @staticmethod
    def _nfs_rules(client, short_name):
        policy = short_name + '-nfs'
        resp = client.get_policies_nfs_client_rules(policy_names=[policy])
        if not registry.ok(resp):
            # HTTP 400 "Policy does not exist." when no access rule was
            # ever granted; nothing to show.
            LOG.debug('No NFS rules for %s: %s', policy,
                      registry.error_message(resp))
            return []
        rules = []
        for rule in registry.items(resp):
            versions = registry.attr(rule, 'nfs_version', []) or []
            rules.append({
                'client': registry.attr(rule, 'client', ''),
                'permission': registry.attr(rule, 'permission', ''),
                'access': registry.attr(rule, 'access', ''),
                'nfs_version': list(versions),
            })
        return rules

    @staticmethod
    def _exports(client, name):
        resp = client.get_directory_exports(directory_names=[name])
        if not registry.ok(resp):
            LOG.debug('No exports for %s: %s', name,
                      registry.error_message(resp))
            return []
        exports = []
        for export in registry.items(resp):
            policy = registry.attr(export, 'policy')
            exports.append({
                'export_name': registry.attr(export, 'export_name', ''),
                'enabled': bool(registry.attr(export, 'enabled', False)),
                'policy': registry.attr(policy, 'name', ''),
            })
        return exports

    @staticmethod
    def _snapshots(client, name):
        """(count, newest-first list of {'suffix', 'created'}) for a dir."""
        resp = client.get_directory_snapshots(source_names=[name])
        if not registry.ok(resp):
            LOG.debug('Unable to list snapshots of %s: %s', name,
                      registry.error_message(resp))
            return 0, []
        found = [snap for snap in registry.items(resp)
                 if is_manila_snapshot(snap)]
        found.sort(key=lambda snap: registry.attr(snap, 'created', 0) or 0,
                   reverse=True)
        listing = [{
            'suffix': snapshot_suffix(snap),
            'created': pure_manila.to_datetime(
                registry.attr(snap, 'created')),
        } for snap in found[:MAX_SNAPSHOTS]]
        return len(found), listing

    def get_directory_info(self, backend_name, share_id, detailed=True):
        """Everything about the directory of ``share_id``, or None.

        Listing keys plus ``quota_limit`` (MiB or None), ``quota_usage``,
        ``percentage_used``, ``quota_enforced``, ``nfs_rules`` (list of
        {'client', 'permission', 'access', 'nfs_version'}), ``exports``
        (list of {'export_name', 'enabled', 'policy'}), ``snapshot_count``,
        ``snapshot_list`` ([{'suffix', 'created'}], newest first, at most
        MAX_SNAPSHOTS; ``snapshots`` stays the MiB figure), the performance
        keys, ``array_name``, ``version``, ``model``, ``target``,
        ``parent_fs`` and ``backend_name``. None when the directory is
        missing or destroyed. Raises registry.ArrayUnavailable when the
        backend is not configured or the array cannot be read, so a
        failure is never reported as "not found".
        """
        entry, client, error = self._resolve(backend_name)
        if client is None:
            LOG.warning('Cannot read share %s on %s: %s', share_id,
                        backend_name, error)
            raise registry.ArrayUnavailable(error)
        name = directory_name(entry.parent_fs, share_id)
        short_name = pure_manila.fa_directory_short_name(share_id)
        try:
            resp = client.get_directories(names=[name])
            if not registry.ok(resp) and not registry.not_found(resp):
                raise registry.ArrayUnavailable('%s: %s' % (
                    backend_name, registry.error_message(resp)))
            item = registry.first(resp)
            if item is None:
                LOG.debug('Directory %s not on %s: %s', name, backend_name,
                          'no match' if registry.ok(resp)
                          else registry.error_message(resp))
                return None
            if registry.attr(item, 'destroyed', False):
                LOG.debug('Directory %s on %s is destroyed', name,
                          backend_name)
                return None
            info = directory_dict(item)
            info.update(self._quota(client, name, short_name))
            info['nfs_rules'] = self._nfs_rules(client, short_name)
            info['exports'] = self._exports(client, name)
            info['snapshot_count'], info['snapshot_list'] = self._snapshots(
                client, name)
            if detailed:
                info.update(_perf_dict(registry.first(
                    client.get_directories_performance(names=[name]))))
            array = registry.first(client.get_arrays())
            info['array_name'] = registry.attr(array, 'name', 'Unknown')
            info['version'] = registry.attr(array, 'version', 'Unknown')
            controller = registry.first(client.get_controllers())
            info['model'] = registry.attr(controller, 'model', 'Unknown')
            info['target'] = entry.target
            info['parent_fs'] = entry.parent_fs
            info['backend_name'] = backend_name
            return info
        except registry.ArrayUnavailable:
            raise
        except Exception as exc:
            LOG.warning('Failed to read share %s on %s: %s', share_id,
                        backend_name, exc)
            raise registry.ArrayUnavailable(
                '%s: %s' % (backend_name, exc)) from exc
