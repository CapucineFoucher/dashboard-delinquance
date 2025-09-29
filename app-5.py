import pandas as pd
import plotly.express as px
import streamlit as st

# ----------------------------------
# Page config
# ----------------------------------
st.set_page_config(
    page_title="Dashboard Criminalité France",
    page_icon="🚨",
    layout="wide",
)

def derive_dep(code: str) -> str:
    if not isinstance(code, str) or len(code) < 2:
        return None
    if code.startswith("97") or code.startswith("98"):  # DOM/TOM
        return code[:3]
    if code[:2] in ("2A", "2B"):                        # Corse
        return code[:2]
    return code[:2]

# ----------------------------------
# 1) Data loaders (cloud-friendly)
# ----------------------------------
@st.cache_data(show_spinner=False)
def load_crime_data():
    df = pd.read_csv("crime_2016_2024.csv.gz", sep=";", compression="gzip", dtype={"CODGEO_2025": str})
    df["annee"]  = pd.to_numeric(df["annee"], errors="coerce")
    df["nombre"] = pd.to_numeric(df["nombre"], errors="coerce")
    if "taux_pour_mille" in df.columns:
        df["taux_pour_mille"] = pd.to_numeric(df["taux_pour_mille"], errors="coerce")
    else:
        df["taux_pour_mille"] = pd.NA
    return df, "crime_2016_2024.csv.gz"

@st.cache_data(show_spinner=False)
def load_communes_ref():
    ref = pd.read_csv("v_commune_2025.csv", dtype=str)
    ref = ref.rename(columns={"COM": "CODGEO_2025", "LIBELLE": "Commune"})
    return ref[["CODGEO_2025", "Commune"]]

@st.cache_data(show_spinner=False)
def load_population_data():
    pop = pd.read_csv("population_long.csv", dtype={"codgeo": str, "annee": int})
    pop["codgeo"] = pop["codgeo"].str.zfill(5)
    pop = pop.rename(columns={"codgeo": "CODGEO"})
    return pop[["CODGEO", "annee", "Population"]]

@st.cache_data(show_spinner=False)
def prepare_data(annee_choice=None, communes_choice=None, dep_choice=None, include_all_years=False):
    crime, source = load_crime_data()
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

    df = crime.merge(
        pop,
        left_on=["CODGEO_2025", "annee"],
        right_on=["CODGEO", "annee"],
        how="left"
    )

    df["taux_calcule_pour_mille"] = (df["nombre"] / df["Population"]) * 1000
    df.loc[df["Population"].isna() | (df["Population"] <= 0), "taux_calcule_pour_mille"] = pd.NA
    return df, source

# ----------------------------------
# 2) UI - Sidebar
# ----------------------------------
st.title("🚨 Dashboard Criminalité France")

with st.spinner("Chargement des données de base…"):
    crime_raw, source_url = load_crime_data()
    communes_ref = load_communes_ref()
    _ = load_population_data()

st.markdown(f"Source des données : {source_url}")

st.sidebar.header("📂 Filtres")
niveau = st.sidebar.radio("Niveau d'analyse", ["France", "Commune spécifique"], key="niveau_radio")

if niveau == "Commune spécifique":
    commune_choice = st.sidebar.selectbox(
        "Choisir une commune",
        sorted(communes_ref["Commune"].dropna().unique()),
        key="commune_select"
    )
else:
    commune_choice = None

annee_choice = st.sidebar.selectbox(
    "Année",
    sorted(crime_raw["annee"].dropna().unique(), reverse=True),
    key="annee_select"
)

all_indics = ["Tous les crimes confondus"] + sorted(crime_raw["indicateur"].dropna().unique())
indic_choice = st.sidebar.selectbox("Indicateur", all_indics, key="indic_select")

deps_from_codes = pd.Series(crime_raw["CODGEO_2025"].dropna().unique()).map(derive_dep).dropna().unique()
deps_available = sorted(deps_from_codes.tolist())
dep_choice = st.sidebar.selectbox("Département (optionnel)", ["Tous"] + deps_available, key="dep_select")
dep_choice = None if dep_choice == "Tous" else dep_choice

# Préparer un df global par défaut
df, _ = prepare_data(
    annee_choice=annee_choice,
    communes_choice=[commune_choice] if commune_choice else None,
    dep_choice=dep_choice,
    include_all_years=False
)
if df.empty:
    st.warning("Aucune donnée disponible pour les filtres choisis.")
    st.stop()

# ----------------------------------
# 3) Tabs
# ----------------------------------
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "🗺️ Carte", "📊 Répartition", "🏆 Classements",
    "📈 Évolutions", "🔥 Heatmap", "🔍 Recherche", "⚖️ Comparaison"
])

# ------ TAB 1 ------
with tab1:
    try:
        st.header("🗺️ Carte interactive par département")
        df_map = df.groupby(["DEP", "indicateur"], dropna=False)["nombre"].sum().reset_index()
        if indic_choice == "Tous les crimes confondus":
            df_map_use = df_map.groupby("DEP", as_index=False)["nombre"].sum()
            title_map = f"Tous crimes confondus - {annee_choice}"
        else:
            df_map_use = df_map[df_map["indicateur"] == indic_choice][["DEP", "nombre"]]
            title_map = f"{indic_choice} - {annee_choice}"
        if not df_map_use.empty:
            fig_map = px.choropleth(
                df_map_use,
                geojson="https://france-geojson.gregoiredavid.fr/repo/departements.geojson",
                locations="DEP",
                featureidkey="properties.code",
                color="nombre",
                color_continuous_scale="Reds",
                title=title_map,
            )
            fig_map.update_geos(fitbounds="locations", visible=False)
            st.plotly_chart(fig_map, width="stretch")
        else:
            st.info("Pas de données cartographiables.")
    except Exception as e:
        st.error("Erreur dans l'onglet Carte")
        st.exception(e)

