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

    # Join names and derive DEP
    crime = crime.merge(ref, on="CODGEO_2025", how="left")
    crime["DEP"] = crime["CODGEO_2025"].map(derive_dep)

    # Early filters
    if not include_all_years and annee_choice is not None:
        crime = crime[crime["annee"] == annee_choice]

    if communes_choice:
        crime = crime[crime["Commune"].isin(communes_choice)]

    if dep_choice:
        crime = crime[crime["DEP"] == dep_choice]

    # Merge population on the filtered subset
    df = crime.merge(
        pop,
        left_on=["CODGEO_2025", "annee"],
        right_on=["CODGEO", "annee"],
        how="left"
    )

    # Safe rate calculation
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
    commune_choice = "France"

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

# Prepare the single-year df used by most tabs
df, _ = prepare_data(
    annee_choice=annee_choice,
    communes_choice=None if commune_choice == "France" else [commune_choice],
    dep_choice=dep_choice,
    include_all_years=False
)

if df.empty:
    st.warning("Aucune donnée disponible pour les filtres choisis.")
    st.stop()

# ----------------------------------
# Excel export helper
# ----------------------------------
def create_excel_rankings(df_single_year: pd.DataFrame, year: int) -> bytes:
    # Compute rankings similar to Tab 3
    base = df_single_year.copy()
    # If you want to export for a specific indicator only, filter here based on indic_choice
    # For now, we export "tous indicateurs" aggregated
    agg = (
        base.groupby(["Commune", "CODGEO_2025"], as_index=False)
        .agg(Total_crimes=("nombre", "sum"),
             Population=("Population", "first"))
    )
    agg["Taux_pour_mille"] = (agg["Total_crimes"] / agg["Population"]) * 1000
    agg.loc[agg["Population"].isna() | (agg["Population"] <= 0), "Taux_pour_mille"] = pd.NA

    top_nombre = agg.sort_values("Total_crimes", ascending=False).reset_index(drop=True)
    top_taux = agg.sort_values("Taux_pour_mille", ascending=False).reset_index(drop=True)

    # Write to Excel in memory
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        top_nombre.to_excel(writer, index=False, sheet_name="Classement_nombre")
        top_taux.to_excel(writer, index=False, sheet_name="Classement_taux_1000")
        # Optional: by indicator sheet
        by_indic = (
            base.groupby(["indicateur", "Commune", "CODGEO_2025"], as_index=False)["nombre"].sum()
            .sort_values(["indicateur", "nombre"], ascending=[True, False])
        )
        by_indic.to_excel(writer, index=False, sheet_name="Par_indicateur")
        # Metadata sheet
        meta = pd.DataFrame({
            "Clé": ["Année", "Filtres commune", "Filtre département", "Indicateur (UI)"],
            "Valeur": [year,
                      "France" if commune_choice == "France" else commune_choice,
                      dep_choice if dep_choice else "Tous",
                      indic_choice]
        })
        meta.to_excel(writer, index=False, sheet_name="Infos")
    buffer.seek(0)
    return buffer.getvalue()

# Export Excel
st.sidebar.header("📥 Export")
if st.sidebar.button("Générer Excel classements", key="export_btn"):
    excel_data = create_excel_rankings(df, annee_choice)
    st.sidebar.download_button(
        label="📊 Télécharger Excel",
        data=excel_data,
        file_name=f"classements_{annee_choice}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="export_download"
    )

# ----
# 6. ONGLETS PRINCIPAUX (version proche de ta locale)
# ----
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "🗺️ Carte", "📊 Répartition", "🏆 Classements",
    "📈 Évolutions", "🔥 Heatmap", "🔍 Recherche", "⚖️ Comparaison"
])

# ----
# ONGLET 1: CARTE INTERACTIVE
# ----
with tab1:
    st.header("🗺️ Carte interactive par département")

    # Ton code local groupait aussi par annee; ici df est déjà filtré sur l'année
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
        st.warning("Aucune donnée disponible pour cet indicateur")

# ----
# ONGLET 2: PIE CHART
# ----
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
        if indic_choice == "Tous les crimes confondus":
            subset_top = subset.nlargest(15, "nombre")
            fig_pie = px.pie(subset_top, values="nombre", names="indicateur", title=title, hole=0.3)
        else:
            fig_pie = px.pie(subset, values="nombre", names="indicateur", title=title, hole=0.3)
        fig_pie.update_layout(height=600)
        st.plotly_chart(fig_pie, use_container_width=True)

        st.subheader("📋 Détail des données")
        st.dataframe(subset.sort_values("nombre", ascending=False), use_container_width=True)
    else:
        st.warning("Aucune donnée disponible")

