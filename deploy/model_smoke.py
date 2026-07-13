from __future__ import annotations

import asyncio

from backend.app.config import get_settings
from backend.app.services.analyzer import SentimentEngine


async def main() -> None:
    engine = SentimentEngine(get_settings())
    predictions = await engine.predict(["这个游戏太棒了", "性能很差而且经常掉帧"])
    print(predictions)
    if [label for label, _score in predictions] != ["positive", "negative"]:
        raise SystemExit("Unexpected sentiment labels")
    if engine.warning:
        raise SystemExit(engine.warning)


if __name__ == "__main__":
    asyncio.run(main())
