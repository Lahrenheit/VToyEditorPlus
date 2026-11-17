"""Minimal pure-Python 7z extractor (LZMA / LZMA2 / BCJ-x86 / Delta / Copy), stdlib only."""
import lzma, os, struct, sys, zlib


class R:
    def __init__(s, b, o=0):
        s.b, s.o = b, o

    def u8(s):
        v = s.b[s.o]; s.o += 1; return v

    def take(s, n):
        v = s.b[s.o:s.o + n]; s.o += n; return v

    def num(s):
        first = s.u8(); mask = 0x80; val = 0
        for i in range(8):
            if first & mask == 0:
                hi = first & (mask - 1)
                return val | (hi << (8 * i))
            val |= s.u8() << (8 * i)
            mask >>= 1
        return val

    def bits(s, n):
        out = []; mask = 0; cur = 0
        for i in range(n):
            if mask == 0:
                cur = s.u8(); mask = 0x80
            out.append(bool(cur & mask)); mask >>= 1
        return out

    def defbits(s, n):
        if s.u8():
            return [True] * n
        return s.bits(n)


def read_pack_info(r):
    pos = r.num(); n = r.num(); sizes = []
    while True:
        t = r.u8()
        if t == 0: break
        if t == 9: sizes = [r.num() for _ in range(n)]
        elif t == 10:
            d = r.defbits(n)
            for x in d:
                if x: r.take(4)
    return pos, sizes


def read_folder(r):
    nc = r.num(); coders = []; tin = tout = 0
    for _ in range(nc):
        f = r.u8(); idsz = f & 0xF
        cid = bytes(r.take(idsz)); nin = nout = 1
        if f & 0x10: nin = r.num(); nout = r.num()
        props = b""
        if f & 0x20: props = bytes(r.take(r.num()))
        coders.append((cid, nin, nout, props)); tin += nin; tout += nout
    nbp = tout - 1
    bps = [(r.num(), r.num()) for _ in range(nbp)]
    npk = tin - nbp
    if npk == 1:
        bound = {b[0] for b in bps}
        pk = [i for i in range(tin) if i not in bound]
    else:
        pk = [r.num() for _ in range(npk)]
    return dict(coders=coders, bps=bps, pk=pk, tout=tout)


def read_unpack_info(r):
    assert r.u8() == 0xB
    n = r.num(); assert r.u8() == 0
    folders = [read_folder(r) for _ in range(n)]
    assert r.u8() == 0xC
    for f in folders:
        f["sizes"] = [r.num() for _ in range(f["tout"])]
    while True:
        t = r.u8()
        if t == 0: break
        if t == 0xA:
            d = r.defbits(n)
            for x in d:
                if x: r.take(4)
    return folders


def read_substreams(r, folders):
    nums = [1] * len(folders)
    t = r.u8()
    if t == 0xD:
        nums = [r.num() for _ in folders]; t = r.u8()
    sizes = []
    for f, n in zip(folders, nums):
        if n == 0: continue
        tot = f["sizes"][-1] if False else folder_unpack_size(f)
        acc = 0
        if t == 9:
            for _ in range(n - 1):
                s = r.num(); sizes.append(s); acc += s
        else:
            pass
        sizes.append(tot - acc)
    if t == 9: t = r.u8()
    while t != 0:
        if t == 0xA:
            # CRCs; skip: count streams with unknown crc
            cnt = 0
            for f, n in zip(folders, nums):
                cnt += n
            d = r.defbits(cnt)
            for x in d:
                if x: r.take(4)
        t = r.u8()
    return nums, sizes


def folder_unpack_size(f):
    bound_out = {b[1] for b in f["bps"]}
    for i in range(f["tout"]):
        if i not in bound_out:
            return f["sizes"][i]
    return f["sizes"][-1]


def read_streams_info(r):
    pack = None; folders = []; nums = None; sizes = None
    while True:
        t = r.u8()
        if t == 0: break
        if t == 6: pack = read_pack_info(r)
        elif t == 7: folders = read_unpack_info(r)
        elif t == 8: nums, sizes = read_substreams(r, folders)
    if nums is None:
        nums = [1] * len(folders); sizes = [folder_unpack_size(f) for f in folders]
    return pack, folders, nums, sizes


def lzma2_dict(p):
    if p == 40: return 0xFFFFFFFF
    return (2 | (p & 1)) << (p // 2 + 11)


def run_coder(cid, props, data, outsize):
    if cid == b"\x00": return data
    if cid == b"\x21":
        flt = [{"id": lzma.FILTER_LZMA2, "dict_size": lzma2_dict(props[0])}]
    elif cid == b"\x03\x01\x01":
        p = props[0]; lc = p % 9; p //= 9; lp = p % 5; pb = p // 5
        flt = [{"id": lzma.FILTER_LZMA1, "dict_size": struct.unpack("<I", props[1:5])[0], "lc": lc, "lp": lp, "pb": pb}]
    elif cid == b"\x03\x03\x01\x03":
        flt = [{"id": lzma.FILTER_X86}]
    elif cid == b"\x03":
        flt = [{"id": lzma.FILTER_DELTA, "dist": props[0] + 1 if props else 1}]
    else:
        raise NotImplementedError(f"coder {cid.hex()}")
    d = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=flt)
    out = d.decompress(data, max_length=outsize if outsize else -1)
    return out


