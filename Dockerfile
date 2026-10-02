# syntax=docker/dockerfile:1

# This Dockerfile uses Docker Hardened Images (DHI) for enhanced security.
# For more information, see https://docs.docker.com/dhi/

# Use the dev image to build and install dependencies.
FROM dhi.io/python:3.14-dev AS builder

WORKDIR /app

# Install uv in the builder stage
RUN pip install uv

# Configure uv to place the virtual environment at a predictable path
ENV UV_PROJECT_ENVIRONMENT=/venv

# Copy dependency management files
# The asterisk on uv.lock* ensures the build doesn't fail if a lockfile hasn't been generated yet
COPY pyproject.toml uv.lock* ./

# Sync dependencies as a separate step to take advantage of Docker's caching.
# --no-install-project prevents uv from trying to install the app itself before the code is copied.
# --no-dev excludes development dependencies (like pytest or ruff) from the production image.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Use the minimal runtime image. It runs as nonroot by default.
FROM dhi.io/python:3.14

WORKDIR /app

# Copy the pre-built virtual environment from the builder
COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH"

# Copy the source code into the container.
COPY . .

# Expose the port that the application listens on.
EXPOSE 8000

# Run the application. 
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]