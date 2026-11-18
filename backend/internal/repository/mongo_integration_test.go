package repository_test

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"testing"
	"time"

	"finance-dashboard/backend/internal/repository"
	"finance-dashboard/backend/internal/service"
	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"
)

func TestPublishedSECFilingReads(t *testing.T) {
	rawURI := os.Getenv("MONGODB_TEST_URI")
	if rawURI == "" {
		t.Skip("requires disposable authenticated MongoDB")
	}
	uri, err := url.Parse(rawURI)
	if err != nil || uri.Scheme != "mongodb" || uri.Hostname() != "127.0.0.1" {
		t.Fatal("integration test requires loopback disposable MongoDB")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	admin, err := mongo.Connect(options.Client().ApplyURI(rawURI))
	if err != nil {
		t.Fatal(err)
	}
	defer admin.Disconnect(ctx)
	db := admin.Database(repository.Database)
	names, err := db.ListCollectionNames(ctx, bson.M{})
	if err != nil || len(names) != 0 {
		t.Fatal("integration test requires empty disposable SECIngestion")
	}
	defer db.Drop(ctx)
	raw, err := os.ReadFile("../../testdata/published.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixture map[string][]json.RawMessage
	if err = json.Unmarshal(raw, &fixture); err != nil {
		t.Fatal(err)
	}
	for collection, entries := range fixture {
		docs := []bson.M{}
		for _, entry := range entries {
			var doc bson.M
			if err = bson.UnmarshalExtJSON(entry, false, &doc); err != nil {
				t.Fatal(err)
			}
			docs = append(docs, doc)
		}
		if _, err = db.Collection(collection).InsertMany(ctx, docs); err != nil {
			t.Fatal(err)
		}
	}
	if err = db.RunCommand(ctx, bson.D{{Key: "createUser", Value: "fixture-reader"}, {Key: "pwd", Value: "reader-only"}, {Key: "roles", Value: bson.A{"read"}}}).Err(); err != nil {
		t.Fatal(err)
	}
	defer db.RunCommand(ctx, bson.D{{Key: "dropUser", Value: "fixture-reader"}})
	reader, err := repository.Open(fmt.Sprintf("mongodb://fixture-reader:reader-only@%s/SECIngestion", uri.Host))
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Client.Disconnect(ctx)
	if err = reader.Ready(ctx); err != nil {
		t.Fatal(err)
	}
	if _, err = reader.DB.Collection("schema").UpdateOne(ctx, bson.M{"_id": "ingestion"}, bson.M{"$set": bson.M{"version": 999}}); err == nil {
		t.Fatal("reader was able to write")
	}
	broader, err := repository.Open(rawURI)
	if err != nil {
		t.Fatal(err)
	}
	defer broader.Client.Disconnect(ctx)
	if err = broader.Ready(ctx); !errors.Is(err, repository.ErrReaderRole) {
		t.Fatalf("broader credential allowed: %v", err)
	}

	verifyWorkspace(t, ctx, db, uri.Host)
	s := &service.Service{Repo: reader}
	start := time.Now()
	metrics, err := s.Metrics(ctx, "DEMO", "all", 20)
	if err != nil {
		t.Fatal(err)
	}
	t.Logf("Metrics read over %d reporting rows: %s", len(metrics.Rows), time.Since(start))
	var annual, quarter, ytd bool
	for _, row := range metrics.Rows {
		switch [2]string{row.Period.Mode, row.Period.End} {
		case [2]string{"annual", "2026-09-26"}:
			annual = true
			expect(t, row.Values["revenue"].Value, "478834000000")
			if row.Period.FiscalPeriod != "FY" || row.Values["revenue"].Sources[0].Accession != "0000320193-26-000026" || row.Growth["revenue"] == nil {
				t.Fatalf("bad period/provenance: %+v", row)
			}
		case [2]string{"quarter", "2026-06-27"}:
			quarter = true
			expect(t, row.Values["revenue"].Value, "109417000000")
			expect(t, row.Values["operatingIncome"].Value, "13")
			if row.Values["netIncome"].Issue != "conflicting_values" || row.Values["netIncome"].Value != nil || row.Values["operatingCashFlow"].Value != nil {
				t.Fatalf("ambiguous facts were reported: %+v", row)
			}
		case [2]string{"ytd", "2026-06-27"}:
			ytd = true
			expect(t, row.Values["revenue"].Value, "364357000000")
			expect(t, row.Values["freeCashFlow"].Value, "110197000000")
		}
	}
	if !annual || !quarter || !ytd {
		t.Fatal("missing reporting periods")
	}
	var anchor struct {
		ID string `bson:"_id"`
	}
	if err := db.Collection("facts").FindOne(ctx, bson.M{"accession": "0000320193-26-000020", "ordinal": 6}).Decode(&anchor); err != nil {
		t.Fatal(err)
	}
	trend, err := s.Segment(ctx, "DEMO", "0000320193-26-000020", anchor.ID)
	if err != nil || len(trend.Points) != 2 {
		t.Fatalf("segment series: %+v %v", trend, err)
	}
	expect(t, trend.Points[1].Cell.Value, "18816000000")
	issuer, err := reader.Issuer(ctx, "DEMO")
	if err != nil {
		t.Fatal(err)
	}
	related, err := reader.Related(ctx, issuer)
	if err != nil || len(related) != 1 || related[0].Symbols[0] != "PEER" {
		t.Fatalf("related issuers: %+v %v", related, err)
	}
	// A later EUR filing exercises separate currency columns and non-aligned annual ends.
	peerFil := bson.M{"_id": "0000000020-26-000001", "cik": "0000000020", "generation": "p", "form": "10-K", "filingDate": "2026-02-01", "reportDate": "2025-12-31", "sourceUrl": "https://www.sec.gov/Archives/peer"}
	if _, err = db.Collection("filings").InsertOne(ctx, peerFil); err != nil {
		t.Fatal(err)
	}
	base := func() bson.M { return bson.M{"accession": peerFil["_id"], "generation": "p"} }
	c := base()
	c["contextRef"] = "ctx"
	c["entity"] = "0000000020"
	c["startDate"] = "2025-01-01"
	c["endDate"] = "2025-12-31"
	c["dimensions"] = bson.A{}
	u := base()
	u["unitRef"] = "eur"
	u["numerator"] = bson.A{"{http://www.xbrl.org/2003/iso4217}EUR"}
	f := base()
	f["concept"] = "{http://fasb.org/us-gaap/2026}Revenues"
	f["unitRef"] = "eur"
	f["contextRef"] = "ctx"
	f["value"] = "100"
	f["dimensions"] = bson.A{}
	for collection, doc := range map[string]bson.M{"contexts": c, "units": u, "facts": f} {
		if _, err = db.Collection(collection).InsertOne(ctx, doc); err != nil {
			t.Fatal(err)
		}
	}
	peers, err := s.Compare(ctx, []string{"DEMO", "PEER"}, true)
	if err != nil || len(peers) != 2 || !peers[1].Misaligned || len(peers[1].Rows) != 1 || peers[1].Rows[0].Values["revenue"].Unit != "EUR" || peers[0].Rows[0].Values["revenue"].Unit != "USD" {
		t.Fatal(peers, err)
	}

}

func expect(t *testing.T, value *string, want string) {
	t.Helper()
	if value == nil || *value != want {
		t.Fatalf("expected %s, got %v", want, value)
	}
}
