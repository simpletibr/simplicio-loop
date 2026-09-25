"""Deterministic Python reference for the Fast-TurboQuant FWHT primitive."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal


Normalization = Literal["none", "orthonormal"]


def fwht(
    values: Sequence[float], *, normalization: Normalization = "orthonormal"
) -> tuple[float, ...]:
    """Return the Walsh-Hadamard transform of a finite power-of-two vector.

    The butterfly uses only additions and subtractions. ``orthonormal`` applies
    the single transform-wide scale factor required for a unitary transform;
    ``none`` returns the unscaled reference transform.
    """
    if normalization not in {"none", "orthonormal"}:
        raise ValueError("normalization must be 'none' or 'orthonormal'")
    if isinstance(values, (str, bytes, bytearray)):
        raise ValueError("values must be a finite numeric sequence")
    try:
        size = len(values)
    except TypeError as error:
        raise ValueError("values must be a finite numeric sequence") from error
    if size == 0 or size & (size - 1):
        raise ValueError("values length must be a non-empty power of two")

    transformed: list[float] = []
    for value in values:
        if isinstance(value, bool):
            raise ValueError("values must contain finite real numbers")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("values must contain finite real numbers") from error
        if not math.isfinite(number):
            raise ValueError("values must contain finite real numbers")
        transformed.append(number)

    width = 1
    while width < size:
        step = width * 2
        for start in range(0, size, step):
            for offset in range(width):
                left_index = start + offset
                right_index = left_index + width
                left = transformed[left_index]
                right = transformed[right_index]
                transformed[left_index] = left + right
                transformed[right_index] = left - right
        width = step

    if normalization == "orthonormal":
        scale = math.sqrt(size)
        transformed = [value / scale for value in transformed]
    return tuple(transformed)
