// inspect prints field types and indexes, never document values or connection strings.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"time"

	"finance-dashboard/backend/internal/config"
	"finance-dashboard/backend/internal/repository"
	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo/options"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		fmt.Fprintln(os.Stderr, "MONGODB_URI is required")
		os.Exit(1)
	}
	r, err := repository.Open(cfg.MongoURI, cfg.Database)
	if err != nil {
		fmt.Fprintln(os.Stderr, "Cannot configure MongoDB connection")
		os.Exit(1)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	defer r.Client.Disconnect(context.Background())
	for _, name := range repository.Collections {
		cursor, err := r.DB.Collection(name).Find(ctx, bson.M{}, options.Find().SetLimit(10))
		if err != nil {
			fmt.Fprintln(os.Stderr, "Inspection failed; check network, credentials, and database access")
			os.Exit(1)
		}
		var rows []bson.M
		if err = cursor.All(ctx, &rows); err != nil {
			fmt.Fprintln(os.Stderr, "Cannot decode sample")
			os.Exit(1)
		}
		fields := map[string][]string{}
		seen := map[string]bool{}
		for _, row := range rows {
			for k, v := range row {
				t := fmt.Sprintf("%T", v)
				key := k + ":" + t
				if !seen[key] {
					fields[k] = append(fields[k], t)
					seen[key] = true
				}
			}
		}
		for _, types := range fields {
			sort.Strings(types)
		}
		indexes, err := r.DB.Collection(name).Indexes().List(ctx)
		if err != nil {
			fmt.Fprintln(os.Stderr, "Cannot read index metadata")
			os.Exit(1)
		}
		var raw []bson.M
		if err = indexes.All(ctx, &raw); err != nil {
			os.Exit(1)
		}
		keys := []any{}
		for _, index := range raw {
			keys = append(keys, index["key"])
		}
		_ = json.NewEncoder(os.Stdout).Encode(map[string]any{"collection": name, "sampleCount": len(rows), "fieldTypes": fields, "indexKeys": keys})
	}
}
