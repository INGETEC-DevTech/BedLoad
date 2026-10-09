# ui/dialogs/hard_points_dialog.py
from typing import Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
                             QHeaderView, QPushButton, QDialogButtonBox, QLabel, QAbstractItemView,
                             QComboBox, QMessageBox)

from core.hard_points import (EXISTING, FAMILIES, FAMILY_TYPES, PROJECT, HardPoint, complete_points,
                              format_slope, of_family, validate_hard_point_families)
from ui import theme

_MAX_ABS_VALUE = 1_000_000

COL_TYPE, COL_NAME, COL_PK, COL_Z, COL_SLOPE = range(5)


def _format_value(value: Optional[float]) -> str:
    """Valeur en base -> texte de cellule : vide si non renseignée, sinon jusqu'à 3
    décimales sans zéros inutiles (une valeur 0 réellement enregistrée s'affiche "0")."""
    if value is None:
        return ""
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _parse_value(text: str) -> Optional[float]:
    """Texte de cellule -> valeur : None si vide ; virgule ou point décimal. ValueError si
    ce n'est pas un nombre (ou hors de ±1 000 000)."""
    text = (text or "").strip()
    if not text:
        return None
    value = float(text.replace(",", "."))
    if abs(value) > _MAX_ABS_VALUE:
        raise ValueError(text)
    return value


