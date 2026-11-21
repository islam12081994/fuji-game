"""
user/game.py
Le jeu de culture générale.

    play(user, room)
        room = {...}  -> partie en room SYNCHRONISÉE : tout le monde voit la même question en même temps.
                         Le temps par question est choisi par l'hôte à la création de la room. Quand le temps est
                         écoulé, on voit les résultats et les scores de chaque joueur ; l'hôte peut les modifier,
                         puis il clique sur « Question suivante » (rien ne passe tout seul). Si un joueur sort,
                         la partie est mise en pause jusqu'à son retour.
        room = None   -> partie en solo : l'IA prépare les questions (thème, difficulté, nombre, type de
                         questions : QCM / réponse libre / les deux, et temps par question)

Deux types de questions :
  - QCM (4 propositions)            : 100 % si bonne réponse, sinon 0 %
  - Réponse libre (zone de texte)   : correction automatique (user/grading.py) :
                                      faute d'orthographe -> pourcentage réduit ; date à +-1 an -> pourcentage réduit
                                      Vrai si le pourcentage est STRICTEMENT supérieur à 50 %.

Points : le pourcentage / 100 (par exemple 85 % = 0,85 point). Score final = somme des points.
"""
import html
import math
import time

import streamlit as st

from i18n import LANGUES, get_lang, ia_language, t, tm
from user import grading, room_i18n, rooms
from user import questions_ai

LETTRES = "ABCD"

# --- Correction automatique : réglages ---------------------------------------------------------
SEUIL_VRAI = rooms.SEUIL_VRAI        # 50 : réponse VRAIE si le pourcentage est STRICTEMENT supérieur à 50 %
COULEUR_ROUGE = "#ff5a5f"            # pourcentage <= 50 (faux)
COULEUR_ORANGE = "#ffb020"           # de 51 % à 99 % (vrai, mais pas parfait : faute, année décalée...)
COULEUR_VERT = "#34c759"             # 100 %
MONTRER_LA_BONNE_REPONSE = True      # False : la correction n'affiche que le pourcentage (jamais la réponse attendue)


def play(user: dict, room: dict | None = None) -> None:
    if room:
        _play_room(user, room)
    else:
        _play_solo(user)


# --------------------------------------------------------------------------- #
# Outils
# --------------------------------------------------------------------------- #
def _fmt(x: float) -> str:
    """6.0 -> '6', 6.5 -> '6.5', 6.25 -> '6.3'."""
    return f"{x + 1e-9:.1f}".removesuffix(".0")


def _points(questions: list, answers: dict) -> float:
    ids = {q["id"] for q in questions}
    return sum(a["score"] for qid, a in answers.items() if qid in ids) / 100


def _couleur(pct: int) -> str:
    """Rouge si <= 50 % (faux), orange de 51 à 99 %, vert à 100 %."""
    if pct <= SEUIL_VRAI:
        return COULEUR_ROUGE
    return COULEUR_VERT if pct >= 100 else COULEUR_ORANGE


def _verdict(pct: int) -> str:
    """Vrai si le pourcentage est strictement supérieur à 50 %, sinon faux."""
    return t("g_verdict_true") if pct > SEUIL_VRAI else t("g_verdict_false")


def _badge(pct: int) -> None:
    """Pourcentage de correction en grand, dans sa couleur, avec le verdict (vrai / faux) et une barre."""
    pct = max(0, min(100, int(pct)))
    c = _couleur(pct)
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:1rem;margin:.2rem 0 .5rem">'
        f'<span style="font-size:2.6rem;font-weight:800;line-height:1;color:{c}">{pct} %</span>'
        f'<span style="padding:.2rem .9rem;border:2px solid {c};border-radius:999px;color:{c};'
        f'font-weight:800;font-size:1.05rem">{html.escape(_verdict(pct))}</span></div>'
        f'<div style="height:10px;border-radius:6px;background:rgba(255,255,255,.14);overflow:hidden;'
        f'margin-bottom:.8rem"><div style="width:{pct}%;height:100%;background:{c}"></div></div>',
        unsafe_allow_html=True,
    )


