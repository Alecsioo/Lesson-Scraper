from pathlib import Path
import json
from tqdm import tqdm
from database.database import driver, verify_connection, close_driver

DATABASE = "neo4j"
PATH = "01-cleaned_courses/es"
TYPES = {"true_false", "multiple_choice", "highlight_selection"}


def make_question_node(exercise: dict, exercise_type: str) -> dict | None:
    """
    Return the ContentNode that represents the question stem.

    multiple_choice    -> solution_text_orig is the *answer*, not the question.
                          The question stem lives in `instructions`.
    true_false         -> context_text_orig  (the sentence to judge as T/F)
    highlight_selection-> instructions  (the selection prompt)
    """
    if exercise_type == "multiple_choice":
        # `instructions` holds the actual question text
        value = exercise.get("instructions")
        return {"kind": "instructions", "value": value} if value else None

    if exercise_type == "true_false":
        value = exercise.get("context_text_orig") or exercise.get("statement_title_en")
        kind = "context_text_orig" if exercise.get("context_text_orig") else "statement_title_en"
        return {"kind": kind, "value": value} if value else None

    if exercise_type == "highlight_selection":
        value = exercise.get("instructions")
        return {"kind": "instructions", "value": value} if value else None

    return None


def make_answer_nodes(exercise: dict, exercise_type: str) -> list[dict]:
    """
    Return answer dicts: {kind, value, correct}.

    multiple_choice:
        - solution_text_orig  -> correct=True
        - options[]           -> each string, correct=False

    true_false:
        - synthesise two nodes "true" / "false"
        - `is_correct` tells which one is correct

    highlight_selection:
        - selectable_data[] can hold multiple sentence blocks
        - within each block: correct_options -> correct=True, distractors -> correct=False
    """
    if exercise_type == "multiple_choice":
        answers = []

        correct_value = exercise.get("solution_text_orig")
        if correct_value:
            answers.append({"kind": "solution_text_orig", "value": correct_value, "correct": True})

        for option in exercise.get("options", []):
            if option:
                answers.append({"kind": "option", "value": str(option), "correct": False})

        return answers

    if exercise_type == "true_false":
        is_correct = exercise.get("is_correct")
        if is_correct is None:
            return []
        return [
            {"kind": "tf_option", "value": "true", "correct": bool(is_correct)},
            {"kind": "tf_option", "value": "false", "correct": not bool(is_correct)},
        ]

    if exercise_type == "highlight_selection":
        answers = []

        for block in exercise.get("selectable_data", []):
            if not isinstance(block, dict):
                continue

            for word in block.get("correct_options", []):
                if word:
                    answers.append({"kind": "selection", "value": str(word), "correct": True})

            for word in block.get("distractors", []):
                if word:
                    answers.append({"kind": "selection", "value": str(word), "correct": False})

        return answers

    return []


def extract_questions(base_dir: str) -> list[dict]:
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

                question = make_question_node(exercise, exercise_type)
                answers = make_answer_nodes(exercise, exercise_type)

                if not question or not answers:
                    tqdm.write(
                        f"[SKIP] {exercise.get('exercise_id', '?')} "
                        f"({exercise_type}): missing question or answers"
                    )
                    continue

                results.append(
                    {
                        "exercise_type": exercise_type,
                        "question": question,
                        "answers": answers,
                    }
                )

    tqdm.write(f"[INFO] Extracted {len(results)} questions total")
    return results


def import_question(tx, item: dict):
    if item["exercise_type"] == "true_false":
        tx.run(
            """
            MERGE (question:ContentNode {
                kind:  $question_kind,
                value: $question_value
            })
            SET question.is_correct = $is_correct,
                question.family      = "QUESTION",
                question.exercise_type = "true_false"
            """,
            question_kind=item["question"]["kind"],
            question_value=item["question"]["value"],
            is_correct=item["answers"][0]["correct"],
        )
        return

    tx.run(
        """
        MERGE (question:ContentNode {kind: $question_kind, value: $question_value})
        WITH question
        UNWIND $answers AS answer
            MERGE (content:ContentNode {kind: answer.kind, value: answer.value})
            MERGE (question)-[:HAS_ANSWER {
                family:        "QUESTION",
                exercise_type: $exercise_type,
                correct:       answer.correct
            }]->(content)
        """,
        question_kind=item["question"]["kind"],
        question_value=item["question"]["value"],
        answers=item["answers"],
        exercise_type=item["exercise_type"],
    )


def run_import(base_dir: str):
    verify_connection()
    questions = extract_questions(base_dir)

    if not questions:
        tqdm.write("[INFO] No questions to import")
        return

    with driver.session(database=DATABASE) as session:
        for item in tqdm(questions, desc="Importing questions", unit="question"):
            session.execute_write(import_question, item)

    tqdm.write("[INFO] Import complete")


if __name__ == "__main__":
    raise SystemExit(run_import(PATH))
