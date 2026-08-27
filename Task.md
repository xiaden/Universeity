Build from scratch a production-ready, extensible **Universal Media Decomposer API**.

The system accepts arbitrary source media, decomposes it into progressively richer structured representations, preserves exact provenance back to source material, reconciles information across multiple sources/languages/adaptations without collapsing their differences, and exposes both graph-style semantic querying and deterministic structured access to the underlying evidence.

Do not design this system around any particular downstream consumer. It is infrastructure: downstream systems should adapt to the API rather than the API embedding assumptions about what will consume it.

The finished system must be capable of operating autonomously in normal use while allowing a human to inspect, override, edit, invalidate, and selectively rerun any decompositional result.

Do not stop at a plan, prototype, skeleton, TODO list, or partial implementation. Research current implementation options, create an adversarial design, implement the chosen architecture, test it, document it, and perform a final adversarial correctness review before considering the task complete.

---

# 1. Core conceptual model

The system must explicitly separate:

```text
SOURCE MATERIAL
      ↓
EVIDENCE
      ↓
INTERPRETATION / SEMANTICS
      ↓
KNOWLEDGE GRAPH
```

Never collapse these layers.

## Source material

The immutable media supplied by the user:

```text
novel
light novel
manga
comic
webtoon
image
photograph
illustration
anime
movie
TV episode
video
audio
audiobook
podcast
song
subtitle file
transcript
screenplay
HTML
PDF
EPUB
CBZ/CBR
arbitrary document
arbitrary media container
```

This list is non-exhaustive.

## Evidence

Direct observations extracted from a source:

```text
text span
subtitle event
audio interval
video interval
frame
panel
page region
OCR region
speaker observation
face/object observation
music
sound event
scene boundary
layout
visual relationship
timing
metadata
```

Evidence must retain exact provenance.

## Semantic interpretation

Claims inferred from evidence:

```text
person A is speaking
person B is present
event C occurred
location is X
object Y belongs to Z
character appears upset
this subtitle event corresponds to this spoken utterance
this paragraph and this scene represent the same narrative event
```

These are interpretations, not source facts, and must preserve confidence and supporting evidence.

## Knowledge graph

Reconciled entities, events, relationships, states, timelines, locations, identities, aliases, correspondences, and other semantic structure derived from one or more sources.

---

# 2. Fundamental rule: provenance is never lost

Every derived object must be traceable back to its evidence and ultimately to immutable source material.

A semantic assertion should be able to answer:

```text
What claims this?
Which source(s) support it?
Where exactly in those sources?
Which decomposition step produced it?
Which model/tool/version produced it?
What confidence was assigned?
Was it later overridden?
Who/what changed it?
Which other claims disagree?
```

Example conceptual shape:

```json
{
  "claim": {
    "subject": "character:emilia",
    "predicate": "speaks",
    "object": "utterance:1842"
  },
  "confidence": 0.97,
  "evidence": [
    {
      "source_id": "source:anime:s01e05",
      "locator": {
        "start_ms": 842310,
        "end_ms": 845120
      }
    },
    {
      "source_id": "source:subtitle:english-full",
      "locator": {
        "event_id": 418
      }
    }
  ],
  "generated_by": {
    "pipeline_step": "speaker_resolution",
    "version": "..."
  }
}
```

Do not require this exact schema, but preserve the capability.

---

# 3. Media ingestion

Expose an API for ingesting arbitrary media.

A small number of generic endpoints is acceptable:

```text
POST /sources/book
POST /sources/image
POST /sources/audio
POST /sources/video
POST /sources/document
POST /sources/media
```

A richer taxonomy is also acceptable:

```text
/light-novel
/novel
/manga
/webtoon
/comic
/anime
/movie
/tv
/audiobook
/song
/podcast
/subtitle
/image
/document
```

Do not hard-code the architecture around the endpoint taxonomy.

Internally use extensible media/source descriptors.

