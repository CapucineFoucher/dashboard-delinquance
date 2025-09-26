import pandas as pd
import plotly.express as px
import streamlit as st
import requests
from io import BytesIO
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(
    page_title="Dashboard Criminalité France",
    page_icon="🚨",
    layout="wide"
)

st.title("🚨 Tableau de Bord de la Criminalité en France")
st.write("✅ App démarrée (début de script)")

# ----
# CHARGEMENT DES DONNÉES
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
            dtype=str
        )
        st.write(f"✅ Population chargée : {df_pop.shape}")

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
# CHARGE TOUTES LES DONNÉES
# ----
df, source_url = prepare_data()
if df is None or df.empty:
    st.error("❌ Impossible de charger les données.")
    st.stop()
st.success("🎉 Données prêtes!")

# ----
# SIDEBAR
# ----
annees = sorted(df["annee"].dropna().unique())
annee_selection = st.sidebar.selectbox("📅 Choisir une année :", annees, index=len(annees)-1)
type_infraction = st.sidebar.selectbox("🔎 Choisir un type d'infraction :", sorted(df["infraction"].dropna().unique()))

df_filtered = df[(df["annee"] == annee_selection) & (df["infraction"] == type_infraction)]

# ----
# VIZ: CARTE
# ----
st.write("➡️ Préparation carte choroplèthe...")
try:
    fig_choro = px.choropleth(
        df_filtered,
        geojson="https://france-geojson.gregoiredavid.fr/repo/departements.geojson",
        locations="DEP",
        featureidkey="properties.code",
        color="taux_pour_mille",
        color_continuous_scale="OrRd",
        range_color=(0, df_filtered["taux_pour_mille"].max()),
        title=f"Taux de {type_infraction} pour 1000 hab. en {annee_selection}"
    )
    fig_choro.update_geos(fitbounds="locations", visible=False)
    st.plotly_chart(fig_choro, use_container_width=True)
except Exception as e:
    st.error(f"❌ Erreur carte : {e}")

# ----
# VIZ: TOP 20 COMMUNES
# ----
st.write("➡️ Préparation histogramme top 20 communes...")
try:
    top_communes = df_filtered.groupby("Commune")["taux_pour_mille"].mean().nlargest(20).reset_index()
    fig_top = px.bar(
        top_communes,
        x="Commune", y="taux_pour_mille",
        title=f"Top 20 des communes avec le plus haut taux de {type_infraction} ({annee_selection})"
    )
    st.plotly_chart(fig_top, use_container_width=True)
except Exception as e:
    st.error(f"❌ Erreur top communes : {e}")

# ----
# VIZ: EVOLUTION DANS LE TEMPS
# ----
st.write("➡️ Préparation évolution dans le temps...")
try:
    df_evo = df[df["infraction"] == type_infraction].groupby(["annee"])["taux_pour_mille"].mean().reset_index()
    fig_evo = px.line(
        df_evo,
        x="annee", y="taux_pour_mille",
        title=f"Évolution du taux de {type_infraction} en France"
    )
    st.plotly_chart(fig_evo, use_container_width=True)
except Exception as e:
    st.error(f"❌ Erreur évolution : {e}")
