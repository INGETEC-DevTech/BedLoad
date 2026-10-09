"""
Assemblage du profil en long à partir des données par profil (distance au premier point
dur).

Vue de contrôle uniquement : les deux séries sont lues telles quelles depuis chaque
profil (min(z) du terrain existant relevé, anchor_z du profil projet). Rien n'est
recalculé ni réinjecté dans les profils individuels — anchor_z et la pente restent
indépendants profil par profil.

Lit existant et lit projet sont dissociés (rivière déplacée ou reméandrée) : le terrain
existant est placé à la distance existante de chaque profil (au premier point dur
existant), le fond projet à sa distance projet (au premier point dur projet), et chaque
famille de points durs a ses propres repères et tronçons (cf. core.hard_points).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core.hard_points import EXISTING, PROJECT, HardPoint, complete_points, of_family


@dataclass
class HardPointMarker:
    """Un point dur positionné sur le profil en long : distance au premier point dur de sa
    famille (0 pour celui-ci) et altitude, avec son nom pour l'identifier sur le graphique."""
    distance: float
    z: float
    name: str


@dataclass
class SegmentMarker:
    """Tronçon entre deux points durs voisins d'une même famille, avec sa pente (m/m)."""
    start: HardPointMarker
    end: HardPointMarker
    slope: float


@dataclass
class StationEarthworks:
    """Déblai et remblai (surfaces en coupe, m²) d'un profil en travers, tels que les
    calcule l'onglet Profil projet (existant vs projet), pour les afficher sur le profil en
    long. `cut` et `fill` valent None si le calcul est impossible ; `note` dit alors
    pourquoi (ex. profil projet non renseigné)."""
    distance: float
    name: str
    cut: Optional[float] = None
    fill: Optional[float] = None
    note: str = ""

    @property
    def computed(self) -> bool:
        return self.cut is not None and self.fill is not None


@dataclass
class Station:
    """Un profil en travers sur le profil en long : ses deux distances (existante, au
    premier point dur existant ; projet, au premier point dur projet) et ses deux cotes,
    None quand le profil n'a pas encore de terrain existant ou de profil projet."""
    name: str
    distance: float
    project_distance: float
    z_existing: Optional[float] = None
    z_project: Optional[float] = None


@dataclass
class LongitudinalProfile:
    """Deux séries (distance, Z) à tracer : TN existant (thalweg relevé), à la distance
    existante de chaque profil, et fond de lit projet (anchor_z), à sa distance projet. Les
    champs gardent le préfixe `pk_` par cohérence avec le reste du module. Les deux séries
    peuvent avoir des longueurs différentes si certains profils n'ont pas encore de
    points existants ou de paramètres projet enregistrés. `hard_points` liste les points
    durs existants complets (PK et Z), dans l'ordre des PK, et `segments` les tronçons qui
    les relient avec leur pente ; `project_hard_points` et `project_segments`, de même pour
    les points durs projet."""
    pk_existing: List[float] = field(default_factory=list)
    z_existing: List[float] = field(default_factory=list)
    pk_project: List[float] = field(default_factory=list)
    z_project: List[float] = field(default_factory=list)
    hard_points: List[HardPointMarker] = field(default_factory=list)
    segments: List[SegmentMarker] = field(default_factory=list)
    project_hard_points: List[HardPointMarker] = field(default_factory=list)
    project_segments: List[SegmentMarker] = field(default_factory=list)
    # Profils en travers : (distance existante, nom) de chacun, qu'il ait des valeurs ou
    # non, pour les repérer sur le graphique ; et nom du profil de chaque point des deux
    # séries (pour le survol). `station_records` : le détail de chacun (cf. Station).
    stations: List[Tuple[float, str]] = field(default_factory=list)
    station_records: List[Station] = field(default_factory=list)
    names_existing: List[str] = field(default_factory=list)
    names_project: List[str] = field(default_factory=list)
    # Déblai / remblai de chaque profil en travers (cf. ProfileController.station_earthworks).
    earthworks: List[StationEarthworks] = field(default_factory=list)


