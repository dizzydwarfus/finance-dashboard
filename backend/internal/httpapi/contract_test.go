package httpapi

import (
	"encoding/json"
	"finance-dashboard/backend/internal/service"
	"fmt"
	"io"
	"log/slog"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
)

// Validate actual HTTP payloads against the independently maintained OpenAPI schemas.
func TestOpenAPIResponseSchemas(t *testing.T) {
	raw, err := os.ReadFile("../../../docs/openapi.json")
	if err != nil {
		t.Fatal(err)
	}
	var spec map[string]any
	if err = json.Unmarshal(raw, &spec); err != nil {
		t.Fatal(err)
	}
	schemas := spec["components"].(map[string]any)["schemas"].(map[string]any)
	h := (&Server{Service: &service.Service{Repo: &fakeRepo{}}, Log: slog.New(slog.NewTextHandler(io.Discard, nil))}).Handler()
	for path, entry := range spec["paths"].(map[string]any) {
		t.Run(path, func(t *testing.T) {
			url := strings.ReplaceAll(strings.ReplaceAll(path, "{symbol}", "DEMO"), "{type}", "income")
			rec := httptest.NewRecorder()
			h.ServeHTTP(rec, httptest.NewRequest("GET", url, nil))
			if rec.Code != 200 {
				t.Fatal(rec.Code)
			}
			var value any
			if err := json.Unmarshal(rec.Body.Bytes(), &value); err != nil {
				t.Fatal(err)
			}
			schema := entry.(map[string]any)["get"].(map[string]any)["responses"].(map[string]any)["200"].(map[string]any)["content"].(map[string]any)["application/json"].(map[string]any)["schema"].(map[string]any)
			if err := validateSchema(value, schema, schemas); err != nil {
				t.Fatal(err)
			}
		})
	}
}
func validateSchema(value any, schema map[string]any, schemas map[string]any) error {
	if ref, ok := schema["$ref"].(string); ok {
		return validateSchema(value, schemas[strings.TrimPrefix(ref, "#/components/schemas/")].(map[string]any), schemas)
	}
	if value == nil {
		if schema["nullable"] == true {
			return nil
		}
		return fmt.Errorf("unexpected null for %v", schema["type"])
	}
	switch schema["type"] {
	case "string":
		if _, ok := value.(string); !ok {
			return fmt.Errorf("expected string, got %T", value)
		}
	case "number":
		if _, ok := value.(float64); !ok {
			return fmt.Errorf("expected number, got %T", value)
		}
	case "array":
		values, ok := value.([]any)
		if !ok {
			return fmt.Errorf("expected array, got %T", value)
		}
		for _, v := range values {
			if err := validateSchema(v, schema["items"].(map[string]any), schemas); err != nil {
				return err
			}
		}
	case "object":
		obj, ok := value.(map[string]any)
		if !ok {
			return fmt.Errorf("expected object, got %T", value)
		}
		if required, ok := schema["required"].([]any); ok {
			for _, key := range required {
				if _, ok := obj[key.(string)]; !ok {
					return fmt.Errorf("missing required field %s", key)
				}
			}
		}
		props, _ := schema["properties"].(map[string]any)
		for key, v := range obj {
			property, known := props[key]
			if !known {
				switch extra := schema["additionalProperties"].(type) {
				case bool:
					if !extra {
						return fmt.Errorf("unexpected field %s", key)
					}
					continue
				case map[string]any:
					property = extra
				default:
					continue
				}
			}
			if err := validateSchema(v, property.(map[string]any), schemas); err != nil {
				return fmt.Errorf("%s: %w", key, err)
			}
		}
	}
	return nil
}
