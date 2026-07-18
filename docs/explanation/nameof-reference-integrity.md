# NAMEOF reference integrity

*Rule [D002](../reference/rules.md#d002--nameof-resolution).*

## The pitfall

`NAMEOF()` returns the name of a column or measure as a string:
`NAMEOF([Revenue])` → `"Revenue"`. Its whole purpose is refactoring safety —
a rename should be caught where a hardcoded string would silently rot.

The catch: that safety exists only where a DAX *engine* validates the
expression. In a PBIP repository, the expressions that lean hardest on
`NAMEOF` are the ones an engine validates *last*: **field parameters**.
A field parameter is a calculated table whose source is a list of tuples —

```dax
{
    ( "Revenue",             NAMEOF ( [Revenue] ),             0 ),
    ( "Orders #",            NAMEOF ( [Orders #] ),            1 ),
    ( "Average Order Value", NAMEOF ( [Average Order Value] ), 2 )
}
```

— and it is the standard mechanism for letting report users swap the
plotted measure. Now delete or rename `Orders #` in a text editor. No
formula bar fires. The model deploys. And *at refresh or first use*, the
field parameter's source fails to evaluate — which takes down not one
measure but **every visual driven by the parameter**, plus anything
downstream that reads the parameter table. One dangling reference,
sitting in a file nobody re-opened, disables a report page.

The same applies to `NAMEOF` inside ordinary measures and calculation
items, with a smaller blast radius.

## How the rule detects it

Every `NAMEOF()` call in every DAX block is extracted (comments are
stripped first, so intentionally parked rows in a field parameter do not
count) and resolved against the parsed model:

- `NAMEOF([X])` — some table must declare measure `X`. If none does, that
  is an **error**. If *several* do, the reference is ambiguous and flagged
  as a **warning** (see [duplicate measure names](duplicate-measure-names.md),
  which errors on the underlying cause).
- `NAMEOF('T'[X])` — table `T` must exist and declare a column *or measure*
  named `X`; a missing table or member is an **error**. Qualified references
  to measures are accepted as valid: Power BI Desktop itself writes
  `NAMEOF('T'[Measure])` when you add measures to a field parameter, so
  flagging that form would bury real breaks under hundreds of false alarms
  on production-size models.

## Why there is no auto-fix

A dangling `NAMEOF([Orders #])` has at least three legitimate resolutions:
the measure was renamed (retarget the reference), the measure was removed
on purpose (delete the tuple — *and* its separator, see
[stray commas](field-parameter-comma-runs.md)), or the removal was itself
the mistake (restore the measure). Choosing requires intent the file does
not record. The rule's contribution is catching the break at edit time,
with the exact file and line, instead of at refresh time with a report
page down.
