import os
from pathlib import Path
import json
from tqdm import tqdm
from database import driver, verify_connection, close_driver
from dotenv import load_dotenv

load_dotenv()

DATABASE = os.getenv("NEO4J_DATABASE")
PATH = "v2/01-cleaned_courses/en"
TYPE = "match_up"


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
                    })

    tqdm.write(f"[INFO] Extracted {len(results)} pairs total")
    return results


def import_match(tx, item: dict):
    tx.run(
        """
        MERGE (left:ContentNode {text: $left_text})
        MERGE (right:ContentNode {text: $right_text})
        MERGE (left)-[:MATCHES_WITH]->(right)
        """,
        left_text=item["left_text"],
        right_text=item["right_text"],
    )


def run_import(base_dir: str):
    verify_connection()
    pairs = extract_matchup_pairs(base_dir)

    if not pairs:
        tqdm.write("[INFO] No pairs to import")
        close_driver()
        return

    with driver.session(database=DATABASE) as session:
        for item in tqdm(pairs, desc="Importing pairs", unit="pair"):
            session.execute_write(import_match, item)

    tqdm.write("[INFO] Import complete")
    close_driver()


if __name__ == "__main__":
    run_import(PATH)
