# TMDL well-formedness

*Rules [M001](../reference/rules.md#m001--model-structure) and
[M002](../reference/rules.md#m002--tmdl-well-formed).*

## The pitfall

TMDL's greatest strength — it is plain text, edited with ordinary tools —
is also its exposure. Between Power BI Desktop's serializer and your
deployment sit editors, merge drivers, shell scripts and CI checkouts, and
every one of them can damage a file in ways that are hard to spot:

- **Truncated or missing files.** An interrupted save, an overzealous
  `.gitignore`, or a merge that resolves "delete vs modify" the wrong way
  can drop `model.tmdl` or empty the `tables/` folder. The remaining files
  are individually fine; the model as a whole is not.
- **Encoding damage.** TMDL is UTF-8. A file resaved in a legacy codepage,
  or corrupted in transfer, stops decoding — and a single undecodable file
  blocks the whole model import.
- **Null bytes** are the classic symptom of a bad merge or a tool writing
  binary content into a text file. They are invisible in most editors and
  fatal to most parsers.
- **Unpaired expression fences.** Multi-line DAX expressions are wrapped in
  ```` ``` ```` fences. Delete a measure but miss its closing fence — an
  easy mistake in a large file — and everything after the orphan fence is
  swallowed into one giant "expression". The file still *looks* structured;
  parsers disagree about where the next object starts.
- **Headless table files.** A `tables/*.tmdl` with no `table` declaration
  (usually a half-finished refactor) contributes nothing but confusion.

The common thread: each of these is trivially cheap to detect and
disproportionately expensive to discover late, because the error surfaces
as a confusing downstream failure ("relationship endpoint not found",
"unexpected token") rather than as "this file is broken".

## How the rules detect it

M001 checks the skeleton: the definition folder has a `model.tmdl` and a
`tables/` folder containing at least one `.tmdl` file.

M002 sweeps every `.tmdl` file recursively: it must decode as UTF-8,
contain no `\x00` bytes, and carry an even number of ```` ``` ```` markers;
table files must contain a table declaration the parser can find. Parser
failures on individual files are surfaced through the same rule, so "could
not make sense of this file" is always reported as a well-formedness
violation rather than being silently skipped.

## Why there is no auto-fix

Every failure in this class destroys information. A truncated file cannot
be untruncated; the tool cannot know which of the two fence positions was
intended, or what the missing table declaration should say. Any "repair"
would be an invention. The correct resolution is human: restore the file
from version control, or finish the half-done edit. What the rule
contributes is *earliness* — you learn about the damage at your desk, from
a message that names the file and the byte, instead of from a failed
deployment that names neither.

## See also

- [The layered test model](layered-testing.md) — why fixing this layer
  first makes higher-layer noise evaporate.