A source should be able to carry properties such as:

```text
media type
format
language
edition
translation
adaptation
release
volume
chapter
episode
track
page count
duration
parent work
source relationships
user metadata
```

The system must support multiple related sources for the same underlying work.

---

# 4. Multi-source and multilingual by design

Do **not** assume that one work has one authoritative source or one language.

The same work may have:

```text
Japanese novel
English novel translation
revised English translation
manga adaptation
anime adaptation
Japanese audio
English dub
Japanese subtitles
English subtitles
English SDH subtitles
Spanish subtitles
French subtitles
official artwork
audiobook
script
fan translation
```

These are separate source representations.

They must retain their individuality while being alignable.

Language is an attribute of evidence or realization, **not a graph boundary**.

The system should be capable of determining that:

```text
JP novel passage A
EN novel passage B
manga panels 134–139
anime scene 412
subtitle events 918–927
audio interval 00:18:41–00:19:03
```

appear to represent the same or corresponding narrative event.

Store that relationship explicitly rather than merging the underlying evidence.

---

# 5. Adaptation and continuity boundaries

Never assume that two sources depicting similar events are identical.

Represent concepts such as:

```text
WORK
CONTINUITY
EDITION
TRANSLATION_OF
ADAPTATION_OF
DERIVED_FROM
CORRESPONDS_TO
EXPANDS
OMITS
REORDERS
CONTRADICTS
ALTERNATE_REALIZATION
```

Example:

```text
Work
├── Novel continuity
│   ├── Japanese edition
│   ├── English translation
│   └── revised translation
│
└── Animated adaptation
    ├── Japanese audio
    ├── English dub
    ├── Japanese subtitles
    └── English subtitles
```

A scene in an adaptation may correspond to a scene in the source while containing:

```text
omitted dialogue
added dialogue
different blocking
changed characterization
reordered events
merged events
different locations
different participants
```

Those differences are information and must survive reconciliation.

---

# 6. Decomposition must be a rerunnable DAG

Do not build one giant opaque pipeline.

Model decomposition as a dependency graph of explicit steps.

Illustrative structure:

```text
INGEST
  ↓
FORMAT ANALYSIS
  ↓
BASIC SEGMENTATION
  ├── text segmentation
  ├── pages/panels
  ├── shots/scenes
  ├── audio regions
  └── subtitle events
  ↓
LOW-LEVEL EXTRACTION
  ├── OCR
  ├── ASR
  ├── object/face observations
  ├── speaker embeddings
  ├── music/SFX
  ├── layout
  └── metadata
  ↓
STRUCTURAL ANALYSIS
  ├── scene decomposition
  ├── speaker attribution
  ├── entity extraction
  ├── dialogue/narration distinction
  ├── environment
  ├── chronology
  └── relationships
  ↓
ENTITY RESOLUTION
  ↓
CROSS-SOURCE ALIGNMENT
  ↓
SEMANTIC RECONCILIATION
  ↓
KNOWLEDGE GRAPH
```

Individual stages must be independently rerunnable.

Changing one stage should invalidate only dependent descendants rather than forcing complete re-ingestion.

---

# 7. User overrides are first-class data

Users must be able to explicitly correct the system.

Examples:

```text
"This speaker is Emilia."
"These are the same character."
"These are NOT the same character."
"This scene begins here."
"This segment is narration."
"This image is Rem."
"This translation corresponds to this passage."
"This event did not happen in this continuity."
"This relationship is incorrect."
"Use this spelling as canonical."
```

Do not mutate model output invisibly.

Store user corrections as explicit provenance-bearing assertions with precedence over machine inference.

Conceptually:

```text
Machine assertion:
speaker = unknown_character_14
confidence = .73

User assertion:
speaker = character:emilia
authority = USER_OVERRIDE
```

Dependent semantic steps must be invalidated/recomputed appropriately.

Users must be able to:

