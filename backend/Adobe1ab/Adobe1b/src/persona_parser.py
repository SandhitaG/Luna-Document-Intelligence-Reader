def build_query_text(persona: str, job: str) -> str:
    """
    Create a compact query string used to rank sections.
    Keep it lightweight (no model downloads).
    """
    persona = (persona or "").strip()
    job = (job or "").strip()
    return f"Persona: {persona}. Task: {job}."
