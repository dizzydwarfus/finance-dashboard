package service

import (
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"

	"go.mongodb.org/mongo-driver/v2/bson"
)

func text(v any) string {
	if v == nil {
		return ""
	}
	return fmt.Sprint(v)
}

// Number accepts legacy provider strings and BSON numeric types, rejecting NaN/Inf.
func Number(v any) *float64 {
	var n float64
	switch x := v.(type) {
	case float64:
		n = x
	case float32:
		n = float64(x)
	case int:
		n = float64(x)
	case int32:
		n = float64(x)
	case int64:
		n = float64(x)
	case bson.Decimal128:
		return Number(x.String())
	case string:
		parsed, err := strconv.ParseFloat(strings.TrimSpace(x), 64)
		if err != nil {
			return nil
		}
		n = parsed
	default:
		return nil
	}
	if math.IsNaN(n) || math.IsInf(n, 0) {
		return nil
	}
	return &n
}

func timestamp(v any) time.Time {
	switch x := v.(type) {
	case time.Time:
		return x.UTC()
	case bson.DateTime:
		return x.Time().UTC()
	case string:
		for _, layout := range []string{time.RFC3339Nano, "2006-01-02 15:04:05", "2006-01-02", "2006"} {
			if t, err := time.Parse(layout, x); err == nil {
				return t.UTC()
			}
		}
	}
	return time.Time{}
}
func date(v any) string {
	t := timestamp(v)
	if t.IsZero() {
		return ""
	}
	return t.Format("2006-01-02")
}
func updated(row bson.M) time.Time {
	for _, key := range []string{"lastUpdate", "lastUpdated", "acceptedDate", "date"} {
		if t := timestamp(row[key]); !t.IsZero() {
			return t
		}
	}
	return time.Time{}
}
func ordered(rows []bson.M) []bson.M {
	rows = append([]bson.M(nil), rows...)
	sort.SliceStable(rows, func(i, j int) bool {
		a, b := updated(rows[i]), updated(rows[j])
		if !a.Equal(b) {
			return a.After(b)
		}
		return text(rows[i]["_id"]) > text(rows[j]["_id"])
	})
	return rows
}
