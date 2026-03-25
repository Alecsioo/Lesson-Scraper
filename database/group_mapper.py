from pathlib import Path
import json
from tqdm import tqdm
from database import driver, verify_connection, close_driver

DATABASE = "neo4j"
PATH = "v2/01-cleaned_courses/en"
TYPES = {
    "listen_repeat",
    "dialogue",
    "flashcard",
    "speech_recognition",
    "writing",
}

TYPE_CONFIG = {
    "listen_repeat": {
        "label_fields": ["text_orig", "text_en"],
        "item_fields": ["audio_orig", "image", "video"],
        "relationship_type": "GROUPS_WITH",
    },
    "dialogue": {
        "label_fields": ["text_orig", "text_en"],
        "item_fields": ["audio_orig", "gap_sentence_orig", "correct_answer"],
        "relationship_type": "GROUPS_WITH",
    },
    "flashcard": {
        "label_fields": ["text_orig", "text_en"],
        "item_fields": ["audio_orig", "audio_en", "image", "video"],
        "relationship_type": "GROUPS_WITH",
    },
    "speech_recognition": {
        "label_fields": ["text_to_speak_orig"],
        "item_fields": ["image", "audio_orig"],
        "relationship_type": "GROUPS_WITH",
    },
    "writing": {
        "label_fields": ["hint_orig", "hint_en"],
        "item_fields": ["images"],
        "relationship_type": "GROUPS_WITH",
    },
}


def make_label_node(exercise: dict, label_fields: list[str]) -> dict | None:
    for field in label_fields:
        value = exercise.get(field)
        if value:
            return {
                "kind": field,
                "value": value,
            }
    return None


def make_item_nodes(exercise: dict, item_fields: list[str]) -> list[dict]:
    items = []

    for field in item_fields:
        value = exercise.get(field)

        if value is None:
            continue

        if isinstance(value, list):
            for item in value:
                if item:
                    items.append({
                        "kind": field,
                        "value": item,
                    })
        else:
            if value:
                items.append({
                    "kind": field,
                    "value": value,
                })

    return items


def extract_groups(base_dir: str) -> list[dict]:
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

                config = TYPE_CONFIG.get(exercise_type)
                if not config:
                    continue

                label = make_label_node(exercise, config["label_fields"])
                items = make_item_nodes(exercise, config["item_fields"])

                if not label:
                    continue

                if not items:
                    continue

                results.append({
                    "exercise_type": exercise_type,
                    "relationship_type": config["relationship_type"],
                    "label": label,
                    "items": items,
                })

    tqdm.write(f"[INFO] Extracted {len(results)} groups total")
    return results


def import_group(tx, item: dict):
    relationship_type = item["relationship_type"]

    query = f"""
    MERGE (label:ContentNode {{
        kind: $label_kind,
        value: $label_value
    }})
    WITH label
    UNWIND $items AS item
        MERGE (content:ContentNode {{
            kind: item.kind,
            value: item.value
        }})
        MERGE (label)-[r:{relationship_type} {{
            family: "GROUP",
            exercise_type: $exercise_type
        }}]->(content)
    """

    tx.run(
        query,
        label_kind=item["label"]["kind"],
        label_value=item["label"]["value"],
        items=item["items"],
        exercise_type=item["exercise_type"],
    )


def run_import(base_dir: str):
    verify_connection()
    groups = extract_groups(base_dir)

    if not groups:
        tqdm.write("[INFO] No groups to import")
        close_driver()
        return

    with driver.session(database=DATABASE) as session:
        for item in tqdm(groups, desc="Importing groups", unit="group"):
            session.execute_write(import_group, item)

    tqdm.write("[INFO] Import complete")
    close_driver()


if __name__ == "__main__":
    run_import(PATH)
