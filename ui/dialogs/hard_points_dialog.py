# ui/dialogs/hard_points_dialog.py
from typing import Optional

from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QGroupBox, QLineEdit,
                              QDialogButtonBox, QLabel)

from ui import theme

# Nombre signé, au plus 3 décimales, séparateur point ou virgule ; vide autorisé (= non
# renseigné). Mêmes bornes et précision que les anciennes saisies (±1 000 000, 3 décimales).
_NUMBER_PATTERN = QRegularExpression(r"^-?\d{0,7}([.,]\d{0,3})?$")
_MAX_ABS_VALUE = 1_000_000


def _format_value(value: Optional[float]) -> str:
    """Valeur en base -> texte du champ : vide si non renseignée, sinon jusqu'à 3 décimales
    sans zéros inutiles (une valeur 0 réellement enregistrée s'affiche bien "0")."""
    if value is None:
        return ""
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _parse_value(text: str) -> Optional[float]:
    """Texte du champ -> valeur à enregistrer : None si vide. Lève ValueError si le texte
    n'est pas (encore) un nombre complet, ex. "-" seul."""
    text = text.strip()
    if not text:
        return None
    value = float(text.replace(",", "."))
    if abs(value) > _MAX_ABS_VALUE:
        raise ValueError(text)
    return value


class HardPointsDialog(QDialog):
    """Dialogue de saisie/édition des deux points durs (amont/aval) d'un projet : chacun
    est un repère de terrain fixe, avec un nom et des coordonnées (PK, Z ; le PK est
    stocké sous la clé "x", seul le libellé affiché change). La distance 0
    des profils du projet correspond, par convention, à la position du point dur amont
    (rien ici ne calcule ou ne recale automatiquement cette distance à partir des
    coordonnées : ce sont deux informations indépendantes).

    PK et Z sont des champs texte et non des QDoubleSpinBox : un spinbox ne peut pas être
    vide et enregistrait 0 pour un champ jamais rempli, faisant apparaître un point dur
    fantôme à Z = 0 sur le profil en long. Un champ vide est enregistré "non renseigné"
    (None) ; un point dur incomplet n'est alors pas tracé (cf. build_longitudinal_profile)."""

    def __init__(self, parent=None, upstream: dict = None, downstream: dict = None):
        super().__init__(parent)
        self.setWindowTitle("Points durs du projet")

        upstream = upstream or {}
        downstream = downstream or {}

        layout = QVBoxLayout(self)
        layout.setSpacing(theme.SPACE_MD)

        hint = QLabel(
            "Repères de terrain fixes du projet. La distance 0 des profils correspond, "
            "par convention, à la position du point dur amont. Un champ laissé vide est "
            "enregistré comme non renseigné."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(theme.qss("color: $TEXT_MUTED; font-size: ${FONT_SIZE_SM}px;"))
        layout.addWidget(hint)

        self.name_upstream, self.x_upstream, self.z_upstream = self._add_group(
            layout, "Point dur amont", upstream
        )
        self.name_downstream, self.x_downstream, self.z_downstream = self._add_group(
            layout, "Point dur aval", downstream
        )

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        for edit in self._number_edits():
            edit.textChanged.connect(self._update_ok_button)
        self._update_ok_button()

    def _number_edits(self):
        return (self.x_upstream, self.z_upstream, self.x_downstream, self.z_downstream)

    def _make_number_edit(self, value: Optional[float]) -> QLineEdit:
        edit = QLineEdit(_format_value(value))
        edit.setValidator(QRegularExpressionValidator(_NUMBER_PATTERN, edit))
        edit.setPlaceholderText("non renseigné")
        return edit

    def _add_group(self, layout: QVBoxLayout, title: str, values: dict):
        grp = QGroupBox(title)
        form = QFormLayout(grp)

        name_edit = QLineEdit(values.get("name") or "")
        x_edit = self._make_number_edit(values.get("x"))
        z_edit = self._make_number_edit(values.get("z"))

        form.addRow("Nom :", name_edit)
        form.addRow("PK (m) :", x_edit)
        form.addRow("Z (m NGF) :", z_edit)

        layout.addWidget(grp)
        return name_edit, x_edit, z_edit

    def _update_ok_button(self, _=None):
        """OK n'est actif que si chaque champ numérique est vide ou contient un nombre
        complet (le validateur laisse passer les saisies en cours comme "-" ou "12,")."""
        valid = True
        for edit in self._number_edits():
            try:
                _parse_value(edit.text())
            except ValueError:
                valid = False
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid)

    def get_values(self) -> dict:
        """Retourne {"upstream": {"name","x","z"}, "downstream": {...}}, prêt à être
        éclaté en arguments positionnels pour DatabaseManager.set_hard_points. Un nom ou
        une coordonnée laissés vides sont renvoyés comme None (non renseignés)."""
        def _pack(name_edit, x_edit, z_edit):
            name = name_edit.text().strip()
            return {"name": name or None, "x": _parse_value(x_edit.text()), "z": _parse_value(z_edit.text())}

        return {
            "upstream": _pack(self.name_upstream, self.x_upstream, self.z_upstream),
            "downstream": _pack(self.name_downstream, self.x_downstream, self.z_downstream),
        }
