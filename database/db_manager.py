import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import logging
from core.hard_points import (EXISTING, FAMILIES, FAMILY_PLURALS, PROJECT, SLOPE_COMPUTED, SLOPE_IMPOSED,
                              HardPoint, SlopeReport, computed_slope, distance_zone, of_family, reference_pk,
                              validate_hard_point_families)
from core.utils import DATA_DIR_NAME, DB_FILE_NAME, get_base_dir

# Construction du chemin absolu dynamique (à côté de l'exe : appli portable, cf.
# core.utils.find_storage_problem pour la vérification des droits d'écriture au démarrage)
DB_PATH = get_base_dir() / DATA_DIR_NAME / DB_FILE_NAME

# Colonnes des ANCIENS points durs (amont/aval) sur la table `projects`, remplacées par la
# table `hard_points` (liste libre, cf. _HARD_POINTS_TABLE_SQL). Conservées en base pour ne
# rien perdre, elles ne servent plus qu'à la migration et à l'import d'anciens fichiers.
# Ancienne description : Un point dur est un
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
# `distance` est la position du profil le long du lit existant, par rapport au premier
# point dur existant du projet (distance 0), utilisée pour trier les profils et les placer
# sur le profil en long ; `project_distance`, sa position le long du lit projet (rivière
# déplacée ou reméandrée), par rapport au premier point dur projet. Le nom et la distance
# existante sont uniques par scénario (pas la distance projet) : deux scénarios d'un même
# projet peuvent chacun avoir un profil "PK 300".
_PROFILES_TABLE_SQL = """
    CREATE TABLE {table} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scenario_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        distance REAL NOT NULL,
        project_distance REAL NOT NULL,
        existing_data TEXT, -- JSON des points du profil existant
        project_params TEXT, -- JSON des paramètres du profil projet
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (scenario_id) REFERENCES scenarios (id) ON DELETE CASCADE,
        UNIQUE (scenario_id, name),
        UNIQUE (scenario_id, distance)
    )
"""

# Points durs d'un projet : liste libre (nom, PK, Z), commune à tous ses scénarios,
# ordonnée par PK, en deux familles indépendantes (`family` : "existing" le long du lit
# actuel, "project" le long du nouveau lit ; cf. core.hard_points pour les règles). PK et
# Z peuvent être vides pour un point hérité incomplet, ignoré dans les calculs.
_HARD_POINTS_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS hard_points (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        name TEXT,
        pk REAL,
        z REAL,
        family TEXT NOT NULL DEFAULT 'existing',
        FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
    )
"""

# Tables portant un état éditable par le formulaire complet (profil existant + profil
# projet + hydraulique) : les profils des scénarios, et les brouillons de la zone Draft.
# Liste blanche : ces noms sont injectés dans du SQL (un nom de table ne peut pas être
# passé en paramètre lié).
_STATE_TABLES = ("profiles", "drafts")

# Format des fichiers d'export/import JSON (cf. section EXPORT / IMPORT en fin de classe).
# `version` accompagne chaque fichier pour permettre de faire évoluer le format plus tard
# sans casser les exports déjà sur le disque des utilisateurs.
# Version 2 : points durs en liste ("hard_points": [{"name", "pk", "z"}, ...]) au lieu du
# couple {"upstream", "downstream"} de la version 1, toujours accepté à l'import.
# Version 3 : lits existant et projet dissociés. "hard_points" ne liste plus que les points
# durs existants, "project_hard_points" les points durs projet, et chaque profil a sa
# "project_distance". Les clés de la version 2 gardent leur sens : une version antérieure
# de l'application lit un tel fichier comme un projet à un seul lit (le lit existant), en
# ignorant les points durs projet et les distances projet.
_EXPORT_VERSION = 3
_EXPORT_TYPES = ("profile", "scenario", "project")


class DistanceTakenError(ValueError):
    """La distance d'un profil importé ou copié dans un scénario est déjà prise par un autre
    profil de ce scénario (cf. import_profile_into_scenario / copy_draft_to_scenario) :
    l'appelant peut retenter en remplaçant ce profil (replace=True), ou à une autre distance."""

    def __init__(self, distance: float, profile_name: str):
        super().__init__(
            f"La distance {distance:g} m est déjà prise par le profil « {profile_name} » dans ce scénario."
        )
        self.distance = distance
        self.profile_name = profile_name


class ProjectDistanceOutOfZoneError(ValueError):
    """La distance projet d'un profil qui arrive dans un scénario (création, duplication,
    import, copie d'un brouillon) ne peut pas reprendre sa distance existante : elle
    sortirait de la zone couverte par les points durs projet (lit projet plus court).
    L'appelant la demande à l'utilisateur — `suggested` est la valeur autorisée la plus
    proche — puis recommence en la fournissant. Pour l'import d'un scénario,
    `profile_index` désigne le profil concerné dans la liste du fichier."""

    def __init__(self, profile_name: Optional[str], distance: float, zone: Tuple[float, float]):
        who = f"Profil « {profile_name} » : " if profile_name else ""
        super().__init__(
            f"{who}la distance projet ne peut pas reprendre la distance existante ({distance:g} m), "
            f"hors de la zone couverte par les points durs projet ({zone[0]:g} à {zone[1]:g} m)."
        )
        self.profile_name = profile_name
        self.distance = distance
        self.zone = zone
        self.suggested = min(max(distance, zone[0]), zone[1])
        self.profile_index: Optional[int] = None


