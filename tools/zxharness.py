"""Headless driver for ZX-M8XXX (Opus Discovery experiments).

Starts serve.py + headless Edge with a DevTools port, talks CDP over websockets.

    from zxharness import ZX
    with ZX(rom='opus.rom') as zx:
        zx.insert('disk.opd')
        zx.type('CAT 1\n'); zx.frames(100)
        zx.screenshot('cat.png')
"""
import asyncio, base64, json, os, socket, subprocess, sys, tempfile, time, urllib.request, shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
EMU = os.environ.get('ZXM8XXX', r'D:\Emulators\ZX\ZX-M8XXX')          # the emulator's folder (index.html, roms/)
EDGE = os.environ.get('EDGE', r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')   # Chromium browser
HTTP_PORT = 8765
CDP_PORT = 9333

import websockets


def _port_open(port):
    s = socket.socket()
    s.settimeout(0.3)
    try:
        s.connect(('127.0.0.1', port)); return True
    except OSError:
        return False
    finally:
        s.close()


class ZX:
    def __init__(self, rom='opus.rom', machine='48k', verbose=False, opus_ram=True):
        self.rom, self.machine, self.verbose, self.opus_ram = rom, machine, verbose, opus_ram
        self.server = self.edge = None
        self.loop = asyncio.new_event_loop()
        self._id = 0

    # ---------- lifecycle
    def __enter__(self):
        for attempt in range(5):
            try:
                self.open(); return self
            except Exception as e:
                if attempt == 4: raise
                print('harness: retry after', e, file=sys.stderr)
                self.close(); self.loop = asyncio.new_event_loop(); self._id = 0
        return self

    def __exit__(self, *a):
        self.close()

    def open(self):
        if not _port_open(HTTP_PORT):
            self.server = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'zxserve.py'), EMU, str(HTTP_PORT)],
                                           creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0),
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(50):
                if _port_open(HTTP_PORT): break
                time.sleep(0.1)
        self.profile = tempfile.mkdtemp(prefix='zxedge_')
        global CDP_PORT
        so = socket.socket(); so.bind(('127.0.0.1', 0)); CDP_PORT = so.getsockname()[1]; so.close()
        self.edge = subprocess.Popen([EDGE, '--headless=new', '--disable-gpu', '--no-first-run',
                                      '--mute-audio', '--autoplay-policy=no-user-gesture-required',
                                      f'--remote-debugging-port={CDP_PORT}', f'--user-data-dir={self.profile}',
                                      f'http://localhost:{HTTP_PORT}/index.html'],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ws = None
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f'http://127.0.0.1:{CDP_PORT}/json'))
                pages = [t for t in tabs if t.get('type') == 'page' and 'localhost' in t.get('url', '')]
                if pages:
                    ws = pages[0]['webSocketDebuggerUrl']; break
            except Exception:
                pass
            time.sleep(0.1)
        if not ws:
            raise RuntimeError('no CDP page')
        self.ws = self.loop.run_until_complete(websockets.connect(ws, max_size=1 << 28))
        # wait for zxDebug; a page whose module graph stalled gets one reload
        for attempt in range(2):
            for _ in range(300):
                try:
                    if self.js('typeof window.zxDebug !== "undefined" && typeof window.zxDebug.ready === "function"'):
                        break
                except Exception:
                    pass
                time.sleep(0.05)
            else:
                try:
                    diag = self.js('JSON.stringify({u: location.href, rs: document.readyState, '
                                   't: (document.body && document.body.innerText || "").slice(0, 120)})')
                except Exception as e:
                    diag = repr(e)
                print('harness: zxDebug missing:', diag, file=sys.stderr)
                if attempt == 0:
                    try:
                        self.loop.run_until_complete(self._call('Page.reload', {'ignoreCache': True}))
                    except Exception:
                        pass
                    continue
                raise RuntimeError('zxDebug did not appear')
            break
        self.js(f'''(async () => {{
            const zx = window.zxDebug;
            await zx.ready({{machine: '{self.machine}'}});
            await zx.start();
            zx.pause();
            return true; }})()''')
        self.set_rom(self.rom)
        if not self.opus_ram:
            self.remove_opus_ram()
        return self

    def remove_opus_ram(self):
        """Emulate an Opus without the optional 2K RAM: #2000-#27FF reads #FF and
        ignores writes. Resets the machine so that the ROM's init sees it too."""
        self.js('''(() => { const m = window.zxDebug.spectrum.memory;
            m.opusRam = new Proxy(new Uint8Array(2048), {
                get(t, k) { if (typeof k === 'string' && /^\\d+$/.test(k)) return 0xFF;
                            const v = Reflect.get(t, k); return typeof v === 'function' ? v.bind(t) : v; },
                set(t, k, v) { return true; } });
            window.zxDebug.spectrum.reset(); return true; })()''')

    def close(self):
        try:
            self.loop.run_until_complete(self.ws.close())
        except Exception:
            pass
        if self.edge:
            self.edge.kill()
            try: self.edge.wait(5)
            except Exception: pass
            # kill children that hold the profile
            subprocess.run(['powershell', '-NoProfile', '-Command',
                            "Get-CimInstance Win32_Process -Filter \"name='msedge.exe'\" | "
                            f"Where-Object {{ $_.CommandLine -like '*{os.path.basename(self.profile)}*' }} | "
                            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            shutil.rmtree(self.profile, ignore_errors=True)
        # the threaded server is left running for the next run

    # ---------- CDP
    async def _call(self, method, params):
        self._id += 1
        mid = self._id
        await self.ws.send(json.dumps({'id': mid, 'method': method, 'params': params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get('id') == mid:
                return msg

    def js(self, expr):
        r = self.loop.run_until_complete(self._call('Runtime.evaluate', {
            'expression': expr, 'awaitPromise': True, 'returnByValue': True}))
        res = r.get('result', {})
        if 'exceptionDetails' in res:
            ex = res['exceptionDetails']
            raise RuntimeError(ex.get('exception', {}).get('description') or ex.get('text'))
        if 'error' in r:
            raise RuntimeError(r['error'])
        return res.get('result', {}).get('value')

    # ---------- machine helpers
    def set_rom(self, rom):
        """Load an Opus ROM from the emulator's roms/ dir and enable the interface."""
        self.js(f'''(async () => {{
            const s = window.zxDebug.spectrum;
            const r = await fetch('roms/{rom}', {{cache:'no-store'}});
            const b = new Uint8Array(await r.arrayBuffer());
            if (b.length < 8192) throw new Error('bad rom {rom}');
            s.memory.loadOpusRom(b);
            s.plusDEnabled = false;
            s.opusEnabled = true;
            s.updateBetaDiskPagingFlag();
            s.reset();
            return s._opusPagingEnabled; }})()''')

    def reset(self):
        self.js('window.zxDebug.spectrum.reset(), true')

    def insert(self, path_or_bytes, drive=0, name='disk.opd', geom=None):
        """Insert a raw .opd (or .dsk) image. Geometry (tracks/side, sides, spt, bps)
        is taken from the image's anchor sector and forced onto the emulated
        controller, so 80x2x10x512 "DD" disks work although M8XXX only knows
        the two 18x256 sizes. (M8XXX keeps one geometry per controller.)"""
        from opdtool import OPD
        o = OPD(path_or_bytes, geom)
        b64 = base64.b64encode(bytes(o.d)).decode()
        return self.js(f'''(() => {{
            const b = Uint8Array.from(atob("{b64}"), c => c.charCodeAt(0));
            const s = window.zxDebug.spectrum, r = s.loadOPDImage(b, "{name}", {drive});
            const op = s.opus;
            op.tracks = {o.tps}; op.sides = {o.sides};
            op.sectorsPerTrack = {o.spt}; op.bytesPerSector = {o.bps}; op.firstSector = 0;
            return !!r.diskInserted; }})()''')

    def disk(self, drive=0):
        """Current image bytes of drive (after writes)."""
        b64 = self.js(f'''(() => {{
            const d = window.zxDebug.spectrum.opus.drives[{drive}].diskData;
            let s = ''; for (let i = 0; i < d.length; i += 8192)
                s += String.fromCharCode.apply(null, d.subarray(i, i + 8192));
            return btoa(s); }})()''')
        return base64.b64decode(b64)

    def frames(self, n):
        self.js(f'window.zxDebug.runFrames({n}), true')

    def type(self, text, hold=3, gap=3):
        self.js(f'window.zxDebug.typeText({json.dumps(text)}, {{hold:{hold}, gap:{gap}}}), true')

    def key(self, *keys, frames=4):
        for k in keys: self.js(f'window.zxDebug.keyDown({json.dumps(k)})')
        self.frames(frames)
        for k in keys: self.js(f'window.zxDebug.keyUp({json.dumps(k)})')

    def peek(self, addr, n=1):
        r = self.js(f'Array.from(window.zxDebug.peekBlock({addr}, {n}))')
        return bytes(r)

    def poke(self, addr, data):
        self.js(f'window.zxDebug.pokeBlock({addr}, {json.dumps(list(data))}), true')

    def regs(self):
        return self.js('window.zxDebug.captureRegisters()')

    def screen_text(self):
        """Decode the screen to text by matching the 48K ROM font (8x8 grid)."""
        if not hasattr(self, '_font'):
            self._font = {}
            f = self.peek(0x3D00, 768)
            for c in range(96):
                self._font[bytes(f[c*8:c*8+8])] = chr(32 + c)
        scr = self.peek(0x4000, 6144)
        lines = []
        for row in range(24):
            t = ''
            for col in range(32):
                g = bytes(scr[((row & 0x18) << 8) | (r << 8) | ((row & 7) << 5) | col] for r in range(8))
                inv = bytes(255 - x for x in g)
                t += self._font.get(g) or self._font.get(inv) or '?'
            lines.append(t.rstrip())
        return chr(10).join(lines).rstrip(chr(10))

    def basic(self, line, hold=3, gap=3):
        """Type a BASIC line/command in the 48K editor (keyword entry) and press ENTER."""
        from zxkeys import chords
        for ch in chords(line):
            for k in ch: self.js(f'window.zxDebug.keyDown("{k}")')
            self.frames(hold)
            for k in ch: self.js(f'window.zxDebug.keyUp("{k}")')
            self.frames(gap)

    def run_until(self, cond_js, max_frames=3000, step=10):
        """Pump frames until a JS condition holds; returns frames used or None."""
        n = 0
        while n < max_frames:
            if self.js(cond_js): return n
            self.frames(step); n += step
        return None

    def screenshot(self, path):
        b64 = self.js('''(() => { const c = document.querySelector('canvas');
            return c.toDataURL('image/png').split(',')[1]; })()''')
        open(path, 'wb').write(base64.b64decode(b64))

    def opus_active(self):
        return self.js('window.zxDebug.spectrum.memory.opusActive')


if __name__ == '__main__':
    with ZX() as zx:
        print(zx.js('window.zxDebug.version'), zx.js('window.zxDebug.spectrum._opusPagingEnabled'))
        zx.frames(150)
        zx.screenshot(os.path.join(os.path.dirname(__file__), '..', 'work', 'boot.png'))
