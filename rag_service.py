"""
Smart Energy AI - RAG (Retrieval-Augmented Generation) Service

Responsibility:
    Knowledge retrieval and contextual explanation ONLY.

    It does NOT replace the Agent, the ML models, the optimizer, the
    Digital Twin simulator or the database. Live operational data stays
    with the Agent and its tools; this module answers "how / why"
    questions from the documents in knowledge/energy/.

Pipeline:
    question -> BM25 retrieval over document sections -> top chunks
             -> answer generation (LLM if configured, extractive otherwise)
             -> {"answer": ..., "sources": [...]}

Design notes:
    - Pure Python retrieval (BM25). No vector database or embedding model
      is required, so the dashboard starts with zero extra dependencies.
    - LLM generation is optional. Configure with environment variables:
          RAG_LLM_PROVIDER   anthropic | openai | none   (default: auto)
          ANTHROPIC_API_KEY  enables provider "anthropic"
          OPENAI_API_KEY     enables provider "openai"
          OPENAI_BASE_URL    optional, any OpenAI-compatible endpoint
          RAG_LLM_MODEL      model name override
      With no key the service still answers, using an extractive summary of
      the retrieved sections, and says so in the response.
    - Every failure is caught and reported as a structured error; the Flask
      dashboard never depends on this module being healthy.
"""

from __future__ import annotations

import math
import os
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # project-data answers (readings, events, actions); optional
    import data_qa
except Exception as _dq_exc:  # noqa: BLE001
    data_qa = None
    DATA_QA_IMPORT_ERROR = str(_dq_exc)
else:
    DATA_QA_IMPORT_ERROR = None

BASE_DIR = Path(__file__).resolve().parent
KNOWLEDGE_DIR = Path(os.getenv("RAG_KNOWLEDGE_DIR", BASE_DIR / "knowledge" / "energy"))
# Arabic translations of the same documents, so Arabic questions are answered
# (and quoted) in Arabic even without a language model.
KNOWLEDGE_DIR_AR = Path(os.getenv("RAG_KNOWLEDGE_DIR_AR", BASE_DIR / "knowledge" / "energy_ar"))

# Files that describe the knowledge base itself rather than energy topics.
EXCLUDED_FILES = {"readme.md"}

SUPPORTED_SUFFIXES = {".md", ".txt"}

MAX_CHUNK_CHARS = 1200
TOP_K = 4
MIN_SCORE = 0.8           # below this, a section is not considered relevant
DATA_DOC_MIN_SCORE = 6.0  # with a data answer, only strongly related sections are added
DATA_DOC_MAX = 2
LLM_TIMEOUT_SECONDS = 30

DEFAULT_MODELS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
    "groq": "openai/gpt-oss-20b",
}

STOPWORDS = set(
    """
    a an and are as at be been but by can could do does for from had has have
    how i if in into is it its may me might more most my no not of on or our
    should so such than that the their them then there these they this those to
    too was we were what when where which while who why will with would you your
    about also any each other over under very just only same both between during
    """.split()
)


# =========================================================
# TEXT PROCESSING
# =========================================================


