# Relationship integrity

*Rules [R001](../reference/rules.md#r001--relationship-endpoints),
[R002](../reference/rules.md#r002--relationship-cardinality) and
[R003](../reference/rules.md#r003--relationship-duplicates).*

## The pitfall

Relationships are declared in their own file, `relationships.tmdl`, by
naming their endpoints:

```tmdl
relationship 1f6f2b3a-8c1d-4e5f-9a70-1b2c3d4e5f60
	fromColumn: Sales.product_id
	toColumn: Products.product_id
```

That separation is the vulnerability. The tables live in `tables/*.tmdl`;
the relationships that bind them live somewhere else entirely — so the two
**drift independently**. Rename a column in its table file and the
relationship keeps pointing at the old name. Delete a table and its
relationships stay behind. Cherry-pick a commit that adds a relationship
without the commit that adds the column. No single file looks wrong; the
model as a whole is broken, and the break is exactly the kind a
file-by-file code review misses.

A broken endpoint is a hard failure at import. But the softer failure
modes matter just as much:

- **Cardinality typos** (`fromCardinality: both`, `toCardinality: 1`) are
  not values the engine accepts — `one` and `many` are the entire menu.
- **Duplicate relationships** over the same column pair usually come from
  a merge keeping both sides. At best the engine rejects the second; at
  worst tooling behaves inconsistently about which one is "the"
  relationship.

A note on identity: relationships also carry GUIDs, but two models that are
*semantically identical* can have entirely different relationship GUIDs
(re-saving a model regenerates them). Anything that compares or
deduplicates relationships must therefore key on the **endpoints** — the
from/to table-column pairs — never on the GUID. tmdl-preflight follows
that principle in R003.

## How the rules detect it

The relationships file is parsed with a quote-aware reference parser
(table names may contain spaces and escaped quotes: `'Store ''B'''.id`).
Then:

- **R001** resolves each endpoint against the parsed model: the table must
  exist, and the named column must exist on it. Each missing half is a
  separate error naming the relationship.
- **R002** checks declared cardinalities against `{one, many}`.
- **R003** indexes relationships by their endpoint 4-tuple and flags every
  re-declaration of an already-seen pair (a warning — some pipelines
  tolerate a duplicate if only one is active, but it is virtually never
  intended).

## Why there is no auto-fix

Every repair here requires intent. A relationship pointing at a renamed
column *could* be retargeted — but the tool cannot know the rename
happened, versus the column being deliberately removed (in which case the
relationship should be deleted too). Of two duplicate relationships, which
survives depends on which side of the merge was right about `isActive` and
cross-filter direction. The rules make the drift visible at the moment it
is introduced; the resolution stays with the person who knows why the
change was made.

## See also

- [Bidirectional filters and orphan tables](bidirectional-and-orphan-tables.md)
  — the advisory topology checks over the same file.
