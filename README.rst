Everpure Horizon Plugin
-----------------------

.. image:: ./Horizon-Head.JPG
   :width: 300
   :alt: Magnifying Image

*The screenshots in this document predate the Everpure rename and still show
the previous product name and panel layout.*

This OpenStack Dashboard plugin adds deeper integration for Everpure
FlashArray and FlashBlade storage. It includes:

* An Admin panel that shows the configured arrays and their current state,
  with one tab each for Cinder FlashArray backends, Manila FlashBlade
  backends and Manila FlashArray Files backends.
* Overridden volume detail views (Admin and Project) that show additional
  volume usage and performance information.
* An **Everpure** tab on the Manila share detail views (Admin and Project,
  when manila-ui is installed) that shows the share's file system or managed
  directory as the array sees it.


Requirements
------------

The plugin talks to the arrays through the ``py-pure-client`` Python module
(REST API 2.x). Other than that you need a working Horizon installation and,
for the share detail tab, manila-ui.

* OpenStack: 2024.2 (Dalmatian) or later
* Python: 3.10, 3.11, or 3.12
* Django: 4.2 or later
* Horizon: from OpenStack 2024.2 or later
* manila-ui (optional): needed only for the Everpure tab on the share detail
  views; the FlashBlade and FlashArray Files panel tabs work without it
* Everpure FlashArray with Purity//FA 6.1.0 or later (REST API 2.x) for
  Cinder backends, and Purity//FA 6.10.6 or later (REST API 2.54) with FA
  Files enabled for FlashArray Files Manila backends
* Everpure FlashBlade running a Purity//FB release with REST API 2.x support
* py-pure-client 1.58.0 or later (installed automatically with this package)


Building the Package
--------------------

To build a wheel package::

  git clone https://github.com/PureStorage-OpenConnect/horizon-pure-ui.git
  cd horizon-pure-ui
  pip install build
  python -m build --wheel

The wheel file will be created in the ``dist/`` directory as
``horizon_pure-2.1.0-py3-none-any.whl``.


Installation
------------

You will need to install and configure Horizon first.

**Install from Source:**

To install the Everpure Horizon plugin package directly from source::

  git clone https://github.com/PureStorage-OpenConnect/horizon-pure-ui.git
  cd horizon-pure-ui
  sudo pip install .

**Install from Wheel:**

To install from a pre-built wheel package::

  sudo pip install horizon_pure-2.1.0-py3-none-any.whl

**Manila support:**

The Everpure tab on the share detail views needs manila-ui in the same
Python environment as Horizon. The ``manila`` extra pulls it in; use
whichever form matches how you install::

  sudo pip install ".[manila]"
  sudo pip install "horizon-pure[manila]"

If Horizon was installed to run with a virtual environment you may need to
install using a different pip command, for example::

  $HORIZON_DIR/tools/with_venv.sh pip install .

As long as the ``horizon_pure`` module is importable by Horizon you should be
all set.

Copy the enabled file and the example settings file into Horizon's ``local``
directory::

  cp -rv ./horizon_pure/enabled $HORIZON_DIR/openstack_dashboard/local/
  cp -v ./horizon_pure/local_settings.d/_9999_pure_settings.py.example $HORIZON_DIR/openstack_dashboard/local/local_settings.d/_9999_pure_settings.py

Both files are also shipped inside the installed package, so when you
installed from a wheel and have no source checkout you can copy them from
``site-packages`` instead::

  PURE_DIR=$(python -c 'import horizon_pure, os; print(os.path.dirname(horizon_pure.__file__))')
  cp -rv $PURE_DIR/enabled $HORIZON_DIR/openstack_dashboard/local/
  cp -v $PURE_DIR/local_settings.d/_9999_pure_settings.py.example $HORIZON_DIR/openstack_dashboard/local/local_settings.d/_9999_pure_settings.py


Configuration
-------------

