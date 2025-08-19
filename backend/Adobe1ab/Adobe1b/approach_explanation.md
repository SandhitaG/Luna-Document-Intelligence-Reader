# 📘 Persona-Driven Document Intelligence (Round 1B)  
### Adobe India Hackathon 2025 – “Connect What Matters — For the User Who Matters”



## ✅ Overview

This project is an **intelligent document analysis system** designed to extract and prioritize the most relevant sections from a collection of PDFs, based on a given **persona** and their **job-to-be-done**.

It handles various domains such as research papers, educational material, business reports, or instructional guides — and tailors its analysis dynamically using local language models, embeddings, and rule-based scoring.

---

## 🧠 Approach

Our pipeline follows these steps:

1. **PDF Loading & Text Segmentation**  
   - Extracts all pages from PDFs using PyMuPDF (`fitz`) into structured text segments.

2. **Persona & Job Detection**  
   - Automatically detects the best-fitting persona + job pair from a predefined list using local semantic similarity scoring via `all-MiniLM-L6-v2`.

3. **Section Ranking**  
   - Ranks PDF sections (paragraphs/headings) based on semantic similarity to the job-to-be-done using cosine similarity over embeddings.

4. **Granular Sub-section Extraction**  
   - From each top-ranked section, extracts concise and relevant sub-parts with refined, human-readable text to ensure clarity and precision.

5. **Output JSON Generation**  
   - Constructs a structured output in the exact format required by the challenge, including ranked section titles, metadata, and refined sub-section texts.

---

## 🗂️ Project Structure

Adobe1b/
│
├── data/                         # Input folder containing all PDFs
├── output/                       # Stores the final output JSON file
├── src/
│   ├── main.py                   # Entry point of the system
│   ├── pdf_loader.py             # Loads and segments all PDFs
│   ├── persona_detector.py       # Auto-detects persona and job from PDFs
│   ├── persona_parser.py         # Embeds persona and job phrases
│   ├── section_ranker.py         # Ranks PDF chunks by relevance
│   ├── sub_section_analyzer.py   # Refines the extracted segments
│   └── generate_output.py        # Assembles and writes final output JSON
│
├── Dockerfile                    # Dockerized execution for isolated offline runs
├── requirements.txt              # Python dependencies
├── run.sh                        # Optional shell script for execution
└── ReadMe.md

## 📚 Libraries and Models Used
Python 3.10

PyMuPDF (fitz) – PDF layout and text extraction

sentence-transformers – for semantic embedding of text and persona

scikit-learn – cosine similarity for relevance ranking

json, os, datetime – for data handling and I/O

Model Used: all-MiniLM-L6-v2 from SentenceTransformers (offline compatible, ≤90MB)

## ✅ Constraints Met
Constraint	Status
CPU-only execution	
Offline-only (no internet access)	
Model size ≤ 1GB	
Runtime ≤ 60 seconds for 3–5 PDFs	
Docker-compatible execution	
Supports 3–10 PDFs	
Supports dynamic persona detection	