def build_longitudinal_profile(
    rows: List[Tuple],
    hard_points: Optional[List[Dict]] = None,
) -> LongitudinalProfile:
    """Sépare les lignes (distance existante, min_z_existant, anchor_z_projet[, nom du
    profil[, distance projet]]) — typiquement issues de
    DatabaseManager.get_longitudinal_data — en deux séries indépendantes, en ignorant pour
    chaque série les profils où la valeur correspondante est absente (None) : le TN
    existant à la distance existante, le fond projet à la distance projet (la distance
    existante faute de 5e élément). Chaque profil est aussi repéré (distance existante,
    nom) dans `stations`.

    `hard_points` (format DatabaseManager.get_hard_points : [{name, pk, z, family}] ; sans
    famille, un point est existant) positionne en plus, pour chaque famille, tous ses
    points durs complets, à leur distance au premier d'entre eux (la référence "distance
    0" des profils de cette famille), et les tronçons qui les relient avec leur pente. Un
    point incomplet (PK ou Z manquant) n'est pas placé à une position arbitraire : il est
    simplement absent du graphique."""
    profile = LongitudinalProfile()

    for row in rows:
        pk, min_z_existing, anchor_z_project = row[:3]
        # Éléments facultatifs : le nom du profil et sa distance projet (cf. get_longitudinal_data).
        name = row[3] if len(row) > 3 and row[3] else f"{pk:g} m"
        project_pk = row[4] if len(row) > 4 and row[4] is not None else pk
        profile.stations.append((pk, name))
        profile.station_records.append(Station(name=name, distance=pk, project_distance=project_pk,
                                               z_existing=min_z_existing, z_project=anchor_z_project))
        if min_z_existing is not None:
            profile.pk_existing.append(pk)
            profile.z_existing.append(min_z_existing)
            profile.names_existing.append(name)
        if anchor_z_project is not None:
            profile.pk_project.append(project_pk)
            profile.z_project.append(anchor_z_project)
            profile.names_project.append(name)

    all_points = [HardPoint.from_dict(p) for p in (hard_points or [])]
    profile.hard_points, profile.segments = _markers(of_family(all_points, EXISTING))
    profile.project_hard_points, profile.project_segments = _markers(of_family(all_points, PROJECT))
    return profile


def _markers(points: List[HardPoint]) -> Tuple[List[HardPointMarker], List[SegmentMarker]]:
    """Repères et tronçons d'une famille de points durs, à leur distance au premier point
    complet de la famille."""
    points = complete_points(points)
    if not points:
        return [], []
    reference = points[0].pk
    markers = [
        HardPointMarker(distance=p.pk - reference, z=p.z, name=p.name or f"Point dur {i}")
        for i, p in enumerate(points, start=1)
    ]
    segments = [
        SegmentMarker(start=a, end=b, slope=(a.z - b.z) / (b.distance - a.distance))
        for a, b in zip(markers, markers[1:])
        if b.distance > a.distance
    ]
    return markers, segments


@dataclass
class LongitudinalTableRow:
    """Une ligne du tableau du profil en long (export Excel) : un profil en travers, avec
    ses deux distances et ses cotes existante et projet quand il les a, ou un point dur,
    avec la distance et la cote de sa famille (celles de l'autre famille restant None)."""
    name: str
    distance: Optional[float] = None
    project_distance: Optional[float] = None
    z_existing: Optional[float] = None
    z_project: Optional[float] = None
    z_hard_point: Optional[float] = None
    z_project_hard_point: Optional[float] = None


def longitudinal_table(profile: LongitudinalProfile) -> List[LongitudinalTableRow]:
    """Tableau du profil en long : une ligne par profil en travers et une par point dur,
    avec exactement les valeurs du graphique (une cote absente vaut None).

    Ordre : profils et points durs existants par distance existante (à distance égale, le
    point dur d'abord) ; chaque point dur projet, qui n'a qu'une distance projet, juste
    avant le premier profil dont la distance projet l'atteint (à la fin s'il n'y en a pas),
    c'est-à-dire entre les profils qui l'encadrent sur le nouveau lit."""
    rows = [LongitudinalTableRow(name=m.name, distance=m.distance, z_hard_point=m.z)
            for m in profile.hard_points]
    rows += [LongitudinalTableRow(name=s.name, distance=s.distance, project_distance=s.project_distance,
                                  z_existing=s.z_existing, z_project=s.z_project)
             for s in profile.station_records]
    # Tri stable : les points durs, ajoutés en premier, restent devant à distance égale.
    rows.sort(key=lambda row: row.distance)

    project_points = [LongitudinalTableRow(name=m.name, project_distance=m.distance, z_project_hard_point=m.z)
                      for m in profile.project_hard_points]
    table, index = [], 0
    for row in rows:
        if row.project_distance is not None:
            while index < len(project_points) and project_points[index].project_distance <= row.project_distance:
                table.append(project_points[index])
                index += 1
        table.append(row)
    table.extend(project_points[index:])
    return table
