"""The change site for this fixture's ground-truth scenario.

Ground truth (see ../ground_truth.json): renaming ``greet`` to
``greet_person`` requires touching every file that imports or calls it.
"""


def greet(name: str) -> str:
    """Return a greeting for ``name``."""
    return f"Hello, {name}!"
