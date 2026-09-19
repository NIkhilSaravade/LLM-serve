package main

import (
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"sort"
)

type Pcts struct {
	P50  float64 `json:"p50"`
	P95  float64 `json:"p95"`
	P99  float64 `json:"p99"`
	Mean float64 `json:"mean"`
}

// percentile uses the same index rule as engine/metrics.py: round(p/100*(n-1)).
func percentile(sorted []float64, p float64) float64 {
	if len(sorted) == 0 {
		return math.NaN()
	}
	return sorted[int(math.Round(p/100*float64(len(sorted)-1)))]
}

func pcts(xs []float64) Pcts {
	if len(xs) == 0 {
		return Pcts{}
	}
	s := append([]float64(nil), xs...)
	sort.Float64s(s)
	sum := 0.0
	for _, x := range s {
		sum += x
	}
	return Pcts{percentile(s, 50), percentile(s, 95), percentile(s, 99), sum / float64(len(s))}
}

type Report struct {
	Label     string  `json:"label"`
	Workload  string  `json:"workload"`
	Rate      float64 `json:"rate_req_per_s"`
	Seed      int64   `json:"seed"`
	DurationS float64 `json:"duration_s"`
	DrainS    float64 `json:"drain_s"`
	ElapsedS  float64 `json:"elapsed_s"`

	Offered    int `json:"offered"`
	Completed  int `json:"completed"`
	Rejected   int `json:"rejected"`
	Errors     int `json:"errors"`
	Incomplete int `json:"incomplete"`

	SLOTTFT float64 `json:"slo_ttft_s"`
	SLOTPOT float64 `json:"slo_tpot_s"`
	// Goodput = requests that completed AND met both SLOs, per second of arrival window.
	// Rejected, errored and unfinished requests count against it (attainment over ALL offered).
	SLOMet            int     `json:"slo_met"`
	SLOAttainment     float64 `json:"slo_attainment"`
	GoodputReqPerS    float64 `json:"goodput_req_per_s"`
	ThroughputTokPerS float64 `json:"throughput_tok_per_s"`
	P99TTFTMeetsSLO   bool    `json:"p99_ttft_meets_slo"`
	P99TPOTMeetsSLO   bool    `json:"p99_tpot_meets_slo"`

	TTFT Pcts `json:"ttft_s"`
	TPOT Pcts `json:"tpot_s"`
	E2E  Pcts `json:"e2e_s"`
	ITL  Pcts `json:"itl_s"`

	MaxSendLatenessS float64 `json:"max_send_lateness_s"`

	Server        map[string]any `json:"server"`
	ServerMetrics map[string]any `json:"server_metrics"`
	ITLEvents     [][2]float64   `json:"itl_events,omitempty"`
	Requests      []Result       `json:"requests"`
}

func summarize(rs []Result, duration, elapsed, sloTTFT, sloTPOT float64) *Report {
	rep := &Report{ElapsedS: elapsed, SLOTTFT: sloTTFT, SLOTPOT: sloTPOT}
	var ttft, tpot, e2e, itl []float64
	tokens, last := 0, 0.0
	for _, r := range rs {
		if r.Injected {
			continue // the injected long prompt is a probe, not part of the offered load
		}
		rep.Offered++
		if r.LatenessS > rep.MaxSendLatenessS {
			rep.MaxSendLatenessS = r.LatenessS
		}
		switch r.Status {
		case "ok":
			rep.Completed++
			tokens += r.OutTokens
			ttft = append(ttft, r.TTFT)
			e2e = append(e2e, r.E2E)
			if r.OutTokens > 1 {
				tpot = append(tpot, r.TPOT)
			}
			if r.TTFT <= sloTTFT && r.TPOT <= sloTPOT {
				rep.SLOMet++
			}
			if end := r.ArrivalS + r.E2E; end > last {
				last = end
			}
			for i := 1; i < len(r.tokenTimes); i++ {
				itl = append(itl, r.tokenTimes[i]-r.tokenTimes[i-1])
			}
		case "rejected":
			rep.Rejected++
		case "error":
			rep.Errors++
		default:
			rep.Incomplete++
		}
	}
	rep.TTFT, rep.TPOT, rep.E2E, rep.ITL = pcts(ttft), pcts(tpot), pcts(e2e), pcts(itl)
	window := math.Max(duration, last)
	rep.ThroughputTokPerS = float64(tokens) / window
	rep.GoodputReqPerS = float64(rep.SLOMet) / duration
	if rep.Offered > 0 {
		rep.SLOAttainment = float64(rep.SLOMet) / float64(rep.Offered)
	}
	rep.P99TTFTMeetsSLO = rep.Completed > 0 && rep.TTFT.P99 <= sloTTFT
	rep.P99TPOTMeetsSLO = rep.Completed > 0 && rep.TPOT.P99 <= sloTPOT
	return rep
}

func writeJSON(path string, v any) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	b, err := json.MarshalIndent(v, "", " ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, append(b, '\n'), 0o644)
}