class DatabaseManager:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Bilan des pentes recalculées par la migration vers les points durs multiples (à
        # afficher une fois au démarrage), et par la dernière opération qui en recalcule
        # (création/modification de profil, points durs, import...).
        self.startup_slope_report = SlopeReport()
        self.last_slope_report = SlopeReport()
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
            # ou menu contextuel "Points durs du projet"). `archived` (0/1) range un projet
            # hors de l'arborescence de la sidebar sans rien supprimer (cf. menu Archives).
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
                    archived INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Scénarios d'un projet : chacun possède sa propre liste de profils, totalement
            # indépendante de celle des autres scénarios du même projet.
            # `longitudinal_orthonormal` (0/1) : case « Échelle orthonormée » de son profil
            # en long, retrouvée à chaque affichage.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scenarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    longitudinal_orthonormal INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
                    UNIQUE (project_id, name)
                )
            """)

            # Profils rattachés aux scénarios (cf. _PROFILES_TABLE_SQL). Une base créée par
            # une version antérieure a déjà une table `profiles` à l'ancien format : elle
            # est laissée telle quelle ici et convertie par les migrations ci-dessous.
            cursor.execute(_PROFILES_TABLE_SQL.format(table="IF NOT EXISTS profiles"))

            had_hard_points_table = cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'hard_points'"
            ).fetchone() is not None
            cursor.execute(_HARD_POINTS_TABLE_SQL)

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
            # Avant la migration des points durs : elle recalcule les pentes, qui lisent la
            # distance projet des profils.
            self._migrate_to_two_beds(conn)
            if not had_hard_points_table:
                self._migrate_hard_points_to_list(conn)

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
          points durs renseignés, à saisir/éditer depuis la sidebar), ni d'indicateur
          `archived` (même principe : colonne ajoutée, tous les projets restent actifs) ;
        - `scenarios` n'avait pas l'état de la case « Échelle orthonormée » du profil en
          long (colonne ajoutée, décochée pour tous les scénarios existants) ;
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

        # --- projects : ajoute l'indicateur d'archivage (les projets existants restent actifs) ---
        if "archived" not in project_columns:
            cursor.execute("ALTER TABLE projects ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")

        # --- scenarios : ajoute l'état de la case « Échelle orthonormée » (décochée) ---
        scenario_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(scenarios)")}
        if "longitudinal_orthonormal" not in scenario_columns:
            cursor.execute(
                "ALTER TABLE scenarios ADD COLUMN longitudinal_orthonormal INTEGER NOT NULL DEFAULT 0"
            )

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
                       (id, scenario_id, name, distance, project_distance, existing_data,
                        project_params, last_updated)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (row["id"], scenario_id, row["name"], row["distance"], row["distance"],
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

    def _migrate_hard_points_to_list(self, conn: sqlite3.Connection) -> None:
        """Passe des deux points durs amont/aval (colonnes de `projects`) à la liste libre
        (table `hard_points`) : l'amont devient le premier point, l'aval le dernier ; un point
        entièrement vide n'est pas repris, un point incomplet l'est tel quel. Chaque point
        est repris dans les deux familles (existante et projet), comme le fait
        _migrate_to_two_beds pour une liste déjà enregistrée. Puis tous les profils
        existants passent en pente calculée (ou imposée si aucun calcul n'est possible),
        bilan conservé dans startup_slope_report. Une seule transaction."""
        cursor = conn.cursor()
        columns = ", ".join(_HARD_POINT_COLUMNS)
        report = SlopeReport()
        cursor.execute("BEGIN")
        try:
            projects = cursor.execute(f"SELECT id, {columns} FROM projects ORDER BY id").fetchall()
            for row in projects:
                for side in ("upstream", "downstream"):
                    name = row[f"hard_point_{side}_name"]
                    pk = row[f"hard_point_{side}_x"]
                    z = row[f"hard_point_{side}_z"]
                    if name is None and pk is None and z is None:
                        continue
                    for family in FAMILIES:
                        cursor.execute(
                            "INSERT INTO hard_points (project_id, name, pk, z, family) VALUES (?, ?, ?, ?, ?)",
                            (row["id"], name, pk, z, family),
                        )
            for row in projects:
                report.merge(self._refresh_slopes(cursor, row["id"]))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        self.startup_slope_report = report
        logging.info(
            f"Migration vers les points durs multiples : {len(projects)} projet(s), "
            f"{len(report.updated)} profil(s) en pente calculée, "
            f"{len(report.switched_to_imposed)} en pente imposée."
        )

    def _migrate_to_two_beds(self, conn: sqlite3.Connection) -> None:
        """Dissocie le lit existant et le lit projet (rivière déplacée ou reméandrée) dans
        une base d'une version antérieure :
        - `hard_points` reçoit sa famille (`family`) : les points déjà enregistrés deviennent
          les points durs existants, et sont copiés à l'identique en points durs projet ;
        - `profiles` reçoit sa distance projet (`project_distance`), égale à sa distance.
        Rien ne change donc : mêmes repères, mêmes distances, mêmes pentes. Une seule
        transaction ; rien à faire pour une base déjà à jour (ou neuve)."""
        cursor = conn.cursor()
        point_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(hard_points)")}
        profile_columns = {row["name"] for row in cursor.execute("PRAGMA table_info(profiles)")}
        if "family" in point_columns and "project_distance" in profile_columns:
            return

        cursor.execute("BEGIN")
        try:
            copied = 0
            if "family" not in point_columns:
                cursor.execute(
                    f"ALTER TABLE hard_points ADD COLUMN family TEXT NOT NULL DEFAULT '{EXISTING}'"
                )
                cursor.execute(
                    """INSERT INTO hard_points (project_id, name, pk, z, family)
                       SELECT project_id, name, pk, z, ? FROM hard_points WHERE family = ? ORDER BY id""",
                    (PROJECT, EXISTING),
                )
                copied = cursor.rowcount
            if "project_distance" not in profile_columns:
                # Colonne obligatoire : SQLite n'en ajoute une qu'avec une valeur par
                # défaut, aussitôt remplacée par la distance de chaque profil.
                cursor.execute("ALTER TABLE profiles ADD COLUMN project_distance REAL NOT NULL DEFAULT 0")
                cursor.execute("UPDATE profiles SET project_distance = distance")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        logging.info(
            f"Dissociation des lits existant et projet : {copied} point(s) dur(s) copié(s) en "
            "points durs projet, distance projet des profils initialisée à leur distance."
        )

    # --- GESTION DES PROJETS ---

    def get_all_projects(self) -> List[Dict]:
        """Récupère l'arborescence complète Projet → Scénarios → Profils des projets actifs
        (les projets archivés en sont exclus, cf. get_archived_projects). Les projets sont
        triés par nom, les scénarios par ordre de création (le scénario initial reste en
        tête), les profils de chaque scénario par distance existante croissante."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM projects WHERE archived = 0 ORDER BY name")
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

    def get_recent_projects(self, limit: int) -> List[Dict]:
        """Les `limit` projets actifs (non archivés) modifiés le plus récemment, du plus
        récent au plus ancien : {id, name, last_modified}. Faute de date de modification
        propre au projet, `last_modified` est la plus récente de sa création, de celle de
        ses scénarios et du dernier enregistrement de ses profils (création, import ou
        saisie dans le formulaire). Renommages, points durs et suppressions n'en laissent
        pas. C'est un datetime en heure locale (None si le projet n'a aucune date)."""
        with self._get_connection() as conn:
            # MAX() à plusieurs arguments vaut NULL dès que l'un d'eux l'est : chaque date
            # absente est donc remplacée par '' (antérieur à toute date au format texte).
            rows = conn.execute(
                """SELECT p.id, p.name,
                          MAX(COALESCE(p.created_at, ''),
                              COALESCE((SELECT MAX(s.created_at) FROM scenarios s
                                         WHERE s.project_id = p.id), ''),
                              COALESCE((SELECT MAX(pr.last_updated) FROM profiles pr
                                         JOIN scenarios s ON pr.scenario_id = s.id
                                         WHERE s.project_id = p.id), '')) AS last_modified
                   FROM projects p WHERE p.archived = 0
                   ORDER BY last_modified DESC, p.id DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            {"id": row["id"], "name": row["name"], "last_modified": self._local_time(row["last_modified"])}
            for row in rows
        ]

    @staticmethod
    def _local_time(utc_text: Optional[str]) -> Optional[datetime]:
        """Horodatage écrit par SQLite (CURRENT_TIMESTAMP : texte UTC "AAAA-MM-JJ HH:MM:SS")
        converti en heure locale, ou None s'il est absent ou illisible."""
        if not utc_text:
            return None
        try:
            moment = datetime.fromisoformat(utc_text)
        except (TypeError, ValueError):
            return None
        return moment.replace(tzinfo=timezone.utc).astimezone()

    def get_archived_projects(self) -> List[Dict]:
        """Projets archivés, triés par nom : {id, name, scenario_count, profile_count}.
        Les décomptes permettent à la fenêtre Archives de décrire ce que contient chaque
        projet sans charger toute son arborescence."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """SELECT p.id, p.name,
                          (SELECT COUNT(*) FROM scenarios s WHERE s.project_id = p.id) AS scenario_count,
                          (SELECT COUNT(*) FROM profiles pr JOIN scenarios s ON pr.scenario_id = s.id
                            WHERE s.project_id = p.id) AS profile_count
                   FROM projects p WHERE p.archived = 1 ORDER BY p.name"""
            ).fetchall()
        return [dict(row) for row in rows]

    def set_project_archived(self, project_id: int, archived: bool) -> None:
        """Archive un projet (il disparaît de l'arborescence, rien n'est supprimé) ou le
        restaure. Son nom reste réservé : l'unicité des noms de projet porte aussi sur les
        projets archivés."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE projects SET archived = ? WHERE id = ?", (1 if archived else 0, project_id)
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Le projet (ID {project_id}) est introuvable.")
            conn.commit()

    @staticmethod
    def _project_exists_message(conn: sqlite3.Connection, name: str) -> str:
        """Message d'erreur pour un nom de projet déjà pris, précisant s'il l'est par un
        projet archivé (invisible dans l'arborescence, donc sinon incompréhensible)."""
        row = conn.execute("SELECT archived FROM projects WHERE name = ?", (name,)).fetchone()
        if row is not None and row["archived"]:
            return f"Le projet '{name}' existe déjà (dans les archives)."
        return f"Le projet '{name}' existe déjà."

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
                raise ValueError(self._project_exists_message(conn, name))

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
                raise ValueError(self._project_exists_message(conn, new_name))

    @staticmethod
    def _hard_points(cursor: sqlite3.Cursor, project_id: int, family: Optional[str] = None) -> List[HardPoint]:
        """Points durs du projet : ceux d'une famille, ou tous (les existants d'abord)."""
        sql = "SELECT id, name, pk, z, family FROM hard_points WHERE project_id = ?"
        params = [project_id]
        if family is not None:
            sql += " AND family = ?"
            params.append(family)
        sql += f" ORDER BY family = '{PROJECT}', pk IS NULL, pk, id"
        rows = cursor.execute(sql, params).fetchall()
        return [HardPoint(name=r["name"], pk=r["pk"], z=r["z"], id=r["id"], family=r["family"]) for r in rows]

    def get_hard_points(self, project_id: int, family: Optional[str] = None) -> List[Dict]:
        """Points durs d'un projet [{id, name, pk, z, family}] : ceux d'une famille
        (EXISTING ou PROJECT), ou tous, les existants d'abord ; triés par PK (points
        incomplets à la fin). Liste vide si le projet n'en a pas (ou n'existe pas)."""
        with self._get_connection() as conn:
            return [p.to_dict() for p in self._hard_points(conn.cursor(), project_id, family)]

    def get_distance_zone(self, project_id: int, family: str = EXISTING) -> Optional[Tuple[float, float]]:
        """Plage autorisée pour la distance des profils du projet le long d'un lit (0 =
        premier point dur de la famille, jusqu'au dernier), ou None faute de deux points
        durs complets dans cette famille."""
        with self._get_connection() as conn:
            return distance_zone(self._hard_points(conn.cursor(), project_id, family))

    @staticmethod
    def _project_profiles(cursor: sqlite3.Cursor, project_id: int) -> List[sqlite3.Row]:
        return cursor.execute(
            """SELECT p.id, p.name, p.distance, p.project_distance, p.project_params,
                      s.name AS scenario_name
               FROM profiles p JOIN scenarios s ON s.id = p.scenario_id
               WHERE s.project_id = ? ORDER BY s.id, p.distance""",
            (project_id,),
        ).fetchall()

    def _hard_points_errors(self, cursor: sqlite3.Cursor, project_id: int, new_points: List[HardPoint]) -> List[str]:
        """Erreurs de la liste `new_points` pour ce projet (cf. validate_hard_point_families),
        famille par famille, en tenant compte de ses points actuels (référence, points
        incomplets hérités) et de la position réelle de ses profils le long de chaque lit
        (référence actuelle de la famille + distance existante ou projet ; sans référence
        actuelle, les distances sont prises par rapport à la nouvelle)."""
        old_points = self._hard_points(cursor, project_id)
        profiles = self._project_profiles(cursor, project_id)
        reference_ids, profile_pks = {}, {}
        for family in FAMILIES:
            old = of_family(old_points, family)
            old_complete = [p for p in old if p.is_complete]
            reference_ids[family] = min(old_complete, key=lambda p: p.pk).id if old_complete else None
            old_reference_pk = reference_pk(old)
            base_pk = old_reference_pk if old_reference_pk is not None else reference_pk(of_family(new_points, family))
            column = self._distance_column(family)
            profile_pks[family] = {} if base_pk is None else {
                f"{r['scenario_name']} › {r['name']}": base_pk + r[column] for r in profiles
            }
        return validate_hard_point_families(
            new_points, reference_ids, profile_pks,
            original_incomplete={p.id: (p.name, p.pk, p.z) for p in old_points if not p.is_complete},
        )

    def check_hard_points(self, project_id: int, points: List[Dict]) -> List[str]:
        """Vérification "à blanc" d'une liste de points durs (rien n'est enregistré) : les
        mêmes messages que set_hard_points, pour les afficher pendant la saisie."""
        with self._get_connection() as conn:
            return self._hard_points_errors(conn.cursor(), project_id, [HardPoint.from_dict(p) for p in points])

    def set_hard_points(self, project_id: int, points: List[Dict]) -> SlopeReport:
        """Remplace les points durs d'un projet par `points` ([{id?, name, pk, z, family}] ;
        id renseigné pour un point déjà en base ; famille existante par défaut), après
        validation (cf. core.hard_points.validate_hard_point_families ; ValueError avec tous
        les messages sinon).

        Les profils gardent leur position réelle (PK) le long de chaque lit : si le premier
        point dur d'une famille (référence "distance 0" de ce lit) change de PK, la distance
        correspondante des profils (existante ou projet) est décalée d'autant. Les pentes
        calculées sont ensuite recalculées ; le bilan est retourné (et conservé dans
        last_slope_report). Une seule transaction."""
        new_points = [HardPoint.from_dict(p) for p in points]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            errors = self._hard_points_errors(cursor, project_id, new_points)
            if errors:
                raise ValueError("\n".join(errors))
            old_points = self._hard_points(cursor, project_id)
            profiles = self._project_profiles(cursor, project_id)

            cursor.execute("DELETE FROM hard_points WHERE project_id = ?", (project_id,))
            for point in new_points:
                cursor.execute(
                    "INSERT INTO hard_points (id, project_id, name, pk, z, family) VALUES (?, ?, ?, ?, ?, ?)",
                    (point.id, project_id, point.name, point.pk, point.z, point.family),
                )

            for family in FAMILIES:
                old_reference_pk = reference_pk(of_family(old_points, family))
                new_reference_pk = reference_pk(of_family(new_points, family))
                if old_reference_pk is not None and new_reference_pk is not None:
                    self._shift_profile_distances(cursor, profiles, old_reference_pk - new_reference_pk,
                                                  self._distance_column(family))

            report = self._refresh_slopes(cursor, project_id)
            conn.commit()
        self.last_slope_report = report
        return report

    @staticmethod
    def _distance_column(family: str) -> str:
        """Colonne de la distance d'un profil le long du lit de cette famille."""
        return "distance" if family == EXISTING else "project_distance"

    @staticmethod
    def _slope_family(params: Dict) -> str:
        """Famille de points durs (et donc distance) de la pente calculée d'un profil : celle
        du profil sur lequel porte son calcul hydraulique (hydro_source ; projet par
        défaut, comme dans l'onglet Hydraulique)."""
        return EXISTING if params.get("hydro_source") == "existing" else PROJECT

    @staticmethod
    def _shift_profile_distances(cursor: sqlite3.Cursor, profiles: List[sqlite3.Row], delta: float,
                                 column: str = "distance") -> None:
        """Décale de `delta` la distance `column` ("distance" ou "project_distance") de tous
        les profils (même position réelle, nouvelle référence). Mise à jour profil par
        profil dans le sens qui évite toute collision transitoire avec la contrainte UNIQUE
        (scénario, distance)."""
        assert column in ("distance", "project_distance")
        if abs(delta) < 1e-12:
            return
        ordered = sorted(profiles, key=lambda r: r[column], reverse=delta > 0)
        for row in ordered:
            cursor.execute(f"UPDATE profiles SET {column} = ? WHERE id = ?", (row[column] + delta, row["id"]))

    def _refresh_slopes(self, cursor: sqlite3.Cursor, project_id: int,
                        profile_ids: Optional[List[int]] = None) -> SlopeReport:
        """Recalcule la pente des profils en pente calculée (tous ceux du projet, ou ceux de
        `profile_ids`) à partir des points durs et de la distance du lit sur lequel porte
        leur calcul hydraulique (cf. _slope_family) ; un profil sans mode enregistré est en
        pente calculée. Si aucun calcul n'est possible, le profil passe en pente imposée (sa
        valeur actuelle est conservée). Les profils en pente imposée ne sont pas touchés."""
        points = self._hard_points(cursor, project_id)
        report = SlopeReport()
        for row in self._project_profiles(cursor, project_id):
            if profile_ids is not None and row["id"] not in profile_ids:
                continue
            label = f"{row['scenario_name']} › {row['name']}"
            params = json.loads(row["project_params"]) if row["project_params"] else {}
            if params.get("slope_mode") == SLOPE_IMPOSED:
                report.imposed_kept.append(label)
                continue

            family = self._slope_family(params)
            slope, _segment, reason = computed_slope(of_family(points, family),
                                                     row[self._distance_column(family)], family)
            if slope is None:
                params["slope_mode"] = SLOPE_IMPOSED
                report.switched_to_imposed.append((label, reason))
            else:
                if params.get("slope") is None or abs(params["slope"] - slope) > 1e-12:
                    report.updated.append(label)
                params["slope"] = slope
                params["slope_mode"] = SLOPE_COMPUTED
            cursor.execute("UPDATE profiles SET project_params = ? WHERE id = ?",
                           (json.dumps(params), row["id"]))
        return report

    def _check_distance_in_zone(self, cursor: sqlite3.Cursor, scenario_id: int, distance: float,
                                profile_name: Optional[str] = None, family: str = EXISTING) -> None:
        """ValueError si `distance` (existante ou projet, selon `family`) est hors de la zone
        couverte par cette famille de points durs du projet du scénario (aucune contrainte
        sans zone)."""
        row = cursor.execute("SELECT project_id FROM scenarios WHERE id = ?", (scenario_id,)).fetchone()
        if row is None:
            raise ValueError(f"Le scénario (ID {scenario_id}) est introuvable.")
        zone = distance_zone(self._hard_points(cursor, row["project_id"], family))
        if zone is not None and not (zone[0] - 1e-6 <= distance <= zone[1] + 1e-6):
            who = f"Profil « {profile_name} » : " if profile_name else ""
            label = "existante" if family == EXISTING else "projet"
            raise ValueError(
                f"{who}la distance {label} {distance:g} m est hors de la zone couverte par les "
                f"{FAMILY_PLURALS[family]} du projet ({zone[0]:g} à {zone[1]:g} m)."
            )

    def _initial_project_distance(self, cursor: sqlite3.Cursor, project_id: int, distance: float,
                                  profile_name: Optional[str] = None, check_zone: bool = True) -> float:
        """Distance projet d'un profil qui arrive dans un scénario sans en avoir : sa distance
        existante. Si elle sort de la zone couverte par les points durs projet (lit projet
        plus court), ProjectDistanceOutOfZoneError : elle doit être fournie (sauf sans
        contrôle de zone, cf. import_project)."""
        zone = distance_zone(self._hard_points(cursor, project_id, PROJECT))
        if not check_zone or zone is None or zone[0] - 1e-6 <= distance <= zone[1] + 1e-6:
            return distance
        raise ProjectDistanceOutOfZoneError(profile_name, distance, zone)

    def _project_of_scenario(self, cursor: sqlite3.Cursor, scenario_id: int) -> int:
        row = cursor.execute("SELECT project_id FROM scenarios WHERE id = ?", (scenario_id,)).fetchone()
        if row is None:
            raise ValueError(f"Le scénario (ID {scenario_id}) est introuvable.")
        return row["project_id"]

    def profile_slope_info(self, profile_id: int) -> Dict[str, Dict]:
        """Pente calculée d'un profil pour l'onglet Hydraulique, selon le profil sur lequel
        porte le calcul : {EXISTING: info, PROJECT: info}, chaque info valant {"slope":
        valeur ou None, "segment": libellé du tronçon ou None, "reason": pourquoi aucun calcul
        n'est possible}, calculée avec la famille de points durs et la distance de ce lit."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            row = cursor.execute(
                """SELECT p.distance, p.project_distance, s.project_id FROM profiles p
                   JOIN scenarios s ON s.id = p.scenario_id WHERE p.id = ?""", (profile_id,)
            ).fetchone()
            if row is None:
                return {family: {"slope": None, "segment": None, "reason": "profil introuvable"}
                        for family in FAMILIES}
            points = self._hard_points(cursor, row["project_id"])
            info = {}
            for family in FAMILIES:
                slope, segment, reason = computed_slope(of_family(points, family),
                                                        row[self._distance_column(family)], family)
                info[family] = {"slope": slope, "segment": segment.label if segment else None, "reason": reason}
        return info

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
                raise ValueError(self._project_exists_message(conn, new_name))
            new_project_id = cursor.lastrowid
            cursor.execute(
                """INSERT INTO hard_points (project_id, name, pk, z, family)
                   SELECT ?, name, pk, z, family FROM hard_points WHERE project_id = ? ORDER BY id""",
                (new_project_id, project_id),
            )

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
        """Copie tous les profils d'un scénario dans un autre : mêmes noms, distances
        (existante et projet) et données (profil existant, profil projet, hydraulique). Ce
        sont de nouvelles lignes avec leur propre JSON : les modifier ensuite n'a aucun effet
        sur la source."""
        cursor.execute(
            """INSERT INTO profiles (scenario_id, name, distance, project_distance, existing_data, project_params)
               SELECT ?, name, distance, project_distance, existing_data, project_params
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

    def get_longitudinal_orthonormal(self, scenario_id: int) -> bool:
        """Case « Échelle orthonormée » du profil en long du scénario : cochée ou non
        (décochée pour un scénario introuvable)."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT longitudinal_orthonormal FROM scenarios WHERE id = ?", (scenario_id,)
            ).fetchone()
        return bool(row and row["longitudinal_orthonormal"])

    def set_longitudinal_orthonormal(self, scenario_id: int, orthonormal: bool) -> None:
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE scenarios SET longitudinal_orthonormal = ? WHERE id = ?",
                (int(bool(orthonormal)), scenario_id),
            )
            conn.commit()

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

    @staticmethod
    def _profile_name_taken(cursor: sqlite3.Cursor, scenario_id: int, name: str) -> bool:
        return cursor.execute(
            "SELECT 1 FROM profiles WHERE scenario_id = ? AND name = ?", (scenario_id, name)
        ).fetchone() is not None

    def profile_name_taken(self, scenario_id: int, name: str) -> bool:
        """Un profil du scénario porte-t-il déjà ce nom ? (Nom unique par scénario.)"""
        with self._get_connection() as conn:
            return self._profile_name_taken(conn.cursor(), scenario_id, name)

    def create_profile(self, scenario_id: int, name: str, distance: float,
                       project_distance: Optional[float] = None) -> int:
        """Crée un profil vide dans un scénario et retourne son ID. Nom et distance
        (existante) sont uniques par scénario : ValueError si l'un des deux est déjà pris.
        La distance projet vaut par défaut la distance existante, à fournir si elle sort de
        la zone projet (cf. _initial_project_distance) ; chacune doit rester dans la zone de
        sa famille de points durs."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if self._profile_name_taken(cursor, scenario_id, name):
                raise ValueError(f"Le profil « {name} » existe déjà dans ce scénario.")

            self._check_distance_in_zone(cursor, scenario_id, distance)
            if project_distance is None:
                project_distance = self._initial_project_distance(
                    cursor, self._project_of_scenario(cursor, scenario_id), distance, name)
            else:
                self._check_distance_in_zone(cursor, scenario_id, project_distance, family=PROJECT)
            try:
                cursor.execute(
                    """INSERT INTO profiles (scenario_id, name, distance, project_distance, existing_data, project_params)
                       VALUES (?, ?, ?, ?, '{}', '{}')""",
                    (scenario_id, name, distance, project_distance)
                )
            except sqlite3.IntegrityError as e:
                if "FOREIGN KEY" in str(e):
                    raise ValueError(f"Le scénario (ID {scenario_id}) est introuvable.")
                raise ValueError(f"La distance {distance} existe déjà dans ce scénario.")
            profile_id = cursor.lastrowid
            # Nouveau profil : pente calculée d'après les points durs du lit sur lequel porte
            # son calcul hydraulique (le lit projet, par défaut). Sans zone (moins de deux
            # points durs complets), il naît en pente imposée, sans message : il n'a jamais
            # été en pente calculée.
            project_id = self._project_of_scenario(cursor, scenario_id)
            if distance_zone(self._hard_points(cursor, project_id, self._slope_family({}))) is None:
                cursor.execute("UPDATE profiles SET project_params = ? WHERE id = ?",
                               (json.dumps({"slope_mode": SLOPE_IMPOSED}), profile_id))
                self.last_slope_report = SlopeReport()
            else:
                self.last_slope_report = self._refresh_slopes(cursor, project_id, [profile_id])
            conn.commit()
            return profile_id

    def save_profile_state(self, profile_id: int, existing_data: List[Dict], project_params: Dict) -> None:
        """Auto-save : Met à jour les données d'un profil spécifique."""
        self._save_state("profiles", profile_id, existing_data, project_params)
        logging.info(f"Auto-save réussi pour le profil ID {profile_id}.")

    def load_profile_state(self, profile_id: int) -> Tuple[List[Dict], Dict]:
        """Charge l'état d'un profil (Points existants et Paramètres projet)."""
        return self._load_state("profiles", profile_id)

    def rename_profile(self, profile_id: int, new_name: str) -> None:
        """Renomme un profil (nom unique dans son scénario). Ses distances se modifient en
        haut des onglets Profil existant et Profil projet (cf. set_profile_distance)."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT 1 FROM profiles WHERE id = ?", (profile_id,)).fetchone()
            if row is None:
                raise ValueError(f"Le profil (ID {profile_id}) est introuvable.")
            try:
                conn.execute("UPDATE profiles SET name = ? WHERE id = ?", (new_name, profile_id))
            except sqlite3.IntegrityError:
                raise ValueError(f"Le profil « {new_name} » existe déjà dans ce scénario.")
            conn.commit()

    def get_profile_project_id(self, profile_id: int) -> Optional[int]:
        """Projet auquel appartient un profil (pour ses points durs), ou None."""
        with self._get_connection() as conn:
            row = conn.execute(
                """SELECT s.project_id FROM profiles p JOIN scenarios s ON s.id = p.scenario_id
                   WHERE p.id = ?""", (profile_id,)
            ).fetchone()
        return row["project_id"] if row else None

    def get_profile_distances(self, profile_id: int) -> Optional[Tuple[float, float]]:
        """(distance existante, distance projet) d'un profil, ou None s'il est introuvable."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT distance, project_distance FROM profiles WHERE id = ?", (profile_id,)
            ).fetchone()
        return (row["distance"], row["project_distance"]) if row else None

    def set_profile_distance(self, profile_id: int, distance: float, family: str = EXISTING) -> SlopeReport:
        """Modifie la distance d'un profil le long d'un lit : existante (`family` EXISTING,
        unique dans le scénario) ou projet (PROJECT), bornée par la zone couverte par cette
        famille de points durs (ValueError sinon). Sa pente calculée suit, si elle porte
        sur ce lit ; le bilan est retourné (et conservé dans last_slope_report)."""
        column = self._distance_column(family)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            row = cursor.execute("SELECT scenario_id FROM profiles WHERE id = ?", (profile_id,)).fetchone()
            if row is None:
                raise ValueError(f"Le profil (ID {profile_id}) est introuvable.")
            self._check_distance_in_zone(cursor, row["scenario_id"], distance, family=family)
            try:
                cursor.execute(f"UPDATE profiles SET {column} = ? WHERE id = ?", (distance, profile_id))
            except sqlite3.IntegrityError:
                raise ValueError(f"La distance existante {distance:g} m est déjà celle d'un autre profil "
                                 "de ce scénario.")
            report = self._refresh_slopes(cursor, self._project_of_scenario(cursor, row["scenario_id"]), [profile_id])
            conn.commit()
        self.last_slope_report = report
        return report

    def duplicate_profile(self, profile_id: int, new_name: str, new_distance: float,
                          project_distance: Optional[float] = None) -> int:
        """Duplique un profil dans le même scénario, sous un nouveau nom et une nouvelle
        distance existante ; sa distance projet est `project_distance`, ou par défaut celle
        d'un nouveau profil (cf. _initial_project_distance)."""
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

        # Copie avec ses paramètres, dont le mode de pente ; une pente calculée est ensuite
        # recalculée pour la nouvelle distance.
        existing_data, project_params = self.load_profile_state(profile_id)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            self._check_distance_in_zone(cursor, scenario_id, new_distance)
            if project_distance is None:
                project_distance = self._initial_project_distance(
                    cursor, self._project_of_scenario(cursor, scenario_id), new_distance, new_name)
            else:
                self._check_distance_in_zone(cursor, scenario_id, project_distance, new_name, PROJECT)
            cursor.execute(
                """INSERT INTO profiles (scenario_id, name, distance, project_distance, existing_data, project_params)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (scenario_id, new_name, new_distance, project_distance,
                 json.dumps(existing_data), json.dumps(project_params)),
            )
            new_profile_id = cursor.lastrowid
            self.last_slope_report = self._refresh_slopes(
                cursor, self._project_of_scenario(cursor, scenario_id), [new_profile_id]
            )
            conn.commit()
        return new_profile_id

    def get_longitudinal_data(self, scenario_id: int) -> List[Tuple[float, float, float, str, float]]:
        """Pour le profil en long d'un scénario : un quintuplet (distance existante,
        altitude mini du TN existant, anchor_z du projet, nom du profil, distance projet) par
        profil du scénario, trié par distance existante croissante. Les profils sans points
        existants, ou sans paramètres projet enregistrés, renvoient None sur la valeur
        manquante plutôt que d'être exclus entièrement."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT name, distance, project_distance, existing_data, project_params
                   FROM profiles WHERE scenario_id = ?""",
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

            result.append((distance, min_z_existing, anchor_z_project, row["name"], row["project_distance"]))

        result.sort(key=lambda t: t[0])
        return result

    def get_scenario_profile_states(self, scenario_id: int) -> List[Dict]:
        """État enregistré de chaque profil du scénario — {name, distance, project_distance,
        existing_data, project_params} — trié par distance (existante) croissante. Sert au
        calcul des déblais / remblais de tous les profils, affichés sur le profil en long."""
        with self._get_connection() as conn:
            rows = conn.execute(
                """SELECT name, distance, project_distance, existing_data, project_params
                   FROM profiles WHERE scenario_id = ?""",
                (scenario_id,)
            ).fetchall()
        states = [
            {
                "name": row["name"],
                "distance": row["distance"],
                "project_distance": row["project_distance"],
                "existing_data": json.loads(row["existing_data"]) if row["existing_data"] else [],
                "project_params": json.loads(row["project_params"]) if row["project_params"] else {},
            }
            for row in rows
        ]
        states.sort(key=lambda state: state["distance"])
        return states

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

    # --- EXPORT / IMPORT (JSON) ---
    #
    # Trois niveaux, chacun avec sa propre "forme" JSON : un profil ("profile", nom +
    # distance + état complet), un scénario ("scenario", nom + tous ses profils) et un
    # projet ("project", nom + points durs + tous ses scénarios). La collecte (méthodes
    # `_export_*_fields`) réutilise les mêmes accesseurs que la duplication en base
    # (load_profile_state / load_draft_state / get_hard_points) : mêmes données, mais
    # rassemblées en un dict JSON-sérialisable plutôt que recopiées par SQL directement
    # d'une table à l'autre. L'insertion (méthodes `_import_*_fields`) est le pendant
    # symétrique, et sert aussi bien à l'import depuis un fichier qu'à la copie interne
    # Draft → Scénario (cf. copy_draft_to_scenario), qui ne fait qu'enchaîner collecte et
    # insertion en mémoire, sans jamais toucher au disque.

    @staticmethod
    def _resolve_name_collision(existing_names: set, desired_name: str) -> str:
        """Si `desired_name` n'est pas déjà pris, le renvoie tel quel. Sinon, essaie
        "<nom> - importé", puis "<nom> - importé (2)", "(3)", etc. jusqu'à trouver un nom
        libre. Fonction pure : ne touche pas la base, réutilisable pour les noms de
        profil (dans un scénario ou dans Draft), de scénario (dans un projet) et de
        projet (globalement)."""
        if desired_name not in existing_names:
            return desired_name

        candidate = f"{desired_name} - importé"
        if candidate not in existing_names:
            return candidate

        n = 2
        while True:
            candidate = f"{desired_name} - importé ({n})"
            if candidate not in existing_names:
                return candidate
            n += 1

    @staticmethod
    def _resolve_distance_collision(existing_distances: set, desired_distance: float) -> float:
        """Pendant de _resolve_name_collision pour la distance, elle aussi UNIQUE par
        scénario : si elle est déjà prise, on la décale par pas de 0.001 m (la précision
        de saisie de l'application, cf. ui.sidebar._DISTANCE_DECIMALS) jusqu'à trouver une
        valeur libre. Ne sert plus qu'à l'import d'un scénario ou d'un projet, dont les
        profils arrivent dans un scénario neuf (collision quasi impossible) ; un profil
        importé seul dans un scénario existant laisse le choix à l'utilisateur (cf.
        _place_profile_in_scenario). Les distances existantes sont arrondies avant
        comparaison pour ignorer les écarts de représentation flottante d'un aller-retour
        JSON."""
        existing_rounded = {round(d, 3) for d in existing_distances}
        candidate = round(desired_distance, 3)
        while candidate in existing_rounded:
            candidate = round(candidate + 0.001, 3)
        return candidate

    def _export_profile_fields(self, profile_id: int) -> Dict:
        """Champs d'un profil de scénario (nom, distances existante et projet, état
        complet), sans l'enveloppe "type"/"version" : la forme utilisée aussi bien pour
        l'export d'un profil seul que nichée dans l'export d'un scénario ou d'un projet."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT name, distance, project_distance FROM profiles WHERE id = ?", (profile_id,)
            ).fetchone()
        if row is None:
            raise ValueError(f"Le profil (ID {profile_id}) est introuvable.")
        existing_data, project_params = self.load_profile_state(profile_id)
        return {"name": row["name"], "distance": row["distance"], "project_distance": row["project_distance"],
                "existing_data": existing_data, "project_params": project_params}

    def _export_profile_fields_from_draft(self, draft_id: int) -> Dict:
        """Comme _export_profile_fields, pour un brouillon de la zone Draft : même forme
        "profile", mais les distances valent None (un brouillon n'en a pas)."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT name FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        if row is None:
            raise ValueError(f"Le brouillon (ID {draft_id}) est introuvable.")
        existing_data, project_params = self.load_draft_state(draft_id)
        return {"name": row["name"], "distance": None, "project_distance": None,
                "existing_data": existing_data, "project_params": project_params}

    def _export_scenario_fields(self, scenario_id: int) -> Dict:
        with self._get_connection() as conn:
            row = conn.execute("SELECT name FROM scenarios WHERE id = ?", (scenario_id,)).fetchone()
            if row is None:
                raise ValueError(f"Le scénario (ID {scenario_id}) est introuvable.")
            profile_ids = [r["id"] for r in conn.execute(
                "SELECT id FROM profiles WHERE scenario_id = ? ORDER BY id", (scenario_id,)
            )]
        return {"name": row["name"], "profiles": [self._export_profile_fields(pid) for pid in profile_ids]}

    def _export_project_fields(self, project_id: int) -> Dict:
        with self._get_connection() as conn:
            row = conn.execute("SELECT name FROM projects WHERE id = ?", (project_id,)).fetchone()
            if row is None:
                raise ValueError(f"Le projet (ID {project_id}) est introuvable.")
            scenario_ids = [r["id"] for r in conn.execute(
                "SELECT id FROM scenarios WHERE project_id = ? ORDER BY id", (project_id,)
            )]
        def points(family):
            return [{k: p[k] for k in ("name", "pk", "z")} for p in self.get_hard_points(project_id, family)]

        # Points durs existants sous l'ancienne clé, points durs projet sous une clé à part
        # (cf. _EXPORT_VERSION) : une version antérieure de l'application lit le lit existant.
        return {
            "name": row["name"],
            "hard_points": points(EXISTING),
            "project_hard_points": points(PROJECT),
            "scenarios": [self._export_scenario_fields(sid) for sid in scenario_ids],
        }

    def export_profile(self, profile_id: int) -> Dict:
        """Représentation JSON-sérialisable d'un profil de scénario, prête à être écrite
        sur le disque (cf. export_profile_to_file) ou réimportée directement."""
        return {"type": "profile", "version": _EXPORT_VERSION, **self._export_profile_fields(profile_id)}

    def export_draft(self, draft_id: int) -> Dict:
        """Comme export_profile, pour un brouillon de la zone Draft."""
        return {"type": "profile", "version": _EXPORT_VERSION,
                **self._export_profile_fields_from_draft(draft_id)}

    def export_scenario(self, scenario_id: int) -> Dict:
        """Représentation JSON-sérialisable d'un scénario et de tous ses profils."""
        return {"type": "scenario", "version": _EXPORT_VERSION, **self._export_scenario_fields(scenario_id)}

    def export_project(self, project_id: int) -> Dict:
        """Représentation JSON-sérialisable d'un projet complet : points durs, tous ses
        scénarios et tous leurs profils."""
        return {"type": "project", "version": _EXPORT_VERSION, **self._export_project_fields(project_id)}

    def _import_profile_fields_into_scenario(self, cursor: sqlite3.Cursor, scenario_id: int, fields: Dict,
                                             check_zone: bool = True) -> int:
        """Insère un profil (forme "profile", cf. _export_profile_fields) dans un scénario
        comme nouveau profil, en résolvant les collisions de nom et de distance (existante)
        avec ceux déjà présents. Sans distance projet (fichier d'une version antérieure,
        brouillon), elle est initialisée comme pour un nouveau profil (cf.
        _initial_project_distance). Utilisée à l'intérieur d'une transaction déjà ouverte
        par l'appelant (import d'un profil seul, d'un scénario entier, d'un projet entier, ou
        copie Draft → Scénario)."""
        existing = cursor.execute(
            "SELECT name, distance FROM profiles WHERE scenario_id = ?", (scenario_id,)
        ).fetchall()
        name = self._resolve_name_collision({r["name"] for r in existing}, fields["name"])
        # Un profil sans distance (venu d'un brouillon, dans un fichier modifié à la main) :
        # 0.0 par défaut, puis résolution de collision comme pour toute distance importée.
        desired_distance = fields.get("distance")
        distance = self._resolve_distance_collision(
            {r["distance"] for r in existing}, desired_distance if desired_distance is not None else 0.0
        )

        if check_zone:
            self._check_distance_in_zone(cursor, scenario_id, distance, name)
        project_distance = self._imported_project_distance(cursor, scenario_id, fields, distance, name, check_zone)
        cursor.execute(
            """INSERT INTO profiles (scenario_id, name, distance, project_distance, existing_data, project_params)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (scenario_id, name, distance, project_distance,
             json.dumps(fields.get("existing_data") or []), json.dumps(fields.get("project_params") or {})),
        )
        return cursor.lastrowid

    def _imported_project_distance(self, cursor: sqlite3.Cursor, scenario_id: int, fields: Dict,
                                   distance: float, name: str, check_zone: bool = True) -> float:
        """Distance projet d'un profil importé ou copié : celle du fichier (vérifiée comme
        la distance existante), ou, s'il n'en a pas (version antérieure, brouillon), celle
        d'un nouveau profil à `distance` (cf. _initial_project_distance)."""
        project_distance = fields.get("project_distance")
        if project_distance is None:
            return self._initial_project_distance(cursor, self._project_of_scenario(cursor, scenario_id),
                                                  distance, name, check_zone)
        if check_zone:
            self._check_distance_in_zone(cursor, scenario_id, project_distance, name, PROJECT)
        return project_distance

    def _import_scenario_fields_into_project(self, cursor: sqlite3.Cursor, project_id: int, fields: Dict,
                                             check_zone: bool = True) -> int:
        """Insère un scénario (forme "scenario", cf. _export_scenario_fields) et tous ses
        profils dans un projet, en résolvant les collisions de nom de scénario. Chaque
        profil est ensuite inséré un par un via _import_profile_fields_into_scenario, qui
        gère ses propres collisions au sein du scénario tout juste créé (utile si le
        fichier importé contient lui-même deux profils homonymes)."""
        existing_names = {r["name"] for r in cursor.execute(
            "SELECT name FROM scenarios WHERE project_id = ?", (project_id,)
        )}
        name = self._resolve_name_collision(existing_names, fields["name"])

        cursor.execute("INSERT INTO scenarios (project_id, name) VALUES (?, ?)", (project_id, name))
        scenario_id = cursor.lastrowid

        # Profils hors de la zone couverte par les points durs : tout l'import est refusé,
        # avec la liste complète (et non au premier profil en défaut). Une distance projet à
        # demander arrête l'import, qui recommencera avec elle (cf. ProjectDistanceOutOfZoneError).
        out_of_zone = []
        for index, profile_fields in enumerate(fields.get("profiles", [])):
            try:
                self._import_profile_fields_into_scenario(cursor, scenario_id, profile_fields, check_zone)
            except ProjectDistanceOutOfZoneError as e:
                e.profile_index = index
                raise
            except ValueError as e:
                out_of_zone.append(str(e))
        if out_of_zone:
            raise ValueError("Import refusé :\n" + "\n".join(out_of_zone))

        return scenario_id

    def _place_profile_in_scenario(self, cursor: sqlite3.Cursor, scenario_id: int, fields: Dict,
                                   distance: float, replace: bool) -> int:
        """Enregistre un profil importé ou copié (forme "profile") dans un scénario existant,
        à `distance` (arrondie au millimètre, la précision de saisie), et retourne son ID.
        Si un profil du scénario occupe déjà cette distance : DistanceTakenError, ou, avec
        `replace`, ce profil est remplacé. Il garde alors son ID et sa distance existante, et
        prend le nom (rendu unique parmi les autres profils), la distance projet, le profil
        existant et les paramètres du profil importé."""
        distance = round(distance, 3)
        rows = cursor.execute(
            "SELECT id, name, distance FROM profiles WHERE scenario_id = ?", (scenario_id,)
        ).fetchall()
        taken = next((r for r in rows if round(r["distance"], 3) == distance), None)
        if taken is None:
            return self._import_profile_fields_into_scenario(cursor, scenario_id, {**fields, "distance": distance})
        if not replace:
            raise DistanceTakenError(distance, taken["name"])

        name = self._resolve_name_collision({r["name"] for r in rows if r["id"] != taken["id"]}, fields["name"])
        project_distance = self._imported_project_distance(cursor, scenario_id, fields, taken["distance"], name)
        cursor.execute(
            """UPDATE profiles SET name = ?, project_distance = ?, existing_data = ?, project_params = ?,
                                   last_updated = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (name, project_distance, json.dumps(fields.get("existing_data") or []),
             json.dumps(fields.get("project_params") or {}), taken["id"]),
        )
        return taken["id"]

    def import_profile_into_scenario(self, scenario_id: int, data: Dict, distance: Optional[float] = None,
                                     replace: bool = False, project_distance: Optional[float] = None) -> int:
        """Importe un profil (forme "profile", venant de export_profile/export_draft ou
        lu depuis un fichier via read_export_file) dans un scénario existant, comme
        nouveau profil indépendant, à `distance` (par défaut celle du fichier ; un profil
        exporté d'un brouillon n'en a pas, elle doit alors être fournie) et à
        `project_distance` (par défaut celle du fichier, ou la distance existante, cf.
        _imported_project_distance). Le nom est rendu unique automatiquement (cf.
        _resolve_name_collision) ; une distance déjà prise lève DistanceTakenError, sauf avec
        `replace` (cf. _place_profile_in_scenario)."""
        if distance is None:
            distance = data.get("distance")
        if distance is None:
            raise ValueError(f"Le profil « {data['name']} » n'a pas de distance : indiquez-la.")
        if project_distance is not None:
            data = {**data, "project_distance": project_distance}
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if cursor.execute("SELECT 1 FROM scenarios WHERE id = ?", (scenario_id,)).fetchone() is None:
                raise ValueError(f"Le scénario (ID {scenario_id}) est introuvable.")
            new_id = self._place_profile_in_scenario(cursor, scenario_id, data, distance, replace)
            self.last_slope_report = self._refresh_slopes(
                cursor, self._project_of_scenario(cursor, scenario_id), [new_id]
            )
            conn.commit()
            return new_id

    def import_profile_into_drafts(self, data: Dict) -> int:
        """Importe un profil (forme "profile") dans la zone Draft, comme nouveau
        brouillon. La distance éventuelle du fichier est ignorée : un brouillon n'en a
        pas. Renomme automatiquement en cas de collision de nom."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            existing_names = {r["name"] for r in cursor.execute("SELECT name FROM drafts")}
            name = self._resolve_name_collision(existing_names, data["name"])
            cursor.execute(
                "INSERT INTO drafts (name, existing_data, project_params) VALUES (?, ?, ?)",
                (name, json.dumps(data.get("existing_data") or []), json.dumps(data.get("project_params") or {})),
            )
            conn.commit()
            return cursor.lastrowid

    def import_scenario_into_project(self, project_id: int, data: Dict) -> int:
        """Importe un scénario (forme "scenario") et tous ses profils dans un projet
        existant, comme nouveau scénario. Renomme automatiquement en cas de collision de
        nom de scénario (les profils gèrent leurs propres collisions, cf.
        _import_scenario_fields_into_project)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if cursor.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
                raise ValueError(f"Le projet (ID {project_id}) est introuvable.")
            scenario_id = self._import_scenario_fields_into_project(cursor, project_id, data)
            imported = [r["id"] for r in cursor.execute("SELECT id FROM profiles WHERE scenario_id = ?", (scenario_id,))]
            self.last_slope_report = self._refresh_slopes(cursor, project_id, imported)
            conn.commit()
            return scenario_id

    def import_project(self, data: Dict) -> int:
        """Importe un projet (forme "project") comme NOUVEAU projet : jamais fusionné
        dans un projet existant, même si un projet du même nom existe déjà (auquel cas le
        nom est automatiquement renommé, comme les autres collisions à l'import). Points
        durs, scénarios et profils sont tous recréés dans ce nouveau projet."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            existing_names = {r["name"] for r in cursor.execute("SELECT name FROM projects")}
            name = self._resolve_name_collision(existing_names, data["name"])

            cursor.execute("INSERT INTO projects (name) VALUES (?)", (name,))
            project_id = cursor.lastrowid
            for point in self._hard_points_from_export(data):
                cursor.execute(
                    "INSERT INTO hard_points (project_id, name, pk, z, family) VALUES (?, ?, ?, ?, ?)",
                    (project_id, point.get("name"), point.get("pk"), point.get("z"), point["family"]),
                )

            # Les profils viennent avec leurs propres points durs : pas de refus hors zone ;
            # un profil hors zone passe simplement en pente imposée (cf. _refresh_slopes).
            for scenario_fields in data.get("scenarios", []):
                self._import_scenario_fields_into_project(cursor, project_id, scenario_fields, check_zone=False)

            self.last_slope_report = self._refresh_slopes(cursor, project_id)
            conn.commit()
            return project_id

    @classmethod
    def _hard_points_from_export(cls, data: Dict) -> List[Dict]:
        """Points durs d'un fichier d'export de projet, chacun avec sa famille : les points
        durs existants ("hard_points") et projet ("project_hard_points", version 3). Un
        fichier antérieur (versions 1 et 2, un seul lit) n'a que "hard_points" : ses points
        sont repris dans les deux familles, comme à la mise à jour de la base."""
        existing = cls._hard_point_list(data.get("hard_points"))
        project = cls._hard_point_list(data["project_hard_points"]) if "project_hard_points" in data else existing
        return ([{**p, "family": EXISTING} for p in existing]
                + [{**p, "family": PROJECT} for p in project])

    @staticmethod
    def _hard_point_list(hard_points) -> List[Dict]:
        """Une liste de points durs d'un fichier d'export : liste [{name, pk, z}] (version 2
        et suivantes), ou ancien couple {"upstream": {name, x, z}, "downstream": {...}}
        (version 1), converti en liste (amont puis aval, points entièrement vides ignorés)."""
        if isinstance(hard_points, list):
            return [p for p in hard_points if isinstance(p, dict)]
        if isinstance(hard_points, dict):
            converted = []
            for side in ("upstream", "downstream"):
                point = hard_points.get(side) or {}
                if any(point.get(k) is not None for k in ("name", "x", "z")):
                    converted.append({"name": point.get("name"), "pk": point.get("x"), "z": point.get("z")})
            return converted
        return []

    def copy_draft_to_scenario(self, draft_id: int, scenario_id: int, distance: float,
                               replace: bool = False, project_distance: Optional[float] = None) -> int:
        """Copie un brouillon de la zone Draft vers un scénario, comme nouveau profil
        indépendant à `distance` et `project_distance` (un brouillon n'en a pas ; la distance
        projet vaut par défaut la distance existante) : le brouillon source n'est pas
        modifié. Enchaîne exactement la même collecte et la même insertion qu'un
        aller-retour export/import de fichier profil (cf. _export_profile_fields_from_draft
        / _place_profile_in_scenario, dont DistanceTakenError et `replace`), mais
        entièrement en mémoire : rien n'est écrit sur le disque."""
        fields = self._export_profile_fields_from_draft(draft_id)
        fields["project_distance"] = project_distance
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if cursor.execute("SELECT 1 FROM scenarios WHERE id = ?", (scenario_id,)).fetchone() is None:
                raise ValueError(f"Le scénario (ID {scenario_id}) est introuvable.")
            # Un brouillon est toujours en pente imposée (pas de points durs) ; copié dans un
            # scénario dont le projet a des points durs, il passe en pente calculée.
            project_id = self._project_of_scenario(cursor, scenario_id)
            params = fields.get("project_params") or {}
            has_zone = distance_zone(self._hard_points(cursor, project_id, self._slope_family(params))) is not None
            fields["project_params"] = {**params, "slope_mode": SLOPE_COMPUTED if has_zone else SLOPE_IMPOSED}
            new_id = self._place_profile_in_scenario(cursor, scenario_id, fields, distance, replace)
            self.last_slope_report = self._refresh_slopes(
                cursor, self._project_of_scenario(cursor, scenario_id), [new_id]
            )
            conn.commit()
            return new_id

    # --- EXPORT / IMPORT : fichiers .json ---

    @staticmethod
    def _write_export_file(path, data: Dict) -> None:
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def export_profile_to_file(self, profile_id: int, path) -> None:
        self._write_export_file(path, self.export_profile(profile_id))

    def export_draft_to_file(self, draft_id: int, path) -> None:
        self._write_export_file(path, self.export_draft(draft_id))

    def export_scenario_to_file(self, scenario_id: int, path) -> None:
        self._write_export_file(path, self.export_scenario(scenario_id))

    def export_project_to_file(self, project_id: int, path) -> None:
        self._write_export_file(path, self.export_project(project_id))

    @staticmethod
    def read_export_file(path) -> Dict:
        """Lit et valide un fichier d'export .json : renvoie son contenu si son "type" est
        reconnu ("profile", "scenario" ou "project") et qu'il porte un nom, lève
        ValueError sinon (fichier illisible, corrompu, incomplet, ou d'un autre format).
        Le contenu renvoyé est prêt à passer directement à import_profile_into_scenario /
        import_profile_into_drafts / import_scenario_into_project / import_project, selon
        data["type"]."""
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError(f"Impossible de lire le fichier '{path}' : {e}")

        if not isinstance(data, dict) or data.get("type") not in _EXPORT_TYPES:
            raise ValueError(
                f"Le fichier '{path}' n'est pas un export HydroTopo valide "
                "(profil, scénario ou projet)."
            )
        if not data.get("name"):
            raise ValueError(f"Le fichier '{path}' est incomplet : aucun nom.")
        return data
