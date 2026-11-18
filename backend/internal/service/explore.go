package service

import (
	"context"
	"crypto/sha256"
	"fmt"
	"regexp"
	"slices"
	"sort"
	"strings"

	"finance-dashboard/backend/internal/domain"
	"go.mongodb.org/mongo-driver/v2/bson"
)

type Slice struct {
	ID      string             `json:"id"`
	Concept string             `json:"concept"`
	Label   string             `json:"label"`
	Axis    string             `json:"axis"`
	Fixed   []domain.Dimension `json:"fixed"`
	Unit    string             `json:"unit"`
	Mode    string             `json:"mode"`
}
type Pivot struct {
	Periods []domain.Period `json:"periods"`
	Members []Member        `json:"members"`
}
type Member struct {
	Name  string        `json:"name"`
	Cells []domain.Cell `json:"cells"`
}

func (s *Service) researchObservations(ctx context.Context, symbol, through string, filter bson.M) ([]observation, error) {
	issuer, err := s.Repo.Issuer(ctx, symbol)
	if err != nil {
		return nil, err
	}
	filings, err := s.Repo.FilingWindow(ctx, issuer.CIK, through, false, 12)
	if err != nil {
		return nil, err
	}
	return s.observations(ctx, issuer, filings, filter)
}

func sliceFor(o observation, index int, p domain.Period) Slice {
	dims := o.context.Dimensions
	fixed := append([]domain.Dimension{}, dims[:index]...)
	fixed = append(fixed, dims[index+1:]...)
	unit := unitName(o.unit)
	mode := p.Mode
	if mode == "ytd" {
		if duration(p) < 220 {
			mode = "ytd-6m"
		} else {
			mode = "ytd-9m"
		}
	}
	id := fmt.Sprintf("%x", sha256.Sum256([]byte(strings.Join([]string{o.fact.Concept, dims[index].Axis, dimensionKey(fixed), unit, mode}, "\x00"))))
	return Slice{id, o.fact.Concept, o.fact.Label, dims[index].Axis, fixed, unit, mode}
}
func (s *Service) Dimensions(ctx context.Context, symbol, q, through string) ([]Slice, error) {
	filter := bson.M{"dimensions.0": bson.M{"$exists": true}}
	if q != "" {
		pattern := bson.M{"$regex": regexp.QuoteMeta(q), "$options": "i"}
		filter["$or"] = bson.A{bson.M{"concept": pattern}, bson.M{"label": pattern}}
	}
	obs, err := s.researchObservations(ctx, symbol, through, filter)
	if err != nil {
		return nil, err
	}
	seen := map[string]Slice{}
	for _, o := range obs {
		p, ok := fiscalPeriod(o)
		if !ok {
			continue
		}
		for i := range o.context.Dimensions {
			v := sliceFor(o, i, p)
			seen[v.ID] = v
		}
	}
	out := make([]Slice, 0, len(seen))
	for _, v := range seen {
		out = append(out, v)
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Label != out[j].Label {
			return out[i].Label < out[j].Label
		}
		return out[i].ID < out[j].ID
	})
	return out[:min(200, len(out))], nil
}

