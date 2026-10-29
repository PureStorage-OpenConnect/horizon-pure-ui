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

from django.urls import include
from django.urls import re_path

from horizon_pure.pure_panel.fafiles import urls as fafiles_urls
from horizon_pure.pure_panel.flasharrays import urls as flasharray_urls
from horizon_pure.pure_panel.flashblades import urls as flashblade_urls
from horizon_pure.pure_panel import views


urlpatterns = [
    re_path(r'^$', views.IndexView.as_view(), name='index'),
    re_path(r'^flasharrays/', include((flasharray_urls, 'flasharrays'))),
    re_path(r'^flashblades/', include((flashblade_urls, 'flashblades'))),
    re_path(r'^fafiles/', include((fafiles_urls, 'fafiles'))),
]
