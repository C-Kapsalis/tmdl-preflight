# Release notes

## Unreleased

This release adds a large set of rules and commands, with a test suite
that runs on fictional stand-in models.

### Severity changes

Power BI Desktop (Windows, installer build, 2026-10-18) was run on copies of
the example model with one defect each. Where that evidence and the
"stricter wins" policy disagree, the evidence wins.

| Rule | Was | Now | Why |
|---|---|---|---|
| M006 model-table-refs | error, "Power BI will not open the project" | warning, baselinable | Desktop opened a model whose only defect was a table file with no `ref table` line, loaded the table and kept its relationship. The fixer stays: model.tmdl should list every table file. |
| M004 lineage-format | warning | warning | Desktop opened a model whose only defect was a placeholder tag. |
| M003 lineage-duplicates | error | error | Desktop refused to open the model: "Failed to add a deserialized Table object into the model ... An object with lineage-tag '...' already exists in the collection." |
| F001 fieldparam-comma-runs | error | error, new message | Desktop opened the model, but every visual that uses the field parameter failed ("Error fetching data for this visual. Failed to move the data reader to the next row."). F002 and F003 are expected to behave the same; not observed. |
| M011 property-after-child-block | warning | error | The stricter verdict wins. |
| R007 autodetected-relationships | warning | error | Stricter: zero tolerance. Its id match widened to "contains autodetected, any case", and it gains an unsafe fixer that deletes the relationship blocks. |
| M013 dangling-description at end of file | warning | error | The stricter verdict wins. |

### New rules

| ID | Name | Severity | Auto-fix |
|---|---|---|---|
| M016 | tmdl-file-sanity | error | no |
| M017 | space-indentation | error | no |
| M018 | model-annotation-duplicates | error | no |
| M019 | undefined-query-group | error | yes |
| C001 | required-model-objects | error | no |
| C002 | model-contract-objects | error | no |
| C003 | model-contract-relationships | error | no |
| C004 | fieldparam-registration-contract | error | no |
| R008 | fact-conformed-dimension-join | error | no |
| F005 | fieldparam-category-column | error | no |
| S003 | format-inference-naming (opt-in) | info | no |
| S004 | comment-ticket-refs (opt-in) | error | no |
| O001 | user-only-table-purity (opt-in) | warning | no |
| O002 | helper-measure-placement (opt-in) | warning (info in the lenient profile) | no |
| O003 | user-facing-in-helper-tables (opt-in) | warning | no |
| O004 | measures-in-fact-tables (opt-in) | warning (info for advisories) | no |
| O005 | measures-in-dimension-tables (opt-in) | info | no |
| O006 | empty-measure-tables (opt-in) | info | no |
| O007 | dead-fact-tables (opt-in) | error | no |
| N020 | dimension-prefix-floor (opt-in, disabled by default) | error | no |
| C012 | required-calc-groups (opt-in) | error | no |
| O008 | intermediary-helper-folder (opt-in) | warning | no |
| O009 | helper-measures-hidden (opt-in) | warning | yes |
| O010 | unused-helper-measures (opt-in) | info | no |
| O011 | user-facing-measure-visible (opt-in) | error | no |
| O012 | user-facing-display-folder (opt-in) | info | no |
| O013 | user-facing-measure-description (opt-in) | info | no |
| O014 | table-description-coverage (opt-in) | info | no |
| O015 | fact-table-filter-coverage (opt-in) | error | no |
| D010 | calc-dax-blocks-present (opt-in) | error | no |
| D011 | calc-item-blind-average | error | no |
| X001 | cross-fact-multirow-key-join | error | no |
| C005 | measure-reference-contract | error | no |
| C006 | guarded-ratio-wrapper | error | no |
| C007 | typed-flag-predicates | error | no |
| C008 | measure-arm-scoped-filter | error | no |
| S005 | format-min-decimals | error | no |
| R009 | relationships-presence (opt-in) | warning | no |
| R010 | relationship-cycles | info | no |
| R011 | fact-calendar-coverage | warning | no |
| R012 | calendar-relationship-cardinality | warning | no |
| R013 | calendar-standard-columns (opt-in) | info | no |
| R014 | dimension-key-columns (opt-in) | info | no |
| R015 | cohort-calendar-reach | error | no |
| R016 | dead-anchor-calendar | error | no |
| C009 | reach-guard-helper-consistency | error | no |
| C010 | grain-guard-coverage | error | no |
| C011 | grain-policy-exception | error | no |
| D012 | dax-or-chain-depth | error | no |
| M020 | calculated-column-expression-present | error | no |
| F006 | fieldparam-duplicate-rows | error | yes |
| F007 | fieldparam-family-consistency | error | yes |
| F008 | fieldparam-arity | error | no |
| F009 | fieldparam-level-consistency | error | no |
| F010 | fieldparam-retag (opt-in) | error | no (`fieldparam retag` command) |
| F011 | fieldparam-category-required | error | no |
| F012 | fieldparam-coverage (opt-in) | info | no |
| F013 | field-parameter-table-no-measures | error | no |
| F014 | selector-branch-resolution | error | yes |
| F015 | field-parameter-partition-shape (opt-in) | info | no |
| F016 | fieldparam-double-slash-rows | info | yes (opt-in) |
| F017 | fieldparam-blank-lines | info | yes |
| P001 | refresh-policy-repair | error | yes (unsafe; also adds P002's missing policies) |
| M021 | culture-orphan-bindings | error | yes |
| M022 | diagram-layout-blank (opt-in) | warning | yes |
| M023 | model-validation-notes (opt-in) | info | no |
| B005 | pages-metadata-schema (opt-in) | error | no |
| B005 | pages-metadata-schema | error | no |
| B006 | hierarchy-level-binding-shape | error | no |
| B007 | report-format-schema | error | yes |
| B008 | report-scaffold-integrity | error | no |
| L001 | rls-role-grammar | error | no |
| L002 | rls-username-function | error | no |
| L003 | rls-in-values-bypass | error | no |
| L004 | rls-mapping-table-hidden | error | no |
| L005 | rls-mapping-table-no-relationship | error | no |
| L006 | rls-inventory (opt-in) | info | no |
| P002 | refresh-policy-coverage (opt-in) | warning | via P001 |
| A001 | mapping-table-required-columns (opt-in) | error | no |
| A002 | mapping-table-info-reports (opt-in) | info | no |
| A003 | mapping-category-required-keys (opt-in) | error | yes |
| A004 | category-gate-coverage (opt-in, baseline) | error | no |
| A005 | f-measure-pattern (opt-in) | warning | no |

Rules that encode one team's conventions are **opt-in**: they run only when
named in `--select` or in the configuration's `select` (`rules` marks them).
Contract rules (C001-C008, R008, F005, S005, X001) read their contracts from the
configuration (`contracts` section or rule options) and report nothing
until configured.

**S004 stays opt-in.** The reference ran the ticket-reference gate on every
run against a committed floor file. The tool needs a floor file to be
configured before it can gate, and a rule that is on by default without one
fails every model that carries a reference, so the rule runs only when it
is named. The `comment-refs` command is the always-available gate: it reads
the same floor file and fails on a rise.

### Changed rules

- **P001** reports one finding per problem and words it the way the
  original does: a policy that comes after the partition, a policy that
  comes after a table-level annotation, a `policyType` outside
  `('basic',)`, a granularity outside the four, a period count that is not
  a positive integer, an unrecognized property, a missing
  `sourceExpression`, a table with no M partition, a `sourceExpression`
  that is not byte-identical to the partition source (the first difference
  is shown, with its line and column), and a `sourceExpression` that names
  no window. Only the drifted `sourceExpression` can be repaired
  automatically; the other problems need a human, are not marked
  auto-fixable and are not counted by `fix --check`.
- **P002** reports the eligible facts that have no policy with the
  original's reasons: a source that is already windowed (the block was
  probably lost in a merge), an event-date fact on a view, with the
  caution when the column is the ETL load stamp rather than an event date.
  The facts whose M source is hand-written are listed once per model, and
  the stale backlog entries are listed per model too. The exempt list
  accepts a table-to-reason map or a list of `{table, reason}` tables.
- **P001** reads the window markers from the configuration: a source
  counts as windowed when it names `RangeStart` and one of
  `window_markers` (default `["RangeEnd"]`).
  BUGFIX: the original's test hard-coded the window variable of one
  template; `window_markers = ["ir_dfilter"]` restores the original's exact
  test.
- **F015** says which table is wrong and what is wrong with it: `No
  partition found`, `Partition mode is '<mode>', expected 'import'` and
  `Source does not follow tuple pattern with NAMEOF`. It reads an unfenced
  source as well as a fenced one, so a table whose `source =` is followed by
  the M rows is judged on them. The run also prints, per model, how many
  axis tables were analysed, how many follow the pattern and how many do
  not, and how many of the calculated tables carry a partition (with the
  partition modes they declare). BUGFIX: the original printed the emoji
  double-encoded; the tool prints the intended characters.
- **N020** counts the table FILES whose name starts with the prefix (the
  convention is about the file name, not about the name the table
  declares) and says `Expected at least <floor> dimension tables starting
  with '<prefix>', found <n>`. When the floor is met, the rule reports
  how many dimension tables there are and shows a sample of ten names.
  The finding is an error, not a warning: the original failed the run
  when the floor was not met. The rule stays opt-in and disabled by
  default.
- **M022** reports the diagram layouts the way the check has always
  reported them: how many files it found, how many are already blank, and
  the ones that carry stale node data. The repair says which file it
  blanked and how many it blanked; a dry run says which file it would
  blank and writes nothing. Every semantic-model folder under the scanned
  path is checked, including one the tool does not load as a model, and a
  blank layout saved with Windows line endings counts as blank.
  BUGFIX: the layout the repair writes has LF line endings; the original
  wrote the line endings of the platform it ran on.
- **M021** reports the orphan bindings of a culture file as a block:
  `ORPHAN BINDINGS (<n>): <path>` and one line per entity. The repair
  prints how many binding nodes it dropped per file, and the run says how
  many files it fixed and how many nodes it removed. Only a member value
  or an array item binds: a binding that sits on the document's own top
  level binds to nothing and is not reported. BUGFIX: a repaired culture
  file keeps its line endings; the original rewrote the whole file with
  LF.
- **L001-L005** name the file and the problem in the wording the check
  has always used: `<file>: missing `modelPermission: read``,
  `<file>: `tablePermission <table>` has no `= <DAX>``,
  `<file>: `<table>` filter uses USERNAME() — replace with
  USERPRINCIPALNAME()`, the silent-bypass trap for a filter that reads a
  mapping table with `IN VALUES(...)`, the mapping table that is not
  `isHidden`, and the mapping table that is a relationship endpoint.
  `modelPermission:` may be written with any spacing (`modelPermission:read`
  is read). The mapping table is reported once, however many
  relationships point at it. BUGFIX: the section numbers of the original's
  guide are not printed; the tool does not ship that guide, so the
  reference would point a reader at a document they do not have.
- **L006** prints the inventory and the posture in the layout a reviewer
  reads: the roles directory, the role files with their model permission
  and the tables each may read, the user-mapping tables, and the posture
  (no RLS, static, dynamic via a mapping table, or incomplete) with the
  service-side concerns a file check cannot settle. BUGFIX: the section
  numbers of the original's guide are not printed, for the same reason.
- BUGFIX: the report-format validator now runs as a check rule (B007): one
  finding per defect, each carrying the validator's own message, and the
  banner the script printed is not reproduced.
- **B008** checks the report scaffold: `.platform`, `definition.pbir`,
  `definition/version.json` and `definition/report.json` (and
  `definition/pages/pages.json` when the report has pages) must be there, must
  parse, and must carry the three properties the loader reads. A folder that
  holds only `.platform` and `definition.pbir` (the blank-report form) needs
  no version.json and no report.json. The option `required_files` adds the
  files a team's own template requires.
- BUGFIX: `.pbi/localSettings.json` is not a required file: one script wanted
  it, the report-format validator only warns when it is there (B007), and the
  rule follows the validator.
- **B001** writes the bookmark file whole again (2-space indent, the key order
  kept, one trailing newline), so the file it leaves behind is the one the
  bookmark type checker wrote. Its findings carry the checker's wording
  (`[howCreated] at howCreated = 'User' (string, must be int)`), and a value
  the fixer cannot convert is no longer tagged as auto-fixable.
- BUGFIX: a `howCreated` of `"-1"` becomes the integer -1; the original left
  the string alone and failed its own re-check.
- BUGFIX: a bookmark that starts with a byte-order mark is read; the original
  counted it as an unreadable file.
