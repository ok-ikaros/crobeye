#!/usr/bin/env python3
"""Minimal JVM class-file disassembler.

Reads a .class (optionally straight out of a jar entry, since macOS is
case-insensitive and the wakfu client has name collisions) and prints each
method's bytecode with resolved constant-pool references. Enough to trace the
read order of obfuscated binary parsers (readInt/readShort/readByte/...).
"""
import struct, sys, zipfile

# --- constant pool ----------------------------------------------------------
def parse_cp(data):
    off = 8
    count = struct.unpack_from('>H', data, off)[0]; off += 2
    cp = [None] * count
    i = 1
    while i < count:
        tag = data[off]; off += 1
        if tag == 1:
            ln = struct.unpack_from('>H', data, off)[0]; off += 2
            cp[i] = ('Utf8', data[off:off+ln].decode('utf-8', 'replace')); off += ln
        elif tag == 3:
            cp[i] = ('Int', struct.unpack_from('>i', data, off)[0]); off += 4
        elif tag == 4:
            cp[i] = ('Float', struct.unpack_from('>f', data, off)[0]); off += 4
        elif tag == 5:
            cp[i] = ('Long', struct.unpack_from('>q', data, off)[0]); off += 8
        elif tag == 6:
            cp[i] = ('Double', struct.unpack_from('>d', data, off)[0]); off += 8
        elif tag == 7:
            cp[i] = ('Class', struct.unpack_from('>H', data, off)[0]); off += 2
        elif tag == 8:
            cp[i] = ('String', struct.unpack_from('>H', data, off)[0]); off += 2
        elif tag in (9, 10, 11):
            kind = {9:'Field',10:'Method',11:'IfaceMethod'}[tag]
            cp[i] = (kind, struct.unpack_from('>HH', data, off)); off += 4
        elif tag == 12:
            cp[i] = ('NameType', struct.unpack_from('>HH', data, off)); off += 4
        elif tag == 15:
            cp[i] = ('MethodHandle', data[off], struct.unpack_from('>H', data, off+1)[0]); off += 3
        elif tag == 16:
            cp[i] = ('MethodType', struct.unpack_from('>H', data, off)[0]); off += 2
        elif tag in (17, 18):
            cp[i] = ('Dynamic', struct.unpack_from('>HH', data, off)); off += 4
        elif tag in (19, 20):
            cp[i] = ('Module', struct.unpack_from('>H', data, off)[0]); off += 2
        else:
            raise ValueError(f'bad tag {tag} at {off}')
        if tag in (5, 6):
            i += 2
        else:
            i += 1
    return cp, off

def utf(cp, idx):
    e = cp[idx]
    return e[1] if e and e[0] == 'Utf8' else f'#{idx}'

def cp_str(cp, idx):
    e = cp[idx]
    if e is None: return f'#{idx}'
    t = e[0]
    if t == 'Utf8': return repr(e[1])
    if t == 'String': return 'str ' + repr(utf(cp, e[1]))
    if t == 'Class': return 'class ' + utf(cp, e[1])
    if t in ('Int','Float','Long','Double'): return f'{t} {e[1]}'
    if t in ('Field','Method','IfaceMethod'):
        ci, nt = e[1]
        cls = utf(cp, cp[ci][1])
        nm, desc = cp[nt][1]
        return f'{cls}.{utf(cp,nm)}:{utf(cp,desc)}'
    if t == 'NameType':
        return f'{utf(cp,e[1][0])}:{utf(cp,e[1][1])}'
    if t == 'Dynamic':
        nt = cp[e[1][1]]
        return f'dyn {utf(cp, nt[1][0])}:{utf(cp, nt[1][1])}'
    return t

