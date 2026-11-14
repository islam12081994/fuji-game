"""
interface_auth.py
Interface de connexion / inscription pour le jeu de culture générale (Streamlit).

Design : titre « sang » (Nosifer) coupé par un katana ; panneau sombre vertical façon sanctuaire japonais
  - toit de torii en haut, sceau « 侍 » rouge au centre
  - bordure rouge, champs à bordure rouge avec icônes dorées
  - bouton « Se connecter » en coup de pinceau rouge
  - bouton « Créer un compte » contour doré avec flèche

Utilisation dans ton app principale (app.py) :

    from interface_auth import require_auth, logout_button

    user = require_auth()          # bloque l'app tant que l'utilisateur n'est pas connecté
    logout_button()                # optionnel : bouton de déconnexion (sidebar)
    st.write(f"Bienvenue {user['username']} !")

Nécessite Streamlit >= 1.39 (st.container(key=...)).
"""

import base64
from pathlib import Path

import streamlit as st

# Adapte ce nom de module : c'est le fichier qui contient ton code SQLite/bcrypt.
from authentifications import get_user_id, get_user_role, init_db, login_user, register_user
from i18n import language_selector, t, tm

# ====================== PHOTO DE FOND ======================
BACKGROUND_IMAGE = Path("assets/samurai_cherry_petals_animated.gif")
BACKGROUND_SIZE = "cover"        # "cover", "contain", "100% 100%", "auto"...
BACKGROUND_POSITION = "center"
CARD_WIDTH = 440                 # largeur du panneau en px
# ===========================================================

MIN_USERNAME = 3
MIN_PASSWORD = 6

MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Nosifer&family=Cormorant+Garamond:wght@500;600;700&family=Playfair+Display:ital,wght@1,600;1,700&family=Yuji+Syuku&display=swap');

:root {
    --red: #a3121c;
    --red-bright: #d42a2f;
    --gold: #c9a063;
    --cream: #f3e6c8;
    --ink: #0b0b0e;

    /* icônes (SVG intégrés) */
    --ico-user: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23c9a063'><circle cx='12' cy='8' r='4.5'/><path d='M3.5 21c0-4.7 3.8-7.5 8.5-7.5s8.5 2.8 8.5 7.5z'/></svg>");
    --ico-lock: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><rect x='5' y='10.5' width='14' height='10.5' rx='2' fill='%23c9a063'/><path d='M8 10.5V8a4 4 0 0 1 8 0v2.5' fill='none' stroke='%23c9a063' stroke-width='2'/></svg>");
    --ico-torii: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='%23f3e6c8'><path d='M1 4.5c5 1.5 17 1.5 22 0v2.6H1zM4.5 9h15v2h-15zM6 11h2.4v10H6zM15.6 11H18v10h-2.4z'/></svg>");
    --ico-userplus: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23c9a063' stroke-width='1.8' stroke-linecap='round'><circle cx='9' cy='8' r='3.5'/><path d='M2.5 20c0-4 3-6.5 6.5-6.5s6.5 2.5 6.5 6.5'/><path d='M19 8v6M16 11h6'/></svg>");
    --ico-flower: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><g fill='%23c9a063' opacity='.6'><circle cx='12' cy='5.5' r='4.2'/><circle cx='18.2' cy='10' r='4.2'/><circle cx='15.8' cy='17.5' r='4.2'/><circle cx='8.2' cy='17.5' r='4.2'/><circle cx='5.8' cy='10' r='4.2'/></g><circle cx='12' cy='12' r='2.4' fill='%230d0d10'/></svg>");
    --ico-flower-pink: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><g fill='%23ffa3bd'><circle cx='12' cy='5.5' r='4.6'/><circle cx='18.2' cy='10' r='4.6'/><circle cx='15.8' cy='17.5' r='4.6'/><circle cx='8.2' cy='17.5' r='4.6'/><circle cx='5.8' cy='10' r='4.6'/></g><circle cx='12' cy='12' r='2.6' fill='%23d81b60'/></svg>");
    --ico-cloud: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 60 30' fill='none' stroke='%23c9a063' stroke-width='1.6' stroke-linecap='round'><path d='M3 25c6 0 8-6 14-6s6 6 12 6M17 19c0-6 6-10 12-8s6 8 0 8M29 11c2-6 10-8 14-3s0 9-6 8M37 16c6 0 10 4 14 4s5-3 5-6'/></svg>");
    --ico-corner-bl: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 28 28' fill='none' stroke='%23c4202a' stroke-width='2'><path d='M2 2v24h24M7 2v19h19M12 2v14h14M17 8h5v5'/></svg>");
    --ico-corner-br: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 28 28' fill='none' stroke='%23c4202a' stroke-width='2'><path d='M26 2v24H2M21 2v19H2M16 2v14H2M11 8H6v5'/></svg>");
    --ico-branch: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 160 70'><defs><g id='f'><g fill='%23ffa3bd'><circle cy='-5' r='4.4'/><circle cx='4.8' cy='-1.5' r='4.4'/><circle cx='3' cy='4' r='4.4'/><circle cx='-3' cy='4' r='4.4'/><circle cx='-4.8' cy='-1.5' r='4.4'/></g><circle r='2' fill='%23d81b60'/></g></defs><path d='M0 64C40 52 70 42 100 30S140 12 158 8' fill='none' stroke='%23412018' stroke-width='3'/><use href='%23f' x='98' y='28'/><use href='%23f' x='126' y='16'/><use href='%23f' x='72' y='42'/><use href='%23f' x='148' y='9'/><use href='%23f' x='50' y='52'/></svg>");
    --ico-lantern: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 30 90'><path d='M15 0V22' stroke='%23c9a063' stroke-width='1.5'/><rect x='9' y='20' width='12' height='4' fill='%23c9a063'/><ellipse cx='15' cy='38' rx='10' ry='14' fill='%23d6402a'/><ellipse cx='15' cy='38' rx='10' ry='14' fill='none' stroke='%23f0b060' stroke-width='1.5'/><rect x='9' y='50' width='12' height='4' fill='%23c9a063'/><path d='M15 54v16' stroke='%23b0121b' stroke-width='3'/><path d='M12 70h6l-1 14h-4z' fill='%23b0121b'/></svg>");
    --ico-roof: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 600 60' preserveAspectRatio='none'><path d='M120 38L132 24H468L480 38Z' fill='%23101014' stroke='%23a3121c' stroke-width='3' stroke-linejoin='round'/><path d='M2 6Q50 34 120 36H480Q550 34 598 6L586 40Q540 52 480 54H120Q60 52 14 40Z' fill='%23101014' stroke='%23a3121c' stroke-width='3' stroke-linejoin='round'/><path d='M40 45Q80 49 130 49H470Q520 49 560 45' fill='none' stroke='%23a3121c' stroke-width='2'/></svg>");
}

