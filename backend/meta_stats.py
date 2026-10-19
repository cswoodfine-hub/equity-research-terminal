"""Meta-analysis arithmetic for the clinical scorecard, as pure functions.

The contract is docs/design/clinical-scorecard-statistics.md, section 6. Nothing here reads
the database or knows what a drug or a trial is: every function takes numbers and hands back
numbers, so each can be checked by hand, and the hand-worked cases of the spec are its tests
(backend/tests/test_meta_stats.py). ``landscape_score`` decides what the numbers are.

Conventions:

- An *effect* is a difference from the comparator (or the log of a ratio), signed by the
  caller so that more is better; a *se* is its standard error.
- None means "cannot be derived from what was given". A function returns None where an input
  it needs is missing, malformed or not finite; it never fills one in, and it never returns a
  standard error of zero from counts or spreads that could not support one.
- Standard library only, except ``normal_draws``, which uses numpy. No scipy.

What each group is for (spec section in brackets):

- levels and p-values (6.1): ``z_of_level``, ``parse_p``, ``z_of_p``, ``p_one_sided``,
  ``p_above``;
- the standard-error routes of one posted result (2.3, 6.2): ``interval_is_sound``,
  ``se_from_ci``, ``se_from_spread``, ``se_from_arm_ci``, ``two_proportions``, ``se_from_p``;
- one result per trial (2.4, 6.3): ``combine_arms`` (the test), ``top_arm`` (the size),
  ``expected_max_normal``, ``combine_repeats``;
- between trials (2.5, 6.4): ``chi2_sf``, ``heterogeneity``, ``common_tau2``,
  ``pool_common``;
- many endpoints (2.7, 6.5): ``benjamini_hochberg``;
- shrinkage and indirect comparison (2.8, 2.9, 6.6): ``shrink``, ``shrunk_pair_var``,
  ``bucher``;
- safety (2.10, 6.7): ``mantel_haenszel_rd``, ``dispersion``;
- simulation (2.11, 6.8): ``normal_draws``, ``interval``.
"""

from __future__ import annotations

import math
import re
from functools import lru_cache
from statistics import NormalDist

_N = NormalDist()
_SQRT2 = math.sqrt(2.0)

# The normal deviate of a two-sided 95% level, 1.959964 to six places. Held at full
# precision so that it is exactly ``z_of_level(95)``: an interval built from either agrees.
Z95 = _N.inv_cdf(0.975)
Z_CAP = 5.0                      # a p of zero says no more than "beyond the table"
P_FLOOR = 1e-6                   # a posted p is read at no less than this
OFF_CENTRE = 0.25                # an estimate this share of the width off the middle is unsound

_P_TEXT = re.compile(r"-?\d*\.?\d+(?:e[-+]?\d+)?")


