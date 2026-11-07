package config

import (
	"errors"
	"os"
	"path/filepath"
	"time"

	"github.com/joho/godotenv"
)

type Config struct {
	MongoURI, Database, Address string
	QueryTimeout                time.Duration
}

// Local runs select the repository-root .env.local, falling back to .env.
// Containers have no env files; CI always uses explicitly injected environment values.
func Load() (Config, error) {
	values, err := localValues()
	if err != nil {
		return Config{}, err
	}
	get := func(key string) string {
		if value, ok := values[key]; ok {
			return value
		}
		return os.Getenv(key)
	}
	c := Config{MongoURI: get("MONGODB_URI"), Database: get("MONGODB_DATABASE"), Address: get("LISTEN_ADDR"), QueryTimeout: 8 * time.Second}
	if c.MongoURI == "" {
		return c, errors.New("MONGODB_URI is required")
	}
	if c.Database == "" {
		c.Database = "FinanceApp"
	}
	if c.Address == "" {
		c.Address = "127.0.0.1:8080"
	}
	return c, nil
}

func localValues() (map[string]string, error) {
	if os.Getenv("CI") == "true" {
		return nil, nil
	}
	dir, err := os.Getwd()
	if err != nil {
		return nil, errors.New("cannot locate local configuration")
	}
	for {
		if _, err := os.Stat(filepath.Join(dir, "backend", "go.mod")); err == nil {
			for _, name := range []string{".env.local", ".env"} {
				path := filepath.Join(dir, name)
				if _, err := os.Stat(path); os.IsNotExist(err) {
					continue
				}
				values, err := godotenv.Read(path)
				if err != nil {
					return nil, errors.New("cannot read or parse " + name)
				}
				return values, nil
			}
			return nil, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			return nil, nil
		}
		dir = parent
	}
}
