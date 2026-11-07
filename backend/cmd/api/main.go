package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"finance-dashboard/backend/internal/config"
	"finance-dashboard/backend/internal/httpapi"
	"finance-dashboard/backend/internal/repository"
	"finance-dashboard/backend/internal/service"
)

func main() {
	// Also provides a health probe in the minimal runtime image, without curl or a shell.
	if len(os.Args) > 1 && os.Args[1] == "healthcheck" {
		c := http.Client{Timeout: 2 * time.Second}
		r, err := c.Get("http://127.0.0.1:8080/healthz")
		if err != nil {
			os.Exit(1)
		}
		r.Body.Close()
		if r.StatusCode != 200 {
			os.Exit(1)
		}
		return
	}
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	cfg, err := config.Load()
	if err != nil {
		logger.Error(err.Error())
		os.Exit(1)
	}
	repo, err := repository.Open(cfg.MongoURI, cfg.Database)
	if err != nil {
		logger.Error("invalid MongoDB configuration")
		os.Exit(1)
	}
	server := http.Server{Addr: cfg.Address, Handler: (&httpapi.Server{Service: &service.Service{Repo: repo}, Log: logger, Timeout: cfg.QueryTimeout}).Handler(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 15 * time.Second, IdleTimeout: 60 * time.Second}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	go func() {
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	logger.Info("API listening", "address", cfg.Address)
	err = server.ListenAndServe()
	cleanup, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_ = repo.Client.Disconnect(cleanup)
	if err != nil && !errors.Is(err, http.ErrServerClosed) {
		logger.Error("HTTP server failed")
		os.Exit(1)
	}
}
