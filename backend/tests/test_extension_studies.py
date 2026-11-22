"""Which studies are extensions or long-term safety studies, on titles and outcomes
written in the registry's own phrasings. None of these rows is a real study: each is
modelled on a wording the book carries, with the drug's name taken out."""

import extension_studies as E
import pipeline

AE = "Number of Participants With Treatment-Emergent Adverse Events (TEAEs)"
SRI4 = "Percentage of Participants Who Achieved an SRI-4 Response at Week 52"
WEIGHT = "Relative change in body weight"


def test_a_standard_extension_title_is_one_whatever_it_measures():
    """The title alone decides these. An extension that measures efficacy from the
    parent trial's baseline is still made of the parent trial's participants."""
    titles = [
        "A Long-Term Extension Study to Learn More About the Safety of XYZ-1234",
        "Open-label Extension Study of XYZ-1234 in Adults With IgA Nephropathy",
        "Extension Trial to Evaluate the Long-term Efficacy, Safety, and Tolerability"
        " of XYZ-1234",
        "A Rollover Study for Participants Previously Enrolled in an XYZ-1234 Study",
        "XYZ-1234 Long Term Follow Up (LTFU) Study",
    ]
    for title in titles:
        assert E.cannot_carry(title, AE), title
        assert E.cannot_carry(title, WEIGHT), title
        assert E.cannot_carry(title, None), title


def test_a_long_term_title_needs_a_safety_outcome_beside_it():
    """ "Long-term" is in the title of a safety study and of a study of lasting efficacy
    alike, so the primary outcome on file is what tells them apart."""
    safety = "A Study to Learn More About the Long-Term Safety of XYZ-1234 Injections"
    lasting = "A Research Study to Look Into the Long-term Effect on Weight Loss of XYZ-1234"
    assert E.cannot_carry(safety, AE)
    assert E.cannot_carry("Long-term Safety and Efficacy Study of XYZ-1234 in CIDP",
                          "Number of participants having any AEs, SAEs and AESIs")
    assert E.cannot_carry("Long-Term Study to Assess the Safety and Tolerability of"
                          " XYZ-1234", "Long-term safety and tolerability")
    assert not E.cannot_carry(lasting, WEIGHT)
    assert not E.cannot_carry(safety, SRI4), "the outcome on file is efficacy"
    assert not E.cannot_carry(safety, None), "no outcome on file, so nothing confirms it"


def test_a_continuation_study_is_named_for_itself():
    """The disease can be long-term without the study being so."""
    assert E.cannot_carry("A Continuation Study of XYZ-1234 in Adults With COPD", AE)
    assert not E.cannot_carry(
        "A Study of XYZ-1234 in Adults With Long-Term Breathing Difficulty", SRI4)


def test_a_safety_outcome_alone_is_not_enough():
    """Only the first primary outcome is stored, and a seamless study or one with a
    safety run-in lists its safety part first. Those are the studies that carry a
    programme, so the outcome never sets one aside without the title."""
    for outcome in ("Safety Run-In: Number of Participants With Adverse Events (AE)s",
                    "Part A: Safety and Tolerability as Assessed by Number of"
                    " Participants With Adverse Events (AEs)", AE):
        assert not E.cannot_carry(
            "A Study of XYZ-1234 Plus Pomalidomide Versus Standard Therapies", outcome)
        assert not E.cannot_carry("A Study to Evaluate Safety and Efficacy of XYZ-1234",
                                  outcome)


def test_a_study_with_a_controlled_part_of_its_own_is_not_an_extension():
    """A title that names the extension period after the controlled one matches the
    standard phrasing and is a study of efficacy. The extension study of a parent trial
    that happens to say "followed by" stays an extension."""
    own = ["A 52-Week Study Evaluating the Efficacy and Safety of XYZ-1234 in"
           " Participants With VEXAS Followed by Open-Label Extension (OLE) Period",
           "24 Weeks Double-blind Randomized Placebo-controlled Trial of XYZ-1234"
           " Followed by Optional 3 Years Open-label Extension",
           "Phase 2 and 3 Placebo Controlled & Long-term Extension Study of XYZ-1234"]
    for title in own:
        assert E.is_follow_up(title) and E.has_own_part(title), title
        assert not E.cannot_carry(title, SRI4), title
    parent = ("A Randomized, Double-blind 2-arm, Followed by an Open-label 1-arm,"
              " PARENT Extension Study to Assess the Long-term Safety of XYZ-1234")
    assert not E.has_own_part(parent) and E.cannot_carry(parent, AE)


def test_a_plain_or_missing_title_is_counted():
    for title in ("A Study of XYZ-1234 in Adults With Systemic Lupus Erythematosus",
                  "XYZ-1234 Versus Placebo in Refractory Chronic Cough - China Extension",
                  "", None):
        assert not E.cannot_carry(title, SRI4), title
        assert not E.cannot_carry(title, None), title


def test_the_pipeline_flag_is_the_same_title_rule():
    """One rule for a follow-up title, read by the Pipeline tab's flag and by the hold."""
    assert pipeline.is_follow_up is E.is_follow_up
