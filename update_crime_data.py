import io
import sys
import time
import requests
import pandas as pd

# URL stable Data.gouv
STABLE_URL = "https://www.data.gouv.fr/api/1/datasets/r/6252a84c-6b9e-4415-a743-fc6a631877bb"
OUTPUT_LATEST = "crime_2016_latest.csv.gz"

def http_get_with_retry(url, max_retries=4, timeout=60):
    last_err = None
    for i in range(max_retries):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_err = e
            time.sleep(2*(i+1))
    raise last_err

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols_map = {c.lower(): c for c in df.columns}
    def col(*names):
        for n in names:
            if n in df.columns: return n
            if n.lower() in cols_map: return cols_map[n.lower()]
        return None

    c_cod = col("CODGEO","codgeo")
    c_an  = col("ANNEE","annee")
    c_ind = col("INDICATEUR","indicateur")
    c_nb  = col("NB","nb","nombre")

    if not all([c_cod,c_an,c_ind,c_nb]):
        raise ValueError(f"Colonnes non trouvées. Colonnes dispo: {list(df.columns)}")

    df = df.rename(columns={
        c_cod:"CODGEO_2025",
        c_an:"annee",
        c_ind:"indicateur",
        c_nb:"nombre"
    })
    return df[["CODGEO_2025","annee","indicateur","nombre"]]

def main():
    print(f"Téléchargement depuis l’URL stable:\n{STABLE_URL}")
    resp = http_get_with_retry(STABLE_URL)
    content = resp.content

    # 🚨 Ici on précise bien que c’est GZIP 🚨
    df = pd.read_csv(io.BytesIO(content), compression="gzip", sep=";", dtype=str, low_memory=False)

    print(f"Colonnes importées: {list(df.columns)}")
    df = normalize_columns(df)

    df["annee"] = pd.to_numeric(df["annee"], errors="coerce")
    df["nombre"] = pd.to_numeric(df["nombre"], errors="coerce")
    df["CODGEO_2025"] = df["CODGEO_2025"].astype(str).str.strip()

    df = df.dropna(subset=["annee","nombre"])
    print(f"Années couvertes: {df['annee'].min()} → {df['annee'].max()}")
    print(f"Lignes totales: {len(df):,}")

    # On écrase le fichier latest
    df.to_csv(OUTPUT_LATEST, sep=";", index=False, compression="gzip")
    print(f"✅ Écrit: {OUTPUT_LATEST}")

if __name__=="__main__":
    try:
        main()
    except Exception as e:
        print("❌ ERREUR:", e)
        sys.exit(1)
