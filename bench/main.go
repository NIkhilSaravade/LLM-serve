// llm-bench: open-loop Poisson load generator for the llm-serve engine.
//
// Every request is sent at its scheduled arrival time whether or not earlier ones have
// finished (open loop), so a slow server accumulates queueing delay instead of quietly
// slowing the generator down. TTFT is measured from the SCHEDULED arrival, not from when
// the goroutine got around to sending, so generator lateness cannot hide server latency.
//
// Workload parameters mirror scripts/workloads.py exactly. Change one, change both.
package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"math"
	"math/rand"
	"net/http"
	"os"
	"sort"
	"sync"
	"time"
)

type Workload struct {
	PromptFixed, OutFixed     int
	PromptMedian, PromptSigma float64
	PromptLo, PromptHi        int
	OutMedian, OutSigma       float64
	OutLo, OutHi              int
}

var workloads = map[string]Workload{
	"A": {PromptFixed: 64, OutFixed: 64},
	"B": {PromptMedian: 64, PromptSigma: 0.5, PromptLo: 8, PromptHi: 512,
		OutMedian: 48, OutSigma: 0.7, OutLo: 4, OutHi: 256},
	"C": {PromptMedian: 64, PromptSigma: 0.5, PromptLo: 8, PromptHi: 512,
		OutMedian: 40, OutSigma: 1.2, OutLo: 8, OutHi: 400},
}

const vocab = 50257

func lognormal(rng *rand.Rand, median, sigma float64, lo, hi int) int {
	v := int(math.Round(math.Exp(math.Log(median) + sigma*rng.NormFloat64())))
	if v < lo {
		v = lo
	}
	if v > hi {
		v = hi
	}
	return v
}

type Planned struct {
	ID       int
	Arrival  float64 // seconds after start
	Prompt   []int
	MaxNew   int
	Injected bool
}

func randomPrompt(rng *rand.Rand, n int) []int {
	p := make([]int, n)
	for i := range p {
		p[i] = rng.Intn(vocab - 1)
	}
	return p
}

// plan draws Poisson arrivals over [0, duration) with lengths from the workload.
func plan(w Workload, seed int64, rate, duration float64) []Planned {
	rng := rand.New(rand.NewSource(seed))
	var out []Planned
	t := 0.0
	for id := 0; ; id++ {
		t += rng.ExpFloat64() / rate
		if t >= duration {
			break
		}
		pl, ol := w.PromptFixed, w.OutFixed
		if pl == 0 {
			pl = lognormal(rng, w.PromptMedian, w.PromptSigma, w.PromptLo, w.PromptHi)
			ol = lognormal(rng, w.OutMedian, w.OutSigma, w.OutLo, w.OutHi)
		}
		out = append(out, Planned{ID: id, Arrival: t, Prompt: randomPrompt(rng, pl), MaxNew: ol})
	}
	return out
}

type Result struct {
	ID           int       `json:"id"`
	ArrivalS     float64   `json:"arrival_s"`
	Status       string    `json:"status"` // ok | rejected | error | incomplete
	PromptTokens int       `json:"prompt_tokens"`
	OutTokens    int       `json:"out_tokens"`
	TTFT         float64   `json:"ttft_s,omitempty"`
	E2E          float64   `json:"e2e_s,omitempty"`
	TPOT         float64   `json:"tpot_s,omitempty"`
	LatenessS    float64   `json:"send_lateness_s"`
	Injected     bool      `json:"injected,omitempty"`
	tokenTimes   []float64 // seconds after start; kept only for ITL analysis
}

