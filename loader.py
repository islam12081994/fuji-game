"""
loader.py - GIF de chargement (assets/loading.gif).
  - loading_screen()  : plein écran, utilisé 5 secondes après la connexion ;
  - gif_html(width)   : le GIF seul, utilisé pendant le compte à rebours de lancement d'une partie.
"""
import base64
import time
from pathlib import Path

import streamlit as st

GIF_PATH = Path(__file__).parent / "assets" / "loading.gif"
LOGIN_SECONDS = 5


@st.cache_data(show_spinner=False)
def _gif_uri(mtime: float) -> str:
    return "data:image/gif;base64," + base64.b64encode(GIF_PATH.read_bytes()).decode()


def gif_html(width: int = 420) -> str:
    """Balise <img> du GIF (chaîne vide si le fichier n'existe pas)."""
    if not GIF_PATH.exists():
        return ""
    return (f'<div style="text-align:center"><img src="{_gif_uri(GIF_PATH.stat().st_mtime)}" alt="" '
            f'style="width:min({width}px,90%);border-radius:14px"></div>')


def show_gif(width: int = 420) -> None:
    html_ = gif_html(width)
    if html_:
        st.markdown(html_, unsafe_allow_html=True)


def loading_screen(seconds: float = LOGIN_SECONDS, text: str = "") -> None:
    """Affiche le GIF en plein écran pendant `seconds` secondes (bloque le script, puis l'appelant relance)."""
    html_ = gif_html(520)
    if not html_:
        return
    zone = st.empty()
    zone.markdown(
        '<div style="position:fixed;inset:0;z-index:999999;background:#000;display:flex;flex-direction:column;'
        f'align-items:center;justify-content:center;gap:1rem">{html_}'
        f'<div style="color:#F0CF8A;font-size:1.2rem;letter-spacing:.1em">{text}</div></div>',
        unsafe_allow_html=True)
    time.sleep(seconds)
    zone.empty()
