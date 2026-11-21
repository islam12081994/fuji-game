"""
authentifications.py
Comptes utilisateurs (SQLite + bcrypt) avec deux rôles : "admin" et "user".

Comment devient-on admin ?
  1) (recommandé) en mettant ADMIN_USERNAME et ADMIN_PASSWORD dans le fichier .env :
     le compte admin est créé automatiquement au démarrage ;
  2) sinon, le TOUT PREMIER compte créé (base vide) devient admin
     (désactivable avec FIRST_USER_IS_ADMIN = False) ;
  3) ou en ligne de commande :
         python -c "from authentifications import make_admin; print(make_admin('ali'))"
"""
import os
import re
import sqlite3
from contextlib import closing

import bcrypt

try:                                  # lit le fichier .env s'il existe (pip install python-dotenv)
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DB_PATH = "users.db"

ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLES = (ROLE_USER, ROLE_ADMIN)

MIN_PASSWORD = 6
FIRST_USER_IS_ADMIN = True            # le 1er compte créé sur une base vide devient admin


# --------------------------------------------------------------------------- #
# Base de données
# --------------------------------------------------------------------------- #
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user'
        )
    """)
    # Migration : si ta base users.db existe déjà SANS la colonne "role", on l'ajoute.
    colonnes = [ligne[1] for ligne in cursor.execute("PRAGMA table_info(users)").fetchall()]
    if "role" not in colonnes:
        cursor.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
    if "avatar" not in colonnes:             # avatar du joueur (voir avatar.py) ; NULL = avatar par défaut
        cursor.execute("ALTER TABLE users ADD COLUMN avatar TEXT")
    conn.commit()
    _creer_admin_depuis_env(conn)
    conn.close()


def _creer_admin_depuis_env(conn):
    """Crée (ou promeut) le compte admin décrit dans .env : ADMIN_USERNAME / ADMIN_PASSWORD."""
    nom = os.getenv("ADMIN_USERNAME").strip()
    mdp = os.getenv("ADMIN_PASSWORD")
    if not nom or not mdp:
        return

    existe = conn.execute("SELECT id FROM users WHERE username = ?", (nom,)).fetchone()
    if existe:
        conn.execute("UPDATE users SET role = ? WHERE username = ?", (ROLE_ADMIN, nom))
    elif len(mdp) >= MIN_PASSWORD:
        conn.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (nom, _hash(mdp), ROLE_ADMIN),
        )
    else:
        print(f"ADMIN_PASSWORD trop court (minimum {MIN_PASSWORD} caractères) : admin non créé.")
    conn.commit()


def _hash(password: str) -> bytes:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt())


# --------------------------------------------------------------------------- #
# Inscription / connexion (même fonctionnement qu'avant)
# --------------------------------------------------------------------------- #
def register_user(username: str, password: str) -> tuple[bool, str]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
    if cursor.fetchone():
        conn.close()
        return False, "Ce nom d'utilisateur existe déjà."

    # Rôle : "user" par défaut ; admin seulement pour le tout premier compte (si activé)
    nb_comptes = cursor.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    role = ROLE_ADMIN if (FIRST_USER_IS_ADMIN and nb_comptes == 0) else ROLE_USER

    cursor.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
        (username, _hash(password), role),
    )
    conn.commit()
    conn.close()
    if role == ROLE_ADMIN:
        return True, "Compte administrateur créé avec succès."
    return True, "Compte créé avec succès."


def login_user(username: str, password: str) -> tuple[bool, str]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return False, "Utilisateur introuvable."

    stored_hash = row[0]
    if isinstance(stored_hash, str):
        stored_hash = stored_hash.encode()
    if bcrypt.checkpw(password.encode(), stored_hash):
        return True, "Connexion réussie."
    return False, "Mot de passe incorrect."


def get_user_id(username: str):
    """Retourne l'id de l'utilisateur (ou None s'il n'existe pas)."""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return row[0] if row else None


# --------------------------------------------------------------------------- #
# Avatars (le dessin/affichage est dans avatar.py ; ici seulement l'enregistrement)
# --------------------------------------------------------------------------- #
AVATAR_MAX_CHARS = 100_000            # une photo 128 x 128 en JPEG fait ~10 000 caractères en base64
_AVATAR_RE = re.compile(r"^(preset:[a-z]{1,20}|data:image/jpeg;base64,[A-Za-z0-9+/=]+)$")


def get_avatar(username: str):
    """Avatar enregistré ("preset:ninja", "data:image/jpeg;base64,...") ou None (avatar par défaut)."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute("SELECT avatar FROM users WHERE username = ?", (username,)).fetchone()
    return row[0] if row else None


def get_avatars(usernames: list[str]) -> dict:
    """{nom: avatar} pour plusieurs joueurs en une seule requête (classement, salle d'attente)."""
    noms = list(dict.fromkeys(usernames))
    if not noms:
        return {}
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute(
            f"SELECT username, avatar FROM users WHERE username IN ({','.join('?' * len(noms))})", noms
        ).fetchall()
    return {nom: avatar for nom, avatar in rows}


