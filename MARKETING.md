# Launch material — tmdl-preflight

Copy for the open-source launch of **tmdl-preflight**, an MIT-licensed
preflight linter and auto-fixer for Power BI semantic models saved in TMDL
format (PBIP folders). Everything here is truthful to the tool — real
commands, the shipped bike-shop example, no invented benchmarks.

Repo: https://github.com/c-kapsalis/tmdl-preflight

---

## Positioning tagline

**tmdl-preflight — catch the defects that stop Power BI from opening your
project, before you commit. Then let it fix them.**

Alternates:
- *Preflight checks and auto-fixes for Power BI TMDL/PBIP models.*
- *Your PBIP model is plain text now. Test it like code.*

---

## Problem → solution hook

**The problem.** For most of Power BI's life the semantic model was a binary
`.pbix` blob — un-diffable, un-reviewable, un-testable. PBIP and TMDL changed
that: the model is now a folder of plain-text files. But nothing shipped the
testing layer. So a duplicate `lineageTag` left behind by a copy-pasted table
file sails through Power BI Desktop *and* every code review — then kills the
deployment days later with *"an object with that lineage tag already exists."*
A table that lost its `ref table` line, or a field-parameter row deleted
without its comma, won't even let Power BI open the project.

**The solution.** `tmdl-preflight` catches that whole class of defect on your
machine, in seconds, and mechanically repairs the ones whose fix is fully
determined by the failure. Zero runtime dependencies, Python 3.10+, MIT.

```console
$ tmdl-preflight check examples/bike-shop-broken   # exit 1 — see what's wrong
$ tmdl-preflight fix   examples/bike-shop-broken   # auto-repair the blockers
$ tmdl-preflight check examples/bike-shop-broken   # 0 errors — now it opens
```

---

## X / Twitter launch thread (8 posts)

**1/**
Your Power BI PBIP model is plain text now. So why can't you lint it?

Meet tmdl-preflight: preflight checks + auto-fixes for TMDL/PBIP semantic
models. It catches the defects that stop Power BI Desktop from opening your
project — before you commit.

MIT, zero deps, Python 3.10+. 🧵

**2/**
The defect that started it: a copy-pasted table file leaves two objects with
the same `lineageTag`.

Power BI Desktop opens fine. Code review passes. Then the deployment dies
days later:

  "an object with that lineage tag already exists."

That class of bug is exactly what this catches.

**3/**
The demo model in the repo, `bike-shop-broken`, literally won't open in
Power BI Desktop. Four blockers:

• a table with no `ref table` line (not attached to the model)
• a duplicate lineageTag
• a placeholder, non-UUID lineageTag
• a field-parameter row deleted without its comma

**4/**
One command shows you all of them — file, line, severity, and whether the
fixer can handle it:

  $ tmdl-preflight check examples/bike-shop-broken

`check` is strictly read-only. It never touches your files.

**5/**
Then `fix` repairs the mechanical ones and re-checks from disk:

  $ tmdl-preflight fix examples/bike-shop-broken

The missing ref line goes back, the duplicate tag is regenerated, the
placeholder becomes a real UUID, the orphan comma is deleted. Project opens.

**6/**
The design rule: a fixer never vouches for itself.

fix runs check → applies repairs → runs *every rule again from disk*. The run
counts as clean only if that re-check is clean. Auto-repair can never mask a
defect — the worst it can do is fail to remove one.

**7/**
And it only auto-fixes what the failure fully determines — a fresh UUID, a
deleted comma, a re-added ref line. Anything needing human intent (which of
two duplicate measures is real? retarget or delete a relationship?) stays a
plain finding. Your call, not the tool's.

**8/**
Three ways to run it: a CLI (check / fix / rules), a pytest fixture so model
health is an ordinary test, and a plain Python API.

MIT-licensed. Try it on your own PBIP folder:

  pip install -e .
  tmdl-preflight check path/to/YourProject

⭐ github.com/c-kapsalis/tmdl-preflight

---

## LinkedIn post

**Power BI's PBIP format turned the semantic model into plain text. I built
the missing piece: a preflight linter that tests it like code.**

For most of Power BI's life, the semantic model was a binary .pbix blob —
you couldn't diff it, review it, or test it. PBIP and TMDL changed that: the
model is now a folder of plain-text files. But the tooling to catch defects
before they ship never arrived.

So a duplicate lineageTag — left behind by a copy-pasted table file — passes
Power BI Desktop and every code review, then rejects the deployment days
later with "an object with that lineage tag already exists." A table that
lost its "ref table" line, or a field-parameter row deleted without its
comma, won't even let the project open.

tmdl-preflight catches that whole class of defect on your machine, in
seconds — and mechanically repairs the ones whose fix is fully determined by
the failure. The repo ships a demo model, bike-shop-broken, that genuinely
won't open in Power BI Desktop. One `fix` command repairs the four blockers
and it opens.

The design is deliberately conservative: fix runs check → repair → re-check
from disk, and the run is clean only if that re-check is clean, so a fixer
can never mask a defect. Anything that needs human judgment stays a plain
finding.

It runs as a CLI, a pytest fixture, or a plain Python API. Zero runtime
dependencies, Python 3.10+, MIT-licensed.

If you build Power BI models in PBIP and put them in source control, I'd love
your feedback. Repo and a 10-minute getting-started tutorial in the comments.

#PowerBI #DataEngineering #Analytics #OpenSource #DevOps

---

## Standalone one-liner hooks

1. Your PBIP model is plain text now. Lint it like code — tmdl-preflight
   catches what stops Power BI from opening the project.
2. A duplicate lineageTag passes Power BI Desktop and every code review, then
   kills the deploy days later. tmdl-preflight catches it in seconds.
3. The demo model in this repo won't open in Power BI Desktop. One `fix`
   command repairs the blockers and it does.
4. check → fix → re-check from disk: a fixer never gets to vouch for itself,
   so auto-repair can never mask a defect.
5. It only auto-fixes what the failure fully determines — a fresh UUID, a
   deleted comma, a re-added ref line. Everything that needs your judgment
   stays your call.

---

## Suggested hashtags

Primary: `#PowerBI` `#TMDL` `#PBIP`

Secondary: `#DataEngineering` `#Analytics` `#BusinessIntelligence`
`#OpenSource` `#Python` `#DevOps` `#DataOps` `#MicrosoftFabric`

Tight X set (3–4): `#PowerBI #TMDL #PBIP #OpenSource`
