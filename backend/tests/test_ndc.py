"""NDC normalisation: the three printed layouts pad to 5-4-2, and nothing is guessed."""

from __future__ import annotations

import ndc


def test_a_package_code_pads_its_short_segment():
    assert ndc.to_ndc11("71610-662-09") == "71610066209"      # 5-3-2
    assert ndc.to_ndc11("0003-0894-21") == "00003089421"      # 4-4-2
    assert ndc.to_ndc11("50090-1436-0") == "50090143600"      # 5-4-1
    assert ndc.to_ndc11("00003-0894-21") == "00003089421"     # already 5-4-2
    assert ndc.to_ndc11("00003089421") == "00003089421"       # already 11 digits


def test_a_product_code_pads_to_the_form_negotiated_prices_uses():
    assert ndc.product_ndc9("0003-3764") == "00003-3764"
    assert ndc.product_ndc9("71610-662") == "71610-0662"
    assert ndc.product_ndc9("00173-0869") == "00173-0869"


def test_ndc9_and_labeler_of_an_11_digit_code():
    assert ndc.ndc9("00003089321") == "00003-0893"
    assert ndc.ndc9("71610-662-09") == "71610-0662"
    assert ndc.labeler("55154061208") == "55154"


def test_malformed_input_is_none_never_a_guess():
    for bad in (None, "", "0003089421", "0003-0894", "00003-0894-21-1", "abcde-0894-21",
                "000030894211", "123-4567-89", "00003--21"):
        assert ndc.to_ndc11(bad) is None, bad
        assert ndc.ndc9(bad) is None, bad
    assert ndc.product_ndc9("00003-0894-21") is None
    assert ndc.product_ndc9("3-3764") is None
    assert ndc.product_ndc9(None) is None