To configure the plugin, edit
``$HORIZON_DIR/openstack_dashboard/local/local_settings.d/_9999_pure_settings.py``.
There is one list per kind of backend. Leave a list empty, or out, when you
have no backends of that kind; the matching panel tab and summary block are
then not shown. Every ``api_token`` below is a placeholder: put your own
REST API tokens in, and keep the file readable only by the Horizon service
account::

    # Cinder FlashArray backends
    PURE_FLASHARRAYS = [
        {'san_ip': '10.0.0.10', 'api_token': 'REPLACE-WITH-API-TOKEN',
         'backend_name': 'pure-iscsi',          # cinder.conf enabled_backends section
         'verify_ssl': False,                   # optional, default False
         'ca_cert': '/etc/ssl/certs/pure.pem'}, # optional, implies verify
    ]
    # Manila FlashBlade backends
    PURE_FLASHBLADES = [
        {'mgmt_ip': '10.0.0.20', 'api_token': 'REPLACE-WITH-API-TOKEN',
         'backend_name': 'flashblade',          # manila.conf backend section name
         'verify_ssl': False, 'ca_cert': None},
    ]
    # Manila FlashArray Files backends
    PURE_FLASHARRAY_FILES = [
        {'san_ip': '10.0.0.10', 'api_token': 'REPLACE-WITH-API-TOKEN',
         'backend_name': 'flasharray-files',    # manila.conf backend section name
         'parent_fs': 'openstack',              # must equal the driver's pure_cluster_id
         'verify_ssl': False, 'ca_cert': None},
    ]
    PURE_MANILA_SHARE_NAME_TEMPLATE = 'share-%s'   # mirror manila.conf share_name_template
    PURE_API_TIMEOUT = 10        # seconds per REST call
    PURE_API_RETRIES = 1

``PURE_FLASHARRAYS`` was called ``PURE_FLASH_ARRAYS`` in 2.0.0; the old
name is not read any more, so rename it when upgrading.

You may repeat the entry dictionaries for as many backends as needed. The
same physical array may appear in more than one list (for example one Cinder
and one FlashArray Files backend on the same FlashArray); the summary totals
count each array once.

Common keys
~~~~~~~~~~~

san_ip / mgmt_ip
  The virtual IP or FQDN of the array's management interface. It must be
  reachable from the Horizon controllers. Either key name is accepted in
  every list; it is the same value as ``san_ip`` in ``cinder.conf``, and as
  ``flashblade_mgmt_vip`` or ``flasharray_mgmt_vip`` in ``manila.conf``.

api_token
  A valid REST API token for the array: ``pure_api_token`` in
  ``cinder.conf``, ``flashblade_api`` or ``flasharray_api`` in
  ``manila.conf``. The plugin never writes to the array, so a token for a
  read-only user is sufficient.

backend_name
  The name of the backend *section* in the service configuration file, which
  is how the plugin matches a volume or share to an array. For Cinder it is
  a name listed in ``enabled_backends`` in ``cinder.conf``; for Manila it is
  a name listed in ``enabled_share_backends`` in ``manila.conf``. Spell it
  exactly as in the configuration file. It is the section name, not the
  ``volume_backend_name`` / ``share_backend_name`` option, although the two
  are often the same string.

verify_ssl
  Optional, default ``False``: the array's TLS certificate is not verified,
  as in earlier releases of this plugin. Set it to ``True`` to verify
  against the system CA store.

ca_cert
  Optional path to a PEM bundle used to verify the array's certificate.
  Setting it turns verification on, whatever ``verify_ssl`` says.

PURE_API_TIMEOUT / PURE_API_RETRIES
  Seconds allowed for each REST call (default 10) and the number of
  connection attempts retried per call (default 1), so an array that stops
  answering costs at most ``PURE_API_TIMEOUT x (PURE_API_RETRIES + 1)``
  seconds, once. Whether it fails at first contact or later, such an array
  is shown as an ``Error: ...`` row (the share tab tells administrators the
  reason) and is not contacted again for 60 seconds, so one dead array does
  not stall every page load.

Cinder FlashArray backends (PURE_FLASHARRAYS)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

One entry per FlashArray Cinder backend. To find the names, look at the
output of ``cinder service-list``::

  +------------------+---------------------+------+---------+-------+----------------------------+-----------------+
  | Binary           | Host                | Zone | Status  | State | Updated_at                 | Disabled Reason |
  +------------------+---------------------+------+---------+-------+----------------------------+-----------------+
  | cinder-scheduler | devstack            | nova | enabled | up    | 2016-10-12T20:30:25.000000 | -               |
  | cinder-volume    | devstack@pure-iscsi | nova | enabled | up    | 2016-10-12T20:30:28.000000 | -               |
  +------------------+---------------------+------+---------+-------+----------------------------+-----------------+

