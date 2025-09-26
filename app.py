import pandas as pd
import plotly.express as px
import streamlit as st
import requests
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

    # conversions
    df["annee"] = pd.to_numeric(df["annee"], errors="coerce")
    df["nombre"] = pd.to_numeric(df["nombre"], errors="coerce")

    # ⚡ CORRECTION : forcer la conversion de 'taux_pour_mille'
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
    # Charger le fichier Excel INSEE pop
    df_pop = pd.read_excel("POPULATION_MUNICIPALE_COMMUNES_FRANCE.xlsx", dtype=str)
    
    # Garder uniquement les colonnes utiles (p13_pop … p21_pop)
    pop_cols = [c for c in df_pop.columns if c.startswith("p")]
    
    # Reshape en format long (commune × année)
    df_long = df_pop.melt(
        id_vars=["codgeo", "libgeo"],
        value_vars=pop_cols,
        var_name="annee",
        value_name="Population"
    )
    
    # Nettoyage : année "p13_pop" -> 2013, etc.
    df_long["annee"] = df_long["annee"].str.extract(r"p(\d+)_pop").astype(int)
    df_long["annee"] = 2000 + df_long["annee"]   # ex: 13 -> 2013
    
    # Harmonisation
    df_long["codgeo"] = df_long["codgeo"].str.zfill(5)
    df_long["Population"] = pd.to_numeric(df_long["Population"], errors="coerce")
    
    # ⚡ Extension population au-delà de 2021 (copie des valeurs 2021)
    max_year = df_long["annee"].max()   # = 2021
    for year in range(max_year+1, 2025):  # 2022 → 2024
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

    # Merge noms de communes
    df = df.merge(communes_ref, on="CODGEO_2025", how="left")

    # Merge population (commune + année)
    df = df.merge(
        pop_long,
        left_on=["CODGEO_2025", "annee"],
        right_on=["CODGEO", "annee"],
        how="left"
    )

    # Code département
    df["DEP"] = df["CODGEO_2025"].str[:2]
    mask_dom = df["CODGEO_2025"].str.startswith(("97", "98"))
    df.loc[mask_dom, "DEP"] = df["CODGEO_2025"].str[:3]
    df.loc[df["DEP"] == "20", "DEP"] = df["CODGEO_2025"].str[:3]

    # ⚡ Nouveau calcul du taux : ligne par ligne
    df["taux_calcule_pour_mille"] = (df["nombre"] / df["Population"]) * 1000

    return df, source_url

# ----
# 2. FONCTIONS DE CLASSEMENT PAR TAUX
# ----
def rankings_by_rate(df, year, indic=None, n=50):
    """
    Classements des communes par taux pour 1000 habitants (recalculé proprement).
    """
    # Filtrer année
    data = df[df["annee"] == year].copy()
    
    # Filtrer indicateur si précisé
    if indic and indic != "Tous les crimes confondus":
        data = data[data["indicateur"] == indic]

    # Agrégation : on prend somme des crimes ET la population (population = même valeur répétée sur tous les indicateurs)
    agg = (
        data.groupby(["Commune", "CODGEO_2025", "annee"], as_index=False)
        .agg(
            nombre=("nombre", "sum"),
            Population=("Population", "first")   # same pop pour tous indics cette année
        )
    )

    # Recalcul du taux correct
    agg["taux_calcule_pour_mille"] = (agg["nombre"] / agg["Population"]) * 1000

    # Classements
    top = agg.sort_values("taux_calcule_pour_mille", ascending=False).head(n).reset_index(drop=True)
    bottom = agg.sort_values("taux_calcule_pour_mille", ascending=True).head(n).reset_index(drop=True)

    return top, bottom

