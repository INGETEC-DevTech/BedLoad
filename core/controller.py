# core/controller.py
from __future__ import annotations
import math
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
import plotly.graph_objects as go

from core.earthworks import compute_earthworks
from core.geometry import build_project_cross_section
from core.models import CrossSection, ProjectParameters, dataframe_to_points
from core.hydraulics import (clip_to_bounds, compute_hydraulic_params, free_end_levels,
                             overflow_level, resolve_hydraulic_result)
from core.longitudinal import build_longitudinal_profile
from viz.plots import EXISTING_COLOR, PROJECT_COLOR, plot_overlay, plot_single_profile, plot_longitudinal_profile
from ui import theme

# Avertissement "l'eau déborderait hors du profil" (orange, comme une alerte non bloquante).
OVERFLOW_WARNING_COLOR = "#b45309"
OVERFLOW_WARNING_BACKGROUND = "rgba(255, 247, 237, 0.97)"

# Zones d'écoulement du calcul hydraulique (cf. ProjectParameters.hydro_zone).
ALL_ZONE = "all"
LEFT_ARM = "left_arm"
RIGHT_ARM = "right_arm"
CUSTOM_ZONE = "custom"


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


class ViewMode(Enum):
    EXISTING = "existing"
    PROJECT = "project"
    HYDRAULICS = "hydraulics"

