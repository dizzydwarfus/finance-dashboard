package httpapi

import (
	"encoding/json"
	"errors"
	"slices"
	"time"

	"finance-dashboard/backend/internal/domain"
	"finance-dashboard/backend/internal/service"
)

// Check saved shapes at the API boundary. Rebuild model outputs from the captured
// baseline and assumptions so edits and their stored calculation always agree.
func validateAnalysis(item *savedItem) error {
	invalid := errors.New("The saved analysis is incomplete or invalid")
	switch item.Kind {
	case "compare":
		var view struct {
			Peers []string
			Trend *bool
		}
		if json.Unmarshal(item.Payload, &view) != nil || view.Trend == nil || view.Peers == nil || len(view.Peers) > 4 {
			return invalid
		}
		for i, v := range view.Peers {
			if !symbolPattern.MatchString(v) || v == item.Symbol || slices.Contains(view.Peers[:i], v) {
				return invalid
			}
		}
	case "explore":
		var view struct {
			Q, ID, Concept, Through, Display string
			Members                          []string
		}
		if json.Unmarshal(item.Payload, &view) != nil || !factIDPattern.MatchString(view.ID) || view.Concept == "" || len(view.Q) > 160 || !slices.Contains([]string{"value", "growth", "share"}, view.Display) || view.Members == nil {
			return invalid
		}
		if view.Through != "" {
			if _, err := time.Parse(time.DateOnly, view.Through); err != nil {
				return invalid
			}
		}
	case "model":
		var saved struct {
			Baseline  domain.Row                  `json:"baseline"`
			Scenarios map[string]service.Scenario `json:"scenarios"`
			Result    struct {
				Version   string                      `json:"version"`
				Forecasts map[string]service.Forecast `json:"forecasts"`
			} `json:"result"`
		}
		if json.Unmarshal(item.Payload, &saved) != nil {
			return invalid
		}
		revenue := saved.Baseline.Values["revenue"]
		if revenue.Value == nil || len(revenue.Sources) == 0 || saved.Baseline.Period.Mode != "annual" || saved.Result.Version != service.ModelVersion {
			return invalid
		}
		forecasts, err := service.Evaluate(service.Model{Revenue: *revenue.Value, Scenarios: saved.Scenarios})
		if err != nil {
			return err
		}
		saved.Result.Forecasts = forecasts
		item.Payload, err = json.Marshal(saved)
		return err
	default:
		return invalid
	}
	return nil
}
