# tools/make_splash.py
"""Génère assets/splash.png, l'image de l'écran de démarrage de l'exe : logo INGETEC et
nom « BedLoad » sur fond blanc. Le bas de l'image est laissé libre pour le texte d'étape
(« Chargement… »), que PyInstaller écrit par-dessus (cf. ui/splash_screen.py pour la
mise en page partagée, et HydroTopo_V2.spec).

L'image est versionnée : ce script n'est à relancer qu'après un changement de logo, de
nom ou de couleurs du thème, depuis le dossier de l'application :
    python tools/make_splash.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPen  # noqa: E402

from core.utils import ASSETS_DIR_NAME, LOGO_FILE_NAME  # noqa: E402
from ui import splash_screen, theme  # noqa: E402
from ui.views.home_view import APP_NAME  # noqa: E402

OUTPUT = ROOT / ASSETS_DIR_NAME / "splash.png"
_LOGO_HEIGHT = 30
_TITLE_SIZE_PX = 40
_ACCENT_HEIGHT = 4


def _edge_colors(logo: QImage):
    """Couleurs moyennes des bords gauche et droit du logo (bleu → vert), pour le filet
    d'accent en haut de l'image : il reprend le dégradé du logo plutôt qu'une couleur
    d'interface."""
    def average(x_start, x_end):
        total, count = [0, 0, 0], 0
        for x in range(x_start, x_end):
            for y in range(logo.height()):
                color = logo.pixelColor(x, y)
                if color.alpha() > 200:
                    total[0] += color.red()
                    total[1] += color.green()
                    total[2] += color.blue()
                    count += 1
        return QColor(*(round(c / count) for c in total))

    band = max(1, logo.width() // 8)
    return average(0, band), average(logo.width() - band, logo.width())


def render() -> QImage:
    width, height = splash_screen.IMAGE_SIZE
    margin = splash_screen.MARGIN
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(theme.SURFACE))

    logo = QImage(str(ROOT / ASSETS_DIR_NAME / LOGO_FILE_NAME))
    if logo.isNull():
        raise SystemExit(f"Logo introuvable : {ROOT / ASSETS_DIR_NAME / LOGO_FILE_NAME}")

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    # Filet d'accent aux couleurs du logo, puis cadre : la fenêtre n'a pas de bordure, et
    # un fond blanc se perdrait sur un bureau clair.
    left_color, right_color = _edge_colors(logo)
    gradient = QLinearGradient(QPointF(0, 0), QPointF(width, 0))
    gradient.setColorAt(0, left_color)
    gradient.setColorAt(1, right_color)
    painter.fillRect(QRectF(0, 0, width, _ACCENT_HEIGHT), gradient)
    painter.setPen(QPen(QColor(theme.BORDER_INPUT)))
    painter.drawRect(QRectF(0.5, 0.5, width - 1, height - 1))

    logo_width = logo.width() * _LOGO_HEIGHT / logo.height()
    logo_top = 56
    painter.drawImage(QRectF(margin, logo_top, logo_width, _LOGO_HEIGHT), logo)

    title_font = QFont("Segoe UI")
    title_font.setPixelSize(_TITLE_SIZE_PX)
    title_font.setWeight(QFont.Weight.Bold)
    painter.setFont(title_font)
    painter.setPen(QColor(theme.TEXT_PRIMARY))
    title_top = logo_top + _LOGO_HEIGHT + 24
    painter.drawText(
        QRectF(margin, title_top, width - 2 * margin, _TITLE_SIZE_PX * 1.4),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, APP_NAME,
    )

    # Filet discret au-dessus de la zone du texte d'étape (laissée vide ici).
    text_x, text_bottom = splash_screen.TEXT_POS
    rule_y = text_bottom - splash_screen.TEXT_SIZE_PX - 28 + 0.5
    painter.setPen(QPen(QColor(theme.BORDER)))
    painter.drawLine(QPointF(margin, rule_y), QPointF(width - margin, rule_y))
    painter.end()
    return image


def main():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)  # noqa: F841 (polices)
    image = render()
    if not image.save(str(OUTPUT)):
        raise SystemExit(f"Impossible d'écrire {OUTPUT}")
    print(f"{OUTPUT} ({image.width()} x {image.height()} px)")


if __name__ == "__main__":
    main()