def _stem(token: str) -> str:
    """Very light suffix stripping so 'reducing' matches 'reduce'."""
    for suffix in ("ations", "ation", "ings", "ing", "ies", "ers", "ed", "es", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            base = token[: -len(suffix)]
            if suffix == "ies":
                return base + "y"
            return base
    return token


AR_STOPWORDS = set(
    """
    في من على الى عن ما ماذا كيف لماذا ليش ليه هل هو هي هم ان او و ثم كل هذا هذه ذلك تلك التي الذي الذين
    مع عند قد كان كانت يكون تكون بين لا ليس شو ايش اي وين متى لما حتى اذا لو بعد قبل عندما لكن او ام
    انه انها به بها له لها فيه فيها منه منها عليه عليها كما ايضا جدا فقط اكثر اقل يمكن يجب اللي بدي مين
    """.split()
)
_AR_PREFIXES = ("وبال", "وال", "بال", "كال", "فال", "لل", "ال", "و", "ب", "ف", "ل")
_AR_SUFFIXES = ("ات", "ون", "ين", "ان", "ها", "هم", "ه", "ي")
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def _ar_norm(text: str) -> str:
    t = text.translate(_AR_DIGITS)
    t = re.sub(r"[\u0617-\u061A\u064B-\u0652\u0640]", "", t)
    t = re.sub("[إأآٱ]", "ا", t)
    return t.replace("ة", "ه").replace("ى", "ي")


def _ar_stem(tok: str) -> str:
    for p in _AR_PREFIXES:
        if tok.startswith(p) and len(tok) - len(p) >= 3:
            tok = tok[len(p):]
            break
    for suf in _AR_SUFFIXES:
        if tok.endswith(suf) and len(tok) - len(suf) >= 3:
            tok = tok[: -len(suf)]
            break
    return tok


def tokenize(text: str) -> List[str]:
    lowered = text.lower()
    tokens = [_stem(t) for t in re.findall(r"[a-z0-9]+", lowered) if t not in STOPWORDS and len(t) > 1]
    if re.search(r"[\u0600-\u06FF]", lowered):
        for t in re.findall(r"[\u0621-\u064A]+", _ar_norm(lowered)):
            if t in AR_STOPWORDS or len(t) < 2:
                continue
            tokens.append(_ar_stem(t))
    return tokens


# The documents are in English and BM25 matches words, so an Arabic question
# would retrieve nothing. Arabic keywords are mapped to the English terms the
# documents use and appended to the retrieval query.
ARABIC_TERMS = [
    (r"تكييف|تبريد|تدفئ|مكيف", "hvac cooling heating setpoint"),
    (r"شمسي|الواح|خلايا", "solar pv generation"),
    (r"بطاري|تخزين", "battery storage soc discharge"),
    (r"شحن|سيار|شواحن", "ev charging shift"),
    (r"ذرو|الحمل الاقصى|اقصى حمل", "peak demand"),
    (r"استجاب\w* (ال)?طلب", "demand response"),
    (r"شذوذ|شاذ|غير طبيعي|انحراف", "anomaly deviation investigate"),
    (r"توام|رقمي|محاكا", "digital twin simulation simulate"),
    (r"تحقق|التحقق", "verification verify"),
    (r"اعاد\w* (ال)?تخطيط|خطه بديل", "replanning replan alternative"),
    (r"موافق|اعتماد|رفض", "approval approve reject human operator"),
    (r"وكيل|الايجنت|ايجنت", "agent agentic workflow"),
    (r"سير العمل|مراحل|خطوات", "workflow steps"),
    (r"كفاء", "efficiency"),
    (r"استهلاك|مستهلك", "consumption energy"),
    (r"طاق|كهرباء", "energy electricity"),
    (r"تنبؤ|توقع", "forecast prediction model"),
    (r"مبنى|مباني", "building buildings campus"),
    (r"اشغال|حضور", "occupancy"),
    (r"شبك", "grid import limit"),
    (r"توصي|اجراء", "recommendation action optimizer"),
    (r"محسن|تحسين|افضل", "optimizer score constraint"),
    (r"خط (ال)?اساس", "baseline"),
    (r"دوام|ساعات العمل", "working hours schedule"),
    (r"قرار", "decision"),
    (r"سياس", "policy"),
]


# Colloquial / alternative Arabic words mapped to the wording of the Arabic documents.
ARABIC_SYNONYMS = [
    (r"فرق", "مقابل"), (r"بيشتغل|يشتغل|بتشتغل|تشتغل", "يعمل"), (r"بيختار|بختار", "يختار"),
    (r"صرف|بيصرف|يصرف", "استهلاك"), (r"ليش|ليه", "لماذا سبب"),
    (r"الشمسيه|شمسي|الواح", "الطاقه الشمسيه الكهروضوئيه"), (r"مكيف|تكييف", "التكييف"), (r"السيارات|سيارات|شحن", "شحن السيارات الكهربائيه"),
    (r"الذروه|ذروه", "ذروه الطلب"), (r"وكيل|الايجنت", "الوكيل"),
]


def expand_arabic(question: str) -> str:
    t = _ar_norm(question)
    extra = [terms for pattern, terms in ARABIC_SYNONYMS if re.search(pattern, t)]
    return f"{question} {' '.join(extra)}" if extra else question


def expand_query(question: str) -> str:
    if not re.search(r"[\u0600-\u06FF]", question or ""):
        return question
    t = data_qa.normalize(question) if data_qa else question
    extra = [terms for pattern, terms in ARABIC_TERMS if re.search(pattern, t)]
    return f"{question} {' '.join(extra)}"


def _split_sentences(text: str) -> List[str]:
    """Split prose into sentences; each list item counts as its own sentence."""
    sentences: List[str] = []
    prose: List[str] = []
    bullet: List[str] = []

    def flush():
        if bullet:
            item = " ".join(bullet).strip()
            if item and item[-1] not in ".!?:":
                item += "."
            sentences.append(item)
            bullet.clear()
        if prose:
            joined = re.sub(r"\s+", " ", " ".join(prose)).strip()
            sentences.extend(re.split(r"(?<=[.!?؟])\s+(?=[A-Z0-9\u0600-\u06FF])", joined))
            prose.clear()

    for line in text.splitlines():
        item = re.match(r"^\s*(?:[-*]|\d+\.)\s+(.*)$", line)
        if item:
            flush()
            bullet.append(item.group(1).strip())
        elif not line.strip():
            flush()
        elif bullet and line[:1].isspace():
            bullet.append(line.strip())   # wrapped continuation of a list item
        else:
            if bullet:
                flush()
            prose.append(line)
    flush()
    return [s.strip() for s in sentences if len(s.strip()) > 20]


# =========================================================
# DATA STRUCTURES
# =========================================================


@dataclass
class Chunk:
    chunk_id: int
    document: str          # file name
    title: str             # document H1
    section: str           # nearest heading
    text: str
    tokens: List[str] = field(default_factory=list)

    def source_dict(self, score: float, rank: int) -> Dict[str, Any]:
        excerpt = re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", self.text, flags=re.MULTILINE)
        excerpt = re.sub(r"\s+", " ", excerpt).strip()
        if len(excerpt) > 280:
            excerpt = excerpt[:277].rsplit(" ", 1)[0] + "…"
        return {
            "ref": rank,
            "document": self.document,
            "title": self.title,
            "section": self.section,
            "score": round(score, 3),
            "excerpt": excerpt,
        }


# =========================================================
# DOCUMENT LOADING / CHUNKING
# =========================================================


def _chunk_markdown(path: Path, start_id: int) -> List[Chunk]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()

    title = path.stem.replace("_", " ").title()
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    sections: List[tuple[str, List[str]]] = []
    current_heading = title
    buffer: List[str] = []

    for line in lines:
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            if any(b.strip() for b in buffer):
                sections.append((current_heading, buffer))
            current_heading = heading.group(2).strip()
            buffer = []
        else:
            buffer.append(line)
    if any(b.strip() for b in buffer):
        sections.append((current_heading, buffer))

    chunks: List[Chunk] = []
    next_id = start_id
    for heading, body_lines in sections:
        body = "\n".join(body_lines).strip()
        # Split very long sections on paragraph boundaries.
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        piece = ""
        for para in paragraphs:
            if piece and len(piece) + len(para) > MAX_CHUNK_CHARS:
                chunks.append(Chunk(next_id, path.name, title, heading, piece))
                next_id += 1
                piece = ""
            piece = f"{piece}\n\n{para}" if piece else para
        if piece:
            chunks.append(Chunk(next_id, path.name, title, heading, piece))
            next_id += 1

    for chunk in chunks:
        # Headings carry strong topical signal, so they are indexed twice.
        chunk.tokens = tokenize(f"{chunk.title} {chunk.section} {chunk.section} {chunk.text}")
    return chunks


# =========================================================
# BM25 INDEX
# =========================================================


class BM25Index:
    def __init__(self, chunks: List[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self.doc_freqs = [Counter(c.tokens) for c in chunks]
        self.doc_lens = [len(c.tokens) for c in chunks]
        self.avg_len = (sum(self.doc_lens) / len(self.doc_lens)) if chunks else 0.0
        df: Counter = Counter()
        for freqs in self.doc_freqs:
            df.update(freqs.keys())
        n = len(chunks)
        self.idf = {
            term: math.log(1 + (n - count + 0.5) / (count + 0.5))
            for term, count in df.items()
        }

    def search(self, query: str, top_k: int = TOP_K) -> List[tuple[Chunk, float]]:
        q_terms = tokenize(query)
        if not q_terms or not self.chunks:
            return []
        scores = []
        for idx, freqs in enumerate(self.doc_freqs):
            score = 0.0
            length_norm = 1 - self.b + self.b * (self.doc_lens[idx] / (self.avg_len or 1))
            for term in set(q_terms):
                tf = freqs.get(term, 0)
                if not tf:
                    continue
                score += self.idf.get(term, 0.0) * (tf * (self.k1 + 1)) / (tf + self.k1 * length_norm)
            if score > 0:
                scores.append((self.chunks[idx], score))
        scores.sort(key=lambda item: item[1], reverse=True)
        return scores[:top_k]


# =========================================================
# LLM PROVIDERS (optional)
# =========================================================


SYSTEM_PROMPT = (
    "You are the knowledge assistant of a Smart Energy AI operations center. "
    "You receive up to two kinds of context. PROJECT DATA [D] holds figures "
    "computed directly from the project's database: treat them as facts, quote the "
    "numbers, units, dates and times exactly as given, and cite them as [D]. "
    "KNOWLEDGE-BASE EXCERPTS [1], [2]... explain how the system works; cite them "
    "inline. Answer ONLY from this context. Never invent, estimate or recompute "
    "readings, savings or events that are not in the context. If the context does "
    "not contain the answer, say so plainly. If a LIVE OPERATIONAL DATA block is "
    "provided, say clearly which statements come from it. Reply in the same "
    "language as the question (Arabic questions get Arabic answers, keeping "
    "numbers, units and building codes in Latin characters). Write for a reader "
    "who is not an energy expert: lead with the direct answer in one clear "
    "sentence, then explain what it means in everyday words (for example, when "
    "the peak happened and why that is normal or unusual). Use short paragraphs "
    "separated by a blank line, friendly dates (Tuesday 5 July 2016) and clock "
    "times (3 pm), and round figures sensibly (10,117 kWh rather than 10,117.0). "
    "Avoid jargon; if you must use a technical term, explain it in a few words. "
    "No headings, no tables, no bullet lists, under 220 words."
)


def _resolve_provider() -> str:
    configured = os.getenv("RAG_LLM_PROVIDER", "auto").strip().lower()
    if configured in {"none", "off", "disabled", "extractive"}:
        return "none"
    if configured == "groq":
        return "groq" if os.getenv("GROQ_API_KEY") else "none"
    if configured == "anthropic":
        return "anthropic" if os.getenv("ANTHROPIC_API_KEY") else "none"
    if configured == "openai":
        return "openai" if os.getenv("OPENAI_API_KEY") else "none"
    # auto
    if os.getenv("GROQ_API_KEY"):
        return "groq"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "none"


def _model_for(provider: str) -> Optional[str]:
    if provider == "none":
        return None
    return os.getenv("RAG_LLM_MODEL") or DEFAULT_MODELS.get(provider, "llama-3.3-70b-versatile")


def _openai_style_body(model: str, user_prompt: str) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "model": model,
        # Reasoning models (gpt-oss) spend part of this budget thinking; 600 was
        # sometimes used up before any answer text was produced.
        "max_tokens": 1500,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }
    if "gpt-oss" in (model or ""):
        body["reasoning_effort"] = "low"
    return body


def _clean_llm_text(text: str) -> str:
    """Drop any leaked <think> block and markdown emphasis the UI shows literally."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    return text.strip()


def _call_llm(provider: str, model: str, user_prompt: str) -> str:
    import requests  # already in requirements.txt; imported lazily

    if provider == "groq":
        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=_openai_style_body(model, user_prompt),
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return _clean_llm_text(resp.json()["choices"][0]["message"].get("content") or "")

    if provider == "anthropic":
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 900,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_prompt}],
            },
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        blocks = resp.json().get("content", [])
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()

    if provider == "openai":
        base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        resp = requests.post(
            f"{base}/chat/completions",
            headers={
                "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                "Content-Type": "application/json",
            },
            json=_openai_style_body(model, user_prompt),
            timeout=LLM_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return _clean_llm_text(resp.json()["choices"][0]["message"].get("content") or "")

    raise ValueError(f"Unknown LLM provider: {provider}")


# =========================================================
# RAG SERVICE
# =========================================================


def _clean_sentence(sentence: str) -> str:
    """Strip markdown the reader should not see (list dashes, emphasis, backticks)."""
    s = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", sentence)
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
    s = s.replace("`", "")
    return s.strip()


class RAGService:
    def __init__(self, knowledge_dir: Path = KNOWLEDGE_DIR, knowledge_dir_ar: Path = KNOWLEDGE_DIR_AR):
        self.knowledge_dir = Path(knowledge_dir)
        self.knowledge_dir_ar = Path(knowledge_dir_ar)
        self._lock = threading.Lock()
        self._index: Optional[BM25Index] = None
        self._index_ar: Optional[BM25Index] = None
        self._documents: List[str] = []
        self._documents_ar: List[str] = []
        self._load_error: Optional[str] = None

    # ------------------------------------------------------
    # Index management
    # ------------------------------------------------------

    def load(self) -> None:
        with self._lock:
            try:
                if not self.knowledge_dir.exists():
                    raise FileNotFoundError(f"Knowledge folder not found: {self.knowledge_dir}")
                chunks: List[Chunk] = []
                documents: List[str] = []
                for path in sorted(self.knowledge_dir.rglob("*")):
                    if (
                        path.is_file()
                        and path.suffix.lower() in SUPPORTED_SUFFIXES
                        and path.name.lower() not in EXCLUDED_FILES
                    ):
                        chunks.extend(_chunk_markdown(path, start_id=len(chunks)))
                        documents.append(path.name)
                if not chunks:
                    raise ValueError("Knowledge folder contains no indexable documents")
                self._index = BM25Index(chunks)
                self._documents = documents
                self._load_error = None
                # Arabic documents are optional: without them Arabic questions
                # still reach the English index through expand_query().
                self._index_ar, self._documents_ar = None, []
                if self.knowledge_dir_ar.exists():
                    ar_chunks: List[Chunk] = []
                    for path in sorted(self.knowledge_dir_ar.rglob("*")):
                        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES \
                                and path.name.lower() not in EXCLUDED_FILES:
                            ar_chunks.extend(_chunk_markdown(path, start_id=len(ar_chunks)))
                            self._documents_ar.append(path.name)
                    if ar_chunks:
                        self._index_ar = BM25Index(ar_chunks)
            except Exception as exc:  # noqa: BLE001 - reported, never raised
                self._index = None
                self._documents = []
                self._load_error = str(exc)

    def _ensure_loaded(self) -> None:
        if self._index is None and self._load_error is None:
            self.load()

    def status(self) -> Dict[str, Any]:
        self._ensure_loaded()
        provider = _resolve_provider()
        data_status: Dict[str, Any]
        if data_qa is None:
            data_status = {"available": False, "error": DATA_QA_IMPORT_ERROR}
        else:
            try:
                data_status = data_qa.status()
            except Exception as exc:  # noqa: BLE001
                data_status = {"available": False, "error": str(exc)}
        return {
            "available": self._index is not None,
            "documents": list(self._documents),
            "documents_ar": list(self._documents_ar),
            "chunks": len(self._index.chunks) if self._index else 0,
            "generation": "llm" if provider != "none" else "extractive",
            "provider": provider,
            "model": _model_for(provider),
            "error": self._load_error,
            "project_data": data_status,
        }

    # ------------------------------------------------------
    # Query
    # ------------------------------------------------------

    def query(
        self,
        question: str,
        live_context: Optional[Dict[str, Any]] = None,
        top_k: int = TOP_K,
    ) -> Dict[str, Any]:
        """
        Answer a question from the project data and the knowledge base.

        Questions about readings ("energy on 2016-07-01", "which day had the
        highest load") are answered from the dataset by data_qa; the figures are
        computed in Python, never by the language model. Questions about how the
        system works are answered from the documents. A question can use both.

        Returns:
            {
              "answer": str,
              "sources": [ {ref, document, title, section, score, excerpt}, ... ],
              "mode": "llm" | "data" | "extractive" | "no_match",
              "provider": str, "model": str | None,
              "data": {intent, answer, facts} | None,
              "live_context": dict | None,   # echoed back, never mixed in
              "notice": str | None
            }
        Raises ValueError for an empty question; any other failure is
        returned as a structured result by the caller (app.py).
        """
        question = (question or "").strip()
        if not question:
            raise ValueError("Question must not be empty.")
        if len(question) > 1000:
            raise ValueError("Question is too long (max 1000 characters).")

        self._ensure_loaded()
        arabic = bool(re.search(r"[\u0600-\u06FF]", question))

        # 1. Project data -------------------------------------------------
        data = None
        if data_qa is not None:
            try:
                data = data_qa.answer(question)
            except Exception:  # noqa: BLE001 - data layer must never break the page
                data = None

        # 2. Documents ----------------------------------------------------
        if self._index is None and data is None:
            raise RuntimeError(f"Knowledge base unavailable: {self._load_error}")
        hits: List[tuple[Chunk, float]] = []
        if self._index is not None:
            if arabic and self._index_ar is not None:
                hits = [(c, sc) for c, sc in self._index_ar.search(expand_arabic(question), top_k) if sc >= MIN_SCORE]
            if not hits:
                hits = [(c, sc) for c, sc in self._index.search(expand_query(question), top_k) if sc >= MIN_SCORE]
        if data is not None:
            # The data answers the question; keep only documents that clearly add context.
            hits = [(c, sc) for c, sc in hits if sc >= DATA_DOC_MIN_SCORE][:DATA_DOC_MAX]

        provider = _resolve_provider()
        model = _model_for(provider)
        data_block = None
        if data is not None:
            data_block = {"intent": data["intent"], "answer": data["answer"], "facts": data["facts"], "headline": data.get("headline", ""),
                          "plan": data.get("plan")}

        if not hits and data is None:
            return {
                "answer": (
                    "لا يوجد في قاعدة المعرفة أو بيانات المشروع ما يجيب على هذا السؤال. "
                    "جرّب السؤال عن استهلاك الطاقة في تاريخ معيّن، أو التكييف، أو الطاقة الشمسية، "
                    "أو البطاريات، أو شحن السيارات، أو الأحداث، أو كيف يتخذ الوكيل قراراته."
                    if arabic else
                    "Neither the knowledge base nor the project data covers this question. "
                    "Try asking about consumption on a specific date (e.g. 2016-07-01), a "
                    "building, HVAC, solar, batteries, EV charging, events, demand response "
                    "or how the agent makes decisions."
                ),
                "sources": [],
                "mode": "no_match",
                "provider": provider,
                "model": model,
                "data": None,
                "live_context": live_context,
                "notice": None,
            }

        sources: List[Dict[str, Any]] = []
        if data is not None and data.get("source"):
            sources.append(dict(data["source"]))
        sources.extend(chunk.source_dict(score, rank) for rank, (chunk, score) in enumerate(hits, start=1))
        notice = None

        if provider != "none":
            try:
                answer = _call_llm(provider, model, self._build_prompt(question, hits, live_context, data))
                if answer:
                    return {
                        "answer": answer,
                        "sources": sources,
                        "mode": "llm",
                        "provider": provider,
                        "model": model,
                        "data": data_block,
                        "live_context": live_context,
                        "notice": None,
                    }
                notice = "The language model returned an empty answer; showing the computed result instead."
            except Exception as exc:  # noqa: BLE001
                notice = (
                    "The language model could not be reached "
                    f"({type(exc).__name__}); showing the computed result instead."
                )

        if data is not None:
            return {
                "answer": data["answer"],
                "sources": sources,
                "mode": "data",
                "provider": "none" if notice is None else provider,
                "model": None,
                "data": data_block,
                "live_context": live_context,
                "notice": notice,
            }

        return {
            "answer": self._extractive_answer(expand_query(question), hits),
            "sources": sources,
            "mode": "extractive",
            "provider": "none" if notice is None else provider,
            "model": None,
            "data": None,
            "live_context": live_context,
            "notice": notice,
        }

    # ------------------------------------------------------
    # Helpers
    # ------------------------------------------------------

    @staticmethod
    def _build_prompt(
        question: str,
        hits: List[tuple[Chunk, float]],
        live_context: Optional[Dict[str, Any]],
        data: Optional[Dict[str, Any]] = None,
    ) -> str:
        parts = []
        if data is not None:
            parts.append("PROJECT DATA [D] (computed from the project database; exact figures):")
            if data.get("headline"):
                parts.append("Exact result: " + data["headline"])
            parts.append("Plain-language draft (rounded for readers; you may reuse its wording): "
                         + data["answer"].replace("**", ""))
            parts.append("\n".join(f"- {f.strip().lstrip('• ')}" for f in data["facts"]))
        if hits:
            parts.append("KNOWLEDGE-BASE EXCERPTS:")
            for rank, (chunk, _score) in enumerate(hits, start=1):
                parts.append(f"[{rank}] {chunk.title} / {chunk.section}\n{chunk.text}")
        if live_context:
            parts.append("LIVE OPERATIONAL DATA (from the agent, not from the knowledge base):")
            for key, value in live_context.items():
                parts.append(f"- {key}: {value}")
        parts.append(f"QUESTION: {question}")
        return "\n\n".join(parts)

    @staticmethod
    def _extractive_answer(question: str, hits: List[tuple[Chunk, float]]) -> str:
        """Pick the sentences that best overlap the question, keep citation refs."""
        q_terms = set(tokenize(question))
        top_score = hits[0][1] or 1.0
        scored = []
        for rank, (chunk, chunk_score) in enumerate(hits, start=1):
            text = chunk.text
            relevance = chunk_score / top_score  # 1.0 for the best section
            for position, sentence in enumerate(_split_sentences(text)):
                overlap = len(q_terms & set(tokenize(sentence)))
                # Best sections dominate; within them, favour term overlap and
                # earlier sentences (topic sentences come first).
                weight = relevance * 2.0 + overlap * 0.5 - position * 0.08
                if overlap or rank == 1:
                    scored.append((weight, rank, position, sentence))
        if not scored:
            chunk = hits[0][0]
            return f"{_split_sentences(chunk.text)[0] if _split_sentences(chunk.text) else chunk.text} [1]"

        best = sorted(scored, key=lambda s: s[0], reverse=True)[:5]
        best.sort(key=lambda s: (s[1], s[2]))  # restore reading order
        # One short paragraph per source, cited once at its end, reads far more
        # naturally than a citation after every sentence.
        paragraphs: List[str] = []
        current_rank, current = None, []
        for _score, rank, _pos, sentence in best:
            if rank != current_rank and current:
                paragraphs.append(" ".join(current) + f" [{current_rank}]")
                current = []
            current_rank = rank
            current.append(_clean_sentence(sentence))
        if current:
            paragraphs.append(" ".join(current) + f" [{current_rank}]")
        return "\n".join(paragraphs)


# Module-level singleton used by app.py
rag_service = RAGService()


if __name__ == "__main__":
    import json
    import sys

    q = " ".join(sys.argv[1:]) or "Why can reducing HVAC load reduce building energy consumption?"
    print(json.dumps(rag_service.status(), indent=2))
    print(json.dumps(rag_service.query(q), indent=2, ensure_ascii=False))
