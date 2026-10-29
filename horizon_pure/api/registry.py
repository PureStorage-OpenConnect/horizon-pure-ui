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

"""Array settings registry and lazily built, cached py-pure-client clients.

Settings are parsed afresh on every call (it is cheap and tests override
them). Clients are cached for the life of the process because constructing
one performs REST version discovery over the network, so nothing here may
build a client at import time. A failed construction is remembered for
``FAILURE_TTL`` seconds so an unreachable array does not stall every page;
a client whose array stops answering later is evicted the same way by the
``ClientProxy`` that ``get_client`` hands out.

Response helpers (``ok``, ``items``, ``first``, ``attr``, ``not_found``,
``error_message``) and unit helpers (``to_mib``, ``ratio``) are shared by
every API module.
"""

import logging
import threading
import time

from django.conf import settings
from pypureclient import configuration
from pypureclient import exceptions as pure_exceptions
from pypureclient import flasharray
from pypureclient import flashblade
from urllib3 import exceptions as urllib3_exceptions

import horizon_pure


LOG = logging.getLogger(__name__)

USER_AGENT = 'OpenStack-Horizon-Everpure-UI/%s' % horizon_pure.__version__

#: seconds a failed client build is remembered before it is retried
FAILURE_TTL = 60
DEFAULT_PARENT_FS = 'openstack'
DEFAULT_TIMEOUT = 10
DEFAULT_RETRIES = 1

# (setting name, service, kind), in the order entries() reports them.
_SETTINGS = (
    ('PURE_FLASHARRAYS', 'cinder', 'fa'),
    ('PURE_FLASHBLADES', 'manila', 'fb'),
    ('PURE_FLASHARRAY_FILES', 'manila', 'fa'),
)

_clients = {}
_failures = {}
_lock = threading.Lock()

#: what the SDK lets through when the array itself stops answering: urllib3
#: transport failures (timeouts, refused or hung connections, TLS) and the
#: SDK's own error for a failed (re-)authentication. ErrorResponse objects
#: are returned, not raised, and are not transport failures.
TRANSPORT_ERRORS = (urllib3_exceptions.HTTPError, pure_exceptions.PureError)


class ArrayUnavailable(Exception):
    """A client could not be built for, or could not contact, an array."""


class ArrayEntry(object):
    """One configured array backend.

    ``kind`` is ``'fa'`` or ``'fb'``; ``service`` is ``'cinder'`` or
    ``'manila'``. ``parent_fs`` is only meaningful for Manila FlashArray
    Files entries. ``verify_ssl`` is True when configured or when a
    ``ca_cert`` is given.
    """

    def __init__(self, kind, service, backend_name, target, api_token,
                 verify_ssl=False, ca_cert=None, parent_fs=None):
        self.kind = kind
        self.service = service
        self.backend_name = backend_name
        self.target = target
        self.api_token = api_token
        self.ca_cert = ca_cert or None
        self.verify_ssl = bool(verify_ssl) or bool(self.ca_cert)
        self.parent_fs = parent_fs or DEFAULT_PARENT_FS

    @property
    def key(self):
        return (self.service, self.backend_name)

    @property
    def cache_key(self):
        """Client cache key; the same array shared by several entries."""
        return (self.kind, self.target, self.api_token)

    def __repr__(self):
        # The token must never reach a log line.
        return '<ArrayEntry %s/%s %s target=%s verify_ssl=%s>' % (
            self.service, self.kind, self.backend_name, self.target,
            self.verify_ssl)


def _entry_from_conf(conf, service, kind, setting_name):
    if not isinstance(conf, dict):
        LOG.warning('Ignoring non-dict entry in %s', setting_name)
        return None
    target = conf.get('san_ip') or conf.get('mgmt_ip')
    backend_name = conf.get('backend_name')
    if not target or not backend_name:
        LOG.warning('Ignoring %s entry without backend_name and '
                    'san_ip/mgmt_ip', setting_name)
        return None
    # A missing api_token is kept: the client build fails and the backend
    # shows up as an error row instead of silently disappearing.
    return ArrayEntry(kind, service, backend_name, target,
                      conf.get('api_token'),
                      verify_ssl=conf.get('verify_ssl', False),
                      ca_cert=conf.get('ca_cert'),
                      parent_fs=conf.get('parent_fs'))


def entries(service=None, kind=None):
    """Return the configured ArrayEntry objects, parsed fresh from settings.

    Absent settings yield nothing; entries without a backend_name or a
    san_ip/mgmt_ip are skipped with a warning.
    """
    result = []
    for name, svc, knd in _SETTINGS:
        if service is not None and svc != service:
            continue
        if kind is not None and knd != kind:
            continue
        for conf in getattr(settings, name, None) or []:
            entry = _entry_from_conf(conf, svc, knd, name)
            if entry is not None:
                result.append(entry)
    return result


def find(service, backend_name):
    """Return the entry for (service, backend_name) or None."""
    for entry in entries(service=service):
        if entry.backend_name == backend_name:
            return entry
    return None


def _now():
    """Monotonic clock; a function so tests can patch it."""
    return time.monotonic()


def _build_client(entry):
    """Construct the py-pure-client client for ``entry`` (network I/O).

    PURE_API_RETRIES is applied twice on purpose: as the SDK's own retry
    count for HTTP-level failures (``retries``) and, through the
    ``configuration`` object, as the urllib3 connection retry count. The
    latter otherwise defaults to 3, so a hung array cost timeout x 4 per
    call whatever the setting said.
    """
    retries = getattr(settings, 'PURE_API_RETRIES', DEFAULT_RETRIES)
    config = configuration.Configuration()
    config.retries = retries
    kwargs = {
        'target': entry.target,
        'api_token': entry.api_token,
        'user_agent': USER_AGENT,
        'verify_ssl': entry.verify_ssl,
        'ssl_cert': entry.ca_cert,
        'timeout': getattr(settings, 'PURE_API_TIMEOUT', DEFAULT_TIMEOUT),
        'retries': retries,
        'configuration': config,
    }
    if entry.kind == 'fb':
        return flashblade.Client(**kwargs)
    return flasharray.Client(**kwargs)


