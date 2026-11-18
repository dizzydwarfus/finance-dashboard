package service

import (
	"testing"

	"finance-dashboard/backend/internal/domain"
)

func TestPivotUsesExactContextAndAmendment(t *testing.T) {
	europe := domain.Dimension{Axis: "Geography", Member: pointer("Europe")}
	product := domain.Dimension{Axis: "Product", Member: pointer("Phone")}
	member := observation{filing: domain.Filing{Accession: "original", Generation: "g1", Form: "10-K", Filed: "2026-02-01", ReportDate: "2025-12-31", SourceURL: "https://www.sec.gov/example"},
		context: domain.Context{StartDate: "2025-01-01", EndDate: "2025-12-31", Dimensions: []domain.Dimension{europe, product}},
		fact:    domain.Fact{Concept: "Revenue", Value: pointer("25")}, unit: domain.Unit{Numerator: []string{"USD"}}}
	amended := member
	amended.filing.Accession = "amendment"
	amended.filing.Form = "10-K/A"
	amended.filing.Filed = "2026-02-12"
	amended.fact.Value = pointer("30")
	subtotal := member
	subtotal.context.Dimensions = []domain.Dimension{product}
	subtotal.fact.Value = pointer("100")
	consolidated := subtotal
	consolidated.context.Dimensions = nil
	consolidated.fact.Value = pointer("500")
	foreign := member
	foreign.unit.Numerator = []string{"EUR"}
	foreign.fact.Value = pointer("900")
	prior := member
	prior.context.StartDate = "2024-01-01"
	prior.context.EndDate = "2024-12-31"
	prior.fact.Value = pointer("20")
	all := []observation{consolidated, member, amended, subtotal, foreign, prior}
	p, _ := fiscalPeriod(member)
	id := sliceFor(member, 0, p).ID
	for display, want := range map[string]string{"value": "30", "share": "0.30000000", "growth": "0.50000000"} {
		got, err := pivotValues(all, id, display, nil)
		if err != nil || len(got.Members) != 1 || len(got.Periods) != 2 {
			t.Fatal(got, err)
		}
		c := got.Members[0].Cells[1]
		if c.Value == nil || *c.Value != want || c.Sources[0].Accession != "amendment" {
			t.Fatal(display, c)
		}
		if display == "share" && got.Members[0].Cells[0].Value != nil {
			t.Fatal("missing subtotal inferred")
		}
	}
	conflict := amended
	conflict.fact.Value = pointer("31")
	got, _ := pivotValues(append(all, conflict), id, "value", nil)
	c := got.Members[0].Cells[1]
	if c.Value != nil || c.Issue != "conflicting_values" {
		t.Fatal(c)
	}
}
