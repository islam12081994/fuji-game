"""
main.py - point d'entrée de l'application.
Lance avec :  streamlit run main.py

- Non connecté        -> page de connexion / inscription (interface_auth.py), avec sélecteur de langue en haut à droite
- Connecté (user)     -> Tableau de bord (Créer une room / Jouer) + Mon profil
- Connecté (admin)    -> pareil + Espace admin
- Barre latérale (navbar.py) : navigation, choix de la langue (Français / English / العربية), déconnexion

Dossier du projet :
    main.py   authentifications.py   interface_auth.py   espaces.py   i18n.py   navbar.py
    user/__init__.py   user/dashboard.py   user/rooms.py   user/questions_ai.py   user/game.py
    .streamlit/config.toml
"""
import streamlit as st

# Doit être le tout premier appel Streamlit. "wide" donne plus de place aux tableaux de l'admin ;
# la page de connexion reste centrée grâce à son propre CSS.
st.set_page_config(page_title="Quiz de culture générale", page_icon="🏯", layout="wide")

from authentifications import ROLE_ADMIN, get_user_role      # noqa: E402
from espaces import admin_space, profile_space               # noqa: E402
from interface_auth import require_auth                      # noqa: E402
from navbar import render_navbar                             # noqa: E402
from user.dashboard import restore_room, user_dashboard      # noqa: E402
from user.game import play                                   # noqa: E402


user = require_auth()                       # bloque tant que l'utilisateur n'est pas connecté
                                            # (la page de connexion contient son propre sélecteur de langue)

# On relit le rôle dans la base à chaque affichage : si un admin a changé ton rôle
# ou supprimé ton compte, l'effet est immédiat.
role = get_user_role(user["username"])
if role is None:                            # compte supprimé : on déconnecte
    st.session_state.authenticated = False
    st.session_state.user = None
    st.rerun()

restore_room(user)                          # retrouve sa room enregistrée (en attente ou en cours)

pages = ["dashboard", "profile"]
if role == ROLE_ADMIN:
    pages.append("admin")
page = render_navbar(user, role, pages)

if page == "admin":
    admin_space(user)
elif page == "profile":
    profile_space(user)
else:
    user_dashboard(user, jeu=play)