package service

import (
	"context"
	"errors"
	"math"
	"math/big"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"finance-dashboard/backend/internal/domain"
	"finance-dashboard/backend/internal/repository"
	"go.mongodb.org/mongo-driver/v2/bson"
)

var ErrSegmentNotFound = errors.New("selected segment fact is unavailable")

type Service struct{ Repo repository.Reader }

type mapping struct {
	domain.Field
	tags []string
}

var statementFields = map[string][]mapping{
	"income": {
		{domain.Field{Key: "revenue", Label: "Revenue", Format: "money"}, []string{"RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"}},
		{domain.Field{Key: "operatingIncome", Label: "Operating income", Format: "money"}, []string{"OperatingIncomeLoss"}},
		{domain.Field{Key: "netIncome", Label: "Net income attributable to parent", Format: "money"}, []string{"NetIncomeLoss"}},
		{domain.Field{Key: "eps", Label: "Diluted EPS", Format: "eps"}, []string{"EarningsPerShareDiluted"}},
	},
	"balance": {
		{domain.Field{Key: "assets", Label: "Assets", Format: "money"}, []string{"Assets"}},
		{domain.Field{Key: "liabilities", Label: "Liabilities", Format: "money"}, []string{"Liabilities"}},
		{domain.Field{Key: "equity", Label: "Equity attributable to parent", Format: "money"}, []string{"StockholdersEquity"}},
	},
	"cash-flow": {
		{domain.Field{Key: "operatingCashFlow", Label: "Operating cash flow", Format: "money"}, []string{"NetCashProvidedByUsedInOperatingActivities"}},
		{domain.Field{Key: "capex", Label: "Capital expenditure (outflow)", Format: "money"}, []string{"PaymentsToAcquirePropertyPlantAndEquipment"}},
		{freeCashFlow, nil},
	},
}
var freeCashFlow = domain.Field{Key: "freeCashFlow", Label: "Free cash flow", Format: "money"}
var operatingMargin = domain.Field{Key: "operatingMargin", Label: "Operating margin", Format: "ratio"}
var netMargin = domain.Field{Key: "netMargin", Label: "Net margin", Format: "ratio"}
var gaapNamespace = regexp.MustCompile(`^\{https?://(?:fasb\.org|xbrl\.us)/us-gaap/[^}]+\}`)
var currencyMeasure = regexp.MustCompile(`^\{http://www.xbrl.org/2003/iso4217\}([A-Z]{3})$`)
var decimalPattern = regexp.MustCompile(`^-?[0-9]+(?:\.[0-9]+)?$`)

func ValidStatement(kind string) bool { return len(statementFields[kind]) != 0 }

func (s *Service) Statements(ctx context.Context, symbol, kind, mode string, limit int) (domain.Table, error) {
	return s.table(ctx, symbol, kind, mode, limit)
}
func (s *Service) Metrics(ctx context.Context, symbol, mode string, limit int) (domain.Table, error) {
	return s.table(ctx, symbol, "metrics", mode, limit)
}

