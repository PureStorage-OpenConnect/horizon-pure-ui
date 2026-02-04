from django.urls import reverse
from django.utils.translation import gettext_lazy as _
import logging

from horizon import tables
from horizon.templatetags import sizeformat

LOG = logging.getLogger(__name__)


class PureFilterAction(tables.FilterAction):
    name = "purefilter"


def get_purity_url(array_info):
    LOG.debug('Building url for array %s' % array_info.cinder_id)
    return 'https://%s/' % array_info.target


def get_detail_url(array_info):
    LOG.debug('Building url for detail view of %s' % array_info.cinder_id)
    return reverse('horizon:admin:pure_panel:flasharrays:detail',
                   kwargs={'backend_id': array_info.cinder_id})


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
    volume_count = tables.Column('total_volume_count', verbose_name=_('Volume Count'))
    version = tables.Column('version', verbose_name=_('Purity Version'))

    class Meta(object):
        name = 'flasharrays'
        verbose_name = _('Pure Storage FlashArrays')
        table_actions = (PureFilterAction,)
        multi_select = False
