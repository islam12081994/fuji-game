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
"""
import json
import secrets
import sqlite3
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
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # Migration : si la table existait déjà SANS la colonne "is_public", on l'ajoute
        colonnes = [ligne[1] for ligne in conn.execute("PRAGMA table_info(rooms)").fetchall()]
        if "is_public" not in colonnes:
            conn.execute("ALTER TABLE rooms ADD COLUMN is_public INTEGER NOT NULL DEFAULT 1")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS room_players (
                room_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                PRIMARY KEY (room_id, user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS room_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                choices TEXT NOT NULL,          -- liste JSON de 4 propositions (vide pour une question libre)
                answer INTEGER NOT NULL,        -- index (0 à 3) de la bonne proposition
                kind TEXT NOT NULL DEFAULT 'qcm',        -- 'qcm' ou 'open' (réponse libre)
                reference TEXT NOT NULL DEFAULT ''       -- réponse attendue (questions libres)
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
                comment TEXT NOT NULL DEFAULT '',        -- commentaire de l'IA
                PRIMARY KEY (room_id, user_id, question_id)
            )
        """)
        # Migration : anciennes bases créées sans les colonnes des questions libres
        for table, ajouts in (
            ("room_questions", [("kind", "TEXT NOT NULL DEFAULT 'qcm'"),
                                ("reference", "TEXT NOT NULL DEFAULT ''")]),
            ("room_answers", [("text_answer", "TEXT NOT NULL DEFAULT ''"), ("score", "REAL"),
                              ("comment", "TEXT NOT NULL DEFAULT ''")]),
        ):
            existantes = [l[1] for l in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            for nom, definition in ajouts:
                if nom not in existantes:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {nom} {definition}")
        conn.execute("UPDATE room_answers SET score = is_correct * 100 WHERE score IS NULL")
        conn.commit()


def _new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def create_room(host_id: int, host_name: str, name: str = "",
                max_players: int = 6, nb_questions: int = 10,
                is_public: bool = True) -> tuple[bool, str, str | None]:
    """Crée une room et y place l'hôte. Retourne (ok, message, code)."""
    if not (MIN_PLAYERS <= max_players <= MAX_PLAYERS):
        return False, f"Le nombre de joueurs doit être entre {MIN_PLAYERS} et {MAX_PLAYERS}.", None
    if not (MIN_QUESTIONS <= nb_questions <= MAX_QUESTIONS):
        return False, f"Le nombre de questions doit être entre {MIN_QUESTIONS} et {MAX_QUESTIONS}.", None
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
                    "INSERT INTO rooms (code, name, host_id, max_players, nb_questions, is_public) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (code, name, host_id, max_players, nb_questions, int(is_public)),
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
            "SELECT id, code, name, host_id, max_players, nb_questions, status, is_public "
            "FROM rooms WHERE code = ?", (code.strip().upper(),)
        ).fetchone()
        if not row:
            return None
        players = conn.execute(
            "SELECT user_id, username FROM room_players WHERE room_id = ? ORDER BY rowid", (row[0],)
        ).fetchall()
    room = {
        "id": row[0], "code": row[1], "name": row[2], "host_id": row[3],
        "max_players": row[4], "nb_questions": row[5], "status": row[6],
        "is_public": bool(row[7]),
        "players": [{"user_id": p[0], "username": p[1]} for p in players],
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
        conn.execute("UPDATE rooms SET status = ? WHERE id = ?", (PLAYING, room["id"]))
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
            "SELECT id, question, choices, answer, kind, reference FROM room_questions "
            "WHERE room_id = ? ORDER BY id",
            (room_id,),
        ).fetchall()
    return [{"id": r[0], "question": r[1], "choices": json.loads(r[2]), "answer": r[3],
             "kind": r[4], "reference": r[5]} for r in rows]


def add_questions(code: str, user_id: int, questions: list[dict]) -> tuple[bool, str, int]:
    """Ajoute des questions à la room (hôte seulement, avant le lancement).
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
                "INSERT INTO room_questions (room_id, question, choices, answer, kind, reference) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (room["id"], propre["question"], json.dumps(propre["choices"], ensure_ascii=False),
                 propre["answer"], propre["kind"], propre["reference"]),
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


def submit_answer(code: str, user_id: int, question_id: int, choice: int) -> tuple[bool, str, bool]:
    """Enregistre la réponse d'un joueur à un QCM. Retourne (ok, message, bonne_réponse)."""
    room = get_room(code)
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
        correcte = int(choice == q[0])
        cur = conn.execute(
            "INSERT OR IGNORE INTO room_answers "
            "(room_id, user_id, question_id, choice, is_correct, score) VALUES (?, ?, ?, ?, ?, ?)",
            (room["id"], user_id, question_id, choice, correcte, correcte * 100),
        )
        conn.commit()
    if cur.rowcount == 0:
        return False, "Tu as déjà répondu à cette question.", False
    _finish_if_done(room["id"])
    return True, "", bool(correcte)


