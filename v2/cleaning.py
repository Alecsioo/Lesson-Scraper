import json
import re
import os

def clean_tags(text):
    """
    Rimuove i tag proprietari [k], [h], i tag HTML e normalizza gli spazi.
    Utile per visualizzare il testo pulito in UI senza artefatti di formattazione.
    """
    if not isinstance(text, str): return text
    # Sostituisce i tag principali e i break lineari con uno spazio
    text = re.sub(r'\[/?k\]|\[/?h\]|<b>|</b>|<i>|</i>|<u>|</u>|<br>|<br/>', ' ', text)
    # Rimuove spazi doppi/multipli e spazi iniziali/finali
    return ' '.join(text.split()).strip()

def extract_tokens(text):
    """Estrae una lista di tutte le parole o frasi racchiuse tra i tag [k]...[/k]."""
    if not text: return []
    return re.findall(r'\[k\](.*?)\[/k\]', text)

def extract_gap(text):
    """Estrae solo la prima occorrenza trovata tra i tag [k], utile per gap singoli."""
    match = re.search(r'\[k\](.*?)\[/k\]', text)
    return match.group(1) if match else None

def get_gap_sentence(text):
    """Sostituisce le parole marcate con [k] con un segnaposto ____ per creare l'esercizio."""
    if not text: return None
    return re.sub(r'(\[k\].*?\[/k\])+', '____', text)