The "Host" column of the cinder-volume rows is ``<host>@<backend_name>``;
the part after ``@`` is the ``backend_name`` to configure.

Manila FlashBlade backends (PURE_FLASHBLADES)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

One entry per FlashBlade Manila backend. ``manila service-list`` shows the
manila-share services as ``<host>@<backend_name>``, and an administrator
sees the same prefix in a share's ``host`` field
(``<host>@<backend_name>#<pool>``)::

  +--------------+---------------------------+------+---------+-------+
  | Binary       | Host                      | Zone | Status  | State |
  +--------------+---------------------------+------+---------+-------+
  | manila-share | devstack@flashblade       | nova | enabled | up    |
  | manila-share | devstack@flasharray-files | nova | enabled | up    |
  +--------------+---------------------------+------+---------+-------+

The FlashBlade driver names each file system after the Manila *share
instance*, not the share: ``(share_name_template % <share instance id>) +
"-manila"``, so ``share-<instance-uuid>-manila`` with the default template.
The instance id is not the share id shown in the dashboard. The plugin takes
the file system name from the share's export locations (the last path
segment of ``<data VIP>:/<file system>``) and, for administrators, from the
share instance list, so it finds the right object without any help.
``PURE_MANILA_SHARE_NAME_TEMPLATE`` is used only as a fallback when no export
location is available, and when the **Manila Shares** table on the
FlashBlade detail page parses instance ids back out of file system names. If
you changed ``share_name_template`` in ``manila.conf``, set
``PURE_MANILA_SHARE_NAME_TEMPLATE`` to the same value; otherwise leave it at
the default ``share-%s``.

Manila FlashArray Files backends (PURE_FLASHARRAY_FILES)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

One entry per FlashArray that serves Manila shares through the Everpure
FlashArray Files driver. That driver is proposed upstream in
`manila review 795180 <https://review.opendev.org/c/openstack/manila/+/795180>`_
and is not yet part of a Manila release; this plugin follows the object
naming of that review and needs Purity//FA 6.10.6 or later (REST API 2.54)
with FA Files enabled.

The driver creates every share as a managed directory
``<pure_cluster_id>:share-<share id>-manila`` (the API share id, not the
instance id) inside one parent file system, together with the policies
``share-<share id>-manila-nfs`` and ``share-<share id>-manila-quota``. The
``parent_fs`` key must be exactly the driver's ``pure_cluster_id`` for that
backend section (``openstack`` unless you changed it): the plugin lists and
looks up directories only inside that file system. ``share_name_template``
does not apply to this driver. The export name may differ from the directory
name when the tenant chose a mount point name; that is fine, because the
plugin resolves the directory from the share id rather than from the export
path.

Restart Horizon GUI
-------------------

After any changes to the configuration file, it is necessary to restart the
``httpd`` service provided by OpenStack Horizon. For example::

  sudo systemctl restart apache2

Using the Everpure Horizon GUI
------------------------------

After installing the plugin and restarting your httpd service, the
Everpure-related information is available in three places. The screenshots
below were taken before the Everpure rename, so labels and layout differ
slightly from 2.1.0.

1. As an administrator, navigate to **Admin** -> **System** -> **Everpure**.
   The panel starts with one summary block per configured kind of backend
   (capacity usage and object counts), followed by a tab for each kind:
   **FlashArray** (Cinder), **FlashBlade** (Manila) and **FlashArray Files**
   (Manila). A tab is shown only when its settings list has entries. The
   panel looks similar to this:

   .. image:: ./Horizon-1.JPG
      :width: 400
      :alt: Main Everpure Panel

   * Selecting the ``Array Name`` opens a new browser window to the array's
     Purity GUI.
   * Selecting the backend name (the ``Cinder Name`` column on the
     FlashArray tab) opens a detailed view of that specific backend, such as:

   .. image:: ./Horizon-3.JPG
      :width: 400
      :alt: Detailed Array Panel

   The FlashBlade and FlashArray Files detail views have an **Overview** tab
   (array identity, space and performance, with a link to the Purity GUI)
   and a **Manila Shares** tab that lists the file systems or managed
   directories Manila created on that backend. When manila-ui is installed,
   FlashArray Files rows link to the share's detail page and FlashBlade rows
   to the share instance's detail page (**Admin** -> **Share** -> **Share
   Instances**), from which the owning share is one click away; a FlashBlade
   file system is named after the share instance, not the share.

   The detail pages live at ``/admin/pure_panel/flasharrays/<backend>/``,
   ``/admin/pure_panel/flashblades/<backend>/`` and
   ``/admin/pure_panel/fafiles/<backend>/``. Before 2.1.0 the FlashArray
   page was ``/admin/pure_panel/<backend>/``; update any bookmarks.