- `check` and `fix` accept a `*.bookmark.json` file, or a folder that holds
  bookmark files, as a target: the bookmark rules no longer need a report
  folder around them.
- **B002** counts a visual only when it is a folder directly under a page's
  `visuals` folder; a folder named `visuals` anywhere else (a theme's static
  resources, for example) holds no visual and no longer hides a dangling
  reference. A report's bookmarks are the files directly under its
  `definition/bookmarks` folder. Its findings carry the original wording
  (`<file>: visualName '<ref>' has no matching visual directory`, and
  `Could not parse <path>: <error>` for a file it cannot read), and the rule
  description keeps the advice on how to resolve one.
- **B003** names the file it found an illegal key in, relative to the scan
  root, so two reports that hold a bookmark of the same name are told apart:
  the finding is `<path>  ->  options.<key>` and the fix line is
  `<path>  ->  removed options.<key>`. The summaries are the ones the repair
  script printed (`<n> illegal options key(s) across <scanned> bookmark
  file(s):`, `clean: <scanned> bookmark file(s), no illegal options keys`,
  `fixed <n> illegal options key(s):`, `nothing to fix: <scanned> bookmark
  file(s) already clean`, and `REFUSED <n> unsafe repair(s):`).
- BUGFIX: B003 removes an illegal key whatever its value is (an object, an
  array, a number in exponent form); the original refused those repairs and
  left the file unchanged.
- STRICTER: **B005** (pages-metadata-schema) is no longer opt-in: the pages
  metadata is checked in every run, because a report whose `pages.json`
  declares another schema or whose `pageOrder` is not a list breaks the page
  navigation. The option `accepted_schemas` still says which versions are
  expected.
- BUGFIX: **B004** reads `pageOrder` as a list of page names; a `pageOrder`
  that is a string is no longer read as a list of one-letter page names (B005
  reports it).
- **B006** names the offender the way the gate that grew out of the same
  script named it: `<visual.json>:<json path>.HierarchyLevel` (the path
  starts with a dot), and `<visual.json>: invalid JSON (<error>)` for a file
  it cannot read.
- `check --select B003` on a path with no bookmark file says `error: no
  bookmark files under <path> — the glob is broken, not the repo` and exits
  2.
- BUGFIX: a "MISSING $schema" finding of B007 names the path relative to the
  `.Report` folder (`definition/pages/p1/visuals/v1/visual.json`, `.platform`);
  the original computed the path three folders up, which was wrong for every
  file but `page.json`.
- BUGFIX: a `definition.pbir` whose `version` is not a string is an invalid
  version format, and a file that is not a JSON object is skipped; the original
  crashed on both. A byte-order mark is tolerated.
- **B007** tags only the findings its fixer repairs as auto-fixable: the
  schema URL and the version format of `version.json`. Everything else it
  reports (a missing `definition.pbir`, a `report.json` without a theme, a
  content file without a `$schema`) is a human decision.
- **M002** pairs ``` fences by structure (a fence opens after `=` and closes
  on the next line that starts with backticks), so backticks inside a fenced
  string literal are no longer an "unpaired fence". It also reports a
  broken quoted name (`'Rider's Name'`, an apostrophe not doubled) as an
  error and an empty name as a warning. The messages now read
  `File encoding error: <detail>`,
  `<file>:<line> contains null bytes` and
  `unmatched DAX code fences: <N> ``` markers (must be even)`.
- **M003** keeps a shared tag on the occurrence that most plausibly owns
  it: table files first, then `relationships.tmdl`, `expressions.tmdl`,
  `cultures/`, everything else (path, then line, inside a class). Before, a
  column could lose its tag to an expression because `expressions.tmdl`
  sorts before `tables/`. Expression occurrences now name the expression.
  BUGFIX: the order is deterministic — the first file in directory-listing
  order keeps the tag. The message now reads
  `Duplicate lineageTag '<tag>' found in files: <first file>, <duplicate file>`
  and names the line and the object of each occurrence.
- **M010** recognises `kpi`, `detailRows` and `relatedColumnDetails`, and in
  DAX bodies matches a metadata keyword as a whole word whatever follows it
  (`displayFolder` with no colon counts). Shared expressions are checked
  too; in M bodies only a line shaped like a property counts. STRICTER: a
  property-shaped line inside a string or a comment is not reported, and
  partitions, calculation items and shared expressions are checked too. The
  messages now name the object and quote the offending line:
  `<object>: property right after `=` (line <N>): <text>`,
  `<object>: property buried in expression (line <N>): <text>` and
  `<object>: property inside ``` expression (line <N>): <text>`. BUGFIX: a
  property-shaped line inside a multi-line string in a fenced body is not
  reported; it is text, not a property.
- **M011** knows the nested sections `kpi`, `detailRows`,
  `relatedColumnDetails` and `formatStringDefinition`, resets at `role`
  declarations, and its fixer moves the line to the object's first property
  slot (right after the expression) instead of the end of the property
  section. Valued properties move like flags; a file that would need more
  than 200 moves is left alone. STRICTER: the rule applies to any object,
  not only to measures and columns, and a valued property moves like a
  flag. The repair moves the one line: the blank line that stood before it
  stays where it was, the line keeps its own indentation, and an object
  that carried the same flag twice keeps one copy, in its first property
  slot (Power BI rejects a duplicated property). BUGFIX: the file keeps
  the final newline it had, and a file that mixes its line endings is now
  reported as a refused repair (it was silently left alone). STRICTER: the
  rule knows a few more simple properties than the reference
  (`sourceColumn`, `sourceLineageTag`, `isNullable`,
  `isAvailableInMdx`) and wants the property one level under its owner,
  where the reference wanted any depth.
- **M013** fix removes the run and the one blank line directly after it, at
  the end of the file too; blank lines before a run are never touched. New
  option `fix_mode = "attach"` deletes the blank lines between a
  description and its object instead, keeping the documentation. The attach
  mode works on the table files only, and its report counts the occurrences
  in a dry run and the blank lines it removed in a live run.
- **M001** and **M016** name what is missing:
  `<model>: required directories missing: [<names>]` and
  `<model>: required files missing: [<names>]`. M016's other messages read
  `Model file must start with 'model' declaration`,
  `Table file must start with 'table' declaration`,
  `Measure '<name>' has empty DAX expression`,
  `<file>: Windows line endings (CRLF)`,
  `line <N>: root-level comment is indented` and
  `unmatched DAX code fences: <N> ``` markers (must be even)`.
- **M004** says `LineageTag '<tag>' is not a canonically-formatted UUID
  (expected 8-4-4-4-12 hex)`.
- **M020** says `<Table>[<Column>] has empty expression` for a calculated
  column whose expression is empty, whether the expression is a blank block
  or the `=` has nothing after it at all. STRICTER: the check covers every
  table of the model, not only the axis tables; a calculated column with no
  expression is broken wherever it sits.
- **M023** (new, opt-in) carries the notes the file validator raised
  without failing on them: `Missing recommended model property: <p>`,
  `Column '<c>' missing dataType`,
  `Column '<c>' has unknown summarizeBy: <v> (valid: none, sum, min, max,
  count, distinctCount, average, standardDeviation, variance)`,
  `Calculation group has no explicit precedence (defaults to 0)` and
  `Calculation item should typically use SELECTEDMEASURE or
  ISSELECTEDMEASURE`. The rule is off by default: the notes are advice,
  and a run never fails because of one. The measure-prefix and
  selector-table naming notes of the reference are tied to one template and
  are not carried over.
- **R001** messages say "not found"; an endpoint spelled with different
  casing is an error; new option `min_endpoint_success_rate` (default 0.95)
  notes a low share of valid relationships (each broken endpoint is an
  error whatever the share, so the rate never adds a finding).
- Policy toggles (`require_fact_link`, `require_dimension_keys`, D010's
  `enabled`, ...) set to false skip their rule: the run lists it under
  `skipped` and reports nothing for it.
- A fixer marked unsafe can be opted into a blanket `fix` by its own option
  (R007 `fix_autodetected_relationships`).
- **D001** messages name the delimiter kind ("double quote", "single
  quote", "bracket", "parenthesis", "brace") and the character position of
  the problem inside the expression: `Unmatched opening parenthesis '(' at
  position 3`. The closers come first, in text order; only the earliest
  still-open opener of each kind is reported, in the order parenthesis,
  bracket, brace, double quote, single quote. The object label is
  `Table[Measure]` (or `Table[Column]`, `Table (partition source)`,
  `Table[Item] (calculationItem)`, `Table (formatStringDefinition)`). New
  option `min_success_rate` (default 0.90): when fewer measure and
  calculated-column expressions are clean, one extra error says so (each
  unbalanced expression stays an error whatever the share). Every model
  with expressions gets the summary note (`DAX Validation Summary:` with
  the expression count and the clean share), a clean model too. A model
  with no measures is an error.
- **D005** says `VAR 'total' declared twice in the same scope (measure at
  line 12)`: the name in lower case and the line the object is declared
  on.
- **D010** reports an error when it is enabled (it used to warn) and prints
  the per-kind counts the way the reference does: `[OK] Extracted 3
  non-measure DAX blocks:` with one `   - {kind}: {count}` line per kind,
  sorted by kind name. It stays opt-in: the convention is one template's.
  STRICTER: the reference failed the run on a model without such blocks,
  and so does the tool now.
- **X001** says `'Left'[key] compared against VALUES('Right'[key])` and
  advises comparing at the grain the question is asked at: build each
  side's set of business keys with
  `CALCULATETABLE(VALUES(<dimension>[<business key>]), <fact>)`, then use
  EXCEPT/INTERSECT over those sets.
- **D002** is rebuilt on the new `tmdl_preflight.nameof` module: quoted
  members (`Sales['Amount']`), double-quoted tables and dotted table names
  are accepted; an unparseable NAMEOF in a field-parameter row is an error;
  a table-qualified measure outside a field parameter is a warning (it
  names the bare form to use instead); new option `excluded_tables`. Every
  unresolved-reference message contains "not found".
- **D002** says why a reference does not resolve, in the reference's
  wording: `Measure 'X' not found in any table`, `Ambiguous: measure 'X'
  exists in multiple tables: ['A', 'B']`, `Table 'T' not found`, `Column 'C'
  not found in table 'T'`, `'M' is a measure, not a column. Use
  NAMEOF([M]) instead` and `Invalid reference format`. A finding in a
  field-parameter row names the row it sits in: the object label is
  `x-Plot Specific 1['Bad']`. BUGFIX: a broken row said nothing about which
  row it was.
- **Casing mismatches are errors** (project decision): D002 and D004 report
  a table, column or measure spelled with different casing from its
  declaration as an error, although DAX itself resolves it.
- **D004** reports an unqualified `[X]` that names a measure declared in two
  or more tables as an ambiguous reference (warning), ignores TMDL property
  lines that leaked into an expression (M010 reports those), and gains a
  fixer marked unsafe: selected explicitly, it deletes whole generated
  `ISFILTERED('<missing table>') || ...` lines and nothing else.
- **D004** ignores every property line that can leak into an expression:
  `sortByColumn`, `lineageTag`, `sourceLineageTag`, `displayFolder`,
  `formatString`, `dataType`, `summarizeBy`, `sourceColumn`, `isHidden`,
  `isKey`, `isNullable`, `isUnique`, `isDataTypeInferred`,
  `isAvailableInMdx`, `dataCategory`, `encodingHint`, `queryGroup`,
  `contentType`, `mode`, `annotation`, `changedProperty`,
  `extendedProperty`, `relatedColumnDetails` and `description`. A member
  written in the quoted form (`Sales['Amount']`) resolves without the
  quotes, the way the NAMEOF rule reads it. BUGFIX: both were false
  positives on legal expressions.
- **D004** reports a missing table as one finding per object, with the
  missing tables in sorted order: `measure Sales[Revenue] -> missing
  'Alpha', 'Beta'`. The model carries the note `DANGLING TABLE REFS (1
  object(s), 2 ref(s)): <definition folder>`, and the run ends with `1
  model(s) with dangling DAX table references.`
- **D004** rebuilds the generated `i-Applied Filters` measure from the
  y-axis field-parameter tables before it removes anything else, and says
  what it repaired and what it could not: `repaired 1 site-group(s)` and
  `NOT auto-fixable: Sales[Revenue] -> Alpha`. Every model is processed
  before the run ends, and the run fails when something is left to a
  human. BUGFIX: the repair no longer stops at the first model that needs
  a human.
- **NAMEOF** extraction ignores a malformed reference whose quoted table
  name contains a double quote.
- Names declared with trailing spaces inside quotes (`'Frame Size   '`) are
  read trimmed.
- **D012** checks every measure and calculated column by default, not only
  the configured grain-guard measure: an over-long `||` chain breaks the
  model on import wherever it sits. `or_chain_measures` narrows the rule to
  the named measures. STRICTER.
- **F001** says how many orphan commas it found, before anything else
  (`2 orphan comma(s).`), and names the place it found them: a whole
  field-parameter file is `(field-parameter file)`, a calculated table's
  partition is `(partition source)`. The Desktop sentence is unchanged.
- **F002** and **F003** say what the defect is, in the words the original
  scripts used: `tuple closes with no ',' before the next tuple` and
  `last row before '}' has a trailing ',' -> DAX: "Table constructor cannot
  have optional argument"`, followed by the note that the Desktop symptom
  is expected but was not observed for these defects alone.
