"""
espaces.py
Deux "espaces" Streamlit :
  - user_space(user, jeu=None) : accessible à tous les comptes connectés
  - admin_space(user)          : réservé aux administrateurs

`user` est le dictionnaire donné par require_auth() : {"id": ..., "username": ..., "role": ...}
"""
import streamlit as st

from authentifications import (
    MIN_PASSWORD,
    ROLE_ADMIN,
    ROLES,
    change_password,
    delete_user,
    get_user_role,
    list_users,
    reset_password,
    set_role,
)


# --------------------------------------------------------------------------- #
# ESPACE UTILISATEUR
# --------------------------------------------------------------------------- #
def user_space(user: dict, jeu=None) -> None:
    """Onglet « Jouer » (ton jeu) + onglet « Mon profil »."""
    st.title(f"Espace utilisateur - {user['username']}")
    tab_jeu, tab_profil = st.tabs(["🎮 Jouer", "👤 Mon profil"])

    with tab_jeu:
        if jeu is not None:
            jeu(user)                      # ta fonction de jeu de culture générale
        else:
            st.info("Ton jeu de culture générale s'affichera ici.")

    with tab_profil:
        profile_space(user, titre=False)


def profile_space(user: dict, titre: bool = True) -> None:
    """Informations du compte + changement de mot de passe."""
    if titre:
        st.title("Mon profil")
    role = get_user_role(user["username"]) or "user"
    st.subheader("Informations")
    st.write(f"**Nom d'utilisateur :** {user['username']}")
    st.write(f"**Identifiant :** {user['id']}")
    st.write(f"**Rôle :** {role}")

    st.subheader("Changer mon mot de passe")
    with st.form("form_change_mdp", clear_on_submit=True):
        ancien = st.text_input("Ancien mot de passe", type="password")
        nouveau = st.text_input("Nouveau mot de passe", type="password")
        confirm = st.text_input("Confirmer le nouveau mot de passe", type="password")
        envoye = st.form_submit_button("Modifier")

    if envoye:
        if nouveau != confirm:
            st.error("Les deux nouveaux mots de passe ne correspondent pas.")
        else:
            ok, message = change_password(user["username"], ancien, nouveau)
            (st.success if ok else st.error)(message)


# --------------------------------------------------------------------------- #
# ESPACE ADMIN
# --------------------------------------------------------------------------- #
def admin_space(user: dict) -> None:
    """Gestion des comptes : liste, rôles, mots de passe, suppression."""
    # Sécurité : on relit le rôle dans la base (la session peut être périmée)
    if get_user_role(user["username"]) != ROLE_ADMIN:
        st.error("Accès refusé : cet espace est réservé aux administrateurs.")
        st.stop()

    st.title("Espace administrateur")

    # message laissé par l'action précédente (affiché après le rafraîchissement)
    flash = st.session_state.pop("admin_flash", None)
    if flash:
        (st.success if flash[0] else st.error)(flash[1])

    utilisateurs = list_users(user["username"])
    noms = [u["username"] for u in utilisateurs]
    autres = [n for n in noms if n != user["username"]]     # on ne s'applique pas d'action à soi-même

    col1, col2 = st.columns(2)
    col1.metric("Comptes", len(utilisateurs))
    col2.metric("Administrateurs", sum(1 for u in utilisateurs if u["role"] == ROLE_ADMIN))

    tab_liste, tab_roles, tab_mdp, tab_suppr = st.tabs(
        ["📋 Utilisateurs", "🛡️ Rôles", "🔑 Mots de passe", "🗑️ Supprimer"]
    )

    def _terminer(resultat):
        """Mémorise le message puis recharge la page pour mettre à jour la liste."""
        st.session_state["admin_flash"] = resultat
        st.rerun()

    with tab_liste:
        st.dataframe(utilisateurs, use_container_width=True, hide_index=True)

    with tab_roles:
        if not autres:
            st.info("Il n'y a pas d'autre compte à gérer.")
        else:
            with st.form("form_role"):
                cible = st.selectbox("Utilisateur", autres, key="role_cible")
                role = st.selectbox("Nouveau rôle", ROLES, key="role_choisi")
                envoye = st.form_submit_button("Appliquer")
            if envoye:
                _terminer(set_role(user["username"], cible, role))

    with tab_mdp:
        if not autres:
            st.info("Il n'y a pas d'autre compte à gérer.")
        else:
            with st.form("form_reset_mdp", clear_on_submit=True):
                cible = st.selectbox("Utilisateur", autres, key="mdp_cible")
                nouveau = st.text_input(
                    f"Nouveau mot de passe (min. {MIN_PASSWORD} caractères)", type="password"
                )
                envoye = st.form_submit_button("Réinitialiser")
            if envoye:
                _terminer(reset_password(user["username"], cible, nouveau))

    with tab_suppr:
        if not autres:
            st.info("Il n'y a pas d'autre compte à supprimer.")
        else:
            with st.form("form_suppr"):
                cible = st.selectbox("Utilisateur à supprimer", autres, key="suppr_cible")
                sur = st.checkbox("Oui, je veux supprimer ce compte définitivement")
                envoye = st.form_submit_button("Supprimer")
            if envoye:
                if sur:
                    _terminer(delete_user(user["username"], cible))
                else:
                    st.warning("Coche la case pour confirmer la suppression.")