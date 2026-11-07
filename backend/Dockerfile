# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM golang:1.26-alpine AS build
ARG TARGETOS=linux
ARG TARGETARCH=amd64
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY cmd ./cmd
COPY internal ./internal
RUN CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -trimpath -ldflags='-s -w' -o /api ./cmd/api && go clean -cache
FROM --platform=$TARGETPLATFORM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /api /api
ENV LISTEN_ADDR=:8080
EXPOSE 8080
USER 65532:65532
HEALTHCHECK --interval=30s --timeout=3s CMD ["/api", "healthcheck"]
ENTRYPOINT ["/api"]