- **F004** says `<row> has <n> fields, norm is <m>`.
- **F006** says `'<row>' -> <NAMEOF call> (order=<n>, id='<id>') appears <n>x`,
  with the whole NAMEOF call compared whitespace run by whitespace run: two
  spellings of the same call (`NAMEOF([Units])` and `NAMEOF ( [Units] )`)
  are two rows, not one row twice. Findings are ordered by the row, not by
  where the first copy sits.
- **F001, F002, F003, F004 and F006** now say, per file and per row,
  what they changed (`x-Selector 1.tmdl: removed 2 orphan comma(s)`, `x-
  Selector 1.tmdl:12: "CPM" padded 5 -> 6 (field 6 set to "Other") —
  ANNOTATED IN PLACE, needs BI review.`), and print the original's closing
  advice once per run, after the summary: `Removed 3 orphan comma(s) across
  1 file(s). ...`, `Repaired 1 separator defect(s) across 1 file(s). ...`,
  `removed 1 duplicate axis row(s) under <folder>`, and the three ragged-row
  blocks (auto-realigned, auto-padded, over-long rows left untouched). F002
  and F003 are two rules, so each prints its own separator-defect line when
  it changed something.
- **F006**'s fixer leaves a commented-out row alone: a copy of the row
  that sits behind a `--` or `//` marker is a parked row, and removing it
  would destroy a row the author kept on purpose.
- **F007** says `MISSING <field> (offered by <file>)`, `date-named field
  <field> must not be in Plot Specific 2` and `<field> is offered NOWHERE
  in the canonical set — Plot Specific 1 may not introduce fields`. The
  field is named by its identity: a measure by its bare name, a column as
  `<table>[<column>]`.
- **F007** copies a missing row from the numbered tables first and only
  then from the second plot-specific table, and the second plot-specific
  table is the LAST one numbered 2 or higher (`x-Plot Specific 3` when both
  2 and 3 exist). A row of another width is never copied; the fixer says
  so and leaves the file alone.
- **F007** writes the three annotations the original wrote - `AUTO-ADDED`,
  `AUTO-PROMOTED` and `AUTO-REMOVED`, each with the reviewer's line below
  it - and names the file and the row it edited.
- **F005** is on by default for the numbered x tables `x-Selector 1` to
  `x-Selector 9` (exact names), reading only fenced calculated sources, and
  reports one row at a time as `<table>: "<label>"`. The rule text is "All
  x-Selector field parameters must have 4th parameter (category_x_id)".
  Configure `category_column_tables` to read other tables instead.
- **F016** reports a field-parameter row that carries `//`: a row that was
  commented out, or a label with a double slash in it that some editor
  truncates. The rule reads the first fenced source of every axis table
  (`*-Selector*`, `*-Plot Specific*`). The repair deletes the offending
  rows, keeps a copy of the file in `tables/backups/<file
  .double_slash_backup>` and is opt-in, because it removes text from a
  picker a user sees: a blanket `fix` skips it, `fix --select F016` runs
  it. A dry run says what it would remove and writes nothing.
- **F017** reports a fenced field-parameter source that is not in its
  canonical form - a blank line, the indented brace, the rows with their
  blank runs collapsed, the indented closing brace - and the repair rewrites
  the block to that form. The canonical indentation is the indentation of
  the `source = ` line plus two tabs.
- **B002** reports a bookmark file that is not valid JSON.
- **B001-B003** skip bookmarks of archived report copies: paths containing
  `legacy/`, `_backup/`, `_legacy/`, `_b2/`, `DemoData.` or `demodata/`
  (project section `bookmarks.archive_markers`; an empty list scans them).
- `check`/`fix --select B003` on a path with no bookmark file exits 2
  (nothing scanned is not a clean result).
- `fix` exits 2 when a fixer refuses a repair it cannot prove (the file is
  left unchanged and listed under `refused_fixes`); other files are still
  repaired.
- **F010** judges the numbered `y-Selector` tables and the `y-Plot Specific`
  tables as ONE family: a display name must carry the same category in all
  of them, and the finding says which file disagrees
  (`Main is g_b in y-Plot Specific 1.tmdl but g_a in a sibling table`). The
  globs that share their first word are one family, so the default family
  is `y-Selector *` together with `y-Plot Specific *`. BUGFIX: before, only
  the first file that held a name was compared, so a half-finished retag
  went unnoticed.
- **F011** runs in the default suite (it only looks at the tables named
  `x-Selector 1` to `x-Selector 9` and `y-Selector 1` to `y-Selector 9`, so
  it cannot fire on a model without them) and reports one finding per axis
  family, with the rows that carry no category:
  ```
  Found 1 x-Selector entries without category (4th parameter)
  All x-Selector field parameters must have 4th parameter (category_x_id)

    - x-Selector 1: "Pace"

  Valid categories: Performance_x, analytics_api_x, kplanner_x, etc.
  Example: ("Cost", NAMEOF([!Cost]), -10, "Performance_x")
  ```
  A row behind a `--` or `//` marker is parked, not live, and is never
  judged. BUGFIX: before, a parked row was reported as a row without a
  category.
- **F012** opens its report with the counts of the audit — how many measures
  the metric axis names, how many user-facing measures there are, how many
  of them the axis covers (with the share) and how many it does not, then
  the dimension side: how many dimension tables the axis names, how many
  the model holds, how many of them the axis does not expose and how many
  the axis names that do not exist. The lists follow, each under its own
  heading:
  ```
  User-facing measures not in x-Selector (5):
    - #Report Measures[Cups]
  ```
  BUGFIX: a row that names its measure with a quoted table name
  (`NAMEOF('#Report Measures'[Cost])`) counts as on the metric axis; the
  measure is on the axis, whatever way the row spells it.
- **F008** says what the rows carry and what the table declares:
  `field-parameter tuples carry 7 field(s) but the table declares 6 column(s) (Value1..Value6) — mismatch breaks compilation.`
  STRICTER: the check reads a field-parameter source that is not written
  between fences; the original skipped those tables, but Desktop writes
  some of them that way.
- **F009** names the drilldown levels a dimension is missing from:
  `NAMEOF(beans[roast]) in y-Selector 1,2 but MISSING from y-Selector 3`,
  and reports every target a plot-specific table adds to the numbered
  levels on its own:
  `y-Plot Specific 1: NAMEOF(beans[farm]) absent from every numbered y-Selector level`.
- **F013** says which table carries the measures and which family it
  belongs to: `x-Selector 2 unexpectedly contains 1 measures. x-Selector tables should be dimension tables with columns only.`
  A plot-specific table names the family it belongs to.
- **F014** reports one finding per branch line, not per call, and the
  finding carries the count of the model and the line it is about:
  `2 field-parameter selector branch(es) call a measure that does not exist — the containing helper/projected measure fails at processing time and PBI rejects the model on refresh/deploy.: Fixture Measures.tmdl:11  [Gone Measure] [Also Gone]`.
  The auto-fix says how many branches it killed, once per model:
  `killed 2 dangling selector branch(es)`.
- The findings of F011, F012, F013 and F014 name the object in the message
  and leave the report's object field empty: the message already says which
  table, which line and which measure the finding is about.

### Console reports

Four rules came from scripts that printed a report of their own instead of
a list of findings. When such a rule is the one rule the run selected
(`--select`), the tool prints that report in front of its own summary, in
the same layout and with the same wording:

- **M003** (the lineage repair) prints the model it works on, whether the
  run is live or a dry run, every duplicated tag with its locations, the
  fresh tag every occurrence gets, and the footer. A run over more than one
  model also prints the repository scan and its summary.
- **M011** (the misordered-property repair) prints, per file, the
  properties it moved and the object they belong to, and the footer.
- **M013** (the dangling-description sweep) prints, per file, the run it
  found and the comment text it holds. In attach mode it prints the
  comment-spacing cleanup's report instead.
- **M017** (the TMDL file validation) prints the validation header, the
  files it checked, the validation summary and the model's own counts
  (files, valid files, invalid files, measures, tables, lineage tags,
  duplicate tags, success rate). A repair the tool could not prove is
  reported on standard error as `ERROR <path>: <reason>`, and the run
  exits 2.

The tool's own report follows, so the exit code and the JSON payload are
unchanged.

### Commands and options

- The parseability check is `check --select D001`. Every finding is
  labelled `Table[Measure]` and names the delimiter kind and the character
  position, so the same information the standalone console printed is in
  the report; there is no separate console for it.
- `exclude` globs match the path relative to the scan root (the folder you
  pass), as well as the path inside the PBIP item. Folders above the scan
  root never take part, so a checkout under `~/legacy/` is still scanned. A
  model or report whose files are all excluded is skipped before parsing.
  The JSON summary gains `files_scanned`, `excluded_files`, and `excluded`
  now counts skipped files as well as excluded violations. A partly
  excluded model is still parsed in full (so references into excluded files
  resolve); only its findings in excluded files are dropped.
- A bare `definition/` folder is accepted as a model when it holds
  `tables/`, `model.tmdl` or `expressions.tmdl`.
- `fix --dry-run` reports what would be repaired and writes nothing.
- `fix --verbose` lists every file a dry run would change (the attach mode
  of M013 lists its files only with this flag).
- STRICTER: `fix` exits 1 when findings remain after the re-check; the
  original's fixers always exited 0 and left the verdict to the gate that ran
  them. The re-check is the fix contract of every rule, so the run says what
  is left.
- `fix --clear-cache` deletes `<Model>.SemanticModel/.pbi/cache.abf` after
  lineage tags changed; without it the tool prints a hint when the cache
  exists.
- `grain <path> [--cost-fact T] [--backend-fact T ...] [--permit T] [--check
  --guard-table T [--guard-measure M]] [--emit-config]` derives conformed and
  blocked dimensions from the relationship graph (USERELATIONSHIP to a
  calendar counts) and checks a grain guard against it. The cost fact
  defaults to `Campaigns`, the backend facts to `_Users` and `Transactions`
  (naming one replaces the default list) and the guard measure to
  `-helper Cost Grain Valid`; a guard measure whose name starts with `-`
  needs the `--guard-measure=...` form. The verdict table is one row per
  dimension, left-aligned and padded, and `--check` prints the coverage
  gaps (or the clean line) under it. BUGFIX: a dimension that is also a
  fact counts as reaching itself, so a backend fact that is a dimension is
  CONFORMED when it reaches every backend fact.
- `report complexity|nameof|relationships <path> [--json]`: read-only
  reports (measure length distribution and threshold suggestions, NAMEOF
  inventory, relationship topology). The NAMEOF report prints the
  reference's layout: the title rule, the counts, and then either
  `✅ All references are valid!` or the issues under `ERRORS:` and
  `WARNINGS:`, each with the reference, the reason and the line the call
  sits in. Within one expression the references come in the reference's
  order: the quoted-table ones, the unquoted-table ones, then the bare
  ones.
- `format-resolve <path> --name NAME [--axis T] [--label L] [--compare N2]`
  resolves the format a name gets from a format calculation group; the same
  evaluator backs S005. Python API: `tmdl_preflight.format_resolver`
  (`resolve`, `decimals`, `UNKNOWN`).
- `stats --measures` summarises how measures are organised (name classes,
  helper kinds, field-parameter surfacing, top tables, described helpers).
- `comment-refs <path> [--list] [--json] [--floors FILE] [--tighten]`
  counts ticket references in comments; `--tighten` only ever lowers floors
  and drops all-zero entries.
- `dead-facts <path> [--capture FILE] [--json]` lists the fact tables no
  measure reads. `--capture FILE` records them as the floor the dead-fact
  gate compares against (a JSON object of model key to the sorted list of
  dead fact tables, the models with none left out).

  counts ticket references in comments. With a floor file it gates: a rise
  above the floor fails, a fall is reported for tightening. `--tighten`
  only ever lowers floors and drops all-zero entries.
