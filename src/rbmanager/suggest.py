"""
Tri semi-automatique à l'import — suggestion de playlists pour un morceau.

Conformément au cahier des charges : ceci ne fait que PROPOSER, rien n'est
jamais ajouté automatiquement à une playlist. L'algorithme est une
heuristique simple et volontairement transparente (chaque suggestion
explique pourquoi elle a été retenue), pas un système d'apprentissage :
- Le genre du morceau correspond au genre majoritaire des morceaux déjà
  présents dans la playlist.
- Le BPM du morceau est proche de la moyenne des BPM de la playlist.
- Le nom du fichier audio contient un mot du nom de la playlist (ou
  inversement), ex : un fichier "speed_garage_mix.mp3" pour une playlist
  "Speed Garage".

Ces trois signaux sont combinés en un score ; les playlists sans aucun
signal ne sont pas proposées. Si aucune playlist ne correspond, un nom de
playlist est suggéré à partir du genre du morceau (si connu), pour que
l'utilisateur puisse en créer une nouvelle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rbmanager.etape0 import EXIT_PLAYLIST_INTROUVABLE, ErreurConnexion, InfoPlaylist, lister_playlists_classic
from rbmanager.pdb_format import PdbFile

# Écart de BPM en dessous duquel on considère un morceau "proche" du tempo d'une playlist.
ECART_BPM_MAX = 6.0
# Seuil de proportion de morceaux de même genre dans la playlist pour considérer que ça correspond.
SEUIL_PROPORTION_GENRE = 0.5


@dataclass
class SuggestionPlaylist:
    playlist_id: str
    nom: str
    score: float
    raisons: list[str] = field(default_factory=list)

    def vers_dict(self) -> dict[str, Any]:
        return {"playlist_id": self.playlist_id, "nom": self.nom, "score": self.score, "raisons": self.raisons}


def _aplatir_playlists(noeuds: list[InfoPlaylist]):
    """Parcourt récursivement la hiérarchie et ne renvoie que les playlists (pas les dossiers)."""
    for n in noeuds:
        if n.type != "dossier":
            yield n
        yield from _aplatir_playlists(n.enfants)


def _mots_significatifs(texte: str) -> set[str]:
    separateurs = " _-.()[]"
    mot = ""
    mots = []
    for c in texte.lower():
        if c in separateurs:
            if mot:
                mots.append(mot)
            mot = ""
        else:
            mot += c
    if mot:
        mots.append(mot)
    return {m for m in mots if len(m) > 2}


def suggerer_playlists_classic(chemin_export_pdb: str | Path, track_id: str) -> tuple[list[SuggestionPlaylist], str | None]:
    """Renvoie (suggestions triées par score décroissant, nom_suggere_si_aucune_ne_correspond)."""
    db = PdbFile(chemin_export_pdb)
    pistes = db.track_info()
    piste = pistes.get(track_id)
    if piste is None:
        raise ErreurConnexion(f"Morceau introuvable dans la base (id={track_id}).", EXIT_PLAYLIST_INTROUVABLE)

    genres = db.genre_names()
    entries = db.playlist_entry_rows()
    hierarchie = lister_playlists_classic(chemin_export_pdb)

    par_playlist: dict[str, list[str]] = {}
    for e in entries:
        par_playlist.setdefault(e.playlist_id, []).append(e.track_id)

    suggestions: list[SuggestionPlaylist] = []
    for p in _aplatir_playlists(hierarchie):
        track_ids_playlist = par_playlist.get(p.id, [])
        pistes_playlist = [pistes[tid] for tid in track_ids_playlist if tid in pistes]
        if not pistes_playlist:
            continue

        score = 0.0
        raisons: list[str] = []

        if piste.genre_id != "0":
            genres_playlist = [t.genre_id for t in pistes_playlist]
            proportion = genres_playlist.count(piste.genre_id) / len(genres_playlist)
            if proportion >= SEUIL_PROPORTION_GENRE:
                score += 2 * proportion
                nom_genre = genres.get(piste.genre_id, f"genre #{piste.genre_id}")
                raisons.append(f"genre « {nom_genre} » partagé par {proportion * 100:.0f}% des morceaux de la playlist")

        bpms = [t.tempo_bpm for t in pistes_playlist if t.tempo_bpm > 0]
        if bpms and piste.tempo_bpm > 0:
            moyenne = sum(bpms) / len(bpms)
            ecart = abs(piste.tempo_bpm - moyenne)
            if ecart <= ECART_BPM_MAX:
                score += (ECART_BPM_MAX - ecart) / ECART_BPM_MAX
                raisons.append(f"BPM proche de la moyenne de la playlist ({moyenne:.0f}, écart de {ecart:.1f})")

        if piste.filename:
            mots_playlist = _mots_significatifs(p.nom)
            nom_fichier = piste.filename.lower()
            if any(mot in nom_fichier for mot in mots_playlist):
                score += 1.0
                raisons.append(f"le nom du fichier contient un mot du nom de la playlist « {p.nom} »")

        if score > 0:
            suggestions.append(SuggestionPlaylist(playlist_id=p.id, nom=p.nom, score=round(score, 2), raisons=raisons))

    suggestions.sort(key=lambda s: -s.score)

    nom_suggere = None
    if not suggestions and piste.genre_id != "0":
        nom_suggere = genres.get(piste.genre_id)

    return suggestions[:5], nom_suggere