def _recap(questions: list, answers: dict) -> None:
    """Correction automatique de toutes les questions, affichée à la fin de la partie."""
    lignes = []
    for i, q in enumerate(questions, start=1):
        rec = answers.get(q["id"])
        if rec is None:
            continue
        pct = max(0, min(100, int(round(rec["score"]))))
        c = _couleur(pct)
        court = q["question"] if len(q["question"]) <= 70 else q["question"][:67] + "..."
        lignes.append(
            f'<div style="display:flex;justify-content:space-between;align-items:center;gap:1rem;'
            f'padding:.5rem 0;border-bottom:1px solid rgba(240,207,138,.2)">'
            f'<span>{i}. {html.escape(court)}</span>'
            f'<span style="color:{c};font-weight:800;white-space:nowrap">{pct} %  -  {html.escape(_verdict(pct))}</span></div>'
        )
    if lignes:
        st.subheader(t("g_recap"))
        st.markdown("".join(lignes), unsafe_allow_html=True)


def _clear(cle: str) -> None:
    st.session_state[cle] = None


def _resultat_final(points: float, total: int) -> None:
    pourcent = round(points / total * 100) if total else 0
    st.success(t("g_finished"))
    st.subheader(t("g_your_score", score=_fmt(points), total=total, percent=pourcent))


# --------------------------------------------------------------------------- #
# Correction d'une question (solo)
# --------------------------------------------------------------------------- #
def _feedback(q: dict, rec: dict, n: int, total: int) -> None:
    """Correction de la question qui vient d'être terminée (pourcentage + vrai / faux)."""
    st.progress(n / total, text=t("g_question_n", n=n, total=total))
    st.subheader(q["question"])
    _badge(round(rec["score"]))
    manque = rec["choice"] < 0 and not rec["text"]
    if manque:
        st.write(t("g_missed"))

    if q.get("kind") == "open":
        if not manque:
            st.write(t("g_your_answer", answer=rec["text"]))
        if MONTRER_LA_BONNE_REPONSE:
            st.info(t("q_expected", answer=q["reference"]))
            if rec["comment"]:
                st.write(t("g_ai_comment", comment=rec["comment"]))
        return

    for j, texte in enumerate(q["choices"]):
        if MONTRER_LA_BONNE_REPONSE:
            marque = "✅" if j == q["answer"] else ("❌" if j == rec["choice"] else "▫️")
        else:
            marque = "🔘" if j == rec["choice"] else "▫️"
        st.write(f"{marque} {LETTRES[j]}. {texte}")


# --------------------------------------------------------------------------- #
# Partie en room (synchronisée : même question, au même moment, pour tous les joueurs)
# --------------------------------------------------------------------------- #
def _etat(room: dict) -> tuple:
    """Ce qui oblige tous les joueurs à recharger la page quand ça change."""
    return (room["status"], room["current_q"], room["phase"], room["paused_at"] is not None,
            rooms.countdown_left(room) > 0)


def _questions_du_joueur(room_id: int) -> list:
    """Les questions de la room dans la langue choisie par CE joueur (traduites par l'IA, une seule fois par
    langue, puis enregistrées). Deux joueurs de la même room peuvent donc jouer en arabe et en français."""
    lang = get_lang()
    questions = room_i18n.localize_questions(room_id, lang, allow_ai=False)
    if room_i18n.is_translation_missing(questions, lang):
        with st.spinner(t("g_translating")):
            questions = room_i18n.localize_questions(room_id, lang)
    return questions