- `baseline --capture-floors O007|R008|R016 [--output FILE]` writes the
  floor file of a ratcheted rule from today's findings.
- Ratchet files for O007, R008 and S004 keep the shape teams already use: a
  JSON object keyed by the `*.SemanticModel` folder relative to the scanned
  root (with or without the suffix). Recorded entries that no longer fail
  produce a tighten hint in the report's `notes`.
- `info --categories <path> [--json]` decodes the encoded category-mapping
  table: `groups` maps each group id to its categories (many-to-many; axis
  spacers and the standard calendar groups excluded) and `fact_tables`
  maps every fact table to the categories its metric-axis measures reach.
  Python API: `tmdl_preflight.categories`.
- `fix --check` writes nothing and exits with the number of objects the
  selected fixers would act on (capped at 255); `fix --only missing|invalid`
  narrows the refresh-policy fixers. The project section `refresh_policy`
  holds `loader_function`, `window_markers` (default `["RangeEnd"]`),
  `window`, `exempt`, `backlog` (per model), `etl_stamp_columns` and
  `inline_template`.
- `manifest <MODEL> [--out FILE] [--check] [--targets FILE]` writes a
  byte-stable JSON manifest (table roles, columns with their warehouse
  origin through Power Query renames, measures, the warehouse table each
  partition reads in loader-call, inline-window or navigator form,
  relationships, domains). The warehouse project and dataset the model
  declares are compared with an optional targets file; a mismatch exits 1
  and writes nothing. Config section `manifest` (`sources`, `target`,
  `domains`, ...). Python API: `tmdl_preflight.manifest`.
- `schema-check --manifest M --schema SNAPSHOT [--ignore-columns FILE]
  [--strict] [--project P] [--dataset D]` reconciles a manifest with an
  exported schema snapshot (`missing_in_bq` fails, `needs_review` for
  programmatically renamed tables, `not_surfaced_in_pbi` and suspicious
  type pairs are informational); the result is written next to the
  manifest as `<name>.bq.json` and says what was checked against, what
  the warehouse has and how the model's columns differ from it;
  `schema-check --sql-dir DIR --entries FILE [--write-holdbacks]
  [--clear-ready]` proves view-column exposure from SQL files (exit 3
  when an entry is held).
  Python API: `tmdl_preflight.reconcile`.
- `refs NAME [PATH ...] [--files] [--include-nonlive] [--loose]` counts
  the anchored references to a name, model side and report side, live and
  archived.
- `live <MODEL> --workspace ID --dataset ID [--checks ...] [--strict]
  [--record DIR | --replay DIR]` (opt-in, the only command that uses the
  network): checks the published dataset over the Power BI REST API.
  Checks: `live-refresh-status`, `live-freshness`, `live-table-sample`,
  `live-dimension-rows`, `live-measure-sample`,
  `live-parameter-table-measures` (off unless `live.parameter_table_measures`),
  `live-uniform-row-limit`, `live-calendar-rows`, `live-dimension-multirow`,
  `live-calendar-scan`, `live-calendar-vs-parameters`, `live-parameter-audit`,
  `live-identity`, `live-filter-compare`, `live-metadata`,
  `live-filter-diagnostic`, `live-smoke` and `live-bpa`. Outcomes are pass,
  warn, fail, skip or error; exit 1 on fail or error (and on warn with
  `--strict`). The dataset name must match the local model folder unless
  `--expect-name` or `--no-coupling-check` is given. Recordings are keyed
  on the whitespace-normalised query text. Settings: config section `live`.
  The command signs in with a service principal, and with an interactive
  sign-in when the optional `msal` package is installed; the interactive
  sign-in is an addition the original did not have. Python API:
  `tmdl_preflight.live` (`ReplayClient`, `LiveBPA`, ...).
- The pytest plugin demotes test-body failures on the models listed in the
  configuration's `advisory` list to expected failures; passes stay passes
  and setup failures stay failures.
- `fieldparam retag <files> --names N1,N2 --from OLD --to NEW` changes the
  category value of the named live rows across sibling tables; a name not
  found live under OLD fails with "retag incomplete" and nothing is written.
  Every file given is retagged, and a name missing from any one of them
  stops the whole run:
  `field-parameter retag incomplete: ['Main'] not found under category 'g_a' in y-Selector 2.tmdl`.
  `--names` may be given more than once, one name per option, for a display
  name that holds a comma. The success lines list the retagged names in the
  order their rows occur in the file. BUGFIX: before, only the first file
  that held a name was rewritten, and the siblings were left behind — the
  half-retag the family rule then reported.
- New Python API: `tmdl_preflight.measure_classes.classify_measure_name`
  (helper vs user-facing names, helper subcategory, scaffolding noise) and
  `tmdl_preflight.roles.fact_tables` (the shared fact-table law).
- The configuration accepts project sections (`contracts`,
  `refresh_policy`, `live`, `advisory`); rule options whose default is
  unset accept any JSON value.
- Rules carry a `safe` flag (`rules --json`). A fixer marked `safe: false`
  (it changes data or regenerates content) never runs in a blanket `fix`;
  select its rule explicitly to run it. The JSON payload lists such
  fixers under `skipped_fixers`.

### Changed

- **The opt-in rules say so, and the catalog lists how to enable them.**
  Every rule that encodes one team's conventions (the organisation, naming
  and coverage rules, the required calculation groups and the format
  inference naming) now says in its description that it is opt-in, and
  the generated catalog prints the `select` line that turns the whole
  opt-in set on.
- **The unused-helper check prints the reference's inventory.** It reports
  per model how many TMDL and report files it scanned, how many helper
  measures there are, how many are used and how many are not, the helpers
  that five or more references point at (with the TMDL and JSON counts) and
  the ones nothing references. A report file is matched by its extension
  whatever its case.
- **An inline-row table is recognised only in the case M spells it.** M is
  case-sensitive, so a source that says `table.fromrows(` calls a
  different function and does not author the table's rows: such a table
  is a fact like any other, and the dead-fact gate can report it.
- **The measure-organisation summary reads the y-axis tables and counts the
  helpers by kind.** The surfacing set of the summary is now the numbered
  x-axis *and* y-axis tables (`x-Selector 1` to `x-Selector 9` and
  `y-Selector 1` to `y-Selector 9`); the option still overrides it. The
  summary lists the helper measures by kind, each with a line that says
  what that kind of helper is, and the dash-helper block leaves out the
  two description lines when there is no dash helper at all.
- **The visibility and coverage checks print their reports.** The
  helper-visibility check reports per model how many helper measures there
  are, how many are hidden and which visible ones need hiding; the
  user-facing-visibility check reports the same for the user-facing names
  (with the scaffolding names counted apart) and, when one is hidden, the
  judgment note that says what to do with it. The folder, description and
  table-description checks print the coverage of the model with one
  decimal, and the list of the measures or tables that are missing it. A
  display folder counts when the property is there and not empty as
  written, so a whitespace-only value is a folder; the rule that wants a
  display folder on an intermediary helper still treats whitespace as
  empty.
- **The required-calculation-group check prints a summary and an
  inventory.** Per model it says how many calculation groups are required,
  how many are present and how many are missing, and lists each of them.
  The inventory of the `z-Selector` tables (their columns and measures, and
  the measures that use `SELECTEDMEASURENAME()`) is report output only,
  never a finding.
- **A skipped rule says why it did not run.** The description check that
  is turned off reports `Description validation disabled`; the
  calculation-group check with all its switches off reports `Calculation
  group validation disabled in policy`. The `skipped` list of the JSON
  output still holds the rule names; the reasons are in `skip_reasons`.
- **The helper-placement rule frees the axis field-parameter tables and
  prints its reports.** The default `field_parameter_prefixes` are
  `x-Selector`, `y-Selector`, `x-Plot Specific` and `y-Plot Specific`, so a
  helper in one of them is never a finding in the strict profile (the `#`
  and `_` host bans still come first). STRICTER: a helper in a user-only
  (`#`) or dimension (`_`) table is still a finding even when the table is
  an axis table, so the two bans cannot hide each other. The strict text
  output groups the findings by subcategory, with the guidance of each
  kind; the JSON output keeps one record per finding. The lenient profile
  prints, per model, the four counts (f-, `-helper`, `-Visual`/`w-`, i-),
  the list under each non-empty one with the table the helper belongs in,
  and an all-clear line when nothing is misplaced.
- **The measures-on-facts check reads the reference's internal-name list and
  prints its report blocks.** A measure whose name carries one of
  `ga4traf`, `ga4users`, `ga4convs` or `related` is advisory, never a
  warning; the token itself is not a tag. The tool's list was empty
  before, so such a measure was a warning; the option still overrides the
  list. The advisory tags follow the reference: `hidden`, `test`, `helper`
  (a name that starts with `-` only), `diagnostic` and `lowercase`, in that
  order, and no bracket group when there is none. The text report now
  prints, per model, the user-facing measures it found on a fact (with the
  field parameter that surfaces one) and the advisory ones with the
  recommended actions.

- **A floor file can be written by the tool.** `baseline --capture-floors
  O007|R008|R016 [--output FILE]` records what the rule finds today in the
  file the rule reads back, so a team does not have to write it by hand.
  The dead fact tables and the dead anchor calendars record only the models
  that have some; the account keys record every scanned model, an empty
  list included.
- **R016 reads a floor file.** The `floors` option holds the dead anchor
  calendars that are known: one that is listed is not a finding, one that
  now reaches something prints a tighten hint, and a configured file that
  does not exist is an error.
- **R008 fails a model with no floor entry.** Until the entry is recorded
  deliberately, the model is a finding and the message names what is
  flagged. The old option turns this off.
- **The tighten hints read as the reference reads them.** The dead fact
  tables print `[dead-fact-table floor] entries no longer dead — tighten
  the floor:` and the account keys print `FIXED since the floor was
  recorded (N): ...` and `KNOWN BACKLOG (ratcheted, not failing) - N
  table(s) awaiting an active <dimension> relationship: ...`.
- **A relative floor path is resolved against the configuration.** A
  `floors` or `baseline` path that is relative is read next to the
  configuration file that names it, not next to the working directory, so a
  run from anywhere finds the same file. BUGFIX.
- **`report complexity` reads like a report.** The banners, the statistics,
  the length distribution, the longest measures and the suggested
  thresholds are printed in the layout a reviewer reads, and the expression
  statistics follow. The report writes no file: the old version left a
  `measure_complexity.json` in the working directory on every run.
- **`report complexity --json` holds the reference keys.** `total_measures`,
  `statistics`, `top_10_complex` and `all_measures`, in that order, with
  the average lengths as plain floats. The extra blocks the tool used to
  add (buckets, thresholds, the flat copies of the expression block) are
  gone; the thresholds the text report prints are still there.
- **A measure is measured without the indentation of its first line.** The
  later lines keep theirs, so a multi-line measure is two characters
  shorter than the file suggests. BUGFIX.
- **`report nameof` groups the field-parameter tables in two families.**
  The x family (the `x-Selector` and `x-Plot Specific` tables) and the y
  family (the `y-Selector` and `y-Plot Specific` tables), each sorted by
  name, with the references each table holds and the broken ones. The
  validation block comes first, then the two families, then the summary.
- **`report nameof --json` holds the two families and the summary.** The
  keys are `x_selector`, `y_selector` and `summary`.
- **The NAMEOF reasons read as the reference reads them.** `Measure 'X' not
  found in any table`, `Ambiguous: measure 'X' exists in multiple tables:
  ['A', 'B']`, `Table 'T' not found`, `Column 'C' not found in table 'T'`,
  `'C' is a measure, not a column. Use NAMEOF([C]) instead` and `Invalid
  reference format`. The tool-only cases (a casing mismatch, an excluded
  table, an unparseable field-parameter row) keep their own text.
- **`report relationships` reads like a report.** The progress lines, the
  summary, the cardinality types, the bidirectional relationships, the
  orphan categories and the hub tables are printed in the layout a reviewer
  reads. The report writes no file.
- **The orphan categories are named after what they are.** The key is
  `report_tables`, not `parameter_tables`, and the JSON keeps the
  cardinalities and the hubs in the order the relationships file lists
  them. BUGFIX: a relationship block on the first line of the file is
  counted, as the file's own structure says it should be.
- **`comment-refs` is a gate.** With a floor file it compares the counts
  with the floors and fails when a model or a class rose above its floor:
  the risen model/class pairs, the offending lines, and the line that says
  to raise the floor by hand. Without a rise it prints the totals and, for
  every class below its floor, the pair to tighten. Without a floor file it
  keeps printing today's counts.
