"""
user/rooms.py
Logique des "rooms" (salles de jeu) : SQLite uniquement, sans Streamlit.
Les tables sont créées dans la même base que les comptes (users.db).

Une room = un code à 5 caractères que l'hôte partage ; les autres joueurs le tapent pour entrer.
Statuts : "waiting" (salle d'attente) -> "playing" (partie lancée) -> "finished" (partie terminée),
ou "closed" (annulée avant le lancement). Une room n'est JAMAIS supprimée : elle reste enregistrée
(questions, joueurs, réponses, scores) et chaque joueur la retrouve à sa reconnexion et dans « Mes rooms ».

Visibilité :
  - publique : apparaît dans la liste « Rooms disponibles » (une fois ses questions toutes prêtes) et y
               RESTE tant que l'hôte ne l'a pas fermée ou lancée, même s'il se déconnecte ;
  - privée   : n'apparaît pas dans la liste, on ne peut entrer qu'avec le code.

Questions : chaque room a ses questions (QCM à 4 propositions), ajoutées par l'hôte
à la main ou par l'IA. La partie ne peut être lancée que lorsque toutes les questions sont prêtes.

Partie SYNCHRONISÉE : tous les joueurs voient la même question en même temps.
  - l'hôte choisit à la création le temps de réponse par question (time_per_question, en secondes) ;
  - quand le temps est écoulé (ou quand l'hôte clique sur « Terminer la question »), la question passe en phase
    « résultats » : on voit la réponse et le pourcentage de chaque joueur, et l'hôte peut modifier les scores ;
  - la question SUIVANTE n'arrive que lorsque l'hôte clique sur « Question suivante » (advance_question) ;
  - les joueurs qui n'ont pas répondu reçoivent 0 % ;
  - si un joueur quitte la partie (ou ferme son navigateur), la partie est mise EN PAUSE (temps arrêté) jusqu'à
    son retour ; l'hôte peut aussi continuer sans lui (skip_absent).
Une réponse est VRAIE si son pourcentage est strictement supérieur à 50 %.

Au lancement, un COMPTE À REBOURS (COUNTDOWN_SECONDS) précède la première question.

MODE PARIS (wager_mode, choisi par l'hôte à la création) :
  - avant chaque question (sauf la dernière) le joueur choisit une mise de 1 à N-1 points (N = nombre de
    questions) ; une mise ne peut servir QU'UNE SEULE FOIS dans la partie (elle devient désactivée ensuite) ;
    points gagnés = mise x pourcentage / 100, rien n'est perdu si la réponse est fausse ;
  - la DERNIÈRE question est la question finale : le joueur mise 0, S ou 2xS points (S = son score actuel,
    10 au minimum) ; si sa réponse est fausse (pourcentage <= 50), il PERD sa mise (le score peut devenir négatif).
Sans mode paris : 1 point par question x pourcentage / 100, comme avant.
"""
import json
import secrets
import sqlite3
import time
from contextlib import closing

from authentifications import DB_PATH

# Lettres/chiffres sans ambiguïté (pas de 0/O, 1/I)
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 5

WAITING = "waiting"
PLAYING = "playing"
FINISHED = "finished"   # tous les joueurs ont répondu à toutes les questions : la room est gardée en historique
CLOSED = "closed"       # annulée avant le lancement

MIN_PLAYERS, MAX_PLAYERS = 2, 10
MIN_QUESTIONS, MAX_QUESTIONS = 5, 30
NB_CHOICES = 4
MAX_OPEN_ROOMS_PER_HOST = 5   # nombre maximum de rooms ouvertes (en attente) par hôte

MIN_TIME, MAX_TIME, DEFAULT_TIME = 5, 300, 30   # temps de réponse par question (secondes), choisi par l'hôte
NO_TIME = 0                   # time_per_question = 0 : PARTIE SANS LIMITE DE TEMPS (les résultats s'affichent quand
                              # tous les joueurs ont répondu, ou quand l'hôte clique sur « Terminer la question »)
CLOSE_GRACE = 4               # secondes de marge après la fin du temps avant d'afficher les résultats
                              # (laisse le temps à une réponse envoyée à la dernière seconde d'être corrigée)
ABSENT_AFTER = 15             # secondes sans signe de vie d'un joueur -> il est considéré comme sorti (pause)
SUBMIT_TOLERANCE = 1.5        # secondes de tolérance pour une réponse envoyée juste à la fin du temps
SEUIL_VRAI = 50               # une réponse est VRAIE si son pourcentage est > 50
AUTO_REVIEW_IF_ALL_ANSWERED = False  # True : les résultats s'affichent dès que TOUS les joueurs ont répondu
COUNTDOWN_SECONDS = 6         # compte à rebours « La partie commence dans... » au lancement
ANSWERING, REVIEW = "answering", "review"   # phases d'une question : on répond / on voit les résultats