class ClientProxy(object):
    """The object ``get_client`` returns: an SDK client that evicts itself.

    Attribute access is forwarded to the wrapped py-pure-client client. A
    method that raises one of TRANSPORT_ERRORS (the array stopped answering
    after the client was built) marks the entry unavailable for FAILURE_TTL
    seconds and raises ArrayUnavailable instead, so the page shows a reason
    and the next page does not pay the timeout again. ErrorResponse objects
    and any other exception pass through untouched.
    """

    def __init__(self, entry, client):
        self._entry = entry
        self._client = client

    def __getattr__(self, name):
        if name.startswith('__') or name in ('_entry', '_client'):
            raise AttributeError(name)
        attr = getattr(self._client, name)
        if not callable(attr):
            return attr

        def call(*args, **kwargs):
            try:
                return attr(*args, **kwargs)
            except TRANSPORT_ERRORS as exc:
                message = 'Unable to contact %s (%s): %s' % (
                    self._entry.backend_name, self._entry.target, exc)
                LOG.warning(message)
                mark_unavailable(self._entry, message, client=self)
                raise ArrayUnavailable(message) from exc
        return call

    def __repr__(self):
        return '<ClientProxy %r>' % (self._entry,)


def get_client(entry):
    """Return the cached client for ``entry``, building it on first use.

    Raises ArrayUnavailable when the client cannot be built; the failure is
    cached for FAILURE_TTL seconds and re-raised without a new attempt. The
    result is a ClientProxy, which applies the same rule to an array that
    stops answering later (see ``mark_unavailable``).
    """
    key = entry.cache_key
    with _lock:
        client = _clients.get(key)
        if client is not None:
            return client
        failure = _failures.get(key)
        if failure is not None:
            expires, message = failure
            if _now() < expires:
                raise ArrayUnavailable(message)
            del _failures[key]
    # Build outside the lock: construction can take timeout * retries.
    try:
        client = ClientProxy(entry, _build_client(entry))
    except Exception as exc:
        message = 'Unable to connect to %s (%s): %s' % (
            entry.backend_name, entry.target, exc)
        LOG.warning(message)
        with _lock:
            _failures[key] = (_now() + FAILURE_TTL, message)
        raise ArrayUnavailable(message) from exc
    with _lock:
        _clients[key] = client
    return client


def mark_unavailable(entry, message, client=None):
    """Evict the cached client of ``entry`` and remember the failure.

    Until FAILURE_TTL has passed, ``get_client`` for the same array raises
    ArrayUnavailable(``message``) without a network round trip. With
    ``client`` (an object ``get_client`` returned) nothing happens unless
    that very object is still the cached one, so a client rebuilt in the
    meantime is left alone.
    """
    key = entry.cache_key
    with _lock:
        if client is not None and _clients.get(key) is not client:
            return
        _clients.pop(key, None)
        _failures[key] = (_now() + FAILURE_TTL, message)


def reset():
    """Forget cached clients and cached failures (tests, reconfiguration)."""
    with _lock:
        _clients.clear()
        _failures.clear()


def backend_from_host(host):
    """'host@backend#pool' -> 'backend'; None when there is no '@'."""
    if not isinstance(host, str) or '@' not in host:
        return None
    backend = host.split('@', 1)[1].split('#', 1)[0]
    return backend or None


def ok(resp):
    """True when ``resp`` is a successful py-pure-client response."""
    return getattr(resp, 'status_code', None) == 200


def not_found(resp):
    """True when ``resp`` says the named object does not exist.

    Purity answers a lookup of a missing object with HTTP 400 ("Managed
    directory does not exist.", "File system does not exist.", ...), not
    404. Any other failure (401, 403, 5xx, status 0 for a TLS problem) is
    the array failing, which callers must not report as "not found".
    """
    return getattr(resp, 'status_code', None) == 400


def items(resp):
    """The response items as a list; [] on error."""
    if not ok(resp):
        return []
    found = getattr(resp, 'items', None)
    if found is None:
        return []
    return list(found)


def first(resp):
    """The first response item, or None on error or when empty."""
    found = items(resp)
    return found[0] if found else None


def attr(obj, name, default=None):
    """getattr that treats None as missing.

    py-pure-client models raise AttributeError for attributes whose value
    is None, so a plain getattr with a default is not enough.
    """
    try:
        value = getattr(obj, name)
    except AttributeError:
        return default
    return default if value is None else value


def error_message(resp):
    """Human readable text for an ErrorResponse (or any response)."""
    parts = []
    for err in getattr(resp, 'errors', None) or []:
        message = getattr(err, 'message', None) or str(err)
        context = getattr(err, 'context', None)
        parts.append('%s (%s)' % (message, context) if context else message)
    status = getattr(resp, 'status_code', None)
    if parts:
        text = '; '.join(parts)
        return 'HTTP %s: %s' % (status, text) if status is not None else text
    if status is not None:
        return 'HTTP %s' % status
    return 'unknown error'


def to_mib(nbytes):
    """Bytes -> MiB (templates render MiB with ``mb_float_format``)."""
    return float(nbytes or 0) / (1024 ** 2)


def ratio(value):
    """Reduction ratio as the "x.xx to 1" string the templates show."""
    return '%.2f to 1' % (value or 1.0)
