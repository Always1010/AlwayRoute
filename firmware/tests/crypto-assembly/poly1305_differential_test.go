//go:build mipsle && gc && !purego

// Experimental CL585755 regression coverage. This adds no MAC implementation.
package poly1305

import (
	"bytes"
	"math/rand"
	"syscall"
	"testing"
)

// Compare assembly streaming state against the unchanged generic one-shot MAC.
// Upstream tests additionally cover RFC vectors, noncanonical accumulator states,
// unaligned inputs and Verify failures.
func TestAlwayRouteAssemblyDifferential(t *testing.T) {
	rng := rand.New(rand.NewSource(585755))
	sizes := []int{0, 1, 15, 16, 17, 31, 32, 33, 63, 64, 65, 255, 256, 257,
		1023, 1024, 1025, 4095, 4096, 4097, 16383, 16384, 16385}
	for i := 0; i < 32; i++ {
		sizes = append(sizes, rng.Intn(4097))
	}
	for caseID, size := range sizes {
		var key [32]byte
		rng.Read(key[:])
		storage := make([]byte, size+8)
		rng.Read(storage)
		for offset := 0; offset < 4; offset++ {
			src := storage[offset : offset+size]
			var want [TagSize]byte
			sumGeneric(&want, src, &key)
			for _, step := range []int{1, 15, 16, 17, 63, 64, 65, 257, 16384} {
				mac := New(&key)
				for position := 0; position < size; {
					end := position + step
					if end > size {
						end = size
					}
					if n, err := mac.Write(src[position:end]); err != nil || n != end-position {
						t.Fatalf("Write failed: %d, %v", n, err)
					}
					position = end
				}
				mac.Write(nil)
				var got [TagSize]byte
				mac.Sum(got[:0])
				if got != want {
					t.Fatalf("case=%d size=%d offset=%d step=%d: assembly differs from generic", caseID, size, offset, step)
				}
			}
		}
	}
}

func TestAlwayRouteAssemblyGuardedBuffers(t *testing.T) {
	page := syscall.Getpagesize()
	mapping, err := syscall.Mmap(-1, 0, 3*page, syscall.PROT_READ|syscall.PROT_WRITE, syscall.MAP_PRIVATE|syscall.MAP_ANON)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := syscall.Munmap(mapping); err != nil {
			t.Error(err)
		}
	})
	for _, guard := range [][]byte{mapping[:page], mapping[2*page:]} {
		if err := syscall.Mprotect(guard, syscall.PROT_NONE); err != nil {
			t.Fatal(err)
		}
	}
	input := mapping[page : 2*page : 2*page]
	var key [32]byte
	for i := range key {
		key[i] = byte(i*23 + 1)
	}
	for _, size := range []int{0, 1, 15, 16, 17, 31, 32, 33, 63, 64, 65, page - 1, page} {
		for _, start := range []int{0, 1, 3, page - size, page - size - 1, page - size - 3} {
			if start < 0 || start+size > page {
				continue
			}
			for i := range input {
				input[i] = 0xa5
			}
			for i := 0; i < size; i++ {
				input[start+i] = byte(i*17 + size)
			}
			before := append([]byte(nil), input...)
			var want [TagSize]byte
			sumGeneric(&want, input[start:start+size], &key)
			// Make the payload read-only too, to catch accidental assembly writes.
			if err := syscall.Mprotect(input, syscall.PROT_READ); err != nil {
				t.Fatal(err)
			}
			var got [TagSize]byte
			Sum(&got, input[start:start+size], &key)
			if err := syscall.Mprotect(input, syscall.PROT_READ|syscall.PROT_WRITE); err != nil {
				t.Fatal(err)
			}
			if got != want || !bytes.Equal(input, before) {
				t.Fatalf("size=%d start=%d: wrong MAC or modified input", size, start)
			}
		}
	}
}
