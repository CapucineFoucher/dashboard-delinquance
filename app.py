import pandas as pd
import plotly.express as px
import streamlit as st
from io import BytesIO

# Configuration de la page
st.set_page_config(
    page_title="Dashboard Criminalité France",
    page_icon="🚨",
    layout="wide"
)

# ----
# 1. FONCTIONS DE CHARGEMENT
# ----
@st.cache_data
def load_crime_data():
    """Charge les données de criminalité depuis l'API data.gouv.fr (version latest)"""
    url_latest = "https://static.data.gouv.fr/resources/bases-statistiques-communale-departementale-et-regionale-de-la-delinquance-enregistree-par-la-police-et-la-gendarmerie-nationales/20250710-144817/donnee-data.gouv-2024-geographie2025-produit-le2025-06-04.csv.gz"

    df = pd.read_csv(url_latest, sep=";", dtype=str, compression="gzip")
    df["annee"] = pd.to_numeric(df["annee"], errors="coerce")
    df["nombre"] = pd.to_numeric(df["nombre"], errors="coerce")

    df["taux_pour_mille"] = (
        df["taux_pour_mille"]
        .str.replace(",", ".", regex=False)
        .astype(float)
    )
    return df, url_latest


@st.cache_data
def load_communes_ref():
    """Charge la table de référence INSEE des communes"""
    communes_ref = pd.read_csv("v_commune_2025.csv", dtype=str)
    return communes_ref[["COM", "LIBELLE"]].rename(columns={"COM": "CODGEO_2025", "LIBELLE": "Commune"})


@st.cache_data
def load_population_local():
    cols_to_use = ["codgeo", "libgeo"]
    header_cols = pd.read_excel("POPULATION_MUNICIPALE_COMMUNES_FRANCE.xlsx", nrows=0).columns.tolist()
    pop_cols = [c for c in header_cols if c.startswith("p")]
    use_cols = cols_to_use + pop_cols

    df_pop = pd.read_excel("POPULATION_MUNICIPALE_COMMUNES_FRANCE.xlsx", usecols=use_cols, dtype=str)

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

    max_year = df_long["annee"].max()
    for year in range(max_year + 1, 2025):
        extrap = df_long[df_long["annee"] == max_year].copy()
        extrap["annee"] = year
        df_long = pd.concat([df_long, extrap])

    return df_long.rename(columns={"codgeo": "CODGEO"})


def prepare_data():
    df, source_url = load_crime_data()
    if df is None:
        return None, None

    communes_ref = load_communes_ref()
    pop_long = load_population_local()

    df = df.merge(communes_ref, on="CODGEO_2025", how="left")
    df = df.merge(
        pop_long,
        left_on=["CODGEO_2025", "annee"],
        right_on=["CODGEO", "annee"],
        how="left"
    )

    df["DEP"] = df["CODGEO_2025"].str[:2]
    mask_dom = df["CODGEO_2025"].str.startswith(("97", "98"))
    df.loc[mask_dom, "DEP"] = df["CODGEO_2025"].str[:3]
    df.loc[df["DEP"] == "20", "DEP"] = df["CODGEO_2025"].str[:3]

    df["taux_calcule_pour_mille"] = (df["nombre"] / df["Population"]) * 1000

    return df, source_url


# ----
# 2. DONNÉES
# ----
df, source_url = prepare_data()

if df is None:
    st.error("Impossible de charger les données. Vérifiez votre connexion internet.")
    st.stop()

# ----
# 3. INTERFACE
# ----
st.title("🚨 Dashboard Criminalité France")
st.markdown(f"**Source :** {source_url}")

# Sidebar
st.sidebar.header("📂 Filtres")

niveau = st.sidebar.radio("Niveau d'analyse", ["France", "Commune spécifique"])
if niveau == "Commune spécifique":
    commune_choice = st.sidebar.selectbox("Choisir une commune", sorted(df["Commune"].dropna().unique()))
else:
    commune_choice = "France"

annee_choice = st.sidebar.selectbox("Année", sorted(df["annee"].dropna().unique()))
all_indics = ["Tous les crimes confondus"] + sorted(df["indicateur"].dropna().unique())
indic_choice = st.sidebar.selectbox("Indicateur", all_indics)

communes_compare = st.sidebar.multiselect(
    "Comparer plusieurs communes",
    sorted(df["Commune"].dropna().unique()),
    default=["Paris", "Lyon", "Marseille"]
)

st.sidebar.header("📥 Export")
if st.sidebar.button("Générer Excel classements"):
    excel_data = BytesIO()
    st.sidebar.download_button(
        label="📊 Télécharger Excel",
        data=excel_data.getvalue(),
        file_name=f"classements_{annee_choice}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ----
# 4. ONGLET PRINCIPAL
# ----
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "🗺️ Carte", "📊 Répartition", "🏆 Classements",
    "📈 Évolutions", "🔥 Heatmap", "🔍 Recherche", "⚖️ Comparaison"
])

# ONGLET 1
with tab1:
    st.header("🗺️ Carte interactive par département")
    df_map = df.groupby(["annee", "DEP", "indicateur"])["nombre"].sum().reset_index()
    if indic_choice == "Tous les crimes confondus":
        df_map_filtered = df_map.groupby(["annee", "DEP"], as_index=False)["nombre"].sum()
        title_map = "Évolution: Tous les crimes confondus"
    else:
        df_map_filtered = df_map[df_map["indicateur"] == indic_choice]
        title_map = f"Évolution: {indic_choice}"

    if not df_map_filtered.empty:
        fig_map = px.choropleth_mapbox(
            df_map_filtered,
            geojson="https://france-geojson.gregoiredavid.fr/repo/departements.geojson",
            locations="DEP",
            featureidkey="properties.code",
            color="nombre",
            color_continuous_scale="Reds",
            mapbox_style="carto-positron",
            center={"lat": 46.6, "lon": 2.5},
            zoom=4.5,
            opacity=0.7,
            hover_name="DEP",
            title=title_map
        )
        fig_map.update_layout(height=600)
        st.plotly_chart(fig_map, use_container_width=True)
    else:
        st.warning("Aucune donnée disponible")

# ONGLET 2
with tab2:
    st.header("📊 Répartition des crimes")
    # idem code pie chart ...

# ONGLET 3
with tab3:
    st.header("🏆 Classements des communes")
    # idem code classements ...

# ONGLET 4
with tab4:
    st.header("📈 Évolutions temporelles")
    # idem évolutions ...

# ONGLET 5
with tab5:
    st.header("🔥 Heatmap Année × Indicateur")
    # idem heatmap ...

# ONGLET 6
with tab6:
    st.header("🔍 Recherche par commune")
    # idem recherche ...

# ONGLET 7
with tab7:
    st.header("⚖️ Comparaison entre communes")
    # idem comparaison ...


# ----
# FOOTER
# ----
st.markdown("---")
st.markdown("**📊 Dashboard créé par CSF avec Streamlit | Données : data.gouv.fr**")
