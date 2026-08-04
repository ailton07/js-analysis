# Stage 1: build Go tools
FROM golang:1.26-alpine AS go-builder

RUN apk add --no-cache git ca-certificates gcc musl-dev curl

ENV CGO_ENABLED=0

RUN go install github.com/projectdiscovery/katana/cmd/katana@latest
RUN go install github.com/projectdiscovery/notify/cmd/notify@latest
RUN go install github.com/zricethezav/gitleaks/v8@latest

# Subdomain enumeration (passive-only — see subenum-config.yaml)
RUN go install github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest
RUN go install github.com/projectdiscovery/dnsx/cmd/dnsx@latest
RUN go install github.com/projectdiscovery/tlsx/cmd/tlsx@latest
RUN go install github.com/projectdiscovery/httpx/cmd/httpx@latest

# trufflehog uses replace directives in go.mod — go install is rejected; use official script
RUN curl -sSfL https://raw.githubusercontent.com/trufflesecurity/trufflehog/main/scripts/install.sh \
    | sh -s -- -b /go/bin

# Stage 2: Python runtime
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=go-builder /go/bin/katana     /usr/local/bin/
COPY --from=go-builder /go/bin/notify     /usr/local/bin/
COPY --from=go-builder /go/bin/gitleaks   /usr/local/bin/
COPY --from=go-builder /go/bin/trufflehog /usr/local/bin/
COPY --from=go-builder /go/bin/subfinder  /usr/local/bin/
COPY --from=go-builder /go/bin/dnsx       /usr/local/bin/
COPY --from=go-builder /go/bin/tlsx       /usr/local/bin/
COPY --from=go-builder /go/bin/httpx      /usr/local/bin/

# go-rod (used by katana for JS crawling) picks up CHROME_BIN
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMIUM_PATH=/usr/bin/chromium
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data/raw_js data/normalized_js data/tmp reports

ENTRYPOINT ["python", "main.py"]