# --- input checks -------------------------------------------------------------------
def _num(x) -> float | None:
    """``x`` as a finite float, or None where it is missing, not a number or not finite."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _series(effects, ses) -> tuple[list, list] | None:
    """Two equal-length lists of finite floats with every se above zero, or None where any
    entry fails. A standard error of zero would claim certainty no trial has."""
    if effects is None or ses is None:
        return None
    try:
        ys, ss = list(effects), list(ses)
    except TypeError:
        return None
    if len(ys) != len(ss):
        return None
    ys = [_num(y) for y in ys]
    ss = [_num(s) for s in ss]
    if any(y is None for y in ys) or any(s is None or s <= 0.0 for s in ss):
        return None
    return ys, ss


def _sizes(ns, k) -> list | None:
    """Arm sizes as floats where every one of the k is a positive finite number, else None
    (the arms are then weighted equally, as the spec says)."""
    if ns is None:
        return None
    ns = list(ns)
    if len(ns) != k:
        return None
    out = [_num(n) for n in ns]
    if any(n is None or n <= 0.0 for n in out):
        return None
    return out


# --- levels and p-values (6.1) ------------------------------------------------------
def z_of_level(ci_pct) -> float | None:
    """The normal deviate of a two-sided interval level: 95 -> 1.959964, 90 -> 1.644854.
    A level posted as a fraction (between 0.5 and 1, as 0.95) is read as a percentage.
    None for a missing level or one outside (50, 100)."""
    level = _num(ci_pct)
    if level is None:
        return None
    if 0.5 < level < 1.0:
        level *= 100.0
    if not 50.0 < level < 100.0:
        return None
    return _N.inv_cdf(0.5 + level / 200.0)


def parse_p(text) -> tuple[float, str] | None:
    """(p, kind) of a posted p-value: kind is 'exact', 'below' ("<0.001", "≤0.05") or
    'above' (">0.05"). None where the text holds no number between 0 and 1."""
    if text is None or isinstance(text, bool):
        return None
    s = str(text).strip().lower()
    m = _P_TEXT.search(s)
    if not m:
        return None
    try:
        p = float(m.group(0))
    except ValueError:
        return None
    if not (math.isfinite(p) and 0.0 <= p <= 1.0):
        return None
    if "<" in s or "≤" in s:
        kind = "below"
    elif ">" in s or "≥" in s:
        kind = "above"
    else:
        kind = "exact"
    return p, kind


def z_of_p(p, one_sided: bool = False) -> float | None:
    """The unsigned normal deviate of a p-value, p floored at P_FLOOR and the deviate
    capped at Z_CAP. Two-sided unless ``one_sided``. A one-sided p above 0.5 reads 0.
    None for a missing or non-finite p."""
    p = _num(p)
    if p is None:
        return None
    p = min(max(p, P_FLOOR), 1.0)
    q = 1.0 - p if one_sided else 1.0 - p / 2.0
    q = min(max(q, 0.5), 1.0 - 1e-16)
    return min(_N.inv_cdf(q), Z_CAP)


def p_one_sided(z) -> float | None:
    """The one-sided p-value of a signed deviate, 1 - Φ(z): the chance of a result this far
    in the drug's favour when it does nothing. A result against the drug has p above 0.5.
    None for a missing z or NaN."""
    if z is None or isinstance(z, bool):
        return None
    try:
        z = float(z)
    except (TypeError, ValueError):
        return None
    if math.isnan(z):
        return None
    return 0.5 * math.erfc(z / _SQRT2)


def p_above(diff, var) -> float | None:
    """P(a normal quantity with this mean and variance is above zero), Φ(diff / sqrt(var)).
    With no variance: 0.5 on an exact tie, else 1 or 0. None for a missing value or a
    negative variance."""
    d, v = _num(diff), _num(var)
    if d is None or v is None or v < 0.0:
        return None
    if v > 0.0:
        return _N.cdf(d / math.sqrt(v))
    return 0.5 if abs(d) < 1e-12 else float(d > 0.0)


# --- standard-error routes (6.2) ----------------------------------------------------
def interval_is_sound(estimate, lower, upper, log: bool = False) -> bool:
    """An interval that brackets its estimate (lower < estimate < upper) with the estimate
    within OFF_CENTRE of the width of the midpoint, on the log scale for a ratio.
    NCT00106704 posted -0.74 (-90.0 to -0.57), a typo; an interval like it is not used."""
    e, lo, hi = _num(estimate), _num(lower), _num(upper)
    if e is None or lo is None or hi is None:
        return False
    if log:
        if e <= 0.0 or lo <= 0.0 or hi <= 0.0:
            return False
        e, lo, hi = math.log(e), math.log(lo), math.log(hi)
    width = hi - lo
    if width <= 0.0 or not lo < e < hi:
        return False
    return abs(e - (lo + hi) / 2.0) <= OFF_CENTRE * width


def se_from_ci(lower, upper, ci_pct, log: bool = False) -> float | None:
    """The standard error behind a two-sided interval: its width over 2 z(level), on the
    log scale for a ratio. None without both bounds, a posted level, a positive width, or
    (``log``) positive bounds."""
    z = z_of_level(ci_pct)
    lo, hi = _num(lower), _num(upper)
    if lo is None or hi is None or z is None:
        return None
    if log:
        if lo <= 0.0 or hi <= 0.0:
            return None
        lo, hi = math.log(lo), math.log(hi)
    if hi <= lo:
        return None
    return (hi - lo) / (2.0 * z)


def se_from_spread(spread, n, ref_spread, ref_n, kind: str) -> tuple[float, float] | None:
    """The standard error of a difference of two means from each arm's posted spread, and
    the control arm's variance: (se, control variance).

    ``kind`` 'sd' (a standard deviation, which needs each arm's n): sqrt(sd1^2/n1 +
    sd0^2/n0). ``kind`` 'se' (a standard error per arm): sqrt(se1^2 + se0^2). None for any
    other kind, a missing or negative spread, a missing n where one is needed, or two
    spreads of zero (a standard error of zero is never claimed)."""
    s1, s0 = _num(spread), _num(ref_spread)
    if s1 is None or s0 is None or s1 < 0.0 or s0 < 0.0:
        return None
    if kind == "sd":
        n1, n0 = _num(n), _num(ref_n)
        if n1 is None or n0 is None or n1 <= 0.0 or n0 <= 0.0:
            return None
        v1, v0 = s1 ** 2 / n1, s0 ** 2 / n0
    elif kind == "se":
        v1, v0 = s1 ** 2, s0 ** 2
    else:
        return None
    if v1 + v0 <= 0.0:
        return None
    return math.sqrt(v1 + v0), v0


def se_from_arm_ci(lower, upper, ref_lower, ref_upper, ci_pct) -> tuple[float, float] | None:
    """As ``se_from_spread`` where each arm posted an interval around its own mean: each
    arm's se from its interval, then (sqrt(se1^2 + se0^2), se0^2)."""
    s1 = se_from_ci(lower, upper, ci_pct)
    s0 = se_from_ci(ref_lower, ref_upper, ci_pct)
    if s1 is None or s0 is None:
        return None
    return math.sqrt(s1 ** 2 + s0 ** 2), s0 ** 2


