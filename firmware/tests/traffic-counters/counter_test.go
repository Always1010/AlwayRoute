package trafficontrol

import (
	"math"
	"sync"
	"sync/atomic"
	"testing"

	"github.com/gofrs/uuid/v5"
)

// Exercise carry across the 32-bit boundary, signed overflow, and operations
// overlapping Load/Store. A torn 64-bit access must not become an API value.
func TestAlwayRouteCounterFullWidth(t *testing.T) {
	var counter TrafficCounter
	counter.Store(math.MaxUint32 - 1)
	if got := counter.Add(3); got != 1<<32+1 {
		t.Fatalf("32-bit carry: %d", got)
	}
	counter.Store(math.MaxInt64)
	if got := counter.Add(1); got != math.MinInt64 {
		t.Fatalf("signed overflow: %d", got)
	}
	const first, second = int64(0x55555555aaaaaaaa), int64(-6148914692668172971)
	counter.Store(first)
	var workers sync.WaitGroup
	for worker := 0; worker < 4; worker++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for i := 0; i < 10000; i++ {
				counter.Store(second)
				counter.Store(first)
				if got := counter.Load(); got != first && got != second {
					t.Errorf("torn load: %x", got)
					return
				}
			}
		}()
	}
	workers.Wait()
}

// Reset retains the upstream per-direction Store(0) behavior. It does not
// clear connection counters, nor defer updates until a periodic flush.
func TestAlwayRouteCounterConcurrentResetAndClose(t *testing.T) {
	manager := NewManager()
	tracker := &counterTestTracker{TrackerMetadata{
		ID: uuid.Must(uuid.NewV4()), Upload: new(TrafficCounter), Download: new(TrafficCounter),
	}}
	manager.Join(tracker)
	const workers, rounds, amount = 8, 1000, int64(1<<32 + 7)
	addPhase := func() {
		var group sync.WaitGroup
		for worker := 0; worker < workers; worker++ {
			group.Add(1)
			go func() {
				defer group.Done()
				for i := 0; i < rounds; i++ {
					tracker.metadata.Upload.Add(amount)
					manager.PushUploaded(amount)
					tracker.metadata.Download.Add(1)
					manager.PushDownloaded(1)
					manager.Total()
				}
			}()
		}
		group.Wait()
	}
	addPhase()
	if up, down := manager.Total(); up != workers*rounds*amount || down != workers*rounds {
		t.Fatalf("lost increments: %d, %d", up, down)
	}
	// Leave preserves pointers, including updates from I/O already in flight.
	manager.Leave(tracker)
	manager.Leave(tracker)
	closed := manager.ClosedConnections()
	if manager.ConnectionsLen() != 0 || len(closed) != 1 || closed[0].Upload != tracker.metadata.Upload {
		t.Fatal("closed connection lost its original counter")
	}
	manager.ResetStatistic()
	if up, down := manager.Total(); up != 0 || down != 0 {
		t.Fatalf("reset: %d, %d", up, down)
	}
	addPhase()
	if up, down := manager.Total(); up != workers*rounds*amount || down != workers*rounds {
		t.Fatalf("post-reset increments: %d, %d", up, down)
	}
	if got := closed[0].Upload.Load(); got != 2*workers*rounds*amount {
		t.Fatalf("closed/in-flight connection total: %d", got)
	}
	// Concurrent resets may discard preceding additions, exactly as atomic.Store.
	// Exercise this boundary under -race, then establish an unambiguous final epoch.
	var group sync.WaitGroup
	group.Add(1)
	go func() {
		defer group.Done()
		for i := 0; i < rounds; i++ {
			manager.ResetStatistic()
		}
	}()
	addPhase()
	group.Wait()
	manager.ResetStatistic()
	manager.PushUploaded(amount)
	if up, down := manager.Total(); up != amount || down != 0 {
		t.Fatalf("final reset epoch: %d, %d", up, down)
	}
}

type counterTestTracker struct{ metadata TrackerMetadata }

func (c *counterTestTracker) Metadata() *TrackerMetadata { return &c.metadata }
func (c *counterTestTracker) Close() error              { return nil }

// These matched update pairs model one connection plus one manager counter.
// Host numbers are a non-MIPS control, not evidence of router throughput.
func BenchmarkAlwayRouteCounters(b *testing.B) {
	b.Run("AtomicSerial", func(b *testing.B) {
		var connection, manager atomic.Int64
		for i := 0; i < b.N; i++ {
			connection.Add(16384)
			manager.Add(16384)
		}
	})
	b.Run("CandidateSerial", func(b *testing.B) {
		var connection, manager TrafficCounter
		for i := 0; i < b.N; i++ {
			connection.Add(16384)
			manager.Add(16384)
		}
	})
	b.Run("AtomicSharedManager", func(b *testing.B) {
		var manager atomic.Int64
		b.RunParallel(func(pb *testing.PB) {
			var connection atomic.Int64
			for pb.Next() {
				connection.Add(16384)
				manager.Add(16384)
			}
		})
	})
	b.Run("CandidateSharedManager", func(b *testing.B) {
		var manager TrafficCounter
		b.RunParallel(func(pb *testing.PB) {
			var connection TrafficCounter
			for pb.Next() {
				connection.Add(16384)
				manager.Add(16384)
			}
		})
	})
}
