# Alpine Linux 3.19 - minimal base (~5MB)
FROM alpine:3.19

# Install common development tools
RUN apk add --no-cache \
    bash \
    coreutils \
    python3 \
    py3-pip \
    nodejs \
    npm \
    git \
    curl \
    wget \
    jq \
    # Build tools for compilation
    gcc \
    musl-dev \
    python3-dev \
    # Networking tools
    ca-certificates \
    && rm -rf /var/cache/apk/*

# Create non-root user for execution
RUN addgroup -g 1000 sandbox && \
    adduser -D -u 1000 -G sandbox sandbox

# Create workspace directory with proper permissions
RUN mkdir -p /workspace && chown sandbox:sandbox /workspace

# Set working directory
WORKDIR /workspace

# Switch to non-root user (overridden at runtime but good default)
USER sandbox

# Keep container running
CMD ["tail", "-f", "/dev/null"]
