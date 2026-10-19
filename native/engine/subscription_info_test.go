// SPDX-License-Identifier: GPL-3.0-only
package engine

import (
	"context"
	"errors"
	"io"
	"net/http"
	"strconv"
	"sync/atomic"
	"testing"
	"time"
)

type subscriptionInfoTransport func(*http.Request) (*http.Response, error)

func (f subscriptionInfoTransport) RoundTrip(request *http.Request) (*http.Response, error) {
	return f(request)
}

type subscriptionInfoBody struct {
	close func()
}

func (b *subscriptionInfoBody) Read([]byte) (int, error) { return 0, io.EOF }
func (b *subscriptionInfoBody) Close() error {
	if b.close != nil {
		b.close()
	}
	return nil
}

func TestSubscriptionAccountingUsesOnlyBoundedServerValues(t *testing.T) {
	info := parseSubscriptionInfo("upload=100; download=200; total=1000; expire=2000000000; token=opaque")
	if len(info) != 4 || info["download"] != 200 || info["total"] != 1000 {
		t.Fatal(info)
	}
	for _, header := range []string{"total=-1; expire=99999999999999999", "total=NaN", "upload=18446744073709551615"} {
		if len(parseSubscriptionInfo(header)) != 0 {
			t.Fatal("Invalid accounting accepted")
		}
	}
	for _, url := range []string{"https://127.0.0.1/token", "http://provider.example/token", "https://user:secret@provider.example/token"} {
		if SubscriptionInfo(url) != `{"available":false}` {
			t.Fatal("Unsafe URL accepted")
		}
	}
}

func TestSubscriptionInfoCanceledBeforeDispatch(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	calls := 0
	transport := subscriptionInfoTransport(func(*http.Request) (*http.Response, error) {
		calls++
		return nil, errors.New("unexpected request")
	})
	if got := requestSubscriptionInfo(ctx, "https://provider.example/sub", transport); got != subscriptionInfoUnavailable {
		t.Fatal(got)
	}
	if calls != 0 {
		t.Fatal("canceled request reached transport")
	}
}

func TestSubscriptionInfoCanceledInFlightByEngineStop(t *testing.T) {
	for _, method := range []string{http.MethodHead, http.MethodGet} {
		t.Run(method, func(t *testing.T) {
			cfg := validConfig()
			core := newEmbeddedCore(cfg)
			app := &Engine{cfg: cfg, core: core, proxy: NewProxy(cfg, core), running: true}
			defer app.Stop()
			started := make(chan struct{}, 1)
			result := make(chan string, 1)
			var calls atomic.Int32
			transport := subscriptionInfoTransport(func(request *http.Request) (*http.Response, error) {
				calls.Add(1)
				if request.Method != method {
					return &http.Response{StatusCode: http.StatusMethodNotAllowed, Body: http.NoBody}, nil
				}
				started <- struct{}{}
				<-request.Context().Done()
				return nil, request.Context().Err()
			})
			go func() { result <- requestSubscriptionInfo(core.ctx, cfg.SubscriptionURL, transport) }()
			select {
			case <-started:
			case <-time.After(2 * time.Second):
				t.Fatal("metadata request did not start")
			}
			app.Stop()
			select {
			case got := <-result:
				if got != subscriptionInfoUnavailable {
					t.Fatal(got)
				}
			case <-time.After(2 * time.Second):
				t.Fatal("Stop did not cancel in-flight metadata request")
			}
			wantCalls := int32(1)
			if method == http.MethodGet {
				wantCalls = 2
			}
			if calls.Load() != wantCalls {
				t.Fatal("unexpected request after cancellation")
			}
		})
	}
}

func TestSubscriptionInfoCancellationAtHeadBoundary(t *testing.T) {
	for _, status := range []int{http.StatusOK, http.StatusMethodNotAllowed, http.StatusNotImplemented} {
		t.Run(strconv.Itoa(status), func(t *testing.T) {
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			calls, closed := 0, false
			transport := subscriptionInfoTransport(func(request *http.Request) (*http.Response, error) {
				calls++
				return &http.Response{StatusCode: status, Body: &subscriptionInfoBody{close: func() {
					closed = true
					cancel()
				}}}, nil
			})
			if got := requestSubscriptionInfo(ctx, "https://provider.example/sub", transport); got != subscriptionInfoUnavailable {
				t.Fatal(got)
			}
			if calls != 1 || !closed {
				t.Fatal("cancellation allowed GET fallback or left HEAD open")
			}
		})
	}
}

func TestSubscriptionInfoDiscardsResponseAfterCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	transport := subscriptionInfoTransport(func(*http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: http.StatusOK,
			Header: http.Header{"Subscription-Userinfo": []string{"total=1000"}},
			Body:   &subscriptionInfoBody{close: cancel}}, nil
	})
	if got := requestSubscriptionInfo(ctx, "https://provider.example/sub", transport); got != subscriptionInfoUnavailable {
		t.Fatal("returned metadata from canceled engine", got)
	}
}

func TestSubscriptionInfoHeadAndGetCompatibility(t *testing.T) {
	for _, status := range []int{http.StatusOK, http.StatusMethodNotAllowed, http.StatusNotImplemented} {
		t.Run(strconv.Itoa(status), func(t *testing.T) {
			methods := []string{}
			closed := 0
			transport := subscriptionInfoTransport(func(request *http.Request) (*http.Response, error) {
				methods = append(methods, request.Method)
				response := &http.Response{StatusCode: status, Header: http.Header{},
					Body: &subscriptionInfoBody{close: func() { closed++ }}}
				if request.Method == http.MethodGet {
					response.StatusCode = http.StatusOK
					response.Header.Set("subscription-userinfo", "total=1000; token=opaque")
				}
				return response, nil
			})
			if got := requestSubscriptionInfo(context.Background(), "https://provider.example/sub", transport); got != `{"total":1000}` {
				t.Fatal(got)
			}
			if len(methods) != 2 || methods[0] != http.MethodHead || methods[1] != http.MethodGet || closed != 2 {
				t.Fatal("HEAD/GET fallback changed", methods, closed)
			}
		})
	}
}

func TestEngineSubscriptionInfoRequiresLiveMatchingCore(t *testing.T) {
	cfg := validConfig()
	app := &Engine{cfg: cfg}
	if got := app.SubscriptionInfo(cfg.SubscriptionURL); got != subscriptionInfoUnavailable {
		t.Fatal("stopped engine fetched metadata", got)
	}
	core := newEmbeddedCore(cfg)
	defer core.Close()
	app.core, app.running = core, true
	if got := app.SubscriptionInfo("https://other-provider.example/sub"); got != subscriptionInfoUnavailable {
		t.Fatal("engine accepted another subscription", got)
	}
	core.cancel()
	if got := app.SubscriptionInfo(cfg.SubscriptionURL); got != subscriptionInfoUnavailable {
		t.Fatal("engine did not inherit canceled core context", got)
	}
}
