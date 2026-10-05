"""Statistics used in evaluation reports."""
import math

import pytest

from eval.stats import percentile, wilson_interval


def test_wilson_interval_for_a_perfect_score_is_not_a_perfect_interval():
    low, high = wilson_interval(30, 30)

    assert high == pytest.approx(1.0)
    assert 0.88 < low < 0.89  # 30 out of 30 only proves "at least about 89%"


def test_wilson_interval_known_value():
    # Worked by hand: z^2 = 3.8416, centre = (0.95 + 0.0192) / 1.0384 = 0.9333,
    # margin = 1.96 * sqrt(0.000475 + 0.000096) / 1.0384 = 0.0451  ->  0.8882 to 0.9784.
    low, high = wilson_interval(95, 100)

    assert low == pytest.approx(0.8882, abs=0.001)
    assert high == pytest.approx(0.9784, abs=0.001)


def test_the_interval_narrows_as_the_sample_grows():
    small = wilson_interval(9, 10)
    large = wilson_interval(90, 100)

    assert (large[1] - large[0]) < (small[1] - small[0])


def test_zero_trials_gives_the_whole_range():
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_zero_successes_has_a_zero_lower_bound():
    low, high = wilson_interval(0, 20)

    assert low == 0.0 and 0 < high < 0.2


def test_percentiles_use_linear_interpolation():
    values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

    assert percentile(values, 50) == pytest.approx(5.5)
    assert percentile(values, 95) == pytest.approx(9.55)
    assert percentile([7], 95) == 7
    assert math.isnan(percentile([], 50))
