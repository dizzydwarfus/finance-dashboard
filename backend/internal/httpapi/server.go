package httpapi

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode"

	"finance-dashboard/backend/internal/domain"
	"finance-dashboard/backend/internal/repository"
	"finance-dashboard/backend/internal/service"
)

type Server struct {
	Service *service.Service
	Log     *slog.Logger
	Timeout time.Duration
}

type response struct {
	Data any `json:"data"`
}
type apiError struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}
type statusWriter struct {
	http.ResponseWriter
	status int
}

func (w *statusWriter) WriteHeader(status int) {
	if w.status != 0 {
		return
	}
	w.status = status
	w.ResponseWriter.WriteHeader(status)
}
func (w *statusWriter) Write(data []byte) (int, error) {
	if w.status == 0 {
		w.WriteHeader(http.StatusOK)
	}
	return w.ResponseWriter.Write(data)
}

var symbolPattern = regexp.MustCompile(`^[A-Z0-9][A-Z0-9.-]{0,19}$`)
var csvNumber = regexp.MustCompile(`^-?[0-9]+(?:\.[0-9]+)?$`)
var factIDPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)
var accessionPattern = regexp.MustCompile(`^[0-9]{10}-[0-9]{2}-[0-9]{6}$`)

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		write(w, 200, response{Data: map[string]string{"status": "ok"}})
	})
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		if err := s.Service.Repo.Ready(r.Context()); err != nil {
			s.fail(w, err)
			return
		}
		write(w, 200, response{Data: map[string]string{"status": "ready"}})
	})
	mux.HandleFunc("GET /api/v1/companies/{symbol}/statements/{type}", s.statements)
	mux.HandleFunc("GET /api/v1/companies/{symbol}/metrics", s.metrics)
	mux.HandleFunc("GET /api/v1/companies/{symbol}/related", s.related)
	mux.HandleFunc("GET /api/v1/companies/{symbol}/segments", s.segment)
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) { problem(w, 404, "not_found", "Endpoint not found") })
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		recorded := &statusWriter{ResponseWriter: w}
		timeout := s.Timeout
		if timeout == 0 {
			timeout = 8 * time.Second
		}
		ctx, cancel := context.WithTimeout(r.Context(), timeout)
		defer cancel()
		recorded.Header().Set("Cache-Control", "no-store")
		recorded.Header().Set("X-Content-Type-Options", "nosniff")
		defer func() {
			if recover() != nil {
				s.Log.Error("request panic")
				problem(recorded, 500, "internal_error", "Unexpected server error")
			}
			s.Log.Info("request", "method", r.Method, "path", r.URL.Path, "status", recorded.status, "duration_ms", time.Since(start).Milliseconds())
		}()
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			recorded.Header().Set("Allow", "GET, HEAD")
			problem(recorded, 405, "method_not_allowed", "This API is read-only")
			return
		}
		mux.ServeHTTP(recorded, r.WithContext(ctx))
	})
}
func write(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
func problem(w http.ResponseWriter, status int, code, message string) {
	write(w, status, map[string]any{"error": apiError{Code: code, Message: message}})
}
func (s *Server) fail(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, repository.ErrNotFound):
		problem(w, 404, "company_not_found", "No imported filings exist for this ticker")
	case errors.Is(err, service.ErrSegmentNotFound):
		problem(w, 404, "segment_not_found", "This fact has no comparable segment series")
	case errors.Is(err, repository.ErrTooManyRecords):
		problem(w, 422, "dataset_too_large", "The dataset exceeds the supported analysis size")
	case errors.Is(err, repository.ErrReaderRole):
		problem(w, 503, "reader_role_not_scoped", "The financial service requires read access on SECIngestion only")
	default:
		s.Log.Error("database request failed", "timeout", errors.Is(err, context.DeadlineExceeded))
		problem(w, 503, "database_unavailable", "Data is temporarily unavailable. Please retry.")
	}
}
func symbol(w http.ResponseWriter, r *http.Request) (string, bool) {
	value := strings.ToUpper(r.PathValue("symbol"))
	if !symbolPattern.MatchString(value) {
		problem(w, 400, "invalid_symbol", "Invalid ticker symbol")
		return "", false
	}
	return value, true
}
func filters(w http.ResponseWriter, r *http.Request) (string, int, bool) {
	mode := strings.ToLower(r.URL.Query().Get("period"))
	if mode == "" {
		mode = "all"
	}
	switch mode {
	case "all", "annual", "quarter", "ytd":
	default:
		problem(w, 400, "invalid_period", "Choose annual, quarter, ytd, or all")
		return "", 0, false
	}
	n := 20
	if raw := r.URL.Query().Get("limit"); raw != "" {
		var err error
		n, err = strconv.Atoi(raw)
		if err != nil || n < 1 || n > 200 {
			problem(w, 400, "invalid_limit", "Limit must be between 1 and 200")
			return "", 0, false
		}
	}
	return mode, n, true
}
func exportFormat(w http.ResponseWriter, r *http.Request) (bool, bool) {
	switch r.URL.Query().Get("format") {
	case "", "json":
		return false, true
	case "csv":
		return true, true
	default:
		problem(w, 400, "invalid_format", "Choose json or csv")
		return false, false
	}
}
func (s *Server) statements(w http.ResponseWriter, r *http.Request) {
	v, ok := symbol(w, r)
	if !ok {
		return
	}
	kind := r.PathValue("type")
	if !service.ValidStatement(kind) {
		problem(w, 400, "invalid_statement_type", "Type must be income, balance, or cash-flow")
		return
	}
	mode, n, ok := filters(w, r)
	if !ok {
		return
	}
	export, ok := exportFormat(w, r)
	if !ok {
		return
	}
	table, err := s.Service.Statements(r.Context(), v, kind, mode, n)
	if err != nil {
		s.fail(w, err)
		return
	}
	if !export {
		write(w, 200, response{Data: table})
		return
	}
	out := newCSV(w, v+"-"+kind)
	for _, row := range table.Rows {
		for _, field := range table.Fields {
			writeCell(out, field.Label, row.Period, row.Values[field.Key])
		}
	}
	out.Flush()
}
func (s *Server) metrics(w http.ResponseWriter, r *http.Request) {
	v, ok := symbol(w, r)
	if !ok {
		return
	}
	mode, n, ok := filters(w, r)
	if !ok {
		return
	}
	table, err := s.Service.Metrics(r.Context(), v, mode, n)
	if err != nil {
		s.fail(w, err)
		return
	}
	write(w, 200, response{Data: table})
}
func (s *Server) related(w http.ResponseWriter, r *http.Request) {
	v, ok := symbol(w, r)
	if !ok {
		return
	}
	issuer, err := s.Service.Repo.Issuer(r.Context(), v)
	if err != nil {
		s.fail(w, err)
		return
	}
	rows, err := s.Service.Repo.Related(r.Context(), issuer)
	if err != nil {
		s.fail(w, err)
		return
	}
	write(w, 200, response{Data: rows})
}
func (s *Server) segment(w http.ResponseWriter, r *http.Request) {
	v, ok := symbol(w, r)
	if !ok {
		return
	}
	accession := r.URL.Query().Get("accession")
	factID := r.URL.Query().Get("fact")
	if !accessionPattern.MatchString(accession) || !factIDPattern.MatchString(factID) {
		problem(w, 400, "invalid_fact", "Select an accession and a published fact")
		return
	}
	export, ok := exportFormat(w, r)
	if !ok {
		return
	}
	series, err := s.Service.Segment(r.Context(), v, accession, factID)
	if err != nil {
		s.fail(w, err)
		return
	}
	if !export {
		write(w, 200, response{Data: series})
		return
	}
	dimensions, _ := json.Marshal(series.Dimensions)
	out := newCSV(w, v+"-segment")
	for _, point := range series.Points {
		writeCell(out, series.Label+" "+string(dimensions), point.Period, point.Cell)
	}
	out.Flush()
}