# ----
# ONGLET 3: CLASSEMENTS (AVEC TAUX POUR 1000)
# ----
with tab3:
    st.header("🏆 Classement des communes")
    n_communes = st.slider("Nombre de communes à afficher", 10, 100, 15, key="n_communes")

    df_year = df[df["annee"] == annee_choice].copy()
    if indic_choice != "Tous les crimes confondus":
        df_year = df_year[df_year["indicateur"] == indic_choice]

    top_nombre = (
        df_year.groupby(["Commune", "CODGEO_2025"], as_index=False)
        .agg(Total_crimes=("nombre", "sum"), Population=("Population", "first"))
        .sort_values("Total_crimes", ascending=False)
        .head(n_communes)
    )

    taux_rank = (
        df_year.groupby(["Commune", "CODGEO_2025"], as_index=False)
        .agg(Total_crimes=("nombre", "sum"), Population=("Population", "first"))
    )
    taux_rank["Taux_pour_mille"] = (taux_rank["Total_crimes"] / taux_rank["Population"]) * 1000
    top_taux = taux_rank.sort_values("Taux_pour_mille", ascending=False).head(n_communes)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader(f"Top {n_communes} communes par nombre - {indic_choice} ({annee_choice})")
        st.dataframe(top_nombre.reset_index(drop=True), use_container_width=True)
        if not top_nombre.empty:
            fig_bar_nombre = px.bar(
                top_nombre, x="Commune", y="Total_crimes", color="Total_crimes",
                color_continuous_scale="Blues"
            )
            fig_bar_nombre.update_xaxes(tickangle=45)
            st.plotly_chart(fig_bar_nombre, use_container_width=True)

    with col2:
        st.subheader(f"Top {n_communes} par taux pour 1000 hab. - {indic_choice} ({annee_choice})")
        st.dataframe(top_taux.reset_index(drop=True), use_container_width=True)
        if not top_taux.empty:
            fig_bar_taux = px.bar(
                top_taux, x="Commune", y="Taux_pour_mille", color="Taux_pour_mille",
                color_continuous_scale="Reds"
            )
            fig_bar_taux.update_xaxes(tickangle=45)
            st.plotly_chart(fig_bar_taux, use_container_width=True)

# ----
# ONGLET 4: ÉVOLUTIONS
# ----
with tab4:
    st.header("📈 Évolutions temporelles")

    if commune_choice == "France":
        if indic_choice == "Tous les crimes confondus":
            subset_evol = df.groupby(["annee", "indicateur"])["nombre"].sum().reset_index()
            title_evol = "Évolution des crimes en France"
        else:
            subset_evol = (
                df[df["indicateur"] == indic_choice]
                .groupby(["annee"])["nombre"]
                .sum()
                .reset_index()
            )
            subset_evol["indicateur"] = indic_choice
            title_evol = f"Évolution: {indic_choice} en France"
    else:
        if indic_choice == "Tous les crimes confondus":
            subset_evol = (
                df[df["Commune"] == commune_choice]
                .groupby(["annee", "indicateur"])["nombre"]
                .sum()
                .reset_index()
            )
            title_evol = f"Évolution des crimes à {commune_choice}"
        else:
            subset_evol = (
                df[(df["Commune"] == commune_choice) & (df["indicateur"] == indic_choice)]
                .groupby(["annee"])["nombre"]
                .sum()
                .reset_index()
            )
            subset_evol["indicateur"] = indic_choice
            title_evol = f"Évolution: {indic_choice} à {commune_choice}"

    if not subset_evol.empty:
        if indic_choice == "Tous les crimes confondus":
            fig_line = px.line(subset_evol, x="annee", y="nombre", color="indicateur", title=title_evol)
        else:
            fig_line = px.line(subset_evol, x="annee", y="nombre", title=title_evol, markers=True)
        fig_line.update_layout(height=600)
        st.plotly_chart(fig_line, use_container_width=True)

# ----
# ONGLET 5: HEATMAP
# ----
with tab5:
    st.header("🔥 Heatmap Année × Indicateur")

    if commune_choice == "France":
        subset_heat = df.copy()
        title_heat = "Heatmap des crimes en France"
    else:
        subset_heat = df[df["Commune"] == commune_choice]
        title_heat = f"Heatmap des crimes à {commune_choice}"

    if indic_choice != "Tous les crimes confondus":
        subset_heat = subset_heat[subset_heat["indicateur"] == indic_choice]
        title_heat += f" - {indic_choice}"

    pivot = subset_heat.groupby(["annee", "indicateur"])["nombre"].sum().reset_index()
    heat_matrix = pivot.pivot(index="indicateur", columns="annee", values="nombre").fillna(0)

    if not heat_matrix.empty:
        fig_heat = px.imshow(
            heat_matrix, aspect="auto",
            labels=dict(x="Année", y="Indicateur", color="Nombre"),
            title=title_heat, color_continuous_scale="Reds"
        )
        fig_heat.update_layout(height=800)
        st.plotly_chart(fig_heat, use_container_width=True)

