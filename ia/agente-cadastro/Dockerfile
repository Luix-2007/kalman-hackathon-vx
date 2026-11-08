# Imagem ARM64 com uv pré-instalado (mesma base recomendada pelo Strands docs).
# O AgentCore Runtime usa microVMs linux/arm64.
FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Instala dependências antes de copiar o código (melhor uso do cache de camadas).
COPY src/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código do agente.
COPY src/agent.py agent.py

# O BedrockAgentCoreApp escuta na porta 8080 por padrão.
EXPOSE 8080

# Inicia o servidor ASGI. O objeto `app` é o BedrockAgentCoreApp definido em agent.py.
CMD ["uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8080"]
