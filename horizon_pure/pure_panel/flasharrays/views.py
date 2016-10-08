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


from django.core.urlresolvers import reverse

from horizon import tabs

from horizon_pure.pure_panel.flasharrays import tabs as flasharray_tabs


class DetailView(tabs.TabView):
    tab_group_class = flasharray_tabs.FlashArrayDetailTabs
    template_name = 'horizon/common/_detail.html'
    page_title = "{{ backend.name }}"

    def get_context_data(self, **kwargs):
        context = super(DetailView, self).get_context_data(**kwargs)
        context['backend_id'] = self.get_data()
        return context

    def get_redirect_url(self):
        return reverse('horizon:admin:pure_panel:index')

    def get_data(self):
        return self.kwargs['backend_id']