def _play_room(user: dict, room: dict) -> None:
    rooms.heartbeat(room["code"], user["id"])               # « je suis là » (sinon la partie se met en pause)
    questions = _questions_du_joueur(room["id"])
    if not questions:
        st.warning(t("g_no_questions"))
        return
    if room_i18n.is_translation_missing(questions, get_lang()):
        st.caption(t("g_translate_fail"))
    elif any(q["translated"] for q in questions):
        st.caption(t("g_translated", lang=LANGUES[get_lang()]))
    room = rooms.sync_room(room["code"]) or room
    est_hote = room["host_id"] == user["id"]
    wm = room["wager_mode"]
    if st.session_state.pop(f"left_{room['id']}", False):
        st.toast(t("g_welcome_back"))

    # partie terminée : résultats, classement détaillé (et correction de l'hôte)
    if room["status"] == rooms.FINISHED:
        _final_live(room["id"], user["id"], wm)
        st.divider()
        _classement(room["id"], len(questions), user["id"], True, wm)
        if est_hote:
            st.divider()
            _host_panel(room["code"], room["id"], host_id=user["id"], questions=questions, wm=wm)
        return

    # compte à rebours de lancement : « La partie commence dans... »
    if rooms.countdown_left(room) > 0:
        st.markdown(f'<h2 style="text-align:center;margin-top:2rem">{html.escape(t("g_starting_in"))}</h2>',
                    unsafe_allow_html=True)
        _countdown(room["code"], user["id"], _etat(room))
        return

    total = len(questions)
    idx = min(room["current_q"], total - 1)
    q = questions[idx]
    final = wm and idx == total - 1                          # question finale du mode paris
    answers = rooms.get_answers(room["id"], user["id"])
    rec = answers.get(q["id"])
    en_pause = room["paused_at"] is not None
    absents = [p["username"] for p in rooms.absent_players(room)]

    # un joueur vient de revenir : on prévient les autres
    cle_pause = f"paused_names_{room['id']}"
    if en_pause:
        st.session_state[cle_pause] = absents
    elif st.session_state.get(cle_pause):
        st.toast(t("g_resumed", names=", ".join(st.session_state.pop(cle_pause))))

    points = rooms.player_points(room["id"], user["id"])
    st.caption(t("g_points", points=_fmt(points)) if wm else
               t("g_score", score=_fmt(_points(questions, answers)), total=total))
    _timer(room["code"], user["id"], _etat(room), room["time_per_question"])
    st.progress(idx / total, text=t("g_question_n", n=idx + 1, total=total))

    if en_pause:                                             # un joueur est sorti : tout s'arrête
        st.warning(t("g_paused", names=", ".join(absents)))
        if est_hote:
            st.button(t("g_skip_absent"), key=f"btn_skip_{room['id']}", on_click=_host_skip,
                      args=(room["code"], user["id"]))
        st.divider()
        _classement(room["id"], total, user["id"], False, wm)
        return

    if room["phase"] == rooms.REVIEW:
        _review(room["code"], room["id"], q, idx, room["host_id"], user["id"], total, wm)
    else:
        _prev_result(questions, answers, idx, wm)
        cle_mise = f"wager_{room['id']}_{q['id']}"
        mise = st.session_state.get(cle_mise) if (wm and rec is None) else None
        if rec is None and final and mise is None:
            _mise_finale(room, user["id"], idx, points, cle_mise)     # la question reste cachée jusqu'à la mise
        else:
            st.subheader(q["question"])
            if rec is not None:
                st.success(t("g_answered_wait"))
                if wm and rec["wager"] is not None:
                    st.write(t("g_your_wager", w=rec["wager"]))
                if q["kind"] == "open":
                    st.write(t("g_your_answer", answer=rec["text"]))
                elif rec["choice"] >= 0:
                    st.write(t("g_your_answer", answer=f"{LETTRES[rec['choice']]}. {q['choices'][rec['choice']]}"))
            else:
                if wm and not final:
                    _grille_mises(room, user["id"], idx, cle_mise, mise)
                elif final:
                    st.info(t("g_final_bet", w=mise))
                bloque = wm and mise is None                  # il faut d'abord choisir sa mise
                if q["kind"] == "open":
                    st.caption(t("g_open_free"))
                    with st.form(f"form_open_{room['id']}_{q['id']}"):
                        texte = st.text_area(t("g_open_label"), max_chars=300, height=100,
                                             key=f"open_{room['id']}_{q['id']}", disabled=bloque)
                        envoye = st.form_submit_button(t("g_open_submit"), type="primary", disabled=bloque)
                    if envoye and _repondre_room(user, room, q, texte, mise):
                        st.rerun()
                else:
                    st.caption(t("g_choose"))
                    for j, texte in enumerate(q["choices"]):
                        if st.button(f"{LETTRES[j]}.  {texte}", key=f"ans_{room['id']}_{q['id']}_{j}",
                                     use_container_width=True, disabled=bloque):
                            if _repondre_room(user, room, q, j, mise):
                                st.rerun()

    if not est_hote and room["phase"] == rooms.ANSWERING and not rooms.has_timer(room):
        _host_answered(room["id"], room["current_q"])        # sans temps : tout le monde voit qui a répondu
    if est_hote:
        st.divider()
        if room["phase"] == rooms.ANSWERING:
            _host_answered(room["id"], room["current_q"])
            libelle = t("g_host_close")
        else:
            libelle = t("g_next") if idx + 1 < total else t("g_host_end")
        st.button(libelle, key=f"btn_host_next_{room['id']}_{idx}_{room['phase']}", type="primary",
                  on_click=_host_next, args=(room["code"], user["id"]))
        st.caption(t("g_host_hint"))
    elif room["phase"] == rooms.REVIEW:
        st.info(t("g_wait_host_next"))

    st.divider()
    _classement(room["id"], total, user["id"], False, wm)