class ProfileController:
    MIN_POINTS_FOR_PLOT = 2

    def build_figure(
        self,
        existing_data: List[Dict[str, Any]],
        project_data: Dict[str, Any],
        mode: ViewMode,
        show_overlay: bool = False,
    ) -> Optional[go.Figure]:

        if mode is ViewMode.EXISTING:
            return self._build_existing_figure(existing_data)
        if mode is ViewMode.HYDRAULICS:
            return self._build_hydraulics_figure(existing_data, project_data, project_data, show_overlay)
        return self._build_project_figure(existing_data, project_data, show_overlay)

    @staticmethod
    def default_project_params() -> Dict[str, Any]:
        return vars(ProjectParameters())

    def build_longitudinal_figure(
        self, rows: List[Tuple[float, Optional[float], Optional[float]]],
        hard_points: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[go.Figure]:
        """Construit le profil en long d'un scénario à partir des triplets
        (distance, min_z_existant, anchor_z_projet) renvoyés par
        DatabaseManager.get_longitudinal_data, et des points durs du projet (format
        DatabaseManager.get_hard_points)."""
        profile = build_longitudinal_profile(rows, hard_points)
        if not profile.pk_existing and not profile.pk_project and not profile.hard_points:
            return None
        return plot_longitudinal_profile(profile)

    def _build_existing_figure(self, existing_data: List[Dict[str, Any]]) -> Optional[go.Figure]:
        section = self._to_cross_section(existing_data, name="Existant")
        if section is None:
            return None
        return plot_single_profile(section, color=EXISTING_COLOR)

    def _build_project_figure(
        self,
        existing_data: List[Dict[str, Any]],
        project_data: Dict[str, Any],
        show_overlay: bool,
    ) -> go.Figure:
        """Éditeur de géométrie pure : aucun calcul hydraulique ni annotation de résultats
        (ceux-ci vivent désormais dans l'onglet Hydraulique, cf. _build_hydraulics_figure)."""

        params = self._to_project_parameters(project_data)
        section_proj = build_project_cross_section(params, name="Projet")

        if show_overlay:
            section_ext = self._to_cross_section(existing_data, name="Existant", allow_empty=True)
            # Les deux profils affichés ensemble : on montre aussi ce qu'il faut enlever
            # (déblai) ou ajouter (remblai) pour passer de l'un à l'autre, par zone.
            earthworks = (compute_earthworks(section_ext, section_proj)
                          if len(section_ext.points) >= self.MIN_POINTS_FOR_PLOT else None)
            return plot_overlay(section_ext, section_proj, earthworks=earthworks)
        return plot_single_profile(section_proj, color=PROJECT_COLOR)

    def _build_hydraulics_figure(
        self,
        existing_data: List[Dict[str, Any]],
        project_data: Dict[str, Any],
        hydro_data: Dict[str, Any],
        show_overlay: bool,
    ) -> Optional[go.Figure]:
        hydro_source = hydro_data.get('hydro_source', 'project')
        zone, bounds = flow_zone_bounds(hydro_data)

        if hydro_source == 'existing':
            section = self._to_cross_section(existing_data, name="Existant")
            if section is None:
                return None
        else:
            params = self._to_project_parameters(project_data)
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
            color = EXISTING_COLOR
        else:
            # Profil projet : depuis le fond du lit (cote d'ancrage) tant que ce fond est dans
            # la zone d'écoulement, sinon depuis le point le plus bas de la zone.
            bed_in_zone = bounds is None or (
                params.anchor_x < bounds[1] and params.anchor_x + params.bed_width > bounds[0]
            )
            z_ref = params.anchor_z if bed_in_zone or not zone_points else min(pt.z for pt in zone_points)
            color = PROJECT_COLOR

        # --- Moteur Hydraulique --- (fonction pure, cf. core.hydraulics.resolve_hydraulic_result :
        # aucune valeur ne peut "fuiter" d'un appel précédent, tout est recalculé depuis
        # hydro_data/section actuels à chaque appel de _build_hydraulics_figure)
        calc_mode = hydro_data.get('calc_mode', 'Q_FROM_H')
        slope = hydro_data.get('slope', 0.005)
        ks = hydro_data.get('ks_pro', 25.0)
        q_target = hydro_data.get('q_target', 15.0)
        h_eau = hydro_data.get('h_eau', 0.5)

        res = resolve_hydraulic_result(section, calc_mode, q_target, h_eau, z_ref, slope, ks, bounds)
        water = dict(water_level=res["water_z"], water_intervals=res["wet_intervals"], calc_bounds=bounds)

        # --- Génération de la figure ---
        if show_overlay:
            # L'AUTRE profil (existant si la source est le projet, et vice-versa) est
            # superposé en fond. plot_overlay colore son 1er argument en "existant" (vert)
            # et son 2e en "projet" (violet), quel que soit le rôle qu'il joue ici.
            if hydro_source == 'existing':
                other_params = self._to_project_parameters(project_data)
                other_section = build_project_cross_section(other_params, name="Projet")
                fig = plot_overlay(section, other_section, frame_all=True, **water)
            else:
                other_section = self._to_cross_section(existing_data, name="Existant", allow_empty=True)
                fig = plot_overlay(other_section, section, frame_all=True, **water)
        else:
            fig = plot_single_profile(section, color=color, **water)

        # --- Incrustation des résultats ---
        if res["S"] > 0:
            h_relative = res["water_z"] - z_ref
            is_h_calculated = calc_mode == 'H_FROM_Q'

            def highlighted_line(label: str, value_str: str) -> str:
                # La grandeur calculée : toute la ligne en gras et en couleur d'accent,
                # pour qu'on repère d'un coup d'œil LE résultat qui bouge avec la saisie.
                return f'<span style="color:{theme.PRIMARY}"><b>{label} : {value_str} [Calculé]</b></span>'

            def discreet_line(label: str, value_str: str, tag: Optional[str] = None) -> str:
                line = f"<b>{label} :</b> {value_str}"
                return f"{line} <i>[{tag}]</i>" if tag else line

            q_line = (
                discreet_line("Débit (Q)", f"{res['Q']:.2f} m³/s", "Saisi")
                if is_h_calculated
                else highlighted_line("Débit (Q)", f"{res['Q']:.2f} m³/s")
            )
            h_line = (
                highlighted_line("Tirant d'eau (h)", f"{h_relative:.2f} m")
                if is_h_calculated
                else discreet_line("Tirant d'eau (h)", f"{h_relative:.2f} m", "Saisi")
            )

            v_line = discreet_line("Vitesse moyenne (V)", f"{res['V']:.2f} m/s")
            s_line = discreet_line("Surface mouillée (S)", f"{res['S']:.2f} m²")

            texte_resultats = (
                f'<span style="color:{theme.TEXT_PRIMARY}"><b>Résultats hydrauliques</b></span><br><br>'
                f"{q_line}<br>{v_line}<br>{s_line}<br>{h_line}"
            )
            zone_label = None
            if zone == LEFT_ARM:
                zone_label = f"bras gauche seul (X < {bounds[1]:.2f} m)"
            elif zone == RIGHT_ARM:
                zone_label = f"bras droit seul (X > {bounds[0]:.2f} m)"
            elif zone == CUSTOM_ZONE:
                zone_label = f"X = {bounds[0]:.2f} → {bounds[1]:.2f} m"
            if zone_label:
                texte_resultats += "<br>" + discreet_line("Zone d'écoulement", zone_label)

            # Plusieurs zones en eau (typiquement les deux bras) : répartition du débit,
            # chacune avec son propre rayon hydraulique (cf. compute_hydraulic_params).
            if len(res["wet_intervals"]) > 1:
                texte_resultats += "<br><b>Répartition du débit :</b>"
                for (x0, x1), q in zip(res["wet_intervals"], res["bed_discharges"]):
                    share = 100 * q / res["Q"] if res["Q"] else 0
                    texte_resultats += f"<br>&nbsp;&nbsp;• X {x0:.2f} → {x1:.2f} m : {q:.2f} m³/s ({share:.0f} %)"

            fig.add_annotation(
                text=texte_resultats, align="left", showarrow=False,
                xref="paper", yref="paper", x=0.02, y=0.96, xanchor="left", yanchor="top",
                bgcolor="rgba(255, 255, 255, 0.95)", bordercolor=theme.BORDER,
                borderwidth=1, borderpad=14, font=dict(size=13, color=theme.TEXT_SECONDARY)
            )

        # --- Avertissement de débordement --- (affiché même sans résultat : c'est justement
        # le cas où tout le lit a été ignoré et Q vaut 0)
        warning = self._overflow_warning(section, bounds, res, calc_mode, q_target, slope, ks)
        if warning:
            fig.add_annotation(
                text=warning, align="left", showarrow=False,
                xref="paper", yref="paper", x=0.02, y=0.03, xanchor="left", yanchor="bottom",
                bgcolor=OVERFLOW_WARNING_BACKGROUND, bordercolor=OVERFLOW_WARNING_COLOR,
                borderwidth=1, borderpad=10, font=dict(size=12, color=OVERFLOW_WARNING_COLOR),
            )

        return fig

    @staticmethod
    def _overflow_warning(section, bounds, res: Dict[str, Any], calc_mode: str,
                          q_target: float, slope: float, ks: float) -> Optional[str]:
        """Message à afficher quand l'eau déborderait hors du profil calculé (débordement
        non modélisé), ou None :
        - "Imposer H" : la cote d'eau saisie dépasse une extrémité libre du profil ;
        - "Imposer Q" : le débit cible n'est pas atteint, la cote d'eau étant plafonnée
          (la dichotomie ne peut pas monter au-dessus du profil sans débordement).
        Le message rappelle la capacité maximale sans débordement, pour situer la valeur
        saisie."""
        level = overflow_level(section, bounds)
        capacity = ""
        if level is not None:
            q_max = compute_hydraulic_params(section, level, slope, ks, bounds)["Q"]
            capacity = (f"<br>Capacité maximale sans débordement : Q = {q_max:.2f} m³/s "
                        f"(cote Z = {level:.2f} m NGF).")

        if calc_mode == 'H_FROM_Q':
            if res["water_z"] is not None and abs(res["Q"] - q_target) < 0.01:
                return None
            reason = (
                "l'eau déborderait hors du profil (débordement non modélisé)."
                if level is not None else
                "la cote d'eau est plafonnée au sommet du profil calculé."
            )
            return (
                f"<b>⚠ Débit cible non atteint</b> : {q_target:.2f} m³/s demandés, "
                f"{res['Q']:.2f} m³/s calculés —<br>{reason}{capacity}"
            )

        sides = res.get("overflow_sides") or []
        if not sides:
            return None
        side_label = {"left": "gauche", "right": "droite"}
        ends = free_end_levels(section, bounds)
        details = " et ".join(f"{side_label[side]} (Z = {ends[side]:.2f} m NGF)" for side in sides)
        return (
            f"<b>⚠ Débordement</b> : la cote d'eau (Z = {res['water_z']:.2f} m NGF) dépasse "
            f"l'extrémité {details} du profil.<br>"
            "L'eau déborderait hors du profil levé : non modélisé, le lit concerné est exclu "
            f"du calcul.{capacity}"
        )

    def _to_cross_section(self, raw_data: List[Dict[str, Any]], name: str, allow_empty: bool = False) -> Optional[CrossSection]:
        points = dataframe_to_points(pd.DataFrame(raw_data))
        if not allow_empty and len(points) < self.MIN_POINTS_FOR_PLOT:
            return None
        return CrossSection(name=name, points=points)

    @staticmethod
    def _to_project_parameters(project_data: Dict[str, Any]) -> ProjectParameters:
        valid_keys = ProjectParameters.__dataclass_fields__.keys()
        filtered = {k: v for k, v in project_data.items() if k in valid_keys}
        return ProjectParameters(**filtered)