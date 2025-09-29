import pandas as pd

# ⚠️ Mets ici le nom exact du fichier téléchargé depuis data.gouv
# Exemple: "donnee-data.gouv-2024-geographie2025.csv.gz"
input_file = "donnee-data.gouv-2024-geographie2025.csv.gz"
output_file = "crime_2016_2024.csv.gz"

# Colonnes utiles
usecols = ["annee", "codgeo", "indicateur", "nombre", "taux_pour_mille"]

chunks = []
print("▶️ Lecture par morceaux du gros fichier...")
for chunk in pd.read_csv(input_file, sep=";", dtype=str, compression="gzip", usecols=usecols, chunksize=200000):
    chunk["annee"] = pd.to_numeric(chunk["annee"], errors="coerce")
    chunk["nombre"] = pd.to_numeric(chunk["nombre"], errors="coerce")
    
    # ➡️ On garde uniquement 2016–2024
    chunk = chunk[(chunk["annee"] >= 2016) & (chunk["annee"] <= 2024)]
    chunks.append(chunk)

df = pd.concat(chunks, ignore_index=True)

# Standardisation
df.rename(columns={"codgeo": "CODGEO_2025"}, inplace=True)
df["taux_pour_mille"] = df["taux_pour_mille"].str.replace(",", ".", regex=False).astype(float)

# Sauvegarde compressée
df.to_csv(output_file, sep=";", index=False, compression="gzip")
print(f"✅ {output_file} sauvegardé avec {len(df):,} lignes.")
