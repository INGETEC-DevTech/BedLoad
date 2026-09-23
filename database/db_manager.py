import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import logging
from core.utils import get_base_dir

# Construction du chemin absolu dynamique
DB_PATH = get_base_dir() / "data" / "hydrotopo.db"

# Colonnes des points durs (amont/aval) sur la table `projects`. Un point dur est un
# repère de terrain fixe, associé à un nom et des coordonnées (X, Z) ; le point dur
# amont sert de référence pour la distance des profils (cf. table `profiles`), mais
# cette relation n'est que conventionnelle : rien ne recalcule automatiquement les
# distances à partir de ces coordonnées.
_HARD_POINT_COLUMNS = (
    "hard_point_upstream_name", "hard_point_upstream_x", "hard_point_upstream_z",
    "hard_point_downstream_name", "hard_point_downstream_x", "hard_point_downstream_z",
)

class DatabaseManager:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialise le schéma de la base de données si nécessaire, et migre une base
        créée par une version antérieure de l'application (cf. _migrate_legacy_schema)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Table des projets, avec ses deux points durs (amont/aval) : un seul jeu de
            # coordonnées par projet, saisi/édité depuis la sidebar (création de projet,
            # ou menu contextuel "Points durs du projet").
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    hard_point_upstream_name TEXT,
                    hard_point_upstream_x REAL,
                    hard_point_upstream_z REAL,
                    hard_point_downstream_name TEXT,
                    hard_point_downstream_x REAL,
                    hard_point_downstream_z REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Table des profils rattachés aux projets. `name` est un texte libre purement
            # identifiant (affiché dans la sidebar et le bandeau de contexte) ; `distance`
            # est la position du profil par rapport au point dur amont du projet (distance
            # 0 = position du point dur amont), utilisée pour trier/positionner les profils
            # sur le profil en long. Les deux sont indépendants et uniques par projet.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    distance REAL NOT NULL,
                    existing_data TEXT, -- JSON des points du profil existant
                    project_params TEXT, -- JSON des paramètres du profil projet
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
                    UNIQUE (project_id, name),
                    UNIQUE (project_id, distance)
                )
            """)
            conn.commit()

            self._migrate_legacy_schema(conn)

    def _migrate_legacy_schema(self, conn: sqlite3.Connection) -> None:
        """Adapte une base créée par une version antérieure de l'app, où :
        - `projects` n'avait pas encore de points durs (colonnes ajoutées ici via
          ALTER TABLE, nullables : une base existante n'a simplement pas encore de
          points durs renseignés, à saisir/éditer depuis la sidebar) ;
        - `profiles` identifiait chaque profil par un unique champ `pk_name`, à la fois
          nom affiché ET valeur de tri/position sur le profil en long. On le remplace
          par `name` (texte libre) et `distance` (numérique), chacun initialisé à
          l'ancienne valeur de pk_name (cf. demande : la distance reprend l'ancienne
          valeur numérique, le nom reprend telle quelle l'ancienne chaîne)."""
        cursor = conn.cursor()

        # --- projects : ajoute les colonnes de points durs si absentes ---
        project_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(projects)")}
        for column in _HARD_POINT_COLUMNS:
            if column not in project_columns:
                col_type = "TEXT" if column.endswith("_name") else "REAL"
                cursor.execute(f"ALTER TABLE projects ADD COLUMN {column} {col_type}")

        # --- profiles : remplace pk_name par name + distance. SQLite ne sait pas retirer
        # une contrainte UNIQUE par ALTER TABLE, donc on reconstruit la table (motif
        # standard SQLite : nouvelle table, copie des données, suppression de l'ancienne,
        # renommage).
        profile_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(profiles)")}
        if "pk_name" in profile_columns and "distance" not in profile_columns:
            legacy_rows = cursor.execute(
                "SELECT id, project_id, pk_name, existing_data, project_params, last_updated "
                "FROM profiles"
            ).fetchall()

            cursor.execute("""
                CREATE TABLE profiles_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    distance REAL NOT NULL,
                    existing_data TEXT,
                    project_params TEXT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
                    UNIQUE (project_id, name),
                    UNIQUE (project_id, distance)
                )
            """)

            for row in legacy_rows:
                try:
                    distance = float(row["pk_name"].replace(",", "."))
                except (AttributeError, ValueError):
                    # Ancien pk_name non numérique (déjà une incohérence avant migration :
                    # get_longitudinal_data l'ignorait silencieusement). On retombe sur
                    # l'id du profil comme distance de repli, garanti unique.
                    distance = float(row["id"])

                cursor.execute(
                    """INSERT INTO profiles_new
                       (id, project_id, name, distance, existing_data, project_params, last_updated)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (row["id"], row["project_id"], row["pk_name"], distance,
                     row["existing_data"], row["project_params"], row["last_updated"]),
                )

            cursor.execute("DROP TABLE profiles")
            cursor.execute("ALTER TABLE profiles_new RENAME TO profiles")

        conn.commit()

    # --- GESTION DES PROJETS ---

    def get_all_projects(self) -> List[Dict]:
        """Récupère l'arborescence complète (Projets et leurs Profils), les profils de
        chaque projet étant triés par distance croissante au point dur amont."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM projects ORDER BY name")
            projects = [dict(row) for row in cursor.fetchall()]

            for project in projects:
                cursor.execute(
                    """SELECT id, name, distance FROM profiles WHERE project_id = ?
                       ORDER BY distance""",
                    (project["id"],)
                )
                project["profiles"] = [dict(row) for row in cursor.fetchall()]

            return projects

    def create_project(self, name: str) -> int:
        """Crée un nouveau projet et retourne son ID. Les points durs sont laissés vides
        (NULL) : à saisir ensuite via set_hard_points."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO projects (name) VALUES (?)", (name,))
                conn.commit()
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                raise ValueError(f"Le projet '{name}' existe déjà.")

    def rename_project(self, project_id: int, new_name: str) -> None:
        """Renomme un projet existant."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "UPDATE projects SET name = ? WHERE id = ?",
                    (new_name, project_id)
                )
                conn.commit()
            except sqlite3.IntegrityError:
                raise ValueError(f"Le projet '{new_name}' existe déjà.")

    def get_hard_points(self, project_id: int) -> Optional[Dict[str, Dict[str, Optional[float]]]]:
        """Retourne les points durs amont/aval d'un projet : {"upstream": {"name","x","z"},
        "downstream": {...}}. Les champs non renseignés valent None. Retourne None si le
        projet est introuvable."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT {', '.join(_HARD_POINT_COLUMNS)} FROM projects WHERE id = ?",
                (project_id,)
            )
            row = cursor.fetchone()

        if row is None:
            return None

        return {
            "upstream": {
                "name": row["hard_point_upstream_name"],
                "x": row["hard_point_upstream_x"],
                "z": row["hard_point_upstream_z"],
            },
            "downstream": {
                "name": row["hard_point_downstream_name"],
                "x": row["hard_point_downstream_x"],
                "z": row["hard_point_downstream_z"],
            },
        }

    def set_hard_points(
        self, project_id: int,
        upstream_name: Optional[str], upstream_x: Optional[float], upstream_z: Optional[float],
        downstream_name: Optional[str], downstream_x: Optional[float], downstream_z: Optional[float],
    ) -> None:
        """Enregistre (ou met à jour) les points durs amont/aval d'un projet."""
        with self._get_connection() as conn:
            conn.execute(
                """UPDATE projects SET
                       hard_point_upstream_name = ?, hard_point_upstream_x = ?, hard_point_upstream_z = ?,
                       hard_point_downstream_name = ?, hard_point_downstream_x = ?, hard_point_downstream_z = ?
                   WHERE id = ?""",
                (upstream_name, upstream_x, upstream_z,
                 downstream_name, downstream_x, downstream_z, project_id),
            )
            conn.commit()

    # --- GESTION DES PROFILS ET AUTO-SAVE ---

    def create_or_get_profile(self, project_id: int, name: str, distance: float) -> int:
        """Crée un profil s'il n'existe pas (identifié par son nom), ou retourne l'ID de
        celui qui porte déjà ce nom dans ce projet (la distance fournie n'est alors pas
        appliquée : le profil existant n'est pas modifié)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM profiles WHERE project_id = ? AND name = ?",
                (project_id, name)
            )
            row = cursor.fetchone()
            if row:
                return row["id"]

            try:
                cursor.execute(
                    """INSERT INTO profiles (project_id, name, distance, existing_data, project_params)
                       VALUES (?, ?, ?, '{}', '{}')""",
                    (project_id, name, distance)
                )
            except sqlite3.IntegrityError:
                raise ValueError(f"La distance {distance} existe déjà dans ce projet.")
            conn.commit()
            return cursor.lastrowid

    def save_profile_state(self, profile_id: int, existing_data: List[Dict], project_params: Dict) -> None:
            """Auto-save : Met à jour les données d'un profil spécifique."""
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE profiles
                    SET existing_data = ?, project_params = ?, last_updated = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (json.dumps(existing_data), json.dumps(project_params), profile_id))
                conn.commit()

            logging.info(f"Auto-save réussi pour le profil ID {profile_id}.")

    def load_profile_state(self, profile_id: int) -> Tuple[List[Dict], Dict]:
        """Charge l'état d'un profil (Points existants et Paramètres projet)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT existing_data, project_params FROM profiles WHERE id = ?",
                (profile_id,)
            )
            row = cursor.fetchone()

            if row:
                existing_data = json.loads(row["existing_data"]) if row["existing_data"] else []
                project_params = json.loads(row["project_params"]) if row["project_params"] else {}
                return existing_data, project_params
            return [], {}

    def rename_profile(self, profile_id: int, new_name: str, new_distance: float) -> None:
        """Renomme un profil et met à jour sa distance au point dur amont."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "UPDATE profiles SET name = ?, distance = ? WHERE id = ?",
                    (new_name, new_distance, profile_id)
                )
                conn.commit()
            except sqlite3.IntegrityError:
                raise ValueError(
                    f"Le nom '{new_name}' ou la distance {new_distance} existe déjà dans ce projet."
                )

    def duplicate_profile(self, profile_id: int, new_name: str, new_distance: float) -> int:
        """Duplique un profil dans le même projet, sous un nouveau nom et une nouvelle
        distance."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT project_id FROM profiles WHERE id = ?", (profile_id,))
            row = cursor.fetchone()
            if row is None:
                raise ValueError(f"Le profil source (ID {profile_id}) est introuvable.")
            project_id = row["project_id"]

            cursor.execute(
                "SELECT id FROM profiles WHERE project_id = ? AND (name = ? OR distance = ?)",
                (project_id, new_name, new_distance)
            )
            if cursor.fetchone() is not None:
                raise ValueError(
                    f"Le nom '{new_name}' ou la distance {new_distance} existe déjà dans ce projet."
                )

        existing_data, project_params = self.load_profile_state(profile_id)
        new_profile_id = self.create_or_get_profile(project_id, new_name, new_distance)
        self.save_profile_state(new_profile_id, existing_data, project_params)
        return new_profile_id

    def duplicate_project(self, project_id: int, new_name: str) -> int:
        """Duplique un projet (points durs compris) et tous ses profils dans un nouveau
        projet."""
        new_project_id = self.create_project(new_name)

        hard_points = self.get_hard_points(project_id)
        if hard_points is not None:
            self.set_hard_points(
                new_project_id,
                hard_points["upstream"]["name"], hard_points["upstream"]["x"], hard_points["upstream"]["z"],
                hard_points["downstream"]["name"], hard_points["downstream"]["x"], hard_points["downstream"]["z"],
            )

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name, distance FROM profiles WHERE project_id = ?",
                (project_id,)
            )
            profiles = [dict(row) for row in cursor.fetchall()]

        for profile in profiles:
            existing_data, project_params = self.load_profile_state(profile["id"])
            new_profile_id = self.create_or_get_profile(new_project_id, profile["name"], profile["distance"])
            self.save_profile_state(new_profile_id, existing_data, project_params)

        return new_project_id

    def get_longitudinal_data(self, project_id: int) -> List[Tuple[float, float, float]]:
        """Pour le profil en long : un triplet (distance au point dur amont, altitude mini
        du TN existant, anchor_z du projet) par profil du projet, trié par distance
        croissante. Les profils sans points existants, ou sans paramètres projet
        enregistrés, renvoient None sur la valeur manquante plutôt que d'être exclus
        entièrement."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT distance, existing_data, project_params FROM profiles WHERE project_id = ?",
                (project_id,)
            )
            rows = cursor.fetchall()

        result = []
        for row in rows:
            distance = row["distance"]

            existing_data = json.loads(row["existing_data"]) if row["existing_data"] else []
            z_values = [pt["Z (m NGF)"] for pt in existing_data if "Z (m NGF)" in pt]
            min_z_existing = min(z_values) if z_values else None

            project_params = json.loads(row["project_params"]) if row["project_params"] else {}
            anchor_z_project = project_params.get("anchor_z")

            result.append((distance, min_z_existing, anchor_z_project))

        result.sort(key=lambda t: t[0])
        return result

    def delete_project(self, project_id: int) -> None:
        """Supprime un projet et tous ses profils associés (grâce au CASCADE)."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()

    def delete_profile(self, profile_id: int) -> None:
        """Supprime un profil spécifique."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
            conn.commit()
