package httpapi

import (
	"encoding/json"
	"errors"
	"finance-dashboard/backend/internal/repository"
	"finance-dashboard/backend/internal/service"
	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"
	"io"
	"net/http"
	"slices"
	"strconv"
	"strings"
	"time"
)

func body(w http.ResponseWriter, r *http.Request, v any) bool {
	if strings.Split(r.Header.Get("Content-Type"), ";")[0] != "application/json" {
		problem(w, 415, "invalid_type", "Send application/json")
		return false
	}
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 512<<10))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(v); err != nil || decoder.Decode(new(any)) != io.EOF {
		problem(w, 400, "invalid_body", "Invalid or oversized JSON body")
		return false
	}
	return true
}
func filingCutoff(w http.ResponseWriter, r *http.Request) (string, bool) {
	value := r.URL.Query().Get("through")
	if value != "" {
		if _, err := time.Parse(time.DateOnly, value); err != nil {
			problem(w, 400, "invalid_date", "Use a YYYY-MM-DD filing date")
			return "", false
		}
	}
	return value, true
}
func (s *Server) dimensions(w http.ResponseWriter, r *http.Request) {
	v, ok := symbol(w, r)
	if !ok {
		return
	}
	q := strings.TrimSpace(r.URL.Query().Get("q"))
	if len(q) > 160 {
		problem(w, 400, "invalid_query", "Use a shorter search")
		return
	}
	through, ok := filingCutoff(w, r)
	if !ok {
		return
	}
	data, err := s.Service.Dimensions(r.Context(), v, q, through)
	if err != nil {
		s.fail(w, err)
		return
	}
	write(w, 200, response{data})
}
func (s *Server) pivot(w http.ResponseWriter, r *http.Request) {
	v, ok := symbol(w, r)
	if !ok {
		return
	}
	q := r.URL.Query()
	display := q.Get("display")
	if !factIDPattern.MatchString(q.Get("slice")) || len(q.Get("concept")) > 2048 || !slices.Contains([]string{"", "value", "growth", "share"}, display) {
		problem(w, 400, "invalid_slice", "Select a dimension from discovery")
		return
	}
	csv, ok := exportFormat(w, r)
	if !ok {
		return
	}
	through, ok := filingCutoff(w, r)
	if !ok {
		return
	}
	data, err := s.Service.Pivot(r.Context(), v, q.Get("concept"), q.Get("slice"), display, through, q["member"])
	if err != nil {
		s.fail(w, err)
		return
	}
	if csv {
		out := newCSV(w, v+"-pivot")
		for _, m := range data.Members {
			for i, c := range m.Cells {
				writeCell(out, q.Get("concept")+" · "+m.Name+" · "+display, data.Periods[i], c)
			}
		}
		out.Flush()
		return
	}
	write(w, 200, response{data})
}
func (s *Server) compare(w http.ResponseWriter, r *http.Request) {
	symbols := strings.Split(strings.ToUpper(r.URL.Query().Get("symbols")), ",")
	if len(symbols) > 5 {
		problem(w, 400, "invalid_symbols", "Choose up to five companies")
		return
	}
	for i, v := range symbols {
		if !symbolPattern.MatchString(v) || slices.Contains(symbols[:i], v) {
			problem(w, 400, "invalid_symbols", "Choose unique ticker symbols")
			return
		}
	}
	csv, ok := exportFormat(w, r)
	if !ok {
		return
	}
	data, err := s.Service.Compare(r.Context(), symbols, r.URL.Query().Get("trend") == "true")
	if err != nil {
		s.fail(w, err)
		return
	}
	if csv {
		out := newCSV(w, "peer-comparison")
		for _, peer := range data {
			for _, row := range peer.Rows {
				for _, field := range []string{"revenue", "revenueGrowth", "operatingMargin", "cashConversion", "capitalIntensity"} {
					writeCell(out, peer.Symbol+" "+field, row.Period, row.Values[field])
				}
			}
		}
		out.Flush()
		return
	}
	write(w, 200, response{data})
}
func (s *Server) evaluate(w http.ResponseWriter, r *http.Request) {
	var model service.Model
	if !body(w, r, &model) {
		return
	}
	data, err := service.Evaluate(model)
	if err != nil {
		problem(w, 422, "invalid_model", err.Error())
		return
	}
	write(w, 200, response{map[string]any{"version": service.ModelVersion, "forecasts": data}})
}

