import io
import pandas as pd
import plotly.express as px
import streamlit as st

# ----------------------------------
# Config
# ----------------------------------
st.set_page_config(
    page_title="Dashboard Criminalité France",
    page_icon="🚨",
    layout="wide",
)

# ----------------------------------
# Global constants
# ----------------------------------
MAX_ROWS = 200_000  # Limite anti-crash (200k lignes max pour un rendu)

# ----------------------------------
# Helper: safe plotting
# ----------------------------------
def safe_chart(df, render_fn, *args, **kwargs):
    """
    Render a chart safely:
    - If df too big, warn instead of crashing
    - Otherwise, call plotting function
    """
    if df is None or df.empty:
        st.info("⚠️ Pas de données à afficher.")
        return
    if len(df) > MAX_ROWS:
        st.warning(
            f"🚨 Trop de données sélectionnées ({len(df):,} lignes). "
            f"Veuillez affiner vos filtres en dessous de {MAX_ROWS:,} lignes."
        )
        return
    try:
        fig = render_fn(df, *args, **kwargs)
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(f"⚠️ Erreur lors du rendu: {e}")

# ----------------------------------
# Loaders
# ----------------------------------
@st.cache_data(show_spinner=False)
def load_crime_data():
    import os
    candidate_files = ["crime_2016_latest.csv.gz", "crime_2016_2024.csv.gz"]
    file_to_use = None
    for f in candidate_files:
        if os.path.exists(f):
            file_to_use = f
            break
    if file_to_use is None:
        raise FileNotFoundError(f"Aucun fichier trouvé parmi: {candidate_files}")

    df = pd.read_csv(file_to_use, sep=";", compression="gzip", dtype={"CODGEO_2025": str})
    df["annee"] = pd.to_numeric(df["annee"], errors="coerce")
    df["nombre"] = pd.to_numeric(df["nombre"], errors="coerce")
    if "taux_pour_mille" not in df.columns:
        df["taux_pour_mille"] = pd.NA
    return df, file_to_use

@st.cache_data(show_spinner=False)
def load_communes_ref():
    ref = pd.read_csv("v_commune_2025.csv", dtype=str)
    return ref.rename(columns={"COM": "CODGEO_2025", "LIBELLE": "Commune"})[["CODGEO_2025","Commune"]]

@st.cache_data(show_spinner=False)
def load_population_data():
    pop = pd.read_csv("population_long.csv", dtype={"codgeo":str,"annee":int})
    pop["codgeo"] = pop["codgeo"].str.zfill(5)
    return pop.rename(columns={"codgeo":"CODGEO"})[["CODGEO","annee","Population"]]

# Pour simplifier : je garde ta fonction prepare_data() comme avant …
# (on suppose qu’elle est déjà implémentée correctement)
from your_previous_code import prepare_data

# ----------------------------------
# UI - Sidebar
# ----------------------------------
st.title("🚨 Dashboard Criminalité France")
crime_raw, _ = load_crime_data()
communes_ref = load_communes_ref()

st.sidebar.header("📂 Filtres")
niveau = st.sidebar.radio("Niveau d'analyse", ["France", "Commune spécifique"])
if niveau == "Commune spécifique":
    commune_choice = st.sidebar.selectbox("Choisir une commune", sorted(communes_ref["Commune"].dropna().unique()))
else:
    commune_choice = "France"

annee_choice = st.sidebar.selectbox("Année", sorted(crime_raw["annee"].dropna().unique(), reverse=True))
all_indics = ["Tous les crimes confondus"] + sorted(crime_raw["indicateur"].dropna().unique())
indic_choice = st.sidebar.selectbox("Indicateur", all_indics)

# ----------------------------------
# Tabs
# ----------------------------------
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "🗺️ Carte", "📊 Répartition", "🏆 Classements",
    "📈 Évolutions", "🔥 Heatmap", "🔍 Recherche", "⚖️ Comparaison"
])