def _arm_var(x: float, n: float) -> float:
    """p (1 - p) / n of one arm's share, with a share of 0 or 1 read as (x + 0.5) / (n + 1)
    so an empty (or full) arm never claims a variance of zero."""
    p = x / n
    if p <= 0.0 or p >= 1.0:
        p = (x + 0.5) / (n + 1.0)
    return p * (1.0 - p) / n


def _count_pair(x, n, ref_x, ref_n) -> tuple | None:
    """Two arms' counts where each is a count within its positive n, else None. A whole
    number comes back as an int, so a total of people prints as one."""
    vals = [_num(v) for v in (x, n, ref_x, ref_n)]
    if any(v is None for v in vals):
        return None
    x1, n1, x0, n0 = vals
    if n1 <= 0.0 or n0 <= 0.0 or not (0.0 <= x1 <= n1 and 0.0 <= x0 <= n0):
        return None
    return tuple(int(v) if v.is_integer() else v for v in vals)


def two_proportions(x, n, ref_x, ref_n) -> tuple[float, float, float] | None:
    """(risk difference, se, control variance) of two shares from their counts, as
    fractions: x/n - ref_x/ref_n. A share of 0 or 1 takes its variance from
    (x + 0.5) / (n + 1), so a zero cell never claims a standard error of zero; the
    difference itself is left as posted. None for a missing count, an n that is not
    positive, or a count outside 0 to n."""
    got = _count_pair(x, n, ref_x, ref_n)
    if got is None:
        return None
    x1, n1, x0, n0 = got
    v1, v0 = _arm_var(x1, n1), _arm_var(x0, n0)
    return x1 / n1 - x0 / n0, math.sqrt(v1 + v0), v0


def se_from_p(delta, p, kind: str = "exact", one_sided: bool = False) -> tuple[float, bool] | None:
    """The standard error that makes a Wald test of ``delta`` reproduce the posted p-value,
    |delta| / z_p, and whether it rests on a bound: (se, is_bound). A bound below
    ("<0.001") gives the largest se the bound allows. None for a zero or missing delta, a
    missing p, a bound above (">0.05") or any other kind, or z_p under 0.01."""
    d = _num(delta)
    if d is None or d == 0.0 or kind not in ("exact", "below"):
        return None
    z = z_of_p(p, one_sided)
    if z is None or z < 0.01:
        return None
    return abs(d) / z, kind == "below"


# --- one result per trial (6.3) -----------------------------------------------------
def _control_shares(ses, ns, ref_n, control_vars) -> list:
    """The control arm's share of each arm's variance, or None where it is not known: the
    posted control variance where the route gave one, else s_k^2 n_k / (n_k + n_0) where
    both sizes are known. Never more than the arm's whole variance."""
    out = []
    for i, s in enumerate(ses):
        cv = control_vars[i] if control_vars is not None else None
        if cv is None and ns is not None and ref_n is not None:
            cv = s ** 2 * ns[i] / (ns[i] + ref_n)
        out.append(None if cv is None else min(cv, s ** 2))
    return out