def process_file(input_path):
    """
    Funzione principale di parsing del JSON originale.
    Mappa i dati grezzi in una struttura pulita e semplificata per il database/UI.
    """
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # lesson_id estratto direttamente dal campo id radice
    lesson_id = data.get("id", "unknown_id")
    trans = data.get("translation_map", {})
    ents = data.get("entity_map", {})

    # Helper interni per recuperare testi e media mappati negli oggetti originali
    def get_s(s_id): return trans.get(s_id, {}).get("en", {}).get("value", "")
    def get_s_audio(s_id): return trans.get(s_id, {}).get("en", {}).get("audio")
    def get_e_text(e_id): return get_s(ents.get(e_id, {}).get("phrase"))
    def get_e_example(e_id): return get_s(ents.get(e_id, {}).get("keyphrase"))
    
    def get_e_media(e_id):
        """Recupera URL di immagini, audio e video (selezionando la qualità migliore disponibile)."""
        e = ents.get(e_id, {})
        p_id = e.get("phrase")
        v_urls = e.get("video_urls", {}).get("mp4", {})
        video_link = v_urls.get("L") or v_urls.get("M") or v_urls.get("S")
        
        return {
            "image": e.get("image") if e.get("image") else None,
            "audio": trans.get(p_id, {}).get("en", {}).get("audio") if p_id else None,
            "video": video_link 
        }

    # Struttura di output della lezione
    output = {
        "lesson_id": lesson_id,
        "lesson_title": clean_tags(get_s(data["content"].get("title"))),
        "lesson_description": clean_tags(get_s(data["content"].get("description"))),
        "units": []
    }

    def extract_exercises(structure_list):
        """
        Naviga ricorsivamente la struttura del JSON per trovare oggetti di classe 'exercise'.
        Gestisce diversi tipi (t) estraendo i campi specifici per ognuno.
        """
        found = []
        for item in structure_list:
            if item.get("class") == "exercise":
                t = item.get("type")
                c = item.get("content", {})
                ex_out = {
                    "exercise_id": item.get("id"),
                    "type": t,
                    "instructions": clean_tags(get_s(c.get("instructions"))),
                    "grammar_tag": c.get("grammar_topic_id")
                }

                # --- Tipo: singleEntity (Flashcards) e listenRepeat ---
                if t in ["singleEntity", "listenRepeat"]:
                    mid = c.get("entity") or c.get("phrase")
                    if mid:
                        ex_out["text"] = clean_tags(get_e_text(mid))
                        ex_out["example_text"] = clean_tags(get_e_example(mid))
                        ex_out.update(get_e_media(mid))

                # --- Tipo: Comprensione Video o Testo ---
                elif t in ["comprehension_video", "comprehension_text"]:
                    mid = c.get("entity")
                    ex_out["content_title"] = clean_tags(get_s(c.get("title")))
                    ex_out["content_body"] = clean_tags(get_e_text(mid))
                    ex_out.update(get_e_media(mid))

                # --- Tipo: listenRepeat (sovrascrittura specifica se necessario) ---
                elif t == "listenRepeat":
                    mid = c.get("phrase")
                    if mid:
                        ex_out["full_text"] = clean_tags(get_e_text(mid))
                        ex_out.update(get_e_media(mid))
                
                # --- Tipo: Riconoscimento Vocale ---
                if t == "speech_rec":
                    mid = c.get("question")
                    ex_out["text_to_speak"] = clean_tags(get_e_text(mid))
                    ex_out.update(get_e_media(mid))

                # --- Tipo: Phrase Builder (metti in ordine) ---
                elif t == "24":
                    raw = get_e_text(c.get("sentence"))
                    ex_out["full_text"] = clean_tags(raw)
                    ex_out["tokens"] = extract_tokens(raw) or clean_tags(raw).split()
                    ex_out.update(get_e_media(c.get("sentence")))

                # --- Tipo: Selezione Multipla / Highlight (Coppie o liste) ---
                elif t == "28":
                    raw_sentences = [get_s(s_id) for s_id in c.get("sentences", [])]
                    processed_items = []
                    for raw in raw_sentences:
                        correct_tokens = re.findall(r'\[h\](.*?)\[/h\]', raw)
                        clean_line = raw.replace('[h]', '').replace('[/h]', '')
                        all_tokens = clean_line.split()
                        distractors = [t for t in all_tokens if t not in correct_tokens]
                        processed_items.append({
                            "all_options": all_tokens,
                            "correct_options": correct_tokens,
                            "distractors": distractors
                        })
                    ex_out["instructions"] = clean_tags(get_s(c.get("instructions")))
                    ex_out["selectable_data"] = processed_items

                # --- Tipo: Tabelle Spiegazione (multi-colonna) ---
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

                # --- Tipo: Tip (box grammaticale semplice) ---
                elif t == "tip":
                    ex_out["tip_title"] = clean_tags(get_s(c.get("title")))
                    ex_out["tip_text"] = clean_tags(get_s(c.get("text")))
                    ex_out["examples"] = [{"text": clean_tags(get_s(sid)), "audio": get_s_audio(sid)} for sid in c.get("examples", [])]

                # --- Tipo: Vero/Falso (con o senza immagine) ---
                if t in ["23", "23i"]:
                    ex_out["statement_title"] = clean_tags(get_s(c.get("title")))
                    ex_out["context_text"] = clean_tags(get_e_text(c.get("question")))
                    ex_out["is_correct_true"] = c.get("answer")
                    ex_out.update(get_e_media(c.get("question")))

                # --- Tipo: Fill the Gap con Scelta (Multiple Choice) ---
                elif t in ["26a_aud", "26a_img"]:
                    mid = c.get("sentence")
                    raw = get_e_text(mid)
                    ex_out["full_text"] = clean_tags(raw)
                    ex_out["gap_sentence"] = clean_tags(get_gap_sentence(raw))
                    ex_out["correct_answer"] = extract_gap(raw)
                    ex_out["options"] = [clean_tags(get_e_text(d)) for d in c.get("distractors", [])]
                    ex_out.update(get_e_media(mid))

                # --- Tipo: Fill the Gap Typing (Spelling lettere) ---
                elif t == "fill-gap-typing":
                    main_id = c.get("entity")
                    raw_text = get_e_text(main_id)
                    ex_out["full_text"] = clean_tags(raw_text)
                    ex_out["letters"] = extract_tokens(raw_text)
                    ex_out["gap_sentence"] = clean_tags(get_gap_sentence(raw_text))
                    ex_out.update(get_e_media(main_id))

                # --- Tipo: Multiple Choice Question Classica ---
                elif t == "multipleChoiceQuestion":
                    sol_id = c.get("solution")
                    ex_out["solution_text"] = clean_tags(get_e_text(sol_id))
                    ex_out["options"] = [clean_tags(get_e_text(d)) for d in c.get("distractors", [])]
                    ex_out.update(get_e_media(sol_id))

                # --- Tipo: MatchUp (abbinamento sinistra/destra) ---
                elif t == "matchUpEntity":
                    ex_out["pairs"] = [
                        {"left": clean_tags(get_e_text(l)), "right": clean_tags(get_e_text(r))}
                        for l, r in zip(c.get("entities", []), c.get("matchingEntities", []))
                    ]

                # --- Tipo: Fill the Gap (Testo standard) ---
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

                # --- Tipo: Produzione Libera (Writing) ---
                elif t == "writing":
                    ex_out["hint"] = clean_tags(get_s(c.get("hint")))
                    ex_out["word_counter"] = c.get("wordCounter")
                    ex_out["images"] = c.get("images", [])

                # --- Tipo: Typing Puro (Tastiera, dettato o immagine) ---
                if t in ["27a", "27a_img", "27a_aud"]:
                    mid = c.get("sentence")
                    raw = get_e_text(mid)
                    ex_out["full_text"] = clean_tags(raw)
                    ex_out["gap_sentence"] = clean_tags(get_gap_sentence(raw))
                    ex_out["correct_answers_to_type"] = extract_tokens(raw)
                    ex_out.update(get_e_media(mid))
                    if c.get("hint"): ex_out["hint"] = clean_tags(get_s(c.get("hint")))

                # Aggiunta spiegazione finale dell'esercizio (se presente)
                explanation = get_s(c.get("correctAnswer"))
                if explanation: ex_out["explanation"] = clean_tags(explanation)
                found.append(ex_out)
            
            # Se l'item contiene una sottostruttura, continua la ricerca degli esercizi
            elif "structure" in item:
                found.extend(extract_exercises(item["structure"]))
        return found

    # Iterazione sulle Unit della lezione (Grammar, Vocabulary, Checkpoint, etc.)
    for unit in data.get("structure", []):
        u_out = {
            "unit_type": unit.get("type"),
            "points": unit.get("points"),
            "estimated_seconds": unit.get("time_estimate"),
            "grammar_ids": unit.get("content", {}).get("grammar_topic_ids", []),
            "exercises": extract_exercises(unit.get("structure", []))
        }
        output["units"].append(u_out)

    return output

