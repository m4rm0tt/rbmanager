"""
Découpage d'un champ artiste brut (potentiellement multi-artistes) en
artistes individuels — voir ARCHITECTURE.md §4 et PROJECT_CONTEXT.md §9.

"Niska feat. Booba" ne doit JAMAIS devenir un seul artiste
"Niska feat. Booba" : on veut ["Niska", "Booba"], avec "Niska" comme
artiste principal (premier de la liste), utilisé pour le genre du
morceau dans le MVP.

Séparateurs gérés, validés empiriquement sur une vraie base Rekordbox
(511 artistes réels) : "&" n'est reconnu comme séparateur que s'il est
entouré d'espaces, pour ne jamais casser un nom de duo écrit sans
espaces comme "W&W".
"""

from __future__ import annotations

import re

_SEPARATEURS = re.compile(
    r"""
    \s+feat\.?\s+ |
    \s+featuring\s+ |
    \s+ft\.?\s+ |
    \s+&\s+ |
    ,\s* |
    \s+x\s+ |
    \s+vs\.?\s+ |
    \s+with\s+
    """,
    re.IGNORECASE | re.VERBOSE,
)


def split_artists(champ_artiste_brut: str) -> list[str]:
    """Renvoie la liste ordonnée des artistes individuels (artiste
    principal en premier), noms nettoyés mais accents/casse préservés."""
    if not champ_artiste_brut or not champ_artiste_brut.strip():
        return []
    morceaux = _SEPARATEURS.split(champ_artiste_brut)
    noms = [m.strip() for m in morceaux if m and m.strip()]
    # Dédoublonne en préservant l'ordre (un featuring peut citer deux fois
    # le même nom par erreur de métadonnées).
    vus: set[str] = set()
    resultat = []
    for nom in noms:
        cle = nom.lower()
        if cle not in vus:
            vus.add(cle)
            resultat.append(nom)
    return resultat


def artiste_principal(champ_artiste_brut: str) -> str | None:
    """Raccourci : premier artiste du champ, ou None si le champ est vide."""
    noms = split_artists(champ_artiste_brut)
    return noms[0] if noms else None
