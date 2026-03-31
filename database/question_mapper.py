import json
import re
from pathlib import Path
from tqdm import tqdm
from database.database import driver, verify_connection, close_driver
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE = os.getenv("NEO4J_DATABASE")
PATH = "01-cleaned_courses"
TYPES = {"true_false", "multiple_choice"}

# ── helpers ──────────────────────────────────────────────────────────────────

def make_question_text(exercise: dict, exercise_type: str) -> str | None:
    if exercise_type == "true_false":
        return {
            "context": exercise.get("context_text_orig"),
            "statement": exercise.get("statement_title_en")
        }
    return exercise.get("instructions")

def make_answers(exercise: dict, exercise_type: str) -> list[dict] | None:
    """
    Ritorna una lista di dizionari con metadati per le risposte.
    """
    if exercise_type == "multiple_choice":
        answers = []
        isCorrect = exercise.get("solution_text_orig")
        if isCorrect:
            answers.append({"text": isCorrect, "isCorrect": True})
        for i, opt in enumerate(exercise.get("options", []), 1):
            if opt:
                answers.append({"text": str(opt), "isCorrect": False})
        return answers

    return None

# ── extraction ────────────────────────────────────────────────────────────────

def extract_questions(base_dir: str) -> list[dict]:
    results = []
    base_path = Path(base_dir)

    json_files = list(base_path.rglob("*.json"))
    for path in tqdm(json_files, desc="Scanning JSON files"):
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        for unit in data.get("units", []):
            for exercise in unit.get("exercises", []):
                ex_type = exercise.get("type")
                if ex_type not in TYPES: continue

                q_text = make_question_text(exercise, ex_type)
                ex_id = exercise.get("exercise_id")
                
                if not q_text or not ex_id: continue

                if ex_type == "true_false":
                    results.append({
                        "exercise_id": ex_id,
                        "exercise_type": ex_type,
                        "question_text": q_text,
                        "is_correct": bool(exercise.get("is_correct")),
                        "answers": None
                    })
                else:
                    answers = make_answers(exercise, ex_type)
                    if answers:
                        results.append({
                            "exercise_id": ex_id,
                            "exercise_type": ex_type,
                            "question_text": q_text,
                            "answers": answers
                        })
    return results

# ── import ────────────────────────────────────────────────────────────────────

def import_question(tx, item: dict):
    ex_id = item["exercise_id"]
    ex_type = item["exercise_type"]
    
    if ex_type == "true_false":
        q_data = item["question_text"]
        root_text = f"{q_data['context']}\n\n{q_data['statement']}"
        
        is_correct = item["is_correct"]
        answers = [
            {"text": "True", "isCorrect": is_correct},
            {"text": "False", "isCorrect": not is_correct}
        ]
    else:
        root_text = item["question_text"]
        answers = item["answers"]

    tx.run("MERGE (q:ContentNode {text: $root_text})", root_text=root_text)

    for ans in answers:
        tx.run("""
            MATCH (q:ContentNode {text: $root_text})
            MERGE (a:ContentNode {text: $ans_text})
            MERGE (q)-[r:HAS_ANSWER {exercise_id: $ex_id}]->(a)
            SET r.family = "QUESTION",
                r.exercise_type = $ex_type,
                r.isCorrect = $isCorrect
            """, 
            root_text=root_text,
            ans_text=ans["text"],
            ex_id=ex_id,
            ex_type=ex_type,
            isCorrect=ans["isCorrect"]
        )

def run_import(base_dir: str):
    verify_connection()
    questions = extract_questions(base_dir)

    if not questions:
        tqdm.write("[INFO] No questions to import")
        return

    with driver.session(database=DATABASE) as session:
        for item in tqdm(questions, desc="Importing"):
            session.execute_write(import_question, item)

    tqdm.write("[INFO] Import complete")

if __name__ == "__main__":
    raise SystemExit(run_import(PATH))