def init_rooms_db() -> None:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                host_id INTEGER NOT NULL,
                max_players INTEGER NOT NULL,
                nb_questions INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'waiting',
                is_public INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                time_per_question INTEGER NOT NULL DEFAULT 30,   -- secondes par question (choisi par l'hôte)
                current_q INTEGER NOT NULL DEFAULT 0,            -- index (0, 1, 2...) de la question en cours
                q_started_at REAL,                               -- heure (epoch) de début de la question en cours
                phase TEXT NOT NULL DEFAULT 'answering',         -- 'answering' (on répond) ou 'review' (résultats)
                paused_at REAL,                                  -- heure de début de la pause (joueur sorti), sinon NULL
                wager_mode INTEGER NOT NULL DEFAULT 0            -- 1 : mode paris (mises de points)
            )
        """)
        # Migration : si la table existait déjà SANS la colonne "is_public", on l'ajoute
        colonnes = [ligne[1] for ligne in conn.execute("PRAGMA table_info(rooms)").fetchall()]
        if "is_public" not in colonnes:
            conn.execute("ALTER TABLE rooms ADD COLUMN is_public INTEGER NOT NULL DEFAULT 1")
        # Migration : partie synchronisée (temps par question, question en cours)
        if "current_q" not in colonnes:
            conn.execute("ALTER TABLE rooms ADD COLUMN time_per_question INTEGER NOT NULL DEFAULT 30")
            conn.execute("ALTER TABLE rooms ADD COLUMN current_q INTEGER NOT NULL DEFAULT 0")
            conn.execute("ALTER TABLE rooms ADD COLUMN q_started_at REAL")
            # les anciennes parties (chacun à son rythme) ne sont pas compatibles : on les termine
            conn.execute("UPDATE rooms SET status = ? WHERE status = ?", (FINISHED, PLAYING))
        colonnes = [ligne[1] for ligne in conn.execute("PRAGMA table_info(rooms)").fetchall()]
        if "phase" not in colonnes:
            conn.execute("ALTER TABLE rooms ADD COLUMN phase TEXT NOT NULL DEFAULT 'answering'")
            conn.execute("ALTER TABLE rooms ADD COLUMN paused_at REAL")
        if "wager_mode" not in colonnes:
            conn.execute("ALTER TABLE rooms ADD COLUMN wager_mode INTEGER NOT NULL DEFAULT 0")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS room_players (
                room_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                last_seen REAL,                  -- dernier signe de vie (epoch) pendant la partie
                skipped INTEGER NOT NULL DEFAULT 0,   -- 1 : l'hôte a décidé de continuer sans ce joueur absent
                PRIMARY KEY (room_id, user_id)
            )
        """)
        colonnes_j = [l[1] for l in conn.execute("PRAGMA table_info(room_players)").fetchall()]
        if "last_seen" not in colonnes_j:
            conn.execute("ALTER TABLE room_players ADD COLUMN last_seen REAL")
        if "skipped" not in colonnes_j:
            conn.execute("ALTER TABLE room_players ADD COLUMN skipped INTEGER NOT NULL DEFAULT 0")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS room_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                choices TEXT NOT NULL,          -- liste JSON de 4 propositions (vide pour une question libre)
                answer INTEGER NOT NULL,        -- index (0 à 3) de la bonne proposition
                kind TEXT NOT NULL DEFAULT 'qcm',        -- 'qcm' ou 'open' (réponse libre)
                reference TEXT NOT NULL DEFAULT '',      -- réponse attendue (questions libres)
                lang TEXT NOT NULL DEFAULT 'fr'          -- langue (fr / en / ar) dans laquelle la question est écrite
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS room_question_i18n (
                question_id INTEGER NOT NULL,
                lang TEXT NOT NULL,
                question TEXT NOT NULL,
                choices TEXT NOT NULL,
                reference TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (question_id, lang)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS room_answers (
                room_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                question_id INTEGER NOT NULL,
                choice INTEGER NOT NULL,        -- proposition choisie (0 à 3)
                is_correct INTEGER NOT NULL,    -- 1 si bonne réponse
                text_answer TEXT NOT NULL DEFAULT '',    -- réponse écrite (questions libres)
                score REAL,                              -- pourcentage de bonne réponse (0 à 100)
                comment TEXT NOT NULL DEFAULT '',        -- commentaire de la correction
                wager INTEGER,                           -- mise du joueur (mode paris), sinon NULL
                auto_score REAL,                         -- pourcentage de la correction automatique
                host_verdict INTEGER,                    -- décision de l'hôte : NULL = aucune, 1 = correct, 0 = faux
                PRIMARY KEY (room_id, user_id, question_id)
            )
        """)
        # Migration : anciennes bases créées sans les colonnes des questions libres
        for table, ajouts in (
            ("room_questions", [("kind", "TEXT NOT NULL DEFAULT 'qcm'"),
                                ("reference", "TEXT NOT NULL DEFAULT ''"),
                                ("lang", "TEXT NOT NULL DEFAULT 'fr'")]),
            ("room_answers", [("text_answer", "TEXT NOT NULL DEFAULT ''"), ("score", "REAL"),
                              ("comment", "TEXT NOT NULL DEFAULT ''"),
                              ("auto_score", "REAL"), ("host_verdict", "INTEGER"), ("wager", "INTEGER")]),
        ):
            existantes = [l[1] for l in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            for nom, definition in ajouts:
                if nom not in existantes:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {nom} {definition}")
        conn.execute("UPDATE room_answers SET score = is_correct * 100 WHERE score IS NULL")
        conn.execute("UPDATE room_answers SET auto_score = score WHERE auto_score IS NULL")
        conn.commit()


def _new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def create_room(host_id: int, host_name: str, name: str = "",
                max_players: int = 6, nb_questions: int = 10,
                is_public: bool = True,
                time_per_question: int = DEFAULT_TIME,
                wager_mode: bool = False) -> tuple[bool, str, str | None]:
    """Crée une room et y place l'hôte. Retourne (ok, message, code)."""
    if not (MIN_PLAYERS <= max_players <= MAX_PLAYERS):
        return False, f"Le nombre de joueurs doit être entre {MIN_PLAYERS} et {MAX_PLAYERS}.", None
    if not (MIN_QUESTIONS <= nb_questions <= MAX_QUESTIONS):
        return False, f"Le nombre de questions doit être entre {MIN_QUESTIONS} et {MAX_QUESTIONS}.", None
    if time_per_question != NO_TIME and not (MIN_TIME <= time_per_question <= MAX_TIME):
        return False, f"Le temps par question doit être entre {MIN_TIME} et {MAX_TIME} secondes.", None
    name = name.strip()[:40] or f"Room de {host_name}"

    with closing(sqlite3.connect(DB_PATH)) as conn:
        # Seuls les BROUILLONS de cet hôte (rooms en attente dont les questions ne sont pas toutes prêtes :
        # invisibles et injouables) sont fermés. Les rooms prêtes restent ouvertes et visibles dans « Jouer » :
        # créer une nouvelle room ne ferme plus les autres.
        conn.execute(
            "UPDATE rooms SET status = ? WHERE host_id = ? AND status = ? AND "
            "(SELECT COUNT(*) FROM room_questions q WHERE q.room_id = rooms.id) < rooms.nb_questions",
            (CLOSED, host_id, WAITING),
        )
        ouvertes = conn.execute("SELECT COUNT(*) FROM rooms WHERE host_id = ? AND status = ?",
                                (host_id, WAITING)).fetchone()[0]
        if ouvertes >= MAX_OPEN_ROOMS_PER_HOST:
            return False, f"Tu as déjà {ouvertes} rooms ouvertes : ferme-en une avant d'en créer une autre.", None
        for _ in range(20):                       # on réessaie si le code existe déjà
            code = _new_code()
            try:
                cur = conn.execute(
                    "INSERT INTO rooms (code, name, host_id, max_players, nb_questions, is_public, "
                    "time_per_question, wager_mode) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (code, name, host_id, max_players, nb_questions, int(is_public), int(time_per_question),
                     int(wager_mode)),
                )
                break
            except sqlite3.IntegrityError:
                continue
        else:
            return False, "Impossible de générer un code, réessaie.", None
        conn.execute("INSERT INTO room_players (room_id, user_id, username) VALUES (?, ?, ?)",
                     (cur.lastrowid, host_id, host_name))
        conn.commit()
    return True, "Room créée.", code


