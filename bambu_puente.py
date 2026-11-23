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
import argparse, getpass, json, os, ssl, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE = {"connected": False, "state": "IDLE", "percent": 0, "remainMin": 0,
         "layer": 0, "totalLayers": 0, "file": "", "nozzle": 0, "bed": 0, "updated": 0}
LOCK = threading.Lock()

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
        print("Desconectado; reintentando...")

    c.on_connect, c.on_message, c.on_disconnect = on_connect, on_message, on_disconnect
    c.reconnect_delay_set(2, 30)
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
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--ip", default=os.environ.get("BAMBU_IP"))
    ap.add_argument("--serial", default=os.environ.get("BAMBU_SERIAL"))
    a = ap.parse_args()
    if a.demo:
        threading.Thread(target=run_demo, daemon=True).start()
        print("Modo demo: simulando una impresión.")
    else:
        ip = a.ip or input("IP de la impresora: ").strip()
        serial = a.serial or input("Número de serie: ").strip()
        code = os.environ.get("BAMBU_CODE") or getpass.getpass("Código de acceso (no se ve al escribir): ").strip()
        threading.Thread(target=run_mqtt, args=(ip, serial, code), daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    print("Listo. La app puede leer http://localhost:%d/status  (Ctrl+C para cerrar)" % a.port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
