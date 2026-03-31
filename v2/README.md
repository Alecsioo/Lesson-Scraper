# Lesson Scraper

A Python pipeline that scrapes language learning exercises from [Busuu](https://busuu.com), cleans the raw data, and maps exercises into a Neo4j graph database organised by exercise family, language, and level.

---

## Project Structure

```
lesson_scraper/
├── run_pipeline.py              # Orchestrator — runs all steps end to end
├── .env                         # Environment variables (not committed)
│
├── lesson_scraper.py        # Step 1 — scrapes raw lessons from Busuu
├── cleaning.py              # Step 2 — cleans and normalises raw JSON
├── graphql_scraper.py       # GraphQL helper used by the scraper
├── extractExercisesType.py  # Exercise type utilities
├── classes.py               # Data classes (Course, Level, Chapter, Lesson)
├── 00-raw_courses/          # Raw scraped data (generated, not committed)
├── 01-cleaned_courses/      # Cleaned data (generated, not committed)
│
└── database/
    ├── database.py              # Neo4j driver setup
    ├── pair_mapper.py           # Maps PAIR family exercises
    ├── group_mapper.py          # Maps GROUP family exercises
    ├── list_mapper.py           # Maps LIST family exercises
    ├── question_mapper.py       # Maps QUESTION family exercises
    └── gap_fill_mapper.py       # Maps GAP_FILL family exercises
```

---

## Prerequisites

### 1. Environment variables

Create a `.env` file at the project root with the following keys:

```env
# Busuu API
ACCESS_TOKEN=               # Retrieved from browser cookies after logging in to busuu.com
                            # Go to DevTools → Application → Cookies → access-token
                            # This token does not appear to expire, so this only needs to be done once

GRAPHQL_URL=https://api.busuu.com/graphql
BASE_COURSE_LIST_URL=https://api.busuu.com/api/courses-overview
BASE_COURSE_PACK_URL=https://api.busuu.com/api/course-pack/{pack}?translations={source},en&interface_language=en&lang1={lang}&content_version=3.0
BASE_LESSON_URL=https://api.busuu.com/api/v2/component/{lesson_id}?lang1={lang}&interface_language=en&translations={lang},en&content_version=3.0

# Neo4j
NEO4J_DATABASE=
NEO4J_URI=
NEO4J_USERNAME=
NEO4J_PASSWORD=
```

### 2. Neo4j database

The project uses a **cloud-hosted Neo4j AuraDB** instance. To get credentials, reach out to Alex Rodrigues or Giada Galdiolo.

Alternatively, you can spin up a **local Neo4j instance** and point `NEO4J_URI` to it (e.g. `neo4j://localhost:7687`).

### 3. Python dependencies

```bash
pip install -r requirements.txt
```

---

## Running the pipeline

### Full pipeline

To run all steps in sequence — scraping, cleaning, and all database mappers — run from the project root:

```bash
py -m run_pipeline
```

The script will prompt you to select a language to scrape, then proceed through each step automatically.

### Individual steps

Any individual mapper or script can also be run in isolation using module notation from the project root:

```bash
py -m database.pair_mapper
py -m database.group_mapper
py -m database.list_mapper
py -m database.question_mapper
py -m database.gap_fill_mapper
```

> **Note:** Always run scripts using `py -m <module.name>` from the project root — never use a file path like `py .\database\pair_mapper.py`, and never include the `.py` extension in the module name.

---

## Pipeline steps

| Step | Script | Description |
|------|--------|-------------|
| 1 | `lesson_scraper.py` | Prompts for a language, fetches all course packs and lessons from the Busuu API, and saves raw JSON to `v2/00-raw_courses/` |
| 2 | `cleaning.py` | Cleans and normalises the raw JSON files, writing output to `v2/01-cleaned_courses/` |
| 3–7 | `database/*_mapper.py` | Reads cleaned data and imports exercises into Neo4j, organised by exercise family |

---

## Exercise families

Exercises are mapped into the following families in the graph:

| Family | Relationship | Exercise types |
|--------|-------------|---------------|
| `PAIR` | `MATCHES_WITH` | `match_up` |
| `GROUP` | `GROUPS_WITH` | `listen_repeat`, `dialogue`, `flashcard`, `speech_recognition`, `writing` |
| `LIST` | `LISTED_WITH` | `phrase_builder`, `word_spelling`, `gap_fill_typing`|
| `QUESTION` | `ANSWERS` | `true_false`, `multiple_choice`, `highlight_selection` |
| `GAP_FILL` | `FILLS_GAP_IN` | `gap_fill_click`, `gap_fill_multiple` |

Each `ContentNode` in the graph is linked to:
- a `Language` node via `IS_FOR_LANGUAGE`
- a `Level` node (e.g. `A1`, `B2`) via `IS_OF_LEVEL`
- a `Family` node via `IS_OF_FAMILY`

---

## Example Cypher queries

All pairs for Italian A1:

```cypher
MATCH (left:ContentNode)-[r:MATCHES_WITH]->(right:ContentNode),
      (left)-[:IS_FOR_LANGUAGE]->(:Language {code: "it"}),
      (left)-[:IS_OF_LEVEL]->(:Level {name: "A1"})
RETURN left, r, right
LIMIT 25
```

Count exercises per language and level:

```cypher
MATCH (n:ContentNode)-[:IS_FOR_LANGUAGE]->(lang:Language),
      (n)-[:IS_OF_LEVEL]->(level:Level)
RETURN lang.code, level.name, count(n) AS node_count
ORDER BY lang.code, level.name
```
