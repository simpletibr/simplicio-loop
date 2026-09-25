# Pending SkillOpt Review Candidates

This directory contains SkillOpt-generated `SKILL.md` artifacts prepared for
human review evidence on #32/#33.

These files are not trusted project skills yet. They intentionally live under
`bench/` instead of the active `.skills/` directory so they cannot be loaded as
default local skills before review.

Use `bench/results_skillopt_review_packet.json` as the review form. A reviewer
must fill `reviewer`, boolean `approved`, `reviewed_at`, and `notes` for each
accepted row before the live gate can count the evidence.