def _arms(effects, ses, ns, ref_n, control_vars):
    """The checked inputs of ``combine_arms`` and ``top_arm``, or None where malformed:
    (effects, ses, sizes or None, control size or None, control variances or None)."""
    got = _series(effects, ses)
    if got is None or not got[0]:
        return None
    ys, ss = got
    k = len(ys)
    sizes = _sizes(ns, k)
    n0 = _num(ref_n)
    if n0 is not None and n0 <= 0.0:
        n0 = None
    cvs = None
    if control_vars is not None:
        cvs = list(control_vars)
        if len(cvs) != k:
            return None
        for i, cv in enumerate(cvs):
            if cv is None:
                continue
            v = _num(cv)
            if v is None or v < 0.0:
                return None
            cvs[i] = v
    return ys, ss, sizes, n0, cvs


def combine_arms(effects, ses, ns=None, ref_n=None, control_vars=None) -> tuple[float, float] | None:
    """Several dose arms of one trial against one shared control, as one result: the test
    of "any dose works", which feeds strength and wins (spec 2.4).

    w_k    = n_k / sum(n), equal weights where an n is missing
    effect = sum(w_k e_k)
    var    = sum(w_k^2 (s_k^2 - c_k)) + sum(w_k c_k)

    c_k is the control arm's share of arm k's variance (see ``_control_shares``), so the
    shared control is counted once. Where it is not known for some arm, the arms are taken
    as fully correlated, se = sum(w_k s_k), the largest it can be. One arm returns itself.
    None for no arms or malformed input."""
    got = _arms(effects, ses, ns, ref_n, control_vars)
    if got is None:
        return None
    ys, ss, sizes, n0, cvs = got
    k = len(ys)
    if k == 1:
        return ys[0], ss[0]
    w = [n / sum(sizes) for n in sizes] if sizes else [1.0 / k] * k
    effect = sum(wi * e for wi, e in zip(w, ys))
    shares = _control_shares(ss, sizes, n0, cvs)
    if any(c is None for c in shares):
        return effect, sum(wi * s for wi, s in zip(w, ss))
    common = sum(wi * c for wi, c in zip(w, shares))
    var = sum(wi ** 2 * (s ** 2 - c) for wi, s, c in zip(w, ss, shares)) + common
    return effect, math.sqrt(var)


@lru_cache(maxsize=64)
def _expected_max(k: int) -> float:
    steps, lo, hi = 2000, -9.0, 9.0
    h = (hi - lo) / steps

    def f(x):
        return x * k * _N.pdf(x) * _N.cdf(x) ** (k - 1)
    total = f(lo) + f(hi)
    for i in range(1, steps):
        total += (4 if i % 2 else 2) * f(lo + i * h)
    return total * h / 3.0


def expected_max_normal(k) -> float:
    """The expected largest of k independent standard normal draws, by Simpson's rule on
    x k φ(x) Φ(x)^(k-1) over [-9, 9]: 0 for one (or none), 0.564190 for two, 0.846284,
    1.029375, 1.162964, 1.267206 for three to six."""
    kk = _num(k)
    if kk is None or kk < 2.0:
        return 0.0
    return _expected_max(int(kk))


def top_arm(effects, ses, ns=None, ref_n=None, control_vars=None) -> dict | None:
    """The size of effect of a multi-dose trial: its most effective arm, less what picking
    the best of k arms adds by chance (spec 2.4).

    allowance = E[max of k standard normals] x sqrt(s_b^2 - c_b)

    sqrt(s_b^2 - c_b) is the part of the top arm's error that is its own: the shared
    control moves every arm alike and cannot favour one. Where the control's share is not
    known the whole s_b is used, the larger allowance. The se is the top arm's own.

    Returns {effect, se, index, arms, allowance}; one arm returns itself with allowance 0.
    None for no arms or malformed input."""
    got = _arms(effects, ses, ns, ref_n, control_vars)
    if got is None:
        return None
    ys, ss, sizes, n0, cvs = got
    k = len(ys)
    b = max(range(k), key=lambda i: ys[i])
    if k == 1:
        return {"effect": ys[0], "se": ss[0], "index": 0, "arms": 1, "allowance": 0.0}
    share = _control_shares(ss, sizes, n0, cvs)[b]
    own = math.sqrt(max(ss[b] ** 2 - (share or 0.0), 0.0))
    allowance = expected_max_normal(k) * own
    return {"effect": ys[b] - allowance, "se": ss[b], "index": b, "arms": k,
            "allowance": allowance}


