package service

import (
	"context"
	"finance-dashboard/backend/internal/domain"
	"go.mongodb.org/mongo-driver/v2/bson"
	"math"
	"os"
	"testing"
	"time"
)

type fixtureRepo map[string][]bson.M

func (f fixtureRepo) Records(_ context.Context, collection, symbol string) ([]bson.M, error) {
	out := []bson.M{}
	for _, r := range f[collection] {
		if r["symbol"] == symbol {
			out = append(out, r)
		}
	}
	return out, nil
}
func (f fixtureRepo) Tickers(context.Context) ([]domain.Ticker, error) { return []domain.Ticker{}, nil }
func (f fixtureRepo) Ping(context.Context) error                       { return nil }
func fixture(t *testing.T) fixtureRepo {
	t.Helper()
	b, err := os.ReadFile("../../testdata/financeapp.json")
	if err != nil {
		t.Fatal(err)
	}
	var f fixtureRepo
	if err = bson.UnmarshalExtJSON(b, false, &f); err != nil {
		t.Fatal(err)
	}
	return f
}
func TestLegacyNormalization(t *testing.T) {
	s := Service{Repo: fixture(t)}
	ctx := context.Background()
	c, err := s.Company(ctx, "DEMO")
	if err != nil || c.Name != "Example Industries" || c.Price == nil || *c.Price != 12.55 || c.AsOf == nil {
		t.Fatalf("profile: %+v %v", c, err)
	}
	rows, err := s.Statements(ctx, "DEMO", "income")
	if err != nil || len(rows) != 3 {
		t.Fatalf("statements: %+v %v", rows, err)
	}
	if rows[0].Date != "2024-12-31" || *rows[0].Values["revenue"] != 125.5 || rows[0].Values["costOfRevenue"] != nil {
		t.Fatalf("unexpected normalized record: %+v", rows[0])
	}
	prices, err := s.Prices(ctx, "DEMO", "2024-12-31", "2024-12-31")
	if err != nil || len(prices) != 1 || *prices[0].Close != 12.75 {
		t.Fatalf("prices: %+v %v", prices, err)
	}
	splits, err := s.Splits(ctx, "DEMO")
	if err != nil || len(splits) != 1 || *splits[0].Numerator != 2 {
		t.Fatalf("splits: %+v %v", splits, err)
	}
}
func TestMetricAlignment(t *testing.T) {
	s := Service{Repo: fixture(t)}
	m, err := s.Metrics(context.Background(), "DEMO")
	if err != nil {
		t.Fatal(err)
	}
	if len(m.Points) != 3 {
		t.Fatalf("points: %+v", m.Points)
	}
	p := m.Points[2]
	if *p.Values["workingCapital"] != 50 || *p.Values["freeCashFlowPerShare"] != 2 || math.Abs(*p.Growth["revenue"]-.255) > 1e-10 {
		t.Fatalf("metrics: %+v", p)
	}
	if m.Points[1].Growth["revenue"] != nil {
		t.Fatal("quarter compared to annual")
	}
}
func TestGrowthMissingYearZeroAndCurrency(t *testing.T) {
	for _, tc := range []struct {
		name, year, currency string
		previous             float64
	}{{"gap", "2021", "USD", 10}, {"zero", "2023", "USD", 0}, {"currency", "2023", "EUR", 10}} {
		t.Run(tc.name, func(t *testing.T) {
			s := Service{Repo: fixtureRepo{"income_statement": {{"symbol": "X", "date": tc.year + "-12-31", "calendarYear": tc.year, "period": "FY", "reportedCurrency": tc.currency, "revenue": tc.previous}, {"symbol": "X", "date": "2024-12-31", "calendarYear": "2024", "period": "FY", "reportedCurrency": "USD", "revenue": 20}}}}
			m, err := s.Metrics(context.Background(), "X")
			if err != nil {
				t.Fatal(err)
			}
			if m.Points[len(m.Points)-1].Growth["revenue"] != nil {
				t.Fatal("undefined growth must be null")
			}
		})
	}
}
func TestNumberRejectsNonFiniteAndMissing(t *testing.T) {
	for _, v := range []any{nil, "N/A", "NaN", "Inf", math.Inf(1), true} {
		if Number(v) != nil {
			t.Fatalf("accepted %v", v)
		}
	}
	if date(bson.NewDateTimeFromTime(time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC))) != "2024-01-01" {
		t.Fatal("BSON date")
	}
}
func TestPartialAndUnknownCompany(t *testing.T) {
	s := Service{Repo: fixture(t)}
	c, err := s.Company(context.Background(), "EMPTY")
	if err != nil || c.Symbol != "EMPTY" || c.Price != nil {
		t.Fatal(c, err)
	}
	if _, err := s.Company(context.Background(), "UNKNOWN"); err != ErrNotFound {
		t.Fatal(err)
	}
}

func TestObservedAtlasShapes(t *testing.T) {
	b, err := os.ReadFile("../../testdata/observed-shapes.json")
	if err != nil {
		t.Fatal(err)
	}
	var f fixtureRepo
	if err = bson.UnmarshalExtJSON(b, false, &f); err != nil {
		t.Fatal(err)
	}
	s := Service{Repo: f}
	ctx := context.Background()
	if _, err = s.Company(ctx, "SAMPLE"); err != nil {
		t.Fatal(err)
	}
	for _, kind := range []string{"income", "balance", "cash-flow"} {
		rows, err := s.Statements(ctx, "SAMPLE", kind)
		if err != nil || len(rows) != 2 {
			t.Fatalf("%s: %d rows %v", kind, len(rows), err)
		}
		for _, row := range rows {
			if len(row.Values) != len(Fields[kind]) {
				t.Fatal("missing fields")
			}
		}
	}
	prices, err := s.Prices(ctx, "SAMPLE", "", "")
	if err != nil || len(prices) != 2 {
		t.Fatal(prices, err)
	}
}