# --- opcodes ----------------------------------------------------------------
# name, operand-bytes (negative codes = special)
OPS = {
0:'nop',1:'aconst_null',2:'iconst_m1',3:'iconst_0',4:'iconst_1',5:'iconst_2',
6:'iconst_3',7:'iconst_4',8:'iconst_5',9:'lconst_0',10:'lconst_1',11:'fconst_0',
12:'fconst_1',13:'fconst_2',14:'dconst_0',15:'dconst_1',16:'bipush',17:'sipush',
18:'ldc',19:'ldc_w',20:'ldc2_w',21:'iload',22:'lload',23:'fload',24:'dload',
25:'aload',26:'iload_0',27:'iload_1',28:'iload_2',29:'iload_3',30:'lload_0',
31:'lload_1',32:'lload_2',33:'lload_3',34:'fload_0',35:'fload_1',36:'fload_2',
37:'fload_3',38:'dload_0',39:'dload_1',40:'dload_2',41:'dload_3',42:'aload_0',
43:'aload_1',44:'aload_2',45:'aload_3',46:'iaload',47:'laload',48:'faload',
49:'daload',50:'aaload',51:'baload',52:'caload',53:'saload',54:'istore',
55:'lstore',56:'fstore',57:'dstore',58:'astore',59:'istore_0',60:'istore_1',
61:'istore_2',62:'istore_3',63:'lstore_0',64:'lstore_1',65:'lstore_2',
66:'lstore_3',67:'fstore_0',68:'fstore_1',69:'fstore_2',70:'fstore_3',
71:'dstore_0',72:'dstore_1',73:'dstore_2',74:'dstore_3',75:'astore_0',
76:'astore_1',77:'astore_2',78:'astore_3',79:'iastore',80:'lastore',
81:'fastore',82:'dastore',83:'aastore',84:'bastore',85:'castore',86:'sastore',
87:'pop',88:'pop2',89:'dup',90:'dup_x1',91:'dup_x2',92:'dup2',93:'dup2_x1',
94:'dup2_x2',95:'swap',96:'iadd',97:'ladd',98:'fadd',99:'dadd',100:'isub',
101:'lsub',102:'fsub',103:'dsub',104:'imul',105:'lmul',106:'fmul',107:'dmul',
108:'idiv',109:'ldiv',110:'fdiv',111:'ddiv',112:'irem',113:'lrem',114:'frem',
115:'drem',116:'ineg',117:'lneg',118:'fneg',119:'dneg',120:'ishl',121:'lshl',
122:'ishr',123:'lshr',124:'iushr',125:'lushr',126:'iand',127:'land',128:'ior',
129:'lor',130:'ixor',131:'lxor',132:'iinc',133:'i2l',134:'i2f',135:'i2d',
136:'l2i',137:'l2f',138:'l2d',139:'f2i',140:'f2l',141:'f2d',142:'d2i',143:'d2l',
144:'d2f',145:'i2b',146:'i2c',147:'i2s',148:'lcmp',149:'fcmpl',150:'fcmpg',
151:'dcmpl',152:'dcmpg',153:'ifeq',154:'ifne',155:'iflt',156:'ifge',157:'ifgt',
158:'ifle',159:'if_icmpeq',160:'if_icmpne',161:'if_icmplt',162:'if_icmpge',
163:'if_icmpgt',164:'if_icmple',165:'if_acmpeq',166:'if_acmpne',167:'goto',
168:'jsr',169:'ret',170:'tableswitch',171:'lookupswitch',172:'ireturn',
173:'lreturn',174:'freturn',175:'dreturn',176:'areturn',177:'return',
178:'getstatic',179:'putstatic',180:'getfield',181:'putfield',
182:'invokevirtual',183:'invokespecial',184:'invokestatic',
185:'invokeinterface',186:'invokedynamic',187:'new',188:'newarray',
189:'anewarray',190:'arraylength',191:'athrow',192:'checkcast',
193:'instanceof',194:'monitorenter',195:'monitorexit',196:'wide',
197:'multianewarray',198:'ifnull',199:'ifnonnull',200:'goto_w',201:'jsr_w',
}
CP_OPS = {18,19,20,178,179,180,181,182,183,184,185,186,187,189,192,193,197}