# --------------------------------------------------------------------------- #
# Mode paris : choix de la mise
# --------------------------------------------------------------------------- #
def _choisir_mise(cle: str, valeur: int) -> None:
    st.session_state[cle] = valeur


def _grille_mises(room: dict, user_id: int, idx: int, cle: str, choisie) -> None:
    """Grille des mises 1..N-1 : une mise déjà utilisée dans la partie est désactivée (elle ne sert qu'une fois)."""
    st.markdown(f"**{t('g_wager_h')}**")
    st.caption(t("g_wager_help"))
    options = rooms.wager_options(room, user_id, idx)
    utilisees = rooms.used_wagers(room["id"], user_id)
    for debut in range(0, len(options), 5):
        colonnes = st.columns(5)
        for col, v in zip(colonnes, options[debut:debut + 5]):
            col.button(str(v), key=f"wg_{room['id']}_{idx}_{v}", disabled=v in utilisees,
                       type="primary" if choisie == v else "secondary", use_container_width=True,
                       on_click=_choisir_mise, args=(cle, v))
    if choisie is None:
        st.info(t("g_choose_wager"))


def _mise_finale(room: dict, user_id: int, idx: int, points: float, cle: str) -> None:
    """Question finale : on mise AVANT de voir la question. Si la réponse est fausse, la mise est PERDUE."""
    st.subheader(t("g_final_title"))
    st.caption(t("g_final_help"))
    st.markdown(f"**{t('g_current_score', s=_fmt(points))}**")
    colonnes = st.columns(3)
    for col, v in zip(colonnes, rooms.wager_options(room, user_id, idx)):
        col.button(str(v), key=f"wgf_{room['id']}_{idx}_{v}", use_container_width=True,
                   on_click=_choisir_mise, args=(cle, v))


@st.fragment(run_every=1)
def _countdown(code: str, user_id: int, etat: tuple) -> None:
    """Grand compte à rebours de lancement ; recharge la page quand la première question démarre."""
    rooms.heartbeat(code, user_id)
    room = rooms.sync_room(code)
    if room is None or _etat(room) != etat:
        st.rerun()
    restant = max(1, math.ceil(rooms.countdown_left(room)))
    st.markdown(f'<div style="text-align:center;font-size:7rem;font-weight:800;line-height:1.1;'
                f'color:#F0CF8A">{restant}</div>', unsafe_allow_html=True)


