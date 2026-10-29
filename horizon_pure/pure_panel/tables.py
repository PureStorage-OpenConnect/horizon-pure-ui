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

"""Tables of the Everpure admin panel index and helpers shared by the
per-backend detail tables.

Rows are the ``APIDictWrapper`` objects the API modules return; every size
is MiB and rendered with ``mb_float_format``, ratios are already strings.
"""

from django.template import defaultfilters
from django.urls import NoReverseMatch
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
import logging

from horizon import tables
from horizon.templatetags import sizeformat

LOG = logging.getLogger(__name__)


class PureFilterAction(tables.FilterAction):
    name = "purefilter"


def get_purity_url(array_info):
    """Link to the Purity web UI of the array behind a row."""
    return 'https://%s/' % array_info.target


def get_detail_url(array_info):
    LOG.debug('Building detail url for %s', array_info.cinder_id)
    return reverse('horizon:admin:pure_panel:flasharrays:detail',
                   kwargs={'backend_id': array_info.cinder_id})


def get_flashblade_detail_url(array_info):
    return reverse('horizon:admin:pure_panel:flashblades:detail',
                   kwargs={'backend_id': array_info.backend_id})


def get_fafiles_detail_url(array_info):
    return reverse('horizon:admin:pure_panel:fafiles:detail',
                   kwargs={'backend_id': array_info.backend_id})


def share_detail_url(share_id):
    """URL of the manila-ui admin share detail page, or None.

    None when there is no share id or the URL name does not reverse
    (manila-ui not installed); the column then renders plain text.
    """
    if not share_id:
        return None
    try:
        return reverse('horizon:admin:shares:detail',
                       kwargs={'share_id': share_id})
    except NoReverseMatch:
        return None


def share_instance_detail_url(instance_id):
    """URL of the manila-ui admin share instance detail page, or None.

    FlashBlade file systems are named after the share *instance*, whose
    page is one click from the owning share. None when there is no id or
    the URL name does not reverse (manila-ui not installed).
    """
    if not instance_id:
        return None
    try:
        return reverse('horizon:admin:share_instances:share_instance_detail',
                       kwargs={'share_instance_id': instance_id})
    except NoReverseMatch:
        return None


def format_created(value):
    """Column filter for the aware ``created`` datetimes the APIs return."""
    if not value:
        return '-'
    return defaultfilters.date(value, 'Y-m-d H:i T')


class PureFlashArrayTable(tables.DataTable):
    array_name = tables.WrappingColumn(
        'array_name',
        verbose_name=_('Array Name'),
        link=get_purity_url,
        link_attrs={"target": "_blank"}
    )
    cinder_id = tables.Column(
        'cinder_name',
        verbose_name=_('Cinder Name'),
        link=get_detail_url
    )
    status = tables.Column('status', verbose_name=_('Status'))
    total = tables.Column('total', verbose_name=_('Used Space'),
                          filters=[sizeformat.mb_float_format])
    capacity = tables.Column('capacity', verbose_name=_('Capacity'),
                             filters=[sizeformat.mb_float_format])
    data_reduction = tables.Column('data_reduction',
                                   verbose_name=_('Data Reduction'))
    total_reduction = tables.Column('total_reduction',
                                    verbose_name=_('Total Reduction'))
    volume_count = tables.Column('total_volume_count',
                                 verbose_name=_('Volume Count'))
    version = tables.Column('version', verbose_name=_('Purity Version'))

    class Meta(object):
        name = 'flasharrays'
        verbose_name = _('Everpure FlashArrays')
        table_actions = (PureFilterAction,)
        multi_select = False


class PureFlashBladeTable(tables.DataTable):
    """Manila FlashBlade backends; rows from FlashBladeAPI.get_array_info."""
    array_name = tables.WrappingColumn(
        'array_name',
        verbose_name=_('Array Name'),
        link=get_purity_url,
        link_attrs={"target": "_blank"}
    )
    backend_name = tables.Column(
        'backend_name',
        verbose_name=_('Manila Backend'),
        link=get_flashblade_detail_url
    )
    status = tables.Column('status', verbose_name=_('Status'))
    total = tables.Column('total', verbose_name=_('Used Space'),
                          filters=[sizeformat.mb_float_format])
    capacity = tables.Column('capacity', verbose_name=_('Capacity'),
                             filters=[sizeformat.mb_float_format])
    data_reduction = tables.Column('data_reduction',
                                   verbose_name=_('Data Reduction'))
    file_system_count = tables.Column('file_system_count',
                                      verbose_name=_('File Systems'))
    version = tables.Column('version', verbose_name=_('Purity Version'))

    def get_object_id(self, datum):
        return datum['backend_id']

    def get_object_display(self, datum):
        return datum['backend_name']

    class Meta(object):
        name = 'flashblades'
        verbose_name = _('Everpure FlashBlades')
        table_actions = (PureFilterAction,)
        multi_select = False


class PureFlashArrayFilesTable(tables.DataTable):
    """Manila FlashArray Files backends; rows from FlashArrayFilesAPI."""
    array_name = tables.WrappingColumn(
        'array_name',
        verbose_name=_('Array Name'),
        link=get_purity_url,
        link_attrs={"target": "_blank"}
    )
    backend_name = tables.Column(
        'backend_name',
        verbose_name=_('Manila Backend'),
        link=get_fafiles_detail_url
    )
    parent_fs = tables.Column('parent_fs',
                              verbose_name=_('Parent File System'))
    status = tables.Column('status', verbose_name=_('Status'))
    total = tables.Column('total', verbose_name=_('Used Space'),
                          filters=[sizeformat.mb_float_format])
    capacity = tables.Column('capacity', verbose_name=_('Capacity'),
                             filters=[sizeformat.mb_float_format])
    data_reduction = tables.Column('data_reduction',
                                   verbose_name=_('Data Reduction'))
    directory_count = tables.Column('directory_count',
                                    verbose_name=_('Managed Directories'))
    version = tables.Column('version', verbose_name=_('Purity Version'))

    def get_object_id(self, datum):
        return datum['backend_id']

    def get_object_display(self, datum):
        return datum['backend_name']

    class Meta(object):
        name = 'fafiles'
        verbose_name = _('Everpure FlashArray Files')
        table_actions = (PureFilterAction,)
        multi_select = False
