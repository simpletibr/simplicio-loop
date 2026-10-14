"""PyInstaller entry script of the standalone binary (issue #1576). The logic is in simplicio_loop.frozen."""
from simplicio_loop.frozen import main

raise SystemExit(main())
