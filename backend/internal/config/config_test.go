package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func configRoot(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	if err := os.Mkdir(filepath.Join(root, "backend"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "backend", "go.mod"), []byte("module fixture"), 0600); err != nil {
		t.Fatal(err)
	}
	t.Chdir(filepath.Join(root, "backend"))
	t.Setenv("CI", "")
	t.Setenv("SEC_READ_MONGODB_URI", "")
	t.Setenv("LISTEN_ADDR", "")
	return root
}
func TestLocalDotEnvSelection(t *testing.T) {
	root := configRoot(t)
	os.WriteFile(filepath.Join(root, ".env"), []byte("SEC_READ_MONGODB_URI='mongodb://fallback'\n"), 0600)
	os.WriteFile(filepath.Join(root, ".env.production"), []byte("SEC_READ_MONGODB_URI='mongodb://production'\n"), 0600)
	os.WriteFile(filepath.Join(root, ".env.local"), []byte("SEC_READ_MONGODB_URI='mongodb://local'\nLISTEN_ADDR=127.0.0.1:8081\n"), 0600)
	t.Setenv("SEC_READ_MONGODB_URI", "mongodb://stale-shell")
	c, err := Load()
	if err != nil || c.MongoURI != "mongodb://local" || c.Address != "127.0.0.1:8081" {
		t.Fatal(c, err)
	}
}
func TestDotEnvFallbackAndCI(t *testing.T) {
	root := configRoot(t)
	os.WriteFile(filepath.Join(root, ".env"), []byte("SEC_READ_MONGODB_URI='mongodb://fallback'\n"), 0600)
	c, err := Load()
	if err != nil || c.MongoURI != "mongodb://fallback" {
		t.Fatal(c, err)
	}
	t.Setenv("CI", "true")
	t.Setenv("SEC_READ_MONGODB_URI", "mongodb://injected")
	c, err = Load()
	if err != nil || c.MongoURI != "mongodb://injected" {
		t.Fatal(c, err)
	}
}
func TestConfigErrorsDoNotRevealValues(t *testing.T) {
	root := configRoot(t)
	os.WriteFile(filepath.Join(root, ".env.local"), []byte("bad-secret-content='unterminated"), 0600)
	_, err := Load()
	if err == nil || strings.Contains(err.Error(), "bad-secret-content") {
		t.Fatal("dotenv error may reveal file contents")
	}
}
