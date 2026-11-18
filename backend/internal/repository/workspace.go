package repository

import (
	"context"
	"errors"

	"go.mongodb.org/mongo-driver/v2/bson"
	"go.mongodb.org/mongo-driver/v2/mongo"
)

const WorkspaceCollection = "analyst_workspaces"

// Verify effective privileges so an accidentally reused ingestion credential cannot enable saves.
func VerifyWorkspace(ctx context.Context, db *mongo.Database) error {
	var result struct {
		Auth struct {
			Privileges []struct {
				Resource struct {
					DB, Collection       string
					Cluster, AnyResource bool
				}
				Actions []string
			} `bson:"authenticatedUserPrivileges"`
		} `bson:"authInfo"`
	}
	err := db.RunCommand(ctx, bson.D{{Key: "connectionStatus", Value: 1}, {Key: "showPrivileges", Value: true}}).Decode(&result)
	if err != nil {
		return err
	}
	allowed := map[string]bool{"find": true, "insert": true, "update": true, "remove": true}
	seen := map[string]bool{}
	scopeError := errors.New("workspace credential needs collection-scoped read and write access")
	for _, p := range result.Auth.Privileges {
		if p.Resource.DB != Database || p.Resource.Collection != WorkspaceCollection || p.Resource.Cluster || p.Resource.AnyResource {
			return scopeError
		}
		for _, action := range p.Actions {
			if !allowed[action] {
				return scopeError
			}
			seen[action] = true
		}
	}
	if len(seen) != len(allowed) {
		return scopeError
	}
	return nil
}
