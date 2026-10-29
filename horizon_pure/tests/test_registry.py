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

"""Tests for horizon_pure.api.registry."""

import types
from unittest import mock

from django.conf import settings
from django.test import override_settings

from openstack_dashboard.test import helpers as test
from urllib3 import exceptions as urllib3_exceptions

from horizon_pure.api import registry


FA_CONF = {'san_ip': '192.0.2.10', 'api_token': 'tok-fa',
           'backend_name': 'pure-iscsi'}
FB_CONF = {'mgmt_ip': '192.0.2.20', 'api_token': 'tok-fb',
           'backend_name': 'flashblade', 'verify_ssl': True}
FAF_CONF = {'san_ip': '192.0.2.10', 'api_token': 'tok-fa',
            'backend_name': 'flasharray-files',
            'ca_cert': '/etc/ssl/certs/pure.pem'}


def _entry(**overrides):
    kwargs = {'kind': 'fa', 'service': 'cinder', 'backend_name': 'be',
              'target': '192.0.2.10', 'api_token': 'secret-token'}
    kwargs.update(overrides)
    return registry.ArrayEntry(**kwargs)


class RegistryTestCase(test.TestCase):

    def setUp(self):
        super().setUp()
        registry.reset()
        self.addCleanup(registry.reset)


class EntriesTests(RegistryTestCase):

    def test_absent_settings(self):
        with override_settings():
            for name in ('PURE_FLASH_ARRAYS', 'PURE_FLASH_BLADES',
                         'PURE_FLASH_ARRAY_FILES'):
                if hasattr(settings, name):
                    delattr(settings, name)
            self.assertEqual([], registry.entries())
            self.assertEqual([], registry.entries(service='manila'))
            self.assertIsNone(registry.find('cinder', 'pure-iscsi'))

    @override_settings(PURE_FLASH_ARRAYS=[FA_CONF],
                       PURE_FLASH_BLADES=[FB_CONF],
                       PURE_FLASH_ARRAY_FILES=[FAF_CONF])
    def test_parses_all_three_lists(self):
        found = registry.entries()
        self.assertEqual([('cinder', 'pure-iscsi'),
                          ('manila', 'flashblade'),
                          ('manila', 'flasharray-files')],
                         [entry.key for entry in found])
        fa, fb, faf = found

        self.assertEqual('fa', fa.kind)
        self.assertEqual('192.0.2.10', fa.target)
        self.assertEqual('tok-fa', fa.api_token)
        self.assertFalse(fa.verify_ssl)
        self.assertIsNone(fa.ca_cert)
        self.assertEqual('openstack', fa.parent_fs)

        # mgmt_ip is accepted as the target and verify_ssl is honoured.
        self.assertEqual('fb', fb.kind)
        self.assertEqual('192.0.2.20', fb.target)
        self.assertTrue(fb.verify_ssl)
        self.assertIsNone(fb.ca_cert)

        # ca_cert implies verification; parent_fs defaults to openstack.
        self.assertEqual('fa', faf.kind)
        self.assertEqual('manila', faf.service)
        self.assertTrue(faf.verify_ssl)
        self.assertEqual('/etc/ssl/certs/pure.pem', faf.ca_cert)
        self.assertEqual('openstack', faf.parent_fs)
        # Same array as the Cinder entry: shares one client.
        self.assertEqual(fa.cache_key, faf.cache_key)

    @override_settings(PURE_FLASH_ARRAYS=[FA_CONF],
                       PURE_FLASH_BLADES=[FB_CONF],
                       PURE_FLASH_ARRAY_FILES=[FAF_CONF])
    def test_filters(self):
        self.assertEqual(['flashblade', 'flasharray-files'],
                         [e.backend_name for e in
                          registry.entries(service='manila')])
        self.assertEqual(['pure-iscsi', 'flasharray-files'],
                         [e.backend_name for e in registry.entries(kind='fa')])
        self.assertEqual(['flasharray-files'],
                         [e.backend_name for e in
                          registry.entries(service='manila', kind='fa')])
        self.assertEqual([], registry.entries(service='cinder', kind='fb'))

    @override_settings(PURE_FLASH_ARRAY_FILES=[
        dict(FAF_CONF, parent_fs='tenant-fs')])
    def test_parent_fs_explicit(self):
        entry = registry.find('manila', 'flasharray-files')
        self.assertEqual('tenant-fs', entry.parent_fs)

    @override_settings(PURE_FLASH_ARRAYS=[
        {'api_token': 'x'},                       # no identity at all
        {'san_ip': '192.0.2.99'},                 # no backend_name
        {'backend_name': 'no-ip', 'api_token': 'x'},
        'garbage',
        {'san_ip': '192.0.2.98', 'backend_name': 'no-token'},
        FA_CONF,
    ])
    def test_skips_entries_without_identity(self):
        found = registry.entries()
        self.assertEqual(['no-token', 'pure-iscsi'],
                         [entry.backend_name for entry in found])
        # A missing token is kept so the backend surfaces as an error row.
        self.assertIsNone(found[0].api_token)

    def test_repr_hides_token(self):
        entry = _entry(api_token='secret-token')
        text = repr(entry)
        self.assertNotIn('secret-token', text)
        self.assertIn('be', text)
        self.assertIn('192.0.2.10', text)

    @override_settings(PURE_FLASH_ARRAYS=[FA_CONF],
                       PURE_FLASH_BLADES=[FB_CONF])
    def test_find(self):
        self.assertEqual(('cinder', 'pure-iscsi'),
                         registry.find('cinder', 'pure-iscsi').key)
        self.assertEqual('fb', registry.find('manila', 'flashblade').kind)
        self.assertIsNone(registry.find('manila', 'pure-iscsi'))
        self.assertIsNone(registry.find('cinder', 'missing'))
        self.assertIsNone(registry.find('cinder', None))

    def test_backend_from_host(self):
        cases = (
            ('host@pure-iscsi#pure-iscsi', 'pure-iscsi'),
            ('host@pure-iscsi', 'pure-iscsi'),
            ('host@be#pool#extra', 'be'),
            ('host@', None),
            ('nohost', None),
            ('', None),
            (None, None),
            (42, None),
        )
        for host, expected in cases:
            with self.subTest(host=host):
                self.assertEqual(expected, registry.backend_from_host(host))

    def test_response_helpers(self):
        good = types.SimpleNamespace(status_code=200, items=iter(['a', 'b']))
        self.assertTrue(registry.ok(good))
        self.assertEqual(['a', 'b'], registry.items(good))
        self.assertEqual('HTTP 200', registry.error_message(good))

        first = types.SimpleNamespace(status_code=200, items=iter(['a']))
        self.assertEqual('a', registry.first(first))
        empty = types.SimpleNamespace(status_code=200, items=[])
        self.assertIsNone(registry.first(empty))

        bad = types.SimpleNamespace(
            status_code=400,
            errors=[types.SimpleNamespace(
                message='Managed directory does not exist.',
                context='openstack:share-x-manila'),
                types.SimpleNamespace(message='Second', context=None)])
        self.assertFalse(registry.ok(bad))
        self.assertEqual([], registry.items(bad))
        self.assertIsNone(registry.first(bad))
        self.assertEqual(
            'HTTP 400: Managed directory does not exist. '
            '(openstack:share-x-manila); Second',
            registry.error_message(bad))

        self.assertFalse(registry.ok(None))
        self.assertEqual([], registry.items(None))
        self.assertEqual('unknown error', registry.error_message(None))

    def test_attr(self):
        class Model(object):
            present = 5
            empty = None

            @property
            def exploding(self):
                # py-pure-client models raise for None-valued attributes.
                raise AttributeError('exploding')

        model = Model()
        self.assertEqual(5, registry.attr(model, 'present', 0))
        self.assertEqual(0, registry.attr(model, 'empty', 0))
        self.assertEqual(0, registry.attr(model, 'exploding', 0))
        self.assertEqual(0, registry.attr(model, 'missing', 0))
        self.assertIsNone(registry.attr(None, 'anything'))

    def test_units(self):
        self.assertEqual(1.0, registry.to_mib(1024 ** 2))
        self.assertEqual(0.5, registry.to_mib(512 * 1024))
        self.assertEqual(0.0, registry.to_mib(None))
        self.assertEqual(0.0, registry.to_mib(0))
        self.assertEqual('3.46 to 1', registry.ratio(3.456))
        self.assertEqual('1.00 to 1', registry.ratio(None))
        self.assertEqual('1.00 to 1', registry.ratio(0))

    def test_user_agent(self):
        self.assertEqual('OpenStack-Horizon-Everpure-UI/2.1.0',
                         registry.USER_AGENT)


