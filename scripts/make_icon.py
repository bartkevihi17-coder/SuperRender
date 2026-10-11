"""Gera iconografia simples e original sem dependencias externas."""
import struct
import zlib
from pathlib import Path


def inside_polygon(px, py, vertices):
    result = False
    previous = len(vertices)-1
    for idx, (ax, ay) in enumerate(vertices):
        bx, by = vertices[previous]
        if (ay > py) != (by > py):
            limit = (bx-ax)*(py-ay)/(by-ay)+ax
            if px < limit:
                result = not result
        previous = idx
    return result


def png_blob(size: int) -> bytes:
    lines = bytearray()
    bolt = [(37,8),(17,32),(30,32),(23,55),(49,25),(36,25),(44,8)]
    border = 3
    for yy in range(size):
        lines.append(0)
        for xx in range(size):
            x=(xx+0.5)*64/size
            y=(yy+0.5)*64/size
            outside = (x < 9 and y < 9 and (x-9)**2+(y-9)**2 > 9**2) or \
                      (x > 55 and y < 9 and (x-55)**2+(y-9)**2 > 9**2) or \
                      (x < 9 and y > 55 and (x-9)**2+(y-55)**2 > 9**2) or \
                      (x > 55 and y > 55 and (x-55)**2+(y-55)**2 > 9**2)
            if outside:
                rgba=(0,0,0,0)
            elif inside_polygon(x,y,bolt):
                rgba=(105,228,235,255)
            else:
                border_distance=min(x,y,64-x,64-y)
                if border_distance < border:
                    rgba=(96,170,217,255)
                else:
                    rgba=(20+int(y/15),31+int(y/14),52+int(x/13),255)
            lines.extend(rgba)
    def chunk(tag,payload):
        return struct.pack(">I",len(payload))+tag+payload+struct.pack(">I",zlib.crc32(tag+payload)&0xffffffff)
    header=struct.pack(">IIBBBBB",size,size,8,6,0,0,0)
    return b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",header)+chunk(b"IDAT",zlib.compress(bytes(lines),9))+chunk(b"IEND",b"")


root=Path(__file__).resolve().parents[1]/"assets"
root.mkdir(parents=True,exist_ok=True)
images=[(s,png_blob(s)) for s in (16,32,48,64,128,256)]
(root/"SuperRender.png").write_bytes(images[-1][1])
count=len(images)
header=struct.pack("<HHH",0,1,count)
offset=6+count*16
entries=[]
payload=b""
for size,blob in images:
    entry=struct.pack("<BBBBHHII",size if size<256 else 0,size if size<256 else 0,0,0,1,32,len(blob),offset)
    entries.append(entry)
    payload+=blob
    offset+=len(blob)
(root/"SuperRender.ico").write_bytes(header+b"".join(entries)+payload)
print("ICON_READY", [(f.name,f.stat().st_size) for f in root.iterdir()])
