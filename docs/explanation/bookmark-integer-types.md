# Bookmark integer types

*Rule [B001](../reference/rules.md#b001--bookmark-int-types).*

## The pitfall

In a PBIP project the report layer is JSON, and bookmarks
(`*.bookmark.json`) capture exploration state: which visuals are selected,
what filters apply, schema versions. Several of those fields —
`howCreated`, `ComparisonKind`, `Version` — are validated as **JSON
numbers**. If one arrives as a string, the report loader rejects the
bookmark with:

```
Invalid type. Expected Number but got String
```

How does `2` become `"2"`? Almost never by hand. It happens when bookmark
JSON passes through tooling that round-trips values as text: templating
scripts, JSON libraries in stringly-typed languages, sed-style bulk edits,
diff/patch workflows, or an editor autocompleting quotes. Semantically the
value is identical; `"howCreated": "0"` *reads* fine in review. JSON's type
system disagrees, and JSON-schema validation is exact about it.

The failure is also unusually annoying to diagnose: the error names neither
the file nor the path, a report can contain dozens of bookmarks, and each
bookmark nests the offending fields arbitrarily deep inside
`explorationState`. So a one-character defect costs a debugging session.

## How the rule detects it

Every `*.bookmark.json` under each `*.Report` folder is loaded and walked
recursively. Any occurrence of the three field names holding a string
value is reported with its full JSON path
(`explorationState.visualContainers.abc123.filters...Version`), so the fix
— manual or automatic — goes straight to the spot. Unparseable bookmark
files are reported by the same rule.

## Why the fix is safe

This is the purest fixer in the tool, because the repair is a *type*
correction with zero semantic freedom:

- `"2"` → `2` is information-preserving in both directions; nothing about
  the bookmark's meaning changes.
- Legacy string spellings of `howCreated` with a known meaning are mapped
  (`"User"` → `0`, `"System"` → `1`) — a documented translation, not a
  guess.
- A string with **no** known integer meaning (`"howCreated": "someday"`)
  is *left alone* and stays a violation on the re-check. The fixer never
  invents a value; unknown cases go to a human.

The rewrite re-serializes the JSON with standard 2-space indentation, so
the diff is exactly the changed values (plus, at worst, normalized
whitespace on first run). Running the fixer twice is a no-op.