func (s *Service) Pivot(ctx context.Context, symbol, concept, id, display, through string, members []string) (Pivot, error) {
	obs, err := s.researchObservations(ctx, symbol, through, bson.M{"concept": concept})
	if err != nil {
		return Pivot{}, err
	}
	return pivotValues(obs, id, display, members)
}
func pivotValues(obs []observation, id, display string, members []string) (Pivot, error) {
	buckets := map[string]map[domain.Period][]observation{}
	totals := map[domain.Period][]observation{}
	periods := map[domain.Period]bool{}
	var selected Slice
	for _, o := range obs {
		p, ok := fiscalPeriod(o)
		if !ok {
			continue
		}
		for i, d := range o.context.Dimensions {
			v := sliceFor(o, i, p)
			if v.ID != id {
				continue
			}
			selected = v
			periods[p] = true
			name := ""
			if d.Member != nil {
				name = *d.Member
			} else if d.TypedValue != nil {
				name = *d.TypedValue
			}
			if len(members) > 0 && !slices.Contains(members, name) {
				continue
			}
			if buckets[name] == nil {
				buckets[name] = map[domain.Period][]observation{}
			}
			o.comparableUnit = v.Unit
			buckets[name][p] = append(buckets[name][p], o)
		}
	}
	if selected.ID == "" {
		return Pivot{}, ErrSegmentNotFound
	}
	// A subtotal must match all the fixed dimensions after removing the pivot axis.
	for _, o := range obs {
		p, ok := fiscalPeriod(o)
		if ok && periods[p] && unitName(o.unit) == selected.Unit && dimensionKey(o.context.Dimensions) == dimensionKey(selected.Fixed) {
			o.comparableUnit = selected.Unit
			totals[p] = append(totals[p], o)
		}
	}
	out := Pivot{Periods: []domain.Period{}, Members: []Member{}}
	for p := range periods {
		out.Periods = append(out.Periods, p)
	}
	sort.Slice(out.Periods, func(i, j int) bool {
		a, b := out.Periods[i], out.Periods[j]
		if a.End == b.End {
			return a.Start < b.Start
		}
		return a.End < b.End
	})
	for name, values := range buckets {
		m := Member{Name: name, Cells: []domain.Cell{}}
		for _, p := range out.Periods {
			c := choose(values[p])
			switch display {
			case "share":
				c = calculate(c, choose(totals[p]), true)
			case "growth":
				var priors []domain.Cell
				for old, group := range values {
					if priorPeriod(p, old) || (p.Mode == "instant" && comparableDate(parseDate(old.End), parseDate(p.End), 1, 10)) {
						priors = append(priors, choose(group))
					}
				}
				c = yearChange(c, priors)
			}
			m.Cells = append(m.Cells, c)
		}
		out.Members = append(out.Members, m)
	}
	sort.Slice(out.Members, func(i, j int) bool { return out.Members[i].Name < out.Members[j].Name })
	return out, nil
}
func yearChange(current domain.Cell, priors []domain.Cell) domain.Cell {
	if len(priors) != 1 {
		out := missing("missing_comparable_period")
		out.Sources = append(out.Sources, current.Sources...)
		return out
	}
	old := priors[0]
	result := calculate(current, old, true)
	if result.Value != nil {
		r := asDecimal(result.Value)
		r.Sub(r, one())
		if asDecimal(old.Value).Sign() < 0 {
			r.Neg(r)
		}
		v := r.FloatString(8)
		result.Value = &v
	}
	return result
}

type Peer struct {
	Symbol     string       `json:"symbol"`
	Rows       []domain.Row `json:"rows"`
	Misaligned bool         `json:"misaligned"`
}

func (s *Service) Compare(ctx context.Context, symbols []string, trend bool) ([]Peer, error) {
	out := []Peer{}
	anchor := ""
	for _, symbol := range symbols {
		t, err := s.Metrics(ctx, symbol, "annual", 12)
		if err != nil {
			return nil, err
		}
		rows := []domain.Row{}
		for _, r := range t.Rows {
			if r.Period.Start == "" {
				continue
			}
			var prior []domain.Cell
			for _, o := range t.Rows {
				if priorPeriod(r.Period, o.Period) {
					prior = append(prior, o.Values["revenue"])
				}
			}
			rows = append(rows, domain.Row{Period: r.Period, Values: map[string]domain.Cell{"revenue": r.Values["revenue"], "revenueGrowth": yearChange(r.Values["revenue"], prior), "operatingMargin": r.Values["operatingMargin"], "cashConversion": calculate(r.Values["operatingCashFlow"], r.Values["netIncome"], true), "capitalIntensity": calculate(r.Values["capex"], r.Values["revenue"], true)}})
			if !trend || len(rows) == 10 {
				break
			}
		}
		far := false
		if len(rows) > 0 {
			end := rows[0].Period.End
			if symbol == symbols[0] {
				anchor = end
			}
			if anchor != "" {
				far = parseDate(end).Sub(parseDate(anchor)).Abs().Hours() > 90*24
			}
		}
		out = append(out, Peer{symbol, rows, far})
	}
	return out, nil
}
