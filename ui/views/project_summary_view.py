# ui/views/project_summary_view.py
"""Page "Récapitulatif du projet", affichée à la place des formulaires et du graphique
quand on clique sur un projet : une ligne de chiffres clés par scénario (cf.
core.project_summary), pour les comparer d'un coup d'œil."""
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QKeySequence
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QHeaderView, QLabel, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from core.hard_points import format_slope
from core.project_summary import ProjectSummary, ScenarioSummary
from ui import theme

_NOT_AVAILABLE = "—"

COLUMNS = [
    ("Scénario", None),
    ("Profils", "Nombre de profils du scénario."),
    ("Complets", "Profils dont le terrain existant (au moins 2 points) et le profil projet "
                 "sont renseignés."),
    ("Linéaire\n(m)", "Distances du premier et du dernier profil."),
    ("Déblai Σ\n(m²)", "Somme des surfaces de déblai en coupe des profils calculés (comme la "
                      "légende du profil en long)."),
    ("Remblai Σ\n(m²)", "Somme des surfaces de remblai en coupe des profils calculés."),
    ("Bilan Σ\n(m²)", "Déblai − remblai : positif = excédent de matériaux, négatif = apport."),
    ("Déblai\n(m³)", "Volume par la méthode des moyennes des aires : entre deux profils calculés "
                    "consécutifs, surface moyenne × distance qui les sépare. Rien n'est compté "
                    "au-delà du premier et du dernier profil calculés."),
    ("Remblai\n(m³)", "Volume de remblai, même méthode."),
    ("Bilan\n(m³)", "Déblai − remblai, en volume."),
    ("Débordements", "Profils dont le réglage de l'onglet Hydraulique fait déborder l'eau hors "
                     "du profil (ou n'atteint pas le débit cible)."),
]


class _SortableItem(QTableWidgetItem):
    """Cellule triée selon une clé numérique (et non selon son texte affiché, où "10"
    passerait avant "9"). Sans clé (valeur non disponible), elle se range en dernier."""

    def __init__(self, text: str, sort_key=None):
        super().__init__(text)
        self.sort_key = sort_key
        self.setFlags(self.flags() & ~Qt.ItemFlag.ItemIsEditable)

    def __lt__(self, other):
        if isinstance(other, _SortableItem):
            if self.sort_key is None or other.sort_key is None:
                return other.sort_key is None and self.sort_key is not None
            return self.sort_key < other.sort_key
        return super().__lt__(other)


def _number(value: Optional[float], decimals: int, signed: bool = False) -> _SortableItem:
    if value is None:
        item = _SortableItem(_NOT_AVAILABLE)
    else:
        text = f"{value:+.{decimals}f}" if signed else f"{value:.{decimals}f}"
        item = _SortableItem(text, value)
    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


class _SummaryTable(QTableWidget):
    """Tableau en lecture seule ; Ctrl+C copie la sélection (avec les en-têtes) pour Excel."""

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection_to_clipboard()
            return
        super().keyPressEvent(event)

    def copy_selection_to_clipboard(self):
        indexes = self.selectedIndexes()
        if not indexes:
            return
        rows = sorted({idx.row() for idx in indexes})
        cols = sorted({idx.column() for idx in indexes})
        # En-têtes sur une ligne : leur retour à la ligne (unité) casserait le collage.
        lines = ['\t'.join(self.horizontalHeaderItem(c).text().replace("\n", " ") for c in cols)]
        for r in rows:
            lines.append('\t'.join(self.item(r, c).text() if self.item(r, c) else "" for c in cols))
        QApplication.clipboard().setText('\n'.join(lines))


