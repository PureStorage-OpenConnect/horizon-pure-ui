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


def get_share_url(directory):
    """manila-ui share detail link for a directory row, or None."""
    return pure_tables.share_detail_url(directory['share_id'])


class ManilaDirectoriesTable(tables.DataTable):
    """Manila share directories in one FlashArray Files backend.

    Rows are the dicts ``FlashArrayFilesAPI.list_manila_directories``
    returns (sizes in MiB). The directory name carries the share id, so
    it links to the manila-ui share detail page when that is installed.
    """
    name = tables.WrappingColumn('name',
                                 verbose_name=_('Managed Directory'))
    share_id = tables.Column('share_id', verbose_name=_('Share ID'),
                             link=get_share_url)
    used = tables.Column('used', verbose_name=_('Used (physical)'),
                         filters=[sizeformat.mb_float_format])
    virtual = tables.Column('virtual', verbose_name=_('Used (logical)'),
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
        name = 'manila_directories'
        verbose_name = _('Manila Shares')
        table_actions = (pure_tables.PureFilterAction,)
        multi_select = False
