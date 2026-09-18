# ui/views/plot_view.py
import tempfile
from pathlib import Path

import plotly
from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QVBoxLayout, QWidget

def _get_or_create_plotly_cache_dir() -> tuple[Path, str]:
    """Écrit plotly.min.js sur disque (une fois par version) et renvoie
    (dossier de cache, nom du fichier JS).

    setHtml() a une limite de taille (~2 Mo côté Chromium/Qt) qui tronque
    silencieusement le JS de Plotly (plusieurs Mo) s'il est injecté inline.
    On passe donc par un vrai fichier local, chargé via load(), qui n'a pas
    cette limite.
    """
    cache_dir = Path(tempfile.gettempdir()) / "hydrotopo_plotly_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    js_path = cache_dir / f"plotly-{plotly.__version__}.min.js"
    if not js_path.exists():
        js_path.write_text(plotly.offline.get_plotlyjs(), encoding="utf-8")

    return cache_dir, js_path.name

class PlotView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.browser = QWebEngineView()
        self.main_layout.addWidget(self.browser)
        
        # --- NOUVEAU : Gestion de l'asynchronisme ---
        self._is_ready = False       # Vrai quand la page HTML est totalement chargée
        self._pending_fig = None     # Stocke le graphique en attente
        self.browser.loadFinished.connect(self.on_page_loaded)

        cache_dir, plotly_js_filename = _get_or_create_plotly_cache_dir()
        html_base = f"""
        <html>
        <head>
            <script type="text/javascript" src="{plotly_js_filename}"></script>
            <style>
                /* Fond de la page web unifié avec le gris de l'application */
                body {{ 
                    margin: 0; 
                    padding: 20px; /* Crée l'espacement pour décoller le graphique des bords */
                    background-color: #f8f9fa; 
                    height: 100vh; 
                    box-sizing: border-box;
                    display: flex; 
                    justify-content: center; 
                    align-items: center; 
                    overflow: hidden; 
                }}
                
                /* La carte blanche qui contient le graphique */
                #card {{
                    position: relative;
                    width: 100%;
                    height: 100%;
                    background-color: #ffffff;
                    border-radius: 12px;
                    border: 1px solid #dee2e6;
                    box-shadow: 0 8px 16px rgba(0, 0, 0, 0.04), 0 2px 6px rgba(0, 0, 0, 0.04);
                    overflow: hidden;
                }}
                
                /* Le graphique prend toute la place DANS la carte */
                #graph {{ 
                    position: absolute; 
                    top: 0; left: 0; 
                    width: 100%; height: 100%; 
                    z-index: 1; 
                }}
                
                /* L'écran d'attente superposé avec icône intégrée */
                #empty-state {{ 
                    position: absolute; 
                    top: 0; left: 0; 
                    width: 100%; height: 100%; 
                    z-index: 2; 
                    display: flex; 
                    flex-direction: column;
                    justify-content: center; 
                    align-items: center; 
                    background-color: #ffffff; 
                    font-family: "Segoe UI", sans-serif; 
                    color: #adb5bd; 
                    font-size: 15px; 
                }}
                
                .icon-placeholder {{ margin-bottom: 15px; opacity: 0.5; }}
            </style>
        </head>
        <body>
            <div id="card">
                <div id="graph"></div>
                <div id="empty-state">
                    <!-- Icône de graphique vectorielle (SVG) -->
                    <svg class="icon-placeholder" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M3 3v18h18"/>
                        <path d="M18 9l-5 5-4-4-4 4"/>
                    </svg>
                    <span id="empty-state-text">Chargement du moteur graphique...</span>
                </div>
            </div>
            
            <script>
                function updateGraph(figData) {{
                    try {{
                        if (typeof Plotly === 'undefined') {{
                            document.getElementById('empty-state-text').innerHTML = "Erreur : La librairie Plotly est introuvable.";
                            return;
                        }}
                        
                        var graphDiv = document.getElementById('graph');
                        var config = {{
                            displaylogo: false,
                            modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'],
                            displayModeBar: 'hover'
                        }};
                        
                        Plotly.react(graphDiv, figData.data, figData.layout, config);
                        
                        // Masque l'écran d'attente
                        document.getElementById('empty-state').style.display = 'none';
                        
                    }} catch(err) {{
                        document.getElementById('empty-state-text').innerHTML = "Erreur d'affichage : " + err.message;
                        document.getElementById('empty-state').style.display = 'flex';
                    }}
                }}
                
                function showEmptyState() {{
                    document.getElementById('empty-state-text').innerHTML = 'Données insuffisantes pour tracer le profil.';
                    document.getElementById('empty-state').style.display = 'flex';
                }}
            </script>
        </body>
        </html>
        """

        # Le HTML lui-même reste petit : il peut passer par un fichier, à côté
        # de plotly.min.js pour que le <script src="..."> relatif se résolve.
        html_path = cache_dir / "index.html"
        html_path.write_text(html_base, encoding="utf-8")

        self.browser.load(QUrl.fromLocalFile(str(html_path)))
        
    def on_page_loaded(self, ok: bool):
        """Déclenché automatiquement par Qt quand le HTML a fini de charger."""
        if not ok:
            # Le chargement local a échoué (fichier manquant, permissions...) :
            # on ne bascule pas _is_ready pour ne pas exécuter du JS sur une page vide.
            return

        self._is_ready = True
        # Si un graphique attendait dans la file, on l'affiche maintenant
        if self._pending_fig is not None:
            self.update_plot(self._pending_fig)
            self._pending_fig = None

    def update_plot(self, fig):
        # Si la page n'est pas prête, on met la figure en attente et on s'arrête
        if not self._is_ready:
            self._pending_fig = fig
            return
            
        if fig is None:
            self.browser.page().runJavaScript("showEmptyState();")
            return
        
        # Sérialisation instantanée de la figure Python en texte JSON
        fig_json = fig.to_json()
        
        # Injection du JSON pur dans la fonction JavaScript
        self.browser.page().runJavaScript(f"updateGraph({fig_json});")