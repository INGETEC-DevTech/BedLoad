# core/controller.py
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
import plotly.graph_objects as go

from core.earthworks import compute_earthworks
from core.geometry import build_project_cross_section
from core.models import CrossSection, ProjectParameters, dataframe_to_points
from core.hydraulics import clip_to_bounds, resolve_hydraulic_result
from core.longitudinal import build_longitudinal_profile
from viz.plots import EXISTING_COLOR, PROJECT_COLOR, plot_overlay, plot_single_profile, plot_longitudinal_profile
from ui import theme

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
        hard_points: Optional[Dict[str, Dict[str, Optional[float]]]] = None,
    ) -> Optional[go.Figure]:
        """Construit le profil en long d'un scénario à partir des triplets
        (pk, min_z_existant, anchor_z_projet) renvoyés par DatabaseManager.get_longitudinal_data,
        et des points durs amont/aval (format DatabaseManager.get_hard_points)."""
        profile = build_longitudinal_profile(rows, hard_points)
        if (not profile.pk_existing and not profile.pk_project
                and profile.hard_point_upstream is None and profile.hard_point_downstream is None):
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
        bounds = self._calc_bounds(hydro_data)

        if hydro_source == 'existing':
            section = self._to_cross_section(existing_data, name="Existant")
            if section is None:
                return None
            # Tirant d'eau mesuré depuis le fond du lit de calcul (le point le plus bas
            # entre ses limites), pas depuis le point le plus bas de tout le profil, qui
            # peut se trouver dans un autre lit.
            bed_points, _, _ = clip_to_bounds(section.points, bounds)
            z_ref = min(pt.z for pt in (bed_points or section.points))
            color = EXISTING_COLOR
        else:
            params = self._to_project_parameters(project_data)
            section = build_project_cross_section(params, name="Projet")
            z_ref = params.anchor_z
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
                fig = plot_overlay(section, other_section, **water)
            else:
                other_section = self._to_cross_section(existing_data, name="Existant", allow_empty=True)
                fig = plot_overlay(other_section, section, **water)
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
            if bounds is not None:
                texte_resultats += "<br>" + discreet_line(
                    "Lit de calcul", f"X = {bounds[0]:.2f} → {bounds[1]:.2f} m"
                )

            fig.add_annotation(
                text=texte_resultats, align="left", showarrow=False,
                xref="paper", yref="paper", x=0.02, y=0.96, xanchor="left", yanchor="top",
                bgcolor="rgba(255, 255, 255, 0.95)", bordercolor=theme.BORDER,
                borderwidth=1, borderpad=14, font=dict(size=13, color=theme.TEXT_SECONDARY)
            )

        return fig

    @staticmethod
    def _calc_bounds(hydro_data: Dict[str, Any]) -> Optional[Tuple[float, float]]:
        """Limites (X gauche, X droite) du lit de calcul hydraulique, ou None si l'option
        n'est pas activée. Lève ValueError si elles sont incohérentes : MainWindow affiche
        alors le message à la place du graphique."""
        if not hydro_data.get('hydro_bounds_enabled'):
            return None
        x_left = float(hydro_data.get('hydro_x_left', 0.0))
        x_right = float(hydro_data.get('hydro_x_right', 0.0))
        if not x_left < x_right:
            raise ValueError(
                "Lit de calcul : le X gauche doit être strictement inférieur au X droite."
            )
        return x_left, x_right

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