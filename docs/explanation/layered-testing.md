# The layered test model behind the rule set

tmdl-preflight's rules are organized the way mature BI test suites organize
their checks: in layers, ordered by how early the defect can be caught and
how much infrastructure the check needs. Understanding the layers explains
both the rule IDs and what this tool deliberately does *not* try to do.

## The layers

| Layer | Question | Rules | Needs |
|---|---|---|---|
| **Structural** | Do the files even parse? Is identity metadata sound? | M001–M005 | the files |
| **Expression** | Is the DAX lexically sound and are its references real? | D001–D003 | a parsed model |
| **Model integration** | Do cross-object structures cohere — relationships, field parameters? | R001–R005, F001 | a parsed model |
| **Report** | Does the report layer agree with itself? | B001, B002 | the `*.Report` folder |
| **Advisory** | Is the model following good practice? | S001 (and R004/R005 by severity) | a parsed model |

The ordering is diagnostic, not just taxonomic. A defect at one layer
routinely *causes* noise at higher layers: a table file that does not parse
(M002) makes every relationship into it look broken (R001), and a stray
comma in a field-parameter source (F001) makes every `NAMEOF` inside it
unresolvable (D002). When a run reports violations at several layers, fix
the lowest layer first and re-run — much of the rest usually evaporates.

## Everything here is "pre-flight"

All five layers share one property: they run **locally, against files, in
seconds, with no credentials**. That is the niche this tool occupies — the
checks you can afford to run on every save and must run before every push.

Deliberately out of scope, because they need a live service or a human:

- **Deployment state** — whether the model actually loaded, refreshed and
  returns sensible numbers. That is a post-deploy smoke test.
- **Data quality** — whether the pipelines filled the tables correctly.
  That belongs to the data layer's own tests.
- **Visual rendering** — whether the report *looks* right. That is manual
  review.

A useful way to say it: tmdl-preflight verifies the *definition*, not the
*deployment*. Passing preflight means the model deserves the (much more
expensive) downstream verification — it does not replace it.

## Severity encodes the layer's authority

Structural and expression defects fail hard (`error`) because they are
facts: the import *will* reject a duplicate lineage tag. Advisory rules
(`info`) never block, because they encode judgement, and judgement belongs
to the modeler: three bidirectional relationships might be exactly right
for your model. The `warning` tier in between (`--strict` promotes it to
blocking) covers things that are almost always wrong but have legitimate
exceptions.

This is also why the advisory rules do not grow fixers. An auto-fix that
"repairs" a bidirectional filter would be the tool overruling the modeler
on a judgement call — precisely what the
[imposition pattern's safety contract](imposition-pattern.md) forbids.

## Using layers in practice

- **Inner loop (editing):** `--select M002,D001` — parse and delimiter
  confidence in well under a second.
- **Pre-push:** the full default set.
- **CI:** the full set with `--strict`, read-only. See
  [Run tmdl-preflight in CI](../how-to/run-in-ci.md).