class ProjectSummaryView(QWidget):
    # Double-clic sur un scénario : MainWindow le sélectionne (profil en long).
    scenario_activated = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE_XL, theme.SPACE_XL, theme.SPACE_XL, theme.SPACE_XL)
        layout.setSpacing(theme.SPACE_SM)

        self.lbl_title = QLabel()
        self.lbl_title.setStyleSheet(theme.qss(
            "font-size: 18px; font-weight: bold; color: $TEXT_PRIMARY;"
        ))
        layout.addWidget(self.lbl_title)

        self.lbl_subtitle = QLabel()
        self.lbl_subtitle.setWordWrap(True)
        self.lbl_subtitle.setStyleSheet(theme.qss(
            "font-size: ${FONT_SIZE_BASE}px; color: $TEXT_SECONDARY;"
        ))
        layout.addWidget(self.lbl_subtitle)

        self.lbl_segments = QLabel()
        self.lbl_segments.setWordWrap(True)
        self.lbl_segments.setStyleSheet(theme.qss(
            "font-size: ${FONT_SIZE_BASE}px; color: $TEXT_SECONDARY;"
        ))
        layout.addWidget(self.lbl_segments)
        layout.addSpacing(theme.SPACE_MD)

        self.table = _SummaryTable(0, len(COLUMNS))
        for col, (label, tooltip) in enumerate(COLUMNS):
            header = QTableWidgetItem(label)
            if tooltip:
                header.setToolTip(tooltip)
            self.table.setHorizontalHeaderItem(col, header)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        # Colonnes de chiffres réparties sur toute la largeur (pas de défilement horizontal),
        # celles des noms et des débordements (en-tête d'un seul mot) ajustées à leur contenu.
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for col in (0, len(COLUMNS) - 1):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.cellDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.table)

        self.lbl_empty = QLabel("Ce projet n'a pas encore de scénario.")
        self.lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.setStyleSheet(theme.qss(
            "font-size: ${FONT_SIZE_TITLE}px; color: $TEXT_MUTED;"
        ))
        layout.addWidget(self.lbl_empty, 1)

        self.lbl_hint = QLabel(
            "Double-cliquez sur un scénario pour ouvrir son profil en long. "
            "Survolez un en-tête de colonne pour le détail du calcul ; Ctrl+C copie la sélection."
        )
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet(theme.qss(
            "font-size: ${FONT_SIZE_SM}px; color: $TEXT_MUTED; padding-top: ${SPACE_SM}px;"
        ))
        layout.addWidget(self.lbl_hint)
        layout.addStretch(1)

    def set_summary(self, summary: ProjectSummary):
        self.lbl_title.setText(f"Projet « {summary.name} »")

        n = len(summary.scenarios)
        parts = [f"{n} scénario{'s' if n > 1 else ''}"]
        points = summary.hard_points
        if points:
            parts.append(f"{len(points)} point{'s' if len(points) > 1 else ''} dur{'s' if len(points) > 1 else ''} "
                         f"(PK {points[0].pk:g} → {points[-1].pk:g})")
        else:
            parts.append("aucun point dur complet")
        self.lbl_subtitle.setText(" · ".join(parts))

        if summary.segments:
            slopes = " / ".join(format_slope(s.slope) for s in summary.segments)
            self.lbl_segments.setText(f"Pentes des tronçons entre points durs : I = {slopes}")
        else:
            self.lbl_segments.setText("")
        self.lbl_segments.setVisible(bool(summary.segments))

        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for scenario in summary.scenarios:
            self._append_row(scenario)
        # Ordre d'affichage par défaut : celui des scénarios (création). L'indicateur de tri
        # est levé AVANT d'activer le tri, qui sinon trierait aussitôt selon la 1re colonne
        # (ou le dernier tri choisi).
        self.table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.table.setSortingEnabled(True)

        self._fit_table_height()
        self.table.setVisible(n > 0)
        self.lbl_hint.setVisible(n > 0)
        self.lbl_empty.setVisible(n == 0)

    def _fit_table_height(self):
        """Tableau à la hauteur de ses lignes (sans grand vide en dessous), plafonnée :
        au-delà d'une quinzaine de scénarios, il défile."""
        self.table.resizeRowsToContents()
        rows = sum(self.table.rowHeight(r) for r in range(min(self.table.rowCount(), 15)))
        frame = 2 * self.table.frameWidth()
        self.table.setFixedHeight(self.table.horizontalHeader().sizeHint().height() + rows + frame)

    def _append_row(self, s: ScenarioSummary):
        row = self.table.rowCount()
        self.table.insertRow(row)

        name = _SortableItem(s.name, s.name.lower())
        name.setData(Qt.ItemDataRole.UserRole, s.scenario_id)
        self.table.setItem(row, 0, name)
        self.table.setItem(row, 1, _number(s.n_profiles, 0))

        complete = _SortableItem(f"{s.n_complete}/{s.n_profiles}", s.n_complete)
        complete.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if s.n_complete < s.n_profiles:
            complete.setForeground(QColor(theme.WARNING))
        self.table.setItem(row, 2, complete)

        if s.distance_range is None:
            extent = _SortableItem(_NOT_AVAILABLE)
        else:
            start, end = s.distance_range
            extent = _SortableItem(f"{start:g} → {end:g}", end - start)
        extent.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 3, extent)

        has_areas = s.n_earthworks > 0
        self.table.setItem(row, 4, _number(s.cut_area if has_areas else None, 2))
        self.table.setItem(row, 5, _number(s.fill_area if has_areas else None, 2))
        self.table.setItem(row, 6, _number(s.area_balance if has_areas else None, 2, signed=True))
        self.table.setItem(row, 7, _number(s.cut_volume, 1))
        self.table.setItem(row, 8, _number(s.fill_volume, 1))
        self.table.setItem(row, 9, _number(s.volume_balance, 1, signed=True))
        if s.n_earthworks < s.n_profiles:
            note = (f"{s.n_earthworks} profil{'s' if s.n_earthworks > 1 else ''} calculé"
                    f"{'s' if s.n_earthworks > 1 else ''} sur {s.n_profiles} (les autres n'ont "
                    "pas d'existant ou de projet renseigné).")
            for col in range(4, 10):
                self.table.item(row, col).setToolTip(note)

        self.table.setItem(row, 10, self._overflow_item(s))

    @staticmethod
    def _overflow_item(s: ScenarioSummary) -> _SortableItem:
        if s.n_hydraulics == 0:
            item = _SortableItem(_NOT_AVAILABLE)
            item.setToolTip("Aucun profil n'a de réglage hydraulique calculable.")
        else:
            count = len(s.overflow_names)
            item = _SortableItem(f"{count} ⚠" if count else "0", count)
            lines = []
            if count:
                item.setForeground(QColor(theme.WARNING))
                lines.append("Débordement : " + ", ".join(s.overflow_names))
            if s.n_hydraulics < s.n_profiles:
                lines.append(f"{s.n_hydraulics} profil{'s' if s.n_hydraulics > 1 else ''} "
                             f"contrôlé{'s' if s.n_hydraulics > 1 else ''} sur {s.n_profiles} "
                             "(les autres n'ont pas de réglage hydraulique calculable).")
            item.setToolTip("\n".join(lines))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item

    def _on_double_click(self, row: int, _col: int):
        item = self.table.item(row, 0)
        if item is not None:
            self.scenario_activated.emit(item.data(Qt.ItemDataRole.UserRole))