def disasm(code, cp):
    out = []
    i = 0; n = len(code)
    while i < n:
        pc = i
        op = code[i]; i += 1
        name = OPS.get(op, f'op{op}')
        arg = ''
        if op in (16,):  # bipush
            arg = str(struct.unpack_from('>b', code, i)[0]); i += 1
        elif op in (17,):  # sipush
            arg = str(struct.unpack_from('>h', code, i)[0]); i += 2
        elif op == 18:  # ldc
            arg = cp_str(cp, code[i]); i += 1
        elif op in (19,20):  # ldc_w/ldc2_w
            arg = cp_str(cp, struct.unpack_from('>H', code, i)[0]); i += 2
        elif op in (21,22,23,24,25,54,55,56,57,58,169):  # local var index
            arg = str(code[i]); i += 1
        elif op == 132:  # iinc
            arg = f'{code[i]} by {struct.unpack_from(">b",code,i+1)[0]}'; i += 2
        elif 153 <= op <= 168 or op in (198,199):  # branches (2-byte)
            arg = f'-> {pc + struct.unpack_from(">h", code, i)[0]}'; i += 2
        elif op in (200,201):  # goto_w/jsr_w
            arg = f'-> {pc + struct.unpack_from(">i", code, i)[0]}'; i += 4
        elif op in CP_OPS:
            idx = struct.unpack_from('>H', code, i)[0]; i += 2
            arg = cp_str(cp, idx)
            if op == 185: i += 2  # invokeinterface count+0
            if op == 186: i += 2  # invokedynamic 0 0
            if op == 197: i += 1  # multianewarray dims
        elif op == 188:  # newarray
            arg = {4:'bool',5:'char',6:'float',7:'double',8:'byte',9:'short',10:'int',11:'long'}.get(code[i],'?'); i += 1
        elif op in (170,171):  # switches
            pad = (4 - (i % 4)) % 4; i += pad
            if op == 170:
                default, lo, hi = struct.unpack_from('>iii', code, i); i += 12
                i += 4 * (hi - lo + 1)
                arg = f'low={lo} high={hi}'
            else:
                default, npairs = struct.unpack_from('>ii', code, i); i += 8
                i += 8 * npairs
                arg = f'npairs={npairs}'
        elif op == 196:  # wide
            wop = code[i]; i += 1
            idx = struct.unpack_from('>H', code, i)[0]; i += 2
            if wop == 132: i += 2
            arg = f'{OPS.get(wop)} {idx}'
        out.append(f'    {pc:5d}: {name:16s} {arg}')
    return out

def attrs(data, off, cp, count):
    res = {}
    for _ in range(count):
        nidx, ln = struct.unpack_from('>HI', data, off); off += 6
        res.setdefault(utf(cp, nidx), data[off:off+ln])
        # keep first; store all in list too
        res.setdefault('__list__', []).append((utf(cp, nidx), data[off:off+ln]))
        off += ln
    return res, off

def dump(data, want_methods=None):
    cp, off = parse_cp(data)
    aflags, this_i, super_i = struct.unpack_from('>HHH', data, off); off += 6
    print(f'class {utf(cp, cp[this_i][1])} extends {utf(cp, cp[super_i][1])}')
    ifc = struct.unpack_from('>H', data, off)[0]; off += 2 + 2*ifc
    # fields
    fcount = struct.unpack_from('>H', data, off)[0]; off += 2
    print(f'-- {fcount} fields --')
    for _ in range(fcount):
        fl, nidx, didx, acount = struct.unpack_from('>HHHH', data, off); off += 8
        print(f'  field {utf(cp,nidx)} : {utf(cp,didx)}')
        for _ in range(acount):
            an, al = struct.unpack_from('>HI', data, off); off += 6 + al
    # methods
    mcount = struct.unpack_from('>H', data, off)[0]; off += 2
    print(f'-- {mcount} methods --')
    for _ in range(mcount):
        ml, nidx, didx, acount = struct.unpack_from('>HHHH', data, off); off += 8
        mname = utf(cp, nidx); mdesc = utf(cp, didx)
        mattrs = []
        code_attr = None
        for _ in range(acount):
            an, al = struct.unpack_from('>HI', data, off); off += 6
            aname = utf(cp, an)
            body = data[off:off+al]; off += al
            if aname == 'Code': code_attr = body
        if want_methods and mname not in want_methods:
            continue
        print(f'\n  method {mname} {mdesc}')
        if code_attr:
            max_stack, max_locals, clen = struct.unpack_from('>HHI', code_attr, 0)
            code = code_attr[8:8+clen]
            for line in disasm(code, cp):
                print(line)

if __name__ == '__main__':
    src = sys.argv[1]
    want = set(sys.argv[3:]) if len(sys.argv) > 3 else None
    if ':' in src and src.endswith('.jar') is False and '.jar:' in src:
        jarpath, entry = src.split('.jar:'); jarpath += '.jar'
        data = zipfile.ZipFile(jarpath).read(entry)
    elif len(sys.argv) > 2:
        # usage: javap.py JAR ENTRY [methods...]
        data = zipfile.ZipFile(sys.argv[1]).read(sys.argv[2])
        want = set(sys.argv[3:]) if len(sys.argv) > 3 else None
    else:
        data = open(src, 'rb').read()
    dump(data, want)
