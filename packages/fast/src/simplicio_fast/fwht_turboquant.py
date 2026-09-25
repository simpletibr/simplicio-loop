"""Python-only FWHT plus signed 4-bit packed reference contract."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from .fwht import fwht
from .turboquant import (
    QuantizationError,
    _as_vector,
    _round_half_away_from_zero,
    _splitmix64,
    _validate_seed,
    pack_nibbles,
    unpack_nibbles,
)

SCHEMA = "simplicio.fast.fwht-turboquant-4bit/v1"
Normalization = Literal["orthonormal"]
_MASK64 = (1 << 64) - 1
_MIN_CODE = -8
_MAX_CODE = 7


def _next_power_of_two(dimension: int) -> int:
    padded = 1
    while padded < dimension:
        padded <<= 1
    return padded


def _rademacher_signs(dimension: int, seed: int) -> tuple[int, ...]:
    state = _validate_seed(seed)
    signs: list[int] = []
    for _ in range(dimension):
        state = _splitmix64(state)
        signs.append(-1 if state & 1 else 1)
    return tuple(signs)


def _validate_input(values: object) -> tuple[float, ...]:
    if isinstance(values, (str, bytes, bytearray)):
        raise QuantizationError("values must be a finite non-empty iterable")
    try:
        raw = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise QuantizationError("values must be a finite non-empty iterable") from error
    if any(isinstance(value, bool) for value in raw):
        raise QuantizationError("values must contain finite real numbers")
    return _as_vector(raw)


@dataclass(frozen=True, slots=True)
class FwhtQuantizedVector:
    """Immutable, padded FWHT/4-bit reference vector; never a production claim."""

    dimension: int
    padded_dimension: int
    seed: int
    scale: float
    packed: bytes
    normalization: Normalization = "orthonormal"

    def __post_init__(self) -> None:
        if (
            isinstance(self.dimension, bool)
            or not isinstance(self.dimension, int)
            or self.dimension < 1
        ):
            raise QuantizationError("dimension must be a positive integer")
        if self.padded_dimension != _next_power_of_two(self.dimension):
            raise QuantizationError("padded_dimension must be the next power of two")
        if (
            isinstance(self.seed, bool)
            or not isinstance(self.seed, int)
            or not 0 <= self.seed <= _MASK64
        ):
            raise QuantizationError("seed must be a normalized unsigned 64-bit integer")
        if self.normalization != "orthonormal":
            raise QuantizationError("normalization must be orthonormal")
        if (
            not isinstance(self.scale, (int, float))
            or isinstance(self.scale, bool)
            or not math.isfinite(self.scale)
            or self.scale <= 0
        ):
            raise QuantizationError("scale must be a positive finite number")
        if not isinstance(self.packed, bytes):
            raise QuantizationError("packed values must be bytes")
        unpack_nibbles(self.packed, self.padded_dimension)

    @property
    def schema(self) -> str:
        return SCHEMA

    @property
    def codes(self) -> tuple[int, ...]:
        return unpack_nibbles(self.packed, self.padded_dimension)


def quantize_fwht(values: object, seed: int = 0) -> FwhtQuantizedVector:
    """Apply seeded Rademacher signs, orthonormal FWHT, and packed signed 4-bit quantization."""
    vector = _validate_input(values)
    normalized_seed = _validate_seed(seed)
    padded_dimension = _next_power_of_two(len(vector))
    padded = vector + (0.0,) * (padded_dimension - len(vector))
    signs = _rademacher_signs(padded_dimension, normalized_seed)
    signed = tuple(value * sign for value, sign in zip(padded, signs, strict=True))
    transformed = fwht(signed, normalization="orthonormal")
    peak = max(abs(value) for value in transformed)
    scale = peak / _MAX_CODE if peak else 1.0
    codes = tuple(
        max(_MIN_CODE, min(_MAX_CODE, _round_half_away_from_zero(value / scale)))
        for value in transformed
    )
    return FwhtQuantizedVector(
        dimension=len(vector),
        padded_dimension=padded_dimension,
        seed=normalized_seed,
        scale=scale,
        packed=pack_nibbles(codes),
    )


def dequantize_fwht(vector: FwhtQuantizedVector) -> tuple[float, ...]:
    """Decode the Python reference vector and remove deterministic zero padding."""
    if not isinstance(vector, FwhtQuantizedVector):
        raise QuantizationError("vector must be an FwhtQuantizedVector")
    signs = _rademacher_signs(vector.padded_dimension, vector.seed)
    transformed = tuple(code * vector.scale for code in vector.codes)
    signed = fwht(transformed, normalization=vector.normalization)
    restored = tuple(value * sign for value, sign in zip(signed, signs, strict=True))
    return restored[: vector.dimension]


__all__ = ["FwhtQuantizedVector", "SCHEMA", "dequantize_fwht", "quantize_fwht"]
