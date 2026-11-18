package httpapi

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"finance-dashboard/backend/internal/domain"
	"finance-dashboard/backend/internal/repository"
	"finance-dashboard/backend/internal/service"
	"go.mongodb.org/mongo-driver/v2/bson"
)

type fakeRepo struct{}

var demo = domain.Issuer{CIK: "0000000001", Name: "Example", Symbols: []string{"DEMO"}, SIC: "2000"}
var accession = "0000000001-26-000001"
var fakeID = strings.Repeat("a", 64)

func (*fakeRepo) Ready(context.Context) error { return nil }
func (*fakeRepo) Issuer(_ context.Context, symbol string) (domain.Issuer, error) {
	if symbol != "DEMO" {
		return domain.Issuer{}, repository.ErrNotFound
	}
	return demo, nil
}
func (*fakeRepo) Related(context.Context, domain.Issuer) ([]domain.Issuer, error) {
	return []domain.Issuer{demo}, nil
}
func (*fakeRepo) Filings(context.Context, string) ([]domain.Filing, error) {
	return []domain.Filing{{Accession: accession, Generation: "g1", Form: "10-K", ReportDate: "2026-09-26", Filed: "2026-11-03", SourceURL: "https://www.sec.gov/Archives/edgar/filing.html"}}, nil
}
func (*fakeRepo) Facts(_ context.Context, _ []domain.Filing, filter bson.M) ([]domain.Fact, error) {
	value := "123"
	ctx := "ctx"
	if filter["_id"] != nil || filter["dimensions.0"] != nil {
		ctx = "seg"
	}
	return []domain.Fact{{Accession: accession, Generation: "g1", Concept: "{http://fasb.org/us-gaap/2026}Revenues", Label: "=not a formula", Value: &value, ContextRef: ctx, UnitRef: "usd", RawValue: "-123"}}, nil
}
func (*fakeRepo) Contexts(context.Context, []domain.Filing) ([]domain.Context, error) {
	main := domain.Context{Accession: accession, Generation: "g1", ContextRef: "ctx", Entity: "0000000001", StartDate: "2025-09-28", EndDate: "2026-09-26"}
	seg := main
	seg.ContextRef = "seg"
	seg.Dimensions = []domain.Dimension{{Axis: "axis"}}
	return []domain.Context{main, seg}, nil
}
func (*fakeRepo) Units(context.Context, []domain.Filing) ([]domain.Unit, error) {
	return []domain.Unit{{Accession: accession, Generation: "g1", UnitRef: "usd", Numerator: []string{"{http://www.xbrl.org/2003/iso4217}USD"}}}, nil
}
func server() http.Handler {
	return (&Server{Service: &service.Service{Repo: &fakeRepo{}}, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}).Handler()
}
func TestCutoverRoutes(t *testing.T) {
	h := server()
	for _, test := range []struct {
		method, path string
		status       int
	}{
		{"GET", "/api/v1/companies/DEMO/prices", 404},
		{"GET", "/api/v1/companies/DEMO/splits", 404},
		{"GET", "/api/v1/companies/NOPE/metrics", 404},
		{"GET", "/api/v1/companies/DEMO/metrics?period=invalid", 400},
		{"GET", "/api/v1/companies/DEMO/metrics?limit=201", 400},
		{"GET", "/api/v1/companies/DEMO/segments", 400},
		{"POST", "/api/v1/companies/DEMO/metrics", 405},
	} {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest(test.method, test.path, nil))
		if rec.Code != test.status {
			t.Errorf("%s: got %d, want %d", test.path, rec.Code, test.status)
		}
	}
}

func TestStatementAndSegmentCSV(t *testing.T) {
	h := server()
	for _, suffix := range []string{"statements/income?period=annual&format=csv", "segments?format=csv&accession=" + accession + "&fact=" + fakeID} {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest("GET", "/api/v1/companies/DEMO/"+suffix, nil))
		body := rec.Body.String()
		if rec.Code != 200 || !strings.Contains(rec.Header().Get("Content-Type"), "text/csv") || !strings.Contains(body, "2026-09-26") || !strings.Contains(body, accession) || !strings.Contains(body, "'-123") {
			t.Fatalf("bad CSV: %d %s", rec.Code, body)
		}
		if strings.HasPrefix(suffix, "segments") && !strings.Contains(body, "'=not a formula") {
			t.Fatalf("unescaped formula: %s", body)
		}
	}
}
