"""PyInstaller hook: bundle the three packages of the single wheel (issue #1576).

The wheel holds simplicio_loop, simplicio_mapper (survey) and simplicio (dev-cli). The entry
points are loaded by name at run time, so the import graph does not see them. The hook asks
PyInstaller for every submodule and every data file instead of listing them by hand.
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

PACKAGES = ("simplicio_loop", "simplicio_mapper", "simplicio")

hiddenimports = [name for package in PACKAGES for name in collect_submodules(package)]

# The metadata gives importlib.metadata the version and the console scripts that frozen.py reads.
datas = copy_metadata("simplicio-loop")
for package in PACKAGES:
    datas += collect_data_files(package)
# The installer copies the hooks and scripts under _bundle as files, so their .py files are data.
datas += collect_data_files("simplicio_loop", include_py_files=True, subdir="_bundle")
