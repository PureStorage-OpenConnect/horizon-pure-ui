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

"""Manila share -> Everpure backend -> array object resolution.

Also home of the object-naming rules both Manila drivers follow, shared by
``pure_flash_blade`` and ``pure_fa_files``:

* FlashBlade: file system ``(share_name_template % <share INSTANCE id>)
  + '-manila'``; export path ``<data VIP>:/<file system>``, so the last
  path segment of an export location is the file system name.
* FlashArray Files: managed directory ``<parent_fs>:share-<SHARE id>-manila``
  regardless of the template; the export name may differ (mount_point_name)
  so the directory is never derived from an export path.

Nothing here raises towards a view: ``get_share_info`` always returns a
dict and reports problems in its ``error`` key.
"""

import datetime
import functools
import logging
import re

from django.conf import settings

from horizon_pure.api import registry


LOG = logging.getLogger(__name__)

DEFAULT_SHARE_NAME_TEMPLATE = 'share-%s'
MANILA_SUFFIX = '-manila'
# Manila ids are dashed UUIDs; matched case-insensitively.
_UUID = (r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
         r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')


def share_name_template():
    """The manila.conf share_name_template mirrored into Horizon settings.

    Anything that is not a string holding exactly one ``%s`` falls back to
    the default with a warning rather than breaking every page.
    """
    template = getattr(settings, 'PURE_MANILA_SHARE_NAME_TEMPLATE', None)
    if not template:
        return DEFAULT_SHARE_NAME_TEMPLATE
    if not isinstance(template, str) or template.count('%s') != 1:
        LOG.warning('PURE_MANILA_SHARE_NAME_TEMPLATE %r must contain exactly '
                    'one %%s; using %r', template,
                    DEFAULT_SHARE_NAME_TEMPLATE)
        return DEFAULT_SHARE_NAME_TEMPLATE
    return template


@functools.lru_cache(maxsize=8)
def _compile_name_re(template):
    prefix, suffix = template.split('%s', 1)
    return re.compile('^%s(?P<id>%s)%s%s$' % (
        re.escape(prefix), _UUID, re.escape(suffix),
        re.escape(MANILA_SUFFIX)))


def manila_fs_name_re(template=None):
    """Regex matching ``template % <uuid> + '-manila'``; group ``id``.

    With no ``template`` the configured share_name_template is used. The
    FlashArray Files driver ignores the template, so it passes the default.
    """
    return _compile_name_re(template or share_name_template())


FA_DIRECTORY_RE = manila_fs_name_re(DEFAULT_SHARE_NAME_TEMPLATE)


def id_from_name(name, pattern=None):
    """The UUID embedded in a Manila object name, or None."""
    match = (pattern or manila_fs_name_re()).match(name or '')
    return match.group('id') if match else None


def fb_file_system_name(instance_id, template=None):
    """FlashBlade file system name for a share instance id."""
    return (template or share_name_template()) % instance_id + MANILA_SUFFIX


def fa_directory_short_name(share_id):
    """FlashArray managed directory name (without the parent file system)."""
    return DEFAULT_SHARE_NAME_TEMPLATE % share_id + MANILA_SUFFIX


def name_from_export_path(path):
    """'10.0.0.1:/share-x-manila' or '[fd00::1]:/share-x-manila' -> name."""
    if not isinstance(path, str):
        return None
    text = path.strip()
    if ':/' in text:
        # rsplit keeps IPv6 bracket forms intact.
        text = text.rsplit(':/', 1)[1]
    text = text.strip('/')
    if not text:
        return None
    return text.rsplit('/', 1)[-1] or None


def _path_of(location):
    """The path of an export location object, dict or plain string."""
    if isinstance(location, str):
        return location
    if isinstance(location, dict):
        return location.get('path')
    return getattr(location, 'path', None)


def fb_file_system_names(share, export_paths=(), instance_ids=(),
                         template=None):
    """Candidate FlashBlade file system names for a share.

    Names come from the export paths first, then from the share instance
    ids through the template; when no paths are given the share's own
    ``export_locations`` attribute is consulted. The result is de-duplicated
    with order preserved.
    """
    paths = list(export_paths or [])
    if not paths:
        for location in getattr(share, 'export_locations', None) or []:
            path = _path_of(location)
            if path:
                paths.append(path)
    names = []
    for path in paths:
        name = name_from_export_path(path)
        if name and name not in names:
            names.append(name)
    for instance_id in instance_ids or []:
        if not instance_id:
            continue
        name = fb_file_system_name(instance_id, template)
        if name not in names:
            names.append(name)
    return names


def to_datetime(epoch_ms):
    """Purity ``created`` (milliseconds since the epoch) -> aware datetime.

    None (or garbage) stays None so templates can apply ``|date`` safely.
    """
    try:
        return datetime.datetime.fromtimestamp(
            float(epoch_ms) / 1000.0, tz=datetime.timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _manila_api():
    """The manila-ui API module, or None when manila-ui is not installed."""
    try:
        from manila_ui.api import manila as manila_api
    except ImportError:
        LOG.debug('manila-ui is not installed; export locations and share '
                  'instances are unavailable')
        return None
    return manila_api


def _fb_api():
    # Imported here: pure_flash_blade imports this module for the naming
    # helpers, so a module-level import would be circular.
    from horizon_pure.api import pure_flash_blade
    return pure_flash_blade.FlashBladeAPI()


def _fa_api():
    from horizon_pure.api import pure_fa_files
    return pure_fa_files.FlashArrayFilesAPI()


def _share_locations(request, share, is_admin):
    """(export paths, share instance ids) known to Manila for ``share``.

    Export locations come from manila-ui's API, then from the share object
    itself. Admins additionally get the share instance ids (needed when a
    share has no export location yet) from the instance list, which is
    only consulted when no path was found because it lists every instance
    in the cloud.
    """
    share_id = getattr(share, 'id', None)
    manila_api = _manila_api()
    paths = []
    if manila_api is not None and share_id:
        try:
            locations = manila_api.share_export_location_list(
                request, share_id) or []
        except Exception as exc:
            LOG.warning('Unable to list export locations of share %s: %s',
                        share_id, exc)
            locations = []
        paths = [p for p in (_path_of(loc) for loc in locations) if p]
    if not paths:
        locations = getattr(share, 'export_locations', None) or []
        paths = [p for p in (_path_of(loc) for loc in locations) if p]

    instance_ids = []
    if not paths and is_admin and manila_api is not None and share_id:
        try:
            instances = manila_api.share_instance_list(request) or []
        except Exception as exc:
            LOG.warning('Unable to list share instances for share %s: %s',
                        share_id, exc)
            instances = []
        for instance in instances:
            if getattr(instance, 'share_id', None) != share_id:
                continue
            instance_id = getattr(instance, 'id', None)
            if instance_id and instance_id not in instance_ids:
                instance_ids.append(instance_id)
    return paths, instance_ids


def get_share_info_for_backend(request, share, entry, names=None):
    """Look ``share`` up on one configured Manila backend.

    Returns {'found', 'kind', 'backend_name', 'entry', 'file_systems',
    'directory', 'error'}. ``names`` are the FlashBlade candidate names;
    when None they are derived from the share. Never raises.
    """
    result = {
        'found': False,
        'kind': entry.kind,
        'backend_name': entry.backend_name,
        'entry': entry,
        'file_systems': [],
        'directory': None,
        'error': None,
    }
    try:
        # A backend whose client could not be built, or whose array has
        # stopped answering, is remembered by the registry for a while:
        # this raises at once instead of paying another timeout below.
        registry.get_client(entry)
    except registry.ArrayUnavailable as exc:
        result['error'] = str(exc)
        return result

    try:
        if entry.kind == 'fb':
            if names is None:
                is_admin = request_is_admin(request)
                paths, instance_ids = _share_locations(request, share,
                                                       is_admin)
                names = fb_file_system_names(share, paths, instance_ids)
            if not names:
                result['error'] = (
                    '%s: no file system name could be derived for the '
                    'share (no export locations or share instances '
                    'visible)' % entry.backend_name)
                return result
            api = _fb_api()
            for name in names:
                info = api.get_file_system_info(entry.backend_name, name)
                if info is not None:
                    result['file_systems'].append(info)
            result['found'] = bool(result['file_systems'])
            if not result['found']:
                result['error'] = '%s: no file system named %s' % (
                    entry.backend_name, ' or '.join(names))
        else:
            share_id = getattr(share, 'id', None)
            if not share_id:
                result['error'] = '%s: share has no id' % entry.backend_name
                return result
            directory = _fa_api().get_directory_info(entry.backend_name,
                                                     share_id)
            result['directory'] = directory
            result['found'] = directory is not None
            if not result['found']:
                result['error'] = '%s: no managed directory %s:%s' % (
                    entry.backend_name, entry.parent_fs,
                    fa_directory_short_name(share_id))
    except registry.ArrayUnavailable as exc:
        # The array, not the share, failed; the message names the backend
        # and must not be mistaken for "no such object".
        LOG.warning('Everpure share lookup on %s failed: %s',
                    entry.backend_name, exc)
        result['error'] = str(exc)
    except Exception as exc:
        LOG.exception('Everpure share lookup on %s failed',
                      entry.backend_name)
        result['error'] = '%s: %s' % (entry.backend_name, exc)
    return result


def request_is_admin(request):
    """True for a superuser request; never raises (used in error paths)."""
    user = getattr(request, 'user', None)
    return bool(getattr(user, 'is_superuser', False))


def get_share_info(request, share):
    """Everything the Everpure share tab needs for ``share``.

    Admin shares carry ``host`` ('<host>@<backend>#<pool>'), which picks
    the backend directly; otherwise every configured Manila backend is
    tried in settings order and the first hit wins. FlashBlade lookups
    need the file system name (from export locations or, for admins,
    share instances); FlashArray Files lookups need only the share id.
    """
    is_admin = request_is_admin(request)
    info = {
        'configured': False,
        'kind': None,
        'backend_name': None,
        'entry': None,
        'found': False,
        'error': None,
        'is_admin': is_admin,
        'file_systems': [],
        'directory': None,
        'share_id': getattr(share, 'id', None),
        'export_paths': [],
        'candidate_names': [],
    }
    try:
        candidates = registry.entries(service='manila')
        if not candidates:
            return info
        info['configured'] = True

        host = getattr(share, 'host', None)
        backend = registry.backend_from_host(host)
        entry = registry.find('manila', backend) if backend else None
        if entry is not None:
            candidates = [entry]
        elif backend:
            LOG.debug('Share %s is on backend %s, which is not an Everpure '
                      'Manila backend in settings; trying all of them',
                      info['share_id'], backend)

        names = None
        if any(candidate.kind == 'fb' for candidate in candidates):
            paths, instance_ids = _share_locations(request, share, is_admin)
            names = fb_file_system_names(share, paths, instance_ids)
            info['export_paths'] = paths
            info['candidate_names'] = names

        errors = []
        for candidate in candidates:
            result = get_share_info_for_backend(request, share, candidate,
                                                names=names)
            if result['error']:
                errors.append(result['error'])
            if result['found']:
                info.update({
                    'kind': result['kind'],
                    'backend_name': result['backend_name'],
                    'entry': candidate,
                    'found': True,
                    'file_systems': result['file_systems'],
                    'directory': result['directory'],
                })
                break
        else:
            info['error'] = '; '.join(errors) or None
            LOG.debug('Share %s not found on Everpure backends %s: %s',
                      info['share_id'],
                      [candidate.backend_name for candidate in candidates],
                      info['error'])
    except Exception as exc:
        LOG.exception('Everpure share info failed for share %s',
                      info['share_id'])
        info['error'] = str(exc)
    return info
