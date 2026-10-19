// SPDX-License-Identifier: GPL-3.0-only
package queue_test

import (
	"sync"
	"sync/atomic"
	"testing"

	"github.com/metacubex/mihomo/common/queue"
)

// Use only public methods: the upstream test manually locks and pops the
// backing slice, so it cannot detect Pop/Last's former unlocked length reads.
func TestPublicMethodsConcurrentEmptyTransitions(t *testing.T) {
	const workers, operations = 4, 2000
	q := queue.New[int](0)
	var popped atomic.Int64
	var done sync.WaitGroup
	start := make(chan struct{})
	for worker := 0; worker < workers; worker++ {
		done.Add(3)
		go func() {
			defer done.Done()
			<-start
			for i := 0; i < operations; i++ {
				q.Put(1)
			}
		}()
		go func() {
			defer done.Done()
			<-start
			for i := 0; i < operations; i++ {
				if value := q.Pop(); value == 1 {
					popped.Add(1)
				} else if value != 0 {
					t.Errorf("unexpected popped value: %d", value)
				}
			}
		}()
		go func() {
			defer done.Done()
			<-start
			for i := 0; i < operations; i++ {
				if value := q.Last(); value != 0 && value != 1 {
					t.Errorf("unexpected last value: %d", value)
				}
			}
		}()
	}
	close(start)
	done.Wait()
	if got, want := popped.Load()+q.Len(), int64(workers*operations); got != want {
		t.Fatalf("popped + remaining = %d; want %d", got, want)
	}
	for q.Pop() != 0 {
	}
	if q.Pop() != 0 || q.Last() != 0 || q.Len() != 0 {
		t.Fatal("empty queue no longer returns zero values")
	}
}
