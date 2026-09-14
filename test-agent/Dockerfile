FROM python:3.12-slim

WORKDIR /opt/aitp-coverage-agent
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agent.py .
COPY examples /opt/sample

ENV COVERAGE_AGENT_CONFIG=/opt/sample/agent.json
EXPOSE 8765 8202
CMD ["uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8765"]
