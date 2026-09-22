"""
Normalisation des noms d'artiste — clé de recherche de l'Artist
Classification Database (voir ARCHITECTURE.md §4).

Objectif : que "Niska", "niska", "NISKA", "  Niska  " pointent tous vers
la même ligne en base, SANS jamais fusionner deux artistes réellement
différents par ressemblance (pas de fuzzy matching ici — seulement une
égalité exacte sur la forme normalisée, déterministe).
"""

from __future__ import annotations

import re
import unicodedata

_ESPACES_MULTIPLES = re.compile(r"\s+")
# Ponctuation bénigne à ignorer dans la clé de recherche (ne change pas
# l'identité de l'artiste : apostrophes, points, tirets isolés...).
_PONCTUATION_A_IGNORER = re.compile(r"[.'’`\"]")
# Suffixe de collaboration résiduel en fin de chaîne sans nom derrière
# (ex: "Niska feat." mal renseigné) — nettoyé après le split (voir
# artist_split.py), pas avant, pour ne pas perdre d'information ici.
_SUFFIXE_COLLAB_RESIDUEL = re.compile(r"\s+(feat\.?|featuring|ft\.?)\s*$", re.IGNORECASE)


def _sans_accents(texte: str) -> str:
    """Replie les caractères accentués vers leur forme de base (Ömer -> Omer)."""
    decompose = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in decompose if not unicodedata.combining(c))


def normalize_artist_name(nom_artiste: str) -> str:
    """Renvoie la clé de recherche normalisée d'un nom d'artiste unique.

    Ne pas appeler directement sur un champ multi-artistes brut : passer
    d'abord par `artist_split.split_artists`. Le nom d'affichage
    d'origine (avec accents et casse) est conservé séparément par
    l'appelant — cette fonction ne produit qu'une clé de recherche.
    """
    if not nom_artiste:
        return ""
    texte = nom_artiste.strip()
    texte = _SUFFIXE_COLLAB_RESIDUEL.sub("", texte)
    texte = texte.lower()
    texte = _sans_accents(texte)
    texte = _PONCTUATION_A_IGNORER.sub("", texte)
    texte = _ESPACES_MULTIPLES.sub(" ", texte)
    return texte.strip()