func (s *Service) table(ctx context.Context, symbol, kind, mode string, limit int) (domain.Table, error) {
	issuer, err := s.Repo.Issuer(ctx, symbol)
	if err != nil {
		return domain.Table{}, err
	}
	filings, err := s.Repo.Filings(ctx, issuer.CIK)
	if err != nil {
		return domain.Table{}, err
	}
	var fields []mapping
	if kind == "metrics" {
		for _, name := range []string{"income", "balance", "cash-flow"} {
			fields = append(fields, statementFields[name]...)
		}
		fields = append(fields, mapping{operatingMargin, nil}, mapping{netMargin, nil})
	} else {
		fields = statementFields[kind]
	}
	out := domain.Table{Fields: []domain.Field{}, Rows: []domain.Row{}}
	var names []string
	tagFields := map[string]mapping{}
	priorities := map[string]int{}
	for _, field := range fields {
		out.Fields = append(out.Fields, field.Field)
		for index, tag := range field.tags {
			names = append(names, regexp.QuoteMeta(tag))
			tagFields[tag] = field
			priorities[tag] = index
		}
	}
	filter := bson.M{"concept": bson.M{"$regex": gaapNamespace.String() + "(?:" + strings.Join(names, "|") + ")$"}, "dimensions": bson.A{}}
	observations, err := s.observations(ctx, issuer, filings, filter)
	if err != nil {
		return domain.Table{}, err
	}

	// Assemble duration rows first and attach matching balance sheet instants by end date.
	buckets := map[domain.Period]map[string][]observation{}
	instant := map[string]map[string][]observation{}
	for _, item := range observations {
		if len(item.context.Dimensions) != 0 {
			continue
		}
		tag := gaapNamespace.ReplaceAllString(item.fact.Concept, "")
		field, ok := tagFields[tag]
		if !ok {
			continue
		}
		unit := financialUnit(item.unit, field.Format)
		if unit == "" {
			continue
		}
		item.comparableUnit = unit
		item.priority = priorities[tag]
		p, ok := fiscalPeriod(item)
		if !ok {
			continue
		}
		if isBalance(field.Key) {
			if p.Mode != "instant" {
				continue
			}
			if instant[p.End] == nil {
				instant[p.End] = map[string][]observation{}
			}
			instant[p.End][field.Key] = append(instant[p.End][field.Key], item)
		} else {
			if p.Mode == "instant" {
				continue
			}
			// Fiscal labels are optional metadata, not part of period identity.
			key := periodIdentity(p)
			if buckets[key] == nil {
				buckets[key] = map[string][]observation{}
			}
			buckets[key][field.Key] = append(buckets[key][field.Key], item)
		}
	}
	if kind == "balance" || kind == "metrics" {
		for date, byField := range instant {
			for _, items := range byField {
				for _, item := range items {
					p := balancePeriod(item)
					if kind == "balance" || !hasEnd(buckets, p.End, p.Mode) {
						if buckets[p] == nil {
							buckets[p] = map[string][]observation{}
						}
					}
				}
			}
			for p, byKey := range buckets {
				if p.End == date {
					for field, items := range byField {
						byKey[field] = items
					}
				}
			}
		}
	}
	for p, values := range buckets {
		row := domain.Row{Period: p, Values: map[string]domain.Cell{}}
		setFiscalLabel(&row.Period, values)
		for _, field := range fields {
			if field.tags != nil {
				row.Values[field.Key] = choose(values[field.Key])
			}
		}
		if kind == "cash-flow" || kind == "metrics" {
			row.Values[freeCashFlow.Key] = calculate(row.Values["operatingCashFlow"], row.Values["capex"], false)
		}
		if kind == "metrics" {
			row.Values[operatingMargin.Key] = calculate(row.Values["operatingIncome"], row.Values["revenue"], true)
			row.Values[netMargin.Key] = calculate(row.Values["netIncome"], row.Values["revenue"], true)
		}
		out.Rows = append(out.Rows, row)
	}
	sort.Slice(out.Rows, func(i, j int) bool {
		a, b := out.Rows[i].Period, out.Rows[j].Period
		if a.End != b.End {
			return a.End > b.End
		}
		if a.Mode != b.Mode {
			return a.Mode < b.Mode
		}
		return a.Start > b.Start
	})
	if kind == "metrics" {
		growth(out.Rows)
	}
	out.Rows = slices.DeleteFunc(out.Rows, func(r domain.Row) bool { return mode != "all" && r.Period.Mode != mode })
	if len(out.Rows) > limit {
		out.Rows = out.Rows[:limit]
	}
	return out, nil
}

func hasEnd(rows map[domain.Period]map[string][]observation, end, mode string) bool {
	for p := range rows {
		if p.End == end && p.Mode == mode {
			return true
		}
	}
	return false
}

func isBalance(key string) bool {
	return key == "assets" || key == "liabilities" || key == "equity"
}

type observation struct {
	fact           domain.Fact
	context        domain.Context
	unit           domain.Unit
	filing         domain.Filing
	comparableUnit string
	priority       int
}

func (s *Service) observations(ctx context.Context, issuer domain.Issuer, filings []domain.Filing, filter bson.M) ([]observation, error) {
	facts, err := s.Repo.Facts(ctx, filings, filter)
	if err != nil || len(facts) == 0 {
		return nil, err
	}
	contexts, err := s.Repo.Contexts(ctx, filings)
	if err != nil {
		return nil, err
	}
	units, err := s.Repo.Units(ctx, filings)
	if err != nil {
		return nil, err
	}
	type key struct{ accession, generation, ref string }
	ctxIndex := map[key]domain.Context{}
	unitIndex := map[key]domain.Unit{}
	filingIndex := map[key]domain.Filing{}
	for _, row := range contexts {
		ctxIndex[key{row.Accession, row.Generation, row.ContextRef}] = row
	}
	for _, row := range units {
		unitIndex[key{row.Accession, row.Generation, row.UnitRef}] = row
	}
	for _, row := range filings {
		filingIndex[key{row.Accession, row.Generation, ""}] = row
	}
	out := make([]observation, 0, len(facts))
	for _, fact := range facts {
		c, ok := ctxIndex[key{fact.Accession, fact.Generation, fact.ContextRef}]
		if !ok || strings.TrimLeft(c.Entity, "0") != strings.TrimLeft(issuer.CIK, "0") {
			continue
		}
		u, ok := unitIndex[key{fact.Accession, fact.Generation, fact.UnitRef}]
		if !ok {
			continue
		}
		f, ok := filingIndex[key{fact.Accession, fact.Generation, ""}]
		if !ok {
			continue
		}
		out = append(out, observation{fact: fact, context: c, unit: u, filing: f})
	}
	return out, nil
}

