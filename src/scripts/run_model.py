import logging
import os
import time
from dotenv import load_dotenv
import ollama

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

load_dotenv()


def main() -> None:
    model = os.environ.get("MODEL_NAME", "gemma2:2b")
    temperature = float(os.environ.get("TEMPERATURE", "0.2"))

    prompt = (
        "You are a helpful assistant.\n"
        "Explain in 5 bullet points what RAG is and when to use it."
    )

    logger.info("llm.generate.start model=%s temperature=%s", model, temperature)
    t0 = time.time()

    response = ollama.generate(
        model=model,
        prompt=prompt,
        options={"temperature": temperature},
    )

    dt = time.time() - t0
    text = response["response"]
    eval_count = response.get("eval_count", 0)
    tps = eval_count / dt if dt > 0 else 0

    logger.info("llm.generate.output")
    logger.info(text.strip())
    logger.info(
        "llm.generate.done output_tokens=%d wall_time_s=%.2f approx_tps=%.2f",
        eval_count,
        dt,
        tps,
    )


if __name__ == "__main__":
    main()
