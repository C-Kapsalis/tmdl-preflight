# Explanation guides

Each guide covers one data-modeling precaution: the pitfall itself (why it
happens and what it costs), how the rule detects it, and — where a fixer
exists — why the automatic repair is safe.

## Design

- [The imposition pattern: check → fix → re-check](imposition-pattern.md)
- [The layered test model behind the rule set](layered-testing.md)

## Precautions

| Guide | Rules |
|---|---|
| [TMDL well-formedness](tmdl-well-formedness.md) | M001, M002 |
| [Duplicate and malformed lineage tags](duplicate-lineage-tags.md) | M003, M004 |
| [Column data types](column-data-types.md) | M005 |
| [DAX delimiter balance](dax-delimiter-balance.md) | D001 |
| [NAMEOF reference integrity](nameof-reference-integrity.md) | D002 |
| [Duplicate measure names](duplicate-measure-names.md) | D003 |
| [Relationship integrity](relationship-integrity.md) | R001, R002, R003 |
| [Bidirectional filters and orphan tables](bidirectional-and-orphan-tables.md) | R004, R005 |
| [Stray commas in field-parameter sources](field-parameter-comma-runs.md) | F001 |
| [Bookmark integer types](bookmark-integer-types.md) | B001 |
| [Bookmark visual references](bookmark-visual-references.md) | B002 |
| [Format strings](format-strings.md) | S001 |
