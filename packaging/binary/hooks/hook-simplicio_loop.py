"""PyInstaller hook: bundle the three packages of the single wheel (issue #1576).

The wheel holds simplicio_loop, simplicio_mapper (survey) and simplicio (dev-cli). The entry
points are loaded by name at run time, so the import graph does not see them. The hook asks
PyInstaller for every submodule and every data file instead of listing them by hand.

Some .py files are data, not modules: the hooks and scripts under ``_bundle`` that the installer
copies, the project templates of the dev-cli, and provider scripts. They sit in directories without
``__init__.py``. The hook ships them as files.

The metadata of the distribution keeps only what the program reads. ``direct_url.json``, ``INSTALLER`` and
``RECORD`` hold the path of the machine that built the executable, so they stay out. The module
``_sysconfigdata`` of the build Python holds that path too, and no code of the program needs it.
"""
import sysconfig
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata, get_package_paths

PACKAGES = ("simplicio_loop", "simplicio_mapper", "simplicio")


def _is_module(source, package_dir):
    """True when every directory from the file up to the package has an __init__.py."""
    directory = Path(source).parent
    while True:
        if not (directory / "__init__.py").is_file():
            return False
        if directory == package_dir:
            return True
        directory = directory.parent


hiddenimports = [name for package in PACKAGES for name in collect_submodules(package)]

KEEP_METADATA = ("METADATA", "entry_points.txt", "top_level.txt", "WHEEL")

# importlib.metadata reads the version and the console scripts that frozen.py uses.
datas = [(source, target) for source, target in copy_metadata("simplicio-loop") if Path(source).name in KEEP_METADATA]
excludedimports = [sysconfig._get_sysconfigdata_name()]
for package in PACKAGES:
    package_dir = Path(get_package_paths(package)[1])
    datas += [
        (source, target) for source, target in collect_data_files(package, include_py_files=True)
        if not (source.endswith(".py") and _is_module(source, package_dir))
    ]
