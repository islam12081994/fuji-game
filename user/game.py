"""
user/game.py
Le jeu de culture générale.

    play(user, room)
        room = {...}  -> partie en room : les questions de l'hôte, chaque joueur répond à son rythme,
                         le classement se met à jour en direct
        room = None   -> partie en solo : l'IA prépare des QCM (thème, difficulté, nombre)

Deux types de questions :
  - QCM (4 propositions)            : 100 % si bonne réponse, sinon 0 %
  - Réponse libre (zone de texte)   : le modèle Groq compare la réponse du joueur à la réponse attendue
                                      et donne un POURCENTAGE de bonne réponse (0 à 100 %)

Points : le pourcentage / 100 (par exemple 85 % = 0,85 point). Score final = somme des points.
"""
import html

import streamlit as st

from i18n import ia_language, t, tm
from user import questions_ai, rooms

LETTRES = "ABCD"

# --- Correction automatique : réglages ---------------------------------------------------------
SEUIL_VRAI = 50                      # >= 50 % : réponse VRAIE ; < 50 % : réponse FAUSSE
COULEUR_ROUGE = "#ff5a5f"            # pourcentage < 50
COULEUR_ORANGE = "#ffb020"           # pourcentage = 50
COULEUR_VERT = "#34c759"             # pourcentage > 50
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
    """Rouge si < 50 %, orange si = 50 %, vert si > 50 %."""
    if pct < SEUIL_VRAI:
        return COULEUR_ROUGE
    return COULEUR_ORANGE if pct == SEUIL_VRAI else COULEUR_VERT


def _verdict(pct: int) -> str:
    """Vrai si >= 50 %, sinon faux."""
    return t("g_verdict_true") if pct >= SEUIL_VRAI else t("g_verdict_false")


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
# Moteur commun (room et solo)
# --------------------------------------------------------------------------- #
def _feedback(q: dict, rec: dict, n: int, total: int) -> None:
    """Correction automatique de la question qui vient d'être répondue (pourcentage + vrai / faux)."""
    st.progress(n / total, text=t("g_question_n", n=n, total=total))
    st.subheader(q["question"])
    _badge(round(rec["score"]))

    if q.get("kind") == "open":
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


def _jouer(questions: list, answers: dict, cle: str, repondre, ecran_final) -> None:
    """questions = [{"id", "question", "kind", ...}] ; answers = {id_question: {"choice","text","score","comment"}}.
    repondre(question, valeur) enregistre la réponse (valeur = index du QCM ou texte) et retourne True si c'est fait.
    ecran_final(points, total) dessine l'écran de fin."""
    total = len(questions)
    points = _points(questions, answers)
    dernier = st.session_state.get(cle)
    en_attente = next((q for q in questions if q["id"] not in answers), None)

    st.caption(t("g_score", score=_fmt(points), total=total))

    # 1) la question qu'on vient de répondre : correction + bouton « suivante »
    if dernier is not None and dernier in answers:
        q = next(q for q in questions if q["id"] == dernier)
        _feedback(q, answers[dernier], questions.index(q) + 1, total)
        st.button(t("g_next") if en_attente else t("g_see_results"), key="btn_game_next",
                  type="primary", on_click=_clear, args=(cle,))
        return

    # 2) plus de question : écran de fin
    if en_attente is None:
        ecran_final(points, total)
        _recap(questions, answers)
        return

    # 3) la question en cours
    q = en_attente
    n = questions.index(q) + 1
    st.progress((n - 1) / total, text=t("g_question_n", n=n, total=total))
    st.subheader(q["question"])

    if q.get("kind") == "open":
        # zone libre : pas de proposition, le joueur écrit sa réponse
        st.caption(t("g_open_free"))
        with st.form(f"form_open_{cle}_{q['id']}"):
            texte = st.text_area(t("g_open_label"), max_chars=300, height=100,
                                 key=f"open_{cle}_{q['id']}")
            envoye = st.form_submit_button(t("g_open_submit"), type="primary")
        if envoye and repondre(q, texte):
            st.session_state[cle] = q["id"]
            st.rerun()
        return

    st.caption(t("g_choose"))
    for j, texte in enumerate(q["choices"]):
        if st.button(f"{LETTRES[j]}.  {texte}", key=f"ans_{q['id']}_{j}", use_container_width=True):
            if repondre(q, j):
                st.session_state[cle] = q["id"]
                st.rerun()


