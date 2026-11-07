package service

import (
	"context"
	"errors"
	"sort"
	"strings"
	"time"

	"finance-dashboard/backend/internal/domain"
	"finance-dashboard/backend/internal/repository"
	"go.mongodb.org/mongo-driver/v2/bson"
)

var ErrNotFound = errors.New("company not found")
var StatementCollections = map[string]string{"income": "income_statement", "balance": "balance_sheet", "cash-flow": "cash_flow_statement"}
var Fields = map[string][]string{
	"income":  {"revenue", "costOfRevenue", "grossProfit", "grossProfitRatio", "researchAndDevelopmentExpenses", "generalAndAdministrativeExpenses", "sellingAndMarketingExpenses", "sellingGeneralAndAdministrativeExpenses", "otherExpenses", "operatingExpenses", "costAndExpenses", "interestIncome", "interestExpense", "depreciationAndAmortization", "ebitda", "ebitdaratio", "operatingIncome", "operatingIncomeRatio", "totalOtherIncomeExpensesNet", "incomeBeforeTax", "incomeBeforeTaxRatio", "incomeTaxExpense", "netIncome", "netIncomeRatio", "eps", "epsdiluted", "weightedAverageShsOut", "weightedAverageShsOutDil"},
	"balance": {"cashAndCashEquivalents", "shortTermInvestments", "cashAndShortTermInvestments", "netReceivables", "inventory", "otherCurrentAssets", "totalCurrentAssets", "propertyPlantEquipmentNet", "goodwill", "intangibleAssets", "goodwillAndIntangibleAssets", "longTermInvestments", "taxAssets", "otherNonCurrentAssets", "totalNonCurrentAssets", "otherAssets", "totalAssets", "accountPayables", "shortTermDebt", "taxPayables", "deferredRevenue", "otherCurrentLiabilities", "totalCurrentLiabilities", "longTermDebt", "deferredRevenueNonCurrent", "deferredTaxLiabilitiesNonCurrent", "otherNonCurrentLiabilities", "totalNonCurrentLiabilities", "otherLiabilities", "capitalLeaseObligations", "totalLiabilities", "preferredStock", "commonStock", "retainedEarnings", "accumulatedOtherComprehensiveIncomeLoss", "othertotalStockholdersEquity", "totalStockholdersEquity", "totalEquity", "totalLiabilitiesAndStockholdersEquity", "minorityInterest", "totalLiabilitiesAndTotalEquity", "totalInvestments", "totalDebt", "netDebt"},
	"cash-flow": {
		"netIncome",
		"depreciationAndAmortization",
		"deferredIncomeTax",
		"stockBasedCompensation",
		"changeInWorkingCapital",
		"accountsReceivables",
		"inventory",
		"accountsPayables",
		"otherWorkingCapital",
		"otherNonCashItems",
		"netCashProvidedByOperatingActivities",
		"investmentsInPropertyPlantAndEquipment",
		"acquisitionsNet",
		"purchasesOfInvestments",
		"salesMaturitiesOfInvestments",
		"otherInvestingActivites",
		"netCashUsedForInvestingActivites",
		"debtRepayment",
		"commonStockIssued",
		"commonStockRepurchased",
		"dividendsPaid",
		"otherFinancingActivites",
		"netCashUsedProvidedByFinancingActivities",
		"effectOfForexChangesOnCash",
		"netChangeInCash",
		"cashAtEndOfPeriod",
		"cashAtBeginningOfPeriod",
		"operatingCashFlow",
		"capitalExpenditure",
		"freeCashFlow",
	},
}
var Definitions = []domain.Metric{
	{Key: "revenue", Label: "Revenue", Format: "currency"}, {Key: "grossProfitRatio", Label: "Gross margin", Format: "percent"},
	{Key: "operatingIncome", Label: "Operating income", Format: "currency"}, {Key: "operatingIncomeRatio", Label: "Operating margin", Format: "percent"},
	{Key: "netIncome", Label: "Net income", Format: "currency"}, {Key: "netIncomeRatio", Label: "Net margin", Format: "percent"},
	{Key: "epsdiluted", Label: "Diluted EPS", Format: "currency"}, {Key: "weightedAverageShsOutDil", Label: "Diluted shares", Format: "number"},
	{Key: "dividendsPaid", Label: "Dividends paid", Format: "currency"}, {Key: "operatingCashFlow", Label: "Operating cash flow", Format: "currency"},
	{Key: "capitalExpenditure", Label: "Capital expenditure", Format: "currency"}, {Key: "freeCashFlow", Label: "Free cash flow", Format: "currency"},
	{Key: "freeCashFlowPerShare", Label: "Free cash flow per share", Format: "currency"}, {Key: "workingCapital", Label: "Working capital", Format: "currency"},
	{Key: "netDebt", Label: "Net debt", Format: "currency"},
}

