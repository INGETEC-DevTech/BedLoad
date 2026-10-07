# ui/splash_screen.py
"""Écran de démarrage de l'exe : image fixe (assets/splash.png) affichée par le bootloader
de PyInstaller dès le double-clic, pendant l'extraction et le chargement, avec une ligne de
texte d'étape (cf. HydroTopo_V2.spec). Ce module en pilote le texte et la fermeture.
Lancée depuis les sources (python app.py), l'application n'a pas d'écran de démarrage : ces
fonctions ne font alors rien.

Volontairement sans import de Qt : app.py l'utilise avant de charger les gros modules
(PyQt6, WebEngine, plotly, pandas), qui prennent à eux seuls plusieurs secondes.

Les constantes de mise en page sont partagées par le .spec (position du texte) et par
tools/make_splash.py (qui dessine l'image en laissant cette zone libre)."""
import sys

try:
    # Fourni par PyInstaller, uniquement dans un exe construit avec un écran de démarrage.
    import pyi_splash
except ImportError:
    pyi_splash = None

# Image (px) et zone du texte d'étape : coin inférieur gauche du texte, hauteur en px.
IMAGE_SIZE = (520, 300)
MARGIN = 48
TEXT_POS = (MARGIN, IMAGE_SIZE[1] - 40)
TEXT_SIZE_PX = 13
# Texte affiché dès l'apparition de l'écran, pendant l'extraction de l'exe.
DEFAULT_TEXT = "Chargement…"


def show_step(text: str) -> None:
    """Remplace le texte d'étape (ex. « Préparation de l'interface… »)."""
    if pyi_splash is None or not pyi_splash.is_alive():
        return
    try:
        pyi_splash.update_text(text)
    except ConnectionError:
        pass  # écran déjà fermé : simple indication, jamais bloquant


def close() -> None:
    """Ferme l'écran de démarrage (sans effet s'il est déjà fermé). Il est toujours au
    premier plan : à fermer avant tout message affiché au démarrage, qu'il masquerait."""
    if pyi_splash is None:
        return
    try:
        pyi_splash.close()
    except OSError:
        pass


def close_on_error() -> None:
    """Fait fermer l'écran de démarrage par toute exception non interceptée, avant le
    gestionnaire déjà en place. Dans l'exe, PyInstaller appelle sys.excepthook avant
    d'afficher son propre message d'erreur, que l'écran (toujours au premier plan)
    masquerait sinon. À appeler au plus tôt : une erreur d'import doit aussi être vue."""
    previous_hook = sys.excepthook

    def hook(exc_type, exc_value, exc_tb):
        close()
        previous_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = hook
