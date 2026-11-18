package httpapi

import (
	"context"
	"encoding/json"
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
func (f *fakeRepo) FilingWindow(ctx context.Context, cik, _ string, _ bool, _ int) ([]domain.Filing, error) {
	return f.Filings(ctx, cik)
}
func (*fakeRepo) Facts(_ context.Context, _ []domain.Filing, filter bson.M) ([]domain.Fact, error) {
	value := "123"
	ctx := "ctx"
	if filter["_id"] != nil || filter["dimensions.0"] != nil || filter["concept"] == "{http://fasb.org/us-gaap/2026}Revenues" {
		ctx = "seg"
	}
	return []domain.Fact{{Accession: accession, Generation: "g1", Concept: "{http://fasb.org/us-gaap/2026}Revenues", Label: "=not a formula", Value: &value, ContextRef: ctx, UnitRef: "usd", RawValue: "-123"}}, nil
}
func (*fakeRepo) Contexts(context.Context, []domain.Filing, []domain.Fact) ([]domain.Context, error) {
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
		{"GET", "/api/v1/companies/DEMO/unsupported", 404},
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

func TestWorkspaceModelSnapshots(t *testing.T) {
	row, err := (&service.Service{Repo: &fakeRepo{}}).Metrics(context.Background(), "DEMO", "annual", 5)
	if err != nil || len(row.Rows) == 0 {
		t.Fatal(err)
	}
	scenarios := map[string]service.Scenario{}
	for _, name := range []string{"bear", "base", "bull"} {
		s := service.Scenario{OpeningWC: "0", WACC: "10", TerminalGrowth: "0"}
		for range 5 {
			s.Years = append(s.Years, service.Drivers{Growth: "0", Margin: "10", Tax: "0", DA: "0", Capex: "0", WC: "0"})
		}
		scenarios[name] = s
	}
	payload, err := json.Marshal(map[string]any{"baseline": row.Rows[0], "scenarios": scenarios, "result": map[string]any{"version": service.ModelVersion}})
	if err != nil {
		t.Fatal(err)
	}
	item := savedItem{Kind: "model", Payload: payload}
	if err = validateAnalysis(&item); err != nil {
		t.Fatal(err)
	}
	var result struct {
		Baseline domain.Row
		Result   struct {
			Forecasts map[string]service.Forecast
			Version   string
		}
	}
	if err = json.Unmarshal(item.Payload, &result); err != nil {
		t.Fatal(err)
	}
	f := result.Result.Forecasts["base"]
	c := result.Baseline.Values["revenue"]
	if *f.EV != "123.0000" || *c.Value != "123" || c.Sources[0].Generation != "g1" || result.Result.Version != service.ModelVersion {
		t.Fatal(result)
	}
}
