# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
STORE_SAVE_RAW = False
TOP_N = 100
RERANK_TOP_N = 20
RERANK_ENABLED = True

# ---------------------------------------------------------------------------
# DEBUG
# ---------------------------------------------------------------------------
DEBUG_ROUTER = False
DEBUG_EXTRACTOR = False
DEBUG_STORE = False
DEBUG_RETRIEVER = True
DEBUG_ANSWER = False

# ---------------------------------------------------------------------------
# LLM clients
# ---------------------------------------------------------------------------

from app.core.llm import LLMInference
from app.core.reranker import RerankingInference
from app.core.router import RouterInference

chat_llm = LLMInference(temperature=0.1)
router_llm = RouterInference(temperature=0.0) # Fast model
reranker = RerankingInference(top_n=RERANK_TOP_N)
