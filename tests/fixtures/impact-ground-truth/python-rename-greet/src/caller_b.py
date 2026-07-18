"""Real caller #2 of ``greeter.greet`` -- part of the ground-truth impact set."""

from src import greeter


def shout(name: str) -> str:
    return greeter.greet(name) + "!"