def get_room(code: str):
    """Retourne la room (dict avec la liste des joueurs) ou None."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute(
            "SELECT id, code, name, host_id, max_players, nb_questions, status, is_public, "
            "time_per_question, current_q, q_started_at, phase, paused_at, wager_mode FROM rooms WHERE code = ?", (code.strip().upper(),)
        ).fetchone()
        if not row:
            return None
        players = conn.execute(
            "SELECT user_id, username, last_seen, skipped FROM room_players WHERE room_id = ? ORDER BY rowid",
            (row[0],)
        ).fetchall()
    room = {
        "id": row[0], "code": row[1], "name": row[2], "host_id": row[3],
        "max_players": row[4], "nb_questions": row[5], "status": row[6],
        "is_public": bool(row[7]),
        "time_per_question": row[8], "current_q": row[9], "q_started_at": row[10],
        "phase": row[11], "paused_at": row[12], "wager_mode": bool(row[13]),
        "players": [{"user_id": p[0], "username": p[1], "last_seen": p[2], "skipped": bool(p[3])}
                    for p in players],
    }
    room["host_name"] = next((p["username"] for p in room["players"] if p["user_id"] == row[3]), "?")
    return room


def join_room(code: str, user_id: int, username: str) -> tuple[bool, str]:
    """Rejoint une room avec son code (fonctionne aussi pour les rooms privées)."""
    room = get_room(code)
    if room is None or room["status"] == CLOSED:
        return False, "Aucune room avec ce code."
    if any(p["user_id"] == user_id for p in room["players"]):
        return True, "Tu es déjà dans cette room."
    if room["status"] != WAITING:
        return False, "La partie a déjà commencé."
    if len(room["players"]) >= room["max_players"]:
        return False, "La room est pleine."

    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("INSERT OR IGNORE INTO room_players (room_id, user_id, username) VALUES (?, ?, ?)",
                     (room["id"], user_id, username))
        conn.commit()
    return True, f"Tu as rejoint « {room['name']} »."


def leave_room(code: str, user_id: int) -> tuple[bool, str]:
    """Un joueur quitte la room.
    - room en attente : l'hôte l'annule (fermée), un joueur en sort ;
    - partie lancée ou terminée : RIEN n'est supprimé, la progression reste enregistrée
      et le joueur peut revenir dans la room quand il veut."""
    room = get_room(code)
    if room is None:
        return False, "Room introuvable."
    if room["status"] != WAITING:
        return True, "Tu as quitté la room."
    with closing(sqlite3.connect(DB_PATH)) as conn:
        if room["host_id"] == user_id:
            conn.execute("UPDATE rooms SET status = ? WHERE id = ?", (CLOSED, room["id"]))
            message = "Room fermée."
        else:
            conn.execute("DELETE FROM room_players WHERE room_id = ? AND user_id = ?",
                         (room["id"], user_id))
            message = "Tu as quitté la room."
        conn.commit()
    return True, message


def leave_all_rooms(user_id: int) -> None:
    """Déconnexion : le joueur quitte automatiquement toutes ses rooms.
    - room en attente : il en sort (si c'est l'hôte, la room est fermée) ;
    - partie en cours : il est marqué absent (la partie se met en pause), ses réponses restent enregistrées."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        lignes = conn.execute(
            "SELECT r.code, r.status FROM rooms r JOIN room_players p ON p.room_id = r.id "
            "WHERE p.user_id = ? AND r.status IN (?, ?)", (user_id, WAITING, PLAYING)).fetchall()
    for code, statut in lignes:
        if statut == WAITING:
            leave_room(code, user_id)
        else:
            mark_left(code, user_id)


def start_room(code: str, user_id: int) -> tuple[bool, str]:
    """Seul l'hôte peut lancer la partie, une fois toutes les questions prêtes."""
    room = get_room(code)
    if room is None or room["status"] == CLOSED:
        return False, "Room introuvable."
    if room["host_id"] != user_id:
        return False, "Seul l'hôte peut lancer la partie."
    if room["status"] != WAITING:
        return False, "La partie a déjà commencé."
    nb = count_questions(room["id"])
    if nb < room["nb_questions"]:
        return False, f"Il manque des questions ({nb}/{room['nb_questions']})."
    with closing(sqlite3.connect(DB_PATH)) as conn:
        maintenant = time.time()
        # la 1re question commence APRÈS le compte à rebours (q_started_at est dans le futur)
        conn.execute("UPDATE rooms SET status = ?, current_q = 0, q_started_at = ?, phase = ?, "
                     "paused_at = NULL WHERE id = ?",
                     (PLAYING, maintenant + COUNTDOWN_SECONDS, ANSWERING, room["id"]))
        conn.execute("UPDATE room_players SET last_seen = ?, skipped = 0 WHERE room_id = ?",
                     (maintenant, room["id"]))
        conn.commit()
    return True, "Partie lancée !"


def active_room_of(user_id: int):
    """Code de la room active (en attente ou en cours) de ce joueur, sinon None."""
    close_stale_rooms()
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute(
            "SELECT r.code FROM rooms r JOIN room_players p ON p.room_id = r.id "
            "WHERE p.user_id = ? AND r.status IN (?, ?) ORDER BY r.id DESC LIMIT 1",
            (user_id, WAITING, PLAYING),
        ).fetchone()
    return row[0] if row else None


STALE_HOURS = 6            # une room restée en attente plus longtemps est fermée automatiquement
STALE_PLAYING_HOURS = 24   # une partie lancée depuis plus longtemps est considérée comme terminée
PUBLIC_ROOM_MAX_HOURS = None   # None = une room publique prête reste visible TOUJOURS (jusqu'à ce que l'hôte
                               # la ferme ou lance la partie). Mets par ex. 72 pour la fermer après 3 jours.


