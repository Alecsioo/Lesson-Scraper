from pathlib import Path
import json
from tqdm import tqdm
from database import driver, verify_connection, close_driver

DATABASE = "neo4j"
PATH = "01-cleaned_courses/es"
TYPES = {"phrase_builder", "word_spelling", "gap_fill_typing"}


def make_source_node(exercise: dict, exercise_type: str) -> dict | None:
    """
    Return the ContentNode that acts as the "anchor" of the list.

    phrase_builder  -> full_text_orig  (complete sentence; tokens must reproduce it)
    word_spelling   -> gap_sentence_orig  (sentence with gap; letters fill the blank)
    gap_fill_typing -> full_text_orig  (complete sentence; gap variant stored as item)
    """
    if exercise_type == "phrase_builder":
        value = exercise.get("full_text_orig")
        return {"kind": "full_text_orig", "value": value} if value else None

    if exercise_type == "word_spelling":
        value = exercise.get("gap_sentence_orig") or exercise.get("full_text_orig")
        kind = "gap_sentence_orig" if exercise.get("gap_sentence_orig") else "full_text_orig"
        return {"kind": kind, "value": value} if value else None

    if exercise_type == "gap_fill_typing":
        value = exercise.get("full_text_orig")
        return {"kind": "full_text_orig", "value": value} if value else None

    return None


def make_item_nodes(exercise: dict, exercise_type: str) -> list[dict]:
    """
    Return ordered items: {kind, value, position}.

    phrase_builder  -> tokens  (plain strings)
    word_spelling   -> letters (plain strings)
    gap_fill_typing -> single item: gap_sentence_orig
                       (correct_answers is unreliable / empty in the source data)
    """
    if exercise_type == "phrase_builder":
        raw = exercise.get("tokens", [])
        return [
            {"kind": "token", "value": str(token), "position": i}
            for i, token in enumerate(raw)
            if token
        ]

    if exercise_type == "word_spelling":
        raw = exercise.get("letters", [])
        return [
            {"kind": "letter", "value": str(letter), "position": i}
            for i, letter in enumerate(raw)
            if letter
        ]

    if exercise_type == "gap_fill_typing":
        value = exercise.get("gap_sentence_orig")
        if not value:
            return []
        return [{"kind": "gap_sentence_orig", "value": value, "position": 0}]

    return []



def extract_lists(base_dir: str) -> list[dict]:
    results = []
    base_path = Path(base_dir)

    if not base_path.exists():
        tqdm.write(f"[ERROR] Directory does not exist: {base_path}")
        return results

    json_files = list(base_path.rglob("*.json"))

    if not json_files:
        tqdm.write(f"[INFO] No JSON files found in: {base_path}")
        return results

    for path in tqdm(json_files, desc="Scanning JSON files", unit="file"):
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except OSError as e:
            tqdm.write(f"[WARN] Failed to open {path}: {e}")
            continue
        except json.JSONDecodeError as e:
            tqdm.write(f"[WARN] Invalid JSON in {path}: {e}")
            continue

        for unit in data.get("units", []):
            for exercise in unit.get("exercises", []):
                exercise_type = exercise.get("type")

                if exercise_type not in TYPES:
                    continue

                source = make_source_node(exercise, exercise_type)
                items = make_item_nodes(exercise, exercise_type)

                if not source or not items:
                    tqdm.write(
                        f"[SKIP] {exercise.get('exercise_id', '?')} "
                        f"({exercise_type}): missing source or items"
                    )
                    continue

                results.append(
                    {
                        "exercise_type": exercise_type,
                        "source": source,
                        "items": items,
                    }
                )

    tqdm.write(f"[INFO] Extracted {len(results)} lists total")
    return results



def import_list(tx, item: dict):
    """
    Graph pattern:
        (source:ContentNode) -[:HAS_ITEM {family, exercise_type, position}]-> (item:ContentNode)

    `position` preserves the original order of tokens / letters.
    All three relationship properties are part of the MERGE key, so two identical
    nodes at different positions produce distinct relationships.
    """
    tx.run(
        """
        MERGE (source:ContentNode {kind: $source_kind, value: $source_value})
        WITH source
        UNWIND $items AS item
            MERGE (content:ContentNode {kind: item.kind, value: item.value})
            MERGE (source)-[:HAS_ITEM {
                family:        "LIST",
                exercise_type: $exercise_type,
                position:      item.position
            }]->(content)
        """,
        source_kind=item["source"]["kind"],
        source_value=item["source"]["value"],
        items=item["items"],
        exercise_type=item["exercise_type"],
    )


def run_import(base_dir: str):
    verify_connection()
    lists = extract_lists(base_dir)

    if not lists:
        tqdm.write("[INFO] No lists to import")
        close_driver()
        return

    with driver.session(database=DATABASE) as session:
        for item in tqdm(lists, desc="Importing lists", unit="list"):
            session.execute_write(import_list, item)

    tqdm.write("[INFO] Import complete")
    close_driver()


if __name__ == "__main__":
    run_import(PATH)