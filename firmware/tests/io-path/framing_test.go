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

const longFramingCount = 1<<16 + 4

func longFramingPayload(frame int, storage []byte) []byte {
	payload := storage[:1+frame%len(storage)]
	for i := range payload {
		payload[i] = byte(frame>>16) ^ byte(frame>>8) ^ byte(frame) ^ byte(i*31)
	}
	return payload
}

func TestAlwayRouteFramingLongStream(t *testing.T) {
	for _, masked := range []bool{false, true} {
		for _, padded := range []bool{false, true} {
			t.Run(fmt.Sprintf("mask=%v/pad=%v", masked, padded), func(t *testing.T) {
				// Use the pinned writer as the wire producer. Keep both readers and
				// all SHAKE states alive across every frame; buffer only one frame.
				var wire, oldWire bytes.Buffer
				state := maskingReader(nil, masked, padded)
				writer := NewStreamChunkWriter(&wire, state.chunkMasking, state.globalPadding)
				candidate := bufio.NewChunkReader(maskingReader(&wire, masked, padded), ReadChunkSize)
				baseline := bufio.NewChunkReader(legacyReader{maskingReader(&oldWire, masked, padded)}, ReadChunkSize)
				leftBuffer, rightBuffer := buf.NewSize(29), buf.NewSize(29)
				defer leftBuffer.Release()
				defer rightBuffer.Release()
				var storage [47]byte
				var leftSmall, rightSmall [17]byte
				readIndex := 0
				for frame := 0; frame < longFramingCount; frame++ {
					want := longFramingPayload(frame, storage[:])
					if n, err := writer.Write(want); err != nil || n != len(want) {
						t.Fatalf("frame %d write: %d bytes, %v", frame, n, err)
					}
					oldWire.Write(wire.Bytes())
					for offset := 0; offset < len(want); readIndex++ {
						var left, right []byte
						var e1, e2 error
						if readIndex%2 == 0 {
							var n1, n2 int
							n1, e1 = candidate.Read(leftSmall[:])
							n2, e2 = baseline.Read(rightSmall[:])
							left, right = leftSmall[:n1], rightSmall[:n2]
						} else {
							leftBuffer.Reset()
							rightBuffer.Reset()
							e1, e2 = candidate.ReadBuffer(leftBuffer), baseline.ReadBuffer(rightBuffer)
							left, right = leftBuffer.Bytes(), rightBuffer.Bytes()
						}
						// Pinned buf.Buffer.ReadFrom reports ErrShortBuffer when
						// full, even if that read consumed the final cached byte.
						matchingErrors := e1 == nil && e2 == nil || readIndex%2 == 1 &&
							e1 == io.ErrShortBuffer && e2 == io.ErrShortBuffer && leftBuffer.IsFull() && rightBuffer.IsFull()
						if !matchingErrors || len(left) == 0 || !bytes.Equal(left, right) ||
							len(left) > len(want)-offset || !bytes.Equal(left, want[offset:offset+len(left)]) || wire.Len() != oldWire.Len() {
							t.Fatalf("frame %d offset %d: payload %x/%x, errors %v/%v, wire remaining %d/%d", frame, offset, left, right, e1, e2, wire.Len(), oldWire.Len())
						}
						offset += len(left)
					}
					if wire.Len() != 0 || oldWire.Len() != 0 {
						t.Fatalf("frame %d left unread wire bytes", frame)
					}
				}
				// No synthesized terminator: only the actual exhausted input may EOF.
				n1, e1 := candidate.Read(leftSmall[:])
				n2, e2 := baseline.Read(rightSmall[:])
				if n1 != 0 || n2 != 0 || e1 != io.EOF || e2 != io.EOF {
					t.Fatalf("terminal read: (%d,%v)/(%d,%v)", n1, e1, n2, e2)
				}
			})
		}
	}
}

func TestAlwayRouteFramingAEADNonceWrap(t *testing.T) {
	for _, masked := range []bool{false, true} {
		for _, padded := range []bool{false, true} {
			t.Run(fmt.Sprintf("mask=%v/pad=%v", masked, padded), func(t *testing.T) {
				// Exercise the actual protocol factories and cipher, not a copied
				// nonce/encryption implementation. This verifies current round-trip
				// behavior across uint16 wrap, not the cryptographic safety of reuse.
				key, nonce := []byte("0123456789abcdef"), []byte("fedcba9876543210")
				option := byte(RequestOptionChunkStream)
				if masked {
					option |= RequestOptionChunkMasking
				}
				if padded {
					option |= RequestOptionGlobalPadding
				}
				var wire, oldWire bytes.Buffer
				writer := CreateWriter(&wire, nil, key, nonce, key, nonce, SecurityTypeChacha20Poly1305, option)
				candidate := CreateReader(&wire, nil, key, nonce, key, nonce, SecurityTypeChacha20Poly1305, option).(*AEADReader)
				oldFraming := CreateReader(&oldWire, nil, key, nonce, key, nonce, SecurityTypeNone, option).(*StreamChunkReader)
				baseline := NewChacha20Poly1305Reader(legacyReader{oldFraming}, key, nonce)
				leftBuffer, rightBuffer := buf.NewSize(ReadChunkSize), buf.NewSize(ReadChunkSize)
				defer leftBuffer.Release()
				defer rightBuffer.Release()
				leftRead, rightRead := make([]byte, ReadChunkSize), make([]byte, ReadChunkSize)
				var storage [47]byte
				for frame := 0; frame < longFramingCount; frame++ {
					want := longFramingPayload(frame, storage[:])
					if n, err := writer.Write(want); err != nil || n != len(want) {
						t.Fatalf("frame %d write: %d bytes, %v", frame, n, err)
					}
					oldWire.Write(wire.Bytes())
					var left, right []byte
					var e1, e2 error
					if frame%2 == 0 {
						var n1, n2 int
						n1, e1 = candidate.Read(leftRead)
						n2, e2 = baseline.Read(rightRead)
						left, right = leftRead[:n1], rightRead[:n2]
					} else {
						leftBuffer.Reset()
						rightBuffer.Reset()
						e1, e2 = candidate.ReadBuffer(leftBuffer), baseline.ReadBuffer(rightBuffer)
						left, right = leftBuffer.Bytes(), rightBuffer.Bytes()
					}
					if e1 != nil || e2 != nil || !bytes.Equal(left, want) || !bytes.Equal(right, want) || wire.Len() != 0 || oldWire.Len() != 0 {
						t.Fatalf("frame %d: payload %x/%x want %x, errors %v/%v, wire remaining %d/%d", frame, left, right, want, e1, e2, wire.Len(), oldWire.Len())
					}
					if frame >= 65534 && (candidate.nonceCount != uint16(frame+1) || baseline.nonceCount != uint16(frame+1)) {
						t.Fatalf("frame %d did not cross nonce boundary: %d/%d", frame, candidate.nonceCount, baseline.nonceCount)
					}
				}
				n1, e1 := candidate.Read(leftRead)
				n2, e2 := baseline.Read(rightRead)
				if n1 != 0 || n2 != 0 || e1 != io.EOF || e2 != io.EOF {
					t.Fatalf("terminal read: (%d,%v)/(%d,%v)", n1, e1, n2, e2)
				}
			})
		}
	}
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
