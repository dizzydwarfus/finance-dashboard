package service

import (
	"math"
	"testing"

	"finance-dashboard/backend/internal/domain"
)

func pointer(value string) *string { return &value }

func TestExactDecimalAndUnavailableDerivedValues(t *testing.T) {
	a := domain.Cell{Value: pointer("9007199254740993.25"), Unit: "USD"}
	b := domain.Cell{Value: pointer("1.05"), Unit: "USD"}
	if c := calculate(a, b, false); c.Value == nil || *c.Value != "9007199254740992.20" {
		t.Fatalf("incorrect exact cash flow: %+v", c)
	}
	b.Unit = "EUR"
	if c := calculate(a, b, false); c.Value != nil || c.Issue != "conflicting_units" {
		t.Fatalf("mixed currencies: %+v", c)
	}
	b.Unit = "USD"
	b.Value = pointer("0")
	if c := calculate(a, b, true); c.Value != nil || c.Issue != "zero_denominator" {
		t.Fatalf("zero should be unavailable: %+v", c)
	}
}

func TestGrowthNeedsComparableDurationsAndUnits(t *testing.T) {
	current := domain.Period{Mode: "quarter", Start: "2026-03-29", End: "2026-06-27"}
	prior := domain.Period{Mode: "quarter", Start: "2025-03-30", End: "2025-06-28"}
	for _, test := range []struct {
		mode, unit, value string
		match             bool
	}{
		{"quarter", "USD", "100", true}, {"quarter", "USD", "0", false}, {"ytd", "USD", "100", false}, {"quarter", "EUR", "100", false},
	} {
		old := prior
		old.Mode = test.mode
		rows := []domain.Row{
			{Period: current, Values: map[string]domain.Cell{"revenue": {Unit: "USD", Value: pointer("125")}}},
			{Period: old, Values: map[string]domain.Cell{"revenue": {Unit: test.unit, Value: pointer(test.value)}}},
		}
		growth(rows)
		value := rows[0].Growth["revenue"]
		if test.match && (value == nil || math.Abs(*value-.25) > .000001) || !test.match && value != nil {
			t.Fatalf("%+v produced %v", test, value)
		}
	}
}
