// Package repository contains read-only MongoDB access. It never creates indexes.
package repository

import (
	"context"
	"errors"
	"sort"
	"strings"
	"time"

	"finance-dashboard/backend/internal/domain"
	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"
)

var Collections = []string{"balance_sheet", "income_statement", "cash_flow_statement", "company_profile", "historical", "stock_split"}

const MaxRecords = 20000

var ErrTooManyRecords = errors.New("dataset exceeds per-company read bound")

type Reader interface {
	Tickers(context.Context) ([]domain.Ticker, error)
	Records(context.Context, string, string) ([]bson.M, error)
	Ping(context.Context) error
}

type Mongo struct {
	Client *mongo.Client
	DB     *mongo.Database
}

func Open(uri, database string) (*Mongo, error) {
	c, err := mongo.Connect(options.Client().ApplyURI(uri).SetMaxPoolSize(10).SetMinPoolSize(0).SetConnectTimeout(5 * time.Second).SetServerSelectionTimeout(5 * time.Second).SetServerAPIOptions(options.ServerAPI(options.ServerAPIVersion1)))
	if err != nil {
		return nil, err
	}
	return &Mongo{Client: c, DB: c.Database(database)}, nil
}
func (m *Mongo) Ping(ctx context.Context) error { return m.Client.Ping(ctx, nil) }
func (m *Mongo) Records(ctx context.Context, collection, symbol string) ([]bson.M, error) {
	allowed := false
	for _, name := range Collections {
		if collection == name {
			allowed = true
		}
	}
	if !allowed {
		return nil, errors.New("unsupported collection")
	}
	cursor, err := m.DB.Collection(collection).Find(ctx, bson.M{"symbol": symbol}, options.Find().SetLimit(MaxRecords+1))
	if err != nil {
		return nil, err
	}
	defer cursor.Close(ctx)
	rows := []bson.M{}
	if err := cursor.All(ctx, &rows); err != nil {
		return nil, err
	}
	if len(rows) > MaxRecords {
		return nil, ErrTooManyRecords
	}
	return rows, nil
}
func (m *Mongo) Tickers(ctx context.Context) ([]domain.Ticker, error) {
	coverage := map[string][]string{}
	for _, collection := range Collections {
		var values []any
		if err := m.DB.Collection(collection).Distinct(ctx, "symbol", bson.M{}).Decode(&values); err != nil {
			return nil, err
		}
		for _, v := range values {
			if symbol, ok := v.(string); ok && symbol != "" {
				// Existing provider symbols are uppercase. Do not advertise unqueryable variants.
				if symbol != strings.ToUpper(symbol) {
					continue
				}
				coverage[symbol] = append(coverage[symbol], collection)
			}
		}
	}
	out := []domain.Ticker{}
	for symbol, collections := range coverage {
		out = append(out, domain.Ticker{Symbol: symbol, Coverage: collections})
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Symbol < out[j].Symbol })
	return out, nil
}