def close_stale_rooms(hours: int = STALE_HOURS) -> None:
    """Ferme les rooms en attente depuis trop longtemps (hôte parti sans la fermer)
    et termine les parties lancées depuis plus de 24 h (les résultats restent enregistrés)."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        # Brouillons et rooms PRIVÉES en attente depuis trop longtemps : fermés.
        # Une room PUBLIQUE prête n'expire pas (voir PUBLIC_ROOM_MAX_HOURS) : elle reste visible dans « Jouer »
        # même si l'hôte s'est déconnecté.
        conn.execute(
            "UPDATE rooms SET status = ? WHERE status = ? AND created_at < datetime('now', ?) "
            "AND (is_public = 0 OR "
            "(SELECT COUNT(*) FROM room_questions q WHERE q.room_id = rooms.id) < rooms.nb_questions)",
            (CLOSED, WAITING, f"-{int(hours)} hours"),
        )
        if PUBLIC_ROOM_MAX_HOURS is not None:
            conn.execute(
                "UPDATE rooms SET status = ? WHERE status = ? AND is_public = 1 "
                "AND created_at < datetime('now', ?)",
                (CLOSED, WAITING, f"-{int(PUBLIC_ROOM_MAX_HOURS)} hours"),
            )
        conn.execute(
            "UPDATE rooms SET status = ? WHERE status = ? AND created_at < datetime('now', ?)",
            (FINISHED, PLAYING, f"-{int(STALE_PLAYING_HOURS)} hours"),
        )
        conn.commit()


def list_open_rooms(limit: int = 50) -> list[dict]:
    """Rooms PUBLIQUES en attente de joueurs et dont toutes les questions sont prêtes."""
    close_stale_rooms()
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            """
            SELECT r.code, r.name, r.max_players, r.nb_questions, r.created_at,
                   (SELECT COUNT(*) FROM room_players p WHERE p.room_id = r.id),
                   (SELECT p.username FROM room_players p
                     WHERE p.room_id = r.id AND p.user_id = r.host_id)
            FROM rooms r
            WHERE r.status = ? AND r.is_public = 1
              AND (SELECT COUNT(*) FROM room_questions q WHERE q.room_id = r.id) >= r.nb_questions
            ORDER BY r.id DESC
            LIMIT ?
            """,
            (WAITING, limit),
        ).fetchall()
    return [
        {"code": r[0], "name": r[1], "max_players": r[2], "nb_questions": r[3],
         "created_at": r[4], "nb_players": r[5], "host_name": r[6] or "?"}
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# Questions de la room
# --------------------------------------------------------------------------- #
def _clean_question(q: dict) -> tuple[dict | None, str]:
    """Vérifie et nettoie une question. Retourne (question, erreur).
    QCM  : {"question", "choices": [4 propositions], "answer": index}
    Libre: {"kind": "open", "question", "reference": réponse attendue}"""
    texte = str(q.get("question", "")).strip()
    if not texte:
        return None, "La question est vide."

    if q.get("kind") == "open":
        reference = str(q.get("reference", "")).strip()
        if not reference:
            return None, "La réponse attendue est vide."
        return {"kind": "open", "question": texte[:300], "choices": [], "answer": 0,
                "reference": reference[:200]}, ""

    choix = [str(c).strip() for c in (q.get("choices") or [])]
    reponse = q.get("answer")
    if len(choix) != NB_CHOICES or any(not c for c in choix):
        return None, f"Il faut {NB_CHOICES} propositions non vides."
    if len({c.lower() for c in choix}) != NB_CHOICES:
        return None, "Les propositions doivent être différentes."
    if not isinstance(reponse, int) or not (0 <= reponse < NB_CHOICES):
        return None, "La bonne réponse est invalide."
    return {"kind": "qcm", "question": texte[:300], "choices": [c[:120] for c in choix],
            "answer": reponse, "reference": ""}, ""


def count_questions(room_id: int) -> int:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        return conn.execute("SELECT COUNT(*) FROM room_questions WHERE room_id = ?",
                            (room_id,)).fetchone()[0]


def list_questions(room_id: int) -> list[dict]:
    """Questions de la room : [{"id", "question", "choices", "answer", "kind", "reference"}, ...]."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            "SELECT id, question, choices, answer, kind, reference, lang FROM room_questions "
            "WHERE room_id = ? ORDER BY id",
            (room_id,),
        ).fetchall()
    return [{"id": r[0], "question": r[1], "choices": json.loads(r[2]), "answer": r[3],
             "kind": r[4], "reference": r[5], "lang": r[6]} for r in rows]


def get_translations(room_id: int, lang: str) -> dict:
    """Traductions déjà faites des questions de la room dans la langue `lang` : {id_question: {...}}."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            "SELECT t.question_id, t.question, t.choices, t.reference FROM room_question_i18n t "
            "JOIN room_questions q ON q.id = t.question_id WHERE q.room_id = ? AND t.lang = ?",
            (room_id, lang),
        ).fetchall()
    return {r[0]: {"question": r[1], "choices": json.loads(r[2]), "reference": r[3]} for r in rows}


def save_translations(lang: str, items: dict) -> None:
    """Enregistre des traductions : items = {id_question: {"question", "choices", "reference"}}."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        for qid, v in items.items():
            conn.execute(
                "INSERT OR REPLACE INTO room_question_i18n (question_id, lang, question, choices, reference) "
                "VALUES (?, ?, ?, ?, ?)",
                (qid, lang, v["question"], json.dumps(v["choices"], ensure_ascii=False), v["reference"]),
            )
        conn.commit()


def add_questions(code: str, user_id: int, questions: list[dict],
                  lang: str = "fr") -> tuple[bool, str, int]:
    """Ajoute des questions à la room (hôte seulement, avant le lancement). `lang` = langue des questions
    (fr / en / ar) : chaque joueur les verra traduites dans SA langue.
    On s'arrête quand la room a son nombre de questions. Retourne (ok, message, nb_ajoutées)."""
    room = get_room(code)
    if room is None or room["status"] != WAITING:
        return False, "Room introuvable ou déjà lancée.", 0
    if room["host_id"] != user_id:
        return False, "Seul l'hôte peut modifier les questions.", 0

    ajoutees, erreur = 0, ""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        deja = conn.execute("SELECT COUNT(*) FROM room_questions WHERE room_id = ?",
                            (room["id"],)).fetchone()[0]
        place = room["nb_questions"] - deja
        if place <= 0:
            return False, "La room a déjà toutes ses questions.", 0
        for q in questions:
            if ajoutees >= place:
                break
            propre, err = _clean_question(q)
            if propre is None:
                erreur = err
                continue
            conn.execute(
                "INSERT INTO room_questions (room_id, question, choices, answer, kind, reference, lang) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (room["id"], propre["question"], json.dumps(propre["choices"], ensure_ascii=False),
                 propre["answer"], propre["kind"], propre["reference"], lang),
            )
            ajoutees += 1
        conn.commit()

    if ajoutees == 0:
        return False, erreur or "Aucune question valide.", 0
    return True, f"{ajoutees} question(s) ajoutée(s).", ajoutees


