"""
user/room_i18n.py
Langue des questions d'une room : chaque joueur voit les questions dans SA langue.

Les questions sont écrites dans la langue de l'hôte (colonne "lang"). Quand un joueur a choisi une autre langue
(Français / English / العربية), les questions sont traduites par l'IA (Groq) UNE SEULE FOIS par langue, puis
enregistrées dans la base (table room_question_i18n) : les autres joueurs de la même langue les retrouvent
instantanément. Le texte original est toujours gardé ; si la traduction est impossible (clé manquante, réseau...),
le joueur voit les questions dans la langue de l'hôte.
"""
import time

from i18n import LANGUES_IA
from user import questions_ai, rooms

RETRY_AFTER = 30                 # secondes avant de retenter une traduction qui a échoué
_echecs: dict = {}               # {(room_id, langue): heure du dernier échec}


def localize_questions(room_id: int, lang: str, allow_ai: bool = True) -> list[dict]:
    """Questions de la room dans la langue `lang` (code : fr / en / ar).
    Chaque question garde ses champs ("id", "kind", "answer"...) et reçoit en plus :
      "orig_question", "orig_reference" : le texte original ; "translated" : True si traduit.
    allow_ai = False : n'utilise que les traductions déjà enregistrées (jamais d'appel à l'IA)."""
    questions = rooms.list_questions(room_id)
    for q in questions:
        q.update(orig_question=q["question"], orig_reference=q["reference"], translated=False)
    a_traduire = [q for q in questions if q["lang"] != lang]
    if not a_traduire:
        return questions

    deja = rooms.get_translations(room_id, lang)
    manquantes = [q for q in a_traduire if q["id"] not in deja]
    cle = (room_id, lang)
    if (manquantes and allow_ai and time.time() - _echecs.get(cle, 0) > RETRY_AFTER):
        try:
            items = [{"id": q["id"], "question": q["question"], "choices": q["choices"],
                      "reference": q["reference"]} for q in manquantes]
            nouvelles = questions_ai.translate_questions(items, LANGUES_IA.get(lang, lang))
            if nouvelles:
                rooms.save_translations(lang, nouvelles)
                deja.update(nouvelles)
            if len(nouvelles) < len(manquantes):
                _echecs[cle] = time.time()
            else:
                _echecs.pop(cle, None)
        except Exception:                      # clé manquante, réseau, réponse illisible...
            _echecs[cle] = time.time()

    for q in a_traduire:
        tr = deja.get(q["id"])
        if tr:
            q.update(question=tr["question"], choices=tr["choices"], reference=tr["reference"], translated=True)
    return questions


def is_translation_missing(questions: list[dict], lang: str) -> bool:
    """True si au moins une question reste dans une autre langue que celle du joueur (traduction impossible)."""
    return any(q["lang"] != lang and not q["translated"] for q in questions)
