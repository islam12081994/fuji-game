"""
navbar.py
Thème global (texte clair et bien lisible) + barre de navigation latérale,
dans la même ambiance que la page de connexion (rouge, or, sanctuaire japonais).

Utilisation (dans main.py, une fois l'utilisateur connecté) :
    from navbar import render_navbar
    page = render_navbar(user, role, ["dashboard", "profile", "admin"])
"""
import html

import streamlit as st

from i18n import language_selector, t
from interface_auth import logout_button

ICONS = {"dashboard": "🏯", "profile": "👤", "admin": "🛡️"}

# Couleurs : texte crème très clair (#FFF6E0) sur fond sombre, or clair (#F0CF8A) pour les accents
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@600;800&family=Nunito:wght@400;600;700;800&family=Cairo:wght@400;600;700&display=swap');

:root {
    --txt: #FFF6E0;
    --txt-soft: #E6D9BD;
    --gold: #F0CF8A;
    --red: #a3121c;
    --red-bright: #d42a2f;
}

/* ===================== Page ===================== */
.stApp {
    background: radial-gradient(circle at 20% 0%, #4a0d14 0%, #1a0b0d 55%);
    font-family: 'Nunito', 'Cairo', 'Segoe UI', sans-serif;
}
.stApp, .stApp p, .stApp li { font-size: 1.04rem; }
h1, h2, h3 { font-family: 'Cinzel', 'Cairo', serif; color: var(--gold) !important; letter-spacing: .02em; }
[data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p,
[data-testid="stWidgetLabel"] p, label, label p { color: var(--txt) !important; }
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: var(--txt-soft) !important; }

/* champs de saisie : fond sombre, texte clair, bordure dorée */
.stTextInput input, .stTextArea textarea, .stNumberInput input {
    background: #20100f !important; color: var(--txt) !important;
    border: 1px solid rgba(240,207,138,.55) !important; border-radius: 10px;
}
.stTextInput input::placeholder, .stTextArea textarea::placeholder { color: #bfae8b !important; }
[data-baseweb="select"] > div {
    background: #20100f !important; border: 1px solid rgba(240,207,138,.55) !important; border-radius: 10px;
}
[data-baseweb="select"] div, [data-baseweb="select"] span { color: var(--txt) !important; }

/* cartes, formulaires, statistiques */
div[data-testid="stForm"], div[data-testid="stVerticalBlockBorderWrapper"] {
    background: rgba(0,0,0,.30); border: 1px solid rgba(240,207,138,.35) !important; border-radius: 14px;
}
div[data-testid="stMetric"] {
    background: rgba(0,0,0,.35); border: 1px solid rgba(240,207,138,.35); border-radius: 12px; padding: .8rem 1rem;
}
div[data-testid="stMetricLabel"] p { color: var(--txt-soft) !important; }
div[data-testid="stMetricValue"] { color: var(--gold); }

/* onglets */
.stTabs [data-baseweb="tab"] p { color: var(--txt-soft) !important; font-weight: 700; }
.stTabs [aria-selected="true"] p { color: var(--gold) !important; }
.stTabs [data-baseweb="tab-highlight"] { background: var(--red-bright); }

/* boutons */
.stButton button, [data-testid="stFormSubmitButton"] button {
    border-radius: 10px; font-weight: 700; color: var(--txt);
    border: 1px solid rgba(240,207,138,.6); background: rgba(0,0,0,.45);
}
.stButton button:hover, [data-testid="stFormSubmitButton"] button:hover {
    border-color: var(--gold); background: rgba(163,18,28,.45); color: #fff;
}
.stButton button[kind="primary"], [data-testid="stFormSubmitButton"] button[kind="primary"] {
    background: linear-gradient(100deg, #86101a, var(--red-bright)); border-color: var(--gold);
}

/* ===================== Barre latérale ===================== */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #2a0a0f 0%, #120708 100%);
    border-right: 2px solid var(--red);
    box-shadow: 4px 0 24px rgba(0,0,0,.55);
    min-width: 270px;
}
[data-testid="stSidebar"] p, [data-testid="stSidebar"] label, [data-testid="stSidebar"] span { color: var(--txt); }

/* marque : sceau + nom */
.nav-brand { display: flex; align-items: center; gap: .8rem; padding: .4rem .2rem 1rem;
             border-bottom: 1px solid rgba(240,207,138,.3); margin-bottom: 1rem; }
.nav-seal {
    flex: 0 0 auto; width: 52px; height: 52px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    background: radial-gradient(circle, #111 55%, #2a060b 100%);
    border: 3px solid var(--red); outline: 1px solid rgba(163,18,28,.6); outline-offset: 2px;
    font-size: 1.7rem; color: var(--txt); line-height: 1;
}
.nav-title { font-family: 'Cinzel', 'Cairo', serif; font-weight: 800; font-size: 1.05rem;
             color: var(--gold); line-height: 1.25; }

/* carte utilisateur */
.nav-user { padding: .8rem 1rem; margin-bottom: 1rem; border-radius: 12px;
            background: rgba(0,0,0,.35); border: 1px solid rgba(240,207,138,.35); }
.nav-user-name { font-size: 1.15rem; font-weight: 800; color: var(--txt); word-break: break-word; }
.nav-role { display: inline-block; margin-top: .35rem; padding: .1rem .7rem; border-radius: 999px;
            background: var(--red); color: #fff; font-size: .85rem; font-weight: 700; letter-spacing: .03em; }

/* menu de navigation (boutons radio transformés en rubans) */
[data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] { gap: .45rem; }
[data-testid="stSidebar"] [data-testid="stRadio"] label {
    width: 100%; padding: .65rem .9rem; border-radius: 10px; cursor: pointer;
    background: rgba(0,0,0,.40); border: 1px solid rgba(240,207,138,.35);
    transition: background .12s ease, border-color .12s ease, transform .12s ease;
}
[data-testid="stSidebar"] [data-testid="stRadio"] label > div:first-child { display: none; }   /* cache le rond */
[data-testid="stSidebar"] [data-testid="stRadio"] label p { font-size: 1.08rem; font-weight: 700; color: var(--txt) !important; }
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
    border-color: var(--gold); background: rgba(163,18,28,.35); transform: translateX(3px);
}
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) {
    background: linear-gradient(100deg, #86101a, var(--red-bright));
    border-color: var(--gold); box-shadow: 0 4px 14px rgba(163,18,28,.5);
}
[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) p { color: #fff !important; }

/* déconnexion */
.st-key-logout_btn button {
    width: 100%; min-height: 2.8rem; background: rgba(0,0,0,.45); color: var(--txt);
    border: 1px solid rgba(240,207,138,.7); border-radius: 8px; font-weight: 700;
}
.st-key-logout_btn button:hover { border-color: var(--gold); background: rgba(163,18,28,.45); color: #fff; }
</style>
"""


def render_navbar(user: dict, role: str, pages: list[str]) -> str:
    """Applique le thème, dessine la barre latérale et retourne la page choisie ("dashboard", "profile", "admin")."""
    st.markdown(CSS, unsafe_allow_html=True)
    bar = st.sidebar

    bar.markdown(
        f'<div class="nav-brand"><div class="nav-seal">侍</div>'
        f'<div class="nav-title">{html.escape(t("app_name"))}</div></div>'
        f'<div class="nav-user"><div class="nav-user-name">{html.escape(user["username"])}</div>'
        f'<span class="nav-role">{html.escape(t("role_" + role))}</span></div>',
        unsafe_allow_html=True,
    )

    page = bar.radio(
        t("navigation"),
        pages,
        format_func=lambda p: f"{ICONS.get(p, '•')}  {t('nav_' + p)}",
        label_visibility="collapsed",
        key="nav_page",
    )

    bar.divider()
    language_selector(where="sidebar", key="lang_widget")
    logout_button()
    return page
