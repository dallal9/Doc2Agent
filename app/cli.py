"""Terminal-based chat CLI."""

import asyncio

from src.chat import ChatAssistant
from src.logging import setup_logging

logger = setup_logging("cli")


def print_help():
    lines = [
        "Commands:",
        "  /load <path>   Load a PDF file",
        "  /text          Enter text directly (end with empty line)",
        "  /reset         Clear chat history",
        "  /info          Show current state",
        "  /help          Show this help",
        "  /quit          Exit",
        "",
        "Just type normally to chat.",
    ]
    for line in lines:
        logger.info(line)


async def run_cli():
    logger.info("MyAgent Chat (CLI)")
    logger.info("Type /help for commands. Type normally to chat.")

    assistant = ChatAssistant()

    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue

        if user_input.startswith("/"):
            parts = user_input.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd == "/quit":
                break
            elif cmd == "/help":
                print_help()
            elif cmd == "/load":
                if not arg:
                    logger.warning("Usage: /load <path>")
                else:
                    logger.info(assistant.load_pdf(arg))
            elif cmd == "/text":
                logger.info("Enter text (empty line to finish):")
                lines = []
                while True:
                    line = input()
                    if not line:
                        break
                    lines.append(line)
                logger.info(assistant.set_text("\n".join(lines)))
            elif cmd == "/reset":
                logger.info(assistant.reset_chat())
            elif cmd == "/info":
                logger.info("\n%s", assistant.show_info())
            else:
                logger.warning("Unknown command: %s. Type /help", cmd)
        else:
            logger.info("assistant> %s", await assistant.chat(user_input))

    logger.info("Goodbye!")


def main():
    asyncio.run(run_cli())


if __name__ == "__main__":
    main()
