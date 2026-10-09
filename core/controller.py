# core/controller.py
"""
Calculs d'un profil à partir de ses données enregistrées (points du profil existant,
paramètres du profil projet et de l'hydraulique) : sections, calcul hydraulique,
débordement, déblais / remblais, récapitulatifs de scénario et de projet.

Uniquement du calcul : aucune figure, aucun texte ni couleur d'affichage. La présentation
(graphiques, encadrés de résultats, avertissements) vit dans viz.figures.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

from core.earthworks import compute_earthworks
from core.geometry import build_project_cross_section
from core.models import CrossSection, ProjectParameters, dataframe_to_points
from core.hydraulics import (clip_to_bounds, compute_hydraulic_params, free_end_levels,
                             overflow_level, resolve_hydraulic_result, target_discharge_reached)
from core.hard_points import EXISTING, PROJECT, HardPoint, complete_points, of_family
from core.longitudinal import StationEarthworks, build_longitudinal_profile
from core.project_summary import ProjectSummary, ScenarioSummary, earthwork_volumes

# Zones d'écoulement du calcul hydraulique (cf. ProjectParameters.hydro_zone).
ALL_ZONE = "all"
LEFT_ARM = "left_arm"
RIGHT_ARM = "right_arm"
CUSTOM_ZONE = "custom"

# Sortes de débordement (cf. OverflowDiagnosis).
TARGET_NOT_REACHED = "target_not_reached"
OVERFLOW = "overflow"


def flow_zone_bounds(hydro_data: Dict[str, Any]) -> Tuple[str, Optional[Tuple[float, float]]]:
    """Traduit le choix de zone d'écoulement en limites de calcul (cf. core.hydraulics.Bounds) :
    - tout le profil : aucune limite, l'eau remplit tous les bras qu'atteint la cote d'eau ;
    - un seul bras : une paroi sur la séparation des bras, le côté du bras choisi restant
      borné par l'extrémité naturelle du profil (limite infinie) ;
    - entre deux X : deux parois.
    Retourne (zone, limites). Lève ValueError si les deux X sont incohérents : MainWindow
    affiche alors le message à la place du graphique."""
    zone = hydro_data.get('hydro_zone')
    if zone is None:
        # Profil enregistré avant le choix du bras : ancienne case "Limiter le calcul au lit
        # compris entre deux X".
        zone = CUSTOM_ZONE if hydro_data.get('hydro_bounds_enabled') else ALL_ZONE

    if zone == CUSTOM_ZONE:
        x_left = float(hydro_data.get('hydro_x_left', 0.0))
        x_right = float(hydro_data.get('hydro_x_right', 0.0))
        if not x_left < x_right:
            raise ValueError(
                "Zone de calcul : le X gauche doit être strictement inférieur au X droite."
            )
        return zone, (x_left, x_right)
    if zone in (LEFT_ARM, RIGHT_ARM):
        split = float(hydro_data.get('hydro_arm_split_x', 0.0))
        return zone, ((-math.inf, split) if zone == LEFT_ARM else (split, math.inf))
    return ALL_ZONE, None


@dataclass
class HydraulicsSolution:
    """Calcul hydraulique d'un profil, tel que l'affiche l'onglet Hydraulique."""
    section: CrossSection
    hydro_source: str
    zone: str
    bounds: Any
    z_ref: float
    calc_mode: str
    slope: float
    ks: float
    q_target: float
    res: Dict[str, Any]


@dataclass
class OverflowDiagnosis:
    """L'eau déborderait hors du profil calculé (débordement non modélisé) :
    - TARGET_NOT_REACHED ("Imposer Q") : le débit cible n'est pas atteint, la cote d'eau
      étant plafonnée (la dichotomie ne peut pas monter au-dessus du profil sans déborder) ;
    - OVERFLOW ("Imposer H") : la cote d'eau saisie dépasse une extrémité libre du profil.
    `level` est la cote maximale sans débordement et `q_max` la capacité à cette cote (None
    tous les deux faute d'extrémité libre) ; `end_levels` donne, pour OVERFLOW, la cote de
    chaque extrémité débordée ("left" / "right"), dans l'ordre de res["overflow_sides"]."""
    kind: str
    level: Optional[float]
    q_max: Optional[float]
    end_levels: Dict[str, float] = field(default_factory=dict)


