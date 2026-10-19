// SPDX-License-Identifier: GPL-3.0-only
// PSPortal regression for concurrent ApplyConfig and adapter-finalizer logging.
package log

import (
	"sync"
	"testing"
)

func TestLevelRoundTrip(t *testing.T) {
	previous := Level()
	t.Cleanup(func() { SetLevel(previous) })
	for _, want := range []LogLevel{DEBUG, INFO, WARNING, ERROR, SILENT, -1, 12345} {
		SetLevel(want)
		if got := Level(); got != want {
			t.Fatalf("Level() = %v; want %v", got, want)
		}
	}
}

func TestConcurrentLevelAndDebugLogging(t *testing.T) {
	previous := Level()
	t.Cleanup(func() { SetLevel(previous) })
	SetLevel(INFO)
	start := make(chan struct{})
	var done sync.WaitGroup
	for worker := 0; worker < 8; worker++ {
		done.Add(1)
		go func(writer bool) {
			defer done.Done()
			<-start
			for i := 0; i < 2000; i++ {
				if writer {
					// Keep DEBUG suppressed so this test does not emit log output.
					SetLevel(INFO + LogLevel(i%4))
				} else {
					if got := Level(); got < INFO || got > SILENT {
						t.Errorf("concurrent Level() = %v", got)
					}
					// Same public read path used by adapter finalizers.
					Debugln("atomic level regression")
				}
			}
		}(worker%2 == 0)
	}
	close(start)
	done.Wait()
}
