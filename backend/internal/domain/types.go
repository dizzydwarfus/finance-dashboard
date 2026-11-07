// Package domain describes the API independently of MongoDB and HTTP.
package domain

type Ticker struct {
	Symbol   string   `json:"symbol"`
	Coverage []string `json:"coverage"`
}

type Company struct {
	Symbol      string   `json:"symbol"`
	Name        string   `json:"name"`
	Description string   `json:"description"`
	Sector      string   `json:"sector"`
	Industry    string   `json:"industry"`
	Country     string   `json:"country"`
	Exchange    string   `json:"exchange"`
	Website     string   `json:"website"`
	Currency    string   `json:"currency"`
	CEO         string   `json:"ceo"`
	Price       *float64 `json:"price"`
	MarketCap   *float64 `json:"marketCap"`
	Employees   *float64 `json:"employees"`
	AsOf        *string  `json:"asOf"`
}

type Statement struct {
	Date     string              `json:"date"`
	Year     string              `json:"year"`
	Period   string              `json:"period"`
	Currency string              `json:"currency"`
	Values   map[string]*float64 `json:"values"`
}

type Metric struct {
	Key    string `json:"key"`
	Label  string `json:"label"`
	Format string `json:"format"`
}

type MetricPoint struct {
	Date     string              `json:"date"`
	Year     string              `json:"year"`
	Period   string              `json:"period"`
	Currency string              `json:"currency"`
	Values   map[string]*float64 `json:"values"`
	Growth   map[string]*float64 `json:"growth"`
}

type Metrics struct {
	Definitions []Metric      `json:"definitions"`
	Points      []MetricPoint `json:"points"`
}

type Price struct {
	Date   string   `json:"date"`
	Open   *float64 `json:"open"`
	High   *float64 `json:"high"`
	Low    *float64 `json:"low"`
	Close  *float64 `json:"close"`
	Volume *float64 `json:"volume"`
}

type Split struct {
	Date        string   `json:"date"`
	Numerator   *float64 `json:"numerator"`
	Denominator *float64 `json:"denominator"`
}