class ClientCacheTests(RegistryTestCase):

    def test_build_client_flasharray_kwargs(self):
        entry = _entry(verify_ssl=False, ca_cert='/x.pem')
        with override_settings(PURE_API_TIMEOUT=5, PURE_API_RETRIES=2), \
                mock.patch.object(registry.flasharray, 'Client') as fa, \
                mock.patch.object(registry.flashblade, 'Client') as fb:
            client = registry.get_client(entry)
        fa.assert_called_once_with(
            target='192.0.2.10', api_token='secret-token',
            user_agent=registry.USER_AGENT, verify_ssl=True,
            ssl_cert='/x.pem', timeout=5, retries=2,
            configuration=mock.ANY)
        fb.assert_not_called()
        # The urllib3 connection retries follow PURE_API_RETRIES as well;
        # the SDK alone would leave them at urllib3's default of 3.
        config = fa.call_args[1]['configuration']
        self.assertIsInstance(config, registry.configuration.Configuration)
        self.assertEqual(2, config.retries)
        self.assertIsInstance(client, registry.ClientProxy)
        self.assertIs(fa.return_value, client._client)

    def test_build_client_flashblade_defaults(self):
        entry = _entry(kind='fb', service='manila', target='192.0.2.20')
        with override_settings():
            for name in ('PURE_API_TIMEOUT', 'PURE_API_RETRIES'):
                if hasattr(settings, name):
                    delattr(settings, name)
            with mock.patch.object(registry.flasharray, 'Client') as fa, \
                    mock.patch.object(registry.flashblade, 'Client') as fb:
                client = registry.get_client(entry)
        fb.assert_called_once_with(
            target='192.0.2.20', api_token='secret-token',
            user_agent=registry.USER_AGENT, verify_ssl=False,
            ssl_cert=None, timeout=10, retries=1,
            configuration=mock.ANY)
        fa.assert_not_called()
        self.assertEqual(1, fb.call_args[1]['configuration'].retries)
        self.assertIs(fb.return_value, client._client)

    def test_cache_per_kind_target_token(self):
        def build(entry):
            return mock.Mock(name='client-%s' % entry.backend_name)

        with mock.patch.object(registry, '_build_client',
                               side_effect=build) as builder:
            a = registry.get_client(_entry(backend_name='cinder-be'))
            # Same kind/target/token under another service: shared.
            b = registry.get_client(_entry(backend_name='manila-be',
                                           service='manila'))
            self.assertIs(a, b)
            c = registry.get_client(_entry(api_token='other-token'))
            self.assertIsNot(a, c)
            d = registry.get_client(_entry(kind='fb'))
            self.assertIsNot(a, d)
            self.assertIsNot(c, d)
            e = registry.get_client(_entry(target='192.0.2.11'))
            self.assertIsNot(a, e)

        self.assertEqual(4, builder.call_count)
        self.assertEqual(['cinder-be', 'be', 'be', 'be'],
                         [call[0][0].backend_name
                          for call in builder.call_args_list])

    def test_failure_cached_for_ttl(self):
        clock = {'now': 1000.0}
        entry = _entry()
        with mock.patch.object(registry, '_now',
                               side_effect=lambda: clock['now']), \
                mock.patch.object(registry, '_build_client',
                                  side_effect=RuntimeError('boom')) as build:
            with self.assertRaises(registry.ArrayUnavailable) as ctx:
                registry.get_client(entry)
            message = str(ctx.exception)
            self.assertIn('boom', message)
            self.assertIn('192.0.2.10', message)
            self.assertIn('be', message)
            self.assertNotIn('secret-token', message)
            build.assert_called_once_with(entry)

            # Inside the window: the cached failure is raised, no rebuild.
            clock['now'] += registry.FAILURE_TTL - 1
            with self.assertRaises(registry.ArrayUnavailable) as ctx:
                registry.get_client(entry)
            self.assertEqual(message, str(ctx.exception))
            self.assertEqual(1, build.call_count)

            # Past the window: a new attempt is made and succeeds.
            clock['now'] += 2
            build.side_effect = None
            build.return_value = mock.Mock(name='client')
            client = registry.get_client(entry)
            self.assertIs(build.return_value, client._client)
            self.assertEqual(2, build.call_count)
            # And is cached from then on.
            self.assertIs(client, registry.get_client(entry))
            self.assertEqual(2, build.call_count)

    def test_reset_clears_both_caches(self):
        entry = _entry()
        with mock.patch.object(registry, '_build_client',
                               return_value=mock.Mock()) as build:
            registry.get_client(entry)
            registry.get_client(entry)
            self.assertEqual(1, build.call_count)
            registry.reset()
            registry.get_client(entry)
            self.assertEqual(2, build.call_count)

        with mock.patch.object(registry, '_build_client',
                               side_effect=RuntimeError('down')) as build:
            registry.reset()
            self.assertRaises(registry.ArrayUnavailable,
                              registry.get_client, entry)
            self.assertRaises(registry.ArrayUnavailable,
                              registry.get_client, entry)
            self.assertEqual(1, build.call_count)
            registry.reset()
            self.assertRaises(registry.ArrayUnavailable,
                              registry.get_client, entry)
            self.assertEqual(2, build.call_count)