```text
edit
override
delete an interpretation
split
merge
reassociate
lock
unlock
invalidate
rerun
```

segments and semantics.

---

# 8. Explicit source segmentation

Every media type must expose addressable segments.

Examples:

### Text

```text
document
chapter
section
paragraph
sentence
token/span
```

### Sequential art

```text
volume
chapter
page
panel
region
speech bubble
caption
```

### Video

```text
file
episode
scene
shot
frame
region
time interval
```

### Audio

```text
file
chapter
scene
utterance
speaker turn
music region
sound event
time interval
```

These do not need one universal physical hierarchy.

They need a universal way to reference them.

---

# 9. Stable structured source references

Create a deterministic structured locator system.

A client must be able to reference exact source material without relying on fuzzy text matching.

Examples:

```text
source://novel-123/chapter/4/paragraph/18
source://manga-22/page/143/panel/3
source://anime-s01e05/time/842310-845120
source://anime-s01e05/frame/21482
source://subtitle-77/event/418
source://audio-42/time/68123-71982
```

These are illustrative.

References should remain stable across semantic reprocessing wherever possible.

Support retrieving:

```text
raw source
normalized representation
neighboring context
derived evidence
semantic claims
graph entities
provenance
```

from a locator.

---

# 10. Knowledge graph representation

Design a graph model capable of representing at least:

```text
works
continuities
sources
editions
adaptations
translations
entities
characters
people
organizations
locations
objects
concepts
scenes
events
utterances
actions
relationships
states
emotions
goals
knowledge/beliefs
timelines
presence
speaker identity
aliases
visual appearances
environment
music
sounds
cross-source correspondence
contradictions
```

Do not restrict the ontology to fictional media.

The model should remain usable for arbitrary media.

Prefer an extensible typed-property graph or similarly expressive representation rather than hard-coding every possible semantic concept into SQL columns.

The graph must retain links to source evidence.

---

# 11. Evidence versus canonical semantics

Never force every observation into one canonical truth.

Support:

```text
assertions
confidence
source authority
support
contradiction
alternative interpretation
scope
continuity
temporal validity
user override
```

Example:

```text
Source A claims hair = silver.
Source B renders hair = white.
Source C describes hair = pale silver.
```

The system may infer a semantic reconciliation while preserving all three source claims.

Likewise:

```text
English subtitle: "I hate you."
Japanese source: nuance closer to "I can't stand you."
Dub: "You're the worst."
```

Do not replace them with a fabricated authoritative sentence.

Represent:

```text
shared semantic intent
+
multiple language/source realizations
```

---

# 12. Cross-source alignment

Implement explicit mechanisms for aligning segments across sources.

Signals may include:

```text
semantic similarity
translated semantic similarity
entity overlap
event overlap
scene order
timestamps
dialogue correspondence
speaker sequence
visual correspondence
audio correspondence
chapter structure
adaptation sequence
```

Alignment should be confidence-bearing and many-to-many.

Support:

```text
1 passage → 1 scene
1 passage → several scenes
several passages → 1 adaptation scene
source event omitted entirely
adaptation-only event
reordered sequence
```

Do not assume one-to-one alignment.

---

# 13. ML/LLM architecture

ML/LLMs are allowed and expected where they improve extraction, reconciliation, or reasoning.

They must not become an opaque database.

Every model-driven operation must emit structured results.

Record:

```text
model
version
prompt/instruction version
input evidence references
output
confidence where applicable
timestamp
dependency step
```

Prefer deterministic algorithms before expensive model reasoning where suitable.

Use specialized models where materially better:

```text
OCR
ASR
speaker diarization
speaker embeddings
vision
object detection
face analysis
scene detection
music/audio classification
language identification
translation/alignment
LLM semantic reconciliation
```

Make model implementations swappable behind interfaces.

Do not bind the architecture to one model provider.

Support local and remote inference where reasonable.

---