class HardPointsDialog(QDialog):
    """Saisie/édition des points durs d'un projet (type, nom, PK, Z), communs à tous ses
    scénarios. Deux familles indépendantes, choisies dans la colonne « Type » : les points
    durs existants, le long du lit actuel, et les points durs projet, le long du nouveau lit
    (rivière déplacée ou reméandrée) ; un même ouvrage présent dans les deux lits est saisi
    deux fois. Dans chaque famille, le premier point (plus petit PK) est la référence
    « distance 0 » des profils le long de ce lit ; la pente de chaque tronçon entre deux
    points voisins de la même famille est affichée (m/m).

    Les erreurs (cf. core.hard_points.validate_hard_point_families) s'affichent pendant la
    saisie et bloquent la validation. `validator`, s'il est fourni, fait la vérification
    complète pour le projet (dont : un déplacement qui ferait sortir des profils existants
    de la zone couverte), sans rien enregistrer ; à défaut, seules les règles propres à la
    liste sont vérifiées."""

    def __init__(self, parent=None, points: Optional[List[Dict]] = None,
                 validator: Optional[Callable[[List[Dict]], List[str]]] = None):
        super().__init__(parent)
        self.setWindowTitle("Points durs du projet")
        self.setMinimumSize(700, 440)
        self._validator = validator
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setSpacing(theme.SPACE_MD)

        hint = QLabel(
            "Repères de terrain fixes du projet, communs à tous ses scénarios, en deux familles : "
            "« Existant » le long du lit actuel, « Projet » le long du nouveau lit (un même ouvrage "
            "présent dans les deux lits est saisi deux fois). Dans chaque famille, le premier point "
            "(plus petit PK) est la référence « distance 0 » des profils, et le Z doit baisser d'un "
            "point au suivant : la pente de chaque tronçon sert de pente hydraulique aux profils "
            "qu'il encadre, selon le lit sur lequel porte leur calcul."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(theme.qss("color: $TEXT_MUTED; font-size: ${FONT_SIZE_SM}px;"))
        layout.addWidget(hint)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Type", "Nom", "PK (m)", "Z (m NGF)", "Pente du tronçon aval (m/m)"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for col in (COL_TYPE, COL_PK, COL_Z, COL_SLOPE):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.table, 1)

        buttons_row = QHBoxLayout()
        self.btn_add = QPushButton("+ Ajouter un point")
        self.btn_remove = QPushButton("Supprimer le point")
        # Projets où le lit ne change pas : les points durs projet sont ceux du lit existant.
        self.btn_copy_to_project = QPushButton("Copier les points existants en projet")
        self.btn_copy_to_project.setToolTip(
            "Pour un projet où le lit ne change pas : les points durs projet deviennent une copie "
            "des points durs existants (ceux déjà saisis sont remplacés)."
        )
        buttons_row.addWidget(self.btn_add)
        buttons_row.addWidget(self.btn_remove)
        buttons_row.addStretch(1)
        buttons_row.addWidget(self.btn_copy_to_project)
        layout.addLayout(buttons_row)

        self.lbl_errors = QLabel()
        self.lbl_errors.setWordWrap(True)
        self.lbl_errors.setStyleSheet(theme.qss("color: $DANGER;"))
        layout.addWidget(self.lbl_errors)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.btn_add.clicked.connect(self.add_point)
        self.btn_remove.clicked.connect(self.remove_selected_point)
        self.btn_copy_to_project.clicked.connect(self.copy_existing_to_project)
        self.table.itemChanged.connect(lambda _item: self.refresh())

        self._loading = True
        for point in points or []:
            self._append_row(point)
        self._loading = False
        self.refresh()

    # --- Lignes ---

    def _append_row(self, point: Dict) -> int:
        # Signaux coupés le temps de créer les cellules : Qt signale une modification dès
        # la première, et la lecture du tableau tomberait sur des cellules pas encore créées.
        self.table.blockSignals(True)
        try:
            row = self.table.rowCount()
            self.table.insertRow(row)
            type_box = QComboBox()
            for family in FAMILIES:
                type_box.addItem(FAMILY_TYPES[family], family)
            type_box.setCurrentIndex(max(0, type_box.findData(point.get("family") or EXISTING)))
            type_box.currentIndexChanged.connect(lambda _index: self.refresh())
            self.table.setCellWidget(row, COL_TYPE, type_box)
            name_item = QTableWidgetItem(point.get("name") or "")
            name_item.setData(Qt.ItemDataRole.UserRole, point.get("id"))
            self.table.setItem(row, COL_NAME, name_item)
            self.table.setItem(row, COL_PK, QTableWidgetItem(_format_value(point.get("pk"))))
            self.table.setItem(row, COL_Z, QTableWidgetItem(_format_value(point.get("z"))))
            slope_item = QTableWidgetItem("")
            slope_item.setFlags(slope_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, COL_SLOPE, slope_item)
        finally:
            self.table.blockSignals(False)
        return row

    def _cell_text(self, row: int, col: int) -> str:
        item = self.table.item(row, col)
        return item.text() if item is not None else ""

    def _family(self, row: int) -> str:
        box = self.table.cellWidget(row, COL_TYPE)
        return box.currentData() if box is not None else EXISTING

    def set_family(self, row: int, family: str):
        """Choisit le type (EXISTING ou PROJECT) d'une ligne, comme dans sa liste."""
        box = self.table.cellWidget(row, COL_TYPE)
        box.setCurrentIndex(box.findData(family))

    def add_point(self):
        # Même type que la ligne sélectionnée : on saisit souvent plusieurs points d'un lit.
        current = self.table.currentRow()
        family = self._family(current) if current >= 0 else EXISTING
        row = self._append_row({"family": family})
        self.table.setCurrentCell(row, COL_NAME)
        self.table.editItem(self.table.item(row, COL_NAME))
        self.refresh()

    def remove_selected_point(self):
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
        self.refresh()

    def copy_existing_to_project(self):
        """Remplace les points durs projet par une copie des points durs existants (nouveaux
        points, à enregistrer avec le dialogue). Les points projet déjà saisis ne sont
        remplacés qu'après confirmation."""
        title = "Copier les points existants en projet"
        existing = [p for p in self._read_rows()[0] if p["family"] == EXISTING]
        if not existing:
            QMessageBox.information(self, title, "Aucun point dur existant à copier.")
            return
        project_rows = [row for row in range(self.table.rowCount()) if self._family(row) == PROJECT]
        if project_rows:
            count = len(project_rows)
            reply = QMessageBox.question(
                self, title,
                f"{count} point{'s' if count > 1 else ''} dur{'s' if count > 1 else ''} projet déjà "
                f"saisi{'s' if count > 1 else ''} {'seront remplacés' if count > 1 else 'sera remplacé'} "
                "par la copie des points durs existants. Continuer ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            for row in reversed(project_rows):
                self.table.removeRow(row)

        self._loading = True
        for point in existing:
            self._append_row({"name": point["name"], "pk": point["pk"], "z": point["z"], "family": PROJECT})
        self._loading = False
        self.refresh()

    # --- Lecture / validation ---

    def _read_rows(self) -> Tuple[List[Dict], List[str]]:
        """(points saisis, erreurs de format) ; une valeur illisible est comptée vide."""
        points, errors = [], []
        for row in range(self.table.rowCount()):
            name = self._cell_text(row, COL_NAME).strip() or None
            values = {}
            for key, col, label in (("pk", COL_PK, "PK"), ("z", COL_Z, "Z")):
                try:
                    values[key] = _parse_value(self._cell_text(row, col))
                except ValueError:
                    values[key] = None
                    errors.append(f"Ligne {row + 1} : le {label} « {self._cell_text(row, col)} » "
                                  "n'est pas un nombre.")
            name_item = self.table.item(row, COL_NAME)
            points.append({"id": name_item.data(Qt.ItemDataRole.UserRole) if name_item else None,
                           "name": name, "family": self._family(row), **values})
        return points, errors

    def get_points(self) -> List[Dict]:
        """Points saisis : [{"id" (None si nouveau), "name", "pk", "z", "family"}], prêts
        pour DatabaseManager.set_hard_points."""
        return self._read_rows()[0]

    def errors(self) -> List[str]:
        points, errors = self._read_rows()
        if self._validator is not None:
            errors += self._validator(points)
        else:
            errors += validate_hard_point_families([HardPoint.from_dict(p) for p in points])
        return errors

    def refresh(self):
        """Met à jour la pente affichée de chaque tronçon (entre points voisins d'une même
        famille), les erreurs et le bouton OK."""
        if self._loading:
            return
        points, _ = self._read_rows()
        hard_points = [HardPoint(name=p["name"], pk=p["pk"], z=p["z"], id=row, family=p["family"])
                       for row, p in enumerate(points)]
        slopes, complete_rows = {}, set()
        for family in FAMILIES:
            ordered = complete_points(of_family(hard_points, family))
            complete_rows |= {p.id for p in ordered}
            for a, b in zip(ordered, ordered[1:]):
                if b.pk != a.pk:
                    slopes[a.id] = format_slope((a.z - b.z) / (b.pk - a.pk)).replace(" m/m", "")

        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            slope_item = self.table.item(row, COL_SLOPE)
            if slope_item is not None:
                slope_item.setText(slopes.get(row, "—" if row in complete_rows else ""))
        self.table.blockSignals(False)

        errors = self.errors()
        self.lbl_errors.setText("\n".join(f"• {e}" for e in errors))
        self.lbl_errors.setVisible(bool(errors))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not errors)
