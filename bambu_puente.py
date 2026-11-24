#!/usr/bin/env python3
"""
Puente Bambu Lab -> Taller 3D
Lee el avance de tu impresora Bambu Lab por la red local (MQTT) y lo ofrece
a la app en http://localhost:8765/status

Uso:
  pip install paho-mqtt
  python3 bambu_puente.py                 (te pregunta IP, serial y código)
  python3 bambu_puente.py --demo          (simula una impresión para probar)

Datos que necesitas (en la pantalla de la impresora: Ajustes > WLAN / Red):
  - Dirección IP de la impresora
  - Número de serie (en la etiqueta de la impresora o en Bambu Studio)
  - Código de acceso (8 caracteres, en la pantalla de la impresora)
Activa también el "Modo LAN" si tu modelo lo pide. El código se usa solo en
tu computadora y no se guarda en ningún archivo.
"""
import argparse, getpass, json, os, ssl, sys, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE = {"connected": False, "state": "IDLE", "percent": 0, "remainMin": 0,
         "layer": 0, "totalLayers": 0, "file": "", "nozzle": 0, "bed": 0, "updated": 0}
LOCK = threading.Lock()
CFG = os.path.join(os.path.expanduser("~"), ".bambu_puente.json")

def load_cfg():
    try:
        with open(CFG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_cfg(d):
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(d, f)
    try:
        os.chmod(CFG, 0o600)
    except Exception:
        pass

def merge(p):
    m = {"gcode_state": "state", "mc_percent": "percent", "mc_remaining_time": "remainMin",
         "layer_num": "layer", "total_layer_num": "totalLayers",
         "nozzle_temper": "nozzle", "bed_temper": "bed"}
    with LOCK:
        for k, v in m.items():
            if k in p and p[k] is not None:
                STATE[v] = v == "state" and str(p[k]).upper() or p[k]
        name = p.get("subtask_name") or p.get("gcode_file")
        if name:
            STATE["file"] = name
        STATE["connected"] = True
        STATE["updated"] = int(time.time())

def run_mqtt(ip, serial, code):
    import paho.mqtt.client as mqtt
    try:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        c = mqtt.Client()
    c.username_pw_set("bblp", code)
    c.tls_set(cert_reqs=ssl.CERT_NONE)
    c.tls_insecure_set(True)
    topic = "device/%s/report" % serial

    def on_connect(client, *a):
        rc = a[2] if len(a) > 2 else 0
        try:
            rc = rc.value if hasattr(rc, "value") else int(rc)
        except Exception:
            pass
        if rc != 0:
            print("La impresora rechazó la conexión (código %s)." % rc)
            if rc in (4, 5, 134, 135):
                print("  -> El código de acceso parece incorrecto. Cierra con Ctrl+C y vuelve a abrir.")
            return
        client.subscribe(topic)
        client.publish("device/%s/request" % serial,
                       json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}}))
        print("Conectado a la impresora.")

    def on_message(client, userdata, msg):
        try:
            p = json.loads(msg.payload).get("print")
            if p:
                merge(p)
        except Exception:
            pass

    def on_disconnect(*a):
        with LOCK:
            STATE["connected"] = False
        print("Sin conexión con la impresora; reintentando...")

    c.on_connect, c.on_message, c.on_disconnect = on_connect, on_message, on_disconnect
    c.reconnect_delay_set(2, 30)
    import socket
    try:
        socket.create_connection((ip, 8883), timeout=5).close()
        print("La impresora responde en %s. Conectando..." % ip)
    except Exception as e:
        print("No llego a la impresora en %s:8883 (%s)." % (ip, e))
        print("  -> Revisa que esté encendida, en la misma red wifi que esta PC y con el Modo LAN activado.")
    c.connect_async(ip, 8883, 60)
    c.loop_start()
    # pide el estado completo cada 30 s por si faltan campos
    while True:
        time.sleep(30)
        try:
            c.publish("device/%s/request" % serial,
                      json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}}))
        except Exception:
            pass

def gh(method, path, token, body=None):
    req = urllib.request.Request("https://api.github.com" + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                 "User-Agent": "taller3d-puente", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read() or b"{}")

