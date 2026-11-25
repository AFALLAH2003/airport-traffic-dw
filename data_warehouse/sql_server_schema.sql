-- ============================================================================
-- Schéma SQL Server - Entrepôt de Données : P1 - Trafic aérien ONDA (Maroc)
-- Compatible SQL Server (T-SQL) + SSAS (Multidimensionnel / Tabulaire) + SSRS
-- ============================================================================

IF DB_ID('DW_Trafic_Aerien_ONDA') IS NULL
    CREATE DATABASE DW_Trafic_Aerien_ONDA;
GO
USE DW_Trafic_Aerien_ONDA;
GO

-- 1. Dimensions
CREATE TABLE dbo.Dim_Aeroport (
    id_aeroport   INT           NOT NULL PRIMARY KEY,
    code_iata     VARCHAR(10)   NOT NULL,
    code_icao     VARCHAR(10)   NOT NULL,
    nom_aeroport  NVARCHAR(100) NOT NULL,
    nom_complet   NVARCHAR(150) NOT NULL,
    ville         NVARCHAR(100) NOT NULL,
    region        NVARCHAR(100) NOT NULL,
    iso_region    VARCHAR(10)   NOT NULL,
    type_aeroport VARCHAR(30)   NOT NULL,
    latitude_deg  DECIMAL(10,6) NOT NULL,
    longitude_deg DECIMAL(10,6) NOT NULL
);

CREATE TABLE dbo.Dim_Temps (
    id_temps                       INT          NOT NULL PRIMARY KEY, -- YYYYMM
    date_debut_mois                DATE         NOT NULL,
    annee                          SMALLINT     NOT NULL,
    mois                           TINYINT      NOT NULL,
    nom_mois                       NVARCHAR(20) NOT NULL,
    trimestre                      TINYINT      NOT NULL,
    nom_trimestre                  VARCHAR(5)   NOT NULL,
    semestre                       TINYINT      NOT NULL,
    saison                         NVARCHAR(20) NOT NULL,
    est_periode_covid              BIT          NOT NULL,
    donnees_mensuelles_disponibles BIT          NOT NULL
);

CREATE TABLE dbo.Dim_Type_Trafic (
    id_type_trafic INT          NOT NULL PRIMARY KEY,
    code_type      VARCHAR(10)  NOT NULL,
    libelle_type   NVARCHAR(30) NOT NULL
);

CREATE TABLE dbo.Dim_Zone_Origine (
    id_zone            INT          NOT NULL PRIMARY KEY,
    code_zone          VARCHAR(10)  NOT NULL,
    nom_zone           NVARCHAR(60) NOT NULL,
    est_zone_detaillee BIT          NOT NULL
);

-- 2. Tables de faits
CREATE TABLE dbo.Fact_Trafic_Mensuel (
    id_temps    INT            NOT NULL,
    id_aeroport INT            NOT NULL,
    passagers   INT            NULL,
    mouvements  INT            NULL,
    fret_tonnes DECIMAL(12,3)  NULL,
    CONSTRAINT PK_Fact_Trafic_Mensuel PRIMARY KEY (id_temps, id_aeroport),
    CONSTRAINT FK_Mensuel_Temps       FOREIGN KEY (id_temps)    REFERENCES dbo.Dim_Temps(id_temps),
    CONSTRAINT FK_Mensuel_Aeroport    FOREIGN KEY (id_aeroport) REFERENCES dbo.Dim_Aeroport(id_aeroport)
);

CREATE TABLE dbo.Fact_Trafic_Par_Type (
    id_temps       INT NOT NULL,
    id_aeroport    INT NOT NULL,
    id_type_trafic INT NOT NULL,
    passagers      INT NOT NULL,
    CONSTRAINT PK_Fact_Trafic_Par_Type PRIMARY KEY (id_temps, id_aeroport, id_type_trafic),
    CONSTRAINT FK_Type_Temps           FOREIGN KEY (id_temps)       REFERENCES dbo.Dim_Temps(id_temps),
    CONSTRAINT FK_Type_Aeroport        FOREIGN KEY (id_aeroport)    REFERENCES dbo.Dim_Aeroport(id_aeroport),
    CONSTRAINT FK_Type_TypeTrafic      FOREIGN KEY (id_type_trafic) REFERENCES dbo.Dim_Type_Trafic(id_type_trafic)
);

CREATE TABLE dbo.Fact_Trafic_Par_Zone (
    id_temps    INT NOT NULL,
    id_aeroport INT NOT NULL,
    id_zone     INT NOT NULL,
    passagers   INT NOT NULL,
    CONSTRAINT PK_Fact_Trafic_Par_Zone PRIMARY KEY (id_temps, id_aeroport, id_zone),
    CONSTRAINT FK_Zone_Temps           FOREIGN KEY (id_temps)    REFERENCES dbo.Dim_Temps(id_temps),
    CONSTRAINT FK_Zone_Aeroport        FOREIGN KEY (id_aeroport) REFERENCES dbo.Dim_Aeroport(id_aeroport),
    CONSTRAINT FK_Zone_Origine         FOREIGN KEY (id_zone)     REFERENCES dbo.Dim_Zone_Origine(id_zone)
);

CREATE TABLE dbo.Fact_Trafic_Zone_Global (
    id_temps  INT NOT NULL,
    id_zone   INT NOT NULL,
    passagers INT NOT NULL,
    CONSTRAINT PK_Fact_Trafic_Zone_Global PRIMARY KEY (id_temps, id_zone),
    CONSTRAINT FK_ZoneGlobal_Temps        FOREIGN KEY (id_temps) REFERENCES dbo.Dim_Temps(id_temps),
    CONSTRAINT FK_ZoneGlobal_Zone         FOREIGN KEY (id_zone)  REFERENCES dbo.Dim_Zone_Origine(id_zone)
);

CREATE TABLE dbo.Fact_Trafic_Annuel (
    annee       SMALLINT      NOT NULL,
    id_aeroport INT           NOT NULL,
    passagers   INT           NULL,
    mouvements  INT           NULL,
    fret_tonnes DECIMAL(12,3) NULL,
    source      VARCHAR(30)   NOT NULL,
    CONSTRAINT PK_Fact_Trafic_Annuel PRIMARY KEY (annee, id_aeroport),
    CONSTRAINT FK_Annuel_Aeroport    FOREIGN KEY (id_aeroport) REFERENCES dbo.Dim_Aeroport(id_aeroport)
);

CREATE TABLE dbo.Fact_Trafic_Zone_Annuel (
    annee     SMALLINT    NOT NULL,
    id_zone   INT         NOT NULL,
    passagers INT         NOT NULL,
    source    VARCHAR(30) NOT NULL,
    CONSTRAINT PK_Fact_Trafic_Zone_Annuel PRIMARY KEY (annee, id_zone),
    CONSTRAINT FK_ZoneAnnuel_Zone         FOREIGN KEY (id_zone) REFERENCES dbo.Dim_Zone_Origine(id_zone)
);

CREATE TABLE dbo.Fact_Top_Routes (
    id_temps       INT            NOT NULL,
    scope_aeroport VARCHAR(10)    NOT NULL,
    rang           TINYINT        NOT NULL,
    route          NVARCHAR(100)  NOT NULL,
    passagers      INT            NULL,
    part_pct       DECIMAL(8,4)   NULL,
    CONSTRAINT PK_Fact_Top_Routes PRIMARY KEY (id_temps, scope_aeroport, rang),
    CONSTRAINT FK_Routes_Temps    FOREIGN KEY (id_temps) REFERENCES dbo.Dim_Temps(id_temps)
);
GO