def delete_question(code: str, user_id: int, question_id: int) -> tuple[bool, str]:
    room = get_room(code)
    if room is None or room["status"] != WAITING:
        return False, "Room introuvable ou déjà lancée."
    if room["host_id"] != user_id:
        return False, "Seul l'hôte peut modifier les questions."
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("DELETE FROM room_questions WHERE id = ? AND room_id = ?",
                     (question_id, room["id"]))
        conn.commit()
    return True, "Question supprimée."


# --------------------------------------------------------------------------- #
# Réponses et classement (pendant la partie)
# --------------------------------------------------------------------------- #
def _check_player(room, user_id: int) -> str:
    """Retourne un message d'erreur, ou "" si le joueur peut répondre."""
    if room is None or room["status"] != PLAYING:
        return "La partie n'est pas en cours."
    if not any(p["user_id"] == user_id for p in room["players"]):
        return "Tu ne fais pas partie de cette partie."
    return ""


def _check_window(conn, room, question_id: int, submitted_at: float | None) -> str:
    """La réponse doit concerner la question EN COURS et arriver avant la fin du temps.
    submitted_at = heure du clic du joueur (la correction par l'IA peut durer quelques secondes)."""
    if room["phase"] != ANSWERING:
        return "Temps écoulé : la question est terminée."
    if room["paused_at"]:
        return "La partie est en pause (un joueur est sorti)."
    index = conn.execute("SELECT COUNT(*) FROM room_questions WHERE room_id = ? AND id < ?",
                         (room["id"], question_id)).fetchone()[0]
    if index != room["current_q"]:
        return "Temps écoulé : la question est terminée."
    if room["q_started_at"] and time.time() < room["q_started_at"] - 0.5:
        return "La partie n'a pas encore commencé."
    debut = room["q_started_at"] or 0
    envoye = submitted_at if submitted_at is not None else time.time()
    if has_timer(room) and envoye > debut + room["time_per_question"] + SUBMIT_TOLERANCE:
        return "Temps écoulé : la question est terminée."
    return ""


def submit_answer(code: str, user_id: int, question_id: int, choice: int,
                  submitted_at: float | None = None, wager: int | None = None) -> tuple[bool, str, bool]:
    """Enregistre la réponse d'un joueur à un QCM. Retourne (ok, message, bonne_réponse)."""
    room = sync_room(code)
    erreur = _check_player(room, user_id)
    if erreur:
        return False, erreur, False
    if not isinstance(choice, int) or not (0 <= choice < NB_CHOICES):
        return False, "La bonne réponse est invalide.", False

    with closing(sqlite3.connect(DB_PATH)) as conn:
        q = conn.execute("SELECT answer, kind FROM room_questions WHERE id = ? AND room_id = ?",
                         (question_id, room["id"])).fetchone()
        if q is None or q[1] != "qcm":
            return False, "Question introuvable.", False
        erreur = _check_window(conn, room, question_id, submitted_at)
        if erreur:
            return False, erreur, False
        erreur, wager = _check_wager(conn, room, user_id, question_id, wager)
        if erreur:
            return False, erreur, False
        correcte = int(choice == q[0])
        cur = conn.execute(
            "INSERT OR IGNORE INTO room_answers "
            "(room_id, user_id, question_id, choice, is_correct, score, auto_score, wager) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (room["id"], user_id, question_id, choice, correcte, correcte * 100, correcte * 100, wager),
        )
        conn.commit()
    if cur.rowcount == 0:
        return False, "Tu as déjà répondu à cette question.", False
    _review_if_all_answered(room["code"])
    return True, "", bool(correcte)


def submit_open_answer(code: str, user_id: int, question_id: int, text: str,
                       percent: float, comment: str = "",
                       submitted_at: float | None = None, wager: int | None = None) -> tuple[bool, str]:
    """Enregistre la réponse écrite d'un joueur, avec le pourcentage de la correction automatique (0 à 100).
    La réponse est vraie si percent > 50."""
    room = sync_room(code)
    erreur = _check_player(room, user_id)
    if erreur:
        return False, erreur
    text = (text or "").strip()
    if not text:
        return False, "Ta réponse est vide."
    percent = max(0.0, min(100.0, float(percent)))

    with closing(sqlite3.connect(DB_PATH)) as conn:
        q = conn.execute("SELECT kind FROM room_questions WHERE id = ? AND room_id = ?",
                         (question_id, room["id"])).fetchone()
        if q is None or q[0] != "open":
            return False, "Question introuvable."
        erreur = _check_window(conn, room, question_id, submitted_at)
        if erreur:
            return False, erreur
        erreur, wager = _check_wager(conn, room, user_id, question_id, wager)
        if erreur:
            return False, erreur
        cur = conn.execute(
            "INSERT OR IGNORE INTO room_answers "
            "(room_id, user_id, question_id, choice, is_correct, text_answer, score, auto_score, comment, wager) "
            "VALUES (?, ?, ?, -1, ?, ?, ?, ?, ?, ?)",
            (room["id"], user_id, question_id, int(percent > SEUIL_VRAI), text[:300], percent, percent,
             (comment or "")[:300], wager),
        )
        conn.commit()
    if cur.rowcount == 0:
        return False, "Tu as déjà répondu à cette question."
    _review_if_all_answered(room["code"])
    return True, ""


# --------------------------------------------------------------------------- #
# Mode paris : mises, points
# --------------------------------------------------------------------------- #
def answer_points(wager_mode: bool, is_final: bool, wager, score) -> float:
    """Points rapportés par UNE réponse.
    - sans mode paris : pourcentage / 100 (1 point maximum par question) ;
    - mode paris, question normale : mise x pourcentage / 100 (une réponse fausse ne fait rien perdre) ;
    - mode paris, question FINALE : mise x pourcentage / 100 si la réponse est vraie (> 50 %), sinon on PERD la mise."""
    score = score or 0
    if not wager_mode:
        return score / 100
    mise = wager or 0
    if is_final:
        return mise * score / 100 if score > SEUIL_VRAI else -float(mise)
    return mise * score / 100