type Service struct{ Repo repository.Reader }

func (s *Service) Exists(ctx context.Context, symbol string) error {
	// Check collections by bounded symbol queries; no writes or provider requests.
	for _, collection := range repository.Collections {
		rows, err := s.Repo.Records(ctx, collection, symbol)
		if err != nil {
			return err
		}
		if len(rows) > 0 {
			return nil
		}
	}
	return ErrNotFound
}

func (s *Service) Company(ctx context.Context, symbol string) (domain.Company, error) {
	rows, err := s.Repo.Records(ctx, "company_profile", symbol)
	if err != nil {
		return domain.Company{}, err
	}
	c := domain.Company{Symbol: symbol, Name: symbol}
	if len(rows) == 0 {
		return c, s.Exists(ctx, symbol)
	}
	r := ordered(rows)[0]
	c.Name = text(r["companyName"])
	if c.Name == "" {
		c.Name = symbol
	}
	c.Description = text(r["description"])
	c.Sector = text(r["sector"])
	c.Industry = text(r["industry"])
	c.Country = text(r["country"])
	c.Exchange = text(r["exchangeShortName"])
	c.Website = text(r["website"])
	c.Currency = text(r["currency"])
	c.CEO = text(r["ceo"])
	c.Price = Number(r["price"])
	c.MarketCap = Number(r["mktCap"])
	c.Employees = Number(r["fullTimeEmployees"])
	if t := updated(r); !t.IsZero() {
		v := t.Format(time.RFC3339)
		c.AsOf = &v
	}
	return c, nil
}

func normalizeStatements(rows []bson.M, kind string) []domain.Statement {
	out := []domain.Statement{}
	seen := map[string]bool{}
	for _, r := range ordered(rows) {
		d := date(r["date"])
		if d == "" {
			continue
		}
		period := strings.ToUpper(text(r["period"]))
		if period == "" {
			period = "FY"
		}
		key := d + "/" + period + "/" + text(r["reportedCurrency"])
		if seen[key] {
			continue
		}
		seen[key] = true
		values := map[string]*float64{}
		for _, field := range Fields[kind] {
			values[field] = Number(r[field])
		}
		year := text(r["calendarYear"])
		if year == "" {
			year = d[:4]
		}
		out = append(out, domain.Statement{Date: d, Year: year, Period: period, Currency: text(r["reportedCurrency"]), Values: values})
	}
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].Date == out[j].Date {
			return out[i].Period < out[j].Period
		}
		return out[i].Date > out[j].Date
	})
	return out
}

func (s *Service) Statements(ctx context.Context, symbol, kind string) ([]domain.Statement, error) {
	rows, err := s.Repo.Records(ctx, StatementCollections[kind], symbol)
	if err != nil {
		return nil, err
	}
	return normalizeStatements(rows, kind), nil
}

