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
    # Reads your locally committed, prefiltered file (2016-2024)
    df = pd.read_csv("crime_2016_2024.csv.gz", sep=";", compression="gzip", dtype={"CODGEO_2025": str})
    df["annee"]  = pd.to_numeric(df["annee"], errors="coerce")
    df["nombre"] = pd.to_numeric(df["nombre"], errors="coerce")
    # taux_pour_mille may be missing/blank -> float
    if "taux_pour_mille" in df.columns:
        df["taux_pour_mille"] = pd.to_numeric(df["taux_pour_mille"], errors="coerce")
    else:
        df["taux_pour_mille"] = pd.NA
    return df, "crime_2016_2024.csv.gz"

@st.cache_data(show_spinner=False)
def load_communes_ref():
    ref = pd.read_csv("v_commune_2025.csv", dtype=str)
    ref = ref.rename(columns={"COM": "CODGEO_2025", "LIBELLE": "Commune"})
    # Keep only the essential columns
    return ref[["CODGEO_2025", "Commune"]]

@st.cache_data(show_spinner=False)
def load_population_data():
    # population_long.csv with columns: codgeo, annee, Population
    pop = pd.read_csv("population_long.csv", dtype={"codgeo": str, "annee": int})
    pop["codgeo"] = pop["codgeo"].str.zfill(5)
    pop = pop.rename(columns={"codgeo": "CODGEO"})
    return pop[["CODGEO", "annee", "Population"]]

# ----------------------------------
# 2) Prepare data (merge-on-demand)
# ----------------------------------
@st.cache_data(show_spinner=False)
def prepare_data(annee_choice=None, communes_choice=None, dep_choice=None, include_all_years=False):
    crime, source = load_crime_data()
    ref = load_communes_ref()
    pop = load_population_data()

    # Join commune names
    crime = crime.merge(ref, on="CODGEO_2025", how="left")

    # Compute DEP robustly
    crime["DEP"] = crime["CODGEO_2025"].map(derive_dep)

    # Early filters to reduce memory
    if not include_all_years and annee_choice is not None:
        crime = crime[crime["annee"] == annee_choice]

    if communes_choice:
        crime = crime[crime["Commune"].isin(communes_choice)]

    if dep_choice:
        # Accept both 2-digit (dept) or 3-digit (DOM/TOM) or 2A/2B
        crime = crime[crime["DEP"] == dep_choice]

    # Merge population on the filtered subset
    df = crime.merge(
        pop,
        left_on=["CODGEO_2025", "annee"],
        right_on=["CODGEO", "annee"],
        how="left"
    )

    # Safe rate calculation (avoid divide-by-zero / NaN)
    df["taux_calcule_pour_mille"] = (df["nombre"] / df["Population"]) * 1000
    df.loc[df["Population"].isna() | (df["Population"] <= 0), "taux_calcule_pour_mille"] = pd.NA

    return df, source

# ----------------------------------
# 3) UI
# ----------------------------------
st.title("🚨 Dashboard Criminalité France")

with st.spinner("Chargement des données de base…"):
    crime_raw, source_url = load_crime_data()
    communes_ref = load_communes_ref()
    _ = load_population_data()

st.markdown(f"Source des données : {source_url}")

# Sidebar filters (CREATE VARIABLES FIRST)
st.sidebar.header("📂 Filtres")
niveau = st.sidebar.radio("Niveau d'analyse", ["France", "Commune spécifique"])

if niveau == "Commune spécifique":
    commune_choice = st.sidebar.selectbox(
        "Choisir une commune",
        sorted(communes_ref["Commune"].dropna().unique())
    )
else:
    commune_choice = None

annee_choice = st.sidebar.selectbox(
    "Année",
    sorted(crime_raw["annee"].dropna().unique(), reverse=True)
)

all_indics = ["Tous les crimes confondus"] + sorted(crime_raw["indicateur"].dropna().unique())
indic_choice = st.sidebar.selectbox("Indicateur", all_indics)

