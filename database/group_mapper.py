import os
from pathlib import Path
import json
from tqdm import tqdm
from database.database import driver, verify_connection, close_driver
from dotenv import load_dotenv

load_dotenv()

DATABASE = os.getenv("NEO4J_DATABASE")

PATH = "01-cleaned_courses"
FAMILY = "GROUP"
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
    },
    "dialogue": {
        "label_fields": ["text_orig", "text_en"],
        "item_fields": ["audio_orig", "gap_sentence_orig", "correct_answer"],
    },
    "flashcard": {
        "label_fields": ["text_orig", "text_en"],
        "item_fields": ["audio_orig", "audio_en", "image", "video"],
    },
    "speech_recognition": {
        "label_fields": ["text_to_speak_orig"],
        "item_fields": ["image", "audio_orig"],
    },
    "writing": {
        "label_fields": ["hint_orig", "hint_en"],
        "item_fields": ["images"],
    },
}

# Expected structure relative to PATH:
# <language> / <course_pack_type> / <level> / <chapter> / <lesson>.json
PATH_LANGUAGE_IDX = 0
PATH_LEVEL_IDX = 2
PATH_MIN_DEPTH = 5


def _parse_level(raw: str) -> str:
    """'pack_level_it_a1' -> 'A1'"""
    return raw.rsplit("_", 1)[-1].upper()


def _extract_path_metadata(path: Path, base_path: Path) -> tuple[str, str] | None:
    parts = path.relative_to(base_path).parts
    if len(parts) < PATH_MIN_DEPTH:
        tqdm.write(f"[WARN] Unexpected path depth ({len(parts)}): {path}")
        return None
    language = parts[PATH_LANGUAGE_IDX]
    level = _parse_level(parts[PATH_LEVEL_IDX])
    return language, level


def make_label_node(exercise: dict, label_fields: list[str]) -> dict | None:
    for field in label_fields:
        value = exercise.get(field)
        if value:
            return {"value": value}
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
                    items.append({"value": item})
        else:
            if value:
                items.append({"value": value})

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
        metadata = _extract_path_metadata(path, base_path)
        if not metadata:
            continue

        language, level = metadata

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

                if not label or not items:
                    continue

                results.append({
                    "exercise_type": exercise_type,
                    "label": label,
                    "items": items,
                    "language": language,
                    "level": level,
                })

    tqdm.write(f"[INFO] Extracted {len(results)} groups total")
    return results


def import_group(tx, item: dict):
    tx.run(
        """
        MERGE (lang:Language {code: $language})
        MERGE (level:Level {name: $level})
        MERGE (family:Family {name: $family})

        MERGE (label:ContentNode {value: $label_value})

        MERGE (label)-[:IS_OF_FAMILY]->(family)
        MERGE (label)-[:IS_FOR_LANGUAGE]->(lang)
        MERGE (label)-[:IS_OF_LEVEL]->(level)

        WITH label
        UNWIND $items AS item
            MERGE (content:ContentNode {value: item.value})
            MERGE (label)-[:GROUPS_WITH]->(content)
        """,
        label_value=item["label"]["value"],
        items=item["items"],
        exercise_type=item["exercise_type"],
        language=item["language"],
        level=item["level"],
        family=FAMILY,
    )


def run_import(base_dir: str):
    verify_connection()
    groups = extract_groups(base_dir)

    if not groups:
        tqdm.write("[INFO] No groups to import")
        return

    with driver.session(database=DATABASE) as session:
        for item in tqdm(groups, desc="Importing groups", unit="group"):
            session.execute_write(import_group, item)

    tqdm.write("[INFO] Import complete")


if __name__ == "__main__":
    run_import(PATH)