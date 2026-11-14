"""
avatar.py
Avatars des joueurs : au choix, un avatar prêt à l'emploi (emoji sur fond coloré) ou sa propre photo.
Sans choix, le joueur a un avatar par défaut (son initiale sur un fond coloré).

    avatar_html(avatar, nom, taille)  -> HTML d'un avatar rond (menu, salle d'attente, classement...)
    avatar_picker(user)               -> écran de choix (page « Mon profil »)
    prepare_image(octets)             -> valide et réduit une photo envoyée (sécurité)

Un avatar est enregistré dans la base (colonne `avatar` de la table users) sous la forme :
    None                      -> avatar par défaut
    "preset:ninja"            -> avatar prêt à l'emploi (voir PRESETS)
    "data:image/jpeg;base64,..." -> photo du joueur, recadrée en carré 128 x 128 et ré-encodée en JPEG
"""
import base64
import hashlib
import html
import io
import re

import streamlit as st
from PIL import Image, ImageOps, UnidentifiedImageError

from authentifications import get_avatar, set_avatar
from i18n import t

# id : (emoji, couleur 1, couleur 2)
PRESETS = {
    "ninja": ("🥷", "#27406b", "#0b1020"),
    "samourai": ("⚔️", "#8a1a1a", "#2a0508"),
    "oni": ("👹", "#b3172a", "#3a0509"),
    "renard": ("🦊", "#e8590c", "#7a2a05"),
    "dragon": ("🐉", "#0e8a5a", "#064030"),
    "sakura": ("🌸", "#d6478a", "#6a1e45"),
    "torii": ("⛩️", "#c0392b", "#5a140d"),
    "tigre": ("🐯", "#e8a317", "#6a4308"),
    "loup": ("🐺", "#5b6b7b", "#1f2933"),
    "hibou": ("🦉", "#7a4aa0", "#2f1a45"),
    "panda": ("🐼", "#2e8b57", "#10361f"),
    "aigle": ("🦅", "#237898", "#0b3447"),
    "lune": ("🌙", "#3d4a9a", "#161c45"),
    "etoile": ("⭐", "#c9a063", "#5a4119"),
}

MAX_BYTES = 2 * 1024 * 1024          # taille maximale du fichier envoyé
MAX_PIXELS = 25_000_000              # protège contre les images géantes
SIZE = 128                           # l'avatar enregistré fait 128 x 128 pixels
FORMATS = ("PNG", "JPEG", "WEBP")    # formats acceptés (pas de GIF, SVG...)
PHOTO_RE = re.compile(r"^data:image/jpeg;base64,[A-Za-z0-9+/=]{20,}$")


# --------------------------------------------------------------------------- #
# Affichage
# --------------------------------------------------------------------------- #
def avatar_html(avatar, nom: str = "", taille: int = 40) -> str:
    """HTML d'un avatar rond. `avatar` vient de la base ; toute valeur inconnue donne l'avatar par défaut."""
    base = (f"width:{taille}px;height:{taille}px;flex:0 0 {taille}px;border-radius:50%;"
            f"border:2px solid #F0CF8A;box-sizing:border-box;")
    if isinstance(avatar, str) and PHOTO_RE.match(avatar):
        return f'<img src="{avatar}" alt="" style="{base}object-fit:cover;display:block">'
    if isinstance(avatar, str) and avatar.startswith("preset:") and avatar[7:] in PRESETS:
        emoji, c1, c2 = PRESETS[avatar[7:]]
        return (f'<div style="{base}display:flex;align-items:center;justify-content:center;'
                f'background:linear-gradient(135deg,{c1},{c2});font-size:{int(taille * 0.52)}px;line-height:1">'
                f'{emoji}</div>')
    teinte = int(hashlib.md5((nom or "?").encode("utf-8")).hexdigest()[:6], 16) % 360   # couleur stable par nom
    initiale = html.escape((nom or "?").strip()[:1].upper() or "?")
    return (f'<div style="{base}display:flex;align-items:center;justify-content:center;'
            f'background:hsl({teinte},45%,32%);color:#FFF6E0;font-weight:800;font-size:{int(taille * 0.5)}px;'
            f'line-height:1">{initiale}</div>')


# --------------------------------------------------------------------------- #
# Photo envoyée par le joueur
# --------------------------------------------------------------------------- #
def prepare_image(octets: bytes):
    """Valide une photo et la transforme en avatar. Retourne (data_uri, None) ou (None, clé_du_message_d_erreur).
    L'image est entièrement ré-encodée (recadrée en carré, JPEG) : aucune donnée cachée du fichier d'origine n'est gardée."""
    if len(octets) > MAX_BYTES:
        return None, "av_err_size"
    try:
        img = Image.open(io.BytesIO(octets))
        if img.format not in FORMATS:
            return None, "av_err_type"
        if img.width * img.height > MAX_PIXELS:
            return None, "av_err_image"
        img = ImageOps.exif_transpose(img)                    # remet la photo à l'endroit
        rgba = img.convert("RGBA")
        fond = Image.new("RGB", rgba.size, "#20100f")         # les zones transparentes deviennent sombres
        fond.paste(rgba, mask=rgba.split()[3])
        carre = ImageOps.fit(fond, (SIZE, SIZE), method=Image.LANCZOS, centering=(0.5, 0.4))
        tampon = io.BytesIO()
        carre.save(tampon, "JPEG", quality=85, optimize=True)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None, "av_err_image"
    return "data:image/jpeg;base64," + base64.b64encode(tampon.getvalue()).decode("ascii"), None


# --------------------------------------------------------------------------- #
# Écran de choix (page « Mon profil »)
# --------------------------------------------------------------------------- #
def _enregistrer(username: str, valeur, message_cle: str) -> None:
    ok, message = set_avatar(username, valeur)
    st.session_state["avatar_flash"] = (ok, t(message_cle) if ok else message)


def avatar_picker(user: dict) -> None:
    st.subheader(t("av_title"))

    flash = st.session_state.pop("avatar_flash", None)
    if flash:
        (st.success if flash[0] else st.error)(flash[1])

    actuel = get_avatar(user["username"])
    col_photo, col_texte = st.columns([1, 4])
    col_photo.markdown(avatar_html(actuel, user["username"], 88), unsafe_allow_html=True)
    col_texte.write(t("av_hint"))

    # 1) avatars prêts à l'emploi
    st.write(t("av_choose"))
    ids = list(PRESETS)
    par_ligne = 7
    for debut in range(0, len(ids), par_ligne):
        colonnes = st.columns(par_ligne)
        for colonne, pid in zip(colonnes, ids[debut:debut + par_ligne]):
            emoji = PRESETS[pid][0]
            choisi = actuel == f"preset:{pid}"
            if colonne.button(f"{emoji} ✓" if choisi else emoji, key=f"av_pick_{pid}", use_container_width=True):
                _enregistrer(user["username"], f"preset:{pid}", "av_saved")
                st.rerun()

    # 2) sa propre photo
    fichier = st.file_uploader(t("av_upload"), type=["png", "jpg", "jpeg", "webp"], key="av_file")
    if fichier is not None:
        photo, erreur = prepare_image(fichier.getvalue())
        if erreur:
            st.error(t(erreur))
        else:
            st.markdown(avatar_html(photo, user["username"], 88), unsafe_allow_html=True)
            if st.button(t("av_use_photo"), key="av_use_photo", type="primary"):
                _enregistrer(user["username"], photo, "av_saved")
                st.rerun()

    # 3) retirer
    if actuel:
        if st.button(t("av_remove"), key="av_remove"):
            _enregistrer(user["username"], None, "av_removed")
            st.rerun()
