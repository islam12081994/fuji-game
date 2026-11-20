"""
user/grading.py
Correction des réponses libres : pourcentage de bonne réponse (0 à 100).

Règles (réglables avec les constantes ci-dessous) :
  - réponse exacte                      -> 100 %
  - faute(s) d'orthographe              -> on retire TYPO_PENALTY % par faute (distance de Levenshtein),
                                           et jamais plus que ce que permet la longueur du mot
  - date / année décalée de 1 an (+-1)  -> on retire YEAR_PENALTY % (par année décalée)
  - date / année décalée de 2 ans ou +  -> 0 %
  - nombre (non date) différent         -> 0 %
  - la réponse est VRAIE seulement si le pourcentage est STRICTEMENT supérieur à SEUIL_VRAI (50 %)

La correction locale est instantanée et ne dépend d'aucune clé API. Si elle trouve moins de 50 % et que la
réponse attendue ne contient aucun chiffre, l'IA (Groq) est consultée UNIQUEMENT pour reconnaître un synonyme,
un surnom ou une reformulation ; son score est plafonné à IA_MAX (ce n'est pas la réponse exacte).
Si l'IA n'est pas disponible (clé manquante, réseau...), on garde simplement la correction locale.
"""
import re
import unicodedata
from dataclasses import dataclass

from i18n import t

SEUIL_VRAI = 50          # vrai seulement si pourcentage > 50
TYPO_PENALTY = 12        # % retirés par faute d'orthographe
TYPO_RELATIVE = 1.5      # une faute coûte aussi (1,5 x faute / longueur) : sur un mot court, ça compte plus
YEAR_PENALTY = 25        # % retirés quand l'année est décalée de 1 an (+-1)
IA_MAX = 90              # plafond du pourcentage donné par l'IA (synonymes, reformulations)

# mots de liaison ignorés dans la comparaison
_MOTS_VIDES = {"le", "la", "les", "l", "un", "une", "des", "du", "de", "d", "en", "au", "aux", "et",
               "the", "a", "an", "of", "in", "and", "on"}


_CHIFFRES = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


@dataclass
class Resultat:
    pct: int                 # pourcentage final (0 à 100)
    raison: str              # exact | typo | year | wrong | year_wrong | year_missing | number_wrong | empty
    fautes: int = 0          # nombre de fautes d'orthographe
    annees_decalees: int = 0 # nombre d'années décalées de 1 an


# --------------------------------------------------------------------------- #
# Outils
# --------------------------------------------------------------------------- #
def normaliser(texte: str) -> str:
    """minuscules, sans accents, sans ponctuation, espaces simples."""
    texte = (texte or "").translate(_CHIFFRES)         # chiffres arabes (١٧٨٩) -> 1789
    texte = unicodedata.normalize("NFKD", texte.lower())
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = re.sub(r"[^\w\s]|_", " ", texte)
    return re.sub(r"\s+", " ", texte).strip()


def _est_annee(mot: str) -> bool:
    return mot.isdigit() and 3 <= len(mot) <= 4 and 100 <= int(mot) <= 2999


def _annees(texte: str) -> list[int]:
    return [int(m) for m in re.findall(r"\d+", texte) if _est_annee(m)]


def _sans_annees(texte: str) -> str:
    return re.sub(r"\d+", lambda m: " " if _est_annee(m.group()) else m.group(), texte)


def _mots_utiles(texte: str) -> list[str]:
    return [m for m in texte.split() if m not in _MOTS_VIDES]


