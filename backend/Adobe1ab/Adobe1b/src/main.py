import os, json, time, argparse, datetime
from generate_output import write_final_output
from pdf_loader import load_documents_and_sections
from persona_parser import build_query_text
from section_ranker import rank_sections_for_persona
from sub_section_analyzer import build_snippets
import sys
DEFAULT_INPUT_DIR = os.environ.get("A1B_INPUT_DIR", "../input")
DEFAULT_OUTPUT_FILE = os.environ.get("A1B_OUTPUT_FILE", "../output/challenge1b_output.json")

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass
# Hardcoded quick-pick options (you can surface these in UI dropdowns)
PRESET_OPTIONS = [
    {"persona": "Travel Planner", "job": "Plan a trip of 4 days for a group of 10 college friends."},
    {"persona": "HR professional", "job": "Create and manage fillable forms for onboarding and compliance."},
    {"persona": "Food Contractor", "job": "Prepare a vegetarian buffet-style dinner menu for a corporate gathering, including gluten-free items."},
    {"persona": "PhD Researcher", "job": "Extract related work and methods section from recent academic publications."},
    {"persona": "Investment Analyst", "job": "Analyze revenue trends, R&D investments, and market positioning strategies."},
    {"persona": "Undergraduate Chemistry Student", "job": "Identify key concepts and mechanisms for exam preparation on reaction kinetics."},
]

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input_dir", default=DEFAULT_INPUT_DIR, help="Folder with PDFs")
    ap.add_argument("--output_file", default=DEFAULT_OUTPUT_FILE, help="Output JSON path")
    ap.add_argument("--persona", type=str, help="Persona string")
    ap.add_argument("--job", type=str, help="Job-to-be-done string")
    ap.add_argument("--preset", type=int, help="Index into preset options (0..5)")
    ap.add_argument("--time_budget_sec", type=float, default=9.0, help="Hard cap (seconds)")
    return ap.parse_args()

def main():
    args = parse_args()
    start = time.time()
    deadline = start + float(args.time_budget_sec)

    # Resolve persona + job (required)
    persona = args.persona
    job = args.job
    if (persona is None or job is None) and args.preset is not None:
        if 0 <= args.preset < len(PRESET_OPTIONS):
            persona = PRESET_OPTIONS[argspreset]["persona"]  # typo fixed below
        else:
            raise ValueError("Invalid --preset index.")
    if persona is None or job is None:
        # Also allow env vars (for Docker / API)
        persona = persona or os.environ.get("A1B_PERSONA")
        job = job or os.environ.get("A1B_JOB")
    if persona is None or job is None:
        raise SystemExit("ERROR: persona and job are required. Use --persona/--job or --preset N or env A1B_PERSONA/A1B_JOB.")

    # Fix small typo if preset path used
    if isinstance(args.preset, int) and 0 <= args.preset < len(PRESET_OPTIONS):
        persona = PRESET_OPTIONS[args.preset]["persona"]
        job = PRESET_OPTIONS[args.preset]["job"]

    # 1) Load PDFs + candidate sections (fast)
    docs, sections = load_documents_and_sections(args.input_dir, deadline)

    # 2) Build query text
    query_text = build_query_text(persona, job)

    # 3) Rank sections globally with per-doc guarantee
    ranked = rank_sections_for_persona(query_text, sections, docs, deadline)

    # 4) Build sub-section snippets for top items
    snippets = build_snippets(query_text, ranked, deadline)

    # 5) Assemble metadata + write JSON
    meta = {
        "input_documents": docs,
        "persona": persona,
        "job_to_be_done": job,
        "processing_timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    }
    out = write_final_output(meta, ranked, snippets, args.output_file)

    took = time.time() - start
    print(f"✅ 1B done in {took:.2f}s → {args.output_file}")
    print(json.dumps({"seconds": round(took, 2), "documents": len(docs), "sections": len(ranked)}, ensure_ascii=False))

if __name__ == "__main__":
    main()