func (s *Service) Metrics(ctx context.Context, symbol string) (domain.Metrics, error) {
	points := map[string]*domain.MetricPoint{}
	for _, kind := range []string{"income", "cash-flow", "balance"} {
		rows, err := s.Statements(ctx, symbol, kind)
		if err != nil {
			return domain.Metrics{}, err
		}
		for _, row := range rows {
			key := row.Date + "/" + row.Period + "/" + row.Currency
			p := points[key]
			if p == nil {
				p = &domain.MetricPoint{Date: row.Date, Year: row.Year, Period: row.Period, Currency: row.Currency, Values: map[string]*float64{}, Growth: map[string]*float64{}}
				points[key] = p
			}
			for k, v := range row.Values {
				if p.Values[k] == nil && v != nil {
					p.Values[k] = v
				}
			}
		}
	}
	out := domain.Metrics{Definitions: Definitions, Points: []domain.MetricPoint{}}
	for _, p := range points {
		if a, b := p.Values["totalCurrentAssets"], p.Values["totalCurrentLiabilities"]; a != nil && b != nil {
			p.Values["workingCapital"] = Number(*a - *b)
		}
		if a, b := p.Values["freeCashFlow"], p.Values["weightedAverageShsOutDil"]; a != nil && b != nil && *b != 0 {
			p.Values["freeCashFlowPerShare"] = Number(*a / *b)
		}
		for _, def := range Definitions {
			if _, ok := p.Values[def.Key]; !ok {
				p.Values[def.Key] = nil
			}
		}
		out.Points = append(out.Points, *p)
	}
	sort.Slice(out.Points, func(i, j int) bool {
		a, b := out.Points[i], out.Points[j]
		if a.Date != b.Date {
			return a.Date < b.Date
		}
		if a.Period != b.Period {
			return a.Period < b.Period
		}
		return a.Currency < b.Currency
	})
	// Compare the same fiscal period and currency in the immediately preceding fiscal year.
	previous := map[string]domain.MetricPoint{}
	for i := range out.Points {
		p := &out.Points[i]
		key := p.Period + "/" + p.Currency
		prev, ok := previous[key]
		for _, def := range Definitions {
			p.Growth[def.Key] = nil
			a, b := p.Values[def.Key], prev.Values[def.Key]
			if ok && a != nil && b != nil && *b != 0 && nextYear(prev.Year, p.Year) {
				p.Growth[def.Key] = Number((*a - *b) / abs(*b))
			}
		}
		previous[key] = *p
	}
	return out, nil
}
func abs(v float64) float64 {
	if v < 0 {
		return -v
	}
	return v
}
func nextYear(a, b string) bool {
	x, y := Number(a), Number(b)
	return x != nil && y != nil && *y-*x == 1
}

func (s *Service) Prices(ctx context.Context, symbol, from, to string) ([]domain.Price, error) {
	rows, err := s.Repo.Records(ctx, "historical", symbol)
	if err != nil {
		return nil, err
	}
	out := []domain.Price{}
	seen := map[string]bool{}
	for _, r := range ordered(rows) {
		d := date(r["date"])
		if d == "" || seen[d] || (from != "" && d < from) || (to != "" && d > to) {
			continue
		}
		seen[d] = true
		out = append(out, domain.Price{Date: d, Open: Number(r["open"]), High: Number(r["high"]), Low: Number(r["low"]), Close: Number(r["close"]), Volume: Number(r["volume"])})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Date < out[j].Date })
	return out, nil
}
func (s *Service) Splits(ctx context.Context, symbol string) ([]domain.Split, error) {
	rows, err := s.Repo.Records(ctx, "stock_split", symbol)
	if err != nil {
		return nil, err
	}
	out := []domain.Split{}
	seen := map[string]bool{}
	for _, r := range ordered(rows) {
		d := date(r["date"])
		if d == "" || seen[d] {
			continue
		}
		seen[d] = true
		out = append(out, domain.Split{Date: d, Numerator: Number(r["numerator"]), Denominator: Number(r["denominator"])})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Date < out[j].Date })
	return out, nil
}