def combine_repeats(effects, ses) -> tuple[float, float] | None:
    """One measure posted more than once by one trial (two analysis sets, two time points):
    the precision-weighted mean, with se the same weighted mean of the standard errors. The
    same patients are behind every repeat, so the repeat buys no precision. None for no
    repeats or malformed input."""
    got = _series(effects, ses)
    if got is None or not got[0]:
        return None
    ys, ss = got
    w = [1.0 / s ** 2 for s in ss]
    total = sum(w)
    return (sum(wi * e for wi, e in zip(w, ys)) / total,
            sum(wi * s for wi, s in zip(w, ss)) / total)


# --- between trials (6.4) -----------------------------------------------------------
def chi2_sf(q, df) -> float | None:
    """P(a chi-square on df degrees of freedom exceeds q): the regularised upper incomplete
    gamma Q(df/2, q/2), by its series below a + 1 and its continued fraction above. 1 for
    q at or below zero, 0 for an infinite q. None for a missing q or df not above zero."""
    d = _num(df)
    if d is None or d <= 0.0 or q is None or isinstance(q, bool):
        return None
    try:
        qq = float(q)
    except (TypeError, ValueError):
        return None
    if math.isnan(qq):
        return None
    if qq <= 0.0:
        return 1.0
    if math.isinf(qq):
        return 0.0
    a, x = d / 2.0, qq / 2.0
    lg = math.lgamma(a)
    if x < a + 1.0:
        term = total = 1.0 / a
        n = a
        for _ in range(500):
            n += 1.0
            term *= x / n
            total += term
            if abs(term) < abs(total) * 1e-14:
                break
        return min(1.0, max(0.0, 1.0 - total * math.exp(-x + a * math.log(x) - lg)))
    tiny = 1e-300
    b = x + 1.0 - a
    c = 1.0 / tiny
    dd = 1.0 / b
    h = dd
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2.0
        dd = an * dd + b
        dd = tiny if abs(dd) < tiny else dd
        c = b + an / c
        c = tiny if abs(c) < tiny else c
        dd = 1.0 / dd
        delta = dd * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return min(1.0, max(0.0, math.exp(-x + a * math.log(x) - lg) * h))


def heterogeneity(effects, ses) -> dict | None:
    """Cochran's Q of k trials around their inverse-variance mean, its degrees of freedom
    and the C that scales it into a variance:

    w_i = 1 / s_i^2   Q = sum(w_i (y_i - fixed)^2)   C = sum(w_i) - sum(w_i^2) / sum(w_i)

    Returns {q, df, c}. None under two trials or for malformed input."""
    got = _series(effects, ses)
    if got is None or len(got[0]) < 2:
        return None
    ys, ss = got
    w = [1.0 / s ** 2 for s in ss]
    sw = sum(w)
    fixed = sum(wi * e for wi, e in zip(w, ys)) / sw
    q = sum(wi * (e - fixed) ** 2 for wi, e in zip(w, ys))
    return {"q": q, "df": len(ys) - 1, "c": sw - sum(wi ** 2 for wi in w) / sw}


def common_tau2(cells) -> dict | None:
    """One between-trial variance for a measure (spec 2.5), from every cell (one drug on
    one control) with two or more trials on it:

    tau2 = max(0, (sum Q_j - sum(k_j - 1)) / sum C_j)

    With one cell this is the DerSimonian-Laird estimate. ``cells`` is a list of
    (effects, ses). None where no cell has two trials, since the spread between trials is
    then not known and is not guessed, and None where any cell is malformed.

    Returns {tau2, q, df, cells}: df is sum(k_j - 1), the degrees of freedom tau2 rests on,
    and cells the number of cells that fed it."""
    if cells is None:
        return None
    q = df = c = 0.0
    used = 0
    for cell in cells:
        try:
            effects, ses = cell
        except (TypeError, ValueError):
            return None
        got = _series(effects, ses)
        if got is None:
            return None
        h = heterogeneity(*got)
        if not h:
            continue
        q, df, c, used = q + h["q"], df + h["df"], c + h["c"], used + 1
    if not used or c <= 0.0:
        return None
    return {"tau2": max(0.0, (q - df) / c), "q": q, "df": int(df), "cells": used}