func financialUnit(unit domain.Unit, format string) string {
	if len(unit.Numerator) != 1 {
		return ""
	}
	match := currencyMeasure.FindStringSubmatch(unit.Numerator[0])
	if match == nil {
		return ""
	}
	if format == "eps" {
		if len(unit.Denominator) != 1 || unit.Denominator[0] != "{http://www.xbrl.org/2003/instance}shares" {
			return ""
		}
		return match[1] + "/share"
	}
	if len(unit.Denominator) != 0 {
		return ""
	}
	return match[1]
}

func parseDate(value string) time.Time { result, _ := time.Parse(time.DateOnly, value); return result }

func comparableDate(a, b time.Time, years, tolerance int) bool {
	if a.IsZero() || b.IsZero() {
		return false
	}
	delta := a.AddDate(years, 0, 0).Sub(b)
	return math.Abs(delta.Hours()/24) <= float64(tolerance)
}

func fiscalPeriod(o observation) (domain.Period, bool) {
	c, f := o.context, o.filing
	annual := f.Form == "10-K" || f.Form == "10-K/A"
	if !annual && f.Form != "10-Q" && f.Form != "10-Q/A" {
		return domain.Period{}, false
	}
	report := parseDate(f.ReportDate)
	end := parseDate(c.EndDate)
	if c.Instant != "" {
		end = parseDate(c.Instant)
	}
	current := !report.IsZero() && end.Equal(report)
	prior := comparableDate(end, report, 1, 14) || (annual && comparableDate(end, report, 2, 14))
	if !current && !prior {
		return domain.Period{}, false
	}
	if c.Instant != "" {
		return domain.Period{Mode: "instant", End: c.Instant}, true
	}
	start := parseDate(c.StartDate)
	if start.IsZero() || !start.Before(end) {
		return domain.Period{}, false
	}
	days := int(end.Sub(start).Hours()/24) + 1
	p := domain.Period{Start: c.StartDate, End: c.EndDate}
	switch {
	case annual && days >= 350 && days <= 385:
		p.Mode = "annual"
	case !annual && days >= 75 && days <= 110:
		p.Mode = "quarter"
	case !annual && days >= 155 && days <= 300:
		p.Mode = "ytd"
	default:
		return domain.Period{}, false
	}
	return p, true
}

func balancePeriod(o observation) domain.Period {
	mode := "quarter"
	if strings.HasPrefix(o.filing.Form, "10-K") {
		mode = "annual"
	}
	return domain.Period{Mode: mode, End: o.context.Instant}
}

func periodIdentity(p domain.Period) domain.Period {
	return domain.Period{Mode: p.Mode, Start: p.Start, End: p.End}
}

func setFiscalLabel(p *domain.Period, group map[string][]observation) {
	var year, period string
	for _, observations := range group {
		for _, o := range observations {
			f := o.filing
			if f.ReportDate != p.End || f.FiscalYear == "" || f.FiscalPeriod == "" {
				continue
			}
			if (p.Mode == "annual") != (f.FiscalPeriod == "FY") {
				continue
			}
			if year != "" && (year != f.FiscalYear || period != f.FiscalPeriod) {
				return
			}
			year, period = f.FiscalYear, f.FiscalPeriod
		}
	}
	p.FiscalYear, p.FiscalPeriod = year, period
}

func provenance(o observation) domain.Source {
	return domain.Source{Accession: o.filing.Accession, URL: o.filing.SourceURL, Form: o.filing.Form, Filed: o.filing.Filed, Concept: o.fact.Concept, Ordinal: o.fact.Ordinal, ReportedValue: o.fact.Value, RawValue: o.fact.RawValue}
}

func missing(issue string) domain.Cell { return domain.Cell{Issue: issue, Sources: []domain.Source{}} }

func isDirect(o observation) bool {
	return o.filing.ReportDate != "" && (o.context.EndDate == o.filing.ReportDate || o.context.Instant == o.filing.ReportDate)
}

