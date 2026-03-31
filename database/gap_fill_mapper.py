import json
import re
from pathlib import Path
from tqdm import tqdm
from database.database import driver, verify_connection, close_driver

DATABASE = "neo4j"
PATH = "v2/01-cleaned_courses/es"
TYPES = {"gap_fill_click", "gap_fill_multiple"}

# ── helpers ──────────────────────────────────────────────────────────────────

def extract_items(exercise: dict, ex_type: str):
    gap_sentence = exercise.get("gap_sentence_orig", "")
    if not gap_sentence: return None

    if ex_type == "gap_fill_click":
        correct_list = [exercise.get("correct_answer", "")]
    else:
        correct_list = exercise.get("correct_answers", [])
    
    all_distractors = exercise.get("options", [])

    parts = re.findall(r"_+|[¿?¡!\wáéíóúüñ]+", gap_sentence)
    
    tokens = []
    gap_counter = 0 
    
    for p in parts:
        if p.startswith('_'):
            if gap_counter < len(correct_list):
                sol = correct_list[gap_counter]
                
                tokens.append({
                    "text": sol,
                    "isTarget": True,
                    "options": all_distractors 
                })
                gap_counter += 1
        else:
            tokens.append({
                "text": p,
                "isTarget": False,
                "options": []
            })
    return tokens

# ── extraction ────────────────────────────────────────────────────────────────

def extract_all_gap_fills(base_dir: str) -> list[dict]:
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

                items = extract_items(exercise, ex_type)
                if items:
                    results.append({
                        "exercise_id": exercise.get("exercise_id"),
                        "exercise_type": ex_type,
                        "tokens": items
                    })
    return results

# ── import ────────────────────────────────────────────────────────────────────

def import_gap_fill(tx, item: dict):
    ex_id = item["exercise_id"]
    ex_type = item["exercise_type"]
    tokens = item["tokens"]

    for i in range(len(tokens) - 1):
        tx.run("""
            MERGE (a:ContentNode {text: $text_a})
            MERGE (b:ContentNode {text: $text_b})
            WITH a, b
            MERGE (a)-[r:NEXT {exercise_id: $ex_id, idx: $idx}]->(b)
            SET r.family = "LIST",
                r.exercise_type = $ex_type,
                r.a_isTarget = $a_target,
                r.b_isTarget = $b_target
            """,
            text_a=tokens[i]["text"],
            text_b=tokens[i+1]["text"],
            a_target=tokens[i]["isTarget"],
            b_target=tokens[i+1]["isTarget"],
            ex_id=ex_id, ex_type=ex_type, idx=i
        )

    for token in tokens:
        if token["isTarget"] and token["options"]:
            for opt in token["options"]:
                tx.run("""
                    MATCH (q:ContentNode {text: $gap_text})
                    MERGE (o:ContentNode {text: $opt_text})
                    MERGE (q)-[r:HAS_ANSWER {exercise_id: $ex_id}]->(o)
                    SET r.family = "QUESTION",
                        r.correct = false
                    """,
                    gap_text=token["text"],
                    opt_text=opt,
                    ex_id=ex_id
                )

def run_import(base_dir: str):
    verify_connection()
    gap_fills = extract_all_gap_fills(base_dir)

    if not gap_fills:
        tqdm.write("[INFO] No gap fill exercises to import")
        return

    with driver.session(database=DATABASE) as session:
        for item in tqdm(gap_fills, desc="Importing gap fills"):
            session.execute_write(import_gap_fill, item)

    tqdm.write("[INFO] Import complete")

if __name__ == "__main__":
    raise SystemExit(run_import(PATH))