- **`comment-refs --list` lists the references.** One line per reference —
  `<file>:<line>  [<class>]  <line>` — then the number of references and
  the number of models. `--list` takes precedence over `--tighten`.
- **`comment-refs --tighten` says what it lowered.** A floor file that does
  not exist yet is seeded from the current scan; otherwise one line per
  lowered class, or `nothing to tighten`.
- **A floor key never borrows another model's floor.** A floor key matches
  a model only when it is that model's key, with or without the
  `.SemanticModel` suffix. A key whose last path segments equal the model
  key is used when exactly one key in the file says so; when several do,
  none is used, so a run on one client never passes on another's floor.
- **`comment-refs` reads the whole scan root.** Every `*.tmdl` under it
  counts, not only the model definition folders; a file outside a model
  belongs to the folder it sits in. In a git work tree only tracked files
  are read. The `tests/` folder is skipped, and a configured `exclude` list
  replaces that default as it does for every other scan. BUGFIX: an
  unclosed double quote no longer hides the comment behind it, and a file
  that cannot be decoded is read with replacement characters instead of
  being skipped. BUGFIX: a file with a byte-order mark keeps its `///`
  line a description.
- **`format-resolve` resolves every model under the path.** It used to
  answer for the first model it found; now it answers for each model under
  the path, in model-path order, one row for the measure-name path and one
  row for every axis the calculation group branches on. A model without the
  calculation group is skipped silently. Each row reads
  `  <model> axis=<axis> <format>`, the format quoted the Python way, with
  `  ->  <format>` and `   ⚠ CHANGES` appended under `--compare`. A row
  whose conditions could not be read is followed by
  `       unresolved: [...]` with the first two conditions named.
- **`format-resolve` reads a wider grammar.** A parenthesised condition,
  `FALSE()`, a `TRUE ()` selector, a lower-case `return`, a fenced
  definition and a `{...}` list inside a condition are now evaluated
  instead of reported as unknown. BUGFIX.
- **An unquoted table in `SELECTEDVALUE` means "nothing selected".** The
  condition is then readable (usually false) and the evaluation continues,
  so the format resolves instead of coming back unknown. BUGFIX.
- **The format resolver names every unreadable condition of a chain.** It
  recorded only the first; now each unreadable condition of an `&&` / `||`
  chain is named. A non-literal needle in `CONTAINSSTRING` and an unquoted
  table in `ISINSCOPE` give the unknown result without a note, and the
  note for a selector that is not `TRUE()` is exactly
  `SWITCH on a non-TRUE() selector`. BUGFIX.
- **S005 names the file and the axis it failed on.** The finding reads
  `<file> axis=<axis> renders '<name>' as <format> — <n> decimals`, so a
  reviewer sees which calculation group and which branch lost the
  decimals. One finding per failing axis, not one per model.

- **The cohort-calendar check reads the relationship sides.** A subject
  dimension is the many side of an active relationship whose one side is a
  cohort calendar and that is itself the one side of another active
  relationship; the subject facts are the many sides of those dimensions.
  The reverse edge a bidirectional relationship adds never makes a subject
  or a fact.
- **The anchor-calendar check records a floor.** The new option `floor`
  names a JSON file that holds the dead calendars each model already has;
  those do not fail, the ones that are new do. A calendar in the floor
  that reaches something now produces a tighten note.
- **The anchor-calendar check reads the template from any folder.** The
  `template` option may name a model folder anywhere on disk, absolute or
  relative to the configuration file; a folder that does not exist excludes
  nothing. `retained` may be a list that applies to every model or a
  mapping from a model key to the tables that model keeps unwired.
- **The account-key check reports one finding per model.** The new
  offenders are listed together, split into the ones that carry the key
  column but have no active join and the ones that do not carry the key
  column at all; the latter are called out as a template fact (a
  core-model defect) or as model-specific, depending on the new
  `template_facts` option (a list) or the new `template` option (a model
  folder whose facts are read with the shared table-role law). A model with
  a floor file but no entry of its own fails: the backlog has to be
  recorded deliberately. The key column is matched case-sensitively.
- **`check --capture-floor FILE` writes the ratchet floor** of the
  selected rules and prints what it captured; the file keeps the entries
  of the models it did not see.
- **The cohort-calendar check stays opt-in on "nothing checked".** The
  earlier gate failed a run in which no model had a cohort calendar with
  subject facts; here a single-model run without cohort calendars would
  fail for no reason, so the check is off by default. Set
  `require_cohort_calendars: true` to make a run that checked nothing an
  error.
