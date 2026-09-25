"""Deliberate noise file: never imports or calls ``greeter.greet``.

Part of the ground-truth *negative* set -- if a prediction includes this
file it counts against precision.
"""


def noop() -> int:
    return 1