# ---- Carte
with tab1:
    st.header("🗺️ Carte interactive par département")
    df = prepare_data(annee_choice, None if commune_choice=="France" else [commune_choice])
    df_map = df.groupby(["DEP","indicateur"], dropna=False)["nombre"].sum().reset_index()
    if indic_choice == "Tous les crimes confondus":
        df_map = df_map.groupby("DEP", as_index=False)["nombre"].sum()
        title_map = f"Tous crimes {annee_choice}"
    else:
        df_map = df_map[df_map["indicateur"] == indic_choice]
        title_map = f"{indic_choice} {annee_choice}"

    safe_chart(
        df_map,
        lambda d: px.choropleth(
            d,
            geojson="https://france-geojson.gregoiredavid.fr/repo/departements.geojson",
            locations="DEP",
            featureidkey="properties.code",
            color="nombre",
            color_continuous_scale="Reds",
            title=title_map
        )
    )

# ---- Répartition
with tab2:
    st.header("📊 Répartition")
    df = prepare_data(annee_choice, None if commune_choice=="France" else [commune_choice])
    if indic_choice=="Tous les crimes confondus":
        subset = df.groupby("indicateur", as_index=False)["nombre"].sum()
    else:
        subset = df[df["indicateur"] == indic_choice]

    if len(subset) > MAX_ROWS:
        st.warning(f"Trop de lignes ({len(subset):,}), affichage limité à {MAX_ROWS:,}")
        subset = subset.head(MAX_ROWS)
    st.dataframe(subset, use_container_width=True)

# ---- Classements
with tab3:
    st.header("🏆 Classements")
    df = prepare_data(annee_choice)
    n = st.slider("Nombre de communes", 10, 100, 15)
    rank = df.groupby(["Commune","CODGEO_2025"], as_index=False).agg(
        Total_crimes=("nombre","sum"),
        Population=("Population","first")
    )
    rank["Taux_pour_mille"] = (rank["Total_crimes"]/rank["Population"]) * 1000
    top_nombre = rank.sort_values("Total_crimes", ascending=False).head(n)

    if len(top_nombre) > MAX_ROWS:
        st.warning("Table trop grosse, réduite")
        top_nombre = top_nombre.head(MAX_ROWS)

    st.dataframe(top_nombre, use_container_width=True)

# ---- Evolutions
with tab4:
    st.header("📈 Evolutions temporelles")
    df_all = prepare_data(None, None if commune_choice=="France" else [commune_choice], include_all_years=True)
    subset_evol = (
        df_all if indic_choice=="Tous les crimes confondus"
        else df_all[df_all["indicateur"] == indic_choice]
    )
    safe_chart(
        subset_evol,
        lambda d: px.line(d, x="annee", y="nombre", color="indicateur", title="Evolution")
    )

# ---- Heatmap
with tab5:
    st.header("🔥 Heatmap")
    df_h = prepare_data(None, None if commune_choice=="France" else [commune_choice], include_all_years=True)
    pivot = df_h.groupby(["annee","indicateur"], as_index=False)["nombre"].sum().pivot(
        index="indicateur", columns="annee", values="nombre"
    )
    if len(pivot) > 50:
        st.info("Heatmap limitée aux 50 indicateurs les plus fréquents")
        pivot = pivot.head(50)
    safe_chart(
        pivot.reset_index(),
        lambda d: px.imshow(
            d.set_index("indicateur"),
            aspect="auto",
            labels=dict(x="Année", y="Indicateur", color="Nombre"),
            color_continuous_scale="Reds"
        )
    )

# ---- Comparaison
with tab7:
    st.header("⚖️ Comparaison")
    communes_compare = st.multiselect("Choisir des communes", sorted(communes_ref["Commune"].unique()))
    if communes_compare:
        dfc = prepare_data(annee_choice, communes_compare)
        safe_chart(
            dfc,
            lambda d: px.bar(d, x="indicateur", y="nombre", color="Commune", barmode="group")
        )