deps_from_codes = pd.Series(crime_raw["CODGEO_2025"].dropna().unique()).map(derive_dep).dropna().unique()
deps_available = sorted(deps_from_codes.tolist())
dep_choice = st.sidebar.selectbox("Département (optionnel)", ["Tous"] + deps_available)
dep_choice = None if dep_choice == "Tous" else dep_choice

# NOW USE THE VARIABLES ✅
with st.spinner("Préparation des données filtrées…"):
    df, _ = prepare_data(
        annee_choice=annee_choice,
        communes_choice=[commune_choice] if commune_choice else None,
        dep_choice=dep_choice,
        include_all_years=False
    )

# Ensure DEP exists even if upstream code changed
if "DEP" not in df.columns or df["DEP"].isna().all():
    base_code_col = "CODGEO_2025" if "CODGEO_2025" in df.columns else ("CODGEO" if "CODGEO" in df.columns else None)
    if base_code_col is not None:
        df["DEP"] = df[base_code_col].map(derive_dep)

if df.empty:
    st.warning("Aucune donnée disponible pour les filtres choisis.")
    st.stop()

# Tabs
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "🗺️ Carte", "📊 Répartition", "🏆 Classements",
    "📈 Évolutions", "🔥 Heatmap", "🔍 Recherche", "⚖️ Comparaison"
])

# ----------------------------------
# Tab 1: Carte (single year)
# ----------------------------------
with tab1:
    st.header("🗺️ Carte interactive par département")
    df_map_src, _ = prepare_data(
        annee_choice=annee_choice,
        communes_choice=[commune_choice] if commune_choice else None,
        dep_choice=dep_choice,
        include_all_years=False
    )
    if "DEP" not in df_map_src or df_map_src["DEP"].isna().all():
        base_code_col = "CODGEO_2025" if "CODGEO_2025" in df_map_src else ("CODGEO" if "CODGEO" in df_map_src else None)
        if base_code_col:
            df_map_src["DEP"] = df_map_src[base_code_col].map(derive_dep)

    if df_map_src.empty:
        st.info("Pas de données cartographiables pour ces filtres.")
    else:
        df_map = df_map_src.groupby(["DEP", "indicateur"], dropna=False)["nombre"].sum().reset_index()
        if indic_choice == "Tous les crimes confondus":
            df_map_use = df_map.groupby("DEP", as_index=False)["nombre"].sum()
            title_map = f"Tous crimes confondus - {annee_choice}"
        else:
            df_map_use = df_map[df_map["indicateur"] == indic_choice][["DEP", "nombre"]]
            title_map = f"{indic_choice} - {annee_choice}"

        if not df_map_use.empty and df_map_use["DEP"].notna().any():
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
            fig_map.update_layout(height=560, margin=dict(l=10, r=10, t=50, b=10))
            st.plotly_chart(fig_map, width="stretch")
        else:
            st.info("Pas de données cartographiables pour ces filtres.")

# ----------------------------------
# Tab 2: Répartition (single year)
# ----------------------------------
with tab2:
    st.header("📊 Répartition")
    df_rep, _ = prepare_data(
        annee_choice=annee_choice,
        communes_choice=[commune_choice] if (commune_choice and commune_choice != "France") else None,
        dep_choice=dep_choice,
        include_all_years=False
    )
    if df_rep.empty:
        st.info("Aucune donnée disponible pour ces filtres.")
    else:
        if indic_choice == "Tous les crimes confondus":
            rep = df_rep.groupby("indicateur", as_index=False)["nombre"].sum().sort_values("nombre", ascending=False)
            st.dataframe(rep, width="stretch")
            if not rep.empty:
                st.plotly_chart(
                    px.pie(rep.head(15), values="nombre", names="indicateur", hole=0.3, title="Top 15 catégories"),
                    width="stretch"
                )
        else:
            subset = df_rep[df_rep["indicateur"] == indic_choice]
            table = subset.groupby("Commune", as_index=False)["nombre"].sum().sort_values("nombre", ascending=False)
            st.dataframe(table, width="stretch")

