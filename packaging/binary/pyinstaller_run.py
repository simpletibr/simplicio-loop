"""Run PyInstaller with a deterministic ``base_library.zip`` (issue #1576).

PyInstaller writes the entries of ``base_library.zip`` in the order of its module graph. Builds of one
commit gave the same entries in a different order, so the SHA-256 of the executable changed. This runner
sorts the entries by module name and then runs PyInstaller with the same arguments. It needs the
PyInstaller version that ``scripts/build_binary.py`` pins: the names below are internals of that version.
"""
import sys

import PyInstaller.__main__
import PyInstaller.building.build_main as build_main
import PyInstaller.building.utils as utils

_create_base_library_zip = utils.create_base_library_zip
assert build_main.create_base_library_zip is _create_base_library_zip, "PyInstaller internals changed"


def _sorted_base_library_zip(filename, modules_toc, code_cache=None):
    return _create_base_library_zip(filename, sorted(modules_toc, key=lambda entry: entry[0]), code_cache)


utils.create_base_library_zip = _sorted_base_library_zip
build_main.create_base_library_zip = _sorted_base_library_zip

if __name__ == "__main__":
    PyInstaller.__main__.run(sys.argv[1:])
