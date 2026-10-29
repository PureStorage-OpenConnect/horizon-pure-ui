# Upgrade Notes

## 2.0.0 -> 2.1.0 (Manila support and Everpure branding)

### Summary

Version 2.1.0 extends the plugin from Cinder FlashArray backends to the
Manila FlashBlade and FlashArray Files backends, and completes the Everpure
rename of the user-visible text. Nothing you installed for 2.0.0 has to be
renamed: the distribution (`horizon-pure`), the Python package
(`horizon_pure`), the panel slug (`pure_panel`), the enabled file and every
`PURE_*` setting name are unchanged, so an existing
`_9999_pure_settings.py` keeps working as it is.

### Manila support

- The **Admin -> System -> Everpure** panel now has up to three tabs:
  **FlashArray** (Cinder backends), **FlashBlade** (Manila backends) and
  **FlashArray Files** (Manila backends). A tab is shown only when its
  settings list has entries, and the summary blocks at the top of the panel
  follow the same rule.
- New detail pages for FlashBlade and FlashArray Files backends with an
  **Overview** tab (array identity, space, performance, link to the Purity
  GUI) and a **Manila Shares** tab listing the file systems or managed
  directories that Manila created on that backend. When manila-ui is
  installed, FlashArray Files rows link to the share detail page and
  FlashBlade rows to the share instance detail page (a FlashBlade file
  system is named after the share instance, not the share).
- When manila-ui is installed, an **Everpure** tab is appended to the share
  detail page in both the Project and the Admin dashboard. It shows the
  share's file system (FlashBlade) or managed directory (FlashArray Files):
  provisioned size or quota, used, unique and snapshot space, data
  reduction, limit enforcement, snapshot count, NFS rules and exports, and
  current read/write IOPS, bandwidth and latency. Administrators also see
  the array identity (name, Purity GUI link, Purity version, backend name)
  and the detail of a failed lookup (which backends and names were tried,
  or why an array could not be reached); project users do not, because
  they cannot see the share's `host`.
- manila-ui is optional. `pip install "horizon-pure[manila]"` installs it;
  without it the plugin logs one info message at start-up and skips the
  share tab. The panel tabs for FlashBlade and FlashArray Files do not need
  manila-ui.
- The FlashArray Files support follows the Everpure FlashArray Manila driver
  proposed upstream in
  [review 795180](https://review.opendev.org/c/openstack/manila/+/795180);
  it needs Purity//FA 6.10.6 or later (REST API 2.54).

### New settings

All new settings have defaults; an absent or empty list simply disables that
kind of backend.

- `PURE_FLASH_BLADES` and `PURE_FLASH_ARRAY_FILES`: lists of Manila backends
  with the same shape as `PURE_FLASH_ARRAYS`. `backend_name` is the backend
  section name from `enabled_share_backends` in `manila.conf`. For FlashArray
  Files, `parent_fs` must equal the driver's `pure_cluster_id` (default
  `openstack`).
- `mgmt_ip` is accepted as an alias of `san_ip` in every list.
- Optional per-entry keys in every list: `verify_ssl` and `ca_cert`. The
  default is still `verify_ssl: False`, exactly what 2.0.0 hard-coded, so
  nothing changes for existing entries. Setting `ca_cert` to a PEM bundle
  turns verification on.
- `PURE_MANILA_SHARE_NAME_TEMPLATE` (default `share-%s`): mirror of
  `share_name_template` in `manila.conf`, used to derive FlashBlade file
  system names from share instance ids.
- `PURE_API_TIMEOUT` (default 10 seconds per REST call) and
  `PURE_API_RETRIES` (default 1): the connection attempts retried per call,
  so one failed call costs at most `PURE_API_TIMEOUT x (PURE_API_RETRIES +
  1)` seconds. 2.0.0 used the SDK defaults, so an unreachable array could
  stall every page load. In 2.1.0 an array that fails, at first contact or
  later, is shown as an `Error: ...` row and is not contacted again for 60
  seconds.

See the shipped `horizon_pure/local_settings.d/_9999_pure_settings.py.example`
for the full annotated example.

### URL change

