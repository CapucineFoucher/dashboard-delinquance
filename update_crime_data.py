import io
import sys
import time
import json
import hashlib
import requests
import pandas as pd

STABLE_URL = "https://www.data.gouv.fr/api/1/datasets/r/6252a84c-6b9e-4415-a743-fc6a631877bb"
OUTPUT_LATEST = "crime_2016_latest.csv.gz"

REQUIRED_COLS_VARIANTS = {
    "CODGEO": ["CODGEO", "codgeo"],
    "ANNEE": ["ANNEE", "annee"],
    "INDICATEUR": ["INDICATEUR", "indicateur"],
    "NB": ["NB", "nb", "nombre"]
}

def http_get_with_retry(url, max_retries=4, timeout=60):
    last_err = None
    for i in range(max_retries):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_err = e
            time.sleep(2 * (i + 1))
    raise last_err

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    # Map columns robustly
    cols_lower = {c.lower(): c for c in df.columns}
    def find_col(candidates):
        for cand in candidates:
            if cand in df.columns:
                return cand
            if cand.lower() in cols_lower:
                return cols_lower[cand.lower()]
        return None

    col_cod = find_col(REQUIRED_COLS_VARIANTS["CODGEO"])
    col_year = find_col(REQUIRED_COLS_VARIANTS["ANNEE"])
    col_ind = find_col(REQUIRED_COLS_VARIANTS["INDICATEUR"])
    col_nb  = find_col(REQUIRED_COLS_VARIANTS["NB"])

    missing = [name for name, col in {
        "CODGEO/CODGEO_2025": col_cod,
        "ANNEE": col_year,
        "INDICATEUR": col_ind,
        "NB/nombre": col_nb
    }.items() if col is None]
    if missing:
        raise ValueError(f"Colonnes manquantes ou non détectées: {missing}. Colonnes présentes: {list(df.columns)}")

    df = df.rename(columns={
        col_cod: "CODGEO_2025",
        col_year: "annee",
        col_ind: "indicateur",
        col_nb: "nombre"
    })
    return df[["CODGEO_2025", "annee", "indicateur", "nombre"]]

def main():
    print(f"Téléchargement depuis l’URL stable…\n{STABLE_URL}")
    resp = http_get_with_retry(STABLE_URL)
    content = resp.content

    # Essayer lecture CSV (compression auto “infer”)
    try:
        df = pd.read_csv(io.BytesIO(content), sep=";", dtype=str, compression="infer")
    except Exception:
        # Certains dumps sont en CSV “,” → réessayer virgule
        df = pd.read_csv(io.BytesIO(content), sep=",", dtype=str, compression="infer")

    print(f"Colonnes reçues: {list(df.columns)}")
    df = normalize_columns(df)

    # Types
    df["annee"] = pd.to_numeric(df["annee"], errors="coerce")
    df["nombre"] = pd.to_numeric(df["nombre"], errors="coerce")
    # Nettoyage basique
    df["CODGEO_2025"] = df["CODGEO_2025"].astype(str).str.strip()
    df = df.dropna(subset=["annee", "nombre"])

    an_min, an_max = int(df["annee"].min()), int(df["annee"].max())
    print(f"Plage d’années détectée: {an_min} → {an_max}")
    print(f"Lignes: {len(df):,}")

    # Ecriture “latest” (l’app lira ce fichier automatiquement)
    df.to_csv(OUTPUT_LATEST, sep=";", index=False, compression="gzip")
    print(f"✅ Écrit: {OUTPUT_LATEST}")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("❌ ERREUR:", e)
        sys.exit(1)