/* ---------- Page ---------- */
.stApp { background: #0f1923; font-family: 'Cormorant Garamond', serif; }
header[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer { visibility: hidden; }
.block-container {
    width: 100% !important;
    max-width: 760px !important;
    margin-left: auto !important;
    margin-right: auto !important;
    padding-top: 14vh;
}

/* ---------- Panneau principal ---------- */
.st-key-auth_card {
    position: relative;
    overflow: visible;
    margin: 3.2rem auto 0;
    padding: 0 2.2rem 2.2rem;
    background:
        var(--ico-corner-bl) no-repeat left 8px bottom 8px / 30px 30px,
        var(--ico-corner-br) no-repeat right 8px bottom 8px / 30px 30px,
        radial-gradient(circle at 50% 0%, rgba(163,18,28,.16), transparent 55%),
        linear-gradient(180deg, rgba(0,0,0,.55), rgba(0,0,0,.68));
    -webkit-backdrop-filter: blur(2px);
    backdrop-filter: blur(2px);
    border: 3px solid var(--red);
    border-radius: 3px;
    box-shadow:
        inset 0 0 0 5px rgba(0,0,0,.25),
        inset 0 0 0 6px rgba(163,18,28,.55),
        0 24px 70px rgba(0,0,0,.75);
}
/* toit du sanctuaire (SVG) */
.st-key-auth_card::before {
    content: "";
    position: absolute;
    top: -48px; left: -72px; right: -72px;
    height: 60px;
    background: var(--ico-roof) no-repeat center / 100% 100%;
    pointer-events: none;
}

/* ---------- Décors (lanternes, nuages, fleurs) ---------- */
.deco { position: absolute; pointer-events: none; z-index: 3; background-repeat: no-repeat; }
.deco-branch { left: 50%; top: -34px; width: 44%; height: 78px; background-image: var(--ico-branch); background-size: contain; background-position: left center; }
.deco-lantern-l, .deco-lantern-r { top: -8px; width: 24px; height: 74px; background-image: var(--ico-lantern); background-size: contain; }
.deco-lantern-l { left: 14px; }
.deco-lantern-r { right: 14px; }
.deco-cloud-l { left: 7%; top: 46px; width: 74px; height: 37px; background-image: var(--ico-cloud); background-size: contain; }
.deco-flower-r, .deco-flower-l {
    width: 66px; height: 46px;
    background: var(--ico-flower-pink) no-repeat 34% 0 / 24px, var(--ico-cloud) no-repeat 0 100% / 58px;
}
.deco-flower-r { right: -34px; top: 46%; }
.deco-flower-l { left: -36px; bottom: 17%; }
.deco-swirl { right: 5%; bottom: 25%; width: 46px; height: 24px; background-image: var(--ico-cloud); background-size: contain; }
.st-key-auth_card [data-testid="stForm"] { background: transparent; border: none; padding: 0; }
.st-key-auth_card [data-testid="stVerticalBlock"] { gap: .8rem; }

/* ---------- Sceau + titre ---------- */
.seal-wrap { display: flex; justify-content: center; margin-top: -3.2rem; position: relative; z-index: 2; }
.seal {
    width: 92px; height: 92px;
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    background: radial-gradient(circle, #111 55%, #1a0508 100%);
    border: 5px solid var(--red);
    outline: 2px solid rgba(163,18,28,.55);
    outline-offset: 3px;
    box-shadow: 0 0 0 2px var(--ink), 0 6px 18px rgba(0,0,0,.7);
    font-family: 'Yuji Syuku', serif;
    font-size: 3.2rem;
    color: var(--cream);
    line-height: 1;
}
/* ---------- Titre : sang + coup de katana ---------- */
.katana-wrap { display: flex; justify-content: center; margin: .6rem 0 .1rem; }
.katana {
    position: relative;
    display: inline-grid;
    font-family: 'Nosifer', 'Creepster', cursive;
    font-size: var(--fs, 1.4rem);
    line-height: 1.15;
    color: var(--red-bright);
}
.katana .cut {
    grid-area: 1 / 1;
    padding: .3em 0;
    white-space: nowrap;
    text-shadow: 0 0 6px rgba(176,0,32,.55), 0 2px 0 rgba(40,0,0,.85);
}
.katana .cut-a {
    clip-path: polygon(-10% -50%, 110% -50%, 110% 4.9%, -10% 96.1%);
    transform: translate(-2px, -3px);
    animation: split-a .2s .35s ease-out both;
}
.katana .cut-b {
    clip-path: polygon(-10% 96.1%, 110% 4.9%, 110% 150%, -10% 150%);
    transform: translate(2px, 3px);
    animation: split-b .2s .35s ease-out both;
}
.katana .slash {
    position: absolute;
    top: 0; bottom: 0; left: -6%; right: -6%;
    pointer-events: none;
    animation: slash-in .3s .1s ease-out both;
}
.katana .slash-glow {
    width: 100%; height: 100%;
    filter: drop-shadow(0 0 3px #fff) drop-shadow(0 0 8px rgba(255,255,255,.6));
}
.katana .slash-blade {
    width: 100%; height: 100%;
    background: linear-gradient(100deg, #ffffff, #d9e2ea 55%, #ffffff);
    clip-path: polygon(0 93%, 50% 46.5%, 100% 7.9%, 50% 54.5%);
}
@keyframes slash-in {
    from { clip-path: inset(-12px 100% -12px -12px); }
    to   { clip-path: inset(-12px -12px -12px -12px); }
}
@keyframes split-a { from { transform: none; } to { transform: translate(-2px, -3px); } }
@keyframes split-b { from { transform: none; } to { transform: translate(2px, 3px); } }
.auth-sub {
    margin: 0 0 .8rem;
    text-align: center;
    font-family: 'Cormorant Garamond', serif;
    font-weight: 700;
    font-size: 1.05rem;
    letter-spacing: .28em;
    color: #fff1d0;
}

/* ---------- Champs ---------- */
.st-key-auth_card [data-testid="stTextInput"] [data-baseweb="input"] {
    background-color: rgba(0,0,0,.5);
    background-repeat: no-repeat;
    background-position: .95rem center, calc(100% - .85rem) center;
    background-size: 1.3rem, 1.15rem;
    border: 1.5px solid var(--red);
    border-radius: 10px;
    min-height: 3.1rem;
    padding-right: 2.1rem;
    box-shadow: inset 0 0 0 2px rgba(0,0,0,.25), inset 0 0 0 3px rgba(163,18,28,.45);
}
.st-key-auth_card [data-testid="stTextInput"] [data-baseweb="input"]:focus-within { border-color: #ff4a4a; }
.st-key-auth_card [data-testid="stTextInput"] [data-baseweb="base-input"] { background: transparent; }
.st-key-login_user [data-baseweb="input"],
.st-key-reg_user [data-baseweb="input"] { background-image: var(--ico-user), var(--ico-flower); }
.st-key-login_pwd [data-baseweb="input"],
.st-key-reg_pwd [data-baseweb="input"],
.st-key-reg_confirm [data-baseweb="input"] { background-image: var(--ico-lock), var(--ico-flower); }
.st-key-auth_card [data-testid="stTextInput"] input {
    padding-left: 2.8rem;
    background: transparent !important;      /* zone noire transparente (portée par le conteneur) */
    color: #f6dc9b !important;               /* écriture dorée */
    -webkit-text-fill-color: #f6dc9b;
    caret-color: #f6dc9b;
    font-family: 'Cormorant Garamond', serif;
    font-size: 1.1rem;
    font-weight: 700;
}
/* remplissage automatique du navigateur : garde le fond transparent et le texte doré */
.st-key-auth_card [data-testid="stTextInput"] input:-webkit-autofill {
    -webkit-text-fill-color: #f6dc9b;
    transition: background-color 9999s ease-in-out 0s;
}
.st-key-auth_card [data-testid="stTextInput"] input::placeholder { color: rgba(240,215,160,.85); -webkit-text-fill-color: rgba(240,215,160,.85); }
.st-key-auth_card [data-testid="stTextInput"] button { color: var(--gold); background: transparent; }

/* zone de saisie : toujours noir transparent (jamais blanc), quel que soit le thème Streamlit */
.st-key-auth_card [data-testid="stTextInput"] [data-baseweb="input"],
.st-key-auth_card [data-testid="stTextInputRootElement"] {
    background-color: rgba(0,0,0,.55) !important;
    color-scheme: dark;
}
.st-key-auth_card [data-testid="stTextInput"] [data-baseweb="base-input"],
.st-key-auth_card [data-testid="stTextInput"] input,
.st-key-auth_card [data-testid="stTextInput"] button {
    background: transparent !important;
    background-color: transparent !important;
}

/* ---------- Case « Se souvenir de moi » ---------- */
.st-key-auth_card [data-testid="stCheckbox"] label span:first-child {
    background: rgba(0,0,0,.5) !important;
    border-color: #5a1a1f !important;
}
.st-key-auth_card [data-testid="stCheckbox"] p {
    color: #fff1d0;
    font-family: 'Cormorant Garamond', serif;
    font-size: 1.05rem;
    font-weight: 600;
}

/* ---------- Bouton principal : coup de pinceau rouge, centré et long ---------- */
.st-key-auth_card [data-testid="stFormSubmitButton"] {
    display: flex;
    justify-content: center;
}
.st-key-auth_card [data-testid="stFormSubmitButton"] button {
    flex: 0 0 auto;
    width: calc(100% + 2.6rem);   /* dépasse un peu des champs : plus long */
    min-height: 3.4rem;
    padding: 0 3rem;
    border: none;
    background:
        var(--ico-torii) no-repeat 14% center / 1.7rem,
        linear-gradient(100deg, #86101a, var(--red-bright) 50%, #92101a);
    clip-path: polygon(1% 38%, 4% 18%, 12% 8%, 22% 14%, 36% 4%, 52% 10%, 68% 2%, 84% 9%, 95% 16%, 99% 34%, 97% 52%, 100% 70%, 93% 84%, 80% 92%, 66% 100%, 50% 94%, 34% 99%, 18% 92%, 8% 96%, 2% 78%, 0 58%);
    color: var(--cream);
    font-family: 'Playfair Display', serif;
    font-style: italic;
    font-weight: 700;
    font-size: 1.4rem;
    text-align: center;
    text-shadow: 0 1px 4px rgba(0,0,0,.6);
    transition: filter .12s ease;
}
.st-key-auth_card [data-testid="stFormSubmitButton"] button:hover { filter: brightness(1.18); }

/* ---------- Bouton « Créer un compte » ---------- */
.st-key-switch_mode { width: 82%; margin: .2rem auto 0; }
.st-key-switch_mode button {
    position: relative;
    width: 100%;
    min-height: 3rem;
    padding: 0 2.4rem;
    background: rgba(0,0,0,.45) var(--ico-userplus) no-repeat 1.1rem center / 1.3rem;
    border: 1px solid rgba(201,160,99,.6);
    border-radius: 6px;
    box-shadow: inset 0 0 0 2px rgba(0,0,0,.25), inset 0 0 0 3px rgba(163,18,28,.5);
    color: #fff6e0;
    font-family: 'Cormorant Garamond', serif;
    font-size: 1.15rem;
    font-weight: 700;
}
.st-key-switch_mode button::after {
    content: "→";
    position: absolute;
    right: 1.1rem;
    top: 50%;
    transform: translateY(-52%);
    color: var(--gold);
    font-size: 1.3rem;
}
.st-key-switch_mode button:hover { border-color: var(--gold); color: #fff; background-color: rgba(163,18,28,.25); }

.st-key-auth_card [data-testid="stAlert"] { border-radius: 10px; padding: .5rem .75rem; }

@media (max-width: 640px) {
    .st-key-auth_card { padding: 0 1rem 2rem; }
    .st-key-auth_card::before { left: -16px; right: -16px; }
    .deco-flower-r, .deco-flower-l { display: none; }
}
@media (prefers-reduced-motion: reduce) {
    .katana .slash, .katana .cut-a, .katana .cut-b { animation: none; }
    .st-key-auth_card [data-testid="stFormSubmitButton"] button { transition: none; }
}

/* ---------- Sélecteur de langue (en haut à droite) ---------- */
.st-key-lang_bar { position: fixed; top: .9rem; right: 1.2rem; width: 175px; z-index: 1000; }
.st-key-lang_bar [data-baseweb="select"] > div {
    background: rgba(0,0,0,.65); border: 1.5px solid var(--red); border-radius: 10px;
}
.st-key-lang_bar [data-baseweb="select"] div,
.st-key-lang_bar [data-baseweb="select"] span { color: #fff1d0 !important; font-weight: 700; }
.st-key-lang_bar svg { fill: var(--gold); }
</style>
"""


# --------------------------------------------------------------------------- #
# Utilitaires
# --------------------------------------------------------------------------- #
@st.cache_resource
def _setup_db() -> bool:
    init_db()
    return True


@st.cache_data(show_spinner=False)
def _data_uri(path_str: str, mtime: float) -> str:
    """Encode une image en data URI (mtime rafraîchit le cache si le fichier change)."""
    path = Path(path_str)
    mime = MIME_TYPES.get(path.suffix.lower(), "image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _background_css() -> str:
    """Photo de fond de la page + largeur du panneau."""
    css = f".st-key-auth_card {{ width: min({CARD_WIDTH}px, 100%); }}"
    if BACKGROUND_IMAGE.exists():
        uri = _data_uri(str(BACKGROUND_IMAGE), BACKGROUND_IMAGE.stat().st_mtime)
        css += f"""
        .stApp {{
            background-color: #0f1923;
            background-image: url("{uri}");
            background-size: {BACKGROUND_SIZE};
            background-position: {BACKGROUND_POSITION};
            background-repeat: no-repeat;
            background-attachment: fixed;
        }}"""
    return f"<style>{css}</style>"


def _header(title: str, subtitle: str) -> None:
    """Sceau « 侍 », titre « sang » coupé par un coup de katana, sous-titre."""
    size = min(1.4, 22 / len(title))  # les titres longs rétrécissent pour tenir dans le panneau
    st.markdown(
        '<div class="deco deco-lantern-l"></div><div class="deco deco-lantern-r"></div>'
        '<div class="deco deco-branch"></div><div class="deco deco-cloud-l"></div>'
        '<div class="deco deco-flower-r"></div><div class="deco deco-flower-l"></div>'
        '<div class="deco deco-swirl"></div>'
        '<div class="seal-wrap"><div class="seal">侍</div></div>'
        f'<div class="katana-wrap"><div class="katana" style="--fs:{size:.2f}rem">'
        f'<span class="cut cut-a">{title}</span>'
        f'<span class="cut cut-b" aria-hidden="true">{title}</span>'
        '<div class="slash" aria-hidden="true"><div class="slash-glow">'
        '<div class="slash-blade"></div></div></div>'
        "</div></div>"
        f'<p class="auth-sub">{subtitle}</p>',
        unsafe_allow_html=True,
    )


def _init_state() -> None:
    st.session_state.setdefault("authenticated", False)
    st.session_state.setdefault("user", None)
    st.session_state.setdefault("auth_page", "login")
    st.session_state.setdefault("auth_flash", None)


def _switch_to(page: str) -> None:
    st.session_state.auth_page = page


# --------------------------------------------------------------------------- #
# Écrans
# --------------------------------------------------------------------------- #
def _login_view() -> None:
    _header(t("auth_welcome_title"), t("auth_welcome_sub"))

    if st.session_state.auth_flash:
        st.success(tm(st.session_state.auth_flash) + " " + t("can_login"))
        st.session_state.auth_flash = None

    with st.form("login_form"):
        username = st.text_input(
            t("auth_username"), placeholder=t("auth_username"),
            label_visibility="collapsed", key="login_user",
        )
        password = st.text_input(
            t("auth_password"), type="password", placeholder=t("auth_password"),
            label_visibility="collapsed", key="login_pwd",
        )
        st.checkbox(t("auth_remember"), key="remember_me")
        submitted = st.form_submit_button(t("auth_login"))

    if submitted:
        username = username.strip()
        if not username or not password:
            st.error(t("auth_fill"))
        else:
            ok, message = login_user(username, password)
            if ok:
                st.session_state.authenticated = True
                st.session_state.user = {"id": get_user_id(username), "username": username,
                                         "role": get_user_role(username)}
                st.rerun()
            else:
                st.error(tm(message))

    st.button(t("auth_create_account"), key="switch_mode", on_click=_switch_to, args=("register",))


def _register_view() -> None:
    _header(t("reg_title"), t("reg_sub"))

    with st.form("register_form"):
        username = st.text_input(
            t("auth_username"), placeholder=t("auth_username"),
            label_visibility="collapsed", key="reg_user",
        )
        password = st.text_input(
            t("auth_password"), type="password", placeholder=t("auth_password"),
            label_visibility="collapsed", key="reg_pwd",
        )
        confirm = st.text_input(
            t("reg_confirm"), type="password",
            placeholder=t("reg_confirm"),
            label_visibility="collapsed", key="reg_confirm",
        )
        submitted = st.form_submit_button(t("reg_submit"))

    if submitted:
        username = username.strip()
        if len(username) < MIN_USERNAME:
            st.error(t("reg_username_min", n=MIN_USERNAME))
        elif len(password) < MIN_PASSWORD:
            st.error(t("reg_pwd_min", n=MIN_PASSWORD))
        elif password != confirm:
            st.error(t("reg_mismatch"))
        else:
            ok, message = register_user(username, password)
            if ok:
                st.session_state.auth_flash = message
                st.session_state.auth_page = "login"
                st.rerun()
            else:
                st.error(tm(message))

    st.button(t("reg_have_account"), key="switch_mode", on_click=_switch_to, args=("login",))


# --------------------------------------------------------------------------- #
# API publique
# --------------------------------------------------------------------------- #
def render_auth() -> bool:
    """Affiche l'écran de connexion/inscription. Retourne True si connecté."""
    try:
        st.set_page_config(page_title="Quiz de cultures générales ", page_icon="🏯", layout="centered")
    except st.errors.StreamlitAPIException:
        pass  # déjà défini par l'app principale

    _setup_db()
    _init_state()

    if st.session_state.authenticated:
        return True

    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(_background_css(), unsafe_allow_html=True)

    with st.container(key="lang_bar"):
        language_selector(where="main", key="lang_widget_login", compact=True)

    with st.container(key="auth_card"):
        if st.session_state.auth_page == "register":
            _register_view()
        else:
            _login_view()
    return False


def require_auth() -> dict:
    """À appeler en haut de l'app : stoppe l'exécution tant que l'utilisateur n'est pas connecté.
    Retourne {"id": ..., "username": ..., "role": "admin" ou "user"}."""
    if not render_auth():
        st.stop()
    return st.session_state.user


_APP_KEYS = ("dash_page", "dash_flash", "room_code", "q_mode", "q_proposals", "manual_n",
             "solo", "admin_flash", "restored_for")


def logout_button(label: str | None = None) -> None:
    """Bouton de déconnexion (placé dans la sidebar)."""
    if st.sidebar.button(label or t("logout"), key="logout_btn", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.user = None
        st.session_state.auth_page = "login"
        # On vide l'état de navigation (la room, elle, reste enregistrée dans la base : on la retrouve à la reconnexion)
        for cle in list(st.session_state.keys()):
            if cle in _APP_KEYS or cle.startswith("game_last"):
                del st.session_state[cle]
        st.rerun()


if __name__ == "__main__":
    user = require_auth()
    logout_button()
    st.title(f"Bienvenue {user['username']} ⛩️")