- The FlashArray detail page moved from `/admin/pure_panel/<backend>/` to
  `/admin/pure_panel/flasharrays/<backend>/`. The URL name
  `horizon:admin:pure_panel:flasharrays:detail` is unchanged, so links
  rendered by Horizon follow automatically; only bookmarks need updating.
- FlashBlade detail pages are at `/admin/pure_panel/flashblades/<backend>/`
  and FlashArray Files detail pages at `/admin/pure_panel/fafiles/<backend>/`.

### Behaviour changes on existing pages

- Summary totals count each array once, even when the same array appears in
  several backend entries (for example one Cinder and one Manila backend on
  the same FlashArray). This removes the "double counted" known issue of
  2.0.0.
- On the volume detail view the performance rows are labelled **Read IOPS**,
  **Write IOPS**, **Read Bandwidth** and **Write Bandwidth**; bandwidth is
  derived from the array's byte counters and shown in MiB/s. 2.0.0 showed
  the IOPS counters under the bandwidth labels.
- An unreachable FlashArray row now shows its backend id instead of a
  literal placeholder.
- The page title and heading of the panel say **Everpure**.

### Dependencies and packaging

- `py-pure-client>=1.58.0` (was `>=1.47.0`).
- `setup.cfg` was removed; `pyproject.toml` is the only build definition
  and the package metadata now names Everpure as the author. `setup.py`
  remains as a shim for tools that still call it.
- A `tox.ini` is included: `tox -e py312` runs the unit tests and
  `tox -e pep8` runs flake8 with the OpenStack hacking rules.

### Upgrade steps

1. Install the new version over the old one, for example
   `sudo pip install --upgrade .` from a checkout, or
   `sudo pip install --upgrade horizon_pure-2.1.0-py3-none-any.whl`.
   Add `[manila]` (`".[manila]"` / `"horizon-pure[manila]"`) if manila-ui is
   not already installed and you want the share tab.
2. Keep your existing `_9999_pure_settings.py`; add `PURE_FLASH_BLADES`
   and/or `PURE_FLASH_ARRAY_FILES` entries for your Manila backends, and the
   optional settings if you need them.
3. The enabled file `_9999_pure_panel.py` is functionally unchanged; copying
   it again is harmless.
4. Restart Horizon: `sudo systemctl restart apache2`.

## 1.0.0 -> 2.0.0 (OpenStack 2024.2 Dalmatian)

### Summary of Changes

This section outlines the changes made to upgrade the horizon-pure-ui plugin from version 1.0.0 (OpenStack Victoria) to version 2.0.0 (OpenStack 2024.2 Dalmatian and later).

### Key Changes

#### 1. Python Version Support
- **Removed:** Python 2.7 and Python 3.4 support
- **Added:** Python 3.10, 3.11, and 3.12 support
- **Minimum Required:** Python 3.10

#### 2. Django Compatibility Updates
- **Changed:** Replaced deprecated `ugettext_lazy` with `gettext_lazy` throughout the codebase
- **Reason:** Django 4.0+ removed the `ugettext_lazy` alias
- **Changed:** Replaced deprecated `url()` with `re_path()` in URL configurations
- **Reason:** Django 4.0+ removed `django.conf.urls.url()` in favor of `django.urls.re_path()`
- **Files Updated:**
  - `horizon_pure/overrides.py`
  - `horizon_pure/pure_panel/panel.py`
  - `horizon_pure/pure_panel/tables.py`
  - `horizon_pure/pure_panel/tabs.py`
  - `horizon_pure/pure_panel/views.py`
  - `horizon_pure/pure_panel/flasharrays/tabs.py`
  - `horizon_pure/pure_panel/urls.py`
  - `horizon_pure/pure_panel/flasharrays/urls.py`

#### 3. Array SDK Migration (py-pure-client)
- **Replaced:** `purestorage` SDK (REST API 1.x) with `py-pure-client` SDK (REST API 2.x)
- **requirements.txt:**
  - Changed from `purestorage>=1.19.0` to `py-pure-client>=1.47.0`
  - Added explicit `pbr>=2.0.0` requirement
