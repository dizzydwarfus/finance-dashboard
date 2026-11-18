package service

import (
	"math"
	"strconv"
	"testing"
)

func TestFiveYearScenarioDCF(t *testing.T) {
	// Constant sales 100, EBIT 20, tax 5, D&A 2, capex 4 and unchanged NWC.
	// At zero perpetual growth the entire stream is a 13 per year perpetuity.
	m := Model{Revenue: "100", Scenarios: map[string]Scenario{}}
	for _, n := range []string{"bear", "base", "bull"} {
		s := Scenario{OpeningWC: "10", WACC: "10", TerminalGrowth: "0"}
		for range 5 {
			s.Years = append(s.Years, Drivers{"0", "20", "25", "2", "4", "10"})
		}
		m.Scenarios[n] = s
	}
	out, err := Evaluate(m)
	if err != nil {
		t.Fatal(err)
	}
	for _, f := range out {
		if *f.EV != "130.0000" || *f.PV != "49.2802" || *f.Grid[2][2] != *f.EV || len(f.Grid) != 5 || *f.Years[4]["fcff"] != "13.0000" {
			t.Fatal(f)
		}
	}
	// Independent double-precision annuity and Gordon growth reference for every grid cell.
	for i, row := range out["base"].Grid {
		w := 0.08 + float64(i)*0.01
		for j, cell := range row {
			g := -0.01 + float64(j)*0.005
			discount := math.Pow(1+w, -5)
			want := 13*(1-discount)/w + 13*(1+g)/(w-g)*discount
			actual, err := strconv.ParseFloat(*cell, 64)
			if err != nil || math.Abs(want-actual) > .000051 {
				t.Fatal(i, j, want, actual)
			}
		}
	}

	s := m.Scenarios["bear"]
	s.Years[2].DA = ""
	m.Scenarios["bear"] = s
	s = m.Scenarios["bull"]
	s.TerminalGrowth = s.WACC
	m.Scenarios["bull"] = s
	out, err = Evaluate(m)
	if err != nil || out["bear"].EV != nil || out["bear"].Years[2]["da"] != nil || out["bull"].EV != nil || out["bull"].PV == nil || out["base"].EV == nil {
		t.Fatal(out, err)
	}
}
