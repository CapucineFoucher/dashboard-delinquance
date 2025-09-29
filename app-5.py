import io
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
    if code.startswith("97") or code.startswith("98"):
        return code[:3]
    if code[:2] in ("2A", "2B"):
        return code[:2]
    return code[:2]

# ----------------------------------
# 1) Data loaders
# ----------------------------------
@st.cache_data(show_spinner=False)
def load_crime_data():
    import os

    # Liste des fichiers possibles (ordre de priorité)
    candidate_files = [
        "crime_2016_latest.csv.gz",  # mis à jour automatiquement par GitHub Action
        "crime_2016_2024.csv.gz"     # ancien fichier statique
    ]

    file_to_use = None
    for f in candidate_files:
        if os.path.exists(f):
            file_to_use = f
            break

    if file_to_use is None:
        raise FileNotFoundError(f"Aucun fichier crime trouvé parmi: {candidate_files}")

    df = pd.read_csv(file_to_use, sep=";", compression="gzip", dtype={"CODGEO_2025": str})
    df["annee"]  = pd.to_numeric(df["annee"], errors="coerce")
    df["nombre"] = pd.to_numeric(df["nombre"], errors="coerce")

    if "taux_pour_mille" not in df.columns:
        df["taux_pour_mille"] = pd.NA

    return df, file_to_use

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
    return df, "crime_2016_2024.csv.gz"

# ----------------------------------
# 2) UI - Sidebar
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

df, _ = prepare_data(annee_choice, None if commune_choice=="France" else [commune_choice], dep_choice, False)

if df.empty:
    st.warning("Aucune donnée disponible pour ces filtres.")
    st.stop()

# ----------------------------------
# Export Excel helper
# ----------------------------------
def create_excel_rankings(df_single_year: pd.DataFrame, year: int) -> bytes:
    base = df_single_year.copy()
    agg = (
        base.groupby(["Commune", "CODGEO_2025"], as_index=False)
        .agg(Total_crimes=("nombre", "sum"), Population=("Population", "first"))
    )
    agg["Taux_pour_mille"] = (agg["Total_crimes"] / agg["Population"]) * 1000
    agg.loc[agg["Population"].isna() | (agg["Population"] <= 0), "Taux_pour_mille"] = pd.NA

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        agg.sort_values("Total_crimes", ascending=False).to_excel(writer, index=False, sheet_name="Classement_nombre")
        agg.sort_values("Taux_pour_mille", ascending=False).to_excel(writer, index=False, sheet_name="Classement_taux_1000")
    buffer.seek(0)
    return buffer.getvalue()

st.sidebar.header("📥 Export")
if st.sidebar.button("Générer Excel classements"):
    excel_data = create_excel_rankings(df, annee_choice)
    st.sidebar.download_button(
        label="📊 Télécharger Excel",
        data=excel_data,
        file_name=f"classements_{annee_choice}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ----------------------------------
# Tabs
# ----------------------------------
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "🗺️ Carte", "📊 Répartition", "🏆 Classements",
    "📈 Évolutions", "🔥 Heatmap", "🔍 Recherche", "⚖️ Comparaison"
])

# ---- Tab 1 Carte
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

# ---- Tab 2 Répartition
with tab2:
    st.header("📊 Répartition des crimes")
    if commune_choice == "France":
        if indic_choice == "Tous les crimes confondus":
            subset = df[df["annee"] == annee_choice].groupby("indicateur", as_index=False)["nombre"].sum()
            title = f"Répartition des crimes en France en {annee_choice}"
        else:
            subset = df[(df["annee"] == annee_choice) & (df["indicateur"] == indic_choice)]
            title = f"{indic_choice} en France en {annee_choice}"
    else:
        if indic_choice == "Tous les crimes confondus":
            subset = df[(df["Commune"] == commune_choice) & (df["annee"] == annee_choice)].groupby("indicateur", as_index=False)["nombre"].sum()
            title = f"Répartition des crimes à {commune_choice} en {annee_choice}"
        else:
            subset = df[(df["Commune"] == commune_choice) & (df["annee"] == annee_choice) & (df["indicateur"] == indic_choice)]
            title = f"{indic_choice} à {commune_choice} en {annee_choice}"
    if not subset.empty:
        fig_pie = px.pie(subset, values="nombre", names="indicateur", title=title, hole=0.3)
        fig_pie.update_layout(height=600)
        st.plotly_chart(fig_pie, use_container_width=True)
        st.dataframe(subset.sort_values("nombre", ascending=False))
    else:
        st.warning("Aucune donnée disponible")

