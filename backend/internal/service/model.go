package service

import (
	"errors"
	"math/big"
)

// All input drivers are percentage points. Working capital is a balance as a percentage of sales.
type Drivers struct {
	Growth string `json:"growth"`
	Margin string `json:"margin"`
	Tax    string `json:"tax"`
	DA     string `json:"da"`
	Capex  string `json:"capex"`
	WC     string `json:"wc"`
}
type Scenario struct {
	Years          []Drivers `json:"years"`
	OpeningWC      string    `json:"openingWC"`
	WACC           string    `json:"wacc"`
	TerminalGrowth string    `json:"terminalGrowth"`
}
type Model struct {
	Revenue   string              `json:"revenue"`
	Scenarios map[string]Scenario `json:"scenarios"`
}
type Forecast struct {
	Years      []map[string]*string `json:"years"`
	PV         *string              `json:"pv"`
	TerminalPV *string              `json:"terminalPV"`
	EV         *string              `json:"ev"`
	Grid       [][]*string          `json:"grid"`
	Issue      string               `json:"issue"`
}

const ModelVersion = "fcff-1"

func one() *big.Rat { return big.NewRat(1, 1) }
func percent(v string) *big.Rat {
	if len(v) > 16 {
		return nil
	}
	n := asDecimal(&v)
	if n == nil {
		return nil
	}
	return n.Quo(n, big.NewRat(100, 1))
}
func sum(a, b *big.Rat) *big.Rat {
	if a == nil || b == nil {
		return nil
	}
	return new(big.Rat).Add(a, b)
}
func sub(a, b *big.Rat) *big.Rat {
	if a == nil || b == nil {
		return nil
	}
	return new(big.Rat).Sub(a, b)
}
func mul(a, b *big.Rat) *big.Rat {
	if a == nil || b == nil {
		return nil
	}
	return new(big.Rat).Mul(a, b)
}
func div(a, b *big.Rat) *big.Rat {
	if a == nil || b == nil || b.Sign() == 0 {
		return nil
	}
	return new(big.Rat).Quo(a, b)
}
func amount(a *big.Rat) *string {
	if a == nil {
		return nil
	}
	v := a.FloatString(4)
	return &v
}
func valuation(flows []*big.Rat, w, g *big.Rat) (pv, tv, ev *big.Rat) {
	if w == nil || w.Sign() <= 0 {
		return
	}
	factor := one()
	pv = new(big.Rat)
	for _, cf := range flows {
		factor = mul(factor, sum(one(), w))
		pv = sum(pv, div(cf, factor))
	}
	if g == nil || g.Cmp(big.NewRat(-1, 1)) <= 0 || w.Cmp(g) <= 0 {
		return
	}
	terminal := mul(flows[len(flows)-1], sum(one(), g))
	if terminal == nil || terminal.Sign() <= 0 {
		return
	}
	tv = div(div(terminal, sub(w, g)), factor)
	ev = sum(pv, tv)
	return
}
func Evaluate(model Model) (map[string]Forecast, error) {
	base := asDecimal(&model.Revenue)
	if base == nil || base.Sign() <= 0 || len(model.Scenarios) != 3 {
		return nil, errors.New("Select a positive annual revenue baseline and provide three scenarios")
	}
	out := map[string]Forecast{}
	for _, name := range []string{"bear", "base", "bull"} {
		s := model.Scenarios[name]
		if len(s.Years) != 5 {
			return nil, errors.New("Each scenario requires five annual forecasts")
		}
		rev := base
		wc := mul(base, percent(s.OpeningWC))
		flows := []*big.Rat{}
		f := Forecast{}
		for _, value := range []string{s.OpeningWC, s.WACC, s.TerminalGrowth} {
			if value != "" && percent(value) == nil {
				return nil, errors.New("Use decimal percentages for the opening balance and discount assumptions")
			}
		}
		for _, d := range s.Years {
			for _, value := range []string{d.Growth, d.Margin, d.Tax, d.DA, d.Capex, d.WC} {
				if value != "" && percent(value) == nil {
					return nil, errors.New("Use decimal percentages for annual drivers")
				}
			}
			if growth := percent(d.Growth); growth != nil && growth.Cmp(big.NewRat(-1, 1)) < 0 {
				return nil, errors.New("Revenue growth must be at least -100%")
			}
			for _, value := range []string{d.Capex, d.DA} {
				if v := percent(value); v != nil && v.Sign() < 0 {
					return nil, errors.New("Enter capex and depreciation as positive magnitudes or zero")
				}
			}

			rev = mul(rev, sum(one(), percent(d.Growth)))
			op := mul(rev, percent(d.Margin))
			tax := mul(op, percent(d.Tax))
			da := mul(rev, percent(d.DA))
			capex := mul(rev, percent(d.Capex))
			balance := mul(rev, percent(d.WC))
			delta := sub(balance, wc)
			wc = balance
			cf := sub(sub(sum(sub(op, tax), da), capex), delta)
			flows = append(flows, cf)
			f.Years = append(f.Years, map[string]*string{"revenue": amount(rev), "operatingIncome": amount(op), "tax": amount(tax), "da": amount(da), "capex": amount(capex), "workingCapital": amount(balance), "changeWC": amount(delta), "fcff": amount(cf)})
		}
		w, g := percent(s.WACC), percent(s.TerminalGrowth)
		pv, tv, ev := valuation(flows, w, g)
		f.PV, f.TerminalPV, f.EV = amount(pv), amount(tv), amount(ev)
		if ev == nil {
			f.Issue = "Complete the drivers and use positive WACC above terminal growth with positive terminal cash flow."
		}
		for i := -2; i <= 2; i++ {
			row := []*string{}
			for j := -2; j <= 2; j++ {
				_, _, v := valuation(flows, sum(w, big.NewRat(int64(i), 100)), sum(g, big.NewRat(int64(j), 200)))
				row = append(row, amount(v))
			}
			f.Grid = append(f.Grid, row)
		}
		out[name] = f
	}
	return out, nil
}