def pool_common(effects, ses, tau2, level: float = 95.0) -> dict | None:
    """One averaged effect from a drug's k trials on a measure, each weighted by
    1 / (s_i^2 + tau2) with the measure's own between-trial variance (spec 2.5):

    w*_i = 1 / (s_i^2 + tau2)   effect = sum(w*_i y_i) / sum(w*_i)   se = sqrt(1 / sum(w*_i))

    A single trial carries tau2 too: se^2 = s^2 + tau2. With ``tau2`` None (not estimable
    on the measure) the trials' own errors stand alone and ``tau2_known`` is False.

    Returns {effect, se, lo, hi, k, tau2_known, q, q_p, i2, coef}: q and q_p are the drug's
    own Cochran's Q and its chi-square p (from two trials); i2 = max(0, (Q - (k-1)) / Q)
    only from five trials, since with fewer it has no usable precision; coef_i =
    sqrt(w*_i) / sum(w*), what one standard normal redraw of trial i moves the effect by.
    None for no trials, malformed input, a negative or non-finite tau2, or a level outside
    (50, 100)."""
    got = _series(effects, ses)
    if got is None or not got[0]:
        return None
    ys, ss = got
    if tau2 is None:
        t = 0.0
    else:
        t = _num(tau2)
        if t is None or t < 0.0:
            return None
    z = z_of_level(level)
    if z is None:
        return None
    k = len(ys)
    w = [1.0 / (s ** 2 + t) for s in ss]
    sw = sum(w)
    effect = sum(wi * e for wi, e in zip(w, ys)) / sw
    se = math.sqrt(1.0 / sw)
    h = heterogeneity(ys, ss)
    q = h["q"] if h else None
    if k >= 5:
        i2 = max(0.0, (q - (k - 1)) / q) if q and q > 0.0 else 0.0
    else:
        i2 = None
    return {"effect": effect, "se": se, "lo": effect - z * se, "hi": effect + z * se, "k": k,
            "tau2_known": tau2 is not None,
            "q": q, "q_p": chi2_sf(q, k - 1) if h else None, "i2": i2,
            "coef": [math.sqrt(wi) / sw for wi in w]}


# --- many endpoints (6.5) -----------------------------------------------------------
def benjamini_hochberg(pvalues) -> list[float] | None:
    """Benjamini-Hochberg adjusted p-values, in the order given: sort ascending, p_(i) m / i,
    made monotone from the largest down (adj_(i) = min over j >= i), capped at 1. An empty
    list gives an empty list. None where any p is missing, not finite or outside 0 to 1."""
    if pvalues is None:
        return None
    ps = [_num(p) for p in pvalues]
    if any(p is None or not 0.0 <= p <= 1.0 for p in ps):
        return None
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    out = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, ps[i] * m / rank)
        out[i] = running
    return out


# --- shrinkage and indirect comparison (6.6) ----------------------------------------
def shrink(effects, ses) -> dict | None:
    """Empirical Bayes toward the mean of J drugs of one mechanism class, with Morris's
    small-sample factor for a prior fitted on few drugs (spec 2.9):

    tau2, mean, var(mean)  between the J drugs, by the method of moments on the s_j
    factor   = (J - 3) / (J - 1)
    weight_j = factor x s_j^2 / (s_j^2 + tau2)
    shrunk_j = weight_j mean + (1 - weight_j) y_j
    se_j^2   = (1 - weight_j) s_j^2 + weight_j^2 var(mean)
               + (2 / (J - 3)) weight_j^2 (y_j - mean)^2

    The factor keeps a drug from being moved all the way to the mean on a between-drug
    variance estimated as zero from a handful of drugs: with four drugs no result moves
    more than a third of the way. The last term is the uncertainty in the weight itself.

    Returns {mean, mean_se, tau2, factor, shrunk, se, weight, mean_weight}; mean_weight are
    the normalised weights the mean gives each drug. None under four drugs or for
    malformed input."""
    got = _series(effects, ses)
    if got is None or len(got[0]) < 4:
        return None
    ys, ss = got
    j = len(ys)
    h = heterogeneity(ys, ss)
    tau2 = max(0.0, (h["q"] - h["df"]) / h["c"]) if h["c"] > 0.0 else 0.0
    w = [1.0 / (s ** 2 + tau2) for s in ss]
    sw = sum(w)
    mean = sum(wi * e for wi, e in zip(w, ys)) / sw
    mean_var = 1.0 / sw
    factor = (j - 3.0) / (j - 1.0)
    weight = [factor * s ** 2 / (s ** 2 + tau2) for s in ss]
    shrunk = [b * mean + (1.0 - b) * y for b, y in zip(weight, ys)]
    se = [math.sqrt((1.0 - b) * s ** 2 + b ** 2 * mean_var
                    + (2.0 / (j - 3.0)) * b ** 2 * (y - mean) ** 2)
          for b, s, y in zip(weight, ss, ys)]
    return {"mean": mean, "mean_se": math.sqrt(mean_var), "tau2": tau2, "factor": factor,
            "shrunk": shrunk, "se": se, "weight": weight, "mean_weight": [wi / sw for wi in w]}


