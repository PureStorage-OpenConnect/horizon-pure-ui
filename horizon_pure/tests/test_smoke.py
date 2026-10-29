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

from django.urls import reverse

from openstack_dashboard.test import helpers as test


class PanelSmokeTests(test.BaseAdminViewTests):

    def test_panel_index_url_resolves(self):
        self.assertEqual(reverse('horizon:admin:pure_panel:index'),
                         '/admin/pure_panel/')

    def test_flasharray_detail_url_resolves(self):
        url = reverse('horizon:admin:pure_panel:flasharrays:detail',
                      kwargs={'backend_id': 'pure-iscsi'})
        self.assertEqual(url, '/admin/pure_panel/flasharrays/pure-iscsi/')
