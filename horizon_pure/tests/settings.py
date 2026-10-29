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

"""Django settings for the horizon_pure unit tests.

Mirrors manila_ui/tests/settings.py: the Horizon and openstack_dashboard
test settings plus this plugin's enabled files. manila-ui is optional; when
it is importable its panels are registered too so the share-detail hook can
be exercised.
"""

from horizon.test.settings import *  # noqa: F403,H303
from openstack_dashboard.test.settings import *  # noqa: F403,H303

import openstack_dashboard.enabled
from openstack_dashboard.utils import settings as settings_utils

import horizon_pure.enabled

try:
    import manila_ui.local.enabled as manila_ui_enabled
except ImportError:  # manila-ui not installed
    manila_ui_enabled = None

INSTALLED_APPS = list(INSTALLED_APPS)  # noqa: F405
_enabled_modules = [horizon_pure.enabled]
if manila_ui_enabled is not None:
    INSTALLED_APPS.append('manila_ui.dashboards')
    _enabled_modules.append(manila_ui_enabled)
_enabled_modules.append(openstack_dashboard.enabled)

settings_utils.update_dashboards(
    _enabled_modules,
    HORIZON_CONFIG,  # noqa: F405
    INSTALLED_APPS,
)
# openstack_dashboard.test.settings already registered its own enabled files
# once; the second pass above prepends them again, so drop the duplicates
# while keeping the first occurrence of each app.
INSTALLED_APPS = list(dict.fromkeys(INSTALLED_APPS))

# Array settings consumed by the plugin. Tests patch the API layer, so no
# real array is ever contacted; the entries only need to parse.
PURE_FLASH_ARRAYS = [
    {'san_ip': '192.0.2.10', 'api_token': 'test-token',
     'backend_name': 'pure-iscsi'},
]
