import os
import re
import uuid
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_experimental.agents.agent_toolkits import create_pandas_dataframe_agent

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
load_dotenv()

# Google AI Studio API key
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

CHARTS_DIR = Path("charts")
CHARTS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# In-memory response cache with fuzzy matching
# ---------------------------------------------------------------------------
from difflib import SequenceMatcher

# Common filler / stop words + domain words that don't change the meaning
_STOP_WORDS = {
    "a", "an", "the", "of", "in", "on", "for", "to", "is", "was", "were",
    "are", "it", "its", "this", "that", "and", "or", "but", "with", "from",
    "by", "at", "do", "does", "did", "can", "could", "will", "would",
    "should", "shall", "may", "might", "please", "me", "my", "i",
    # Domain‑specific words – these appear in many Titanic questions
    "titanic", "dataset", "data", "passengers", "ship",
}

SIMILARITY_THRESHOLD = 0.85  # 85 % match → cache hit

_cache: list[tuple[str, dict]] = []  # [(normalized_question, response_dict), ...]


def _normalize(question: str) -> str:
    """Lowercase, strip punctuation & stop words to get the semantic core."""
    text = re.sub(r"[^\w\s]", "", question.lower())         # drop punctuation
    words = [w for w in text.split() if w not in _STOP_WORDS]
    return " ".join(words)


def _find_cached(question: str) -> dict | None:
    """Return a cached response if a similar question was already answered."""
    norm = _normalize(question)
    for cached_q, cached_resp in _cache:
        ratio = SequenceMatcher(None, norm, cached_q).ratio()
        if ratio >= SIMILARITY_THRESHOLD:
            return cached_resp
    return None


def _store_cache(question: str, response: dict) -> None:
    _cache.append((_normalize(question), response))

DATA_PATH = Path("data/Titanic-Dataset.csv")

# ---------------------------------------------------------------------------
# Load & light‑clean the dataset once at startup
# ---------------------------------------------------------------------------
df = pd.read_csv(DATA_PATH)
df.columns = df.columns.str.strip()

DATASET_DESCRIPTION = (
    "The dataframe `df` contains Titanic passenger data with columns:\n"
    + ", ".join(df.columns.tolist())
    + "\n\nKey columns: Survived (0/1), Pclass (1‑3), Sex, Age, Fare, Embarked (C/Q/S)."
)

# ---------------------------------------------------------------------------
# LangChain agent
# ---------------------------------------------------------------------------
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=GOOGLE_API_KEY,
    temperature=0,
    max_output_tokens=2048,
)

SYSTEM_PREFIX = f"""You are a data‑analysis assistant for the Titanic dataset.

{DATASET_DESCRIPTION}

RULES
1. Answer questions accurately using pandas operations on `df`.
2. When the user asks for a chart / plot / visualization, use matplotlib to
   create it. ALWAYS save the figure with:
       plt.savefig(r"{CHARTS_DIR.resolve()}/{{{{unique_name}}}}.png", bbox_inches="tight", dpi=120)
       plt.close()
   Then include the **exact filename** in your final answer inside double
   square brackets like this: [[unique_name.png]]
3. Keep text answers concise but informative.
4. If a question is ambiguous, make a reasonable assumption and state it.
5. For percentage calculations round to 2 decimal places.
6. If the question is NOT related to the Titanic dataset or data analysis,
   politely decline and say: "I'm specifically designed to help with the
   Titanic dataset. Please ask me something about Titanic passengers,
   their survival, demographics, or related statistics."
   Do NOT attempt to run any code for irrelevant questions.
"""

agent = create_pandas_dataframe_agent(
    llm,
    df,
    verbose=True,
    prefix=SYSTEM_PREFIX,
    allow_dangerous_code=True,
    handle_parsing_errors=True,
)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Titanic Chat Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    question: str


class ChatResponse(BaseModel):
    answer: str
    chart: str | None = None   # filename of generated chart, if any
    cached: bool = False       # whether the response came from cache


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Run the LangChain agent and return an answer + optional chart path."""

    # ---- Cache lookup (fuzzy) ----
    hit = _find_cached(req.question)
    if hit:
        return ChatResponse(answer=hit["answer"], chart=hit["chart"], cached=True)

    # ---- Run the agent ----
    result = agent.invoke({"input": req.question})
    answer: str = result.get("output", "")

    # Detect chart filename embedded in the answer  [[filename.png]]
    chart_match = re.search(r"\[\[(.+?\.png)\]\]", answer)
    chart_filename = None
    if chart_match:
        chart_filename = chart_match.group(1)
        # Strip the [[...]] marker from the text answer
        answer = answer.replace(chart_match.group(0), "").strip()

    # Fallback: check if any new chart was just created in the charts dir
    if chart_filename is None:
        pngs = sorted(CHARTS_DIR.glob("*.png"), key=os.path.getmtime, reverse=True)
        if pngs:
            latest = pngs[0]
            import time
            if time.time() - latest.stat().st_mtime < 10:
                chart_filename = latest.name

    # ---- Store in cache ----
    _store_cache(req.question, {"answer": answer, "chart": chart_filename})

    return ChatResponse(answer=answer, chart=chart_filename, cached=False)


@app.get("/charts/{filename}")
async def get_chart(filename: str):
    """Serve a generated chart image."""
    path = CHARTS_DIR / filename
    if not path.exists():
        return {"error": "Chart not found"}
    return FileResponse(path, media_type="image/png")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