func choose(items []observation) domain.Cell {
	if len(items) == 0 {
		return missing("not_reported")
	}
	sort.Slice(items, func(i, j int) bool {
		a, b := items[i], items[j]
		if isDirect(a) != isDirect(b) {
			return isDirect(a)
		}
		if a.filing.Filed != b.filing.Filed {
			return a.filing.Filed > b.filing.Filed
		}
		if a.filing.Accession != b.filing.Accession {
			return a.filing.Accession > b.filing.Accession
		}
		if a.priority != b.priority {
			return a.priority < b.priority
		}
		return a.fact.Ordinal < b.fact.Ordinal
	})
	first := items[0]
	cell := domain.Cell{Unit: first.comparableUnit, Sources: []domain.Source{}}
	var value *big.Rat
	sawNil := false
	for _, item := range items {
		if item.filing.Accession != first.filing.Accession || item.priority != first.priority {
			break
		}
		cell.Sources = append(cell.Sources, provenance(item))
		if item.comparableUnit != cell.Unit {
			cell.Issue = "conflicting_units"
		}
		if item.fact.Nil || item.fact.Value == nil {
			sawNil = true
			continue
		}
		next := asDecimal(item.fact.Value)
		if next == nil {
			cell.Issue = "invalid_value"
			continue
		}
		if value != nil && value.Cmp(next) != 0 {
			cell.Issue = "conflicting_values"
		}
		if value == nil {
			value = next
			cell.Value = item.fact.Value
		}
	}
	if cell.Issue == "" && value == nil {
		cell.Issue = "not_reported"
	}
	if cell.Issue == "" && sawNil {
		cell.Issue = "conflicting_values"
	}
	if cell.Issue != "" {
		cell.Value = nil
	}
	return cell
}

func asDecimal(value *string) *big.Rat {
	if value == nil || len(*value) > 512 || !decimalPattern.MatchString(*value) {
		return nil
	}
	result, ok := new(big.Rat).SetString(*value)
	if !ok {
		return nil
	}
	return result
}
func fractionDigits(s string) int {
	if i := strings.IndexByte(s, '.'); i >= 0 {
		return len(s) - i - 1
	}
	return 0
}
func calculate(a, b domain.Cell, ratio bool) domain.Cell {
	x, y := asDecimal(a.Value), asDecimal(b.Value)
	if x == nil || y == nil {
		return missing("missing_inputs")
	}
	out := domain.Cell{Unit: a.Unit, Sources: append(slices.Clone(a.Sources), b.Sources...)}
	if a.Unit != b.Unit {
		out.Issue = "conflicting_units"
		return out
	}
	precision := max(fractionDigits(*a.Value), fractionDigits(*b.Value))
	if ratio {
		out.Unit = "ratio"
		if y.Sign() == 0 {
			out.Issue = "zero_denominator"
			return out
		}
		x.Quo(x, y)
		precision = 8
	} else {
		if y.Sign() < 0 {
			out.Issue = "unexpected_capex_sign"
			return out
		}
		x.Sub(x, y)
	}
	result := x.FloatString(precision)
	out.Value = &result
	return out
}
func priorPeriod(current, prior domain.Period) bool {
	if current.Mode != prior.Mode || !comparableDate(parseDate(prior.End), parseDate(current.End), 1, 10) {
		return false
	}
	if current.FiscalPeriod != "" && prior.FiscalPeriod != "" && current.FiscalPeriod != prior.FiscalPeriod {
		return false
	}
	if current.FiscalYear != "" && prior.FiscalYear != "" {
		a, ea := strconv.Atoi(current.FiscalYear)
		b, eb := strconv.Atoi(prior.FiscalYear)
		if ea != nil || eb != nil || a != b+1 {
			return false
		}
	}
	if current.Start == "" || prior.Start == "" {
		return false
	}
	return comparableDate(parseDate(prior.Start), parseDate(current.Start), 1, 10)
}

func growth(rows []domain.Row) {
	for i := range rows {
		current := &rows[i]
		current.Growth = map[string]*float64{}
		for key, cell := range current.Values {
			current.Growth[key] = nil
			var old *domain.Cell
			for j := i + 1; j < len(rows); j++ {
				if !priorPeriod(current.Period, rows[j].Period) {
					continue
				}
				candidate := rows[j].Values[key]
				if old != nil {
					old = nil
					break
				}
				old = &candidate
			}
			if old == nil || cell.Unit != old.Unit || cell.Unit == "ratio" {
				continue
			}
			x, y := asDecimal(cell.Value), asDecimal(old.Value)
			if x == nil || y == nil || y.Sign() == 0 {
				continue
			}
			n, _ := new(big.Rat).Quo(new(big.Rat).Sub(x, y), new(big.Rat).Abs(y)).Float64()
			if !math.IsInf(n, 0) {
				current.Growth[key] = &n
			}
		}
	}
}