func doRequest(ctx context.Context, client *http.Client, url string, start time.Time, p Planned) Result {
	r := Result{ID: p.ID, ArrivalS: p.Arrival, PromptTokens: len(p.Prompt), Injected: p.Injected, Status: "incomplete"}
	sched := start.Add(time.Duration(p.Arrival * float64(time.Second)))
	select {
	case <-time.After(time.Until(sched)):
	case <-ctx.Done():
		return r
	}
	r.LatenessS = time.Since(sched).Seconds()

	body, _ := json.Marshal(map[string]any{
		"prompt_token_ids": p.Prompt, "max_new_tokens": p.MaxNew, "ignore_eos": true, "stream": true})
	req, _ := http.NewRequestWithContext(ctx, "POST", url+"/generate", bytes.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	resp, err := client.Do(req)
	if err != nil {
		if ctx.Err() == nil {
			r.Status = "error"
		}
		return r
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusTooManyRequests {
		r.Status = "rejected"
		io.Copy(io.Discard, resp.Body)
		return r
	}
	if resp.StatusCode != http.StatusOK {
		r.Status = "error"
		io.Copy(io.Discard, resp.Body)
		return r
	}
	sc := bufio.NewScanner(resp.Body)
	sc.Buffer(make([]byte, 1<<16), 1<<20)
	done := false
	for sc.Scan() {
		now := time.Now()
		var m struct {
			TokenID *int `json:"token_id"`
			Done    bool `json:"done"`
		}
		if json.Unmarshal(sc.Bytes(), &m) != nil {
			continue
		}
		if m.TokenID != nil {
			r.OutTokens++
			off := now.Sub(start).Seconds()
			r.tokenTimes = append(r.tokenTimes, off)
			if r.OutTokens == 1 {
				r.TTFT = off - p.Arrival
			}
		}
		if m.Done {
			done = true
			r.E2E = now.Sub(start).Seconds() - p.Arrival
		}
	}
	if !done {
		return r // stream cut off (deadline) -> incomplete
	}
	r.Status = "ok"
	if r.OutTokens > 1 {
		r.TPOT = (r.E2E - r.TTFT) / float64(r.OutTokens-1)
	}
	return r
}

func getJSON(client *http.Client, url string) map[string]any {
	resp, err := client.Get(url)
	if err != nil {
		return nil
	}
	defer resp.Body.Close()
	var m map[string]any
	json.NewDecoder(resp.Body).Decode(&m)
	return m
}

func main() {
	url := flag.String("url", "http://127.0.0.1:8000", "server base url")
	wl := flag.String("workload", "B", "A uniform | B realistic | C high variance")
	rate := flag.Float64("rate", 2, "offered load, requests per second (Poisson)")
	duration := flag.Float64("duration", 30, "arrival window, seconds")
	drain := flag.Float64("drain", 20, "extra seconds to let in-flight requests finish")
	seed := flag.Int64("seed", 1, "random seed")
	warmup := flag.Int("warmup", 3, "sequential warmup requests, discarded")
	sloTTFT := flag.Float64("slo-ttft", 2.0, "SLO: TTFT seconds")
	sloTPOT := flag.Float64("slo-tpot", 0.2, "SLO: TPOT seconds")
	out := flag.String("out", "", "write JSON here")
	label := flag.String("label", "", "free-text label stored in the JSON")
	injectAt := flag.Float64("inject-at", 0, "if >0, inject one long-prompt request at this time (s)")
	injectPrompt := flag.Int("inject-prompt", 800, "prompt tokens of the injected request")
	recordITL := flag.Bool("record-itl", false, "store inter-token gaps of every request")
	flag.Parse()

	w, ok := workloads[*wl]
	if !ok {
		fmt.Fprintln(os.Stderr, "unknown workload", *wl)
		os.Exit(2)
	}
	client := &http.Client{Transport: &http.Transport{MaxIdleConnsPerHost: 512, MaxConnsPerHost: 0}}

	// Warmup: discard. First-run effects would otherwise pollute the numbers.
	wrng := rand.New(rand.NewSource(*seed + 999))
	for i := 0; i < *warmup; i++ {
		doRequest(context.Background(), client, *url, time.Now(),
			Planned{Prompt: randomPrompt(wrng, 64), MaxNew: 16})
	}
	client.Post(*url+"/stats/reset", "application/json", nil)
	health := getJSON(client, *url+"/health")

	planned := plan(w, *seed, *rate, *duration)
	if *injectAt > 0 {
		planned = append(planned, Planned{ID: len(planned), Arrival: *injectAt,
			Prompt: randomPrompt(wrng, *injectPrompt), MaxNew: 16, Injected: true})
	}
	start := time.Now()
	ctx, cancel := context.WithDeadline(context.Background(),
		start.Add(time.Duration((*duration+*drain)*float64(time.Second))))
	defer cancel()

	results := make([]Result, len(planned))
	var wg sync.WaitGroup
	for i, p := range planned {
		wg.Add(1)
		go func(i int, p Planned) {
			defer wg.Done()
			results[i] = doRequest(ctx, client, *url, start, p)
		}(i, p)
	}
	wg.Wait()
	elapsed := time.Since(start).Seconds()
	serverMetrics := getJSON(client, *url+"/stats")

	rep := summarize(results, *duration, elapsed, *sloTTFT, *sloTPOT)
	rep.Label, rep.Workload, rep.Rate, rep.Seed = *label, *wl, *rate, *seed
	rep.DurationS, rep.DrainS = *duration, *drain
	rep.Server, rep.ServerMetrics = health, serverMetrics
	if *recordITL {
		for _, r := range results {
			if r.Injected {
				continue
			}
			for i := 1; i < len(r.tokenTimes); i++ {
				rep.ITLEvents = append(rep.ITLEvents, [2]float64{r.tokenTimes[i], r.tokenTimes[i] - r.tokenTimes[i-1]})
			}
		}
		sort.Slice(rep.ITLEvents, func(a, b int) bool { return rep.ITLEvents[a][0] < rep.ITLEvents[b][0] })
	}
	rep.Requests = results
	if *out != "" {
		if err := writeJSON(*out, rep); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
	}
	fmt.Printf("%s %s rate=%.1f seed=%d offered=%d ok=%d rej=%d inc=%d  tput=%.1f tok/s goodput=%.2f req/s  ttft p99=%.2f tpot p99=%.3f\n",
		*label, *wl, *rate, *seed, rep.Offered, rep.Completed, rep.Rejected, rep.Incomplete,
		rep.ThroughputTokPerS, rep.GoodputReqPerS, rep.TTFT.P99, rep.TPOT.P99)
}
