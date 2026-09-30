"""The meta-analysis arithmetic under the clinical scorecard, checked by hand.

Every case of docs/design/clinical-scorecard-statistics.md section 6 is asserted to four
decimal places, with the properties of section 7.1, the edge cases each function must meet
(one study, zero variance, zero cells, bounds, empty and non-finite input), and where a
method has a well-known published example, that example recomputed.
"""

import ast
import math
from pathlib import Path

import numpy as np
import pytest

import meta_stats as M


def near(value):
    return pytest.approx(value, abs=1e-4)


def assert_close(got: dict, want: dict):
    """Every key of ``want`` in ``got``, numbers to four places, lists element by element."""
    assert got is not None
    for key, value in want.items():
        if isinstance(value, float):
            assert got[key] == near(value), key
        elif isinstance(value, list):
            assert got[key] == [near(v) for v in value], key
        else:
            assert got[key] == value, key


# --- the module is pure -------------------------------------------------------------
def test_the_module_reads_no_database_and_knows_no_drug():
    tree = ast.parse(Path(M.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "math", "re", "functools", "statistics", "numpy"}


def test_the_constants_are_the_spec_values():
    assert M.Z95 == pytest.approx(1.959964, abs=1e-6)
    assert M.Z95 == M.z_of_level(95)
    assert M.Z_CAP == 5.0
    assert M.P_FLOOR == 1e-6
    assert M.OFF_CENTRE == 0.25


# --- 6.1 levels and p-values --------------------------------------------------------
@pytest.mark.parametrize("level, z", [
    (95, 1.959964), (90, 1.644854), (0.95, 1.959964), (96.85, 2.150699), (100, None),
    # edges: a level must be posted, and lie strictly inside (50, 100)
    (None, None), (50, None), (0.5, None), (1.0, None), (0, None), (-95, None),
    (float("nan"), None), (float("inf"), None), ("abc", None), (True, None),
    ("95", 1.959964), (99.99, 3.890592), (80, 1.281552),
])
def test_z_of_level(level, z):
    got = M.z_of_level(level)
    assert got is None if z is None else got == near(z)


@pytest.mark.parametrize("text, want", [
    ("<0.001", (0.001, "below")), ("0.0003", (0.0003, "exact")), (">0.05", (0.05, "above")),
    ("NA", None), ("1.4", None),
    # edges
    (None, None), ("", None), ("<.0001", (0.0001, "below")), ("p = 0.03", (0.03, "exact")),
    ("≤0.05", (0.05, "below")), ("≥0.2", (0.2, "above")), ("0", (0.0, "exact")),
    ("1", (1.0, "exact")), (0.0003, (0.0003, "exact")), ("3.2E-05", (3.2e-05, "exact")),
    ("-0.01", None), ("nan", None), (float("nan"), None), (True, None), ("NS", None),
])
def test_parse_p(text, want):
    got = M.parse_p(text)
    if want is None:
        assert got is None
    else:
        assert got[0] == pytest.approx(want[0], rel=1e-9)
        assert got[1] == want[1]


@pytest.mark.parametrize("p, one_sided, z", [
    (0.05, False, 1.959964), (0.001, False, 3.290527), (0.025, True, 1.959964),
    (0, False, 4.891638), (0.0003, False, 3.615300),
    # edges: floored at P_FLOOR, a one-sided p above one half reads 0, p of 1 reads 0
    (1e-12, False, 4.891638), (0, True, 4.753424), (1.0, False, 0.0), (0.9, True, 0.0),
    (1.5, False, 0.0),
])
def test_z_of_p(p, one_sided, z):
    got = M.z_of_p(p, one_sided)
    assert got == near(z)
    assert 0.0 <= got <= M.Z_CAP


def test_z_of_p_of_nothing_is_nothing():
    assert M.z_of_p(None) is None
    assert M.z_of_p(float("nan")) is None


@pytest.mark.parametrize("z, p", [
    (1.959964, 0.025), (0, 0.5), (-1.644854, 0.95),
    (float("inf"), 0.0), (float("-inf"), 1.0), (M.Z_CAP, 2.866516e-07),
])
def test_p_one_sided(z, p):
    assert M.p_one_sided(z) == pytest.approx(p, abs=1e-4, rel=1e-6)


def test_p_one_sided_stays_accurate_in_the_tail_and_refuses_nothing():
    # 1 - Phi(5) = 2.8665157e-7, to six significant figures and not rounded to zero.
    assert M.p_one_sided(5.0) == pytest.approx(2.8665157e-7, rel=1e-6)
    assert M.p_one_sided(None) is None
    assert M.p_one_sided(float("nan")) is None


@pytest.mark.parametrize("diff, var, p", [
    (1, 4, 0.691462), (0, 0, 0.5), (2, 0, 1.0), (-1, 1, 0.158655),
    (-2, 0, 0.0), (0, 1, 0.5),
])
def test_p_above(diff, var, p):
    assert M.p_above(diff, var) == near(p)


def test_p_above_refuses_a_negative_missing_or_infinite_variance():
    assert M.p_above(1, -1) is None
    assert M.p_above(None, 1) is None
    assert M.p_above(1, None) is None
    assert M.p_above(float("nan"), 1) is None
    assert M.p_above(3, float("inf")) is None


@pytest.mark.parametrize("d, v", [(1, 4), (0, 0), (2, 0), (-1, 1), (0.3, 0.01), (7.8, 2.37)])
def test_property_10_the_chance_of_beating_and_losing_adds_to_one(d, v):
    assert M.p_above(d, v) + M.p_above(-d, v) == pytest.approx(1.0, abs=1e-12)


# --- 6.2 standard-error routes ------------------------------------------------------
@pytest.mark.parametrize("args, log, sound", [
    ((-12.44, -13.37, -11.51), False, True),
    ((-0.74, -90.0, -0.57), False, False),            # NCT00106704, a typo
    ((0.59, 0.43, 0.81), True, True),                 # nivolumab, NCT01642004
    ((2.0, 1.0, 1.5), False, False),
    ((None, 1, 2), False, False),
    ((0.97, 0.848, 1.114), True, True),               # VERTIS CV
    # edges
    ((1.0, 1.0, 2.0), False, False),                  # on a bound
    ((1.5, 2.0, 1.0), False, False),                  # bounds the wrong way round
    ((1.0, 0.0, 2.0), True, False),                   # a ratio bound of zero
    ((float("nan"), 0.0, 2.0), False, False),
    ((1.0, float("-inf"), 2.0), False, False),
    ((0.74, 0.0, 1.0), False, True),                  # 0.24 of the width off the middle
    ((0.76, 0.0, 1.0), False, False),                 # 0.26 of it
])
def test_interval_is_sound(args, log, sound):
    assert M.interval_is_sound(*args, log=log) is sound


@pytest.mark.parametrize("args, log, se", [
    ((-13.37, -11.51, 95), False, 0.474499),          # STEP 1, NCT03548935
    ((0.43, 0.81, 96.85), True, 0.147219),            # nivolumab: (ln .81 - ln .43) / 4.3014
    ((0.848, 1.114, 95.6), True, 0.067731),           # VERTIS CV
    ((None, 1, 95), False, None), ((1, 1, 95), False, None),
    ((-0.1, 0.8, 95), True, None), ((1, 2, None), False, None),
    # edges
    ((2, 1, 95), False, None), ((1, 2, 50), False, None), ((1, float("nan"), 95), False, None),
    ((0, 0.8, 95), True, None),
])
def test_se_from_ci(args, log, se):
    got = M.se_from_ci(*args, log=log)
    assert got is None if se is None else got == near(se)


def test_property_1_a_level_written_as_a_fraction_reads_as_a_percentage():
    assert M.se_from_ci(-13.37, -11.51, 0.95) == M.se_from_ci(-13.37, -11.51, 95)
    assert M.se_from_ci(0.43, 0.81, 0.9685, log=True) == pytest.approx(
        M.se_from_ci(0.43, 0.81, 96.85, log=True), rel=1e-12)


@pytest.mark.parametrize("args, want", [
    ((0.66, 194, 0.63, 188, "se"), (0.912414, 0.3969)),
    ((8.1, 97, 6.2, 95, "sd"), (1.039723, 0.404632)),     # semaglutide, NCT05649137
    ((10.1, None, 6.5, 655, "sd"), None),
    # edges
    ((8.1, 0, 6.2, 95, "sd"), None), ((-1.0, 97, 6.2, 95, "sd"), None),
    ((0.0, 97, 0.0, 95, "sd"), None),                     # never a standard error of zero
    ((0.0, None, 0.0, None, "se"), None),
    ((8.1, 97, 6.2, 95, "iqr"), None), ((None, 97, 6.2, 95, "sd"), None),
    ((float("nan"), 97, 6.2, 95, "sd"), None),
    ((0.0, None, 0.5, None, "se"), (0.5, 0.25)),          # one arm's spread still counts
])
def test_se_from_spread(args, want):
    got = M.se_from_spread(*args)
    if want is None:
        assert got is None
    else:
        assert got == (near(want[0]), near(want[1]))


def test_se_from_arm_ci():
    # Each arm's se from its own 95% interval: 2 / 3.919928 and 1 / 3.919928.
    assert M.se_from_arm_ci(1.0, 3.0, 0.0, 1.0, 95) == (near(0.570436), near(0.065079))
    assert M.se_from_arm_ci(1.0, None, 0.0, 1.0, 95) is None
    assert M.se_from_arm_ci(1.0, 3.0, 0.0, 1.0, None) is None
    assert M.se_from_arm_ci(3.0, 1.0, 0.0, 1.0, 95) is None


@pytest.mark.parametrize("args, want", [
    ((267, 404, 107, 403), (0.395382, 0.032228, 0.000484)),   # semaglutide, NCT03552757
    ((39, 270, 0, 46), (0.144444, 0.026201, 0.000229)),       # a zero cell: 0.5 / 47
    ((5, 4, 1, 10), None),
    # edges
    ((0, 50, 0, 50), (0.0, 0.019706, 0.000194)),              # both empty: se above zero
    ((50, 50, 50, 50), (0.0, 0.019706, 0.000194)),            # both full: the same
    ((1, 0, 1, 10), None), ((-1, 10, 1, 10), None), ((None, 10, 1, 10), None),
    ((1, 10, float("nan"), 10), None), ((1, float("inf"), 1, 10), None),
])
def test_two_proportions(args, want):
    got = M.two_proportions(*args)
    if want is None:
        assert got is None
    else:
        assert got == tuple(near(v) for v in want)


@pytest.mark.parametrize("args", [(267, 404, 107, 403), (39, 270, 0, 46), (3, 10, 7, 12)])
def test_property_2_two_proportions_is_antisymmetric(args):
    x, n, rx, rn = args
    forward, back = M.two_proportions(x, n, rx, rn), M.two_proportions(rx, rn, x, n)
    assert back[0] == pytest.approx(-forward[0], abs=1e-12)
    assert back[1] == pytest.approx(forward[1], abs=1e-12)


@pytest.mark.parametrize("args, want", [
    ((3.45, 0.0003), (0.954278, False)),                  # liraglutide, NCT02963935
    ((12.44, 0.0001, "below"), (3.197457, True)),         # STEP 1's "<.0001"
    ((1.0, 0.05, "above"), None),
    ((0, 0.01), None),
    ((2.0, 0.025, "exact", True), (1.020427, False)),
    ((-math.log(0.82), 0.148), (0.137181, False)),        # dasatinib, NCT00767520
    # edges
    ((None, 0.01), None), ((1.0, None), None), ((1.0, 1.0), None),   # z_p of 0
    ((1.0, 0.05, "range"), None), ((float("nan"), 0.05), None),
    ((-3.45, 0.0003), (0.954278, False)),                 # the size of delta, not its sign
])
def test_se_from_p(args, want):
    got = M.se_from_p(*args)
    if want is None:
        assert got is None
    else:
        assert got[0] == near(want[0])
        assert got[1] is want[1]


# --- 6.3 one result per trial -------------------------------------------------------
SURMOUNT_1 = ([13.5, 18.9, 20.1], [0.5357, 0.5612, 0.5612], [623, 629, 625], 635)


@pytest.mark.parametrize("args, want", [
    (SURMOUNT_1, (17.507246, 0.450593)),
    (([4.0, 6.0], [1.0, 2.0]), (5.0, 1.5)),                          # fully correlated
    (([4.0, 6.0], [1.0, 1.0], [100, 100], 100, [0.5, 0.5]), (5.0, 0.866025)),
])
def test_combine_arms(args, want):
    assert M.combine_arms(*args) == (near(want[0]), near(want[1]))


def test_combine_arms_with_a_missing_n_takes_equal_weights_and_the_largest_error():
    # One n missing and no posted control variance: equal weights, se = sum(w_k s_k).
    got = M.combine_arms([4.0, 6.0], [1.0, 2.0], [100, None], 100)
    assert got == (near(5.0), near(1.5))
    # Every n posted but not the control's: the same.
    assert M.combine_arms([4.0, 6.0], [1.0, 2.0], [100, 300], None) == (near(5.5), near(1.75))


def test_combine_arms_refuses_what_it_cannot_read():
    assert M.combine_arms([], []) is None
    assert M.combine_arms([1.0, 2.0], [1.0]) is None
    assert M.combine_arms([1.0, 2.0], [1.0, 0.0]) is None                 # a zero se
    assert M.combine_arms([1.0, float("nan")], [1.0, 1.0]) is None
    assert M.combine_arms([1.0, 2.0], [1.0, 1.0], None, None, [0.5]) is None
    assert M.combine_arms([1.0, 2.0], [1.0, 1.0], None, None, [0.5, -0.1]) is None


def test_property_3_combine_arms_with_one_arm_returns_it_and_counts_the_control_once():
    assert M.combine_arms([3.0], [0.5]) == (3.0, 0.5)
    assert M.combine_arms([3.0], [0.5], [100], 50, [0.1]) == (3.0, 0.5)
    # However many arms share it, the control's own variance is never averaged away.
    for k in (2, 3, 6):
        effect, se = M.combine_arms([5.0] * k, [1.0] * k, [100] * k, 100, [0.4] * k)
        assert se >= math.sqrt(0.4) - 1e-12
    # And the SURMOUNT-1 control, 0.5 of each arm's variance by size, stays in.
    _, se = M.combine_arms(*SURMOUNT_1)
    assert se ** 2 >= min(s ** 2 * n / (n + 635) for s, n in zip(SURMOUNT_1[1], SURMOUNT_1[2]))


@pytest.mark.parametrize("k, e", [
    (1, 0.0), (2, 0.564190), (3, 0.846284), (4, 1.029375), (5, 1.162964), (6, 1.267206),
    (0, 0.0),
])
def test_expected_max_normal(k, e):
    assert M.expected_max_normal(k) == near(e)


def test_expected_max_normal_against_the_published_values():
    # Closed forms (Bose and Gupta 1959): k = 2, 1/sqrt(pi); k = 3, 3 / (2 sqrt(pi));
    # k = 4, (6 / pi^1.5) arctan(sqrt 2); k = 5, 5 / (4 sqrt(pi)) + (15 / (2 pi^1.5)) asin(1/3).
    rp = math.sqrt(math.pi)
    assert M.expected_max_normal(2) == pytest.approx(1 / rp, abs=1e-7)
    assert M.expected_max_normal(3) == pytest.approx(3 / (2 * rp), abs=1e-7)
    assert M.expected_max_normal(4) == pytest.approx(
        6 / math.pi ** 1.5 * math.atan(math.sqrt(2)), abs=1e-7)
    assert M.expected_max_normal(5) == pytest.approx(
        5 / (4 * rp) + 15 / (2 * math.pi ** 1.5) * math.asin(1 / 3), abs=1e-7)
    # Harter's (1961) table of expected normal order statistics: 1.53875 for 10,
    # 1.86748 for 20, 2.50759 for 100.
    assert M.expected_max_normal(10) == near(1.53875)
    assert M.expected_max_normal(20) == near(1.86748)
    assert M.expected_max_normal(100) == near(2.50759)


@pytest.mark.parametrize("args, want", [
    (SURMOUNT_1, {"effect": 19.76284, "se": 0.5612, "index": 2, "arms": 3,
                  "allowance": 0.33716}),
    (([4.0, 6.0], [1.0, 2.0]), {"effect": 4.871621, "se": 2.0, "index": 1, "arms": 2,
                                "allowance": 1.128379}),
    (([4.0, 6.0], [1.0, 1.0], [100, 100], 100, [0.5, 0.5]),
     {"effect": 5.601058, "se": 1.0, "index": 1, "arms": 2, "allowance": 0.398942}),
    (([3.0], [0.5]), {"effect": 3.0, "se": 0.5, "index": 0, "arms": 1, "allowance": 0.0}),
])
def test_top_arm(args, want):
    assert_close(M.top_arm(*args), want)


def test_top_arm_worked_by_hand_on_surmount_1():
    # The 15 mg arm: c = 0.3150 x 625 / 1260 = 0.15625; own = sqrt(0.31494 - 0.15625)
    # = 0.39836; allowance = 0.846284 x 0.39836 = 0.33713; effect 20.1 - 0.337 = 19.763.
    s = 0.5612
    own = math.sqrt(s ** 2 - s ** 2 * 625 / (625 + 635))
    assert M.top_arm(*SURMOUNT_1)["allowance"] == pytest.approx(0.846284 * own, abs=1e-5)


def test_property_4_top_arm():
    one = M.top_arm([3.0], [0.5], [100], 100)
    assert one["effect"] == 3.0 and one["allowance"] == 0.0
    # The allowance grows with the number of arms at equal errors.
    allowances = [M.top_arm([5.0] * k, [1.0] * k)["allowance"] for k in range(1, 8)]
    assert allowances == sorted(allowances)
    assert len(set(round(a, 9) for a in allowances)) == 7
    # The effect never exceeds the best arm's.
    for args in (SURMOUNT_1, ([4.0, 6.0], [1.0, 2.0]), ([1.0, 1.0, 1.0], [0.1, 5.0, 0.1])):
        assert M.top_arm(*args)["effect"] <= max(args[0])


def test_top_arm_edges():
    assert M.top_arm([], []) is None
    assert M.top_arm([2.0, 2.0], [1.0, 1.0])["index"] == 0          # a tie takes the first
    assert M.top_arm([1.0, 2.0], [1.0, 0.0]) is None
    assert M.top_arm([1.0, 2.0], [1.0]) is None
    # A control variance as large as the arm's leaves no error of its own: no allowance.
    assert M.top_arm([1.0, 2.0], [1.0, 1.0], None, None, [1.0, 1.0])["allowance"] == 0.0


def test_combine_repeats():
    # Semaglutide, NCT04998136: in-trial and on-treatment.
    assert M.combine_repeats([12.99, 13.40], [1.1684, 1.1709]) == (near(13.194562),
                                                                   near(1.169647))
    assert M.combine_repeats([3.0], [0.5]) == (3.0, 0.5)
    # The same patients behind every repeat: no precision is bought.
    assert M.combine_repeats([1.0, 2.0, 3.0], [0.5, 0.5, 0.5]) == (near(2.0), near(0.5))
    assert M.combine_repeats([], []) is None
    assert M.combine_repeats([1.0, 2.0], [0.5, 0.0]) is None
    assert M.combine_repeats([1.0, 2.0], [0.5]) is None


# --- 6.4 between trials -------------------------------------------------------------
@pytest.mark.parametrize("q, df, p", [
    (3.841459, 1, 0.05), (16, 2, 0.000335), (0, 3, 1.0), (22, 22, 0.459889),
    (9.95, 1, 0.001608),
    # edges
    (-1, 3, 1.0), (float("inf"), 3, 0.0), (1000, 3, 0.0), (5.991465, 2, 0.05),
    (7.814728, 3, 0.05), (31.410433, 20, 0.05),     # the tabled 5% points on 3 and 20 df
])
def test_chi2_sf(q, df, p):
    assert M.chi2_sf(q, df) == near(p)


@pytest.mark.parametrize("q", [0.01, 0.5, 1.0, 2.7, 6.63, 15.0, 40.0])
def test_chi2_sf_against_its_closed_forms(q):
    # df 1: erfc(sqrt(q/2)); df 2: exp(-q/2); df 3: erfc(sqrt(q/2)) + sqrt(2q/pi) exp(-q/2);
    # df 4: exp(-q/2) (1 + q/2). Odd df exercise the half-integer gamma function.
    assert M.chi2_sf(q, 1) == pytest.approx(math.erfc(math.sqrt(q / 2)), abs=1e-10)
    assert M.chi2_sf(q, 2) == pytest.approx(math.exp(-q / 2), abs=1e-10)
    assert M.chi2_sf(q, 3) == pytest.approx(
        math.erfc(math.sqrt(q / 2)) + math.sqrt(2 * q / math.pi) * math.exp(-q / 2), abs=1e-10)
    assert M.chi2_sf(q, 4) == pytest.approx(math.exp(-q / 2) * (1 + q / 2), abs=1e-10)


def test_property_7_chi2_sf_is_the_usual_bar_and_falls_with_q():
    assert M.chi2_sf(3.841459, 1) == pytest.approx(0.05, abs=1e-6)
    for df in (1, 2, 5, 22, 110):
        ps = [M.chi2_sf(q, df) for q in (0, 0.5, 1, 2, 5, 10, 20, 50, 100, 200)]
        assert all(a >= b for a, b in zip(ps, ps[1:]))
        assert all(0.0 <= p <= 1.0 for p in ps)


def test_chi2_sf_of_nothing_is_nothing():
    assert M.chi2_sf(None, 3) is None
    assert M.chi2_sf(3.0, 0) is None
    assert M.chi2_sf(3.0, None) is None
    assert M.chi2_sf(float("nan"), 3) is None


def test_heterogeneity():
    # w = 1, 1, 0.25; fixed = 16.5 / 2.25 = 7.3333; Q = 7.1111 + 1.7778 + 7.1111 = 16;
    # C = 2.25 - 2.0625 / 2.25 = 1.3333.
    assert_close(M.heterogeneity([10, 6, 2], [1, 1, 2]), {"q": 16.0, "df": 2, "c": 1.333333})
    assert_close(M.heterogeneity([5, 5.2], [0.5, 0.5]), {"q": 0.08, "df": 1, "c": 4.0})
    assert_close(M.heterogeneity([4, 4, 4], [1, 2, 3]), {"q": 0.0, "df": 2})
    assert M.heterogeneity([3.0], [0.5]) is None
    assert M.heterogeneity([], []) is None
    assert M.heterogeneity([1, 2], [1, 0]) is None
    assert M.heterogeneity([1, float("inf")], [1, 1]) is None


def test_common_tau2():
    cells = [([10, 6, 2], [1, 1, 2]), ([5, 5.2], [0.5, 0.5]), ([3.0], [0.5])]
    # (16.08 - 3) / 5.333333 = 2.4525; the one-trial cell adds nothing to Q or C.
    assert_close(M.common_tau2(cells), {"tau2": 2.4525, "q": 16.08, "df": 3, "cells": 2})
    assert M.common_tau2([([3.0], [0.5]), ([4.0], [1.0])]) is None
    assert_close(M.common_tau2([([5, 5.2], [0.5, 0.5])]), {"tau2": 0.0})


def test_property_5_common_tau2_is_unknown_without_a_pair_and_zero_when_cells_agree():
    assert M.common_tau2([]) is None
    assert M.common_tau2([([3.0], [0.5])]) is None
    agree = [([2.0, 2.0, 2.0], [1.0, 0.5, 2.0]), ([7.0, 7.0], [0.3, 0.3])]
    assert M.common_tau2(agree)["tau2"] == 0.0


def test_common_tau2_refuses_a_malformed_cell():
    assert M.common_tau2([([1.0, 2.0], [1.0, 0.0])]) is None
    assert M.common_tau2([([1.0, 2.0], [1.0])]) is None
    assert M.common_tau2([([10, 6, 2], [1, 1, 2]), "not a cell"]) is None
    assert M.common_tau2(None) is None


@pytest.mark.parametrize("effects, ses, tau2, want", [
    ([10, 6, 2], [1, 1, 2], 2.4525,
     {"effect": 6.733608, "se": 1.167004, "k": 3, "q_p": 0.000335, "i2": None,
      "tau2_known": True}),
    ([5, 5.2], [0.5, 0.5], 2.4525, {"effect": 5.1, "se": 1.162433, "k": 2}),
    ([3.0], [0.5], 2.4525, {"effect": 3.0, "se": 1.643928, "q": None, "q_p": None}),
    ([3.0], [0.5], None, {"effect": 3.0, "se": 0.5, "tau2_known": False}),
    ([7.975, 7.236], [0.5153, 1.3597], 7.932, {"effect": 7.63804, "se": 2.111806}),
])
def test_pool_common(effects, ses, tau2, want):
    assert_close(M.pool_common(effects, ses, tau2), want)


def test_pool_common_worked_by_hand_on_tirzepatide():
    # Spec 2.5: five trials, tau2 7.932; w* sum 0.56085; 18.76 (se 1.335), 16.1 to 21.4.
    y = [12.125, 24.5, 19.763, 16.94, 20.579]
    s = [0.6888, 0.8419, 0.5612, 1.4031, 1.301]
    got = M.pool_common(y, s, 7.932)
    assert got["effect"] == pytest.approx(18.76, abs=0.005)
    assert got["se"] == pytest.approx(1.335, abs=0.0005)
    assert (got["lo"], got["hi"]) == (pytest.approx(16.1, abs=0.05), pytest.approx(21.4, abs=0.05))
    assert got["i2"] is not None                     # five trials: I2 is quoted
    # Eloralintide's one trial: sqrt(1.5951^2 + 7.932) = 3.237.
    assert M.pool_common([18.04], [1.5951], 7.932)["se"] == pytest.approx(3.237, abs=0.0005)


def test_property_5_pool_common_at_tau2_zero_is_the_inverse_variance_answer():
    y, s = [10.0, 6.0, 2.0], [1.0, 1.0, 2.0]
    w = [1 / v ** 2 for v in s]
    got = M.pool_common(y, s, 0.0)
    assert got["effect"] == pytest.approx(sum(a * b for a, b in zip(w, y)) / sum(w), abs=1e-12)
    assert got["se"] == pytest.approx(math.sqrt(1 / sum(w)), abs=1e-12)
    # One trial carries the measure's spread: se^2 = s^2 + tau2.
    for s1, t in ((0.5, 2.4525), (1.0, 0.0), (3.0, 10.0)):
        assert M.pool_common([4.0], [s1], t)["se"] ** 2 == pytest.approx(s1 ** 2 + t, abs=1e-12)


def test_pool_common_redraw_coefficients_carry_exactly_the_pooled_variance():
    # A redraw moves the effect by sum(coef_i x draw_i): its variance must be se^2.
    for tau2 in (None, 0.0, 2.4525):
        got = M.pool_common([10, 6, 2, 7, 1], [1, 1, 2, 0.5, 3], tau2)
        assert sum(c ** 2 for c in got["coef"]) == pytest.approx(got["se"] ** 2, rel=1e-12)


def test_pool_common_quotes_i2_only_from_five_trials_and_reads_agreement_as_zero():
    assert M.pool_common([1, 2, 3, 4], [1, 1, 1, 1], 0.0)["i2"] is None
    assert M.pool_common([2, 2, 2, 2, 2], [1, 1, 1, 1, 1], 0.0)["i2"] == 0.0
    # Q = 10 on 4 df: I2 = (10 - 4) / 10 = 0.6.
    assert M.pool_common([1, 2, 3, 4, 5], [1, 1, 1, 1, 1], 0.0)["i2"] == near(0.6)


def test_pool_common_refuses_what_it_cannot_read():
    assert M.pool_common([], [], 1.0) is None
    assert M.pool_common([1.0], [0.0], 1.0) is None            # a zero se
    assert M.pool_common([1.0], [1.0], -0.5) is None           # a negative tau2
    assert M.pool_common([1.0], [1.0], float("nan")) is None
    assert M.pool_common([1.0], [1.0], 1.0, level=100) is None
    assert M.pool_common([1.0, float("nan")], [1.0, 1.0], 1.0) is None


def test_property_6_a_one_trial_drug_is_never_the_more_certain():
    # One measure, every trial's se 1.0: a drug of three trials and a drug of one.
    three, one = ([10.0, 6.0, 2.0], [1.0, 1.0, 1.0]), ([5.0], [1.0])
    fit = M.common_tau2([three, one])
    assert fit["tau2"] > 0            # (32 - 2) / 2 = 15
    p3 = M.pool_common(*three, fit["tau2"])
    p1 = M.pool_common(*one, fit["tau2"])
    assert p1["se"] > p3["se"]
    # Passed to shrink with two more drugs that differ, so the class has a spread of its
    # own, its weight toward the class is the larger.
    sh = M.shrink([p3["effect"], p1["effect"], 20.0, -8.0], [p3["se"], p1["se"], 1.0, 1.0])
    assert sh["tau2"] > 0
    assert sh["weight"][1] > sh["weight"][0]


def test_dersimonian_laird_on_the_bcg_trials_reproduces_the_published_figures():
    # Colditz et al. (1994), the 13 BCG vaccine trials, log risk ratio of tuberculosis
    # (tpos, tneg, cpos, cneg). The DerSimonian-Laird fit published for them (metafor's
    # rma(method="DL") on dat.bcg): tau2 0.3088, Q 152.2330 on 12 df, estimate -0.7141,
    # se 0.1787, interval -1.0644 to -0.3638, I2 92.12%; the fixed-effect answer is
    # -0.4303, se 0.0405. With one cell, common_tau2 is DerSimonian-Laird exactly.
    bcg = [(4, 119, 11, 128), (6, 300, 29, 274), (3, 228, 11, 209), (62, 13536, 248, 12619),
           (33, 5036, 47, 5761), (180, 1361, 372, 1079), (8, 2537, 10, 619),
           (505, 87886, 499, 87892), (29, 7470, 45, 7232), (17, 1699, 65, 1600),
           (186, 50448, 141, 27197), (5, 2493, 3, 2338), (27, 16886, 29, 17825)]
    y = [math.log((a / (a + b)) / (c / (c + d))) for a, b, c, d in bcg]
    s = [math.sqrt(1 / a - 1 / (a + b) + 1 / c - 1 / (c + d)) for a, b, c, d in bcg]
    fit = M.common_tau2([(y, s)])
    assert fit["tau2"] == near(0.3088)
    assert fit["q"] == near(152.2330)
    assert fit["df"] == 12
    re_ = M.pool_common(y, s, fit["tau2"])
    assert re_["effect"] == near(-0.7141)
    assert re_["se"] == near(0.1787)
    assert (re_["lo"], re_["hi"]) == (near(-1.0644), near(-0.3638))
    assert re_["i2"] == near(0.9212)
    fe = M.pool_common(y, s, 0.0)
    assert (fe["effect"], fe["se"]) == (near(-0.4303), near(0.0405))


# --- 6.5 many endpoints -------------------------------------------------------------
PERTUZUMAB = [0.0006, 0.0031, 0.0193, 0.0199, 0.0421, 0.1049, 0.1666]


@pytest.mark.parametrize("ps, want", [
    # 0.0006 x 7, 0.0031 x 7/2, 0.0193 x 7/3 = 0.0450 made monotone to 0.0348, ...
    (PERTUZUMAB, [0.0042, 0.01085, 0.034825, 0.034825, 0.05894, 0.122383, 0.1666]),
    ([0.04], [0.04]),
    ([0.01, 0.04, 0.03], [0.03, 0.04, 0.04]),
    ([], []),
    ([0.2, 0.2, 0.2], [0.2, 0.2, 0.2]),
    ([0.0, 1.0], [0.0, 1.0]),
])
def test_benjamini_hochberg(ps, want):
    assert M.benjamini_hochberg(ps) == [near(v) for v in want]


def test_benjamini_hochberg_one_sided_results_against_the_drug_loosen_nothing():
    favour = M.p_one_sided(2.054)                       # 0.019988
    against = M.benjamini_hochberg([0.9995] * 4 + [favour])
    flat = M.benjamini_hochberg([0.5] * 4 + [favour])
    assert against[-1] == near(0.099939)
    assert flat[-1] == near(0.099939)
    # A posted "<0.05" standing alone, read one-sided at 0.025, is a win at WIN_LEVEL.
    assert M.benjamini_hochberg([0.025])[0] <= 0.025 + 1e-9


def test_benjamini_hochberg_on_the_published_example():
    # Benjamini and Hochberg (1995), section 4: 15 endpoints of a thrombolysis trial. At a
    # false discovery rate of 0.05 the procedure rejects the four smallest (Bonferroni,
    # 0.05 / 15 = 0.0033, rejects three). By hand: the fourth, 0.0095 x 15/4 = 0.035625;
    # the fifth, min over j >= 5 of p_(j) 15 / j = 0.0201 x 3 = 0.0603.
    ps = [0.0001, 0.0004, 0.0019, 0.0095, 0.0201, 0.0278, 0.0298, 0.0344, 0.0459,
          0.3240, 0.4262, 0.5719, 0.6528, 0.7590, 1.000]
    adj = M.benjamini_hochberg(ps)
    assert sum(a <= 0.05 for a in adj) == 4
    assert sum(p <= 0.05 / 15 for p in ps) == 3
    assert adj[3] == near(0.035625)
    assert adj[4] == near(0.0603)


def test_property_8_benjamini_hochberg():
    ps = [0.3, 0.0006, 0.04, 0.2, 0.0199, 0.9, 0.0193, 0.04]
    adj = M.benjamini_hochberg(ps)
    assert all(a >= p - 1e-15 for a, p in zip(adj, ps))          # never below its input
    assert all(a <= 1.0 for a in adj)
    assert len(adj) == len(ps)
    order = sorted(range(len(ps)), key=lambda i: ps[i])        # in input order, monotone in p
    assert all(adj[i] <= adj[j] + 1e-15 for i, j in zip(order, order[1:]))
    # Adding results with p near 1 never lowers another result's adjusted p.
    more = M.benjamini_hochberg(ps + [0.999, 0.9999, 1.0])
    assert all(b >= a - 1e-15 for a, b in zip(adj, more))


def test_benjamini_hochberg_refuses_a_p_that_is_not_one():
    assert M.benjamini_hochberg([0.01, None]) is None
    assert M.benjamini_hochberg([0.01, float("nan")]) is None
    assert M.benjamini_hochberg([0.01, 1.2]) is None
    assert M.benjamini_hochberg([-0.01]) is None
    assert M.benjamini_hochberg(None) is None


# --- 6.6 shrinkage and indirect comparison ------------------------------------------
def test_shrink():
    assert_close(M.shrink([10, 6, 2, 7], [1, 1, 2, 1]), {
        "tau2": 5.666667, "mean": 6.607477, "factor": 1 / 3,
        "weight": [0.05, 0.05, 0.137931, 0.05],
        "shrunk": [9.830374, 6.030374, 2.635514, 6.980374],
        "se": [1.006014, 0.977938, 2.07133, 0.977388]})
    # Drugs that agree: tau2 0, every weight 1/3 (never 1), each se above sqrt(2/3) x 0.5.
    agree = M.shrink([5, 5.2, 4.9, 5.1], [0.5] * 4)
    assert_close(agree, {"tau2": 0.0, "weight": [1 / 3] * 4,
                         "shrunk": [5.016667, 5.15, 4.95, 5.083333]})
    assert all(0.417333 - 1e-4 <= s <= 0.422624 + 1e-4 for s in agree["se"])
    assert all(s > math.sqrt(2 / 3) * 0.5 for s in agree["se"])
    assert M.shrink([1, 2, 3], [1, 1, 1]) is None


def test_shrink_on_the_glp1_agonists_in_diabetes():
    # Spec 2.9: HbA1c against placebo, five GLP-1 agonists; factor 0.5, class mean 0.99,
    # between-drug variance 0.137; semaglutide 1.299 counted at 1.295, lixisenatide 0.534
    # at 0.541. The table's inputs are rounded to three places, hence the tolerances.
    got = M.shrink([1.299, 1.154, 1.024, 0.955, 0.534], [0.061, 0.120, 0.100, 0.142, 0.067])
    assert got["factor"] == 0.5
    assert got["mean"] == pytest.approx(0.99, abs=0.01)
    assert got["tau2"] == pytest.approx(0.137, abs=0.002)
    assert got["weight"][0] == pytest.approx(0.013, abs=0.001)
    assert got["shrunk"][0] == pytest.approx(1.295, abs=0.001)
    assert got["shrunk"][4] == pytest.approx(0.541, abs=0.001)


@pytest.mark.parametrize("effects, ses", [
    ([10, 6, 2, 7], [1, 1, 2, 1]),
    ([5, 5.2, 4.9, 5.1], [0.5] * 4),
    ([1.299, 1.154, 1.024, 0.955, 0.534], [0.061, 0.120, 0.100, 0.142, 0.067]),
    ([3, -1, 8, 0.5, 2, 12, 4, 4], [2, 0.3, 3, 1, 0.8, 4, 1, 1.5]),
])
def test_property_9_shrink_moves_toward_the_mean_never_past_it(effects, ses):
    got = M.shrink(effects, ses)
    j = len(effects)
    mean = got["mean"]
    for y, s, b, post, se in zip(effects, ses, got["weight"], got["shrunk"], got["se"]):
        assert 0.0 <= b <= (j - 3) / (j - 1) + 1e-12
        assert abs(post - mean) <= abs(y - mean) + 1e-12            # toward the mean
        assert (post - mean) * (y - mean) >= -1e-12                   # never past it
        assert se >= math.sqrt(1 - b) * s - 1e-12


def test_shrink_edges():
    assert M.shrink([], []) is None
    assert M.shrink([1, 2, 3, 4], [1, 1, 0, 1]) is None
    assert M.shrink([1, 2, 3, float("nan")], [1, 1, 1, 1]) is None
    assert M.shrink([1, 2, 3, 4], [1, 1, 1]) is None


def test_shrunk_pair_var():
    effects, ses = [10, 6, 2, 7], [1, 1, 2, 1]
    fit = M.shrink(effects, ses)
    # By hand, drugs 0 and 2: w 0.05 and 0.137931, mean 6.607477, var(mean) 1.806854.
    wa, wb, mean, mv = 0.05, 0.1379310, 6.607477, fit["mean_se"] ** 2
    want = ((1 - wa) * 1 + (1 - wb) * 4 + (wa - wb) ** 2 * mv
            + 2.0 * ((wa * (10 - mean)) ** 2 + (wb * (2 - mean)) ** 2))
    assert M.shrunk_pair_var(fit, effects, ses, 0, 2) == near(want)
    assert M.shrunk_pair_var(fit, effects, ses, 2, 0) == near(want)
    assert M.shrunk_pair_var(fit, effects, ses, 1, 1) == 0.0
    # Two drugs of equal weight share the class mean wholly: it drops out.
    assert M.shrunk_pair_var(fit, effects, ses, 0, 1) == near(
        0.95 * 2 + 2.0 * 0.05 ** 2 * ((10 - mean) ** 2 + (6 - mean) ** 2))
    assert M.shrunk_pair_var(fit, effects, ses, 0, 4) is None
    assert M.shrunk_pair_var(None, effects, ses, 0, 1) is None
    assert M.shrunk_pair_var(fit, effects[:3], ses[:3], 0, 1) is None


@pytest.mark.parametrize("args, want", [
    # Tirzepatide against semaglutide, obesity: 7.826, 4.8 to 10.8, a near certainty.
    ((18.763, 1.335, 10.937, 0.764),
     {"diff": 7.826, "se": 1.538155, "lo": 4.811271, "hi": 10.840729, "p_better": 1.0}),
    # Tirzepatide against eloralintide: Φ(0.723 / 3.5015) = 0.5818.
    ((18.763, 1.335, 18.040, 3.237),
     {"diff": 0.723, "se": 3.501485, "lo": -6.139784, "hi": 7.585784, "p_better": 0.581794}),
    # Two log odds ratios against a common control, -0.5 (se 0.2) and -0.2 (se 0.15):
    # -0.3, se sqrt(0.04 + 0.0225) = 0.25, 95% interval -0.79 to 0.19.
    ((-0.5, 0.2, -0.2, 0.15), {"diff": -0.3, "se": 0.25, "lo": -0.789991, "hi": 0.189991,
                               "p_better": 0.115070}),
    ((1.0, 0.0, 1.0, 0.0), {"diff": 0.0, "se": 0.0, "p_better": 0.5}),
])
def test_bucher(args, want):
    assert_close(M.bucher(*args), want)


def test_bucher_is_antisymmetric_and_refuses_what_it_cannot_read():
    ab, ba = M.bucher(18.763, 1.335, 18.040, 3.237), M.bucher(18.040, 3.237, 18.763, 1.335)
    assert ba["diff"] == pytest.approx(-ab["diff"], abs=1e-12)
    assert ab["p_better"] + ba["p_better"] == pytest.approx(1.0, abs=1e-12)
    assert M.bucher(None, 1, 2, 1) is None
    assert M.bucher(1, -1, 2, 1) is None
    assert M.bucher(1, 1, float("nan"), 1) is None
    assert M.bucher(1, 1, 2, 1, level=40) is None


# --- 6.7 safety ---------------------------------------------------------------------
DARATUMUMAB = [(186, 346, 117, 354), (289, 364, 262, 365), (205, 283, 148, 281),
               (142, 197, 131, 195), (29, 96, 22, 98), (56, 193, 38, 196)]


@pytest.mark.parametrize("strata, want", [
    ([(10, 100, 5, 100), (30, 200, 10, 100)],
     {"rd": 0.05, "se": 0.02747, "drug_rate": 0.128571, "control_rate": 0.078571, "q": 0.0,
      "top_share": 0.571429, "k": 2, "df": 1, "n_drug": 300, "n_control": 200}),
    ([(10, 100, 5, 100), (60, 200, 10, 100)], {"rd": 0.135714, "se": 0.029821, "q": 7.462537}),
    (DARATUMUMAB, {"rd": 0.129269, "se": 0.016715, "drug_rate": 0.612432,
                   "control_rate": 0.483163, "q": 14.501981, "df": 5}),
    ([(0, 50, 0, 50)], {"rd": 0.0, "se": 0.019706, "q": None, "df": 0, "top_share": 1.0}),
    ([(39, 270, 0, 46)], {"rd": 0.144444, "se": 0.026201}),
])
def test_mantel_haenszel_rd(strata, want):
    assert_close(M.mantel_haenszel_rd(strata), want)


@pytest.mark.parametrize("strata", [
    [(10, 100, 5, 100), (30, 200, 10, 100)], DARATUMUMAB, [(39, 270, 0, 46)],
    [(2941, 8803, 3204, 8801), (40, 400, 20, 200)],
])
def test_mantel_haenszel_rates_differ_by_exactly_the_pooled_difference(strata):
    got = M.mantel_haenszel_rd(strata)
    assert got["drug_rate"] - got["control_rate"] == pytest.approx(got["rd"], abs=1e-12)
    # A redraw moves rd by sum(coef_i x draw_i): its variance must be se^2.
    assert sum(c ** 2 for c in got["coef"]) == pytest.approx(got["se"] ** 2, rel=1e-12)
    assert got["lo"] == pytest.approx(got["rd"] - M.Z95 * got["se"], abs=1e-12)


def test_mantel_haenszel_variance_is_greenland_and_robins():
    # Greenland and Robins (1985), written as they wrote it, with a, b the drug arm's
    # events and non-events, c, d the control's, N the stratum:
    # var = sum((a b n0^3 + c d n1^3) / (n1 n0 N^2)) / (sum(n1 n0 / N))^2.
    num = den = 0.0
    for a, n1, c, n0 in DARATUMUMAB:
        b, d, big = n1 - a, n0 - c, n1 + n0
        num += (a * b * n0 ** 3 + c * d * n1 ** 3) / (n1 * n0 * big ** 2)
        den += n1 * n0 / big
    assert M.mantel_haenszel_rd(DARATUMUMAB)["se"] == pytest.approx(math.sqrt(num / den ** 2),
                                                                    rel=1e-12)


def test_mantel_haenszel_one_stratum_is_the_plain_difference_and_equal_strata_average():
    one = M.mantel_haenszel_rd([(267, 404, 107, 403)])
    rd, se, _ = M.two_proportions(267, 404, 107, 403)
    assert (one["rd"], one["se"]) == (pytest.approx(rd, abs=1e-12), pytest.approx(se, abs=1e-12))
    equal = M.mantel_haenszel_rd([(10, 100, 5, 100), (20, 100, 5, 100), (3, 100, 6, 100)])
    assert equal["rd"] == pytest.approx((0.05 + 0.15 - 0.03) / 3, abs=1e-12)


def test_mantel_haenszel_leaves_out_a_stratum_it_cannot_read_and_fills_in_nothing():
    good = [(10, 100, 5, 100)]
    bad = [(5, 0, 1, 10), (11, 10, 1, 10), (-1, 10, 1, 10), (None, 10, 1, 10),
           (1, 10, float("nan"), 10), (1, 10, 1), "abcd", None]
    got = M.mantel_haenszel_rd(good + bad)
    assert_close(got, {"rd": 0.05, "k": 1, "n_drug": 100})
    assert M.mantel_haenszel_rd(bad) is None
    assert M.mantel_haenszel_rd([]) is None
    assert M.mantel_haenszel_rd(None) is None
    assert M.mantel_haenszel_rd(good, level=100) is None


def test_dispersion():
    second = M.mantel_haenszel_rd([(10, 100, 5, 100), (60, 200, 10, 100)])
    dara = M.mantel_haenszel_rd(DARATUMUMAB)
    first = M.mantel_haenszel_rd([(10, 100, 5, 100), (30, 200, 10, 100)])
    single = M.mantel_haenszel_rd([(39, 270, 0, 46)])
    # (7.462537 + 14.501981) / (1 + 5) = 3.660753.
    assert M.dispersion([second, dara]) == near(3.660753)
    assert M.dispersion([single]) is None
    assert M.dispersion([first]) == 1.0          # agreement never narrows an interval
    assert M.dispersion([second, dara, single, None]) == near(3.660753)
    assert M.dispersion([]) is None
    assert M.dispersion(None) is None


def test_dispersion_on_the_myeloma_serious_events():
    # Spec 2.10: daratumumab Q 14.5 on 5 df with carfilzomib's 7.9 on 3 gives phi = 22.4 / 8
    # = 2.80, and daratumumab's se 1.67 points widens to 2.80.
    phi = M.dispersion([{"q": 14.501981, "df": 5}, {"q": 7.9, "df": 3}])
    assert phi == pytest.approx(2.80, abs=0.005)
    se = M.mantel_haenszel_rd(DARATUMUMAB)["se"]
    assert 100 * se * math.sqrt(phi) == pytest.approx(2.80, abs=0.01)


# --- 6.8 simulation -----------------------------------------------------------------
def test_normal_draws_are_fixed_by_their_seed():
    a = M.normal_draws(2000, 7, 20260930)
    b = M.normal_draws(2000, 7, 20260930)
    assert a.shape == (2000, 7)
    assert np.array_equal(a, b)
    direct = np.random.Generator(np.random.PCG64(20260930)).standard_normal((2000, 7))
    assert np.array_equal(a, direct)
    assert not np.array_equal(a, M.normal_draws(2000, 7, 20260931))
    assert abs(float(a.mean())) < 0.05 and abs(float(a.std()) - 1.0) < 0.05


def test_normal_draws_edges():
    assert M.normal_draws(2000, 0, 1).shape == (2000, 0)       # no safety column to draw
    assert M.normal_draws(0, 3, 1).shape == (0, 3)
    assert M.normal_draws(-1, 3, 1) is None
    assert M.normal_draws(10, 2.5, 1) is None
    assert M.normal_draws(10, 3, None) is None


def test_interval():
    assert M.interval(list(range(101))) == (near(2.5), near(97.5))
    assert M.interval([1.0]) == (1.0, 1.0)
    assert M.interval([3, 1, 2], level=100) == (1.0, 3.0)
    assert M.interval([3, 1, 2], level=0) == (2.0, 2.0)


def test_interval_matches_numpy_percentile():
    xs = list(M.normal_draws(1, 997, 7)[0])
    lo, hi = M.interval(xs, 95.0)
    want = np.percentile(xs, [2.5, 97.5])
    assert (lo, hi) == (pytest.approx(want[0], abs=1e-12), pytest.approx(want[1], abs=1e-12))


def test_interval_of_nothing_is_nothing():
    assert M.interval([]) is None
    assert M.interval(None) is None
    assert M.interval([1.0, float("nan")]) is None
    assert M.interval([1.0, 2.0], level=101) is None


def test_mantel_haenszel_names_the_strata_it_read():
    fit = M.mantel_haenszel_rd([(5, 50, 3, 50), (450, 400, 10, 400), (2, 40, 1, 40)])
    assert fit["kept"] == [0, 2] and fit["k"] == 2 and len(fit["coef"]) == 2
    empty = M.mantel_haenszel_rd([(0, 50, 2, 45)])
    assert empty["drug_rate"] == 0.0            # never a rounding error below zero
