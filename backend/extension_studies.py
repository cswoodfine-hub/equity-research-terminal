"""Which registered studies are extensions, rollovers or long-term safety studies.

The registry files these under a development phase: litifilimab's long-term extension in
cutaneous lupus (NCT06044337) and its long-term safety study in systemic lupus
(NCT05352919) are both Phase 3. Neither asks whether the drug works. An extension takes
the people who finished a parent study and keeps treating them; a long-term safety study
counts adverse events over years. If the study that does ask the question misses, these
cannot answer it in its place, so the forecast must not count them among the Phase 3s
still asking (pos_granular's mixed rule and its held note).

What tells them apart, and what does not. The registry has no field for "this is an
extension", so every field on file was tried against the book on 2026-11-22: 624 open
Phase 3 and Phase 2/3 studies on unmarketed assets.

- ``design`` (allocation, masking, purpose) does not say it. Litifilimab's long-term
  safety study is randomised and quadruple masked, the same string as the two studies it
  extends; a single-arm open-label design is also what a registration study in a rare
  disease or in cell therapy looks like (VX-880's NCT04786262).
- ``overall_status`` is the nearest thing to a field: "Enrolling by invitation" means
  the people come from somewhere the sponsor already knows, usually a parent study. It
  is true of 9 of the 43 studies set aside here and of 2 more that nothing else marks,
  and it stops being true the day enrolment closes, when the study turns "Active not
  recruiting" with nothing else about it changed. A status that expires cannot be the
  rule.
- ``primary_outcome`` is a field and it nearly says it: an extension's first primary
  outcome is almost always a count of adverse events. On its own it is wrong 38 times
  in the 624, because only the first primary outcome is stored and a seamless Phase
  1/2/3 or a study with a safety run-in lists its safety part first (etentamig's
  NCT07728188, "Safety Run-In: Number of Participants With Adverse Events").
- ``title`` is what says it. Sponsors name these studies in a handful of standard
  phrasings, and that is a title match, not a registry field: it can be wrong where a
  sponsor words a title unusually.

So the rule is the title, with the primary outcome as the check where the title alone is
too loose:

1. A title in the registry's standard phrasing for an extension, a rollover or a
   long-term follow-up (``is_follow_up``) is one, whatever it measures. Title only. 26 of
   the 624. Five of them do not count adverse events first (MariTide's two extension
   trials measure weight from the parent trial's baseline) and are extensions all the
   same: their participants are the parent study's.
2. A title that says only "long-term" or "continuation study" is one where the primary
   outcome on file is safety (``is_long_term_safety``). Title and field together. 17 more
   of the 624. The outcome is what keeps CagriSema's two studies of long-term weight loss
   (NCT07011667, NCT06780449), both randomised with weight as the outcome, out of it.

One wording is taken back out. A study that runs a controlled part of its own and then
an extension names both in its title ("... Followed by Open-Label Extension (OLE)
Period", arumakimig's NCT07748624; remibrutinib's NCT05677451 the same). The standard
phrasing matches it and it is not an extension: its first part asks the question. None
of the 43 is worded that way, and ``has_own_part`` keeps the next one counted.

A study neither catches stays in, including one that probably is an extension but is not
named as one (bomedemstat's NCT06351631, "A Study to Evaluate Safety and Efficacy",
single arm, adverse events first). Leaving a doubtful study in errs toward the behaviour
the model had before, which is the safe direction for a rule that removes value.

Pure and import-free, so pos_granular can read it without the rNPV path taking on the
pipeline module, which is where ``is_follow_up`` lived until it had a second reader.
"""

from __future__ import annotations

import re

# Long-term follow-up, extension and rollover studies carry a development phase in the
# registry (Casgevy's follow-up is filed as Phase 3), so they sit inside the pipeline
# counts though they are lifecycle work on a product already in or past development, not
# new development. They are recognised by the standard titling the registry uses. This is
# a title heuristic, not a registry field: it errs toward the unmistakable phrasings.
_FOLLOW_UP_RE = re.compile(
    r"long[- ]term follow[- ]?up"
    r"|long[- ]term extension"
    r"|open[- ]label extension"
    r"|\bextension (study|trial|phase|of)\b"
    r"|\broll[- ]?over\b"
    r"|follow[- ]up (study|trial|of|gene|safety)"
    r"|safety follow[- ]up",
    re.I,
)

# The looser phrasings, which a study of efficacy can carry too ("the long-term effect on
# weight loss"), so they count only beside a safety outcome. "Continuation study" is
# named for itself: tilrekimig's NCT07839884 would otherwise match on "long-term
# breathing difficulty", which is the disease and not the study.
_LONG_TERM_RE = re.compile(r"\blong[- ]?term\b|\bcontinuation (study|trial)\b", re.I)

# A first primary outcome that counts harm rather than benefit: adverse events under
# their usual abbreviations, or safety and tolerability named outright.
_SAFETY_OUTCOME_RE = re.compile(
    r"adverse event|\bTEAEs?\b|\bSAEs?\b|\bAEs?\b|\bsafety\b|tolerab", re.I)


# An extension that is a later part of the study the title names, after a controlled part
# of its own: "followed by" an extension that is not itself called a study or a trial
# (the NEPTUNUS Extension Study is "randomized, double-blind 2-arm, followed by an
# open-label 1-arm", and is an extension throughout), or "placebo controlled and
# long-term extension" in one title.
_OWN_PART_RE = re.compile(
    r"\bfollowed by\b[^.;]*?\bextension\b(?! (?:study|trial)\b)"
    r"|\bcontrolled (?:&|and) [\w -]{0,30}\bextension\b",
    re.I,
)


def is_follow_up(title: str | None) -> bool:
    """True when a trial title marks it as a long-term follow-up, extension or rollover
    study. Pure, so the same rule serves the per-trial flag and the pipeline counts."""
    return bool(title and _FOLLOW_UP_RE.search(title))


def is_long_term_safety(title: str | None, primary_outcome: str | None) -> bool:
    """True when the title says long-term or continuation and the primary outcome on
    file is safety. Both are needed: the title alone takes in long-term efficacy studies,
    and the outcome alone takes in every study that lists a safety run-in first."""
    return bool(title and primary_outcome and _LONG_TERM_RE.search(title)
                and _SAFETY_OUTCOME_RE.search(primary_outcome))


def has_own_part(title: str | None) -> bool:
    """True when the title names an extension as what follows a controlled part of the
    same study, so the study is not an extension itself."""
    return bool(title and _OWN_PART_RE.search(title))


def cannot_carry(title: str | None, primary_outcome: str | None = None) -> bool:
    """True for a study that cannot answer for the programme if the study asking the
    efficacy question misses: an extension, a rollover, a long-term follow-up, or a
    long-term safety study. False where neither the title nor the outcome says so, and
    where both are missing, so a study the registry says little about is still counted.
    False too where the extension is only the later part of a study with a controlled
    part of its own (has_own_part)."""
    if has_own_part(title):
        return False
    return is_follow_up(title) or is_long_term_safety(title, primary_outcome)
