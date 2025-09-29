import io
import os
import gc
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
# Constants
# ----------------------------------
MAX_ROWS = 200_000
DEPARTEMENTS_GEOJSON = "https://france-geojson.gregoiredavid.fr/repo/departements.geojson"

# ----------------------------------
# Helpers
# ----------------------------------
def safe_chart(df, render_fn, *args, **kwargs):
    """Render safely with row limits and error handling"""
    if df is None or df.empty:
        st.info("⚠️ Pas de données à afficher.")
        return
    if len(df) > MAX_ROWS:
        st.warning(f"🚨 Trop de données ({len(df):,} lignes). Veuillez affiner vos filtres.")
        return
    try:
        fig = render_fn(df, *args, **kwargs)
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(f"⚠️ Erreur lors du rendu: {e}")

def derive_dep(code: str) -> str:
    if not isinstance(code, str) or len(code) < 2:
        return None
    if code.startswith("97") or code.startswith("98"):
        return code[:3]
    if code[:2] in ("2A","2B"):
        return code[:2]
    return code[:2]

# ----------------------------------
# Data loaders
# ----------------------------------
@st.cache_data(show_spinner=False)
def load_crime_data():
    candidate_files = ["crime_2016_latest.csv.gz", "crime_2016_2024.csv.gz"]
    file_to_use = next((f for f in candidate_files if os.path.exists(f)), None)
    if file_to_use is None:
        raise FileNotFoundError(f"Aucun fichier trouvé parmi: {candidate_files}")
    df = pd.read_csv(file_to_use, sep=";", compression="gzip", dtype={"CODGEO_2025": str})
    df["annee"]  = pd.to_numeric(df["annee"], errors="coerce")
    df["nombre"] = pd.to_numeric(df["nombre"], errors="coerce")
    if "taux_pour_mille" not in df.columns:
        df["taux_pour_mille"] = pd.NA
    return df, file_to_use

@st.cache_data(show_spinner=False)
def load_communes_ref():
    ref = pd.read_csv("v_commune_2025.csv", dtype=str)
    return ref.rename(columns={"COM":"CODGEO_2025","LIBELLE":"Commune"})[["CODGEO_2025","Commune"]]

@st.cache_data(show_spinner=False)
def load_population_data():
    pop = pd.read_csv("population_long.csv", dtype={"codgeo":str,"annee":int})
    pop["codgeo"] = pop["codgeo"].str.zfill(5)
    return pop.rename(columns={"codgeo":"CODGEO"})[["CODGEO","annee","Population"]]

# ----------------------------------
# Data prep
# ----------------------------------
@st.cache_data(show_spinner=False)
def prepare_data(annee_choice=None, communes_choice=None, dep_choice=None, include_all_years=False):
    crime, _ = load_crime_data()
    ref = load_communes_ref()
    pop = load_population_data()

    crime = crime.merge(ref, on="CODGEO_2025", how="left")
    crime["DEP"] = crime["CODGEO_2025"].map(derive_dep)

    if not include_all_years and annee_choice is not None:
        crime = crime[crime["annee"] == annee_choice]
    if communes_choice:
        crime = crime[crime["Commune"].isin(communes_choice)]
    if dep_choice:
        crime = crime[crime["DEP"] == dep_choice]

    df = crime.merge(pop, left_on=["CODGEO_2025","annee"], right_on=["CODGEO","annee"], how="left")
    df["taux_calcule_pour_mille"] = (df["nombre"] / df["Population"]) * 1000
    df.loc[df["Population"].isna() | (df["Population"] <= 0), "taux_calcule_pour_mille"] = pd.NA
    return df

# --- Cached ranking computation ---
@st.cache_data(show_spinner=False)
def compute_ranking(df, indic_choice, n):
    if indic_choice=="Tous les crimes confondus":
        rank = df.groupby(["Commune","CODGEO_2025"],as_index=False).agg(
            Total_crimes=("nombre","sum"),
            Population=("Population","first")
        )
    else:
        rank = df[df["indicateur"]==indic_choice].groupby(
            ["Commune","CODGEO_2025"],as_index=False
        ).agg(
            Total_crimes=("nombre","sum"),
            Population=("Population","first")
        )
    rank["Taux_pour_mille"] = (rank["Total_crimes"]/rank["Population"])*1000
    result = rank.sort_values("Total_crimes",ascending=False).head(n)
    # free memory
    del rank
    gc.collect()
    return result

# ----------------------------------
# UI
# ----------------------------------
st.title("🚨 Dashboard Criminalité France")
crime_raw, _ = load_crime_data()
communes_ref = load_communes_ref()

st.sidebar.header("📂 Filtres")
niveau = st.sidebar.radio("Niveau d'analyse", ["France","Commune spécifique"])
if niveau=="Commune spécifique":
    commune_choice = st.sidebar.selectbox("Commune", sorted(communes_ref["Commune"].dropna().unique()))
else:
    commune_choice = "France"

annee_choice = st.sidebar.selectbox("Année", sorted(crime_raw["annee"].dropna().unique(), reverse=True))
all_indics = ["Tous les crimes confondus"] + sorted(crime_raw["indicateur"].dropna().unique())
indic_choice = st.sidebar.selectbox("Indicateur", all_indics)

