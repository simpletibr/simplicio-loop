"""Real caller #1 of ``greeter.greet`` -- part of the ground-truth impact set."""

from src.greeter import greet


def announce(name: str) -> str:
    return greet(name).upper()
