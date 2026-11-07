package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"

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

var symbolPattern = regexp.MustCompile(`^[A-Z0-9][A-Z0-9.^-]{0,19}$`)

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		write(w, 200, response{Data: map[string]string{"status": "ok"}})
	})
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		if err := s.Service.Repo.Ping(r.Context()); err != nil {
			s.fail(w, r, err)
			return
		}
		write(w, 200, response{Data: map[string]string{"status": "ready"}})
	})
	mux.HandleFunc("GET /api/v1/tickers", s.tickers)
	mux.HandleFunc("GET /api/v1/companies/{symbol}", s.company)
	mux.HandleFunc("GET /api/v1/companies/{symbol}/statements/{type}", s.statements)
	mux.HandleFunc("GET /api/v1/companies/{symbol}/metrics", s.metrics)
	mux.HandleFunc("GET /api/v1/companies/{symbol}/prices", s.prices)
	mux.HandleFunc("GET /api/v1/companies/{symbol}/splits", s.splits)
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) { problem(w, 404, "not_found", "Endpoint not found") })
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		recorded := &statusWriter{ResponseWriter: w}
		w = recorded
		timeout := s.Timeout
		if timeout == 0 {
			timeout = 8 * time.Second
		}
		ctx, cancel := context.WithTimeout(r.Context(), timeout)
		defer cancel()
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		defer func() {
			if recover() != nil {
				s.Log.Error("request panic")
				problem(w, 500, "internal_error", "Unexpected server error")
			}
			s.Log.Info("request", "method", r.Method, "path", r.URL.Path, "status", recorded.status, "duration_ms", time.Since(start).Milliseconds())
		}()
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			w.Header().Set("Allow", "GET, HEAD")
			problem(w, http.StatusMethodNotAllowed, "method_not_allowed", "This API is read-only")
			return
		}
		mux.ServeHTTP(w, r.WithContext(ctx))
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
func (s *Server) fail(w http.ResponseWriter, r *http.Request, err error) {
	if errors.Is(err, service.ErrNotFound) {
		problem(w, 404, "company_not_found", "Company not found")
		return
	}
	if errors.Is(err, repository.ErrTooManyRecords) {
		problem(w, 422, "dataset_too_large", "Company dataset exceeds the supported read bound")
		return
	}
	// Never emit driver errors: they may contain credentials or private host names.
	s.Log.Error("database request failed", "timeout", errors.Is(err, context.DeadlineExceeded))
	problem(w, 503, "database_unavailable", "Data is temporarily unavailable; please retry")
}
func symbol(w http.ResponseWriter, r *http.Request) (string, bool) {
	v := strings.ToUpper(r.PathValue("symbol"))
	if !symbolPattern.MatchString(v) {
		problem(w, 400, "invalid_symbol", "Invalid ticker symbol")
		return "", false
	}
	return v, true
}
func limit(w http.ResponseWriter, r *http.Request, defaultValue, max int) (int, bool) {
	v := r.URL.Query().Get("limit")
	if v == "" {
		return defaultValue, true
	}
	n, err := strconv.Atoi(v)
	if err != nil || n < 1 || n > max {
		problem(w, 400, "invalid_limit", "Limit is outside the supported range")
		return 0, false
	}
	return n, true
}
func period(w http.ResponseWriter, r *http.Request) (string, bool) {
	v := strings.ToUpper(r.URL.Query().Get("period"))
	switch v {
	case "", "FY", "Q1", "Q2", "Q3", "Q4":
		return v, true
	default:
		problem(w, 400, "invalid_period", "Period must be FY, Q1, Q2, Q3, or Q4")
		return "", false
	}
}
func (s *Server) known(w http.ResponseWriter, r *http.Request, symbol string) bool {
	if err := s.Service.Exists(r.Context(), symbol); err != nil {
		s.fail(w, r, err)
		return false
	}
	return true
}
func (s *Server) tickers(w http.ResponseWriter, r *http.Request) {
	n, ok := limit(w, r, 100, 2000)
	if !ok {
		return
	}
	q := strings.ToUpper(strings.TrimSpace(r.URL.Query().Get("q")))
	if len(q) > 50 {
		problem(w, 400, "invalid_query", "Search is limited to 50 characters")
		return
	}
	rows, err := s.Service.Repo.Tickers(r.Context())
	if err != nil {
		s.fail(w, r, err)
		return
	}
	out := []domain.Ticker{}
	for _, row := range rows {
		if strings.Contains(row.Symbol, q) {
			out = append(out, row)
			if len(out) == n {
				break
			}
		}
	}
	write(w, 200, response{Data: out})
}
func (s *Server) company(w http.ResponseWriter, r *http.Request) {
	v, ok := symbol(w, r)
	if !ok {
		return
	}
	c, err := s.Service.Company(r.Context(), v)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	write(w, 200, response{Data: c})
}
func (s *Server) statements(w http.ResponseWriter, r *http.Request) {
	v, ok := symbol(w, r)
	if !ok {
		return
	}
	kind := r.PathValue("type")
	if _, ok := service.StatementCollections[kind]; !ok {
		problem(w, 400, "invalid_statement_type", "Type must be income, balance, or cash-flow")
		return
	}
	n, ok := limit(w, r, 10, 200)
	if !ok {
		return
	}
	p, ok := period(w, r)
	if !ok {
		return
	}
	rows, err := s.Service.Statements(r.Context(), v, kind)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	if len(rows) == 0 && !s.known(w, r, v) {
		return
	}
	out := []domain.Statement{}
	for _, row := range rows {
		if p == "" || row.Period == p {
			out = append(out, row)
			if len(out) == n {
				break
			}
		}
	}
	write(w, 200, response{Data: out})
}
func (s *Server) metrics(w http.ResponseWriter, r *http.Request) {
	v, ok := symbol(w, r)
	if !ok {
		return
	}
	n, ok := limit(w, r, 20, 200)
	if !ok {
		return
	}
	p, ok := period(w, r)
	if !ok {
		return
	}
	result, err := s.Service.Metrics(r.Context(), v)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	if len(result.Points) == 0 && !s.known(w, r, v) {
		return
	}
	points := []domain.MetricPoint{}
	for _, row := range result.Points {
		if p == "" || row.Period == p {
			points = append(points, row)
		}
	}
	if len(points) > n {
		points = points[len(points)-n:]
	}
	result.Points = points
	write(w, 200, response{Data: result})
}
func (s *Server) prices(w http.ResponseWriter, r *http.Request) {
	v, ok := symbol(w, r)
	if !ok {
		return
	}
	n, ok := limit(w, r, 365, 5000)
	if !ok {
		return
	}
	q := r.URL.Query()
	from, to := q.Get("from"), q.Get("to")
	for _, d := range []string{from, to} {
		if d != "" {
			if _, err := time.Parse("2006-01-02", d); err != nil {
				problem(w, 400, "invalid_date", "Dates must use YYYY-MM-DD")
				return
			}
		}
	}
	if from != "" && to != "" && from > to {
		problem(w, 400, "invalid_date_range", "From must be on or before to")
		return
	}
	rows, err := s.Service.Prices(r.Context(), v, from, to)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	if len(rows) == 0 && !s.known(w, r, v) {
		return
	}
	if len(rows) > n {
		rows = rows[len(rows)-n:]
	}
	write(w, 200, response{Data: rows})
}
func (s *Server) splits(w http.ResponseWriter, r *http.Request) {
	v, ok := symbol(w, r)
	if !ok {
		return
	}
	n, ok := limit(w, r, 200, 1000)
	if !ok {
		return
	}
	rows, err := s.Service.Splits(r.Context(), v)
	if err != nil {
		s.fail(w, r, err)
		return
	}
	if len(rows) == 0 && !s.known(w, r, v) {
		return
	}
	if len(rows) > n {
		rows = rows[len(rows)-n:]
	}
	write(w, 200, response{Data: rows})
}
