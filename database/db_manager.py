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
# distances à partir de ces coordonnées. Les points durs restent au niveau du projet :
# ce sont des repères de terrain réels, partagés par tous ses scénarios.
_HARD_POINT_COLUMNS = (
    "hard_point_upstream_name", "hard_point_upstream_x", "hard_point_upstream_z",
    "hard_point_downstream_name", "hard_point_downstream_x", "hard_point_downstream_z",
)

# Nom du scénario créé automatiquement pour chaque projet existant lors de la migration
# vers la hiérarchie Projet → Scénario → Profil (et pour tout nouveau projet créé depuis
# la sidebar). Simple valeur initiale : le scénario est renommable comme les autres.
DEFAULT_SCENARIO_NAME = "Scénario initial"

# Schéma de la table des profils, partagé entre la création d'une base neuve et la
# reconstruction de la table lors de la migration vers les scénarios. `name` est un texte
# libre purement identifiant (affiché dans la sidebar et le bandeau de contexte) ;
# `distance` est la position du profil par rapport au point dur amont du projet
# (distance 0 = position du point dur amont), utilisée pour trier/positionner les
# profils sur le profil en long. Les deux sont indépendants et uniques par scénario :
# deux scénarios d'un même projet peuvent chacun avoir un profil "PK 300".
_PROFILES_TABLE_SQL = """
    CREATE TABLE {table} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scenario_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        distance REAL NOT NULL,
        existing_data TEXT, -- JSON des points du profil existant
        project_params TEXT, -- JSON des paramètres du profil projet
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (scenario_id) REFERENCES scenarios (id) ON DELETE CASCADE,
        UNIQUE (scenario_id, name),
        UNIQUE (scenario_id, distance)
    )
"""

# Tables portant un état éditable par le formulaire complet (profil existant + profil
# projet + hydraulique) : les profils des scénarios, et les brouillons de la zone Draft.
# Liste blanche : ces noms sont injectés dans du SQL (un nom de table ne peut pas être
# passé en paramètre lié).
_STATE_TABLES = ("profiles", "drafts")


