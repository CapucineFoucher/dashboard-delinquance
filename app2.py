import pandas as pd
import plotly.express as px
import streamlit as st
import requests
from io import BytesIO

st.set_page_config(
    page_title="Dashboard Criminalité France",
    page_icon="🚨",
    layout="wide"
)

# Petit message pour confirmer que l’app se lance
st.write("✅ App démarrée (début de script)")

# ----
# 1. FONCTIONS DE CHARGEMENT
# ----
@st.cache_data
def load_crime_data():
    st.write("➡️ Chargement données criminalité...")
    try:
        url_latest = "https://static.data.gouv.fr/resources/bases-statistiques-communale-departementale-et-regionale-de-la-delinquance-enregistree-par-la-police-et-la-gendarmerie-nationales/20250710-144817/donnee-data.gouv-2024-geographie2025-produit-le2025-06-04.csv.gz"
        df = pd.read_csv(url_latest, sep=";", dtype=str, compression="gzip")
        df["annee"] = pd.to_numeric(df["annee"], errors="coerce")
        df["nombre"] = pd.to_numeric(df["nombre"], errors="coerce")
        df["taux_pour_mille"] = (
            df["taux_pour_mille"]
            .str.replace(",", ".", regex=False)
            .astype(float)
        )
        st.write(f"✅ Criminalité chargée : {df.shape}")
        return df, url_latest
    except Exception as e:
        st.error(f"❌ Erreur load_crime_data : {e}")
        return None, None

@st.cache_data
def load_communes_ref():
    st.write("➡️ Chargement référence communes...")
    try:
        df = pd.read_csv("v_commune_2025.csv", dtype=str)
        st.write(f"✅ Communes chargées : {df.shape}")
        return df[["COM", "LIBELLE"]].rename(columns={"COM": "CODGEO_2025", "LIBELLE": "Commune"})
    except Exception as e:
        st.error(f"❌ Erreur load_communes_ref : {e}")
        return pd.DataFrame(columns=["CODGEO_2025", "Commune"])

@st.cache_data
def load_population_local():
    st.write("➡️ Début load_population_local...")
    try:
        header_cols = pd.read_excel("POPULATION_MUNICIPALE_COMMUNES_FRANCE.xlsx", nrows=0).columns.tolist()
        pop_cols = [c for c in header_cols if c.startswith("p")]
        use_cols = ["codgeo", "libgeo"] + pop_cols
        df_pop = pd.read_excel(
            "POPULATION_MUNICIPALE_COMMUNES_FRANCE.xlsx",
            usecols=use_cols,
            dtype=str,
            nrows=5000   # ⚠️ limite pour test mémoire
        )
        st.write(f"✅ Population chargée (test) : {df_pop.shape}")

        df_long = df_pop.melt(
            id_vars=["codgeo", "libgeo"],
            value_vars=pop_cols,
            var_name="annee",
            value_name="Population"
        )
        df_long["annee"] = df_long["annee"].str.extract(r"p(\d+)_pop").astype(int)
        df_long["annee"] = 2000 + df_long["annee"]
        df_long["codgeo"] = df_long["codgeo"].str.zfill(5)
        df_long["Population"] = pd.to_numeric(df_long["Population"], errors="coerce")

        return df_long.rename(columns={"codgeo": "CODGEO"})
    except Exception as e:
        st.error(f"❌ Erreur load_population_local : {e}")
        return pd.DataFrame(columns=["CODGEO", "annee", "Population"])

def prepare_data():
    st.write("➡️ Début prepare_data()")

    df, source_url = load_crime_data()
    if df is None:
        st.stop()

    communes_ref = load_communes_ref()
    pop_long = load_population_local()

    try:
        df = df.merge(communes_ref, on="CODGEO_2025", how="left")
        df = df.merge(
            pop_long,
            left_on=["CODGEO_2025", "annee"],
            right_on=["CODGEO", "annee"],
            how="left"
        )
        st.write("✅ Merge terminé :", df.shape)
    except Exception as e:
        st.error(f"❌ Erreur merge : {e}")
        st.stop()

    return df, source_url

# ----
# 2. CHARGEMENT DES DONNÉES
# ----
df, source_url = prepare_data()

if df is None or df.empty:
    st.error("❌ Impossible de charger les données.")
    st.stop()

st.success("🎉 Données prêtes ! L’app fonctionne, ajoute maintenant tes visualisations...")

# Pour le moment on arrête ici pour tester le déploiement
st.write(df.head())
