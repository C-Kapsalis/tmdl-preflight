# The imposition pattern: check → fix → re-check

Most linters stop at detection: they tell you what is wrong and leave the
repair to you. tmdl-preflight treats a class of defects differently. For
violations that are *mechanical* — where the correct repair is fully
determined by the failure itself — the repair is part of the run, not a
separate chore. We call this the **imposition pattern**: the tool imposes
the invariant rather than merely observing its absence.

## The loop

`tmdl-preflight fix` executes three phases, strictly in order:

1. **Check.** Every selected rule runs read-only and reports violations.
2. **Fix.** Each *fixable* rule that reported violations applies its
   repair. Fixers edit the files on disk, surgically; they never mutate the
   in-memory model.
3. **Re-check.** The parse cache is dropped and every rule runs again —
   against what is actually on disk now.

The run is clean only if the **re-check** is clean. This is the load-bearing
detail: a fixer never gets to vouch for itself. If a repair was incomplete,
wrong, or impossible (a bookmark value with no known integer meaning, say),
the violation is still on the final report and the exit code is still
nonzero. Auto-repair can therefore never *mask* a defect — the worst it can
do is fail to remove one, exactly as if it did not exist.

## Why fold the fix into the run at all?

Because for mechanical defects, "report and wait for a human" is strictly
worse:

- **The human adds no information.** When a duplicate `lineageTag` must
  become a fresh UUID, there is no judgement call. Routing it through a
  person adds latency and a chance of a hand-edit typo, nothing else.
- **Defect classes that recur deserve automation.** These defects are
  produced by tooling and merges, not by misunderstanding — so they recur
  forever. A fix documented in a wiki gets executed inconsistently; a fix
  encoded in the tool gets executed identically every time.
- **The check and the fix stay in sync.** When detection logic and repair
  logic live together and the re-check arbitrates between them, they cannot
  silently drift apart.

## What earns a fixer — the safety contract

Only four of the seventeen rules ship a fixer, and that is deliberate. A
repair qualifies only if it satisfies all of:

1. **The failure mode fully determines the repair.** No intent needs to be
   inferred. A duplicate tag needs a fresh unique value; an orphan comma
   needs deletion; a `"2"` needs to become `2`.
2. **It never overwrites human-authored semantics.** Fixers touch identity
   metadata, separators and JSON types — never a DAX expression, a name, or
   a relationship.
3. **It is idempotent.** Running `fix` twice produces the same tree as
   running it once.
4. **It is minimal.** Line-level, targeted edits, so the resulting diff is
   reviewable at a glance.

Counter-examples make the boundary clear. An unbalanced DAX expression
(D001) has infinitely many "balanced" completions — only the author knows
which one is meant, so there is no fixer. A dangling bookmark reference
(B002) could mean *restore the visual*, *retarget the bookmark*, or *delete
the bookmark* — three different intents, so there is no fixer.

## Check-only mode is a first-class citizen

`tmdl-preflight check` never writes, unconditionally. This split matters in
practice: pipelines and audits run `check` (a mutating gate in CI is a
recipe for confusing states), while developers run `fix` locally and commit
the diff like any other change. The same discipline is available in pytest
via the fixture's `autofix` parameter and the `TMDL_PREFLIGHT_AUTOFIX`
environment variable.

## See also

- [The layered test model](layered-testing.md) — where imposition sits in a
  broader verification strategy.
- [How to run only the auto-fixable rules](../how-to/run-only-autofixable-rules.md)
