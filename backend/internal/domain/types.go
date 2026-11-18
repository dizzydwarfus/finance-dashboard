// Package domain describes published EDGAR documents and the read API.
package domain

type Issuer struct {
	CIK     string   `bson:"_id" json:"cik"`
	Name    string   `json:"name"`
	Symbols []string `json:"symbols"`
	SIC     string   `json:"sic"`
}

type Filing struct {
	Accession    string `bson:"_id"`
	Generation   string
	Form         string
	Filed        string `bson:"filingDate"`
	ReportDate   string `bson:"reportDate"`
	SourceURL    string `bson:"sourceUrl"`
	FiscalYear   string `bson:"fiscalYear"`
	FiscalPeriod string `bson:"fiscalPeriod"`
}

type Dimension struct {
	Axis       string  `json:"axis"`
	Member     *string `json:"member"`
	TypedValue *string `bson:"typedValue" json:"typedValue"`
}

type Fact struct {
	Accession  string
	Generation string
	Ordinal    int64
	Concept    string
	Label      string
	Value      *string
	RawValue   string `bson:"rawValue"`
	Nil        bool
	ContextRef string `bson:"contextRef"`
	UnitRef    string `bson:"unitRef"`
}

type Context struct {
	Accession    string
	Generation   string
	ContextRef   string `bson:"contextRef"`
	Entity       string
	EntityScheme string `bson:"entityScheme"`
	StartDate    string `bson:"startDate"`
	EndDate      string `bson:"endDate"`
	Instant      string
	Dimensions   []Dimension
}

type Unit struct {
	Accession   string
	Generation  string
	UnitRef     string `bson:"unitRef"`
	Numerator   []string
	Denominator []string
}

type Source struct {
	Accession     string  `json:"accession"`
	URL           string  `json:"url"`
	Form          string  `json:"form"`
	Filed         string  `json:"filed"`
	Concept       string  `json:"concept"`
	Ordinal       int64   `json:"ordinal"`
	ReportedValue *string `json:"reportedValue"`
	RawValue      string  `json:"rawValue"`
}

type Cell struct {
	Value   *string  `json:"value"`
	Unit    string   `json:"unit"`
	Issue   string   `json:"issue,omitempty"`
	Sources []Source `json:"sources"`
}

type Field struct {
	Key    string `json:"key"`
	Label  string `json:"label"`
	Format string `json:"format"`
}

type Period struct {
	Mode         string `json:"mode"`
	Start        string `json:"start"`
	End          string `json:"end"`
	FiscalYear   string `json:"fiscalYear,omitempty"`
	FiscalPeriod string `json:"fiscalPeriod,omitempty"`
}

type Row struct {
	Period Period              `json:"period"`
	Values map[string]Cell     `json:"values"`
	Growth map[string]*float64 `json:"growth,omitempty"`
}

type Table struct {
	Fields []Field `json:"fields"`
	Rows   []Row   `json:"rows"`
}
type SegmentPoint struct {
	Period Period `json:"period"`
	Cell   Cell   `json:"cell"`
}
type SegmentSeries struct {
	Concept    string         `json:"concept"`
	Label      string         `json:"label"`
	Dimensions []Dimension    `json:"dimensions"`
	Unit       string         `json:"unit"`
	Points     []SegmentPoint `json:"points"`
}
