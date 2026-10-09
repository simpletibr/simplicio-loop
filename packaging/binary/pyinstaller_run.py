"""Run PyInstaller with two small repairs for the standalone binary (issue #1576).

* ``base_library.zip`` lists its entries in the order of the PyInstaller module graph. Builds of one commit gave
  the same entries in a different order, so the SHA-256 of the executable changed. The runner sorts them by name.
* ``copy_metadata`` returns the whole ``.dist-info`` directory of a package, and PyInstaller calls it for every
  package whose version the code reads. The directory holds ``direct_url.json``, ``INSTALLER`` and ``RECORD``,
  which hold the path of the machine that built the executable. No code of the program reads them. The runner
  lists only the files the program can read and the licenses.

The names below are internals of the PyInstaller version that ``scripts/build_binary.py`` pins.
"""
import os
import sys

KEEP_METADATA = frozenset({"METADATA", "entry_points.txt", "top_level.txt", "WHEEL", "namespace_packages.txt"})
LICENSE_DIRECTORIES = ("licenses", "LICENSES")


def sorted_base_library_zip(original):
    """Wrap ``create_base_library_zip`` so that it writes the entries sorted by module name."""
    def create(filename, modules_toc, code_cache=None):
        return original(filename, sorted(modules_toc, key=lambda entry: entry[0]), code_cache)
    return create


def trimmed_copy_metadata(original):
    """Wrap ``copy_metadata`` so that a ``.dist-info`` directory becomes a list of the wanted files."""
    def copy_metadata(package_name, recursive=False):
        entries = []
        for source, target in original(package_name, recursive):
            if not os.path.isdir(source):  # an .egg-info file
                entries.append((source, target))
                continue
            for directory, subdirectories, files in os.walk(source):
                subdirectories.sort()
                relative = os.path.relpath(directory, source)
                licensed = relative.split(os.sep)[0] in LICENSE_DIRECTORIES
                for name in sorted(files):
                    if name in KEEP_METADATA and relative == "." or licensed:
                        entries.append((os.path.join(directory, name),
                                        target if relative == "." else os.path.join(target, relative)))
        return entries
    return copy_metadata


def main(arguments):
    import PyInstaller.__main__
    import PyInstaller.building.build_main as build_main
    import PyInstaller.building.utils as utils
    import PyInstaller.utils.hooks as hooks

    assert build_main.create_base_library_zip is utils.create_base_library_zip, "PyInstaller internals changed"
    patched = sorted_base_library_zip(utils.create_base_library_zip)
    utils.create_base_library_zip = build_main.create_base_library_zip = patched
    hooks.copy_metadata = trimmed_copy_metadata(hooks.copy_metadata)
    PyInstaller.__main__.run(arguments)


if __name__ == "__main__":
    main(sys.argv[1:])
