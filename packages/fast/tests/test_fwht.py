import math
import unittest

from simplicio_fast.fwht import fwht


class FwhtReferenceTest(unittest.TestCase):
    def test_unscaled_golden_vector_uses_addition_subtraction_butterfly(self) -> None:
        self.assertEqual(
            (10.0, -2.0, -4.0, 0.0), fwht((1, 2, 3, 4), normalization="none")
        )

    def test_orthonormal_golden_vector_has_unitary_scale(self) -> None:
        result = fwht((1, 2, 3, 4))
        for actual, expected in zip(result, (5.0, -1.0, -2.0, 0.0)):
            self.assertAlmostEqual(expected, actual)

    def test_orthonormal_transform_is_its_own_inverse(self) -> None:
        values = (0.25, -1.0, 2.0, 3.5, -4.0, 0.0, 1.25, 8.0)
        for actual, expected in zip(fwht(fwht(values)), values):
            self.assertAlmostEqual(expected, actual)

    def test_unscaled_transform_round_trips_with_dimension_factor(self) -> None:
        values = (1.5, -2.0, 0.0, 4.25)
        round_trip = fwht(fwht(values, normalization="none"), normalization="none")
        for actual, expected in zip(round_trip, (4 * value for value in values)):
            self.assertAlmostEqual(expected, actual)

    def test_input_is_unchanged_and_result_is_deterministic_tuple(self) -> None:
        values = [1.0, -2.0]
        first = fwht(values)
        second = fwht(values)
        self.assertEqual([1.0, -2.0], values)
        self.assertIsInstance(first, tuple)
        self.assertEqual(first, second)

    def test_length_and_values_are_validated(self) -> None:
        for values in ((), (1, 2, 3)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                fwht(values)
        for values in ((math.nan, 1), (math.inf, 1), (True, 0), (object(), 0)):
            with self.subTest(values=values), self.assertRaises(ValueError):
                fwht(values)

    def test_normalization_and_input_type_are_validated(self) -> None:
        with self.assertRaises(ValueError):
            fwht((1, 2), normalization="forward")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            fwht("12")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            fwht(None)  # type: ignore[arg-type]

    def test_single_element_vector_is_supported(self) -> None:
        self.assertEqual((7.0,), fwht((7,), normalization="none"))
        self.assertEqual((7.0,), fwht((7,)))


if __name__ == "__main__":
    unittest.main()
