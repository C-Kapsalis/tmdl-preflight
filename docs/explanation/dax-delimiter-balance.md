# DAX delimiter balance

*Rule [D001](../reference/rules.md#d001--dax-delimiters).*

## The pitfall

An unbalanced parenthesis in a measure sounds like the kind of error that
cannot possibly survive to a commit — Power BI Desktop's formula bar would
have refused it. And that intuition is exactly why it *does* survive:
**once a model lives in text files, most edits never pass through the
formula bar.** Delimiter damage arrives via:

- **Merges.** A conflict resolution keeps the `CALCULATE(` from one side
  and the closing of the other side's shorter expression.
- **Scripted refactors.** A rename script that matches a little too much,
  a template that emits one `)` too few.
- **Hand edits** to a fenced multi-line expression, where the closing
  delimiter is forty lines from the opening one.

The cost profile is asymmetric. The defective measure itself fails loudly —
but in TMDL, an expression's *textual boundary* is defined by indentation
and fences, so a runaway string or bracket can also confuse where the next
object begins, corrupting the parse of neighbours that are themselves
perfectly fine. And expressions outside measures are easy to forget:
calculated-table sources, calculation items and **dynamic format strings**
carry DAX too. A syntax error in a calculation group's format string is
particularly vicious, because it breaks every visual that touches the
calculation group, not just one measure.

Counting delimiters naively does not work, which is why "just grep for
unbalanced parens" fails in both directions. DAX comments (`--`, `//`,
`/* */`) legitimately contain unmatched delimiters; string literals may
contain `")("`; quoted identifiers may contain doubled escapes
(`'It''s Fine'`); a measure *name* may even contain `--`. A checker that
ignores this context drowns you in false positives until you turn it off.

## How the rule detects it

The checker runs a small character-class scanner over each expression,
tagging every position as code, string, quoted identifier, bracketed
identifier or comment — honoring the escape forms (`""`, `''`, `]]`).
Balance is then enforced only over *code* positions: parentheses and braces
must nest correctly, and every string/identifier/bracket region must
actually terminate. It checks **every** DAX expression the model carries:
measures, calculated columns, calculated-partition sources, calculation
items, and format-string definitions.

This is deliberately *not* a DAX parser. It cannot tell you that `SUMX`
got the wrong argument types; it tells you the expression is lexically
closed — the property whose violation corrupts files and blocks imports.
Semantic validation belongs to the engine, at deploy time.

## Why there is no auto-fix

An unbalanced expression has unboundedly many balanced completions, and
only the author knows which one restores the intended logic. Appending a
`)` at the end would silence the checker while changing — or preserving —
the wrong semantics silently. This is the canonical example of a defect
that *detects* mechanically but *repairs* only with intent, so it fails
plainly and points at the line.

## See also

- [NAMEOF reference integrity](nameof-reference-integrity.md) — the next
  check up: the expression closes, but do its references resolve?