# 14. Confidence and uncertainty

Uncertainty must survive all the way through the system.

Do not force:

```text
unknown → invented answer
```

Represent:

```text
unknown
ambiguous
conflicting
probable
confirmed
user-confirmed
```

Where useful, store candidate sets:

```json
{
  "speaker_candidates": [
    ["character:emilia", 0.72],
    ["character:rem", 0.21],
    ["unknown", 0.07]
  ]
}
```

Downstream graph queries must be able to request confidence thresholds.

---

# 15. Semantic editing API

Expose explicit APIs for editing semantic structures.

Clients must be able to:

```text
create entity
edit entity
merge entities
split entity
add/remove alias
create assertion
override assertion
invalidate assertion
change segment boundary
split segment
merge segments
associate evidence
disassociate evidence
change speaker
change scene
change correspondence
lock corrected data
unlock data
rerun dependent analysis
```

Edits must retain history.

Prefer append-only/versioned semantic operations over destructive silent mutation where practical.

---

# 16. Rerun / invalidation engine

Support selective recomputation.

Example:

```text
User corrects character identity
        ↓
invalidate:
  speaker-resolution descendants
  scene-presence descendants
  cross-source entity alignment descendants

DO NOT invalidate:
  OCR
  raw ASR
  source segmentation
  unrelated scenes
```

Expose APIs resembling:

```text
POST /analysis/{id}/rerun
POST /segments/{id}/rerun
POST /sources/{id}/rerun
POST /claims/{id}/invalidate
```

Also support specifying a stage:

```text
rerun from speaker_resolution
rerun cross_source_alignment only
rerun semantic_reconciliation for scene 418
```

The dependency system must determine what downstream state becomes stale.

---

# 17. Semantic questioning

Expose graph-style semantic QA.

Examples:

```text
Who is present in this scene?

Who is speaking at this point?

Where is Character X during Event Y?

Which characters know Fact Z by Chapter 10?

When did Character A first meet Character B?

What sources support that relationship?

Does the anime contradict the novel here?

Which scenes adapt Chapter 4?

Where does the English translation differ semantically from the Japanese source?

Which entities are unresolved?

What evidence supports this speaker attribution?

Show every source representation of this utterance.

Which claims have low confidence?

What changed after the user corrected this entity?
```

The questioning layer must query the structured evidence/semantic system rather than treating all ingested media as an unstructured RAG corpus.

Natural-language QA may compile into graph/query operations, but answers must return structured provenance.

---

# 18. Structured graph querying

Do not expose semantic knowledge only through natural language.

Provide a structured API/query mechanism.

Possible options include:

```text
GraphQL
Cypher-compatible query layer
typed REST query API
custom graph query DSL
```

Research current options and choose based on implementation quality and extensibility.

Clients must be able to deterministically retrieve things like:

```text
all scenes containing character X
all utterances by character Y
all evidence for claim Z
all sources corresponding to event Q
all entities present during interval T
all unresolved entity aliases
all contradictions between continuity A and B
```

---

# 19. Source-material retrieval

The API must make it easy to retrieve the actual evidence associated with a graph node.

Example:

```text
GET semantic event
        ↓
source references:
  JP novel passage
  EN novel passage
  anime interval
  subtitle events
  manga panels
```

Then:

```text
GET source reference
```

returns the corresponding bounded source material or an appropriate representation.

Support source-native retrieval:

```text
text
image crop
frame
panel crop
audio clip
video clip metadata/time locator
subtitle event
```

Do not duplicate huge source blobs into the graph database unnecessarily.

---

# 20. Search

Support both:

### Semantic search

```text
"scenes where Subaru is isolated"
"arguments between these two characters"
"events involving the mansion"
```

### Exact/source search

```text
exact phrase
character name
source locator
timestamp
chapter/page
track/event identifier
```

Search results must identify whether they refer to:

```text
source evidence
semantic interpretation
canonical entity
```

