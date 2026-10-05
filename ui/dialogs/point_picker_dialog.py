# ui/dialogs/point_picker_dialog.py
from typing import List, Optional

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QListWidget, QDialogButtonBox, QLabel

from ui import theme


class PointPickerDialog(QDialog):
    """Choix d'un point parmi une liste (point d'ancrage, point de raccord...). Remplace
    QInputDialog.getItem, dont le menu déroulant est borné par la hauteur de l'écran et ne
    permet plus d'atteindre les derniers choix quand les points sont nombreux : ici la
    liste est toujours affichée dans la fenêtre, avec sa barre de défilement, et un double
    clic valide directement le point visé."""

    def __init__(self, parent=None, title: str = "Choisir un point", label: str = "Point :",
                 items: List[str] = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(380, 360)

        layout = QVBoxLayout(self)
        layout.setSpacing(theme.SPACE_MD)

        layout.addWidget(QLabel(label))

        self.list_widget = QListWidget()
        self.list_widget.addItems(items or [])
        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.list_widget, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_index(self) -> Optional[int]:
        """Position (dans la liste fournie) du point sélectionné, ou None si aucun."""
        row = self.list_widget.currentRow()
        return row if row >= 0 else None