def _repondre_room(user: dict, room: dict, q: dict, valeur, mise=None) -> bool:
    """Enregistre la réponse du joueur. Le clic est horodaté AVANT la correction : si la correction par l'IA
    prend quelques secondes, une réponse envoyée à temps reste valable."""
    clic = time.time()
    if q["kind"] == "open":
        texte = (valeur or "").strip()
        if not texte:
            st.error(t("g_open_empty"))
            return False
        with st.spinner(t("g_open_grading")):
            pourcentage, commentaire = grading.grade(q["question"], q["reference"], texte, ia_language(),
                                                     autre_reference=q.get("orig_reference", ""))
        ok, message = rooms.submit_open_answer(room["code"], user["id"], q["id"], texte,
                                               pourcentage, commentaire, submitted_at=clic, wager=mise)
    else:
        ok, message, _ = rooms.submit_answer(room["code"], user["id"], q["id"], valeur, submitted_at=clic,
                                             wager=mise)
    if not ok:
        st.error(tm(message))
    return ok


def _host_next(code: str, user_id: int) -> None:
    """Bouton de l'hôte : terminer la question (résultats), puis question suivante / fin de la partie."""
    rooms.advance_question(code, user_id)


def _host_skip(code: str, user_id: int) -> None:
    rooms.skip_absent(code, user_id)


@st.fragment(run_every=1)
def _timer(code: str, user_id: int, etat: tuple, duree: int) -> None:
    """Minuteur : se met à jour toutes les secondes chez chaque joueur, envoie le signe de vie du joueur, et
    recharge la page de tous dès que la situation change (résultats, question suivante, pause, reprise)."""
    rooms.heartbeat(code, user_id)
    room = rooms.sync_room(code)
    if room is None or _etat(room) != etat:
        st.rerun()
    restant = rooms.seconds_left(room)
    if room["phase"] == rooms.REVIEW:
        st.progress(0.0, text=t("g_time_up_review") if rooms.has_timer(room) else t("g_review_notime"))
    elif not rooms.has_timer(room):
        st.caption(t("g_no_time"))
    elif room["paused_at"]:
        st.progress(min(restant / max(duree, 1), 1.0), text=t("g_time_paused", s=math.ceil(restant)))
    elif restant > 0:
        st.progress(min(restant / max(duree, 1), 1.0), text=t("g_time_left", s=math.ceil(restant)))
    else:
        st.progress(0.0, text=t("g_time_up"))


@st.fragment(run_every=2)
def _host_answered(room_id: int, current_q: int) -> None:
    n, total = rooms.current_question_stats(room_id, current_q)
    st.caption(t("g_answered_count", n=n, total=total))


def _prev_result(questions: list, answers: dict, idx: int, wm: bool = False) -> None:
    """Rappel de ton résultat à la question précédente, au-dessus de la question en cours."""
    if idx == 0:
        return
    qp = questions[idx - 1]
    rec = answers.get(qp["id"])
    with st.container(border=True):
        st.caption(t("g_prev_title", n=idx))
        if rec is None or (rec["choice"] < 0 and not rec["text"]):
            st.write(t("g_missed"))
        else:
            pct = max(0, min(100, int(round(rec["score"]))))
            gain = ""
            if wm:
                pts = rooms.answer_points(True, idx - 1 == len(questions) - 1, rec["wager"], rec["score"])
                gain = f"  ({pts:+.1f} pts)".replace(".0 pts", " pts")
            st.markdown(f'<span style="color:{_couleur(pct)};font-weight:800;font-size:1.3rem">{pct} %  -  '
                        f'{html.escape(_verdict(pct))}{html.escape(gain)}</span>', unsafe_allow_html=True)


def _attendue(q: dict) -> str:
    return q["reference"] if q["kind"] == "open" else f"{LETTRES[q['answer']]}. {q['choices'][q['answer']]}"


# --------------------------------------------------------------------------- #
# Résultats d'une question (temps écoulé) + correction par l'hôte
# --------------------------------------------------------------------------- #
def _decider(code: str, host_id: int, question_id: int, user_id: int, pourcentage) -> None:
    rooms.set_score(code, host_id, question_id, user_id, pourcentage)