def _final_question_id(conn, room_id: int):
    row = conn.execute("SELECT MAX(id) FROM room_questions WHERE room_id = ?", (room_id,)).fetchone()
    return row[0] if row else None


def _points_by_player(conn, room_id: int) -> dict:
    """{user_id: [points, nombre de réponses]} pour la room."""
    wm = bool(conn.execute("SELECT wager_mode FROM rooms WHERE id = ?", (room_id,)).fetchone()[0])
    finale = _final_question_id(conn, room_id)
    out: dict = {}
    for uid, qid, score, mise in conn.execute(
            "SELECT user_id, question_id, COALESCE(score, is_correct * 100), wager FROM room_answers "
            "WHERE room_id = ?", (room_id,)):
        cumul = out.setdefault(uid, [0.0, 0])
        cumul[0] += answer_points(wm, qid == finale, mise, score)
        cumul[1] += 1
    return out


def player_points(room_id: int, user_id: int) -> float:
    with closing(sqlite3.connect(DB_PATH)) as conn:
        return _points_by_player(conn, room_id).get(user_id, [0.0, 0])[0]


def used_wagers(room_id: int, user_id: int) -> set:
    """Mises déjà utilisées par ce joueur dans la partie (hors question finale) : elles sont désactivées."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        finale = _final_question_id(conn, room_id)
        rows = conn.execute("SELECT wager FROM room_answers WHERE room_id = ? AND user_id = ? "
                            "AND wager IS NOT NULL AND question_id <> ?", (room_id, user_id, finale or -1)).fetchall()
    return {r[0] for r in rows}


def wager_options(room: dict, user_id: int, index: int) -> list[int]:
    """Mises possibles pour la question n° `index` (0, 1, 2...).
    - question normale : 1, 2, ... N-1 (N = nombre de questions) ;
    - question finale  : 0, S, 2xS (S = score actuel du joueur, 10 au minimum)."""
    n = room["nb_questions"]
    if index >= n - 1:
        base = max(10, int(round(player_points(room["id"], user_id))))
        return [0, base, 2 * base]
    return list(range(1, n))


def _check_wager(conn, room: dict, user_id: int, question_id: int, wager) -> tuple[str, int | None]:
    """Vérifie la mise envoyée avec une réponse. Retourne (erreur, mise à enregistrer)."""
    if not room["wager_mode"]:
        return "", None
    if not isinstance(wager, int) or isinstance(wager, bool):
        return "Choisis une mise avant de répondre.", None
    index = conn.execute("SELECT COUNT(*) FROM room_questions WHERE room_id = ? AND id < ?",
                         (room["id"], question_id)).fetchone()[0]
    if index >= room["nb_questions"] - 1:                       # question finale
        base = max(10, int(round(_points_by_player(conn, room["id"]).get(user_id, [0.0, 0])[0])))
        if wager not in (0, base, 2 * base):
            return "Mise invalide.", None
        return "", wager
    if not (1 <= wager <= room["nb_questions"] - 1):
        return "Mise invalide.", None
    finale = _final_question_id(conn, room["id"])
    deja = conn.execute("SELECT 1 FROM room_answers WHERE room_id = ? AND user_id = ? AND wager = ? "
                        "AND question_id <> ?", (room["id"], user_id, wager, finale or -1)).fetchone()
    if deja:
        return "Cette mise est déjà utilisée.", None
    return "", wager


# --------------------------------------------------------------------------- #
# Déroulement synchronisé : minuteur, question suivante
# --------------------------------------------------------------------------- #
def has_timer(room: dict) -> bool:
    """False si l'hôte a choisi une partie SANS limite de temps."""
    return bool(room["time_per_question"])


def countdown_left(room: dict) -> float:
    """Secondes restantes avant la 1re question (compte à rebours de lancement), 0 sinon."""
    if (room["status"] != PLAYING or room["phase"] != ANSWERING or room["current_q"] != 0
            or not room.get("q_started_at")):
        return 0.0
    return max(0.0, room["q_started_at"] - (room["paused_at"] or time.time()))


def seconds_left(room: dict) -> float:
    """Secondes restantes pour la question en cours (0 si le temps est écoulé ou si on est en phase résultats).
    Pendant une pause, le temps est figé."""
    if (room["status"] != PLAYING or room["phase"] != ANSWERING or not room.get("q_started_at")
            or not has_timer(room)):
        return 0.0
    maintenant = room["paused_at"] or time.time()
    return max(0.0, min(room["q_started_at"] + room["time_per_question"] - maintenant, room["time_per_question"]))


def heartbeat(code: str, user_id: int) -> None:
    """Signe de vie d'un joueur présent dans la partie (appelé toutes les secondes par son minuteur)."""
    with closing(sqlite3.connect(DB_PATH, timeout=10)) as conn:
        conn.execute(
            "UPDATE room_players SET last_seen = ?, skipped = 0 WHERE user_id = ? AND room_id = "
            "(SELECT id FROM rooms WHERE code = ?)", (time.time(), user_id, code.strip().upper()))
        conn.commit()


def mark_left(code: str, user_id: int) -> None:
    """Le joueur quitte la partie (bouton « Quitter ») : il est tout de suite considéré comme absent."""
    with closing(sqlite3.connect(DB_PATH, timeout=10)) as conn:
        conn.execute(
            "UPDATE room_players SET last_seen = 0 WHERE user_id = ? AND room_id = "
            "(SELECT id FROM rooms WHERE code = ? AND status = ?)", (user_id, code.strip().upper(), PLAYING))
        conn.commit()


def absent_players(room: dict) -> list[dict]:
    """Joueurs sortis de la partie : plus de signe de vie depuis ABSENT_AFTER secondes (sauf ceux que l'hôte
    a décidé d'ignorer avec skip_absent)."""
    maintenant = time.time()
    return [p for p in room["players"]
            if not p["skipped"] and p["last_seen"] is not None and maintenant - p["last_seen"] > ABSENT_AFTER]


def skip_absent(code: str, host_id: int) -> tuple[bool, str]:
    """L'hôte continue la partie SANS les joueurs absents (s'ils reviennent, ils sont de nouveau comptés)."""
    room = get_room(code)
    if room is None or room["status"] != PLAYING:
        return False, "La partie n'est pas en cours."
    if room["host_id"] != host_id:
        return False, "Seul l'hôte peut continuer sans les joueurs absents."
    ids = [p["user_id"] for p in absent_players(room)]
    with closing(sqlite3.connect(DB_PATH, timeout=10)) as conn:
        conn.executemany("UPDATE room_players SET skipped = 1 WHERE room_id = ? AND user_id = ?",
                         [(room["id"], i) for i in ids])
        conn.commit()
    sync_room(code)
    return True, ""


