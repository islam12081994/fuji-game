"""
user/dashboard.py
Tableau de bord utilisateur (textes traduits avec i18n.t, langue choisie dans la barre latérale).

    - « Créer une room »  -> formulaire (publique ou privée), puis étape QUESTIONS avec 3 boutons :
                               1) ✍️ Création manuelle   (formulaire d'ajout de question)
                               2) 💡 Propositions par IA  (l'IA propose, tu coches celles que tu gardes)
                               3) 🤖 Générer par IA       (l'IA remplit toutes les questions restantes)
                             puis salle d'attente avec un code à partager
    - « Jouer »           -> jouer en solo OU rejoindre une room publique / avec son code

`jeu(user, room)` est ta fonction de jeu : `room` vaut None en solo, sinon un dictionnaire
{"code", "name", "players", "nb_questions", "is_public", "questions", ...}
où room["questions"] = [{"id", "question", "choices": [4 propositions], "answer": index}, ...].
"""
import html
import io
import os

import streamlit as st

from authentifications import get_avatars
from avatar import avatar_html
from i18n import get_lang, ia_language, t, tm
from user import questions_ai, room_i18n, rooms

LETTRES = "ABCD"

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@600;800&display=swap');

/* Fond de la page */
.stApp {
    background: radial-gradient(circle at 20% 0%, #3a0a10 0%, #14090b 55%);
}

/* Titres */
h1, h2, h3 { font-family: 'Cinzel', serif; color: #f0cf8a !important; letter-spacing: .02em; }

/* Bannière d'accueil */
.hero {
    padding: 1.6rem 2rem; margin-bottom: 1.5rem; border-radius: 16px;
    border: 1px solid rgba(201,160,99,.4);
    background: linear-gradient(120deg, rgba(163,18,28,.45), rgba(0,0,0,.35));
    box-shadow: 0 10px 30px rgba(0,0,0,.35);
}
.hero h1 { margin: 0; font-size: 2.2rem; }
.hero p  { margin: .3rem 0 0; color: #fff6e0; opacity: 1; font-size: 1.1rem; }

/* Cartes (rooms, questions, formulaires) */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background: rgba(0,0,0,.28);
    border: 1px solid rgba(201,160,99,.3) !important;
    border-radius: 12px;
}
div[data-testid="stForm"] {
    background: rgba(0,0,0,.25);
    border: 1px solid rgba(201,160,99,.3);
    border-radius: 14px;
}

/* Statistiques */
div[data-testid="stMetric"] {
    background: rgba(0,0,0,.3); border: 1px solid rgba(201,160,99,.3);
    border-radius: 12px; padding: .8rem 1rem;
}

/* Les deux gros boutons du tableau de bord */
.st-key-btn_create button, .st-key-btn_play button {
    min-height: 9rem;
    border-radius: 16px;
    border: 2px solid #a3121c;
    background: linear-gradient(160deg, rgba(0,0,0,.55), rgba(70,0,10,.6));
    color: #fff6e0;
    box-shadow: 0 8px 24px rgba(0,0,0,.35);
    transition: transform .12s ease, border-color .12s ease, box-shadow .12s ease;
}
.st-key-btn_create button p, .st-key-btn_play button p { font-size: 1.7rem; font-weight: 700; }
.st-key-btn_create button:hover, .st-key-btn_play button:hover {
    border-color: #c9a063; color: #fff; transform: translateY(-3px);
    box-shadow: 0 14px 30px rgba(163,18,28,.45);
}

/* Les 3 boutons de l'étape « questions » */
.st-key-btn_q_manual button, .st-key-btn_q_propose button, .st-key-btn_q_generate button {
    min-height: 5rem; border-radius: 12px; font-weight: 700;
}

/* Boutons normaux : coins arrondis */
.stButton button { border-radius: 10px; }

/* Code de la room, en grand */
.room-code {
    text-align: center; font-size: 3rem; font-weight: 800; letter-spacing: .4em;
    padding: .6rem 0 .6rem .4em; border: 2px dashed #c9a063; border-radius: 12px;
    color: #f0cf8a; background: rgba(0,0,0,.35);
}
</style>
"""


@st.cache_resource
def _setup() -> bool:
    rooms.init_rooms_db()
    return True


def _goto(page: str, **extra) -> None:
    """Change de page du tableau de bord (utilisé par les boutons via on_click)."""
    st.session_state["dash_page"] = page
    for cle, valeur in extra.items():
        st.session_state[cle] = valeur


def _flash(ok: bool, message: str) -> None:
    st.session_state["dash_flash"] = (ok, message)


def _visibilite(room: dict) -> str:
    return t("vis_public") if room.get("is_public", True) else t("vis_private")


# --------------------------------------------------------------------------- #
# Point d'entrée
# --------------------------------------------------------------------------- #
def user_dashboard(user: dict, jeu=None) -> None:
    _setup()
    st.markdown(CSS, unsafe_allow_html=True)

    flash = st.session_state.pop("dash_flash", None)
    if flash:
        (st.success if flash[0] else st.error)(flash[1])

    page = st.session_state.get("dash_page", "home")
    if page == "create":
        _page_create(user)
    elif page == "questions":
        _page_questions(user)
    elif page == "play":
        _page_play(user)
    elif page == "history":
        _page_history(user)
    elif page == "lobby":
        _page_lobby(user)
    elif page == "game":
        _page_game(user, jeu)
    else:
        _page_home(user)


# --------------------------------------------------------------------------- #
# Accueil
# --------------------------------------------------------------------------- #
def _page_home(user: dict) -> None:
    st.markdown(
        f'<div class="hero"><h1>{t("welcome", name=user["username"])}</h1>'
        f'<p>{t("tagline")}</p></div>',
        unsafe_allow_html=True,
    )

    ouvertes = rooms.list_open_rooms()
    m1, m2 = st.columns(2)
    m1.metric(t("metric_rooms"), len(ouvertes))
    m2.metric(t("metric_players"), sum(r["nb_players"] for r in ouvertes))

    st.write("")
    col1, col2 = st.columns(2, gap="large")
    with col1:
        st.button(t("btn_create"), key="btn_create", use_container_width=True,
                  on_click=_goto, args=("create",))
        st.caption(t("desc_create"))
    with col2:
        st.button(t("btn_play"), key="btn_play", use_container_width=True,
                  on_click=_goto, args=("play",))
        st.caption(t("desc_play"))

    st.button(t("btn_history"), key="btn_history", on_click=_goto, args=("history",))

    # Si le joueur est déjà dans une room, on lui propose d'y retourner
    code = rooms.active_room_of(user["id"])
    if code:
        st.divider()
        room = rooms.get_room(code)
        st.info(t("in_room", name=room["name"], code=code))
        st.button(t("back_room"), key="btn_back_room",
                  on_click=_goto, args=("game" if room["status"] == rooms.PLAYING else "lobby",),
                  kwargs={})
        st.session_state["room_code"] = code


# --------------------------------------------------------------------------- #
# Créer une room (étape 1 : réglages)
# --------------------------------------------------------------------------- #
def _page_create(user: dict) -> None:
    st.title(t("create_title"))
    with st.form("form_create_room"):
        nom = st.text_input(t("room_name"), placeholder=t("room_name_ph", name=user["username"]),
                            max_chars=40)
        max_joueurs = st.slider(t("max_players"), rooms.MIN_PLAYERS, rooms.MAX_PLAYERS, 6)
        nb_questions = st.slider(t("nb_questions"), rooms.MIN_QUESTIONS, rooms.MAX_QUESTIONS, 10)
        sans_temps = st.checkbox(t("solo_no_limit"), value=False, help=t("no_time_help"))
        temps = st.slider(t("time_per_q"), rooms.MIN_TIME, rooms.MAX_TIME, rooms.DEFAULT_TIME, step=5,
                          help=t("time_per_q_help"))
        publique = st.checkbox(t("public_label"), value=True, help=t("public_help"))
        envoye = st.form_submit_button(t("next_questions"))

    if envoye:
        ok, message, code = rooms.create_room(
            user["id"], user["username"], nom, max_joueurs, nb_questions, is_public=publique,
            time_per_question=rooms.NO_TIME if sans_temps else temps,
        )
        if ok:
            st.session_state["room_code"] = code
            st.session_state["q_mode"] = None
            st.session_state["q_proposals"] = []
            _flash(True, t("room_created", n=nb_questions))
            _goto("questions")
            st.rerun()
        else:
            st.error(tm(message))

    st.button(t("back"), key="back_create", on_click=_goto, args=("home",))


# --------------------------------------------------------------------------- #
# Créer une room (étape 2 : les questions, avec 3 boutons)
# --------------------------------------------------------------------------- #
def _set_mode(mode: str) -> None:
    st.session_state["q_mode"] = mode


def _page_questions(user: dict) -> None:
    code = st.session_state.get("room_code")
    room = rooms.get_room(code) if code else None
    if room is None or room["status"] != rooms.WAITING or room["host_id"] != user["id"]:
        _flash(False, t("q_no_access"))
        st.session_state["room_code"] = None
        _goto("home")
        st.rerun()

    questions = rooms.list_questions(room["id"])
    total = room["nb_questions"]
    restant = max(total - len(questions), 0)
    mode = st.session_state.get("q_mode")

    st.title(t("q_title", name=room["name"]))
    st.progress(min(len(questions) / total, 1.0),
                text=t("q_progress", done=len(questions), total=total))

    # Les 3 boutons
    c1, c2, c3 = st.columns(3, gap="medium")
    with c1:
        st.button(t("q_manual"), key="btn_q_manual", use_container_width=True,
                  type="primary" if mode == "manual" else "secondary",
                  on_click=_set_mode, args=("manual",))
    with c2:
        st.button(t("q_propose"), key="btn_q_propose", use_container_width=True,
                  type="primary" if mode == "propose" else "secondary",
                  on_click=_set_mode, args=("propose",))
    with c3:
        st.button(t("q_generate"), key="btn_q_generate", use_container_width=True,
                  type="primary" if mode == "generate" else "secondary",
                  on_click=_set_mode, args=("generate",))

    st.divider()
    if restant == 0:
        st.success(t("q_all_ready"))
    elif mode == "manual":
        _q_manual(room, user)
    elif mode == "propose":
        _q_propose(room, user, questions, restant)
    elif mode == "generate":
        _q_generate(room, user, questions, restant)
    else:
        st.info(t("q_hint"))

    # Questions déjà ajoutées
    if questions:
        st.subheader(t("q_added"))
        st.caption(t("q_answers_hidden"))
        for i, q in enumerate(questions, start=1):
            with st.container(border=True):
                a, b = st.columns([8, 1])
                a.markdown(f"**{i}. {q['question']}**")
                if q["kind"] == "open":
                    a.write(t("q_open_tag"))                      # la réponse attendue reste masquée
                else:
                    for j, choix in enumerate(q["choices"]):
                        a.write(f"▫️ {LETTRES[j]}. {choix}")      # la bonne réponse reste masquée
                if b.button("🗑️", key=f"del_q_{q['id']}", help=t("q_delete")):
                    ok, message = rooms.delete_question(room["code"], user["id"], q["id"])
                    if not ok:
                        _flash(False, tm(message))
                    st.rerun()

    st.divider()
    d1, d2 = st.columns(2)
    d1.button(t("q_continue"), key="btn_q_continue", use_container_width=True,
              type="primary", disabled=restant > 0, on_click=_goto, args=("lobby",))
    if d2.button(t("q_cancel"), key="btn_q_cancel", use_container_width=True):
        rooms.leave_room(room["code"], user["id"])      # l'hôte quitte -> room fermée
        st.session_state["room_code"] = None
        _goto("home")
        st.rerun()


def _q_manual(room: dict, user: dict) -> None:
    """Bouton 1 : formulaire pour ajouter une question à la main (réponse libre OU à choix)."""
    st.subheader(t("m_title"))
    genre = st.radio(t("m_kind"), ["open", "qcm"], horizontal=True, key="manual_kind",
                     format_func=lambda k: t("qtype_" + k))
    n = st.session_state.get("manual_n", 0)      # change après un ajout -> le formulaire se vide
    with st.form(f"form_q_manual_{genre}_{n}"):
        question = st.text_area(t("m_question"), max_chars=300, key=f"m_q_{genre}_{n}")
        if genre == "open":
            reference = st.text_input(t("m_reference"), max_chars=200, key=f"m_ref_{n}")
        else:
            choix = [st.text_input(t("m_choice_n", l=LETTRES[j]), max_chars=120, key=f"m_c{j}_{n}")
                     for j in range(rooms.NB_CHOICES)]
            bonne = st.selectbox(t("m_correct"), range(rooms.NB_CHOICES), key=f"m_ok_{n}",
                                 format_func=lambda j: LETTRES[j])
        envoye = st.form_submit_button(t("m_add"))

    if envoye:
        q = ({"kind": "open", "question": question, "reference": reference} if genre == "open"
             else {"kind": "qcm", "question": question, "choices": choix, "answer": bonne})
        ok, message, _ = rooms.add_questions(room["code"], user["id"], [q], lang=get_lang())
        if ok:
            st.session_state["manual_n"] = n + 1
            _flash(True, tm(message))
            st.rerun()
        else:
            st.error(tm(message))


def _q_propose(room: dict, user: dict, questions: list, restant: int) -> None:
    """Bouton 2 : l'IA propose des questions (à choix, à réponse libre ou les deux), l'hôte coche celles qu'il garde."""
    st.subheader(t("p_title"))
    st.caption(t("p_caption"))
    with st.form("form_q_propose"):
        theme = st.text_input(t("theme"), value=t("default_theme"), max_chars=60)
        niveau = st.selectbox(t("difficulty"), questions_ai.DIFFICULTES, index=1,
                              format_func=lambda d: t("diff_" + d))
        types = st.radio(t("qtype_label"), questions_ai.TYPES, index=2, horizontal=True,
                         format_func=lambda k: t("qtype_" + k))
        nb = st.slider(t("p_count"), 3, 10, 6)
        envoye = st.form_submit_button(t("p_btn"))

    if envoye:
        try:
            with st.spinner(t("p_spinner")):
                st.session_state["q_proposals"] = questions_ai.generate_mixed(
                    theme, nb, niveau, types, exclude=[q["question"] for q in questions],
                    langue=ia_language(),
                )
        except Exception as e:                       # clé manquante, réseau, réponse invalide...
            st.error(t("ai_error", error=e))

    propositions = st.session_state.get("q_proposals", [])
    if not propositions:
        return

    st.write(t("p_check", n=restant))
    st.caption(t("q_answers_hidden"))
    choisies = []
    for i, p in enumerate(propositions):
        with st.container(border=True):
            etiquette = t("qtype_" + p.get("kind", "open"))
            if st.checkbox(f"**{p['question']}**  ({etiquette})", key=f"prop_{i}"):
                choisies.append(p)

    if st.button(t("p_add"), key="btn_add_props", disabled=not choisies):
        ok, message, _ = rooms.add_questions(room["code"], user["id"], choisies, lang=get_lang())
        if ok:
            st.session_state["q_proposals"] = []
            _flash(True, tm(message))
            st.rerun()
        else:
            st.error(tm(message))


def _q_generate(room: dict, user: dict, questions: list, restant: int) -> None:
    """Bouton 3 : l'IA génère directement toutes les questions restantes (type au choix)."""
    st.subheader(t("g_title"))
    st.caption(t("g_caption", n=restant))
    with st.form("form_q_generate"):
        theme = st.text_input(t("theme"), value=t("default_theme"), max_chars=60)
        niveau = st.selectbox(t("difficulty"), questions_ai.DIFFICULTES, index=1,
                              format_func=lambda d: t("diff_" + d))
        types = st.radio(t("qtype_label"), questions_ai.TYPES, index=2, horizontal=True,
                         format_func=lambda k: t("qtype_" + k))
        envoye = st.form_submit_button(t("g_btn", n=restant))

    if envoye:
        try:
            with st.spinner(t("g_spinner")):
                generees = questions_ai.generate_mixed(
                    theme, restant, niveau, types, exclude=[q["question"] for q in questions],
                    langue=ia_language(),
                )
        except Exception as e:
            st.error(t("ai_error", error=e))
            return
        ok, message, _ = rooms.add_questions(room["code"], user["id"], generees, lang=get_lang())
        if ok:
            _flash(True, tm(message))
            st.rerun()
        else:
            st.error(tm(message))


# --------------------------------------------------------------------------- #
# Jouer : solo ou rejoindre une room
# --------------------------------------------------------------------------- #
def _page_play(user: dict) -> None:
    st.title(t("play_title"))
    col1, col2 = st.columns(2, gap="large")

    with col1:
        st.subheader(t("solo_h"))
        st.write(t("solo_desc"))
        st.button(t("btn_solo"), key="btn_solo", use_container_width=True,
                  on_click=_goto, args=("game",), kwargs={"room_code": None, "solo": None})

    with col2:
        st.subheader(t("join_h"))
        with st.form("form_join_room"):
            code = st.text_input(t("code_label"), placeholder=t("code_ph"), max_chars=rooms.CODE_LENGTH)
            envoye = st.form_submit_button(t("join_btn"))
        if envoye:
            if not code.strip():
                st.error(t("enter_code"))
            else:
                ok, message = rooms.join_room(code, user["id"], user["username"])
                if ok:
                    st.session_state["room_code"] = code.strip().upper()
                    _flash(True, tm(message))
                    _goto("lobby")
                    st.rerun()
                else:
                    st.error(tm(message))

    st.divider()
    st.subheader(t("rooms_h"))
    _rooms_list(user)

    st.button(t("back"), key="back_play", on_click=_goto, args=("home",))


@st.fragment(run_every=5)
def _rooms_list(user: dict) -> None:
    """Liste des rooms PUBLIQUES prêtes (se met à jour toute seule toutes les 5 secondes)."""
    ouvertes = rooms.list_open_rooms()
    if not ouvertes:
        st.info(t("no_rooms"))
        return

    ma_room = rooms.active_room_of(user["id"])
    for r in ouvertes:
        with st.container(border=True):
            c1, c2, c3 = st.columns([4, 2, 2])
            c1.markdown(f"**{r['name']}**  \n" + t("room_card_host", host=r["host_name"], code=r["code"]))
            c2.write(t("room_card_info", n=r["nb_players"], max=r["max_players"], q=r["nb_questions"]))
            if r["code"] == ma_room:
                etat, deja = "enter", True
            elif r["nb_players"] >= r["max_players"]:
                etat, deja = "full", False
            else:
                etat, deja = "join", False
            if c3.button(t("btn_" + etat), key=f"join_{r['code']}", disabled=etat == "full",
                         use_container_width=True):
                if deja:
                    ok, message = True, ""
                else:
                    ok, message = rooms.join_room(r["code"], user["id"], user["username"])
                if ok:
                    st.session_state["room_code"] = r["code"]
                    if message:
                        _flash(True, tm(message))
                    _goto("lobby")
                    st.rerun()
                else:
                    st.error(tm(message))


# --------------------------------------------------------------------------- #
# QR code et lien direct pour rejoindre une room
# --------------------------------------------------------------------------- #
def _app_url() -> str:
    """Adresse du site, sans « ? » : variable d'environnement APP_URL, sinon l'adresse du navigateur de l'hôte,
    sinon celle qu'il a saisie. (Pour que le QR code marche sur les téléphones, ce ne doit pas être localhost :
    mets l'adresse réseau de l'ordinateur, ex. http://192.168.1.20:8501, ou l'adresse publique du site.)"""
    url = st.session_state.get("app_url") or os.getenv("APP_URL", "").strip()
    if not url:
        try:
            url = str(st.context.url or "")
        except Exception:                            # ancienne version de Streamlit
            url = ""
    if not url.startswith(("http://", "https://")):
        return ""
    return url.split("?")[0].rstrip("/")


@st.cache_data(show_spinner=False)
def _qr_png(texte: str) -> bytes | None:
    try:
        import segno
    except ImportError:
        return None
    tampon = io.BytesIO()
    segno.make(texte, error="m").save(tampon, kind="png", scale=8, border=2)
    return tampon.getvalue()


def _qr_block(code: str) -> None:
    """QR code de la room : le joueur le scanne et arrive directement dans la room (après connexion)."""
    with st.expander(t("qr_title"), expanded=False):
        url = _app_url()
        nouvelle = st.text_input(t("qr_url_label"), value=url, key=f"qr_url_{code}",
                                 help=t("qr_url_help"))
        if nouvelle.strip() and nouvelle.strip().rstrip("/") != url:
            st.session_state["app_url"] = nouvelle.strip().rstrip("/")
            url = st.session_state["app_url"]
        if not url:
            st.info(t("qr_need_url"))
            return
        if any(h in url for h in ("localhost", "127.0.0.1")):
            st.warning(t("qr_localhost"))
        lien = f"{url}/?room={code}"
        png = _qr_png(lien)
        if png is None:
            st.error(t("qr_missing"))
        else:
            st.image(png, width=240)
        st.caption(t("qr_help"))
        st.code(lien, language=None)


def handle_join_link(user: dict) -> None:
    """À appeler dans main.py après la connexion : si le joueur est arrivé par un lien / QR code « ?room=CODE »,
    il rejoint directement la room (salle d'attente, ou partie en cours s'il y était déjà)."""
    code = st.session_state.pop("pending_room", None)
    if not code:
        return
    try:
        st.query_params.clear()
    except Exception:
        pass
    _setup()
    ok, message = rooms.join_room(code, user["id"], user["username"])
    if ok:
        room = rooms.get_room(code)
        st.session_state["room_code"] = room["code"]
        st.session_state["dash_page"] = "game" if room["status"] == rooms.PLAYING else "lobby"
        st.session_state["nav_page"] = "dashboard"
    _flash(ok, tm(message))


# --------------------------------------------------------------------------- #
# Salle d'attente (se met à jour toute seule toutes les 3 secondes)
# --------------------------------------------------------------------------- #
def _page_lobby(user: dict) -> None:
    code = st.session_state.get("room_code")
    if not code:
        _goto("home")
        st.rerun()
    _lobby_live(user, code)


@st.fragment(run_every=3)
def _lobby_live(user: dict, code: str) -> None:
    room = rooms.get_room(code)

    # la room n'existe plus ou a été fermée par l'hôte
    if room is None or room["status"] == rooms.CLOSED or not any(
        p["user_id"] == user["id"] for p in room["players"]
    ):
        _flash(False, t("lobby_unavailable"))
        st.session_state["room_code"] = None
        _goto("home")
        st.rerun()

    # la partie vient d'être lancée par l'hôte
    if room["status"] in (rooms.PLAYING, rooms.FINISHED):
        _goto("game")
        st.rerun()

    est_hote = room["host_id"] == user["id"]
    nb_prets = rooms.count_questions(room["id"])
    pret = nb_prets >= room["nb_questions"]
    if pret:                                         # prépare les questions dans la langue de ce joueur (traduction)
        room_i18n.localize_questions(room["id"], get_lang())

    st.title(room["name"])
    st.caption(t("lobby_info", host=room["host_name"], q=room["nb_questions"], vis=_visibilite(room)))
    st.caption(t("lobby_time", s=room["time_per_question"]) if room["time_per_question"] else t("lobby_no_time"))
    st.markdown(f'<div class="room-code">{room["code"]}</div>', unsafe_allow_html=True)
    st.caption(t("share_code"))
    _qr_block(room["code"])

    st.subheader(t("players_h", n=len(room["players"]), max=room["max_players"]))
    avatars = get_avatars([p["username"] for p in room["players"]])
    for p in room["players"]:
        etiquette = " 👑" if p["user_id"] == room["host_id"] else ""
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:.7rem;margin:.35rem 0">'
            f'{avatar_html(avatars.get(p["username"]), p["username"], 40)}'
            f'<b>{html.escape(p["username"])}</b>{etiquette}</div>',
            unsafe_allow_html=True,
        )

    if est_hote:
        if pret:
            st.caption(t("q_ready", n=nb_prets, total=room["nb_questions"]))
        else:
            st.warning(t("q_missing", n=nb_prets, total=room["nb_questions"]))
        if st.button(t("edit_q"), key="btn_edit_q"):
            st.session_state["q_mode"] = None
            _goto("questions")
            st.rerun()

    if est_hote:
        col1, col_back, col2 = st.columns(3)
    else:
        col1, col2 = st.columns(2)
        col_back = None
    with col1:
        if est_hote:
            if st.button(t("start"), key="btn_start", use_container_width=True, disabled=not pret):
                ok, message = rooms.start_room(code, user["id"])
                if ok:
                    _goto("game")
                    st.rerun()
                else:
                    st.error(tm(message))
        else:
            st.info(t("wait_host"))
    if col_back is not None:
        with col_back:
            # Revient à l'accueil SANS fermer la room : elle reste ouverte (et visible dans « Jouer » si elle est publique)
            if st.button(t("back"), key="btn_lobby_back", use_container_width=True):
                _goto("home")
                st.rerun()
    with col2:
        libelle = t("close_room") if est_hote else t("leave_room")
        if st.button(libelle, key="btn_leave", use_container_width=True):
            ok, message = rooms.leave_room(code, user["id"])
            _flash(ok, tm(message))
            st.session_state["room_code"] = None
            _goto("home")
            st.rerun()
    if est_hote:
        st.caption(t("lobby_keep_public") if room["is_public"] else t("lobby_keep_private"))


# --------------------------------------------------------------------------- #
# La partie
# --------------------------------------------------------------------------- #
def _page_game(user: dict, jeu) -> None:
    code = st.session_state.get("room_code")
    room = rooms.get_room(code) if code else None

    if code and (room is None or room["status"] not in (rooms.PLAYING, rooms.FINISHED)):
        _flash(False, t("game_unavailable"))
        st.session_state["room_code"] = None
        _goto("home")
        st.rerun()

    st.title(t("game_title", name=room["name"]) if room else t("game_solo"))
    if room:
        st.caption(t("game_players", players=", ".join(p["username"] for p in room["players"])))
        room["questions"] = rooms.list_questions(room["id"])     # les questions de la room

    if jeu is not None:
        jeu(user, room)                    # TON jeu de culture générale
    else:
        st.info(t("game_placeholder"))

    if room:
        st.caption(t("g_saved_hint"))
    if st.button(t("quit_game"), key="btn_quit_game"):
        st.session_state["solo"] = None
        if room:
            if room["status"] == rooms.PLAYING:
                rooms.mark_left(code, user["id"])         # la partie se met en pause pour les autres joueurs
                st.session_state[f"left_{room['id']}"] = True
            rooms.leave_room(code, user["id"])
        st.session_state["room_code"] = None
        _goto("home")
        st.rerun()


# --------------------------------------------------------------------------- #
# Room enregistrée : retrouvée à la connexion + historique « Mes rooms »
# --------------------------------------------------------------------------- #
def restore_room(user: dict) -> None:
    """À appeler une fois l'utilisateur connecté (dans main.py).
    À chaque connexion (ou rechargement de la page), on le ramène dans sa room en attente ou en cours,
    avec sa progression : tout est enregistré dans la base."""
    _setup()
    if st.session_state.get("restored_for") == user["id"]:
        return
    st.session_state["restored_for"] = user["id"]

    code = rooms.active_room_of(user["id"])
    if not code:
        return
    room = rooms.get_room(code)
    st.session_state["room_code"] = code
    st.session_state["dash_page"] = "game" if room["status"] == rooms.PLAYING else "lobby"
    st.session_state["nav_page"] = "dashboard"
    _flash(True, t("restored_room", name=room["name"]))


def _open_room(code: str, page: str) -> None:
    st.session_state["room_code"] = code
    st.session_state["dash_page"] = page


def _fmt(x: float) -> str:
    return f"{x + 1e-9:.1f}".removesuffix(".0")


def _page_history(user: dict) -> None:
    st.title(t("history_title"))
    historique = rooms.list_user_rooms(user["id"])
    if not historique:
        st.info(t("history_empty"))

    for r in historique:
        with st.container(border=True):
            c1, c2, c3 = st.columns([4, 4, 2])
            hote = " 👑" if r["host_id"] == user["id"] else ""
            c1.markdown(t("history_card", name=r["name"] + hote, code=r["code"],
                          date=r["created_at"][:16]))
            ligne = t("history_info", players=r["nb_players"], q=r["nb_questions"])
            ligne += "  \n" + t("status_" + r["status"])
            if r["answered"]:
                ligne += "  \n" + t("history_score", score=_fmt(r["score"]), total=r["nb_questions"])
            c2.write(ligne)

            if r["status"] in (rooms.WAITING, rooms.PLAYING):
                page = "game" if r["status"] == rooms.PLAYING else "lobby"
                c3.button(t("history_open"), key=f"hist_{r['code']}", use_container_width=True,
                          on_click=_open_room, args=(r["code"], page))
            elif r["status"] == rooms.FINISHED:
                c3.button(t("history_results"), key=f"hist_{r['code']}", use_container_width=True,
                          on_click=_open_room, args=(r["code"], "game"))

    st.button(t("back"), key="back_history", on_click=_goto, args=("home",))