def _ligne_resultat(a: dict, q: dict, code: str, room_id: int, host_id: int, user_id: int, prefixe: str,
                    wm: bool = False, finale: bool = False) -> None:
    """Une ligne : joueur, sa réponse, son pourcentage (et sa mise / ses points) ; l'hôte a en plus les boutons
    de correction."""
    pct = int(round(a["score"]))
    c = _couleur(pct)
    moi = f" {t('g_you')}" if a["user_id"] == user_id else ""
    if not a["answered"]:
        detail = t("g_review_noanswer")
    else:
        if q["kind"] == "open":
            reponse = a["text"]
        else:
            reponse = f"{LETTRES[a['choice']]}. {q['choices'][a['choice']]}"
        origine = t("h_by_host") if a["verdict"] is not None else (a["comment"] or "")
        gain = ""
        if wm:
            pts = rooms.answer_points(True, finale, a["wager"], a["score"])
            gain = t("g_wager_gain", w=a["wager"] or 0, pts=f"{pts:+.1f}".replace(".0", ""))
        detail = (f'« {html.escape(reponse)} »  \n<span style="color:{c};font-weight:800">{pct} %  -  '
                  f'{html.escape(_verdict(pct))}</span> <span style="opacity:.7">{html.escape(origine)}</span>'
                  + (f'  \n<b>{html.escape(gain)}</b>' if gain else ""))
    peut_corriger = user_id == host_id and a["answered"]          # l'hôte corrige tout, y compris sa propre réponse
    if not a["answered"]:
        detail = f'<span style="color:{c};font-weight:800">{html.escape(detail)}</span>'
    if not peut_corriger:
        st.markdown(f'**{html.escape(a["username"])}**{html.escape(moi)} : {detail}', unsafe_allow_html=True)
        return
    col_txt, *cols = st.columns([5, 1.2, 1.2, 1.2, 1.2, 1.4])
    col_txt.markdown(f'**{html.escape(a["username"])}** : {detail}', unsafe_allow_html=True)
    cle = f"{prefixe}_{room_id}_{a['question_id']}_{a['user_id']}"
    args = (code, host_id, a["question_id"], a["user_id"])
    for col, (valeur, texte) in zip(cols[:4], ((100, "✅ 100"), (75, "75"), (25, "25"), (0, "❌ 0"))):
        col.button(texte, key=f"{prefixe}_{valeur}_{cle}", on_click=_decider, args=(*args, valeur),
                   type="primary" if pct == valeur and a["verdict"] is not None else "secondary",
                   help=f"{valeur} %")
    cols[4].button(t("h_auto"), key=f"{prefixe}_au_{cle}", on_click=_decider, args=(*args, None),
                   disabled=a["verdict"] is None)


@st.fragment(run_every=2)
def _review(code: str, room_id: int, q: dict, idx: int, host_id: int, user_id: int, total: int,
            wm: bool = False) -> None:
    """Résultats de la question qui vient de se terminer : réponse de chaque joueur et son pourcentage.
    L'hôte peut modifier chaque score ; le classement en dessous se met à jour tout de suite."""
    st.subheader(t("g_review_title", n=idx + 1))
    st.markdown(f"**{html.escape(q['question'])}**")
    st.info(t("q_expected", answer=_attendue(q)))
    if user_id == host_id:
        st.caption(t("g_host_review_hint"))
    for a in rooms.list_answers(room_id, q["id"]):
        with st.container(border=True):
            _ligne_resultat(a, q, code, room_id, host_id, user_id, "rv", wm, wm and idx == total - 1)


@st.fragment(run_every=3)
def _final_live(room_id: int, user_id: int, wm: bool = False) -> None:
    """Résultat final du joueur (se met à jour si l'hôte corrige une réponse après la partie)."""
    questions = room_i18n.localize_questions(room_id, get_lang(), allow_ai=False)
    answers = rooms.get_answers(room_id, user_id)
    if wm:
        st.success(t("g_finished"))
        st.subheader(t("g_your_points", points=_fmt(rooms.player_points(room_id, user_id))))
    else:
        _resultat_final(_points(questions, answers), len(questions))
    _recap(questions, answers)


