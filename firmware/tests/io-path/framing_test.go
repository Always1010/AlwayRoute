package vmess

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"testing"

	"github.com/sagernet/sing/common/buf"
	"github.com/sagernet/sing/common/bufio"
	"golang.org/x/crypto/sha3"
)

var injectedReadError = errors.New("injected read error")

type fragmentReader struct {
	data     []byte
	step     int
	pos      int
	terminal error
}

func (r *fragmentReader) Read(p []byte) (int, error) {
	if r.pos == len(r.data) {
		return 0, r.terminal
	}
	if len(p) > r.step {
		p = p[:r.step]
	}
	n := copy(p, r.data[r.pos:])
	r.pos += n
	return n, nil
}

func maskingReader(upstream io.Reader, masked, padded bool) *StreamChunkReader {
	var mask, padding sha3.ShakeHash
	if padded {
		padding = sha3.NewShake128()
		padding.Write([]byte("test seed"))
	}
	if masked {
		mask = padding
		if mask == nil {
			mask = sha3.NewShake128()
			mask.Write([]byte("test seed"))
		}
	}
	return NewStreamChunkReader(upstream, mask, padding)
}

func framedBytes(lengths []int, masked, padded bool) []byte {
	r := maskingReader(nil, masked, padded)
	var wire bytes.Buffer
	for _, length := range lengths {
		paddingLength := 0
		if padded {
			var scratch [2]byte
			io.ReadFull(r.globalPadding, scratch[:])
			paddingLength = int(binary.BigEndian.Uint16(scratch[:]) % 64)
		}
		header := uint16(length + paddingLength)
		if masked {
			var scratch [2]byte
			io.ReadFull(r.chunkMasking, scratch[:])
			header ^= binary.BigEndian.Uint16(scratch[:])
		}
		binary.Write(&wire, binary.BigEndian, header)
		wire.Write(bytes.Repeat([]byte{byte(length)}, length))
		wire.Write(make([]byte, paddingLength))
	}
	return wire.Bytes()
}

func TestAlwayRouteFramingDifferential(t *testing.T) {
	for _, masked := range []bool{false, true} {
		for _, padded := range []bool{false, true} {
			for _, lengths := range [][]int{{1, 2, 3, 31, 1, 0}, {15000, 16384, 1}, {16385}, {0}} {
				wire := framedBytes(lengths, masked, padded)
				for _, step := range []int{1, 3, 32768} {
					for _, cut := range []int{0, 1, len(wire) / 2, len(wire) - 1, len(wire)} {
						for _, terminal := range []error{io.EOF, injectedReadError} {
							name := fmt.Sprintf("mask=%v/pad=%v/length=%v/step=%d/cut=%d/error=%v", masked, padded, lengths, step, cut, terminal)
							t.Run(name, func(t *testing.T) {
								a := &fragmentReader{data: wire[:cut], step: step, terminal: terminal}
								b := &fragmentReader{data: wire[:cut], step: step, terminal: terminal}
								candidate, baseline := maskingReader(a, masked, padded), maskingReader(b, masked, padded)
								for i := 0; i <= len(lengths); i++ {
									left, right := make([]byte, 16384), make([]byte, 16384)
									n1, e1 := candidate.Read(left)
									n2, e2 := legacyStreamRead(baseline, right)
									if n1 != n2 || fmt.Sprint(e1) != fmt.Sprint(e2) || !bytes.Equal(left, right) || a.pos != b.pos {
										t.Fatalf("frame %d: candidate=(%d,%v,pos %d), baseline=(%d,%v,pos %d)", i, n1, e1, a.pos, n2, e2, b.pos)
									}
									if e1 != nil {
										break
									}
								}
							})
						}
					}
				}
			}
		}
	}
}

type legacyReader struct{ *StreamChunkReader }

func (r legacyReader) Read(p []byte) (int, error) { return legacyStreamRead(r.StreamChunkReader, p) }

func TestAlwayRouteFramingExtendedRead(t *testing.T) {
	// Both readers pass through the same chunk-buffer adapter as VMess TCP.
	// Alternate Read and ReadBuffer while a partial chunk is cached.
	wire := framedBytes([]int{31, 2, 15000, 1, 0}, true, true)
	a := bufio.NewChunkReader(maskingReader(bytes.NewReader(wire), true, true), ReadChunkSize)
	b := bufio.NewChunkReader(legacyReader{maskingReader(bytes.NewReader(wire), true, true)}, ReadChunkSize)
	for i := 0; i < 2000; i++ {
		var left, right []byte
		var e1, e2 error
		if i%2 == 0 {
			left, right = make([]byte, 17), make([]byte, 17)
			var n1, n2 int
			n1, e1 = a.Read(left)
			n2, e2 = b.Read(right)
			left, right = left[:n1], right[:n2]
		} else {
			ba, bb := buf.NewSize(29), buf.NewSize(29)
			e1, e2 = a.ReadBuffer(ba), b.ReadBuffer(bb)
			left, right = append([]byte(nil), ba.Bytes()...), append([]byte(nil), bb.Bytes()...)
			ba.Release()
			bb.Release()
		}
		if !bytes.Equal(left, right) || fmt.Sprint(e1) != fmt.Sprint(e2) {
			t.Fatalf("read %d diverged: %d/%d bytes, %v/%v", i, len(left), len(right), e1, e2)
		}
		if e1 != nil {
			return
		}
	}
	t.Fatal("reader did not terminate")
}

func BenchmarkAlwayRouteFraming(b *testing.B) {
	for _, size := range []int{64, 15000} {
		for _, legacy := range []bool{true, false} {
			b.Run(fmt.Sprintf("size=%d/legacy=%v", size, legacy), func(b *testing.B) {
				wire := framedBytes([]int{size}, true, false)
				source := bytes.NewReader(wire)
				r := maskingReader(source, true, false)
				payload := make([]byte, ReadChunkSize)
				seed := []byte("test seed")
				b.ReportAllocs()
				b.SetBytes(int64(size))
				b.ResetTimer()
				for i := 0; i < b.N; i++ {
					source.Reset(wire)
					r.chunkMasking.Reset()
					r.chunkMasking.Write(seed)
					var n int
					var err error
					if legacy {
						n, err = legacyStreamRead(r, payload)
					} else {
						n, err = r.Read(payload)
					}
					if err != nil || n != size {
						b.Fatalf("read %d: %v", n, err)
					}
				}
			})
		}
	}
}