# ---- Tab 3 Classements
with tab3:
    st.header("🏆 Classement des communes")
    n_communes = st.slider("Nombre", 10, 100, 15)
    df_year = df[df["annee"] == annee_choice].copy()
    if indic_choice != "Tous les crimes confondus":
        df_year = df_year[df_year["indicateur"] == indic_choice]
    top_nombre = df_year.groupby(["Commune", "CODGEO_2025"], as_index=False).agg(Total_crimes=("nombre", "sum"), Population=("Population", "first")).sort_values("Total_crimes", ascending=False).head(n_communes)
    taux_rank = df_year.groupby(["Commune", "CODGEO_2025"], as_index=False).agg(Total_crimes=("nombre", "sum"), Population=("Population", "first"))
    taux_rank["Taux_pour_mille"] = (taux_rank["Total_crimes"] / taux_rank["Population"]) * 1000
    top_taux = taux_rank.sort_values("Taux_pour_mille", ascending=False).head(n_communes)
    st.dataframe(top_nombre)
    st.dataframe(top_taux)

# ---- Tab 4 Evolutions (corrigé)
with tab4:
    st.header("📈 Évolutions temporelles")
    df_all, _ = prepare_data(
        communes_choice=None if commune_choice=="France" else [commune_choice],
        dep_choice=dep_choice,
        include_all_years=True
    )
    if commune_choice == "France":
        if indic_choice == "Tous les crimes confondus":
            subset_evol = df_all.groupby(["annee","indicateur"])["nombre"].sum().reset_index()
            title_evol = "Évolution des crimes en France"
        else:
            subset_evol = df_all[df_all["indicateur"]==indic_choice].groupby("annee")["nombre"].sum().reset_index()
            subset_evol["indicateur"] = indic_choice
            title_evol = f"Évolution: {indic_choice} en France"
    else:
        if indic_choice == "Tous les crimes confondus":
            subset_evol = df_all[df_all["Commune"]==commune_choice].groupby(["annee","indicateur"])["nombre"].sum().reset_index()
            title_evol = f"Évolution des crimes à {commune_choice}"
        else:
            subset_evol = df_all[(df_all["Commune"]==commune_choice)&(df_all["indicateur"]==indic_choice)].groupby("annee")["nombre"].sum().reset_index()
            subset_evol["indicateur"] = indic_choice
            title_evol = f"Évolution: {indic_choice} à {commune_choice}"
    if not subset_evol.empty:
        fig_line = px.line(subset_evol, x="annee", y="nombre", color="indicateur" if indic_choice=="Tous les crimes confondus" else None, title=title_evol, markers=True)
        fig_line.update_layout(height=600)
        st.plotly_chart(fig_line, use_container_width=True)

# ---- Tab 5 Heatmap
with tab5:
    st.header("🔥 Heatmap")
    subset_heat = df.copy()
    pivot = subset_heat.groupby(["annee","indicateur"])["nombre"].sum().reset_index().pivot(index="indicateur", columns="annee", values="nombre").fillna(0)
    if not pivot.empty:
        fig_heat = px.imshow(pivot, aspect="auto", labels=dict(x="Année", y="Indicateur", color="Nombre"), color_continuous_scale="Reds")
        st.plotly_chart(fig_heat, use_container_width=True)

# ---- Tab 6 Recherche
with tab6:
    st.header("🔍 Recherche")
    search_term = st.text_input("Tapez le nom d'une commune:", placeholder="Ex: Paris ...")
    if search_term:
        matches = communes_ref[communes_ref["Commune"].str.contains(search_term, case=False, na=False)]
        if not matches.empty:
            selected_commune = st.selectbox("Choisir une commune:", matches["Commune"].unique())
            dfx, _ = prepare_data(include_all_years=True)
            commune_data = dfx[dfx["Commune"] == selected_commune]
            evol_commune = commune_data.groupby(["annee","indicateur"])["nombre"].sum().reset_index()
            fig_search = px.line(evol_commune, x="annee", y="nombre", color="indicateur", title=f"Évolution à {selected_commune}")
            st.plotly_chart(fig_search, use_container_width=True)

# ---- Tab 7 Comparaison
with tab7:
    st.header("⚖️ Comparaison")
    communes_compare = st.multiselect("Choisir des communes", sorted(communes_ref["Commune"].dropna().unique()))
    if communes_compare:
        dfc, _ = prepare_data(annee_choice, communes_compare, include_all_years=False)
        fig=px.bar(dfc,x="indicateur",y="nombre",color="Commune",barmode="group")
        st.plotly_chart(fig, use_container_width=True)

# ---- Footer
st.markdown("---")
st.caption("📊 Dashboard par CSF | Données : data.gouv.fr")