def shrunk_pair_var(fit: dict, effects, ses, a: int, b: int) -> float | None:
    """The variance of the difference between two drugs shrunk toward one class mean by
    ``fit`` (the return of ``shrink`` on ``effects`` and ``ses``), spec 2.9:

    var = (1 - w_a) s_a^2 + (1 - w_b) s_b^2 + (w_a - w_b)^2 var(mean)
          + (2 / (J - 3)) ((w_a (y_a - mean))^2 + (w_b (y_b - mean))^2)

    The class mean is common to both, so only the part they weigh differently is uncertain
    between them. A drug against itself has variance 0. Any pair not shrunk toward one
    class adds the two variances, which is the caller's to do. None for malformed input."""
    got = _series(effects, ses)
    if got is None or not fit:
        return None
    ys, ss = got
    j = len(ys)
    weights = fit.get("weight")
    mean, mean_se = _num(fit.get("mean")), _num(fit.get("mean_se"))
    if (j < 4 or weights is None or len(weights) != j or mean is None or mean_se is None
            or not (isinstance(a, int) and isinstance(b, int)) or not (0 <= a < j and 0 <= b < j)):
        return None
    if a == b:
        return 0.0
    wa, wb = _num(weights[a]), _num(weights[b])
    if wa is None or wb is None:
        return None
    return ((1.0 - wa) * ss[a] ** 2 + (1.0 - wb) * ss[b] ** 2
            + (wa - wb) ** 2 * mean_se ** 2
            + (2.0 / (j - 3.0)) * ((wa * (ys[a] - mean)) ** 2 + (wb * (ys[b] - mean)) ** 2))


def bucher(effect_a, se_a, effect_b, se_b, level: float = 95.0) -> dict | None:
    """A against B through the control both were tested against (Bucher's adjusted indirect
    comparison): the difference of their effects, with the two variances added, its
    interval at ``level``, and ``p_better``, the chance the difference is above zero
    (effects signed so that more is better). None for a missing value, a negative se or a
    level outside (50, 100)."""
    ea, sa, eb, sb = _num(effect_a), _num(se_a), _num(effect_b), _num(se_b)
    z = z_of_level(level)
    if ea is None or sa is None or eb is None or sb is None or z is None:
        return None
    if sa < 0.0 or sb < 0.0:
        return None
    diff = ea - eb
    se = math.sqrt(sa ** 2 + sb ** 2)
    return {"diff": diff, "se": se, "lo": diff - z * se, "hi": diff + z * se,
            "p_better": p_above(diff, se ** 2)}


