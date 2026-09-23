"""
Assemblage du profil en long à partir des données par profil (distance au point dur
amont).

Vue de contrôle uniquement : les deux séries sont lues telles quelles depuis chaque
profil (min(z) du terrain existant relevé, anchor_z du profil projet). Rien n'est
recalculé ni réinjecté dans les profils individuels — anchor_z et la pente restent
indépendants profil par profil.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class HardPointMarker:
    """Un point dur positionné sur le profil en long : distance au point dur amont (0
    pour le point dur amont lui-même, par convention) et altitude, avec son nom pour
    l'identifier sur le graphique."""
    distance: float
    z: float
    name: str


@dataclass
class LongitudinalProfile:
    """Deux séries (distance au point dur amont, Z) à tracer en fonction de cette
    distance : TN existant (thalweg relevé) et fond de lit projet (anchor_z). Les champs
    gardent le préfixe `pk_` par cohérence avec le reste du module. Les deux séries
    peuvent avoir des longueurs différentes si certains profils n'ont pas encore de
    points existants ou de paramètres projet enregistrés. Les points durs amont/aval
    sont absents (None) tant que les coordonnées nécessaires à leur positionnement ne
    sont pas toutes renseignées."""
    pk_existing: List[float] = field(default_factory=list)
    z_existing: List[float] = field(default_factory=list)
    pk_project: List[float] = field(default_factory=list)
    z_project: List[float] = field(default_factory=list)
    hard_point_upstream: Optional[HardPointMarker] = None
    hard_point_downstream: Optional[HardPointMarker] = None


def build_longitudinal_profile(
    rows: List[Tuple[float, Optional[float], Optional[float]]],
    hard_points: Optional[dict] = None,
) -> LongitudinalProfile:
    """Sépare les triplets (pk, min_z_existant, anchor_z_projet) — typiquement issus de
    DatabaseManager.get_longitudinal_data — en deux séries indépendantes, en ignorant
    pour chaque série les profils où la valeur correspondante est absente (None).

    `hard_points`, si fourni (format DatabaseManager.get_hard_points), positionne en
    plus les deux points durs : le point dur amont est toujours à la distance 0 (par
    convention) dès que son altitude est connue ; le point dur aval est positionné à
    (X_aval - X_amont) dès que les deux X et le Z aval sont connus. Rien n'est calculé
    si les coordonnées nécessaires manquent : le point correspondant reste absent
    (None) plutôt que d'être placé à une position arbitraire."""
    profile = LongitudinalProfile()

    for pk, min_z_existing, anchor_z_project in rows:
        if min_z_existing is not None:
            profile.pk_existing.append(pk)
            profile.z_existing.append(min_z_existing)
        if anchor_z_project is not None:
            profile.pk_project.append(pk)
            profile.z_project.append(anchor_z_project)

    if hard_points:
        upstream = hard_points.get("upstream") or {}
        downstream = hard_points.get("downstream") or {}

        if upstream.get("z") is not None:
            profile.hard_point_upstream = HardPointMarker(
                distance=0.0, z=upstream["z"], name=upstream.get("name") or "Point dur amont"
            )

        if (upstream.get("x") is not None and downstream.get("x") is not None
                and downstream.get("z") is not None):
            profile.hard_point_downstream = HardPointMarker(
                distance=downstream["x"] - upstream["x"],
                z=downstream["z"],
                name=downstream.get("name") or "Point dur aval",
            )

    return profile
