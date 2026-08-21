# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
STORE_SAVE_RAW = False
TOP_N = 20
HYBRID_RETRIEVAL_ENABLED = True

RERANK_ENABLED = True
RERANK_TOP_N = 5

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