- **The relationship rules speak the reference's language.** R001 names a
  missing endpoint ("From table not found: X (in relationship abcdef12...)")
  and prints the validation summary as a note; R002 says "Invalid from
  cardinality: X in abcdef12..." and prints the cardinality distribution;
  R004 prints the cross-filtering analysis; R005 prints the orphan analysis
  and exempts the tables that are expected to stand alone by name; R006
  reports one finding per table pair, naming every relationship in it;
  R007 says whether the relationship is active ("ACTIVE  <-- changing
  measure results NOW") and prints the run note; R010 says "Cycle
  detected: a -> b -> c -> a"; R011, R012 and R013 print their coverage,
  cardinality and completeness notes. STRICTER: R010 now reports a table
  joined to itself, and R011/R012 are errors (the reference fails on
  them).
- **R005 exempts the tables that stand alone by name.** A table whose name
  holds "Plot Specific", "Selector" or "Measure", or that starts with
  "z-", is expected to have no relationship; the rest are reported and
  listed. The rule never fails the run.
- **R009 runs by default.** A model without relationships.tmdl, or with a
  file that parses to zero relationships, is an error. A single-table model
  legitimately has none: switch the rule off with
  `rules: {R009: {enabled: false}}`. STRICTER: the rule was a warning and
  opt-in; the earlier gate failed the run.
- **R013 and R014 run by default.** They are advisory (info), so they never
  fail the run, and they print the completeness and the key-coverage
  analysis. STRICTER: both were opt-in; the earlier gate always printed
  them.
- **R011 checks a model that has no calendar table.** Coverage is then 0%
  and every fact is listed, instead of the model being skipped.
- **R012 compares the cardinalities exactly as written.** "Many" is not
  "many": a relationship that spells its cardinality with a capital letter
  is reported, as the reference reports it.
- **The R007 fixer keeps every other byte.** It removes the offending
  relationship block from its header line up to the next relationship
  declaration and leaves the rest of the file exactly as it was, blank
  lines included. STRICTER: R007 can never be baselined (zero tolerance).
- **A relationship declaration may be followed by any whitespace.** A tab
  after the keyword starts the block, as a space does.
- **`stats --measures** prints one summary per model.** A folder with two
- **The manifest names its target block `bigquery` and keeps its key
  order.** The block that describes the warehouse target is `bigquery`
  (the `block_key` setting still renames it) and its keys keep the order
  the contract reads them in: `model_project`, `model_dataset`,
  `model_billing_project`, `project`, `dataset`, `billing_project`, then
  `client_id`, `registry_project` and `registry_dataset` when a targets
  entry matched, then `warehouse` and `note`.
- **A table's `fqtn_default` lives in its `bq_source` object.** It is the
  last key there and every table that reads the warehouse carries one,
  whatever its classification: a `z-` selector that reads the warehouse
  is checked like any fact.
- **A table record lists its keys in one order.** `name`,
  `classification`, `column_count`, `domain` (for a fact, a dimension or
  a calendar), `bq_source`, `programmatic_renames`, `m_type_changes` (or
  `unresolved_source`), `columns`, `measures`. The domain rules ship with
  the tool: the shared tables are `Core / Shared`, and the first rule
  whose word appears in the table name wins.
- **A relationship record carries no `name`.** Its keys are `fromTable`,
  `fromColumn`, `toTable`, `toColumn`, `isActive`,
  `crossFilteringBehavior`, `fromCardinality` and `toCardinality`. A
  type step keeps the spaces it was written with.
- **The manifest reads the registry shape of the targets file.** A
  `clients:` mapping whose entries carry `bq_project`, `bq_billing_project`
  and `bq_dataset` is accepted next to the flat shape; a secondary model
  row overrides any of the three target fields, and an explicit null
  removes one. The billing project is the declared one when the key is
  there, else the project.
- **The manifest command prints the summary the pipelines read.** `Wrote
  <path>`, the model and the warehouse target it resolved to, the table
  and relationship counts, the classification map and the domains.
- **The best-practice analysis uses the original's catalogue and prints its
  reports.** The five rules carry their name, category, severity, scope and
  description, and a finding carries the original's message: `Measure
  '!Revenue' uses / operator instead of DIVIDE() function`, `Calculated
  column 'Band' in table 'Sales' may impact performance`, `User-facing
  measure '!Revenue' in table 'Coffee Measures' lacks description`. The
  command prints the analysis report, the results summary and the audit
  report, and the times are local and carry no offset. A column whose
  table name the service does not return is `Unknown`, not a table id.
  BUGFIX.
- **The best-practice analysis needs a healthy connection.** The client's
  health check now reports its three steps - sign in, read the dataset and
  run `EVALUATE { 1 }` - with the time each took, and the analysis fails
  when the check is not healthy: `health check unhealthy: <reason>`. The
  number of objects analysed is all or nothing: when a count query fails
  the number is zero and the gate fails. BUGFIX.
- **The live diagnostics print the original's blocks.** The calendar scan
  prints the full-scan block, the sample dates and the assessment (a
  calendar that holds one row is a critical finding); the identity check
  prints the RLS detection block; the filter comparison prints every table,
  the summary table with its columns and the closing lines; the metadata
  check prints the connection investigation; the filter diagnostic prints
  its four checks, the summary groups and the recommendations. A calendar
  count of zero is an error instead of a crash, and a finding that is an
  error alone no longer asks for action. BUGFIX.
- **The live row, measure, refresh and smoke checks print the original's
  lines.** A probed table prints `✅ PASS Table 'Sales' has data: Table
  'Sales' has 5,000 rows (12.34ms)` and a failed one `❌ FAIL ...`; the
  dimension check warns `⚠️  Warning: 1 dimension tables are empty:
  ['_Days']`; the refresh check prints the warning and the details and says
  `Refresh status check failed (non-blocking): ...`; the freshness check
  says `Data is 48.0 hours old (exceeds 24h threshold)`; the smoke suite
  prints its summary, the failed items and the total execution time, and
  fails with `Smoke test suite failed. Pass rate: 50.0% (expected >= 80%).
  5 tests failed.` The parameter audit prints the whole report, and only
  `LIMIT 1` itself is critical. BUGFIX.
- **Every live check prints its report block.** In text mode a check prints
  the block the original printed — the row-count pattern, the calendar
  validation, the dimension validation, the date range — before its result
  line, and the checks run in the original's order. The result line now
  carries the original's wording: `🔴 CRITICAL: All 5 tables have exactly 1
  row. ...`, `⚠️  WARNING: Calendar has only 50 rows (expected 365+). ...`,
  `⚠️  WARNING: 4/5 dimension tables have only 1 row. ...`. A query that
  answers with no rows reads as unknown, not as zero rows. BUGFIX.
- **The live coupling guard compares the dataset with the local model.** The
  original paired a client id with a workspace name and failed with two
  different texts; this tool has no client id, so it compares the dataset
  name with the model folder and says what does not match. The check is
  stricter: a dataset that is not the local model is refused, which the
  original's pairing could not see. STRICTER.
- **`stats --measures` prints one summary per model.** A folder with two
  models prints two summaries, each with its own totals, in the layout a
  reviewer reads: the totals, the user-facing and helper split, the
  field-parameter surfacing, the helper subcategories, the top tables and
  the dash-helper description block. A sum across models would hide which
  model is the problem.
- **The category-mechanism exemption reads the numbered x-axis tables.**
  By default it reads its axis rows only from `x-Selector 1` to
  `x-Selector 9`; a plot-specific table is added only by configuration.
  A fact whose only surfacing row lives in a plot-specific table therefore
  stays uncovered.
- **The filter-coverage check prints the fact-table completeness.** Beside
  the uncovered findings, it reports per model how many fact tables there
  are, how many are consumed by a user-facing measure, how many are
  reachable through a filter measure, how many are uncovered and how many
  are unused — and the lists that say which fact is which. An exempt fact
  and an unused fact never fail; they are reported so that a reader can
  see why nothing was said about them.
- **The mapping table's rows are read the way the source tool reads them.**
  Only a row with three or more values attributes a category: the category
  is the first value, the group id the third. A two-column table therefore
  attributes nothing, and a null cell counts as empty (it is no longer the
  text `None`).
- **The category attribution reads the numbered x-axis tables only.** By
  default it reads its axis rows from `x-Selector 1` to `x-Selector 9`; a
  plot-specific table is added only by configuration.
- **An axis row must have the source tool's shape to attribute.** A row is
  `("label", NAMEOF('Table'[Measure]) or NAMEOF([Measure]), <order>,
  "group")`: the label may not be empty, the order is a whole number, and
  a row may span several lines. A row behind a `//` or `--` marker is not
  a row.
- **The measure trace follows every bracketed reference.** A reference is
  the text between the brackets, trimmed of surrounding spaces, and it may
  not span a line break. When two measures share a name, the later one in
  model order is the one traced.
- **The mapping fixer writes the payload in the layout the table stores.**
  The rows are serialized with a comma and a space between items, a colon
  and a space between keys, and every non-ASCII character escaped as
  `\uXXXX`; only the first payload in the file is replaced.
- **The account-key finding reads the way the source tool reads it.** A
  category that misses an account group is reported as
  `[<Category>] missing ['<Key>'] Each must assign both Account_y and
  Service_y.`, and a category whose backing facts cannot carry the key is
  reported as `[<Category>] account-UNSUPPORTED — backing fact table(s)
  lack 'account_x_id': ['<Fact>']` (or `account-filterable, but these
  backing fact tables still lack ...`). The key column is matched by its
  exact name, so a fact that spells it differently does not carry it. A
  warning is never tagged auto-fixable.
- **A mapping table whose payload cannot be read is an error.** A table
  with no `Binary.FromText(...)` payload is reported as `No binary data
  found in <file path>`, a payload that does not decode as `mapping
  payload does not decode: <reason>`, and the fixer writes nothing there.
- **The gate-coverage rule reports one finding per check, worded as the
  source tool words it.** A check that fires once says so once, and the
  message names the model, the list it holds and the repair to run. The
  gate patterns are strict again: `CONTAINSSTRING(all_cats, "<literal>")`
  and `IF([f-X] > 0` are spelled the way the source tool spells them, and
  the two chains are looked for in the whole `f-Filters` table file.
- **A check that cannot run is listed as skipped, with the reason.** A
  model without an `f-Filters` table, an `f-All` that is absent or
  non-canonical (no `temp_basic`/`temp_alt`), and a mapping table that
  yields no category are each reported under `skipped` (with the model
  and the reason) instead of passing silently. A mapping table with no
  categories skips the four checks that need them, so no literal is
  reported inert and no baseline entry is reported stale.
- **The mapping-table checks read the way the source tool reads them.** A
  missing table is reported as `P1 WARNING: <table> table not found`, a
  table that lacks a required column as `Z-Map Table Structure: table
  found: <name>; total columns: <n>; required columns present: <k>/<m>;
  present required columns: <list>; missing required columns: <list>.
  These columns are critical for dimension-measure grouping`, and the
  inventory reports `Unique x-Selector categories found: <n>` with the
  group ids and `Relationships involving z-Map: <n>`. BUGFIX: A001 is a P1
  check, so it is a warning (the spec says warning) and `--strict`, the
  full run, fails it.
- **The filter-measure rule reports the inventory of the filter
  measures.** Per model it reports `F-Measure Pattern Classification:
  Total f-measures: <n>` with a line per kind (STANDARD, AGGREGATOR,
  SWITCH-ROUTER, DISPLAY-STRING, EXEMPTED, UNCLASSIFIED), and `F-Measure
  Coverage Analytics: Total f- measures: <n>; In f-Filters table: <a>
  (<pct>%); In other tables: <b>; Visible: <v> (<pct>%); Hidden: <h>`,
  with the filter measures that live elsewhere and the recommendation to
  move them. A model with no filter measures reports the counts and no
  percentages.
- **The priority of the analysis-category checks is written down.** A P0
  check (an unpaired gate chain, a gate that names a measure the model
  does not declare, a gate literal that matches no category) is an error;
  a P1 check (a category that owns a filter measure but is not gated, a
  category with no filter measure to gate on, a gate literal that spans
  two categories, a mapping table without its key columns, a filter
  measure that fits no known shape) is a warning. A plain run fails on the
  P0 checks, `--strict` is the full run and fails on the P1 checks too.
  The mapping is in the rule descriptions and in the README.

- **The schema check names its drift the way the contract names it.** The
  keys are `missing_in_bq` (the failure), `needs_review`,
  `not_surfaced_in_pbi` (the information), `ignored_bookkeeping` and
  `type_mismatch`, in that order. A column the warehouse does not import
  is listed with the snapshot's own spelling, and a type difference says
  whether an M Changed Type confirms it.
- **The schema check writes its result into the manifest.** Each table's
  source object carries `checked_against`, the snapshot's `bq_columns` and
  its `drift`; a table the snapshot does not hold carries a `check_error`
  instead. The run summary is the `bq_schema_check` block: the project,
  the dataset, the warehouse, the authentication, the unresolved and the
  skipped tables, the time of the check and the table counts.
- **The schema check prints the report the contract describes.** The
  authentication, the tables checked, the failing, needs-review,
  informational and type-mismatch counts, the ignored bookkeeping
  columns, the unreachable and the unresolved tables, the tables that were
  skipped, and — when anything failed — the read-only routing block.
- **`schema-check` can be pointed at another project or dataset.**
  `--project` and `--dataset` replace the target the manifest declares,
  in the recorded `checked_against` and in the summary.

- **`schema-check --sql-dir` reads the registry shape of the entries
  file.** An entry may name its view `client_view` and its universal
  source `universal_view`, and a column may be an object with a
  `sourceColumn`; the flat spelling is accepted as well. A missing
  entries file is an empty registry: nothing to hold, exit 0.
- **`schema-check --sql-dir` prints the state it checked.** The first
  line names the SQL project and the commit it is at, then every entry
  in the order the registry lists it, with the file that proves it and
  the reason, and the clients that are ready to deploy and the ones
  that are held.
- **The holdbacks file is built from the whole registry.** It lists every
  client in the entries file, with the work that holds its deploy, and a
  client that is ready is still outstanding work until `--clear-ready`
  removes it.
- **`schema-check --sql-dir --clear-ready` clears the registry.** The
  entries of a client whose every entry is READY are removed and the
  file is rewritten; the run says how many entries went and that the
  registry is a committed receipt.

- **The reference census prints the report the contract describes.** The
  live and the non-live counts, per layer, the number of files, the live
  blast radius and the warning that report bindings are not covered by a
  model-side test. With `--files` the matching files are listed, sorted by
  how often they name the object, with the non-live ones hidden unless
  they are asked for.
- **A quoted reference may carry any dotted prefix.** `"a.b.Margin"` and
  `".Margin"` count for `Margin`, the way a report binding writes it.
- **A targets file defines the live set of the census.** The live set is
  the first path segment of every registered model path; without a
  targets file the archived-folder globs decide. `--include-nonlive`
  shows the non-live files (`--include-history` still works).
- **The census lists the files relative to the folder it scanned**, so
  the same tree gives the same report wherever it is checked out.

### Bug fixes

- **An inline-row table is recognised only in the case M spells it.** M is
  case-sensitive, so a source that says `table.fromrows(` calls a
  different function and does not author the table's rows. The tool
  ignored the case before, so such a table was no longer a fact and the
  dead-fact gate could not report it. BUGFIX: the tool now matches the
  case the reference matched.
- **A measure whose name only mentions "helper" is a diagnostic, not a
  helper.** The tool tagged every name that contains "helper" as a helper
  before, so the advisory line of a measure on a fact said the wrong
  thing. The reference tags a name that starts with `-` as a helper and a
  name that contains "helper" as a diagnostic; the tool now does the
  same. BUGFIX.
- **The dead-fact gate reports the whole floor, not one table at a time.**
  A floor entry that is no longer dead now produces one tighten block that
  covers every such entry, including the ones of a model that was not
  scanned or does not exist any more. A new dead fact table beyond the
  floor produces a summary that names every one of them.

- **A numeric floor in a guarded ratio is found whatever the spacing.** The
  floor of a guarded ratio is a closing `]` followed by `<` and digits; the
  gap between them may be any amount of whitespace, so `[Leads #]  <  5`
  hides a floor no more than `[Leads #]<5` does. BUGFIX.
- **The re-check gate of the policy exception matches the whole variable
  name.** `notrecheck = 1` is not the re-check the rule asks for; the name
  must stand as a word on both sides. BUGFIX.
- **The reach guards find their own helpers.** Beside the configured helper
  names, every measure of the host table whose name starts with
  `-helper Filter Misses ` or `-helper Slicer Cannot Reach ` is collected and
  checked like the configured ones (the prefixes are an option,
  `helper_prefixes`). A helper nobody listed is exactly the one that drifts
  silently. BUGFIX.
- **The edge floor counts edges, not relationships.** Two active
  relationships between the same two tables are one edge, so they count
  once against `min_active_edges`. The self-test that asks whether some
  active relationship touches the fact now runs for every reach guard, not
  only for the ones with a floor. BUGFIX.
- **A model without a relationships file skips the axis contract.** The
  contracted edges are not reported as missing; the run notes the skip.
  BUGFIX.
- **The below-grain check says when it skips.** A model without the
  configured host table skips the check, and the run names the skipped
  check. BUGFIX.
- **A registered column needs an ordinal.** A row that registers a column
  but carries no ordinal is reported: the contract cannot check it against
  the group's free range, and a silent pass reads as permission. BUGFIX.
- **A group row is a live line that carries an ordinal.** The rows of a
  group are the live lines that name the group and carry an ordinal, and a
  row's label is the quoted text right after the opening parenthesis at the
  start of the line, not a quoted string further down. BUGFIX.
- **A reference contract can check its own universe.** A contract that names
  a template model or a minimum universe counts the models that declare its
  anchor: fewer than the minimum, or the template missing, is reported as
  broken discovery, the way the arm-scoped filter already does. BUGFIX.
- **A flag predicate is recognised whatever the spacing.** Any amount of
  whitespace (spaces or tabs) between the column name and `]`, between `]`
  and the operator and between the operator and the literal is free, and the
  predicate counts toward `min_predicates`. BUGFIX.
- **A canary literal matches a model that writes the function form.** The
  literal of a found predicate is compared with the canary after a trailing
  `()` is dropped, so `= TRUE()` satisfies the canary `= TRUE` (the literal
  itself stays case-sensitive). BUGFIX.
- **A guarded ratio is recognised whatever the spacing in its brackets.**
  `DIVIDE ( [ Cost ] , [Accounts #] )` is the same ratio as
  `DIVIDE([Cost],[Accounts #])`, so it is wrapped like the other ones.
  BUGFIX.
- **A mention outside every arm says so.** The finding names the arm
  `outside any arm` instead of `none`. BUGFIX.
- **The Daily calculation item is read as a whole block.** The check looks
  for the required tokens in the item's source, from its
  `calculationItem Daily` line to the next calculation item or the end of
  the file, so a property line of the item counts too. BUGFIX.
- **The contract findings carry the counts, the names and the guard.** A
  missing-column finding says how many columns of the table are
  axis-selectable but absent from the guard and names them all, and a
  blocked-conformed-column finding names the guard too. One finding per
  object, as before; the facts a reader needs to act on it are the same.
  BUGFIX.
- **A commented-out expression is not live DAX.** The reference contracts
  read the raw text of a measure, so a `-- DIVIDE([Cost], ...)` line in a
  comment was reported as a live raw-cost ratio. The tool skips comment
  lines: a commented-out expression is not executed, so it is not a
  defect. BUGFIX.

- **An apostrophe or a parenthesis inside a bracketed name belongs to the
  name.** `SUM([Customer's Count])` and `SUM([Cost (USD])` are legal DAX:
  the checker reads the whole bracketed name as one region and reports
  nothing. The reference read the characters inside the brackets as code
  and reported three unclosed delimiters for the first name. BUGFIX.
- **A delimiter of one kind inside another is reported.** `{(})` reports
  the closing brace and the opening brace. The reference paired every kind
  separately and reported nothing. STRICTER.
- **An unterminated block comment is ordinary text.** `/* unterminated (`
  no longer hides the rest of the expression: the delimiters after it are
  checked, so a broken comment surfaces instead of passing unnoticed.
  BUGFIX.
- **An escaped quote inside a string is blanked as two spaces.** The
  contents of a string literal are blanked and the length of the text
  never changes; only the two quotes of the literal itself survive.
  BUGFIX.
- **A clean share of exactly 90% is not below the threshold.** Nine clean
  expressions out of ten meet the 90% threshold: the share is compared as
  a share, not as a floating-point percentage, so the boundary is not a
  coin toss. BUGFIX.
- **A model with no measures is an error, not a warning.** The parse
  check failed on a model without measures, whether or not the model had
  tables; the tool now says `<model>: no measures found (suspicious)` and
  fails. STRICTER.
- **A `--` line is a DAX comment.** A comparison written on a `--` line is
  commented out, so the cross-fact key check does not report it. The
  reference removed only `//` and `/* */` comments and reported the
  comparison anyway. BUGFIX.
- **A repaired file keeps its own line endings.** The reference rewrote
  every file it touched with LF endings, so a CRLF file became LF
  throughout and every line of a Windows checkout showed up as a change.
  The tool writes the file in the style it already has: a CRLF file loses
  exactly the line that was removed and stays CRLF. BUGFIX.
- **An axis table that no measure reads is not a failure.** A model whose
  `y-Selector` tables no measure references used to fail the
  reference-integrity check with a division by zero; it now passes, because
  there is no reference to check. BUGFIX.
- **The axis tables are reference-checked in full.** Every expression of an
  axis table is checked, not only the measures: a calculated column or a
  partition source that names a table that does not exist is reported as
  well. BUGFIX.
- **A permission line is read even when the line before it is a bare
  permission.** The original never examined a `tablePermission` line that
  followed a bare `tablePermission <T>` line, so its `USERNAME()` or
  `IN VALUES` problem went unreported; and it read
  `tablePermission T=<expr>` (no spaces) as a bare permission on a table
  named `T=<expr>`. BUGFIX: both are read as written.
- **The refresh repair replaces only the loader call.** The windowed query
  takes the place of the loader call itself, so the rest of the partition's
  M source (the surrounding `let ... in ...`, the other steps, the
  indentation, the line breaks) stands, and the policy's `sourceExpression`
  is the new partition body, line for line.
  BUGFIX: the repair used to replace the whole source body with the
  template, which dropped every other step of the M query.
- **The refresh repair says what it did.** It prints the tables it
  repaired, the tables it could not repair and why, the tables that owe a
  manual XMLA full refresh because their partition source changed, and the
  tables it only reinstated a policy over (no refresh owed).
- **A refresh table the repair cannot write is reported, not skipped.** A
  loader table with no `inline_template` configured, a source that is
  deliberately unfiltered or has no date column, and a source whose loader
  call cannot be parsed are listed under the failed repairs, and the
  coverage finding for them is not marked auto-fixable.
- **A blanket `fix --check` does not count the unsafe refresh fixer.** The
  repair changes what a partition stores, so a blanket fix does not run
  it; the check now counts what the selected fixers would act on and lists
  the same rules, so `fix --check` without `--select` neither lists nor
  counts P001, and `fix --check --select P001` does.
- **The written refresh policy closes its fence with four tabs.** The
  partition's own fence may sit at any indentation; the fence the repair
  writes is always four tabs and three backticks.
- **The refresh repair prunes the backlog it fixed.** The repaired entries
  are removed from that model's backlog in the configuration file, line by
  line, so every other line of the file stays byte-identical, and the run
  says how many entries it pruned. `--no-prune` keeps them.
- **A star select is a star select.** `select distinct *` is not one, and
  a `source()` or `ref()` outside the jinja braces does not count as a
  relation the view reads. BUGFIX.
- **A client the owner pattern does not match is held.** It was looked up
  in a folder named after the whole client key, so the view was never
  found and the reason was misleading; the client is now held with the
  reason that its folder could not be derived. BUGFIX.
- **The schema check never talks to a warehouse.** The live schema
  lookup, the credential setup message, `--env-file` and `--key-file`
  stay out: the tool reads a snapshot the user exported. BUGFIX.
- **The read-only routing block names the issue to open.** It said which
  private repository and which person owned the warehouse side; it now
  says to open an issue with the warehouse owners, which is the part a
  reader can act on. BUGFIX.
- **The manifest names the tool that wrote it.** `generated_by` says
  `tmdl-preflight manifest`; naming a script the tool does not ship is
  meaningless to whoever reads the file. BUGFIX.
- **The manifest is written with unix line endings.** The original wrote
  in text mode, so a Windows run produced CRLF endings; the file is
  written with LF everywhere, and the `--check` comparison normalises
  line endings so a copy with CRLF endings is not stale. BUGFIX.
- **The manifest command keeps the tool's usage-error exit code.** A
  model that is neither a registry client id nor a model directory, and a
  registry entry without a model path, exit 2 — the tool-wide usage-error
  code — with the wording the contract uses. BUGFIX.
- **The unregistered-model warning appears only when a targets file is in
  use.** With no registry file there is nothing to be missing from, so
  the warning is noise. BUGFIX.
- **The manifest reads a pair list and a property line leniently.** A
  rename or type pair may carry spaces around the braces, a column
  property is read from any line that starts with two tabs, and a file
  with a byte-order mark is read as UTF-8. BUGFIX.
- **The `manifest` section of the configuration file is read again.** The
  section was listed in the documentation, but the configuration
  validator rejected it as an unknown key, so `sources`, `target` and
  `domains` never reached the command. BUGFIX.
- **The live client sends the query and nothing else.** The executeQueries
  body carried a `serializerSettings` block that the service does not need;
  it is gone, so a null column no longer arrives as a key. A failed query is
  retried three times with two waits of two seconds and no wait after the
  last attempt (before: two, four and eight seconds, the last one after the
  third attempt had already failed). A token that comes back without
  `expires_in` lasts 3599 seconds, and a sign-in that comes back without a
  token says `Authentication failed: <reason>`. BUGFIX.
- **The live usage error names the credentials that are missing.** It said
  only that no credentials were set; it now starts with `Missing required
  environment variables: <names>.` The names `FABRIC_TENANT_ID`,
  `FABRIC_CLIENT_ID`, `FABRIC_CLIENT_SECRET`, `FABRIC_WORKSPACE_ID` and
  `FABRIC_MODEL_ID` are read as fallbacks for the `PBI_*` variables and for
  `--workspace` and `--dataset`; no `.env` file is loaded. BUGFIX.
- **The live command finds a table's columns and measures at any
  indentation.** A column line indented with two tabs was not seen, so the
  table was never probed; a measure line is now only a measure when it
  carries the `=`. A name that holds a doubled quote is still decoded
  (`It''s` is `It's`) and a `]` inside a measure reference is still
  doubled. A parameter is read at any indentation too, and its value ends
  at the first `meta` or at the end of the line. BUGFIX.
- **A fact is matched only when the reference names it.** The reference
  counted a fact `Sales` as read whenever the text `Sales[` appeared, even
  inside `MySales[`. The tool requires a non-word character before the
  name, so a measure reading `MySales[amount]` does not consume `Sales`.
  BUGFIX.
- **A fact is matched by plain text, as the source tool matches it.** A
  fact counts as read when the expression holds `'Fact'`, `[Fact]` or
  `Fact[`, anywhere in the text. The earlier word-boundary rule was
  stricter than the source tool, so the two could disagree about which
  facts a measure reads.
- **The filter-coverage finding names the command that writes the missing
  filter measure.** The repair lives in pbip-model-forge, not here, so the
  finding names the exact `pbip-forge f-filters --model <model>` command
  for the model at hand instead of pointing at the tool in general. The
  split is deliberate: the check reports, the other tool writes.
- **A qualified measure reference is an edge in the fact trace.** A
  reference of the form `'Table'[Name]` or `Table[Name]`, where `Name` is a
  measure the model declares, is followed like a bare `[Name]`. The
  qualifier says which table owns the measure; it does not change what the
  reference means. Without this, a filter measure that reached a fact
  through a qualified reference was not counted as coverage, and the
  filter-coverage rule reported a false error.
- **A single-model lineage fix clears Desktop's cache by default.** The
  cache (`.pbi/cache.abf`) is what makes Power BI Desktop reuse the old
  lineage tags, so a run that changed a tag now deletes it and says
  `🗑️  Deleted cache file: <path>`. A whole-repository run never deletes
  a cache; it says that it exists. `--keep-cache` opts out on a
  single-model run, and `--clear-cache` forces the deletion.
- **Every line that starts with four spaces is an M017 error, expression
  bodies included.** The rule's `strict` option (on by default) exempts
  expression bodies; the default now flags them too, and the message is
  `Line <N>: Uses spaces instead of tabs for indentation`. A line that
  starts with tabs and then has spaces is still never flagged. The bare
  quoted multi-line measure note is always computed, as a non-failing info
  note.
- **M018 reports one finding per duplicated annotation name.** A name used
  three times yielded two findings that each said "appears twice". There is
  now one finding per name, saying how many times it occurs and listing
  every line. STRICTER: the annotations are scoped by declaration, so the
  same name in two scopes is not a duplicate.
- **Archived copies are skipped by default.** With no `exclude` list
  configured, every file whose path relative to the scan root has a folder
  segment that holds `legacy`, `_backup` or `_b2` is skipped. A configured
  `exclude` list replaces the default; an empty list turns it off.
- **A file that mixes its line endings is never rewritten.** A fleet
  committed from Windows and then touched by a tool that writes LF ends up
  with a file that mixes CRLF and LF. Such a file cannot be split on one
  style and joined on another: the lines that use the other style fold into
  one, and the edit computed on that deleted the model — a three-measure
  table went from 28 lines to 3. Such a file is now left exactly as it is,
  and the violation stays on the report.
- A file whose lines end with a lone CR (no LF) is read line by line like
  any other file. Before, it was read as one line, so the check reported a
  different set of findings than the same model with LF.
- A manifest or a schema snapshot that is valid JSON but not an object, and
  a field-parameter table that is not UTF-8, are configuration errors:
  exit 2, a message on standard error, and never a Python traceback.
- A lineage tag followed by a tab or several spaces after `lineageTag:` is
  rewritten like any other (before, only one space was handled).
- **The field-parameter fixers keep the file's byte-order mark and its line
  endings.** The original scripts rewrote every file they touched with the
  platform's own line ending and dropped a byte-order mark, so a CRLF file
  checked out on a Mac came back with LF. BUGFIX.
- **The `fix` command always re-checks, and a finding that survives fails
  the run.** The original's comma, separator and duplicate fixers always
  exited 0 after `--fix`; the tool exits 1 when a selected error is still
  there. STRICTER.
- **Removing a date row from the second plot-specific table takes the
  separator with it.** The original left the previous row's comma behind,
  so the constructor ended with `,` before `}` - a defect of its own. BUGFIX.
- **A row copied into another table is followed by a separator repair.** The
  original copied the row's text verbatim and stopped there: appending a row
  that carried a comma left a trailing comma before `}`, and a promoted row
  left the previous last row without its separator. The tool repairs both.
  BUGFIX.
- **A duplicate row that sits behind a comment marker is never removed.** The
  original searched for the survivor's text and found the commented-out copy
  first, so it emptied the parked row and reported the live copy again. The
  tool skips a copy that sits after a `--` or `//` on its line. BUGFIX.
- Three or more copies of a tag in one file: the later copies are
  rewritten, the first is kept.
- The `fact-table-filter-coverage` rule now exempts a fact the way the
  forge's gap-fill planner does: a user-facing measure on an x row with a
  mapped group that reads the fact directly (a data read, not only inside
  a sensor) means the fact is already gated, so no `f-` measure is owed.
  A helper measure on an x row never exempts a fact: it is the model's own
  business. Before, the exemption needed the x-row measure to be one of
  the fact's consumers, so the two tools could disagree about the same
  model.

### Test expectations and why

Tests whose expectation follows a deliberate choice are listed with the
reason (BUGFIX: earlier behaviour was a bug; STRICTER: the stricter of test
and rule wins; DESKTOP: Power BI Desktop evidence).

- DESKTOP: `test_lineage_tag_uniqueness::test_lineage_tag_format_validity[placeholder-fail]`
  expects M004 as a warning (an error was expected before).
- STRICTER: `test_tmdl_parser_explore::test_ec020_column_and_measure_share_a_name_target`
  accepts any severity; M012 already reports a measure named like a column
  of its own table as an error.
- Test convention: `test_p0_tmdl_guardian` turns on M016's opt-in
  `check_line_endings` (off by default because Windows checkouts are often
  CRLF) to pin the line-ending verdicts.
- BUGFIX: `test_naming_conventions::TestHelperMeasuresFollowConventions`
  counts 2 described dash helpers where earlier versions printed 1 (its index
  dropped the description of a measure that directly follows another).
- STRICTER (project decision): `test_dax_table_references::test_dax_references_resolve[reference_casing-*]`
  now fail: `sales[Amount]` against table `Sales` resolves in DAX, but casing
  mismatches are D004 errors (the earlier verdict was pass).
- STRICTER: `test_dax_parsable::test_dax_comprehensive_syntax_check[one_unmatched_paren]`
  asserts the D001 error even though the clean share (90.9%) meets the
  threshold (earlier versions passed).
- Existing test updated: `test_dax_parsable::test_dax_balanced_brackets` and
  `::test_dax_comprehensive_syntax_check` find the measure and
  calculated-column findings in the message; the object label is now
  `Table[Object]`, with no kind in brackets.
- Existing test updated: `test_dax_spec_cases::test_measureless_model_fails`
  (was `test_measureless_model_warns`) expects the reference's error text.
- Existing test updated: `test_dax::TestBalancedDelimiters::test_unterminated_string`
  expects the quote wording (`Unmatched opening double quote at position 11`).
- Existing test updated: `test_output::test_text_prints_scanned_summary`
  looks for the scanned line in the output; the D001 summary note is
  printed with the other notes, before the final count.
- Existing test updated: `test_rules_dax::test_case_mismatch_resolves_but_is_an_error`
  (was `test_case_insensitive_resolution`) expects three casing errors.
- Existing test updated: `test_rules_dax::test_missing_table_is_error` expects
  the finding text `measure Sales Measures[Revenue] -> missing 'Orders'`.
- Existing test updated: `test_rules_dax::test_ambiguous_measure_is_warning`
  expects `Ambiguous: measure 'Units Sold' exists in multiple tables:`.
- Existing test updated: `test_dax_spec_cases::test_qualified_measure_in_a_measure_is_a_warning`
  expects `'Units' is a measure, not a column. Use NAMEOF([Units]) instead`.
- Existing test updated: `test_calc_group_table_dax::test_calc_group_and_calc_table_dax_blocks_found`
  expects the D010 finding as an error (it was a warning).
- STRICTER (project decision): `test_relationships::test_relationship_endpoints_exist[rel_casing-fail]`
  expects the casing mismatch as an error that fails without `--strict`
  (a warning was expected before).
- Test convention: R001's success rate is a note, not a finding (the
  tests count exactly one R001 finding per broken endpoint).