# ----------------------------------
# Tab 3: Classements (single year)
# ----------------------------------
with tab3:
    st.header("🏆 Classements des communes")
    n = st.slider("Nombre de communes à afficher", 10, 100, 15)
    df_rank_src, _ = prepare_data(
        annee_choice=annee_choice,
        dep_choice=dep_choice,
        communes_choice=None if (commune_choice is None or commune_choice == "France") else [commune_choice],
        include_all_years=False
    )
    if indic_choice != "Tous les crimes confondus":
        df_rank_src = df_rank_src[df_rank_src["indicateur"] == indic_choice]
    if df_rank_src.empty:
        st.info("Pas de données pour le classement.")
    else:
        rank = (
            df_rank_src.groupby(["Commune", "CODGEO_2025"], as_index=False)
            .agg(Total_crimes=("nombre", "sum"), Population=("Population", "first"))
        )
        rank["Taux_pour_mille"] = (rank["Total_crimes"] / rank["Population"]) * 1000
        rank.loc[rank["Population"].isna() | (rank["Population"] <= 0), "Taux_pour_mille"] = pd.NA

        top_nombre = rank.sort_values("Total_crimes", ascending=False).head(n)
        top_taux = rank.dropna(subset=["Taux_pour_mille"]).sort_values("Taux_pour_mille", ascending=False).head(n)

        c1, c2 = st.columns(2)
        with c1:
            st.subheader(f"Top {n} par nombre - {indic_choice} ({annee_choice})")
            st.dataframe(top_nombre.reset_index(drop=True), width="stretch")
            if not top_nombre.empty:
                st.plotly_chart(
                    px.bar(top_nombre, x="Commune", y="Total_crimes", color="Total_crimes", color_continuous_scale="Blues"),
                    width="stretch"
                )
        with c2:
            st.subheader(f"Top {n} par taux pour 1000 - {indic_choice} ({annee_choice})")
            st.dataframe(top_taux.reset_index(drop=True), width="stretch")
            if not top_taux.empty:
                st.plotly_chart(
                    px.bar(top_taux, x="Commune", y="Taux_pour_mille", color="Taux_pour_mille", color_continuous_scale="Reds"),
                    width="stretch"
                )

# ----------------------------------
# Tab 4: Évolutions (all years)
# ----------------------------------
with tab4:
    st.header("📈 Évolutions temporelles")
    df_evol, _ = prepare_data(
        communes_choice=[commune_choice] if (commune_choice and commune_choice != "France") else None,
        dep_choice=dep_choice,
        include_all_years=True
    )
    if df_evol.empty:
        st.info("Pas de série temporelle disponible.")
    else:
        if indic_choice == "Tous les crimes confondus":
            evol = df_evol.groupby(["annee", "indicateur"], as_index=False)["nombre"].sum()
            title_e = "Évolution des crimes (France)" if not commune_choice or commune_choice == "France" else f"Évolution des crimes ({commune_choice})"
        else:
            evol = (
                df_evol[df_evol["indicateur"] == indic_choice]
                .groupby(["annee"], as_index=False)["nombre"].sum()
            )
            evol["indicateur"] = indic_choice
            title_e = f"Évolution: {indic_choice}"
        st.plotly_chart(px.line(evol, x="annee", y="nombre", color="indicateur", markers=True, title=title_e), width="stretch")

