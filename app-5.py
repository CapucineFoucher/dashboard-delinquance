import pandas as pd
import plotly.express as px
import streamlit as st

# Configuration de la page
st.set_page_config(
    page_title="Dashboard Criminalité France",
    page_icon="🚨",
    layout="wide"
)

# ----
# 1. FONCTIONS DE CHARGEMENT (fichiers locaux déjà préparés)
# ----
@st.cache_data
def load_crime_data():
    """Lit le CSV déjà filtré (2016-2024) en local"""
    df = pd.read_csv("crime_2016_2024.csv.gz", sep=";", dtype={"CODGEO_2025": str}, compression="gzip")
    df["annee"] = pd.to_numeric(df["annee"], errors="coerce")
    df["nombre"] = pd.to_numeric(df["nombre"], errors="coerce")
    return df, "crime_2016_2024.csv.gz"


@st.cache_data
def load_communes_ref():
    """Charge la table INSEE des communes"""
    communes_ref = pd.read_csv("v_commune_2025.csv", dtype=str)
    return communes_ref[["COM", "LIBELLE"]].rename(columns={"COM": "CODGEO_2025", "LIBELLE": "Commune"})


@st.cache_data
def load_population_data():
    """Charge les populations prétraitées"""
    df_pop = pd.read_csv("population_long.csv", dtype={"codgeo": str, "annee": int})
    df_pop["codgeo"] = df_pop["codgeo"].str.zfill(5)
    return df_pop.rename(columns={"codgeo": "CODGEO"})


def prepare_data(annee_choice=None, communes_choice=None, dep_choice=None):
    """Merge uniquement sur le sous-ensemble demandé"""
    df_crime, source_url = load_crime_data()
    df_ref = load_communes_ref()
    df_pop = load_population_data()

    df_crime = df_crime.merge(df_ref, on="CODGEO_2025", how="left")

    if annee_choice:
        df_crime = df_crime[df_crime["annee"] == annee_choice]

    if communes_choice:
        df_crime = df_crime[df_crime["Commune"].isin(communes_choice)]

    if dep_choice:
        df_crime = df_crime[df_crime["CODGEO_2025"].str.startswith(dep_choice)]

    df = df_crime.merge(
        df_pop,
        left_on=["CODGEO_2025", "annee"],
        right_on=["CODGEO", "annee"],
        how="left"
    )

    df["taux_calcule_pour_mille"] = (df["nombre"] / df["Population"]) * 1000
    return df, source_url


# ----
# 2. INTERFACE
# ----
st.title("🚨 Dashboard Criminalité France")

crime_raw, source_url = load_crime_data()
communes_ref = load_communes_ref()
pop_data = load_population_data()

st.markdown(f"**Source :** {source_url}")

# --- Filtres sidebar
st.sidebar.header("📂 Filtres")

niveau = st.sidebar.radio("Niveau d'analyse", ["France", "Commune spécifique"])
if niveau == "Commune spécifique":
    commune_choice = st.sidebar.selectbox("Choisir une commune", sorted(communes_ref["Commune"].dropna().unique()))
else:
    commune_choice = None

annee_choice = st.sidebar.selectbox("Année", sorted(crime_raw["annee"].dropna().unique(), reverse=True))
all_indics = ["Tous les crimes confondus"] + sorted(crime_raw["indicateur"].dropna().unique())
indic_choice = st.sidebar.selectbox("Indicateur", all_indics)

communes_compare = st.sidebar.multiselect(
    "Comparer plusieurs communes",
    sorted(communes_ref["Commune"].dropna().unique()),
    default=["Paris", "Lyon", "Marseille"]
)

# ----
# 3. Données filtrées
# ----
df, _ = prepare_data(
    annee_choice=annee_choice,
    communes_choice=[commune_choice] if commune_choice else None
)

if df.empty:
    st.warning("Aucune donnée disponible pour ces filtres")
    st.stop()

# ----
# 4. Onglets (mêmes logiques que ton code actuel)
# ----
tab1, tab2, tab3 = st.tabs(["🗺️ Carte", "📊 Répartition", "🏆 Classements"])

with tab1:
    st.header("🗺️ Carte interactive par département")
    df_map = df.groupby(["DEP", "indicateur"])["nombre"].sum().reset_index()
    if indic_choice == "Tous les crimes confondus":
        df_map_filtered = df_map.groupby("DEP", as_index=False)["nombre"].sum()
    else:
        df_map_filtered = df_map[df_map["indicateur"] == indic_choice]

    if not df_map_filtered.empty:
        fig = px.choropleth_mapbox(
            df_map_filtered,
            geojson="https://france-geojson.gregoiredavid.fr/repo/departements.geojson",
            locations="DEP",
            featureidkey="properties.code",
            color="nombre",
            color_continuous_scale="Reds",
            mapbox_style="carto-positron",
            center={"lat": 46.6, "lon": 2.5},
            zoom=4.5,
        )
        st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.header("📊 Répartition des crimes")
    subset = df.groupby("indicateur", as_index=False)["nombre"].sum()
    st.dataframe(subset)

with tab3:
    st.header("🏆 Classement")
    top = df.groupby("Commune", as_index=False)["nombre"].sum().sort_values("nombre", ascending=False).head(15)
    st.dataframe(top)

st.markdown("---")
st.caption("📊 Dashboard créé avec Streamlit | Données : data.gouv.fr")