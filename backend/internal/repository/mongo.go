// Package repository reads immutable generations published by ingestion.
package repository

import (
	"context"
	"errors"
	"time"

	"finance-dashboard/backend/internal/domain"
	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"
	"go.mongodb.org/mongo-driver/v2/mongo/readconcern"
)

const (
	Database   = "SECIngestion"
	MaxFilings = 100
	MaxFacts   = 50000
)

var (
	ErrTooManyRecords = errors.New("dataset exceeds read bound")
	ErrNotFound       = errors.New("issuer not found")
	ErrReaderRole     = errors.New("read-only SECIngestion role required")
)

type Reader interface {
	Ready(context.Context) error
	Issuer(context.Context, string) (domain.Issuer, error)
	Related(context.Context, domain.Issuer) ([]domain.Issuer, error)
	Filings(context.Context, string) ([]domain.Filing, error)
	Facts(context.Context, []domain.Filing, bson.M) ([]domain.Fact, error)
	Contexts(context.Context, []domain.Filing) ([]domain.Context, error)
	Units(context.Context, []domain.Filing) ([]domain.Unit, error)
}

type Mongo struct {
	Client *mongo.Client
	DB     *mongo.Database
}

func Open(uri string) (*Mongo, error) {
	client, err := mongo.Connect(options.Client().ApplyURI(uri).SetReadConcern(readconcern.Majority()).SetMaxPoolSize(10).
		SetConnectTimeout(5 * time.Second).SetServerSelectionTimeout(5 * time.Second).SetServerAPIOptions(options.ServerAPI(options.ServerAPIVersion1)))
	if err != nil {
		return nil, err
	}
	return &Mongo{Client: client, DB: client.Database(Database)}, nil
}

func (m *Mongo) Ready(ctx context.Context) error {
	var status struct {
		AuthInfo struct {
			AuthenticatedUserRoles []struct{ Role, DB string } `bson:"authenticatedUserRoles"`
		} `bson:"authInfo"`
	}
	if err := m.DB.RunCommand(ctx, bson.D{{Key: "connectionStatus", Value: 1}}).Decode(&status); err != nil {
		return err
	}
	roles := status.AuthInfo.AuthenticatedUserRoles
	if len(roles) != 1 || roles[0].Role != "read" || roles[0].DB != Database {
		return ErrReaderRole
	}
	return m.DB.Collection("schema").FindOne(ctx, bson.M{"_id": "ingestion"}).Err()
}

func (m *Mongo) Issuer(ctx context.Context, symbol string) (domain.Issuer, error) {
	rows, err := find[domain.Issuer](ctx, m.DB.Collection("issuers"), bson.M{"symbols": symbol}, 2, nil)
	if err != nil {
		return domain.Issuer{}, err
	}
	if len(rows) != 1 {
		return domain.Issuer{}, ErrNotFound
	}
	return rows[0], nil
}

func (m *Mongo) Related(ctx context.Context, issuer domain.Issuer) ([]domain.Issuer, error) {
	if issuer.SIC == "" {
		return []domain.Issuer{}, nil
	}
	cursor, err := m.DB.Collection("issuers").Find(ctx, bson.M{"sic": issuer.SIC, "_id": bson.M{"$ne": issuer.CIK}},
		options.Find().SetLimit(12).SetSort(bson.D{{Key: "_id", Value: 1}}).SetProjection(bson.M{"name": 1, "symbols": 1, "sic": 1}))
	if err != nil {
		return nil, err
	}
	rows := []domain.Issuer{}
	err = cursor.All(ctx, &rows)
	return rows, err
}

func (m *Mongo) Filings(ctx context.Context, cik string) ([]domain.Filing, error) {
	return find[domain.Filing](ctx, m.DB.Collection("filings"), bson.M{"cik": cik, "generation": bson.M{"$exists": true}}, MaxFilings,
		bson.D{{Key: "filingDate", Value: -1}, {Key: "_id", Value: -1}})
}

// Each accession is paired with the generation read from its published pointer.
func published(filings []domain.Filing) bson.A {
	pairs := make(bson.A, 0, len(filings))
	for _, f := range filings {
		pairs = append(pairs, bson.M{"accession": f.Accession, "generation": f.Generation})
	}
	return pairs
}
func (m *Mongo) Facts(ctx context.Context, filings []domain.Filing, extra bson.M) ([]domain.Fact, error) {
	if len(filings) == 0 {
		return nil, nil
	}
	return find[domain.Fact](ctx, m.DB.Collection("facts"), bson.M{"$and": bson.A{bson.M{"$or": published(filings)}, extra}}, MaxFacts, nil)
}
func (m *Mongo) Contexts(ctx context.Context, filings []domain.Filing) ([]domain.Context, error) {
	if len(filings) == 0 {
		return nil, nil
	}
	return find[domain.Context](ctx, m.DB.Collection("contexts"), bson.M{"$or": published(filings)}, MaxFacts, nil)
}
func (m *Mongo) Units(ctx context.Context, filings []domain.Filing) ([]domain.Unit, error) {
	if len(filings) == 0 {
		return nil, nil
	}
	return find[domain.Unit](ctx, m.DB.Collection("units"), bson.M{"$or": published(filings)}, 10000, nil)
}

func find[T any](ctx context.Context, collection *mongo.Collection, query bson.M, limit int, sort bson.D) ([]T, error) {
	opts := options.Find().SetLimit(int64(limit + 1))
	if len(sort) != 0 {
		opts.SetSort(sort)
	}
	cursor, err := collection.Find(ctx, query, opts)
	if err != nil {
		return nil, err
	}
	rows := []T{}
	if err := cursor.All(ctx, &rows); err != nil {
		return nil, err
	}
	if len(rows) > limit {
		return nil, ErrTooManyRecords
	}
	return rows, nil
}
