import urllib.request
import json
import time

def main():
    payload = json.dumps({
        "model": "llama3.2:1b",
        "prompt": "Say hello in one word.",
        "stream": True,
    }).encode("utf-8")

    samples = []
    print("Collecting 5 real Ollama (llama3.2:1b) samples on localhost:11434...")
    for i in range(5):
        t0 = time.perf_counter()
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        ttft = None
        chunks = 0
        with urllib.request.urlopen(req, timeout=10) as r:
            for line in r:
                if line.strip():
                    chunks += 1
                    if ttft is None:
                        ttft = time.perf_counter() - t0
        total = time.perf_counter() - t0
        samples.append({"sample": i+1, "ttft_ms": round(ttft*1000, 2), "total_ms": round(total*1000, 2), "chunks": chunks})
        print(f"Sample {i+1}: TTFT={ttft*1000:.1f}ms, Total={total*1000:.1f}ms, Chunks={chunks}")

    avg_ttft = sum(s["ttft_ms"] for s in samples) / len(samples)
    avg_total = sum(s["total_ms"] for s in samples) / len(samples)
    print(f"Average TTFT: {avg_ttft:.1f}ms | Average Total: {avg_total:.1f}ms")

if __name__ == "__main__":
    main()
