from pathlib import Path
import json
from tqdm import tqdm
from database.database import driver, verify_connection
from dotenv import load_dotenv
import os
import re

load_dotenv()

DATABASE = os.getenv("NEO4J_DATABASE")
PATH = "01-cleaned_courses"
TYPES = {"phrase_builder", "word_spelling", "gap_fill_typing", "highlight_selection"}


# ── helpers ──────────────────────────────────────────────────────────────────

def extract_items(exercise: dict, exercise_type: str) -> list[str] | None:
    """
    Return the ordered list of text values to link as a chain.

    phrase_builder  -> tokens[]   (plain strings)
    word_spelling   -> letters[]  (plain strings)
    gap_fill_typing -> [full_text_orig, gap_sentence_orig]
                       (two nodes: complete sentence -> gapped version)
    """
    if exercise_type == "phrase_builder":
        tokens = exercise.get("tokens", [])
        return [{"text": t, "isTarget": True} for t in tokens if t]

    if exercise_type == "gap_fill_typing":
        gap_sentence = exercise.get("gap_sentence_orig", "")
        solution = exercise.get("correct_answers", [""])[0] 
        
        if gap_sentence:
            parts = re.findall(r"_+|[¿?¡!\wáéíóúüñ]+", gap_sentence)
            
            tokens_with_metadata = []
            for p in parts:
                if p.startswith('_'):
                    tokens_with_metadata.append({"text": solution, "isTarget": True})
                else:
                    tokens_with_metadata.append({"text": p, "isTarget": False})
            
            return tokens_with_metadata if tokens_with_metadata else None

    if exercise_type == "word_spelling":
        full = exercise.get("full_text_orig", "")
        gap = exercise.get("gap_sentence_orig", "")
        
        if full and gap:
            full_chain = []
            for f_char, g_char in zip(full, gap):
                full_chain.append({
                    "text": f_char,
                    "isTarget": (g_char == "_") 
                })
            return full_chain
        
    if exercise_type == "highlight_selection":
        full_chain = []
        blocks = exercise.get("selectable_data", [])
        
        for i, block in enumerate(blocks):
            correct_set = set(block.get("correct_options", []))
            
            for word in block.get("all_options", []):
                if word is None: continue
                full_chain.append({
                    "text": str(word),
                    "isTarget": word in correct_set
                })
            
            if i < len(blocks) - 1:
                full_chain.append({"text": "\n", "isTarget": False})
                
        return full_chain
            
    return None


# ── extraction ────────────────────────────────────────────────────────────────

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

                items = extract_items(exercise, exercise_type)
                if not items:
                    tqdm.write(
                        f"[SKIP] {exercise.get('exercise_id', '?')} "
                        f"({exercise_type}): missing items"
                    )
                    continue

                results.append({
                    "exercise_type": exercise_type, 
                    "items": items, 
                    "exercise_id": exercise.get("exercise_id") 
                })

    tqdm.write(f"[INFO] Extracted {len(results)} lists total")
    return results


# ── import ────────────────────────────────────────────────────────────────────

def import_list(tx, item: dict):
    nodes_data = item["items"]
    ex_id = item["exercise_id"]
    ex_type = item["exercise_type"]

    for i in range(len(nodes_data) - 1):
        tx.run(
            """
            MERGE (a:ContentNode {text: $text_a})
            MERGE (b:ContentNode {text: $text_b})
            MERGE (a)-[r:NEXT {exercise_id: $ex_id, idx: $idx}]->(b)
            
            // 3. Imposta le proprietà sulla relazione
            SET r.family = "LIST",
                r.exercise_type = $ex_type,
                r.a_isTarget = $a_target,
                r.b_isTarget = $b_target
            """,
            text_a=nodes_data[i]["text"],
            text_b=nodes_data[i+1]["text"],
            a_target=nodes_data[i]["isTarget"],
            b_target=nodes_data[i+1]["isTarget"],
            ex_id=ex_id,
            ex_type=ex_type,
            idx=i
        )

def run_import(base_dir: str):
    verify_connection()
    lists = extract_lists(base_dir)

    if not lists:
        tqdm.write("[INFO] No lists to import")
        return

    with driver.session(database=DATABASE) as session:
        for item in tqdm(lists, desc="Importing lists", unit="list"):
            session.execute_write(import_list, item)

    tqdm.write("[INFO] Import complete")


if __name__ == "__main__":
    raise SystemExit(run_import(PATH))