def set_avatar(username: str, avatar) -> tuple[bool, str]:
    """Enregistre l'avatar (None = le retirer). La valeur est vérifiée avant d'être écrite dans la base."""
    if avatar is not None and (not isinstance(avatar, str) or len(avatar) > AVATAR_MAX_CHARS
                               or not _AVATAR_RE.match(avatar)):
        return False, "Avatar invalide."
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.execute("UPDATE users SET avatar = ? WHERE username = ?", (avatar, username))
        conn.commit()
    if cur.rowcount == 0:
        return False, "Utilisateur introuvable."
    return True, "Avatar enregistré."


# --------------------------------------------------------------------------- #
# Rôles
# --------------------------------------------------------------------------- #
def get_user_role(username: str):
    """Retourne "admin" ou "user" (ou None si l'utilisateur n'existe pas)."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        row = conn.execute("SELECT role FROM users WHERE username = ?", (username,)).fetchone()
    return row[0] if row else None


def is_admin(username: str) -> bool:
    return get_user_role(username) == ROLE_ADMIN


def make_admin(username: str) -> tuple[bool, str]:
    """Donne le rôle admin à un compte existant (usage : ligne de commande, pas dans l'interface)."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.execute("UPDATE users SET role = ? WHERE username = ?", (ROLE_ADMIN, username))
        conn.commit()
    if cur.rowcount == 0:
        return False, "Utilisateur introuvable."
    return True, f"{username} est maintenant administrateur."


# --------------------------------------------------------------------------- #
# Espace utilisateur : changer SON mot de passe
# --------------------------------------------------------------------------- #
def change_password(username: str, old_password: str, new_password: str) -> tuple[bool, str]:
    ok, _ = login_user(username, old_password)
    if not ok:
        return False, "Ancien mot de passe incorrect."
    if len(new_password) < MIN_PASSWORD:
        return False, f"Le nouveau mot de passe doit contenir au moins {MIN_PASSWORD} caractères."

    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE username = ?",
                     (_hash(new_password), username))
        conn.commit()
    return True, "Mot de passe modifié."


MIN_USERNAME = 3


def change_username(user_id: int, new_username: str) -> tuple[bool, str]:
    """Change le nom d'utilisateur du compte `user_id` (nom unique). Met aussi à jour le nom affiché dans les rooms."""
    new_username = (new_username or "").strip()
    if len(new_username) < MIN_USERNAME:
        return False, f"Le nom d'utilisateur doit contenir au moins {MIN_USERNAME} caractères."
    with closing(sqlite3.connect(DB_PATH)) as conn:
        actuel = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
        if actuel is None:
            return False, "Utilisateur introuvable."
        if actuel[0] == new_username:
            return True, "Nom d'utilisateur modifié."
        if conn.execute("SELECT 1 FROM users WHERE username = ? AND id <> ?", (new_username, user_id)).fetchone():
            return False, "Ce nom d'utilisateur existe déjà."
        conn.execute("UPDATE users SET username = ? WHERE id = ?", (new_username, user_id))
        try:                                   # le nom est aussi copié dans les rooms (table créée par user/rooms.py)
            conn.execute("UPDATE room_players SET username = ? WHERE user_id = ?", (new_username, user_id))
        except sqlite3.OperationalError:
            pass
        conn.commit()
    return True, "Nom d'utilisateur modifié."


# --------------------------------------------------------------------------- #
# Espace admin : chaque fonction vérifie elle-même que l'appelant est admin
# (on ne se fie pas seulement à l'interface)
# --------------------------------------------------------------------------- #
def list_users(acting_username: str) -> list[dict]:
    """Liste tous les comptes (jamais les mots de passe). Liste vide si l'appelant n'est pas admin."""
    if not is_admin(acting_username):
        return []
    with closing(sqlite3.connect(DB_PATH)) as conn:
        rows = conn.execute("SELECT id, username, role FROM users ORDER BY id").fetchall()
    return [{"id": r[0], "username": r[1], "role": r[2]} for r in rows]


def set_role(acting_username: str, username: str, new_role: str) -> tuple[bool, str]:
    if not is_admin(acting_username):
        return False, "Accès refusé : réservé aux administrateurs."
    if new_role not in ROLES:
        return False, "Rôle invalide."
    if username == acting_username:
        return False, "Tu ne peux pas modifier ton propre rôle."
    if get_user_role(username) is None:
        return False, "Utilisateur introuvable."

    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("UPDATE users SET role = ? WHERE username = ?", (new_role, username))
        conn.commit()
    return True, f"{username} est maintenant « {new_role} »."


def reset_password(acting_username: str, username: str, new_password: str) -> tuple[bool, str]:
    if not is_admin(acting_username):
        return False, "Accès refusé : réservé aux administrateurs."
    if len(new_password) < MIN_PASSWORD:
        return False, f"Le mot de passe doit contenir au moins {MIN_PASSWORD} caractères."
    if get_user_role(username) is None:
        return False, "Utilisateur introuvable."

    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE username = ?",
                     (_hash(new_password), username))
        conn.commit()
    return True, f"Mot de passe de {username} réinitialisé."


def delete_user(acting_username: str, username: str) -> tuple[bool, str]:
    if not is_admin(acting_username):
        return False, "Accès refusé : réservé aux administrateurs."
    if username == acting_username:
        return False, "Tu ne peux pas supprimer ton propre compte."
    if get_user_role(username) is None:
        return False, "Utilisateur introuvable."

    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.commit()
    return True, f"{username} a été supprimé."