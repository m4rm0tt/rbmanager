"""
Pipeline de classification d'une bibliothèque entière — le cœur du
produit (voir ARCHITECTURE.md §5 et PROJECT_CONTEXT.md §5-6-18).

Track -> Artist -> Genre, JAMAIS Track -> Genre directement. Le nombre
d'appels à `researcher.research()` est proportionnel au nombre
d'ARTISTES PRINCIPAUX INCONNUS, jamais au nombre de morceaux — c'est la
propriété vérifiée par `test_pipeline_batch_lookup.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.artist_split import split_artists
from app.classification.db_repo import ArtistClassificationRepo, ClassificationRecord
from app.classification.research import ArtistResearcher
from app.normalization import normalize_artist_name


@dataclass
class TrackArtistInput:
    """Entrée minimale du pipeline : un morceau et son champ artiste brut
    (tel que sorti de rbmanager, ex. "Niska feat. Booba")."""

    track_id: str
    raw_artist_field: str
    title: str = ""


@dataclass
class TrackClassification:
    track_id: str
    title: str
    primary_artist: str
    all_artists: list[str]
    primary_genre: str
    genres: list[str]
    confidence: float
    source: str


@dataclass
class ClassificationStats:
    nb_tracks: int = 0
    nb_unique_artists: int = 0
    nb_known_from_db: int = 0
    nb_researched: int = 0
    nb_tracks_without_artist: int = 0


@dataclass
class ClassificationRunResult:
    tracks: list[TrackClassification] = field(default_factory=list)
    stats: ClassificationStats = field(default_factory=ClassificationStats)


UNKNOWN_ARTIST_GENRE = "Other"
UNKNOWN_ARTIST_LABEL = "(Unknown Artist)"


def classify_library(
    tracks: list[TrackArtistInput],
    repo: ArtistClassificationRepo,
    researcher: ArtistResearcher,
) -> ClassificationRunResult:
    """Classifie tous les morceaux d'une bibliothèque en minimisant les
    recherches externes au strict nécessaire :

    1. extraire l'artiste principal de chaque morceau (split multi-artistes)
    2. normaliser + dédupliquer -> ensemble d'artistes uniques
    3. UNE requête batch pour savoir lesquels sont déjà connus
    4. rechercher UNE SEULE FOIS chaque artiste inconnu, persister
       immédiatement (disponible pour toutes les bibliothèques futures)
    5. assigner le genre de l'artiste principal à chaque morceau (le genre
       de la playlist vient toujours de l'artiste principal, mais TOUS les
       artistes cités — principal et featurings — sont classifiés et
       ajoutés à la base de connaissance partagée, voir PROJECT_CONTEXT §9)
    """
    # Étape 1-2 : artistes de chaque morceau + ensemble unique normalisé
    # (principal ET featurings, pour que la base de connaissance profite
    # aussi des artistes en featuring, sans jamais dépasser le nombre
    # d'artistes distincts réellement présents dans la bibliothèque).
    artistes_par_track: dict[str, tuple[str, list[str]]] = {}
    noms_normalises_uniques: dict[str, str] = {}  # normalisé -> forme d'affichage (première vue)
    nb_sans_artiste = 0

    for t in tracks:
        artistes = split_artists(t.raw_artist_field)
        if not artistes:
            nb_sans_artiste += 1
            artistes_par_track[t.track_id] = (UNKNOWN_ARTIST_LABEL, [])
            continue
        artistes_par_track[t.track_id] = (artistes[0], artistes)
        for nom in artistes:
            cle = normalize_artist_name(nom)
            noms_normalises_uniques.setdefault(cle, nom)

    # Étape 3 : lookup batch (une seule requête SQL, voir ArtistClassificationRepo.batch_lookup).
    connus = repo.batch_lookup(list(noms_normalises_uniques.keys()))

    # Étape 4 : recherche des seuls artistes inconnus, une fois chacun.
    inconnus = [cle for cle in noms_normalises_uniques if cle not in connus]
    nouveaux_enregistrements: list[ClassificationRecord] = []
    for cle in inconnus:
        nom_affichage = noms_normalises_uniques[cle]
        resultat = researcher.research(nom_affichage)
        record = ClassificationRecord(
            artist_name=nom_affichage,
            normalized_artist_name=cle,
            primary_genre=resultat.primary_genre,
            genres=resultat.genres,
            confidence=resultat.confidence,
            source=resultat.source,
        )
        nouveaux_enregistrements.append(record)
        connus[cle] = record

    if nouveaux_enregistrements:
        repo.upsert_many(nouveaux_enregistrements)

    # Étape 5 : assignation du genre à chaque morceau.
    resultats: list[TrackClassification] = []
    for t in tracks:
        principal, tous = artistes_par_track[t.track_id]
        if not tous:
            resultats.append(
                TrackClassification(
                    track_id=t.track_id,
                    title=t.title,
                    primary_artist=UNKNOWN_ARTIST_LABEL,
                    all_artists=[],
                    primary_genre=UNKNOWN_ARTIST_GENRE,
                    genres=[UNKNOWN_ARTIST_GENRE],
                    confidence=0.0,
                    source="no_artist",
                )
            )
            continue
        cle = normalize_artist_name(principal)
        record = connus[cle]
        resultats.append(
            TrackClassification(
                track_id=t.track_id,
                title=t.title,
                primary_artist=principal,
                all_artists=tous,
                primary_genre=record.primary_genre,
                genres=record.genres,
                confidence=record.confidence,
                source=record.source,
            )
        )

    stats = ClassificationStats(
        nb_tracks=len(tracks),
        nb_unique_artists=len(noms_normalises_uniques),
        nb_known_from_db=len(noms_normalises_uniques) - len(inconnus),
        nb_researched=len(inconnus),
        nb_tracks_without_artist=nb_sans_artiste,
    )
    return ClassificationRunResult(tracks=resultats, stats=stats)