# ----
# 3. FONCTIONS D'EXPORT
# ----
def create_excel_rankings(df, year=None):
    """Crée un fichier Excel avec classements (nombre + taux pour 1000 recalculé correctement)"""
    df_temp = df.copy()
    
    if year is not None:
        df_temp = df_temp[df_temp["annee"] == year]
    
    # ---- Classement général par nombre de crimes ----
    general_rank = (
        df_temp.groupby(["CODGEO_2025", "Commune"], as_index=False)
        .agg(
            Total_crimes=("nombre", "sum"),
            Types_crimes=("indicateur", "nunique")
        )
        .sort_values("Total_crimes", ascending=False)
        .reset_index(drop=True)
    )
    
    # ---- Classement par taux pour 1000 ----
    taux_rank = (
        df_temp.groupby(["CODGEO_2025", "Commune", "annee"], as_index=False)
        .agg(
            Total_crimes=("nombre", "sum"),
            Population=("Population", "first")
        )
    )
    taux_rank["Taux_pour_mille"] = (taux_rank["Total_crimes"] / taux_rank["Population"]) * 1000
    taux_rank = taux_rank.sort_values("Taux_pour_mille", ascending=False).reset_index(drop=True)
    
    # ---- Création du fichier Excel en mémoire ----
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        # Onglet classement général
        general_rank.to_excel(writer, sheet_name="Classement général", index=False)
        
        # Onglet classement par taux pour 1000
        taux_rank.to_excel(writer, sheet_name="Classement taux pour 1000", index=False)
        
        # ---- Onglets par indicateur ----
        for indic in sorted(df_temp["indicateur"].dropna().unique()):
            subset = (
                df_temp[df_temp["indicateur"] == indic]
                .groupby(["CODGEO_2025", "Commune", "annee"], as_index=False)
                .agg(
                    Total_crimes=("nombre", "sum"),
                    Population=("Population", "first")
                )
            )
            subset["Taux_pour_mille"] = (subset["Total_crimes"] / subset["Population"]) * 1000
            subset = subset.sort_values("Taux_pour_mille", ascending=False).reset_index(drop=True)
            
            # ⚠️ Excel limite les noms d’onglets à 31 caractères
            sheet_name = indic[:31] if len(indic) > 31 else indic
            subset.to_excel(writer, sheet_name=sheet_name, index=False)
    
    return output.getvalue()
# ----
# 4. CHARGEMENT DES DONNÉES
# ----
df, source_url = prepare_data()

if df is None:
    st.error("Impossible de charger les données. Vérifiez votre connexion internet.")
    st.stop()

# ----
# 5. INTERFACE PRINCIPALE
# ----
st.title("🚨 Dashboard Criminalité France")
st.markdown(f"**Source :** {source_url}")

# Sidebar avec filtres
st.sidebar.header("📂 Filtres")

# Sélection niveau d'analyse
niveau = st.sidebar.radio("Niveau d'analyse", ["France", "Commune spécifique"])

if niveau == "Commune spécifique":
    commune_choice = st.sidebar.selectbox(
        "Choisir une commune",
        sorted(df["Commune"].dropna().unique())
    )
else:
    commune_choice = "France"

annee_choice = st.sidebar.selectbox("Année", sorted(df["annee"].dropna().unique()))

# Ajout "Tous les crimes confondus" dans le menu des indicateurs
all_indics = ["Tous les crimes confondus"] + sorted(df["indicateur"].dropna().unique())
indic_choice = st.sidebar.selectbox("Indicateur", all_indics)

# Choix comparaison communes 
communes_compare = st.sidebar.multiselect(
    "Comparer plusieurs communes",
    sorted(df["Commune"].dropna().unique()),
    default=["Paris", "Lyon", "Marseille"]
)

