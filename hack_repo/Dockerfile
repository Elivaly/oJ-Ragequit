FROM python:3.11-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HOME=/tmp/hf \
    TIKTOKEN_CACHE_DIR=/app/.tiktoken \
    HOME=/tmp

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir uv \
 && uv pip install --system --no-cache -r requirements.txt \
 && python -c "import tiktoken; tiktoken.get_encoding('cl100k_base'); tiktoken.get_encoding('o200k_base')"

COPY harness/ /app/harness/
COPY run_agent.py /app/run_agent.py
COPY models/ /app/models/

RUN cd /tmp && python -c "from openjiuwen.core.foundation.llm import Model; print('openjiuwen OK')"

ENTRYPOINT ["python", "/app/run_agent.py"]