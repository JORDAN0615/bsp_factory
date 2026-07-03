from rag_integration import query_rag

queries = [
    "Jetson Thor CAN bus SPI frequency 設定錯誤",
    "pinmux I2C conflict causing boot failure",
]

for q in queries:
    print("\n" + "=" * 60)
    print(f"QUERY: {q}")
    print("=" * 60)
    result = query_rag(q)
    print("source:", result["source"])
    print("score:", result["crag_score"])
    print("citations:", result["citations"][:3])
    print("--- answer ---")
    print(result["answer"])
