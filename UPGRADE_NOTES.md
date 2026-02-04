# Upgrade to OpenStack 2024.2 (Dalmatian) - Version 2.0.0

## Summary of Changes

This document outlines the changes made to upgrade the horizon-pure-ui plugin from version 1.0.0 (OpenStack Victoria) to version 2.0.0 (OpenStack 2024.2 Dalmatian and later).

## Key Changes

### 1. Python Version Support
- **Removed:** Python 2.7 and Python 3.4 support
- **Added:** Python 3.10, 3.11, and 3.12 support
- **Minimum Required:** Python 3.10

### 2. Django Compatibility Updates
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

### 3. Pure Storage SDK Migration
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
  - Accurate limits for volumes, snapshots, hosts, and protection groups per model
- **Minimum FlashArray Version:** Purity 6.1.0 or later (REST API 2.x support required)

### 4. Package Metadata Updates (setup.cfg)
- **Version:** Bumped from 1.0.0 to 2.0.0
- **Python Classifiers:** Updated to reflect Python 3.10, 3.11, 3.12 support
- **Removed:** Python 2.7 and 3.4 classifiers

### 5. Documentation Updates (README.rst)
- Updated compatibility section to reflect:
  - OpenStack 2024.2 (Dalmatian) or later support
  - Python 3.10+ requirement
  - Django 4.2+ requirement
  - Legacy version (1.0.0) for older OpenStack releases

## Installation

The installation process remains the same:

```bash
git clone https://github.com/PureStorage-OpenConnect/horizon-pure-ui.git
cd horizon-pure-ui
sudo pip install .
```

## Compatibility Matrix

| Plugin Version | OpenStack Release | Python Version | Django Version |
|---------------|-------------------|----------------|----------------|
| 1.0.0         | Victoria          | 2.7, 3.4+      | 2.x - 3.x      |
| 2.0.0         | 2024.2 (Dalmatian)+ | 3.10, 3.11, 3.12 | 4.2+          |

## Breaking Changes

1. **Python 2.7 Support Removed:** This version will not work with Python 2.7
2. **Older OpenStack Versions:** Not compatible with OpenStack releases prior to 2024.2
3. **Django 3.x and Earlier:** Not compatible with Django versions prior to 4.2
4. **Pure Storage SDK Changed:** Migrated from `purestorage` SDK to `py-pure-client` SDK
   - FlashArrays must support REST API 2.x (Purity 6.1.0 or later)
   - The old `purestorage` SDK is no longer used or supported

## Migration Guide

If you are upgrading from version 1.0.0:

1. Ensure your OpenStack deployment is running 2024.2 (Dalmatian) or later
2. Ensure Python 3.10 or later is installed
3. Uninstall the old version: `sudo pip uninstall horizon-pure`
4. Install the new version: `sudo pip install .`
5. Restart your Horizon service: `sudo systemctl restart apache2`

## Testing

After upgrading, verify the plugin works correctly by:

1. Logging into Horizon as an administrator
2. Navigate to **Admin** → **System** → **Pure Storage**
3. Verify that your FlashArrays are displayed correctly
4. Check volume details to ensure Pure Storage metrics are shown

## Known Issues

The same known issues from version 1.0.0 apply:
- An array running Purity//FA 6.0.x will show Total Reduction as "0.00 to 1" if FA-Files is enabled
- Using the same array in different cinder stanzas will confuse calculations

## Support

Please file bugs and issues at the GitHub issues page. The code and documentation are released with no warranties or SLAs and are intended to be supported through a community-driven process.

