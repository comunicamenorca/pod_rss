# 🎙️ Podcast RSS Generator

Genera feeds RSS de podcast automàticament a partir de pàgines web amb MP3s.
S'actualitza sol amb GitHub Actions i es publica via GitHub Pages.

---

## 📁 Estructura del projecte

```
podcast-rss/
├── scraper.py               ← Script principal
├── feeds.yaml               ← Configuració dels podcasts
├── requirements.txt         ← Dependències Python
├── docs/                    ← Feeds RSS generats (publicats per GitHub Pages)
│   ├── tecnologia-radioestel.xml
│   └── informatius-menorca-ib3.xml
└── .github/
    └── workflows/
        ├── workflow-daily.yml   ← Executa cada dia (Ràdio Estel)
        └── workflow-6h.yml      ← Executa cada 6h (IB3 Menorca)
```

---

## 🚀 Posada en marxa (pas a pas)

### 1. Crea un compte a GitHub
Ves a [github.com](https://github.com) i registra't.

### 2. Crea un repositori nou
- Botó verd **"New"** o **"+"** → **"New repository"**
- Nom: `podcast-rss` (o el que vulguis)
- Marca **"Public"** (necessari per GitHub Pages gratuït)
- Clica **"Create repository"**

### 3. Puja els fitxers
- A la pàgina del repositori, clica **"uploading an existing file"**
- Arrossega tots els fitxers d'aquest projecte
- ⚠️ La carpeta `.github/workflows/` cal crear-la manualment:
  - Clica **"Add file"** → **"Create new file"**
  - Escriu el nom: `.github/workflows/workflow-daily.yml`
  - Enganxa el contingut del fitxer
  - Repeteix per `workflow-6h.yml`

### 4. Activa GitHub Pages
- Ves a **Settings** → **Pages**
- A "Source" selecciona **"Deploy from a branch"**
- Branch: **`main`**, carpeta: **`/docs`**
- Clica **Save**

### 5. Primera execució manual
- Ves a **Actions** → **"Actualitza feeds diaris"**
- Clica **"Run workflow"** → **"Run workflow"**
- Repeteix amb **"Actualitza feeds cada 6 hores"**

### 6. Les teves URLs de podcast
Un cop executat, els feeds estaran disponibles a:
```
https://EL-TEU-USUARI.github.io/podcast-rss/tecnologia-radioestel.xml
https://EL-TEU-USUARI.github.io/podcast-rss/informatius-menorca-ib3.xml
```

Enganxa aquestes URLs a la teva app de podcasts (Pocket Casts, Overcast, Apple Podcasts...)
amb l'opció **"Afegir per URL"** o **"Add RSS feed"**.

---

## ➕ Afegir un nou podcast

Edita `feeds.yaml` i afegeix:
```yaml
  - name: "Nom del Podcast"
    url: "https://la-pagina-amb-mp3s.cat/seccio/"
    description: "Descripció breu"
    language: "ca"
    image: "https://...imatge.jpg"
    output: "nom-fitxer.xml"
    max_episodes: 30
```

Si vols una freqüència diferent, crea un nou fitxer a `.github/workflows/` basant-te
en els existents i canvia el cron i el nom del feed.

---

## 🛠️ Execució local (opcional)

```bash
pip install -r requirements.txt
python scraper.py                          # Tots els feeds
python scraper.py --feed "Nom del feed"    # Un feed concret
```

Els fitxers XML es generen a la carpeta `docs/`.
