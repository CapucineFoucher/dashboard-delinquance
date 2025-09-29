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

def derive_dep(code: str) -> str:
    if not isinstance(code, str) or len(code) < 2:
        return None
    if code.startswith("97") or code.startswith("98"):
        return code[:3]
    if code[:2] in ("2A", "2B"):
        return code[:2]
    return code[:2]

# ----------------------------------
# Loaders
# ----------------------------------
@st.cache_data(show_spinner=False)
def load_crime_data():
    df = pd.read_csv("crime_2016_2024.csv.gz", sep=";", compression="gzip", dtype={"CODGEO_2025": str})
    df["annee"]  = pd.to_numeric(df["annee"], errors="coerce")
    df["nombre"] = pd.to_numeric(df["nombre"], errors="coerce")
    if "taux_pour_mille" not in df.columns:
        df["taux_pour_mille"] = pd.NA
    return df, "crime_2016_2024.csv.gz"

@st.cache_data(show_spinner=False)
def load_communes_ref():
    ref = pd.read_csv("v_commune_2025.csv", dtype=str)
    return ref.rename(columns={"COM": "CODGEO_2025", "LIBELLE": "Commune"})[["CODGEO_2025", "Commune"]]

@st.cache_data(show_spinner=False)
def load_population_data():
    pop = pd.read_csv("population_long.csv", dtype={"codgeo": str, "annee": int})
    pop["codgeo"] = pop["codgeo"].str.zfill(5)
    return pop.rename(columns={"codgeo": "CODGEO"})[["CODGEO", "annee", "Population"]]

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

    df = crime.merge(pop, left_on=["CODGEO_2025", "annee"], right_on=["CODGEO", "annee"], how="left")
    df["taux_calcule_pour_mille"] = (df["nombre"] / df["Population"]) * 1000
    df.loc[df["Population"].isna() | (df["Population"] <= 0), "taux_calcule_pour_mille"] = pd.NA
    return df

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

deps = pd.Series(crime_raw["CODGEO_2025"].dropna().unique()).map(derive_dep).dropna().unique()
dep_choice = st.sidebar.selectbox("Département", ["Tous"] + sorted(deps.tolist()))
dep_choice = None if dep_choice == "Tous" else dep_choice

df = prepare_data(annee_choice, None if commune_choice=="France" else [commune_choice], dep_choice, False)

if df.empty:
    st.warning("Aucune donnée disponible pour ces filtres.")
    st.stop()

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
    df_map = df.groupby(["DEP","indicateur"], dropna=False)["nombre"].sum().reset_index()
    if indic_choice == "Tous les crimes confondus":
        df_map = df_map.groupby("DEP", as_index=False)["nombre"].sum()
        title_map = "Tous crimes confondus " + str(annee_choice)
    else:
        df_map = df_map[df_map["indicateur"]==indic_choice]
        title_map = indic_choice+" "+str(annee_choice)
    if not df_map.empty:
        fig = px.choropleth(
            df_map, geojson="https://france-geojson.gregoiredavid.fr/repo/departements.geojson",
            locations="DEP", featureidkey="properties.code",
            color="nombre", color_continuous_scale="Reds", title=title_map
        )
        fig.update_geos(fitbounds="locations", visible=False)
        st.plotly_chart(fig, width="stretch")

# ---- Répartition
with tab2:
    st.header("📊 Répartition")
    if indic_choice=="Tous les crimes confondus":
        subset = df.groupby("indicateur", as_index=False)["nombre"].sum().sort_values("nombre",ascending=False)
    else:
        subset = df[df["indicateur"]==indic_choice]
    subset_disp = subset.copy()
    if len(subset_disp)>200:
        st.info(f"Affichage limité à 200 lignes sur {len(subset_disp)}")
        subset_disp = subset_disp.head(200)
    st.dataframe(subset_disp, use_container_width=True)

# ---- Classements
with tab3:
    st.header("🏆 Classements des communes")
    n = st.slider("Nombre",10,100,15)
    df_rank = df if indic_choice=="Tous les crimes confondus" else df[df["indicateur"]==indic_choice]
    rank = df_rank.groupby(["Commune","CODGEO_2025"],as_index=False).agg(
        Total_crimes=("nombre","sum"), Population=("Population","first"))
    rank["Taux_pour_mille"]=(rank["Total_crimes"]/rank["Population"])*1000
    top_nombre = rank.sort_values("Total_crimes",ascending=False).head(n)
    top_taux = rank.sort_values("Taux_pour_mille",ascending=False).head(n)
    st.dataframe(top_nombre,use_container_width=True)

# ---- Evolutions (fixé)
with tab4:
    st.header("📈 Évolutions temporelles")
    df_all = prepare_data(None,None if commune_choice=="France" else [commune_choice],dep_choice,True)
    if indic_choice=="Tous les crimes confondus":
        evo = df_all.groupby(["annee","indicateur"],as_index=False)["nombre"].sum()
        fig = px.line(evo,x="annee",y="nombre",color="indicateur")
    else:
        evo = df_all[df_all["indicateur"]==indic_choice].groupby("annee",as_index=False)["nombre"].sum()
        fig = px.line(evo,x="annee",y="nombre",markers=True,title=indic_choice)
    st.plotly_chart(fig,width="stretch")

# ---- Heatmap
with tab5:
    st.header("🔥 Heatmap")
    df_h = prepare_data(None,None if commune_choice=="France" else [commune_choice],dep_choice,True)
    pivot = df_h.groupby(["annee","indicateur"],as_index=False)["nombre"].sum().pivot(
        index="indicateur",columns="annee",values="nombre").fillna(0)
    if len(pivot)>50:
        st.info(f"Heatmap limitée à 50 indicateurs (sur {len(pivot)})")
        pivot = pivot.sort_values(pivot.columns[-1],ascending=False).head(50)
    fig = px.imshow(pivot,aspect="auto",labels=dict(x="Année",y="Indicateur",color="Nombre"),color_continuous_scale="Reds")
    st.plotly_chart(fig,width="stretch")

# ---- Recherche
with tab6:
    st.header("🔍 Recherche")
    search = st.text_input("Chercher une commune:")
    if search:
        matches = communes_ref[communes_ref["Commune"].str.contains(search,case=False,na=False)]
        if not matches.empty:
            commune_sel = st.selectbox("Choisir",matches["Commune"].unique())
            dfx=prepare_data(None,[commune_sel],None,True)
            evol=dfx.groupby(["annee","indicateur"],as_index=False)["nombre"].sum()
            fig=px.line(evol,x="annee",y="nombre",color="indicateur",title=f"Évolution {commune_sel}")
            st.plotly_chart(fig,width="stretch")

# ---- Comparaison
with tab7:
    st.header("⚖️ Comparaison")
    communes_compare=st.multiselect("Choisir des communes",sorted(communes_ref["Commune"].dropna().unique()))
    if communes_compare:
        dfc=prepare_data(annee_choice,communes_compare,None,False)
        fig=px.bar(dfc,x="indicateur",y="nombre",color="Commune",barmode="group")
        st.plotly_chart(fig,width="stretch")

st.markdown("---")
st.caption("📊 Dashboard CSF – Données data.gouv.fr")