# --- safety (6.7) -------------------------------------------------------------------
def mantel_haenszel_rd(strata, level: float = 95.0) -> dict | None:
    """The Mantel-Haenszel risk difference across trials (spec 2.10). Each stratum is
    (x1, n1, x0, n0): people with the event and people at risk on the drug and on its
    control.

    w_i = n1 n0 / (n1 + n0)
    rd  = sum(w_i (x1/n1 - x0/n0)) / sum(w_i)
    var = sum(w_i^2 (p1 (1 - p1) / n1 + p0 (1 - p0) / n0)) / sum(w_i)^2

    The variance is Greenland and Robins' (1985) for this estimate. The estimate needs no
    correction for a zero cell; for the variance only, an arm with no events (or only
    events) takes its p from (x + 0.5) / (n + 1), so an empty arm never claims to be
    certain.

    The two rates are on the same weights as the difference, so drug_rate - control_rate
    is rd up to rounding: control_rate = sum(w_i x0/n0) / sum(w_i), drug_rate likewise,
    each held inside 0 to 1.

    A stratum that cannot be read (not four numbers, an n not above zero, a count outside
    0 to n, a value not finite) is left out; nothing is filled in for it.

    Returns {rd, se, lo, hi, k, drug_rate, control_rate, n_drug, n_control, q, df,
    top_share, coef, kept}: q is the disagreement of the stratum differences around rd on
    their own variances, sum((d_i - rd)^2 / v_i), None for one stratum; df = k - 1;
    top_share the largest stratum's share of the weight; coef_i = w_i sqrt(v_i) / sum(w),
    what one standard normal redraw of stratum i moves rd by; kept the positions in
    ``strata`` of the strata read, in order, so a caller can name each one. ``se`` is not yet widened for
    disagreement between trials: see ``dispersion``. None where no stratum can be read or
    the level is outside (50, 100)."""
    z = z_of_level(level)
    if strata is None or z is None:
        return None
    rows, kept = [], []
    for i, s in enumerate(strata):
        try:
            x1, n1, x0, n0 = s
        except (TypeError, ValueError):
            continue
        got = _count_pair(x1, n1, x0, n0)
        if got is not None:
            rows.append(got)
            kept.append(i)
    if not rows:
        return None
    weights = [n1 * n0 / (n1 + n0) for _, n1, _, n0 in rows]
    total = sum(weights)
    diffs = [x1 / n1 - x0 / n0 for x1, n1, x0, n0 in rows]
    variances = [_arm_var(x1, n1) + _arm_var(x0, n0) for x1, n1, x0, n0 in rows]
    rd = sum(w * d for w, d in zip(weights, diffs)) / total
    var = sum(w ** 2 * v for w, v in zip(weights, variances)) / total ** 2
    control = sum(w * x0 / n0 for w, (_, _, x0, n0) in zip(weights, rows)) / total
    # Each rate is its own weighted mean, held inside 0 to 1, so an arm with no events
    # reads 0 and never a rounding error below it.
    drug = min(1.0, max(0.0, sum(w * x1 / n1 for w, (x1, n1, _, _) in zip(weights, rows))
                        / total))
    control = min(1.0, max(0.0, control))
    se = math.sqrt(var)
    q = sum((d - rd) ** 2 / v for d, v in zip(diffs, variances))
    return {"rd": rd, "se": se, "lo": rd - z * se, "hi": rd + z * se, "k": len(rows),
            "drug_rate": drug, "control_rate": control,
            "n_drug": sum(r[1] for r in rows), "n_control": sum(r[3] for r in rows),
            "q": q if len(rows) > 1 else None, "df": len(rows) - 1,
            "top_share": max(weights) / total,
            "coef": [w * math.sqrt(v) / total for w, v in zip(weights, variances)],
            "kept": kept}


def dispersion(fits) -> float | None:
    """How much more the trials of each drug differ on a safety count than their own
    sampling error explains, as one factor for an indication, part and kind of control:
    phi = max(1, sum Q_j / sum df_j) over every fit (a ``mantel_haenszel_rd`` return) with
    two or more strata. A Mantel-Haenszel se is multiplied by sqrt(phi), a one-trial drug's
    included. None where no drug has two strata: the spread between trials is then not
    known."""
    if fits is None:
        return None
    q = df = 0.0
    for f in fits:
        if not f:
            continue
        fq, fdf = _num(f.get("q")), _num(f.get("df"))
        if fq is None or fdf is None or fdf <= 0.0:
            continue
        q, df = q + fq, df + fdf
    if df <= 0.0:
        return None
    return max(1.0, q / df)


# --- simulation (6.8) ---------------------------------------------------------------
def normal_draws(n: int, size: int, seed: int):
    """An ``n`` by ``size`` array of standard normal draws from
    numpy.random.Generator(PCG64(seed)), so every run of the scorecard draws the same
    numbers. ``size`` may be 0 (no column to draw). None for a negative or non-integer
    shape or seed."""
    import numpy as np

    for v in (n, size, seed):
        if isinstance(v, bool) or not isinstance(v, (int, np.integer)) or v < 0:
            return None
    return np.random.Generator(np.random.PCG64(int(seed))).standard_normal((int(n), int(size)))


def interval(values, level: float = 95.0) -> tuple[float, float] | None:
    """The central ``level`` percent of a list of simulated values, by linear
    interpolation between order statistics (numpy's default percentile). None for no
    values, a value that is not finite, or a level outside 0 to 100."""
    lvl = _num(level)
    if values is None or lvl is None or not 0.0 <= lvl <= 100.0:
        return None
    xs = [_num(v) for v in values]
    if not xs or any(v is None for v in xs):
        return None
    xs.sort()
    n = len(xs)
    tail = (1.0 - lvl / 100.0) / 2.0

    def at(q):
        pos = q * (n - 1)
        lo = int(math.floor(pos))
        hi = min(lo + 1, n - 1)
        return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)
    return at(tail), at(1.0 - tail)