def submit_open_answer(code: str, user_id: int, question_id: int, text: str,
                       percent: float, comment: str = "") -> tuple[bool, str]:
    """Enregistre la réponse écrite d'un joueur, avec le pourcentage donné par l'IA (0 à 100)."""
    room = get_room(code)
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
        cur = conn.execute(
            "INSERT OR IGNORE INTO room_answers "
            "(room_id, user_id, question_id, choice, is_correct, text_answer, score, comment) "
            "VALUES (?, ?, ?, -1, ?, ?, ?, ?)",
            (room["id"], user_id, question_id, int(percent >= 50), text[:300], percent,
             (comment or "")[:300]),
        )
        conn.commit()
    if cur.rowcount == 0:
        return False, "Tu as déjà répondu à cette question."
    _finish_if_done(room["id"])
    return True, ""


def get_answers(room_id: int, user_id: int) -> dict:
    """Réponses d'un joueur : {id_question: {"choice", "text", "score" (0-100), "comment"}}."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            "SELECT question_id, choice, text_answer, COALESCE(score, is_correct * 100), comment "
            "FROM room_answers WHERE room_id = ? AND user_id = ?",
            (room_id, user_id),
        ).fetchall()
    return {r[0]: {"choice": r[1], "text": r[2], "score": r[3], "comment": r[4]} for r in rows}


def scoreboard(room_id: int) -> list[dict]:
    """Classement : points (somme des pourcentages / 100), nombre de questions répondues."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            """
            SELECT p.user_id, p.username,
                   COALESCE(SUM(COALESCE(a.score, a.is_correct * 100)), 0) / 100.0 AS points,
                   COUNT(a.question_id) AS answered
            FROM room_players p
            LEFT JOIN room_answers a ON a.room_id = p.room_id AND a.user_id = p.user_id
            WHERE p.room_id = ?
            GROUP BY p.user_id, p.username
            ORDER BY points DESC, answered DESC, p.username
            """,
            (room_id,),
        ).fetchall()
    return [{"user_id": r[0], "username": r[1], "score": round(r[2], 2), "answered": r[3]} for r in rows]


def answers_matrix(room_id: int) -> list[dict]:
    """Pourcentage de chaque joueur pour chaque question : [{"question_id", "user_id", "score"}, ...]."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            "SELECT question_id, user_id, COALESCE(score, is_correct * 100) "
            "FROM room_answers WHERE room_id = ?",
            (room_id,),
        ).fetchall()
    return [{"question_id": r[0], "user_id": r[1], "score": r[2]} for r in rows]


def _finish_if_done(room_id: int) -> None:
    """Quand tous les joueurs ont répondu à toutes les questions, la room passe à « terminée »
    (elle reste enregistrée : résultats et historique)."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        nb_q = conn.execute("SELECT COUNT(*) FROM room_questions WHERE room_id = ?",
                            (room_id,)).fetchone()[0]
        restants = conn.execute(
            "SELECT COUNT(*) FROM room_players p WHERE p.room_id = ? AND "
            "(SELECT COUNT(*) FROM room_answers a WHERE a.room_id = p.room_id AND a.user_id = p.user_id) < ?",
            (room_id, nb_q),
        ).fetchone()[0]
        if nb_q > 0 and restants == 0:
            conn.execute("UPDATE rooms SET status = ? WHERE id = ? AND status = ?",
                         (FINISHED, room_id, PLAYING))
            conn.commit()


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
                   (SELECT COUNT(*) FROM room_answers a WHERE a.room_id = r.id AND a.user_id = ?)
            FROM rooms r JOIN room_players p ON p.room_id = r.id
            WHERE p.user_id = ?
            ORDER BY r.id DESC
            LIMIT ?
            """,
            (user_id, user_id, user_id, limit),
        ).fetchall()
    return [
        {"code": r[0], "name": r[1], "status": r[2], "created_at": r[3], "host_id": r[4],
         "nb_questions": r[5], "nb_players": r[6], "score": round(r[7], 2), "answered": r[8]}
        for r in rows
    ]