func newCSV(w http.ResponseWriter, name string) *csv.Writer {
	w.Header().Set("Content-Type", "text/csv; charset=utf-8")
	w.Header().Set("Content-Disposition", `attachment; filename="`+name+`.csv"`)
	out := csv.NewWriter(w)
	_ = out.Write([]string{"field", "period", "start", "end", "fiscal_year", "fiscal_period", "value", "unit", "issue", "accession", "source_url", "concept", "reported_value", "raw_value"})
	return out
}
func csvText(value string) string {
	trimmed := strings.TrimLeftFunc(value, unicode.IsSpace)
	if strings.HasPrefix(value, "\t") || strings.HasPrefix(value, "\r") || strings.HasPrefix(value, "\n") || (trimmed != "" && strings.ContainsRune("=+-@", rune(trimmed[0]))) {
		return "'" + value
	}
	return value
}
func writeCell(out *csv.Writer, label string, p domain.Period, cell domain.Cell) {
	sources := cell.Sources
	if len(sources) == 0 {
		sources = []domain.Source{{}}
	}
	for _, source := range sources {
		record := []string{csvText(label), p.Mode, p.Start, p.End, p.FiscalYear, p.FiscalPeriod, "", csvText(cell.Unit), cell.Issue, csvText(source.Accession), csvText(source.URL), csvText(source.Concept), "", csvText(source.RawValue)}
		if cell.Value != nil {
			record[6] = *cell.Value
		}
		if source.ReportedValue != nil {
			if csvNumber.MatchString(*source.ReportedValue) {
				record[12] = *source.ReportedValue
			} else {
				record[12] = csvText(*source.ReportedValue)
			}
		}
		_ = out.Write(record)
	}
}