---

# 21. Versioning and audit history

Every important derived artifact should be versioned or otherwise historically recoverable.

Track:

```text
source ingestion version
pipeline version
model version
ontology/schema version
user modifications
semantic changes
reruns
invalidations
entity merges/splits
cross-source alignment changes
```

Provide an audit API.

A user must be able to determine:

```text
Why does the graph currently believe X?
What believed X previously?
What caused it to change?
```

---

# 22. Storage architecture

Research and choose appropriate persistence technologies.

Do not assume that all data belongs in a graph database.

Likely categories include:

```text
immutable source/blob storage
structured relational state
graph semantics
vector indexes
derived media/cache
pipeline/job state
```

Use separate technologies where that materially simplifies correctness.

Avoid duplicating authoritative data across stores without a clear ownership model.

Define which store owns:

```text
source truth
segment truth
semantic truth
embeddings
pipeline state
user edits
audit history
```

---

# 23. Background processing

Large media decomposition is naturally asynchronous.

Provide a durable job system.

Clients should be able to:

```text
submit source
receive source/job ID
poll or stream progress
inspect pipeline stages
cancel work
retry failed stages
rerun selected stages
```

A failed late-stage analysis must not require repeating expensive successful early extraction.

Jobs must be restartable after process/container restart.

---

# 24. API behavior

Expose an actual network API.

At minimum provide:

```text
source ingestion
source metadata
source references
segment retrieval/editing
analysis status
rerun/invalidation
entities
claims/assertions
relationships
cross-source alignment
semantic querying
structured querying
search
provenance
audit/history
health
capabilities
```

Produce OpenAPI documentation if REST is used.

Use stable IDs.

Use pagination for large collections.

Use structured errors.

---

# 25. Extensible decomposition plugins

Adding a new media type or analysis capability must not require rewriting the core.

Define explicit plugin/provider interfaces for:

```text
ingestors
extractors
segmenters
analyzers
aligners
reconcilers
model providers
embedders
storage backends where appropriate
```

Example:

```text
MangaPlugin
  → page extraction
  → panel segmentation
  → OCR
  → bubble detection
  → reading order

VideoPlugin
  → demux
  → scene detection
  → frame sampling
  → ASR
  → diarization
  → visual analysis
```

Both emit into common evidence/semantic contracts.

---

# 26. Initial modality support

The first release must actually implement representative decomposition pipelines rather than merely defining interfaces.

At minimum support:

### Text / book

Accept at least:

```text
TXT
Markdown
EPUB
PDF where text extraction is viable
```

Extract:

```text
document structure
chapters
paragraphs
sentences
entities
dialogue
speaker candidates
events
locations
relationships
semantic segments
```

### Image

Accept common raster formats.

Extract:

```text
image metadata
OCR
regions
objects
people/characters where possible
spatial relationships
descriptions
```

### Audio

Accept common audio formats.

Extract:

```text
segments
ASR
language
speaker diarization
speaker identity candidates
music
sound events
timing
semantic utterances
```

### Video

Accept common containers/codecs through established media tooling.

Extract:

```text
video/audio/subtitle tracks
scenes
shots
frames
ASR
subtitle events
speakers
visible entities
environment
objects
music/SFX
temporal events
```

Additional media such as manga/webtoon/audiobook should either be implemented directly or naturally compose existing modality plugins.

---

# 27. Subtitle tracks are evidence sources

For media containing multiple subtitle tracks, treat each track as an independent evidence source.

Preserve:

```text
language
track metadata
timings
styles
SDH/HI annotations
speaker labels
signs
songs
typesetting
translation differences
```

Align them with:

```text
audio
video
other subtitle tracks
other languages
related textual sources
```

Do not assume one subtitle track is authoritative.

Do not flatten them into one subtitle representation during ingestion.

---

# 28. Derived canonical structures

The system may derive canonical semantic structures such as:

