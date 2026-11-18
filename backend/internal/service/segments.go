package service

import (
	"context"
	"encoding/json"
	"regexp"
	"slices"
	"sort"
	"strings"

	"finance-dashboard/backend/internal/domain"
	"go.mongodb.org/mongo-driver/v2/bson"
)

func (s *Service) Segment(ctx context.Context, symbol, accession, factID string) (domain.SegmentSeries, error) {
	issuer, err := s.Repo.Issuer(ctx, symbol)
	if err != nil {
		return domain.SegmentSeries{}, err
	}
	filings, err := s.Repo.Filings(ctx, issuer.CIK)
	if err != nil {
		return domain.SegmentSeries{}, err
	}
	index := slices.IndexFunc(filings, func(f domain.Filing) bool { return f.Accession == accession })
	if index == -1 {
		return domain.SegmentSeries{}, ErrSegmentNotFound
	}
	selected, err := s.observations(ctx, issuer, filings[index:index+1], bson.M{"_id": factID})
	if err != nil {
		return domain.SegmentSeries{}, err
	}
	if len(selected) != 1 || len(selected[0].context.Dimensions) == 0 {
		return domain.SegmentSeries{}, ErrSegmentNotFound
	}
	anchor := selected[0]
	period, ok := fiscalPeriod(anchor)
	if !ok {
		return domain.SegmentSeries{}, ErrSegmentNotFound
	}
	measure := unitName(anchor.unit)
	dimension := dimensionKey(anchor.context.Dimensions)
	out := domain.SegmentSeries{Concept: anchor.fact.Concept, Label: anchor.fact.Label, Dimensions: anchor.context.Dimensions, Unit: measure, Points: []domain.SegmentPoint{}}
	var match any = anchor.fact.Concept
	if gaapNamespace.MatchString(anchor.fact.Concept) {
		match = bson.M{"$regex": gaapNamespace.String() + regexp.QuoteMeta(gaapNamespace.ReplaceAllString(anchor.fact.Concept, "")) + "$"}
	}
	observations, err := s.observations(ctx, issuer, filings, bson.M{"concept": match, "dimensions.0": bson.M{"$exists": true}})
	if err != nil {
		return domain.SegmentSeries{}, err
	}
	buckets := map[domain.Period][]observation{}
	for _, item := range observations {
		if unitName(item.unit) != measure || dimensionKey(item.context.Dimensions) != dimension {
			continue
		}
		p, ok := fiscalPeriod(item)
		if !ok || p.Mode != period.Mode {
			continue
		}
		// Six- and nine-month YTD data are separate by duration.
		if p.Mode == "ytd" && (duration(p) < 220) != (duration(period) < 220) {
			continue
		}
		item.comparableUnit = measure
		buckets[p] = append(buckets[p], item)
	}
	for p, items := range buckets {
		setFiscalLabel(&p, map[string][]observation{"segment": items})
		out.Points = append(out.Points, domain.SegmentPoint{Period: p, Cell: choose(items)})
	}
	sort.Slice(out.Points, func(i, j int) bool {
		a, b := out.Points[i].Period, out.Points[j].Period
		if a.End != b.End {
			return a.End < b.End
		}
		return a.Start < b.Start
	})
	return out, nil
}
func duration(p domain.Period) int {
	return int(parseDate(p.End).Sub(parseDate(p.Start)).Hours()/24) + 1
}
func unitName(u domain.Unit) string {
	num, den := slices.Clone(u.Numerator), slices.Clone(u.Denominator)
	slices.Sort(num)
	slices.Sort(den)
	value := strings.Join(num, " × ")
	if len(den) > 0 {
		value += " / " + strings.Join(den, " × ")
	}
	return value
}
func dimensionKey(dims []domain.Dimension) string {
	// Treat dimension order as irrelevant but preserve the complete axis/member identity.
	parts := make([]string, 0, len(dims))
	for _, d := range dims {
		row, _ := json.Marshal(d)
		parts = append(parts, string(row))
	}
	slices.Sort(parts)
	return strings.Join(parts, "\n")
}
