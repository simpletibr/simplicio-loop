__version__ = "0.18.13"


def mapper_module():
    """Resolve the optional Mapper module only when a caller requests it."""
    from .mapper_api import mapper_module as resolve

    return resolve()


def mapper_version():
    """Resolve the installed Mapper distribution version on demand."""
    from .mapper_api import mapper_version as resolve

    return resolve()


__all__ = ["__version__", "mapper_module", "mapper_version"]
