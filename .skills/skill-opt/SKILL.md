---
name: skill-opt
description: Generates new .skills/<slug>/SKILL.md entries on demand from a one-line description, guarded by a review gate so unreviewed skills do not become defaults.
trigger: User invokes `simplicio-py skill new "<description>"`, OR the scratch executor encounters a plan task that requires a capability not yet covered by any installed skill.
auto_generated:
  by: human
  date: 2026-05-29
  source_goal: bootstrap skill-opt itself
  planner_model: n/a
  review_required: false
---

# skill-opt

A meta-skill: generates other skills. Lives at `.skills/skill-opt/` and is
invoked via the `simplicio-py skill new` CLI command (`simplicio.scratch.skill_opt`).

## When to use

- The user explicitly asks: `simplicio-py skill new "what the skill does"`
- The scratch executor processes a plan task that references a capability
  with no matching skill in `.skills/` — it calls `generate_skill_doc()` +
  `install_skill()` inline before continuing the plan

Do NOT use to update an existing skill — for that, edit the SKILL.md directly
or open a PR. Skill-opt always CREATES, never amends.

## Steps

1. Call `simplicio.providers.planner_complete(prompt)` with a strict template
   that demands the exact frontmatter shape (see `SKILL_GEN_SYSTEM` in
   `simplicio/scratch/skill_opt.py`).
2. Validate the response:
   - YAML frontmatter present
   - `name` matches `^[a-z][a-z0-9-]{1,40}$`
   - `review_required: true` is present (refuses any output without it — this
     is the gate that protects `.skills/` from contamination)
   - Slug does not collide with an existing skill
3. Write the document to `.skills/<slug>/SKILL.md`
4. Print the path to stderr + a one-line reminder that human review is
   required before relying on the new skill

## Auto-generated guarantees

- Every skill produced via this flow has `review_required: true` in its
  frontmatter — non-negotiable; `install_skill()` rejects otherwise
- The frontmatter also carries `auto_generated.by: skill-opt`, the date,
  the source goal verbatim, and the planner model id, so audit trail
  survives even if the SKILL.md is later moved or renamed

## DoD

- [ ] Generated SKILL.md has all required frontmatter fields
- [ ] `review_required: true` present
- [ ] Slug is unique within `.skills/`
- [ ] File written under `.skills/<slug>/SKILL.md`
- [ ] Stderr line tells the user to review

## Anti-patterns

- **Generating a skill without `review_required: true`.** Hard fail at write
  time; never allow it to slip in.
- **Generating a skill that duplicates an existing one.** Refuse and exit;
  the user should refine the description.
- **Auto-merging the new skill into `.skills/README.md`.** The README is the
  user-facing index of *trusted* skills; auto-generated entries stay out
  until a human reviews and amends.
- **Running on a model that isn't `SIMPLICIO_PLANNER`.** Doer-grade models
  often produce malformed YAML or skip the review gate. Planner provider
  is the contract.
