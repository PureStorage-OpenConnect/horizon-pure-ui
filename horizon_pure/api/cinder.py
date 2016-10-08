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

from openstack_dashboard.api import cinder


class PureVolume(cinder.Volume):
    _pure_attrs = [
        'total',
        'data_reduction',
        'thin_provisioning',
        'total_reduction',
        'reads_per_sec',
        'writes_per_sec',
        'output_per_sec',
        'input_per_sec',
        'usec_per_read_op',
        'usec_per_write_op',
    ]

    def __init__(self, apiresource):
        super(PureVolume, self).__init__(apiresource)
        self._attrs = self._attrs + self._pure_attrs