def run_gist(token):
    """Publica el estado en un Gist secreto para verlo desde cualquier red."""
    cfg = load_cfg()
    gid = cfg.get("gist_id")
    last, last_t = None, 0
    while True:
        with LOCK:
            d = dict(STATE)
        d["updated"] = int(time.time())
        sig = (d["connected"], d["state"], int(d["percent"] or 0), int(d["remainMin"] or 0), d["layer"])
        if sig != last or time.time() - last_t > 120:
            files = {"estado.json": {"content": json.dumps(d)}}
            try:
                if not gid:
                    g = gh("POST", "/gists", token, {"description": "Taller 3D - estado de la impresora",
                                                     "public": False, "files": files})
                    gid = g["id"]
                    cfg = load_cfg(); cfg["gist_id"] = gid; save_cfg(cfg)
                    print("Nube lista. ID para la app (Ajustes > Impresora Bambu Lab): %s" % gid)
                else:
                    gh("PATCH", "/gists/" + gid, token, {"files": files})
                last, last_t = sig, time.time()
            except Exception as e:
                print("No pude publicar en la nube (%s). Reintento en un momento." % e)
        time.sleep(20)

def run_demo():
    total = 90  # minutos simulados
    t0 = time.time()
    while True:
        el = (time.time() - t0) / 60 * 30  # 30x más rápido
        pct = min(100, int(el / total * 100))
        merge({"gcode_state": "FINISH" if pct >= 100 else "RUNNING", "mc_percent": pct,
               "mc_remaining_time": max(0, int(total - el)), "layer_num": int(pct * 2.4),
               "total_layer_num": 240, "subtask_name": "demo.gcode.3mf",
               "nozzle_temper": 220, "bed_temper": 60})
        time.sleep(2)

class H(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()
    def do_GET(self):
        with LOCK:
            d = dict(STATE)
        if d["updated"] and time.time() - d["updated"] > 90:
            d["connected"] = False
        body = json.dumps(d).encode()
        self.send_response(200); self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def log_message(self, *a):
        pass

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--olvidar", action="store_true", help="borra los datos guardados")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--ip", default=os.environ.get("BAMBU_IP"))
    ap.add_argument("--serial", default=os.environ.get("BAMBU_SERIAL"))
    a = ap.parse_args()
    if a.olvidar:
        try:
            os.remove(CFG)
            print("Datos borrados.")
        except OSError:
            print("No había datos guardados.")
        return
    if a.demo:
        threading.Thread(target=run_demo, daemon=True).start()
        print("Modo demo: simulando una impresión.")
    else:
        cfg = load_cfg()
        ip = a.ip or cfg.get("ip")
        serial = a.serial or cfg.get("serial")
        code = os.environ.get("BAMBU_CODE") or cfg.get("code")
        if not (ip and serial and code):
            if not sys.stdin or not sys.stdin.isatty():
                return  # arranque automático sin datos guardados: no hay a quién preguntar
            ip = ip or input("IP de la impresora: ").strip()
            serial = serial or input("Número de serie: ").strip()
            code = code or getpass.getpass("Código de acceso (no se ve al escribir): ").strip()
            if input("¿Guardar estos datos para no volver a escribirlos? (S/N): ").strip().lower() != "n":
                save_cfg({"ip": ip, "serial": serial, "code": code})
                print("Guardado en %s" % CFG)
        threading.Thread(target=run_mqtt, args=(ip, serial, code), daemon=True).start()
    tok = os.environ.get("BAMBU_GH_TOKEN") or load_cfg().get("gh_token")
    if not a.demo and not tok and sys.stdin and sys.stdin.isatty():
        print("Para ver el avance fuera de tu red necesitas un token de GitHub (ver LEEME).")
        tok = getpass.getpass("Token de GitHub (Enter para omitir): ").strip()
        if tok:
            c = load_cfg(); c["gh_token"] = tok; save_cfg(c)
    if tok:
        threading.Thread(target=run_gist, args=(tok,), daemon=True).start()
        print("Publicando el avance en la nube (Gist secreto).")
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    print("Listo. La app puede leer http://localhost:%d/status  (Ctrl+C para cerrar)" % a.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