class ClientProxyTests(RegistryTestCase):
    """get_client hands out a proxy that evicts a client whose array dies."""

    def setUp(self):
        super().setUp()
        self.entry = _entry()
        self.sdk = mock.Mock(name='sdk-client')
        patcher = mock.patch.object(registry, '_build_client',
                                    return_value=self.sdk)
        self.build = patcher.start()
        self.addCleanup(patcher.stop)

    def test_calls_and_attributes_pass_through(self):
        self.sdk.get_arrays.return_value = 'resp'
        self.sdk.plain = 'value'
        client = registry.get_client(self.entry)

        self.assertEqual('resp', client.get_arrays(names=['a'], limit=1))
        self.sdk.get_arrays.assert_called_once_with(names=['a'], limit=1)
        self.assertEqual('value', client.plain)
        self.assertIs(client, registry.get_client(self.entry))
        self.assertIn('be', repr(client))
        self.assertNotIn('secret-token', repr(client))
        # An ErrorResponse (TLS failures come back as status 0) is data,
        # not a transport failure: returned as is, client kept.
        error = types.SimpleNamespace(status_code=0, errors=[])
        self.sdk.get_volumes.return_value = error
        self.assertIs(error, client.get_volumes())
        self.assertIs(client, registry.get_client(self.entry))

    def test_other_exceptions_pass_through(self):
        self.sdk.get_arrays.side_effect = RuntimeError('bug')
        client = registry.get_client(self.entry)
        self.assertRaises(RuntimeError, client.get_arrays)
        # A plain bug is not an unreachable array: still cached.
        self.assertIs(client, registry.get_client(self.entry))
        self.assertEqual(1, self.build.call_count)

    def test_transport_failure_evicts_and_caches_the_failure(self):
        clock = {'now': 1000.0}
        self.sdk.get_arrays.side_effect = urllib3_exceptions.MaxRetryError(
            None, '/api/2.x/arrays', reason='hung')
        with mock.patch.object(registry, '_now',
                               side_effect=lambda: clock['now']):
            client = registry.get_client(self.entry)
            with self.assertRaises(registry.ArrayUnavailable) as ctx:
                client.get_arrays()
            message = str(ctx.exception)
            self.assertIn('Unable to contact be (192.0.2.10)', message)
            self.assertIn('Max retries exceeded', message)
            self.assertNotIn('secret-token', message)
            self.assertIsInstance(ctx.exception.__cause__,
                                  urllib3_exceptions.MaxRetryError)
            # Evicted and remembered: same message, no rebuild, for the TTL.
            with self.assertRaises(registry.ArrayUnavailable) as ctx:
                registry.get_client(self.entry)
            self.assertEqual(message, str(ctx.exception))
            self.assertEqual(1, self.build.call_count)
            clock['now'] += registry.FAILURE_TTL - 1
            self.assertRaises(registry.ArrayUnavailable,
                              registry.get_client, self.entry)
            clock['now'] += 2
            fresh = registry.get_client(self.entry)
        self.assertIsNot(client, fresh)
        self.assertEqual(2, self.build.call_count)

    def test_pure_error_is_a_transport_failure(self):
        # The SDK raises PureError (not an ErrorResponse) when a rotated
        # token fails to re-authenticate after a 401.
        self.sdk.get_file_systems.side_effect = (
            registry.pure_exceptions.PureError('token rejected'))
        client = registry.get_client(self.entry)
        with self.assertRaises(registry.ArrayUnavailable) as ctx:
            client.get_file_systems(names=['x'])
        self.assertIn('token rejected', str(ctx.exception))
        self.sdk.get_file_systems.assert_called_once_with(names=['x'])
        self.assertRaises(registry.ArrayUnavailable,
                          registry.get_client, self.entry)
        self.assertEqual(1, self.build.call_count)

    def test_mark_unavailable(self):
        client = registry.get_client(self.entry)
        # A stale proxy must not evict a client rebuilt in the meantime.
        registry.mark_unavailable(self.entry, 'old', client=mock.Mock())
        self.assertIs(client, registry.get_client(self.entry))

        registry.mark_unavailable(self.entry, 'gone', client=client)
        with self.assertRaises(registry.ArrayUnavailable) as ctx:
            registry.get_client(self.entry)
        self.assertEqual('gone', str(ctx.exception))

        registry.reset()
        registry.get_client(self.entry)
        registry.mark_unavailable(self.entry, 'unconditional')
        self.assertRaises(registry.ArrayUnavailable,
                          registry.get_client, self.entry)
        self.assertEqual(2, self.build.call_count)
