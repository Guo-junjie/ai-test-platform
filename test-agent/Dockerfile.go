FROM golang:1.24-alpine

RUN apk add --no-cache python3 py3-pip && python3 -m venv /opt/agent-venv
COPY requirements.txt /opt/agent/requirements.txt
RUN /opt/agent-venv/bin/pip install --no-cache-dir -r /opt/agent/requirements.txt
COPY agent.py /opt/agent/agent.py
COPY examples/go /opt/sample-go/src
COPY examples/go-agent.json /opt/sample-go/agent.json
WORKDIR /opt/sample-go/src
RUN go build -cover -o /opt/sample-go/server .
ENV PATH="/opt/agent-venv/bin:${PATH}"
WORKDIR /opt/agent
CMD ["uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8765"]
