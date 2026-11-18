package repository_test

import (
	"context"
	"encoding/json"
	"finance-dashboard/backend/internal/httpapi"
	"finance-dashboard/backend/internal/repository"
	"fmt"
	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"io"
	"log/slog"
	"net/http/httptest"
	"strings"
	"testing"
)

func verifyWorkspace(t *testing.T, ctx context.Context, db *mongo.Database, host string) {
	t.Helper()
	coll := repository.WorkspaceCollection
	if err := repository.VerifyWorkspace(ctx, db); err == nil {
		t.Fatal("workspace accepted an admin credential")
	}
	if err := db.CreateCollection(ctx, coll); err != nil {
		t.Fatal(err)
	}
	if err := db.RunCommand(ctx, bson.D{{Key: "createRole", Value: "analystEditor"}, {Key: "privileges", Value: bson.A{bson.M{"resource": bson.M{"db": db.Name(), "collection": coll}, "actions": bson.A{"find", "insert", "update", "remove"}}}}, {Key: "roles", Value: bson.A{}}}).Err(); err != nil {
		t.Fatal(err)
	}
	defer db.RunCommand(ctx, bson.D{{Key: "dropRole", Value: "analystEditor"}})
	if err := db.RunCommand(ctx, bson.D{{Key: "createUser", Value: "analyst-fixture"}, {Key: "pwd", Value: "fixture-only"}, {Key: "roles", Value: bson.A{"analystEditor"}}}).Err(); err != nil {
		t.Fatal(err)
	}
	defer db.RunCommand(ctx, bson.D{{Key: "dropUser", Value: "analyst-fixture"}})
	ws, err := repository.Open(fmt.Sprintf("mongodb://analyst-fixture:fixture-only@%s/SECIngestion", host))
	if err != nil {
		t.Fatal(err)
	}
	defer ws.Client.Disconnect(ctx)
	if _, err = ws.DB.Collection("facts").InsertOne(ctx, bson.M{"test": true}); err == nil {
		t.Fatal("workspace role could write facts")
	}
	if err = ws.DB.Collection("facts").FindOne(ctx, bson.M{}).Err(); err == nil {
		t.Fatal("workspace role could read facts")
	}
	h := (&httpapi.Server{Workspaces: ws.DB.Collection(coll), Log: slog.New(slog.NewTextHandler(io.Discard, nil))}).Handler()
	request := func(method, path, body, owner, rev string) *httptest.ResponseRecorder {
		r := httptest.NewRequest(method, "/api/v1/workspaces"+path, strings.NewReader(body))
		r.Header.Set("X-Workspace-Owner", owner)
		r.Header.Set("Content-Type", "application/json")
		r.Header.Set("If-Match", rev)
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		return w
	}
	input := `{"name":"base","symbol":"DEMO","kind":"compare","payload":{"peers":["PEER"],"trend":true}}`
	create := request("POST", "", input, "analyst-a", "")
	if create.Code != 201 {
		t.Fatal(create.Code, create.Body.String())
	}
	var result struct{ Data struct{ ID string } }
	if err = json.Unmarshal(create.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	path := "/" + result.Data.ID
	if w := request("GET", path, "", "analyst-b", ""); w.Code != 404 {
		t.Fatal("owner isolation", w.Code)
	}
	if w := request("GET", path, "", "analyst-a", ""); w.Code != 200 || !strings.Contains(w.Body.String(), `"peers":["PEER"]`) {
		t.Fatal(w.Code, w.Body.String())
	}
	results := make(chan int, 2)
	for range 2 {
		go func() { results <- request("PUT", path, input, "analyst-a", "1").Code }()
	}
	a, b := <-results, <-results
	if !((a == 200 && b == 409) || (a == 409 && b == 200)) {
		t.Fatal(a, b)
	}
	if w := request("DELETE", path, "", "analyst-b", "2"); w.Code != 409 {
		t.Fatal(w.Code)
	}
	if w := request("DELETE", path, "", "analyst-a", "2"); w.Code != 200 {
		t.Fatal(w.Code)
	}
}
