"""PyInstaller hook: bundle the three packages of the single wheel (issue #1576).

The wheel holds simplicio_loop, simplicio_mapper (survey) and simplicio (dev-cli). The entry
points are loaded by name at run time, so the import graph does not see them. The hook asks
PyInstaller for every submodule and every data file instead of listing them by hand.

Some .py files are data, not modules: the hooks and scripts under ``_bundle`` that the installer
copies, the project templates of the dev-cli, and provider scripts. They sit in directories without
``__init__.py``. The hook ships them as files.
"""
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

# The metadata gives importlib.metadata the version and the console scripts that frozen.py reads.
datas = copy_metadata("simplicio-loop")
for package in PACKAGES:
    package_dir = Path(get_package_paths(package)[1])
    datas += [
        (source, target) for source, target in collect_data_files(package, include_py_files=True)
        if not (source.endswith(".py") and _is_module(source, package_dir))
    ]