@st.fragment(run_every=3)
def _host_panel(code: str, room_id: int, host_id: int, questions: list, wm: bool = False) -> None:
    """Fin de partie : l'hôte peut encore modifier le score de n'importe quelle réponse."""
    par_id = {q["id"]: (i, q) for i, q in enumerate(questions, start=1)}
    with st.expander(t("h_panel_title"), expanded=False):
        st.caption(t("h_panel_help"))
        derniere = None
        for a in rooms.list_answers(room_id):
            if a["question_id"] not in par_id:
                continue
            n, q = par_id[a["question_id"]]
            if a["question_id"] != derniere:
                derniere = a["question_id"]
                st.markdown(f"**{n}. {q['question']}**")
                st.caption(t("q_expected", answer=_attendue(q)))
            _ligne_resultat(a, q, code, room_id, host_id, host_id, "hp", wm, wm and n == len(questions))


@st.fragment(run_every=3)
def _classement(room_id: int, total: int, user_id: int, detail: bool, wm: bool = False) -> None:
    """Classement en direct (se met à jour tout seul toutes les 3 secondes).
    detail = True une fois la partie terminée : tableau des pourcentages de chaque joueur par question."""
    lignes = rooms.scoreboard(room_id)
    st.subheader(t("g_ranking"))
    medailles = ["🥇", "🥈", "🥉"]
    for i, ligne in enumerate(lignes):
        rang = medailles[i] if i < 3 else f"{i + 1}."
        etat = "🏁" if ligne["answered"] >= total else f"({ligne['answered']}/{total})"
        moi = f" {t('g_you')}" if ligne["user_id"] == user_id else ""
        valeur = t("g_pts", p=_fmt(ligne["score"])) if wm else f"{_fmt(ligne['score'])} / {total}"
        st.write(f"{rang} **{ligne['username']}**{moi} - {valeur}  {etat}")
    if detail and lignes:
        st.success(t("g_all_done"))
        par = {(m["question_id"], m["user_id"]): m["score"] for m in rooms.answers_matrix(room_id)}
        tableau = []
        for i, q in enumerate(room_i18n.localize_questions(room_id, get_lang(), allow_ai=False), start=1):
            court = q["question"] if len(q["question"]) <= 60 else q["question"][:57] + "..."
            ligne_q = {t("g_question_col"): f"{i}. {court}"}
            for l in lignes:
                v = par.get((q["id"], l["user_id"]))
                ligne_q[l["username"]] = "-" if v is None else f"{v:.0f} %"
            tableau.append(ligne_q)
        st.subheader(t("g_detail"))
        st.dataframe(tableau, use_container_width=True, hide_index=True)


# --------------------------------------------------------------------------- #
# Partie en solo (questions générées par l'IA : QCM, réponse libre ou les deux, avec ou sans temps)
# --------------------------------------------------------------------------- #
def _reset_solo() -> None:
    st.session_state["solo"] = None
    st.session_state["game_last_solo"] = None


def _blanc(answers: dict, q: dict) -> None:
    """Pas de réponse à temps : 0 %."""
    answers[q["id"]] = {"choice": -1, "text": "", "comment": "", "score": 0}