# ------ TAB 2 ------
with tab2:
    try:
        st.header("📊 Répartition")
        if indic_choice == "Tous les crimes confondus":
            rep = df.groupby("indicateur", as_index=False)["nombre"].sum().sort_values("nombre", ascending=False)
            st.dataframe(rep, width="stretch")
            if not rep.empty:
                st.plotly_chart(px.pie(rep.head(15), values="nombre", names="indicateur", hole=0.3), width="stretch")
        else:
            subset = df[df["indicateur"] == indic_choice]
            st.dataframe(subset.groupby("Commune", as_index=False)["nombre"].sum().sort_values("nombre", ascending=False), width="stretch")
    except Exception as e:
        st.error("Erreur dans l'onglet Répartition")
        st.exception(e)

# ------ TAB 3 ------
with tab3:
    try:
        st.header("🏆 Classements des communes")
        n = st.slider("Nombre de communes à afficher", 10, 100, 15, key="classement_slider")
        df_rank = df if indic_choice == "Tous les crimes confondus" else df[df["indicateur"] == indic_choice]
        rank = df_rank.groupby(["Commune", "CODGEO_2025"], as_index=False).agg(Total_crimes=("nombre","sum"), Population=("Population","first"))
        rank["Taux_pour_mille"] = (rank["Total_crimes"] / rank["Population"]) * 1000
        rank.loc[rank["Population"].isna() | (rank["Population"] <= 0), "Taux_pour_mille"] = pd.NA

        top_nombre = rank.sort_values("Total_crimes", ascending=False).head(n)
        top_taux = rank.dropna(subset=["Taux_pour_mille"]).sort_values("Taux_pour_mille", ascending=False).head(n)

        c1, c2 = st.columns(2)
        with c1: st.dataframe(top_nombre, width="stretch")
        with c2: st.dataframe(top_taux, width="stretch")
    except Exception as e:
        st.error("Erreur dans l'onglet Classements")
        st.exception(e)

# ------ TAB 4 ------
with tab4:
    try:
        st.header("📈 Évolutions temporelles")
        df_evol, _ = prepare_data(communes_choice=[commune_choice] if commune_choice else None, dep_choice=dep_choice, include_all_years=True)
        evol = df_evol.groupby(["annee","indicateur"], as_index=False)["nombre"].sum()
        st.plotly_chart(px.line(evol, x="annee", y="nombre", color="indicateur", markers=True), width="stretch")
    except Exception as e:
        st.error("Erreur dans l'onglet Évolutions")
        st.exception(e)

# ------ TAB 5 ------
with tab5:
    try:
        st.header("🔥 Heatmap Année × Indicateur")
        df_h, _ = prepare_data(communes_choice=[commune_choice] if commune_choice else None, dep_choice=dep_choice, include_all_years=True)
        pivot = df_h.groupby(["annee","indicateur"], as_index=False)["nombre"].sum().pivot(index="indicateur", columns="annee", values="nombre").fillna(0)
        if not pivot.empty:
            st.plotly_chart(px.imshow(pivot, aspect="auto", labels=dict(x="Année", y="Indicateur", color="Nombre"), color_continuous_scale="Reds"), width="stretch")
    except Exception as e:
        st.error("Erreur dans l'onglet Heatmap")
        st.exception(e)

# ------ TAB 6 ------
with tab6:
    try:
        st.header("🔍 Recherche par commune")
        search_term = st.text_input("Tapez le nom d'une commune:", key="recherche_input")
        if search_term:
            matches = communes_ref[communes_ref["Commune"].str.contains(search_term, case=False, na=False)]["Commune"].unique()
            if len(matches) > 0:
                selected_commune = st.selectbox("Choisir une commune:", matches, key="recherche_select")
                dfx_all, _ = prepare_data(include_all_years=True)
                commune_data = dfx_all[dfx_all["Commune"] == selected_commune]
                if not commune_data.empty:
                    st.metric("Total crimes", int(commune_data["nombre"].sum()))
                    evo = commune_data.groupby(["annee","indicateur"], as_index=False)["nombre"].sum()
                    st.plotly_chart(px.line(evo, x="annee", y="nombre", color="indicateur"), width="stretch")
            else:
                st.warning("❌ Aucune commune trouvée")
    except Exception as e:
        st.error("Erreur dans l'onglet Recherche")
        st.exception(e)

# ------ TAB 7 ------
with tab7:
    try:
        st.header("⚖️ Comparaison entre communes")
        communes_compare = st.multiselect("Sélectionner des communes", sorted(communes_ref["Commune"].dropna().unique()), key="compare_select")
        if communes_compare:
            dfc, _ = prepare_data(annee_choice=annee_choice, communes_choice=communes_compare, include_all_years=False)
            if not dfc.empty:
                st.plotly_chart(px.bar(dfc, x="indicateur", y="nombre", color="Commune", barmode="group"), width="stretch")
    except Exception as e:
        st.error("Erreur dans l'onglet Comparaison")
        st.exception(e)

# Footer
st.markdown("---")
st.caption("📊 Dashboard créé avec Streamlit | Données : data.gouv.fr")
