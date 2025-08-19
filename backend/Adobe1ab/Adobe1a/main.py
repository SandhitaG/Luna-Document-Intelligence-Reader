# Adobe1a/main.py
import os, sys, json, time, argparse, datetime
from extractor.extract_outline import extract_outline

def parse_args():
    ap = argparse.ArgumentParser(description="Round 1A — PDF Outline Extractor")
    ap.add_argument("--input_dir",  default=os.environ.get("A1A_INPUT_DIR",  "/app/input"),
                    help="Directory containing PDFs to process")
    ap.add_argument("--output_dir", default=os.environ.get("A1A_OUTPUT_DIR", "/app/output"),
                    help="Directory to write JSON outlines")
    ap.add_argument("--time_budget_sec", type=float, default=float(os.environ.get("A1A_TIME_BUDGET", "10")),
                    help="Hard cap for total processing time (seconds)")
    return ap.parse_args()

def is_pdf(fname: str) -> bool:
    return fname.lower().endswith(".pdf")

def main():
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    t0 = time.time()
    deadline = t0 + float(args.time_budget_sec)

    # list PDFs (stable order)
    try:
        files = sorted([f for f in os.listdir(args.input_dir) if is_pdf(f)])
    except FileNotFoundError:
        print(f"ERROR: input_dir not found: {args.input_dir}", file=sys.stderr)
        sys.exit(1)

    processed = 0
    for fname in files:
        if time.time() > deadline:
            print("⏱️  Time budget reached; stopping further files.")
            break

        in_path  = os.path.join(args.input_dir, fname)
        out_path = os.path.join(args.output_dir, os.path.splitext(fname)[0] + ".json")

        try:
            result = extract_outline(in_path)  # {"title": "...", "outline": [...]}
            # Ensure schema is exactly as required
            payload = {
                "title": result.get("title", "") or "",
                "outline": []
            }
            for item in result.get("outline", []):
                level = str(item.get("level", "")).upper()
                text  = str(item.get("text", "")).strip()
                page  = int(item.get("page", 1))  # 1-based already in extractor
                if level in ("H1", "H2", "H3") and text:
                    payload["outline"].append({"level": level, "text": text, "page": page})

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            processed += 1
            took = time.time() - t0
            print(f"✓ {fname} → {os.path.basename(out_path)}  ({took:.2f}s total)")

        except Exception as e:
            print(f"✗ {fname}: {e}", file=sys.stderr)
            # continue with other files

    total = time.time() - t0
    print(json.dumps({
        "processed_files": processed,
        "total_seconds": round(total, 2),
        "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    }))

if __name__ == "__main__":
    main()
