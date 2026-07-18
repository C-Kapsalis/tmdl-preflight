# Format strings

*Rule [S001](../reference/rules.md#s001--format-strings).*

## The pitfall

A measure without a `formatString` is not broken — it deploys, computes
and renders. It just renders **raw**: `1234567.891` instead of `$1,234,568`,
`0.0523` instead of `5.2%`. The costs are small individually and large in
aggregate:

- **Misreading.** `0.0523` sitting where a reader expects a percentage is
  an invitation to be off by a factor of a hundred. Formatting is not
  cosmetics; it encodes the *unit*.
- **Inconsistency.** When some measures are formatted and others are not,
  every report page becomes a patchwork, and every visual author fixes it
  locally — creating divergent per-visual formatting that overrides
  whatever the model later decides.
- **Invisibility in review.** The *absence* of a property is much harder
  to spot in a diff than a wrong property. New measures merge in unformatted
  and nobody notices until a stakeholder does.

Why only `info` severity, when the reasoning above sounds like a warning?
Because presence-of-`formatString` is a *proxy*, and a proxy can be
legitimately false: mature models often apply formats **dynamically**
through a calculation group whose format-string expressions compute the
format at query time (multi-currency models, unit toggles). In such a
model, most measures intentionally carry no static `formatString`, and a
blocking rule would train users to ignore the tool.

## How the rule detects it

Every visible (non-hidden) measure without a `formatString` is reported as
`info`. Hidden measures are exempt — they are internal plumbing whose
formatting nobody sees. And if the model contains any
`formatStringDefinition` block (the calculation-group dynamic-formatting
mechanism), the rule exempts the whole model automatically, on the logic
above. If your formatting strategy lives somewhere the rule cannot see —
per-visual formatting by policy, for instance — silence it explicitly with
`--ignore S001`.

## Why there is no auto-fix

The right format is domain knowledge: is `Discount Rate` a percentage or a
ratio? Is `Revenue` dollars, euros, or "whatever the currency slicer
says"? A fixer would have to guess units from names, and a wrong guess is
worse than no format — it *confidently* displays the wrong unit. The rule
keeps the gap visible; the human supplies the meaning.