```text
canonical character identity
canonical scene identity
canonical event
canonical utterance meaning
canonical timeline relationship
canonical location
```

But every canonical structure must retain competing/source-specific realizations.

Do not create canonical prose when semantic equivalence is the appropriate abstraction.

---

# 29. Identity resolution

Entity resolution is a core subsystem.

Handle:

```text
names
nicknames
titles
aliases
transliterations
different scripts
translation variants
OCR errors
speaker labels
visual identities
unnamed characters
later-resolved identities
```

Example:

```text
エミリア
Emilia
EMILIA
Half-Elf
the silver-haired girl
speaker_07
face_cluster_12
```

may eventually resolve to one entity while preserving every alias/evidence path.

Merging must be reversible.

---

# 30. Temporal model

Provide explicit temporal representation.

Support:

```text
source-local time
video/audio timecodes
narrative sequence
story chronology
flashbacks
simultaneous events
unknown ordering
cross-source temporal correspondence
```

Do not assume narrative order equals chronological order.

---

# 31. Spatial / environmental model

Represent environments where evidence supports them:

```text
location
sub-location
scene environment
participants present
objects present
visual state
audio environment
weather
lighting
relative positioning where useful
```

These should be semantic assertions with provenance rather than freeform descriptions only.

---

# 32. Security and isolation

Treat uploaded media as untrusted.

Requirements:

```text
no shell interpolation
sandbox dangerous parsers where practical
bounded subprocess execution
resource limits
file-size limits/configuration
safe archive extraction
path traversal prevention
media parser failure containment
timeouts
structured logging
```

Never allow an uploaded filename/archive to escape its assigned storage area.

---

# 33. Observability

Provide:

```text
structured logs
job status
stage timing
model invocation metrics
failure counts
queue depth
cache hit rate
per-stage cost/time
source decomposition report
```

A user must be able to inspect why decomposition is slow or incomplete.

---

# 34. Testing

Build serious automated tests.

## Unit tests

Cover:

```text
source locators
segment creation
graph assertions
provenance
entity merge/split
dependency invalidation
user overrides
confidence handling
cross-source alignment
multilingual aliases
versioning
structured queries
```

## Integration tests

Construct synthetic media demonstrating:

```text
book
translated book
images
comic-like pages
audio with multiple speakers
video with dialogue
multiple subtitle tracks
multiple languages
HI/SDH annotations
adaptation differences
contradictory sources
missing events
reordered events
```

## End-to-end test

Demonstrate:

```text
ingest several related heterogeneous sources
        ↓
decompose independently
        ↓
align sources
        ↓
resolve shared entities
        ↓
create semantic graph
        ↓
answer semantic question
        ↓
return supporting source references
        ↓
user corrects an entity
        ↓
invalidate affected descendants
        ↓
rerun only affected analysis
        ↓
new answer reflects correction
        ↓
audit trail explains change
```

---

# 35. Adversarial design requirement

Before implementation, perform a genuine adversarial architecture review.

At minimum challenge:

```text
graph technology
relational vs graph ownership
blob/source storage
segment identity
cross-source alignment
multilingual representation
entity resolution
pipeline DAG/state system
model abstraction
job system
semantic editing/versioning
provenance representation
query architecture
```

Do not preserve the initial architecture merely because it was proposed first.

Research contemporary primary sources and mature implementations.

Record:

```text
credible alternatives
benefits
failure modes
technology maturity
operational complexity
scaling concerns
data migration concerns
surviving risks
```

Then distill an implementation-ready design document.

---

# 36. Do not overfit ontology prematurely

The semantic model must support rich structured concepts without requiring a schema migration for every new predicate.

Avoid either extreme:

```text
everything is an opaque JSON blob
```

or:

```text
every imaginable concept gets a hardcoded SQL table/column
```

Research an appropriate middle ground.

Provide typed core concepts plus extensible semantic assertions.