# --------------------------------------------------------------------------- #
# Partie en room
# --------------------------------------------------------------------------- #
def _play_room(user: dict, room: dict) -> None:
    questions = room.get("questions") or rooms.list_questions(room["id"])
    if not questions:
        st.warning(t("g_no_questions"))
        return

    answers = rooms.get_answers(room["id"], user["id"])
    termine = all(q["id"] in answers for q in questions)

    # partie terminée (ou abandonnée depuis plus de 24 h) alors que ce joueur n'a pas tout répondu : résultats seulement
    if room["status"] == rooms.FINISHED and not termine:
        st.info(t("g_room_finished"))
        _classement(room["id"], len(questions), user["id"], False)
        return

    def repondre(q: dict, valeur) -> bool:
        if q["kind"] == "open":
            texte = (valeur or "").strip()
            if not texte:
                st.error(t("g_open_empty"))
                return False
            try:
                with st.spinner(t("g_open_grading")):
                    pourcentage, commentaire = questions_ai.grade_answer(
                        q["question"], q["reference"], texte, ia_language()
                    )
            except Exception as e:                   # clé manquante, réseau, réponse illisible...
                st.error(t("g_grade_error", error=e))
                return False
            ok, message = rooms.submit_open_answer(room["code"], user["id"], q["id"], texte,
                                                   pourcentage, commentaire)
        else:
            ok, message, _ = rooms.submit_answer(room["code"], user["id"], q["id"], valeur)
        if not ok:
            st.error(tm(message))
        return ok

    _jouer(questions, answers, f"game_last_{room['id']}", repondre, _resultat_final)
    st.divider()
    _classement(room["id"], len(questions), user["id"], termine)


@st.fragment(run_every=3)
def _classement(room_id: int, total: int, user_id: int, detail: bool) -> None:
    """Classement en direct (se met à jour tout seul toutes les 3 secondes).
    detail = True une fois que le joueur a fini : tableau des pourcentages de chaque joueur par question."""
    lignes = rooms.scoreboard(room_id)
    st.subheader(t("g_ranking"))
    medailles = ["🥇", "🥈", "🥉"]
    for i, ligne in enumerate(lignes):
        rang = medailles[i] if i < 3 else f"{i + 1}."
        etat = "🏁" if ligne["answered"] >= total else f"({ligne['answered']}/{total})"
        moi = f" {t('g_you')}" if ligne["user_id"] == user_id else ""
        st.write(f"{rang} **{ligne['username']}**{moi} - {_fmt(ligne['score'])} / {total}  {etat}")
    if lignes and all(l["answered"] >= total for l in lignes):
        st.success(t("g_all_done"))
    elif detail:
        st.info(t("g_waiting_others"))

    if detail and lignes:
        par = {(m["question_id"], m["user_id"]): m["score"] for m in rooms.answers_matrix(room_id)}
        tableau = []
        for i, q in enumerate(rooms.list_questions(room_id), start=1):
            court = q["question"] if len(q["question"]) <= 60 else q["question"][:57] + "..."
            ligne_q = {t("g_question_col"): f"{i}. {court}"}
            for l in lignes:
                v = par.get((q["id"], l["user_id"]))
                ligne_q[l["username"]] = "-" if v is None else f"{v:.0f} %"
            tableau.append(ligne_q)
        st.subheader(t("g_detail"))
        st.dataframe(tableau, use_container_width=True, hide_index=True)


# --------------------------------------------------------------------------- #
# Partie en solo (QCM générés par l'IA)
# --------------------------------------------------------------------------- #
def _reset_solo() -> None:
    st.session_state["solo"] = None
    st.session_state["game_last_solo"] = None


def _play_solo(user: dict) -> None:
    solo = st.session_state.get("solo")
    if not solo:
        _solo_setup()
        return

    answers = solo["answers"]

    def repondre(q: dict, choix: int) -> bool:
        answers[q["id"]] = {"choice": choix, "text": "", "comment": "",
                            "score": 100 if choix == q["answer"] else 0}
        return True

    def fin(points: float, total: int) -> None:
        _resultat_final(points, total)
        st.button(t("g_solo_new"), key="btn_solo_new", type="primary", on_click=_reset_solo)

    _jouer(solo["questions"], answers, "game_last_solo", repondre, fin)


def _solo_setup() -> None:
    st.subheader(t("g_solo_title"))
    with st.form("form_solo"):
        theme = st.text_input(t("theme"), value=t("default_theme"), max_chars=60)
        niveau = st.selectbox(t("difficulty"), questions_ai.DIFFICULTES, index=1,
                              format_func=lambda d: t("diff_" + d))
        nb = st.slider(t("g_solo_count"), rooms.MIN_QUESTIONS, 15, 10)
        envoye = st.form_submit_button(t("g_solo_start"))

    if envoye:
        try:
            with st.spinner(t("g_solo_generating")):
                generees = questions_ai.generate_questions(theme, nb, niveau, langue=ia_language())
        except Exception as e:                       # clé manquante, réseau, réponse invalide...
            st.error(t("ai_error", error=e))
            return
        st.session_state["solo"] = {
            "questions": [{"id": i, "kind": "qcm", **q} for i, q in enumerate(generees)],
            "answers": {},
        }
        st.session_state["game_last_solo"] = None
        st.rerun()