# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
VECTOR_SEARCH_TOP_K = 30
BM25_SEARCH_TOP_K = 30
RRF_TOP_K = 30
RERANKER_TOP_K = 10

# Final score blending after reranking: Final_Score = RERANKER_SCORE_WEIGHT * ScoreReranker + BM25_SCORE_WEIGHT * ScoreBM25
RERANKER_SCORE_WEIGHT = 0.7
BM25_SCORE_WEIGHT = 0.3

# ---------------------------------------------------------------------------
# DEBUG
# ---------------------------------------------------------------------------
DEBUG_ROUTER = False
DEBUG_EXTRACTOR = False
DEBUG_STORE = False
DEBUG_RETRIEVER = False
DEBUG_ANSWER = False

# ---------------------------------------------------------------------------
# LLM clients
# ---------------------------------------------------------------------------

from app.core.llm import LLMInference
from app.core.reranker import RerankingInference
from app.core.router import RouterInference

chat_llm = LLMInference(temperature=0.1)
router_llm = RouterInference(temperature=0.0) # Fast model
reranker = RerankingInference(top_n=RERANKER_TOP_K)