def migrate_courses(source_root, target_root):
    """
    Scansiona ricorsivamente la cartella sorgente, processa ogni JSON trovato
    e salva l'output nella cartella target mantenendo la stessa gerarchia di directory.
    """
    for root, dirs, files in os.walk(source_root):
        for file in files:
            if file.endswith(".json"):
                input_file_path = os.path.join(root, file)
                
                # Mappa il percorso relativo per ricreare le cartelle (es: en/A1/...)
                rel_path = os.path.relpath(root, source_root)
                target_dir = os.path.join(target_root, rel_path)
                
                if not os.path.exists(target_dir):
                    os.makedirs(target_dir)

                try:
                    # Parsing del file e scrittura del nuovo JSON pulito
                    cleaned_data = process_file(input_file_path)
                    target_file_path = os.path.join(target_dir, file)
                    
                    with open(target_file_path, 'w', encoding='utf-8') as f:
                        json.dump(cleaned_data, f, indent=2, ensure_ascii=False)
                    
                    print(f"Cleaned: {file}")
                except Exception as e:
                    print(f"Errore in {input_file_path}: {e}")

# --- Configurazione Percorsi ---
SOURCE = "00-raw_courses"
TARGET = "01-cleaned_courses"

# Avvio del processo
migrate_courses(SOURCE, TARGET)