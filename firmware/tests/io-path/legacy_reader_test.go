package vmess

import (
	"encoding/binary"
	"github.com/sagernet/sing/common"
	E "github.com/sagernet/sing/common/exceptions"
	"io"
)

// Original pinned sing-vmess StreamChunkReader.Read, retained as the oracle.
func legacyStreamRead(r *StreamChunkReader, p []byte) (n int, err error) {
	var length uint16
	err = binary.Read(r.upstream, binary.BigEndian, &length)
	if err != nil {
		return
	}
	var paddingLen int
	if r.globalPadding != nil {
		var hashCode uint16
		common.Must(binary.Read(r.globalPadding, binary.BigEndian, &hashCode))
		paddingLen = int(hashCode % 64)
	}
	if r.chunkMasking != nil {
		var hashCode uint16
		common.Must(binary.Read(r.chunkMasking, binary.BigEndian, &hashCode))
		length ^= hashCode
	}
	dataLen := int(length)
	if paddingLen > 0 {
		dataLen -= paddingLen
	}
	if dataLen < 0 {
		err = E.Extend(ErrBadLengthChunk, "length=", length, ", padding=", paddingLen)
		return
	}
	if dataLen == 0 {
		err = io.EOF
		return
	}
	var readLen int
	readLen = len(p)
	if readLen > dataLen {
		readLen = dataLen
	} else if readLen < dataLen {
		return 0, E.Extend(io.ErrShortBuffer, "stream chunk need ", dataLen)
	}
	n, err = io.ReadFull(r.upstream, p[:readLen])
	if err != nil {
		return
	}
	_, err = io.CopyN(io.Discard, r.upstream, int64(paddingLen))
	return
}
