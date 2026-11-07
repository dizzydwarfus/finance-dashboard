package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"finance-dashboard/backend/internal/domain"
	"finance-dashboard/backend/internal/service"
	"go.mongodb.org/mongo-driver/v2/bson"
	"io"
	"log/slog"
	"net/http/httptest"
	"testing"
	"time"
)

type fakeRepo struct{ fail, wait bool }

func (f *fakeRepo) Ping(ctx context.Context) error {
	if f.wait {
		<-ctx.Done()
		return ctx.Err()
	}
	if f.fail {
		return errors.New("secret URI should not leak")
	}
	return nil
}
func (f *fakeRepo) Tickers(ctx context.Context) ([]domain.Ticker, error) {
	if err := f.Ping(ctx); err != nil {
		return nil, err
	}
	return []domain.Ticker{{Symbol: "DEMO", Coverage: []string{"company_profile"}}}, nil
}
func (f *fakeRepo) Records(ctx context.Context, c, s string) ([]bson.M, error) {
	if err := f.Ping(ctx); err != nil {
		return nil, err
	}
	if s == "DEMO" && c == "company_profile" {
		return []bson.M{{"symbol": s, "companyName": "Demo"}}, nil
	}
	return []bson.M{}, nil
}
func TestHTTPContract(t *testing.T) {
	h := (&Server{Service: &service.Service{Repo: &fakeRepo{}}, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}).Handler()
	cases := []struct {
		path   string
		status int
		key    string
	}{{"/healthz", 200, "data"}, {"/readyz", 200, "data"}, {"/api/v1/tickers?q=dem", 200, "data"}, {"/api/v1/tickers?limit=2001", 400, "error"}, {"/api/v1/companies/demo", 200, "data"}, {"/api/v1/companies/UNKNOWN", 404, "error"}, {"/api/v1/companies/%24bad", 400, "error"}, {"/api/v1/companies/DEMO/statements/income", 200, "data"}, {"/api/v1/companies/DEMO/statements/bogus", 400, "error"}, {"/api/v1/companies/DEMO/metrics?period=Q9", 400, "error"}, {"/api/v1/companies/DEMO/prices?from=2024-02-30", 400, "error"}, {"/api/v1/companies/DEMO/prices?from=2025-01-01&to=2024-01-01", 400, "error"}, {"/api/v1/companies/DEMO/prices", 200, "data"}, {"/api/v1/companies/DEMO/splits", 200, "data"}, {"/missing", 404, "error"}}
	for _, tc := range cases {
		t.Run(tc.path, func(t *testing.T) {
			r := httptest.NewRecorder()
			h.ServeHTTP(r, httptest.NewRequest("GET", tc.path, nil))
			if r.Code != tc.status {
				t.Fatalf("%d: %s", r.Code, r.Body.String())
			}
			var v map[string]json.RawMessage
			if err := json.Unmarshal(r.Body.Bytes(), &v); err != nil || v[tc.key] == nil {
				t.Fatalf("invalid JSON contract %s", r.Body.String())
			}
		})
	}
}
func TestDatabaseFailureAndRecovery(t *testing.T) {
	f := &fakeRepo{fail: true}
	h := (&Server{Service: &service.Service{Repo: f}, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}).Handler()
	for _, want := range []int{503, 200} {
		r := httptest.NewRecorder()
		h.ServeHTTP(r, httptest.NewRequest("GET", "/readyz", nil))
		if r.Code != want {
			t.Fatal(r.Code)
		}
		f.fail = false
	}
}
func TestDeadline(t *testing.T) {
	h := (&Server{Service: &service.Service{Repo: &fakeRepo{wait: true}}, Log: slog.New(slog.NewTextHandler(io.Discard, nil)), Timeout: time.Millisecond}).Handler()
	r := httptest.NewRecorder()
	h.ServeHTTP(r, httptest.NewRequest("GET", "/readyz", nil))
	if r.Code != 503 {
		t.Fatal(r.Code)
	}
}

func TestMutationMethodsAreRejected(t *testing.T) {
	h := (&Server{Service: &service.Service{Repo: &fakeRepo{}}, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}).Handler()
	for _, method := range []string{"POST", "PUT", "PATCH", "DELETE"} {
		r := httptest.NewRecorder()
		h.ServeHTTP(r, httptest.NewRequest(method, "/api/v1/companies/DEMO", nil))
		if r.Code != 405 || r.Header().Get("Allow") != "GET, HEAD" {
			t.Fatalf("%s: %d", method, r.Code)
		}
	}
}
