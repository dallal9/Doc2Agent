"""Example: Call the LLM service."""

import httpx

LLM_URL = "http://localhost:8001"


def main():
    prompt = "Explain in 3 bullet points what RAG is."

    print(f"Prompt: {prompt}\n")
    resp = httpx.post(f"{LLM_URL}/generate", json={"prompt": prompt}, timeout=60)
    resp.raise_for_status()

    data = resp.json()
    print(f"Response:\n{data['text']}")
    print(f"\n[tokens={data['tokens']}, time={data['time_s']:.2f}s]")


if __name__ == "__main__":
    main()