def sync_room(code: str):
    """Retourne la room à jour.
    - un joueur est sorti : la partie se met EN PAUSE (le temps est figé) ; quand il revient, le temps repart là
      où il s'était arrêté ;
    - le temps de la question est écoulé : on passe en phase RÉSULTATS (PAS à la question suivante : seul l'hôte
      peut la lancer).
    Peut être appelée par tous les joueurs en même temps : un seul changement est effectué (verrou dans la base)."""
    room = get_room(code)
    if room is None or room["status"] != PLAYING:
        return room
    maintenant = time.time()

    if not room["q_started_at"]:                     # partie lancée avant la migration : on démarre le chrono
        with closing(sqlite3.connect(DB_PATH)) as conn:
            conn.execute("UPDATE rooms SET q_started_at = ? WHERE id = ? AND q_started_at IS NULL",
                         (maintenant, room["id"]))
            conn.commit()
        return get_room(code)

    absents = absent_players(room)
    if absents and not room["paused_at"]:            # quelqu'un vient de sortir : pause
        with closing(sqlite3.connect(DB_PATH)) as conn:
            conn.execute("UPDATE rooms SET paused_at = ? WHERE id = ? AND paused_at IS NULL",
                         (maintenant, room["id"]))
            conn.commit()
        return get_room(code)
    if not absents and room["paused_at"]:            # tout le monde est revenu : on reprend (temps décalé)
        with closing(sqlite3.connect(DB_PATH)) as conn:
            conn.execute("UPDATE rooms SET q_started_at = q_started_at + (? - paused_at), paused_at = NULL "
                         "WHERE id = ? AND paused_at IS NOT NULL", (maintenant, room["id"]))
            conn.commit()
        return get_room(code)
    if room["paused_at"]:
        return room

    if (room["phase"] == ANSWERING and has_timer(room)
            and maintenant >= room["q_started_at"] + room["time_per_question"] + CLOSE_GRACE):
        if _close_question(room["id"], room["current_q"]):
            return get_room(code)
    return room


def _close_question(room_id: int, expected_q: int) -> bool:
    """Termine la question `expected_q` : les joueurs sans réponse reçoivent 0 %, et on passe en phase
    « résultats ». Ne fait rien (False) si c'est déjà fait."""
    with closing(sqlite3.connect(DB_PATH, timeout=10)) as conn:
        conn.execute("BEGIN IMMEDIATE")                 # verrou : un seul changement même si 10 joueurs l'appellent
        row = conn.execute("SELECT status, current_q, phase FROM rooms WHERE id = ?", (room_id,)).fetchone()
        if row is None or row[0] != PLAYING or row[1] != expected_q or row[2] != ANSWERING:
            conn.rollback()
            return False
        q = conn.execute("SELECT id FROM room_questions WHERE room_id = ? ORDER BY id LIMIT 1 OFFSET ?",
                         (room_id, expected_q)).fetchone()
        if q:                                           # pas de réponse = 0 %
            conn.execute(
                "INSERT OR IGNORE INTO room_answers "
                "(room_id, user_id, question_id, choice, is_correct, text_answer, score, auto_score, comment) "
                "SELECT ?, p.user_id, ?, -1, 0, '', 0, 0, '' FROM room_players p WHERE p.room_id = ?",
                (room_id, q[0], room_id),
            )
        conn.execute("UPDATE rooms SET phase = ? WHERE id = ?", (REVIEW, room_id))
        conn.commit()
    return True