# Tabs
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "🗺️ Carte","📊 Répartition","🏆 Classements",
    "📈 Evolutions","🔥 Heatmap","🔍 Recherche","⚖️ Comparaison"
])

# ----------------------------------
# Tabs content
# ----------------------------------

# ---- Carte
with tab1:
    st.header("🗺️ Carte interactive par département")
    df = prepare_data(annee_choice, None if commune_choice=="France" else [commune_choice])
    df_map = df.groupby(["DEP","indicateur"], dropna=False)["nombre"].sum().reset_index()
    if indic_choice=="Tous les crimes confondus":
        df_map = df_map.groupby("DEP",as_index=False)["nombre"].sum()
    else:
        df_map = df_map[df_map["indicateur"]==indic_choice]
    safe_chart(df_map, lambda d: px.choropleth_mapbox(
        d, geojson=DEPARTEMENTS_GEOJSON,
        locations="DEP", featureidkey="properties.code",
        color="nombre", color_continuous_scale="Reds",
        range_color=(0, d["nombre"].max()),
        mapbox_style="carto-positron",
        zoom=4.5, center={"lat":46.6,"lon":2.5}, opacity=0.7,
        title=f"{indic_choice} {annee_choice}"
    ))

# ---- Répartition
with tab2:
    st.header("📊 Répartition")
    df = prepare_data(annee_choice, None if commune_choice=="France" else [commune_choice])
    if indic_choice=="Tous les crimes confondus":
        subset = df.groupby("indicateur", as_index=False)["nombre"].sum()
    else:
        subset = df[df["indicateur"]==indic_choice]
    if len(subset)>MAX_ROWS:
        st.warning(f"⚠️ Table limitée à {MAX_ROWS:,} lignes")
        subset = subset.head(MAX_ROWS)
    st.dataframe(subset, use_container_width=True)
    if not subset.empty:
        safe_chart(subset, lambda d: px.pie(d, names="indicateur", values="nombre", title="Répartition"))

# ---- Classements
with tab3:
    st.header("🏆 Classements")
    df = prepare_data(annee_choice)
    n = st.slider("Nombre de communes",10,100,15)
    top = compute_ranking(df, indic_choice, n)
    st.dataframe(top,use_container_width=True)

# ---- Evolutions
with tab4:
    st.header("📈 Evolutions temporelles")
    df_all = prepare_data(None, None if commune_choice=="France" else [commune_choice], include_all_years=True)
    if indic_choice=="Tous les crimes confondus":
        top_indics = df_all.groupby("indicateur")["nombre"].sum().nlargest(10).index
        subset = df_all[df_all["indicateur"].isin(top_indics)]
        safe_chart(subset, lambda d: px.line(d,x="annee",y="nombre",color="indicateur",title="Top 10 indicateurs"))
    else:
        subset = df_all[df_all["indicateur"]==indic_choice]
        safe_chart(subset, lambda d: px.line(d,x="annee",y="nombre",title=f"Evolution: {indic_choice}"))

# ---- Heatmap
with tab5:
    st.header("🔥 Heatmap")
    df_h = prepare_data(None, None if commune_choice=="France" else [commune_choice], include_all_years=True)
    pivot = df_h.groupby(["annee","indicateur"], as_index=False)["nombre"].sum().pivot(
        index="indicateur",columns="annee",values="nombre"
    )
    if len(pivot)>50:
        st.info("Heatmap limitée aux 50 indicateurs majeurs")
        pivot = pivot.head(50)
    safe_chart(pivot.reset_index(), lambda d: px.imshow(
        d.set_index("indicateur"),
        aspect="auto",labels=dict(x="Année",y="Indicateur",color="Nombre"),
        color_continuous_scale="Reds"
    ))

# ---- Recherche
with tab6:
    st.header("🔍 Recherche")
    search = st.text_input("Commune à rechercher")
    if search:
        matches = communes_ref[communes_ref["Commune"].str.contains(search,case=False,na=False)]
        if not matches.empty:
            commune_sel = st.selectbox("Choisir", matches["Commune"].unique())
            df_r = prepare_data(None,[commune_sel],include_all_years=True)
            safe_chart(df_r, lambda d: px.line(d,x="annee",y="nombre",color="indicateur",title=f"Evolution {commune_sel}"))
            df_y = df_r[df_r["annee"]==annee_choice]
            safe_chart(df_y, lambda d: px.bar(d,x="indicateur",y="nombre",title=f"{commune_sel} – {annee_choice}"))
            safe_chart(df_y, lambda d: px.pie(d,names="indicateur",values="nombre",title=f"Répartition {commune_sel} – {annee_choice}"))

# ---- Comparaison
with tab7:
    st.header("⚖️ Comparaison")
    communes_compare = st.multiselect("Communes",sorted(communes_ref["Commune"].dropna().unique()))
    if communes_compare:
        dfc = prepare_data(annee_choice, communes_compare)
        safe_chart(dfc, lambda d: px.bar(d,x="indicateur",y="nombre",color="Commune",barmode="group",title=f"Comparaison {annee_choice}"))
        safe_chart(dfc, lambda d: px.line_polar(d,r="nombre",theta="indicateur",color="Commune",line_close=True,title=f"Radar {annee_choice}"))

st.caption("📊 Données: Ministère de l'Intérieur – Data.gouv.fr")