- Test convention: R010 does not report a two-table loop (a reverse pair is
  R006's); the cycle test expects no finding for it.
- STRICTER: `test_reference_integrity_xselector` and `_yselector`
  `::test_case_only_mismatch_is_a_casing_error` expect a D004 casing error
  (the reference resolves in Power BI, but casing mismatches are errors).
- STRICTER: `test_reference_integrity_xselector::test_calculated_column_with_empty_expression_fails`:
  `column X =` followed directly by a property line is a calculated column
  with an empty expression (M020).
- BUGFIX: `test_connection_parameters::test_generate_connection_parameter_audit_report[limit-100]`:
  only `LIMIT 1` itself is CRITICAL; `LIMIT 10` and `LIMIT 100` are warnings.
- BUGFIX: `test_fabric_bpa_validation::TestBPACatalogue` expects the rule
  catalogue in the original's order and the findings with the original's
  messages; `test_data_quality_smoke_tests::test_refresh_status` expects
  the detail keys `end_time` and `request_id` (the original's names).
- BUGFIX: `test_fabric_bpa_validation::TestBPAPerformanceRules::test_calculated_columns_detected`:
  calculated columns are found by the integer column type (the text
  comparison found none).
- Test convention: `test_policy_defaults::test_dax_success_rate_threshold_never_suppresses_per_expression_errors`
  sets `min_success_rate` to 0.8: the example model has 7 expressions, so
  one unbalanced expression is 85.7%.
- Test convention: `test_fixers_config_contract` lists the unsafe fixers by
  their rule names: refresh-policy-repair, dax-reference-resolution and
  autodetected-relationships.
- STRICTER: `test_rls::test_mapping_table_is_hidden` judges the table's own
  `isHidden`; a hidden column no longer makes a visible mapping table pass.
- BUGFIX: `test_integration_f_categories::test_f_measure_coverage_analytics_zero_f_measures`:
  a model with no f- measures reports nothing instead of dividing by zero.
- Existing tests updated: `test_rules_relationships` expects R007 as an
  error and an R001 casing error for `sales.STORE_ID`.
- Existing tests updated for the severity changes above: M011 is an error
  and its fixer targets the first property slot; M013 at end of file is an
  error and keeps blank lines before the run; the M002 fence message
  changed; `rules --json` no longer pins the rule count.

## 1.1.0 (2026-10-12)

### Highlights

- **16 new rules** (37 in total) covering defects that stop Power BI from
  opening, deploying or evaluating a model: TMDL properties leaked into
  expressions, dangling `///` descriptions, duplicate object names, DAX
  references to tables and columns that no longer exist, duplicate
  variables, ambiguous active relationships, missing and trailing commas in
  field-parameter rows, bookmark option keys outside the schema, and broken
  report definitions.
- **5 new auto-fixers** (10 in total): M011, M013, F002, F003, B003.
- **Project configuration**: `[tool.tmdl-preflight]` in `pyproject.toml`,
  `.tmdl-preflight.toml` (Python 3.11+) or `.tmdl-preflight.json` (any
  supported Python), with `select`, `ignore`, `strict`,
  `severity_overrides`, `exclude`, per-rule options, `profiles` (`--profile`)
  and `--config PATH`. Unknown keys and rule ids are errors.
- **Exemptions** with a mandatory `reason` and an optional `until` date;
  once the date passes, the violation is reported again.
- **Baselines**: `tmdl-preflight baseline <path>` records today's violations;
  `check --baseline FILE` fails only on new ones and reports fixed and stale
  entries; `baseline --update` only shrinks the file unless `--accept-new` is
  given.
- **Output formats**: `--format text|json|github|sarif|markdown` (`--json`
  stays as an alias). SARIF 2.1.0 output plugs into GitHub code scanning.
- **`tmdl-preflight stats <path>`**: an inventory of the project, counts only.
- **CI integration**: a `.pre-commit-hooks.yaml` and an example GitHub
  Actions workflow under `examples/ci/`.

### New rules

| ID | Name | Severity | Auto-fix |
|---|---|---|---|
| M010 | metadata-in-expression | error | no |
| M011 | property-after-child-block | warning | yes |
| M012 | duplicate-object-names | error | no |
| M013 | dangling-description | error (warning at end of file) | yes |
| M014 | calc-group-implicit-measures | error | no |
| M015 | ref-table-target-missing | error | no |
| D004 | dax-reference-resolution | error (warning for an unresolved bare `[X]`) | no |
| D005 | duplicate-var-in-scope | error | no |
| R006 | ambiguous-active-pair | error | no |
| R007 | autodetected-relationships | warning | no |
| F002 | fieldparam-missing-separator | error | yes |
| F003 | fieldparam-trailing-comma | error | yes |
| F004 | fieldparam-ragged-rows | warning | no |
| B003 | bookmark-options-schema | error | yes |
| B004 | report-definition-integrity | error | no |
| S002 | measure-descriptions | info | no |

M003, M006, M007, M010, M015 and R006 are marked `baselinable = False`: they
stop a model from opening or deploying, so a baseline can never hide them.

### Parser robustness

- Files are read as `utf-8-sig`, so a byte-order mark no longer hides the
  first declaration of a file.
- An unreadable `relationships.tmdl` is reported by M002 instead of
  crashing the run.
- Duplicate declarations are kept (lists alongside the name-keyed dicts,
  first declaration wins) instead of the last one silently overwriting the
  first; tables, columns and measures also have case-insensitive lookups.
- Relationships with a missing endpoint are kept and reported by R001
  instead of being dropped.
- A raw count of `column`/`measure`/`relationship` declaration lines is
  compared with what was parsed; a difference is reported by M002 ("parser
  dropped N object(s)"), typically a mis-indented declaration.
- The parser now reads `///` descriptions, `displayFolder`,
  `expressions.tmdl` (names and `meta` records), `refreshPolicy` placement,
  and `discourageImplicitMeasures` / `ref table` lines from `model.tmdl`.
- A measure-level `formatStringDefinition` is attributed to its measure.
- DAX lexer: `''` inside quoted table names, `]]` inside brackets and `--`
  inside brackets are covered by tests.

### Fixes

- **Fixers no longer rewrite line endings.** The M003, M004, M006 and F001
  fixers read files with universal newlines and wrote them back with LF, so
  on a CRLF checkout a one-line repair showed up as a whole-file diff. Every
  fixer now preserves the file's newline style and byte-order mark.
- **B001 is surgical.** It used to re-serialize the whole bookmark JSON; it
  now edits only the offending values in the text and proves the edit by
  parsing both versions (refusing to write otherwise). All fixers share the
  new `verified_write` helper.
- **S001** exempts only the measure that carries a `formatStringDefinition`.
  A model is exempt as a whole only when calculation-group items define
  format strings. Previously any format-string definition exempted the whole
  model.
- **D003** compares measure names case-insensitively, as the engine does,
  and leaves duplicates inside one table to M012.
- **D002 and R001** resolve table, column and measure names
  case-insensitively.
- Properties are attached by indentation to the object they belong to, so
  a hierarchy's or annotation's lines no longer overwrite properties of the
  column declared before them.

### Compatibility

- The CLI invocation (`tmdl-preflight check <path>`) and the exit codes
  (`0` clean, `1` violations, `2` usage or path error) are unchanged. Exit
  code `2` now also covers configuration and baseline errors. BUGFIX: a
  single-rule run exits `1` when the rule found something, where the
  reference exited with the number of offending files. The tool's contract
  is `0` clean, `1` violations, `2` a problem with the invocation, and a
  caller can read the count from the report.
- JSON output is additive only: `summary` gains `excluded`, `exempted` and
  `baselined`; the payload gains `scanned`, and `exemptions` / `baseline`
  when they apply; each violation gains `path` (project-relative). Existing
  fields are unchanged. `rules --json` gains `baselinable` and `options`.
- The text report prints a `scanned:` line just before the final
  `tmdl-preflight:` summary line, which is still the last line.
- The new error-level rules only fire on defects that stop a model from
  opening, deploying or evaluating. Rules that can fire on clean,
  Desktop-generated models (M011, R007, F004, S002, and D004 for bare
  references) are warning or info.
- A configuration file found next to (or above) the checked path now
  changes the run. Pass `--no-config` to ignore it.
- Python 3.10 remains supported. TOML configuration needs Python 3.11+
  (`tomllib`); on 3.10 use `.tmdl-preflight.json`.
- Version numbering: the previous release was tagged `v1.0.0-stable` on
  GitHub, but its package metadata (`pyproject.toml` and `__version__`)
  still said `0.1.0`. This release sets both to `1.1.0`.

## 0.1.0

First public release.

### Highlights

- **21 rules** covering the TMDL/PBIP failure modes that reject imports or
  silently corrupt results: model structure (M001–M009), DAX integrity
  (D001–D003), relationship topology (R001–R005), field-parameter sources
  (F001), bookmark JSON (B001–B002), and formatting hygiene (S001).
- **5 auto-fixers** (M003, M004, M006, F001, B001) applied through a
  check → fix → re-check loop: a run only counts as clean when the re-check
  from disk is clean, so a fixer never vouches for itself.
- **Three entry points**: the `tmdl-preflight` CLI (`check`, `fix`,
  `rules`), a pytest fixture (`tmdl_preflight`), and a plain Python API.
- **Zero runtime dependencies**; Python 3.10+.

### Validated against production-scale models

Before release, the suite was run end to end against several multi-megabyte
production semantic models (hundreds of tables, thousands of measures,
calculation groups, legacy expression fences, non-ASCII object names).
Findings folded back into this release:

- **D002 (nameof-resolution)** no longer flags fully-qualified measure
  references such as `NAMEOF('Table'[Measure])`. Power BI Desktop writes
  that form itself when building field parameters, so flagging it buried
  real breaks under hundreds of false alarms per model.
- **R005 (orphan-tables)** now exempts hidden tables and tables whose
  columns are all hidden (the measure-home pattern). Real models declare
  dozens of these and they are unrelated by design.
- **CLI output is resilient to console code pages.** Object names outside
  the console's encoding (Greek, accented, emoji) no longer risk a
  `UnicodeEncodeError`; unencodable characters are replaced instead of
  crashing the report.
- `--select`/`--ignore` now reject rule ids that do not exist (exit code 2)
  instead of silently running a smaller rule set.

### Error-message conventions

Every human-facing message follows a fixed shape: what is wrong, where it
is, why it breaks deployments or analysis, and the concrete next action.
Messages avoid blame, jargon-only phrasing, and vague words such as
"invalid".