def _advance(room_id: int, expected_q: int) -> bool:
    """Passe de la phase « résultats » de la question `expected_q` à la question suivante, ou termine la partie
    après la dernière. Ne fait rien (False) si quelqu'un l'a déjà fait."""
    with closing(sqlite3.connect(DB_PATH, timeout=10)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT status, current_q, phase FROM rooms WHERE id = ?", (room_id,)).fetchone()
        if row is None or row[0] != PLAYING or row[1] != expected_q or row[2] != REVIEW:
            conn.rollback()
            return False
        nb_q = conn.execute("SELECT COUNT(*) FROM room_questions WHERE room_id = ?", (room_id,)).fetchone()[0]
        if expected_q + 1 >= nb_q:
            conn.execute("UPDATE rooms SET status = ?, current_q = ? WHERE id = ?", (FINISHED, nb_q, room_id))
        else:
            conn.execute("UPDATE rooms SET current_q = ?, q_started_at = ?, phase = ? WHERE id = ?",
                         (expected_q + 1, time.time(), ANSWERING, room_id))
        conn.commit()
    return True


def advance_question(code: str, user_id: int) -> tuple[bool, str]:
    """Bouton de l'HÔTE.
    - pendant que les joueurs répondent : termine la question tout de suite (affiche les résultats) ;
    - pendant les résultats : passe à la question suivante (ou termine la partie après la dernière)."""
    room = get_room(code)
    if room is None or room["status"] != PLAYING:
        return False, "La partie n'est pas en cours."
    if room["host_id"] != user_id:
        return False, "Seul l'hôte peut passer à la question suivante."
    if room["paused_at"]:
        return False, "La partie est en pause (un joueur est sorti)."
    if room["phase"] == ANSWERING:
        _close_question(room["id"], room["current_q"])
    else:
        _advance(room["id"], room["current_q"])
    return True, ""


def _review_if_all_answered(code: str) -> None:
    """Affiche les résultats dès que tout le monde a répondu : toujours dans une partie SANS limite de temps,
    et dans une partie avec temps si AUTO_REVIEW_IF_ALL_ANSWERED est True."""
    room = get_room(code)
    if room is None or room["status"] != PLAYING or room["phase"] != ANSWERING:
        return
    if has_timer(room) and not AUTO_REVIEW_IF_ALL_ANSWERED:
        return
    n, total = current_question_stats(room["id"], room["current_q"])
    if n >= total:
        _close_question(room["id"], room["current_q"])


def current_question_stats(room_id: int, current_q: int) -> tuple[int, int]:
    """(nombre de joueurs qui ont répondu à la question en cours, nombre de joueurs)."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        q = conn.execute("SELECT id FROM room_questions WHERE room_id = ? ORDER BY id LIMIT 1 OFFSET ?",
                         (room_id, current_q)).fetchone()
        total = conn.execute("SELECT COUNT(*) FROM room_players WHERE room_id = ?", (room_id,)).fetchone()[0]
        if q is None:
            return 0, total
        n = conn.execute("SELECT COUNT(*) FROM room_answers WHERE room_id = ? AND question_id = ?",
                         (room_id, q[0])).fetchone()[0]
    return n, total


# --------------------------------------------------------------------------- #
# Correction par l'hôte
# --------------------------------------------------------------------------- #
def list_answers(room_id: int, question_id: int | None = None) -> list[dict]:
    """Réponses des joueurs (pour les résultats et la correction de l'hôte), dans l'ordre des questions.
    Un joueur qui n'a pas répondu (temps écoulé) a answered = False. Si question_id est donné : cette question seule."""
    filtre, params = ("AND a.question_id = ?", (room_id, question_id)) if question_id else ("", (room_id,))
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            f"""
            SELECT a.question_id, a.user_id, p.username, a.text_answer, a.choice,
                   COALESCE(a.auto_score, a.score, 0), COALESCE(a.score, 0), a.host_verdict, a.comment, a.wager
            FROM room_answers a
            JOIN room_players p ON p.room_id = a.room_id AND p.user_id = a.user_id
            WHERE a.room_id = ? {filtre}
            ORDER BY a.question_id, p.rowid
            """,
            params,
        ).fetchall()
    return [{"question_id": r[0], "user_id": r[1], "username": r[2], "text": r[3], "choice": r[4],
             "answered": bool(r[3]) or r[4] >= 0, "auto": r[5], "score": r[6], "verdict": r[7],
             "comment": r[8], "wager": r[9]} for r in rows]


def set_score(code: str, host_id: int, question_id: int, user_id: int,
              percent: float | None) -> tuple[bool, str]:
    """L'hôte modifie le score d'une réponse (0 à 100 %), celle d'un joueur comme la sienne : 100 = correcte, 0 = fausse.
    percent = None : retour à la correction automatique. La réponse est vraie si le pourcentage est > 50."""
    room = get_room(code)
    if room is None or room["status"] not in (PLAYING, FINISHED):
        return False, "Room introuvable."
    if room["host_id"] != host_id:
        return False, "Seul l'hôte peut corriger les réponses."
    with closing(sqlite3.connect(DB_PATH)) as conn:
        a = conn.execute(
            "SELECT COALESCE(auto_score, score, 0) FROM room_answers "
            "WHERE room_id = ? AND user_id = ? AND question_id = ? AND (text_answer <> '' OR choice >= 0)",
            (room["id"], user_id, question_id),
        ).fetchone()
        if a is None:
            return False, "Question introuvable."
        if percent is None:
            score, vote = a[0], None
        else:
            score = max(0.0, min(100.0, float(percent)))
            vote = int(score > SEUIL_VRAI)
        conn.execute(
            "UPDATE room_answers SET score = ?, is_correct = ?, host_verdict = ? "
            "WHERE room_id = ? AND user_id = ? AND question_id = ?",
            (score, int(score > SEUIL_VRAI), vote, room["id"], user_id, question_id),
        )
        conn.commit()
    return True, "Correction enregistrée."


def get_answers(room_id: int, user_id: int) -> dict:
    """Réponses d'un joueur : {id_question: {"choice", "text", "score" (0-100), "comment", "auto", "verdict"}}.
    choice = -1 et text = "" : le joueur n'a pas répondu à temps (0 %)."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            "SELECT question_id, choice, text_answer, COALESCE(score, is_correct * 100), comment, "
            "COALESCE(auto_score, score, is_correct * 100), host_verdict, wager "
            "FROM room_answers WHERE room_id = ? AND user_id = ?",
            (room_id, user_id),
        ).fetchall()
    return {r[0]: {"choice": r[1], "text": r[2], "score": r[3], "comment": r[4], "auto": r[5],
                   "verdict": r[6], "wager": r[7]} for r in rows}


def scoreboard(room_id: int) -> list[dict]:
    """Classement : points (voir answer_points), nombre de questions répondues."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        joueurs = conn.execute("SELECT user_id, username FROM room_players WHERE room_id = ?", (room_id,)).fetchall()
        points = _points_by_player(conn, room_id)
    lignes = [{"user_id": uid, "username": nom, "score": round(points.get(uid, [0.0, 0])[0], 2),
               "answered": points.get(uid, [0.0, 0])[1]} for uid, nom in joueurs]
    return sorted(lignes, key=lambda l: (-l["score"], -l["answered"], l["username"]))


def answers_matrix(room_id: int) -> list[dict]:
    """Pourcentage de chaque joueur pour chaque question : [{"question_id", "user_id", "score"}, ...]."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            "SELECT question_id, user_id, COALESCE(score, is_correct * 100) "
            "FROM room_answers WHERE room_id = ?",
            (room_id,),
        ).fetchall()
    return [{"question_id": r[0], "user_id": r[1], "score": r[2]} for r in rows]


def list_user_rooms(user_id: int, limit: int = 30) -> list[dict]:
    """Historique : toutes les rooms de ce joueur (en cours, terminées, annulées), les plus récentes d'abord,
    avec son score (somme des pourcentages / 100) et le nombre de questions auxquelles il a répondu."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            """
            SELECT r.code, r.name, r.status, r.created_at, r.host_id, r.nb_questions,
                   (SELECT COUNT(*) FROM room_players x WHERE x.room_id = r.id),
                   (SELECT COALESCE(SUM(COALESCE(a.score, a.is_correct * 100)), 0) / 100.0
                      FROM room_answers a WHERE a.room_id = r.id AND a.user_id = ?),
                   (SELECT COUNT(*) FROM room_answers a WHERE a.room_id = r.id AND a.user_id = ?),
                   r.id
            FROM rooms r JOIN room_players p ON p.room_id = r.id
            WHERE p.user_id = ?
            ORDER BY r.id DESC
            LIMIT ?
            """,
            (user_id, user_id, user_id, limit),
        ).fetchall()
        points = {r[9]: _points_by_player(conn, r[9]).get(user_id, [0.0, 0])[0] for r in rows}   # mises comprises
    return [
        {"code": r[0], "name": r[1], "status": r[2], "created_at": r[3], "host_id": r[4],
         "nb_questions": r[5], "nb_players": r[6], "score": round(points[r[9]], 2), "answered": r[8]}
        for r in rows
    ]