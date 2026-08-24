import ctypes, fcntl, os, sys
from ctypes import c_uint32, c_uint8
DEV='/dev/v4l/by-id/usb-Insta360_Insta360_Link-video-index0'
class fmtdesc(ctypes.Structure):
    _fields_=[('index',c_uint32),('type',c_uint32),('flags',c_uint32),('description',c_uint8*32),
              ('pixelformat',c_uint32),('mbus_code',c_uint32),('reserved',c_uint32*3)]
class frmsize(ctypes.Structure):
    class _d(ctypes.Union):
        class _disc(ctypes.Structure): _fields_=[('width',c_uint32),('height',c_uint32)]
        _fields_=[('discrete',_disc),('pad',c_uint32*6)]
    _fields_=[('index',c_uint32),('pixel_format',c_uint32),('type',c_uint32),('u',_d),('reserved',c_uint32*2)]
class frmival(ctypes.Structure):
    class _d(ctypes.Union):
        class _frac(ctypes.Structure): _fields_=[('numerator',c_uint32),('denominator',c_uint32)]
        _fields_=[('discrete',_frac),('pad',c_uint32*6)]
    _fields_=[('index',c_uint32),('pixel_format',c_uint32),('width',c_uint32),('height',c_uint32),
              ('type',c_uint32),('u',_d),('reserved',c_uint32*2)]
def IOWR(t,nr,sz): return (3<<30)|(ord(t)<<8)|nr|(sz<<16)
E_FMT,E_SZ,E_IV=IOWR('V',2,ctypes.sizeof(fmtdesc)),IOWR('V',74,ctypes.sizeof(frmsize)),IOWR('V',75,ctypes.sizeof(frmival))
def dump():
    out=[]
    fd=os.open(DEV,os.O_RDWR)
    i=0
    while True:
        f=fmtdesc(); f.index=i; f.type=1
        try: fcntl.ioctl(fd,E_FMT,f)
        except OSError: break
        fourcc=f.pixelformat.to_bytes(4,'little').decode()
        j=0
        while True:
            sz=frmsize(); sz.index=j; sz.pixel_format=f.pixelformat
            try: fcntl.ioctl(fd,E_SZ,sz)
            except OSError: break
            w,h=sz.u.discrete.width,sz.u.discrete.height
            rates=[];k=0
            while True:
                iv=frmival(); iv.index=k; iv.pixel_format=f.pixelformat; iv.width=w; iv.height=h
                try: fcntl.ioctl(fd,E_IV,iv)
                except OSError: break
                d=iv.u.discrete
                if d.numerator: rates.append(round(d.denominator/d.numerator))
                k+=1
            out.append(f'{fourcc} {w}x{h} @ {",".join(map(str,rates))}')
            j+=1
        i+=1
    os.close(fd)
    return out
if __name__=='__main__':
    for line in dump(): print(' ', line)
