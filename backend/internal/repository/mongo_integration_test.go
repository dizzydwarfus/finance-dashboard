package repository_test

import (
	"context"
	"finance-dashboard/backend/internal/repository"
	"finance-dashboard/backend/internal/service"
	"fmt"
	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"
	"net/url"
	"os"
	"testing"
	"time"
)

// Only MONGODB_TEST_URI enables writes, in a randomly named disposable database.
// Never supply an Atlas production URI here. The application itself has no writers.
func TestMongoReadOnlyIntegration(t *testing.T) {
	uri := os.Getenv("MONGODB_TEST_URI")
	if uri == "" {
		t.Skip("MONGODB_TEST_URI not set; requires disposable MongoDB with user-admin permissions")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	writer, err := mongo.Connect(options.Client().ApplyURI(uri))
	if err != nil {
		t.Fatal(err)
	}
	defer writer.Disconnect(context.Background())
	name := fmt.Sprintf("finance_dashboard_test_%d", time.Now().UnixNano())
	db := writer.Database(name)
	defer db.Drop(context.Background())
	bytes, err := os.ReadFile("../../testdata/financeapp.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture map[string][]bson.M
	if err = bson.UnmarshalExtJSON(bytes, false, &fixture); err != nil {
		t.Fatal(err)
	}
	for collection, records := range fixture {
		docs := make([]any, len(records))
		for i, row := range records {
			docs[i] = row
		}
		if len(docs) > 0 {
			if _, err = db.Collection(collection).InsertMany(ctx, docs); err != nil {
				t.Fatal(err)
			}
		}
	}
	if err = db.RunCommand(ctx, bson.D{{Key: "createUser", Value: "reader"}, {Key: "pwd", Value: "fixture-only"}, {Key: "roles", Value: bson.A{bson.M{"role": "read", "db": name}}}}).Err(); err != nil {
		t.Fatal(err)
	}
	defer db.RunCommand(context.Background(), bson.D{{Key: "dropUser", Value: "reader"}})
	u, err := url.Parse(uri)
	if err != nil {
		t.Fatal(err)
	}
	u.User = url.UserPassword("reader", "fixture-only")
	u.Path = "/" + name
	q := u.Query()
	q.Set("authSource", name)
	u.RawQuery = q.Encode()
	reader, err := repository.Open(u.String(), name)
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Client.Disconnect(context.Background())
	s := service.Service{Repo: reader}
	before, err := db.Collection("income_statement").CountDocuments(ctx, bson.M{})
	if err != nil {
		t.Fatal(err)
	}
	tickers, err := reader.Tickers(ctx)
	if err != nil || len(tickers) != 2 {
		t.Fatalf("tickers: %+v %v", tickers, err)
	}
	c, err := s.Company(ctx, "DEMO")
	if err != nil || c.Name != "Example Industries" {
		t.Fatal(c, err)
	}
	rows, err := s.Statements(ctx, "DEMO", "income")
	if err != nil || len(rows) != 3 {
		t.Fatal(rows, err)
	}
	metrics, err := s.Metrics(ctx, "DEMO")
	if err != nil || *metrics.Points[2].Values["workingCapital"] != 50 {
		t.Fatal(metrics, err)
	}
	prices, err := s.Prices(ctx, "DEMO", "", "")
	if err != nil || len(prices) != 2 {
		t.Fatal(prices, err)
	}
	if _, err = reader.DB.Collection("income_statement").InsertOne(ctx, bson.M{"symbol": "UNAUTHORIZED"}); err == nil {
		t.Fatal("read-only user was allowed to write; start MongoDB with authentication enabled")
	}
	after, err := db.Collection("income_statement").CountDocuments(ctx, bson.M{})
	if err != nil || before != after {
		t.Fatal("read API changed stored documents")
	}
}

// Opt-in live smoke test performs no writes or schema changes.
func TestAtlasReadSmoke(t *testing.T) {
	uri := os.Getenv("MONGODB_SMOKE_URI")
	if uri == "" {
		t.Skip("MONGODB_SMOKE_URI not set")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	reader, err := repository.Open(uri, "FinanceApp")
	if err != nil {
		t.Fatal("cannot configure MongoDB")
	}
	defer reader.Client.Disconnect(context.Background())
	if err = reader.Ping(ctx); err != nil {
		t.Fatal("MongoDB ping failed")
	}
	tickers, err := reader.Tickers(ctx)
	if err != nil || len(tickers) == 0 {
		t.Fatal("cannot list stored symbols")
	}
	s := service.Service{Repo: reader}
	symbol := tickers[0].Symbol
	if _, err = s.Company(ctx, symbol); err != nil {
		t.Fatal("profile read failed")
	}
	for _, kind := range []string{"income", "balance", "cash-flow"} {
		if _, err = s.Statements(ctx, symbol, kind); err != nil {
			t.Fatal("statement read failed")
		}
	}
	if _, err = s.Metrics(ctx, symbol); err != nil {
		t.Fatal("metrics read failed")
	}
	if _, err = s.Prices(ctx, symbol, "", ""); err != nil {
		t.Fatal("price read failed")
	}
	if _, err = s.Splits(ctx, symbol); err != nil {
		t.Fatal("split read failed")
	}
	t.Logf("Validated Go driver and six collection reads; %d stored symbols", len(tickers))
}
