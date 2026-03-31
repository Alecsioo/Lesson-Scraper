import os
from pathlib import Path
import json
from tqdm import tqdm
from database.database import driver, verify_connection, close_driver
from dotenv import load_dotenv

load_dotenv()

DATABASE = os.getenv("NEO4J_DATABASE")

PATH = "01-cleaned_courses"
TYPE = "match_up"
FAMILY = "PAIR"

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


def extract_matchup_pairs(base_dir: str) -> list[dict]:
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
                if exercise.get("type") != TYPE:
                    continue

                for pair in exercise.get("pairs", []):
                    left_text = pair.get("left_orig")
                    right_text = pair.get("right_orig")

                    if not left_text or not right_text:
                        continue

                    results.append({
                        "left_text": left_text,
                        "right_text": right_text,
                        "language": language,
                        "level": level,
                    })

    tqdm.write(f"[INFO] Extracted {len(results)} pairs total")
    return results


def import_match(tx, item: dict):
    tx.run(
        """
        MERGE (lang:Language {code: $language})
        MERGE (level:Level {name: $level})
        MERGE (family:Family {name: $family})

        MERGE (left:ContentNode {text: $left_text})
        MERGE (right:ContentNode {text: $right_text})

        MERGE (left)-[:MATCHES_WITH]->(right)

        MERGE (left)-[:IS_OF_FAMILY]->(family)

        MERGE (left)-[:IS_FOR_LANGUAGE]->(lang)
        MERGE (right)-[:IS_FOR_LANGUAGE]->(lang)

        MERGE (left)-[:IS_OF_LEVEL]->(level)
        MERGE (right)-[:IS_OF_LEVEL]->(level)
        """,
        left_text=item["left_text"],
        right_text=item["right_text"],
        language=item["language"],
        level=item["level"],
        family=FAMILY,
    )


def run_import(base_dir: str):
    verify_connection()
    pairs = extract_matchup_pairs(base_dir)

    if not pairs:
        tqdm.write("[INFO] No pairs to import")
        return

    with driver.session(database=DATABASE) as session:
        for item in tqdm(pairs, desc="Importing pairs", unit="pair"):
            session.execute_write(import_match, item)

    tqdm.write("[INFO] Import complete")


if __name__ == "__main__":
    run_import(PATH)
