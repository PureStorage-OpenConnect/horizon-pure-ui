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

from django.utils.translation import gettext_lazy as _

from horizon import tables
from horizon.templatetags import sizeformat

from horizon_pure.pure_panel import tables as pure_tables


def get_share_instance_url(file_system):
    """manila-ui share instance detail link for a row, or None."""
    return pure_tables.share_instance_detail_url(
        file_system['share_instance_id'])


class ManilaFileSystemsTable(tables.DataTable):
    """Manila-created file systems on one FlashBlade backend.

    Rows are the dicts ``FlashBladeAPI.list_manila_file_systems`` returns
    (sizes in MiB). The file system name carries the share *instance* id,
    so it links to manila-ui's admin share instance detail page (one click
    from the owning share) when that URL reverses; a name that does not
    parse stays plain text.
    """
    name = tables.WrappingColumn('name', verbose_name=_('File System'))
    share_instance_id = tables.Column('share_instance_id',
                                      verbose_name=_('Share Instance ID'),
                                      link=get_share_instance_url)
    provisioned = tables.Column('provisioned', verbose_name=_('Provisioned'),
                                filters=[sizeformat.mb_float_format])
    used = tables.Column('used', verbose_name=_('Used'),
                         filters=[sizeformat.mb_float_format])
    data_reduction = tables.Column('data_reduction',
                                   verbose_name=_('Data Reduction'))
    snapshots = tables.Column('snapshots', verbose_name=_('Snapshot Space'),
                              filters=[sizeformat.mb_float_format])
    created = tables.Column('created', verbose_name=_('Created'),
                            filters=[pure_tables.format_created])

    def get_object_id(self, datum):
        return datum['name']

    def get_object_display(self, datum):
        return datum['name']

    class Meta(object):
        name = 'manila_file_systems'
        verbose_name = _('Manila Shares')
        table_actions = (pure_tables.PureFilterAction,)
        multi_select = False
