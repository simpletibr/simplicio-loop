"""Allows ``python -m simplicio_mapper.cli ...`` to keep working now that
``simplicio_mapper.cli`` is a package (issue #159) -- ``python -m <package>``
requires ``__main__.py``; ``__init__.py``'s own ``if __name__ == "__main__"``
guard only fires when that file is executed directly, not via ``-m``.
"""

from __future__ import annotations

import sys

from . import main

if __name__ == "__main__":
    sys.exit(main())