# Export Excel
st.sidebar.header("📥 Export")
if st.sidebar.button("Générer Excel classements"):
    excel_data = create_excel_rankings(df, annee_choice)
    st.sidebar.download_button(
        label="📊 Télécharger Excel",
        data=excel_data,
        file_name=f"classements_{annee_choice}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ----
# 6. ONGLETS PRINCIPAUX
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

    df_map = df.groupby(["annee", "DEP", "indicateur"])["nombre"].sum().reset_index()

    # Gestion "Tous les crimes confondus"
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
            # Limiter aux top 15 pour lisibilité
            subset_top = subset.nlargest(15, "nombre")
            fig_pie = px.pie(subset_top, values="nombre", names="indicateur", title=title, hole=0.3)
        else:
            fig_pie = px.pie(subset, values="nombre", names="indicateur", title=title, hole=0.3)
        
        fig_pie.update_layout(height=600)
        st.plotly_chart(fig_pie, use_container_width=True)

        st.subheader("📋 Détail des données")
        st.dataframe(subset.sort_values("nombre", ascending=False))
    else:
        st.warning("Aucune donnée disponible")

# ----
# ONGLET 3: CLASSEMENTS (AVEC TAUX POUR 1000)
# ----
with tab3:
    st.header("🏆 Classement des communes")
    
    # Slider pour définir combien de communes afficher
    n_communes = st.slider("Nombre de communes à afficher", 10, 100, 15)
    
    # --- Filtrage année & indicateur ---
    df_year = df[df["annee"] == annee_choice].copy()
    if indic_choice != "Tous les crimes confondus":
        df_year = df_year[df_year["indicateur"] == indic_choice]
    
    # --- Classement par nombre ---
    top_nombre = (
        df_year.groupby(["Commune", "CODGEO_2025"], as_index=False)
        .agg(
            Total_crimes=("nombre", "sum"),
            Population=("Population", "first")
        )
        .sort_values("Total_crimes", ascending=False)
        .head(n_communes)
    )
    
    # --- Classement par taux pour 1000 ---
    taux_rank = (
        df_year.groupby(["Commune", "CODGEO_2025"], as_index=False)
        .agg(
            Total_crimes=("nombre", "sum"),
            Population=("Population", "first")
        )
    )
    taux_rank["Taux_pour_mille"] = (taux_rank["Total_crimes"] / taux_rank["Population"]) * 1000
    top_taux = taux_rank.sort_values("Taux_pour_mille", ascending=False).head(n_communes)
    
    # --- Affichage côte à côte ---
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader(f"Top {n_communes} communes par **nombre de faits** - {indic_choice} ({annee_choice})")
        st.dataframe(top_nombre.reset_index(drop=True))
        if not top_nombre.empty:
            fig_bar_nombre = px.bar(
                top_nombre, x="Commune", y="Total_crimes", color="Total_crimes",
                color_continuous_scale="Blues"
            )
            fig_bar_nombre.update_xaxes(tickangle=45)
            st.plotly_chart(fig_bar_nombre, use_container_width=True)
    
    with col2:
        st.subheader(f"Top {n_communes} communes par **taux pour 1000 hab.** - {indic_choice} ({annee_choice})")
        st.dataframe(top_taux.reset_index(drop=True))
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
# ONGLET 6: RECHERCHE
# ----
with tab6:
    st.header("🔍 Recherche par commune")

    search_term = st.text_input("Tapez le nom d'une commune:", placeholder="Ex: Paris, Lyon, Marseille...")
    if search_term:
        matches = df[df["Commune"].str.contains(search_term, case=False, na=False)]["Commune"].unique()
        if len(matches) > 0:
            st.success(f"🎯 {len(matches)} commune(s) trouvée(s)")
            selected_commune = st.selectbox("Choisir une commune:", matches)
            if selected_commune:
                commune_data = df[df["Commune"] == selected_commune]

                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total crimes (toutes années)", f"{commune_data['nombre'].sum():,}")
                with col2:
                    st.metric("Années disponibles", len(commune_data["annee"].unique()))
                with col3:
                    st.metric("Types de crimes", len(commune_data["indicateur"].unique()))

                st.subheader(f"📊 Détail par année - {selected_commune}")
                summary = (
                    commune_data.groupby(["annee", "indicateur"])["nombre"]
                    .sum()
                    .reset_index()
                    .pivot(index="indicateur", columns="annee", values="nombre")
                    .fillna(0)
                )
                st.dataframe(summary)

                evol_commune = commune_data.groupby(["annee", "indicateur"])["nombre"].sum().reset_index()
                fig_search = px.line(
                    evol_commune, x="annee", y="nombre", color="indicateur",
                    title=f"Évolution des crimes à {selected_commune}"
                )
                st.plotly_chart(fig_search, use_container_width=True)
        else:
            st.warning("❌ Aucune commune trouvée avec ce nom")

# ----
# ONGLET 7: COMPARAISON
# ----
with tab7:
    st.header("⚖️ Comparaison entre communes")

    if communes_compare:
        subset_compare = df[(df["Commune"].isin(communes_compare)) & (df["annee"] == annee_choice)]

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

        # --- Radar Chart (facultatif, pour lisibilité limiter aux top crimes) ---
        top_indics = (
            subset_compare.groupby("indicateur")["nombre"].sum()
            .nlargest(8).index.tolist()   # limiter à 8 types majeurs
        )
        radar_data = subset_compare[subset_compare["indicateur"].isin(top_indics)]
        radar_pivot = radar_data.pivot_table(index="indicateur", columns="Commune", values="nombre", fill_value=0)

        # Comme le radar demande une colonne commune / valeur
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
        st.warning("Sélectionne au moins une commune dans la barre latérale pour comparer.")

# ----
# FOOTER
# ----
st.markdown("---")
st.markdown("**📊 Dashboard créé par CSF avec Streamlit | Données : data.gouv.fr : https://www.data.gouv.fr/datasets/bases-statistiques-communale-departementale-et-regionale-de-la-delinquance-enregistree-par-la-police-et-la-gendarmerie-nationales/**")