class DatabaseManager:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self, foreign_keys: bool = True) -> sqlite3.Connection:
        """Ouvre une connexion. SQLite n'applique les clés étrangères (et donc les
        ON DELETE CASCADE du schéma) que si on le lui demande, connexion par connexion :
        sans ce PRAGMA, supprimer un projet laissait ses profils orphelins en base."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if foreign_keys:
            conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        """Initialise le schéma de la base de données si nécessaire, et migre une base
        créée par une version antérieure de l'application (cf. _migrate_legacy_schema
        et _migrate_profiles_to_scenarios).

        Connexion sans clés étrangères : c'est la procédure recommandée par SQLite pour
        reconstruire une table (les migrations recréent `profiles`). L'intégrité est
        vérifiée à la fin par PRAGMA foreign_key_check."""
        conn = self._get_connection(foreign_keys=False)
        try:
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

            # Scénarios d'un projet : chacun possède sa propre liste de profils, totalement
            # indépendante de celle des autres scénarios du même projet.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scenarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
                    UNIQUE (project_id, name)
                )
            """)

            # Profils rattachés aux scénarios (cf. _PROFILES_TABLE_SQL). Une base créée par
            # une version antérieure a déjà une table `profiles` à l'ancien format : elle
            # est laissée telle quelle ici et convertie par les migrations ci-dessous.
            cursor.execute(_PROFILES_TABLE_SQL.format(table="IF NOT EXISTS profiles"))

            # Zone Draft : brouillons de test jetables, sans projet, scénario, distance ni
            # point dur. Aucune clé étrangère : rien ne les relie aux vrais projets.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    existing_data TEXT, -- JSON des points du profil existant
                    project_params TEXT, -- JSON des paramètres du profil projet
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

            self._migrate_legacy_schema(conn)
            self._migrate_profiles_to_scenarios(conn)

            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                logging.error(
                    f"Base {self.db_path} : {len(violations)} violation(s) de clé étrangère "
                    f"détectée(s) après migration : {[tuple(v) for v in violations]}"
                )
        finally:
            conn.close()

    @staticmethod
    def _restore_autoincrement(cursor: sqlite3.Cursor, table: str, previous_seq: Optional[int]) -> None:
        """Après reconstruction d'une table AUTOINCREMENT, remet son compteur au moins à
        sa valeur d'avant migration : sinon, si les derniers ids avaient été supprimés
        (ou écartés par la migration), SQLite les réattribuerait à de nouvelles lignes."""
        if previous_seq is None:
            return
        row = cursor.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)).fetchone()
        if row is None:
            cursor.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (table, previous_seq))
        elif row["seq"] < previous_seq:
            cursor.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = ?", (previous_seq, table))

    def _migrate_legacy_schema(self, conn: sqlite3.Connection) -> None:
        """Adapte une base créée par une version antérieure de l'app, où :
        - `projects` n'avait pas encore de points durs (colonnes ajoutées ici via
          ALTER TABLE, nullables : une base existante n'a simplement pas encore de
          points durs renseignés, à saisir/éditer depuis la sidebar) ;
        - `profiles` identifiait chaque profil par un unique champ `pk_name`, à la fois
          nom affiché ET valeur de tri/position sur le profil en long. On le remplace
          par `name` (texte libre) et `distance` (numérique), chacun initialisé à
          l'ancienne valeur de pk_name (cf. demande : la distance reprend l'ancienne
          valeur numérique, le nom reprend telle quelle l'ancienne chaîne).

        La table produite ici est encore rattachée aux projets (`project_id`) :
        _migrate_profiles_to_scenarios prend le relais pour la rattacher aux scénarios."""
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

    def _migrate_profiles_to_scenarios(self, conn: sqlite3.Connection) -> None:
        """Passe d'une base où les profils sont rattachés directement au projet
        (`profiles.project_id`) à la hiérarchie Projet → Scénario → Profil : chaque
        projet existant reçoit un scénario par défaut (DEFAULT_SCENARIO_NAME), auquel
        sont rattachés tous ses profils, ids, noms, distances et données conservés.
        L'unicité (nom, distance) passe du projet au scénario, ce qui impose de
        reconstruire la table (même motif que _migrate_legacy_schema).

        Les profils dont le projet n'existe plus (orphelins laissés par les suppressions
        de projet d'avant l'activation des clés étrangères : le CASCADE ne se déclenchait
        jamais) n'ont aucun scénario où aller : ils sont écartés, comme leur suppression
        l'avait demandé, et signalés dans le journal.

        Tout se fait dans une seule transaction : une erreur en cours de route laisse la
        base dans son état d'avant migration."""
        cursor = conn.cursor()
        profile_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(profiles)")}
        if "scenario_id" in profile_columns or "project_id" not in profile_columns:
            return

        previous_seq_row = cursor.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = 'profiles'"
        ).fetchone()
        previous_seq = previous_seq_row["seq"] if previous_seq_row else None

        cursor.execute("BEGIN")
        try:
            scenario_by_project = {}
            for project in cursor.execute("SELECT id FROM projects ORDER BY id").fetchall():
                cursor.execute(
                    "INSERT INTO scenarios (project_id, name) VALUES (?, ?)",
                    (project["id"], DEFAULT_SCENARIO_NAME),
                )
                scenario_by_project[project["id"]] = cursor.lastrowid

            rows = cursor.execute(
                "SELECT id, project_id, name, distance, existing_data, project_params, last_updated "
                "FROM profiles ORDER BY id"
            ).fetchall()

            cursor.execute(_PROFILES_TABLE_SQL.format(table="profiles_new"))

            orphans = []
            for row in rows:
                scenario_id = scenario_by_project.get(row["project_id"])
                if scenario_id is None:
                    orphans.append((row["id"], row["project_id"], row["name"]))
                    continue
                cursor.execute(
                    """INSERT INTO profiles_new
                       (id, scenario_id, name, distance, existing_data, project_params, last_updated)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (row["id"], scenario_id, row["name"], row["distance"],
                     row["existing_data"], row["project_params"], row["last_updated"]),
                )

            cursor.execute("DROP TABLE profiles")
            cursor.execute("ALTER TABLE profiles_new RENAME TO profiles")
            self._restore_autoincrement(cursor, "profiles", previous_seq)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        logging.info(
            f"Migration vers les scénarios : {len(scenario_by_project)} scénario(s) par défaut "
            f"créé(s), {len(rows) - len(orphans)} profil(s) rattaché(s)."
        )
        if orphans:
            logging.warning(
                f"Migration vers les scénarios : {len(orphans)} profil(s) orphelin(s) (projet "
                f"déjà supprimé) écarté(s) : {orphans}"
            )

    # --- GESTION DES PROJETS ---

    def get_all_projects(self) -> List[Dict]:
        """Récupère l'arborescence complète Projet → Scénarios → Profils. Les projets sont
        triés par nom, les scénarios par ordre de création (le scénario initial reste en
        tête), les profils de chaque scénario par distance croissante au point dur amont."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM projects ORDER BY name")
            projects = [dict(row) for row in cursor.fetchall()]

            for project in projects:
                cursor.execute(
                    "SELECT id, name FROM scenarios WHERE project_id = ? ORDER BY id",
                    (project["id"],)
                )
                project["scenarios"] = [dict(row) for row in cursor.fetchall()]

                for scenario in project["scenarios"]:
                    cursor.execute(
                        """SELECT id, name, distance FROM profiles WHERE scenario_id = ?
                           ORDER BY distance""",
                        (scenario["id"],)
                    )
                    scenario["profiles"] = [dict(row) for row in cursor.fetchall()]

            return projects

    def create_project(self, name: str) -> int:
        """Crée un nouveau projet (sans scénario) et retourne son ID. Les points durs sont
        laissés vides (NULL) : à saisir ensuite via set_hard_points."""
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

    def duplicate_project(self, project_id: int, new_name: str) -> int:
        """Duplique un projet (points durs compris), tous ses scénarios et tous leurs
        profils dans un nouveau projet, en une seule transaction."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if cursor.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
                raise ValueError(f"Le projet source (ID {project_id}) est introuvable.")

            try:
                cursor.execute(
                    f"""INSERT INTO projects (name, {', '.join(_HARD_POINT_COLUMNS)})
                        SELECT ?, {', '.join(_HARD_POINT_COLUMNS)} FROM projects WHERE id = ?""",
                    (new_name, project_id),
                )
            except sqlite3.IntegrityError:
                raise ValueError(f"Le projet '{new_name}' existe déjà.")
            new_project_id = cursor.lastrowid

            scenarios = cursor.execute(
                "SELECT id, name FROM scenarios WHERE project_id = ? ORDER BY id", (project_id,)
            ).fetchall()
            for scenario in scenarios:
                cursor.execute(
                    "INSERT INTO scenarios (project_id, name) VALUES (?, ?)",
                    (new_project_id, scenario["name"]),
                )
                self._copy_profiles(cursor, scenario["id"], cursor.lastrowid)

            conn.commit()
            return new_project_id

    def delete_project(self, project_id: int) -> None:
        """Supprime un projet, tous ses scénarios et tous leurs profils (CASCADE)."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()

    # --- GESTION DES SCÉNARIOS ---

    def get_scenarios(self, project_id: int) -> List[Dict]:
        """Liste les scénarios {id, name} d'un projet, par ordre de création."""
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT id, name FROM scenarios WHERE project_id = ? ORDER BY id", (project_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def get_scenario_project_id(self, scenario_id: int) -> Optional[int]:
        """Projet auquel appartient un scénario (pour ses points durs), ou None."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT project_id FROM scenarios WHERE id = ?", (scenario_id,)
            ).fetchone()
        return row["project_id"] if row else None

    @staticmethod
    def _copy_profiles(cursor: sqlite3.Cursor, source_scenario_id: int, target_scenario_id: int) -> None:
        """Copie tous les profils d'un scénario dans un autre : mêmes noms, distances et
        données (profil existant, profil projet, hydraulique). Ce sont de nouvelles lignes
        avec leur propre JSON : les modifier ensuite n'a aucun effet sur la source."""
        cursor.execute(
            """INSERT INTO profiles (scenario_id, name, distance, existing_data, project_params)
               SELECT ?, name, distance, existing_data, project_params
               FROM profiles WHERE scenario_id = ? ORDER BY id""",
            (target_scenario_id, source_scenario_id),
        )

    def create_scenario(self, project_id: int, name: str, source_scenario_id: Optional[int] = None) -> int:
        """Crée un scénario dans un projet et retourne son ID. Si `source_scenario_id` est
        fourni (scénario du même projet), tous ses profils sont dupliqués dans le nouveau
        scénario ; sinon, celui-ci démarre vide. Création et copie sont atomiques."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if source_scenario_id is not None:
                row = cursor.execute(
                    "SELECT project_id FROM scenarios WHERE id = ?", (source_scenario_id,)
                ).fetchone()
                if row is None:
                    raise ValueError(f"Le scénario source (ID {source_scenario_id}) est introuvable.")
                if row["project_id"] != project_id:
                    raise ValueError("Le scénario source doit appartenir au même projet.")

            try:
                cursor.execute(
                    "INSERT INTO scenarios (project_id, name) VALUES (?, ?)", (project_id, name)
                )
            except sqlite3.IntegrityError as e:
                if "FOREIGN KEY" in str(e):
                    raise ValueError(f"Le projet (ID {project_id}) est introuvable.")
                raise ValueError(f"Le scénario '{name}' existe déjà dans ce projet.")
            scenario_id = cursor.lastrowid

            if source_scenario_id is not None:
                self._copy_profiles(cursor, source_scenario_id, scenario_id)

            conn.commit()
            return scenario_id

    def rename_scenario(self, scenario_id: int, new_name: str) -> None:
        """Renomme un scénario (nom unique au sein de son projet)."""
        with self._get_connection() as conn:
            try:
                conn.execute("UPDATE scenarios SET name = ? WHERE id = ?", (new_name, scenario_id))
                conn.commit()
            except sqlite3.IntegrityError:
                raise ValueError(f"Le scénario '{new_name}' existe déjà dans ce projet.")

    def delete_scenario(self, scenario_id: int) -> None:
        """Supprime un scénario et tous ses profils (CASCADE). Les points durs, portés par
        le projet, ne sont pas concernés."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM scenarios WHERE id = ?", (scenario_id,))
            conn.commit()

    # --- ÉTAT ÉDITABLE (PROFILS ET BROUILLONS) ---

    def _save_state(self, table: str, row_id: int, existing_data: List[Dict], project_params: Dict) -> None:
        assert table in _STATE_TABLES
        with self._get_connection() as conn:
            conn.execute(
                f"""UPDATE {table}
                    SET existing_data = ?, project_params = ?, last_updated = CURRENT_TIMESTAMP
                    WHERE id = ?""",
                (json.dumps(existing_data), json.dumps(project_params), row_id),
            )
            conn.commit()

    def _load_state(self, table: str, row_id: int) -> Tuple[List[Dict], Dict]:
        assert table in _STATE_TABLES
        with self._get_connection() as conn:
            row = conn.execute(
                f"SELECT existing_data, project_params FROM {table} WHERE id = ?", (row_id,)
            ).fetchone()

        if row:
            existing_data = json.loads(row["existing_data"]) if row["existing_data"] else []
            project_params = json.loads(row["project_params"]) if row["project_params"] else {}
            return existing_data, project_params
        return [], {}

    # --- GESTION DES PROFILS ET AUTO-SAVE ---

    def create_or_get_profile(self, scenario_id: int, name: str, distance: float) -> int:
        """Crée un profil s'il n'existe pas (identifié par son nom), ou retourne l'ID de
        celui qui porte déjà ce nom dans ce scénario (la distance fournie n'est alors pas
        appliquée : le profil existant n'est pas modifié)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM profiles WHERE scenario_id = ? AND name = ?",
                (scenario_id, name)
            )
            row = cursor.fetchone()
            if row:
                return row["id"]

            try:
                cursor.execute(
                    """INSERT INTO profiles (scenario_id, name, distance, existing_data, project_params)
                       VALUES (?, ?, ?, '{}', '{}')""",
                    (scenario_id, name, distance)
                )
            except sqlite3.IntegrityError as e:
                if "FOREIGN KEY" in str(e):
                    raise ValueError(f"Le scénario (ID {scenario_id}) est introuvable.")
                raise ValueError(f"La distance {distance} existe déjà dans ce scénario.")
            conn.commit()
            return cursor.lastrowid

    def save_profile_state(self, profile_id: int, existing_data: List[Dict], project_params: Dict) -> None:
        """Auto-save : Met à jour les données d'un profil spécifique."""
        self._save_state("profiles", profile_id, existing_data, project_params)
        logging.info(f"Auto-save réussi pour le profil ID {profile_id}.")

    def load_profile_state(self, profile_id: int) -> Tuple[List[Dict], Dict]:
        """Charge l'état d'un profil (Points existants et Paramètres projet)."""
        return self._load_state("profiles", profile_id)

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
                    f"Le nom '{new_name}' ou la distance {new_distance} existe déjà dans ce scénario."
                )

    def duplicate_profile(self, profile_id: int, new_name: str, new_distance: float) -> int:
        """Duplique un profil dans le même scénario, sous un nouveau nom et une nouvelle
        distance."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT scenario_id FROM profiles WHERE id = ?", (profile_id,))
            row = cursor.fetchone()
            if row is None:
                raise ValueError(f"Le profil source (ID {profile_id}) est introuvable.")
            scenario_id = row["scenario_id"]

            cursor.execute(
                "SELECT id FROM profiles WHERE scenario_id = ? AND (name = ? OR distance = ?)",
                (scenario_id, new_name, new_distance)
            )
            if cursor.fetchone() is not None:
                raise ValueError(
                    f"Le nom '{new_name}' ou la distance {new_distance} existe déjà dans ce scénario."
                )

        existing_data, project_params = self.load_profile_state(profile_id)
        new_profile_id = self.create_or_get_profile(scenario_id, new_name, new_distance)
        self.save_profile_state(new_profile_id, existing_data, project_params)
        return new_profile_id

    def get_longitudinal_data(self, scenario_id: int) -> List[Tuple[float, float, float]]:
        """Pour le profil en long d'un scénario : un triplet (distance au point dur amont,
        altitude mini du TN existant, anchor_z du projet) par profil du scénario, trié par
        distance croissante. Les profils sans points existants, ou sans paramètres projet
        enregistrés, renvoient None sur la valeur manquante plutôt que d'être exclus
        entièrement."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT distance, existing_data, project_params FROM profiles WHERE scenario_id = ?",
                (scenario_id,)
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

    def delete_profile(self, profile_id: int) -> None:
        """Supprime un profil spécifique."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
            conn.commit()

    # --- ZONE DRAFT (BROUILLONS) ---
    # Brouillons de test, identifiés par un simple nom unique. Même état éditable qu'un
    # profil (existing_data / project_params), mais aucune distance, aucun point dur et
    # aucun lien vers les projets : rien ici ne lit ni n'écrit les tables projets.

    def get_all_drafts(self) -> List[Dict]:
        """Liste les brouillons {id, name}, triés par nom."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT id, name FROM drafts ORDER BY name").fetchall()
        return [dict(row) for row in rows]

    def create_draft(self, name: str) -> int:
        """Crée un brouillon vide et retourne son ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "INSERT INTO drafts (name, existing_data, project_params) VALUES (?, '[]', '{}')",
                    (name,)
                )
            except sqlite3.IntegrityError:
                raise ValueError(f"Le brouillon '{name}' existe déjà.")
            conn.commit()
            return cursor.lastrowid

    def rename_draft(self, draft_id: int, new_name: str) -> None:
        with self._get_connection() as conn:
            try:
                conn.execute("UPDATE drafts SET name = ? WHERE id = ?", (new_name, draft_id))
                conn.commit()
            except sqlite3.IntegrityError:
                raise ValueError(f"Le brouillon '{new_name}' existe déjà.")

    def duplicate_draft(self, draft_id: int, new_name: str) -> int:
        """Duplique un brouillon (données comprises) sous un nouveau nom."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if cursor.execute("SELECT 1 FROM drafts WHERE id = ?", (draft_id,)).fetchone() is None:
                raise ValueError(f"Le brouillon source (ID {draft_id}) est introuvable.")
            try:
                cursor.execute(
                    """INSERT INTO drafts (name, existing_data, project_params)
                       SELECT ?, existing_data, project_params FROM drafts WHERE id = ?""",
                    (new_name, draft_id),
                )
            except sqlite3.IntegrityError:
                raise ValueError(f"Le brouillon '{new_name}' existe déjà.")
            conn.commit()
            return cursor.lastrowid

    def delete_draft(self, draft_id: int) -> None:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
            conn.commit()

    def save_draft_state(self, draft_id: int, existing_data: List[Dict], project_params: Dict) -> None:
        """Auto-save d'un brouillon (même format que save_profile_state)."""
        self._save_state("drafts", draft_id, existing_data, project_params)
        logging.info(f"Auto-save réussi pour le brouillon ID {draft_id}.")

    def load_draft_state(self, draft_id: int) -> Tuple[List[Dict], Dict]:
        return self._load_state("drafts", draft_id)
