package httpapi

import (
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"net/url"
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
	h := server()
	for path, entry := range spec["paths"].(map[string]any) {
		if strings.HasPrefix(path, "/api/v1/sec/") || strings.HasPrefix(path, "/api/v1/workspaces") || entry.(map[string]any)["get"] == nil {
			continue // Workspace operations and model evaluation have dedicated authenticated/mutation tests.
		}
		t.Run(path, func(t *testing.T) {
			target := strings.ReplaceAll(strings.ReplaceAll(path, "{symbol}", "DEMO"), "{type}", "income")
			if strings.HasSuffix(path, "/segments") {
				target += "?accession=" + accession + "&fact=" + fakeID
			}
			if strings.HasSuffix(path, "/compare") {
				target += "?symbols=DEMO"
			}
			if strings.HasSuffix(path, "/pivot") {
				discovery := httptest.NewRecorder()
				h.ServeHTTP(discovery, httptest.NewRequest("GET", "/api/v1/companies/DEMO/dimensions", nil))
				var result struct {
					Data []struct{ ID, Concept string }
				}
				if err := json.Unmarshal(discovery.Body.Bytes(), &result); err != nil || len(result.Data) == 0 {
					t.Fatal("missing fixture slice")
				}
				target += "?slice=" + result.Data[0].ID + "&concept=" + url.QueryEscape(result.Data[0].Concept)
			}
			rec := httptest.NewRecorder()
			h.ServeHTTP(rec, httptest.NewRequest("GET", target, nil))
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
	case "number", "integer":
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