def bcj2_decode(main, call, jump, rc, outsize):
    """7-Zip BCJ2 (x86 branch converter, 4 input streams) decoder, original 9.20 algorithm."""
    prob = [1024] * (2 + 256)
    out = bytearray()
    pos = [0, 0, 0]  # call, jump, rc
    rcpos = 5
    code = 0
    for i in range(5):
        code = ((code << 8) | rc[i]) & 0xFFFFFFFF
    rng = 0xFFFFFFFF
    inpos = 0; prev = 0; n = len(main)
    while len(out) < outsize:
        # copy plain bytes until a jump opcode candidate
        start = inpos
        while inpos < n:
            b = main[inpos]
            if (b & 0xFE) == 0xE8 or (prev == 0x0F and (b & 0xF0) == 0x80):
                break
            prev = b; inpos += 1
        out += main[start:inpos]
        if inpos >= n:
            break
        b = main[inpos]; inpos += 1
        out.append(b)
        if len(out) >= outsize:
            break
        pi = prev if b == 0xE8 else (256 if b == 0xE9 else 257)
        ttt = prob[pi]
        bound = (rng >> 11) * ttt
        if code < bound:
            rng = bound; prob[pi] = ttt + ((2048 - ttt) >> 5)
            bit = 0
        else:
            rng -= bound; code -= bound; prob[pi] = ttt - (ttt >> 5)
            bit = 1
        if rng < (1 << 24):
            rng = (rng << 8) & 0xFFFFFFFF
            code = ((code << 8) | (rc[rcpos] if rcpos < len(rc) else 0)) & 0xFFFFFFFF
            rcpos += 1
        if bit == 0:
            prev = b
        else:
            if b == 0xE8:
                src = int.from_bytes(call[pos[0]:pos[0] + 4], "big"); pos[0] += 4
            else:
                src = int.from_bytes(jump[pos[1]:pos[1] + 4], "big"); pos[1] += 4
            dest = (src - (len(out) + 4)) & 0xFFFFFFFF
            out += dest.to_bytes(4, "little")
            prev = dest >> 24
    return bytes(out[:outsize])


def decode_folder(f, packed_list):
    """Generic folder decoder: coders may have several inputs (BCJ2). `packed_list` = packed streams in order."""
    coders, bps, pk = f["coders"], f["bps"], f["pk"]
    in_base, out_base, i = [], [], 0
    o = 0
    for c in coders:
        in_base.append(i); out_base.append(o); i += c[1]; o += c[2]
    bound_in = {b[0]: b[1] for b in bps}
    cache = {}

    def get_out(oi):
        if oi in cache:
            return cache[oi]
        ci = max(k for k in range(len(coders)) if out_base[k] <= oi)
        ins = []
        for k in range(coders[ci][1]):
            idx = in_base[ci] + k
            if idx in bound_in:
                ins.append(get_out(bound_in[idx]))
            else:
                ins.append(packed_list[pk.index(idx)])
        cid = coders[ci][0]
        size = f["sizes"][oi]
        if cid == b"\x03\x03\x01\x1b":
            res = bcj2_decode(ins[0], ins[1], ins[2], ins[3], size)
        else:
            res = run_coder(cid, coders[ci][3], ins[0], size)
        cache[oi] = res
        return res

    bound_out = {b[1] for b in bps}
    main = [k for k in range(f["tout"]) if k not in bound_out][0]
    return get_out(main)


def parse_header(h):
    r = R(h)
    assert r.u8() == 1
    streams = None; files = []
    while True:
        t = r.u8()
        if t == 0: break
        if t == 2:
            while r.u8() != 0: r.take(r.num())
        elif t == 3:
            read_streams_info(r)
        elif t == 4:
            streams = read_streams_info(r)
        elif t == 5:
            n = r.num(); empty = [False] * n; emptyfile = None; names = []
            while True:
                pt = r.u8()
                if pt == 0: break
                sz = r.num(); end = r.o + sz
                if pt == 0xE: empty = r.bits(n)
                elif pt == 0xF:
                    ne = sum(empty); emptyfile = r.bits(ne)
                elif pt == 0x11:
                    assert r.u8() == 0
                    raw = r.b[r.o:end]
                    names = raw.decode("utf-16-le").split("\0")[:n]
                r.o = end
            ei = 0
            for i in range(n):
                is_empty = empty[i]
                is_dir = False
                if is_empty:
                    is_dir = not (emptyfile[ei] if emptyfile else False); ei += 1
                files.append(dict(name=names[i], empty=is_empty, dir=is_dir))
    return streams, files


def extract(path, outdir):
    data = open(path, "rb").read()
    assert data[:6] == b"7z\xbc\xaf\x27\x1c"
    off, size, crc = struct.unpack("<QQI", data[12:32])
    hdr = data[32 + off:32 + off + size]
    while hdr[0] == 0x17:
        r = R(hdr, 1)
        pack, folders, nums, sizes = read_streams_info(r)
        pos, psizes = pack
        packed = data[32 + pos:32 + pos + psizes[0]]
        hdr = decode_folder(folders[0], [packed])
    streams, files = parse_header(hdr)
    pack, folders, nums, sizes = streams
    ppos, psizes = pack
    pk_off = 32 + ppos; si = 0; fi = 0
    outs = []
    pidx = 0
    for fo, n in zip(folders, nums):
        packed = []
        for _ in fo["pk"]:
            packed.append(data[pk_off:pk_off + psizes[pidx]]); pk_off += psizes[pidx]; pidx += 1
        raw = decode_folder(fo, packed)
        o = 0
        for _ in range(n):
            outs.append(raw[o:o + sizes[si]]); o += sizes[si]; si += 1
    k = 0; count = 0
    for f in files:
        p = os.path.join(outdir, f["name"].replace("\\", "/"))
        if f["dir"]:
            os.makedirs(p, exist_ok=True); continue
        os.makedirs(os.path.dirname(p) or outdir, exist_ok=True)
        if f["empty"]:
            open(p, "wb").close()
        else:
            open(p, "wb").write(outs[k]); k += 1
        count += 1
    return count


if __name__ == "__main__":
    print(extract(sys.argv[1], sys.argv[2]), "files")
