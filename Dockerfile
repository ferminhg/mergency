FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml ./
RUN uv sync --no-install-project

COPY src ./src
COPY tests ./tests
COPY scripts ./scripts

RUN uv sync

ENV PATH="/app/.venv/bin:$PATH"

CMD ["uvicorn", "mergency.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