def _play_solo(user: dict) -> None:
    solo = st.session_state.get("solo")
    if not solo:
        _solo_setup()
        return

    questions, answers = solo["questions"], solo["answers"]
    limite = solo.get("time", 0)                             # secondes par question (0 = sans limite)
    cle = "game_last_solo"
    total = len(questions)
    dernier = st.session_state.get(cle)
    en_attente = next((q for q in questions if q["id"] not in answers), None)
    st.caption(t("g_score", score=_fmt(_points(questions, answers)), total=total))

    # 1) la question qu'on vient de terminer : correction + bouton « suivante » (rien ne passe tout seul)
    if dernier is not None and dernier in answers:
        q = next(q for q in questions if q["id"] == dernier)
        _feedback(q, answers[dernier], questions.index(q) + 1, total)
        st.button(t("g_next") if en_attente else t("g_see_results"), key="btn_game_next",
                  type="primary", on_click=_clear, args=(cle,))
        return

    # 2) plus de question : écran de fin
    if en_attente is None:
        _resultat_final(_points(questions, answers), total)
        st.button(t("g_solo_new"), key="btn_solo_new", type="primary", on_click=_reset_solo)
        _recap(questions, answers)
        return

    # 3) la question en cours, avec son temps
    q = en_attente
    n = questions.index(q) + 1
    debut = solo.setdefault("started", {}).setdefault(q["id"], time.time())
    if limite and time.time() >= debut + limite:             # temps écoulé : 0 %, on affiche la correction
        _blanc(answers, q)
        st.session_state[cle] = q["id"]
        st.rerun()

    if limite:
        _solo_timer(debut, limite)
    st.progress((n - 1) / total, text=t("g_question_n", n=n, total=total))
    st.subheader(q["question"])

    def enregistrer(valeur) -> None:
        clic = time.time()
        if limite and clic > debut + limite + 1.5:           # envoyé après la fin du temps
            _blanc(answers, q)
        elif q["kind"] == "open":
            with st.spinner(t("g_open_grading")):
                pct, com = grading.grade(q["question"], q["reference"], valeur, ia_language())
            answers[q["id"]] = {"choice": -1, "text": valeur, "comment": com, "score": pct}
        else:
            answers[q["id"]] = {"choice": valeur, "text": "", "comment": "",
                                "score": 100 if valeur == q["answer"] else 0}
        st.session_state[cle] = q["id"]
        st.rerun()

    if q["kind"] == "open":
        st.caption(t("g_open_free"))
        with st.form(f"form_open_solo_{q['id']}"):
            texte = st.text_area(t("g_open_label"), max_chars=300, height=100, key=f"open_solo_{q['id']}")
            envoye = st.form_submit_button(t("g_open_submit"), type="primary")
        if envoye:
            if texte.strip():
                enregistrer(texte.strip())
            else:
                st.error(t("g_open_empty"))
    else:
        st.caption(t("g_choose"))
        for j, texte in enumerate(q["choices"]):
            if st.button(f"{LETTRES[j]}.  {texte}", key=f"ans_solo_{q['id']}_{j}", use_container_width=True):
                enregistrer(j)


@st.fragment(run_every=1)
def _solo_timer(debut: float, limite: int) -> None:
    restant = debut + limite - time.time()
    if restant <= 0:
        st.rerun()                                           # temps écoulé : la partie principale enregistre 0 %
    st.progress(min(restant / limite, 1.0), text=t("g_time_left", s=math.ceil(restant)))


def _solo_setup() -> None:
    st.subheader(t("g_solo_title"))
    with st.form("form_solo"):
        theme = st.text_input(t("theme"), value=t("default_theme"), max_chars=60)
        niveau = st.selectbox(t("difficulty"), questions_ai.DIFFICULTES, index=1,
                              format_func=lambda d: t("diff_" + d))
        types = st.radio(t("qtype_label"), questions_ai.TYPES, index=2, horizontal=True,
                         format_func=lambda k: t("qtype_" + k))
        nb = st.slider(t("g_solo_count"), rooms.MIN_QUESTIONS, 15, 10)
        sans_limite = st.checkbox(t("solo_no_limit"), value=False)
        temps = st.slider(t("solo_time"), rooms.MIN_TIME, rooms.MAX_TIME, rooms.DEFAULT_TIME, step=5)
        envoye = st.form_submit_button(t("g_solo_start"))

    if envoye:
        try:
            with st.spinner(t("g_solo_generating")):
                generees = questions_ai.generate_mixed(theme, nb, niveau, types, langue=ia_language())
        except Exception as e:                       # clé manquante, réseau, réponse invalide...
            st.error(t("ai_error", error=e))
            return
        st.session_state["solo"] = {
            "questions": [{"id": i, **q} for i, q in enumerate(generees)],
            "answers": {},
            "time": 0 if sans_limite else temps,
            "started": {},
        }
        st.session_state["game_last_solo"] = None
        st.rerun()