# ----
# ONGLET 6: RECHERCHE (utilise TOUTES les années)
# ----
with tab6:
    st.header("🔍 Recherche par commune")

    search_term = st.text_input("Tapez le nom d'une commune:", placeholder="Ex: Paris, Lyon, Marseille...", key="rech_input")
    if search_term:
        # Utiliser la référence pour des noms propres
        matches = communes_ref[communes_ref["Commune"].str.contains(search_term, case=False, na=False)]["Commune"].unique()
        if len(matches) > 0:
            st.success(f"🎯 {len(matches)} commune(s) trouvée(s)")
            selected_commune = st.selectbox("Choisir une commune:", matches, key="rech_select")
            if selected_commune:
                # Charger toutes les années et filtrer par commune
                dfx_all, _ = prepare_data(include_all_years=True)
                commune_data = dfx_all[dfx_all["Commune"] == selected_commune]

                if not commune_data.empty:
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Total crimes (toutes années)", f"{int(commune_data['nombre'].sum()):,}")
                    with col2:
                        st.metric("Années disponibles", int(commune_data["annee"].nunique()))
                    with col3:
                        st.metric("Types de crimes", int(commune_data["indicateur"].nunique()))

                    st.subheader(f"📊 Détail par année - {selected_commune}")
                    summary = (
                        commune_data.groupby(["annee", "indicateur"])["nombre"]
                        .sum()
                        .reset_index()
                        .pivot(index="indicateur", columns="annee", values="nombre")
                        .fillna(0)
                    )
                    st.dataframe(summary, use_container_width=True)

                    evol_commune = commune_data.groupby(["annee", "indicateur"])["nombre"].sum().reset_index()
                    fig_search = px.line(
                        evol_commune, x="annee", y="nombre", color="indicateur",
                        title=f"Évolution des crimes à {selected_commune}"
                    )
                    st.plotly_chart(fig_search, use_container_width=True)
                else:
                    st.info("Pas de données pour cette commune.")
        else:
            st.warning("❌ Aucune commune trouvée avec ce nom")

# ----
# ONGLET 7: COMPARAISON
# ----
with tab7:
    st.header("⚖️ Comparaison entre communes")

    communes_compare = st.multiselect(
        "Sélectionner des communes",
        sorted(communes_ref["Commune"].dropna().unique()),
        key="compare_multiselect"
    )

    if communes_compare:
        subset_compare, _ = prepare_data(
            annee_choice=annee_choice,
            communes_choice=communes_compare,
            include_all_years=False
        )

        # --- Profil Bar Chart ---
        fig_compare = px.bar(
            subset_compare,
            x="indicateur",
            y="nombre",
            color="Commune",
            barmode="group",
            title=f"Comparaison des communes ({annee_choice})"
        )
        fig_compare.update_layout(xaxis={'categoryorder':'total descending'})
        st.plotly_chart(fig_compare, use_container_width=True)

        # --- Radar Top 8 ---
        top_indics = (
            subset_compare.groupby("indicateur")["nombre"].sum()
            .nlargest(8).index.tolist()
        )
        radar_data = subset_compare[subset_compare["indicateur"].isin(top_indics)]
        radar_pivot = radar_data.pivot_table(index="indicateur", columns="Commune", values="nombre", fill_value=0)
        radar_long = radar_pivot.reset_index().melt(id_vars="indicateur", var_name="Commune", value_name="nombre")

        fig_radar = px.line_polar(
            radar_long,
            r="nombre",
            theta="indicateur",
            color="Commune",
            line_close=True,
            title=f"Radar des crimes (Top {len(top_indics)}) - {annee_choice}"
        )
        st.plotly_chart(fig_radar, use_container_width=True)
    else:
        st.warning("Sélectionne au moins une commune pour comparer.")

# ----
# FOOTER
# ----
st.markdown("---")
st.markdown("**📊 Dashboard créé par CSF avec Streamlit | Données : data.gouv.fr : https://www.data.gouv.fr/datasets/bases-statistiques-communale-departementale-et-regionale-de-la-delinquance-enregistree-par-la-police-et-la-gendarmerie-nationales/**")
