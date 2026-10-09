"""Run PyInstaller with two small repairs for the standalone binary (issue #1576).

* ``base_library.zip`` lists its entries in the order of the PyInstaller module graph. Builds of one commit gave
  the same entries in a different order, so the SHA-256 of the executable changed. The runner sorts them by name.
* PyInstaller copies the whole ``.dist-info`` of each package whose version the code reads. That includes
  ``direct_url.json``, ``INSTALLER`` and ``RECORD``, which hold the path of the machine that built the
  executable. No code of the program reads them, so the runner leaves them out.

The names below are internals of the PyInstaller version that ``scripts/build_binary.py`` pins.
"""
import os
import sys

INSTALL_RECORDS = frozenset({"direct_url.json", "INSTALLER", "RECORD", "REQUESTED", "uv_cache.json"})


def sorted_base_library_zip(original):
    """Wrap ``create_base_library_zip`` so that it writes the entries sorted by module name."""
    def create(filename, modules_toc, code_cache=None):
        return original(filename, sorted(modules_toc, key=lambda entry: entry[0]), code_cache)
    return create


def without_install_records(original):
    """Wrap ``PyiModuleGraph.metadata_required`` so that its files exclude the install records."""
    def metadata_required(self):
        return {(source, target) for source, target in original(self)
                if os.path.basename(source) not in INSTALL_RECORDS}
    return metadata_required


def main(arguments):
    import PyInstaller.__main__
    import PyInstaller.building.build_main as build_main
    import PyInstaller.building.utils as utils
    import PyInstaller.depend.analysis as analysis

    assert build_main.create_base_library_zip is utils.create_base_library_zip, "PyInstaller internals changed"
    patched = sorted_base_library_zip(utils.create_base_library_zip)
    utils.create_base_library_zip = build_main.create_base_library_zip = patched
    analysis.PyiModuleGraph.metadata_required = without_install_records(analysis.PyiModuleGraph.metadata_required)
    PyInstaller.__main__.run(arguments)


if __name__ == "__main__":
    main(sys.argv[1:])
