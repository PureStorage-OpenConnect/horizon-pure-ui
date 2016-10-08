# The name of the panel to be added to HORIZON_CONFIG. Required.
PANEL = 'pure_panel'

# The name of the dashboard the PANEL is associated with. Required.
PANEL_DASHBOARD = 'admin'

# The name of the panel group the PANEL is associated with.
PANEL_GROUP = 'admin'

# Python panel class of the PANEL to be added.
ADD_PANEL = 'horizon_pure.pure_panel.panel.PurePanel'

ADD_INSTALLED_APPS = ['horizon_pure.pure_panel']

# override default behavior for admin->volumes
UPDATE_HORIZON_CONFIG = \
    {'customization_module': 'horizon_pure.overrides', }