# ui/dialogs/hard_points_dialog.py
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QGroupBox, QLineEdit,
                              QDoubleSpinBox, QDialogButtonBox, QLabel)

from ui import theme


class HardPointsDialog(QDialog):
    """Dialogue de saisie/édition des deux points durs (amont/aval) d'un projet : chacun
    est un repère de terrain fixe, avec un nom et des coordonnées (PK, Z ; le PK est
    stocké sous la clé "x", seul le libellé affiché change). La distance 0
    des profils du projet correspond, par convention, à la position du point dur amont
    (rien ici ne calcule ou ne recale automatiquement cette distance à partir des
    coordonnées : ce sont deux informations indépendantes)."""

    def __init__(self, parent=None, upstream: dict = None, downstream: dict = None):
        super().__init__(parent)
        self.setWindowTitle("Points durs du projet")

        upstream = upstream or {}
        downstream = downstream or {}

        layout = QVBoxLayout(self)
        layout.setSpacing(theme.SPACE_MD)

        hint = QLabel(
            "Repères de terrain fixes du projet. La distance 0 des profils correspond, "
            "par convention, à la position du point dur amont."
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

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_group(self, layout: QVBoxLayout, title: str, values: dict):
        grp = QGroupBox(title)
        form = QFormLayout(grp)

        name_edit = QLineEdit(values.get("name") or "")

        x_spin = QDoubleSpinBox()
        x_spin.setRange(-1_000_000, 1_000_000)
        x_spin.setDecimals(3)
        x_spin.setValue(values.get("x") or 0.0)

        z_spin = QDoubleSpinBox()
        z_spin.setRange(-1_000_000, 1_000_000)
        z_spin.setDecimals(3)
        z_spin.setValue(values.get("z") or 0.0)

        form.addRow("Nom :", name_edit)
        form.addRow("PK (m) :", x_spin)
        form.addRow("Z (m NGF) :", z_spin)

        layout.addWidget(grp)
        return name_edit, x_spin, z_spin

    def get_values(self) -> dict:
        """Retourne {"upstream": {"name","x","z"}, "downstream": {...}}, prêt à être
        éclaté en arguments positionnels pour DatabaseManager.set_hard_points. Un nom
        laissé vide est renvoyé comme None plutôt que comme chaîne vide."""
        def _pack(name_edit, x_spin, z_spin):
            name = name_edit.text().strip()
            return {"name": name or None, "x": x_spin.value(), "z": z_spin.value()}

        return {
            "upstream": _pack(self.name_upstream, self.x_upstream, self.z_upstream),
            "downstream": _pack(self.name_downstream, self.x_downstream, self.z_downstream),
        }
