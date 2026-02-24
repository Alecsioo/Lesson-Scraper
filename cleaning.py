import json
import re
import os

def clean_tags(text):
    """Pulisce i tag HTML e i marcatori interni [k]."""
    if not isinstance(text, str): return text
    return re.sub(r'\[/?k\]|<b>|</b>|<i>|</i>', '', text)

def extract_gap(text):
    """Estrae la parola corretta tra i tag [k]."""
    match = re.search(r'\[k\](.*?)\[/k\]', text)
    return match.group(1) if match else None


def extract_tokens(text):
    """Estrae le singole parole/frasi racchiuse tra i tag [k]."""
    if not text: return []
    return re.findall(r'\[k\](.*?)\[/k\]', text)

def get_gap_sentence(text):
    """Crea la frase con il 'buco' ____."""
    if not text: return None
    return re.sub(r'\[k\].*?\[/k\]', '____', text)

def process_file(input_path, output_path):
    """Logica di elaborazione del singolo file JSON."""
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    trans = data.get("translation_map", {})
    ents = data.get("entity_map", {})

    def get_s(s_id):
        return trans.get(s_id, {}).get("en", {}).get("value", "")

    def get_e_text(e_id):
        return get_s(ents.get(e_id, {}).get("phrase"))

    def get_s_audio(s_id):
        return trans.get(s_id, {}).get("en", {}).get("audio")

    def get_e_media(e_id):
        e = ents.get(e_id, {})
        p_id = e.get("phrase")
        return {
            "image": e.get("image") or None,
            "audio": trans.get(p_id, {}).get("en", {}).get("audio") if p_id else None
        }

    output = {
        "lesson_title": clean_tags(get_s(data["content"].get("title"))),
        "lesson_description": clean_tags(get_s(data["content"].get("description"))),
        "units": []
    }

    for unit in data.get("structure", []):
        u_out = {
            "unit_type": unit.get("type"),
            "points": unit.get("points"),
            "estimated_seconds": unit.get("time_estimate"),
            "exercises": []
        }
        
        for act in unit.get("structure", []):
            for ex in act.get("structure", []):
                t = ex.get("type")
                c = ex.get("content", {})
                ex_out = {
                    "exercise_id": ex.get("id"),
                    "type": t,
                    "instructions": clean_tags(get_s(c.get("instructions")))
                }

                # Gestione MatchUp
                if t == "matchUpEntity":
                    ex_out["pairs"] = [
                        {"left": clean_tags(get_e_text(l)), "right": clean_tags(get_e_text(r))}
                        for l, r in zip(c.get("entities", []), c.get("matchingEntities", []))
                    ]

                # Gestione Tip Table
                elif t == "tip_table":
                    ex_out["table_title"] = clean_tags(get_s(c.get("text")))
                    rows = []
                    ex_dict = c.get("examples", {})
                    for r_idx in sorted(ex_dict.keys(), key=int):
                        row = []
                        for c_idx in sorted(ex_dict[r_idx].keys(), key=int):
                            s_id = ex_dict[r_idx][c_idx]
                            row.append({
                                "text": clean_tags(get_s(s_id)),
                                "audio": get_s_audio(s_id)
                            })
                        rows.append(row)
                    ex_out["table_data"] = rows

                elif t == "fill-gap-typing":
                    main_id = c.get("entity")
                    raw_text = get_e_text(main_id)
                    ex_out["full_text"] = clean_tags(raw_text)
                    ex_out["letters"] = extract_tokens(raw_text)
                    ex_out["gap_sentence"] = clean_tags(get_gap_sentence(raw_text))
                    ex_out.update(get_e_media(main_id))
                
                # PHRASE BUILDER 
                elif t == "24":
                    raw_text = get_e_text(c.get("sentence"))
                    tokens = extract_tokens(raw_text)
                    # Fallback se mancano i tag [k]
                    if not tokens:
                        tokens = clean_tags(raw_text).split()
                    
                    ex_out["full_text"] = clean_tags(raw_text)
                    ex_out["tokens"] = tokens
                    ex_out.update(get_e_media(c.get("sentence")))

                # Gestione Writing
                elif t == "writing":
                    ex_out["hint"] = clean_tags(get_s(c.get("hint")))
                    ex_out["word_counter"] = c.get("wordCounter")
                    ex_out["images"] = c.get("images", [])
                
                elif t == "singleEntity":
                    main_id = c.get("entity")
                    if main_id:
                        ex_out["text"] = clean_tags(get_e_text(main_id))
                        ex_out.update(get_e_media(main_id)) # Qui recuperiamo audio e immagine

                elif t == "multipleChoiceQuestion":
                    sol_id = c.get("solution")
                    ex_out["solution_text"] = clean_tags(get_e_text(sol_id))
                    ex_out["options"] = [clean_tags(get_e_text(d)) for d in c.get("distractors", [])]
                    ex_out.update(get_e_media(sol_id))

                elif t == "26a_img":
                    main_id = c.get("sentence")
                    raw = get_e_text(main_id)
                    ex_out["full_text"] = clean_tags(raw)
                    ex_out["gap_sentence"] = clean_tags(get_gap_sentence(raw))
                    ex_out["correct_answer"] = extract_gap(raw) 
                    ex_out["options"] = [clean_tags(get_e_text(d)) for d in c.get("distractors", [])]
                    ex_out.update(get_e_media(main_id))
                
                # --- 10. MULTIPLE SELECTION / HIGHLIGHT (28) ---
                elif t == "28":
                    raw_sentences = [get_s(s_id) for s_id in c.get("sentences", [])]
                    
                    token_pairs = []
                    for raw in raw_sentences:
                        correct_match = re.search(r'\[h\](.*?)\[/h\]', raw)
                        correct_val = correct_match.group(1) if correct_match else ""
                        
                        other_val = re.sub(r'\[h\].*?\[/h\]', '', raw).strip()
                        
                        token_pairs.append({
                            "tokens": [correct_val, other_val],
                            "correct_token": correct_val
                        })
                    
                    ex_out["instructions"] = clean_tags(get_s(c.get("instructions")))
                    ex_out["selectable_pairs"] = token_pairs
        
                #  GESTIONE GAP FILL MULTIPLI
                elif t in ["26a", "26b"]:
                    main_id = c.get("sentence") or c.get("entity")
                    raw_text = get_e_text(main_id)
                    
                    if raw_text:
                        ex_out["full_text"] = clean_tags(raw_text)
                        ex_out["gap_sentence"] = clean_tags(get_gap_sentence(raw_text))
                        
                        correct_answers = extract_tokens(raw_text)
                        
                        if t == "fill-gap-typing":
                            ex_out["letters"] = correct_answers
                        else:
                            ex_out["correct_answers"] = correct_answers
                        
                        ex_out["options"] = [clean_tags(get_e_text(d)) for d in c.get("distractors", [])]
                        ex_out.update(get_e_media(main_id))

                # Gestione True/False
                elif t == "23i":
                    ex_out["statement_title"] = clean_tags(get_s(c.get("title")))
                    ex_out["context_text"] = clean_tags(get_e_text(c.get("question")))
                    ex_out["is_correct_true"] = c.get("answer")
                    ex_out.update(get_e_media(c.get("question")))

                elif t == "27a_aud":
                    raw_text = get_e_text(c.get("sentence"))
                    if raw_text:
                        ex_out["full_text"] = clean_tags(raw_text)
                        
                        if "[k]" in raw_text:
                            ex_out["gap_sentence"] = clean_tags(get_gap_sentence(raw_text))
                            ex_out["correct_answer"] = extract_gap(raw_text)
                        else:
                            ex_out["gap_sentence"] = None
                            ex_out["correct_answer"] = clean_tags(raw_text)
                            
                        ex_out.update(get_e_media(c.get("sentence")))

                explanation = get_s(c.get("correctAnswer"))
                if explanation:
                    ex_out["explanation"] = clean_tags(explanation)

                u_out["exercises"].append(ex_out)
        
        output["units"].append(u_out)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

def process_directory(folder_path):
    """Scansiona la cartella e processa tutti i file .json."""
    # Crea la sottocartella 'cleaned' se non esiste per tenere tutto in ordine
    output_folder = os.path.join(folder_path, "cleaned_results")
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    for filename in os.listdir(folder_path):
        if filename.endswith(".json"):
            input_file = os.path.join(folder_path, filename)
            output_file = os.path.join(output_folder, f"cleaned_{filename}")
            
            try:
                process_file(input_file, output_file)
                print(f"Successo: {filename} -> cleaned_{filename}")
            except Exception as e:
                print(f"Errore nel processare {filename}: {e}")

# --- ESECUZIONE ---
# Inserisci qui il percorso della tua cartella (usa '.' per la cartella corrente)
process_directory('lessons/ch03_Chapter_3_All_about_me')