import os

# ── LLM ─────────────────────────────────────────────────────────────
LLM_CONFIG = {
    "base_url": os.getenv("OPENAI_BASE_URL") or os.getenv("LLM_BASE_URL", "http://172.17.5.206:8002/v1"),
    "model": os.getenv("MODEL_NAME") or os.getenv("LLM_MODEL", "minimax-m2.5-nvfp4"),
    "api_key": os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY", "dummy"),
    "temperature": float(os.getenv("LLM_TEMPERATURE", "0")),
    # Reasoning models (minimax, qwq, deepseek-r1) output long chain-of-thought before responding.
    # 300s covers even complex BSP queries; increase LLM_TIMEOUT env var if still hitting timeouts.
    "timeout": int(os.getenv("LLM_TIMEOUT", "300")),
}

# Qdrant persistent storage path
QDRANT_PATH = os.getenv("QDRANT_PATH") or str(
    os.path.join(os.path.dirname(__file__), "_qdrant_data")
)

# Show retrieval debug info
DEBUG_RETRIEVAL = os.getenv("DEBUG_RETRIEVAL", "1") == "1"

# Max chunks returned after reranking
RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "5"))

# CRAG: reranker score threshold to consider retrieval "good enough"
CRAG_SCORE_THRESHOLD = float(os.getenv("CRAG_SCORE_THRESHOLD", "0.4"))

# Max CRAG rewrite retries before emitting a Knowledge Gap Report
CRAG_MAX_RETRIES = int(os.getenv("CRAG_MAX_RETRIES", "2"))

# Neo4j entry-node list fed to Block A LLM Planner as a constraint
NEO4J_ENTRY_NODES: list[str] = [
    "camera", "CSI driver",
    "USB", "USB hub",
    "power", "power subsystem", "regulator",
    "I2C bus", "SPI bus", "UART",
    "display", "HDMI", "MIPI DSI",
    "audio", "codec",
    "storage", "eMMC", "SD card",
    "ethernet", "WiFi", "Bluetooth",
    "GPIO", "pinctrl",
    "device tree", "bootloader",
    "kernel", "PCIe",
]