class ProfileController:
    # Nombre minimal de points pour former un profil en travers.
    MIN_SECTION_POINTS = 2

    @staticmethod
    def default_project_params() -> Dict[str, Any]:
        return vars(ProjectParameters())

    def station_earthworks(self, states: List[Dict[str, Any]]) -> List[StationEarthworks]:
        """Déblai / remblai de chaque profil d'un scénario (états au format
        DatabaseManager.get_scenario_profile_states), calculés exactement comme dans
        l'onglet Profil projet : existant vs projet, sur leur emprise commune. Un profil
        sans terrain existant (moins de 2 points) ou sans profil projet enregistré (pas de
        cote d'ancrage, comme pour la série "Projet" du profil en long) n'est pas calculé :
        sa raison est notée, pour l'afficher au survol."""
        result = []
        for state in states:
            distance = state["distance"]
            station = StationEarthworks(distance=distance, name=state["name"] or f"{distance:g} m")
            result.append(station)

            existing = self.to_cross_section(state["existing_data"], name="Existant")
            saved_params = state["project_params"] or {}
            if existing is None:
                station.note = "profil existant incomplet"
                continue
            if saved_params.get("anchor_z") is None:
                station.note = "profil projet non renseigné"
                continue
            try:
                params = self.to_project_parameters({**self.default_project_params(), **saved_params})
                works = compute_earthworks(existing, build_project_cross_section(params, name="Projet"))
            except ValueError as e:
                station.note = f"profil projet invalide ({e})"
                continue
            if works.extent is None:
                station.note = "pas d'emprise commune entre existant et projet"
                continue
            station.cut, station.fill = works.cut_total, works.fill_total
        return result

    def solve_hydraulics(
        self,
        existing_data: List[Dict[str, Any]],
        project_data: Dict[str, Any],
        hydro_data: Dict[str, Any],
    ) -> Optional[HydraulicsSolution]:
        """Calcul hydraulique d'un profil (section choisie, zone d'écoulement, cote de
        référence du tirant d'eau, résultat), commun au graphique de l'onglet Hydraulique et
        au récapitulatif du projet. None si la section source n'a pas assez de points ;
        ValueError si la séparation des bras tombe hors du profil."""
        hydro_source = hydro_data.get('hydro_source', 'project')
        zone, bounds = flow_zone_bounds(hydro_data)

        if hydro_source == 'existing':
            section = self.to_cross_section(existing_data, name="Existant")
            if section is None:
                return None
        else:
            params = self.to_project_parameters(project_data)
            section = build_project_cross_section(params, name="Projet")

        if zone in (LEFT_ARM, RIGHT_ARM):
            split = bounds[1] if zone == LEFT_ARM else bounds[0]
            first, last = section.points[0].x, section.points[-1].x
            if not first < split < last:
                raise ValueError(
                    f"Séparation des bras : X = {split:.2f} m est en dehors du profil calculé "
                    f"(X = {first:.2f} → {last:.2f} m)."
                )

        # Tirant d'eau mesuré depuis le fond de la zone d'écoulement (le bras choisi), pas
        # depuis le point le plus bas de tout le profil, qui peut se trouver dans l'autre bras.
        zone_points, _, _ = clip_to_bounds(section.points, bounds)
        if hydro_source == 'existing':
            z_ref = min(pt.z for pt in (zone_points or section.points))
        else:
            # Profil projet : depuis le fond du lit (cote d'ancrage) tant que ce fond est dans
            # la zone d'écoulement, sinon depuis le point le plus bas de la zone.
            bed_in_zone = bounds is None or (
                params.anchor_x < bounds[1] and params.anchor_x + params.bed_width > bounds[0]
            )
            z_ref = params.anchor_z if bed_in_zone or not zone_points else min(pt.z for pt in zone_points)

        # --- Moteur Hydraulique --- (fonction pure, cf. core.hydraulics.resolve_hydraulic_result :
        # aucune valeur ne peut "fuiter" d'un appel précédent, tout est recalculé depuis
        # hydro_data/section actuels à chaque appel)
        calc_mode = hydro_data.get('calc_mode', 'Q_FROM_H')
        slope = hydro_data.get('slope', 0.005)
        ks = hydro_data.get('ks_pro', 25.0)
        q_target = hydro_data.get('q_target', 15.0)
        h_eau = hydro_data.get('h_eau', 0.5)

        res = resolve_hydraulic_result(section, calc_mode, q_target, h_eau, z_ref, slope, ks, bounds)
        return HydraulicsSolution(
            section=section, hydro_source=hydro_source, zone=zone, bounds=bounds, z_ref=z_ref,
            calc_mode=calc_mode, slope=slope, ks=ks, q_target=q_target, res=res,
        )

    @staticmethod
    def overflow_diagnosis(solution: HydraulicsSolution) -> Optional[OverflowDiagnosis]:
        """Débordement hors du profil calculé (cf. OverflowDiagnosis), ou None. La capacité
        maximale sans débordement est jointe, pour situer la valeur saisie."""
        section, bounds, res = solution.section, solution.bounds, solution.res
        if solution.calc_mode == 'H_FROM_Q':
            if res["water_z"] is not None and target_discharge_reached(res["Q"], solution.q_target):
                return None
            kind, end_levels = TARGET_NOT_REACHED, {}
        else:
            sides = res.get("overflow_sides") or []
            if not sides:
                return None
            ends = free_end_levels(section, bounds)
            kind, end_levels = OVERFLOW, {side: ends[side] for side in sides}

        level = overflow_level(section, bounds)
        q_max = None
        if level is not None:
            q_max = compute_hydraulic_params(section, level, solution.slope, solution.ks, bounds)["Q"]
        return OverflowDiagnosis(kind=kind, level=level, q_max=q_max, end_levels=end_levels)

    def profile_overflows(self, existing_data: List[Dict[str, Any]],
                          project_params: Dict[str, Any]) -> Optional[bool]:
        """Le réglage hydraulique enregistré d'un profil fait-il déborder l'eau hors du
        profil (avertissement de l'onglet Hydraulique) ? None si ce n'est pas calculable :
        aucun réglage enregistré, profil source non renseigné ou zone incohérente."""
        saved = project_params or {}
        if 'calc_mode' not in saved:
            return None
        if saved.get('hydro_source', 'project') != 'existing' and saved.get('anchor_z') is None:
            return None
        data = {**self.default_project_params(), **saved}
        try:
            solved = self.solve_hydraulics(existing_data, data, data)
        except ValueError:
            return None
        if solved is None:
            return None
        return self.overflow_diagnosis(solved) is not None

    def scenario_summary(self, scenario_id: int, name: str,
                         states: List[Dict[str, Any]]) -> ScenarioSummary:
        """Chiffres clés d'un scénario (cf. core.project_summary), à partir de l'état de
        ses profils (format DatabaseManager.get_scenario_profile_states)."""
        summary = ScenarioSummary(scenario_id=scenario_id, name=name, n_profiles=len(states))
        if states:
            distances = [state["distance"] for state in states]
            summary.distance_range = (min(distances), max(distances))

        summary.n_complete = sum(
            1 for state in states
            if self.to_cross_section(state["existing_data"], name="Existant") is not None
            and (state["project_params"] or {}).get("anchor_z") is not None
        )

        stations = self.station_earthworks(states)
        computed = [s for s in stations if s.computed]
        summary.n_earthworks = len(computed)
        summary.cut_area = sum(s.cut for s in computed)
        summary.fill_area = sum(s.fill for s in computed)
        summary.cut_volume, summary.fill_volume = earthwork_volumes(stations)

        for state, station in zip(states, stations):
            overflows = self.profile_overflows(state["existing_data"], state["project_params"])
            if overflows is None:
                continue
            summary.n_hydraulics += 1
            if overflows:
                summary.overflow_names.append(station.name)
        return summary

    def project_summary(self, name: str, hard_points: List[Dict[str, Any]],
                        scenarios: List[Tuple[int, str, List[Dict[str, Any]]]]) -> ProjectSummary:
        """Récapitulatif d'un projet : ses deux familles de points durs (existants, projet)
        et leurs tronçons, et une ligne par scénario ((id, nom, états de ses profils), dans
        l'ordre d'affichage)."""
        points = [HardPoint.from_dict(p) for p in hard_points or []]
        markers = build_longitudinal_profile([], hard_points)
        return ProjectSummary(
            name=name,
            scenarios=[self.scenario_summary(sid, sname, states) for sid, sname, states in scenarios],
            hard_points=complete_points(of_family(points, EXISTING)),
            segments=markers.segments,
            project_hard_points=complete_points(of_family(points, PROJECT)),
            project_segments=markers.project_segments,
        )

    def to_cross_section(self, raw_data: List[Dict[str, Any]], name: str, allow_empty: bool = False) -> Optional[CrossSection]:
        """Profil en travers à partir des lignes du tableau (X, Z), ou None s'il a moins de
        MIN_SECTION_POINTS points (sauf avec `allow_empty`)."""
        points = dataframe_to_points(pd.DataFrame(raw_data))
        if not allow_empty and len(points) < self.MIN_SECTION_POINTS:
            return None
        return CrossSection(name=name, points=points)

    @staticmethod
    def to_project_parameters(project_data: Dict[str, Any]) -> ProjectParameters:
        """Paramètres du profil projet tirés d'un état enregistré (les clés inconnues, ex.
        celles de l'onglet Hydraulique ou d'anciennes versions, sont ignorées)."""
        valid_keys = ProjectParameters.__dataclass_fields__.keys()
        filtered = {k: v for k, v in project_data.items() if k in valid_keys}
        return ProjectParameters(**filtered)
