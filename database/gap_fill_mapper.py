from pathlib import Path
import json
from tqdm import tqdm
from database.database import driver, verify_connection, close_driver
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE = os.getenv("NEO4J_DATABASE")
PATH = "01-cleaned_courses"
TYPES = {"gap_fill_click", "gap_fill_multiple"}


# ── helpers ──────────────────────────────────────────────────────────────────

def extract_gap_fills(base_dir: str) -> list[dict]:
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

                full_text = exercise.get("full_text_orig")
                gap_sentence = exercise.get("gap_sentence_orig")

                if not full_text or not gap_sentence:
                    tqdm.write(
                        f"[SKIP] {exercise.get('exercise_id', '?')} "
                        f"({exercise_type}): missing full_text_orig or gap_sentence_orig"
                    )
                    continue

                # ── gap_fill_click: one correct_answer (string), options (list of strings)
                if exercise_type == "gap_fill_click":
                    correct = exercise.get("correct_answer")
                    if not correct:
                        tqdm.write(f"[SKIP] {exercise.get('exercise_id', '?')}: missing correct_answer")
                        continue

                    answers = [{"value": str(correct), "correct": True}]
                    for opt in exercise.get("options", []):
                        if opt:
                            answers.append({"value": str(opt), "correct": False})

                    results.append({
                        "exercise_type": exercise_type,
                        "full_text": full_text,
                        "gap_sentence": gap_sentence,
                        "answers": answers,
                    })

                # ── gap_fill_multiple: correct_answers[] and options[] are parallel arrays
                elif exercise_type == "gap_fill_multiple":
                    correct_answers = exercise.get("correct_answers", [])
                    options = exercise.get("options", [])

                    if not correct_answers:
                        tqdm.write(f"[SKIP] {exercise.get('exercise_id', '?')}: missing correct_answers")
                        continue

                    answers = []
                    for correct in correct_answers:
                        if correct:
                            answers.append({"value": str(correct), "correct": True})
                    for opt in options:
                        if opt:
                            answers.append({"value": str(opt), "correct": False})

                    if not answers:
                        continue

                    results.append({
                        "exercise_type": exercise_type,
                        "full_text": full_text,
                        "gap_sentence": gap_sentence,
                        "answers": answers,
                    })

    tqdm.write(f"[INFO] Extracted {len(results)} gap fill exercises total")
    return results


# ── import ────────────────────────────────────────────────────────────────────

def import_gap_fill(tx, item: dict):
    """
    Graph pattern:

        (source:ContentNode {kind: full_text_orig})
            -[:HAS_ITEM  {family: "LIST",     exercise_type, position: 0}]
            -> (gap:ContentNode {kind: gap_sentence_orig})

        (source:ContentNode)
            -[:HAS_ANSWER {family: "QUESTION", exercise_type, correct: true/false}]
            -> (answer:ContentNode {kind: "gap_answer"})

    Reuses the same relationship types as list_mapper and question_mapper
    so queries across families stay consistent.
    """
    tx.run(
        """
        MERGE (source:ContentNode {kind: "full_text_orig", value: $full_text})

        MERGE (gap:ContentNode {kind: "gap_sentence_orig", value: $gap_sentence})
        MERGE (source)-[:HAS_ITEM {
            family:        "LIST",
            exercise_type: $exercise_type,
            position:      0
        }]->(gap)

        WITH source
        UNWIND $answers AS answer
            MERGE (content:ContentNode {kind: "gap_answer", value: answer.value})
            MERGE (source)-[:HAS_ANSWER {
                family:        "QUESTION",
                exercise_type: $exercise_type,
                correct:       answer.correct
            }]->(content)
        """,
        full_text=item["full_text"],
        gap_sentence=item["gap_sentence"],
        answers=item["answers"],
        exercise_type=item["exercise_type"],
    )


def run_import(base_dir: str):
    verify_connection()
    gap_fills = extract_gap_fills(base_dir)

    if not gap_fills:
        tqdm.write("[INFO] No gap fill exercises to import")
        return

    with driver.session(database=DATABASE) as session:
        for item in tqdm(gap_fills, desc="Importing gap fills", unit="exercise"):
            session.execute_write(import_gap_fill, item)

    tqdm.write("[INFO] Import complete")


if __name__ == "__main__":
    raise SystemExit(run_import(PATH))
