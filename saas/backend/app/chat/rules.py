"""
Chat -> édition de configuration, JAMAIS exécution directe (voir
PROJECT_CONTEXT.md §13/§14, ARCHITECTURE.md §7).

Implémentation MVP : interpréteur à règles (pas d'appel LLM externe
depuis ce sandbox). Le contrat `interpret(message, config) ->
ChatInterpretationResult` est conçu pour être remplacé par un vrai appel
à un modèle de langage sans changer le reste du système : seule cette
fonction changerait, le reste (plan builder, routes, confirmation
utilisateur) reste identique.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass

from app.plan.config import GenreConfig

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^(?:mets?|d[ée]place)\s+(?:le |la |les |l')?(?P<source>.+?)\s+dans\s+(?:le |la |les |l')?(?P<target>.+?)\.?$", re.IGNORECASE), "redirect"),
    (re.compile(r"^tout ce qui est\s+(?P<source>.+?)\s+doit aller dans\s+(?P<target>.+?)\.?$", re.IGNORECASE), "redirect"),
    (re.compile(r"^cr[ée]e?\s+(?:une |la )?(?:cat[ée]gorie|genre)\s+(?P<name>.+?)\.?$", re.IGNORECASE), "create_genre"),
    (re.compile(r"^(?:je veux )?s[ée]parer?\s+(?P<a>.+?)\s+et\s+(?P<b>.+?)\.?$", re.IGNORECASE), "split"),
]


@dataclass
class ChatInterpretationResult:
    understood: bool
    action: str
    explanation: str
    config: GenreConfig


def interpret(message: str, config: GenreConfig) -> ChatInterpretationResult:
    """Renvoie une COPIE de `config` modifiée (jamais mutée en place) : ne
    touche jamais la bibliothèque, seulement la configuration de
    classification. L'appelant (route /chat) doit ensuite régénérer un
    plan et le présenter en preview — voir PROJECT_CONTEXT.md §14."""
    texte = message.strip()
    nouvelle_config = copy.deepcopy(config)

    for pattern, action in _PATTERNS:
        m = pattern.match(texte)
        if not m:
            continue

        if action == "redirect":
            source = m.group("source").strip()
            target = m.group("target").strip()
            if _est_un_genre_connu(source, nouvelle_config):
                nouvelle_config.redirect_genre(source, target)
                return ChatInterpretationResult(
                    True, "redirect_genre", f"Les morceaux classés « {source} » iront désormais dans « {target} ».", nouvelle_config
                )
            # Sinon on suppose que `source` est un nom d'artiste (correction manuelle, voir §23).
            nouvelle_config.override_artist(source, target)
            return ChatInterpretationResult(
                True, "override_artist", f"Les morceaux de « {source} » iront désormais dans « {target} ».", nouvelle_config
            )

        if action == "create_genre":
            name = m.group("name").strip()
            nouvelle_config.add_genre(name)
            return ChatInterpretationResult(True, "create_genre", f"Catégorie « {name} » créée.", nouvelle_config)

        if action == "split":
            a = m.group("a").strip()
            b = m.group("b").strip()
            for genre in (a, b):
                nouvelle_config.add_genre(genre)
                cle = genre.strip().lower()
                nouvelle_config.genre_redirects.pop(cle, None)
            return ChatInterpretationResult(
                True, "split_genres", f"« {a} » et « {b} » sont maintenant deux catégories séparées.", nouvelle_config
            )

    return ChatInterpretationResult(
        False,
        "not_understood",
        "Je n'ai pas compris cette instruction. Essaie par exemple : "
        '"Mets le baile funk dans Latino." ou "Crée une catégorie White Girl Music."',
        nouvelle_config,
    )


def _est_un_genre_connu(nom: str, config: GenreConfig) -> bool:
    return nom.strip().lower() in {g.lower() for g in config.genres} or nom.strip().lower() in config.genre_redirects
