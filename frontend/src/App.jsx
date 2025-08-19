import React, { useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import "./styles/app.css";
import AdobeInlineViewer from "./components/AdobeInlineViewer";
import LunaLogo from "./assets/luna-logo.png";

/* --------------------------------
   API client
----------------------------------- */
const API_BASE = "http://127.0.0.1:8080";
const API = axios.create({ baseURL: API_BASE, timeout: 120000 });

/* --------------------------------
   Bracket-less JSON renderer
----------------------------------- */
const isPrimitive = (v) =>
  v === null ||
  typeof v === "string" ||
  typeof v === "number" ||
  typeof v === "boolean";

const cleanBulletText = (text) => {
  return String(text || "")
    .replace(/[\u2022\u2023\u25E6\u2043\u2219\u00B7]/g, "•")
    .replace(/[\uFFFD\u200B\u2060\uFEFF\u00A0]/g, "")
    .replace(/\s*•\s*/g, " • ")
    .replace(/•+/g, "•")
    .replace(/[^\x20-\x7E\n\r\t•]/g, "")
    .replace(/\u2026|\.{3,}/g, "…") // normalize ellipses

    .trim();
};
// stronger cleaner used for both title + document
const cleanConnectText = (text) =>
  String(text || "")
    // normalize common bullet glyphs + OCR ? to a single •
    .replace(/[\u2022\u2023\u25E6\u2043\u2219\u00B7\u2024\u25CF\u25AA\u25AB\u25FE\u25A0\u25A1\u25CB\uF0B7]/g, "•")
    .replace(/\?/g, "•")
    // tidy bullets & whitespace
    .replace(/•{2,}/g, "•")
    .replace(/\s*•\s*/g, " • ")
    // strip invisibles
    .replace(/[\uFFFD\u200B\u2060\uFEFF\u00A0]/g, "")
    .replace(/\s+/g, " ")
    .trim();

const uniqueBy = (arr, keyFn) => {
  const seen = new Set();
  return (arr || []).filter((x) => {
    const k = keyFn(x);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
};

// IMPORTANT: clean BOTH title and document for the key
const keyFor = (r) => {
  const title = cleanConnectText(r?.section_title || "").toLowerCase();
  const doc   = cleanConnectText(r?.document || "").toLowerCase();
  const page  = String(r?.page_number ?? r?.pageNumber ?? "").trim();
  return `${title}|${doc}|${page}`;
};


const Row = ({ bullet = "•", children, indent = 0 }) => (
  <div
    style={{
      display: "grid",
      gridTemplateColumns: "18px 1fr",
      columnGap: 6,
      paddingLeft: indent ? 10 : 0,
      marginBottom: 4,
      lineHeight: 1.45,
    }}
  >
    <span style={{ opacity: 0.9 }}>{bullet}</span>
    <div>{children}</div>
  </div>
);

const Braceless = ({ data, level = 0 }) => {
  if (Array.isArray(data)) {
    return (
      <div>
        {data.map((item, i) => (
          <Row key={i} indent={level}>
            {isPrimitive(item) ? (
              <span>{String(item)}</span>
            ) : (
              <Braceless data={item} level={level + 1} />
            )}
          </Row>
        ))}
      </div>
    );
  }

  if (data && typeof data === "object") {
    return (
      <div>
        {Object.entries(data).map(([k, v]) => (
          <Row key={k} indent={level}>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "160px 1fr",
                gap: 8,
              }}
            >
              <strong style={{ color: "#c8bfff" }}>{k}</strong>
              {isPrimitive(v) ? (
                <span>{cleanBulletText(v)}</span>
              ) : (
                <Braceless data={v} level={level + 1} />
              )}
            </div>
          </Row>
        ))}
      </div>
    );
  }

  return <span>{String(data)}</span>;
};

/* --------------------------------
   AUDIO CONTROL (server audio + TTS)
----------------------------------- */
const audioRef = { current: null };
const playingRef = { current: false };
const ttsQueueRef = { current: null };

function stopAllAudio() {
  try {
    if (audioRef.current) {
      audioRef.current.pause();
      if (audioRef.current.src?.startsWith("blob:")) {
        URL.revokeObjectURL(audioRef.current.src);
      }
      audioRef.current.src = "";
      audioRef.current = null;
    }
  } catch {}
  try {
    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
  } catch {}
  playingRef.current = false;
}

function ensureVoices() {
  return new Promise((resolve) => {
    const synth = window.speechSynthesis;
    if (!synth) return resolve([]);
    let voices = synth.getVoices();
    if (voices && voices.length) return resolve(voices);
    const on = () => {
      voices = synth.getVoices();
      resolve(voices || []);
      synth.removeEventListener?.("voiceschanged", on);
    };
    synth.addEventListener?.("voiceschanged", on);
    setTimeout(() => {
      voices = synth.getVoices();
      if (voices && voices.length) {
        resolve(voices);
        synth.removeEventListener?.("voiceschanged", on);
      }
    }, 250);
  });
}

function pickVoice(voices, wantFemale = true) {
  const prefer = wantFemale
    ? ["Jenny", "Aria", "Neural2-F", "Salli", "Libby", "Wavenet-F", "Samantha", "Google UK English Female"]
    : ["Guy", "Davis", "Neural2-D", "Matthew", "Brian", "Daniel", "Google US English", "Alex"];
  for (const name of prefer) {
    const v = voices.find((x) => new RegExp(name, "i").test(x.name));
    if (v) return v;
  }
  const genderMatch = voices.find((v) =>
    (wantFemale ? /female/i : /male/i).test(v.name + " " + (v.voiceURI || ""))
  );
  return genderMatch || voices[0] || null;
}

async function speakSingle(text, setIsPlaying) {
  const synth = window.speechSynthesis;
  if (!synth) return alert("Podcast script:\n\n" + text);
  stopAllAudio();
  const voices = await ensureVoices();
  const u = new SpeechSynthesisUtterance(text);
  u.voice = pickVoice(voices, true);
  u.rate = 1.04;
  u.pitch = 1.03;
  u.onend = () => {
    playingRef.current = false;
    setIsPlaying(false);
  };
  playingRef.current = true;
  setIsPlaying(true);
  synth.speak(u);
  ttsQueueRef.current = { queue: [u] };
}

async function speakDuo(script, setIsPlaying) {
  const synth = window.speechSynthesis;
  if (!synth) return alert("Podcast script:\n\n" + script);
  stopAllAudio();
  const voices = await ensureVoices();
  const hostVoice = pickVoice(voices, true);
  const guestVoice = pickVoice(voices, false);

  const lines = script.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const queue = [];

  for (const line of lines) {
    const isHost = /^host:/i.test(line);
    const isGuest = /^guest:/i.test(line);
    const text = line.replace(/^(host|guest):\s*/i, "").trim();
    if (!text) continue;

    const u = new SpeechSynthesisUtterance(text);
    u.voice = isGuest ? guestVoice : hostVoice;
    u.rate = 1.02 + (Math.random() * 0.06 - 0.03);
    u.pitch = (isGuest ? 0.96 : 1.08) + (Math.random() * 0.06 - 0.03);
    u.volume = 1.0;
    queue.push(u);
  }

  if (!queue.length) return;

  playingRef.current = true;
  setIsPlaying(true);
  let i = 0;
  const speakNext = () => {
    if (i >= queue.length) {
      playingRef.current = false;
      setIsPlaying(false);
      return;
    }
    const u = queue[i++];
    u.onend = speakNext;
    synth.speak(u);
  };
  ttsQueueRef.current = { queue, stop: () => synth.cancel() };
  speakNext();
}

async function playAudioOrSpeak(res, { duo = false, setIsPlaying }) {
  const ct = res?.headers?.["content-type"] || "";
  if (ct.includes("audio/")) {
    try {
      stopAllAudio();
      const blob = new Blob([res.data], { type: ct });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audioRef.current = audio;
      playingRef.current = true;
      setIsPlaying(true);
      audio.onended = () => {
        playingRef.current = false;
        setIsPlaying(false);
      };
      await audio.play().catch(() => {
        const a = document.createElement("a");
        a.href = url;
        a.download = "podcast.mp3";
        a.click();
      });
    } catch (e) {
      console.error("Audio playback failed:", e);
      alert("We received audio but couldn't play it. It has been downloaded instead.");
    }
    return;
  }

  try {
    const text = new TextDecoder().decode(res.data || new ArrayBuffer(0));
    const obj = JSON.parse(text);
    const script = obj && typeof obj.script === "string" && obj.script.trim()
      ? obj.script.trim()
      : null;

    if (script) {
      const looksDuo = /(^|\n)\s*host:/i.test(script) && /(^|\n)\s*guest:/i.test(script);
      if (duo || looksDuo) return speakDuo(script, setIsPlaying);
      return speakSingle(script, setIsPlaying);
    }
    if (text && text.trim().length < 50000) {
      const looksDuo = /(^|\n)\s*host:/i.test(text) && /(^|\n)\s*guest:/i.test(text);
      if (duo || looksDuo) return speakDuo(text.trim(), setIsPlaying);
      return speakSingle(text.trim(), setIsPlaying);
    }
    console.warn("No script found in response:", obj || text);
    alert("Podcast was generated, but no playable audio or script returned.");
  } catch (e) {
    console.error("Non-audio, non-JSON response:", e);
    alert("Podcast failed to render.");
  }
}

/* --------------------------------
   Persona → Jobs
----------------------------------- */
const PERSONA_JOBS = {
  "Travel Planner": ["Plan a trip of 4 days for a group of 10 college friends."],
  "HR professional": ["Create and manage fillable forms for onboarding and compliance."],
  "Food Contractor": ["Prepare a buffet-style dinner menu for a corporate gathering, including gluten-free items."],
  "PhD Researcher": ["Extract related work and methods section from recent academic publications."],
  "Investment Analyst": ["Analyze revenue trends, R&D investments, and market positioning strategies."],
  "Undergraduate Chemistry Student": ["Identify key concepts and mechanisms for exam preparation on reaction kinetics."],
};

const TARGET_SECS = 10;

/* --------------------------------
   App
----------------------------------- */
export default function App() {
  const [apiStatus, setApiStatus] = useState("checking");

  const [pdfs, setPdfs] = useState([]); // File[]
  const [output, setOutput] = useState(""); // raw json text

  const [previewIndex, setPreviewIndex] = useState(-1);
  const previewFile = previewIndex >= 0 ? pdfs[previewIndex] : null;

  const personaList = Object.keys(PERSONA_JOBS);
  const [persona, setPersona] = useState(personaList[0]);
  const [job, setJob] = useState(PERSONA_JOBS[personaList[0]][0]);

  const [useCustom, setUseCustom] = useState(false);
  const [customPersona, setCustomPersona] = useState("");
  const [customJob, setCustomJob] = useState("");

  const [sectionText, setSectionText] = useState("");
  const [insight, setInsight] = useState("");
  const [podcastText, setPodcastText] = useState("");
  const [insightBusy, setInsightBusy] = useState(false);

  const [loading, setLoading] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const progressPct = loading
    ? Math.min(99, Math.round(Math.min(elapsedMs / (TARGET_SECS * 1000), 1) * 95 + 4))
    : 0;

  // PDF viewer API / pending jump
  const viewApiRef = useRef(null);
  const pendingLocRef = useRef(null); // { pageNumber, query }
  const lastRequestedPageRef = useRef(1);

  // [SNIPPETS] per-section explanation state
  const [snippetMap, setSnippetMap] = useState({});
  const [snippetBusy, setSnippetBusy] = useState({});
  const [snippetErr, setSnippetErr] = useState({});

  // page-jump & search state (page count is optional)
  const [currentPageInput, setCurrentPageInput] = useState(1);
  const [knownPageCount, setKnownPageCount] = useState(null);

  // optional client search (not shown in UI but kept)
  const [searchQ, setSearchQ] = useState("");
  const [searchPagesFlat, setSearchPagesFlat] = useState([]);
  const [searchHitIdx, setSearchHitIdx] = useState(-1);

  /* -------- Connected Insights state -------- */
  const [connections, setConnections] = useState(null);
  const [connBusy, setConnBusy] = useState(false);
  const [connErr, setConnErr] = useState("");

  /* ---------- backend health ---------- */
  useEffect(() => {
    (async () => {
      setApiStatus("checking");
      try {
        const res = await API.get("/health");
        if (res.status >= 200 && res.status < 500) setApiStatus("ok");
        else setApiStatus("fail");
      } catch (err) {
        if (err?.response) setApiStatus("ok");
        else setApiStatus("fail");
        console.warn("Health check:", err?.message || err);
      }
    })();
  }, []);

  /* ---------- derived ---------- */
  const jobOptions = useMemo(() => PERSONA_JOBS[persona] || [], [persona]);
  useEffect(() => {
    setJob(jobOptions[0] || "");
  }, [jobOptions]);

  const parsedOutput = useMemo(() => {
    if (!output || typeof output !== "string") return null;
    try {
      return JSON.parse(output);
    } catch {
      return null;
    }
  }, [output]);

  const extractedSections = useMemo(() => {
    const xs = parsedOutput?.extracted_sections || parsedOutput?.extractedSections;
    return Array.isArray(xs) ? xs : [];
  }, [parsedOutput]);

  /* ---------- handlers ---------- */
  const handleFileChange = (e) => {
    const files = Array.from(e.target.files || []);
    setPdfs(files);
    setOutput("");
    setPreviewIndex(-1);

    // hard reset navigation state
    setKnownPageCount(null);
    setCurrentPageInput(1);
    setSearchQ("");
    setSearchPagesFlat([]);
    setSearchHitIdx(-1);
    pendingLocRef.current = null;
    lastRequestedPageRef.current = 1;   // <— reset so new viewer starts at 1
  };

  const handleExtract = async () => {
    if (!pdfs.length) {
      alert("Please upload at least one PDF.");
      return;
    }
    const chosenPersona = useCustom ? customPersona.trim() : persona;
    const chosenJob = useCustom ? customJob.trim() : job;
    if (!chosenPersona || !chosenJob) {
      alert("Please provide both a persona and a job to be done.");
      return;
    }

    const formData = new FormData();
    pdfs.forEach((f) => formData.append("pdfs", f));
    formData.append("persona", chosenPersona);
    formData.append("job", chosenJob);

    setLoading(true);
    setElapsedMs(0);
    const t0 = Date.now();
    const timer = setInterval(() => setElapsedMs(Date.now() - t0), 120);

    try {
      const res = await API.post("/extract_1b", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      const data = res.data;
      const obj = data?.result ? JSON.parse(data.result) : data;
      setOutput(JSON.stringify(obj, null, 2));
    } catch (err) {
      console.error("Extract failed:", err);
      const e = err?.response?.data;
      const details =
        (e && (e.stderr || e.stdout || e.error)) ||
        err?.message ||
        "Unknown error";
      alert(`Extraction failed.\n\n${details}`);
    } finally {
      clearInterval(timer);
      setElapsedMs(Date.now() - t0);
      setLoading(false);
    }
  };

  const fetchInsight = async () => {
    const text = (sectionText || "").trim();
    if (!text) {
      alert("Paste a section first to get insights.");
      return;
    }
    setInsightBusy(true);
    setInsight("");
    try {
      const res = await API.post("/insight", { section_text: text });
      setInsight(res.data.insight || res.data.error || "(no insight)");
    } catch (err) {
      console.error("Insight failed:", err);
      setInsight(err?.response?.data?.error || err?.message || "Failed to fetch insight.");
    } finally {
      setInsightBusy(false);
    }
  };

  const ocrCurrentPdf = async () => {
    if (!previewFile) return;
    try {
      const fd = new FormData();
      fd.append("pdf", previewFile);
      const res = await API.post("/ocr_pdf", fd, { responseType: "blob" });
      const blob = new Blob([res.data], { type: "application/pdf" });
      const ocrFile = new File([blob], previewFile.name.replace(/\.pdf$/i, "_ocr.pdf"), {
        type: "application/pdf",
      });

      setPdfs((prev) => {
        const xs = [...prev];
        xs[previewIndex] = ocrFile;
        return xs;
      });

      const stay = Number(lastRequestedPageRef.current) || 1;
      pendingLocRef.current = { pageNumber: stay };

      setPreviewIndex(-1);
      setTimeout(() => setPreviewIndex(previewIndex), 0);
    } catch (err) {
      alert(err?.response?.data?.error || err?.message || "OCR failed");
    }
  };

  /* -------- Connect the Insights -------- */
  const connectInsights = async () => {
    const text = (sectionText || "").trim();
    if (!text) {
      alert("Paste a section first to connect insights.");
      return;
    }
    setConnBusy(true);
    setConnErr("");
    setConnections(null);
    try {
      const res = await API.post("/select_insights", {
        selection_text: text,
        top_k: 8,
      });
      setConnections(res.data);
    } catch (err) {
      setConnErr(
        err?.response?.data?.error || err?.message || "Failed to connect the dots."
      );
    } finally {
      setConnBusy(false);
    }
  };

  /* ======= Voice overview ======= */
  const [voiceBusy, setVoiceBusy] = useState(false);

  function stripMarkdown(s) {
    return String(s || "")
      .replace(/\*\*/g, "")
      .replace(/[_`>#]/g, "")
      .replace(/\[(.*?)\]\((.*?)\)/g, "$1");
  }

  function speakParagraphs(paragraphs) {
    const synth = window.speechSynthesis;
    if (!synth) {
      alert("Speech Synthesis not available.");
      return;
    }
    synth.cancel();
    setVoiceBusy(true);

    let i = 0;
    const next = () => {
      if (i >= paragraphs.length) {
        setVoiceBusy(false);
        return;
      }
      const u = new SpeechSynthesisUtterance(paragraphs[i]);
      u.onend = () => {
        i += 1;
        next();
      };
      u.onerror = () => setVoiceBusy(false);
      synth.speak(u);
    };
    next();
  }

  function voiceOverview() {
    const parts = [];

    if ((insight || "").trim()) {
      parts.push("Insights. " + stripMarkdown(insight.trim()));
    }

    if (connections) {
      const gs = connections.grounded_summary || "";
      if (gs.trim()) parts.push("Connected insights summary. " + stripMarkdown(gs));

      const recent = (connections.related_recent || [])
        .slice(0, 3)
        .map((r) => r.section_title)
        .filter(Boolean);
      if (recent.length) parts.push("Related recent: " + recent.join(", ") + ".");

      const past = (connections.related_past || [])
        .slice(0, 3)
        .map((r) => r.section_title)
        .filter(Boolean);
      if (past.length) parts.push("Related past: " + past.join(", ") + ".");

      const overlaps = (connections.overlaps || [])
        .slice(0, 2)
        .map((r) => r.section_title)
        .filter(Boolean);
      if (overlaps.length) parts.push("Overlaps: " + overlaps.join(", ") + ".");

      const contras = (connections.contradictions || [])
        .slice(0, 2)
        .map((r) => r.section_title)
        .filter(Boolean);
      if (contras.length) parts.push("Potential contradictions: " + contras.join(", ") + ".");
    }

    const text = parts.filter(Boolean).join("\n\n");
    if (!text) {
      alert("Generate an Insight or Connect the Insights first.");
      return;
    }

    const paragraphs = text
      .split(/\n{2,}|\r?\n/)
      .map((t) => t.trim())
      .filter(Boolean);

    speakParagraphs(paragraphs);
  }

  function stopVoice() {
    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    setVoiceBusy(false);
  }

  /* -------- Podcast -------- */
  const [isPodcastLoading, setIsPodcastLoading] = useState(false);
  const [isDuoLoading, setIsDuoLoading] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);

  const generateDuoPodcast = async () => {
    const basis = (sectionText || podcastText || "").trim();
    if (!basis) {
      alert("Paste some text first for the Duo podcast.");
      return;
    }
    try {
      setIsDuoLoading(true);
      const res = await API.post(
        "/podcast_duo",
        { selection_text: basis },
        { responseType: "arraybuffer", validateStatus: () => true }
      );
      await playAudioOrSpeak(res, { duo: true, setIsPlaying });
    } catch (err) {
      alert(err?.response?.data?.error || err?.message || "Failed to generate duo.");
    } finally {
      setIsDuoLoading(false);
    }
  };

  const generatePodcast = async () => {
    const txt = (podcastText || "").trim();
    if (!txt) {
      alert("Paste text for single-voice narration.");
      return;
    }
    try {
      setIsPodcastLoading(true);
      const res = await API.post(
        "/podcast",
        { section_text: txt },
        { responseType: "arraybuffer", validateStatus: () => true }
      );
      await playAudioOrSpeak(res, { duo: false, setIsPlaying });
    } catch (err) {
      console.error("Podcast failed:", err);
      alert("Failed to generate podcast.");
    } finally {
      setIsPodcastLoading(false);
    }
  };

  const stopPodcast = () => {
    stopAllAudio();
    setIsPlaying(false);
  };

  /* ---------- ONE-BASED NAV HELPERS ---------- */
  function _gotoOneBased(api, pageOneBased) {
    if (!api) return;
    const p = Math.max(1, Math.floor(Number(pageOneBased) || 1));
    if (typeof api.gotoLocation === "function") return api.gotoLocation({ pageNumber: p });
    if (typeof api.goToPage === "function") return api.goToPage(p);
    if (typeof api.setPage === "function") return api.setPage(p);
  }

  function gotoPageInViewer(n) {
    const page = Math.max(1, Math.floor(Number(n) || 1));
    lastRequestedPageRef.current = page;
    _gotoOneBased(viewApiRef.current, page);
    setCurrentPageInput(page);
  }

  /* ---------- jump to page from extracted list (with text find) ---------- */
  function jumpToPageInDoc(docName, pageNumberLike, queryText) {
    const page = Math.max(1, Math.floor(Number(pageNumberLike) || 1));

    const idx = pdfs.findIndex((f) => f.name === docName);
    if (idx === -1) {
      alert(`PDF not uploaded: ${docName}`);
      return;
    }

    pendingLocRef.current = { pageNumber: page, query: String(queryText || "") };
    lastRequestedPageRef.current = page;

    if (idx !== previewIndex) {
      setPreviewIndex(idx); // viewer opens; onReady will jump + find once
    } else {
      _gotoOneBased(viewApiRef.current, page);
      if (queryText && viewApiRef.current?.findAndScroll) {
        setTimeout(() => viewApiRef.current.findAndScroll(queryText, { pageHint: page }), 120);
      }
      pendingLocRef.current = null;
    }
  }

  // ---------- [SNIPPETS] helpers ----------
  function findRefinedTextFor(docName, pageNumber) {
    const arr = parsedOutput?.sub_section_analysis;
    if (!Array.isArray(arr)) return null;

    for (const item of arr) {
      const d = item.document || item.doc || "";
      const p = Number(item.page_number ?? item.pageNumber ?? NaN);
      if (d === docName && Number.isFinite(p) && p === pageNumber) {
        if (typeof item.refined_text === "string" && item.refined_text.trim()) {
          return item.refined_text.trim();
        }
      }
    }
    return null;
  }

  async function explainSection(section, index) {
    try {
      setSnippetBusy((m) => ({ ...m, [index]: true }));
      setSnippetErr((m) => ({ ...m, [index]: "" }));

      const raw = Number(section.page_number ?? section.pageNumber ?? 1);
      const page = Number.isFinite(raw) ? Math.max(1, raw) : 1;

      const candidate =
        findRefinedTextFor(section.document, page) ||
        section.section_title ||
        "This section";

      const focusText = (useCustom ? customJob : job) || "the selected job";

      const res = await API.post("/snippet_explain", {
        focus_text: String(focusText),
        candidate_text: String(candidate),
      });

      const snippet =
        (res?.data && (res.data.snippet || res.data.error)) ||
        "No concise reason found.";

      setSnippetMap((m) => ({ ...m, [index]: snippet }));
    } catch (err) {
      console.error("snippet_explain failed:", err);
      setSnippetErr((m) => ({
        ...m,
        [index]:
          err?.response?.data?.error ||
          err?.message ||
          "Failed to generate snippet.",
      }));
    } finally {
      setSnippetBusy((m) => ({ ...m, [index]: false }));
    }
  }

  /* ---------- little style helpers ---------- */
  const outlineShell = {
    border: "2px solid color-mix(in oklab, var(--accent-to) 60%, white 40%)",
    borderRadius: 12,
    padding: 0,
    display: "inline-block",
    background: "transparent",
    boxShadow: "0 8px 22px rgba(124,58,237,.15)",
  };
  const inputInner = {
    background: "transparent",
    color: "var(--ink)",
    padding: "10px 12px",
    border: "none",
    outline: "none",
    width: "100%",
  };
  const preInner = {
    ...inputInner,
    padding: 16,
    whiteSpace: "pre-wrap",
    wordWrap: "break-word",
    fontFamily:
      'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
  };

  const prettySecs = (ms) => (ms / 1000).toFixed(1);
  const effectivePersona = useCustom ? customPersona || "(custom…)" : persona;
  const effectiveJob = useCustom ? customJob || "(custom…)" : job;

  // ===== optional search in current PDF (kept) =====
  const runSearchInCurrentPdf = async () => {
    try {
      const q = (searchQ || "").trim().toLowerCase();
      if (!previewFile || !q) {
        setSearchPagesFlat([]);
        setSearchHitIdx(-1);
        return;
      }

      const pdfjsLib = await import("pdfjs-dist/build/pdf");
      const pdfjsWorker = await import("pdfjs-dist/build/pdf.worker.entry");
      pdfjsLib.GlobalWorkerOptions.workerSrc = pdfjsWorker;

      const data = await previewFile.arrayBuffer();
      const doc = await pdfjsLib.getDocument({ data }).promise;

      if (!knownPageCount) setKnownPageCount(doc.numPages);

      const flat = [];
      for (let p = 1; p <= doc.numPages; p++) {
        const page = await doc.getPage(p);
        const tc = await page.getTextContent();
        const joined = tc.items.map((it) => String(it.str)).join(" ").toLowerCase();
        if (!joined) continue;

        let idx = 0;
        while (true) {
          const hit = joined.indexOf(q, idx);
          if (hit === -1) break;
          flat.push(p);
          idx = hit + q.length;
        }
      }

      setSearchPagesFlat(flat);
      if (flat.length) {
        setSearchHitIdx(0);
        gotoPageInViewer(flat[0]);
      } else {
        setSearchHitIdx(-1);
      }
    } catch (e) {
      console.warn("Search failed:", e);
      setSearchPagesFlat([]);
      setSearchHitIdx(-1);
    }
  };

  const jumpSearchHit = (dir) => {
    if (!searchPagesFlat.length) return;
    let i = searchHitIdx < 0 ? 0 : searchHitIdx;
    i = (i + dir + searchPagesFlat.length) % searchPagesFlat.length;
    setSearchHitIdx(i);
    gotoPageInViewer(searchPagesFlat[i]);
  };

  /* ---------- UI ---------- */
  return (
    <>
      {/* NAV */}
      <header className="nav">
        <div className="nav__inner">
          <a className="brand" href="#" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <img
              src={LunaLogo}
              alt="Luna Logo"
              style={{
                height: "32px",
                width: "32px",
                borderRadius: "6px",
                objectFit: "contain"
              }}
            />
           
          </a>

          <nav className="nav__links" style={{
            display: 'flex',
            gap: '2em',
            fontWeight: '600',
            fontSize: '1.1em',
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
            justifyContent: 'center',
            alignItems: 'center',
          }}>
            {["Home", "About", "Services", "Contact"].map((label) => (
              <a
                key={label}
                href={
                  label === "Home" ? "#" :
                  label === "About" ? "#faq" :
                  label === "Services" ? "#extractor" :
                  "#contact"
                }
                style={{
                  position: 'relative',
                  color: 'white',
                  textDecoration: 'none',
                  transition: 'color 0.3s ease',
                }}
                onMouseEnter={(e) => { e.target.style.color = "#C83FB1"; }}
                onMouseLeave={(e) => { e.target.style.color = "white"; }}
              >
                {label}
                <span
                  style={{
                    position: 'absolute',
                    left: 0,
                    bottom: '-4px',
                    width: '100%',
                    height: '2px',
                    background: 'linear-gradient(90deg, #C83FB1, #7E30E1)',
                    transform: 'scaleX(0)',
                    transformOrigin: 'left',
                    transition: 'transform 0.3s ease',
                    pointerEvents: 'none',
                  }}
                  className="nav-underline"
                />
              </a>
            ))}
          </nav>

          <div className="nav__right">
            <span
              className={`status-pill ${
                apiStatus === "ok"
                  ? "status-ok"
                  : apiStatus === "checking"
                  ? "status-checking"
                  : "status-fail"
              }`}
              title={
                apiStatus === "ok"
                  ? "Backend reachable"
                  : apiStatus === "checking"
                  ? "Checking backend…"
                  : "Backend not reachable"
              }
            >
              {apiStatus === "ok"
                ? "Server Status: Up"
                : apiStatus === "checking"
                ? "Checking…"
                : "Server Status: Down"}
            </span>
          </div>
        </div>
      </header>

      <main className="hero">
        <div className="hero__content" style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          maxWidth: '900px',
          transform: 'translateY(-2.5em)',
          fontSize: '1.15em',
          margin: '0 auto',
          padding: '2rem'
        }}>
          <div style={{
            display: 'flex',
            alignItems: 'baseline',
            justifyContent: 'center',
            fontSize: '3.8em',
            fontWeight: 'bold',
            marginBottom: '0.01em',
          }}>
            <img
              src={LunaLogo}
              alt="Luna Logo"
              style={{
                height: '3em',
                marginRight: '-0.8em',
                position: 'relative',
                top: '0.8em'
              }}
            />
            <span style={{ color: 'white' }}>una</span>
          </div>

          <h1 style={{
            textAlign: 'center',
            fontSize: '2.8em',
            fontWeight: 'bold',
            color: 'white',
            lineHeight: 1.2
          }}>
            <span style={{
              background: 'linear-gradient(90deg, #C83FB1, #7E30E1)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              fontWeight: 'bold'
            }}>
              Document Intelligence Reader
            </span>
          </h1>

          <p className="hero__sub" id="learn" style={{ fontSize: '1.1em' }}>
            Drop in your PDFs and watch chaos turn into clarity as you generate insights,
            spot cross-document connections and bring your content to life with rich audio overviews and podcast-style narrations.
          </p>

          <div className="hero__cta">
            <a href="#extractor" className="btn btn--primary">Start Your Journey</a>
            <a href="#faq" className="btn btn--primary">Learn More</a>
          </div>
        </div>
      </main>

      {/* TOOLS */}
      <section id="extractor" className="app container panel" style={{ padding: 20 }}>
        {/* Persona & Job */}
        <div style={{
          fontSize: "1.6em",
          fontWeight: "bold",
          margin: "20px 0 10px",
          color: "var(--accent)",   // use the same accent class color

          display: "flex",
          alignItems: "center",
          gap: "0.5em"
        }}>
          <span role="img" aria-label="briefcase">💼</span> Persona <span className="accent">& Job</span>

        </div>

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
          <div style={{ ...outlineShell, minWidth: 280, flex: 1, opacity: useCustom ? 0.5 : 1 }}>
            <select
              className="select-themed"
              value={persona}
              onChange={(e) => setPersona(e.target.value)}
              style={inputInner}
              aria-label="Persona (preset options)"
              disabled={useCustom}
            >
              {personaList.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>

          <div style={{ ...outlineShell, minWidth: 420, flex: 2, opacity: useCustom ? 0.5 : 1 }}>
            <select
              className="select-themed"
              value={job}
              onChange={(e) => setJob(e.target.value)}
              style={inputInner}
              aria-label="Job to be Done (preset options)"
              disabled={useCustom}
            >
              {jobOptions.map((j, idx) => (
                <option key={idx} value={j}>
                  {j}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* custom toggle + fields */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
          <input
            id="toggle-custom"
            type="checkbox"
            checked={useCustom}
            onChange={(e) => setUseCustom(e.target.checked)}
          />
          <label htmlFor="toggle-custom" className="muted-label">
            Use custom persona/job
          </label>
        </div>

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 10 }}>
          <div style={{ ...outlineShell, minWidth: 280, flex: 1 }}>
            <input
              type="text"
              placeholder="Type custom persona…"
              value={customPersona}
              onChange={(e) => setCustomPersona(e.target.value)}
              style={inputInner}
              disabled={!useCustom}
              aria-label="Custom persona"
            />
          </div>
          <div style={{ ...outlineShell, minWidth: 420, flex: 2 }}>
            <input
              type="text"
              placeholder="Type custom job to be done…"
              value={customJob}
              onChange={(e) => setCustomJob(e.target.value)}
              style={inputInner}
              disabled={!useCustom}
              aria-label="Custom job"
            />
          </div>
        </div>

        <div className="muted" style={{ marginBottom: 12, color: "#ffffff" }}>
          <strong>Selected Persona:</strong> {effectivePersona} &nbsp;|&nbsp;{" "}
          <strong>Job:</strong> {effectiveJob}
        </div>

        {/* upload + extract */}
        <div
          style={{
            display: "flex",
            gap: 10,
            alignItems: "center",
            flexWrap: "wrap",
            marginBottom: 12,
          }}
        >
          <div style={outlineShell}>
            <input
              className="file-rose"
              type="file"
              onChange={handleFileChange}
              multiple
              accept="application/pdf"
              style={inputInner}
            />
          </div>

          {pdfs.length > 0 && (
            <div
              style={{
                ...outlineShell,
                padding: 8,
                display: "flex",
                gap: 8,
                flexWrap: "wrap",
                maxWidth: "100%",
              }}
            >
              {pdfs.map((f, i) => {
                const selected = i === previewIndex;
                return (
                  <button
                    key={i}
                    type="button"
                    onClick={() => {
                      // open a file at page 1 unless a pending jump is provided
                      pendingLocRef.current = null;
                      lastRequestedPageRef.current = 1; // <— defensive reset
                      setCurrentPageInput(1);
                      setPreviewIndex(i);
                    }}
                    className={`btn ${selected ? "btn--primary" : "btn--outline"}`}
                    title="Click to open viewer"
                    style={{
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      maxWidth: 260,
                    }}
                  >
                    {f.name}
                  </button>
                );
              })}
            </div>
          )}

          <button
            className="btn btn--primary"
            onClick={handleExtract}
            disabled={loading}
            title="Run extraction"
          >
            {loading ? "Processing…" : "Extract"}
          </button>
        </div>

        {(loading || elapsedMs > 0) && (
          <div style={{ marginBottom: 12 }}>
            <div
              style={{
                height: 12,
                width: "100%",
                background: "rgba(255,255,255,.12)",
                borderRadius: 999,
                overflow: "hidden",
                boxShadow: "inset 0 0 0 1px rgba(255,255,255,.35)",
              }}
              aria-label="Processing progress"
            >
              <div
                style={{
                  height: "100%",
                  width: loading ? `${progressPct}%` : "100%",
                  transition: "width .2s linear",
                  background: "#ffffff",
                  boxShadow: "0 0 10px rgba(255,255,255,.35)",
                }}
              />
            </div>
            <div className="muted" style={{ marginTop: 6, color: "#ffffff" }}>
              {loading
                ? `Elapsed: ${prettySecs(elapsedMs)}s · estimating ~${TARGET_SECS}s`
                : `Completed in ${prettySecs(elapsedMs)}s`}
            </div>
          </div>
        )}

        {/* OUTPUT */}
        <h2 id="output" className="section-title" style={{ marginTop: 10 }}>
          <span className="emoji">📄</span> <span className="accent">Output</span>
        </h2>
        <div
          style={{
            borderRadius: 12,
            padding: 2,
            background: "linear-gradient(135deg, var(--accent-from), var(--accent-to))",
            marginBottom: 18,
          }}
        >
          <div className="pre-rose" style={{ maxHeight: 400, overflow: "auto" }}>
            {(() => {
              let parsed = null;
              if (typeof output === "string") {
                try {
                  parsed = JSON.parse(output);
                } catch {
                  /* not JSON */
                }
              } else if (output && typeof output === "object") {
                parsed = output;
              }
              return parsed ? <Braceless data={parsed} /> : <div style={{ padding: 4 }}>{output}</div>;
            })()}
          </div>
        </div>

        {/* EXTRACTED SECTIONS */}
        {extractedSections.length > 0 && (
          <>
            <h2 className="section-title" style={{ marginTop: 10 }}>
              <span className="emoji">🔎</span> Extracted <span className="accent">Sections</span>
            </h2>
            <div style={{ display: "grid", gap: 10 }}>
              {extractedSections.map((s, i) => {
                const raw = Number(s.page_number ?? s.pageNumber ?? 1);
                const page = Number.isFinite(raw) ? Math.max(1, raw) : 1;

                return (
                  <div key={i} style={{ display: "grid", gap: 6 }}>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      <button
                        type="button"
                        className="btn btn--primary"
                        title={`Go to page ${page} in ${s.document}`}
                        onClick={() => jumpToPageInDoc(s.document, page, s.section_title)}
                        style={{
                          justifySelf: "start",
                          maxWidth: 620,
                          textAlign: "left",
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                      >
                        {(s.section_title || "(untitled)") + " — p." + page}
                      </button>

                      <button
                        type="button"
                        className="btn btn--primary"
                        onClick={() => explainSection(s, i)}
                        title="Explain why this is relevant to the job"
                      >
                        {snippetBusy[i] ? "Explaining…" : "Why this section?"}
                      </button>
                    </div>

                    {(snippetErr[i] || snippetMap[i]) && (
                      <div
                        style={{
                          borderRadius: 12,
                          padding: 2,
                          background: "linear-gradient(135deg, var(--accent-from), var(--accent-to))",
                          boxShadow: "0 8px 24px rgba(124,58,237,.18)",
                          width: "100%",
                          marginTop: 6,
                        }}
                      >
                        <div
                          style={{
                            borderRadius: 10,
                            padding: "10px 12px",
                            background: "rgba(10,12,22,.78)",
                            color: "#e9e9ff",
                          }}
                        >
                          {snippetErr[i] ? (
                            <span style={{ color: "#ffb4b4" }}>{snippetErr[i]}</span>
                          ) : (
                            <span>{snippetMap[i]}</span>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </>
        )}

        {/* INSIGHTS */}
        <h2 id="insights" className="section-title">
          <span className="emoji">💡</span> Insights <span className="accent">Bulb</span>
        </h2>
        <div className="field" style={{ width: "100%", marginBottom: 10 }}>
          <textarea
            value={sectionText}
            onChange={(e) => setSectionText(e.target.value)}
            placeholder="Paste a section or paragraph to get insights..."
            rows={3}
            className="input textarea-rose"
            style={{ width: "100%" }}
          />
        </div>

        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "nowrap" }}>
          <button className="btn btn--primary" onClick={fetchInsight}>
            Get Insights
          </button>

          <button
            className="btn btn--primary"
            onClick={connectInsights}
            title="Find related/overlapping/contradictory sections"
          >
            Connect the Insights
          </button>

          <button
            className="btn btn--primary"
            onClick={voiceOverview}
            disabled={voiceBusy}
            title="Read the generated insights and connections"
          >
            {voiceBusy ? "Speaking…" : "Play Audio Summary"}
          </button>

          <button
            className="btn btn--danger"
            onClick={stopVoice}
            disabled={!voiceBusy}
            title="Stop voice"
          >
            Stop
          </button>
        </div>

       {insightBusy && (
  <div className="muted" style={{ marginTop: 10 }}>
    Generating insight…
  </div>
)}
{insight && !insightBusy && (
  <div className="field" style={{ width: "100%", marginTop: 10 }}>
    <div className="pre-rose" style={preInner}>
      {insight}
    </div>
  </div>
)}

        {connBusy && <div className="muted" style={{ marginTop: 10 }}>Connecting the dots…</div>}
        {connErr && <div style={{ color: "#ffb4b4", marginTop: 10 }}>{connErr}</div>}
        {connections && (
          <div className="field" style={{ width: "100%", marginTop: 10 }}>
            <div className="pre-rose" style={preInner}>
<strong>Grounded Summary</strong>
<div style={{ marginTop: 6 }}>
  {cleanConnectText(connections.grounded_summary || "(none)")}
</div>
<div style={{ marginTop: 10 }} />

<strong>Related (Recent)</strong>
<ul style={{ marginTop: 6 }}>
  {uniqueBy((connections.related_recent || []), keyFor).map((r, i) => (
    <li key={i}>
      {cleanConnectText(r.section_title)} — <em>{cleanConnectText(r.document)}</em> (p.{r.page_number})
    </li>
  ))}
</ul>

<strong>Related (Past)</strong>
<ul style={{ marginTop: 6 }}>
  {uniqueBy((connections.related_past || []), keyFor).map((r, i) => (
    <li key={i}>
      {cleanConnectText(r.section_title)} — <em>{cleanConnectText(r.document)}</em> (p.{r.page_number})
    </li>
  ))}
</ul>

<strong>Overlaps</strong>
<ul style={{ marginTop: 6 }}>
  {uniqueBy((connections.overlaps || []), keyFor).map((r, i) => (
    <li key={i}>
      {cleanConnectText(r.section_title)} — <em>{cleanConnectText(r.document)}</em> (p.{r.page_number})
    </li>
  ))}
</ul>

<strong>Contradictions</strong>
<ul style={{ marginTop: 6 }}>
  {uniqueBy((connections.contradictions || []), keyFor).map((r, i) => (
    <li key={i}>
      {cleanConnectText(r.section_title)} — <em>{cleanConnectText(r.document)}</em> (p.{r.page_number})
    </li>
  ))}
</ul>

            </div>
          </div>
        )}


        {/* PODCAST */}
        <h2 id="podcast" className="section-title" style={{ marginTop: 26 }}>
          <span className="emoji">🎧</span> Podcast <span className="accent">Mode</span>
        </h2>
        <div className="field" style={{ width: "100%", marginBottom: 10 }}>
          <textarea
            value={podcastText}
            onChange={(e) => setPodcastText(e.target.value)}
            placeholder="Paste section for audio narration..."
            rows={3}
            className="input textarea-rose"
            style={{ width: "100%" }}
          />
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          <button className="btn btn--primary" onClick={generatePodcast} disabled={isPodcastLoading}>
            {isPodcastLoading ? "Generating…" : "Generate Podcast"}
          </button>
          <button
            className="btn btn--primary"
            onClick={generateDuoPodcast}
            title="Two-voice, grounded on your pasted text"
            disabled={isDuoLoading}
          >
            {isDuoLoading ? "Generating…" : "Generate Duo"}
          </button>
          <button className="btn btn--danger" onClick={stopPodcast} disabled={!isPlaying}>
            Stop
          </button>
          {isPlaying && <span className="muted" style={{ color: "#cbd5e1" }}>Playing…</span>}
        </div>
      </section>

      {/* VIEWER MODAL */}
      {previewFile && (
        <div
          role="dialog"
          aria-modal="true"
          onClick={() => {
            setPreviewIndex(-1);
            viewApiRef.current = null;

            // reset search/jump UI when closing
            setKnownPageCount(null);
            setCurrentPageInput(1);
            setSearchQ("");
            setSearchPagesFlat([]);
            setSearchHitIdx(-1);
          }}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,.55)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 9999,
            padding: 16,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: 540,
              height: 760,
              background: "var(--panel, #0b0b18)",
              borderRadius: 14,
              boxShadow: "0 14px 40px rgba(0,0,0,.45)",
              display: "flex",
              flexDirection: "column",
              overflow: "hidden",
              border: "1px solid rgba(255,255,255,.1)",
            }}
          >
            {/* HEADER */}
            <div
              style={{
                padding: "10px 12px",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                borderBottom: "1px solid rgba(255,255,255,.08)",
                color: "#fff",
                fontSize: 13,
                gap: 8,
              }}
            >
              <div
                title={previewFile.name}
                style={{
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  maxWidth: 200,
                }}
              >
                📄 {previewFile.name}
              </div>

              {/* Header page cube */}
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <input
                    value={currentPageInput}
                    onChange={(e) => {
                      const v = e.target.value;
                      setCurrentPageInput(v === "" ? "" : Number(v));
                      if (v !== "" && Number.isFinite(Number(v))) {
                        gotoPageInViewer(Number(v));
                      }
                    }}
                    style={{
                      width: 56,
                      textAlign: "center",
                      padding: "4px 6px",
                      borderRadius: 8,
                      border: "1px solid rgba(255,255,255,.14)",
                      background: "rgba(255,255,255,.06)",
                      color: "#fff",
                    }}
                    aria-label="Go to page"
                  />
                  <span style={{ color: "#bbb" }}>
                    / {knownPageCount ?? "—"}
                  </span>
                </div>
              </div>

              <button
                onClick={() => {
                  setPreviewIndex(-1);
                  viewApiRef.current = null;
                  setKnownPageCount(null);
                  setCurrentPageInput(1);
                  setSearchQ("");
                  setSearchPagesFlat([]);
                  setSearchHitIdx(-1);
                }}
                className="btn btn--outline"
                style={{ padding: "4px 10px" }}
                aria-label="Close viewer"
              >
                ✕
              </button>
            </div>

            {/* VIEWER */}
            <div style={{ flex: 1, minHeight: 0 }}>
              <AdobeInlineViewer
                file={previewFile}
                height="100%"
                onReady={(api) => {
                  viewApiRef.current = api;

                  // Discover page count if exposed
                  try {
                    const exposedCount =
                      api?.numPages ??
                      api?.pageCount ??
                      (typeof api?.getPageCount === "function" ? api.getPageCount() : null);
                    if (exposedCount && Number.isFinite(Number(exposedCount))) {
                      setKnownPageCount(Number(exposedCount));
                    }
                  } catch (_) {}

                  // *** IMPORTANT: Open at page 1 unless a pending jump exists ***
                  const target = (pendingLocRef.current?.pageNumber) || 1;
                  const query  = pendingLocRef.current?.query || "";

                  setTimeout(() => _gotoOneBased(api, target), 30);
                  if (query && typeof api.findAndScroll === "function") {
                    setTimeout(() => api.findAndScroll(query, { pageHint: target }), 150);
                  }

                  setCurrentPageInput(target);
                  lastRequestedPageRef.current = target;
                  pendingLocRef.current = null;
                }}
              />
            </div>

            {/* Bottom Prev/Next controls */}
            <div
              style={{
                padding: "6px 10px",
                display: "flex",
                gap: 8,
                justifyContent: "center",
                alignItems: "center",
              }}
            >
              <button
                className="btn btn--primary"
                onClick={() => gotoPageInViewer(Number(currentPageInput) - 1)}
                disabled={Number(currentPageInput) <= 1}
                style={{ color: "white", borderColor: "#C83FB1", background: "#C83FB1" }}
              >
                Prev page
              </button>
              <button
                className="btn btn--primary"
                onClick={() => gotoPageInViewer(Number(currentPageInput) + 1)}
                disabled={
                  knownPageCount
                    ? Number(currentPageInput) >= Number(knownPageCount)
                    : false
                }
                style={{ color: "white", borderColor: "#C83FB1", background: "#C83FB1" }}
              >
                Next page
              </button>
            </div>

            {/* FOOTER: mirrored page cube */}
            <div
              style={{
                padding: "8px 12px",
                display: "flex",
                justifyContent: "flex-end",
                alignItems: "center",
                borderTop: "1px solid rgba(255,255,255,.08)",
                gap: 6,
              }}
            >
              <input
                value={currentPageInput}
                onChange={(e) => {
                  const v = e.target.value;
                  setCurrentPageInput(v === "" ? "" : Number(v));
                  if (v !== "" && Number.isFinite(Number(v))) {
                    gotoPageInViewer(Number(v));
                  }
                }}
                style={{
                  width: 56,
                  textAlign: "center",
                  padding: "4px 6px",
                  borderRadius: 8,
                  border: "1px solid rgba(255,255,255,.14)",
                  background: "rgba(255,255,255,.06)",
                  color: "#fff",
                }}
                aria-label="Go to page (footer)"
              />
              <span style={{ color: "#bbb" }}>/ {knownPageCount ?? "—"}</span>
            </div>
          </div>
        </div>
      )}

      {/* ABOUT / FAQ SECTION */}
      <section id="faq" className="app container panel" style={{ padding: "2em 1em", background: "#1a1a2e", color: "white" }}>
        <h2 style={{ fontSize: "2em", textAlign: "center", marginBottom: "1em" }}>
           <span className="accent">Frequently Asked Questions</span>
        </h2>

        <div style={{ maxWidth: 800, margin: "0 auto" }}>
          <details style={{ marginBottom: "1em" }}>
            <summary style={{ cursor: "pointer", fontWeight: "bold", fontSize: "1.1em" }}>
              What does Luna do with my PDF?
            </summary>
            <p>Luna analyzes your PDFs, extracts key sections, summarizes insights, and even generates podcast-style audio from it.</p>
          </details>

          <details style={{ marginBottom: "1em" }}>
            <summary style={{ cursor: "pointer", fontWeight: "bold", fontSize: "1.1em" }}>
              Is the data sent to a server?
            </summary>
            <p>Your PDFs are processed locally or sent securely to the Luna backend for analysis. No data is stored permanently.</p>
          </details>

          <details style={{ marginBottom: "1em" }}>
            <summary style={{ cursor: "pointer", fontWeight: "bold", fontSize: "1.1em" }}>
              Can I generate podcasts from multiple documents?
            </summary>
            <p>Yes. Luna supports combining multiple documents and generating narrated summaries or duo podcasts from them.</p>
          </details>

          <details style={{ marginBottom: "1em" }}>
            <summary style={{ cursor: "pointer", fontWeight: "bold", fontSize: "1.1em" }}>
              What makes Luna different from a PDF viewer?
            </summary>
            <p>Luna doesn't just view PDFs — it intelligently summarizes, connects insights, explains sections, and even narrates them with voice.</p>
          </details>

          <details style={{ marginBottom: "1em" }}>
            <summary style={{ cursor: "pointer", fontWeight: "bold", fontSize: "1.1em" }}>
              How do I get started with this app?
            </summary>
            <p>Step 1: Select a persona and job — for example, "PhD Researcher" + "Extract related work from academic papers."</p>
              <p>Step 2: Upload one or more PDF documents.</p>
             <p> Step 3: Click Extract to generate outputs like summaries, insights, and more.</p>
          </details>

          <details style={{ marginBottom: "1em" }}>
            <summary style={{ cursor: "pointer", fontWeight: "bold", fontSize: "1.1em" }}>
              What does "Get Insights" do?
            </summary>
            <p>This analyzes any paragraph or section you paste and gives you smart, contextual insights — perfect for understanding key points, generating summaries, or discovering hidden themes.</p>
          </details>

          <details style={{ marginBottom: "1em" }}>
            <summary style={{ cursor: "pointer", fontWeight: "bold", fontSize: "1.1em" }}>
              What is "Connect the Insights"?
            </summary>
            <p>It looks across all uploaded PDFs and:</p> 

             <p> Finds related content or repeated themes.</p> 

             <p> Spots contradictions across authors or papers.</p> 

            <p> Links ideas to help build a bigger narrative.</p> 

            <p> This helps researchers, students, and analysts synthesize information better.</p>
          </details>

          <details style={{ marginBottom: "1em" }}>
            <summary style={{ cursor: "pointer", fontWeight: "bold", fontSize: "1.1em" }}>
              What’s the difference between “Play Audio Summary” and Podcast options?
            </summary>
            <p>Play Audio Summary: Quick, AI-generated voice summary of your insight or paragraph.</p>

              <p>Generate Podcast / Duo:</p>

             <p> Solo podcast: One voice narrates your content.</p>

              <p>Duo podcast: Two-character voice dialogue for more engaging delivery.</p>
          </details>

          <details style={{ marginBottom: "1em" }}>
            <summary style={{ cursor: "pointer", fontWeight: "bold", fontSize: "1.1em" }}>
              Can I click on an extracted section to view it in the PDF?
            </summary>
            <p>Yes!
              When you extract information, the app shows a snippet and links it directly to the page number in your uploaded PDF. Just click the snippet, and you’ll jump right to that exact page in the viewer.</p>
          </details>
        </div>
      </section>

      <section id="contact" style={{ padding: "60px 20px", textAlign: "center" }}>
        <h2 style={{ fontSize: "2em", marginBottom: "20px" }}><span className="accent">Contact</span></h2>

        <div style={{ display: "flex", justifyContent: "center", gap: "60px", flexWrap: "wrap" }}>
          <div>
            <h3 style={{ marginBottom: "6px", color: "hotpink" }}>Srijeeta Boral</h3>
            <a href="mailto:srijeetaboral7@gmail.com" style={{ color: "#fff", textDecoration: "underline" }}>
              srijeetaboral7@gmail.com
            </a>
          </div>

          <div>
            <h3 style={{ marginBottom: "6px", color: "hotpink" }}>Sandhita Goswami</h3>
            <a href="mailto:goswamisandhita@gmail.com" style={{ color: "#fff", textDecoration: "underline" }}>
              goswamisandhita@gmail.com
            </a>
          </div>
        </div>
      </section>
    </>
  );
}
