"""The rules that read a press headline for an outcome.

The rule under test is abstention. The feed that carries "meets primary endpoint" also
carries "Begins Treating Patients" and "to Present New Data", both filed as data
readouts, so a classifier confident enough to act on it would be wrong about the model's
biggest numbers. What a headline is tied to, and what is recorded from it, is
``landed_readouts`` and is tested in ``test_landed_readouts.py``.
"""

import auto_resolve as A


# --- what the words say --------------------------------------------------------------

def test_a_headline_that_announces_a_future_event_is_not_a_result():
    for line in ("Biogen to Present New Data Across Nephrology Portfolio",
                 "Revolution Medicines Begins Treating Patients in Phase 3 RASolve 308",
                 "Wave Life Sciences Third Quarter Results Scheduled for October 27",
                 "Acme doses first patient in the Phase 3 study"):
        assert A.classify(line) == (None, None), line


def test_a_miss_is_read_before_a_hit():
    """'did not meet its primary endpoint' contains the word meet, and the cheerful
    reading of that sentence is the expensive one."""
    outcome, words = A.classify("Acme announces TRIAL did not meet its primary endpoint")
    assert outcome == "missed" and "did not meet" in words.lower()


def test_a_hit_is_read_where_the_words_are_the_industry_s():
    assert A.classify("Lilly's Omvoh meets primary endpoint of clinical remission")[0] == "met"
    assert A.classify("Acme Announces Positive Topline Results from Study 3")[0] == "met"
    assert A.classify("Hibsago approved in the US for chronic hepatitis B")[0] == "met"


def test_a_discontinuation_is_a_miss():
    assert A.classify("Acme discontinues development of foobarmab")[0] == "missed"


def test_a_good_result_in_words_no_rule_can_defend_is_not_classified():
    """Significantly reduced proteinuria is a real result. The sentence the model would
    have to write to act on it is one no rule can defend, so it abstains."""
    assert A.classify(
        "Roche presents interim data showing sefaxersen significantly reduced "
        "proteinuria in people with IgA nephropathy") == (None, None)
    assert A.classify("Phase 3 RAINIER Results Supporting Best-in-Class Potential "
                      "Published") == (None, None)


def test_an_empty_headline_classifies_as_nothing():
    assert A.classify(None) == (None, None) and A.classify("   ") == (None, None)


# --- what reaches a gate -------------------------------------------------------------