---

# 37. API neutrality

Do not include architecture or terminology specific to:

```text
audiobook generation
subtitle generation
game generation
screenplay generation
video generation
```

Those may eventually be consumers, but they are not part of this system.

The API's responsibility ends at:

```text
ingestion
decomposition
evidence
semantics
knowledge
provenance
querying
editing
reprocessing
```

---

# 38. Developer ergonomics

Provide:

```text
Dockerfile
Docker Compose
configuration examples
database migrations
seed/test fixture tools
OpenAPI or equivalent schema
API client examples
development setup
production setup
health checks
```

A developer should be able to start the service locally with a small number of commands.

---

# 39. Documentation

Produce documentation covering:

```text
architecture
source model
evidence model
semantic model
graph model
provenance
source locators
pipeline DAG
invalidation semantics
user overrides
multi-source alignment
multilingual handling
adaptations/continuities
model provider interfaces
storage ownership
API endpoints
query mechanisms
deployment
testing
extension/plugin authoring
known limitations
```

Include diagrams where useful.

---

# 40. Definition of done

Do not consider this task complete until:

1. An adversarial technology/design process has been completed and documented.
2. An implementation-ready design has been produced.
3. The service is implemented.
4. Persistent source storage works.
5. Text/book ingestion works.
6. Image ingestion works.
7. Audio ingestion works.
8. Video ingestion works.
9. Sources decompose into stable addressable segments.
10. Derived evidence retains exact provenance.
11. Semantic assertions retain evidence/confidence.
12. Multi-language sources coexist within the same work/semantic graph.
13. Adaptation/continuity boundaries are represented.
14. Cross-source alignment works.
15. Entity resolution works and is reversible.
16. User overrides work.
17. Explicit segment editing works.
18. Explicit semantic editing works.
19. Dependency invalidation works.
20. Individual decomposition stages can be rerun.
21. Durable asynchronous jobs survive restart.
22. Structured source referencing works.
23. Semantic KG-style questioning works.
24. Structured graph querying works.
25. Answers expose supporting evidence/source references.
26. Audit/history explains semantic changes.
27. Model/provider interfaces are swappable.
28. At least one local or self-hostable model path is supported where ML inference is required.
29. Tests cover heterogeneous and contradictory multi-source media.
30. The end-to-end correction → invalidation → selective-rerun test passes.
31. Docker deployment works.
32. Lint/type/static checks pass.
33. Automated tests pass.
34. Perform a final adversarial code correctness review focused on:

    * provenance loss;
    * source/semantic conflation;
    * irreversible entity merges;
    * invalidation errors;
    * stale derived semantics;
    * broken source locators;
    * cross-language collapse;
    * adaptation conflation;
    * race conditions;
    * job restart behavior;
    * inconsistent data across storage technologies;
    * unsafe media handling.
35. Repair findings and rerun the complete validation suite.

---

# 41. Agent authority

You have authority to:

```text
research technologies
choose languages/frameworks/databases
create architecture documents
create source files
create migrations
install project-local dependencies
create containers
run services
run tests
refactor
replace poor architectural choices discovered during implementation
```

Do not ask the user to select routine implementation details, frameworks, database products, libraries, naming, or internal schemas.

Escalate only if a genuinely product-defining ambiguity remains that cannot be safely resolved from these requirements.

Otherwise make the decision, document why, and continue.

The goal is not to produce the smallest implementation.

The goal is to produce a **general-purpose, provenance-preserving, multi-source, multilingual decomposition and semantic knowledge service that can become authoritative infrastructure for arbitrary media understanding.**

The final response should contain only:

* what was implemented;
* the final architecture at a high level;
* test/type/lint results;
* major remaining limitations;
* exact commands to start the service;
* one minimal API example demonstrating:

  * ingest;
  * decomposition;
  * semantic query;
  * source-reference retrieval;
  * user correction;
  * selective rerun.
​