def levenshtein(a: str, b: str) -> int:
    """Nombre minimal de fautes (ajout, oubli, remplacement d'une lettre) pour passer de a à b."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    precedent = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        courant = [i]
        for j, cb in enumerate(b, start=1):
            courant.append(min(precedent[j] + 1, courant[j - 1] + 1, precedent[j - 1] + (ca != cb)))
        precedent = courant
    return precedent[-1]


# --------------------------------------------------------------------------- #
# Correction locale (sans IA)
# --------------------------------------------------------------------------- #
def grade_local(reference: str, reponse: str) -> Resultat:
    ref, rep = normaliser(reference), normaliser(reponse)
    if not rep:
        return Resultat(0, "empty")
    if rep == ref:
        return Resultat(100, "exact")

    # 1) les années (dates) : exactes, ou décalées de 1 an (pénalité), sinon faux
    annees_decalees = 0
    annees_ref = _annees(ref)
    if annees_ref:
        annees_rep = _annees(rep)
        if len(annees_rep) < len(annees_ref):
            return Resultat(0, "year_missing")
        for a_ref, a_rep in zip(annees_ref, annees_rep):
            ecart = abs(a_ref - a_rep)
            if ecart == 1:
                annees_decalees += 1
            elif ecart > 1:
                return Resultat(0, "year_wrong")
        ref, rep = _sans_annees(ref), _sans_annees(rep)

    # 2) le reste du texte : fautes d'orthographe
    mots_ref, mots_rep = _mots_utiles(ref), _mots_utiles(rep)
    fautes, pct_texte = 0, 100
    if mots_ref:
        # les nombres (qui ne sont pas des dates) doivent être exacts
        if re.findall(r"\d+", " ".join(mots_ref)) != re.findall(r"\d+", " ".join(mots_rep)):
            return Resultat(0, "number_wrong")
        a, b = " ".join(mots_ref), " ".join(mots_rep)
        if all(m.isdigit() for m in mots_ref):
            a = b = ""                       # réponse purement numérique : "8848 m" = "8848" (unités ignorées)
        # l'ordre des mots ne compte pas ("Vinci Leonardo de" = "Leonardo de Vinci")
        fautes = min(levenshtein(a, b), levenshtein(" ".join(sorted(a.split())), " ".join(sorted(b.split()))))
        if fautes:
            longueur = max(len(a), 1)
            pct_texte = min(100 - TYPO_PENALTY * fautes,
                            round(100 * (1 - TYPO_RELATIVE * fautes / longueur)))
    pct = max(0, pct_texte - YEAR_PENALTY * annees_decalees)

    if pct == 100:
        raison = "exact"
    elif pct_texte <= 0 or pct <= 0 or (fautes and pct_texte <= SEUIL_VRAI and not annees_decalees):
        raison = "wrong"
    elif annees_decalees and not fautes:
        raison = "year"
    else:
        raison = "typo"
    return Resultat(max(0, pct), raison, fautes, annees_decalees)


def _commentaire(r: Resultat) -> str:
    morceaux = []
    if r.raison == "exact":
        return t("g_cmt_exact")
    if r.fautes and r.raison != "wrong":
        morceaux.append(t("g_cmt_typo", n=r.fautes, p=min(100, TYPO_PENALTY * r.fautes)))
    if r.annees_decalees and r.raison != "wrong":
        morceaux.append(t("g_cmt_year", n=r.annees_decalees, p=YEAR_PENALTY * r.annees_decalees))
    if morceaux:
        return " ".join(morceaux)
    return {"year_wrong": t("g_cmt_year_wrong"), "year_missing": t("g_cmt_year_missing"),
            "number_wrong": t("g_cmt_number_wrong")}.get(r.raison, t("g_cmt_wrong"))


# --------------------------------------------------------------------------- #
# Correction complète : local d'abord, IA seulement en dernier recours
# --------------------------------------------------------------------------- #
def grade(question: str, reference: str, reponse: str, langue: str = "français",
          autre_reference: str = "") -> tuple[int, str]:
    """Retourne (pourcentage 0-100, commentaire). Ne lève jamais d'exception.
    autre_reference : la réponse attendue dans la langue d'origine de la question (room multilingue) ;
    on garde le meilleur des deux résultats."""
    local = grade_local(reference, reponse)
    if autre_reference and autre_reference != reference:
        autre = grade_local(autre_reference, reponse)
        if autre.pct > local.pct:
            local = autre
    commentaire = _commentaire(local)

    a_chiffres = bool(re.search(r"\d", reference or ""))
    if local.pct > SEUIL_VRAI or a_chiffres or local.raison == "empty":
        return local.pct, commentaire

    # moins de 50 % et pas de chiffre : peut-être un synonyme / un surnom / une reformulation
    try:
        from user import questions_ai
        pct_ia, com_ia = questions_ai.grade_answer(question, reference, reponse, langue)
    except Exception:                       # clé manquante, réseau, réponse illisible : on garde le local
        return local.pct, commentaire
    pct_ia = min(pct_ia, IA_MAX)
    if pct_ia > local.pct:
        return pct_ia, com_ia or commentaire
    return local.pct, commentaire