# ----------------------------------
# Tab 5: Heatmap (all years)
# ----------------------------------
with tab5:
    st.header("🔥 Heatmap Année × Indicateur")
    df_h, _ = prepare_data(
        communes_choice=[commune_choice] if (commune_choice and commune_choice != "France") else None,
        dep_choice=dep_choice,
        include_all_years=True
    )
    if df_h.empty:
        st.info("Heatmap indisponible pour ces filtres.")
    else:
        pivot = (
            df_h.groupby(["annee", "indicateur"], as_index=False)["nombre"].sum()
            .pivot(index="indicateur", columns="annee", values="nombre")
            .fillna(0)
        )
        if not pivot.empty:
            st.plotly_chart(
                px.imshow(pivot, aspect="auto", labels=dict(x="Année", y="Indicateur", color="Nombre"), color_continuous_scale="Reds"),
                width="stretch"
            )
        else:
            st.info("Heatmap indisponible pour ces filtres.")

# ----------------------------------
# Tab 6: Recherche (all years; name filter applied after)
# ----------------------------------
with tab6:
    st.header("🔍 Recherche par commune")
    search_term = st.text_input("Tapez le nom d'une commune:", placeholder="Ex: Paris, Lyon…")
    if search_term:
        matches = communes_ref[communes_ref["Commune"].str.contains(search_term, case=False, na=False)]["Commune"].unique()
        if len(matches) == 0:
            st.warning("❌ Aucune commune trouvée avec ce nom")
        else:
            selected_commune = st.selectbox("Choisir une commune:", matches)
            if selected_commune:
                dfx_all, _ = prepare_data(include_all_years=True)
                commune_data = dfx_all[dfx_all["Commune"] == selected_commune].copy()
                if commune_data.empty:
                    st.info("Pas de données pour cette commune.")
                else:
                    col1, col2, col3 = st.columns(3)
                    with col1: st.metric("Total crimes (toutes années)", f"{int(commune_data['nombre'].sum()):,}")
                    with col2: st.metric("Années disponibles", int(commune_data["annee"].nunique()))
                    with col3: st.metric("Types de crimes", int(commune_data["indicateur"].nunique()))
                    summary = (
                        commune_data.groupby(["annee", "indicateur"], as_index=False)["nombre"].sum()
                        .pivot(index="indicateur", columns="annee", values="nombre").fillna(0)
                    )
                    st.dataframe(summary, width="stretch")
                    evo = (
                        commune_data.groupby(["annee", "indicateur"], as_index=False)["nombre"].sum()
                        .sort_values(["indicateur", "annee"])
                    )
                    st.plotly_chart(px.line(evo, x="annee", y="nombre", color="indicateur", markers=True,
                                            title=f"Évolution des crimes à {selected_commune}"),
                                    width="stretch")

# ----------------------------------
# Tab 7: Comparaison (single year)
# ----------------------------------
with tab7:
    st.header("⚖️ Comparaison entre communes")
    communes_compare = st.multiselect(
        "Sélectionner des communes",
        sorted(communes_ref["Commune"].dropna().unique()),
        default=[]
    )
    if communes_compare:
        dfc, _ = prepare_data(
            annee_choice=annee_choice,
            communes_choice=communes_compare,
            dep_choice=None,
            include_all_years=False
        )
        if not dfc.empty:
            st.plotly_chart(
                px.bar(dfc, x="indicateur", y="nombre", color="Commune", barmode="group", title=f"Comparaison - {annee_choice}"),
                width="stretch"
            )
            top_indics = dfc.groupby("indicateur")["nombre"].sum().nlargest(8).index.tolist()
            radar = dfc[dfc["indicateur"].isin(top_indics)].pivot_table(index="indicateur", columns="Commune", values="nombre", fill_value=0).reset_index()
            radar_long = radar.melt(id_vars="indicateur", var_name="Commune", value_name="nombre")
            st.plotly_chart(px.line_polar(radar_long, r="nombre", theta="indicateur", color="Commune", line_close=True, title="Radar Top 8"), width="stretch")
    else:
        st.info("Ajoutez au moins une commune pour comparer.")

# ----------------------------------
st.markdown("---")
st.caption("📊 Dashboard créé avec Streamlit | Données : data.gouv.fr")