2. As a project user, navigate to **Project** -> **Volumes** -> **Volumes**
   and select a volume provided by an Everpure Cinder driver. This gives an
   enhanced view of the volume with additional **Usage** information, for
   example:

   .. image:: ./Horizon-2.JPG
      :width: 400
      :alt: Enhanced Volume Panel

3. With manila-ui installed, open a share under **Project** -> **Share** ->
   **Shares** (or **Admin** -> **Share** -> **Shares**) and select the
   **Everpure** tab. It shows the share as the array sees it: the file system
   or managed directory name, provisioned size or quota, used, unique and
   snapshot space, data reduction, whether the limit is enforced, the number
   of snapshots, the NFS rules and exports, and current performance (read and
   write IOPS, MiB/s and latency).

   Administrators additionally see an **Array** section with the array name
   (linked to its Purity GUI), the Purity version and the Manila backend
   name: they can see the share's ``host``, from which the plugin resolves
   the backend directly. Project users cannot see ``host``, so the plugin
   looks the share up on each configured Manila backend in turn and shows
   the first match without revealing which array serves it. If no Manila
   backend is configured, or the object is not found on any array, the tab
   says so instead; the detail of why (which backends and names were tried,
   or why an array could not be reached) is shown to administrators only.

Uninstalling
------------

To uninstall the Everpure Horizon GUI run::

  sudo pip uninstall horizon-pure

and delete the enabled and settings files::

  rm $HORIZON_DIR/openstack_dashboard/local/enabled/_9999_pure_panel.py
  rm $HORIZON_DIR/openstack_dashboard/local/local_settings.d/_9999_pure_settings.py


Compatibility
-------------

This version (2.1.0) works with OpenStack 2024.2 (Dalmatian) and later
releases.

**Requirements:**

* OpenStack 2024.2 (Dalmatian) or later
* Python 3.10, 3.11, or 3.12
* Django 4.2 or later (as required by modern Horizon)
* Horizon from OpenStack 2024.2 or later
* manila-ui from the same OpenStack release as Horizon, if you want the
  share detail tab

**Legacy Compatibility:**

* For OpenStack Victoria and earlier releases, please use version 1.0.0 of
  this plugin
* This version **WILL NOT** work with OpenStack releases prior to 2024.2 due
  to Python and Django version requirements

See ``UPGRADE_NOTES.md`` for what changed between releases.


Known Issues
------------
* An array running Purity//FA 6.0.x will show Total Reduction as "0.00 to 1"
  if FA-Files is enabled on the array.
* The FlashArray Files support tracks a driver that is still under review
  upstream; if the driver's object naming changes before it merges, this
  plugin will need a matching update.

Development
-----------
Version 2.0.0 was developed with assistance from Augment AI to modernize the
codebase for OpenStack 2024.2 (Dalmatian) and migrate to the py-pure-client
SDK. Version 2.1.0 adds the Manila FlashBlade and FlashArray Files support
and completes the Everpure rename of the user-visible text.

Running the tests
~~~~~~~~~~~~~~~~~

The unit tests are Django tests that run with Horizon's test settings; no
array is contacted. With tox installed::

  tox -e py312                                        # unit tests
  tox -e pep8                                         # flake8 + hacking
  tox -e py312 -- horizon_pure.tests.test_registry    # a single module

Without tox, in an environment that has horizon, manila-ui and
py-pure-client installed::

  python -m django test --settings=horizon_pure.tests.settings horizon_pure
  flake8 horizon_pure

Support
-------
Please file bugs and issues at the Github issues page. The code and
documentation are released with no warranties or SLAs and are intended to be
supported through a community driven process.
