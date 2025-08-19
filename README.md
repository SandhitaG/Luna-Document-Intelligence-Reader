## Luna: PDF Insights & Podcast Generator

Turn PDFs into short, insight-packed summaries and human-sounding podcasts—all in your browser.
This repo includes a React frontend, a Flask backend, an embeddings-backed “Connect the Insights” engine, and multi-provider TTS (local, Azure, or Google Cloud).

## Highlights

- Extract structured sections from PDFs (Adobe 1A → 1B bridge)

- Get Insights: grounded, bullet-free summaries for any selected text

- Connect the Insights: cross-doc overlaps, contradictions, and a grounded note

- Podcast: single-voice summary, or Duo dialog with two voices & stitched audio

- TTS providers: Local (espeak+ffmpeg), Google Cloud TTS, Azure (Speech or AOAI TTS).Automatic fallbacks keep audio generation working.
  
```bash
Document_Intelligence_Reader/
├─ backend/
│  ├─ controller_app.py              # Flask API (serves built frontend too)
│  ├─ requirements.txt
│  ├─ Adobe1ab/
│  │  ├─ Adobe1a/
│  │  │  ├─input/
│  │  │  ├─output/
│  │  │  ├─ extractor/ 
│  │  │   ├─ classifier.py            # 1A outputs (runtime)
│  │  │   ├─ extract_outline.py
│  │  │   ├─ ocr.py
│  │  │   ├─ parser.py
│  │  │   └─ (other helpers…)
│  │  └─ Adobe1b/
│  │     ├─ src/
│  │     │  ├─generate_output.py
│  │     │  ├─main.py
│  │     │  ├─pdf_loader.py
│  │     │  ├─persona_detector.py
│  │     │  ├─ persona_parser.py
│  │     │  ├─ section_ranker.py
│  │     │  ├─ sub_section_analysis.py
│  │     │  ├─ snippets.py
│  │     │  ├─ approach_explain.py
│  │     ├─input/
│  │     ├─output/
│  │     ├─ requirements.txt
│  │     └─ run.sh
│  ├─ insights/
│  │  ├─ __init__.py
│  │  └─ insights.py                  # get_insights(text) — Gemini/Vertex compatible
│  ├─ podcast/
│  │  ├─ __init__.py
│  │  └─ generate_audio.py            # unified TTS (local/gcp/azure) + chunking/concat
│  ├─ memory/
│  │  ├─ index.py
│  │  └─ library.json                 # built at runtime (Connect the Insights store)
│  ├─ recommender/
│  │  └─ local_recommender.py         # (optional)
│  ├─ uploads/                        # user uploads (runtime)
│  ├─ utils/
│  │  └─ pdf_text.py                  # (example utility)
│  └─ snippets_safe.py                # safe snippet builder + embedder for selection rank
│  ├─chat_with_llm.py
│  ├─controller_app.py
│  ├─gemini_helper.py
│  ├─init.py
│  ├─requirements.txt
│
├─ frontend/
│  ├─ build/
│     ├─node_modules                       # created by `npm run build` (copied to /frontend_dist)
│  ├─ public/
│  ├─index.html
│  ├─src/
│     ├─ assets/
│     │  ├─ library-bg.jpg
│     │  └─ luna-logo.png
│     ├─ components/
│     │  ├─ AdobeInlineViewer.jsx
│     │  ├─ InsightBulb.jsx
│     │  ├─ PDFPreviewModal.jsx
│     │  ├─ PDFViewer.jsx
│     │  ├─ PodcastPlayer.jsx
│     │  ├─ RelatedSectionsCard.jsx
│     │  └─ Sidebar.jsx
│     ├─ styles/app.css
│     ├─ utils/helpers.jsx
│     ├─ App.jsx
│     └─ index.js
│   ├─ .env
│   ├─ package-lock.json
│   ├─ package.json
├─ Dockerfile                         # multi-stage: build frontend → slim Python runtime
└─ README.md
```

## Quick Start (Docker)

# Build

docker build --platform linux/amd64 -t yourimageidentifier .

# Run

docker run -p 8080:8080 `
  -e ADOBE_EMBED_API_KEY=cebba3120472436fa9c7bdec9a3ff7ca `
  -e LLM_PROVIDER=gemini `
  -e GOOGLE_API_KEY=AIzaSyBCqxnGx42FTULg2t75wNG1bxJwo4cguD4 `
  -e GEMINI_MODEL=gemini-2.5-flash `
  -e TTS_PROVIDER=local `
  yourimageidentifier

Open http://localhost:8080

- The image installs espeak-ng and ffmpeg so local TTS works out of the box.
- You can switch to gcp or azure TTS by setting the env vars below.
## .env file
- REACT_APP_ADOBE_EMBED_CLIENT_ID(Adobe-Embed-Api-Key)=cebba3120472436fa9c7bdec9a3ff7ca 


## Local Development (optional)
- # Backend
cd backend
python controller_app.py

- # Frontend
cd frontend 
npm start

API Endpoints

All JSON; server runs on :8080.


If server-side TTS isn’t available, the API returns { script, mode:"client-tts" } so the frontend can speak via the Web Speech API immediately.

## How “Connect the Insights” Works
- Every extraction populates memory/library.json with sections + embeddings.
- /select_insights ranks semantically similar sections (recent vs. past), detects overlaps/contradictions, explains “why it matches”, and asks the LLM to write a strictly grounded “connect-the-dots” note with inline citations like (Doc p.#).

## About the Podcast Duo

- The Duo prompt converts bullets into real insights (no bullet reading).

- We post-clean the script to enforce Host/Guest turn-taking and remove stray list symbols.

- Server-side TTS stitches each line (two voices) with ffmpeg. If anything fails, the endpoint returns the script for client-side speech.

## Credits

- Built for the Adobe hackathon by Team Innovators(Sandhita Goswami,Srijeeta Boral)
- Includes an internal bridge to the Adobe 1A/1B pipeline and a lightweight semantic store for cross-document reasoning.