type savedItem struct {
	ID       string          `json:"id" bson:"_id"`
	Name     string          `json:"name" bson:"name"`
	Kind     string          `json:"kind" bson:"kind"`
	Symbol   string          `json:"symbol" bson:"symbol"`
	Revision int             `json:"revision" bson:"revision"`
	Payload  json.RawMessage `json:"payload,omitempty" bson:"payload,omitempty"`
}

func (s *Server) workspace(w http.ResponseWriter, r *http.Request) {
	owner := r.Header.Get("X-Workspace-Owner")
	if s.LocalWorkspace {
		owner = "local-fixture"
	}
	if owner == "" {
		problem(w, 403, "user_required", "Sign in to access private work")
		return
	}
	if s.Workspaces == nil {
		problem(w, 503, "workspace_unavailable", "Private saves are unavailable")
		return
	}
	ctx := r.Context()
	if !s.workspaceVerified.Load() {
		if err := repository.VerifyWorkspace(ctx, s.Workspaces.Database()); err != nil {
			problem(w, 503, "workspace_unavailable", "Check the private workspace connection and collection-scoped permissions")
			return
		}
		s.workspaceVerified.Store(true)
	}
	id := r.PathValue("id")
	filter := bson.M{"owner": owner}
	if id != "" {
		if _, err := bson.ObjectIDFromHex(id); err != nil {
			problem(w, 400, "invalid_id", "Invalid saved item")
			return
		}
		filter["_id"] = id
	}
	if r.Method == "GET" {
		if id == "" {
			filter["symbol"] = r.URL.Query().Get("symbol")
			filter["kind"] = r.URL.Query().Get("kind")
			cursor, err := s.Workspaces.Find(ctx, filter, options.Find().SetProjection(bson.M{"payload": 0}).SetSort(bson.D{{Key: "updated", Value: -1}}).SetLimit(200))
			if err != nil {
				s.fail(w, err)
				return
			}
			items := []savedItem{}
			if err = cursor.All(ctx, &items); err != nil {
				s.fail(w, err)
				return
			}
			write(w, 200, response{items})
			return
		}
		var item savedItem
		err := s.Workspaces.FindOne(ctx, filter).Decode(&item)
		if errors.Is(err, mongo.ErrNoDocuments) {
			problem(w, 404, "not_found", "Saved item not found")
			return
		}
		if err != nil {
			s.fail(w, err)
			return
		}
		write(w, 200, response{item})
		return
	}
	if id != "" {
		rev, err := strconv.Atoi(r.Header.Get("If-Match"))
		if err != nil || rev < 1 {
			problem(w, 428, "revision_required", "Supply the saved revision")
			return
		}
		filter["revision"] = rev
	}
	if r.Method == "DELETE" {
		res, err := s.Workspaces.DeleteOne(ctx, filter)
		if err != nil {
			s.fail(w, err)
			return
		}
		if res.DeletedCount == 0 {
			stale(w)
			return
		}
		write(w, 200, response{true})
		return
	}
	var item savedItem
	if !body(w, r, &item) {
		return
	}
	item.Name = strings.TrimSpace(item.Name)
	if item.Name == "" || len(item.Name) > 120 || !symbolPattern.MatchString(item.Symbol) || !slices.Contains([]string{"explore", "compare", "model"}, item.Kind) || len(item.Payload) == 0 || item.Payload[0] != '{' {
		problem(w, 400, "invalid_item", "Provide a name, ticker, view and workspace object")
		return
	}
	if err := validateAnalysis(&item); err != nil {
		problem(w, 422, "invalid_analysis", err.Error())
		return
	}
	fields := bson.M{"name": item.Name, "kind": item.Kind, "symbol": item.Symbol, "payload": []byte(item.Payload), "updated": time.Now().UTC()}
	if id == "" {
		item.ID = bson.NewObjectID().Hex()
		item.Revision = 1
		fields["_id"] = item.ID
		fields["owner"] = owner
		fields["revision"] = 1
		if _, err := s.Workspaces.InsertOne(ctx, fields); err != nil {
			s.fail(w, err)
			return
		}
		write(w, 201, response{item})
		return
	}
	var updated savedItem
	err := s.Workspaces.FindOneAndUpdate(ctx, filter, bson.M{"$set": fields, "$inc": bson.M{"revision": 1}}, options.FindOneAndUpdate().SetReturnDocument(options.After)).Decode(&updated)
	if errors.Is(err, mongo.ErrNoDocuments) {
		stale(w)
		return
	}
	if err != nil {
		s.fail(w, err)
		return
	}
	write(w, 200, response{updated})
}
func stale(w http.ResponseWriter) {
	problem(w, 409, "revision_conflict", "The saved item changed. Reopen it or save a copy.")
}