- **setup.py:**
  - Updated pbr requirement from `>=1.8` to `>=2.0.0`
  - Removed Python 2.7 compatibility workaround code
- **API Changes:**
  - Updated `horizon_pure/api/pure_flash_array.py` to use py-pure-client REST 2.x API
  - Changed from `purestorage.FlashArray` to `pypureclient.flasharray.Client`
  - Updated all API method calls to use REST 2.x endpoints
  - Changed exception handling from `purestorage.PureError` to generic `Exception`
  - Added `verify_ssl=False` to client initialization for self-signed certificate support
- **Performance Improvements:**
  - Uses `total_item_count=True` parameter in API calls to efficiently get counts without retrieving all items
  - Uses proper `get_volume_snapshots()` method instead of filtering volumes
  - Significantly improves performance for arrays with many volumes, snapshots, hosts, or protection groups
- **Dynamic Capacity Limits:**
  - Uses `get_controllers()` API to detect array model and Purity version
  - Capacity limits are dynamically determined based on actual hardware capabilities
  - Supports all FlashArray models: XL-class, X-class (X10-X90), C-class (C20-C90), E-class, RC20
  - Accurate limits for volumes, snapshots, and hosts per model
  - Protection groups (pgroups) max is 250 for all arrays
- **Minimum FlashArray Version:** Purity 6.1.0 or later (REST API 2.x support required)

#### 4. Package Metadata Updates
- **Version:** Bumped from 1.0.0 to 2.0.0
- **Python Classifiers:** Updated to reflect Python 3.10, 3.11, 3.12 support
- **Removed:** Python 2.7 and 3.4 classifiers

#### 5. Documentation Updates (README.rst)
- Updated compatibility section to reflect:
  - OpenStack 2024.2 (Dalmatian) or later support
  - Python 3.10+ requirement
  - Django 4.2+ requirement
  - Legacy version (1.0.0) for older OpenStack releases

### Installation

The installation process remains the same:

```bash
git clone https://github.com/PureStorage-OpenConnect/horizon-pure-ui.git
cd horizon-pure-ui
sudo pip install .
```

### Compatibility Matrix

| Plugin Version | OpenStack Release   | Python Version   | Django Version |
|----------------|---------------------|------------------|----------------|
| 1.0.0          | Victoria            | 2.7, 3.4+        | 2.x - 3.x      |
| 2.0.0          | 2024.2 (Dalmatian)+ | 3.10, 3.11, 3.12 | 4.2+           |
| 2.1.0          | 2024.2 (Dalmatian)+ | 3.10, 3.11, 3.12 | 4.2+           |

### Breaking Changes

1. **Python 2.7 Support Removed:** This version will not work with Python 2.7
2. **Older OpenStack Versions:** Not compatible with OpenStack releases prior to 2024.2
3. **Django 3.x and Earlier:** Not compatible with Django versions prior to 4.2
4. **Array SDK Changed:** Migrated from the `purestorage` SDK to the `py-pure-client` SDK
   - FlashArrays must support REST API 2.x (Purity 6.1.0 or later)
   - The old `purestorage` SDK is no longer used or supported

### Migration Guide

If you are upgrading from version 1.0.0:

1. Ensure your OpenStack deployment is running 2024.2 (Dalmatian) or later
2. Ensure Python 3.10 or later is installed
3. Uninstall the old version: `sudo pip uninstall horizon-pure`
4. Install the new version: `sudo pip install .`
5. Restart your Horizon service: `sudo systemctl restart apache2`

### Testing

After upgrading, verify the plugin works correctly by:

1. Logging into Horizon as an administrator
2. Navigate to **Admin** -> **System** -> **Everpure**
3. Verify that your FlashArrays are displayed correctly
4. Check volume details to ensure the Everpure metrics are shown

### Known Issues

The same known issues from version 1.0.0 applied to 2.0.0:
- An array running Purity//FA 6.0.x will show Total Reduction as "0.00 to 1" if FA-Files is enabled
- Using the same array in different cinder stanzas will confuse calculations (fixed in 2.1.0, see above)

## Support

Please file bugs and issues at the GitHub issues page. The code and documentation are released with no warranties or SLAs and are intended to be supported through a community-driven process.
